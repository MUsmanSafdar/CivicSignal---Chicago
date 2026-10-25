"""Regression tests for Phase 0 (correctness and safety)."""
from __future__ import annotations

import ast
import pathlib
import time

import pandas as pd
import pytest

import analysis
import chatbot_engine as ce
import civicsignal as cs
from hazard_taxonomy import CANONICAL_HAZARDS, normalize_hazard, normalize_hazard_column
from pdf_tasks import TaskTimeout, run_with_timeout
from safe_stats import count_by, format_kpi, safe_mean, safe_pivot, top_per_group

ROOT = pathlib.Path(__file__).resolve().parent.parent


# ---- 0.1 router -----------------------------------------------------------------------------
def test_router_has_exactly_one_radio_and_every_branch_but_dashboard_stops():
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    radios = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "radio"
              and getattr(getattr(n.func, "value", None), "id", "") == "st"]
    assert len(radios) == 1
    options = [e.value for e in radios[0].args[1].elts]
    assert {"CivicSignal prioritization", "Hazard dashboard", "Cooling centers & shelters"} <= set(options)
    for node in tree.body:
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare) \
                and getattr(node.test.left, "id", "") == "_workspace":
            assert any(isinstance(b, ast.Expr) and "stop" in ast.dump(b) for b in node.body)


# ---- 0.2 chatbot safety ---------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("emergency cooling center needed", "emergency"),
    ("cooling center 60639", "cooling"),
    ("trapped in flooding right now", "emergency"),
    ("hi, emergency at the shelter", "emergency"),
    ("where is the nearest shelter", "shelter"),
])
def test_intent_priority(text, expected):
    assert ce.detect_intent(text) == expected


# ---- 0.3 taxonomy ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw,canon", [
    ("Flooding", "Flood"), ("flood", "Flood"), ("Heat Wave", "Extreme Heat"), ("heat-wave", "Extreme Heat"),
    ("Tornadoes", "Tornado"), ("severe storms", "Severe Storm"), ("Blizzard", "Winter Storm"),
    ("Earthquake", "Earthquake"), ("Drought", "Drought"), ("  FLOODING ", "Flood"),
])
def test_normalize_known(raw, canon):
    assert normalize_hazard(raw) == canon and canon in CANONICAL_HAZARDS


def test_normalize_unknown_and_missing_fall_back():
    assert normalize_hazard("Wildfire") == "Wildfire"
    assert normalize_hazard("sinkhole") == "Sinkhole"
    assert normalize_hazard(None) == "Unknown" and normalize_hazard("") == "Unknown" and normalize_hazard(float("nan")) == "Unknown"


def test_normalize_column_keeps_raw():
    out = normalize_hazard_column(pd.DataFrame({"hazard": ["Flooding", "Heat Wave"]}))
    assert out["hazard"].tolist() == ["Flood", "Extreme Heat"] and out["hazard_raw"].tolist() == ["Flooding", "Heat Wave"]
    assert normalize_hazard_column(pd.DataFrame({"x": [1]})).shape == (1, 1)


def test_analysis_tables_use_canonical_keys():
    assert set(analysis.HAZARD_ACTIONS) <= set(CANONICAL_HAZARDS)
    assert set(analysis.INTERPRETATION) <= set(CANONICAL_HAZARDS)


# ---- 0.4 analysis schema --------------------------------------------------------------------
CAP = pd.DataFrame({
    "county": ["Cook", "Cook", "DuPage"], "hazard": ["Flood", "Severe Storm", "Flood"],
    "mitigation_effort": ["Early warning", "Tree program", "Basin"], "budget_usd": [1000, 500, 200],
    "amount_spent_usd": [250, 100, 50], "people_affected": [10, 20, 30],
})
ROW = pd.Series({"county": "Cook", "hazard": "Flooding", "risk_score": 3.4, "risk_level": "High", "svi_score": 0.7})


def test_analysis_reads_capacity_columns_filtered_by_county_and_hazard():
    res = analysis.rule_based_risk_analysis(ROW, CAP)
    assert [e["effort"] for e in res["efforts"]] == ["Early warning"]
    e = res["efforts"][0]
    assert (e["budget"], e["spent"], e["people"]) == (1000.0, 250.0, 10) and e["pct"] == 25.0
    assert res["hazard"] == "Flood"


def test_analysis_degrades_without_columns_or_data():
    assert analysis.rule_based_risk_analysis(ROW, None)["efforts"] == []
    assert analysis.rule_based_risk_analysis(ROW, pd.DataFrame())["efforts"] == []
    thin = CAP[["county", "hazard"]]
    eff = analysis.rule_based_risk_analysis(ROW, thin)["efforts"]
    assert eff and eff[0]["budget"] == 0 and eff[0]["pct"] == 0 and eff[0]["people"] == 0


def test_app_no_longer_defines_its_own_analysis():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "def _rule_based_risk_analysis" not in src and "filtered_actions[filtered_actions" not in src


# ---- 0.5 chatbot scope ----------------------------------------------------------------------
def test_chat_answers_for_county_outside_dashboard_scope():
    risk = pd.DataFrame({"county": ["Cook", "Sangamon"], "region": ["Northeast", "Central"], "hazard": ["Flood", "Flood"],
                         "risk_score": [3.0, 4.2], "risk_level": ["High", "Very High"], "svi_score": [0.5, 0.6]})
    reply = ce.chat("risk level for Sangamon County", risk, pd.DataFrame(), pd.DataFrame())
    assert "Sangamon" in reply and "Very High" in reply
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "risk_df=risk_all" in src and "capacity_df=capacity_all" in src and "complaints_df=complaints_all" in src


# ---- 0.6 cache invalidation -----------------------------------------------------------------
def test_reference_tables_reload_when_file_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(ce, "_DATA_DIR", tmp_path)
    ce.clear_cache()
    f = tmp_path / "shelters.csv"
    f.write_text("name\nA\n", encoding="utf-8")
    assert ce._load_shelters()["name"].tolist() == ["A"]
    f.write_text("name\nA\nB\n", encoding="utf-8")        # size changes, so the signature changes
    assert ce._load_shelters()["name"].tolist() == ["A", "B"]
    assert ce._load_aid().empty                              # missing file -> empty frame


# ---- 0.7 weights guard ----------------------------------------------------------------------
def test_zero_total_weight_raises_not_silently_ranks_by_cost():
    zero = {k: 0 for k, *_ in cs.CRITERIA}
    assert not cs.weights_valid(zero)
    with pytest.raises(cs.WeightsError):
        cs.ranked(cs.PROJECTS, zero, {})
    ok, msg = cs.decide(cs.new_state(), cs.PROJECTS[0]["id"], "held", "reason", "x", zero, 4.0)
    assert ok is False and "weight" in msg.lower()


def test_valid_weights_still_rank():
    w = {k: d for k, _, d, _ in cs.CRITERIA}
    assert cs.weights_valid(w) and len(cs.ranked(cs.PROJECTS, w, {})) == len(cs.PROJECTS)


# ---- 0.8 performance ------------------------------------------------------------------------
def test_run_with_timeout_returns_and_times_out():
    assert run_with_timeout(lambda: 7, timeout_s=2) == 7
    ticks: list[float] = []
    t0 = time.monotonic()
    with pytest.raises(TaskTimeout):
        run_with_timeout(lambda: time.sleep(2), timeout_s=0.5, poll_s=0.1, on_tick=ticks.append)
    assert time.monotonic() - t0 < 1.5 and ticks


def test_run_with_timeout_propagates_errors():
    def boom() -> None:
        raise ValueError("bad pdf")
    with pytest.raises(ValueError):
        run_with_timeout(boom, timeout_s=2)


def test_geojson_parse_cache_is_keyed_on_file_mtime():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "@st.cache_resource" in src and "def _parse_county_geojson(path, mtime)" in src


# ---- 0.9 robustness -------------------------------------------------------------------------
def test_empty_and_nan_frames_do_not_raise():
    empty = pd.DataFrame()
    assert safe_mean(empty, "risk_score") is None and safe_mean(None, "x") is None
    assert safe_mean(pd.DataFrame({"risk_score": [float("nan")]}), "risk_score") is None
    assert safe_mean(pd.DataFrame({"risk_score": [1.0, 2.0]}), "risk_score") == 1.5
    assert format_kpi(None) == "N/A" and format_kpi(2.5) == 2.5
    assert safe_pivot(empty, "a", "b", "c").empty
    assert safe_pivot(pd.DataFrame({"a": [1]}), "a", "b", "c").empty
    assert top_per_group(empty, "county", "risk_score").empty
    assert count_by(empty, ["county", "status"]).columns.tolist() == ["county", "status", "count"]
    risk = pd.DataFrame({"county": ["A", "A"], "hazard": ["Flood", "Tornado"], "risk_score": [1.0, 3.0]})
    assert top_per_group(risk, "county", "risk_score")["hazard"].tolist() == ["Tornado"]
    assert safe_pivot(risk, "county", "hazard", "risk_score").shape == (1, 2)


def test_capacity_frame_is_defined_before_the_county_analysis_uses_it():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert src.index("capacity_df = normalize_hazard_column(capacity_df)") < src.index("_rule_based_risk_analysis(county_row_for_ai")
    assert src.index("risk_all = risk_df.copy()") < src.index("risk_df = _config.scope_frame(risk_df, SCOPE_COUNTIES)")


def test_chat_survives_empty_frames():
    risk = pd.DataFrame({"county": ["Cook"], "region": ["NE"], "hazard": ["Flood"], "risk_score": [3.0],
                         "risk_level": ["High"], "svi_score": [0.5]})
    for msg in ("mitigation efforts in Cook County", "complaints in Cook County", "risk level for Cook County"):
        assert isinstance(ce.chat(msg, risk, pd.DataFrame(), pd.DataFrame()), str)
