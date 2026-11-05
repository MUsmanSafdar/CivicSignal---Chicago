"""PAS readiness requirement catalogue. Pure data, no Streamlit.

Each requirement records WHERE it comes from and whether that source has been confirmed against the official text:
  source_type: federal_regulation | program_guidance | state_procedure | recommendation
  confirmed:   True only when the cited text was read while building this module; everything else says "needs_confirmation"
               and the UI shows it as such. Nothing here is a FEMA determination, and the catalogue is configurable per tenant.
  authority:   who decides the item: "state" (administrative check) or "federal" (FEMA keeps the determination).
  time_sensitive: the fact can change after it is checked (for example NFIP standing, plan expiry), so a "Verified" status ages and the
               review center warns when it is older than the configured number of days. It never blocks; the reviewer decides.

The catalogue is a starting set for an INTERNAL administrative checklist. It is not a complete statement of HMA
eligibility and must be checked against the Program and Policy Guide version that governs the specific disaster or
funding opportunity (recorded on each case as ``guidance_version``).
"""
from __future__ import annotations

from typing import Any

CATALOGUE_VERSION = "2026.1-mvp"

SOURCES: dict[str, dict[str, Any]] = {
    "cfr_206_437": {"title": "44 CFR 206.437 State administrative plan (HMGP)", "source_type": "federal_regulation", "confirmed": True},
    "pas_faq": {"title": "FEMA, Program Administration by States (PAS) FAQs (2015)", "source_type": "program_guidance", "confirmed": True},
    "hma_guide": {"title": "FEMA Hazard Mitigation Assistance Program and Policy Guide (version in force for the funding opportunity)",
                  "source_type": "program_guidance", "confirmed": False},
    "cfr_206_434": {"title": "44 CFR 206.434 Eligibility (HMGP)", "source_type": "federal_regulation", "confirmed": False},
    "cfr_77": {"title": "44 CFR Part 77 Flood Mitigation Assistance", "source_type": "federal_regulation", "confirmed": False},
    "state_sop": {"title": "State administrative plan / agency intake procedure (configure per agency)", "source_type": "state_procedure",
                  "confirmed": False},
    "civicsignal": {"title": "CivicSignal recommendation (not a requirement)", "source_type": "recommendation", "confirmed": False},
}

# id, label, programs (None = all), required, authority, source key, what counts as evidence
REQUIREMENTS: list[dict[str, Any]] = [
    {"id": "app_form", "label": "Application form complete and signed by an authorized representative", "programs": None, "required": True,
     "authority": "state", "source": "state_sop", "evidence_hint": "Submitted form or upload reference"},
    {"id": "subapplicant_eligible", "label": "Subapplicant is an eligible entity type", "programs": None, "required": True,
     "authority": "state", "source": "hma_guide", "evidence_hint": "Entity documentation"},
    {"id": "hmp_current", "label": "Applicable FEMA-approved hazard mitigation plan, current at the time of the review", "programs": ["HMGP", "FMA"],
     "required": True, "authority": "federal", "source": "cfr_206_434", "time_sensitive": True,
     "evidence_hint": "Plan approval letter and expiration date. Plan approval itself rests with FEMA unless delegated"},
    {"id": "nfip_good_standing", "label": "NFIP participation and good standing for the community (flood projects)", "programs": ["FMA"],
     "required": True, "authority": "state", "source": "cfr_77", "time_sensitive": True, "evidence_hint": "NFIP status record and the date it was checked"},
    {"id": "scope_of_work", "label": "Scope of work describes the activity, location and hazard addressed", "programs": None, "required": True,
     "authority": "state", "source": "hma_guide", "evidence_hint": "Scope narrative, maps"},
    {"id": "cost_estimate", "label": "Detailed cost estimate with basis", "programs": None, "required": True, "authority": "state",
     "source": "hma_guide", "evidence_hint": "Itemized estimate"},
    {"id": "bca", "label": "Cost-effectiveness shown (benefit-cost analysis or an accepted alternative)", "programs": None, "required": True,
     "authority": "state", "source": "hma_guide",
     "evidence_hint": "BCA output file and inputs. Whether the state may review it depends on the delegation in the operational agreement"},
    {"id": "ehp", "label": "Environmental and historic preservation information provided", "programs": None, "required": True,
     "authority": "federal", "source": "pas_faq",
     "evidence_hint": "EHP screening form and attachments. FEMA conducts EHP review even under PAS (per FEMA PAS FAQs)"},
    {"id": "nonfederal_share", "label": "Non-federal share source identified", "programs": None, "required": True, "authority": "state",
     "source": "hma_guide", "evidence_hint": "Commitment letter or budget line"},
    {"id": "maintenance_plan", "label": "Long-term maintenance responsibility identified", "programs": None, "required": False, "authority": "state",
     "source": "civicsignal", "evidence_hint": "Maintenance commitment"},
    {"id": "community_support", "label": "Evidence of community support or outreach", "programs": None, "required": False, "authority": "state",
     "source": "civicsignal", "evidence_hint": "Letters, meeting records"},
]

# State administrative plan elements (44 CFR 206.437, confirmed). Used for the delegation/configuration screen.
STATE_PLAN_ELEMENTS = [
    "Lead agency named", "State Hazard Mitigation Officer named", "Staffing estimate and sources", "Outreach to potential subrecipients",
    "Applicant information on process, eligibility and dates", "Eligibility determination procedure", "Environmental and floodplain review procedures",
    "Project priority criteria", "Advance and reimbursement payment handling", "Project monitoring and evaluation",
    "Cost overrun review", "Appeals process", "Technical assistance to subrecipients", "Compliance with 2 CFR 200 and 44 CFR 206",
    "Quarterly progress reports to the Regional Administrator", "Management cost pass-through basis",
]

# Functions a state may accept under PAS, per the FEMA PAS FAQs (confirmed). FEMA keeps EHP review regardless.
PAS_FUNCTIONS = {
    "application_review": "Review project applications",
    "bca_review": "Review benefit-cost analyses",
    "grant_management": "Manage grants",
    "financial_management": "Manage finances",
    "planning": "Mitigation planning (including plan approval)",
}


def requirements_for(program: str, catalogue: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Requirements that apply to a funding program, each enriched with its source record."""
    out = []
    for r in catalogue or REQUIREMENTS:
        if r["programs"] is None or program in r["programs"]:
            src = SOURCES[r["source"]]
            out.append({"time_sensitive": False, **r, "source_title": src["title"], "source_type": src["source_type"],
                        "confirmed": src["confirmed"], "catalogue_version": CATALOGUE_VERSION})
    return out
