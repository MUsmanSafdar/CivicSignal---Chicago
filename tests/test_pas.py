"""PAS Review Center: engine rules, metrics from timestamps, persistence on the shared audit chain, packet, UI permissions."""
import csv
import io
import sys
import types
from unittest.mock import MagicMock

import pytest

import audit_store
import civicsignal as cs
import identity as ident
import pas_demo
import pas_engine as pe
import pas_packet
import pas_rules
import pas_store

NOW = "2026-10-31T12:00:00+00:00"
A = "user:rev@x.gov"


def t(day):  # day 1..: 2026-10-<day>
    return f"2026-10-{day:02d}T12:00:00+00:00"


def mk(program="HMGP", pid="p1", sub=t(1), due=""):
    pas = pe.new_pas()
    c = pe.create_case(pas, A, project_id=pid, jurisdiction="Cook", program=program, hazard="Flood", submitted_at=sub, due_at=due)
    return pas, c["id"]


def verify_all(pas, cid, at=t(3)):
    for rid in pas["cases"][cid]["checklist"]:
        pe.set_item(pas, cid, A, rid, "Verified", at, evidence=["doc.pdf"])


def to_technical(pas, cid):
    pe.transition(pas, cid, A, "state_intake", t(2))
    pe.assign(pas, cid, A, "r1", t(2))
    pe.transition(pas, cid, A, "completeness_review", t(3))
    verify_all(pas, cid)
    pe.transition(pas, cid, A, "technical_review", t(4))


# ---- checklist
def test_requirements_vary_by_program():
    h = {r["id"] for r in pas_rules.requirements_for("HMGP")}
    f = {r["id"] for r in pas_rules.requirements_for("FMA")}
    assert "nfip_good_standing" in f and "nfip_good_standing" not in h


def test_every_requirement_cites_a_source_and_flags_unconfirmed():
    for r in pas_rules.requirements_for("FMA"):
        assert r["source_title"] and r["source_type"] in {"federal_regulation", "program_guidance", "state_procedure", "recommendation"}
    assert any(not r["confirmed"] for r in pas_rules.requirements_for("HMGP"))


def test_verified_requires_evidence():
    pas, cid = mk()
    with pytest.raises(pe.PasError, match="evidence"):
        pe.set_item(pas, cid, A, "bca", "Verified", t(2))


def test_not_applicable_needs_reason():
    pas, cid = mk()
    with pytest.raises(pe.PasError, match="reason"):
        pe.set_item(pas, cid, A, "bca", "Not applicable", t(2))


def test_readiness_is_not_a_percentage_and_separates_optional():
    pas, cid = mk()
    c = pas["cases"][cid]
    r = pe.evaluate_readiness(c)
    assert r["overall"] == "blocked" and r["required_unresolved"] and r["optional_open"]
    for x in r["required_unresolved"]:
        pe.set_item(pas, cid, A, x["id"], "Verified", t(2), evidence=["e"])
    assert pe.evaluate_readiness(c)["overall"] == "ready"  # optional items still open


def test_federal_item_blocks_ready_and_state_recommendation():
    pas, cid = mk()
    pe.set_delegation(pas, A, {"application_review": True})
    to_technical(pas, cid)
    pe.set_item(pas, cid, A, "ehp", "Requires federal determination", t(5), note="FEMA")
    assert pe.evaluate_readiness(pas["cases"][cid])["overall"] == "federal_determination_needed"
    with pytest.raises(pe.PasError):
        pe.transition(pas, cid, A, "state_decision", t(6))


def test_missing_required_blocks_technical_review():
    pas, cid = mk()
    pe.transition(pas, cid, A, "state_intake", t(2))
    pe.assign(pas, cid, A, "r1", t(2))
    pe.transition(pas, cid, A, "completeness_review", t(3))
    with pytest.raises(pe.PasError, match="Missing"):
        pe.transition(pas, cid, A, "technical_review", t(4))


# ---- workflow
def test_invalid_transition_rejected():
    pas, cid = mk()
    with pytest.raises(pe.PasError, match="Invalid transition"):
        pe.transition(pas, cid, A, "technical_review", t(2))


def test_closed_case_is_final():
    pas, cid = mk()
    pe.transition(pas, cid, A, "closed", t(2), "Withdrawn by applicant")
    with pytest.raises(pe.PasError):
        pe.transition(pas, cid, A, "state_intake", t(3))
    with pytest.raises(pe.PasError):
        pe.set_item(pas, cid, A, "bca", "Missing", t(3))


def test_withdrawal_needs_reason():
    pas, cid = mk()
    with pytest.raises(pe.PasError, match="reason"):
        pe.transition(pas, cid, A, "closed", t(2))


def test_assignment_required_before_completeness():
    pas, cid = mk()
    pe.transition(pas, cid, A, "state_intake", t(2))
    with pytest.raises(pe.PasError, match="reviewer"):
        pe.transition(pas, cid, A, "completeness_review", t(3))


def test_duplicate_open_case_rejected_but_allowed_after_close():
    pas, cid = mk()
    with pytest.raises(pe.PasError, match="already has an open"):
        pe.create_case(pas, A, project_id="p1", jurisdiction="Cook", program="HMGP", submitted_at=t(2))
    pe.transition(pas, cid, A, "closed", t(2), "withdrawn")
    pe.create_case(pas, A, project_id="p1", jurisdiction="Cook", program="HMGP", submitted_at=t(3))


def test_corrections_cycle_needs_requests_and_resolution():
    pas, cid = mk()
    pe.transition(pas, cid, A, "state_intake", t(2))
    pe.assign(pas, cid, A, "r1", t(2))
    pe.transition(pas, cid, A, "completeness_review", t(3))
    with pytest.raises(pe.PasError, match="open request"):
        pe.transition(pas, cid, A, "corrections", t(4))
    r = pe.open_request(pas, cid, A, t(4), kind="Correction", text="Fix BCA", req_id="bca", due_at=t(10))
    pe.transition(pas, cid, A, "corrections", t(4))
    with pytest.raises(pe.PasError, match="Open requests"):
        pe.transition(pas, cid, A, "completeness_review", t(6))
    with pytest.raises(pe.PasError, match="no response"):
        pe.resolve_request(pas, cid, A, r["id"], t(6))
    pe.respond_request(pas, cid, A, r["id"], "Resubmitted", t(6))
    pe.resolve_request(pas, cid, A, r["id"], t(6))
    pe.transition(pas, cid, A, "completeness_review", t(7))


def test_state_recommendation_needs_delegation_and_decision_record():
    pas, cid = mk()
    to_technical(pas, cid)
    pe.transition(pas, cid, A, "state_decision", t(5))
    with pytest.raises(pe.PasError, match="not delegated"):
        pe.record_decision(pas, cid, A, "recommend_approve", "ok", t(6))
    pe.set_delegation(pas, A, {"application_review": True})
    with pytest.raises(pe.PasError, match="rationale"):
        pe.record_decision(pas, cid, A, "recommend_approve", " ", t(6))
    pe.record_decision(pas, cid, A, "recommend_approve", "All verified", t(6))
    pe.transition(pas, cid, A, "monitoring", t(7))
    assert pe.derived_status(pas["cases"][cid]) == "Completed administrative review"


def test_monitoring_requires_decision_or_referral():
    pas, cid = mk()
    to_technical(pas, cid)
    with pytest.raises(pe.PasError):
        pe.transition(pas, cid, A, "monitoring", t(5))


def test_federal_referral_tracking():
    pas, cid = mk()
    to_technical(pas, cid)
    with pytest.raises(pe.PasError, match="reason"):
        pe.refer_to_federal(pas, cid, A, t(5), " ")
    pe.refer_to_federal(pas, cid, A, t(5), "EHP", reference="R-1")
    assert pe.derived_status(pas["cases"][cid]) == "Referred for federal review"
    pe.record_federal_outcome(pas, cid, A, "FEMA returned for additional info", t(9))
    with pytest.raises(pe.PasError):
        pe.record_federal_outcome(pas, cid, A, "again", t(10))


# ---- metrics
def test_metrics_from_timestamps_only():
    pas, cid = mk(sub=t(1))
    to_technical(pas, cid)  # intake day2, completeness day3, technical day4
    m = pe.metrics(list(pas["cases"].values()), pas, t(14))
    ss = m["stage_stats"]
    assert ss["state_intake"]["mean_days"] == 1.0 and ss["completeness_review"]["mean_days"] == 1.0
    assert ss["technical_review"]["mean_days"] == 10.0  # day 4 -> day 14, open stage runs to now
    assert m["avg_review_days"] is None  # nothing completed, so no invented average
    assert m["days_by_holder"]["state"] == 12.0 and m["days_by_holder"]["applicant"] == 1.0


def test_review_time_average_and_median():
    pas = pe.new_pas()
    for i, (pid, days) in enumerate([("p1", 10), ("p2", 20), ("p3", 60)]):
        c = pe.create_case(pas, A, project_id=pid, jurisdiction="Cook", program="HMGP", submitted_at="2026-01-01T00:00:00+00:00")
        c["decision"] = {"at": pe._plus_days("2026-01-01T00:00:00+00:00", days), "outcome": "x"}
    m = pe.metrics(list(pas["cases"].values()), pas, NOW)
    assert m["avg_review_days"] == 30.0 and m["median_review_days"] == 20.0 and m["completed_n"] == 3


def test_overdue_and_deadline_detection():
    pas, cid = mk(due=t(5))
    pe.add_milestone(pas, cid, A, "Intake complete", t(3))
    pe.open_request(pas, cid, A, t(2), kind="Document request", text="Site plan", due_at=t(4))
    kinds = {o["kind"] for o in pe.overdue_items(pas, t(10))}
    assert kinds == {"milestone", "request", "case deadline"}
    pe.complete_milestone(pas, cid, A, "Intake complete", t(3))
    assert "milestone" not in {o["kind"] for o in pe.overdue_items(pas, t(10))}


def test_capacity_notes_do_not_claim_staff_shortage():
    pas = pe.new_pas()
    ids = pas_demo.load_demo(pas, A, {p["id"]: p for p in cs.PROJECTS}, NOW)
    m = pe.metrics(list(pas["cases"].values()), pas, NOW)
    text = " ".join(pe.capacity_notes(m)).lower()
    assert "shortage" not in text and "do not show whether staffing is short" in text
    assert len(ids) == 6


def test_empty_state_has_no_invented_figures():
    m = pe.metrics([], pe.new_pas(), NOW)
    assert m["total"] == 0 and m["avg_review_days"] is None and all(v == 0 for v in m["by_status"].values())


# ---- filtering / import
def test_filters():
    pas = pe.new_pas()
    pas_demo.load_demo(pas, A, {p["id"]: p for p in cs.PROJECTS}, NOW)
    assert len(pe.filter_cases(pas)) == 6
    assert [c["jurisdiction"] for c in pe.filter_cases(pas, jurisdiction="DuPage")] == ["DuPage"]
    assert len(pe.filter_cases(pas, status="Pending correction")) == 1
    assert len(pe.filter_cases(pas, text="p3")) == 1
    assert pe.filter_cases(pas, submitted_from="2999-01-01") == []


def test_import_validates_rows():
    pas = pe.new_pas()
    rows = list(csv.DictReader(io.StringIO(
        "project_id,jurisdiction,program,submitted_at\np1,Cook,HMGP,2026-03-01\n,Cook,HMGP,2026-03-01\npX,Cook,HMGP,2026-03-01\n"
        "p2,Kane,HMGP,not-a-date\np1,Cook,HMGP,2026-03-05\n")))
    res = pe.import_cases(pas, A, rows, {p["id"] for p in cs.PROJECTS})
    assert len(res["created"]) == 1 and len(res["errors"]) == 4
    assert {e["line"] for e in res["errors"]} == {3, 4, 5, 6}


# ---- persistence + audit chain
def test_store_roundtrip_and_shared_chain(tmp_path):
    be = audit_store.SQLiteBackend(str(tmp_path / "p.db"))
    pas = pas_store.load(be, "t")
    pe.create_case(pas, A, project_id="p1", jurisdiction="Cook", program="FMA", submitted_at=t(1))
    pe.set_item(pas, "PAS-0001", A, "bca", "Incomplete", t(2), note="x")
    assert pas_store.save(be, "t", pas) == 2
    again = pas_store.load(be, "t")
    assert again["cases"]["PAS-0001"]["checklist"]["bca"]["status"] == "Incomplete" and again["seq"] == 1
    assert audit_store.verify_chain(be, "t")[0]
    assert len(pas_store.case_events(be, "t", "PAS-0001")) == 2
    assert pas_store.load(be, "other")["cases"] == {}  # tenant isolation


def test_failed_action_queues_no_audit_event():
    pas, cid = mk()
    pe.drain_outbox(pas)
    with pytest.raises(pe.PasError):
        pe.set_item(pas, cid, A, "bca", "Verified", t(2))
    assert pas["_outbox"] == []


def test_existing_prioritization_unchanged():
    w = {k: wt for k, _, wt, _ in cs.CRITERIA}
    state = cs.new_state()
    assert cs.ranked(state["projects"], w, state["published"])  # PAS did not alter the engine
    assert [p["id"] for p in cs.PROJECTS][:3] == ["p1", "p2", "p3"]


# ---- packet
def test_packet_separates_verified_and_pending_and_names_authority(tmp_path):
    be = audit_store.SQLiteBackend(str(tmp_path / "k.db"))
    pas = pas_store.load(be, "t")
    ids = pas_demo.load_demo(pas, A, {p["id"]: p for p in cs.PROJECTS}, NOW)
    pas_store.save(be, "t", pas)
    cid = ids[3]  # federal referral case
    ev = pas_store.case_events(be, "t", cid)
    pk = pas_packet.build_packet(pas, cid, ev, now=NOW, chain=audit_store.verify_chain(be, "t"))
    md = pas_packet.to_markdown(pk)
    assert "DEMO RECORD" in md and "not a FEMA approval" in md
    assert any(i["id"] == "ehp" for i in pk["pending"]) and any(i["id"] == "bca" for i in pk["verified"])
    assert "[FEMA]" in md and "needs confirmation" in md
    assert pas_packet.to_pdf(pk)[:4] == b"%PDF"


# ---- UI
def _ui(monkeypatch):
    from test_ui_smoke import _make_stub
    stub = _make_stub()

    def _col():  # columns delegate inputs to the stub so filter widgets return real values and the workspace renders its case
        c = MagicMock()
        for n in ("button", "selectbox", "text_input", "number_input", "checkbox"):
            setattr(c, n, (lambda name: lambda *a, **k: getattr(stub, name)(*a, **k))(n))
        return c
    stub.columns.side_effect = lambda spec, **kw: [_col() for _ in range(spec if isinstance(spec, int) else len(spec))]
    stub.checkbox.side_effect = lambda label, **k: k.get("value", False)

    class _Mod(types.ModuleType):
        def __getattr__(self, name):
            return getattr(stub, name)
    monkeypatch.setitem(sys.modules, "streamlit", _Mod("streamlit"))
    for m in ("civicsignal_ui", "pas_ui"):
        sys.modules.pop(m, None)
    import pas_ui
    return pas_ui, stub


@pytest.mark.parametrize("roles", [None, {"viewer"}, {"viewer", "reviewer"}, {"viewer", "official"}, {"viewer", "admin"}])
@pytest.mark.parametrize("view", pas_ui_views := ["State Overview", "Project Review Workspace", "Jurisdiction Overview", "Geographic Review Map",
                                                  "Reports and Audit Packets", "Setup"])
def test_ui_renders_every_view_for_every_role(monkeypatch, tmp_path, roles, view):
    mod, st = _ui(monkeypatch)
    be = audit_store.SQLiteBackend(str(tmp_path / "u.db"))
    pas = pas_store.load(be, "t")
    pas_demo.load_demo(pas, A, {p["id"]: p for p in cs.PROJECTS}, pe.now_iso())
    pas_store.save(be, "t", pas)
    st.radio.side_effect = lambda *a, **k: view
    me = ident.Identity("a@b.gov", "A", "aad", frozenset(roles)) if roles else None
    mod.render(me, be, "t")
    assert st.title.called


def test_ui_unauthorised_clicks_write_nothing(monkeypatch, tmp_path):
    mod, st = _ui(monkeypatch)
    be = audit_store.SQLiteBackend(str(tmp_path / "u.db"))
    pas = pas_store.load(be, "t")
    pas_demo.load_demo(pas, A, {p["id"]: p for p in cs.PROJECTS}, pe.now_iso())
    pas_store.save(be, "t", pas)
    before = len(audit_store.list_events(be, "t"))
    st.button.side_effect = lambda *a, **k: True
    for view in pas_ui_views:
        st.session_state.clear()
        st.radio.side_effect = lambda *a, _v=view, **k: _v
        mod.render(ident.Identity("v@b.gov", "V", "aad", frozenset({"viewer"})), be, "t")
        mod.render(None, be, "t")
    assert len(audit_store.list_events(be, "t")) == before


def test_ui_setup_demo_load_requires_admin_and_persists(monkeypatch, tmp_path):
    mod, st = _ui(monkeypatch)
    be = audit_store.SQLiteBackend(str(tmp_path / "u.db"))
    st.radio.side_effect = lambda *a, **k: "Setup"
    st.button.side_effect = lambda label, *a, **k: label == "Load demo records"
    mod.render(ident.Identity("r@b.gov", "R", "aad", frozenset({"viewer", "reviewer"})), be, "t")
    assert pas_store.load(be, "t")["cases"] == {}
    st.session_state.clear()
    mod.render(ident.Identity("a@b.gov", "A", "aad", frozenset({"viewer", "admin"})), be, "t")
    assert len(pas_store.load(be, "t")["cases"]) == 6
    assert audit_store.verify_chain(be, "t")[0]


# ---- re-confirmation warning (time-sensitive items)
def _nfip_case(verified_day=1):
    pas, cid = mk(program="FMA")
    pe.set_item(pas, cid, A, "nfip_good_standing", "Verified", t(verified_day), evidence=["status.pdf"])
    return pas, cid


def test_only_time_sensitive_items_age():
    pas, cid = _nfip_case()
    pe.set_item(pas, cid, A, "bca", "Verified", t(1), evidence=["b.pdf"])
    assert pe.item_freshness(pas["cases"][cid], "bca", "2027-06-01T00:00:00+00:00")["state"] == "not_time_sensitive"
    assert pe.item_freshness(pas["cases"][cid], "nfip_good_standing", "2027-06-01T00:00:00+00:00")["state"] == "stale"


def test_fresh_stale_boundary_and_unverified():
    pas, cid = _nfip_case(verified_day=1)
    c = pas["cases"][cid]
    assert pe.item_freshness(c, "nfip_good_standing", pe._plus_days(t(1), 90), 90)["state"] == "fresh"  # exactly at the limit is not stale
    assert pe.item_freshness(c, "nfip_good_standing", pe._plus_days(t(1), 91), 90)["state"] == "stale"
    assert pe.item_freshness(c, "hmp_current", t(2))["state"] == "not_verified"  # never verified, so readiness already flags it


def test_note_edit_does_not_refresh_but_reconfirm_does():
    pas, cid = _nfip_case(verified_day=1)
    c = pas["cases"][cid]
    pe.set_item(pas, cid, A, "nfip_good_standing", "Verified", t(20), note="typo fix")
    assert c["checklist"]["nfip_good_standing"]["verified_at"] == t(1)
    pe.set_item(pas, cid, A, "nfip_good_standing", "Verified", t(20), reconfirm=True)
    assert c["checklist"]["nfip_good_standing"]["verified_at"] == t(20)


def test_changing_away_from_verified_clears_date_and_reverifying_restarts_it():
    pas, cid = _nfip_case(verified_day=1)
    c = pas["cases"][cid]
    pe.set_item(pas, cid, A, "nfip_good_standing", "Under review", t(5))
    assert "verified_at" not in c["checklist"]["nfip_good_standing"]
    pe.set_item(pas, cid, A, "nfip_good_standing", "Verified", t(9), evidence=["new.pdf"])
    assert c["checklist"]["nfip_good_standing"]["verified_at"] == t(9)


def test_legacy_item_without_verified_at_falls_back_to_updated_at():
    pas, cid = _nfip_case(verified_day=1)
    c = pas["cases"][cid]
    c["checklist"]["nfip_good_standing"].pop("verified_at")
    assert pe.item_freshness(c, "nfip_good_standing", t(10))["verified_at"] == t(1)


def test_stale_warns_but_never_blocks_readiness_or_transitions():
    pas, cid = mk(program="FMA")
    pe.set_delegation(pas, A, {"application_review": True})
    to_technical(pas, cid)
    assert pe.stale_items(pas["cases"][cid], "2027-12-01T00:00:00+00:00")  # old
    assert pe.evaluate_readiness(pas["cases"][cid])["overall"] == "ready"
    pe.transition(pas, cid, A, "state_decision", t(5))
    pe.record_decision(pas, cid, A, "recommend_approve", "ok", "2027-12-01T00:00:00+00:00")
    d = pas["cases"][cid]["decision"]
    assert {s["req_id"] for s in d["stale_items_at_decision"]} >= {"nfip_good_standing", "hmp_current"}  # the warning is on the record


def test_stale_days_setting_validated_and_audited():
    pas = pe.new_pas()
    assert pas["config"]["stale_after_days"] == pe.DEFAULT_STALE_DAYS
    for bad in (0, -5, 4000, "30", True, 1.5):
        with pytest.raises(pe.PasError):
            pe.set_stale_days(pas, A, bad)
    pe.set_stale_days(pas, A, 45)
    assert pas["config"]["stale_after_days"] == 45 and pas["_outbox"][-1]["action"] == "pas.stale_days_set"


def test_stale_setting_persists_and_old_saved_state_gets_default(tmp_path):
    be = audit_store.SQLiteBackend(str(tmp_path / "s.db"))
    pas = pas_store.load(be, "t")
    pe.set_stale_days(pas, A, 30)
    pas_store.save(be, "t", pas)
    assert pas_store.load(be, "t")["config"]["stale_after_days"] == 30
    be.set_setting("old", pas_store.SETTING_KEY, {"config": {"delegation": {}}, "cases": {}, "seq": 0})  # saved before this feature
    assert pas_store.load(be, "old")["config"]["stale_after_days"] == pe.DEFAULT_STALE_DAYS


def test_packet_shows_last_verified_and_stale_notice():
    pas, cid = _nfip_case(verified_day=1)
    pk = pas_packet.build_packet(pas, cid, [], now="2027-12-01T00:00:00+00:00")
    md = pas_packet.to_markdown(pk)
    assert "last verified 2026-10-01" in md and "STALE, re-confirm" in md and "Re-confirm before relying" in md
    fresh = pas_packet.to_markdown(pas_packet.build_packet(pas, cid, [], now=t(5)))
    assert "STALE" not in fresh and "Re-confirm before relying" not in fresh


def test_ui_reconfirm_button_requires_reviewer_role(monkeypatch, tmp_path):
    mod, st = _ui(monkeypatch)
    be = audit_store.SQLiteBackend(str(tmp_path / "r.db"))
    pas = pas_store.load(be, "t")
    c = pe.create_case(pas, A, project_id="p1", jurisdiction="Cook", program="FMA", submitted_at="2026-01-01T00:00:00+00:00")
    pe.set_item(pas, c["id"], A, "nfip_good_standing", "Verified", "2026-01-02T00:00:00+00:00", evidence=["s.pdf"])
    pas_store.save(be, "t", pas)
    before = len(audit_store.list_events(be, "t"))
    st.radio.side_effect = lambda *a, **k: "Project Review Workspace"
    st.button.side_effect = lambda label, *a, **k: label == "Re-confirm now"
    mod.render(ident.Identity("v@b.gov", "V", "aad", frozenset({"viewer"})), be, "t")
    assert len(audit_store.list_events(be, "t")) == before
    st.session_state.clear()
    mod.render(ident.Identity("r@b.gov", "R", "aad", frozenset({"viewer", "reviewer"})), be, "t")
    assert len(audit_store.list_events(be, "t")) == before + 1
    assert pas_store.load(be, "t")["cases"][c["id"]]["checklist"]["nfip_good_standing"]["verified_at"] > "2026-06-01"
