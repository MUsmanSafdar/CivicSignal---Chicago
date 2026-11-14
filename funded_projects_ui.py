"""Funded projects: FEMA-funded hazard mitigation projects in Illinois, by county, on a dark map with a side list.

Project records come from FEMA's public OpenFEMA dataset "Hazard Mitigation Assistance Projects" (v4). They are
fetched when the tab is opened and cached for a day; nothing is invented, and if FEMA cannot be reached the tab
says so instead of showing placeholder projects. County shapes and vulnerability scores come from the same
Illinois dataset as the statewide explorer (site.html), which is sample data.

The parsing and grouping functions are pure so they can be tested without Streamlit or a network.
"""
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

_HERE = Path(__file__).parent
API = "https://www.fema.gov/api/open/v4/HazardMitigationAssistanceProjects"
ENTITY = "HazardMitigationAssistanceProjects"
DATASET_PAGE = "https://www.fema.gov/openfema-data-page/hazard-mitigation-assistance-projects-v4"
FIELDS = ("projectIdentifier", "state", "programArea", "programFy", "county", "projectCounties", "projectType", "status",
          "subrecipient", "dateApproved", "dateClosed", "projectAmount", "federalShareObligated")
PAGE_SIZE = 5000
MAX_PAGES = 10
SVI_MIN = 0.50   # application-defined screening rule (same thresholds as analysis.py), not a federal standard
RISK_MIN = 3.0   # hazard score on the 0 to 5 scale
_ENDED = ("closed", "complet", "withdraw", "void", "denied", "cancel")
_DATA_RE = re.compile(r"const DATA = (\{.*?\});\n", re.S)
_MARK_RE = re.compile(r"/\*DATA\*/.*?/\*END\*/", re.S)


def norm_county(name) -> str:
    """Key for matching county names across sources: 'De Kalb', 'DEKALB' and 'DeKalb (County)' all match."""
    s = re.sub(r"\(.*?\)", "", str(name or "")).lower()
    s = re.sub(r"\bcounty\b", "", s)
    s = re.sub(r"\bsaint\b", "st", s)
    return re.sub(r"[^a-z]", "", s)


def is_open(rec: dict) -> bool:
    """A project counts as open when FEMA shows no close date and its status is not an ended one."""
    if rec.get("dateClosed"):
        return False
    status = str(rec.get("status") or "").lower()
    return not any(word in status for word in _ENDED)


def project_type(text) -> str:
    """'601.1: Generators' -> 'Generators'. FEMA prefixes each type with a numeric code."""
    s = str(text or "").strip()
    parts = [re.sub(r"^\s*\d+(\.\d+)?[a-zA-Z]?\s*:\s*", "", p).strip() for p in s.split(";")]
    seen = [p for i, p in enumerate(parts) if p and p not in parts[:i]]
    return "; ".join(seen) or "Type not stated"


def _money(v) -> float:
    try:
        return max(0.0, float(v))
    except (TypeError, ValueError):
        return 0.0


def counties_of(rec: dict) -> list:
    """County keys a project belongs to. Uses the project county list when present, else the single county."""
    raw = rec.get("projectCounties") or rec.get("county") or ""
    keys = [norm_county(p) for p in re.split(r"[;,/]", str(raw))]
    return [k for i, k in enumerate(keys) if k and k not in keys[:i]]


def clean(rec: dict) -> dict:
    """The fields the page shows, with safe types."""
    fy = rec.get("programFy")
    return {"id": str(rec.get("projectIdentifier") or ""), "program": str(rec.get("programArea") or "").strip() or "Program not stated",
            "fy": int(fy) if str(fy or "").isdigit() else None, "type": project_type(rec.get("projectType")),
            "status": str(rec.get("status") or "").strip() or "Status not stated", "who": str(rec.get("subrecipient") or "").strip(),
            "amount": _money(rec.get("projectAmount")), "fed": _money(rec.get("federalShareObligated")), "open": is_open(rec)}


def group_projects(records: list, county_names: list) -> dict:
    """Return {"by": {county name: [project, ...]}, "statewide": [...], "unmatched": n} for Illinois counties."""
    lookup = {norm_county(n): n for n in county_names}
    by, statewide, unmatched = {}, [], 0
    for rec in records:
        proj, keys = clean(rec), counties_of(rec)
        hits = [lookup[k] for k in keys if k in lookup]
        if hits:
            for name in hits:
                by.setdefault(name, []).append(proj)
        elif any(k.startswith("statewide") for k in keys) or not keys:
            statewide.append(proj)
        else:
            unmatched += 1
    order = lambda p: (not p["open"], -(p["fy"] or 0), p["type"])  # noqa: E731
    for lst in by.values():
        lst.sort(key=order)
    statewide.sort(key=order)
    return {"by": by, "statewide": statewide, "unmatched": unmatched}


def query_url(skip: int = 0, state: str = "Illinois") -> str:
    q = {"$filter": "state eq '%s'" % state, "$select": ",".join(FIELDS), "$top": str(PAGE_SIZE), "$skip": str(skip)}
    return API + "?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote, safe="$',")


def fetch_projects(opener=None, state: str = "Illinois") -> dict:
    """Download every Illinois record. Returns {"records": [...], "rundate": str}. Raises OSError/ValueError on failure."""
    opener = opener or (lambda url: urllib.request.urlopen(  # noqa: S310 - fixed https URL
        urllib.request.Request(url, headers={"User-Agent": "CivicSignal/1.0", "Accept": "application/json"}), timeout=25).read())
    records, rundate = [], ""
    for page in range(MAX_PAGES):
        body = json.loads(opener(query_url(page * PAGE_SIZE, state)))
        rows = body.get(ENTITY)
        if not isinstance(rows, list):
            raise ValueError("unexpected response from FEMA")
        rundate = rundate or str((body.get("metadata") or {}).get("rundate") or "")
        records.extend(r for r in rows if isinstance(r, dict) and str(r.get("state") or "").lower() == state.lower())
        if len(rows) < PAGE_SIZE:
            break
    return {"records": records, "rundate": rundate}


def load_counties(site_html: str) -> dict:
    """Return {"vb": [w, h], "counties": [...]} from the explorer page's embedded dataset."""
    m = _DATA_RE.search(site_html)
    if not m:
        raise ValueError("county dataset not found in site.html")
    d = json.loads(m.group(1))
    counties = [{"n": c["n"], "r": c.get("r", ""), "svi": float(c["svi"]),
                 "top": max(float(v) for v in c["h"].values()), "d": c["d"]} for c in d["counties"]]
    return {"vb": d["vb"], "counties": counties}


def build_payload(site_html: str, fetched) -> dict:
    """fetched is the result of fetch_projects(), or None when FEMA could not be reached."""
    data = load_counties(site_html)
    data["svi_min"], data["risk_min"], data["source"] = SVI_MIN, RISK_MIN, DATASET_PAGE
    if fetched is None:
        data.update(ok=False, by={}, statewide=[], unmatched=0, total=0, rundate="")
    else:
        g = group_projects(fetched["records"], [c["n"] for c in data["counties"]])
        data.update(ok=True, by=g["by"], statewide=g["statewide"], unmatched=g["unmatched"],
                    total=len(fetched["records"]), rundate=fetched.get("rundate", "")[:10])
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

    @st.cache_data(ttl=86400, show_spinner="Loading FEMA project records…")
    def _cached():
        return fetch_projects()

    try:
        fetched = _cached()
    except Exception:  # noqa: BLE001 - any network or format failure: say so, never show placeholder projects
        fetched = None
    st.caption("FEMA-funded hazard mitigation projects in Illinois, by county. Project records are FEMA's public data; "
               "vulnerability scores are sample data.")
    if fetched is None:
        st.warning("FEMA's public project data could not be loaded just now, so no projects are shown. The map still works.")
        if st.button("Try again"):
            _cached.clear()
            st.rerun()
    page = build_page(tpl.read_text(encoding="utf-8"), build_payload(site.read_text(encoding="utf-8"), fetched))
    # The page sizes its own frame to its full height, so only the app scrolls; scrolling=True is a fallback.
    components.html(page, height=1100, scrolling=True)
