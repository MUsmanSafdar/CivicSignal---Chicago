"""PAS Review Center engine: cases, checklist, workflow, metrics. Pure Python, no Streamlit, no I/O.

Internal administrative aid. It records what a state or county reviewer did and when; it does not make or imply a
FEMA approval or any binding federal determination. Every mutator takes the actor and a timestamp, enforces the
transition and evidence rules, and queues an audit event in ``pas["_outbox"]`` for pas_store to append to the
hash-chained audit trail.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timezone
from typing import Any

import pas_rules

STAGES = ["submission", "state_intake", "completeness_review", "technical_review", "corrections", "state_decision",
          "federal_referral", "monitoring", "closed"]
STAGE_LABEL = {"submission": "County/subapplicant submission", "state_intake": "State intake", "completeness_review": "Completeness review",
               "technical_review": "Technical review", "corrections": "Corrections", "state_decision": "State decision",
               "federal_referral": "Federal referral", "monitoring": "Monitoring", "closed": "Closed"}
# who holds the case while it sits in a stage (used to attribute delay only where timestamps support it)
STAGE_HOLDER = {"submission": "applicant", "state_intake": "state", "completeness_review": "state", "technical_review": "state",
                "corrections": "applicant", "state_decision": "state", "federal_referral": "federal", "monitoring": "state"}
TRANSITIONS: dict[str, set[str]] = {
    "submission": {"state_intake"},
    "state_intake": {"completeness_review"},
    "completeness_review": {"technical_review", "corrections"},
    "technical_review": {"corrections", "state_decision", "federal_referral"},
    "corrections": {"completeness_review", "technical_review"},
    "state_decision": {"monitoring", "corrections", "federal_referral"},
    "federal_referral": {"monitoring", "corrections", "closed"},
    "monitoring": {"closed"},
    "closed": set(),
}
ITEM_STATUSES = ["Verified", "Missing", "Incomplete", "Under review", "Not applicable", "Requires federal determination"]
REQUEST_KINDS = ["RFI", "Document request", "Correction"]
DECISIONS = {"recommend_approve": "State recommends approval (administrative; not a FEMA approval)",
             "return_to_applicant": "Returned to applicant for correction",
             "not_recommended": "State does not recommend"}
DASHBOARD_STATUSES = ["Awaiting documentation", "Ready for internal review", "Pending correction", "Awaiting state action",
                      "Referred for federal review", "Completed administrative review"]


# Placeholder. A Verified time-sensitive item older than this gets a warning. Admins set the real number from the guidance in force.
DEFAULT_STALE_DAYS = 90


class PasError(ValueError):
    """Raised for an invalid action (bad transition, missing evidence, duplicate, ...). The message is user-facing."""


# ------------------------------------------------------------------ time helpers
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dt(s: str) -> datetime:
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def days_between(a: str, b: str) -> float:
    return round((_dt(b) - _dt(a)).total_seconds() / 86400, 2)


# ------------------------------------------------------------------ state
def new_pas() -> dict[str, Any]:
    return {"config": {"delegation": {k: False for k in pas_rules.PAS_FUNCTIONS}, "disaster": "", "agreement_ref": "",
                       "guidance_version": "", "mode": "local demo", "stale_after_days": DEFAULT_STALE_DAYS},
            "cases": {}, "seq": 0, "_outbox": []}


def _emit(pas: dict[str, Any], actor: str, action: str, case_id: str, detail: dict[str, Any]) -> None:
    pas.setdefault("_outbox", []).append({"actor": actor, "action": action, "resource_type": "pas_case", "resource_id": case_id, "detail": detail})


def drain_outbox(pas: dict[str, Any]) -> list[dict[str, Any]]:
    out = list(pas.get("_outbox", []))
    pas["_outbox"] = []
    return out


def set_delegation(pas: dict[str, Any], actor: str, delegation: dict[str, bool], *, disaster: str = "", agreement_ref: str = "",
                   guidance_version: str = "") -> None:
    unknown = set(delegation) - set(pas_rules.PAS_FUNCTIONS)
    if unknown:
        raise PasError(f"Unknown PAS function: {sorted(unknown)[0]}")
    pas["config"]["delegation"] = {k: bool(delegation.get(k, False)) for k in pas_rules.PAS_FUNCTIONS}
    pas["config"].update({"disaster": disaster, "agreement_ref": agreement_ref, "guidance_version": guidance_version})
    _emit(pas, actor, "pas.delegation_set", "config", {"delegation": pas["config"]["delegation"], "disaster": disaster,
                                                        "agreement_ref": agreement_ref, "guidance_version": guidance_version})


# ------------------------------------------------------------------ cases
def create_case(pas: dict[str, Any], actor: str, *, project_id: str, jurisdiction: str, program: str, hazard: str = "", subapplicant: str = "",
                submitted_at: str, due_at: str = "", demo: bool = False, funding_opportunity: str = "") -> dict[str, Any]:
    """Open a review case for an existing CivicSignal project id. Rejects a second open case for the same project and program."""
    if not project_id or not jurisdiction or not program or not submitted_at:
        raise PasError("project_id, jurisdiction, program and submitted_at are required.")
    for c in pas["cases"].values():
        if c["project_id"] == project_id and c["program"] == program and c["stage"] != "closed":
            raise PasError(f"Project {project_id} already has an open {program} case ({c['id']}).")
    pas["seq"] += 1
    cid = f"PAS-{pas['seq']:04d}"
    reqs = pas_rules.requirements_for(program)
    case = {"id": cid, "project_id": project_id, "jurisdiction": jurisdiction, "program": program, "hazard": hazard,
            "subapplicant": subapplicant, "submitted_at": submitted_at, "due_at": due_at, "stage": "submission", "assigned_to": "",
            "demo": demo, "funding_opportunity": funding_opportunity, "guidance_version": pas["config"].get("guidance_version", ""),
            "history": [{"at": submitted_at, "actor": actor, "from": "", "to": "submission", "note": "Case opened"}],
            "checklist": {r["id"]: {"status": "Missing", "evidence": [], "note": "", "updated_at": submitted_at, "updated_by": actor}
                          for r in reqs},
            "requests": [], "comments": [], "decision": None, "federal_referral": None, "milestones": []}
    pas["cases"][cid] = case
    _emit(pas, actor, "pas.case_created", cid, {"project_id": project_id, "program": program, "jurisdiction": jurisdiction, "demo": demo})
    return case


def _case(pas: dict[str, Any], cid: str) -> dict[str, Any]:
    if cid not in pas["cases"]:
        raise PasError(f"Unknown case {cid}.")
    return pas["cases"][cid]


def assign(pas: dict[str, Any], cid: str, actor: str, reviewer: str, at: str) -> None:
    c = _case(pas, cid)
    if c["stage"] == "closed":
        raise PasError("A closed case cannot be reassigned.")
    if not reviewer.strip():
        raise PasError("Reviewer is required.")
    prev = c["assigned_to"]
    c["assigned_to"] = reviewer.strip()
    c.setdefault("assignments", []).append({"at": at, "by": actor, "reviewer": reviewer.strip(), "previous": prev})
    _emit(pas, actor, "pas.assigned", cid, {"reviewer": reviewer.strip(), "previous": prev})


def set_stale_days(pas: dict[str, Any], actor: str, days: int) -> None:
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 3650:
        raise PasError("Stale-after days must be a whole number from 1 to 3650.")
    old = pas["config"].get("stale_after_days", DEFAULT_STALE_DAYS)
    pas["config"]["stale_after_days"] = days
    _emit(pas, actor, "pas.stale_days_set", "config", {"from": old, "to": days})


def set_item(pas: dict[str, Any], cid: str, actor: str, req_id: str, status: str, at: str, *, evidence: list[str] | None = None, note: str = "",
             reconfirm: bool = False) -> None:
    c = _case(pas, cid)
    if c["stage"] == "closed":
        raise PasError("A closed case cannot be edited.")
    if req_id not in c["checklist"]:
        raise PasError(f"Unknown requirement {req_id}.")
    if status not in ITEM_STATUSES:
        raise PasError(f"Unknown status {status}.")
    item = c["checklist"][req_id]
    ev = [e.strip() for e in (evidence if evidence is not None else item["evidence"]) if e and e.strip()]
    if status == "Verified" and not ev:
        raise PasError("Verified requires at least one evidence reference.")
    if status == "Not applicable" and not (note or item["note"]).strip():
        raise PasError("Not applicable requires a reason in the note.")
    old = item["status"]
    item.update({"status": status, "evidence": ev, "note": note or item["note"], "updated_at": at, "updated_by": actor})
    if status == "Verified" and (old != "Verified" or reconfirm):
        item["verified_at"], item["verified_by"] = at, actor  # a note edit alone does not count as re-checking the fact
    elif status != "Verified":
        item.pop("verified_at", None)
        item.pop("verified_by", None)
    c.setdefault("item_history", []).append({"at": at, "actor": actor, "req_id": req_id, "from": old, "to": status})
    _emit(pas, actor, "pas.item_set", cid, {"req_id": req_id, "from": old, "to": status, "evidence_count": len(ev), "reconfirm": reconfirm})


def item_freshness(case: dict[str, Any], req_id: str, now: str, stale_days: int = DEFAULT_STALE_DAYS) -> dict[str, Any]:
    """How old a Verified time-sensitive item is. state: not_time_sensitive | not_verified | fresh | stale.

    Items saved before ``verified_at`` existed fall back to ``updated_at``. This only warns; it never changes readiness.
    """
    req = next((r for r in pas_rules.requirements_for(case["program"]) if r["id"] == req_id), None)
    item = case["checklist"].get(req_id)
    if req is None or item is None or not req.get("time_sensitive"):
        return {"req_id": req_id, "state": "not_time_sensitive", "days": None, "verified_at": ""}
    if item["status"] != "Verified":
        return {"req_id": req_id, "state": "not_verified", "days": None, "verified_at": ""}
    at = item.get("verified_at") or item["updated_at"]
    days = max(days_between(at, now), 0.0)
    return {"req_id": req_id, "state": "stale" if days > stale_days else "fresh", "days": round(days), "verified_at": at, "label": req["label"]}


def stale_items(case: dict[str, Any], now: str, stale_days: int = DEFAULT_STALE_DAYS) -> list[dict[str, Any]]:
    out = [item_freshness(case, rid, now, stale_days) for rid in case["checklist"]]
    return [f for f in out if f["state"] == "stale"]


# ------------------------------------------------------------------ readiness
def evaluate_readiness(case: dict[str, Any], catalogue: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Required-vs-optional assessment. Not a percent of boxes: it reports which required items are unresolved and why.

    overall: ready | blocked | pending_review | federal_determination_needed
    ``ready`` means the internal administrative checklist has no unresolved required item. It is not FEMA approval.
    """
    reqs = {r["id"]: r for r in pas_rules.requirements_for(case["program"], catalogue)}
    unresolved, pending, federal, optional_open, resolved = [], [], [], [], []
    for rid, r in reqs.items():
        st = case["checklist"].get(rid, {"status": "Missing"})["status"]
        row = {"id": rid, "label": r["label"], "status": st, "authority": r["authority"], "required": r["required"],
               "source": r["source_title"], "confirmed": r["confirmed"]}
        if st in ("Verified", "Not applicable"):
            resolved.append(row)
        elif not r["required"]:
            optional_open.append(row)
        elif st == "Requires federal determination":
            federal.append(row)
        elif st == "Under review":
            pending.append(row)
        else:
            unresolved.append(row)
    if unresolved:
        overall = "blocked"
    elif pending:
        overall = "pending_review"
    elif federal:
        overall = "federal_determination_needed"
    else:
        overall = "ready"
    return {"overall": overall, "required_unresolved": unresolved, "under_review": pending, "requires_federal": federal,
            "optional_open": optional_open, "resolved": resolved, "required_total": sum(1 for r in reqs.values() if r["required"])}


# ------------------------------------------------------------------ requests / corrections
def open_request(pas: dict[str, Any], cid: str, actor: str, at: str, *, kind: str, text: str, due_at: str = "", req_id: str = "",
                 responsible: str = "applicant") -> dict[str, Any]:
    c = _case(pas, cid)
    if kind not in REQUEST_KINDS:
        raise PasError(f"Unknown request kind {kind}.")
    if responsible not in ("applicant", "state", "federal"):
        raise PasError("responsible must be applicant, state or federal.")
    if not text.strip():
        raise PasError("Request text is required.")
    if req_id and req_id not in c["checklist"]:
        raise PasError(f"Unknown requirement {req_id}.")
    rid = f"{cid}-R{len(c['requests']) + 1}"
    r = {"id": rid, "kind": kind, "text": text.strip(), "req_id": req_id, "created_at": at, "created_by": actor, "due_at": due_at,
         "responsible": responsible, "responded_at": "", "response": "", "resolved_at": ""}
    c["requests"].append(r)
    if req_id and c["checklist"][req_id]["status"] == "Missing" and kind != "Correction":
        pass  # status stays Missing until evidence arrives; the request does not change a determination
    _emit(pas, actor, "pas.request_opened", cid, {"request_id": rid, "kind": kind, "req_id": req_id, "due_at": due_at})
    return r


def respond_request(pas: dict[str, Any], cid: str, actor: str, request_id: str, response: str, at: str) -> None:
    c = _case(pas, cid)
    r = next((x for x in c["requests"] if x["id"] == request_id), None)
    if r is None:
        raise PasError(f"Unknown request {request_id}.")
    if r["resolved_at"]:
        raise PasError("Request already resolved.")
    if not response.strip():
        raise PasError("A response is required.")
    r.update({"responded_at": at, "response": response.strip(), "responded_by": actor})
    _emit(pas, actor, "pas.request_responded", cid, {"request_id": request_id})


def resolve_request(pas: dict[str, Any], cid: str, actor: str, request_id: str, at: str) -> None:
    c = _case(pas, cid)
    r = next((x for x in c["requests"] if x["id"] == request_id), None)
    if r is None:
        raise PasError(f"Unknown request {request_id}.")
    if not r["responded_at"]:
        raise PasError("Cannot resolve a request that has no response.")
    r["resolved_at"] = at
    _emit(pas, actor, "pas.request_resolved", cid, {"request_id": request_id})


def open_requests(case: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in case["requests"] if not r["resolved_at"]]


def add_comment(pas: dict[str, Any], cid: str, actor: str, text: str, at: str) -> None:
    c = _case(pas, cid)
    if not text.strip():
        raise PasError("Comment text is required.")
    c["comments"].append({"at": at, "actor": actor, "text": text.strip()})
    _emit(pas, actor, "pas.comment", cid, {"length": len(text.strip())})


# ------------------------------------------------------------------ transitions and decisions
def transition(pas: dict[str, Any], cid: str, actor: str, to: str, at: str, note: str = "") -> None:
    c = _case(pas, cid)
    frm = c["stage"]
    if to not in STAGES:
        raise PasError(f"Unknown stage {to}.")
    if frm == "closed":
        raise PasError("A closed case cannot change stage.")
    if to == "closed" and frm not in ("monitoring", "federal_referral"):
        # withdrawal from any open stage is allowed but needs a reason
        if not note.strip():
            raise PasError("Closing a case before monitoring requires a reason.")
    elif to not in TRANSITIONS[frm]:
        raise PasError(f"Invalid transition {STAGE_LABEL[frm]} -> {STAGE_LABEL[to]}.")
    ready = evaluate_readiness(c)
    if to == "completeness_review" and frm == "state_intake" and not c["assigned_to"]:
        raise PasError("Assign a reviewer before completeness review.")
    if to == "technical_review" and any(i["status"] == "Missing" for i in ready["required_unresolved"]):
        raise PasError("Required items are still Missing. Resolve or request them (corrections) before technical review.")
    if to == "corrections" and not open_requests(c):
        raise PasError("Corrections need at least one open request describing what is wanted.")
    if to == "state_decision" and ready["overall"] != "ready":
        raise PasError(f"State decision needs a ready checklist (currently: {ready['overall'].replace('_', ' ')}).")
    if to == "monitoring" and not c["decision"] and not c["federal_referral"]:
        raise PasError("Monitoring starts after a recorded decision or a federal referral outcome.")
    if frm == "corrections" and to != "corrections" and open_requests(c):
        raise PasError("Open requests remain. Resolve them before leaving corrections.")
    c["stage"] = to
    c["history"].append({"at": at, "actor": actor, "from": frm, "to": to, "note": note})
    _emit(pas, actor, "pas.transition", cid, {"from": frm, "to": to, "note": note})


def record_decision(pas: dict[str, Any], cid: str, actor: str, outcome: str, rationale: str, at: str) -> None:
    """Record the state's administrative decision. Blocked when the state lacks delegated authority or a federal item is open."""
    c = _case(pas, cid)
    if c["stage"] != "state_decision":
        raise PasError("Decisions are recorded in the State decision stage.")
    if outcome not in DECISIONS:
        raise PasError(f"Unknown outcome {outcome}.")
    if not rationale.strip():
        raise PasError("A rationale is required.")
    if outcome == "recommend_approve":
        if not pas["config"]["delegation"].get("application_review"):
            raise PasError("Application review is not delegated in the PAS configuration. Refer to FEMA instead.")
        if evaluate_readiness(c)["requires_federal"]:
            raise PasError("An item requires a federal determination. Refer to FEMA instead.")
    stale = [{"req_id": s["req_id"], "days": s["days"]} for s in stale_items(c, at, pas["config"].get("stale_after_days", DEFAULT_STALE_DAYS))]
    c["decision"] = {"outcome": outcome, "label": DECISIONS[outcome], "rationale": rationale.strip(), "by": actor, "at": at, "stale_items_at_decision": stale,
                     "delegation": dict(pas["config"]["delegation"]), "guidance_version": pas["config"].get("guidance_version", "")}
    _emit(pas, actor, "pas.decision", cid, {"outcome": outcome, "stale_items": stale})


def refer_to_federal(pas: dict[str, Any], cid: str, actor: str, at: str, reason: str, reference: str = "") -> None:
    if not reason.strip():
        raise PasError("A referral reason is required.")
    transition(pas, cid, actor, "federal_referral", at, reason)
    _case(pas, cid)["federal_referral"] = {"referred_at": at, "by": actor, "reason": reason.strip(), "reference": reference, "returned_at": "", "outcome": ""}
    _emit(pas, actor, "pas.federal_referral", cid, {"reference": reference})


def record_federal_outcome(pas: dict[str, Any], cid: str, actor: str, outcome: str, at: str) -> None:
    c = _case(pas, cid)
    fr = c.get("federal_referral")
    if not fr or fr["returned_at"]:
        raise PasError("No open federal referral on this case.")
    if not outcome.strip():
        raise PasError("The federal outcome (as communicated by FEMA) is required.")
    fr.update({"returned_at": at, "outcome": outcome.strip(), "recorded_by": actor})
    _emit(pas, actor, "pas.federal_outcome", cid, {"outcome": outcome.strip()})


def add_milestone(pas: dict[str, Any], cid: str, actor: str, name: str, due_at: str) -> None:
    c = _case(pas, cid)
    if not name.strip() or not due_at:
        raise PasError("Milestone name and due date are required.")
    c["milestones"].append({"name": name.strip(), "due_at": due_at, "done_at": ""})
    _emit(pas, actor, "pas.milestone_added", cid, {"name": name.strip(), "due_at": due_at})


def complete_milestone(pas: dict[str, Any], cid: str, actor: str, name: str, at: str) -> None:
    c = _case(pas, cid)
    m = next((x for x in c["milestones"] if x["name"] == name and not x["done_at"]), None)
    if m is None:
        raise PasError("No open milestone with that name.")
    m["done_at"] = at
    _emit(pas, actor, "pas.milestone_done", cid, {"name": name})


# ------------------------------------------------------------------ derived status and metrics
def derived_status(case: dict[str, Any]) -> str:
    """Dashboard status, by this precedence: completed > federal referral > correction > awaiting documentation > ready > awaiting state."""
    st = case["stage"]
    if st in ("monitoring", "closed") or case["decision"]:
        return "Completed administrative review"
    if st == "federal_referral":
        return "Referred for federal review"
    if st == "corrections":
        return "Pending correction"
    if any(r["responsible"] == "applicant" and r["kind"] != "Correction" for r in open_requests(case)):
        return "Awaiting documentation"
    if st in ("completeness_review", "technical_review") and evaluate_readiness(case)["overall"] == "ready":
        return "Ready for internal review"
    return "Awaiting state action"


def stage_durations(case: dict[str, Any], now: str) -> list[dict[str, Any]]:
    """Days spent in each stage visit, from the status history. The open stage runs to ``now``."""
    h = case["history"]
    out = []
    for i, e in enumerate(h):
        end = h[i + 1]["at"] if i + 1 < len(h) else now
        if e["to"] == "closed":
            continue
        out.append({"stage": e["to"], "holder": STAGE_HOLDER.get(e["to"], "state"), "start": e["at"], "end": end,
                    "days": max(days_between(e["at"], end), 0.0), "open": i + 1 == len(h)})
    return out


def total_review_days(case: dict[str, Any], now: str) -> float | None:
    """Submission to the first completed-review point (decision, monitoring or close). None while still in progress."""
    done = None
    if case["decision"]:
        done = case["decision"]["at"]
    for e in case["history"]:
        if e["to"] in ("monitoring", "closed"):
            done = done if done and done <= e["at"] else e["at"]
            break
    return days_between(case["submitted_at"], done) if done else None


def overdue_items(pas: dict[str, Any], now: str) -> list[dict[str, Any]]:
    out = []
    for c in pas["cases"].values():
        if c["stage"] == "closed":
            continue
        for m in c["milestones"]:
            if not m["done_at"] and m["due_at"] and m["due_at"] < now:
                out.append({"case": c["id"], "kind": "milestone", "label": m["name"], "due_at": m["due_at"], "days_over": days_between(m["due_at"], now)})
        for r in open_requests(c):
            if r["due_at"] and r["due_at"] < now and not r["responded_at"]:
                out.append({"case": c["id"], "kind": "request", "label": f"{r['kind']}: {r['text'][:60]}", "due_at": r["due_at"],
                            "days_over": days_between(r["due_at"], now), "responsible": r["responsible"]})
        if c["due_at"] and c["due_at"] < now and derived_status(c) != "Completed administrative review":
            out.append({"case": c["id"], "kind": "case deadline", "label": "Review deadline", "due_at": c["due_at"], "days_over": days_between(c["due_at"], now)})
    return sorted(out, key=lambda x: -x["days_over"])


def filter_cases(pas: dict[str, Any], *, jurisdiction: str = "", hazard: str = "", program: str = "", status: str = "", reviewer: str = "",
                 submitted_from: str = "", submitted_to: str = "", text: str = "") -> list[dict[str, Any]]:
    out = []
    t = text.strip().lower()
    for c in pas["cases"].values():
        if jurisdiction and c["jurisdiction"] != jurisdiction:
            continue
        if hazard and c["hazard"] != hazard:
            continue
        if program and c["program"] != program:
            continue
        if status and derived_status(c) != status:
            continue
        if reviewer and c["assigned_to"] != reviewer:
            continue
        if submitted_from and c["submitted_at"][:10] < submitted_from:
            continue
        if submitted_to and c["submitted_at"][:10] > submitted_to:
            continue
        if t and t not in " ".join([c["id"], c["project_id"], c["subapplicant"], c["jurisdiction"], c["hazard"]]).lower():
            continue
        out.append(c)
    return sorted(out, key=lambda c: c["id"])


def metrics(cases: list[dict[str, Any]], pas: dict[str, Any], now: str) -> dict[str, Any]:
    """Every figure here is computed from case records and timestamps. Nothing is estimated."""
    by_status = {s: 0 for s in DASHBOARD_STATUSES}
    for c in cases:
        by_status[derived_status(c)] += 1
    finished = [d for d in (total_review_days(c, now) for c in cases) if d is not None]
    workload: dict[str, int] = {}
    for c in cases:
        if c["stage"] not in ("closed", "monitoring") and not c["decision"]:
            workload[c["assigned_to"] or "(unassigned)"] = workload.get(c["assigned_to"] or "(unassigned)", 0) + 1
    ids = {c["id"] for c in cases}
    by_stage: dict[str, list[float]] = {}
    by_holder: dict[str, float] = {"applicant": 0.0, "state": 0.0, "federal": 0.0}
    for c in cases:
        for d in stage_durations(c, now):
            by_stage.setdefault(d["stage"], []).append(d["days"])
            by_holder[d["holder"]] += d["days"]
    stage_stats = {s: {"visits": len(v), "mean_days": round(sum(v) / len(v), 1), "median_days": round(statistics.median(v), 1), "max_days": round(max(v), 1)}
                   for s, v in by_stage.items()}
    corrections: dict[str, int] = {}
    for c in cases:
        for r in c["requests"]:
            if r["req_id"]:
                corrections[r["req_id"]] = corrections.get(r["req_id"], 0) + 1
    repeated = {k: v for k, v in corrections.items() if v >= 2}
    open_cases = [c for c in cases if c["stage"] != "closed" and derived_status(c) != "Completed administrative review"]
    wait_initial = [days_between(c["submitted_at"], now) for c in open_cases if c["stage"] in ("submission", "state_intake")]
    return {
        "total": len(cases), "by_status": by_status,
        "avg_review_days": round(sum(finished) / len(finished), 1) if finished else None,
        "median_review_days": round(statistics.median(finished), 1) if finished else None, "completed_n": len(finished),
        "overdue": [o for o in overdue_items(pas, now) if o["case"] in ids],
        "workload": workload, "stage_stats": stage_stats,
        "slowest_stage": max(stage_stats, key=lambda s: stage_stats[s]["mean_days"]) if stage_stats else None,
        "days_by_holder": {k: round(v, 1) for k, v in by_holder.items()},
        "returned_count": sum(1 for c in cases if any(h["to"] == "corrections" for h in c["history"])),
        "incomplete_count": sum(1 for c in cases if evaluate_readiness(c)["overall"] == "blocked"),
        "repeated_deficiencies": repeated,
        "avg_wait_for_initial_review_days": round(sum(wait_initial) / len(wait_initial), 1) if wait_initial else None,
        "due_within_14_days": sum(1 for c in open_cases if c["due_at"] and now <= c["due_at"] <= _plus_days(now, 14)),
    }


def _plus_days(iso: str, n: int) -> str:
    from datetime import timedelta
    return (_dt(iso) + timedelta(days=n)).isoformat(timespec="seconds")


def capacity_notes(m: dict[str, Any]) -> list[str]:
    """Plain-language observations that the numbers support. Deliberately never says 'staff shortage'."""
    notes = []
    h = m["days_by_holder"]
    total = sum(h.values())
    if total > 0:
        top = max(h, key=lambda k: h[k])
        notes.append(f"Most recorded waiting time sits with the {top} ({h[top]} of {round(total, 1)} case-days).")
    if m["slowest_stage"]:
        s = m["stage_stats"][m["slowest_stage"]]
        notes.append(f"Slowest stage by mean duration: {STAGE_LABEL[m['slowest_stage']]} ({s['mean_days']} days over {s['visits']} visits).")
    if m["repeated_deficiencies"]:
        notes.append("Repeated deficiencies: " + ", ".join(f"{k} ({v}x)" for k, v in sorted(m["repeated_deficiencies"].items())) + ".")
    if not notes:
        notes.append("Not enough timestamped records yet to say where time is spent.")
    notes.append("Pending counts alone do not show whether staffing is short; compare against stage durations and who holds each case.")
    return notes


# ------------------------------------------------------------------ bulk import
IMPORT_FIELDS = ["project_id", "jurisdiction", "program", "submitted_at"]


def import_cases(pas: dict[str, Any], actor: str, rows: list[dict[str, str]], known_projects: set[str]) -> dict[str, Any]:
    """Validate and create cases from CSV rows. Each bad row is reported with its line number; good rows are still created."""
    created, errors = [], []
    for i, row in enumerate(rows, start=2):
        row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
        missing = [f for f in IMPORT_FIELDS if not row.get(f)]
        if missing:
            errors.append({"line": i, "error": f"Missing required field(s): {', '.join(missing)}"})
            continue
        if row["project_id"] not in known_projects:
            errors.append({"line": i, "error": f"Unknown project_id {row['project_id']}"})
            continue
        try:
            _dt(row["submitted_at"])
            if row.get("due_at"):
                _dt(row["due_at"])
        except ValueError:
            errors.append({"line": i, "error": "submitted_at/due_at must be ISO dates, e.g. 2026-03-15"})
            continue
        try:
            c = create_case(pas, actor, project_id=row["project_id"], jurisdiction=row["jurisdiction"], program=row["program"],
                            hazard=row.get("hazard", ""), subapplicant=row.get("subapplicant", ""), submitted_at=row["submitted_at"],
                            due_at=row.get("due_at", ""))
            created.append(c["id"])
        except PasError as e:
            errors.append({"line": i, "error": str(e)})
    return {"created": created, "errors": errors}
