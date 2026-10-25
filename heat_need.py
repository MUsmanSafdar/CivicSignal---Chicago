"""Heat-wave need index per county (cooling-centers page). Pure pandas, no Streamlit.

need = 100 * (0.5 * heat_risk / 5 + 0.5 * svi), using the Extreme Heat risk score (0 to 5) and the Social
Vulnerability Index (0 to 1) already in the county risk file. Higher means more people are likely to be hurt in a
heat wave. It is a simple, transparent blend for orientation, not a forecast and not a clinical measure.
"""
from __future__ import annotations

import pandas as pd

HEAT_HAZARD = "Extreme Heat"
HEAT_WEIGHT = 0.5
SVI_WEIGHT = 0.5
HIGH_NEED = 50.0
COLUMNS = ["county", "heat_score", "svi", "need", "centers", "gap"]


def need_index(heat_score: float, svi: float) -> float:
    """Blend a 0-5 heat risk score and a 0-1 SVI into a 0-100 index (inputs are clamped to their ranges)."""
    h = min(max(float(heat_score), 0.0), 5.0) / 5.0
    s = min(max(float(svi), 0.0), 1.0)
    return round(100.0 * (HEAT_WEIGHT * h + SVI_WEIGHT * s), 1)


def need_table(risk: pd.DataFrame, centers: pd.DataFrame) -> pd.DataFrame:
    """One row per county with its need index, cooling centers listed, and whether it is a coverage gap.

    ``gap`` is True when need is at least ``HIGH_NEED`` and the list has no centers there. A gap means "none on
    this list", not "none exist". Missing columns or empty input give an empty frame with the standard columns.
    """
    need_cols = {"county", "hazard", "risk_score", "svi_score"}
    if risk is None or risk.empty or not need_cols <= set(risk.columns):
        return pd.DataFrame(columns=COLUMNS)
    heat = risk[risk["hazard"] == HEAT_HAZARD].dropna(subset=["risk_score", "svi_score"])
    if heat.empty:
        return pd.DataFrame(columns=COLUMNS)
    heat = heat.groupby("county", as_index=False).agg(heat_score=("risk_score", "max"), svi=("svi_score", "max"))
    heat["need"] = [need_index(h, s) for h, s in zip(heat["heat_score"], heat["svi"])]
    counts = centers.groupby("county").size() if centers is not None and "county" in centers.columns and not centers.empty else pd.Series(dtype=int)
    heat["centers"] = heat["county"].map(counts).fillna(0).astype(int)
    heat["gap"] = (heat["need"] >= HIGH_NEED) & (heat["centers"] == 0)
    return heat.sort_values("need", ascending=False).reset_index(drop=True)[COLUMNS]
