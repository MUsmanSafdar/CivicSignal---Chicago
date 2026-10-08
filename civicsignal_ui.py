"""Streamlit page for CivicSignal. The logic lives in civicsignal.py."""
import html

import streamlit as st

import civicsignal as cs


CSS = """
<style>
/* Light palette: pale sky-blue page, near-black text, one blue accent */
.stApp { background: linear-gradient(180deg, #dcebf8 0%, #eef5fb 38%, #f7fafd 100%) !important; color: #1d1d1f !important; }
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stHeader"] { visibility: hidden; height: 0; }
.block-container { padding-top: 1.6rem; max-width: 1480px; }
.stApp, .stApp p, .stApp li, .stApp label, .stApp span, .stApp div { color: #1d1d1f; }
.stApp h1, .stApp h2, .stApp h3, .stApp h4 { color: #1d1d1f !important; font-weight: 700; letter-spacing: -0.01em; }
.stApp a { color: #0066cc !important; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color: #6e6e73 !important; }
[data-testid="stWidgetLabel"] p, [data-testid="stWidgetLabel"] label { color: #1d1d1f !important; font-weight: 600; }
/* Inputs: white fields, dark text */
[data-testid="stTextArea"] textarea, [data-testid="stTextInput"] input, [data-testid="stNumberInput"] input {
    background: #ffffff !important; color: #1d1d1f !important; -webkit-text-fill-color: #1d1d1f !important; caret-color: #1d1d1f; border-radius: 10px;
}
[data-testid="stTextArea"] textarea::placeholder, [data-testid="stTextInput"] input::placeholder { color: #86868b !important; -webkit-text-fill-color: #86868b !important; }
[data-testid="stTextArea"] > div, [data-testid="stTextInput"] > div > div, [data-testid="stNumberInput"] > div > div { background: #ffffff !important; border: 1px solid #d2d2d7 !important; border-radius: 10px !important; }
[data-testid="stSelectbox"] div[data-baseweb="select"] > div { background: #ffffff !important; border: 1px solid #d2d2d7 !important; border-radius: 10px; }
[data-testid="stSelectbox"] div[data-baseweb="select"] span, [data-testid="stSelectbox"] div[data-baseweb="select"] div { color: #1d1d1f !important; }
/* Buttons: blue pills */
.stApp .stButton > button { background: #0071e3 !important; color: #ffffff !important; border: 1px solid #0071e3 !important; border-radius: 980px; font-weight: 600; padding: 0.45rem 1.3rem; box-shadow: none; }
.stApp .stButton > button:hover { background: #0077ed !important; opacity: 1; }
.stApp .stButton > button:disabled { background: #e5e5ea !important; border-color: #e5e5ea !important; color: #86868b !important; }
.stApp [class*="st-key-cs_held"] button { background: transparent !important; color: #0071e3 !important; }
.stApp [class*="st-key-cs_held"] button:hover { background: #e8f1fc !important; }
/* Cards, metrics, tabs, expanders */
.stApp [data-testid="stMetric"] { background: #ffffff; border: 1px solid #e5e5ea; border-radius: 16px; padding: 0.9rem 1.1rem; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
.stApp [data-testid="stMetricLabel"], .stApp [data-testid="stMetricLabel"] p { color: #6e6e73 !important; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.05em; }
.stApp [data-testid="stMetricValue"] { color: #1d1d1f !important; font-weight: 700; }
.stApp [data-testid="stMetricDelta"] { color: #6e6e73 !important; }
.stApp [data-testid="stTabs"] [role="tab"] { color: #6e6e73 !important; font-weight: 600; border-bottom: 2px solid transparent; }
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
.cs-table th { text-align: left; color: #6e6e73; font-weight: 600; font-size: 0.74rem; text-transform: uppercase; letter-spacing: 0.05em; padding: 0.7rem 0.8rem; border-bottom: 1px solid #e5e5ea; white-space: nowrap; }
.cs-table td { padding: 0.65rem 0.8rem; border-bottom: 1px solid #f0f0f3; color: #1d1d1f; vertical-align: middle; }
.cs-table tr:last-child td { border-bottom: none; }
.cs-table td.num { font-variant-numeric: tabular-nums; white-space: nowrap; }
.cs-pill { display: inline-block; border-radius: 980px; padding: 2px 10px; font-size: 0.76rem; font-weight: 600; white-space: nowrap; }
.cs-pill.pass { background: #e3f6e8; color: #15692e; }
.cs-pill.review { background: #fff1d6; color: #8a5a00; }
.cs-pill.fail { background: #fde6e6; color: #a1201f; }
.cs-pill.none { background: #efeff2; color: #6e6e73; }
.cs-pill.yes { background: #e1effd; color: #0b5cad; }
.cs-pill.dec { background: #1d1d1f; color: #ffffff; }
</style>
"""

HERO = """
<div class="cs-hero"><h1>__LOGO__Civic<span class="acc">Signal</span></h1>
<p>Prioritize hazard-mitigation projects with a traceable reason for every recommendation. The official keeps the final decision.</p></div>
<div class="cs-note"><b>Sample data only.</b> Every project, score, cost and sponsor is invented to show how the tool would work. Eligibility rules cite real FEMA regulations but this is a rough prototype, not legal advice, and not for any funding decision. Nothing is saved when the session ends.</div>
"""

ELIG_TEXT = {"pass": "Eligible", "review": "Needs review", "fail": "Not eligible", None: "Not checked (no HMGP rules yet)"}


def _logo_html():
    import base64
    from pathlib import Path
    p = Path(__file__).parent / "assets" / "logo.png"
    if not p.exists():
        return ""
    b = base64.b64encode(p.read_bytes()).decode()
    return f'<img src="data:image/png;base64,{b}" alt="" style="height:1.1em;vertical-align:-0.15em;margin-right:0.35em">'


def _state():
    if "cs" not in st.session_state:
        s = cs.new_state()
        cs.init_outcomes(s)
        st.session_state["cs"] = s
    return st.session_state["cs"]


def _weights():
    return {k: st.session_state.get(f"cs_w_{k}", d) for k, _, d, _ in cs.CRITERIA}


def render():
    S = _state()
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(HERO.replace("__LOGO__", _logo_html()), unsafe_allow_html=True)
    who = st.text_input("Your name (recorded with approvals and rule publishing)", key="cs_who").strip()

    t_prio, t_rules, t_audit, t_watch = st.tabs(["Prioritize", "Eligibility rules", "Audit trail", "Funding watch"])

    with t_prio:
        _prioritize(S, who)
    with t_rules:
        _rules(S, who)
    with t_audit:
        _audit(S)
    with t_watch:
        _watch()


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
            f"<td class='num'>{i + 1}</td><td>{html.escape(p['name'])}<br><span style='color:#6e6e73;font-size:0.78rem'>{html.escape(p['sponsor']['name'])}</span></td>"
            f"<td class='num'>{r['s']:.1f}</td><td>{html.escape(p['program'])}</td><td class='num'>${p['cost']:.1f}M</td>"
            f"<td>{_pill(ELIG_TEXT[key] if key else 'Not checked', kinds[key])}</td>"
            f"<td>{_pill('Within budget', 'yes') if p['id'] in within else ''}</td>"
            f"<td>{_pill({'approved': 'Approved', 'held': 'On hold'}[d], 'dec') if d else ''}</td></tr>"
        )
    head = "".join(f"<th>{h}</th>" for h in ("#", "Project", "Score", "Program", "Cost", "Eligibility", "Budget", "Decision"))
    return f"<div class='cs-wrap'><table class='cs-table'><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


def _prioritize(S, who):
    left, right = st.columns([1, 2.6])
    with left:
      with st.container(border=True):
        st.subheader("What matters most")
        for k, label, d, _ in cs.CRITERIA:
            st.slider(label, 0, 50, d, key=f"cs_w_{k}")
        st.caption("Weights are yours to set. Change them and the ranking updates, so you can see how much a judgment call moves the list.")
        budget = st.number_input("Funds available ($ millions)", min_value=0.0, value=4.0, step=0.1, key="cs_budget")
    weights = _weights()
    rk = cs.ranked(S["projects"], weights, S["published"])
    within, spend = cs.funded_line(rk, budget)

    with right:
        unpub = [r for r in cs.RULES if r["id"] not in S["published"]]
        if unpub:
            st.warning(f"{len(unpub)} of {len(cs.RULES)} eligibility rules are waiting for a reviewer to approve them. "
                       "Until then every FMA project shows “Needs review.” Open the Eligibility rules tab.")
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
        st.caption(f"Approved: {ap} \u00b7 On hold: {hd} \u00b7 Not checked (no HMGP rules yet): {counts[None]}")
        st.markdown(_table_html(rk, within, S), unsafe_allow_html=True)

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
            st.write("Not checked. Eligibility rules for HMGP projects have not been written yet.")
        else:
            st.write(f"Overall: **{ELIG_TEXT[e['overall']]}**")
            for o in e["outs"]:
                icon = {"pass": "✅", "review": "⚠️", "fail": "❌"}[o["out"]]
                st.markdown(f"{icon} **{o['rule']['title']}** ([{o['rule']['cite']}]({o['rule']['url']}))  \n{o['why']}")
            with st.expander("Correct the sponsor facts on file"):
                s = p["sponsor"]
                types, nfips, plans = list(cs.ENTITY_LABEL), list(cs.NFIP_LABEL), list(cs.PLAN_LABEL)
                ft = st.selectbox("Entity type", types, index=types.index(s["type"]), format_func=cs.ENTITY_LABEL.get, key=f"cs_ft_{pid}")
                fn = st.selectbox("NFIP status", nfips, index=nfips.index(s["nfip"]), format_func=cs.NFIP_LABEL.get, key=f"cs_fn_{pid}")
                fp = st.selectbox("Hazard mitigation plan", plans, index=plans.index(s["plan"]), format_func=cs.PLAN_LABEL.get, key=f"cs_fp_{pid}")
                fe = st.text_input("Plan expiry (YYYY-MM-DD, blank if none)", value=s["expires"], key=f"cs_fe_{pid}")
                if st.button("Save facts", key=f"cs_sf_{pid}"):
                    ok, msg = cs.save_facts(S, pid, {"type": ft, "nfip": fn, "plan": fp, "expires": fe.strip()}, who)
                    st.session_state["cs_msg"] = msg
                    st.rerun()
        st.subheader("Your decision")
        d = S["decisions"].get(pid)
        if d:
            st.write(f"Recorded: **{'Approved' if d['action'] == 'approved' else 'On hold'}**. Reason: {d['note']}")
        note = st.text_area("Reason (required)", key=f"cs_note_{pid}")
        can_approve = (e is None) or e["overall"] == "pass"
        b1, b2 = st.columns(2)
        for col, action, label in ((b1, "approved", "Approve"), (b2, "held", "Hold")):
            if col.button(label, key=f"cs_{action}_{pid}", disabled=(action == "approved" and not can_approve)):
                if not who:
                    st.session_state["cs_msg"] = "Enter your name at the top first."
                else:
                    ok, msg = cs.decide(S, pid, action, note, who, weights, budget)
                    st.session_state["cs_msg"] = msg
                st.rerun()
        if not can_approve:
            st.caption("Approve is switched off until eligibility is clear. Hold is always available.")
    msg = st.session_state.pop("cs_msg", None)
    if msg:
        st.toast(msg)


def _rules(S, who):
    st.subheader("Eligibility rules (FMA, 44 CFR Part 77)")
    st.write("A rule counts only after a named reviewer approves its wording against the regulation. Until then results are “Needs review”. "
             "A failed check stops the project. A missing fact is a hold, not a denial.")
    for r in cs.RULES:
        pub = S["published"].get(r["id"])
        with st.container(border=True):
            st.markdown(f"**{r['title']}** · [{r['cite']}]({r['url']})")
            st.write(r["text"])
            if pub:
                st.success(f"Approved for use by {pub['by']} on {pub['at']}")
            elif st.button("Approve this rule for use", key=f"cs_pub_{r['id']}"):
                if not who:
                    st.error("Enter your name at the top first.")
                else:
                    cs.publish_rules(S, [r["id"]], who)
                    st.rerun()
    if len(S["published"]) < len(cs.RULES) and st.button("Approve all rules"):
        if not who:
            st.error("Enter your name at the top first.")
        else:
            cs.publish_rules(S, [r["id"] for r in cs.RULES], who)
            st.rerun()


def _audit(S):
    st.subheader("Audit trail")
    st.write("Every approval, eligibility result, fact change and decision is added to one chain. Each entry’s fingerprint (SHA-256) "
             "includes the fingerprint of the entry before it, so changing any earlier entry breaks every later one.")
    c1, c2, c3 = st.columns(3)
    if c1.button("Verify chain"):
        ok, msg = cs.verify_chain(S["audit"])
        (st.success if ok else st.error)(msg)
    if S["tampered"] is None:
        if c2.button("Alter the oldest entry (demo)", disabled=not S["audit"]):
            cs.tamper(S)
            st.warning("The oldest entry was altered in memory. Run Verify chain to see it caught.")
    elif c2.button("Undo the alteration"):
        cs.restore(S)
        st.rerun()
    if not S["audit"]:
        st.caption("No entries yet. Approve a rule or record a decision and it appears here.")
    for e in reversed(S["audit"]):
        with st.expander(f"#{e['n']} · {e['action']} · {e['resourceId']} · {e['actor']} · {e['at']}"):
            st.json(e["detail"])
            st.code(f"prev: {e['prev']}\nhash: {e['hash']}", language="text")


def _watch():
    st.subheader("Funding watch")
    st.write("A daily check of Grants.gov for new notices that match “flood mitigation” and “hazard mitigation.” These are real entries "
             "captured between August and September 2026. Keyword matching is noisy, so only the 4 that look relevant are shown first. "
             "Status and deadlines are not checked here, so open the notice on Grants.gov before relying on any of them.")
    show_all = st.toggle("Show all 16 captured", key="cs_allopps")
    for oid, title, agency, seen, rel in cs.OPPS:
        if show_all or rel:
            st.markdown(f"**{title}**  \n{agency} · first seen {seen} · [Open on Grants.gov](https://www.grants.gov/search-results-detail/{oid})")
