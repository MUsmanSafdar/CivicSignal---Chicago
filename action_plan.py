"""Mitigation action portfolio reader (pure, no Streamlit).

Reads the action tables of a hazard mitigation plan or jurisdictional annex (text from a PDF), and reports
(1) what the plan itself says, and (2) a simple, written-out "fit" score for where vulnerability-based ranking would help.

What it does NOT do: it does not decide which action a jurisdiction should fund, and it is not a FEMA determination.
The fit score is a keyword rule that a person should review; every term list is in this file and can be changed.

Layout assumption: each action starts with a line "Mitigation Action #<n>" and contains labelled rows such as
"Priority and Level of Importance (Low, Medium, High)" and "Project Status & Changes in Priority" with a one-letter code
(N new, I in progress, O ongoing, C completed, R removal requested, X no action/delayed). This is the Cook County MJ-HMP annex
format; other formats may parse partly or not at all, and the result says how many fields it could not read.
"""
from __future__ import annotations

import io
import re
from collections import Counter
from typing import Any

STATUS_LABELS = {"N": "New", "I": "In progress", "O": "Ongoing", "C": "Completed", "R": "Removal requested", "X": "No action / delayed", "": "Not stated"}
GRANT_TERMS = re.compile(r"\bHMGP\b|\bBRIC\b|\bFMA\b|\bHMA\b|Hazard\s+Mitigation\s+Grant|Building\s+Resilient\s+Infrastructure|\bFEMA\b", re.I)
_LEVEL = re.compile(r"\b(Low|Medium|High)\b")
_ACTION = re.compile(r"Mitigation\s+Action\s*#\s*(\d+)\s*[:—–-]?\s*(.*)")

# Fit score parts. Strong terms score 2, weak terms score 1, none 0. Edit these lists to change the rule.
PLACE_STRONG = ("school", "schoolyard", "alley", "park", "neighborhood", "housing", "shoreline", "tree", "canopy", "green space", "basement",
                "homes", "facilit", "tunnel", "intake", "drainage", "retrofit", "ward")
PLACE_WEAK = ("stormwater", "storm water", "flood", "heat", "cooling", "a/c", "air conditioning", "infrastructure")
VULN_STRONG = ("senior", "sensitive population", "vulnerab", "low-income", "low income", "housing authority", "long-term care", "congregate",
               "disadvantaged", "equity", "underserved", "a/c distribution", "heat health", "without indoor")
VULN_WEAK = ("resident", "communit", "public health", "cooling center", "warming center", "homes", "basement", "tree canopy", "heat", "private homes")

FIT_STRONG_AT, FIT_MODERATE_AT = 4, 2


def extract_pdf_text(raw: bytes, max_pages: int = 400) -> dict[str, Any]:
    """Page text from PDF bytes using pdfplumber (imported lazily). Returns text plus page counts."""
    import pdfplumber  # local import: the pure parser below must work without it

    pages: list[str] = []
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        total = len(pdf.pages)
        for i in range(min(total, max_pages)):
            pages.append(pdf.pages[i].extract_text() or "")
    return {"text": "\n".join(pages), "page_count": total, "pages_read": len(pages)}


def _level_after(lines: list[str], label: str) -> str:
    """Low/Medium/High given in the row that starts with ``label``; the '(Low, Medium, High)' legend is ignored."""
    for k, line in enumerate(lines):
        if label.lower() in line.lower():
            for seg in lines[k:k + 4]:
                seg = re.sub(r"\(Low,?(\s*Medium,?)?(\s*High\))?", "", seg)
                seg = re.sub(r"^\s*(Medium,\s*)?High\)\s*$", "", seg)
                m = _LEVEL.search(seg)
                if m:
                    return m.group(1)
            return ""
    return ""


def _has(low: str, terms: tuple[str, ...]) -> bool:
    return any(re.search(r"\b" + re.escape(t), low) for t in terms)  # word start, so "park" does not match "partner"


def _score(text: str, strong: tuple[str, ...], weak: tuple[str, ...]) -> int:
    low = text.lower()
    if _has(low, strong):
        return 2
    return 1 if _has(low, weak) else 0


def fit_tier(score: int) -> str:
    return "Strong" if score >= FIT_STRONG_AT else "Moderate" if score >= FIT_MODERATE_AT else "Weak"


def parse_actions(text: str) -> dict[str, Any]:
    """Split plan text into actions. Returns {"actions": [...], "unread": {field: count}, "duplicates": [numbers]}."""
    lines = [ln.rstrip() for ln in text.splitlines()]
    starts = [i for i, ln in enumerate(lines) if _ACTION.search(ln)]
    starts.append(len(lines))
    actions: dict[int, dict[str, Any]] = {}
    dups: list[int] = []
    for a, b in zip(starts, starts[1:]):
        blk = lines[a:b]
        m = _ACTION.search(blk[0])
        if not m:
            continue
        n = int(m.group(1))
        title, j = m.group(2).strip(), 1
        while j < len(blk) and blk[j].strip() and not blk[j].strip().startswith("Lead"):
            title += " " + blk[j].strip()
            j += 1
        if n in actions:
            dups.append(n)
            continue
        end = next((k for k, ln in enumerate(blk) if "Year Initiated" in ln), min(len(blk), 30))
        head = " ".join(blk[:end])
        funding_region = " ".join(blk[next((k for k, ln in enumerate(blk) if ln.strip().startswith("Lead")), 1):end])
        year = re.search(r"Year Initiated\s+(\d{4})", "\n".join(blk))
        status = ""
        ps = next((k for k, ln in enumerate(blk) if "Project Status" in ln), None)
        if ps is not None:
            same = re.search(r"Project Status[^=]*?\s([NIOCRX])\s*$", blk[ps])  # code can sit on the label's own line
            if same:
                status = same.group(1)
            else:
                for ln in blk[ps + 1:ps + 12]:
                    if re.fullmatch(r"\s*[NIOCRX]\s*", ln):
                        status = ln.strip()
                        break
        d0 = next((k for k, ln in enumerate(blk) if "Action/Implementation Plan" in ln), None)
        d1 = next((k for k, ln in enumerate(blk) if "Actual Completion" in ln), None)
        desc = " ".join(blk[d0:d1]) if d0 is not None and d1 is not None and d1 > d0 else ""  # only the description, not boilerplate rows
        basis = re.sub(r"\s+", " ", f"{title} {desc}")
        place, vuln = _score(basis, PLACE_STRONG, PLACE_WEAK), _score(basis, VULN_STRONG, VULN_WEAK)
        grant = bool(GRANT_TERMS.search(funding_region))
        score = place + vuln + (1 if grant else 0)
        actions[n] = {
            "number": n, "title": re.sub(r"\s+", " ", title)[:240], "priority": _level_after(blk, "Priority and Level"),
            "cost": _level_after(blk, "Cost Analysis"), "status_code": status, "status": STATUS_LABELS.get(status, "Not stated"),
            "year_initiated": year.group(1) if year else "", "grant_source_listed": grant, "place_score": place, "vulnerability_score": vuln,
            "fit_score": score, "fit_tier": fit_tier(score), "counted_in_fit": status not in ("C", "R"),
            "head": head[:200],
        }
    ordered = [actions[k] for k in sorted(actions)]
    unread = {"priority": sum(1 for x in ordered if not x["priority"]), "status": sum(1 for x in ordered if not x["status_code"]),
              "cost": sum(1 for x in ordered if not x["cost"])}
    return {"actions": ordered, "unread": unread, "duplicates": dups}


def apply_overrides(actions: list[dict[str, Any]], overrides: dict[int, dict[str, int]]) -> list[dict[str, Any]]:
    """Return copies of ``actions`` with a reviewer's place/vulnerability scores (0 to 2) applied, and the fit score recomputed.

    The keyword rule is a first pass; a person who knows the jurisdiction replaces it where it is wrong. Values outside 0..2 are ignored.
    """
    out = []
    for a in actions:
        b = dict(a)
        o = overrides.get(a["number"], {})
        for key, field in (("place", "place_score"), ("vulnerability", "vulnerability_score")):
            v = o.get(key)
            if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 2:
                b[field] = v
        b["fit_score"] = b["place_score"] + b["vulnerability_score"] + (1 if b["grant_source_listed"] else 0)
        b["fit_tier"] = fit_tier(b["fit_score"])
        b["reviewed"] = bool(o)
        out.append(b)
    return out


def summarize(actions: list[dict[str, Any]]) -> dict[str, Any]:
    """Facts a reader can check against the document, plus the fit counts."""
    rated = [a for a in actions if a["priority"]]
    pri = Counter(a["priority"] for a in rated)
    top_two = (pri["High"] + pri["Medium"]) / len(rated) if rated else 0.0
    live = [a for a in actions if a["counted_in_fit"]]
    return {
        "actions_read": len(actions),
        "numbers_missing_from_range": sorted(set(range(1, max((a["number"] for a in actions), default=0) + 1)) - {a["number"] for a in actions}),
        "priority_counts": {k: pri.get(k, 0) for k in ("High", "Medium", "Low")},
        "share_high_or_medium": round(top_two, 3),
        "ratings_separate_actions": top_two < 0.8,
        "status_counts": dict(Counter(a["status"] for a in actions)),
        "grant_source_listed": sum(1 for a in actions if a["grant_source_listed"]),
        "fit_counts": dict(Counter(a["fit_tier"] for a in live)),
        "fit_excluded": len(actions) - len(live),
    }


def analyze(text: str) -> dict[str, Any]:
    parsed = parse_actions(text)
    return {**parsed, "summary": summarize(parsed["actions"])}


def to_csv(actions: list[dict[str, Any]]) -> str:
    import csv

    cols = ["number", "title", "status", "priority", "cost", "year_initiated", "grant_source_listed", "place_score", "vulnerability_score", "fit_score",
            "fit_tier"]
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for a in actions:
        w.writerow(a)
    return out.getvalue()
