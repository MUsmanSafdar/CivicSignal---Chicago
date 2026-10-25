"""Streamlit page for CivicSignal. The logic lives in civicsignal.py; identity, storage and exports live in their own modules."""
import html
from typing import Any

import streamlit as st

import audit_store
import civicsignal as cs
import decision_packet
import funding_watch
import identity as ident


CSS = """
<style>
/* Light palette: pale sky-blue page, near-black text, one blue accent */
.stApp { background: linear-gradient(180deg, #dcebf8 0%, #eef5fb 38%, #f7fafd 100%) !important; color: #1d1d1f !important; }
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stHeader"] { visibility: hidden; height: 0; }
.block-container { padding-top: 1.6rem; max-width: 1480px; }
.stApp, .stApp p, .stApp li, .stApp label, .stApp span, .stApp div { color: #1d1d1f; }
.stApp h1, .stApp h2, .stApp h3, .stApp h4 { color: #1d1d1f !important; font-weight: 700; letter-spacing: -0.01em; }
.stApp a { color: #0066cc !important; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color: #515154 !important; }
[data-testid="stWidgetLabel"] p, [data-testid="stWidgetLabel"] label { color: #1d1d1f !important; font-weight: 600; }
/* Inputs: white fields, dark text */
[data-testid="stTextArea"] textarea, [data-testid="stTextInput"] input, [data-testid="stNumberInput"] input {
    background: #ffffff !important; color: #1d1d1f !important; -webkit-text-fill-color: #1d1d1f !important; caret-color: #1d1d1f; border-radius: 10px;
}
[data-testid="stTextArea"] textarea::placeholder, [data-testid="stTextInput"] input::placeholder { color: #6b6b70 !important; -webkit-text-fill-color: #6b6b70 !important; }
[data-testid="stTextArea"] > div, [data-testid="stTextInput"] > div > div, [data-testid="stNumberInput"] > div > div { background: #ffffff !important; border: 1px solid #d2d2d7 !important; border-radius: 10px !important; }
[data-testid="stSelectbox"] div[data-baseweb="select"] > div { background: #ffffff !important; border: 1px solid #d2d2d7 !important; border-radius: 10px; }
[data-testid="stSelectbox"] div[data-baseweb="select"] span, [data-testid="stSelectbox"] div[data-baseweb="select"] div { color: #1d1d1f !important; }
/* Buttons: blue pills */
.stApp .stButton > button { background: #0071e3 !important; color: #ffffff !important; border: 1px solid #0071e3 !important; border-radius: 980px; font-weight: 600; padding: 0.45rem 1.3rem; box-shadow: none; }
.stApp .stButton > button:hover { background: #0077ed !important; opacity: 1; }
.stApp .stButton > button:disabled { background: #e5e5ea !important; border-color: #e5e5ea !important; color: #6b6b70 !important; }
.stApp [class*="st-key-cs_held"] button { background: transparent !important; color: #0071e3 !important; }
.stApp [class*="st-key-cs_held"] button:hover { background: #e8f1fc !important; }
/* Cards, metrics, tabs, expanders */
.stApp [data-testid="stMetric"] { background: #ffffff; border: 1px solid #e5e5ea; border-radius: 16px; padding: 0.9rem 1.1rem; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
.stApp [data-testid="stMetricLabel"], .stApp [data-testid="stMetricLabel"] p { color: #515154 !important; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.05em; }
.stApp [data-testid="stMetricValue"] { color: #1d1d1f !important; font-weight: 700; }
.stApp [data-testid="stMetricDelta"] { color: #515154 !important; }
.stApp [data-testid="stTabs"] [role="tab"] { color: #515154 !important; font-weight: 600; border-bottom: 2px solid transparent; }
.stApp [data-testid="stTabs"] [role="tab"][aria-selected="true"] { color: #0071e3 !important; border-bottom-color: #0071e3; }
.stApp [data-testid="stExpander"], .stApp [data-testid="stVerticalBlockBorderWrapper"] { background: #ffffff; border: 1px solid #e5e5ea; border-radius: 16px; }
.stApp [data-testid="stProgressBar"] > div { background: #e5e5ea !important; }
.stApp [data-testid="stProgressBar"] > div > div { background: #0071e3 !important; }
.stApp hr { border-color: #d2d2d7 !important; }
.stApp pre, .stApp code { background: #f5f5f7 !important; color: #1d1d1f !important; }
/* Title and notice */
.cs-hero { text-align: center; padding: 0.4rem 1rem 0.2rem; }
.cs-hero h1 { font-size: 2.4rem; margin: 0; }
.cs-hero p { color: #515154 !important; font-size: 1.1rem; margin: 0.4rem auto 0; max-width: 720px; }
.cs-hero .acc { color: #0071e3; }
.cs-note { background: #fff8e6; border: 1px solid #f0d58a; color: #6b4e00 !important; border-radius: 12px; padding: 0.6rem 0.9rem; font-size: 0.85rem; margin: 0.8rem 0 1rem; }
.cs-note b { color: #6b4e00; }
/* Ranked table */
.cs-wrap { overflow-x: auto; background: #ffffff; border: 1px solid #e5e5ea; border-radius: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
.cs-table { width: 100%; border-collapse: collapse; font-size: 0.95rem; }
.cs-table th { text-align: left; color: #515154; font-weight: 600; font-size: 0.74rem; text-transform: uppercase; letter-spacing: 0.05em; padding: 0.7rem 0.8rem; border-bottom: 1px solid #e5e5ea; white-space: nowrap; }
.cs-table td { padding: 0.65rem 0.8rem; border-bottom: 1px solid #f0f0f3; color: #1d1d1f; vertical-align: middle; }
.cs-table tr:last-child td { border-bottom: none; }
.cs-table td.num { font-variant-numeric: tabular-nums; white-space: nowrap; }
.cs-pill { display: inline-block; border-radius: 980px; padding: 2px 10px; font-size: 0.76rem; font-weight: 600; white-space: nowrap; }
.cs-pill.pass { background: #e3f6e8; color: #15692e; }
.cs-pill.review { background: #fff1d6; color: #7a4f00; }
.cs-pill.fail { background: #fde6e6; color: #a1201f; }
.cs-pill.none { background: #efeff2; color: #515154; }
.cs-pill.yes { background: #e1effd; color: #0b5cad; }
.cs-pill.dec { background: #1d1d1f; color: #ffffff; }
</style>
"""

HERO = """
<div class="cs-hero"><h1>__LOGO__Civic<span class="acc">Signal</span></h1>
<p>Prioritize hazard-mitigation projects with a traceable reason for every recommendation. The official keeps the final decision.</p></div>
"""

SAMPLE_NOTE = ("<div class='cs-note'><b>Sample data only.</b> Every project, score, cost and sponsor is invented to show how the tool would work. "
               "Eligibility rules cite real FEMA regulations. Results are an administrative screening aid, not a legal determination or legal "
               "advice, and not for any funding decision. Decisions and the audit trail are saved for this workspace.</div>")
VERIFIED_NOTE = ("<div class='cs-note'><b>Verified data confirmed by an administrator.</b> Eligibility results are still an administrative "
                 "screening aid, not a legal determination or legal advice. The official keeps the final decision.</div>")

ELIG_TEXT = {"pass": "Eligible", "review": "Needs review", "fail": "Not eligible", None: "Not checked"}
NEED = {"publish_rules": "a reviewer or admin", "decide": "an official or admin", "edit_facts": "a reviewer, official or admin",
        "run_tamper_demo": "an admin", "refresh_funding": "a reviewer, official or admin"}


def _logo_html():
    import base64
    from pathlib import Path
    p = Path(__file__).parent / "assets" / "logo.png"
    if not p.exists():
        p = Path(__file__).parent / "logo.png"
    if not p.exists():
        return ""
    b = base64.b64encode(p.read_bytes()).decode()
    return f'<img src="data:image/png;base64,{b}" alt="" style="height:1.1em;vertical-align:-0.15em;margin-right:0.35em">'


class Ctx:
    """What the page needs from the app: who is signed in, where data is stored, and which tenant."""

    def __init__(self, identity: "ident.Identity | None", backend: Any, tenant: str, sample_data: bool = True) -> None:
        self.identity, self.backend, self.tenant, self.sample_data = identity, backend, tenant, sample_data

    def can(self, permission: str) -> bool:
        return ident.can(self.identity, permission)

    @property
    def actor_email(self) -> str:
        return self.identity.email if self.identity else ""


def _state(ctx: Ctx):
    key = f"cs::{ctx.tenant}"
    if key not in st.session_state:
        st.session_state[key] = audit_store.load_workspace(ctx.backend, ctx.tenant)
    return st.session_state[key]


def _persist(ctx: Ctx, S) -> None:
    """Write new audit entries and the workspace state; show a clear error instead of losing data silently."""
    try:
        audit_store.sync_state(ctx.backend, ctx.tenant, S)
    except Exception as exc:  # noqa: BLE001 - storage can fail in many ways; the user must know
        st.error(f"Could not save to the audit store: {exc}. Your change is in this session only.")


def _weights():
    return {k: st.session_state.get(f"cs_w_{k}", d) for k, _, d, _ in cs.CRITERIA}


def _denied(permission: str) -> None:
    st.caption(f"Needs {NEED.get(permission, 'a higher role')}. Your role: "
               f"{', '.join(sorted(st.session_state.get('cs_roles', ['not signed in'])))}.")


def render(identity=None, backend=None, tenant: str = "default", sample_data: bool = True):
    if backend is None:
        backend = audit_store.get_backend()
    ctx = Ctx(identity, backend, tenant, sample_data)
    S = _state(ctx)
    st.session_state["cs_roles"] = identity.roles if identity else frozenset({"not signed in"})
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(HERO.replace("__LOGO__", _logo_html()), unsafe_allow_html=True)
    st.markdown(SAMPLE_NOTE if sample_data else VERIFIED_NOTE, unsafe_allow_html=True)
    if identity:
        st.caption(f"Signed in as {identity.email} · roles: {', '.join(sorted(identity.roles))}. Every action is recorded under this identity.")
    else:
        st.caption("Not signed in. You can look around, but approving, holding and publishing rules need a signed-in reviewer or official.")

    t_prio, t_rules, t_audit, t_watch = st.tabs(["Prioritize", "Eligibility rules", "Audit trail", "Funding watch"])
    with t_prio:
        _prioritize(S, ctx)
    with t_rules:
        _rules(S, ctx)
    with t_audit:
        _audit(S, ctx)
    with t_watch:
        _watch(ctx)


def _pill(text, kind):
    return f'<span class="cs-pill {kind}">{html.escape(text)}</span>'


def _table_html(rk, within, S):
    kinds = {"pass": "pass", "review": "review", "fail": "fail", None: "none"}
    rows = []
    for i, r in enumerate(rk):
        p, e = r["p"], r["e"]
        key = e["overall"] if e else None
        d = S["decisions"].get(p["id"], {}).get("action")
        rows.append(
            "<tr>"
            f"<td class='num'>{i + 1}</td><td>{html.escape(p['name'])}<br><span style='color:#515154;font-size:0.78rem'>{html.escape(p['sponsor']['name'])}</span></td>"
            f"<td class='num'>{r['s']:.1f}</td><td>{html.escape(p['program'])}</td><td class='num'>${p['cost']:.1f}M</td>"
            f"<td>{_pill(ELIG_TEXT[key], kinds[key])}</td>"
            f"<td>{_pill('Within budget', 'yes') if p['id'] in within else ''}</td>"
            f"<td>{_pill({'approved': 'Approved', 'held': 'On hold'}[d], 'dec') if d else ''}</td></tr>"
        )
    head = "".join(f"<th scope='col'>{h}</th>" for h in ("#", "Project", "Score", "Program", "Cost", "Eligibility", "Budget", "Decision"))
    return (f"<div class='cs-wrap'><table class='cs-table'><caption style='text-align:left;padding:0.5rem 0.8rem;color:#515154'>"
            f"Projects ranked by weighted score</caption><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>")


def _prioritize(S, ctx: Ctx):
    left, right = st.columns([1, 2.6])
    with left:
      with st.container(border=True):
        st.subheader("What matters most")
        for k, label, d, _ in cs.CRITERIA:
            st.slider(label, 0, 50, d, key=f"cs_w_{k}")
        st.caption("Weights are yours to set. Change them and the ranking updates, so you can see how much a judgment call moves the list.")
        budget = st.number_input("Funds available ($ millions)", min_value=0.0, value=4.0, step=0.1, key="cs_budget")
    weights = _weights()
    if not cs.weights_valid(weights):
        with right:
            st.warning("Total weight is 0, so there is nothing to rank by. Raise at least one criterion above 0 "
                       "(total weight must be at least 1). The ranking table is hidden until you do.")
        return
    rk = cs.ranked(S["projects"], weights, S["published"])
    within, spend = cs.funded_line(rk, budget)

    with right:
        unpub = [r for r in cs.RULES if r["id"] not in S["published"]]
        if unpub:
            st.warning(f"{len(unpub)} of {len(cs.RULES)} eligibility rules are waiting for a reviewer to approve them. "
                       "Until then projects that depend on them show “Needs review.” Open the Eligibility rules tab.")
        counts = {"pass": 0, "review": 0, "fail": 0, None: 0}
        for r in rk:
            counts[r["e"]["overall"] if r["e"] else None] += 1
        ap = sum(1 for d in S["decisions"].values() if d["action"] == "approved")
        hd = sum(1 for d in S["decisions"].values() if d["action"] == "held")
        m = st.columns(5)
        m[0].metric("Fits budget", f"{len(within)} of {len(rk)}")
        m[1].metric("Spend", f"${spend:.1f}M", f"of ${budget:.1f}M", delta_color="off")
        m[2].metric("Eligible", counts["pass"])
        m[3].metric("Needs review", counts["review"])
        m[4].metric("Not eligible", counts["fail"])
        st.caption(f"Approved: {ap} · On hold: {hd}" + (f" · Not checked: {counts[None]}" if counts[None] else ""))
        st.markdown(_table_html(rk, within, S), unsafe_allow_html=True)
        _packet_buttons(S, ctx, weights, budget)

    st.divider()
    names = {r["p"]["id"]: f"{i + 1}. {r['p']['name']}" for i, r in enumerate(rk)}
    pid = st.selectbox("Pick a project to see why it ranks where it does", [r["p"]["id"] for r in rk], format_func=names.get, key="cs_sel")
    r = next(x for x in rk if x["p"]["id"] == pid)
    p, e = r["p"], r["e"]
    tw = sum(weights.values())
    c1, c2 = st.columns(2)
    with c1:
        st.subheader(p["name"])
        st.caption(f"{p['hazard']} · {p['program']} · ${p['cost']:.1f}M · Sponsor: {p['sponsor']['name']} · Score {r['s']:.1f}")
        for k, label, _, src in cs.CRITERIA:
            share = weights[k] / tw if tw else 0
            st.markdown(f"**{label}** ({round(share * 100)}% weight): {p[k]} → {p[k] * share:.1f} pts")
            st.progress(p[k] / 100)
            st.caption(f"Source: {src}")
    with c2:
        st.subheader("Eligibility")
        if not e:
            st.write(f"No eligibility rules exist for the {p['program']} program, so this project cannot be approved here.")
        else:
            st.write(f"Overall: **{ELIG_TEXT[e['overall']]}**")
            for o in e["outs"]:
                icon = {"pass": "✅", "review": "⚠️", "fail": "❌"}[o["out"]]
                st.markdown(f"{icon} **{o['rule']['title']}** — {ELIG_TEXT[o['out']]} ([{o['rule']['cite']}]({o['rule']['url']}))  \n{o['why']}")
            _facts_editor(S, ctx, p, pid)
        _decision_box(S, ctx, p, pid, e, weights, budget)
    msg = st.session_state.pop("cs_msg", None)
    if msg:
        st.toast(msg)


def _packet_buttons(S, ctx: Ctx, weights, budget) -> None:
    packet = decision_packet.build_packet(S, weights, budget, tenant=ctx.tenant, prepared_by=ctx.actor_email, sample_data=ctx.sample_data)
    stamp = packet["generated_at"][:10]
    c1, c2, _ = st.columns([1, 1, 2])
    c1.download_button("Decision packet (.md)", decision_packet.to_markdown(packet).encode("utf-8"),
                       file_name=f"civicsignal_decision_packet_{stamp}.md", mime="text/markdown", key="cs_dl_md")
    try:
        pdf = decision_packet.to_pdf(packet)
    except Exception as exc:  # noqa: BLE001
        c2.caption(f"PDF unavailable: {exc}")
    else:
        c2.download_button("Decision packet (.pdf)", pdf, file_name=f"civicsignal_decision_packet_{stamp}.pdf",
                           mime="application/pdf", key="cs_dl_pdf")


def _facts_editor(S, ctx: Ctx, p, pid) -> None:
    with st.expander("Correct the facts on file"):
        if not ctx.can("edit_facts"):
            _denied("edit_facts")
            return
        s = p["sponsor"]
        types, nfips, plans = list(cs.ENTITY_LABEL), list(cs.NFIP_LABEL), list(cs.PLAN_LABEL)
        ft = st.selectbox("Entity type", types, index=types.index(s["type"]), format_func=cs.ENTITY_LABEL.get, key=f"cs_ft_{pid}")
        fn = st.selectbox("NFIP status", nfips, index=nfips.index(s["nfip"]), format_func=cs.NFIP_LABEL.get, key=f"cs_fn_{pid}")
        fp = st.selectbox("Hazard mitigation plan", plans, index=plans.index(s["plan"]), format_func=cs.PLAN_LABEL.get, key=f"cs_fp_{pid}")
        fe = st.text_input("Plan expiry (YYYY-MM-DD, blank if none)", value=s["expires"], key=f"cs_fe_{pid}")
        extra: dict[str, Any] = {}
        if p["program"] == "HMGP":
            scopes = [None, "mitigation", "planning", "study"]
            fb = st.text_input("Benefit-cost ratio (blank if not on file)", value="" if p.get("bca_ratio") is None else str(p["bca_ratio"]), key=f"cs_fb_{pid}")
            fsc = st.selectbox("Project scope", scopes, index=scopes.index(p.get("scope")),
                               format_func=lambda v: v or "Not on file", key=f"cs_fsc_{pid}")
            extra = {"bca_ratio": fb.strip() or None, "scope": fsc}
        if st.button("Save facts", key=f"cs_sf_{pid}") and ctx.can("edit_facts"):
            ok1, msg1 = cs.save_facts(S, pid, {"type": ft, "nfip": fn, "plan": fp, "expires": fe.strip()}, ctx.actor_email)
            ok2, msg2 = (cs.save_project_facts(S, pid, extra, ctx.actor_email) if extra else (False, ""))
            _persist(ctx, S)
            st.session_state["cs_msg"] = msg2 if (ok2 or not ok1) and msg2 else msg1
            st.rerun()


def _decision_box(S, ctx: Ctx, p, pid, e, weights, budget) -> None:
    st.subheader("Your decision")
    d = S["decisions"].get(pid)
    if d:
        st.write(f"Recorded: **{'Approved' if d['action'] == 'approved' else 'On hold'}**. Reason: {d['note']}")
    allowed = ctx.can("decide")
    if not allowed:
        _denied("decide")
    note = st.text_area("Reason (required)", key=f"cs_note_{pid}", disabled=not allowed)
    can_approve = e is not None and e["overall"] == "pass"
    b1, b2 = st.columns(2)
    for col, action, label in ((b1, "approved", "Approve"), (b2, "held", "Hold")):
        if col.button(label, key=f"cs_{action}_{pid}", disabled=(not allowed) or (action == "approved" and not can_approve)) and allowed:
            ok, msg = cs.decide(S, pid, action, note, ctx.actor_email, weights, budget)
            if ok:
                _persist(ctx, S)
            st.session_state["cs_msg"] = msg
            st.rerun()
    if allowed and not can_approve:
        st.caption("Approve is switched off until eligibility is clear. Hold is always available.")


def _rules(S, ctx: Ctx):
    st.subheader("Eligibility rules")
    st.write("A rule counts only after a named reviewer approves its wording against the regulation. Until then results are “Needs review”. "
             "A failed check stops the project. A missing fact is a hold, not a denial. These rules are a screening aid, not legal advice.")
    can_publish = ctx.can("publish_rules")
    if not can_publish:
        _denied("publish_rules")
    for program, heading in (("FMA", "Flood Mitigation Assistance (44 CFR Part 77)"), ("HMGP", "Hazard Mitigation Grant Program (44 CFR 206.434)")):
        st.markdown(f"#### {heading}")
        for r in cs.rules_for(program):
            pub = S["published"].get(r["id"])
            with st.container(border=True):
                st.markdown(f"**{r['title']}** · [{r['cite']}]({r['url']})")
                st.write(r["text"])
                if pub:
                    st.success(f"Approved for use by {pub['by']} on {pub['at']}")
                elif st.button("Approve this rule for use", key=f"cs_pub_{r['id']}", disabled=not can_publish) and can_publish:
                    cs.publish_rules(S, [r["id"]], ctx.actor_email)
                    _persist(ctx, S)
                    st.rerun()
    if len(S["published"]) < len(cs.RULES) and st.button("Approve all rules", disabled=not can_publish) and can_publish:
        cs.publish_rules(S, [r["id"] for r in cs.RULES], ctx.actor_email)
        _persist(ctx, S)
        st.rerun()


def _audit(S, ctx: Ctx):
    st.subheader("Audit trail")
    st.write("Every approval, eligibility result, fact change and decision is added to one chain and saved. Each entry’s fingerprint (SHA-256) "
             "includes the fingerprint of the entry before it, so changing any earlier entry breaks every later one.")
    c1, c2, c3 = st.columns(3)
    if c1.button("Verify this session"):
        ok, msg = cs.verify_chain(S["audit"])
        (st.success if ok else st.error)(msg)
    if c3.button("Verify saved record"):
        ok, msg = audit_store.verify_chain(ctx.backend, ctx.tenant)
        (st.success if ok else st.error)("Saved record: " + msg)
    demo_ok = ctx.can("run_tamper_demo")
    if S["tampered"] is None:
        if c2.button("Alter the oldest entry (demo)", disabled=(not S["audit"]) or not demo_ok) and demo_ok:
            cs.tamper(S)
            st.warning("The oldest entry was altered in this session only. Nothing is written to the saved record. Run Verify this session to see it caught.")
    elif c2.button("Undo the alteration"):
        cs.restore(S)
        st.rerun()
    if not demo_ok:
        _denied("run_tamper_demo")
    if not S["audit"]:
        st.caption("No entries yet. Approve a rule or record a decision and it appears here.")
    for e in reversed(S["audit"]):
        with st.expander(f"#{e['n']} · {e['action']} · {e['resourceId']} · {e['actor']} · {e['at']}"):
            st.json(e["detail"])
            st.code(f"prev: {e['prev']}\nhash: {e['hash']}", language="text")


def _watch(ctx: Ctx):
    st.subheader("Funding watch")
    st.write("Notices from Grants.gov that match “flood mitigation” and “hazard mitigation”. Keyword matching is noisy, and status and "
             "deadlines can change, so open the notice on Grants.gov before relying on any of them.")
    stale, msg = funding_watch.staleness(ctx.backend, ctx.tenant)
    (st.warning if stale else st.caption)(msg)
    allowed = ctx.can("refresh_funding")
    if st.button("Refresh from Grants.gov", disabled=not allowed) and allowed:
        with st.spinner("Checking Grants.gov…"):
            res = funding_watch.refresh(ctx.backend, ctx.tenant)
        if res["errors"] and not res["seen"]:
            st.error("Grants.gov could not be reached (" + "; ".join(res["errors"]) + "). The saved list is unchanged.")
        else:
            st.success(f"Found {res['seen']} notices, {res['new']} new.")
        st.rerun() if res["seen"] else None
    if not allowed:
        _denied("refresh_funding")
    cached = funding_watch.list_cached(ctx.backend, ctx.tenant)
    if cached:
        for o in cached[:60]:
            close = f" · closes {o['close_date']}" if o.get("close_date") else ""
            st.markdown(f"**{o['title']}**  \n{o.get('agency', '')} · first seen {o['first_seen'][:10]}{close} · "
                        f"[Open on Grants.gov]({funding_watch.DETAIL_URL.format(id=o['id'])})")
    else:
        st.info("Nothing saved yet. Use Refresh to pull current notices.")
    with st.expander("Offline snapshot (captured Aug to Sep 2026, not live)"):
        st.caption("A fixed list kept as a fallback when Grants.gov cannot be reached. It does not update.")
        for o in funding_watch.offline_snapshot():
            if o["relevant"]:
                st.markdown(f"**{o['title']}**  \n{o['agency']} · first seen {o['first_seen']} · "
                            f"[Open on Grants.gov]({funding_watch.DETAIL_URL.format(id=o['id'])})")
