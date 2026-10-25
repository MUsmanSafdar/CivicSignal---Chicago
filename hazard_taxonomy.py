"""Canonical hazard vocabulary and normalization (Phase 0.3). Pure Python plus pandas; no Streamlit."""
from __future__ import annotations

import re
from typing import Final

import pandas as pd

CANONICAL_HAZARDS: Final[tuple[str, ...]] = (
    "Flood", "Tornado", "Severe Storm", "Winter Storm", "Extreme Heat", "Drought", "Earthquake",
)

# Lower-cased alias -> canonical name. Whitespace and punctuation are collapsed before lookup.
_ALIASES: Final[dict[str, str]] = {
    "flood": "Flood", "flooding": "Flood", "floods": "Flood", "flash flood": "Flood",
    "flash flooding": "Flood", "river flood": "Flood", "riverine flooding": "Flood",
    "tornado": "Tornado", "tornadoes": "Tornado", "tornados": "Tornado", "twister": "Tornado",
    "severe storm": "Severe Storm", "severe storms": "Severe Storm", "severe weather": "Severe Storm",
    "thunderstorm": "Severe Storm", "thunderstorms": "Severe Storm", "storm": "Severe Storm",
    "high wind": "Severe Storm", "hail": "Severe Storm", "straight line winds": "Severe Storm",
    "winter storm": "Winter Storm", "winter storms": "Winter Storm", "blizzard": "Winter Storm",
    "ice storm": "Winter Storm", "snow storm": "Winter Storm", "snowstorm": "Winter Storm",
    "extreme heat": "Extreme Heat", "heat": "Extreme Heat", "heat wave": "Extreme Heat",
    "heatwave": "Extreme Heat", "excessive heat": "Extreme Heat", "extreme temperatures": "Extreme Heat",
    "drought": "Drought", "droughts": "Drought", "dry spell": "Drought",
    "earthquake": "Earthquake", "earthquakes": "Earthquake", "seismic": "Earthquake", "quake": "Earthquake",
}


def _key(raw: str) -> str:
    return re.sub(r"[\s_\-/]+", " ", raw.strip().lower())


def normalize_hazard(raw: object) -> str:
    """Return the canonical hazard name for ``raw``.

    Known aliases map to the canonical vocabulary ("Flooding" -> "Flood", "Heat Wave" -> "Extreme Heat").
    Unknown, empty, or non-string values are returned title-cased and trimmed so nothing is silently
    dropped; an empty or missing value returns "Unknown".
    """
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return "Unknown"
    text = str(raw).strip()
    if not text:
        return "Unknown"
    return _ALIASES.get(_key(text), text.title() if text.islower() else text)


def is_canonical(name: str) -> bool:
    """True when ``name`` is one of the canonical hazards."""
    return name in CANONICAL_HAZARDS


def normalize_hazard_column(df: pd.DataFrame, column: str = "hazard", keep_raw: bool = True) -> pd.DataFrame:
    """Return a copy of ``df`` with ``column`` normalized.

    When ``keep_raw`` is true the original display value is kept in ``<column>_raw`` so reports can show
    what the source file said. A frame without the column is returned unchanged (copy).
    """
    out = df.copy()
    if column not in out.columns:
        return out
    if keep_raw and f"{column}_raw" not in out.columns:
        out[f"{column}_raw"] = out[column]
    out[column] = out[column].map(normalize_hazard)
    return out
