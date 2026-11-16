"""Example document reviews for visitors who are not signed in. Pure: no Streamlit, nothing is stored.

The applications below are INVENTED for demonstration (they match the invented CivicSignal sample projects) and
contain deliberate gaps so the review has something to find. They are run through the real ``pas_review`` checks, so
the findings shown are what the tool actually produces for this text. They are held in memory only and are never
written to the review store or the audit trail.
"""
from __future__ import annotations

from typing import Any

import pas_review as pr

ACTOR = "demo (invented example)"
AT = "2026-10-01T15:00:00+00:00"

HMGP_TEXT = """\
DEMONSTRATION DOCUMENT - INVENTED FOR CIVICSIGNAL - NOT A REAL APPLICATION

Hazard Mitigation Grant Program subapplication
Subapplicant: Village of Sample Grove (local government)
Project: Maple Creek flood-prone home acquisition

Application form
The application form is complete and signed by the authorized representative, Village Administrator, on 2026-09-12.

Scope of work
The Village will acquire and demolish six repetitive-loss homes on Maple Creek Lane and return the land to open
space. The activity addresses riverine flooding at this location.

Hazard mitigation plan
The Village is covered by the county multi-jurisdictional hazard mitigation plan, FEMA approved, expiring 2029-06-30.

Cost estimate
Total project cost is $1,850,000 based on appraisals and demolition quotes. The detailed cost estimate is attached.
The budget summary on the cover sheet lists a total project cost of $1,790,000.

Benefit-cost analysis
The benefit-cost analysis is TBD and will be attached before submission.

Non-federal share
The non-federal share of 25 percent will come from the Village capital fund, budget line 410-22.

Community support
Two public meetings were held and owners of all six homes have signed voluntary participation statements.
"""

LOCAL_TEXT = """\
DEMONSTRATION DOCUMENT - INVENTED FOR CIVICSIGNAL - NOT A REAL PROPOSAL

Locally funded project proposal
Department: Sample City Department of Buildings
Project: Senior housing cooling room retrofit

Scope of work
Install a backup-powered cooling room in the common area of a 120-unit senior housing building. The work addresses
extreme heat for residents who cannot leave the building during a heat wave.

Hazard and risk
The building had two heat emergencies in the last five summers. Evidence: building management incident log.

Cost estimate
Estimated cost is $240,000 based on two contractor quotes.

Funding source
City capital budget, resilience line item 2027-R-14.

Schedule
Design in the first quarter, construction in the second quarter, in service before 1 June.

Maintenance
The building owner will maintain the equipment under the existing service contract.
"""


def _one(rid: str, name: str, text: str, program: str, jurisdiction: str, project: str) -> dict[str, Any]:
    raw = text.encode("utf-8")
    facts = pr.validate_upload(name, raw)
    review = pr.new_review(rid, ACTOR, facts, {"program": program, "jurisdiction": jurisdiction, "project": project,
                                                "guidance_version": "Demonstration"}, at=AT)
    pr.analyze(review, pr.extract_units(facts["ext"], raw), ACTOR, at=AT)
    review["demo"] = True
    return review


def demo_store() -> dict[str, Any]:
    """Analyzed example reviews in the same shape as the saved review store."""
    a = _one("DEMO-HMGP", "DEMO_hmgp_subapplication.txt", HMGP_TEXT, "HMGP", "Village of Sample Grove (invented)",
             "Maple Creek home acquisition (invented)")
    reviews = {a["id"]: a}
    if "LOCAL" in pr.PROGRAMS:      # the locally funded track is optional; show its example only where it is installed
        b = _one("DEMO-LOCAL", "DEMO_local_proposal.txt", LOCAL_TEXT, "LOCAL", "Sample City (invented)",
                 "Senior housing cooling room (invented)")
        reviews[b["id"]] = b
    return {"seq": 0, "reviews": reviews}
