# PAS Review Center (internal administrative aid)

Not a FEMA system. Does not approve, award or determine eligibility. Items FEMA decides (for example EHP review, which stays with FEMA under PAS) are labelled federal.

## Run
`pip install -r requirements.txt && streamlit run app.py`, then choose "PAS Review Center". Tests: `python -m pytest` (ruff and mypy per pyproject.toml).
First use: Setup > Load demo records (admin, invented data, flagged DEMO) or import a CSV (project_id, jurisdiction, program, submitted_at; optional hazard, subapplicant, due_at).

## Implemented
State Overview (status counts, average/median review days, overdue items, reviewer workload, stage durations, delay by holder, repeated deficiencies, filters);
Project Review Workspace (configurable checklist with statuses, evidence rule, requests/RFIs/corrections, comments, assignment, stage transitions with guards, decision record, federal referral and outcome);
Jurisdiction Overview; county-level map; PDF/Markdown packets; CSV import with validation; delegation scope (PAS functions) in Setup; every write is an event on the existing hash chain.

## Re-confirmation warning (time-sensitive items)
NFIP standing and plan currency can change after they are checked. The checklist shows when each was last verified, warns after a configurable number of days
(placeholder 90, set in Setup from the guidance in force) and offers "Re-confirm now". A note edit does not count as a re-check. The warning never blocks a
transition or decision; any stale items are written into the decision record and the packet. Which dates the guidance actually requires is NOT confirmed.

## Rules the code enforces
Verified needs evidence; Not applicable needs a reason; no technical review with Missing required items; state decision needs a ready checklist; a state recommendation to approve is blocked unless application review is recorded as delegated and no item awaits a federal determination; one open case per project and program; closed is final; failed actions write no audit event.

## Sources
Confirmed by reading: 44 CFR 206.437 (state administrative plan contents), FEMA PAS FAQs (functions a state may accept; FEMA keeps EHP review; operational agreement after each declaration).
NOT confirmed (eCFR and the 2025 HMA Guide could not be fetched): per-item requirements citing the HMA Guide, 44 CFR 206.434 and Part 77. They are marked "needs confirmation" in the UI and packets. Check them against the guide version governing your funding opportunity and record it in Setup.

## Limits / not built
No real authentication of its own (uses the app's Easy Auth/RBAC; local dev identity is labelled demo). No document file storage (evidence is a reference string). No project-level coordinates (map is county level). Funding-opportunity matching is not built; eligibility is never inferred from scores or location. Email notifications and deadline reminders are not built. Azure Table path reuses the existing settings API but was not run here.
