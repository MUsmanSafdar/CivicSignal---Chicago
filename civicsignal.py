"""CivicSignal: prioritization, fail-closed eligibility rules, hash-chained audit trail.

Everything here is a prototype on INVENTED sample data. Eligibility rules cite real FEMA
regulations but are not legal advice. The engine functions are pure so they can be tested
without Streamlit; render() is the Streamlit page.
"""
import copy
import hashlib
import json
from datetime import date, datetime, timezone

GENESIS = "0" * 64

CRITERIA = [
    ("risk", "Hazard risk", 30, "FEMA National Risk Index (sample values)"),
    ("vul", "Social vulnerability", 25, "CDC/ATSDR Social Vulnerability Index (sample values)"),
    ("loss", "Past losses", 20, "OpenFEMA and NFIP claims history (sample values)"),
    ("bcr", "Benefit-cost", 15, "FEMA BCA Toolkit output (sample values)"),
    ("ready", "Readiness", 10, "Applicant-supplied design status and local match (sample values)"),
]


def _sp(name, type_, nfip, plan, expires=""):
    return {"name": name, "type": type_, "nfip": nfip, "plan": plan, "expires": expires}


def _p(id_, name, hazard, program, cost, risk, vul, loss, bcr, ready, sponsor):
    return {"id": id_, "name": name, "hazard": hazard, "program": program, "cost": cost,
            "risk": risk, "vul": vul, "loss": loss, "bcr": bcr, "ready": ready, "sponsor": sponsor}


PROJECTS = [
    _p("p1", "Elevate 14 repetitive-loss homes, Riverbend", "Flood", "FMA", 1.9, 88, 74, 95, 72, 60, _sp("Sample County", "local_government", "participating", "fema_approved", "2028-03-01")),
    _p("p2", "Upsize culverts, Mill Creek Road", "Flood", "FMA", 1.2, 80, 55, 70, 85, 80, _sp("Sample County Highway Dept.", "local_government", "unknown", "fema_approved", "2028-03-01")),
    _p("p3", "Community safe room, Eastside Center", "Tornado", "HMGP", 0.9, 70, 82, 30, 58, 75, _sp("City of Eastside", "local_government", "participating", "fema_approved", "2027-06-30")),
    _p("p4", "Storm siren network expansion", "Tornado", "HMGP", 0.5, 66, 60, 25, 64, 90, _sp("Sample County EMA", "local_government", "participating", "fema_approved", "2028-03-01")),
    _p("p5", "Buy out 6 parcels, Oak Hollow", "Flood", "FMA", 1.4, 92, 68, 90, 78, 45, _sp("Village of Oak Hollow", "local_government", "participating", "fema_approved", "2025-11-30")),
    _p("p6", "Backup generator, county water plant", "Power loss", "HMGP", 0.8, 60, 50, 40, 66, 85, _sp("Sample County Water District", "special_district", "participating", "fema_approved", "2028-03-01")),
    _p("p7", "Wind retrofit, Memorial Hospital roof", "Wind", "HMGP", 1.1, 58, 62, 35, 40, 70, _sp("Memorial Hospital District", "special_district", "participating", "fema_approved", "2028-03-01")),
    _p("p8", "Detention basin, Pine Street", "Flood", "FMA", 2.2, 74, 48, 65, 52, 50, _sp("Pine Creek Drainage District", "special_district", "participating", "fema_approved", "2027-09-15")),
    _p("p9", "Drainage fix, Lakeview manufactured-home park", "Flood", "FMA", 0.7, 72, 90, 60, 70, 65, _sp("Lakeview Residents Association", "nonprofit", "participating", "fema_approved", "2028-03-01")),
    _p("p10", "Dam spillway study (planning)", "Dam failure", "HMGP", 0.3, 54, 40, 20, 35, 95, _sp("Sample County", "local_government", "participating", "fema_approved", "2028-03-01")),
]

RULES = [
    {"id": "fma.nfip_participation", "title": "NFIP participation", "cite": "44 CFR 77.6(a)(1)",
     "url": "https://www.law.cornell.edu/cfr/text/44/77.6",
     "text": "States, Indian Tribal governments, and communities must be participating in the NFIP and may not be suspended or withdrawn under the program."},
    {"id": "fma.hazard_mitigation_plan", "title": "FEMA-approved hazard mitigation plan", "cite": "44 CFR 77.6(b)",
     "url": "https://www.law.cornell.edu/cfr/text/44/77.6",
     "text": "Applicants and subapplicants must have a FEMA-approved mitigation plan under 44 CFR Part 201."},
    {"id": "fma.eligible_entity_type", "title": "Eligible subapplicant type", "cite": "44 CFR 77.2(m)",
     "url": "https://www.law.cornell.edu/cfr/text/44/77.2",
     "text": "A subapplicant is a State agency, community, or Indian Tribal government. Private nonprofits are not eligible subapplicants. A \u201ccommunity\u201d is defined at 77.2(d)."},
]

ENTITY_LABEL = {"state": "State agency", "local_government": "Local government", "tribal_government": "Tribal government",
                "territory": "Territory", "special_district": "Special district", "nonprofit": "Private nonprofit", "unknown": "Not on file"}
NFIP_LABEL = {"participating": "Participating", "suspended": "Suspended", "withdrawn": "Withdrawn",
              "not_participating": "Not participating", "unknown": "Not on file"}
PLAN_LABEL = {"fema_approved": "FEMA-approved", "expired": "Expired", "not_on_file": "None on file", "unknown": "Not on file"}

# Real Grants.gov entries captured by the tracker, Aug-Sep 2026: (id, title, agency, first_seen, relevant)
OPPS = [(354620, 'Fiscal Year 2024 Flood Mitigation Assistance Swift Current', 'DHS', '2026-08-13', True), (363151, 'Fiscal Year 2026 Flood Mitigation Assistance Swift Current', 'DHS', '2026-08-13', True), (363117, 'Fiscal Year 2026 National Earthquake Hazards Reduction Program Individual State Earthquake Assistance', 'DHS', '2026-08-13', True), (363128, 'Fiscal Year 2026 National Earthquake Hazards Reduction Program Multi-State and National Earthquake Assistance', 'DHS', '2026-08-13', True), (306169, 'Engineering for Civil Infrastructure', 'NSF', '2026-08-13', False), (356561, 'RESTORE Act Direct Component - Non-Construction Activities', 'USDOT', '2026-08-13', False), (356562, 'RESTORE Act Direct Component – Construction and Real Property Acquisition Activities', 'USDOT', '2026-08-13', False), (363334, 'FY26 Bureau of Land Management Abandoned Mine Lands and Hazardous Materials - Bureau wide', 'DOI', '2026-08-13', False), (357579, 'Water, Landscape, and Critical Zone Processes', 'NSF', '2026-08-13', False), (362368, 'Healthy Homes Production Grant Program', 'HUD', '2026-08-14', False), (362367, 'Lead Hazard Reduction Grant Program', 'HUD', '2026-08-14', False), (363318, 'National Disaster Coverage Training for Indonesian Journalists', 'State Dept.', '2026-08-20', False), (363699, 'F26AS00105 National Fish Passage Program', 'DOI', '2026-09-19', False), (334971, 'Commercial Fishing Occupational Safety Research Cooperative Agreement (U01)', 'HHS-CDC', '2026-09-19', False), (103313, 'Climate Program Office for FY 2012', 'DOC', '2026-09-19', False), (349858, 'DRAFT Community Noise Mitigation Program', 'DOD', '2026-09-27', False)]


# ---------------------------------------------------------------- eligibility engine
def eval_rule(rule_id, s, today=None):
    """Return (outcome, reason). Outcome is 'pass', 'fail' or 'review'. Unknown facts never pass."""
    today = today or date.today().isoformat()
    n = s["name"]
    if rule_id == "fma.nfip_participation":
        st = s.get("nfip", "unknown")
        if st == "participating":
            return "pass", f"{n} is recorded as participating in the NFIP."
        if st in ("suspended", "withdrawn", "not_participating"):
            return "fail", f"{n} has NFIP status \u201c{NFIP_LABEL[st].lower()}\u201d, which fails the participation requirement."
        return "review", f"NFIP status for {n} is not on file. Verify it in FEMA\u2019s Community Status Book. This is a hold, not a denial."
    if rule_id == "fma.hazard_mitigation_plan":
        plan, exp = s.get("plan", "unknown"), s.get("expires", "")
        if plan == "fema_approved":
            if not exp:
                return "review", f"A FEMA-approved plan is recorded for {n} but no expiry date is on file. Confirm the plan is current."
            if exp < today:
                return "fail", f"{n}\u2019s plan expired on {exp}. An approved, current plan is required."
            return "pass", f"{n} has a FEMA-approved plan on file, expiring {exp}."
        if plan in ("expired", "not_on_file"):
            return "fail", f"{n}\u2019s plan status is \u201c{PLAN_LABEL[plan].lower()}\u201d. An approved plan is required."
        return "review", f"Plan status for {n} is not on file. This is a hold, not a denial."
    if rule_id == "fma.eligible_entity_type":
        t = s.get("type") or "unknown"
        if t in ("state", "local_government", "tribal_government"):
            return "pass", f"{n} ({ENTITY_LABEL[t].lower()}) is within the eligible subapplicant types."
        if t in ("territory", "special_district"):
            return "review", (f"A {ENTITY_LABEL[t].lower()} is not named in the definition. Whether it counts as a \u201ccommunity\u201d depends on "
                              "zoning and building-code authority over a flood hazard area. A reviewer must confirm.")
        if t == "unknown":
            return "review", f"Entity type for {n} is not on file. This is a hold, not a denial."
        if t == "nonprofit":
            return "fail", (f"{n} ({ENTITY_LABEL[t].lower()}) is not a State agency, community, or Tribal government. Private nonprofits are not "
                            "eligible subapplicants. A county or city could sponsor the project instead.")
    # fail closed: a type or rule we do not recognise is never a pass
    return "review", "This value or rule is not recognised, so a reviewer must decide."


def evaluate_project(p, published, today=None):
    """FMA projects only (no HMGP rules yet). Unpublished rules always give 'review'. Any fail wins, then any review."""
    if p["program"] != "FMA":
        return None
    outs = []
    for r in RULES:
        if r["id"] not in published:
            outs.append({"rule": r, "out": "review", "why": "This rule has not been approved for use by a reviewer yet. No determination can be made against it."})
        else:
            o, w = eval_rule(r["id"], p["sponsor"], today)
            outs.append({"rule": r, "out": o, "why": w})
    kinds = [o["out"] for o in outs]
    overall = "fail" if "fail" in kinds else "review" if "review" in kinds else "pass"
    return {"overall": overall, "outs": outs}


# ---------------------------------------------------------------- scoring
def score_of(p, weights):
    tw = sum(weights.values())
    return sum(p[k] * weights[k] for k, *_ in CRITERIA) / tw if tw else 0.0


def ranked(projects, weights, published, today=None):
    rows = [{"p": p, "s": score_of(p, weights), "e": evaluate_project(p, published, today)} for p in projects]
    return sorted(rows, key=lambda r: (-r["s"], r["p"]["cost"]))


def funded_line(rk, budget):
    """Walk the ranking in order, skipping ineligible (failed) projects; stop at the first one that does not fit."""
    cum, cut, within = 0.0, False, set()
    for r in rk:
        if r["e"] and r["e"]["overall"] == "fail":
            continue
        if cut:
            continue
        if cum + r["p"]["cost"] <= budget + 1e-9:
            cum += r["p"]["cost"]
            within.add(r["p"]["id"])
        else:
            cut = True
    return within, cum


# ---------------------------------------------------------------- audit chain
def canon(v):
    """Canonical JSON: sorted keys, no whitespace, so the hash is stable."""
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _body(e):
    return {k: e[k] for k in ("prev", "actor", "action", "resourceType", "resourceId", "detail", "at")}


def hash_event(body):
    return hashlib.sha256(canon(body).encode("utf-8")).hexdigest()


def append_event(audit, actor, action, resource_type, resource_id, detail):
    prev = audit[-1]["hash"] if audit else GENESIS
    body = {"prev": prev, "actor": actor, "action": action, "resourceType": resource_type, "resourceId": resource_id,
            "detail": detail, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    audit.append({"n": len(audit) + 1, "hash": hash_event(body), **body})


def verify_chain(audit):
    """Return (ok, message)."""
    expected = GENESIS
    for e in audit:
        if e["prev"] != expected:
            return False, f"Chain break at entry #{e['n']}: it does not link to the entry before it."
        if hash_event(_body(e)) != e["hash"]:
            return False, f"Alteration detected at entry #{e['n']}: its contents no longer match its fingerprint."
        expected = e["hash"]
    return True, f"Chain is intact: all {len(audit)} entries verify."


# ---------------------------------------------------------------- state helpers (pure, used by the page)
def new_state():
    return {"projects": copy.deepcopy(PROJECTS), "published": {}, "decisions": {}, "audit": [], "last_outcome": {}, "tampered": None}


def record_determination_changes(st_):
    for p in st_["projects"]:
        e = evaluate_project(p, st_["published"])
        if e and st_["last_outcome"].get(p["id"]) != e["overall"]:
            frm = st_["last_outcome"].get(p["id"])
            st_["last_outcome"][p["id"]] = e["overall"]
            append_event(st_["audit"], "system:eligibility-engine", "eligibility.determination.created", "project", p["id"],
                         {"project": p["name"], "from": frm, "overall": e["overall"],
                          "rules": [{"rule": o["rule"]["id"], "outcome": o["out"]} for o in e["outs"]]})


def init_outcomes(st_):
    for p in st_["projects"]:
        e = evaluate_project(p, st_["published"])
        if e:
            st_["last_outcome"][p["id"]] = e["overall"]


def publish_rules(st_, ids, reviewer):
    for rid in ids:
        if rid not in st_["published"]:
            st_["published"][rid] = {"by": reviewer, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            append_event(st_["audit"], f"user:{reviewer}", "rule.published", "rule", rid, {"reviewer": reviewer})
    record_determination_changes(st_)


def decide(st_, project_id, action, note, actor, weights, budget):
    p = next(x for x in st_["projects"] if x["id"] == project_id)
    if not note.strip():
        return False, "Add a short reason first. The decision stays with you, and the record shows why."
    e = evaluate_project(p, st_["published"])
    if action == "approved" and e and e["overall"] != "pass":
        return False, "This project isn\u2019t eligible to approve yet."
    rk = ranked(st_["projects"], weights, st_["published"])
    rank = next(i + 1 for i, r in enumerate(rk) if r["p"]["id"] == project_id)
    st_["decisions"][project_id] = {"action": action, "note": note.strip()}
    append_event(st_["audit"], f"user:{actor}", f"project.decision.{action}", "project", project_id,
                 {"project": p["name"], "note": note.strip(), "rank": rank, "score": round(score_of(p, weights), 1),
                  "eligibility": e["overall"] if e else "not_checked", "weights": dict(weights), "budget_millions": budget})
    return True, "Approval recorded." if action == "approved" else "Hold recorded."


def save_facts(st_, project_id, new, actor):
    p = next(x for x in st_["projects"] if x["id"] == project_id)
    before = dict(p["sponsor"])
    after = {**before, **new}
    if before == after:
        return False, "No changes to save."
    p["sponsor"] = after
    append_event(st_["audit"], f"user:{actor or 'unnamed'}", "applicant.facts_updated", "project", project_id,
                 {"project": p["name"], "before": before, "after": dict(after)})
    record_determination_changes(st_)
    return True, "Facts saved and eligibility re-checked."


def tamper(st_):
    if st_["audit"] and not st_["tampered"]:
        e = st_["audit"][0]
        st_["tampered"] = copy.deepcopy(e["detail"])
        e["detail"] = {**e["detail"], "edited": True}


def restore(st_):
    if st_["tampered"] is not None:
        st_["audit"][0]["detail"] = st_["tampered"]
        st_["tampered"] = None
