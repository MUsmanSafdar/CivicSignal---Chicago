# Changelog

## v1.0.0 (Phase 0 and Phase 1; Phase 2 packaging follows)

### Added
- Persistent audit store (SQLite for development, Azure Table Storage for production) with per-tenant workspace state.
- Identity and roles (Easy Auth, local-dev fallback); audit actor is the verified identity.
- County scope from `ALLOWED_COUNTIES`, admin-only "Show all uploaded data", and `TENANT_ID`.
- Decision packet export (.md and .pdf).
- HMGP eligibility rules citing 44 CFR 206.434 and project fields `bca_ratio` and `scope`.
- Live Grants.gov funding watch with cache, "Last checked" and a seven-day staleness warning.
- Colour-vision-safe palette, contrast tests, text alternatives, `ACCESSIBILITY.md`.
- English and Spanish public chatbot and captions (`locales/`), plus Spanish intent keywords.
- `TERMS.md`, `PRIVACY.md`, `DISCLAIMER.md`, `DATA_SOURCES.md`, a UI footer and the sample-data banner logic.
- Fourth workspace: Illinois SVI website.

### Changed
- Admin password replaced by roles. `ADMIN_PASSWORD` is no longer read.
- "No HMGP rules yet" dead end removed.
- Static funding list kept only as a labelled offline snapshot.

### Fixed (Phase 0)
- Emergency intent now outranks cooling and shelter; hazard taxonomy; county risk analysis reads capacity rows; chatbot sees unscoped data; cache invalidation on file change; zero-weight guard; GeoJSON caching and PDF timeout; empty-frame guards.
- Shelter "no records" reply printed a literal `{county}`; fixed by the locale template.
- Expander icon text ("_arrow_right") caused by a font override.

### Known limits
See `ACCESSIBILITY.md` and `AZURE_DEPLOYMENT_NOTES.md` section 5.
