import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import civicsignal as cs

ALL = {r["id"]: 1 for r in cs.RULES}
W = {k: d for k, _, d, _ in cs.CRITERIA}
TODAY = "2026-10-07"


def proj(i):
    return next(p for p in cs.PROJECTS if p["id"] == i)


def test_unpublished_rules_never_pass():
    assert cs.evaluate_project(proj("p1"), {}, TODAY)["overall"] == "review"


def test_outcomes_when_published():
    got = {p["id"]: cs.evaluate_project(p, ALL, TODAY)["overall"] for p in cs.PROJECTS if p["program"] == "FMA"}
    assert got == {"p1": "pass", "p2": "review", "p5": "fail", "p8": "review", "p9": "fail"}


def test_hmgp_projects_are_now_evaluated():
    """Regression for the removed 'no HMGP rules yet' dead end (Phase 1.5)."""
    e = cs.evaluate_project(proj("p3"), ALL, TODAY)
    assert e is not None and e["overall"] == "pass"
    assert {o["rule"]["id"] for o in e["outs"]} == {r["id"] for r in cs.rules_for("HMGP")}


def test_unknown_entity_type_is_review_not_fail_or_pass():
    s = dict(proj("p1")["sponsor"], type="mystery")
    assert cs.eval_rule("fma.eligible_entity_type", s, TODAY)[0] == "review"


def test_plan_without_expiry_needs_review():
    s = dict(proj("p1")["sponsor"], expires="")
    assert cs.eval_rule("fma.hazard_mitigation_plan", s, TODAY)[0] == "review"


def test_funded_line_stops_at_first_miss():
    rk = cs.ranked(cs.PROJECTS, W, ALL, TODAY)
    within, spend = cs.funded_line(rk, 4.0)
    order = [r["p"]["id"] for r in rk if r["e"] is None or r["e"]["overall"] != "fail"]
    seen_miss = False
    for pid in order:
        if pid in within:
            assert not seen_miss
        else:
            seen_miss = True
    assert spend <= 4.0


def test_chain_verifies_then_detects_tamper_and_restore():
    s = cs.new_state(); cs.init_outcomes(s)
    cs.publish_rules(s, list(ALL), "Pat")
    ok, _ = cs.decide(s, "p1", "approved", "ranked first, eligible", "Pat", W, 4.0)
    assert ok
    assert cs.verify_chain(s["audit"])[0]
    cs.tamper(s)
    assert not cs.verify_chain(s["audit"])[0]
    cs.restore(s)
    assert cs.verify_chain(s["audit"])[0]


def test_cannot_approve_ineligible_and_reason_required():
    s = cs.new_state(); cs.init_outcomes(s); cs.publish_rules(s, list(ALL), "Pat")
    assert not cs.decide(s, "p5", "approved", "x", "Pat", W, 4.0)[0]
    assert not cs.decide(s, "p1", "approved", "  ", "Pat", W, 4.0)[0]
    assert cs.decide(s, "p5", "held", "plan expired", "Pat", W, 4.0)[0]


def test_fact_change_rechecks_and_logs_once():
    s = cs.new_state(); cs.init_outcomes(s); cs.publish_rules(s, list(ALL), "Pat")
    n = len(s["audit"])
    assert cs.save_facts(s, "p2", {"nfip": "participating"}, "Pat")[0]
    assert cs.evaluate_project(next(p for p in s["projects"] if p["id"] == "p2"), s["published"], TODAY)["overall"] == "pass"
    assert len(s["audit"]) == n + 2  # facts_updated + determination change
    assert not cs.save_facts(s, "p2", {"nfip": "participating"}, "Pat")[0]


def test_module_data_not_mutated_by_state():
    s = cs.new_state(); cs.save_facts(s, "p2", {"nfip": "participating"}, "Pat")
    assert proj("p2")["sponsor"]["nfip"] == "unknown"
