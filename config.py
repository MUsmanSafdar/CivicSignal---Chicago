"""Environment-driven configuration (Phase 1.3). No Streamlit imports, no secrets in code."""
from __future__ import annotations

import os
from collections.abc import Mapping

import pandas as pd

DEFAULT_COUNTIES: tuple[str, ...] = ("Cook", "DuPage", "Kane", "Kendall", "Lake", "McHenry", "Will")


def _env(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env


def allowed_counties(env: Mapping[str, str] | None = None) -> list[str] | None:
    """Counties this deployment is scoped to, from ``ALLOWED_COUNTIES``.

    Unset or blank returns the Chicago-area default (behavior unchanged). ``ALL`` (any case) returns
    ``None``, meaning no filtering. Otherwise a comma-separated list is parsed and trimmed.
    """
    raw = _env(env).get("ALLOWED_COUNTIES", "").strip()
    if not raw:
        return list(DEFAULT_COUNTIES)
    if raw.upper() == "ALL":
        return None
    parsed = [c.strip() for c in raw.split(",") if c.strip()]
    return parsed or list(DEFAULT_COUNTIES)


def scope_frame(df: pd.DataFrame, counties: list[str] | None, column: str = "county") -> pd.DataFrame:
    """Filter ``df`` to ``counties``; ``None`` or a frame without the column is returned as a copy."""
    if counties is None or column not in df.columns:
        return df.copy()
    return df[df[column].isin(counties)].copy()


def tenant_id(env: Mapping[str, str] | None = None) -> str:
    """Tenant key used to separate persisted data (``TENANT_ID``, default ``default``)."""
    return _env(env).get("TENANT_ID", "").strip() or "default"


def scope_label(counties: list[str] | None) -> str:
    """Human-readable scope for captions."""
    if counties is None:
        return "all counties"
    return f"{len(counties)} configured counties"
