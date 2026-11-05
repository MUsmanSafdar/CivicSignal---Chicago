# Action Portfolio

Reads the action tables of a hazard mitigation plan or jurisdictional annex and summarises what the plan itself says.

## What is read from the document (checkable)
Action number and title, plan priority, cost rating, status code, year initiated, and whether HMGP, BRIC, FMA, HMA or FEMA appears in the potential
funding source row. The summary counts these and lists action numbers missing from the range found.

## Fit score (a first pass, not a finding)
`fit = place-specific (0-2) + relevance to vulnerable residents (0-2) + 1 if a FEMA grant source is listed`; Strong 4-5, Moderate 2-3, Weak 0-1.
The first two parts are keyword rules (term lists at the top of `action_plan.py`). On the Cook County Chicago annex (52 action entries found in a
94-page PDF) the facts read from the document matched a manual read of the PDF (24 High, 24 Medium, 4 Low; 31 actions listing a FEMA grant source).
The keyword tiers agreed with a hand scoring of the same actions for 33 of 50 actions, so the tiers need a person to review them. Reviewers can
correct the two judgement parts per action; corrections last for the session only.

## Limits
- Written for the Cook County MJ-HMP annex layout. Other plan formats may be read partly or not at all; unread fields are counted and shown.
- Scanned (image-only) PDFs have no text and return no actions.
- A listed funding source is what the plan says is possible, not what has been applied for or awarded.
- Completed actions and actions marked for removal are left out of the fit counts.
- Not a FEMA determination and not a recommendation of what to fund.
