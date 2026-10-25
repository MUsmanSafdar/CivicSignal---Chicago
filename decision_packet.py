"""Decision packet export (Phase 1.4): Markdown and PDF. No Streamlit imports.

The packet records what was ranked, why, which rules applied (with CFR citations), who decided what and when,
and an excerpt of the hash-chained audit trail with a verification statement. It documents an official's decision;
it never makes one.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any

import civicsignal as cs

DISCLAIMER = ("Administrative screening aid, not a legal determination and not legal advice. Eligibility results apply the "
              "wording of the cited regulations to the facts on file. The decision rests with the named official.")
SAMPLE_NOTICE = "SAMPLE DATA: every project, score, cost and sponsor in this packet is invented for demonstration."
OUTCOME_TEXT = {"pass": "Eligible", "review": "Needs review", "fail": "Not eligible"}
DECISION_TEXT = {"approved": "Approved", "held": "On hold"}


def build_packet(state: dict[str, Any], weights: dict[str, int], budget: float, *, tenant: str = "default",
                 prepared_by: str = "", sample_data: bool = True, audit_limit: int = 25,
                 now: str | None = None) -> dict[str, Any]:
    """Collect everything the packet shows into one plain dict (also handy for tests)."""
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    ok, verdict = cs.verify_chain(state["audit"])
    out: dict[str, Any] = {
        "generated_at": now, "tenant": tenant, "prepared_by": prepared_by or "(not signed in)", "sample_data": sample_data,
        "budget_millions": budget, "weights": dict(weights),
        "total_weight": cs.total_weight(weights), "ranking": [], "decisions": [],
        "audit_total": len(state["audit"]), "audit_excerpt": state["audit"][-audit_limit:],
        "chain_ok": ok, "chain_message": verdict,
        "published_rules": {k: dict(v) for k, v in state["published"].items()},
    }
    if not cs.weights_valid(weights):
        out["ranking_error"] = "Total weight is 0, so no ranking was produced."
        return out
    rk = cs.ranked(state["projects"], weights, state["published"])
    within, spend = cs.funded_line(rk, budget)
    out["spend_millions"] = spend
    tw = cs.total_weight(weights)
    for i, r in enumerate(rk, start=1):
        p, e = r["p"], r["e"]
        dec = state["decisions"].get(p["id"])
        out["ranking"].append({
            "rank": i, "id": p["id"], "name": p["name"], "program": p["program"], "hazard": p["hazard"], "cost": p["cost"],
            "sponsor": p["sponsor"]["name"], "score": round(r["s"], 1), "within_budget": p["id"] in within,
            "eligibility": e["overall"] if e else "not_checked",
            "breakdown": [{"key": k, "label": lbl, "value": p[k], "weight": weights[k], "share": round(weights[k] / tw, 4),
                           "points": round(p[k] * weights[k] / tw, 1), "source": src} for k, lbl, _, src in cs.CRITERIA],
            "rules": [{"title": o["rule"]["title"], "cite": o["rule"]["cite"], "url": o["rule"]["url"], "outcome": o["out"],
                       "reason": o["why"]} for o in (e["outs"] if e else [])],
            "decision": dict(dec) if dec else None,
        })
    for ev in state["audit"]:
        if ev["action"].startswith("project.decision."):
            d = ev["detail"]
            out["decisions"].append({"project": d.get("project", ev["resourceId"]), "id": ev["resourceId"],
                                     "action": ev["action"].rsplit(".", 1)[-1], "actor": ev["actor"], "at": ev["at"],
                                     "reason": d.get("note", ""), "rank": d.get("rank"), "eligibility": d.get("eligibility")})
    return out


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def to_markdown(packet: dict[str, Any]) -> str:
    """Render the packet as Markdown."""
    L: list[str] = ["# CivicSignal decision packet", "",
                    f"Generated: {packet['generated_at']} · Tenant: {packet['tenant']} · Prepared by: {packet['prepared_by']}", ""]
    if packet["sample_data"]:
        L += [f"> **{SAMPLE_NOTICE}**", ""]
    L += [f"> {DISCLAIMER}", "", "## 1. Weights and budget", "",
          "| Criterion | Weight | Share | Data source |", "|---|---|---|---|"]
    tw = packet["total_weight"]
    for k, label, _, src in cs.CRITERIA:
        w = packet["weights"].get(k, 0)
        L.append(f"| {label} | {w} | {round(100 * w / tw) if tw else 0}% | {_cell(src)} |")
    L += ["", f"Funds available: ${packet['budget_millions']:.1f}M", ""]
    L += ["## 2. Ranked projects", ""]
    if packet.get("ranking_error"):
        L += [packet["ranking_error"], ""]
    else:
        L += [f"Spend within budget: ${packet['spend_millions']:.1f}M", "",
              "| # | Project | Program | Score | Cost | Eligibility | Within budget | Decision |", "|---|---|---|---|---|---|---|---|"]
        for r in packet["ranking"]:
            dec = DECISION_TEXT.get(r["decision"]["action"], "") if r["decision"] else ""
            L.append(f"| {r['rank']} | {_cell(r['name'])} | {r['program']} | {r['score']} | ${r['cost']:.1f}M | "
                     f"{OUTCOME_TEXT.get(r['eligibility'], 'Not checked')} | {'Yes' if r['within_budget'] else 'No'} | {dec} |")
        L += ["", "## 3. Score breakdown and eligibility by project", ""]
        for r in packet["ranking"]:
            L += [f"### {r['rank']}. {r['name']} ({r['id']})", "",
                  f"{r['hazard']} · {r['program']} · ${r['cost']:.1f}M · Sponsor: {r['sponsor']} · Score {r['score']}", "",
                  "| Criterion | Value | Weight share | Points | Source |", "|---|---|---|---|---|"]
            for b in r["breakdown"]:
                L.append(f"| {b['label']} | {b['value']} | {round(100 * b['share'])}% | {b['points']} | {_cell(b['source'])} |")
            L += ["", f"Eligibility: **{OUTCOME_TEXT.get(r['eligibility'], 'Not checked')}**", ""]
            for o in r["rules"]:
                L.append(f"- **{OUTCOME_TEXT[o['outcome']]}**: {o['title']} ([{o['cite']}]({o['url']})). {o['reason']}")
            L.append("")
    L += ["## 4. Decisions on record", ""]
    if packet["decisions"]:
        L += ["| Project | Decision | By | When (UTC) | Reason |", "|---|---|---|---|---|"]
        for d in packet["decisions"]:
            L.append(f"| {_cell(d['project'])} | {DECISION_TEXT.get(d['action'], d['action'])} | {_cell(d['actor'])} | {d['at']} | {_cell(d['reason'])} |")
    else:
        L.append("No decisions have been recorded.")
    L += ["", "## 5. Audit trail excerpt", "",
          f"Showing the last {len(packet['audit_excerpt'])} of {packet['audit_total']} entries.", ""]
    for e in packet["audit_excerpt"]:
        L += [f"- #{e['n']} {e['at']} · {e['actor']} · {e['action']} · {e['resourceId']}", f"  - prev `{e['prev']}`", f"  - hash `{e['hash']}`"]
    L += ["", "### Chain verification", "",
          f"{'VERIFIED' if packet['chain_ok'] else 'FAILED'}: {packet['chain_message']}", ""]
    return "\n".join(L)


def to_pdf(packet: dict[str, Any]) -> bytes:
    """Render the packet as a PDF with reportlab."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9, leading=12)
    small = ParagraphStyle("s", parent=body, fontSize=7, leading=9)
    mono = ParagraphStyle("m", parent=small, fontName="Courier", fontSize=6.5, leading=8)
    note = ParagraphStyle("n", parent=body, backColor=colors.HexColor("#fff8e6"), borderPadding=4)

    def P(text: object, style: ParagraphStyle = body) -> Paragraph:
        return Paragraph(escape(str(text)), style)

    def table(rows: list[list[object]], widths: list[float]) -> Table:
        t = Table([[P(c, small) for c in r] for r in rows], colWidths=[w * inch for w in widths], repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e1effd")),
                               ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c7c7cc")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        return t

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.7 * inch, rightMargin=0.7 * inch, topMargin=0.7 * inch,
                            bottomMargin=0.7 * inch, title="CivicSignal decision packet", author=str(packet["prepared_by"]))
    S: list[Any] = [P("CivicSignal decision packet", ss["Title"]),
                    P(f"Generated {packet['generated_at']} · Tenant {packet['tenant']} · Prepared by {packet['prepared_by']}")]
    if packet["sample_data"]:
        S += [Spacer(1, 6), P(SAMPLE_NOTICE, note)]
    S += [Spacer(1, 6), P(DISCLAIMER, note), Spacer(1, 10), P("1. Weights and budget", ss["Heading2"])]
    tw = packet["total_weight"]
    S.append(table([["Criterion", "Weight", "Share", "Data source"]] +
                   [[lbl, packet["weights"].get(k, 0), f"{round(100 * packet['weights'].get(k, 0) / tw) if tw else 0}%", src]
                    for k, lbl, _, src in cs.CRITERIA], [1.6, 0.6, 0.6, 4.3]))
    S += [Spacer(1, 4), P(f"Funds available: ${packet['budget_millions']:.1f}M"), P("2. Ranked projects", ss["Heading2"])]
    if packet.get("ranking_error"):
        S.append(P(packet["ranking_error"]))
    else:
        S.append(table([["#", "Project", "Prog.", "Score", "Cost", "Eligibility", "Budget", "Decision"]] +
                       [[r["rank"], r["name"], r["program"], r["score"], f"${r['cost']:.1f}M",
                         OUTCOME_TEXT.get(r["eligibility"], "Not checked"), "Yes" if r["within_budget"] else "No",
                         DECISION_TEXT.get(r["decision"]["action"], "") if r["decision"] else ""] for r in packet["ranking"]],
                       [0.3, 2.5, 0.5, 0.5, 0.6, 1.1, 0.6, 0.8]))
        S.append(P("3. Score breakdown and eligibility", ss["Heading2"]))
        for r in packet["ranking"]:
            S += [P(f"{r['rank']}. {r['name']} ({r['id']}) · {r['hazard']} · {r['program']} · score {r['score']}", ss["Heading4"]),
                  table([["Criterion", "Value", "Share", "Points", "Source"]] +
                        [[b["label"], b["value"], f"{round(100 * b['share'])}%", b["points"], b["source"]] for b in r["breakdown"]],
                        [1.4, 0.5, 0.6, 0.6, 4.0])]
            if r["rules"]:
                S.append(Spacer(1, 3))
                S.append(table([["Rule", "Citation", "Result", "Reason"]] +
                               [[o["title"], o["cite"], OUTCOME_TEXT[o["outcome"]], o["reason"]] for o in r["rules"]], [1.5, 1.1, 0.8, 3.7]))
            S.append(Spacer(1, 6))
    S.append(P("4. Decisions on record", ss["Heading2"]))
    if packet["decisions"]:
        S.append(table([["Project", "Decision", "By", "When (UTC)", "Reason"]] +
                       [[d["project"], DECISION_TEXT.get(d["action"], d["action"]), d["actor"], d["at"], d["reason"]]
                        for d in packet["decisions"]], [1.6, 0.7, 1.4, 1.2, 2.2]))
    else:
        S.append(P("No decisions have been recorded."))
    S.append(P(f"5. Audit trail excerpt (last {len(packet['audit_excerpt'])} of {packet['audit_total']})", ss["Heading2"]))
    for e in packet["audit_excerpt"]:
        S += [P(f"#{e['n']} {e['at']} · {e['actor']} · {e['action']} · {e['resourceId']}", small),
              P(f"prev {e['prev']}", mono), P(f"hash {e['hash']}", mono), Spacer(1, 3)]
    S += [P("Chain verification", ss["Heading3"]),
          P(f"{'VERIFIED' if packet['chain_ok'] else 'FAILED'}: {packet['chain_message']}")]
    doc.build(S)
    return buf.getvalue()
