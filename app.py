import os
import json
from pathlib import Path

# --- Folder-layout safety net -------------------------------------------------
# If the files were uploaded flat (no data/ or assets/ folders), build the folders at startup.
def _ensure_layout():
    import shutil
    root = Path(__file__).resolve().parent
    os.chdir(root)
    for folder, exts in (("data", (".csv", ".geojson")), ("assets", (".png", ".svg"))):
        target = root / folder
        try:
            target.mkdir(exist_ok=True)
            for f in root.iterdir():
                if f.is_file() and f.suffix.lower() in exts and not (target / f.name).exists():
                    shutil.copy2(f, target / f.name)
        except Exception:
            pass
_ensure_layout()
_D = "data/" if Path("data/county_risk.csv").exists() else ""   # works whether or not the data/ folder exists
from dotenv import load_dotenv
import pandas as pd
import streamlit as st
import plotly.express as px

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)
from security_utils import (
    validate_csv, apply_risk_csv_rules, apply_capacity_csv_rules,
    check_file_size,
    DRAFT_LABEL, PDF_REVIEW_NOTE,
    PROTOTYPE_WARNING, GOVERNANCE_NOTE,
    MAX_CSV_MB, MAX_PDF_MB, MAX_PDF_CHARS, MAX_PDF_PAGES,
    sanitize_text,
)
from hazard_taxonomy import normalize_hazard_column
from analysis import (
    INTERPRETATION as _INTERPRETATION,
    rule_based_risk_analysis as _rule_based_risk_analysis,
)
from pdf_tasks import run_with_timeout, TaskTimeout, DEFAULT_TIMEOUT_S
from safe_stats import safe_mean, format_kpi, safe_pivot, top_per_group, count_by, has_columns
import audit_store
import config as _config
import identity as _ident
from i18n import LANGUAGES, normalize_lang, t as _t
from palette import LOW as GREEN, LIGHT_LOW as LIGHT_GREEN, LIGHT_HIGH as LIGHT_RED, HIGH as RED, RISK_SCALE as RG_SCALE

# ----------------------------------------------------
# Scope and palette
# ----------------------------------------------------
# Chicago metropolitan area: Cook plus the six collar counties.
# Configurable with ALLOWED_COUNTIES (comma-separated, or ALL). Unset keeps this Chicago-area default.
CHICAGO_COUNTIES = _config.allowed_counties() or []
ALLOWED_COUNTIES = _config.allowed_counties()
TENANT = _config.tenant_id()
CHICAGO_CENTER = {"lat": 41.85, "lon": -88.0}

# Colour-vision-safe palette (Phase 1.7): blue = low, orange = high, neutral middle. The names GREEN/RED are kept
# so existing chart code works, but the colours come from palette.py and every chart also carries text labels.

# ----------------------------------------------------
# Page setup
# ----------------------------------------------------

from pathlib import Path as _P
try:
    from PIL import Image as _Img
    _FAVICON = _Img.open(_P(__file__).parent / ("assets" if (_P(__file__).parent / "assets" / "favicon.png").exists() else ".") / "favicon.png")
except Exception:
    _FAVICON = "📍"

st.set_page_config(
    page_title="Chicago-Area Hazard Risk Dashboard",
    layout="wide",
    page_icon=_FAVICON
)

st.markdown("""
<style>
/* Light palette: pale sky-blue page, near-black text, one blue accent */
.stApp { background: linear-gradient(180deg, #dcebf8 0%, #eef5fb 38%, #f7fafd 100%); color: #1d1d1f; }
.stApp, .stApp p, .stApp li, .stApp label, .stApp span { color: #1d1d1f; }
.stApp h1, .stApp h2, .stApp h3, .stApp h4 { color: #1d1d1f !important; font-weight: 700; letter-spacing: -0.01em; }
.stApp a { color: #0066cc !important; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color: #515154 !important; }
[data-testid="stWidgetLabel"] p, [data-testid="stWidgetLabel"] label { color: #1d1d1f !important; font-weight: 600; }

/* Sidebar */
[data-testid="stSidebar"] { background: #eaf2fa; border-right: 1px solid #d2dff0; }
[data-testid="stSidebar"] * { color: #1d1d1f !important; }
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 { color: #0071e3 !important; }

/* Title banner */
.dashboard-title { text-align: center; padding: 1.2rem 1rem 0.4rem; margin-bottom: 0.6rem; }
.dashboard-title h1 { color: #1d1d1f !important; font-size: 2.3rem; margin: 0; }
.dashboard-title p { color: #515154 !important; margin: 0.4rem 0 0; font-size: 1rem; }

/* KPI cards */
[data-testid="stMetric"] { background: #ffffff; border: 1px solid #e5e5ea; border-radius: 16px; padding: 0.9rem 1.1rem; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] p { color: #515154 !important; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.05em; }
[data-testid="stMetricValue"] { color: #1d1d1f !important; font-weight: 700; }

/* Buttons: blue pills */
.stButton > button, .stDownloadButton > button { background: #0071e3; color: #ffffff !important; border: 1px solid #0071e3; border-radius: 980px; font-weight: 600; padding: 0.45rem 1.3rem; }
.stButton > button:hover, .stDownloadButton > button:hover { background: #0077ed; color: #ffffff !important; }
.stButton > button:disabled { background: #e5e5ea; border-color: #e5e5ea; color: #6b6b70 !important; }

/* Tabs */
[data-testid="stTabs"] [role="tab"] { color: #515154 !important; font-weight: 600; border-bottom: 2px solid transparent; }
[data-testid="stTabs"] [role="tab"][aria-selected="true"] { color: #0071e3 !important; border-bottom-color: #0071e3; }

/* Inputs: white fields, dark text */
[data-testid="stTextArea"] textarea, [data-testid="stTextInput"] input, [data-testid="stNumberInput"] input, [data-testid="stChatInput"] textarea {
    background: #ffffff !important; color: #1d1d1f !important; -webkit-text-fill-color: #1d1d1f !important; caret-color: #1d1d1f; border-radius: 10px;
}
[data-testid="stTextArea"] > div, [data-testid="stTextInput"] > div > div, [data-testid="stNumberInput"] > div > div { background: #ffffff !important; border: 1px solid #d2d2d7 !important; border-radius: 10px !important; }
[data-testid="stSelectbox"] div[data-baseweb="select"] > div, [data-testid="stMultiSelect"] div[data-baseweb="select"] > div { background: #ffffff !important; border: 1px solid #d2d2d7 !important; border-radius: 10px; }
[data-testid="stSelectbox"] div[data-baseweb="select"] span, [data-testid="stSelectbox"] div[data-baseweb="select"] div { color: #1d1d1f !important; }

/* Dataframes, expanders, uploaders, chat */
[data-testid="stDataFrame"] { border-radius: 12px; overflow: hidden; border: 1px solid #e5e5ea; }
[data-testid="stExpander"], [data-testid="stVerticalBlockBorderWrapper"] { background: #ffffff; border: 1px solid #e5e5ea; border-radius: 16px; }
[data-testid="stFileUploader"] { background: #ffffff; border: 2px dashed #b9cbe3; border-radius: 12px; }
[data-testid="stFileUploader"] section, [data-testid="stFileUploaderDropzone"] { background: #ffffff !important; }
[data-testid="stChatMessage"] { background: #ffffff !important; border: 1px solid #e5e5ea; border-radius: 14px; color: #1d1d1f !important; }
[data-testid="stChatMessage"] p, [data-testid="stChatMessage"] li, [data-testid="stChatMessage"] span { color: #1d1d1f !important; }
[data-testid="stProgressBar"] > div { background: #e5e5ea !important; }
[data-testid="stProgressBar"] > div > div { background: #0071e3 !important; }
[data-testid="stSpinner"] { color: #0071e3 !important; }
hr { border-color: #d2d2d7 !important; }
.stApp pre, .stApp code { background: #f5f5f7 !important; color: #1d1d1f !important; }

#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stHeader"], [data-testid="stStatusWidget"] { display: none !important; }
.stApp [class*="st-key-workspace"] { position: sticky; top: 0; z-index: 999; background: linear-gradient(180deg, #dcebf8 70%, rgba(220,235,248,0)); padding: 0.6rem 0 0.8rem; margin-top: -0.6rem; }
/* Layout polish: wider canvas, larger type, tidy navigation and cards */
html { font-size: 17px; }
.block-container { max-width: 1480px !important; padding: 1rem 2.2rem 3rem !important; }
.stApp [data-testid="stRadio"] { display: flex; justify-content: center; margin: 0.2rem 0 0.4rem; }
.stApp [data-testid="stRadio"] > label { display: none; }
.stApp [data-testid="stRadio"] [role="radiogroup"] { background: #ffffff; border: 1px solid #d6e3f2; border-radius: 980px; padding: 5px; gap: 4px; box-shadow: 0 1px 4px rgba(0,60,120,0.08); }
.stApp [data-testid="stRadio"] [role="radiogroup"] > label { margin: 0; padding: 0.5rem 1.3rem; border-radius: 980px; cursor: pointer; }
.stApp [data-testid="stRadio"] [role="radiogroup"] > label > div:first-child { display: none; }
.stApp [data-testid="stRadio"] [role="radiogroup"] > label p { font-weight: 600; font-size: 0.95rem; color: #515154 !important; }
.stApp [data-testid="stRadio"] [role="radiogroup"] > label:has(input:checked) { background: #0071e3; }
.stApp [data-testid="stRadio"] [role="radiogroup"] > label:has(input:checked) p { color: #ffffff !important; }
.stApp [data-testid="stMetric"] { min-height: 128px; display: flex; flex-direction: column; justify-content: center; }
.stApp [data-testid="stMetricValue"] { font-size: 2rem; }
.stApp [data-testid="stTabs"] [role="tab"] { font-size: 1rem; padding: 0.6rem 1.1rem; }
.stApp [data-testid="stHorizontalBlock"] { gap: 1.2rem; }
.stApp h2, .stApp h3 { margin-top: 0.2rem; }
.section-accent { height: 3px; background: #0071e3; border-radius: 2px; margin: 0.4rem 0 1rem; }
</style>
""", unsafe_allow_html=True)

# ---- Premium look: branded header, glass nav, animated cards ----
import base64 as _b64
def _logo_uri():
    for _c in (_P(__file__).parent / "assets" / "logo.png", _P(__file__).parent / "logo.png"):
        try:
            return "data:image/png;base64," + _b64.b64encode(_c.read_bytes()).decode()
        except Exception:
            pass
    return ""
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,800&family=Public+Sans:wght@400;500;600;700&display=swap');
html, body, .stApp, .stApp p, .stApp li, .stApp label, .stApp span, .stApp input, .stApp textarea { font-family: 'Public Sans', 'Segoe UI', sans-serif; }
/* Keep Streamlit's icon font: the span rule above must not replace it (fixes '_arrow_right' text) */
.stApp [data-testid="stIconMaterial"], .stApp span[class*="material"] { font-family: 'Material Symbols Rounded', 'Material Icons' !important; }
.stApp h1, .stApp h2, .stApp h3 { font-family: 'Bricolage Grotesque', 'Segoe UI', sans-serif !important; letter-spacing: -0.02em; }
.stApp { background: radial-gradient(900px 520px at 85% -5%, rgba(10,98,208,0.16), transparent 60%), radial-gradient(700px 420px at 0% 30%, rgba(238,123,59,0.10), transparent 60%), linear-gradient(180deg, #e3effb 0%, #f1f6fc 40%, #f8fbfe 100%) !important; }
.cs-top { position: relative; overflow: hidden; border-radius: 22px; padding: 1.5rem 1.8rem; margin: 0.2rem 0 0.9rem; color: #eaf1fa;
  background: radial-gradient(600px 260px at 90% 0%, rgba(90,166,255,0.45), transparent 65%), radial-gradient(500px 240px at 0% 100%, rgba(207,63,44,0.28), transparent 65%), #0b1626;
  box-shadow: 0 22px 60px rgba(11,22,38,0.28); display: flex; align-items: center; gap: 1.2rem; flex-wrap: wrap; animation: csfade .7s ease both; }
.cs-top::after { content: ""; position: absolute; inset: 0; background-image: linear-gradient(rgba(255,255,255,.05) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.05) 1px, transparent 1px); background-size: 38px 38px; -webkit-mask-image: linear-gradient(90deg, transparent 30%, #000); mask-image: linear-gradient(90deg, transparent 30%, #000); pointer-events: none; }
.cs-top > * { position: relative; z-index: 1; }
.cs-top img { width: 58px; height: 58px; border-radius: 50%; background: #fff; padding: 5px; box-shadow: 0 0 0 4px rgba(90,166,255,0.35); }
.stApp .cs-top h1 { margin: 0 !important; color: #ffffff !important; -webkit-text-fill-color: #ffffff; font-size: 2rem !important; line-height: 1.05; }
.stApp .cs-top h1 em { -webkit-text-fill-color: transparent; font-style: normal; background: linear-gradient(100deg, #7db8ff, #ffb26b); -webkit-background-clip: text; background-clip: text; color: transparent; }
.stApp .cs-top p { margin: 0.25rem 0 0 !important; color: #b4c6dc !important; font-size: 0.98rem; }
.cs-pills { margin-left: auto; display: flex; gap: 0.5rem; flex-wrap: wrap; }
.stApp .cs-pills span { color: #eaf1fa !important; border: 1px solid rgba(255,255,255,0.28); background: rgba(255,255,255,0.08); border-radius: 99px; padding: 0.35rem 0.85rem; font-size: 0.82rem; font-weight: 600; backdrop-filter: blur(6px); }
.cs-pills span::before { content: ""; display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: #ee7b3b; margin-right: 0.45rem; animation: cspulse 2.2s infinite; }
@keyframes cspulse { 0% { box-shadow: 0 0 0 0 rgba(238,123,59,.7); } 70% { box-shadow: 0 0 0 9px rgba(238,123,59,0); } 100% { box-shadow: 0 0 0 0 rgba(238,123,59,0); } }
@keyframes csfade { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: none; } }
.stApp [data-testid="stRadio"] [role="radiogroup"] { background: rgba(255,255,255,0.78); backdrop-filter: blur(12px); border: 1px solid #cfe0f3; box-shadow: 0 10px 30px rgba(10,60,120,0.12); }
.stApp [data-testid="stRadio"] [role="radiogroup"] > label { transition: background .2s, transform .15s; }
.stApp [data-testid="stRadio"] [role="radiogroup"] > label:hover { background: rgba(10,98,208,0.09); transform: translateY(-1px); }
.stApp [data-testid="stRadio"] [role="radiogroup"] > label:has(input:checked) { background: linear-gradient(135deg, #0a62d0, #3a8bff); box-shadow: 0 6px 18px rgba(10,98,208,0.4); }
.stApp [data-testid="stMetric"] { border: 1px solid #dbe7f5; border-radius: 18px; background: linear-gradient(180deg, #ffffff, #f4f9ff); transition: transform .25s, box-shadow .25s; animation: csfade .6s ease both; }
.stApp [data-testid="stMetric"]:hover { transform: translateY(-4px); box-shadow: 0 18px 40px rgba(10,60,120,0.16); }
.stApp [data-testid="stMetricValue"] { background: linear-gradient(100deg, #0a3d8f, #0a62d0); -webkit-background-clip: text; background-clip: text; color: transparent !important; }
.stApp [data-testid="stExpander"], .stApp [data-testid="stVerticalBlockBorderWrapper"] { border-color: #d6e4f4; box-shadow: 0 8px 26px rgba(10,60,120,0.07); transition: box-shadow .25s, transform .25s; }
.stApp [data-testid="stVerticalBlockBorderWrapper"]:hover { box-shadow: 0 16px 40px rgba(10,60,120,0.14); }
.stApp .stButton > button { background: linear-gradient(135deg, #0a62d0, #3a8bff); border: 0; box-shadow: 0 8px 20px rgba(10,98,208,0.32); transition: transform .15s, box-shadow .2s, filter .2s; }
.stApp .stButton > button:hover { transform: translateY(-2px); box-shadow: 0 14px 28px rgba(10,98,208,0.42); filter: brightness(1.05); }
.stApp [data-testid="stPlotlyChart"], .stApp [data-testid="stDeckGlJsonChart"] { background: #ffffff; border: 1px solid #dbe7f5; border-radius: 18px; padding: 8px; box-shadow: 0 10px 30px rgba(10,60,120,0.09); }
.stApp [data-testid="stChatMessage"] { box-shadow: 0 6px 18px rgba(10,60,120,0.07); }
.stApp .section-accent { background: linear-gradient(90deg, #0a62d0, #ee7b3b); height: 4px; }
@media (max-width: 700px) { .cs-pills { margin-left: 0; } .cs-top h1 { font-size: 1.5rem !important; } }
@media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }
</style>
""", unsafe_allow_html=True)
st.markdown(
    '<div class="cs-top">' + ('<img alt="" src="' + _logo_uri() + '">' if _logo_uri() else '') +
    '<div><h1>Civic<em>Signal</em></h1><p>Hazard-mitigation decision support for Illinois and the Chicago area</p></div>'
    '<div class="cs-pills"><span>A named official decides</span><span>Sample data</span></div></div>',
    unsafe_allow_html=True)

# ----------------------------------------------------
# Identity, language, storage (Phase 1)
# ----------------------------------------------------
try:
    _headers = dict(st.context.headers)
except Exception:  # noqa: BLE001 - older Streamlit or no request context: treat as anonymous
    _headers = {}
IDENTITY = _ident.resolve_identity(_headers)
BACKEND = st.cache_resource(audit_store.get_backend)()
LANG = normalize_lang(st.session_state.get("lang", "en"))
IS_VERIFIED = bool(BACKEND.get_setting(TENANT, "verified_data", False))

_LEGAL = [("ui.footer.terms", "TERMS.md"), ("ui.footer.privacy", "PRIVACY.md"), ("ui.footer.disclaimer", "DISCLAIMER.md"),
          ("ui.footer.sources", "DATA_SOURCES.md"), ("ui.footer.accessibility", "ACCESSIBILITY.md")]


def _banner() -> None:
    """Sample-data banner: always shown unless an administrator confirmed verified tenant data."""
    if IS_VERIFIED:
        st.success(_t("ui.verified_banner", LANG))
    else:
        st.warning(_t("ui.sample_banner", LANG))


def _footer() -> None:
    """Footer with links to the legal and trust pages (shown inline so no external hosting is needed)."""
    st.divider()
    st.caption(_t("ui.footer.note", LANG))
    cols = st.columns(len(_LEGAL))
    for col, (key, fname) in zip(cols, _LEGAL):
        with col.popover(_t(key, LANG)):
            f = Path(__file__).resolve().parent / fname
            st.markdown(f.read_text(encoding="utf-8") if f.exists() else f"{fname} is not installed.")


# ----------------------------------------------------
# Open access
# ----------------------------------------------------
# The dashboard needs no sign-in. Admin tools (data uploads, PDF summarizer, complaint detail) are the
# "Internal View" and need a signed-in identity with the admin role (Easy Auth, or ALLOWED_EMAILS in local dev).

# ----------------------------------------------------
# Workspace switch: CivicSignal prioritization or the hazard dashboard
# ----------------------------------------------------
_workspace = st.radio(
    "Workspace",
    ["Illinois SVI website", "CivicSignal prioritization", "Hazard dashboard", "Cooling centers & shelters"],
    horizontal=True,
    key="workspace",
)
if _workspace == "CivicSignal prioritization":
    import civicsignal_ui
    civicsignal_ui.render(IDENTITY, BACKEND, TENANT, sample_data=not IS_VERIFIED)
    _footer()
    st.stop()
if _workspace == "Illinois SVI website":
    import website_ui
    _banner()
    website_ui.render()
    _footer()
    st.stop()
if _workspace == "Cooling centers & shelters":
    import heat_ui
    _banner()
    heat_ui.render(LANG)
    _footer()
    st.stop()

st.markdown("""
<div class="dashboard-title">
  <h1>Chicago-Area Hazard Risk Dashboard</h1>
  <p>Cook, DuPage, Kane, Kendall, Lake, McHenry and Will counties · Sample data · Decision support</p>
</div>
""", unsafe_allow_html=True)

# Prototype / data-freshness warning (always visible)
_banner()
st.warning(PROTOTYPE_WARNING)


# Data source label — updated when official data is loaded
_data_source = "Built-in sample data"
_using_sample = True

# ----------------------------------------------------
# About panel
# ----------------------------------------------------

st.markdown('<div class="section-accent"></div>', unsafe_allow_html=True)

# ----------------------------------------------------
# Helper functions
# ----------------------------------------------------

def clean_county_name(name):
    """Clean county names so 'Cook County' becomes 'Cook'."""
    if pd.isna(name):
        return None

    name = str(name)
    name = name.replace(" County", "")
    name = name.replace(" county", "")
    name = name.strip()

    return name


def load_county_geojson(path=_D + "illinois_counties.geojson"):
    """Load Illinois county GeoJSON safely (parsed once per file version via st.cache_resource)."""
    if not os.path.exists(path):
        return None
    return _parse_county_geojson(path, os.path.getmtime(path))


@st.cache_resource(show_spinner=False)
def _parse_county_geojson(path, mtime):
    """Cached parser: the mtime argument invalidates the cache when the file changes."""

    try:
        with open(path, "r", encoding="utf-8") as file:
            content = file.read().strip()

        if not content:
            st.warning("GeoJSON file is empty. Replace it with a valid Illinois county GeoJSON.")
            return None

        geojson_data = json.loads(content)

    except json.JSONDecodeError:
        st.error(
            "The GeoJSON file is not valid JSON. You may have downloaded an HTML page, ZIP file, "
            "or blank file instead of a real GeoJSON."
        )
        return None

    for feature in geojson_data.get("features", []):
        props = feature.get("properties", {})

        possible_fields = [
            "NAME",
            "Name",
            "name",
            "COUNTY",
            "COUNTY_NAME",
            "COUNTY_NAM",
            "NAMELSAD",
            "CountyName"
        ]

        county_name = None

        for field in possible_fields:
            if field in props:
                county_name = props[field]
                break

        props["county_clean"] = clean_county_name(county_name)

    return geojson_data


def add_coordinates(df):
    """Fallback point-map coordinates for selected Illinois counties."""
    county_coordinates = {
        "Cook": {"latitude": 41.7377, "longitude": -87.6976},
        "DuPage": {"latitude": 41.8244, "longitude": -88.0901},
        "Will": {"latitude": 41.5055, "longitude": -88.0901},
        "Sangamon": {"latitude": 39.7817, "longitude": -89.6501},
        "Jackson": {"latitude": 37.7861, "longitude": -89.3812},
        "Alexander": {"latitude": 37.1917, "longitude": -89.3376},
    }

    df = df.copy()

    if "latitude" not in df.columns:
        df["latitude"] = df["county"].map(
            lambda x: county_coordinates.get(str(x), {}).get("latitude")
        )

    if "longitude" not in df.columns:
        df["longitude"] = df["county"].map(
            lambda x: county_coordinates.get(str(x), {}).get("longitude")
        )

    return df


# ----------------------------------------------------
# Built-in sample data
# ----------------------------------------------------

sample_risk_df = pd.DataFrame({
    "county": [
        "Cook", "DuPage", "Will", "Sangamon", "Jackson", "Alexander",
        "Cook", "DuPage", "Will", "Sangamon", "Jackson", "Alexander"
    ],
    "region": [
        "Northeast", "Northeast", "Northeast", "Central", "Southern", "Southern",
        "Northeast", "Northeast", "Northeast", "Central", "Southern", "Southern"
    ],
    "hazard": [
        "Flooding", "Flooding", "Flooding", "Flooding", "Flooding", "Flooding",
        "Heat Wave", "Heat Wave", "Heat Wave", "Heat Wave", "Heat Wave", "Heat Wave"
    ],
    "risk_score": [
        4.8, 3.9, 4.1, 3.4, 4.3, 4.6,
        4.7, 3.8, 4.0, 3.9, 4.1, 4.4
    ],
    "risk_level": [
        "Very High", "High", "High", "Medium", "High", "Very High",
        "Very High", "High", "High", "High", "High", "Very High"
    ],
    "svi_score": [
        0.82, 0.45, 0.51, 0.48, 0.71, 0.88,
        0.82, 0.45, 0.51, 0.48, 0.71, 0.88
    ]
})

sample_actions_df = pd.DataFrame({
    "hazard": [
        "Flooding", "Flooding", "Flooding",
        "Heat Wave", "Heat Wave"
    ],
    "action": [
        "Stormwater upgrades",
        "Buyouts and elevation",
        "Nature-based floodplain restoration",
        "Cooling center coordination",
        "Heat preparedness outreach"
    ],
    "lead_agency": [
        "IDNR / Local",
        "IEMA-OHS / Local",
        "IDNR",
        "IEMA-OHS / Local",
        "IDPH"
    ],
    "priority": [
        "High", "High", "Medium", "High", "High"
    ],
    "status": [
        "Planning", "In Progress", "Planning", "Planning", "Not Started"
    ],
    "funding": [
        "BRIC / HMGP",
        "HMGP / FMA",
        "BRIC / State",
        "State / Local",
        "Public Health Funding"
    ]
})

# ----------------------------------------------------
# Load CSV files
# ----------------------------------------------------

risk_path = _D + "county_risk.csv"
actions_path = _D + "mitigation_actions.csv"

if os.path.exists(risk_path):
    risk_df = pd.read_csv(risk_path)
else:
    risk_df = sample_risk_df

if os.path.exists(actions_path):
    actions_df = pd.read_csv(actions_path)
else:
    actions_df = sample_actions_df

risk_df = add_coordinates(normalize_hazard_column(risk_df))
actions_df = normalize_hazard_column(actions_df)

# ----------------------------------------------------
# Sidebar: data upload
# ----------------------------------------------------

# ── View mode (controls upload visibility and complaint detail) ──────
# Public View  : read-only display of pre-loaded data, no uploads, no internal tools
# Internal View: full admin access — uploads, local analysis, complaint detail, PDF summarizer
st.sidebar.selectbox(_t("ui.language", LANG), list(LANGUAGES), index=list(LANGUAGES).index(LANG),
                     format_func=LANGUAGES.get, key="lang")
st.sidebar.header("Access Level")
IS_INTERNAL = _ident.can(IDENTITY, "upload_data")
SHOW_ALL_DATA = False
if IDENTITY:
    st.sidebar.caption(f"Signed in as {IDENTITY.email} · roles: {', '.join(sorted(IDENTITY.roles))}")
if IS_INTERNAL:
    st.sidebar.success("Internal View — admin access")
    if _ident.can(IDENTITY, "toggle_scope"):
        SHOW_ALL_DATA = st.sidebar.toggle("Show all uploaded data", value=False,
                                          help="Turns off the county scope for the dashboard. Admin only. Default scope: " + _config.scope_label(ALLOWED_COUNTIES))
    if _ident.can(IDENTITY, "confirm_verified_data"):
        _ver = st.sidebar.toggle("Verified tenant data is loaded", value=IS_VERIFIED,
                                 help="Hides the sample-data banner. Turn on only after the data has been checked against its source.")
        if _ver != IS_VERIFIED:
            BACKEND.set_setting(TENANT, "verified_data", _ver)
            audit_store.append_event(BACKEND, TENANT, IDENTITY.actor, "settings.verified_data", "tenant", TENANT, {"verified": _ver})
            st.rerun()
else:
    st.sidebar.info(_t("ui.public_info", LANG) + ("" if IDENTITY else ". Sign in for admin tools."))
SCOPE_COUNTIES = None if SHOW_ALL_DATA else ALLOWED_COUNTIES


st.sidebar.divider()
st.sidebar.header("1. Add / Update Data")

# ── All uploaders are admin-only (Internal View) ─────────────────────
uploaded_risk_file       = None
uploaded_actions_file    = None
uploaded_geojson_file    = None
uploaded_capacity_file   = None
uploaded_complaints_file = None

if IS_INTERNAL:
    uploaded_risk_file = st.sidebar.file_uploader(
        "Upload county risk CSV", type=["csv"]
    )
    uploaded_actions_file = st.sidebar.file_uploader(
        "Upload mitigation actions CSV", type=["csv"]
    )
    uploaded_geojson_file = st.sidebar.file_uploader(
        "Upload Illinois counties GeoJSON", type=["geojson", "json"]
    )
    st.sidebar.header("3. Resource Capacity Data")
    uploaded_capacity_file = st.sidebar.file_uploader(
        "Upload county capacity CSV", type=["csv"], key="capacity_upload"
    )
    uploaded_complaints_file = st.sidebar.file_uploader(
        "Upload complaints CSV", type=["csv"], key="complaints_upload"
    )
    with st.sidebar.expander("Required county risk columns"):
        st.write("county, region, hazard, risk_score, risk_level, svi_score")
    with st.sidebar.expander("Required mitigation action columns"):
        st.write("hazard, action, lead_agency, priority, status, funding")
    with st.sidebar.expander("Required capacity columns"):
        st.write("county, region, hazard, mitigation_effort, status, people_affected, budget_usd, amount_spent_usd, lead_agency, start_date, target_date")
    with st.sidebar.expander("Required complaints columns"):
        st.write("complaint_id, county, hazard, category, description, date_filed, priority, status, date_resolved")
else:
    st.sidebar.caption("Data uploads are available in Internal View only.")

# ── Data download buttons (always visible) ───────────────────────────
st.sidebar.divider()
st.sidebar.markdown("**Download Data Files**")
_dl_files = {
    "county_risk.csv":     _D + "county_risk.csv",
    "county_capacity.csv": _D + "county_capacity.csv",
    "complaints.csv":      _D + "complaints.csv",
}
for _label, _path in _dl_files.items():
    if os.path.exists(_path):
        with open(_path, "rb") as _fh:
            st.sidebar.download_button(
                label=f"⬇ {_label}",
                data=_fh.read(),
                file_name=_label,
                mime="text/csv",
                key=f"dl_{_label}",
            )

# ── Validated CSV ingestion ───────────────────────────────────────────
if uploaded_risk_file is not None:
    if check_file_size(uploaded_risk_file, MAX_CSV_MB):
        _df = pd.read_csv(uploaded_risk_file)
        _ok, _err = validate_csv(_df, "county_risk")
        if _ok:
            _df = normalize_hazard_column(apply_risk_csv_rules(_df))
            risk_df = add_coordinates(_df)
            st.sidebar.success("County risk data uploaded and validated.")
        else:
            st.sidebar.error(f"County risk CSV rejected: {_err}")

if uploaded_actions_file is not None:
    if check_file_size(uploaded_actions_file, MAX_CSV_MB):
        _df = pd.read_csv(uploaded_actions_file)
        _ok, _err = validate_csv(_df, "mitigation_actions")
        if _ok:
            actions_df = normalize_hazard_column(_df)
            st.sidebar.success("Mitigation actions data uploaded and validated.")
        else:
            st.sidebar.error(f"Mitigation actions CSV rejected: {_err}")

# ----------------------------------------------------
# Sidebar: filters
# ----------------------------------------------------

st.sidebar.header("2. Dashboard Filters")

_hazards = sorted(risk_df["hazard"].dropna().unique())
selected_hazard = st.sidebar.selectbox(
    "Select Hazard",
    _hazards,
    index=_hazards.index("Flood") if "Flood" in _hazards else 0,
    help="All hazards are compared in the Hazard Overview below the key numbers.",
)

selected_regions = st.sidebar.multiselect(
    "Select Region",
    sorted(risk_df["region"].dropna().unique()),
    default=sorted(risk_df["region"].dropna().unique())
)

# ----------------------------------------------------
# Scope everything to the Chicago-area counties
# ----------------------------------------------------
risk_all = risk_df.copy()   # unfiltered, used by the Hazard Assistant (Phase 0.5)
risk_df = _config.scope_frame(risk_df, SCOPE_COUNTIES)

# ----------------------------------------------------
# Create filtered data
# ----------------------------------------------------

filtered_risk = risk_df[
    (risk_df["hazard"] == selected_hazard) &
    (risk_df["region"].isin(selected_regions))
].copy()

filtered_actions = actions_df[
    actions_df["hazard"] == selected_hazard
].copy()

# Data-source label — update flag when official data is loaded via upload
if uploaded_risk_file is not None:
    _data_source = f"Uploaded: {uploaded_risk_file.name}"
    _using_sample = False
# Display data-freshness notice
if _using_sample:
    st.info(f"📂 Data source: **{_data_source}** — {PROTOTYPE_WARNING}")
else:
    st.success(f"📂 Data source: **{_data_source}**")

# ----------------------------------------------------
# KPI cards
# ----------------------------------------------------

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Counties Shown", len(filtered_risk))

with col2:
    high_counties = filtered_risk[
        filtered_risk["risk_level"].isin(["High", "Very High"])
    ]
    st.metric("High / Very High Risk", len(high_counties))

with col3:
    st.metric("Average Risk Score", format_kpi(safe_mean(filtered_risk, "risk_score")))

with col4:
    st.metric("Average SVI Score", format_kpi(safe_mean(filtered_risk, "svi_score")))

# ----------------------------------------------------
# Hazard overview: every hazard for every county
# ----------------------------------------------------

st.subheader("Hazard Overview: all hazards by county")
_ov = safe_pivot(risk_df[risk_df["region"].isin(selected_regions)], "county", "hazard", "risk_score", "max")
if _ov.empty:
    st.info("No hazard data for the selected regions.")
else:
    _ov = _ov.loc[_ov.max(axis=1).sort_values(ascending=False).index]
    _ov_fig = px.imshow(
        _ov,
        color_continuous_scale=RG_SCALE,
        range_color=[0, 5],
        aspect="auto",
        text_auto=".1f",
        height=max(300, len(_ov) * 46 + 110),
        labels={"color": "Risk score"},
    )
    _ov_fig.update_layout(paper_bgcolor="#ffffff", plot_bgcolor="#ffffff", font=dict(color="#1d1d1f", family="Inter, sans-serif"), margin=dict(l=10, r=10, t=10, b=10))
    _ov_fig.update_xaxes(side="top", tickangle=0)
    st.plotly_chart(_ov_fig, use_container_width=True)
    _top = top_per_group(risk_df[risk_df["region"].isin(selected_regions)], "county", "risk_score")
    st.caption("Highest hazard per county: " + "; ".join(f"{r.county} {r.hazard} ({r.risk_score:.1f})" for r in _top.itertuples()))

# ----------------------------------------------------
# Load GeoJSON
# ----------------------------------------------------

if uploaded_geojson_file is not None:
    try:
        county_geojson = json.load(uploaded_geojson_file)

        for feature in county_geojson.get("features", []):
            props = feature.get("properties", {})

            possible_fields = [
                "NAME",
                "Name",
                "name",
                "COUNTY",
                "COUNTY_NAME",
                "COUNTY_NAM",
                "NAMELSAD",
                "CountyName"
            ]

            county_name = None

            for field in possible_fields:
                if field in props:
                    county_name = props[field]
                    break

            props["county_clean"] = clean_county_name(county_name)

        st.sidebar.success("County GeoJSON uploaded.")

    except Exception:
        st.sidebar.error("Uploaded GeoJSON could not be read.")
        county_geojson = None
else:
    county_geojson = load_county_geojson()

# ----------------------------------------------------
# GIS county polygon map
# ----------------------------------------------------

st.subheader("Chicago-Area County Risk Map")

filtered_risk["county_clean"] = filtered_risk["county"].apply(clean_county_name)

CHART_LAYOUT = dict(
    paper_bgcolor="#ffffff",
    plot_bgcolor="#ffffff",
    font=dict(color="#1d1d1f", family="Inter, sans-serif"),
    title_font=dict(color="#1d1d1f", size=15),
    legend=dict(bgcolor="#ffffff", bordercolor="#e5e5ea", borderwidth=1),
    xaxis=dict(gridcolor="#eceff3", zerolinecolor="#d2d2d7"),
    yaxis=dict(gridcolor="#eceff3", zerolinecolor="#d2d2d7"),
)

RISK_COLORS = {
    "Low":       GREEN,
    "Medium":    LIGHT_GREEN,
    "High":      LIGHT_RED,
    "Very High": RED,
}

if county_geojson is not None:
    # Pre-format hover values as strings (customdata format specifiers are unreliable)
    _risk_icons = {"Low": "🔵", "Medium": "🔷", "High": "🟠", "Very High": "🟧"}
    filtered_risk["_score_fmt"] = filtered_risk["risk_score"].apply(lambda x: f"{x:.1f}")
    filtered_risk["_svi_fmt"]   = filtered_risk["svi_score"].apply(lambda x: f"{x:.2f}")
    filtered_risk["_icon"]      = filtered_risk["risk_level"].map(_risk_icons).fillna("⚪")
    filtered_risk["_badge"]     = filtered_risk.apply(
        lambda r: f"{r['_icon']} {r['risk_level']} risk · SVI {r['_svi_fmt']}", axis=1
    )

    gis_fig = px.choropleth_mapbox(
        filtered_risk,
        geojson=county_geojson,
        locations="county_clean",
        featureidkey="properties.county_clean",
        color="risk_score",
        hover_name="county",
        custom_data=["region", "hazard", "risk_level", "_score_fmt", "_svi_fmt", "_badge", "_icon"],
        color_continuous_scale=RG_SCALE,
        range_color=[0, 5],
        mapbox_style="carto-positron",
        zoom=7.4,
        center=CHICAGO_CENTER,
        opacity=0.78,
        height=720,
        title=f"Chicago-Area {selected_hazard} Risk by County — hover a county for details",
    )

    gis_fig.update_traces(
        hovertemplate=(
            "<b style='font-size:15px'>%{hovertext} County</b><br>"
            "<span style='color:#515154; font-size:11px'>%{customdata[0]} Region</span><br>"
            "<hr style='border:0;border-top:1px solid #d2d2d7;margin:4px 0'>"
            "🌪 &nbsp;<b>Hazard:</b> %{customdata[1]}<br>"
            "%{customdata[6]} &nbsp;<b>Risk Level:</b> %{customdata[2]}<br>"
            "📊 &nbsp;<b>Risk Score:</b> %{customdata[3]} / 5.0<br>"
            "👥 &nbsp;<b>Social Vulnerability Index:</b> %{customdata[4]}<br>"
            "<hr style='border:0;border-top:1px solid #d2d2d7;margin:4px 0'>"
            "<i style='color:#0071e3; font-size:11px'>%{customdata[5]}</i>"
            "<extra></extra>"
        )
    )

    gis_fig.update_layout(
        margin={"r": 0, "t": 50, "l": 0, "b": 0},
        paper_bgcolor="#ffffff",
        font=dict(color="#1d1d1f"),
        title_font=dict(color="#0071e3", size=16),
        hoverlabel=dict(
            bgcolor="#ffffff",
            bordercolor="#0071e3",
            font_size=13,
            font_family="Inter, sans-serif",
            font_color="#1d1d1f",
        ),
        coloraxis_colorbar=dict(
            title=dict(text="Risk Score", font=dict(color="#0071e3")),
            tickfont=dict(color="#1d1d1f"),
            bgcolor="#ffffff",
            bordercolor="#d2d2d7",
            thickness=16,
            len=0.7,
        ),
    )
    st.plotly_chart(gis_fig, use_container_width=True)
    with st.expander(_t("ui.risk_table", LANG)):
        st.dataframe(filtered_risk[["county", "region", "hazard", "risk_level", "risk_score", "svi_score"]]
                     .sort_values("risk_score", ascending=False), hide_index=True, use_container_width=True)

else:
    st.warning("No valid Illinois county GeoJSON found. Showing fallback point map instead.")
    map_df = filtered_risk.dropna(subset=["latitude", "longitude"])

    if not map_df.empty:
        point_fig = px.scatter_mapbox(
            map_df,
            lat="latitude",
            lon="longitude",
            size="risk_score",
            color="risk_level",
            color_discrete_map=RISK_COLORS,
            hover_name="county",
            hover_data={
                "region": True,
                "hazard": True,
                "risk_score": True,
                "svi_score": True,
                "latitude": False,
                "longitude": False,
            },
            zoom=7.4,
            center=CHICAGO_CENTER,
            height=500,
            title=f"Fallback GIS Point Map: {selected_hazard} Risk by County"
        )
        point_fig.update_layout(
            mapbox_style="carto-positron",
            margin={"r": 0, "t": 40, "l": 0, "b": 0},
            paper_bgcolor="#ffffff",
            font=dict(color="#1d1d1f"),
        )
        st.plotly_chart(point_fig, width="stretch")

# ----------------------------------------------------
# Risk chart
# ----------------------------------------------------

st.subheader(f"{selected_hazard} Risk by County")

bar_fig = px.bar(
    filtered_risk,
    x="county",
    y="risk_score",
    color="risk_level",
    color_discrete_map=RISK_COLORS,
    hover_data=["region", "svi_score"],
    title=f"County-Level {selected_hazard} Risk Scores",
    text_auto=".1f",
    height=380,
)
bar_fig.update_layout(**CHART_LAYOUT)
bar_fig.update_traces(marker_line_width=0)
st.plotly_chart(bar_fig, width="stretch")

# ----------------------------------------------------
# Tables
# ----------------------------------------------------

left, right = st.columns(2)

with left:
    st.subheader("County Risk Table")
    st.dataframe(filtered_risk, width="stretch")

with right:
    st.subheader("Priority Mitigation Actions")
    st.dataframe(filtered_actions, width="stretch")

# ----------------------------------------------------
# Download filtered data
# ----------------------------------------------------

st.subheader("Download Filtered Data")

csv_download = filtered_risk.to_csv(index=False).encode("utf-8")

st.download_button(
    label="Download filtered county risk data",
    data=csv_download,
    file_name=f"{selected_hazard.lower().replace(' ', '_')}_county_risk.csv",
    mime="text/csv"
)

# ----------------------------------------------------
# Dashboard interpretation
# ----------------------------------------------------

st.subheader("Dashboard Interpretation")

st.info(_INTERPRETATION.get(
    selected_hazard,
    "This dashboard helps identify where hazard risk, social vulnerability, and mitigation needs overlap.",
))
# ----------------------------------------------------
# Load resource capacity data
# ----------------------------------------------------

capacity_path = _D + "county_capacity.csv"
complaints_path = _D + "complaints.csv"

sample_capacity_df = pd.DataFrame({
    "county": ["Cook", "DuPage", "Will", "Sangamon", "Jackson", "Alexander"],
    "region": ["Northeast", "Northeast", "Northeast", "Central", "Southern", "Southern"],
    "hazard": ["Flooding"] * 6,
    "mitigation_effort": [
        "Stormwater upgrades", "Retention basin", "Buyouts program",
        "Floodplain restoration", "Levee reinforcement", "Managed retreat"
    ],
    "status": ["In Progress", "Planning", "In Progress", "Planning", "In Progress", "In Progress"],
    "people_affected": [45000, 12000, 9800, 6200, 18500, 4200],
    "budget_usd": [2400000, 1800000, 3200000, 980000, 4100000, 2800000],
    "amount_spent_usd": [840000, 95000, 1120000, 42000, 1640000, 980000],
    "lead_agency": ["IDNR", "DuPage County", "IEMA-OHS", "IDNR", "USACE", "IEMA-OHS"],
    "start_date": ["2025-03-01"] * 6,
    "target_date": ["2026-09-01"] * 6,
})

sample_complaints_df = pd.DataFrame({
    "complaint_id": ["C001", "C002", "C003"],
    "county": ["Cook", "Alexander", "Jackson"],
    "hazard": ["Flooding", "Flooding", "Heat Wave"],
    "category": ["Infrastructure", "Evacuation", "Resource Access"],
    "description": ["Drain blocked", "No warning issued", "No cooling center"],
    "date_filed": ["2025-07-15", "2025-05-20", "2025-07-26"],
    "priority": ["High", "Critical", "Critical"],
    "status": ["Resolved", "Open", "Open"],
    "date_resolved": ["2025-07-22", None, None],
})

if os.path.exists(capacity_path):
    capacity_df = pd.read_csv(capacity_path)
else:
    capacity_df = sample_capacity_df

if os.path.exists(complaints_path):
    complaints_raw = pd.read_csv(complaints_path)
else:
    complaints_raw = sample_complaints_df

if uploaded_capacity_file is not None:
    if check_file_size(uploaded_capacity_file, MAX_CSV_MB):
        _df = pd.read_csv(uploaded_capacity_file)
        _ok, _err = validate_csv(_df, "county_capacity")
        if _ok:
            capacity_df = normalize_hazard_column(apply_capacity_csv_rules(_df))
            st.sidebar.success("Capacity data uploaded and validated.")
        else:
            st.sidebar.error(f"Capacity CSV rejected: {_err}")

if uploaded_complaints_file is not None:
    if check_file_size(uploaded_complaints_file, MAX_CSV_MB):
        _df = pd.read_csv(uploaded_complaints_file)
        _ok, _err = validate_csv(_df, "complaints")
        if _ok:
            complaints_raw = normalize_hazard_column(_df)
            st.sidebar.success("Complaints data uploaded and validated.")
        else:
            st.sidebar.error(f"Complaints CSV rejected: {_err}")

capacity_df = normalize_hazard_column(capacity_df)
complaints_raw = normalize_hazard_column(complaints_raw)
# Unfiltered copies feed the Hazard Assistant so it can answer for any county (Phase 0.5).
capacity_all = capacity_df.copy()
complaints_all = complaints_raw.copy()
capacity_df = _config.scope_frame(capacity_df, SCOPE_COUNTIES)
complaints_raw = _config.scope_frame(complaints_raw, SCOPE_COUNTIES)

# ----------------------------------------------------
# County Risk Analysis (rule-based, no AI)
# ----------------------------------------------------

st.subheader("County Risk Analysis")

if filtered_risk.empty:
    st.warning("No county data available for the selected hazard and region.")
else:
    selected_county_for_ai = st.selectbox(
        "Select county",
        sorted(filtered_risk["county"].dropna().unique()),
        key="risk_analysis_county",
    )

    county_row_for_ai = filtered_risk[filtered_risk["county"] == selected_county_for_ai]

    if not county_row_for_ai.empty:
        result = _rule_based_risk_analysis(county_row_for_ai.iloc[0], capacity_df)

        # ── Header metrics ────────────────────────────────────────────
        m1, m2, m3, m4 = st.columns(4)
        level_color = {"Low": "green", "Medium": "orange", "High": "red", "Very High": "red"}.get(result["risk_level"], "gray")
        m1.metric("Risk Level",  result["risk_level"])
        m2.metric("Risk Score",  f"{result['risk_score']:.1f} / 5.0")
        m3.metric("SVI",         f"{result['svi']:.2f}")
        m4.metric("Vulnerability", result["svi_label"])

        st.divider()

        # ── Risk summary ──────────────────────────────────────────────
        st.markdown(f"**Risk Summary**")
        st.markdown(
            f"{result['county']} County has **:{level_color}[{result['risk_level']}]** "
            f"{result['hazard']} risk (score **{result['risk_score']:.1f} / 5.0**). "
            f"Social Vulnerability Index: **{result['svi']:.2f}** — {result['svi_detail']}."
        )

        # ── Why it matters ────────────────────────────────────────────
        st.markdown("**Why This Matters**")
        st.markdown(result["compound"])

        # ── SVI guidance ──────────────────────────────────────────────
        st.markdown("**Equity Consideration**")
        st.markdown(result["svi_action"])

        # ── Priority actions ──────────────────────────────────────────
        st.markdown("**Priority Mitigation Actions**")
        for action in result["priority_actions"]:
            st.markdown(f"- {action}")

        # ── Existing mitigation efforts ───────────────────────────────
        if result["efforts"]:
            st.markdown("**Current Mitigation Efforts**")
            for e in result["efforts"]:
                spent_pct = e["pct"]
                bar_color = "green" if spent_pct >= 75 else "orange" if spent_pct >= 40 else "red"
                st.markdown(
                    f"- **{e['effort']}** — "
                    f"Budget: ${e['budget']:,.0f} · "
                    f"Spent: ${e['spent']:,.0f} (:{bar_color}[{spent_pct:.0f}%]) · "
                    f"{e['people']:,} people affected"
                )

        with st.expander("Raw source data"):
            st.dataframe(
                county_row_for_ai.drop(columns=["latitude", "longitude"], errors="ignore"),
                use_container_width=True,
            )


# ----------------------------------------------------
# Resource Capacity Section
# ----------------------------------------------------

st.divider()
st.subheader("Resource Capacity")

# Filter capacity data to selected hazard
cap_filtered = capacity_df[capacity_df["hazard"] == selected_hazard].copy()

# Complaints aggregated per county
open_by_county = (
    complaints_raw[complaints_raw["status"] == "Open"]
    .groupby("county")
    .size()
    .reset_index(name="open_complaints")
)
resolved_by_county = (
    complaints_raw[complaints_raw["status"] == "Resolved"]
    .groupby("county")
    .size()
    .reset_index(name="resolved_complaints")
)

# KPI cards ──────────────────────────────────────────
kpi1, kpi2, kpi3, kpi4 = st.columns(4)

with kpi1:
    total_affected = int(cap_filtered["people_affected"].sum()) if not cap_filtered.empty else 0
    st.metric("People Affected", f"{total_affected:,}")

with kpi2:
    total_spent = cap_filtered["amount_spent_usd"].sum() if not cap_filtered.empty else 0
    st.metric("Total Spent", f"${total_spent:,.0f}")

with kpi3:
    total_open = len(complaints_raw[complaints_raw["status"] == "Open"])
    st.metric("Live Complaints", total_open, delta=None)

with kpi4:
    total_resolved = len(complaints_raw[complaints_raw["status"] == "Resolved"])
    st.metric("Complaints Resolved", total_resolved)

# Row 1: Spending + People Affected ─────────────────
r1_left, r1_right = st.columns(2)

with r1_left:
    if not cap_filtered.empty:
        spend_df = (
            cap_filtered.groupby("county")[["budget_usd", "amount_spent_usd"]]
            .sum()
            .reset_index()
        )
        spend_df["budget_remaining_usd"] = spend_df["budget_usd"] - spend_df["amount_spent_usd"]
        spend_melt = spend_df.melt(
            id_vars="county",
            value_vars=["amount_spent_usd", "budget_remaining_usd"],
            var_name="type",
            value_name="usd"
        )
        spend_melt["type"] = spend_melt["type"].map({
            "amount_spent_usd": "Spent",
            "budget_remaining_usd": "Remaining Budget"
        })
        spend_fig = px.bar(
            spend_melt,
            x="usd",
            y="county",
            color="type",
            orientation="h",
            color_discrete_map={"Spent": RED, "Remaining Budget": GREEN},
            title=f"Budget vs Spent per County — {selected_hazard}",
            labels={"usd": "USD", "county": "County"},
            height=320,
        )
        spend_fig.update_layout(
            **CHART_LAYOUT,
            legend_title_text="",
            margin={"t": 40, "b": 0, "l": 0, "r": 0},
            xaxis_tickformat="$,.0f",
        )
        st.plotly_chart(spend_fig, width="stretch")
    else:
        st.info("No capacity data for selected hazard.")

with r1_right:
    if not cap_filtered.empty:
        affected_df = cap_filtered.groupby("county")["people_affected"].sum().reset_index()
        affected_fig = px.bar(
            affected_df,
            x="county",
            y="people_affected",
            color="county",
            color_discrete_sequence=[RED, "#d8514a", "#e57b74", "#a31d1d", LIGHT_RED, "#b8332d", "#ee948d"],
            title=f"People Affected per County — {selected_hazard}",
            labels={"people_affected": "People Affected", "county": "County"},
            height=320,
            text_auto=True,
        )
        affected_fig.update_layout(
            **CHART_LAYOUT,
            showlegend=False,
            margin={"t": 40, "b": 0, "l": 0, "r": 0},
        )
        st.plotly_chart(affected_fig, width="stretch")
    else:
        st.info("No capacity data for selected hazard.")

# Row 2: Complaints ──────────────────────────────────
r2_left, r2_right = st.columns(2)

with r2_left:
    complaint_county = count_by(complaints_raw, ["county", "status"])
    if not complaint_county.empty:
        complaint_colors = {"Open": RED, "Resolved": GREEN}
        comp_fig = px.bar(
            complaint_county,
            x="county",
            y="count",
            color="status",
            barmode="group",
            color_discrete_map={"Open": RED, "Resolved": GREEN},
            title="Live vs Resolved Complaints by County",
            labels={"count": "Complaints", "county": "County"},
            height=320,
            text_auto=True,
        )
        comp_fig.update_layout(
            **CHART_LAYOUT,
            legend_title_text="",
            margin={"t": 40, "b": 0, "l": 0, "r": 0},
        )
        st.plotly_chart(comp_fig, width="stretch")

with r2_right:
    category_counts = count_by(complaints_raw, ["category", "status"])
    if not category_counts.empty:
        cat_fig = px.bar(
            category_counts,
            x="count",
            y="category",
            color="status",
            orientation="h",
            color_discrete_map={"Open": RED, "Resolved": GREEN},
            title="Complaints by Category",
            labels={"count": "Count", "category": "Category"},
            height=320,
            barmode="stack",
        )
        cat_fig.update_layout(
            **CHART_LAYOUT,
            legend_title_text="",
            margin={"t": 40, "b": 0, "l": 0, "r": 0},
        )
        st.plotly_chart(cat_fig, width="stretch")

# Row 3: Priority heatmap ────────────────────────────
priority_order = ["Critical", "High", "Medium", "Low"]
priority_pivot = count_by(
    complaints_raw[complaints_raw["status"] == "Open"] if has_columns(complaints_raw, ["status"]) else complaints_raw.iloc[0:0],
    ["county", "priority"],
)

if not priority_pivot.empty:
    heat_pivot = priority_pivot.pivot(index="county", columns="priority", values="count").fillna(0)
    heat_cols = [c for c in priority_order if c in heat_pivot.columns]
    heat_pivot = heat_pivot[heat_cols]

    # Sort counties by total open complaints (highest at top)
    heat_pivot["_total"] = heat_pivot.sum(axis=1)
    heat_pivot = heat_pivot.sort_values("_total", ascending=True).drop(columns=["_total"])

    n_counties = len(heat_pivot)
    _heat_height = max(300, n_counties * 44 + 120)

    heat_fig = px.imshow(
        heat_pivot,
        text_auto=True,
        color_continuous_scale=[[0.0, "#e6f4ea"], [0.01, "#e6f4ea"], [0.5, LIGHT_RED], [1.0, RED]],
        title="Open Complaints Heatmap — County × Priority",
        labels={"color": "Open Complaints"},
        height=_heat_height,
        aspect="auto",
    )
    heat_fig.update_traces(
        textfont=dict(size=12, color="#1d1d1f"),
        hovertemplate="<b>%{y}</b><br>Priority: %{x}<br>Open complaints: %{z}<extra></extra>",
    )
    _heat_base = {k: v for k, v in CHART_LAYOUT.items() if k not in ("xaxis", "yaxis", "title_font")}
    heat_fig.update_layout(
        **_heat_base,
        margin={"t": 50, "b": 20, "l": 120, "r": 20},
        coloraxis_colorbar=dict(
            title=dict(text="Open", font=dict(color="#0071e3")),
            tickfont=dict(color="#1d1d1f"),
            bgcolor="#ffffff",
            bordercolor="#d2d2d7",
            thickness=14,
            len=0.5,
        ),
        title_font=dict(color="#0071e3", size=15),
    )
    heat_fig.update_xaxes(
        side="top",
        tickfont=dict(size=13, color="#0071e3"),
        title=dict(text="Priority Level", font=dict(color="#0071e3", size=13)),
    )
    heat_fig.update_yaxes(
        tickfont=dict(size=11, color="#1d1d1f"),
        title=dict(text="County", font=dict(color="#0071e3", size=13)),
        automargin=True,
    )
    st.plotly_chart(heat_fig, use_container_width=True)

# Row 4: Mitigation efforts table ────────────────────
st.markdown("**Mitigation Efforts**")

if not cap_filtered.empty:
    effort_display = cap_filtered[[
        "county", "mitigation_effort", "status", "people_affected",
        "budget_usd", "amount_spent_usd", "lead_agency", "start_date", "target_date"
    ]].copy()

    effort_display["pct_spent"] = (
        effort_display["amount_spent_usd"] / effort_display["budget_usd"] * 100
    ).round(1).astype(str) + "%"

    effort_display = effort_display.rename(columns={
        "county": "County",
        "mitigation_effort": "Effort",
        "status": "Status",
        "people_affected": "People Affected",
        "budget_usd": "Budget (USD)",
        "amount_spent_usd": "Spent (USD)",
        "pct_spent": "% Spent",
        "lead_agency": "Lead Agency",
        "start_date": "Start",
        "target_date": "Target",
    })

    status_colors = {
        "Active": "background-color: #d4edda",
        "In Progress": "background-color: #fff3cd",
        "Planning": "background-color: #cce5ff",
        "Completed": "background-color: #e2e3e5",
    }

    def highlight_status(row):
        color = status_colors.get(row["Status"], "")
        return [color if col == "Status" else "" for col in row.index]

    styled = effort_display.style.apply(highlight_status, axis=1).format({
        "Budget (USD)": "${:,.0f}",
        "Spent (USD)": "${:,.0f}",
        "People Affected": "{:,}",
    })

    st.dataframe(styled, width="stretch")
else:
    st.info("No mitigation efforts data for selected hazard.")

# Row 5: Live complaints detail table ────────────────
st.markdown("**Live Complaints**")

live_complaints = complaints_raw[complaints_raw["status"] == "Open"]

if not IS_INTERNAL:
    # Public View: aggregated counts only — no individual descriptions
    if live_complaints.empty:
        st.info("No live complaints.")
    else:
        agg_cols = st.columns(3)
        agg_cols[0].metric("Open Complaints", len(live_complaints))
        agg_cols[1].metric("Critical", int((live_complaints["priority"] == "Critical").sum()))
        agg_cols[2].metric("High Priority", int((live_complaints["priority"] == "High").sum()))
        st.caption(
            "Detailed complaint records are restricted to Internal View. "
            "Contact your emergency management office for operational details."
        )
else:
    live_complaints_display = live_complaints[[
        "complaint_id", "county", "hazard", "category", "priority", "description", "date_filed"
    ]].rename(columns={
        "complaint_id": "ID",
        "county": "County",
        "hazard": "Hazard",
        "category": "Category",
        "priority": "Priority",
        "description": "Description",
        "date_filed": "Filed",
    })

    priority_colors = {
        "Critical": "background-color: #f8d7da",
        "High": "background-color: #fff3cd",
        "Medium": "background-color: #d4edda",
    }

    def highlight_priority(row):
        color = priority_colors.get(row["Priority"], "")
        return [color if col == "Priority" else "" for col in row.index]

    if not live_complaints_display.empty:
        st.caption("⚠️ Operational complaint details — authorized Internal View users only.")
        st.dataframe(
            live_complaints_display.style.apply(highlight_priority, axis=1),
            width="stretch"
        )
    else:
        st.info("No live complaints.")

    st.markdown(GOVERNANCE_NOTE)

# ----------------------------------------------------
# PDF Summarizer
# ----------------------------------------------------

st.divider()
st.subheader("PDF Summarizer")

# PDF Summarizer is Internal View only
if not IS_INTERNAL:
    st.info("PDF upload and summarization are available in Internal View only.")
else:
    st.caption(
        "Upload any hazard planning document (admin only). "
        "Text is extracted and summarized entirely on this machine — no AI, no internet required."
    )
    st.markdown(PDF_REVIEW_NOTE)

    if "pdf_summary" not in st.session_state:
        st.session_state.pdf_summary = None
    if "pdf_filename" not in st.session_state:
        st.session_state.pdf_filename = None

    uploaded_pdf = st.file_uploader("Upload a PDF report", type=["pdf"], key="pdf_upload")

    st.caption("Summarization runs entirely on this machine — no AI model or internet required.")
    summary_focus = st.selectbox(
            "Summarization focus",
            [
                "Full summary (narrative + statistics)",
                "Statistics and numbers only",
                "Key findings and recommendations only",
                "Action items and responsible agencies",
            ],
            key="pdf_focus",
        )

    import io as _io
    import pdfplumber as _pdfplumber

    def _extract_pdf(uploaded_file) -> dict:
        raw = uploaded_file if isinstance(uploaded_file, (bytes, bytearray)) else uploaded_file.read()
        buf = _io.BytesIO(raw)
        text_pages, tables = [], []
        with _pdfplumber.open(buf) as pdf:
            page_count = len(pdf.pages)
            n = min(page_count, MAX_PDF_PAGES)

            # Smart sampling: cover whole document, not just the first pages.
            # Small PDFs → read every page.
            # Large PDFs → proportional sample: first 40 + evenly spaced middle + last 20.
            if page_count <= 120:
                indices = list(range(page_count))
            else:
                first = list(range(40))
                last  = list(range(page_count - 20, page_count))
                mid_slots = n - len(first) - len(last)
                if mid_slots > 0:
                    step = max(1, (page_count - 60) // mid_slots)
                    middle = list(range(40, page_count - 20, step))[:mid_slots]
                else:
                    middle = []
                indices = sorted(set(first + middle + last))

            for i in indices:
                page = pdf.pages[i]
                t = page.extract_text()
                if t:
                    text_pages.append(f"[Page {i + 1}]\n{t.strip()}")
                for tbl in page.extract_tables():
                    if tbl:
                        tables.append(tbl)
        return {
            "text": "\n\n".join(text_pages),
            "tables": tables,
            "page_count": page_count,
            "pages_processed": len(indices),
        }

    import re as _re
    from collections import Counter as _Counter

    _STOPWORDS = {
        'the','a','an','and','or','but','in','on','at','to','for','of','with',
        'by','is','was','are','were','be','been','being','have','has','had',
        'do','does','did','will','would','could','should','may','might','this',
        'that','these','those','it','its','as','from','into','through','during',
        'before','after','above','below','between','out','off','over','under',
        'again','further','then','once','here','there','when','where','why',
        'how','all','both','each','few','more','most','other','some','such',
        'no','nor','not','only','own','same','so','than','too','very','just',
        'because','if','while','although','though','since','until','unless',
        'also','however','therefore','thus','hence','furthermore','moreover',
        'nevertheless','nonetheless','meanwhile','subsequently','consequently',
    }

    _HAZARD_KEYWORDS = {
        'flood','tornado','earthquake','storm','drought','wind','hurricane',
        'wildfire','hazard','risk','damage','loss','injury','death','fatality',
        'emergency','disaster','mitigation','warning','evacuation','shelter',
        'vulnerable','vulnerability','svi','county','illinois','il','fema',
        'iema','preparedness','response','recovery','infrastructure','billion',
        'million','percent','%','residents','population','agency','plan',
    }

    def _clean_sent(s: str) -> str:
        """Remove page markers, collapse whitespace, strip."""
        s = _re.sub(r'\[Page\s*\d+\]', '', s)
        s = _re.sub(r'\s+', ' ', s).strip()
        return s

    def _extractive_summary(text: str, focus: str, n: int = 20) -> str:
        raw_sents = _re.split(r'(?<=[.!?])\s+', text.strip())
        sentences = [_clean_sent(s) for s in raw_sents]
        sentences = [s for s in sentences if len(s.split()) >= 6]
        if not sentences:
            return "No readable text could be extracted from this document."

        words = _re.findall(r'\b\w+\b', text.lower())
        freq  = _Counter(w for w in words if w not in _STOPWORDS and len(w) > 2)

        def score(sent, idx):
            toks = _re.findall(r'\b\w+\b', sent.lower())
            if not toks:
                return 0.0
            f  = sum(freq.get(w, 0) for w in toks) / len(toks)
            kw = sum(1 for w in toks if w in _HAZARD_KEYWORDS) * 2.5
            pos = 1.4 if idx < len(sentences) * 0.15 or idx > len(sentences) * 0.85 else 1.0
            has_num = 1.6 if _re.search(r'\d', sent) else 1.0
            return (f + kw) * pos * has_num

        scored = sorted(enumerate(sentences), key=lambda x: score(x[1], x[0]), reverse=True)

        if focus == "Statistics and numbers only":
            top = [(i, s) for i, s in scored if _re.search(r'\d', s)][:n]
        elif focus == "Key findings and recommendations only":
            action_words = {'recommend','require','should','must','shall','need','ensure',
                            'implement','develop','establish','improve','update','create',
                            'provide','support','address','reduce','increase','priority'}
            top = [(i, s) for i, s in scored
                   if any(w in s.lower() for w in action_words)][:n]
            if not top:
                top = scored[:n]
        elif focus == "Action items and responsible agencies":
            agency_words = {'agency','department','county','city','state','federal','iema',
                            'fema','office','division','district','authority','commission'}
            top = [(i, s) for i, s in scored
                   if any(w in s.lower() for w in agency_words)][:n]
            if not top:
                top = scored[:n]
        else:
            top = scored[:n]

        top = sorted(top, key=lambda x: x[0])  # restore document order

        def _stat_table(stat_sents):
            rows = ["| # | Finding |", "|---|---|"]
            for i, s in enumerate(stat_sents, 1):
                rows.append(f"| {i} | {s} |")
            return "\n".join(rows)

        def _bullets(sents):
            return "\n".join(f"- {s}" for s in sents)

        if focus == "Full summary (narrative + statistics)":
            narrative = [s for _, s in top if not _re.search(r'\d', s)][:8]
            stats     = [s for _, s in top if _re.search(r'\d', s)][:10]
            risks     = [s for _, s in top if any(w in s.lower() for w in
                         {'risk','hazard','flood','tornado','earthquake','storm',
                          'drought','damage','loss','vulnerable'})][:6]
            parts = []
            if narrative:
                parts.append("## Key Findings\n\n" + _bullets(narrative))
            if risks:
                parts.append("## Identified Risks\n\n" + _bullets(risks))
            if stats:
                parts.append("## Statistics & Data\n\n" + _stat_table(stats))
            return "\n\n---\n\n".join(parts) if parts else _bullets(s for _, s in top)

        elif focus == "Statistics and numbers only":
            stat_sents = [s for _, s in top]
            return "## Statistics & Data\n\n" + _stat_table(stat_sents)

        elif focus == "Key findings and recommendations only":
            return "## Key Findings & Recommendations\n\n" + _bullets(s for _, s in top)

        elif focus == "Action items and responsible agencies":
            rows = ["## Action Items & Responsible Agencies\n",
                    "| # | Action / Finding |",
                    "|---|---|"]
            for i, (_, s) in enumerate(top, 1):
                rows.append(f"| {i} | {s} |")
            return "\n".join(rows)

        return _bullets(s for _, s in top)

    def _tables_summary(tables) -> str:
        if not tables:
            return ""
        parts = ["\n\n---\n\n## Tables Extracted from Document"]
        valid = 0
        for tbl in tables[:8]:
            # Clean and filter rows
            clean = [
                [str(c).strip() if c else "" for c in row]
                for row in tbl
                if any(c for c in row)
            ]
            if len(clean) < 2:
                continue
            # Normalize column count
            ncols = max(len(row) for row in clean)
            clean = [row + [""] * (ncols - len(row)) for row in clean]
            valid += 1
            header = clean[0]
            # Escape pipe chars inside cells
            def _esc(cell):
                return cell.replace("|", "\\|").replace("\n", " ")
            parts.append(f"\n**Table {valid}**\n")
            parts.append("| " + " | ".join(_esc(h) for h in header) + " |")
            parts.append("|" + "|".join(["---"] * ncols) + "|")
            for row in clean[1:]:
                parts.append("| " + " | ".join(_esc(c) for c in row) + " |")
        if valid == 0:
            return ""
        return "\n".join(parts)

    def _find_counties(text: str) -> list:
        """Return Illinois county names found in the PDF text."""
        found, t = [], text.lower()
        for county in sorted(risk_df["county"].dropna().unique().tolist(), key=len, reverse=True):
            if county.lower() in t:
                found.append(county)
        return found

    _HAZARD_TYPES = {
        "Flood":        ["flood", "flooding", "inundation", "floodplain"],
        "Tornado":      ["tornado", "twister", "funnel cloud"],
        "Earthquake":   ["earthquake", "seismic", "tremor"],
        "Drought":      ["drought", "water shortage", "dry spell"],
        "Severe Storm": ["severe storm", "thunderstorm", "hail", "lightning"],
        "Wildfire":     ["wildfire", "wildland fire", "brush fire"],
        "Winter Storm": ["winter storm", "blizzard", "ice storm", "snowstorm"],
        "Extreme Heat": ["heat wave", "extreme heat", "heat index"],
        "High Wind":    ["high wind", "windstorm", "straight-line wind", "derecho"],
    }

    def _count_hazards(text: str) -> dict:
        """Count keyword occurrences per hazard type."""
        t = text.lower()
        counts = {h: sum(t.count(kw) for kw in kws)
                  for h, kws in _HAZARD_TYPES.items()}
        return dict(sorted(
            {h: n for h, n in counts.items() if n > 0}.items(),
            key=lambda x: x[1], reverse=True
        ))

    if uploaded_pdf is not None:
        if check_file_size(uploaded_pdf, MAX_PDF_MB):
            btn_col, info_col = st.columns([1, 3])
            with btn_col:
                do_summarize = st.button("Summarize PDF", type="primary", key="summarize_pdf")
            with info_col:
                st.caption(f"Uploaded: **{uploaded_pdf.name}**")

            if do_summarize:
                # Clear previous result before starting a new run
                st.session_state.pdf_summary  = None
                st.session_state.pdf_filename = None
                st.session_state.pdf_stats    = {}

                status_slot = st.empty()
                error_slot  = st.empty()
                try:
                    status_slot.info("Extracting text and tables from PDF…")
                    _pdf_bytes = uploaded_pdf.read()
                    _bar = st.progress(0.0, text="Reading PDF (runs in the background, 120 second limit)…")
                    try:
                        pdf_content = run_with_timeout(
                            lambda: _extract_pdf(_pdf_bytes),
                            timeout_s=DEFAULT_TIMEOUT_S,
                            on_tick=lambda f: _bar.progress(f, text="Reading PDF (runs in the background, 120 second limit)…"),
                        )
                    except TaskTimeout:
                        _bar.empty()
                        raise RuntimeError("The PDF took longer than 120 seconds to read. Try a smaller file or fewer pages.")
                    _bar.empty()

                    if not pdf_content["text"].strip():
                        status_slot.empty()
                        error_slot.warning(
                            "No readable text found. This may be a scanned/image-only PDF. "
                            "OCR is not currently supported."
                        )
                    else:
                        safe_text = sanitize_text(pdf_content["text"])
                        status_slot.info("Generating summary…")
                        summary = _extractive_summary(safe_text, summary_focus)
                        summary += _tables_summary(pdf_content["tables"])

                        _counties_found = _find_counties(safe_text)
                        _hazard_counts  = _count_hazards(safe_text)
                        st.session_state.pdf_summary  = summary
                        st.session_state.pdf_filename = uploaded_pdf.name
                        st.session_state.pdf_stats    = {
                            "pages":              pdf_content["page_count"],
                            "processed":          pdf_content["pages_processed"],
                            "tables":             len(pdf_content["tables"]),
                            "chars":              len(safe_text),
                            "counties_mentioned": _counties_found,
                            "hazard_counts":      _hazard_counts,
                        }
                        st.rerun()

                except Exception as _pdf_err:
                    status_slot.empty()
                    error_slot.error(
                        str(_pdf_err) if isinstance(_pdf_err, RuntimeError) else
                        "PDF could not be processed. Ensure the file is a valid, "
                        "non-password-protected PDF with selectable text."
                    )
    else:
        st.info("Upload a PDF above to summarize it.")

# ── Display summary (Internal View only) ─────────────
if IS_INTERNAL and st.session_state.get("pdf_summary"):
    import plotly.graph_objects as _go

    _stats           = st.session_state.get("pdf_stats", {})
    _counties_in_pdf = [c for c in _stats.get("counties_mentioned", []) if SCOPE_COUNTIES is None or c in SCOPE_COUNTIES]
    _hazard_counts   = _stats.get("hazard_counts", {})

    # ── Header ────────────────────────────────────────────────────────────────
    st.markdown(f"### {st.session_state.pdf_filename}")
    st.info(PDF_REVIEW_NOTE)

    # ── KPI metrics ───────────────────────────────────────────────────────────
    _k1, _k2, _k3, _k4 = st.columns(4)
    _k1.metric("Pages Processed",    f"{_stats.get('processed','?')} / {_stats.get('pages','?')}")
    _k2.metric("Counties Referenced", len(_counties_in_pdf),
               delta=f"of {len(CHICAGO_COUNTIES)} in-scope counties" if _counties_in_pdf else None)
    _k3.metric("Hazard Types Detected", len(_hazard_counts))
    _k4.metric("Tables Extracted",   _stats.get("tables", 0))

    st.markdown("---")

    # ── Chicago-area GIS map ────────────────────────────────
    st.markdown("#### Chicago-Area County Risk Map")
    # Aggregate: one row per county — take the highest risk score across all hazards
    _state_agg = (
        risk_df.groupby("county")
        .agg(
            region      = ("region",     "first"),
            risk_score  = ("risk_score", "max"),
            svi_score   = ("svi_score",  "first"),
        )
        .reset_index()
    )
    def _score_to_level(s):
        if s >= 4.0: return "Very High"
        if s >= 3.0: return "High"
        if s >= 2.0: return "Medium"
        return "Low"
    _state_agg["risk_level"]   = _state_agg["risk_score"].apply(_score_to_level)
    _state_agg["county_clean"] = _state_agg["county"].apply(clean_county_name)
    _state_agg["_sfmt"]        = _state_agg["risk_score"].apply(lambda x: f"{x:.1f}")
    _state_agg["_vfmt"]        = _state_agg["svi_score"].apply(lambda x: f"{x:.2f}")
    _state_agg["_in_pdf"]      = _state_agg["county"].isin(_counties_in_pdf).map(
                                     {True: "Referenced in document", False: "Not referenced"}
                                 )

    if county_geojson is not None:
        _state_fig = px.choropleth_mapbox(
            _state_agg,
            geojson=county_geojson,
            locations="county_clean",
            featureidkey="properties.county_clean",
            color="risk_score",
            hover_name="county",
            custom_data=["region", "risk_level", "_sfmt", "_vfmt", "_in_pdf"],
            color_continuous_scale=RG_SCALE,
            range_color=[0, 5],
            mapbox_style="carto-positron",
            zoom=7.4,
            center=CHICAGO_CENTER,
            opacity=0.82,
            height=540,
        )
        _state_fig.update_traces(
            hovertemplate=(
                "<b>%{hovertext} County</b><br>"
                "<span style='color:#515154'>%{customdata[0]} Region</span><br>"
                "Risk Level: %{customdata[1]}<br>"
                "Peak Risk Score: %{customdata[2]} / 5.0<br>"
                "SVI: %{customdata[3]}<br>"
                "<i style='color:#0071e3'>%{customdata[4]}</i>"
                "<extra></extra>"
            )
        )
        _state_fig.update_layout(
            margin={"r": 0, "t": 0, "l": 0, "b": 0},
            paper_bgcolor="#ffffff",
            font=dict(color="#1d1d1f"),
            coloraxis_colorbar=dict(
                title=dict(text="Peak Risk Score", font=dict(color="#0071e3")),
                tickfont=dict(color="#1d1d1f"),
                bgcolor="#ffffff", bordercolor="#d2d2d7",
                thickness=14, len=0.55,
            ),
        )
        st.plotly_chart(_state_fig, use_container_width=True)
        if _counties_in_pdf:
            st.caption(
                f"Document references {len(_counties_in_pdf)} of {len(CHICAGO_COUNTIES)} in-scope counties: "
                + ", ".join(sorted(_counties_in_pdf))
            )
    else:
        st.info("Upload the Illinois GeoJSON from the sidebar to enable the county map.")

    st.markdown("---")

    # ── County distribution by region ────────────────────────────────────────
    _map_col2, _dist_col = st.columns([3, 2])

    with _map_col2:
        st.markdown("**Counties by Region — Risk Level Distribution**")
        _region_dist = (
            _state_agg.groupby(["region", "risk_level"])
            .size()
            .reset_index(name="count")
        )
        _rl_order  = ["Very High", "High", "Medium", "Low"]
        _rl_colors = {
            "Very High": RED, "High": LIGHT_RED,
            "Medium": LIGHT_GREEN,  "Low":  GREEN,
        }
        _region_fig = px.bar(
            _region_dist,
            x="region", y="count",
            color="risk_level",
            barmode="stack",
            color_discrete_map=_rl_colors,
            category_orders={"risk_level": _rl_order},
            labels={"count": "Counties", "region": "Region", "risk_level": "Risk Level"},
            height=340,
        )
        _region_fig.update_layout(**{**CHART_LAYOUT,
            "height": 340,
            "margin": dict(l=0, r=10, t=10, b=60),
            "legend": dict(
                title="Risk Level", orientation="h",
                yanchor="top", y=-0.22, xanchor="left", x=0,
            ),
            "xaxis": dict(tickangle=-30, gridcolor="#e5e5ea", zerolinecolor="#e5e5ea"),
        })
        st.plotly_chart(_region_fig, use_container_width=True)

    with _dist_col:
        st.markdown("**Counties per Region**")
        _county_region_tbl = (
            _state_agg[["region", "county", "risk_level", "risk_score"]]
            .sort_values(["region", "risk_score"], ascending=[True, False])
            .rename(columns={
                "region": "Region", "county": "County",
                "risk_level": "Risk Level", "risk_score": "Peak Score",
            })
        )
        st.dataframe(
            _county_region_tbl,
            use_container_width=True,
            hide_index=True,
            height=340,
        )

    st.markdown("---")

    # ── Full-width risk matrix heatmap ────────────────────────────────────────
    if _counties_in_pdf:
        _mat = risk_df[risk_df["county"].isin(_counties_in_pdf)][
            ["county", "hazard", "risk_score"]
        ].copy()
        if not _mat.empty:
            st.markdown("#### Risk Matrix — County × Hazard")
            _pivot = _mat.pivot_table(
                index="county", columns="hazard",
                values="risk_score", aggfunc="max"
            ).fillna(0)
            _heat = px.imshow(
                _pivot,
                color_continuous_scale=RG_SCALE,
                range_color=[0, 5],
                aspect="auto",
                height=max(320, len(_pivot) * 26 + 100),
                text_auto=".1f",
            )
            _heat.update_layout(**{**CHART_LAYOUT,
                "margin": dict(l=10, r=10, t=20, b=10),
                "coloraxis_colorbar": dict(
                    title=dict(text="Score", font=dict(color="#0071e3")),
                    tickfont=dict(color="#1d1d1f"),
                    bgcolor="#ffffff", bordercolor="#d2d2d7", thickness=14,
                ),
            })
            _heat.update_xaxes(tickangle=-35)
            st.plotly_chart(_heat, use_container_width=True)
        st.markdown("---")

    # ── Open complaints cross-reference ───────────────────────────────────────
    st.markdown("#### Open Complaints — Counties Referenced in Document")
    if _counties_in_pdf:
        _open_comp = complaints_raw[
            (complaints_raw["county"].isin(_counties_in_pdf)) &
            (complaints_raw["status"] == "Open")
        ][["county", "hazard", "category", "priority", "date_filed", "description"]].copy()
        if not _open_comp.empty:
            _crit_n = len(_open_comp[_open_comp["priority"] == "Critical"])
            st.warning(
                f"**{len(_open_comp)} open complaint(s)** across referenced counties — "
                f"{_crit_n} Critical priority."
            )
            st.dataframe(_open_comp, use_container_width=True, hide_index=True)
        else:
            st.success("No open complaints for counties referenced in this document.")
    else:
        st.info("No counties detected — cannot cross-reference complaints.")

    st.markdown("---")

    # ── Text summary (collapsed by default) ───────────────────────────────────
    with st.expander("Full Text Summary", expanded=False):
        st.markdown(f"*{DRAFT_LABEL}*")
        st.markdown(st.session_state.pdf_summary)

    # ── Downloads ─────────────────────────────────────────────────────────────
    st.markdown("---")
    _base_name = (st.session_state.pdf_filename or "report").rsplit(".", 1)[0]
    _dl1, _dl2, _dl3 = st.columns([1, 1, 4])
    with _dl1:
        st.download_button(
            "⬇ Download (.md)",
            data=st.session_state.pdf_summary.encode("utf-8"),
            file_name=f"summary_{_base_name}.md",
            mime="text/markdown",
            key="download_pdf_summary_md",
        )
    with _dl2:
        st.download_button(
            "⬇ Download (.txt)",
            data=st.session_state.pdf_summary.encode("utf-8"),
            file_name=f"summary_{_base_name}.txt",
            mime="text/plain",
            key="download_pdf_summary_txt",
        )
    with _dl3:
        if st.button("Clear summary", key="clear_pdf_summary"):
            st.session_state.pdf_summary  = None
            st.session_state.pdf_filename = None
            st.rerun()

# ----------------------------------------------------
# Hazard Chatbot (built-in, no external API)
# ----------------------------------------------------

from chatbot_engine import chat as _hazard_chat

st.divider()
st.subheader("Hazard Assistant")

if not IS_INTERNAL:
    st.info("The Hazard Assistant is available in Internal View only.")
else:
    st.caption(
        "Ask about shelters, aid, emergency contacts, risk levels, mitigation, or preparedness. "
        "Runs entirely inside this dashboard — no external AI or API key required."
    )

    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []

    # Display full conversation history
    for _msg in st.session_state.chat_messages:
        with st.chat_message(_msg["role"]):
            st.markdown(_msg["content"])

    if _user_input := st.chat_input("Ask about shelters, aid, risk levels, emergency contacts, or preparedness…"):
        st.session_state.chat_messages.append({"role": "user", "content": _user_input})
        with st.chat_message("user"):
            st.markdown(_user_input)

        with st.chat_message("assistant"):
            _reply = _hazard_chat(
                user_message=_user_input,
                risk_df=risk_all,
                capacity_df=capacity_all,
                complaints_df=complaints_all,
                lang=LANG,
            )
            st.markdown(_reply)

        st.session_state.chat_messages.append({"role": "assistant", "content": _reply})

    if st.session_state.chat_messages:
        if st.button("Clear chat", key="clear_chat"):
            st.session_state.chat_messages = []
            st.rerun()

_footer()
