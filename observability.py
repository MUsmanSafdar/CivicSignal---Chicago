"""Structured logging and an optional Azure Application Insights hook (Phase 2.3). No Streamlit imports.

Every log line is one JSON object on the ``civicsignal`` logger, so App Service log streams, Log Analytics and
Application Insights can all parse it. Application Insights is enabled only when
``APPLICATIONINSIGHTS_CONNECTION_STRING`` is set; the Azure package is imported lazily and a missing package
never stops the app. Log lines carry the actor's email and ids, never free-text reasons or uploaded data.
"""
from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

LOGGER_NAME = "civicsignal"
_configured = False
SAFE_KEYS = ("rank", "score", "eligibility", "outcome", "rule", "program", "role", "roles", "source", "verified", "count", "n", "reason_type")


def _logger() -> logging.Logger:
    log = logging.getLogger(LOGGER_NAME)
    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        log.propagate = False
    return log


def format_event(event: str, actor: str = "", tenant: str = "", **fields: Any) -> str:
    """Build one JSON log line. Only whitelisted keys in ``fields`` are kept, so free text cannot leak into logs."""
    body: dict[str, Any] = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": event,
                            "actor": actor, "tenant": tenant}
    for key, value in fields.items():
        if key in SAFE_KEYS:
            body[key] = sorted(value) if isinstance(value, (set, frozenset)) else value
    return json.dumps(body, sort_keys=True, default=str)


def log_event(event: str, actor: str = "", tenant: str = "", **fields: Any) -> str:
    """Emit a structured line for a login, rule publication or decision, and return it."""
    line = format_event(event, actor, tenant, **fields)
    _logger().info(line)
    return line


def setup_app_insights(env: Mapping[str, str] | None = None) -> bool:
    """Turn on Azure Monitor if ``APPLICATIONINSIGHTS_CONNECTION_STRING`` is set. Returns True when enabled."""
    global _configured
    env = os.environ if env is None else env
    conn = env.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()
    if not conn or _configured:
        return _configured
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor  # optional dependency

        configure_azure_monitor(connection_string=conn, logger_name=LOGGER_NAME)
    except Exception as exc:  # noqa: BLE001 - monitoring must never break the app
        _logger().warning(format_event("observability.disabled", reason_type=type(exc).__name__))
        return False
    _configured = True
    return True
