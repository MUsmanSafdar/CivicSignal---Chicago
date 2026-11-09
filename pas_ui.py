"""PAS Review Center (Streamlit UI). Thin layer over pas_engine / pas_store; all numbers come from case records.

Internal administrative aid for state and county reviewers. Not a FEMA system, not an approval, and not a substitute for FEMA's
determinations. Runs in "local demo mode" unless the host app supplies an authenticated identity (Easy Auth); every write is also
checked server-side against identity.PERMISSIONS.
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any

import streamlit as st

import audit_store
import civicsignal as cs
import civicsignal_ui as cui
import identity as ident
import pas_demo
import pas_engine as pe
import pas_packet
import pas_rules
import pas_store

VIEWS = ["State Overview", "Document Review", "Project Review Workspace", "Jurisdiction Overview", "Geographic Review Map", "Reports and Audit Packets", "Setup"]
BANNER = ("**Internal administrative aid.** This module tracks state and county review steps. It is not a FEMA approval, award or eligibility "
          "determination, and it does not replace FEMA's review. Items FEMA decides are labelled *federal*.")


def _actor(identity: Any) -> str:
    return identity.actor if identity else "anonymous"


def _can(identity: Any, perm: str) -> bool:
    return ident.can(identity, perm)


def _load(backend: Any, tenant: str) -> dict[str, Any]:
    key = f"pas::{tenant}"
    if key not in st.session_state:
        st.session_state[key] = pas_store.load(backend, tenant)
    return st.session_state[key]


def _save(backend: Any, tenant: str, pas: dict[str, Any]) -> None:
    try:
        pas_store.save(backend, tenant, pas)
    except Exception as exc:  # noqa: BLE001 - storage can fail in many ways; the user must know
        st.error(f"Could not save: {exc}. The change is in this session only.")


def _do(backend: Any, tenant: str, pas: dict[str, Any], fn: Any, *a: Any, **k: Any) -> bool:
    """Run an engine call; show validation errors; save on success."""
    try:
        fn(pas, *a, **k)
    except pe.PasError as exc:
        pas["_outbox"] = []
        st.error(str(exc))
        return False
    _save(backend, tenant, pas)
    return True


def _filters(pas: dict[str, Any], key: str) -> list[dict[str, Any]]:
    cases = list(pas["cases"].values())
    opts = lambda f: [""] + sorted({c[f] for c in cases if c[f]})  # noqa: E731
    c1, c2, c3 = st.columns(3)
    jur = c1.selectbox("Jurisdiction", opts("jurisdiction"), key=f"{key}_j")
    haz = c2.selectbox("Hazard", opts("hazard"), key=f"{key}_h")
    prog = c3.selectbox("Funding program", opts("program"), key=f"{key}_p")
    c4, c5, c6 = st.columns(3)
    status = c4.selectbox("Review status", [""] + pe.DASHBOARD_STATUSES, key=f"{key}_s")
    rev = c5.selectbox("Reviewer", [""] + sorted({c["assigned_to"] for c in cases if c["assigned_to"]}), key=f"{key}_r")
    text = c6.text_input("Search id, project, subapplicant", key=f"{key}_t")
    d1, d2 = st.columns(2)
    frm = d1.text_input("Submitted from (YYYY-MM-DD)", key=f"{key}_f")
    to = d2.text_input("Submitted to (YYYY-MM-DD)", key=f"{key}_to")
    return pe.filter_cases(pas, jurisdiction=jur, hazard=haz, program=prog, status=status, reviewer=rev, submitted_from=frm, submitted_to=to, text=text)


def _rows(cases: list[dict[str, Any]], now: str) -> list[dict[str, Any]]:
    return [{"Case": c["id"], "Project": c["project_id"], "Jurisdiction": c["jurisdiction"], "Program": c["program"], "Stage": pe.STAGE_LABEL[c["stage"]],
             "Status": pe.derived_status(c), "Reviewer": c["assigned_to"] or "(unassigned)", "Submitted": c["submitted_at"][:10],
             "Days open": pe.days_between(c["submitted_at"], now) if c["stage"] != "closed" else None, "Demo": "yes" if c["demo"] else ""} for c in cases]


def _table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        st.info("No cases match. Add cases in Setup (import a CSV, or load the labelled demo records).")
        return
    st.dataframe(rows, hide_index=True, use_container_width=True)


# ------------------------------------------------------------------ views
def _overview(ctx: Any, pas: dict[str, Any], now: str) -> None:
    cases = _filters(pas, "ov")
    m = pe.metrics(cases, pas, now)
    cols = st.columns(3)
    for i, s in enumerate(pe.DASHBOARD_STATUSES):
        cols[i % 3].metric(s, m["by_status"][s])
    a, b, c = st.columns(3)
    a.metric("Cases in view", m["total"])
    b.metric("Average review days", m["avg_review_days"] if m["avg_review_days"] is not None else "n/a", help=f"Over {m['completed_n']} completed reviews")
    c.metric("Median review days", m["median_review_days"] if m["median_review_days"] is not None else "n/a")
    st.subheader("Overdue items")
    st.dataframe(m["overdue"], hide_index=True) if m["overdue"] else st.caption("No overdue milestones, requests or deadlines in this view.")
    st.subheader("Reviewer workload (open cases)")
    st.dataframe([{"Reviewer": k, "Open cases": v} for k, v in sorted(m["workload"].items())], hide_index=True) if m["workload"] else st.caption("No open cases.")
    st.subheader("Where time is spent")
    st.dataframe([{"Stage": pe.STAGE_LABEL[s], "Holder": pe.STAGE_HOLDER[s], **v} for s, v in m["stage_stats"].items()], hide_index=True) if m["stage_stats"] else st.caption("No stage history yet.")
    h = m["days_by_holder"]
    st.caption(f"Recorded case-days by holder: applicant {h['applicant']}, state {h['state']}, federal {h['federal']}. "
               f"Returned for correction: {m['returned_count']}. With unresolved required items: {m['incomplete_count']}. "
               f"Due within 14 days: {m['due_within_14_days']}.")
    for n in pe.capacity_notes(m):
        st.markdown(f"- {n}")
    st.subheader("Cases")
    _table(_rows(cases, now))


def _checklist_ui(ctx: Any, pas: dict[str, Any], c: dict[str, Any], now: str) -> None:
    ready = pe.evaluate_readiness(c)
    st.markdown(f"**Checklist result: {ready['overall'].replace('_', ' ')}.** {len(ready['required_unresolved'])} required item(s) unresolved, "
                f"{len(ready['under_review'])} under review, {len(ready['requires_federal'])} awaiting a federal determination, "
                f"{len(ready['optional_open'])} optional open. This is an internal administrative result, not FEMA approval.")
    can = _can(ctx.identity, "pas_review")
    sd = pas["config"].get("stale_after_days", pe.DEFAULT_STALE_DAYS)
    for r in pas_rules.requirements_for(c["program"]):
        it = c["checklist"][r["id"]]
        fr = pe.item_freshness(c, r["id"], now, sd)
        tag = "required" if r["required"] else "optional"
        src = r["source_title"] + ("" if r["confirmed"] else " (needs confirmation)")
        age = f" | verified {fr['days']} d ago" + (", RE-CONFIRM" if fr["state"] == "stale" else "") if fr["state"] in ("fresh", "stale") else ""
        with st.expander(f"{r['label']} | {it['status']}{age} | {tag} | decided by {'FEMA' if r['authority'] == 'federal' else 'state/county'}"):
            if fr["state"] == "stale":
                st.warning(f"Last verified {fr['verified_at'][:10]} ({fr['days']} days ago; warning after {sd}). This fact can change. "
                           "Re-confirm it before a decision. This is a warning only; it does not block anything.")
                if can and st.button("Re-confirm now", key=f"{c['id']}_{r['id']}_rc") and can:
                    if _do(ctx.backend, ctx.tenant, pas, pe.set_item, c["id"], _actor(ctx.identity), r["id"], "Verified", now, reconfirm=True):
                        st.rerun()
            elif fr["state"] == "fresh":
                st.caption(f"Last verified {fr['verified_at'][:10]} by {it.get('verified_by', it['updated_by'])}.")
            st.caption(f"Source ({r['source_type'].replace('_', ' ')}): {src}. Evidence: {r['evidence_hint']}.")
            st.write("Evidence on file: " + ("; ".join(it["evidence"]) or "none"))
            if it["note"]:
                st.write("Note: " + it["note"])
            if can:
                k = f"{c['id']}_{r['id']}"
                stat = st.selectbox("Status", pe.ITEM_STATUSES, index=pe.ITEM_STATUSES.index(it["status"]), key=f"{k}_st")
                ev = st.text_input("Evidence references (separate with ;)", value="; ".join(it["evidence"]), key=f"{k}_ev")
                note = st.text_input("Note / reason", value=it["note"], key=f"{k}_nt")
                if st.button("Save item", key=f"{k}_sv") and can:
                    if _do(ctx.backend, ctx.tenant, pas, pe.set_item, c["id"], _actor(ctx.identity), r["id"], stat, now,
                           evidence=[e for e in ev.split(";")], note=note):
                        st.rerun()


def _workspace(ctx: Any, pas: dict[str, Any], now: str) -> None:
    cases = _filters(pas, "ws")
    if not cases:
        _table([])
        return
    cid = st.selectbox("Case", [c["id"] for c in cases], key="ws_case")
    c = pas["cases"][cid]
    if c["demo"]:
        st.warning(pas_packet.DEMO_NOTICE)
    st.markdown(f"### {c['id']} | project {c['project_id']} | {c['jurisdiction']} | {c['program']}")
    st.write(f"Stage: **{pe.STAGE_LABEL[c['stage']]}**. Status: **{pe.derived_status(c)}**. Reviewer: {c['assigned_to'] or '(unassigned)'}. "
             f"Submitted {c['submitted_at'][:10]}. Deadline {c['due_at'][:10] or 'not set'}.")
    stale = pe.stale_items(c, now, pas["config"].get("stale_after_days", pe.DEFAULT_STALE_DAYS))
    if stale and c["stage"] != "closed":
        st.warning("Time-sensitive items to re-confirm before a decision: " + "; ".join(f"{s['label']} ({s['days']} days old)" for s in stale))
    t1, t2, t3, t4 = st.tabs(["Readiness checklist", "Workflow", "Requests and comments", "History"])
    with t1:
        _checklist_ui(ctx, pas, c, now)
    with t2:
        nxt = sorted(pe.TRANSITIONS[c["stage"]])
        if _can(ctx.identity, "pas_review") and nxt:
            to = st.selectbox("Move to", nxt, format_func=lambda s: pe.STAGE_LABEL[s], key=f"{cid}_to")
            note = st.text_input("Note", key=f"{cid}_tn")
            if st.button("Change stage", key=f"{cid}_tb") and _can(ctx.identity, "pas_review"):
                if _do(ctx.backend, ctx.tenant, pas, pe.transition, cid, _actor(ctx.identity), to, now, note):
                    st.rerun()
        if _can(ctx.identity, "pas_intake"):
            rv = st.text_input("Assign reviewer (email or name)", value=c["assigned_to"], key=f"{cid}_rv")
            if st.button("Assign", key=f"{cid}_as") and _can(ctx.identity, "pas_intake"):
                if _do(ctx.backend, ctx.tenant, pas, pe.assign, cid, _actor(ctx.identity), rv, now):
                    st.rerun()
        if c["stage"] in ("technical_review", "state_decision") and _can(ctx.identity, "pas_decide"):
            why = st.text_input("Federal referral reason", key=f"{cid}_fr")
            if st.button("Refer to FEMA", key=f"{cid}_frb") and _can(ctx.identity, "pas_decide"):
                if _do(ctx.backend, ctx.tenant, pas, pe.refer_to_federal, cid, _actor(ctx.identity), now, why):
                    st.rerun()
        if c["stage"] == "state_decision" and _can(ctx.identity, "pas_decide"):
            oc = st.selectbox("Decision", list(pe.DECISIONS), format_func=lambda k: pe.DECISIONS[k], key=f"{cid}_do")
            ra = st.text_input("Rationale", key=f"{cid}_dr")
            if st.button("Record decision", key=f"{cid}_db") and _can(ctx.identity, "pas_decide"):
                if _do(ctx.backend, ctx.tenant, pas, pe.record_decision, cid, _actor(ctx.identity), oc, ra, now):
                    st.rerun()
        fr = c["federal_referral"]
        if fr and not fr["returned_at"] and _can(ctx.identity, "pas_decide"):
            out = st.text_input("FEMA outcome as communicated", key=f"{cid}_fo")
            if st.button("Record FEMA outcome", key=f"{cid}_fob") and _can(ctx.identity, "pas_decide"):
                if _do(ctx.backend, ctx.tenant, pas, pe.record_federal_outcome, cid, _actor(ctx.identity), out, now):
                    st.rerun()
        if c["decision"]:
            st.info(f"{c['decision']['label']} by {c['decision']['by']} on {c['decision']['at'][:10]}: {c['decision']['rationale']}")
    with t3:
        for r in c["requests"]:
            st.write(f"**{r['id']}** {r['kind']} to {r['responsible']}: {r['text']} (due {r['due_at'][:10] or 'n/a'}) "
                     + ("resolved" if r["resolved_at"] else "responded" if r["responded_at"] else "open"))
            if r["responded_at"] and not r["resolved_at"] and _can(ctx.identity, "pas_review"):
                if st.button("Resolve " + r["id"], key=f"{r['id']}_rs") and _can(ctx.identity, "pas_review"):
                    if _do(ctx.backend, ctx.tenant, pas, pe.resolve_request, cid, _actor(ctx.identity), r["id"], now):
                        st.rerun()
            elif not r["responded_at"] and _can(ctx.identity, "pas_review"):
                resp = st.text_input("Record applicant response", key=f"{r['id']}_rt")
                if st.button("Save response " + r["id"], key=f"{r['id']}_rb") and _can(ctx.identity, "pas_review"):
                    if _do(ctx.backend, ctx.tenant, pas, pe.respond_request, cid, _actor(ctx.identity), r["id"], resp, now):
                        st.rerun()
        if _can(ctx.identity, "pas_review"):
            kind = st.selectbox("New request type", pe.REQUEST_KINDS, key=f"{cid}_rk")
            txt = st.text_input("What is needed", key=f"{cid}_rtx")
            due = st.text_input("Due (YYYY-MM-DD)", key=f"{cid}_rdu")
            req = st.selectbox("Related requirement", [""] + list(c["checklist"]), key=f"{cid}_rq")
            if st.button("Open request", key=f"{cid}_ro") and _can(ctx.identity, "pas_review"):
                if _do(ctx.backend, ctx.tenant, pas, pe.open_request, cid, _actor(ctx.identity), now, kind=kind, text=txt, due_at=due, req_id=req):
                    st.rerun()
            cm = st.text_input("Add comment", key=f"{cid}_cm")
            if st.button("Post comment", key=f"{cid}_cb") and _can(ctx.identity, "pas_review"):
                if _do(ctx.backend, ctx.tenant, pas, pe.add_comment, cid, _actor(ctx.identity), cm, now):
                    st.rerun()
        for cmt in c["comments"]:
            st.caption(f"{cmt['at'][:16]} {cmt['actor']}: {cmt['text']}")
    with t4:
        st.dataframe([{"When": h["at"], "Who": h["actor"], "From": h["from"], "To": h["to"], "Note": h["note"]} for h in c["history"]], hide_index=True)
        st.dataframe(pe.stage_durations(c, now), hide_index=True)
        ev = pas_store.case_events(ctx.backend, ctx.tenant, cid)
        st.caption(f"{len(ev)} audit event(s) for this case in the shared hash-chained trail.")


def _jurisdictions(ctx: Any, pas: dict[str, Any], now: str) -> None:
    rows = []
    for j in sorted({c["jurisdiction"] for c in pas["cases"].values()}):
        cs_ = [c for c in pas["cases"].values() if c["jurisdiction"] == j]
        m = pe.metrics(cs_, pas, now)
        rows.append({"Jurisdiction": j, "Cases": m["total"], **{k: v for k, v in m["by_status"].items() if v}, "Overdue items": len(m["overdue"]),
                     "Avg review days": m["avg_review_days"], "Returned for correction": m["returned_count"]})
    st.dataframe(rows, hide_index=True) if rows else _table([])


def _points(x: Any, acc: list[Any]) -> list[Any]:
    if isinstance(x, list) and x and isinstance(x[0], (int, float)):
        acc.append(x)
    elif isinstance(x, list):
        for y in x:
            _points(y, acc)
    return acc


def _centroids() -> dict[str, tuple[float, float]]:
    import os
    path = os.path.join(os.path.dirname(__file__), "data", "illinois_counties.geojson")
    out: dict[str, tuple[float, float]] = {}
    try:
        gj = json.load(open(path, encoding="utf-8"))  # noqa: SIM115
    except OSError:
        return out
    for f in gj["features"]:
        pts = _points(f["geometry"]["coordinates"], [])
        if pts:
            out[f["properties"]["name"]] = (sum(p[1] for p in pts) / len(pts), sum(p[0] for p in pts) / len(pts))
    return out


def _map(ctx: Any, pas: dict[str, Any], now: str) -> None:
    cen = _centroids()
    rows = []
    for j in sorted({c["jurisdiction"] for c in pas["cases"].values()}):
        cs_ = [c for c in pas["cases"].values() if c["jurisdiction"] == j]
        m = pe.metrics(cs_, pas, now)
        projects = {p["id"]: p for p in cs.PROJECTS}
        w = {k: wt for k, _, wt, _ in cs.CRITERIA}
        sc = [cs.score_of(projects[c["project_id"]], w) for c in cs_ if c["project_id"] in projects]
        rows.append({"Jurisdiction": j, "lat": cen.get(j, (None, None))[0], "lon": cen.get(j, (None, None))[1], "Open cases": m["total"] - m["by_status"]["Completed administrative review"],
                     "Overdue": len(m["overdue"]), "Avg days open": m["avg_wait_for_initial_review_days"], "Mean score (default weights)": round(sum(sc) / len(sc), 1) if sc else None})
    st.caption("County-level view. Points are county centers, sized by open cases and colored by overdue items. Prioritization scores use the existing CivicSignal "
               "scoring unchanged. Project-level coordinates are not stored, so exact sites are not mapped.")
    st.dataframe(rows, hide_index=True) if rows else _table([])
    try:
        import plotly.graph_objects as go
        pts = [r for r in rows if r["lat"] is not None]
        if pts:
            fig = go.Figure(go.Scattergeo(lat=[r["lat"] for r in pts], lon=[r["lon"] for r in pts], text=[f"{r['Jurisdiction']}: {r['Open cases']} open, {r['Overdue']} overdue" for r in pts],
                                          marker={"size": [10 + 8 * r["Open cases"] for r in pts], "color": [r["Overdue"] for r in pts], "colorscale": "Reds", "showscale": True,
                                                  "colorbar": {"title": "Overdue"}}, hoverinfo="text"))
            fig.update_geos(fitbounds="locations", scope="usa")
            fig.update_layout(margin={"l": 0, "r": 0, "t": 0, "b": 0}, height=420)
            st.plotly_chart(fig, use_container_width=True)
    except ImportError:
        st.caption("Install plotly to see the map; the table above has the same data.")


def _reports(ctx: Any, pas: dict[str, Any], now: str) -> None:
    ok, msg = audit_store.verify_chain(ctx.backend, ctx.tenant)
    st.write(("Audit chain verified. " if ok else "AUDIT CHAIN PROBLEM. ") + msg)
    if not pas["cases"]:
        _table([])
        return
    cid = st.selectbox("Case", sorted(pas["cases"]), key="rp_case")
    ev = pas_store.case_events(ctx.backend, ctx.tenant, cid)
    pk = pas_packet.build_packet(pas, cid, ev, tenant=ctx.tenant, prepared_by=_actor(ctx.identity), now=now, chain=(ok, msg))
    st.download_button("Download packet (PDF)", pas_packet.to_pdf(pk), file_name=f"{cid}_packet.pdf", mime="application/pdf")
    st.download_button("Download packet (Markdown)", pas_packet.to_markdown(pk), file_name=f"{cid}_packet.md", mime="text/markdown")
    st.dataframe(ev, hide_index=True) if ev else st.caption("No audit events recorded for this case.")


def _setup(ctx: Any, pas: dict[str, Any], now: str) -> None:
    st.subheader("Delegation scope (PAS)")
    st.caption("Record which functions your state has accepted in its operational agreement with the FEMA Regional Office. FEMA keeps environmental and historic "
               "preservation review in all cases. Until application review is recorded here, the tool will not record a state recommendation to approve.")
    d = dict(pas["config"]["delegation"])
    edit = _can(ctx.identity, "pas_config")
    new = {k: st.checkbox(v, value=d.get(k, False), key=f"dg_{k}", disabled=not edit) for k, v in pas_rules.PAS_FUNCTIONS.items()}
    dis = st.text_input("Disaster declaration / funding opportunity", value=pas["config"]["disaster"], key="dg_dis", disabled=not edit)
    ag = st.text_input("Operational agreement reference", value=pas["config"]["agreement_ref"], key="dg_ag", disabled=not edit)
    gv = st.text_input("HMA guidance version in force", value=pas["config"]["guidance_version"], key="dg_gv", disabled=not edit)
    if st.button("Save delegation", disabled=not edit) and edit:
        if _do(ctx.backend, ctx.tenant, pas, pe.set_delegation, _actor(ctx.identity), new, disaster=dis, agreement_ref=ag, guidance_version=gv):
            st.success("Saved.")
    st.subheader("Re-confirmation warning")
    st.caption("Time-sensitive items (for example NFIP standing, plan currency) show a warning when their last verification is older than this. "
               f"The starting value ({pe.DEFAULT_STALE_DAYS} days) is a placeholder: set it from the guidance in force. It warns only and never blocks a decision.")
    sd = st.number_input("Warn after (days)", min_value=1, max_value=3650, value=int(pas["config"].get("stale_after_days", pe.DEFAULT_STALE_DAYS)), step=1,
                         key="stale_days", disabled=not edit)
    if st.button("Save warning period", disabled=not edit, key="stale_b") and edit:
        if _do(ctx.backend, ctx.tenant, pas, pe.set_stale_days, _actor(ctx.identity), int(sd)):
            st.success("Saved.")
    st.subheader("Import cases (CSV)")
    st.caption("Required columns: project_id, jurisdiction, program, submitted_at. Optional: hazard, subapplicant, due_at. project_id must match an existing CivicSignal project.")
    up = st.file_uploader("CSV file", type=["csv"], key="imp") if _can(ctx.identity, "pas_intake") else None
    if up is not None and st.button("Import", key="imp_b") and _can(ctx.identity, "pas_intake"):
        rows = list(csv.DictReader(io.StringIO(up.getvalue().decode("utf-8-sig"))))
        res = pe.import_cases(pas, _actor(ctx.identity), rows, {p["id"] for p in cs.PROJECTS})
        _save(ctx.backend, ctx.tenant, pas)
        st.write(f"Created {len(res['created'])} case(s).")
        if res["errors"]:
            st.dataframe(res["errors"], hide_index=True)
    st.subheader("Demo records")
    st.caption("Loads six invented cases on the CivicSignal sample projects, each flagged DEMO. For training and walkthroughs only.")
    if st.button("Load demo records", disabled=not edit, key="demo_b") and edit:
        if not any(c["demo"] for c in pas["cases"].values()):
            pas_demo.load_demo(pas, _actor(ctx.identity), {p["id"]: p for p in cs.PROJECTS}, now)
            _save(ctx.backend, ctx.tenant, pas)
            st.rerun()
        else:
            st.info("Demo records are already loaded.")
    st.subheader("Requirement catalogue")
    st.dataframe([{"Requirement": r["label"], "Required": r["required"], "Decided by": r["authority"], "Source": r["source_title"], "Source type": r["source_type"],
                   "Confirmed against text": r["confirmed"]} for r in pas_rules.requirements_for("HMGP") + [x for x in pas_rules.requirements_for("FMA") if x["programs"] == ["FMA"]]],
                 hide_index=True)
    st.caption(f"Catalogue version {pas_rules.CATALOGUE_VERSION}. Rows not confirmed need checking against the guide for your funding opportunity.")


def _doc_review(ctx: Any, pas: dict[str, Any], now: str) -> None:
    import pas_review_ui
    pas_review_ui.render(ctx.identity, ctx.backend, ctx.tenant, sample_data=ctx.sample_data)


def render(identity: Any, backend: Any, tenant: str, *, sample_data: bool = True) -> None:
    st.markdown(cui.CSS, unsafe_allow_html=True)
    st.title("PAS Review Center")
    st.markdown(BANNER)
    if identity is None:
        st.caption("Local demo mode: no authenticated user. Read-only. Sign in through the host app's identity provider to record review actions.")
    elif identity.source != "easy_auth":
        st.caption("Local demo mode: identity comes from local development settings, not a verified agency sign-in.")
    pas = _load(backend, tenant)
    now = pe.now_iso()
    if any(c["demo"] for c in pas["cases"].values()):
        st.warning("Demo records are present. Figures include invented cases.")
    view = st.radio("View", VIEWS, horizontal=True, key="pas_view")
    {"State Overview": _overview, "Document Review": _doc_review, "Project Review Workspace": _workspace, "Jurisdiction Overview": _jurisdictions,
     "Geographic Review Map": _map, "Reports and Audit Packets": _reports, "Setup": _setup}[view](
        type("Ctx", (), {"identity": identity, "backend": backend, "tenant": tenant, "sample_data": sample_data})(), pas, now)
