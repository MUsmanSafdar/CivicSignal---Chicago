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
from functools import lru_cache

_ROOT = Path(__file__).resolve().parent
_DATA_DIR = _ROOT / "data" if (_ROOT / "data" / "cooling_centers.csv").exists() else _ROOT

# ── Reference table loader (cached per session) ───────────────────────────────

@lru_cache(maxsize=1)
def _load_shelters() -> pd.DataFrame:
    p = _DATA_DIR / "shelters.csv"
    return pd.read_csv(p) if p.exists() else pd.DataFrame()

@lru_cache(maxsize=1)
def _load_aid() -> pd.DataFrame:
    p = _DATA_DIR / "aid_resources.csv"
    return pd.read_csv(p) if p.exists() else pd.DataFrame()

@lru_cache(maxsize=1)
def _load_cooling() -> pd.DataFrame:
    p = _DATA_DIR / "cooling_centers.csv"
    return pd.read_csv(p, dtype={"zip": str}) if p.exists() else pd.DataFrame()

@lru_cache(maxsize=1)
def _load_contacts() -> pd.DataFrame:
    p = _DATA_DIR / "emergency_contacts.csv"
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


# ── Intent detection ──────────────────────────────────────────────────────────
# PowerBI: SWITCH(TRUE(), CONTAINSSTRING(query, kw1) || CONTAINSSTRING(query, kw2), "intent", ...)

_INTENTS: dict[str, list[str]] = {
    "greeting":   ["hi", "hello", "hey", "good morning", "good afternoon", "good evening", "howdy"],
    "thanks":     ["thank you", "thanks", "thx", "appreciate"],
    "cooling":    ["cooling", "cool down", "heat", "hot", "heatwave", "heat wave", "air condition",
                   "air-condition", "a/c", "too hot", "swelter"],
    "emergency":  ["emergency", "urgent", "danger", "crisis", "trapped", "hurt", "injured",
                   "fire", "flooding", "tornado", "earthquake", "disaster", "sos", "right now", "immediately"],
    "shelter":    ["shelter", "evacuation center", "safe place", "where to go", "refuge",
                   "emergency housing", "sleep", "stay tonight", "warming center"],
    "aid":        ["aid", "assistance", "food", "water", "supplies", "medical", "medicine",
                   "financial", "fema", "relief", "support", "grant", "benefit", "donation",
                   "resource", "help me", "need help"],
    "contact":    ["contact", "phone number", "who to call", "ema", "hotline", "helpline",
                   "211", "reach", "email", "call"],
    "risk":       ["risk", "risk score", "risk level", "how bad", "how risky", "svi",
                   "vulnerability", "danger level", "hazard level", "score"],
    "mitigation": ["mitigation", "what is being done", "protection", "prevention",
                   "budget", "program", "project", "effort", "funding", "spending"],
    "complaint":  ["complaint", "complaints", "report issue", "open complaint",
                   "filed", "utility outage", "critical issue", "resolved"],
    "prepare":    ["prepare", "preparation", "what should i do", "advice", "recommend",
                   "plan", "planning", "emergency kit", "ready", "steps to take", "what to do",
                   "how do i", "should i"],
}

def detect_intent(text: str) -> str:
    """
    Returns the intent category for a user message.
    PowerBI equivalent: nested CONTAINSSTRING checks inside a SWITCH(TRUE(), ...) column.
    """
    t = text.lower()
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

def _risk_badge(level: str) -> str:
    return {"Low": "🟢 Low", "Medium": "🟡 Medium",
            "High": "🔴 High", "Very High": "🔴 Very High"}.get(level, level)

def _svi_label(svi: float) -> str:
    if svi >= 0.7:   return "Very High — vulnerable populations need priority support"
    if svi >= 0.5:   return "High — targeted outreach recommended"
    if svi >= 0.3:   return "Moderate"
    return "Lower vulnerability"

def _season_tip() -> str:
    m = datetime.now().month
    if m in (12, 1, 2):
        return "❄️ **Winter**: Hypothermia and ice hazards are elevated. Find a warming center near you."
    if m in (3, 4, 5):
        return "🌪️ **Spring**: Peak tornado and flooding season in Illinois. Know your evacuation route."
    if m in (6, 7, 8):
        return "☀️ **Summer**: Heat is dangerous especially for high-SVI communities. Use cooling centers."
    return "🍂 **Fall**: Early freezes and wind events are possible. Check your emergency kit."


# ── Response builder ──────────────────────────────────────────────────────────

def _cooling_response(text: str, county: str | None) -> str:
    cc = _load_cooling()
    if cc.empty:
        return "No cooling-center list is loaded. Call **311** (Chicago) or **211** for the nearest cooling center."
    t = text.lower()
    zip_m = re.search(r"\b(\d{5})\b", t)
    cities = sorted(cc["city"].dropna().unique(), key=len, reverse=True)
    city = next((c for c in cities if c.lower() in t), None)
    if zip_m:
        sel, where = cc[cc["zip"] == zip_m.group(1)], f"ZIP {zip_m.group(1)}"
        if sel.empty:
            sel, where = cc[cc["city"] == "Chicago"], "Chicago (none listed in that ZIP)"
    elif city:
        sel, where = cc[cc["city"] == city], city
    else:
        sel, where = cc[cc["city"] == "Chicago"], "Chicago"
    lines = [f"\u2600\ufe0f **Cooling centers: {where}** ({len(sel)} listed)\n"]
    for _, r in sel.head(8).iterrows():
        lines.append(
            f"**{r['name']}**\n"
            f"  \U0001F4CD {r['address']}, {r['city']} {r['zip']}\n"
            f"  \U0001F550 {r['hours']}\n"
            f"  \U0001F4DE {r['phone']}\n"
        )
    if len(sel) > 8:
        lines.append(f"*Showing 8 of {len(sel)}. Add a ZIP code or suburb to narrow it, or open the list on this page.*\n")
    lines.append(
        "**Heat safety**: drink water, avoid strenuous activity, and check on older neighbors. "
        "Call **911** for confusion, fainting, hot dry skin or a very high body temperature.\n\n"
        "*Hours change. Call before you go, or call **311** (Chicago) or **211**. "
        f"List last refreshed {str(cc['last_refreshed_utc'].iloc[0])[:10]}.*"
    )
    return "\n".join(lines)


def build_response(
    intent: str,
    county: str | None,
    risk_df: pd.DataFrame,
    capacity_df: pd.DataFrame,
    complaints_df: pd.DataFrame,
    user_text: str = "",
) -> str:
    """
    Produces a formatted response string from structured data lookups.
    PowerBI equivalent: a series of FILTER / LOOKUPVALUE calls feeding a template measure.
    """
    shelters  = _load_shelters()
    aid       = _load_aid()
    contacts  = _load_contacts()

    # ── Greeting ─────────────────────────────────────────────────────────────
    if intent == "greeting":
        return (
            "👋 **Hello! I'm your Illinois Hazard Assistant.**\n\n"
            "I run entirely inside this dashboard — no external AI needed. I can help with:\n\n"
            "- ☀️ **Cooling centers** — *'cooling centers in Chicago'* or add a ZIP like *'cooling center 60639'*\n"
            "- 🏠 **Shelter locations** — *'shelters in Cook County'*\n"
            "- 🤝 **Aid and assistance** — *'aid available in Peoria County'*\n"
            "- 📞 **Emergency contacts** — *'contact for McLean County'*\n"
            "- 📊 **Risk levels and SVI** — *'risk level for Sangamon County'*\n"
            "- 🔧 **Mitigation efforts** — *'mitigation in DuPage County'*\n"
            "- 📋 **Open complaints** — *'complaints in Adams County'*\n"
            "- 🧭 **Preparedness guidance** — *'how should I prepare?'*\n"
            "- 🚨 **Immediate help** — type *'emergency'* for critical resources\n\n"
            f"{_season_tip()}"
        )

    if intent == "thanks":
        return "You're welcome! Stay safe. Ask me anything else about Illinois hazard preparedness. 🙏"

    # ── Cooling centers (heat) ────────────────────────────────────────────────
    if intent == "cooling":
        return _cooling_response(user_text, county)

    # ── Emergency (highest priority — always shown first) ─────────────────────
    if intent == "emergency":
        lines = [
            "🚨 **IMMEDIATE EMERGENCY RESOURCES**\n",
            "- **Call 911** for life-threatening emergencies (fire, medical, police)",
            "- **IEMA 24/7 Hotline**: 1-800-782-7860",
            "- **Red Cross Disaster Relief**: 1-800-733-2767",
            "- **FEMA Disaster Helpline**: 1-800-621-3362",
            "- **211** — food, shelter, utilities, and non-emergency support",
            "- **Text SHELTER + ZIP to 43362** — FEMA nearest shelter locator",
            "- **Poison Control**: 1-800-222-1222",
        ]
        if county and not contacts.empty:
            row = contacts[contacts["county"].str.lower() == county.lower()]
            if not row.empty:
                r = row.iloc[0]
                lines.append(f"\n📍 **{county} County EMA**: {r['ema_phone']}")
        lines.append(f"\n{_season_tip()}")
        return "\n".join(lines)

    # ── Shelter ───────────────────────────────────────────────────────────────
    if intent == "shelter":
        if county and not shelters.empty:
            s = shelters[shelters["county"].str.lower() == county.lower()]
            if not s.empty:
                lines = [f"🏠 **Emergency Shelters — {county} County**\n"]
                for _, r in s.iterrows():
                    lines.append(
                        f"**{r['shelter_name']}**\n"
                        f"  📍 {r['address']}, {r['city']} {r['zip']}\n"
                        f"  👥 Capacity: {r['capacity']} people\n"
                        f"  🏷️ Type: {r['shelter_type']}\n"
                        f"  📞 {r['phone']}  |  24hr open: {r['open_24h']}\n"
                    )
                lines.append("*Always call ahead to confirm a shelter is active before traveling.*")
                return "\n".join(lines)
            else:
                return (
                    f"No shelter records on file for **{county} County**.\n\n"
                    "**How to find the nearest shelter:**\n"
                    "- Call **211** (free, 24/7 Illinois helpline)\n"
                    "- Text **SHELTER + your ZIP** to **43362** (FEMA)\n"
                    "- Contact your county EMA — ask me *'contact for {county} County'*\n"
                    "- Visit [IEMA](https://www2.illinois.gov/iema) for registered sites"
                )
        return (
            "🏠 **Finding Emergency Shelters in Illinois**\n\n"
            "- **Call 211** — nearest shelter, 24/7, free\n"
            "- **Text SHELTER + ZIP** to **43362** (FEMA)\n"
            "- **Red Cross**: 1-800-733-2767\n"
            "- **IEMA Shelter Locator**: www2.illinois.gov/iema\n\n"
            "💡 For county-specific listings ask me: *'shelters in [County] County'*"
        )

    # ── Aid ───────────────────────────────────────────────────────────────────
    if intent == "aid":
        lines = []
        if county and not aid.empty:
            a = aid[aid["county"].str.lower() == county.lower()]
            if not a.empty:
                lines.append(f"🤝 **Aid Resources — {county} County**\n")
                for _, r in a.iterrows():
                    lines.append(
                        f"**{r['org_name']}**\n"
                        f"  🎯 {r['aid_type']}\n"
                        f"  📞 {r['phone']}  |  ⏰ {r['hours']}\n"
                    )
                lines.append("")
        lines += [
            "🌐 **Statewide Aid (always available)**\n",
            "- **211** — food, housing, utilities, crisis support (24/7, free)",
            "- **FEMA Disaster Helpline**: 1-800-621-3362 | fema.gov",
            "- **Red Cross**: 1-800-733-2767 | redcross.org",
            "- **SBA Disaster Loans**: 1-800-659-2955",
            "- **Illinois DCEO Emergency Grants**: dceo.illinois.gov",
            "- **Salvation Army Disaster Services**: 1-800-725-2769",
        ]
        return "\n".join(lines)

    # ── Contact ───────────────────────────────────────────────────────────────
    if intent == "contact":
        if county and not contacts.empty:
            row = contacts[contacts["county"].str.lower() == county.lower()]
            if not row.empty:
                r = row.iloc[0]
                return (
                    f"📞 **{county} County Emergency Management**\n\n"
                    f"- **Agency**: {r['ema_name']}\n"
                    f"- **Phone**: {r['ema_phone']}\n"
                    f"- **IEMA Region**: {r['iema_region']}\n"
                    f"- **Community Helpline**: {r['hotline']}\n\n"
                    "**Statewide contacts:**\n"
                    "- IEMA 24/7: **1-800-782-7860**\n"
                    "- Community resources: **211**\n"
                    "- FEMA: **1-800-621-3362**"
                )
        return (
            "📞 **Illinois Emergency Contacts**\n\n"
            "- **IEMA 24/7 Hotline**: 1-800-782-7860\n"
            "- **Community Help (211)**: Dial 2-1-1\n"
            "- **FEMA**: 1-800-621-3362\n"
            "- **Red Cross**: 1-800-733-2767\n"
            "- **Poison Control**: 1-800-222-1222\n"
            "- **Crisis Text Line**: Text HOME to 741741\n\n"
            "💡 For a specific county EMA: *'contact for Kane County'*"
        )

    # ── Risk ──────────────────────────────────────────────────────────────────
    if intent == "risk":
        if county:
            c_risk = risk_df[risk_df["county"].str.lower() == county.lower()]
            if not c_risk.empty:
                svi = c_risk["svi_score"].iloc[0]
                lines = [f"📊 **{county} County — Hazard Risk Profile**\n"]
                for _, r in c_risk.iterrows():
                    lines.append(
                        f"- **{r['hazard']}**: {_risk_badge(r['risk_level'])} "
                        f"| Score: {r['risk_score']:.1f}/5.0 | SVI: {r['svi_score']:.2f}"
                    )
                lines.append(f"\n**Social Vulnerability Index**: {svi:.2f} — {_svi_label(svi)}")
                open_c = complaints_df[
                    (complaints_df["county"].str.lower() == county.lower()) &
                    (complaints_df["status"] == "Open")
                ]
                if not open_c.empty:
                    crit = open_c[open_c["priority"] == "Critical"]
                    lines.append(
                        f"\n⚠️ **{len(open_c)} open complaint(s)** — "
                        f"{len(crit)} critical priority"
                    )
                return "\n".join(lines)
            return f"No risk data found for **{county} County** in the current dataset."

        high = risk_df[risk_df["risk_level"].isin(["High", "Very High"])]
        return (
            f"📊 **Statewide Risk Snapshot**\n\n"
            f"- High/Very High risk records: **{len(high)}**\n"
            f"- Average risk score: **{risk_df['risk_score'].mean():.2f} / 5.0**\n"
            f"- Average SVI: **{risk_df['svi_score'].mean():.2f}**\n\n"
            "💡 Ask about a specific county: *'risk level for McLean County'*"
        )

    # ── Mitigation ────────────────────────────────────────────────────────────
    if intent == "mitigation":
        if county:
            cap = capacity_df[capacity_df["county"].str.lower() == county.lower()]
            if not cap.empty:
                lines = [f"🔧 **Mitigation Efforts — {county} County**\n"]
                for _, r in cap.iterrows():
                    pct = (r["amount_spent_usd"] / r["budget_usd"] * 100) if r.get("budget_usd", 0) > 0 else 0
                    lines.append(
                        f"**{r['mitigation_effort']}** _{r['hazard']}_\n"
                        f"  Status: {r['status']} | Budget: ${r['budget_usd']:,.0f} "
                        f"| Spent: {pct:.0f}% | People covered: {r['people_affected']:,}\n"
                    )
                return "\n".join(lines)
            return f"No mitigation records on file for **{county} County**."

        in_prog = capacity_df[capacity_df["status"] == "In Progress"]
        return (
            f"🔧 **Statewide Mitigation Summary**\n\n"
            f"- Active projects: **{len(in_prog)}**\n"
            f"- Total budget allocated: **${capacity_df['budget_usd'].sum():,.0f}**\n"
            f"- Total spent to date: **${capacity_df['amount_spent_usd'].sum():,.0f}**\n"
            f"- People covered: **{capacity_df['people_affected'].sum():,}**\n\n"
            "💡 For county detail: *'mitigation in Peoria County'*"
        )

    # ── Complaint ─────────────────────────────────────────────────────────────
    if intent == "complaint":
        if county:
            c_comp = complaints_df[complaints_df["county"].str.lower() == county.lower()]
            open_c = c_comp[c_comp["status"] == "Open"]
            res_c  = c_comp[c_comp["status"] == "Resolved"]
            lines  = [
                f"📋 **Complaints — {county} County**\n",
                f"Open: **{len(open_c)}** | Resolved: **{len(res_c)}**\n",
            ]
            if not open_c.empty:
                lines.append("*Open issues:*")
                for _, r in open_c.head(5).iterrows():
                    date = str(r["date_filed"])[:10] if pd.notna(r.get("date_filed")) else "N/A"
                    lines.append(
                        f"- [{r['priority']}] **{r['hazard']}** — {r['category']} ({date})"
                    )
            return "\n".join(lines)

        total_open = len(complaints_df[complaints_df["status"] == "Open"])
        total_crit = len(
            complaints_df[(complaints_df["status"] == "Open") & (complaints_df["priority"] == "Critical")]
        )
        return (
            f"📋 **Statewide Complaint Summary**\n\n"
            f"- Open: **{total_open}** | Critical open: **{total_crit}**\n\n"
            "💡 For county detail: *'complaints in Adams County'*"
        )

    # ── Preparedness guidance ─────────────────────────────────────────────────
    if intent == "prepare":
        lines = ["🧭 **Emergency Preparedness Guidance**\n"]
        if county:
            c_risk = risk_df[risk_df["county"].str.lower() == county.lower()]
            if not c_risk.empty:
                worst = c_risk.loc[c_risk["risk_score"].idxmax()]
                svi   = c_risk["svi_score"].iloc[0]
                lines += [
                    f"**{county} County Profile:**",
                    f"- Highest risk: **{worst['hazard']}** — {_risk_badge(worst['risk_level'])} ({worst['risk_score']:.1f}/5.0)",
                    f"- SVI: **{svi:.2f}** — {_svi_label(svi)}",
                    "",
                ]
                if worst["risk_level"] in ("High", "Very High"):
                    lines += [
                        "**Priority actions for your high-risk county:**",
                        "1. 📋 Register with your county EMA for priority alerts and assistance",
                        "2. 🗺️ Plan 2 evacuation routes from your home",
                        "3. 🎒 Build a 72-hour kit: water (1 gal/person/day), food, meds, flashlight, radio, documents",
                        "4. 📱 Sign up for Wireless Emergency Alerts and county text notifications",
                        "5. 🏠 Locate your nearest shelter — ask *'shelters in " + county + " County'*",
                        "6. 👴 Help neighbors who may need extra assistance during events",
                    ]
                else:
                    lines += [
                        "**Recommended actions:**",
                        "1. 📋 Review your household emergency plan annually",
                        "2. 🎒 Keep a basic 72-hour emergency kit updated",
                        "3. 📱 Stay informed via county alerts and IEMA notifications",
                        "4. 👴 Check on elderly or disabled neighbors during severe weather",
                    ]
        else:
            lines += [
                "**Step 1 — Build a 72-hour emergency kit:**",
                "- 💧 Water: 1 gallon per person per day (3-day minimum)",
                "- 🥫 Non-perishable food (3-day supply)",
                "- 🩹 First aid kit and a battery-powered or hand-crank radio",
                "- 💊 Medications — at least a 7-day supply",
                "- 📄 Copies of IDs, insurance documents, and bank info",
                "- 🔦 Flashlight, extra batteries, phone charger",
                "",
                "**Step 2 — Make a plan:**",
                "- Identify 2 evacuation routes from your home",
                "- Agree on a family meeting point",
                "- Designate an out-of-state contact everyone can reach",
                "",
                "**Step 3 — Stay informed:**",
                "- Sign up for your county's emergency alert system",
                "- Bookmark IEMA: www2.illinois.gov/iema",
                "- Follow NOAA Weather Radio or weather.gov",
                "",
                "**Step 4 — Register if you have special needs** with your county EMA for priority assistance.",
                "",
                f"{_season_tip()}",
            ]
        return "\n".join(lines)

    # ── General / county quick summary ────────────────────────────────────────
    if county:
        c_risk = risk_df[risk_df["county"].str.lower() == county.lower()]
        if not c_risk.empty:
            lines = [f"📊 **{county} County — Quick Summary**\n"]
            for _, r in c_risk.iterrows():
                lines.append(
                    f"- **{r['hazard']}**: {_risk_badge(r['risk_level'])} "
                    f"(Score {r['risk_score']:.1f}/5.0)"
                )
            lines.append(
                "\nAsk me about **shelters**, **aid**, **contacts**, "
                "**mitigation**, **complaints**, or **preparedness** for this county."
            )
            return "\n".join(lines)

    # ── Fallback ──────────────────────────────────────────────────────────────
    return (
        "I can help with Illinois hazard information. Try:\n\n"
        "- *'Cooling centers in Chicago'* (add a ZIP or suburb to narrow it)\n"
        "- *'Shelters in Cook County'*\n"
        "- *'Aid available in Peoria County'*\n"
        "- *'Risk level for McLean County'*\n"
        "- *'Emergency contacts for DuPage County'*\n"
        "- *'Open complaints in Adams County'*\n"
        "- *'Mitigation efforts in Sangamon County'*\n"
        "- *'How should I prepare for emergencies?'*\n"
        "- *'Emergency!'* — immediate critical resources"
    )


# ── Public entry point ────────────────────────────────────────────────────────

def chat(
    user_message: str,
    risk_df: pd.DataFrame,
    capacity_df: pd.DataFrame,
    complaints_df: pd.DataFrame,
) -> str:
    """
    Main chatbot entry point. No external calls. No API keys required.
    Pass the full (unfiltered) DataFrames so users can query any county.
    """
    county_list = risk_df["county"].dropna().unique().tolist()
    intent      = detect_intent(user_message)
    county      = extract_county(user_message, county_list)
    return build_response(intent, county, risk_df, capacity_df, complaints_df, user_message)
