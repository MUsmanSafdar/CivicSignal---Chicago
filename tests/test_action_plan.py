"""Action portfolio reader: parsing both text layouts, scoring, overrides, and the screen."""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

import action_plan as ap
import identity as ident

# Layout A: pdfplumber-style (label and value on the same line, status code on the label line)
A = """VOLUME 2: MJ-HMP JURISDICTIONAL ANNEXES
Action C.27
Mitigation Action #27: Retrofit electric panels at senior housing so residents keep power in an outage
Lead Agency/Department Supporting Estimated Cost: Potential Estimated Hazard(s)
Organization: Agencies/ High Funding Projected Mitigated:
CDPH Organizations: Source: Completion Extreme Heat
HMGP, BRIC Date:
Year Initiated 2019
Applicable Jurisdiction City of Chicago
Cost Analysis (Low, Medium, High) High
Priority and Level of Importance (Low,
High
Medium, High)
Action/Implementation Plan and Project
Description: Install exterior connections at senior housing buildings for generators.
Actual Completion Date or Ongoing Indefinite
Project Status & Changes in Priority O
Action C.2
Mitigation Action #2: Continue to support the countywide actions identified in this plan.
Lead Agency/Department Supporting Estimated Cost: Potential Estimated Hazard(s)
Organization: Agencies/ Low Funding Projected Mitigated:
OEMC Organizations: Source: Completion All
General Fund Date:
Year Initiated 2014
Cost Analysis (Low, Medium, High) Low
Priority and Level of Importance (Low,
Medium
Medium, High)
Project Status & Changes in Priority O
"""

# Layout B: pdftotext -layout style (value on its own indented line, status letter alone, legend after)
B = """Action C.51
  Mitigation Action #51: Support Roots Tree Canopy Program
  Lead Agency/Department         Supporting         Estimated Cost:           Potential         Estimated             Hazard(s)
  Department of Streets and      Organizations:     $46,000,000               Funding           Projected             Extreme Heat
                                                                              General Fund, BRIC, HMGP
  Year Initiated                                     2022
  Cost Analysis (Low, Medium, High)                  Medium
  Priority and Level of Importance (Low, Medium,
                                                     Medium
                                                     High)
  Action/Implementation Plan and Project
  Description:                                       Plant 75,000 trees in neighborhoods that have less tree canopy coverage.
  Actual Completion Date or Ongoing Indefinite
  Project Status & Changes in Priority
  Completion status legend:
                                                     I
  O = Ongoing Indefinitely; C = Project Completed;
"""


def test_parses_priority_status_funding_in_layout_a():
    r = ap.analyze(A)
    a = {x["number"]: x for x in r["actions"]}
    assert a[27]["priority"] == "High" and a[27]["cost"] == "High" and a[27]["status_code"] == "O" and a[27]["grant_source_listed"] is True
    assert a[2]["priority"] == "Medium" and a[2]["grant_source_listed"] is False
    assert r["summary"]["priority_counts"] == {"High": 1, "Medium": 1, "Low": 0}


def test_parses_layout_b_and_ignores_the_legend():
    a = ap.analyze(B)["actions"][0]
    assert a["priority"] == "Medium" and a["cost"] == "Medium" and a["status_code"] == "I" and a["year_initiated"] == "2022"
    assert a["grant_source_listed"] is True and a["status"] == "In progress"


def test_boilerplate_words_do_not_inflate_the_score():
    txt = ("Mitigation Action #9: Continue the policy\nLead Agency\nYear Initiated 2014\nPriority and Level of Importance (Low, Medium, High)\nHigh\n"
           "Action/Implementation Plan and Project\nDescription: Maintain the policy.\nActual Completion Date\n"
           "Benefits of the Mitigation Project: reduction in risk exposure for life and property, in the building\n")
    a = ap.analyze(txt)["actions"][0]
    assert a["place_score"] == 0 and a["fit_tier"] == "Weak"


def test_fit_scoring_and_tiers():
    a = {x["number"]: x for x in ap.analyze(A)["actions"]}
    assert a[27]["place_score"] == 2 and a[27]["vulnerability_score"] == 2 and a[27]["fit_score"] == 5 and a[27]["fit_tier"] == "Strong"
    assert a[2]["fit_tier"] == "Weak"
    assert [ap.fit_tier(s) for s in (0, 1, 2, 3, 4, 5)] == ["Weak", "Weak", "Moderate", "Moderate", "Strong", "Strong"]


def test_completed_and_removed_are_left_out_of_fit_counts():
    txt = A + "\nMitigation Action #3: Plan upkeep\nProject Status & Changes in Priority R\n" + \
        "Mitigation Action #4: Finished tunnel\nProject Status & Changes in Priority C\n"
    s = ap.analyze(txt)["summary"]
    assert s["fit_excluded"] == 2 and sum(s["fit_counts"].values()) == 2


def test_summary_reports_gaps_and_priority_spread():
    s = ap.analyze(A)["summary"]
    assert s["numbers_missing_from_range"][:3] == [1, 3, 4] and s["share_high_or_medium"] == 1.0 and s["ratings_separate_actions"] is False
    assert ap.summarize([])["actions_read"] == 0


def test_duplicate_numbers_keep_first_and_are_reported():
    r = ap.analyze(A + "\nMitigation Action #2: Duplicate entry\n")
    assert r["duplicates"] == [2] and len(r["actions"]) == 2


def test_unreadable_fields_are_counted_not_guessed():
    r = ap.analyze("Mitigation Action #5: Something with no table\n")
    assert r["actions"][0]["priority"] == "" and r["unread"] == {"priority": 1, "status": 1, "cost": 1}


def test_no_actions_in_unrelated_text():
    assert ap.analyze("Just a memo with no action tables.")["actions"] == []


def test_overrides_recompute_and_ignore_bad_values():
    acts = ap.analyze(A)["actions"]
    out = {x["number"]: x for x in ap.apply_overrides(acts, {2: {"place": 2, "vulnerability": 2}, 27: {"place": 9, "vulnerability": True}})}
    assert out[2]["fit_score"] == 4 and out[2]["fit_tier"] == "Strong" and out[2]["reviewed"] is True
    assert out[27]["place_score"] == 2 and out[27]["vulnerability_score"] == 2  # invalid values ignored
    assert acts[0]["fit_score"] == ap.analyze(A)["actions"][0]["fit_score"]  # originals not mutated


def test_csv_has_header_and_rows():
    out = ap.to_csv(ap.analyze(A)["actions"]).splitlines()
    assert out[0].startswith("number,title,status") and len(out) == 3


def test_extract_pdf_text_reads_a_real_pdf(tmp_path):
    pytest.importorskip("pdfplumber")
    from reportlab.pdfgen import canvas
    f = tmp_path / "t.pdf"
    c = canvas.Canvas(str(f))
    c.drawString(72, 750, "Mitigation Action #7: Test action")
    c.save()
    r = ap.extract_pdf_text(f.read_bytes())
    assert r["page_count"] == 1 and "Mitigation Action #7" in r["text"]


# ---- screen
def _ui(monkeypatch):
    from test_ui_smoke import _make_stub
    stub = _make_stub()

    class _Mod(types.ModuleType):
        def __getattr__(self, name):
            return getattr(stub, name)
    monkeypatch.setitem(sys.modules, "streamlit", _Mod("streamlit"))
    sys.modules.pop("portfolio_ui", None)
    import portfolio_ui
    return portfolio_ui, stub


def _upload(raw=b"%PDF"):
    u = MagicMock()
    u.size = len(raw)
    u.read.return_value = raw
    return u


def test_screen_without_upload_and_without_role(monkeypatch):
    mod, st = _ui(monkeypatch)
    st.file_uploader.return_value = None
    mod.render(ident.Identity("a@b.gov", "A", "aad", frozenset({"viewer"})), None, "t")
    assert st.title.called
    mod.render(ident.Identity("a@b.gov", "A", "aad", frozenset()), None, "t")  # no role: warned, no crash


@pytest.mark.parametrize("roles", [{"viewer"}, {"viewer", "reviewer"}, {"admin"}])
def test_screen_renders_results_for_roles(monkeypatch, roles):
    mod, st = _ui(monkeypatch)
    st.file_uploader.return_value = _upload()
    monkeypatch.setattr(mod.ap, "extract_pdf_text", lambda raw: {"text": A + B, "page_count": 2, "pages_read": 2})
    st.session_state = {}
    st.selectbox.side_effect = lambda label, options=None, **k: (options or ["All"])[0]
    mod.render(ident.Identity("a@b.gov", "A", "aad", frozenset(roles)), None, "t")
    assert st.dataframe.called and st.download_button.called
    assert (st.expander.called) == bool(roles & {"reviewer", "admin"})


def test_screen_handles_unreadable_pdf_and_empty_result(monkeypatch):
    mod, st = _ui(monkeypatch)
    st.file_uploader.return_value = _upload()
    monkeypatch.setattr(mod.ap, "extract_pdf_text", lambda raw: (_ for _ in ()).throw(ValueError("bad")))
    mod.render(ident.Identity("a@b.gov", "A", "aad", frozenset({"viewer"})), None, "t")
    assert st.error.called
    mod2, st2 = _ui(monkeypatch)
    st2.file_uploader.return_value = _upload()
    monkeypatch.setattr(mod2.ap, "extract_pdf_text", lambda raw: {"text": "nothing here", "page_count": 1, "pages_read": 1})
    mod2.render(ident.Identity("a@b.gov", "A", "aad", frozenset({"viewer"})), None, "t")
    assert st2.warning.called and not st2.dataframe.called
