# Audit traceability matrix (v1.0.0)

Status: **Done** = implemented and covered by a passing test. **Partial** = implemented, with a limit stated in the last column.
Run all tests: `pytest` (see README). Names below are test functions in `tests/`.

## Phase 0: correctness and safety
| Task | Status | Files | Test proving it | Note |
|---|---|---|---|---|
| 0.1 One router radio, branches stop | Done | app.py | test_phase0::test_router_has_exactly_one_radio_and_every_branch_but_dashboard_stops | A fourth workspace (Illinois SVI website) was added at the user's request; the list differs from the three in the brief |
| 0.2 Emergency intent first | Done | chatbot_engine.py | test_phase0::test_intent_priority; test_phase1::test_spanish_and_english_intents | |
| 0.3 Hazard taxonomy | Done | hazard_taxonomy.py | test_phase0::test_normalize_known, test_normalize_unknown_and_missing_fall_back, test_normalize_column_keeps_raw | |
| 0.4 County risk analysis schema | Done | analysis.py, app.py | test_phase0::test_analysis_reads_capacity_columns_filtered_by_county_and_hazard, test_analysis_degrades_without_columns_or_data | |
| 0.5 Chatbot sees unscoped data | Done | app.py, chatbot_engine.py | test_phase0::test_chat_answers_for_county_outside_dashboard_scope | |
| 0.6 Cache invalidation | Done | chatbot_engine.py | test_phase0::test_reference_tables_reload_when_file_changes | |
| 0.7 Zero-weight guard | Done | civicsignal.py, civicsignal_ui.py | test_phase0::test_zero_total_weight_raises_not_silently_ranks_by_cost | |
| 0.8 GeoJSON cache, PDF timeout | Done | app.py, pdf_tasks.py | test_phase0::test_run_with_timeout_returns_and_times_out, test_geojson_parse_cache_is_keyed_on_file_mtime | Timeout verified with a stand-in task, not a real PDF in a browser |
| 0.9 Empty-frame guards | Done | safe_stats.py, chatbot_engine.py | test_phase0::test_empty_and_nan_frames_do_not_raise, test_chat_survives_empty_frames | |

## Phase 1: market-ready MVP
| Task | Status | Files | Test proving it | Note |
|---|---|---|---|---|
| 1.1 Persistent audit store | Done | audit_store.py, civicsignal_ui.py | test_phase1::test_chain_persists_across_reload, test_state_roundtrip_and_resume, test_azure_backend_with_fake_client, test_ui_smoke::test_official_decision_persists_after_reload | Azure backend tested against a fake client, not a live account. WORM/retention is documented, not enforced by code |
| 1.2 Identity and RBAC | Done | identity.py, civicsignal_ui.py, app.py | test_phase1::test_easy_auth_headers_parsed, test_headers_ignored_when_not_behind_easy_auth, test_role_gates; test_ui_smoke::test_reviewer_cannot_decide | Easy Auth not exercised against real Entra ID here |
| 1.3 Tenant scope | Done | config.py, app.py | test_phase1::test_allowed_counties_default_all_and_custom, test_scope_frame | |
| 1.4 Decision packet | Done | decision_packet.py | test_phase1::test_packet_contents, test_packet_pdf_is_valid, test_packet_reports_broken_chain | PDF is not a tagged PDF |
| 1.5 HMGP rules | Done | civicsignal.py | test_phase1::test_hmgp_outcomes_all_published, test_hmgp_cost_effectiveness, test_hmgp_scope, test_hmgp_plan_missing_is_review_with_waiver_note, test_ui_has_no_hmgp_dead_end | Rules are a screening aid and still need a named reviewer to approve their wording |
| 1.6 Grants.gov feed | Partial | funding_watch.py | test_phase1::test_refresh_caches_and_keeps_first_seen, test_staleness_banner_after_seven_days, test_failed_refresh_keeps_old_cache_and_timestamp | Live API call not testable from the build sandbox; tested with an injected fetcher. Response field names follow the public Search2 format and should be checked on first live run |
| 1.7 Accessibility | Partial | palette.py, app.py, heat_ui.py, ACCESSIBILITY.md | test_phase1::test_text_contrast_meets_aa, test_risk_levels_stay_distinct_under_cvd, test_app_uses_safe_palette_and_text_alternative | No third-party audit or screen-reader run; known limits listed in ACCESSIBILITY.md |
| 1.8 Language access | Partial | i18n.py, locales/, chatbot_engine.py | test_phase1::test_locales_have_identical_keys, test_placeholders_match_between_locales, test_spanish_chat_responses | Spanish needs native-speaker review; internal screens stay English |
| 1.9 Legal and trust pages | Partial | TERMS.md, PRIVACY.md, DISCLAIMER.md, DATA_SOURCES.md, app.py footer | test_phase1::test_ui_has_no_hmgp_dead_end (disclaimer wording); test_phase2::test_required_files_exist | Drafts; counsel must review and fill in contacts. Licence notes should be re-checked at each source |
| 1.10 Docs reconciliation | Done | AZURE_DEPLOYMENT_NOTES.md, README.md, CHANGELOG.md | test_phase2::test_required_files_exist | |

## Phase 2: packaging and QA
| Task | Status | Files | Test proving it | Note |
|---|---|---|---|---|
| 2.1 Missing files | Done | security_utils.py, heat_ui.py, startup.sh, requirements.txt, requirements-dev.txt, .env.example, tests/, .github/workflows/ci.yml, pyproject.toml | test_phase2::test_required_files_exist, test_security_utils_exports_every_name_the_app_imports, test_requirements_are_bounded_and_have_the_new_dependencies, test_ci_workflow_runs_ruff_mypy_pytest, test_startup_command_runs_the_app | Requirements use bounded ranges; generate `requirements.lock` for exact pins (see file header). Workflow not run on GitHub yet |
| 2.2 Security hardening | Done | security_utils.py, rate_limit.py, civicsignal_ui.py, heat_ui.py | test_phase2::test_safe_equals_is_correct_and_constant_time_api, test_no_admin_password_mechanism_remains, test_no_eval_exec_or_shell_in_source, test_ranked_table_escapes_hostile_text, test_limiter_blocks_after_max_then_recovers | No password comparison remains; `safe_equals` is provided for any future one. Per-session limiter only; network-level limits are a deployment step |
| 2.3 Observability | Done | observability.py, app.py, civicsignal_ui.py | test_phase2::test_event_line_is_json_and_drops_free_text, test_app_insights_is_off_without_connection_string, test_app_insights_enabled_when_package_present, test_rule_publication_is_logged_without_free_text, test_decision_is_logged | Not verified against a real Application Insights resource |
| 2.4 Traceability matrix | Done | TRACEABILITY.md | n/a | This file |

## Not verified in the build environment
Streamlit pages in a real browser, the Plotly maps, Azure services (Table Storage, Easy Auth, Application Insights), the Grants.gov live call, and the GitHub Actions run.
