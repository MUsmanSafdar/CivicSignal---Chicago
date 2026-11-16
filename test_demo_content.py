"""Demo content for visitors: nothing on the PAS, document review, action portfolio or cooling-center screens is empty,
every example is labelled, and showing an example never writes to the store or the audit trail."""
import csv
import re
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import action_plan as ap
import audit_store
import civicsignal as cs
import identity as ident
import pas_engine as pe
import pas_review as pr
import pas_review_demo
import pas_store

ROOT = Path(__file__).resolve().parent.parent
AREA = {"Cook", "DuPage", "Kane", "Kendall", "Lake", "McHenry", "Will"}


def _stub(monkeypatch, *mods):
    from test_ui_smoke import _make_stub
    stub = _make_stub()

    def _col():
        c = MagicMock()
        for n in ("button", "selectbox", "text_input", "number_input", "checkbox", "metric"):
            setattr(c, n, (lambda name: lambda *a, **k: getattr(stub, name)(*a, **k))(n))
        return c
    stub.columns.side_effect = lambda spec, **kw: [_col() for _ in range(spec if isinstance(spec, int) else len(spec))]
    stub.checkbox.side_effect = lambda label, **k: k.get("value", False)
    stub.session_state = {}

    class _Mod(types.ModuleType):
        def __getattr__(self, name):
            return getattr(stub, name)
    monkeypatch.setitem(sys.modules, "streamlit", _Mod("streamlit"))
    for m in mods:
        sys.modules.pop(m, None)
    return stub


# ---- cooling centers
def _centers():
    with open(ROOT / "cooling_centers.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_cooling_centers_cover_all_seven_counties_with_usable_points():
    rows = _centers()
    assert {r["county"] for r in rows} == AREA and len(rows) >= 200
    for r in rows:
        assert r["name"].strip() and r["address"].strip() and r["source"].strip()
        assert 41.0 <= float(r["latitude"]) <= 42.6 and -88.8 <= float(r["longitude"]) <= -87.4, r["name"]


def test_cooling_center_addresses_are_split_into_street_city_zip():
    for r in _centers():
        assert not re.search(r"\bUSA\b|,\s*IL\b|,\s*Illinois\b|\d{5}$", r["address"]), r["address"]
        assert r["zip"] == "" or re.fullmatch(r"\d{5}", r["zip"]), r["zip"]
        assert r["city"] == "" or (r["city"][0].isupper() and not r["city"].isupper()), r["city"]
        assert r["phone"] in ("", "311") or re.fullmatch(r"\(\d{3}\) \d{3}-\d{4}", r["phone"]) or re.search(r"\d{3}.*\d{4}", r["phone"]), r["phone"]
    assert not any(r["phone"].startswith("000") for r in _centers())


def test_no_county_is_left_without_a_center():
    import pandas as pd

    import heat_need
    cc = pd.read_csv(ROOT / "cooling_centers.csv", dtype={"zip": str}, keep_default_na=False)
    need = heat_need.need_table(pd.read_csv(ROOT / "county_risk.csv"), cc)
    assert len(need) == 7 and int((need["centers"] == 0).sum()) == 0


# ---- document review examples
def test_example_reviews_are_real_check_output_on_invented_documents():
    store = pas_review_demo.demo_store()
    assert set(store["reviews"]) == ({"DEMO-HMGP", "DEMO-LOCAL"} if "LOCAL" in pr.PROGRAMS else {"DEMO-HMGP"})
    h = store["reviews"]["DEMO-HMGP"]
    assert "INVENTED" in pas_review_demo.HMGP_TEXT and "INVENTED" in pas_review_demo.LOCAL_TEXT
    assert "invented" in h["config"]["jurisdiction"] and h["demo"] and h["status"] == "analyzed"
    cats = [f["category"] for f in h["findings"]]
    labels = " | ".join(f["label"] for f in h["findings"])
    assert {"located", "missing", "issue", "undeterminable"} <= set(cats)
    assert "Conflicting total cost" in labels and "laceholder" in labels
    if "LOCAL" in pr.PROGRAMS:
        loc = store["reviews"]["DEMO-LOCAL"]
        assert [f["label"] for f in loc["findings"] if f["category"] == "missing"] == [
            "Internal approval or sign-off recorded", "Evidence of community support or outreach"]
    assert pr.summary(h)["blocking"] >= 1


def test_visitor_sees_example_reviews_and_nothing_is_written(monkeypatch, tmp_path):
    st = _stub(monkeypatch, "pas_review_ui")
    import pas_review_ui as ui
    be = audit_store.SQLiteBackend(str(tmp_path / "t.db"))
    st.file_uploader.return_value = None
    st.button.side_effect = lambda *a, **k: True          # press everything
    st.radio.side_effect = lambda label, options=None, **k: "DEMO-HMGP" if label == "Work on" else (options or [None])[0]
    ui.render(None, be, "t", sample_data=True)
    assert any("example reviews" in str(c.args[0]).lower() for c in st.info.call_args_list)
    assert ui.load_reviews(be, "t")["reviews"] == {} and audit_store.list_events(be, "t") == []


def test_example_reviews_are_not_shown_to_staff_or_outside_sample_mode(monkeypatch, tmp_path):
    st = _stub(monkeypatch, "pas_review_ui")
    import pas_review_ui as ui
    be = audit_store.SQLiteBackend(str(tmp_path / "t.db"))
    st.file_uploader.return_value = None
    ui.render(ident.Identity("r@b.gov", "R", "aad", frozenset({"viewer", "reviewer"})), be, "t", sample_data=True)
    ui.render(None, be, "t", sample_data=False)
    assert not any("example reviews" in str(c.args[0]).lower() for c in st.info.call_args_list)


# ---- PAS review center example cases
def test_visitor_gets_example_cases_in_memory_only(monkeypatch, tmp_path):
    st = _stub(monkeypatch, "civicsignal_ui", "pas_ui")
    import pas_ui
    be = audit_store.SQLiteBackend(str(tmp_path / "u.db"))
    pas = pas_store.load(be, "t")
    assert pas_ui._preview_demo(None, pas, True, pe.now_iso()) is True
    assert len(pas["cases"]) == 6 and all(c["demo"] for c in pas["cases"].values()) and pe.drain_outbox(pas) == []
    for view in pas_ui.VIEWS:
        st.radio.side_effect = lambda *a, _v=view, **k: _v
        pas_ui.render(None, be, "t", sample_data=True)
    assert any("Example cases" in str(c.args[0]) for c in st.info.call_args_list)
    assert pas_store.load(be, "t")["cases"] == {} and audit_store.list_events(be, "t") == []


@pytest.mark.parametrize("roles", [{"viewer", "reviewer"}, {"viewer", "official"}, {"viewer", "admin"}])
def test_staff_never_get_the_preview(monkeypatch, roles):
    _stub(monkeypatch, "civicsignal_ui", "pas_ui")
    import pas_ui
    me = ident.Identity("a@b.gov", "A", "aad", frozenset(roles))
    pas = pe.new_pas()
    assert pas_ui._preview_demo(me, pas, True, pe.now_iso()) is False and pas["cases"] == {}


def test_no_preview_outside_sample_mode_or_when_real_cases_exist(monkeypatch):
    _stub(monkeypatch, "civicsignal_ui", "pas_ui")
    import pas_ui
    assert pas_ui._preview_demo(None, pe.new_pas(), False, pe.now_iso()) is False
    pas = pe.new_pas()
    p = cs.PROJECTS[0]
    pe.create_case(pas, "a@b.gov", project_id=p["id"], jurisdiction="Cook", program=p["program"], submitted_at=pe.now_iso())
    assert pas_ui._preview_demo(None, pas, True, pe.now_iso()) is False and len(pas["cases"]) == 1


# ---- action portfolio worked example
def test_portfolio_example_is_a_saved_reading_of_a_public_plan(monkeypatch):
    _stub(monkeypatch, "portfolio_ui")
    import portfolio_ui
    ex = portfolio_ui.load_example()
    assert ex and "public document" in ex["document"] and "Chicago" in ex["document"] and ex["pages"] == 94
    acts = ex["result"]["actions"]
    s = ap.summarize(acts)
    assert s["actions_read"] == len(acts) == 52 and s["priority_counts"] == {"High": 24, "Medium": 24, "Low": 4}
    assert all(a["title"] and a["fit_tier"] in ("Strong", "Moderate", "Weak") for a in acts)
    blob = (ROOT / "portfolio_demo.json").read_text(encoding="utf-8")
    assert "@" not in blob and not re.search(r"\b\d{3}-\d{3}-\d{4}\b", blob)     # no contact details carried over from the plan


@pytest.mark.parametrize("who", [None, ident.Identity("v@b.gov", "V", "aad", frozenset({"viewer"}))])
def test_portfolio_screen_is_never_empty(monkeypatch, who):
    st = _stub(monkeypatch, "portfolio_ui")
    import portfolio_ui
    st.file_uploader.return_value = None
    st.selectbox.side_effect = lambda label, options=None, **k: (options or ["All"])[0]
    portfolio_ui.render(who, None, "t")
    assert st.dataframe.called and len(st.dataframe.call_args.args[0]) >= 40
    assert any("Worked example" in str(c.args[0]) for c in st.info.call_args_list)
    assert not st.expander.called            # the example takes no corrections
    assert st.session_state == {}            # and leaves nothing behind


def test_portfolio_screen_survives_a_missing_example_file(monkeypatch, tmp_path):
    st = _stub(monkeypatch, "portfolio_ui")
    import portfolio_ui
    monkeypatch.setattr(portfolio_ui, "DEMO_FILE", tmp_path / "nope.json")
    st.file_uploader.return_value = None
    portfolio_ui.render(None, None, "t")
    assert portfolio_ui.load_example() is None and st.warning.called and not st.dataframe.called
