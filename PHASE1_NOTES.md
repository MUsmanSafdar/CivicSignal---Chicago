# Phase 1 traceability

| Task | Status | Files | Tests |
|---|---|---|---|
| 1.1 Persistent audit store | Done | audit_store.py, civicsignal_ui.py | test_chain_persists_across_reload, test_state_roundtrip_and_resume, test_tamper_demo_is_never_persisted, test_azure_backend_with_fake_client, test_official_decision_persists_after_reload |
| 1.2 Identity and RBAC | Done | identity.py, civicsignal_ui.py, app.py | test_easy_auth_headers_parsed, test_headers_ignored_when_not_behind_easy_auth, test_role_gates, test_anonymous_cannot_publish_or_decide, test_reviewer_cannot_decide |
| 1.3 Tenant scope | Done | config.py, app.py | test_allowed_counties_default_all_and_custom, test_scope_frame |
| 1.4 Decision packet | Done | decision_packet.py, civicsignal_ui.py | test_packet_contents, test_packet_pdf_is_valid, test_packet_reports_broken_chain |
| 1.5 HMGP rules | Done | civicsignal.py, civicsignal_ui.py | test_hmgp_outcomes_all_published, test_hmgp_cost_effectiveness, test_hmgp_plan_missing_is_review_with_waiver_note, test_ui_has_no_hmgp_dead_end |
| 1.6 Grants.gov feed | Done (live call untested here; sandbox blocks it) | funding_watch.py, civicsignal_ui.py | test_refresh_caches_and_keeps_first_seen, test_staleness_banner_after_seven_days, test_failed_refresh_keeps_old_cache_and_timestamp |
| 1.7 Accessibility | Done, partial conformance (see ACCESSIBILITY.md) | palette.py, app.py, heat_ui.py, ACCESSIBILITY.md | test_text_contrast_meets_aa, test_risk_levels_stay_distinct_under_cvd |
| 1.8 Language access | Done; Spanish needs native review | i18n.py, locales/, chatbot_engine.py, heat_ui.py | test_locales_have_identical_keys, test_spanish_chat_responses, test_spanish_and_english_intents |
| 1.9 Legal and trust pages | Drafts; need counsel | TERMS.md, PRIVACY.md, DISCLAIMER.md, DATA_SOURCES.md, app.py footer | (content review) |
| 1.10 Docs | Done | AZURE_DEPLOYMENT_NOTES.md, README.md, CHANGELOG.md | n/a |
| Extra: cooling-centers page | Star markers, one-hue need map | heat_need.py, heat_ui.py, palette.py | test_need_table_*, test_ramp_is_one_hue_light_to_dark |

Not verified here: the Streamlit pages were smoke-tested only through a stubbed `streamlit` (no browser), and the Plotly map was not rendered because plotly is not installable in this sandbox.
