"""Methodology & Evidence screen. Streamlit UI only; all logic is in ``methodology`` (pure, tested).

Read-only: nothing here changes the baseline weights, the ranking on the Prioritize screen, or any stored record. "What if" sliders work on copies.
"""
from __future__ import annotations

from typing import Any

import streamlit as st

import civicsignal as cs
import methodology as mt


def _baseline() -> dict[str, float]:
    return {k: float(w) for k, _label, w, _src in cs.CRITERIA}


def render(identity: Any, backend: Any, tenant: str, *, sample_data: bool = True) -> None:
    st.title("Methodology & Evidence")
    st.caption("How CivicSignal's rankings are calculated, where each input comes from, and how sure we can be. This page describes the scoring that is "
               "implemented in the application; it does not add a different method.")
    status = mt.data_status(verified=not sample_data)
    (st.warning if sample_data else st.info)(f"{status['label']}. {status['detail']}")

    projects = cs.PROJECTS
    base = _baseline()
    t1, t2, t3, t4 = st.tabs(["Sources and formulas", "Why this rank", "What if the weights change", "Limits and export"])

    with t1:
        st.subheader("Project ranking formula")
        st.code(mt.formula_text(), language="text")
        rows = mt.criteria_table(base, verified=not sample_data)
        st.dataframe([{"Criterion": r["label"], "Weight": r["weight"], "Share": f"{r['share']:.0%}", "Evidence kind": r["evidence_kind"],
                       "Source": r["source"], "Data status": r["data_status"]} for r in rows], use_container_width=True)
        st.caption("Evidence kind says what the real-world source is: observed events, a modeled or derived index, an estimate, or self-reported.")
        for r in rows:
            st.markdown(f"**{r['label']} ({r['evidence_kind']}).** {r['evidence_note']}")
        st.subheader("County narrative bands")
        st.caption("County summaries classify social vulnerability (SVI) into bands and flag a county as compound when exposure and vulnerability are both high.")
        r_score = st.slider("Hazard risk score", 0, 5, 3, key="meth_risk")
        svi = st.slider("SVI (percent)", 0, 100, 50, key="meth_svi")
        band = mt.county_band(float(r_score), svi / 100.0)
        st.write(f"SVI band: **{band['svi_label']}**. Reading: **{band['case']}**.")
        st.caption("Bands: " + ", ".join(f"{lbl} at {fl:g} or above" for fl, lbl in mt.SVI_BANDS) +
                   f". Significant exposure means a risk score of {mt.COMPOUND_RISK_THRESHOLD:g} or above.")

    with t2:
        st.subheader("Why a project has its rank")
        names = {p["name"]: p for p in projects}
        pick = st.selectbox("Project", list(names), key="meth_project")
        ex = mt.explain_project(names[pick], projects, base)
        c = st.columns(3)
        c[0].metric("Rank", f"{ex['rank']} of {ex['of']}")
        c[1].metric("Score", f"{ex['score']:.1f}")
        c[2].metric("Strongest driver", ex["top_driver"])
        st.dataframe([{"Criterion": p["label"], "Value (0-100)": p["value"], "Weight": p["weight"], "Points toward score": round(p["points"], 1),
                       "Source": p["source"]} for p in ex["parts"]], use_container_width=True)
        st.bar_chart({p["label"]: p["points"] for p in ex["parts"]})
        st.write(f"The score is the sum of the points column. Weakest contribution: **{ex['weakest_driver']}**.")

    with t3:
        st.subheader("Try different weights")
        st.caption("These sliders change a copy only. The official baseline weights and the ranking on the Prioritize screen are not affected.")
        adj: dict[str, float] = {}
        for key, label, default, _src in cs.CRITERIA:
            adj[key] = float(st.slider(label, 0, 60, int(default), key=f"meth_w_{key}"))
        if not cs.weights_valid(adj):
            st.error("Total weight must be at least 1. Raise at least one weight to compare rankings.")
        else:
            cmp_rows = mt.compare_weights(projects, base, adj)
            st.dataframe([{"Project": r["name"], "Baseline rank": r["baseline_rank"], "Rank with your weights": r["adjusted_rank"],
                           "Change": ("up " + str(r["change"])) if r["change"] > 0 else ("down " + str(-r["change"])) if r["change"] < 0 else "no change",
                           "Baseline score": round(r["baseline_score"], 1), "Your score": round(r["adjusted_score"], 1)} for r in cmp_rows],
                         use_container_width=True)
            moved = sum(1 for r in cmp_rows if r["change"] != 0)
            st.write(f"{moved} of {len(cmp_rows)} projects change rank with these weights.")
        st.subheader("How stable is the baseline ranking?")
        st.caption("Each weight is moved up and down by 5 and 10 points, one at a time. A project whose best and worst ranks are far apart depends on that choice.")
        st.dataframe([{"Project": r["name"], "Baseline rank": r["baseline_rank"], "Best rank": r["best"], "Worst rank": r["worst"],
                       "Stable (within 1)": "Yes" if r["stable"] else "No"} for r in mt.rank_stability(projects, base)], use_container_width=True)

    with t4:
        st.subheader("Limitations")
        for x in mt.LIMITATIONS:
            st.markdown(f"- {x}")
        st.subheader("Data gaps in this build")
        for g in mt.data_gaps(projects):
            st.markdown(f"- {g}")
        st.download_button("Download methodology summary (Markdown)", mt.summary_markdown(projects, base, verified=not sample_data),
                           file_name="civicsignal_methodology_summary.md", mime="text/markdown", key="meth_dl")
