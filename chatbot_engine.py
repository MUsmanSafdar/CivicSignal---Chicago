"""
Illinois Hazard Chatbot Engine
Built-in rule-based assistant — zero external API calls.

PowerBI portability notes:
  - detect_intent()   → DAX SWITCH(TRUE(), CONTAINSSTRING([query], kw), "intent", ...)
  - extract_county()  → DAX LOOKUPVALUE with CONTAINSSTRING
  - build_response()  → Power Query M template string concatenation
  - All reference data is in flat CSV tables importable directly into Power BI
"""

import re
import pandas as pd
from pathlib import Path
from datetime import datetime
import threading
import unicodedata
from typing import Callable

from i18n import normalize_lang, t

_ROOT = Path(__file__).resolve().parent
_DATA_DIR = _ROOT / "data" if (_ROOT / "data" / "cooling_centers.csv").exists() else _ROOT

# ── Reference table loader (cache keyed on file mtime + size, Phase 0.6) ──────

_CACHE: dict[str, tuple[tuple[int, int], pd.DataFrame]] = {}
_CACHE_LOCK = threading.Lock()


def _read_cached(name: str, reader: Callable[[Path], pd.DataFrame]) -> pd.DataFrame:
    """Load ``name`` from the data directory, re-reading whenever the file's mtime or size changes."""
    path = _DATA_DIR / name
    if not path.exists():
        return pd.DataFrame()
    stat = path.stat()
    sig = (stat.st_mtime_ns, stat.st_size)
    with _CACHE_LOCK:
        hit = _CACHE.get(name)
        if hit is not None and hit[0] == sig:
            return hit[1]
        frame = reader(path)
        _CACHE[name] = (sig, frame)
        return frame


def clear_cache() -> None:
    """Drop every cached table (used by tests and admin refresh)."""
    with _CACHE_LOCK:
        _CACHE.clear()


def _load_shelters() -> pd.DataFrame:
    return _read_cached("shelters.csv", pd.read_csv)


def _load_aid() -> pd.DataFrame:
    return _read_cached("aid_resources.csv", pd.read_csv)


def _load_cooling() -> pd.DataFrame:
    return _read_cached("cooling_centers.csv", lambda p: pd.read_csv(p, dtype={"zip": str}))


def _load_contacts() -> pd.DataFrame:
    return _read_cached("emergency_contacts.csv", pd.read_csv)


# ── Intent detection ──────────────────────────────────────────────────────────
# PowerBI: SWITCH(TRUE(), CONTAINSSTRING(query, kw1) || CONTAINSSTRING(query, kw2), "intent", ...)

_INTENTS: dict[str, list[str]] = {
    # Safety first: "emergency" is evaluated before every other intent (Phase 0.2).
    "emergency":  ["emergencia", "emergencias", "urgente", "peligro", "atrapado", "atrapada", "herido", "incendio", "inundacion", "terremoto", "ahora mismo", "socorro", "emergency", "urgent", "danger", "crisis", "trapped", "hurt", "injured",
                   "fire", "flooding", "tornado", "earthquake", "disaster", "sos", "right now", "immediately"],
    "greeting":   ["hola", "buenos dias", "buenas tardes", "buenas noches", "hi", "hello", "hey", "good morning", "good afternoon", "good evening", "howdy"],
    "thanks":     ["gracias", "thank you", "thanks", "thx", "appreciate"],
    "cooling":    ["enfriamiento", "calor", "aire acondicionado", "cooling", "cool down", "heat", "hot", "heatwave", "heat wave", "air condition",
                   "air-condition", "a/c", "too hot", "swelter"],
    "shelter":    ["refugio", "refugios", "albergue", "donde ir", "alojamiento", "shelter", "evacuation center", "safe place", "where to go", "refuge",
                   "emergency housing", "sleep", "stay tonight", "warming center"],
    "aid":        ["ayuda", "asistencia", "comida", "agua", "medicinas", "suministros", "aid", "assistance", "food", "water", "supplies", "medical", "medicine",
                   "financial", "fema", "relief", "support", "grant", "benefit", "donation",
                   "resource", "help me", "need help"],
    "contact":    ["contacto", "contactos", "telefono", "llamar", "numero", "contact", "phone number", "who to call", "ema", "hotline", "helpline",
                   "211", "reach", "email", "call"],
    "risk":       ["riesgo", "nivel de riesgo", "vulnerabilidad", "risk", "risk score", "risk level", "how bad", "how risky", "svi",
                   "vulnerability", "danger level", "hazard level", "score"],
    "mitigation": ["mitigacion", "presupuesto", "proyecto", "proyectos", "mitigation", "what is being done", "protection", "prevention",
                   "budget", "program", "project", "effort", "funding", "spending"],
    "complaint":  ["queja", "quejas", "reclamo", "reclamos", "complaint", "complaints", "report issue", "open complaint",
                   "filed", "utility outage", "critical issue", "resolved"],
    "prepare":    ["prepararse", "preparar", "preparacion", "que debo hacer", "como debo", "prepare", "preparation", "what should i do", "advice", "recommend",
                   "plan", "planning", "emergency kit", "ready", "steps to take", "what to do",
                   "how do i", "should i"],
}

def _fold(text: str) -> str:
    """Lower-case and strip accents so 'inundación' matches 'inundacion' (Spanish support)."""
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


def detect_intent(text: str) -> str:
    """
    Returns the intent category for a user message.
    PowerBI equivalent: nested CONTAINSSTRING checks inside a SWITCH(TRUE(), ...) column.
    """
    t = _fold(text)
    for intent, keywords in _INTENTS.items():
        for kw in keywords:
            # Short keywords must be whole words ("hi" must not match "Chicago");
            # longer ones may match as a word prefix ("complaint" matches "complaints").
            pattern = r"\b" + re.escape(kw) + (r"\b" if len(kw) <= 4 else "")
            if re.search(pattern, t):
                return intent
    return "general"


# ── County extraction ─────────────────────────────────────────────────────────
# PowerBI equivalent: LOOKUPVALUE(Counties[county], CONTAINSSTRING(query, Counties[county]))

def extract_county(text: str, county_list: list[str]) -> str | None:
    """
    Returns the first county name found in text, or None.
    Matches longest name first to avoid partial matches (e.g. 'Rock Island' before 'Rock').
    """
    t = text.lower()
    for county in sorted(county_list, key=len, reverse=True):
        if county.lower() in t:
            return county
    if "chicago" in t:
        return "Cook" if "Cook" in county_list else None
    return None


# ── Formatting helpers ────────────────────────────────────────────────────────

def _risk_badge(level: str, lang: str = "en") -> str:
    key = {"Low": "risk.low", "Medium": "risk.medium", "High": "risk.high", "Very High": "risk.very_high"}.get(level)
    return t(key, lang) if key else level


def _svi_label(svi: float, lang: str = "en") -> str:
    if svi >= 0.7:
        return t("svi.very_high", lang)
    if svi >= 0.5:
        return t("svi.high", lang)
    if svi >= 0.3:
        return t("svi.moderate", lang)
    return t("svi.low", lang)


def _season_tip(lang: str = "en") -> str:
    m = datetime.now().month
    key = "season.winter" if m in (12, 1, 2) else "season.spring" if m in (3, 4, 5) else "season.summer" if m in (6, 7, 8) else "season.fall"
    return t(key, lang)


# ── Response builder ──────────────────────────────────────────────────────────

def _eq(series: pd.Series, county: str) -> pd.Series:
    return series.astype(str).str.lower() == county.lower()


def _cooling_response(text: str, county: str | None, lang: str = "en") -> str:
    cc = _load_cooling()
    if cc.empty:
        return t("chat.cooling.no_list", lang)
    tl = text.lower()
    zip_m = re.search(r"\b(\d{5})\b", tl)
    cities = sorted(cc["city"].dropna().unique(), key=len, reverse=True)
    city = next((c for c in cities if c.lower() in tl), None)
    if zip_m:
        sel, where = cc[cc["zip"] == zip_m.group(1)], t("chat.cooling.where_zip", lang, zip=zip_m.group(1))
        if sel.empty:
            sel, where = cc[cc["city"] == "Chicago"], t("chat.cooling.where_zip_none", lang)
    elif city:
        sel, where = cc[cc["city"] == city], city
    else:
        sel, where = cc[cc["city"] == "Chicago"], "Chicago"
    lines = [t("chat.cooling.header", lang, where=where, n=len(sel))]
    for _, r in sel.head(8).iterrows():
        lines.append(f"**{r['name']}**\n  \U0001F4CD {r['address']}, {r['city']} {r['zip']}\n  \U0001F550 {r['hours']}\n  \U0001F4DE {r['phone']}\n")
    if len(sel) > 8:
        lines.append(t("chat.cooling.more", lang, n=len(sel)))
    lines.append(t("chat.cooling.footer", lang, refreshed=str(cc["last_refreshed_utc"].iloc[0])[:10]))
    return "\n".join(lines)


def build_response(
    intent: str,
    county: str | None,
    risk_df: pd.DataFrame,
    capacity_df: pd.DataFrame,
    complaints_df: pd.DataFrame,
    user_text: str = "",
    lang: str = "en",
) -> str:
    """Produce a formatted response from structured data lookups, in ``lang`` ('en' or 'es').

    Text comes from ``locales/<lang>.json``; data values (place names, hazards, statuses) are shown as stored.
    """
    shelters = _load_shelters()
    aid = _load_aid()
    contacts = _load_contacts()
    tip = _season_tip(lang)

    if intent == "greeting":
        return t("chat.greeting", lang, season_tip=tip)
    if intent == "thanks":
        return t("chat.thanks", lang)
    if intent == "cooling":
        return _cooling_response(user_text, county, lang)

    if intent == "emergency":  # highest priority, always shown first
        lines = [t("chat.emergency", lang)]
        if county and not contacts.empty:
            row = contacts[_eq(contacts["county"], county)]
            if not row.empty:
                lines.append(t("chat.emergency.county", lang, county=county, phone=row.iloc[0]["ema_phone"]))
        lines.append(f"\n{tip}")
        return "\n".join(lines)

    if intent == "shelter":
        if county and not shelters.empty:
            s = shelters[_eq(shelters["county"], county)]
            if not s.empty:
                lines = [t("chat.shelter.header", lang, county=county)]
                for _, r in s.iterrows():
                    lines.append(t("chat.shelter.item", lang, name=r["shelter_name"], address=r["address"], city=r["city"], zip=r["zip"],
                                   capacity=r["capacity"], type=r["shelter_type"], phone=r["phone"], open_24h=r["open_24h"]))
                lines.append(t("chat.shelter.call_ahead", lang))
                return "\n".join(lines)
            return t("chat.shelter.none", lang, county=county)
        return t("chat.shelter.general", lang)

    if intent == "aid":
        lines = []
        if county and not aid.empty:
            a = aid[_eq(aid["county"], county)]
            if not a.empty:
                lines.append(t("chat.aid.header", lang, county=county))
                for _, r in a.iterrows():
                    lines.append(t("chat.aid.item", lang, name=r["org_name"], aid_type=r["aid_type"], phone=r["phone"], hours=r["hours"]))
                lines.append("")
        lines.append(t("chat.aid.statewide", lang))
        return "\n".join(lines)

    if intent == "contact":
        if county and not contacts.empty:
            row = contacts[_eq(contacts["county"], county)]
            if not row.empty:
                r = row.iloc[0]
                return t("chat.contact.county", lang, county=county, agency=r["ema_name"], phone=r["ema_phone"],
                         region=r["iema_region"], hotline=r["hotline"])
        return t("chat.contact.general", lang)

    if intent == "risk":
        if county:
            c_risk = risk_df[_eq(risk_df["county"], county)]
            if not c_risk.empty:
                svi = c_risk["svi_score"].iloc[0]
                lines = [t("chat.risk.header", lang, county=county)]
                for _, r in c_risk.iterrows():
                    lines.append(t("chat.risk.line", lang, hazard=r["hazard"], badge=_risk_badge(r["risk_level"], lang),
                                   score=f"{r['risk_score']:.1f}", svi=f"{r['svi_score']:.2f}"))
                lines.append(t("chat.risk.svi", lang, svi=f"{svi:.2f}", label=_svi_label(svi, lang)))
                open_c = complaints_df[_eq(complaints_df["county"], county) & (complaints_df["status"] == "Open")]
                if not open_c.empty:
                    lines.append(t("chat.risk.complaints", lang, n=len(open_c), crit=len(open_c[open_c["priority"] == "Critical"])))
                return "\n".join(lines)
            return t("chat.risk.none", lang, county=county)
        high = risk_df[risk_df["risk_level"].isin(["High", "Very High"])]
        return t("chat.risk.state", lang, high=len(high), avg=f"{risk_df['risk_score'].mean():.2f}", svi=f"{risk_df['svi_score'].mean():.2f}")

    if intent == "mitigation":
        if county:
            cap = capacity_df[_eq(capacity_df["county"], county)]
            if not cap.empty:
                lines = [t("chat.mit.header", lang, county=county)]
                for _, r in cap.iterrows():
                    pct = (r["amount_spent_usd"] / r["budget_usd"] * 100) if r.get("budget_usd", 0) > 0 else 0
                    lines.append(t("chat.mit.item", lang, effort=r["mitigation_effort"], hazard=r["hazard"], status=r["status"],
                                   budget=f"{r['budget_usd']:,.0f}", pct=f"{pct:.0f}", people=f"{r['people_affected']:,}"))
                return "\n".join(lines)
            return t("chat.mit.none", lang, county=county)
        return t("chat.mit.state", lang, active=len(capacity_df[capacity_df["status"] == "In Progress"]),
                 budget=f"{capacity_df['budget_usd'].sum():,.0f}", spent=f"{capacity_df['amount_spent_usd'].sum():,.0f}",
                 people=f"{capacity_df['people_affected'].sum():,}")

    if intent == "complaint":
        if county:
            c_comp = complaints_df[_eq(complaints_df["county"], county)]
            open_c = c_comp[c_comp["status"] == "Open"]
            res_c = c_comp[c_comp["status"] == "Resolved"]
            lines = [t("chat.comp.header", lang, county=county, open=len(open_c), resolved=len(res_c))]
            if not open_c.empty:
                lines.append(t("chat.comp.open_issues", lang))
                for _, r in open_c.head(5).iterrows():
                    d = str(r["date_filed"])[:10] if pd.notna(r.get("date_filed")) else t("chat.comp.na", lang)
                    lines.append(t("chat.comp.item", lang, priority=r["priority"], hazard=r["hazard"], category=r["category"], date=d))
            return "\n".join(lines)
        open_all = complaints_df[complaints_df["status"] == "Open"]
        return t("chat.comp.state", lang, open=len(open_all), crit=len(open_all[open_all["priority"] == "Critical"]))

    if intent == "prepare":
        lines = [t("chat.prep.header", lang)]
        if county:
            c_risk = risk_df[_eq(risk_df["county"], county)]
            if not c_risk.empty:
                worst = c_risk.loc[c_risk["risk_score"].idxmax()]
                svi = c_risk["svi_score"].iloc[0]
                lines.append(t("chat.prep.profile", lang, county=county, hazard=worst["hazard"], badge=_risk_badge(worst["risk_level"], lang),
                               score=f"{worst['risk_score']:.1f}", svi=f"{svi:.2f}", label=_svi_label(svi, lang)))
                lines.append(t("chat.prep.high" if worst["risk_level"] in ("High", "Very High") else "chat.prep.normal", lang, county=county))
        else:
            lines.append(t("chat.prep.general", lang, season_tip=tip))
        return "\n".join(lines)

    if county:
        c_risk = risk_df[_eq(risk_df["county"], county)]
        if not c_risk.empty:
            lines = [t("chat.summary.header", lang, county=county)]
            for _, r in c_risk.iterrows():
                lines.append(t("chat.summary.line", lang, hazard=r["hazard"], badge=_risk_badge(r["risk_level"], lang), score=f"{r['risk_score']:.1f}"))
            lines.append(t("chat.summary.footer", lang))
            return "\n".join(lines)

    return t("chat.fallback", lang)


_RISK_COLS = ("county", "region", "hazard", "risk_score", "risk_level", "svi_score")
_CAPACITY_COLS = ("county", "hazard", "mitigation_effort", "status", "people_affected", "budget_usd", "amount_spent_usd")
_COMPLAINT_COLS = ("county", "hazard", "category", "status", "priority", "description")


def _ensure_columns(df: pd.DataFrame | None, columns: tuple[str, ...]) -> pd.DataFrame:
    """Return ``df`` with every expected column present so empty or partial frames never raise KeyError."""
    out = pd.DataFrame() if df is None else df.copy()
    for col in columns:
        if col not in out.columns:
            out[col] = pd.Series(dtype="object")
    return out


# ── Public entry point ────────────────────────────────────────────────────────

def chat(
    user_message: str,
    risk_df: pd.DataFrame,
    capacity_df: pd.DataFrame,
    complaints_df: pd.DataFrame,
    lang: str = "en",
) -> str:
    """
    Main chatbot entry point (``lang`` is 'en' or 'es'). No external calls. No API keys required.
    Pass the full (unfiltered) DataFrames so users can query any county.
    """
    risk_df = _ensure_columns(risk_df, _RISK_COLS)
    capacity_df = _ensure_columns(capacity_df, _CAPACITY_COLS)
    complaints_df = _ensure_columns(complaints_df, _COMPLAINT_COLS)
    county_list = risk_df["county"].dropna().unique().tolist()
    intent      = detect_intent(user_message)
    county      = extract_county(user_message, county_list)
    return build_response(intent, county, risk_df, capacity_df, complaints_df, user_message, normalize_lang(lang))
