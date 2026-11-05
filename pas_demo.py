"""Clearly labelled DEMO records for the PAS Review Center. Pure. Every case is flagged ``demo=True`` and the UI says so.

These are built by calling the real engine functions with relative timestamps, so they exercise the same guards and audit events as live
data. They describe invented applications on the invented CivicSignal sample projects, never real submissions.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import pas_engine as pe
import pas_rules

COUNTIES = ["Cook", "DuPage", "Kane", "Kendall", "Lake", "McHenry", "Will"]


def _t(now: str, days_ago: float) -> str:
    return (pe._dt(now) - timedelta(days=days_ago)).isoformat(timespec="seconds")


def _verify_all(pas: dict[str, Any], cid: str, actor: str, at: str, skip: tuple[str, ...] = ()) -> None:
    c = pas["cases"][cid]
    for rid in c["checklist"]:
        if rid in skip:
            continue
        r = next(x for x in pas_rules.requirements_for(c["program"]) if x["id"] == rid)
        if r["authority"] == "federal":
            pe.set_item(pas, cid, actor, rid, "Verified", at, evidence=[f"DEMO-{rid}.pdf"])
        else:
            pe.set_item(pas, cid, actor, rid, "Verified", at, evidence=[f"DEMO-{rid}.pdf"])


def load_demo(pas: dict[str, Any], actor: str, projects: dict[str, dict[str, Any]], now: str) -> list[str]:
    """Create up to six demo cases from the given projects (id -> project dict). Returns the new case ids."""
    pe.set_delegation(pas, actor, {"application_review": True, "bca_review": False, "grant_management": False, "financial_management": False,
                                   "planning": False}, disaster="DEMO-DR-0000", agreement_ref="DEMO operational agreement (invented)",
                       guidance_version="DEMO - set to the guide version in force")
    ids = []
    plan = [  # project, county, submitted days ago, scenario
        ("p1", 0, 60, "decided"), ("p2", 1, 45, "corrections"), ("p3", 2, 30, "ready"), ("p4", 3, 50, "federal"),
        ("p5", 4, 12, "intake"), ("p6", 5, 5, "new")]
    for pid, ci, ago, scenario in plan:
        if pid not in projects:
            continue
        p = projects[pid]
        sub = _t(now, ago)
        c = pe.create_case(pas, actor, project_id=pid, jurisdiction=COUNTIES[ci], program=p["program"], hazard=p.get("hazard", ""),
                           subapplicant=(p.get("sponsor") or {}).get("name", ""), submitted_at=sub, due_at=_t(now, ago - 75), demo=True)
        cid = c["id"]
        ids.append(cid)
        if scenario == "new":
            continue
        pe.transition(pas, cid, actor, "state_intake", _t(now, ago - 2))
        pe.assign(pas, cid, actor, "reviewer.a@example.org" if ci % 2 == 0 else "reviewer.b@example.org", _t(now, ago - 3))
        if scenario == "intake":
            continue
        pe.transition(pas, cid, actor, "completeness_review", _t(now, ago - 6))
        if scenario == "corrections":
            pe.set_item(pas, cid, actor, "bca", "Incomplete", _t(now, ago - 8), note="Inputs do not match scope")
            pe.open_request(pas, cid, actor, _t(now, ago - 9), kind="Correction", text="Resubmit BCA with corrected inputs", req_id="bca",
                            due_at=_t(now, ago - 25))
            pe.transition(pas, cid, actor, "corrections", _t(now, ago - 9))
            continue
        _verify_all(pas, cid, actor, _t(now, ago - 10), skip=("ehp",) if scenario == "federal" else ())
        if scenario == "federal":
            pe.set_item(pas, cid, actor, "ehp", "Requires federal determination", _t(now, ago - 10), note="EHP review rests with FEMA")
        pe.transition(pas, cid, actor, "technical_review", _t(now, ago - 11))
        if scenario == "ready":
            continue
        if scenario == "federal":
            pe.refer_to_federal(pas, cid, actor, _t(now, ago - 20), "EHP and plan status need FEMA determination", reference="DEMO-REF-1")
            continue
        pe.transition(pas, cid, actor, "state_decision", _t(now, ago - 25))
        pe.record_decision(pas, cid, actor, "recommend_approve", "All required items verified with evidence (demo).", _t(now, ago - 28))
        pe.transition(pas, cid, actor, "monitoring", _t(now, ago - 29))
    return ids
