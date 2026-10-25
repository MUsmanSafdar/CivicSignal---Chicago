"""Language access (Phase 1.8): English and Spanish dictionaries for public-facing text. No Streamlit imports.

Locale files live in ``locales/<code>.json``. Values are strings or lists of lines (joined with newlines).
A missing key falls back to English, then to the key itself, so a gap never crashes the page.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

LOCALE_DIR = Path(__file__).resolve().parent / "locales"
DEFAULT_LANG = "en"
LANGUAGES: dict[str, str] = {"en": "English", "es": "Español"}


@lru_cache(maxsize=8)
def load_locale(lang: str) -> dict[str, Any]:
    """Load one locale dictionary; an unknown or unreadable locale yields ``{}``."""
    try:
        with open(LOCALE_DIR / f"{lang}.json", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


class _Safe(dict):  # type: ignore[type-arg]
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def normalize_lang(lang: str | None) -> str:
    """Map a code such as ``es-MX`` to a supported language, defaulting to English."""
    code = (lang or DEFAULT_LANG).lower().split("-")[0].split("_")[0]
    return code if code in LANGUAGES else DEFAULT_LANG


def t(key: str, lang: str | None = DEFAULT_LANG, **values: object) -> str:
    """Translate ``key`` into ``lang``, filling ``{placeholders}`` from ``values``."""
    code = normalize_lang(lang)
    raw = load_locale(code).get(key)
    if raw is None:
        raw = load_locale(DEFAULT_LANG).get(key, key)
    text = "\n".join(raw) if isinstance(raw, list) else str(raw)
    return text.format_map(_Safe(values)) if values or "{" in text else text


def missing_keys(lang: str) -> set[str]:
    """Keys present in English but absent in ``lang`` (used by tests)."""
    return set(load_locale(DEFAULT_LANG)) - set(load_locale(lang))
