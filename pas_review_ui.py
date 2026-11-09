"""PAS Document Review (Streamlit UI). Logic is in ``pas_review`` (pure, tested).

Upload only stages the file in this session. Nothing is analyzed or stored until a signed-in user with the intake permission presses Submit for review.
Reviews persist in the tenant settings store; every action is also written to the hash-chained audit trail.
"""
from __future__ import annotations

from typing import Any

import streamlit as st

import audit_store
import identity as ident
import pas_review as pr

SETTING_KEY = "pas_doc_reviews_v1"


def _actor(identity: Any) -> str:
    return identity.actor if identity else "anonymous"


def load_reviews(backend: Any, tenant: str) -> dict[str, Any]:
    raw = backend.get_setting(tenant, SETTING_KEY, None) or {}
    return {"seq": int(raw.get("seq", 0)), "reviews": dict(raw.get("reviews", {}))}


def save_reviews(backend: Any, tenant: str, store: dict[str, Any]) -> None:
    backend.set_setting(tenant, SETTING_KEY, {"schema": 1, "seq": store["seq"], "reviews": store["reviews"]})


def _log(backend: Any, tenant: str, actor: str, action: str, rid: str, detail: dict[str, Any]) -> None:
    audit_store.append_event(backend, tenant, actor, f"pas.docreview.{action}", "doc_review", rid, detail)


def render(identity: Any, backend: Any, tenant: str, *, sample_data: bool = True) -> None:
    st.subheader("Document review")
    st.caption("Upload a plan, project or grant document, submit it for review, then work through the findings. This is an internal aid, not a FEMA determination.")
    can_submit = ident.can(identity, "pas_intake")
    can_review = ident.can(identity, "pas_review")
    can_decide = ident.can(identity, "pas_decide")
    if not can_submit:
        st.info("Sign in with a reviewer, official or admin role to submit and review documents. You can read existing reviews.")
    store = load_reviews(backend, tenant)
    ids = sorted(store["reviews"], reverse=True)
    mode = st.radio("Work on", ["New submission"] + ids, horizontal=True, key="docrev_pick") if ids else "New submission"
    review = None if mode == "New submission" else store["reviews"][mode]
    staged = st.session_state.get("docrev_staged")
    st.progress((pr.step(review, bool(staged)) + 1) / len(pr.STEPS), text=" > ".join(
        f"**{s}**" if i == pr.step(review, bool(staged)) else s for i, s in enumerate(pr.STEPS)))

    if review is None:
        _submission(identity, backend, tenant, store, can_submit)
    else:
        _workspace(identity, backend, tenant, store, review, can_review, can_decide, sample_data)


def _submission(identity: Any, backend: Any, tenant: str, store: dict[str, Any], can_submit: bool) -> None:
    up = st.file_uploader("1. Upload document", type=[e.lstrip(".") for e in pr.ALLOWED_EXT], key="docrev_up",
                          help=f"PDF, text, Markdown or CSV, up to {pr.MAX_BYTES // (1024 * 1024)} MB. Only a hash and short excerpts are stored, not the file.")
    if up is not None:
        try:
            raw = up.getvalue()
            facts = pr.validate_upload(up.name, raw)
            st.session_state["docrev_staged"] = {"facts": facts, "raw": raw}
            st.success(f"Uploaded {facts['name']} ({facts['size']:,} bytes). It has NOT been submitted yet.")
        except pr.ReviewError as e:
            st.session_state.pop("docrev_staged", None)
            st.error(str(e))
    else:
        st.session_state.pop("docrev_staged", None)
    staged = st.session_state.get("docrev_staged")
    if not staged:
        return
    st.markdown("**2. Configure review**")
    c = st.columns(2)
    program = c[0].selectbox("Funding program", list(pr.PROGRAMS), key="docrev_prog")
    jur = c[1].text_input("Jurisdiction", key="docrev_jur")
    proj = c[0].text_input("Project name", key="docrev_proj")
    gv = c[1].text_input("Program guidance version (optional)", key="docrev_gv")
    st.caption("The review checks the document against the PAS requirement catalogue for this program.")
    st.markdown("**3. Submit for review**")
    if st.button("Submit for review", type="primary", disabled=not can_submit, key="docrev_submit") and can_submit:
        actor = _actor(identity)
        try:
            store["seq"] += 1
            rid = pr.next_review_id(store["seq"])
            review = pr.new_review(rid, actor, staged["facts"], {"program": program, "jurisdiction": jur, "project": proj, "guidance_version": gv})
            with st.status("Submitting and analyzing...", expanded=True) as stat:
                st.write(f"Review {rid} created at {review['created_at']}.")
                units = pr.extract_units(staged["facts"]["ext"], staged["raw"])
                pr.analyze(review, units, actor)
                st.write(f"Analysis complete: {len(review['findings'])} findings.")
                store["reviews"][rid] = review
                save_reviews(backend, tenant, store)
                _log(backend, tenant, actor, "submitted", rid, {"sha256": staged["facts"]["sha256"], "program": program})
                _log(backend, tenant, actor, "analyzed", rid, {"findings": len(review["findings"])})
                stat.update(label=f"Submitted as {rid}", state="complete")
            st.session_state.pop("docrev_staged", None)
            st.success(f"Review ID {rid}, submitted {review['created_at']}. Select it above to review findings.")
        except pr.ReviewError as e:
            store["seq"] -= 1
            st.error(str(e))
        except Exception as e:  # noqa: BLE001 - unreadable PDFs, storage failures: say so, change nothing
            store["seq"] = max(0, store["seq"] - 1)
            st.error(f"Could not complete the review: {e}. Nothing was saved.")


def _workspace(identity: Any, backend: Any, tenant: str, store: dict[str, Any], review: dict[str, Any], can_review: bool, can_decide: bool,
               sample_data: bool) -> None:
    actor, rid = _actor(identity), review["id"]
    s = pr.summary(review)
    st.write(f"**{rid}** | {review['config']['project']} | {review['config']['jurisdiction']} | {review['config']['program']} | submitted {review['created_at']}")
    m = st.columns(5)
    for col, (k, v) in zip(m, s["counts"].items()):
        col.metric(pr.CATEGORY_LABEL[k].split(",")[0], v)
    st.progress(s["progress"], text=f"{s['handled']} of {s['total']} findings handled; {s['blocking']} blocking")
    show = st.multiselect("Show", list(pr.CATEGORY_LABEL), default=list(pr.CATEGORY_LABEL), format_func=pr.CATEGORY_LABEL.get, key=f"docrev_f_{rid}")
    for f in review["findings"]:
        if f["category"] not in show:
            continue
        mark = {"located": "?", "verified": "OK", "issue": "!", "missing": "-", "undeterminable": "FEMA"}[f["category"]]
        with st.expander(f"[{mark}] {f['id']} {f['label']} ({f['status']})"):
            st.write(f["explanation"])
            st.caption(f"Decided by: {f['authority']}. Source: {f['source_title']}" + ("" if f["source_confirmed"] else " (text not yet confirmed)"))
            for e in f["evidence"]:
                st.markdown(f"- **{e['locator']}:** {e['snippet']}")
            if f["note"]:
                st.info(f"{f['resolved_by']} at {f['resolved_at']}: {f['note']}")
            if can_review and not review["decision"]:
                note = st.text_input("Note", key=f"docrev_n_{rid}_{f['id']}")
                b = st.columns(2)
                label = "Confirm evidence" if f["category"] == "located" else "Mark resolved"
                if f["status"] == "open" and b[0].button(label, key=f"docrev_c_{rid}_{f['id']}"):
                    _act(backend, tenant, store, review, lambda f=f, note=note: pr.close_finding(review, f["id"], actor, note), actor, "finding_closed", f["id"])
                if f["status"] != "open" and b[1].button("Reopen", key=f"docrev_r_{rid}_{f['id']}"):
                    _act(backend, tenant, store, review, lambda f=f, note=note: pr.reopen_finding(review, f["id"], actor, note), actor, "finding_reopened", f["id"])
    st.markdown("**Decision**")
    if review["decision"]:
        d = review["decision"]
        st.success(f"{pr.DECISION_LABEL[d['decision']]}: {d['note']} ({d['by']}, {d['at']})")
    elif can_decide:
        dec = st.selectbox("Outcome", list(pr.DECISIONS), format_func=pr.DECISION_LABEL.get, key=f"docrev_d_{rid}")
        dn = st.text_area("Decision note", key=f"docrev_dn_{rid}")
        if st.button("Record decision", key=f"docrev_db_{rid}"):
            _act(backend, tenant, store, review, lambda: pr.record_decision(review, actor, dec, dn), actor, "decision", rid)
    else:
        st.caption("Recording a decision needs the official or admin role.")
    st.markdown("**History**")
    st.dataframe([{"When": h["at"], "Who": h["actor"], "Action": h["action"], "Note": h["note"]} for h in review["history"]], hide_index=True)
    st.download_button("Download review packet (Markdown)", pr.packet_markdown(review, tenant, sample_data), file_name=f"{rid}_packet.md",
                       mime="text/markdown", key=f"docrev_dl_{rid}")


def _act(backend: Any, tenant: str, store: dict[str, Any], review: dict[str, Any], fn: Any, actor: str, action: str, ref: str) -> None:
    try:
        fn()
        save_reviews(backend, tenant, store)
        _log(backend, tenant, actor, action, review["id"], {"ref": ref})
        st.rerun()
    except pr.ReviewError as e:
        st.error(str(e))
