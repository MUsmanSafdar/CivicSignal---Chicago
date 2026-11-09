"""Tests for the PAS document review engine and its UI wiring."""
from datetime import date

import pytest
from unittest.mock import MagicMock

import audit_store
import identity as ident
import pas_review as pr

GOOD = b"""Application form signed by the authorized representative.
Applicant: Example County, a local government and eligible subapplicant.
The FEMA-approved hazard mitigation plan expires March 3, 2031.
NFIP participation: community identification number 170000, in good standing.
Scope of work: elevate pump station. Project location: latitude 41.9.
Total project cost: $1,200,000. Itemized cost estimate attached.
Benefit-cost analysis BCR 1.4. Environmental and historic preservation screening attached.
Non-federal share: 25% local match from county funds.
Maintenance: county public works will operate and maintain.
Letters of support attached.
"""


def _review(prog="FMA", text=GOOD):
    facts = pr.validate_upload("plan.txt", text)
    r = pr.new_review("REV-1", "a@x.gov", facts, {"program": prog, "jurisdiction": "Example County", "project": "Pump"}, at="2026-11-01T00:00:00Z")
    return pr.analyze(r, pr.extract_units(".txt", text), "a@x.gov", today=date(2026, 11, 1), at="2026-11-01T00:01:00Z")


def test_validate_rejects_bad_files():
    for name, raw in [("a.exe", b"x"), ("a.txt", b""), ("a.pdf", b"not pdf"), ("a.txt", b"\x00\x01"), ("a.txt", b"\xff\xfe\xfa"), ("a.txt", b"x" * (pr.MAX_BYTES + 1))]:
        with pytest.raises(pr.ReviewError):
            pr.validate_upload(name, raw)


def test_safe_name_strips_paths():
    assert pr.safe_name("../../etc/passwd") == "passwd"
    assert "/" not in pr.safe_name("a\\b\\c.pdf")


def test_new_review_requires_config():
    f = pr.validate_upload("a.txt", b"x")
    with pytest.raises(pr.ReviewError):
        pr.new_review("R", "u", f, {"program": "BRIC", "jurisdiction": "x", "project": "y"})
    with pytest.raises(pr.ReviewError):
        pr.new_review("R", "u", f, {"program": "FMA", "jurisdiction": " ", "project": "y"})


def test_analysis_finds_evidence_with_locators_and_never_verifies():
    r = _review()
    cats = {f["req_id"]: f["category"] for f in r["findings"]}
    assert cats["scope_of_work"] == "located" and cats["cost_estimate"] == "located"
    assert not any(f["category"] == "verified" for f in r["findings"])
    assert all(f["evidence"] and f["evidence"][0]["locator"].startswith("Lines") for f in r["findings"] if f["category"] == "located")


def test_federal_items_are_undeterminable():
    r = _review()
    fed = {f["req_id"] for f in r["findings"] if f["category"] == "undeterminable"}
    assert {"hmp_current", "ehp"} <= fed


def test_missing_required_items_flagged():
    r = _review(text=b"Just a cover letter.")
    missing = {f["req_id"] for f in r["findings"] if f["category"] == "missing"}
    assert {"scope_of_work", "cost_estimate", "bca"} <= missing
    assert all(f["required"] for f in r["findings"] if f["req_id"] == "bca")


def test_program_filters_requirements():
    assert "nfip_good_standing" in {f["req_id"] for f in _review("FMA")["findings"]}
    assert "nfip_good_standing" not in {f["req_id"] for f in _review("HMGP")["findings"]}


def test_consistency_checks():
    text = GOOD + b"Plan expires January 5, 2020.\nTotal project cost: $900,000.\nSection TBD.\nNFIP status: suspended.\n"
    r = _review(text=text)
    labels = " | ".join(f["label"] for f in r["findings"] if f["category"] == "issue")
    for k in ("already passed", "Conflicting total cost", "Placeholder", "NFIP status may be suspended"):
        assert k in labels
    assert not [f for f in _review()["findings"] if f["category"] == "issue"]


def test_close_requires_note_and_confirms():
    r = _review()
    fid = next(f["id"] for f in r["findings"] if f["category"] == "located")
    with pytest.raises(pr.ReviewError):
        pr.close_finding(r, fid, "rev", " ")
    pr.close_finding(r, fid, "rev", "checked page")
    f = next(x for x in r["findings"] if x["id"] == fid)
    assert f["category"] == "verified" and f["status"] == "confirmed" and f["resolved_by"] == "rev"
    with pytest.raises(pr.ReviewError):
        pr.close_finding(r, fid, "rev", "again")
    pr.reopen_finding(r, fid, "rev", "wrong page")
    assert f["category"] == "located" and f["status"] == "open"


def test_decision_blocked_until_blocking_items_handled():
    r = _review(text=b"Cover letter only.")
    with pytest.raises(pr.ReviewError):
        pr.record_decision(r, "off", "ready_for_next_stage", "ok")
    for f in pr.blocking(r):
        pr.close_finding(r, f["id"], "rev", "handled")
    assert pr.blocking(r) == []
    d = pr.record_decision(r, "off", "ready_for_next_stage", "ok")
    assert r["status"] == "decided" and d["by"] == "off"
    with pytest.raises(pr.ReviewError):
        pr.record_decision(r, "off", "return_for_corrections", "x")
    with pytest.raises(pr.ReviewError):
        pr.reopen_finding(r, "F1", "rev", "late")


def test_return_for_corrections_allowed_with_open_items():
    r = _review(text=b"Cover letter only.")
    pr.record_decision(r, "off", "return_for_corrections", "missing items")
    assert r["decision"]["decision"] == "return_for_corrections"


def test_history_records_every_step():
    r = _review()
    assert [h["action"] for h in r["history"]] == ["submitted", "analyzed"]


def test_packet_contains_required_parts():
    r = _review()
    md = pr.packet_markdown(r, "t1", sample_data=True)
    for k in ("REV-1", r["file"]["sha256"], "not a FEMA approval", "Unresolved items", "## History", "Illustrative or test session", "Evidence, Lines"):
        assert k in md


def test_pdf_extraction_pages():
    pytest.importorskip("reportlab")
    import io
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 700, "Scope of work: replace culvert")
    c.showPage()
    c.drawString(72, 700, "Total project cost: $50,000")
    c.save()
    raw = buf.getvalue()
    pr.validate_upload("a.pdf", raw)
    units = pr.extract_units(".pdf", raw)
    assert [u["locator"] for u in units] == ["Page 1", "Page 2"] and "culvert" in units[0]["text"]


def test_step_progression():
    assert pr.step(None, False) == 0 and pr.step(None, True) == 1
    r = _review()
    assert pr.step(r, True) == 4


def _ui(monkeypatch):
    import sys
    import types

    from test_ui_smoke import _make_stub
    stub = _make_stub()

    class _Mod(types.ModuleType):
        def __getattr__(self, name):
            return getattr(stub, name)
    monkeypatch.setitem(sys.modules, "streamlit", _Mod("streamlit"))
    sys.modules.pop("pas_review_ui", None)
    import pas_review_ui
    return pas_review_ui, stub


def test_store_roundtrip_and_audit(tmp_path, monkeypatch):
    ui, _st = _ui(monkeypatch)
    be = audit_store.SQLiteBackend(str(tmp_path / "t.db"))
    store = ui.load_reviews(be, "t")
    store["seq"] = 1
    store["reviews"]["REV-1"] = _review()
    ui.save_reviews(be, "t", store)
    assert ui.load_reviews(be, "t")["reviews"]["REV-1"]["status"] == "analyzed"
    ui._log(be, "t", "a", "submitted", "REV-1", {})
    ok, _msg = audit_store.verify_chain(be, "t")
    assert ok and len(be.list_events("t")) == 1


def test_screen_renders_read_only_without_identity(monkeypatch, tmp_path):
    ui, st = _ui(monkeypatch)
    be = audit_store.SQLiteBackend(str(tmp_path / "t.db"))
    st.file_uploader.return_value = None
    ui.render(None, be, "t", sample_data=True)
    assert st.info.called  # anonymous viewers are told to sign in
    assert not st.button.called  # nothing to submit without an upload


def test_permissions_exist():
    assert ident.PERMISSIONS["pas_intake"] and ident.PERMISSIONS["pas_decide"]


def _signed_in(monkeypatch, tmp_path, roles, raw=GOOD, pressed="Submit for review"):
    ui, st = _ui(monkeypatch)
    be = audit_store.SQLiteBackend(str(tmp_path / "t.db"))
    up = type("U", (), {"name": "plan.txt", "getvalue": lambda self: raw})()
    st.file_uploader.return_value = up
    st.selectbox.return_value = "FMA"
    st.text_input.return_value = "Example"
    st.button.side_effect = lambda label, *a, **k: label == pressed
    st.session_state = {}

    def _cols(n, *a, **k):
        n = n if isinstance(n, int) else len(n)
        out = []
        for _ in range(n):
            c = MagicMock()
            c.selectbox.return_value = "FMA"
            c.text_input.return_value = "Example"
            out.append(c)
        return out
    st.columns.side_effect = _cols
    st.radio.return_value = "New submission"
    who = ident.Identity(email="r@x.gov", name="R", idp="t", roles=frozenset(roles), source="dev")
    ui.render(who, be, "t", sample_data=True)
    return ui, st, be


def test_submit_button_creates_review_audit_and_nothing_before(monkeypatch, tmp_path):
    ui, st, be = _signed_in(monkeypatch, tmp_path, {"reviewer"}, pressed="(none)")
    assert ui.load_reviews(be, "t")["reviews"] == {}  # upload alone submits nothing
    assert be.list_events("t") == []
    ui, st, be = _signed_in(monkeypatch, tmp_path, {"reviewer"})
    reviews = ui.load_reviews(be, "t")["reviews"]
    assert len(reviews) == 1
    r = next(iter(reviews.values()))
    assert r["id"].startswith("REV-") and r["created_at"] and r["status"] == "analyzed" and r["findings"]
    assert [e["action"] for e in be.list_events("t")] == ["pas.docreview.submitted", "pas.docreview.analyzed"]
    assert audit_store.verify_chain(be, "t")[0]


def test_viewer_role_cannot_submit(monkeypatch, tmp_path):
    ui, st, be = _signed_in(monkeypatch, tmp_path, {"viewer"})
    assert ui.load_reviews(be, "t")["reviews"] == {}
