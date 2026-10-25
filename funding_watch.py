"""Grants.gov funding watch (Phase 1.6). No Streamlit imports.

Queries the public Grants.gov ``search2`` API (no key needed) for flood and hazard mitigation notices and caches
what it finds in the persistent store. Network access goes through an injectable ``fetcher`` so tests run offline.
The static ``cs.OPPS`` list stays only as a labelled offline snapshot.
"""
from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import civicsignal as cs

API_URL = "https://api.grants.gov/v1/api/search2"
KEYWORDS: tuple[str, ...] = ("flood mitigation", "hazard mitigation")
STALE_AFTER_DAYS = 7
SETTING_LAST_CHECKED = "funding_last_checked"
SETTING_LAST_ERROR = "funding_last_error"
DETAIL_URL = "https://www.grants.gov/search-results-detail/{id}"

Fetcher = Callable[[str], dict[str, Any]]


def default_fetcher(keyword: str, timeout: float = 20.0) -> dict[str, Any]:
    """POST one keyword search to Grants.gov and return the decoded JSON."""
    body = json.dumps({"keyword": keyword, "oppStatuses": "forecasted|posted", "rows": 50}).encode()
    req = urllib.request.Request(API_URL, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https URL
        data = json.loads(resp.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Unexpected Grants.gov response")
    return data


def parse_hits(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract opportunity records (id, title, agency, close_date, status) from a ``search2`` response."""
    data = payload.get("data") if isinstance(payload, dict) else None
    hits = data.get("oppHits") if isinstance(data, dict) else None
    out: list[dict[str, Any]] = []
    for h in hits or []:
        if not isinstance(h, dict) or not h.get("id"):
            continue
        out.append({"id": str(h["id"]), "title": str(h.get("title", "")).strip(), "number": str(h.get("number", "")),
                    "agency": str(h.get("agency") or h.get("agencyCode") or ""), "close_date": str(h.get("closeDate") or ""),
                    "status": str(h.get("oppStatus") or "")})
    return out


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def refresh(backend: Any, tenant: str, fetcher: Fetcher | None = None, now: str | None = None,
            keywords: tuple[str, ...] = KEYWORDS) -> dict[str, Any]:
    """Fetch every keyword, merge into the store and record the check time.

    Existing notices keep their ``first_seen``; new ones get ``now``. If every keyword fails, nothing is marked as
    checked and the error is stored so the UI can say so. Returns ``{"new": n, "seen": n, "errors": [...]}``.
    """
    fetcher = fetcher or default_fetcher
    now = now or _now()
    known = {o["id"]: o for o in backend.list_opportunities(tenant)}
    new = seen = 0
    errors: list[str] = []
    ok_any = False
    for kw in keywords:
        try:
            hits = parse_hits(fetcher(kw))
        except Exception as exc:  # noqa: BLE001 - network, JSON and HTTP errors all mean "keep the old cache"
            errors.append(f"{kw}: {type(exc).__name__}")
            continue
        ok_any = True
        for h in hits:
            prev = known.get(h["id"])
            rec = {**h, "first_seen": prev["first_seen"] if prev else now, "last_checked": now, "keyword": kw}
            if prev is None:
                new += 1
            seen += 1
            known[h["id"]] = rec
            backend.upsert_opportunity(tenant, rec)
    if ok_any:
        backend.set_setting(tenant, SETTING_LAST_CHECKED, now)
        backend.set_setting(tenant, SETTING_LAST_ERROR, "")
    else:
        backend.set_setting(tenant, SETTING_LAST_ERROR, "; ".join(errors))
    return {"new": new, "seen": seen, "errors": errors}


def list_cached(backend: Any, tenant: str) -> list[dict[str, Any]]:
    """Cached notices, newest ``first_seen`` first."""
    return sorted(backend.list_opportunities(tenant), key=lambda o: (o.get("first_seen", ""), o["id"]), reverse=True)


def last_checked(backend: Any, tenant: str) -> str | None:
    """ISO timestamp of the last successful refresh, or ``None``."""
    return backend.get_setting(tenant, SETTING_LAST_CHECKED, None) or None


def age_days(stamp: str | None, now: str | None = None) -> float | None:
    """Days between ``stamp`` and ``now`` (``None`` when ``stamp`` is missing or unreadable)."""
    if not stamp:
        return None
    try:
        a = datetime.fromisoformat(stamp)
        b = datetime.fromisoformat(now) if now else datetime.now(timezone.utc)
    except ValueError:
        return None
    if a.tzinfo is None:
        a = a.replace(tzinfo=timezone.utc)
    if b.tzinfo is None:
        b = b.replace(tzinfo=timezone.utc)
    return (b - a).total_seconds() / 86400


def staleness(backend: Any, tenant: str, now: str | None = None) -> tuple[bool, str]:
    """``(is_stale, message)``. Never checked, or older than 7 days, counts as stale."""
    stamp = last_checked(backend, tenant)
    days = age_days(stamp, now)
    if stamp is None or days is None:
        return True, "Funding notices have never been refreshed from Grants.gov. Showing the offline snapshot only."
    if days > STALE_AFTER_DAYS:
        return True, f"Last checked {stamp}, which is {int(days)} days ago. Notices may be out of date; refresh before relying on them."
    return False, f"Last checked: {stamp}"


def offline_snapshot() -> list[dict[str, Any]]:
    """The static captured list, shaped like cached records and clearly flagged as a snapshot."""
    return [{"id": str(i), "title": t, "agency": a, "first_seen": seen, "close_date": "", "relevant": rel, "snapshot": True}
            for i, t, a, seen, rel in cs.OPPS]
