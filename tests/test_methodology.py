"""Methodology & Evidence: the explanation must match the scoring that is actually implemented."""
from __future__ import annotations

import copy
import sys
import types

import pandas as pd
import pytest

import analysis
import civicsignal as cs
import methodology as mt

BASE = {k: float(w) for k, _l, w, _s in cs.CRITERIA}


def test_criteria_table_reads_the_live_criteria():
    rows = mt.criteria_table(BASE)
    assert [r["key"] for r in rows] == [k for k, *_ in cs.CRITERIA]
    assert abs(sum(r["share"] for r in rows) - 1.0) < 1e-9
    assert all(r["evidence_kind"] != "Unspecified" for r in rows)


def test_data_status_is_honest_about_sample_data():
    assert "Illustrative" in mt.data_status(False)["label"]
    assert "Verified" in mt.data_status(True)["label"]
    assert all(r["data_status"] == "Illustrative sample data" for r in mt.criteria_table(BASE, verified=False))


def test_explanation_adds_up_to_the_score_and_rank_matches_the_engine():
    projects = cs.PROJECTS
    engine_rank = {r["p"]["id"]: i + 1 for i, r in enumerate(cs.ranked(projects, BASE, set()))}
    for p in projects:
        ex = mt.explain_project(p, projects, BASE)
        assert abs(sum(x["points"] for x in ex["parts"]) - cs.score_of(p, BASE)) < 1e-9
        assert ex["rank"] == engine_rank[p["id"]]


def test_compare_weights_does_not_change_baseline_or_projects():
    projects, before_p, before_w = cs.PROJECTS, copy.deepcopy(cs.PROJECTS), dict(BASE)
    crit_before = copy.deepcopy(cs.CRITERIA)
    adj = dict(BASE, risk=0.0, ready=60.0)
    rows = mt.compare_weights(projects, BASE, adj)
    assert BASE == before_w and projects == before_p and cs.CRITERIA == crit_before
    assert {r["baseline_rank"] for r in rows} == set(range(1, len(projects) + 1))
    assert any(r["change"] != 0 for r in rows)


def test_identical_weights_change_nothing():
    assert all(r["change"] == 0 for r in mt.compare_weights(cs.PROJECTS, BASE, dict(BASE)))


def test_invalid_weights_raise_instead_of_ranking():
    with pytest.raises(cs.WeightsError):
        mt.compare_weights(cs.PROJECTS, BASE, {k: 0.0 for k in BASE})


def test_rank_stability_ranges_include_baseline():
    out = mt.rank_stability(cs.PROJECTS, BASE)
    assert len(out) == len(cs.PROJECTS) and out[0]["scenarios"] > 0
    for r in out:
        assert r["best"] <= r["baseline_rank"] <= r["worst"] and r["spread"] == r["worst"] - r["best"]


def test_rank_stability_skips_invalid_scenarios():
    tiny = {"risk": 1.0, "vul": 0.0, "loss": 0.0, "bcr": 0.0, "ready": 0.0}
    out = mt.rank_stability(cs.PROJECTS, tiny)  # lowering the only weight would be invalid; must not raise
    assert out and out[0]["scenarios"] >= 1


@pytest.mark.parametrize("risk,svi", [(1.0, 0.1), (2.0, 0.3), (3.0, 0.3), (3.0, 0.5), (4.5, 0.75), (2.5, 0.9), (0.0, 0.0), (5.0, 1.0), (2.99, 0.49), (3.0, 0.25)])
def test_county_band_matches_analysis_module(risk, svi):
    """The thresholds shown on screen must be the ones analysis.rule_based_risk_analysis uses."""
    row = pd.Series({"county": "X", "hazard": "Flood", "risk_score": risk, "risk_level": "High", "svi_score": svi})
    real = analysis.rule_based_risk_analysis(row, None)
    shown = mt.county_band(risk, svi)
    assert shown["svi_label"] == real["svi_label"]
    compound_real = svi >= 0.50 and risk >= 3.0
    assert (shown["case"].startswith("Compound")) == compound_real


def test_data_gaps_report_what_is_missing():
    gaps = mt.data_gaps(cs.PROJECTS)
    assert any("benefit-cost ratio" in g for g in gaps) and any("vintage" in g for g in gaps)
    full = [dict(p, bca_ratio=1.5, scope="mitigation") for p in cs.PROJECTS]
    assert not any("benefit-cost ratio" in g for g in mt.data_gaps(full))


def test_summary_markdown_has_required_sections_and_labels_sample_data():
    md = mt.summary_markdown(cs.PROJECTS, BASE, verified=False)
    for h in ("## Formula", "## Criteria, weights and sources", "## Ranking with these weights", "## How stable is the ranking?",
              "## County narrative bands", "## Data gaps", "## Limitations"):
        assert h in md
    assert "Illustrative sample data" in md and "not official records" in md
    assert "Verified data loaded" in mt.summary_markdown(cs.PROJECTS, BASE, verified=True)


def test_summary_never_claims_a_fema_determination():
    assert "Nothing here is a FEMA determination" in mt.summary_markdown(cs.PROJECTS)


def _ui(monkeypatch):
    from test_ui_smoke import _make_stub
    stub = _make_stub()

    class _Mod(types.ModuleType):
        def __getattr__(self, name):
            return getattr(stub, name)
    monkeypatch.setitem(sys.modules, "streamlit", _Mod("streamlit"))
    sys.modules.pop("methodology_ui", None)
    import methodology_ui
    return methodology_ui, stub


@pytest.mark.parametrize("sample", [True, False])
def test_screen_renders_for_anonymous_visitors(monkeypatch, sample):
    mod, st = _ui(monkeypatch)
    mod.render(None, None, "t", sample_data=sample)
    assert st.title.called and st.dataframe.called and st.download_button.called
    assert (st.warning.called) == sample


def test_screen_with_invalid_weights_shows_error_not_a_crash(monkeypatch):
    mod, st = _ui(monkeypatch)
    st.slider.side_effect = lambda label, lo, hi, d, **k: 0
    mod.render(None, None, "t")
    assert st.error.called


def test_screen_does_not_change_baseline(monkeypatch):
    mod, st = _ui(monkeypatch)
    st.slider.side_effect = lambda label, lo, hi, d, **k: hi
    before = copy.deepcopy(cs.CRITERIA)
    mod.render(None, None, "t")
    assert cs.CRITERIA == before
