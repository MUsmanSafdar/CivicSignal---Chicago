"""
security_utils.py — Security helpers for the IL Hazard Dashboard.

Covers:
  - PII sanitization before AI calls
  - CSV schema validation + numeric coercion
  - File-size enforcement
  - Session-based AI rate limiting
  - Standard UI disclaimers
"""

import re
import streamlit as st
import pandas as pd

# ── Limits ────────────────────────────────────────────────────────────
AI_REQUEST_LIMIT = 10     # max AI calls per browser session
MAX_CSV_MB       = 10     # MB cap for CSV uploads (admin only)
MAX_PDF_MB       = 200    # MB cap for PDF uploads (admin only)
MAX_PDF_CHARS    = 8000   # max chars sent to AI from PDF text
MAX_PDF_PAGES    = 800    # max pages to extract

# ── Required columns per schema ───────────────────────────────────────
REQUIRED_COLUMNS: dict[str, list[str]] = {
    "county_risk": [
        "county", "region", "hazard", "risk_score", "risk_level", "svi_score",
    ],
    "mitigation_actions": [
        "hazard", "action", "lead_agency", "priority", "status", "funding",
    ],
    "county_capacity": [
        "county", "region", "hazard", "mitigation_effort", "status",
        "people_affected", "budget_usd", "amount_spent_usd",
        "lead_agency", "start_date", "target_date",
    ],
    "complaints": [
        "complaint_id", "county", "hazard", "category", "description",
        "date_filed", "priority", "status", "date_resolved",
    ],
}

# ── PII regex patterns ────────────────────────────────────────────────
_EMAIL  = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
_PHONE  = re.compile(r'\b(\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}\b')
_SSN    = re.compile(r'\b\d{3}-\d{2}-\d{4}\b')
_ADDR   = re.compile(
    r'\b\d{1,5}\s+[A-Za-z0-9\s]{2,40}'
    r'(Street|St|Avenue|Ave|Boulevard|Blvd|Road|Rd|Drive|Dr'
    r'|Lane|Ln|Way|Court|Ct|Place|Pl)\b',
    re.IGNORECASE,
)
_ID_NUM = re.compile(r'\b\d{8,}\b')   # generic long numeric IDs


def sanitize_text(text: str) -> str:
    """Remove common PII patterns before sending free text to an AI provider."""
    text = _EMAIL.sub('[EMAIL]', text)
    text = _PHONE.sub('[PHONE]', text)
    text = _SSN.sub('[ID]', text)
    text = _ADDR.sub('[ADDRESS]', text)
    text = _ID_NUM.sub('[ID]', text)
    return text


def sanitize_dict_list(
    records: list[dict],
    exclude_keys: list[str] | None = None,
) -> list[dict]:
    """
    Sanitize a list of record dicts before sending to AI.
    Strips PII from string values; drops keys listed in exclude_keys.
    """
    drop = set(exclude_keys or [])
    cleaned = []
    for row in records:
        cleaned.append({
            k: sanitize_text(str(v)) if isinstance(v, str) else v
            for k, v in row.items()
            if k not in drop
        })
    return cleaned


# ── CSV validation ────────────────────────────────────────────────────

def validate_csv(df: pd.DataFrame, schema: str) -> tuple[bool, str]:
    """Return (is_valid, error_message)."""
    if df is None or df.empty:
        return False, "File is empty — no data loaded."
    missing = set(REQUIRED_COLUMNS.get(schema, [])) - set(df.columns)
    if missing:
        return False, f"Missing required columns: {', '.join(sorted(missing))}"
    return True, ""


def coerce_numeric(df: pd.DataFrame, col: str, lo: float, hi: float) -> pd.DataFrame:
    """Safely coerce col to numeric, clip to [lo, hi], warn on problems."""
    df = df.copy()
    original = df[col].copy()
    df[col]  = pd.to_numeric(df[col], errors="coerce")
    bad = df[col].isna() & original.notna()
    if bad.any():
        st.warning(f"'{col}': {int(bad.sum())} non-numeric value(s) set to NaN.")
    oor = df[col].notna() & ((df[col] < lo) | (df[col] > hi))
    if oor.any():
        st.warning(f"'{col}': {int(oor.sum())} value(s) outside [{lo}, {hi}] — clipped.")
        df[col] = df[col].clip(lo, hi)
    return df


def apply_risk_csv_rules(df: pd.DataFrame) -> pd.DataFrame:
    df = coerce_numeric(df, "risk_score", 0.0, 5.0)
    df = coerce_numeric(df, "svi_score",  0.0, 1.0)
    return df


def apply_capacity_csv_rules(df: pd.DataFrame) -> pd.DataFrame:
    df = coerce_numeric(df, "people_affected", 0, 10_000_000)
    df = coerce_numeric(df, "budget_usd",       0, 1_000_000_000)
    df = coerce_numeric(df, "amount_spent_usd", 0, 1_000_000_000)
    return df


# ── File-size enforcement ─────────────────────────────────────────────

def check_file_size(uploaded_file, max_mb: float) -> bool:
    """Return True if within limit, else show st.error and return False."""
    size_mb = getattr(uploaded_file, "size", 0) / (1024 * 1024)
    if size_mb > max_mb:
        st.error(
            f"**{uploaded_file.name}** is {size_mb:.1f} MB — "
            f"maximum is {max_mb} MB. Upload a smaller file."
        )
        return False
    return True


# ── Session AI rate limiter ───────────────────────────────────────────

def _init_rate():
    if "ai_request_count" not in st.session_state:
        st.session_state.ai_request_count = 0


def ai_allowed() -> bool:
    _init_rate()
    return st.session_state.ai_request_count < AI_REQUEST_LIMIT


def consume_ai_request():
    _init_rate()
    st.session_state.ai_request_count += 1


def remaining_ai() -> int:
    _init_rate()
    return max(0, AI_REQUEST_LIMIT - st.session_state.ai_request_count)


def rate_limit_sidebar():
    rem = remaining_ai()
    colour = "green" if rem > 6 else "orange" if rem > 2 else "red"
    st.sidebar.markdown(
        f"**AI requests remaining:** :{colour}[{rem} / {AI_REQUEST_LIMIT}]"
    )
    if rem == 0:
        st.sidebar.error("Session limit reached. Reload the page to reset.")


def rate_limit_blocked_msg():
    st.warning(
        f"AI request limit ({AI_REQUEST_LIMIT} per session) reached. "
        "Reload the page to start a new session."
    )


# ── Standard disclaimers ──────────────────────────────────────────────

AI_DISCLAIMER = (
    "> ⚠️ **AI-generated planning support.** "
    "Verify all outputs against official data before operational use. "
    "Do not send personally identifiable information, sensitive infrastructure "
    "details, or confidential material to AI providers."
)

DRAFT_LABEL = "*Draft recommendations only — not official IEMA-OHS guidance.*"

PDF_REVIEW_NOTE = (
    "📋 **AI-generated PDF summary — requires human review "
    "before use in planning or reporting.**"
)

PROTOTYPE_WARNING = (
    "⚠️ **Prototype / sample data** — replace with verified official datasets "
    "before operational use."
)

GOVERNANCE_NOTE = """
---
#### Governance Note
This dashboard is a planning-support tool and does **not** replace:
- Official **IEMA-OHS** review and approval
- **FEMA** plan or grant approval processes
- Local emergency management professional judgment
- Legal or regulatory compliance review

All AI summaries and recommendations are **draft planning support only**.
"""
