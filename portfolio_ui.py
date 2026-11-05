"""Action Portfolio screen: read a hazard mitigation plan annex (PDF) and show what it says about priorities and funding.

Streamlit UI only. All parsing and scoring is in ``action_plan`` (pure, tested). Nothing is stored; the analysis lives in the session.
Not a FEMA determination, and the fit score is a keyword first pass that the reviewer can correct.
"""
from __future__ import annotations

from typing import Any

import streamlit as st

import action_plan as ap
import identity as ident
from pdf_tasks import DEFAULT_TIMEOUT_S, TaskTimeout, run_with_timeout

MAX_UPLOAD_MB = 60


def render(identity: Any, backend: Any, tenant: str, *, sample_data: bool = True) -> None:
    st.title("Action Portfolio")
    st.caption("Reads the mitigation action tables in a hazard mitigation plan or jurisdictional annex and shows how the plan itself rates and funds its actions. "
               "It does not decide what a jurisdiction should fund and is not a FEMA determination.")
    if sample_data:
        st.info("Demonstration mode. Use a public plan document; do not upload anything confidential.")
    if not ident.can(identity, "pas_view"):
        st.warning("Sign in with a role that can view the review center to use this screen.")
        return
    up = st.file_uploader("Upload a plan or annex PDF", type=["pdf"], key="portfolio_pdf")
    if up is None:
        st.write("Upload a PDF in the Cook County MJ-HMP annex format (actions labelled “Mitigation Action #n”). Other formats may be read only in part.")
        return
    if getattr(up, "size", 0) > MAX_UPLOAD_MB * 1024 * 1024:
        st.error(f"That file is larger than {MAX_UPLOAD_MB} MB.")
        return
    raw = up.read()
    try:
        doc = run_with_timeout(lambda: ap.extract_pdf_text(raw), DEFAULT_TIMEOUT_S)
    except TaskTimeout:
        st.error("Reading the PDF took too long. Try a smaller file.")
        return
    except Exception:  # noqa: BLE001 - a bad PDF should show a message, not a stack trace
        st.error("This file could not be read as a PDF.")
        return
    res = ap.analyze(doc["text"])
    acts = res["actions"]
    if not acts:
        st.warning("No “Mitigation Action #n” entries were found. The file may be in a different format or scanned as an image.")
        return

    over: dict[int, dict[str, int]] = st.session_state.setdefault("portfolio_overrides", {})
    shown = ap.apply_overrides(acts, over)
    s = ap.summarize(shown)
    st.subheader("What the document says")
    c = st.columns(4)
    c[0].metric("Actions read", s["actions_read"])
    c[1].metric("Rated High", s["priority_counts"]["High"])
    c[2].metric("Rated Medium", s["priority_counts"]["Medium"])
    c[3].metric("List HMGP / BRIC / FEMA funding", s["grant_source_listed"])
    if s["numbers_missing_from_range"]:
        st.warning(f"Action numbers not found in this file: {', '.join(str(n) for n in s['numbers_missing_from_range'])}. "
                   "The document may not contain them, or they may be formatted differently.")
    if not s["ratings_separate_actions"]:
        st.write(f"{s['share_high_or_medium']:.0%} of rated actions are High or Medium, so the plan's own ratings do little to separate one action from another.")
    if any(res["unread"].values()):
        st.caption("Fields that could not be read: " + ", ".join(f"{k} ({v})" for k, v in res["unread"].items() if v))

    st.subheader("Where vulnerability-based ranking would help")
    st.caption("Fit score = place-specific (0 to 2) + relevance to vulnerable residents (0 to 2) + 1 if a FEMA hazard mitigation grant is listed as a possible source. "
               "Strong is 4 or 5, Moderate 2 or 3, Weak 0 or 1. The first two parts come from a keyword rule and should be checked by a person; completed "
               "actions and actions the jurisdiction asked to remove are left out.")
    tier = st.selectbox("Show", ["All", "Strong", "Moderate", "Weak"], key="portfolio_tier")
    rows = [a for a in shown if a["counted_in_fit"] and (tier == "All" or a["fit_tier"] == tier)]
    rows.sort(key=lambda a: (-a["fit_score"], a["number"]))
    st.dataframe([{"Action": a["number"], "Title": a["title"][:110], "Status": a["status"], "Plan priority": a["priority"] or "n/a",
                   "Place": a["place_score"], "Vulnerability": a["vulnerability_score"], "Grant listed": "Yes" if a["grant_source_listed"] else "No",
                   "Fit": a["fit_score"], "Tier": a["fit_tier"], "Reviewed": "Yes" if a.get("reviewed") else ""} for a in rows], use_container_width=True)
    st.caption(f"Fit tiers across {sum(s['fit_counts'].values())} actions: " + ", ".join(f"{k} {v}" for k, v in s["fit_counts"].items()))

    if ident.can(identity, "pas_review"):
        with st.expander("Correct a score"):
            nums = [a["number"] for a in acts]
            n = st.selectbox("Action", nums, key="portfolio_pick")
            cur = next(a for a in shown if a["number"] == n)
            p = st.number_input("Place-specific (0 to 2)", 0, 2, int(cur["place_score"]), key="portfolio_place")
            v = st.number_input("Relevance to vulnerable residents (0 to 2)", 0, 2, int(cur["vulnerability_score"]), key="portfolio_vuln")
            if st.button("Save correction", key="portfolio_save"):
                over[int(n)] = {"place": int(p), "vulnerability": int(v)}
                st.session_state["portfolio_overrides"] = over
                st.success(f"Saved for action {n}. This stays in this session only.")
    st.download_button("Download the table (CSV)", ap.to_csv(shown), file_name="action_portfolio.csv", mime="text/csv", key="portfolio_csv")
