"""Methodology & Evidence (pure, no Streamlit).

Explains the scoring that is ALREADY implemented in ``civicsignal.py`` (project ranking) and ``analysis.py`` (county narrative bands). It does not add a new
method. Everything here reads the live criteria and weights, so the explanation cannot drift from the code, and a test checks the county band thresholds
against ``analysis.rule_based_risk_analysis``.

Sensitivity analysis works on COPIES of the weights. The baseline in ``civicsignal.CRITERIA`` is never changed.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import civicsignal as cs

# What kind of evidence each criterion is, in general terms. These describe the real-world sources the criterion is meant to come from; in this build the
# values are invented samples (see ``data_status``).
EVIDENCE_KIND: dict[str, tuple[str, str]] = {
    "risk": ("Modeled", "FEMA National Risk Index is a modeled index (expected annual loss, social vulnerability and community resilience)."),
    "vul": ("Derived index", "CDC/ATSDR SVI ranks areas from Census survey estimates; a composite index, not a direct count."),
    "loss": ("Observed", "Claims and assistance history are recorded events, but they undercount uninsured and unreported losses."),
    "bcr": ("Estimated", "A benefit-cost ratio is an estimate from the FEMA BCA Toolkit; it depends on the inputs the applicant supplies."),
    "ready": ("Self-reported", "Design status and local match come from the applicant and have not been independently checked."),
}

# County narrative bands as implemented in analysis.rule_based_risk_analysis. A test keeps this table in step with the code.
SVI_BANDS = [(0.75, "Very High"), (0.50, "High"), (0.25, "Moderate"), (0.0, "Low")]
COMPOUND_RISK_THRESHOLD = 3.0  # risk_score at or above this counts as significant exposure
COMPOUND_SVI_THRESHOLD = 0.50

LIMITATIONS = [
    "Scores are relative rankings between the projects shown. They are not probabilities, dollar losses, or predictions.",
    "Each criterion is already on a 0 to 100 scale when it enters the formula; this build does not rescale raw data.",
    "Weights are a policy choice. The default weights are the prototype's starting point and have not been validated against outcomes.",
    "Eligibility rules are checked separately and fail closed; a high score never makes an ineligible project eligible.",
    "Nothing here is a FEMA determination or legal advice.",
]


def data_status(verified: bool) -> dict[str, str]:
    """Plain statement of whether the numbers on screen are real. ``verified`` is True only when an administrator has loaded and confirmed real data."""
    if verified:
        return {"label": "Verified data loaded", "detail": "An administrator marked the loaded data as verified. Check each source's vintage before relying on it."}
    return {"label": "Illustrative sample data",
            "detail": "The county and project figures are invented to show how the method works. They are not official records and must not be used for decisions."}


def criteria_table(weights: dict[str, float] | None = None, verified: bool = False) -> list[dict[str, Any]]:
    """One row per criterion: weight, share of the total, source, evidence kind, and what the evidence kind means."""
    w = dict(weights) if weights is not None else {k: float(wt) for k, _l, wt, _s in cs.CRITERIA}
    total = cs.total_weight(w)
    rows = []
    for key, label, default_wt, source in cs.CRITERIA:
        kind, why = EVIDENCE_KIND.get(key, ("Unspecified", ""))
        rows.append({"key": key, "label": label, "default_weight": default_wt, "weight": float(w.get(key, 0)),
                     "share": (float(w.get(key, 0)) / total) if total else 0.0, "source": source,
                     "evidence_kind": kind, "evidence_note": why, "data_status": data_status(verified)["label"]})
    return rows


def formula_text() -> str:
    return "score = (sum over criteria of value x weight) / (sum of weights); each value is 0 to 100. Ties are broken by lower cost."


def _rank(projects: list[dict[str, Any]], weights: dict[str, float]) -> dict[str, int]:
    scored = [(p["id"], cs.score_of(p, weights), p["cost"]) for p in projects]
    scored.sort(key=lambda t: (-t[1], t[2]))
    return {pid: i + 1 for i, (pid, _s, _c) in enumerate(scored)}


def explain_project(project: dict[str, Any], projects: list[dict[str, Any]], weights: dict[str, float] | None = None) -> dict[str, Any]:
    """Why a project has its score and rank: each criterion's value, weight and contribution, plus the strongest and weakest drivers."""
    w = dict(weights) if weights is not None else {k: float(wt) for k, _l, wt, _s in cs.CRITERIA}
    total = cs.total_weight(w)
    score = cs.score_of(project, w)
    ranks = _rank(projects, w)
    parts = []
    for key, label, _wt, source in cs.CRITERIA:
        val = float(project[key])
        wt = float(w.get(key, 0))
        parts.append({"key": key, "label": label, "value": val, "weight": wt, "points": val * wt / total, "source": source})
    by_points = sorted(parts, key=lambda r: -r["points"])
    return {"id": project["id"], "name": project["name"], "score": score, "rank": ranks[project["id"]], "of": len(projects), "parts": parts,
            "top_driver": by_points[0]["label"], "weakest_driver": by_points[-1]["label"]}


def compare_weights(projects: list[dict[str, Any]], baseline: dict[str, float], adjusted: dict[str, float]) -> list[dict[str, Any]]:
    """Baseline versus adjusted ranks. The inputs are not modified."""
    b, a = _rank(projects, dict(baseline)), _rank(projects, dict(adjusted))
    rows = []
    for p in projects:
        rows.append({"id": p["id"], "name": p["name"], "baseline_rank": b[p["id"]], "adjusted_rank": a[p["id"]], "change": b[p["id"]] - a[p["id"]],
                     "baseline_score": cs.score_of(p, baseline), "adjusted_score": cs.score_of(p, adjusted)})
    return sorted(rows, key=lambda r: r["adjusted_rank"])


def rank_stability(projects: list[dict[str, Any]], baseline: dict[str, float], deltas: tuple[int, ...] = (-10, -5, 5, 10)) -> list[dict[str, Any]]:
    """For each project, the best and worst rank when any one criterion's weight is moved by each delta (never below zero). A narrow range means the
    ranking does not depend much on that weight choice."""
    base_rank = _rank(projects, dict(baseline))
    seen: dict[str, list[int]] = {p["id"]: [base_rank[p["id"]]] for p in projects}
    scenarios = 0
    for key, *_ in cs.CRITERIA:
        for d in deltas:
            w = dict(baseline)
            w[key] = max(0.0, float(w.get(key, 0)) + d)
            if not cs.weights_valid(w):
                continue
            scenarios += 1
            r = _rank(projects, w)
            for pid, rk in r.items():
                seen[pid].append(rk)
    out = []
    for p in projects:
        ranks = seen[p["id"]]
        out.append({"id": p["id"], "name": p["name"], "baseline_rank": base_rank[p["id"]], "best": min(ranks), "worst": max(ranks),
                    "spread": max(ranks) - min(ranks), "stable": (max(ranks) - min(ranks)) <= 1, "scenarios": scenarios})
    return sorted(out, key=lambda r: r["baseline_rank"])


def county_band(risk_score: float, svi: float) -> dict[str, Any]:
    """How the county narrative classifies a risk score and SVI, with the thresholds used."""
    label = next(lbl for floor, lbl in SVI_BANDS if svi >= floor)
    significant = risk_score >= COMPOUND_RISK_THRESHOLD
    high_svi = svi >= COMPOUND_SVI_THRESHOLD
    if high_svi and significant:
        case = "Compound: significant exposure and high vulnerability"
    elif high_svi:
        case = "High vulnerability, lower exposure"
    elif significant:
        case = "Significant exposure, lower vulnerability"
    else:
        case = "Routine monitoring"
    return {"svi_label": label, "significant_exposure": significant, "high_vulnerability": high_svi, "case": case,
            "thresholds": {"svi_bands": SVI_BANDS, "risk_score_at_or_above": COMPOUND_RISK_THRESHOLD}}


def data_gaps(projects: list[dict[str, Any]]) -> list[str]:
    """Gaps a reader should know about, from the data actually loaded."""
    gaps = []
    no_bca = [p["id"] for p in projects if p.get("bca_ratio") is None]
    if no_bca:
        gaps.append(f"{len(no_bca)} of {len(projects)} projects have no benefit-cost ratio on file ({', '.join(no_bca)}); the benefit-cost criterion for them is a sample value.")
    no_scope = [p["id"] for p in projects if not p.get("scope")]
    if no_scope:
        gaps.append(f"{len(no_scope)} projects have no scope recorded, so scope-based rules cannot be evaluated for them.")
    gaps.append("No data vintage (year) is recorded for any criterion in this build.")
    return gaps


def summary_markdown(projects: list[dict[str, Any]], weights: dict[str, float] | None = None, verified: bool = False,
                     today: date | None = None) -> str:
    """Exportable methodological summary: what is computed, from what, with which weights, and what is uncertain."""
    w = dict(weights) if weights is not None else {k: float(wt) for k, _l, wt, _s in cs.CRITERIA}
    st = data_status(verified)
    lines = ["# CivicSignal: Methodology Summary", "", f"Generated {(today or date.today()).isoformat()}.", "",
             f"**Data status: {st['label']}.** {st['detail']}", "", "## Formula", "", formula_text(), "", "## Criteria, weights and sources", "",
             "| Criterion | Weight | Share | Evidence kind | Source |", "| --- | --- | --- | --- | --- |"]
    for r in criteria_table(w, verified):
        lines.append(f"| {r['label']} | {r['weight']:g} | {r['share']:.0%} | {r['evidence_kind']} | {r['source']} |")
    lines += ["", "## What each evidence kind means", ""]
    for r in criteria_table(w, verified):
        lines.append(f"- **{r['label']} ({r['evidence_kind']}):** {r['evidence_note']}")
    lines += ["", "## Ranking with these weights", "", "| Rank | Project | Score |", "| --- | --- | --- |"]
    for p in sorted(projects, key=lambda p: (-cs.score_of(p, w), p["cost"])):
        lines.append(f"| {_rank(projects, w)[p['id']]} | {p['name']} | {cs.score_of(p, w):.1f} |")
    lines += ["", "## How stable is the ranking?", "",
              "Each weight was moved by 5 and 10 points up and down, one at a time. Best and worst rank for each project:", "",
              "| Project | Baseline | Best | Worst |", "| --- | --- | --- | --- |"]
    for r in rank_stability(projects, w):
        lines.append(f"| {r['name']} | {r['baseline_rank']} | {r['best']} | {r['worst']} |")
    lines += ["", "## County narrative bands", "", "SVI bands: " + ", ".join(f"{lbl} at {fl:g} or above" for fl, lbl in SVI_BANDS) +
              f". A county is called compound when the risk score is {COMPOUND_RISK_THRESHOLD:g} or above and SVI is {COMPOUND_SVI_THRESHOLD:g} or above.",
              "", "## Data gaps", ""] + [f"- {g}" for g in data_gaps(projects)] + ["", "## Limitations", ""] + [f"- {x}" for x in LIMITATIONS]
    return "\n".join(lines) + "\n"
