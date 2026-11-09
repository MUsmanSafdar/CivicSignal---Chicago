"""PAS document review: validate an upload, run a submitted review against the PAS requirement catalogue, track findings. Pure, no Streamlit.

Flow: upload (staged in the session only) -> configure -> SUBMIT (creates the review record) -> analyze -> reviewer resolves findings -> decision -> packet.
Nothing is analyzed or recorded until ``submit`` is called.

What the analysis can and cannot say
- It searches the document text for evidence of each requirement and reports WHERE it found it (page or line range plus a short excerpt).
  Finding text is not proof: a reviewer must confirm it. Only a reviewer's confirmation makes a finding "verified".
- Requirements FEMA decides (``authority == "federal"``) are never judged here; they are listed as "cannot be determined automatically".
- Consistency checks (expired dates, conflicting cost figures, placeholder text, a suspended NFIP status) raise "potential issues for human review".
- No requirement is marked met, approved or eligible, and nothing here is a FEMA determination.

Only a hash, file facts, short excerpts and the findings are stored. The uploaded file itself and its full text are not retained.
"""
from __future__ import annotations

import hashlib
import io
import re
from datetime import date, datetime, timezone
from typing import Any

import pas_rules

ALLOWED_EXT = (".pdf", ".txt", ".md", ".csv")
MAX_BYTES = 20 * 1024 * 1024
MAX_PAGES = 400
MAX_CHARS = 2_000_000
MAX_EXCERPT = 280
MAX_EVIDENCE = 3
PROGRAMS = ("HMGP", "FMA")  # programs the requirement catalogue covers

CATEGORY_LABEL = {
    "located": "Evidence located, reviewer to confirm",
    "verified": "Verified by reviewer",
    "issue": "Potential issue, human review needed",
    "missing": "Missing information",
    "undeterminable": "Cannot be determined automatically",
}
DECISIONS = ("ready_for_next_stage", "return_for_corrections")
DECISION_LABEL = {"ready_for_next_stage": "Ready for the next review stage", "return_for_corrections": "Return to the applicant for corrections"}

# requirement id -> patterns that suggest the document addresses it. A match is a pointer for the reviewer, not proof.
EVIDENCE_TERMS: dict[str, list[str]] = {
    "app_form": [r"authorized (?:representative|official)", r"\bsigned\b", r"signature", r"application form"],
    "subapplicant_eligible": [r"local government", r"\bcounty\b", r"\bmunicipal\w*", r"subapplicant", r"eligible (?:applicant|entity)", r"drainage district"],
    "hmp_current": [r"hazard mitigation plan", r"FEMA[- ]approved", r"plan (?:approval|adoption|expir\w+)"],
    "nfip_good_standing": [r"\bNFIP\b", r"National Flood Insurance Program", r"community (?:identification|id) (?:number|no)", r"\bCRS\b"],
    "scope_of_work": [r"scope of work", r"project description", r"project location", r"latitude", r"work will include"],
    "cost_estimate": [r"cost estimate", r"total (?:project )?cost", r"project budget", r"itemized"],
    "bca": [r"benefit[- ]cost", r"\bBCA\b", r"\bBCR\b", r"cost[- ]effective\w*"],
    "ehp": [r"environmental", r"historic preservation", r"\bEHP\b", r"\bNEPA\b", r"section 106"],
    "nonfederal_share": [r"non-?federal share", r"local match", r"cost share", r"matching funds", r"\b25\s?%"],
    "maintenance_plan": [r"maintenance", r"operate and maintain", r"\bO&M\b"],
    "community_support": [r"letters? of support", r"public (?:meeting|comment)", r"community (?:support|outreach)", r"outreach"],
}

_DATE = r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? \d{1,2}, \d{4})"
_EXPIRY = re.compile(r"(?:expir\w*|valid (?:through|until))[^.\n]{0,60}?" + _DATE, re.I)
_COST = re.compile(r"(?:total (?:project )?cost|project cost|total cost)[^$\n]{0,40}\$\s?([\d,]+(?:\.\d+)?)", re.I)
_PLACEHOLDER = re.compile(r"\b(TBD|TBA|to be determined|lorem ipsum)\b|\[insert[^\]]*\]", re.I)
_NFIP_BAD = re.compile(r"NFIP[^.\n]{0,80}\b(suspended|withdrawn|not participating)\b|\b(suspended|withdrawn)\b[^.\n]{0,40}NFIP", re.I)


class ReviewError(ValueError):
    """A refused action (bad file, missing note, not allowed in this state). The message says what to fix."""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- upload validation and text extraction
def safe_name(name: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", (name or "").replace("\\", "/").split("/")[-1]).strip(" .")
    return (base or "document")[:120]


def validate_upload(name: str, raw: bytes) -> dict[str, Any]:
    """Check type, size and content. Raises ReviewError with a plain message; returns file facts on success."""
    fname = safe_name(name)
    ext = ("." + fname.rsplit(".", 1)[-1].lower()) if "." in fname else ""
    if ext not in ALLOWED_EXT:
        raise ReviewError(f"Unsupported file type. Use one of: {', '.join(ALLOWED_EXT)}.")
    if not raw:
        raise ReviewError("The file is empty.")
    if len(raw) > MAX_BYTES:
        raise ReviewError(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    if ext == ".pdf" and not raw.startswith(b"%PDF-"):
        raise ReviewError("The file is named .pdf but is not a PDF.")
    if ext != ".pdf":
        if b"\x00" in raw[:4096]:
            raise ReviewError("The file does not look like plain text.")
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as e:
            raise ReviewError("Text files must be UTF-8.") from e
    return {"name": fname, "ext": ext, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def extract_units(ext: str, raw: bytes) -> list[dict[str, str]]:
    """Split a document into locatable units: one per PDF page, or 50-line blocks for text. Each unit is {locator, text}."""
    if ext == ".pdf":
        import pdfplumber  # lazy: the pure rules below do not need it

        units: list[dict[str, str]] = []
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            if len(pdf.pages) > MAX_PAGES:
                raise ReviewError(f"The PDF has more than {MAX_PAGES} pages.")
            for i, page in enumerate(pdf.pages, start=1):
                units.append({"locator": f"Page {i}", "text": page.extract_text() or ""})
        return units
    lines = raw.decode("utf-8").splitlines()
    return [{"locator": f"Lines {i + 1}-{min(i + 50, len(lines))}", "text": "\n".join(lines[i:i + 50])} for i in range(0, len(lines), 50)] or \
           [{"locator": "Lines 1-1", "text": ""}]


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x08\x0b-\x1f]", " ", s)).strip()


def _excerpt(text: str, start: int, end: int) -> str:
    a, b = max(0, start - 90), min(len(text), end + 90)
    return ("..." if a else "") + _clean(text[a:b])[:MAX_EXCERPT] + ("..." if b < len(text) else "")


def _parse_date(s: str) -> date | None:
    s = s.replace(".", "")
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------- the review record
def new_review(review_id: str, actor: str, file_facts: dict[str, Any], config: dict[str, Any], at: str | None = None) -> dict[str, Any]:
    program = config.get("program", "")
    if program not in PROGRAMS:
        raise ReviewError(f"Choose a program: {', '.join(PROGRAMS)}.")
    if not str(config.get("jurisdiction", "")).strip() or not str(config.get("project", "")).strip():
        raise ReviewError("Enter the jurisdiction and the project name before submitting.")
    at = at or now_iso()
    return {"id": review_id, "status": "submitted", "created_at": at, "submitted_by": actor, "analyzed_at": "", "file": file_facts,
            "config": {"program": program, "jurisdiction": str(config["jurisdiction"]).strip()[:120], "project": str(config["project"]).strip()[:160],
                       "guidance_version": str(config.get("guidance_version", "")).strip()[:80], "catalogue_version": pas_rules.CATALOGUE_VERSION},
            "findings": [], "decision": None, "history": [{"at": at, "actor": actor, "action": "submitted", "note": f"{file_facts['name']} ({file_facts['sha256'][:12]})"}]}


def _finding(n: int, category: str, label: str, explanation: str, evidence: list[dict[str, str]], **extra: Any) -> dict[str, Any]:
    return {"id": f"F{n}", "category": category, "label": label, "explanation": explanation, "evidence": evidence[:MAX_EVIDENCE], "status": "open",
            "note": "", "resolved_by": "", "resolved_at": "", "req_id": "", "authority": "", "source_title": "", "source_confirmed": False, "required": False, **extra}


def analyze(review: dict[str, Any], units: list[dict[str, str]], actor: str, today: date | None = None, at: str | None = None) -> dict[str, Any]:
    """Run the requirement and consistency checks. Replaces the findings; the document text is not kept."""
    if review["status"] not in ("submitted", "analyzed"):
        raise ReviewError("This review has already moved past analysis.")
    today = today or date.today()
    findings: list[dict[str, Any]] = []
    n = 0
    for req in pas_rules.requirements_for(review["config"]["program"]):
        hits: list[dict[str, str]] = []
        for u in units:
            text = u["text"]
            for pat in EVIDENCE_TERMS.get(req["id"], []):
                m = re.search(pat, text, re.I)
                if m and len(hits) < MAX_EVIDENCE and not any(h["locator"] == u["locator"] for h in hits):
                    hits.append({"locator": u["locator"], "snippet": _excerpt(text, m.start(), m.end())})
                    break
        n += 1
        meta = {"req_id": req["id"], "authority": req["authority"], "source_title": req["source_title"], "source_confirmed": bool(req["confirmed"]),
                "required": bool(req["required"])}
        if req["authority"] == "federal":
            expl = "FEMA keeps this determination, so CivicSignal does not judge it. " + ("Passages that may be relevant are shown for the reviewer." if hits
                                                                                           else "No relevant passage was found; the reviewer should check the file.")
            findings.append(_finding(n, "undeterminable", req["label"], expl, hits, **meta))
        elif hits:
            findings.append(_finding(n, "located", req["label"], "Text that may address this requirement was found. Confirm that it actually does.", hits, **meta))
        elif req["required"]:
            findings.append(_finding(n, "missing", req["label"], "No text addressing this required item was found in the document.", [], **meta))
        else:
            findings.append(_finding(n, "missing", req["label"], "No text addressing this optional item was found.", [], **{**meta, "required": False}))
    for cat_label, expl, ev in _consistency_checks(units, today):
        n += 1
        findings.append(_finding(n, "issue", cat_label, expl, ev, req_id="consistency", authority="state", source_title="CivicSignal consistency check", source_confirmed=False))
    review["findings"] = findings
    review["status"] = "analyzed"
    review["analyzed_at"] = at or now_iso()
    review["history"].append({"at": review["analyzed_at"], "actor": actor, "action": "analyzed",
                              "note": f"{len(findings)} findings: " + ", ".join(f"{k} {v}" for k, v in summary(review)["counts"].items() if v)})
    return review


def _consistency_checks(units: list[dict[str, str]], today: date) -> list[tuple[str, str, list[dict[str, str]]]]:
    out: list[tuple[str, str, list[dict[str, str]]]] = []
    expired: list[dict[str, str]] = []
    costs: dict[str, dict[str, str]] = {}
    placeholders: list[dict[str, str]] = []
    nfip: list[dict[str, str]] = []
    for u in units:
        t = u["text"]
        for m in _EXPIRY.finditer(t):
            d = _parse_date(m.group(1))
            if d and d < today:
                expired.append({"locator": u["locator"], "snippet": _excerpt(t, m.start(), m.end())})
        for m in _COST.finditer(t):
            costs.setdefault(m.group(1).replace(",", ""), {"locator": u["locator"], "snippet": _excerpt(t, m.start(), m.end())})
        m2 = _PLACEHOLDER.search(t)
        if m2:
            placeholders.append({"locator": u["locator"], "snippet": _excerpt(t, m2.start(), m2.end())})
        m3 = _NFIP_BAD.search(t)
        if m3:
            nfip.append({"locator": u["locator"], "snippet": _excerpt(t, m3.start(), m3.end())})
    if expired:
        out.append(("A date in the document has already passed", "An expiry or validity date is earlier than today. Check that the plan or approval is still current.", expired))
    if len({round(float(c), 2) for c in costs}) > 1:
        out.append(("Conflicting total cost figures", "The document gives more than one total cost: " + ", ".join(f"${float(c):,.0f}" for c in costs) + ".",
                    list(costs.values())))
    if placeholders:
        out.append(("Placeholder text left in the document", "Text such as TBD or a bracketed placeholder suggests unfinished sections.", placeholders))
    if nfip:
        out.append(("NFIP status may be suspended or withdrawn", "The document describes NFIP participation as suspended, withdrawn or absent. Confirm in FEMA's Community Status Book.", nfip))
    return out


# ---------------------------------------------------------------- reviewer actions
def _find(review: dict[str, Any], fid: str) -> dict[str, Any]:
    for f in review["findings"]:
        if f["id"] == fid:
            return f
    raise ReviewError(f"No finding {fid}.")


def close_finding(review: dict[str, Any], fid: str, actor: str, note: str, at: str | None = None) -> dict[str, Any]:
    """A reviewer confirms located evidence (becomes verified) or resolves an issue, missing item or federal item. A note is required."""
    if review["decision"]:
        raise ReviewError("A decision has been recorded; this review is closed to changes.")
    if review["status"] not in ("analyzed", "in_review"):
        raise ReviewError("Findings can be changed only after the analysis has run.")
    if not (note or "").strip():
        raise ReviewError("Add a note explaining what you checked or what resolved this finding.")
    f = _find(review, fid)
    if f["status"] != "open":
        raise ReviewError(f"{fid} is already {f['status']}.")
    at = at or now_iso()
    f["status"] = "confirmed" if f["category"] == "located" else "resolved"
    if f["category"] == "located":
        f["category"] = "verified"
    f.update({"note": note.strip()[:1000], "resolved_by": actor, "resolved_at": at})
    review["status"] = "in_review"
    review["history"].append({"at": at, "actor": actor, "action": f"finding_{f['status']}", "note": f"{fid} {f['label'][:60]}: {f['note'][:120]}"})
    return f


def reopen_finding(review: dict[str, Any], fid: str, actor: str, note: str, at: str | None = None) -> dict[str, Any]:
    if review["decision"]:
        raise ReviewError("A decision has been recorded; this review is closed to changes.")
    if not (note or "").strip():
        raise ReviewError("Add a note explaining why this finding is being reopened.")
    f = _find(review, fid)
    if f["status"] == "open":
        raise ReviewError(f"{fid} is already open.")
    if f["category"] == "verified":
        f["category"] = "located"
    f.update({"status": "open", "resolved_by": "", "resolved_at": ""})
    at = at or now_iso()
    review["history"].append({"at": at, "actor": actor, "action": "finding_reopened", "note": f"{fid}: {note.strip()[:200]}"})
    return f


def blocking(review: dict[str, Any]) -> list[dict[str, Any]]:
    """Open findings that must be handled before a 'ready' decision: issues, missing required items and items for FEMA."""
    return [f for f in review["findings"] if f["status"] == "open" and
            (f["category"] in ("issue", "undeterminable") or (f["category"] == "missing" and f["required"]))]


def record_decision(review: dict[str, Any], actor: str, decision: str, note: str, at: str | None = None) -> dict[str, Any]:
    if decision not in DECISIONS:
        raise ReviewError("Unknown decision.")
    if review["decision"]:
        raise ReviewError("A decision has already been recorded.")
    if review["status"] not in ("analyzed", "in_review"):
        raise ReviewError("Run the analysis before recording a decision.")
    if not (note or "").strip():
        raise ReviewError("Add a note explaining the decision.")
    if decision == "ready_for_next_stage" and blocking(review):
        raise ReviewError(f"{len(blocking(review))} finding(s) are still open: " + ", ".join(f['id'] for f in blocking(review)) + ". Resolve them first.")
    at = at or now_iso()
    review["decision"] = {"decision": decision, "note": note.strip()[:1000], "by": actor, "at": at, "unconfirmed_evidence": [
        f["id"] for f in review["findings"] if f["category"] == "located" and f["status"] == "open"]}
    review["status"] = "decided"
    review["history"].append({"at": at, "actor": actor, "action": "decision", "note": f"{DECISION_LABEL[decision]}: {note.strip()[:160]}"})
    return review["decision"]


def summary(review: dict[str, Any]) -> dict[str, Any]:
    counts = {k: 0 for k in CATEGORY_LABEL}
    for f in review["findings"]:
        counts[f["category"]] += 1
    total = len(review["findings"])
    handled = sum(1 for f in review["findings"] if f["status"] != "open")
    return {"counts": counts, "total": total, "handled": handled, "blocking": len(blocking(review)), "progress": (handled / total) if total else 0.0}


def step(review: dict[str, Any] | None, staged: bool) -> int:
    """Index into STEPS for the progress display."""
    if review is None:
        return 1 if staged else 0
    if review["status"] == "submitted":
        return 3
    if review["status"] == "analyzed":
        return 4
    if review["status"] == "in_review":
        return 5 if blocking(review) else 6
    return 6


STEPS = ["Upload", "Configure", "Submit for review", "Analyze", "Review findings", "Resolve issues", "Decision packet"]


def next_review_id(seq: int, at: str | None = None) -> str:
    return f"REV-{(at or now_iso())[:10].replace('-', '')}-{seq:04d}"


# ---------------------------------------------------------------- decision packet
DISCLAIMER = ("This packet is an internal administrative aid prepared with CivicSignal. It is not a FEMA approval, award or eligibility determination. "
              "Located evidence is a pointer for the reviewer, not proof; only findings marked verified were confirmed by a named reviewer.")


def packet_markdown(review: dict[str, Any], tenant: str = "", sample_data: bool = True) -> str:
    cfg, f = review["config"], review["file"]
    s = summary(review)
    L = [f"# Document Review Packet {review['id']}", "", f"> {DISCLAIMER}", ""]
    if sample_data:
        L += ["> **Illustrative or test session.** Do not treat the contents as an official record.", ""]
    L += ["## Submission", "", f"- Review ID: {review['id']}", f"- Tenant: {tenant or 'n/a'}", f"- Submitted: {review['created_at']} by {review['submitted_by']}",
          f"- Analyzed: {review['analyzed_at'] or 'not yet'}", f"- Document: {f['name']} ({f['size']:,} bytes)", f"- SHA-256: {f['sha256']}",
          f"- Program: {cfg['program']}; jurisdiction: {cfg['jurisdiction']}; project: {cfg['project']}",
          f"- Guidance version: {cfg['guidance_version'] or 'not recorded'}; requirement catalogue {cfg['catalogue_version']}", "",
          "## Summary", "", "| Category | Count |", "| --- | --- |"]
    L += [f"| {CATEGORY_LABEL[k]} | {v} |" for k, v in s["counts"].items()]
    L += ["", f"{s['handled']} of {s['total']} findings handled; {s['blocking']} blocking items still open.", ""]
    d = review["decision"]
    L += ["## Decision", "", (f"**{DECISION_LABEL[d['decision']]}** by {d['by']} at {d['at']}. {d['note']}" if d else "No decision recorded yet.")]
    if d and d["unconfirmed_evidence"]:
        L += ["", "Evidence not confirmed by a reviewer at decision time: " + ", ".join(d["unconfirmed_evidence"]) + "."]
    unresolved = [x for x in review["findings"] if x["status"] == "open"]
    L += ["", "## Unresolved items", ""] + ([f"- **{x['id']}** [{CATEGORY_LABEL[x['category']]}] {x['label']}" for x in unresolved] or ["None."])
    L += ["", "## Findings", ""]
    for x in review["findings"]:
        L += [f"### {x['id']}. {x['label']}", "", f"- Status: {CATEGORY_LABEL[x['category']]} ({x['status']})",
              f"- Decided by: {x['authority'] or 'n/a'}; source: {x['source_title'] or 'n/a'}" + ("" if x["source_confirmed"] else " (source text not yet confirmed)"),
              f"- {x['explanation']}"]
        for e in x["evidence"]:
            L.append(f"- Evidence, {e['locator']}: \"{e['snippet']}\"")
        if x["note"]:
            L.append(f"- Reviewer note ({x['resolved_by']}, {x['resolved_at']}): {x['note']}")
        L.append("")
    L += ["## History", "", "| When | Who | Action | Note |", "| --- | --- | --- | --- |"]
    L += [f"| {h['at']} | {h['actor']} | {h['action']} | {h['note'].replace('|', '/')} |" for h in review["history"]]
    return "\n".join(L) + "\n"
