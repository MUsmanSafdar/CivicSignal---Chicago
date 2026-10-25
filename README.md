# CivicSignal and the Chicago-Area Hazard Risk Dashboard

Decision support for hazard-mitigation grants. It ranks projects with weights **you** choose, screens them against published FEMA rules (FMA 44 CFR Part 77, HMGP 44 CFR 206.434) with a fail-closed engine, and keeps a hash-chained audit trail. A named official makes every decision. Sample data only unless an administrator confirms verified data.

## Quickstart
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# local sign-in as an admin (development only):
export ALLOWED_EMAILS=you@example.org DEV_USER_EMAIL=you@example.org ROLE_ADMINS=you@example.org
streamlit run app.py
```
Open http://localhost:8501. Data is saved to `civicsignal_data.sqlite3`.

## Workspaces
Illinois SVI website · CivicSignal prioritization · Hazard dashboard · Cooling centers & shelters (English and Spanish).

## Tests and checks (what CI runs)
```bash
pip install -r requirements-dev.txt
ruff check .
mypy
pytest
pip-audit -r requirements.txt     # dependency scan
```

## Docs
`AZURE_DEPLOYMENT_NOTES.md` (deploy, RBAC, retention) · `TERMS.md` · `PRIVACY.md` · `DISCLAIMER.md` · `DATA_SOURCES.md` · `ACCESSIBILITY.md` · `PHASE0_NOTES.md` · `TRACEABILITY.md` · `CHANGELOG.md`

## Not legal advice
Eligibility output is an administrative screening aid. See `DISCLAIMER.md`.
