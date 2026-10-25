# Phase 0 traceability

| Task | Status | Files | Proving test (tests/test_phase0.py) |
|---|---|---|---|
| 0.1 One router radio, branches stop | Done, with one deliberate deviation (see below) | app.py | test_router_has_exactly_one_radio_and_every_branch_but_dashboard_stops |
| 0.2 Emergency before cooling/shelter | Done | chatbot_engine.py | test_intent_priority |
| 0.3 Hazard taxonomy | Done | hazard_taxonomy.py, app.py, analysis.py | test_normalize_known, test_normalize_unknown_and_missing_fall_back, test_normalize_column_keeps_raw, test_analysis_tables_use_canonical_keys |
| 0.4 County analysis uses capacity rows | Done (also fixed a NameError this move would have caused) | analysis.py, app.py | test_analysis_reads_capacity_columns_filtered_by_county_and_hazard, test_analysis_degrades_without_columns_or_data, test_capacity_frame_is_defined_before_the_county_analysis_uses_it |
| 0.5 Chatbot gets unfiltered frames | Done | app.py, chatbot_engine.py | test_chat_answers_for_county_outside_dashboard_scope, test_chat_survives_empty_frames |
| 0.6 mtime+size cache | Done | chatbot_engine.py | test_reference_tables_reload_when_file_changes |
| 0.7 Weights guard | Done | civicsignal.py, civicsignal_ui.py | test_zero_total_weight_raises_not_silently_ranks_by_cost, test_valid_weights_still_rank |
| 0.8 Performance | Done: GeoJSON cache, PDF on a worker thread with progress and 120 s limit | app.py, pdf_tasks.py | test_run_with_timeout_returns_and_times_out, test_run_with_timeout_propagates_errors, test_geojson_parse_cache_is_keyed_on_file_mtime |
| 0.9 Empty/NaN guards | Done for KPIs, hazard overview, complaints charts, chatbot | safe_stats.py, app.py, chatbot_engine.py | test_empty_and_nan_frames_do_not_raise |

## Deviation to approve
Constraint 0.1 lists three workspace options. The router keeps a fourth, "Illinois SVI website", because you asked for it to be first. Remove it from the list in app.py if you want exactly three.

## Limits
- The PDF worker thread cannot be killed on timeout; it is abandoned and ends when extraction returns.
- Streamlit is not installed in the build environment, so the app itself was not launched. The 42 tests cover the pure modules and static checks on app.py.
- ruff and mypy are clean on all new modules and tests. Existing legacy lines in app.py and the other old modules still have 22 style findings (mostly import placement and one-line statements); these predate Phase 0.

Run: `python -m pytest -q tests`
