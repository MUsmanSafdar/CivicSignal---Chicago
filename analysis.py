"""Pure county risk analysis (Phase 0.4). No Streamlit imports so it can be unit tested."""
from __future__ import annotations

from typing import Any

import pandas as pd

from hazard_taxonomy import normalize_hazard

HAZARD_ACTIONS: dict[str, list[str]] = {
    "Flood": [
        "Update floodplain maps and enforce current building setbacks.",
        "Install or upgrade early-warning stream gauges in high-risk corridors.",
        "Strengthen stormwater infrastructure in low-lying areas.",
    ],
    "Tornado": [
        "Audit shelter availability and capacity county-wide.",
        "Test and expand outdoor warning siren coverage.",
        "Establish rapid shelter-in-place guidance for mobile home communities.",
    ],
    "Earthquake": [
        "Assess structural vulnerability of critical facilities (schools, hospitals, bridges).",
        "Update local building codes to current seismic standards.",
        "Train first-responders in post-earthquake rapid damage assessment.",
    ],
    "Severe Storm": [
        "Harden power distribution infrastructure against wind damage.",
        "Pre-position emergency supplies at county distribution points.",
        "Review mutual-aid agreements with adjacent counties.",
    ],
    "Winter Storm": [
        "Audit road salt stockpiles and plow equipment readiness before October.",
        "Identify and pre-register vulnerable residents for wellness checks.",
        "Coordinate with utilities on outage response protocols.",
    ],
    "Extreme Heat": [
        "Open and publicize cooling centers; extend hours during heat advisories.",
        "Run welfare checks and outreach for older adults and people living alone.",
        "Expand tree canopy and cool surfaces in the hottest neighborhoods.",
    ],
    "Drought": [
        "Enact tiered water-use restrictions at defined supply thresholds.",
        "Engage agricultural stakeholders on irrigation efficiency programs.",
        "Map alternative water supply sources for critical infrastructure.",
    ],
}

INTERPRETATION: dict[str, str] = {
    "Flood": "Prioritize flood mitigation where high exposure overlaps with high social vulnerability: stormwater upgrades, buyouts and elevation, floodplain restoration and better warning.",
    "Tornado": "Prioritize safe rooms and warning coverage where mobile-home parks, schools and care facilities have little shelter access.",
    "Severe Storm": "Prioritize backup power and hardening for critical facilities, and check outage exposure for people who rely on powered medical equipment.",
    "Winter Storm": "Prioritize warming-center capacity, road clearing and welfare checks for older adults and people without reliable heat.",
    "Extreme Heat": "Prioritize cooling centers, outreach and tree canopy where high temperatures overlap with older adults, renters and low-income households.",
    "Drought": "Drought is a slow-onset hazard here. Prioritize water-supply planning and grass-fire readiness at the county edges.",
    "Earthquake": "Earthquake risk is low across the area but not zero. Focus on assessing critical facilities and checking building-code compliance.",
}

_DEFAULT_ACTIONS = [
    "Review county hazard mitigation plan for this hazard type.",
    "Coordinate with IEMA on resource pre-positioning.",
    "Update public communication and alert systems.",
]


def _num(value: Any, default: float = 0.0) -> float:
    """Coerce to float; NaN, None and junk become ``default``."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return default if pd.isna(out) else out


def capacity_efforts(capacity_df: pd.DataFrame | None, county: str, hazard: str, limit: int = 3) -> list[dict[str, Any]]:
    """Build effort rows from CAPACITY data filtered by county AND hazard.

    Reads ``mitigation_effort``, ``budget_usd``, ``amount_spent_usd`` and ``people_affected``. Missing
    columns degrade to zero or a generic label; an empty or missing frame returns an empty list.
    """
    if capacity_df is None or capacity_df.empty or "county" not in capacity_df.columns:
        return []
    rows = capacity_df[capacity_df["county"] == county]
    if "hazard" in rows.columns:
        rows = rows[rows["hazard"].map(normalize_hazard) == normalize_hazard(hazard)]
    efforts: list[dict[str, Any]] = []
    for _, row in rows.head(limit).iterrows():
        budget = _num(row.get("budget_usd"))
        spent = _num(row.get("amount_spent_usd"))
        efforts.append({
            "effort": str(row.get("mitigation_effort", "Mitigation effort")),
            "budget": budget,
            "spent": spent,
            "pct": (spent / budget * 100.0) if budget > 0 else 0.0,
            "people": int(_num(row.get("people_affected"))),
        })
    return efforts


def rule_based_risk_analysis(county_row: pd.Series, capacity_df: pd.DataFrame | None) -> dict[str, Any]:
    """Rule-based (no AI) county risk narrative.

    ``county_row`` is one row of the risk frame; ``capacity_df`` is the capacity frame (not the
    mitigation-actions frame), which is filtered here by county and hazard.
    """
    county = str(county_row.get("county", "This county"))
    hazard = normalize_hazard(county_row.get("hazard", "Unknown"))
    risk_score = _num(county_row.get("risk_score"))
    svi = _num(county_row.get("svi_score", county_row.get("svi", 0)))
    risk_level = str(county_row.get("risk_level", "Unknown"))

    if svi >= 0.75:
        svi_label, svi_detail = "Very High", "large share of residents face compounding hardship"
        svi_action = "Prioritize equity-focused outreach, multilingual warnings, and direct assistance."
    elif svi >= 0.50:
        svi_label, svi_detail = "High", "elevated vulnerability across income, age, and housing dimensions"
        svi_action = "Ensure warning systems reach seniors, renters, and low-income households."
    elif svi >= 0.25:
        svi_label, svi_detail = "Moderate", "moderate vulnerability — some segments need targeted support"
        svi_action = "Maintain standard community outreach and public education programs."
    else:
        svi_label, svi_detail = "Low", "community capacity is relatively strong"
        svi_action = "Focus on infrastructure hardening; residents generally able to self-prepare."

    if svi >= 0.50 and risk_score >= 3.0:
        compound = (f"The overlap of {risk_level.lower()} hazard exposure and {svi_label.lower()} social vulnerability "
                    f"means residents of {county} County have reduced capacity to prepare, respond, and recover. "
                    f"{hazard} impacts here are likely to be disproportionate and longer-lasting.")
    elif svi >= 0.50:
        compound = (f"While {hazard} risk is {risk_level.lower()}, the {svi_label.lower()} SVI means affected residents "
                    f"may require targeted support to recover without prolonged hardship.")
    elif risk_score >= 3.0:
        compound = (f"{county} County faces significant {hazard} exposure. Community adaptive capacity is adequate "
                    f"but infrastructure and response systems require continued investment.")
    else:
        compound = (f"{county} County's {hazard} risk is currently {risk_level.lower()} with manageable social "
                    f"vulnerability. Routine monitoring and preparedness activities are appropriate.")

    base = HAZARD_ACTIONS.get(hazard, _DEFAULT_ACTIONS)
    return {
        "county": county, "hazard": hazard, "risk_score": risk_score, "risk_level": risk_level,
        "svi": svi, "svi_label": svi_label, "svi_detail": svi_detail, "svi_action": svi_action,
        "compound": compound, "priority_actions": base if risk_score >= 3.0 else base[:2],
        "efforts": capacity_efforts(capacity_df, county, hazard),
    }
