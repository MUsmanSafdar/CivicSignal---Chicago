"""Funded projects: FEMA hazard mitigation grant applications in Illinois, by county and town, on a map with a list.

Records come from FEMA's public OpenFEMA dataset "HMA Subapplications" (v2). They are fetched when the tab is
opened and cached for a day. If FEMA cannot be reached, a saved copy (fema_hma_illinois.json, next to this file)
is used when present; otherwise the tab says so. Nothing is invented and placeholder projects are never shown.

Town pins use il_city_points.json (town centre coordinates from OpenStreetMap). A pin marks the applicant's town,
not the project address: FEMA does not publish project addresses. County shapes and vulnerability scores come from
the same Illinois dataset as the statewide explorer (site.html), which is sample data.

The parsing and grouping functions are pure so they can be tested without Streamlit or a network.
"""
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

_HERE = Path(__file__).parent
ENTITY = "HmaSubapplications"
API = "https://www.fema.gov/api/open/v2/" + ENTITY
DATASET_PAGE = "https://www.fema.gov/openfema-data-page/hma-subapplications-v2"
SNAPSHOT = "fema_hma_illinois.json"
POINTS = "il_city_points.json"
FIELDS = ("subapplicationIdentifier", "program", "fiscalYear", "subapplicantName", "subapplicantCity",
          "subapplicantStateAbbreviation", "status", "subapplicationType", "benefitingCounties", "primaryActivity",
          "subapplicationTitle", "primaryHazard", "federalShareAmount", "totalObligatedAmount")
PAGE_SIZE = 5000
MAX_PAGES = 10
SVI_MIN = 0.50   # application-defined screening rule (same thresholds as analysis.py), not a federal standard
RISK_MIN = 3.0   # hazard score on the 0 to 5 scale
STAGES = ("open", "closed", "review", "no")   # funded and in progress, completed, under review, not funded
_NO = ("ineligible", "denied", "not approved", "not selected", "withdraw", "void", "cancel")
_CLOSED = ("closed", "complet")
_OPEN = ("approved", "obligated", "awarded", "accepted", "closeout")
_PROGRAMS = (("swift current", "FMA Swift Current"), ("congressionally directed", "PDM Directed Spending"),
             ("legislative pre-disaster", "LPDM"), ("hazard mitigation grant program", "HMGP"),
             ("building resilient infrastructure", "BRIC"), ("pre-disaster mitigation", "PDM"),
             ("flood mitigation assistance", "FMA"), ("severe repetitive loss", "SRL"),
             ("repetitive flood claims", "RFC"))
_DATA_RE = re.compile(r"const DATA = (\{.*?\});\n", re.S)
_MARK_RE = re.compile(r"/\*DATA\*/.*?/\*END\*/", re.S)


def norm_county(name) -> str:
    """Key for matching county names across sources: 'De Kalb', 'DEKALB COUNTY' and 'DeKalb (County)' all match."""
    s = re.sub(r"\(.*?\)", "", str(name or "")).lower()
    s = re.sub(r"\bcounty\b", "", s)
    s = re.sub(r"\bsaint\b", "st", s)
    return re.sub(r"[^a-z]", "", s)


def stage(status) -> str:
    """Sort FEMA's status wording into one of STAGES. Unfunded wording is checked first ('Not Approved')."""
    s = str(status or "").lower()
    if any(w in s for w in _NO):
        return "no"
    if any(w in s for w in _CLOSED):
        return "closed"
    if any(w in s for w in _OPEN):
        return "open"
    return "review"


def program_short(name) -> str:
    s = str(name or "").strip()
    low = s.lower()
    for needle, short in _PROGRAMS:
        if needle in low:
            return short
    return s or "Program not stated"


def _text(v) -> str:
    s = str(v).strip() if v is not None else ""
    return "" if s.lower() in ("null", "none", "unknown") else s


def _money(v) -> float:
    try:
        return max(0.0, float(v))
    except (TypeError, ValueError):
        return 0.0


def city_key(name) -> str:
    return re.sub(r"\s+", " ", _text(name).upper())


def city_label(name) -> str:
    """'EAST ST. LOUIS' -> 'East St. Louis', 'MCHENRY' -> 'McHenry'. Trailing ', IL' and stray commas are dropped."""
    s = re.sub(r",\s*IL$", "", city_key(name)).strip(" ,")
    out = " ".join(w.capitalize() for w in s.split())
    return re.sub(r"\bMc([a-z])", lambda m: "Mc" + m.group(1).upper(), out)


def counties_of(rec: dict) -> list:
    """County keys a record names as benefiting."""
    keys = [norm_county(p) for p in re.split(r"[;,/]", str(rec.get("benefitingCounties") or ""))]
    return [k for i, k in enumerate(keys) if k and k not in keys[:i]]


def clean(rec: dict, points: dict) -> dict:
    """The fields the page shows, with safe types. FEMA's own wording (status, title, redactions) is kept."""
    fy = rec.get("fiscalYear")
    kind, activity = _text(rec.get("subapplicationType")), _text(rec.get("primaryActivity"))
    pt = points.get(city_key(rec.get("subapplicantCity")))
    return {"id": _text(rec.get("subapplicationIdentifier")), "program": program_short(rec.get("program")),
            "pf": _text(rec.get("program")), "co": [],
            "fy": int(fy) if str(fy or "").isdigit() else None,
            "title": _text(rec.get("subapplicationTitle")) or activity or kind or "Activity not stated",
            "what": " · ".join(p for p in (kind, activity) if p), "hazard": _text(rec.get("primaryHazard")),
            "who": _text(rec.get("subapplicantName")), "city": city_label(rec.get("subapplicantCity")),
            "status": _text(rec.get("status")) or "Status not stated", "stage": stage(rec.get("status")),
            "fed": _money(rec.get("federalShareAmount")), "obl": _money(rec.get("totalObligatedAmount")),
            "pt": [float(pt[0]), float(pt[1])] if pt else None}


def group_projects(records: list, county_names: list, points: dict) -> dict:
    """Return {"by": {county: [project]}, "other": [project]} - "other" holds records naming no Illinois county."""
    lookup = {norm_county(n): n for n in county_names}
    by, other = {}, []
    rank = {s: i for i, s in enumerate(STAGES)}
    for rec in records:
        proj = clean(rec, points)
        keys = counties_of(rec)
        hits = [lookup[k] for k in keys if k in lookup]
        if len(hits) != len(keys):
            # Some FEMA records list counties from other states; a few of those names also exist in Illinois.
            # When any listed name is not an Illinois county, trust only the first Illinois one.
            hits = hits[:1]
        proj["co"] = hits
        if hits:
            for name in hits:
                by.setdefault(name, []).append(proj)
        else:
            other.append(proj)
    order = lambda p: (rank[p["stage"]], -(p["fy"] or 0), p["title"])  # noqa: E731
    for lst in by.values():
        lst.sort(key=order)
    other.sort(key=order)
    return {"by": by, "other": other}


def query_url(skip: int = 0) -> str:
    q = {"$filter": "subapplicantStateAbbreviation eq 'IL'", "$select": ",".join(FIELDS), "$top": str(PAGE_SIZE), "$skip": str(skip)}
    return API + "?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote, safe="$',")


def fetch_projects(opener=None) -> dict:
    """Download every Illinois record. Returns {"records": [...], "rundate": str}. Raises OSError/ValueError on failure."""
    opener = opener or (lambda url: urllib.request.urlopen(  # noqa: S310 - fixed https URL
        urllib.request.Request(url, headers={"User-Agent": "CivicSignal/1.0", "Accept": "application/json"}), timeout=25).read())
    records, rundate = [], ""
    for page in range(MAX_PAGES):
        body = json.loads(opener(query_url(page * PAGE_SIZE)))
        rows = body.get(ENTITY) if isinstance(body, dict) else None
        if not isinstance(rows, list):
            raise ValueError("unexpected response from FEMA")
        rundate = rundate or str((body.get("metadata") or {}).get("rundate") or "")
        records.extend(r for r in rows if isinstance(r, dict) and str(r.get("subapplicantStateAbbreviation") or "").upper() == "IL")
        if len(rows) < PAGE_SIZE:
            break
    if not records:
        raise ValueError("FEMA returned no Illinois records")
    return {"records": records, "rundate": rundate}


def load_snapshot(path: Path):
    """Saved copy of a past download, or None when missing or unreadable."""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not isinstance(d.get("records"), list) or not d["records"]:
        return None
    return {"records": [r for r in d["records"] if isinstance(r, dict)], "rundate": str(d.get("rundate") or ""), "saved": True}


def load_points(path: Path) -> dict:
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {city_key(k): v for k, v in d.items() if isinstance(v, list) and len(v) == 2} if isinstance(d, dict) else {}


def load_counties(site_html: str) -> dict:
    """Return {"vb": [w, h], "counties": [...]} from the explorer page's embedded dataset."""
    m = _DATA_RE.search(site_html)
    if not m:
        raise ValueError("county dataset not found in site.html")
    d = json.loads(m.group(1))
    counties = [{"n": c["n"], "r": c.get("r", ""), "svi": float(c["svi"]),
                 "top": max(float(v) for v in c["h"].values()), "d": c["d"]} for c in d["counties"]]
    return {"vb": d["vb"], "counties": counties}


def build_payload(site_html: str, fetched, points=None) -> dict:
    """fetched is the result of fetch_projects() or load_snapshot(), or None when no records are available."""
    data = load_counties(site_html)
    data["svi_min"], data["risk_min"], data["source"] = SVI_MIN, RISK_MIN, DATASET_PAGE
    if fetched is None:
        data.update(ok=False, by={}, other=[], total=0, rundate="", saved=False)
    else:
        g = group_projects(fetched["records"], [c["n"] for c in data["counties"]], points or {})
        data.update(ok=True, by=g["by"], other=g["other"], total=len(fetched["records"]),
                    rundate=str(fetched.get("rundate") or "")[:10], saved=bool(fetched.get("saved")))
    return data


def build_page(template: str, payload: dict) -> str:
    """Put the payload into the page template. '<' is escaped so data can never open or close a tag."""
    blob = json.dumps(payload, separators=(",", ":")).replace("<", "\\u003c")
    page, n = _MARK_RE.subn(lambda _m: blob, template, count=1)
    if n != 1:
        raise ValueError("data marker not found in projects_view.html")
    return page


def render():
    import streamlit as st
    import streamlit.components.v1 as components

    site, tpl = _HERE / "site.html", _HERE / "projects_view.html"
    missing = [p.name for p in (site, tpl) if not p.exists()]
    if missing:
        st.error("Funded projects files are missing: " + ", ".join(missing))
        return

    @st.cache_data(ttl=86400, show_spinner="Loading FEMA grant records…")
    def _cached():
        return fetch_projects()

    live = True
    try:
        fetched = _cached()
    except Exception:  # noqa: BLE001 - any network or format failure: fall back to the saved copy, never to placeholders
        live, fetched = False, load_snapshot(_HERE / SNAPSHOT)
    st.caption("FEMA hazard mitigation grant applications in Illinois, by county and town. Grant records are FEMA's "
               "public data; vulnerability scores are sample data.")
    if not live:
        if fetched is None:
            st.warning("FEMA's public grant data could not be loaded just now and no saved copy is installed, so no projects are shown.")
        else:
            st.info("FEMA could not be reached, so this is the saved copy of its records"
                    + (f" from {fetched['rundate'][:10]}." if fetched["rundate"] else "."))
        if st.button("Try FEMA again"):
            _cached.clear()
            st.rerun()
    page = build_page(tpl.read_text(encoding="utf-8"),
                      build_payload(site.read_text(encoding="utf-8"), fetched, load_points(_HERE / POINTS)))
    # The page sizes its own frame to its full height, so only the app scrolls; scrolling=True is a fallback.
    components.html(page, height=1100, scrolling=True)
    if live:
        with st.expander("Save a copy for offline use"):
            st.write(f"Download today's FEMA records and add the file to the app folder as `{SNAPSHOT}`. "
                     "The tab then works without internet and when FEMA is unavailable.")
            st.download_button("Download FEMA records", json.dumps({"rundate": fetched["rundate"], "records": fetched["records"]}),
                               file_name=SNAPSHOT, mime="application/json")
