"""PAS persistence: JSON state in the existing per-tenant settings store, events in the existing hash-chained audit trail.

No new tables are needed: audit_store already provides set_setting/get_setting on both the SQLite and Azure Table backends,
so this module works on either and the PAS audit events share the same chain (and verify_chain) as the rest of CivicSignal.
"""
from __future__ import annotations

from typing import Any

import audit_store
import pas_engine

SETTING_KEY = "pas_state_v1"
SCHEMA_VERSION = 1


def load(backend: audit_store.Backend, tenant: str) -> dict[str, Any]:
    raw = backend.get_setting(tenant, SETTING_KEY, None)
    if not raw:
        return pas_engine.new_pas()
    pas = pas_engine.new_pas()
    pas.update({k: v for k, v in raw.items() if k in ("config", "cases", "seq")})
    pas["config"] = {**pas_engine.new_pas()["config"], **pas["config"]}
    return pas


def save(backend: audit_store.Backend, tenant: str, pas: dict[str, Any]) -> int:
    """Append queued events to the audit chain, then store the state. Returns the number of events written."""
    events = pas_engine.drain_outbox(pas)
    for e in events:
        audit_store.append_event(backend, tenant, e["actor"], e["action"], e["resource_type"], e["resource_id"], e["detail"])
    blob = {"schema": SCHEMA_VERSION, "config": pas["config"], "cases": pas["cases"], "seq": pas["seq"]}
    backend.set_setting(tenant, SETTING_KEY, blob)
    return len(events)


def case_events(backend: audit_store.Backend, tenant: str, case_id: str) -> list[dict[str, Any]]:
    return [e for e in audit_store.list_events(backend, tenant) if e.get("resourceId") == case_id and str(e.get("action", "")).startswith("pas.")]
