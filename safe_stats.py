"""NaN- and empty-safe helpers for dashboard KPIs and pivots (Phase 0.9). No Streamlit imports."""
from __future__ import annotations

from typing import Iterable

import pandas as pd


def has_columns(df: pd.DataFrame | None, columns: Iterable[str]) -> bool:
    """True when ``df`` is a non-None frame containing every column in ``columns``."""
    return df is not None and all(c in df.columns for c in columns)


def safe_mean(df: pd.DataFrame | None, column: str, digits: int = 2) -> float | None:
    """Mean of ``column`` rounded to ``digits``; ``None`` for a missing, empty, or all-NaN column."""
    if not has_columns(df, [column]) or df is None or df.empty:
        return None
    value = pd.to_numeric(df[column], errors="coerce").mean()
    return None if pd.isna(value) else round(float(value), digits)


def format_kpi(value: float | None, fallback: str = "N/A") -> float | str:
    """Return ``value`` for display, or ``fallback`` when it is missing."""
    return fallback if value is None else value


def safe_pivot(df: pd.DataFrame | None, index: str, columns: str, values: str, aggfunc: str = "max") -> pd.DataFrame:
    """Pivot table that returns an empty frame instead of raising on empty or incomplete input."""
    if not has_columns(df, [index, columns, values]) or df is None or df.empty:
        return pd.DataFrame()
    return df.pivot_table(index=index, columns=columns, values=values, aggfunc=aggfunc)


def top_per_group(df: pd.DataFrame | None, group: str, sort_by: str, n: int = 1) -> pd.DataFrame:
    """Top ``n`` rows per ``group`` by ``sort_by`` (descending); empty frame when inputs are unusable."""
    if not has_columns(df, [group, sort_by]) or df is None or df.empty:
        return pd.DataFrame(columns=list(df.columns) if df is not None else [])
    return df.sort_values(sort_by, ascending=False).groupby(group).head(n)


def count_by(df: pd.DataFrame | None, keys: list[str]) -> pd.DataFrame:
    """Row counts per ``keys`` as a frame with a ``count`` column; empty frame when columns are missing."""
    if not has_columns(df, keys) or df is None or df.empty:
        return pd.DataFrame(columns=[*keys, "count"])
    return df.groupby(keys).size().reset_index(name="count")
