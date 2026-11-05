"""PAS decision packet: Markdown and PDF for one case. No Streamlit imports.

Distinguishes what is verified (with evidence) from what is pending, and names the responsible authority for each item.
It documents an internal administrative review; it is not a FEMA approval and makes no federal determination.
"""
from __future__ import annotations

import io
from typing import Any

import pas_engine as pe
import pas_rules

DISCLAIMER = ("Internal administrative review record prepared with CivicSignal. It is not a FEMA approval, award or eligibility determination. "
              "Items marked 'federal' are determined by FEMA. Requirement sources marked 'needs confirmation' must be checked against the "
              "guidance version governing the funding opportunity.")
DEMO_NOTICE = "DEMO RECORD: this case was loaded as sample data for demonstration and does not describe a real application."


def build_packet(pas: dict[str, Any], case_id: str, events: list[dict[str, Any]], *, tenant: str = "default", prepared_by: str = "",
                 now: str | None = None, chain: tuple[bool, str] | None = None) -> dict[str, Any]:
    now = now or pe.now_iso()
    c = pas["cases"][case_id]
    ready = pe.evaluate_readiness(c)
    reqs = {r["id"]: r for r in pas_rules.requirements_for(c["program"])}
    items = []
    sd = pas["config"].get("stale_after_days", pe.DEFAULT_STALE_DAYS)
    for rid, r in reqs.items():
        it = c["checklist"][rid]
        fr = pe.item_freshness(c, rid, now, sd)
        items.append({"time_sensitive": r.get("time_sensitive", False), "freshness": fr["state"], "age_days": fr["days"], "verified_at": fr["verified_at"], "id": rid, "label": r["label"], "required": r["required"], "status": it["status"], "authority": r["authority"],
                      "evidence": it["evidence"], "note": it["note"], "source": r["source_title"], "source_type": r["source_type"],
                      "confirmed": r["confirmed"], "updated_at": it["updated_at"], "updated_by": it["updated_by"]})
    return {"generated_at": now, "tenant": tenant, "prepared_by": prepared_by or "(not signed in)", "case": {k: c[k] for k in (
        "id", "project_id", "jurisdiction", "program", "hazard", "subapplicant", "submitted_at", "due_at", "stage", "assigned_to", "demo",
        "guidance_version", "funding_opportunity")},
        "status": pe.derived_status(c), "overall": ready["overall"], "delegation": dict(pas["config"]["delegation"]),
        "agreement_ref": pas["config"].get("agreement_ref", ""), "disaster": pas["config"].get("disaster", ""),
        "items": items, "verified": [i for i in items if i["status"] == "Verified"],
        "pending": [i for i in items if i["status"] not in ("Verified", "Not applicable")],
        "stale_after_days": sd, "stale": [i for i in items if i["freshness"] == "stale"],
        "history": c["history"], "requests": c["requests"], "comments": c["comments"], "decision": c["decision"],
        "federal_referral": c["federal_referral"], "stage_durations": pe.stage_durations(c, now), "audit": events,
        "chain_ok": chain[0] if chain else None, "chain_message": chain[1] if chain else "not checked",
        "catalogue_version": pas_rules.CATALOGUE_VERSION}


def _auth(i: dict[str, Any]) -> str:
    return "FEMA" if i["authority"] == "federal" else "State/county"


def to_markdown(p: dict[str, Any]) -> str:
    c = p["case"]
    L = [f"# PAS Review Packet: {c['id']}", "", f"*{DISCLAIMER}*", ""]
    if c["demo"]:
        L += [f"**{DEMO_NOTICE}**", ""]
    L += [f"- Project: {c['project_id']} ({c['program']}, {c['hazard'] or 'hazard not set'})", f"- Jurisdiction: {c['jurisdiction']}; subapplicant: {c['subapplicant'] or 'not set'}",
          f"- Submitted: {c['submitted_at']}; review deadline: {c['due_at'] or 'not set'}", f"- Stage: {pe.STAGE_LABEL[c['stage']]}; status: {p['status']}",
          f"- Reviewer: {c['assigned_to'] or 'unassigned'}", f"- Checklist result: {p['overall'].replace('_', ' ')}",
          f"- Guidance version recorded: {c['guidance_version'] or 'not recorded'}; operational agreement: {p['agreement_ref'] or 'not recorded'}",
          f"- Delegated PAS functions: {', '.join(k for k, v in p['delegation'].items() if v) or 'none recorded'}",
          f"- Prepared by {p['prepared_by']} at {p['generated_at']}", "", "## Verified (evidence on file)", ""]
    L += [f"- {i['label']} [{_auth(i)}] evidence: {'; '.join(i['evidence'])} (by {i['updated_by']}, last verified {(i['verified_at'] or i['updated_at'])[:10]}"
          f"{', ' + str(i['age_days']) + ' days before this packet' if i['freshness'] in ('fresh', 'stale') else ''}"
          f"{'; STALE, re-confirm' if i['freshness'] == 'stale' else ''})" for i in p["verified"]] or ["- None"]
    if p["stale"]:
        L += ["", f"**Re-confirm before relying on this packet:** {len(p['stale'])} time-sensitive item(s) were verified more than {p['stale_after_days']} days ago."]
    L += ["", "## Pending or unresolved", ""]
    L += [f"- {i['label']}: **{i['status']}** [{_auth(i)}; {'required' if i['required'] else 'optional'}] source: {i['source']}"
          f"{'' if i['confirmed'] else ' (needs confirmation)'}" for i in p["pending"]] or ["- None"]
    L += ["", "## Requests and corrections", ""]
    L += [f"- {r['id']} {r['kind']} to {r['responsible']}: {r['text']} (opened {r['created_at']}, due {r['due_at'] or 'n/a'}, "
          f"{'resolved ' + r['resolved_at'] if r['resolved_at'] else 'responded ' + r['responded_at'] if r['responded_at'] else 'open'})" for r in p["requests"]] or ["- None"]
    L += ["", "## Decision record", ""]
    d = p["decision"]
    L += [f"- {d['label']} by {d['by']} at {d['at']}. Rationale: {d['rationale']}"] if d else ["- No state decision recorded."]
    fr = p["federal_referral"]
    if fr:
        L += [f"- Federal referral {fr['referred_at']} ({fr['reason']}); FEMA outcome: {fr['outcome'] or 'pending'}"]
    L += ["", "## Stage history", ""] + [f"- {h['at']}: {h['from'] or 'start'} -> {h['to']} by {h['actor']} {h['note']}" for h in p["history"]]
    L += ["", "## Audit trail excerpt", f"Chain check: {p['chain_message']}", ""] + [f"- #{e['n']} {e['at']} {e['actor']} {e['action']} {e['hash'][:12]}" for e in p["audit"]]
    return "\n".join(L) + "\n"


def to_pdf(p: dict[str, Any]) -> bytes:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    from xml.sax.saxutils import escape

    ss = getSampleStyleSheet()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, title=f"PAS Review Packet {p['case']['id']}")
    flow: list[Any] = []
    for line in to_markdown(p).splitlines():
        if not line.strip():
            flow.append(Spacer(1, 6))
        elif line.startswith("# "):
            flow.append(Paragraph(escape(line[2:]), ss["Title"]))
        elif line.startswith("## "):
            flow.append(Paragraph(escape(line[3:]), ss["Heading2"]))
        else:
            flow.append(Paragraph(escape(line.replace("**", "").replace("*", "")), ss["BodyText"]))
    doc.build(flow)
    return buf.getvalue()

