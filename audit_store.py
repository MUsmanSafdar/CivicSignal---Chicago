"""Persistent, tenant-scoped storage for the audit chain, workspace state, settings and funding notices (Phase 1.1).

Backends: SQLite (local/dev, default) and Azure Table Storage (production, ``AUDIT_CONNECTION_STRING``).
Hash-chain semantics are unchanged: the hashes come from ``civicsignal.hash_event`` and an event links to
the one before it for the same tenant. No Streamlit imports.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Protocol

import civicsignal as cs

Event = dict[str, Any]
_STATE_KEYS = ("projects", "published", "decisions", "last_outcome")


class Backend(Protocol):
    """Storage interface shared by the SQLite and Azure Table backends."""

    def append_event(self, tenant: str, event: Event) -> None: ...
    def list_events(self, tenant: str) -> list[Event]: ...
    def save_state(self, tenant: str, state: dict[str, Any]) -> None: ...
    def load_state(self, tenant: str) -> dict[str, Any] | None: ...
    def set_setting(self, tenant: str, key: str, value: Any) -> None: ...
    def get_setting(self, tenant: str, key: str, default: Any = None) -> Any: ...
    def upsert_opportunity(self, tenant: str, opp: dict[str, Any]) -> None: ...
    def list_opportunities(self, tenant: str) -> list[dict[str, Any]]: ...


class SQLiteBackend:
    """SQLite backend. Safe for the single-process dev and pilot deployments this app targets."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = threading.Lock()
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (tenant TEXT NOT NULL, n INTEGER NOT NULL, body TEXT NOT NULL,
                                                   PRIMARY KEY (tenant, n));
                CREATE TABLE IF NOT EXISTS state (tenant TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (tenant TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
                                                     PRIMARY KEY (tenant, key));
                CREATE TABLE IF NOT EXISTS opportunities (tenant TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL,
                                                          PRIMARY KEY (tenant, id));
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path)

    def append_event(self, tenant: str, event: Event) -> None:
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO events (tenant, n, body) VALUES (?, ?, ?)",
                       (tenant, int(event["n"]), cs.canon(event)))

    def list_events(self, tenant: str) -> list[Event]:
        with self._connect() as db:
            rows = db.execute("SELECT body FROM events WHERE tenant = ? ORDER BY n", (tenant,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def save_state(self, tenant: str, state: dict[str, Any]) -> None:
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO state (tenant, body) VALUES (?, ?) ON CONFLICT(tenant) DO UPDATE SET body = excluded.body",
                       (tenant, json.dumps(state)))

    def load_state(self, tenant: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT body FROM state WHERE tenant = ?", (tenant,)).fetchone()
        return json.loads(row[0]) if row else None

    def set_setting(self, tenant: str, key: str, value: Any) -> None:
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO settings (tenant, key, value) VALUES (?, ?, ?) "
                       "ON CONFLICT(tenant, key) DO UPDATE SET value = excluded.value", (tenant, key, json.dumps(value)))

    def get_setting(self, tenant: str, key: str, default: Any = None) -> Any:
        with self._connect() as db:
            row = db.execute("SELECT value FROM settings WHERE tenant = ? AND key = ?", (tenant, key)).fetchone()
        return json.loads(row[0]) if row else default

    def upsert_opportunity(self, tenant: str, opp: dict[str, Any]) -> None:
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO opportunities (tenant, id, body) VALUES (?, ?, ?) "
                       "ON CONFLICT(tenant, id) DO UPDATE SET body = excluded.body", (tenant, str(opp["id"]), json.dumps(opp)))

    def list_opportunities(self, tenant: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT body FROM opportunities WHERE tenant = ?", (tenant,)).fetchall()
        return [json.loads(r[0]) for r in rows]


class AzureTableBackend:
    """Azure Table Storage backend (``azure-data-tables``). One table per record kind; partition key = tenant.

    Pass an already-built ``service`` (a ``TableServiceClient``) in tests; otherwise ``connection_string``
    is used. Events use a zero-padded row key so they sort in chain order.
    """

    def __init__(self, connection_string: str | None = None, service: Any = None) -> None:
        if service is None:
            from azure.data.tables import TableServiceClient  # imported lazily: optional dependency

            service = TableServiceClient.from_connection_string(connection_string or "")
        self._tables = {name: service.create_table_if_not_exists(name)
                        for name in ("csevents", "csstate", "cssettings", "csopps")}

    def append_event(self, tenant: str, event: Event) -> None:
        self._tables["csevents"].create_entity({"PartitionKey": tenant, "RowKey": f"{int(event['n']):010d}", "body": cs.canon(event)})

    def list_events(self, tenant: str) -> list[Event]:
        rows = self._tables["csevents"].query_entities(f"PartitionKey eq '{_odata(tenant)}'")
        return [json.loads(r["body"]) for r in sorted(rows, key=lambda r: r["RowKey"])]

    def _upsert(self, table: str, tenant: str, row: str, body: Any) -> None:
        self._tables[table].upsert_entity({"PartitionKey": tenant, "RowKey": row, "body": json.dumps(body)})

    def _get(self, table: str, tenant: str, row: str) -> Any:
        try:
            return json.loads(self._tables[table].get_entity(partition_key=tenant, row_key=row)["body"])
        except Exception:  # noqa: BLE001 - azure raises ResourceNotFoundError; any miss means "absent"
            return None

    def save_state(self, tenant: str, state: dict[str, Any]) -> None:
        self._upsert("csstate", tenant, "state", state)

    def load_state(self, tenant: str) -> dict[str, Any] | None:
        out = self._get("csstate", tenant, "state")
        return out if isinstance(out, dict) else None

    def set_setting(self, tenant: str, key: str, value: Any) -> None:
        self._upsert("cssettings", tenant, key, value)

    def get_setting(self, tenant: str, key: str, default: Any = None) -> Any:
        out = self._get("cssettings", tenant, key)
        return default if out is None else out

    def upsert_opportunity(self, tenant: str, opp: dict[str, Any]) -> None:
        self._upsert("csopps", tenant, str(opp["id"]), opp)

    def list_opportunities(self, tenant: str) -> list[dict[str, Any]]:
        rows = self._tables["csopps"].query_entities(f"PartitionKey eq '{_odata(tenant)}'")
        return [json.loads(r["body"]) for r in rows]


def _odata(value: str) -> str:
    """Escape a value for an OData filter (single quotes are doubled)."""
    return value.replace("'", "''")


def get_backend(env: Mapping[str, str] | None = None) -> Backend:
    """Choose the backend from the environment.

    ``AUDIT_CONNECTION_STRING`` set: Azure Table Storage. Otherwise SQLite at ``AUDIT_DB_PATH``
    (default ``civicsignal_data.sqlite3`` next to the app).
    """
    env = os.environ if env is None else env
    conn = env.get("AUDIT_CONNECTION_STRING", "").strip()
    if conn:
        return AzureTableBackend(connection_string=conn)
    return SQLiteBackend(env.get("AUDIT_DB_PATH", "civicsignal_data.sqlite3"))


# ---------------------------------------------------------------- audit chain API
def append_event(backend: Backend, tenant: str, actor: str, action: str, resource_type: str, resource_id: str,
                 detail: dict[str, Any]) -> Event:
    """Append one event to the tenant's chain, linking it to the stored previous event, and return it."""
    events = backend.list_events(tenant)
    chain: list[Event] = list(events)
    cs.append_event(chain, actor, action, resource_type, resource_id, detail)
    event = chain[-1]
    backend.append_event(tenant, event)
    return event


def list_events(backend: Backend, tenant: str) -> list[Event]:
    """All events for the tenant, oldest first."""
    return backend.list_events(tenant)


def verify_chain(backend: Backend, tenant: str) -> tuple[bool, str]:
    """Verify the stored chain for the tenant."""
    return cs.verify_chain(backend.list_events(tenant))


# ---------------------------------------------------------------- workspace state persistence
def sync_state(backend: Backend, tenant: str, state: dict[str, Any]) -> int:
    """Persist new in-memory audit entries and the rest of the workspace state; returns entries written.

    Only entries beyond the stored count are appended, and each must link to the stored tail, so a tampered
    in-memory chain (the demo) is never written. The state snapshot excludes the audit list.
    """
    stored = backend.list_events(tenant)
    written = 0
    tail = stored[-1]["hash"] if stored else cs.GENESIS
    for entry in state["audit"][len(stored):]:
        if entry["prev"] != tail or cs.hash_event(cs._body(entry)) != entry["hash"]:
            raise ValueError("In-memory audit entry does not extend the stored chain; refusing to write it.")
        backend.append_event(tenant, entry)
        tail = entry["hash"]
        written += 1
    backend.save_state(tenant, {k: state[k] for k in _STATE_KEYS})
    return written


def load_workspace(backend: Backend, tenant: str) -> dict[str, Any]:
    """Rebuild a workspace state for the tenant from storage (or a fresh one if nothing is stored)."""
    state = cs.new_state()
    saved = backend.load_state(tenant)
    if saved:
        state.update({k: saved[k] for k in _STATE_KEYS if k in saved})
    state["audit"] = backend.list_events(tenant)
    if not saved:
        cs.init_outcomes(state)
    return state


def utc_now() -> str:
    """Current UTC time as an ISO string (seconds)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
