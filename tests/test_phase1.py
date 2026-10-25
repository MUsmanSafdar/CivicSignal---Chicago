"""Phase 1 tests: audit store, identity, scope, HMGP rules, decision packet, funding watch, palette, i18n."""
import base64
import json
import re

import pandas as pd
import pytest

import audit_store as a
import chatbot_engine as chat_engine
import civicsignal as cs
import config
import decision_packet as dp
import funding_watch as fw
import i18n
import identity as ident
import palette

TODAY = "2026-10-07"
W = {k: d for k, _, d, _ in cs.CRITERIA}
ALL = {r["id"]: 1 for r in cs.RULES}


# ------------------------------------------------------------------ 1.1 audit store
@pytest.fixture()
def backend(tmp_path):
    return a.SQLiteBackend(str(tmp_path / "t.db"))


def test_chain_persists_across_reload(tmp_path):
    path = str(tmp_path / "x.db")
    b1 = a.SQLiteBackend(path)
    a.append_event(b1, "t", "user:a@x", "rule.published", "rule", "r1", {"k": 1})
    a.append_event(b1, "t", "user:a@x", "project.decision.held", "project", "p1", {"note": "n"})
    b2 = a.SQLiteBackend(path)  # a "reload": new object, same file
    assert [e["n"] for e in a.list_events(b2, "t")] == [1, 2] or len(a.list_events(b2, "t")) == 2
    assert a.verify_chain(b2, "t")[0] is True


def test_tenants_are_separate(backend):
    a.append_event(backend, "t1", "u", "x", "r", "1", {})
    assert a.list_events(backend, "t2") == []
    assert a.verify_chain(backend, "t2")[0] is True


def test_tampering_with_stored_row_is_detected(tmp_path):
    import sqlite3
    path = str(tmp_path / "x.db")
    b = a.SQLiteBackend(path)
    a.append_event(b, "t", "u", "x", "r", "1", {"v": 1})
    a.append_event(b, "t", "u", "y", "r", "1", {"v": 2})
    with sqlite3.connect(path) as db:
        body = json.loads(db.execute("SELECT body FROM events WHERE n = 1").fetchone()[0])
        body["detail"]["v"] = 999
        db.execute("UPDATE events SET body = ? WHERE n = 1", (json.dumps(body),))
    ok, msg = a.verify_chain(b, "t")
    assert ok is False and msg


def test_state_roundtrip_and_resume(backend):
    S = a.load_workspace(backend, "t")
    cs.publish_rules(S, [r["id"] for r in cs.RULES], "rev@x.org")
    ok, _ = cs.decide(S, "p3", "approved", "safe room fits", "off@x.org", W, 4.0)
    assert ok
    written = a.sync_state(backend, "t", S)
    assert written == len(S["audit"])
    S2 = a.load_workspace(backend, "t")  # new session
    assert S2["decisions"]["p3"]["action"] == "approved"
    assert set(S2["published"]) == {r["id"] for r in cs.RULES}
    assert S2["audit"] == S["audit"]
    assert cs.verify_chain(S2["audit"])[0]


def test_sync_is_incremental(backend):
    S = a.load_workspace(backend, "t")
    cs.publish_rules(S, ["fma.nfip_participation"], "r@x")
    first = a.sync_state(backend, "t", S)
    assert a.sync_state(backend, "t", S) == 0
    cs.publish_rules(S, ["fma.hazard_mitigation_plan"], "r@x")
    assert a.sync_state(backend, "t", S) >= 1 and first >= 1


def test_tamper_demo_is_never_persisted(backend):
    S = a.load_workspace(backend, "t")
    cs.publish_rules(S, ["fma.nfip_participation"], "r@x")
    a.sync_state(backend, "t", S)
    cs.tamper(S)
    assert cs.verify_chain(S["audit"])[0] is False
    cs.publish_rules(S, ["fma.hazard_mitigation_plan"], "r@x")
    a.sync_state(backend, "t", S)
    assert a.verify_chain(backend, "t")[0] is True  # stored record untouched by the demo


def test_sync_refuses_entry_that_does_not_extend_stored_chain(backend):
    S = a.load_workspace(backend, "t")
    cs.publish_rules(S, ["fma.nfip_participation"], "r@x")
    a.sync_state(backend, "t", S)
    cs.append_event(S["audit"], "u", "x", "r", "1", {})
    S["audit"][-1]["prev"] = "f" * 64
    with pytest.raises(ValueError):
        a.sync_state(backend, "t", S)


def test_settings_and_opportunities(backend):
    assert backend.get_setting("t", "verified_data", False) is False
    backend.set_setting("t", "verified_data", True)
    assert backend.get_setting("t", "verified_data") is True
    backend.upsert_opportunity("t", {"id": "1", "title": "A"})
    backend.upsert_opportunity("t", {"id": "1", "title": "B"})
    assert [o["title"] for o in backend.list_opportunities("t")] == ["B"]


class _FakeTable:
    def __init__(self):
        self.rows = {}

    def create_entity(self, e):
        k = (e["PartitionKey"], e["RowKey"])
        if k in self.rows:
            raise KeyError("exists")
        self.rows[k] = dict(e)

    def upsert_entity(self, e):
        self.rows[(e["PartitionKey"], e["RowKey"])] = dict(e)

    def get_entity(self, partition_key, row_key):
        return self.rows[(partition_key, row_key)]

    def query_entities(self, flt):
        pk = re.search(r"PartitionKey eq '(.*)'", flt).group(1).replace("''", "'")
        return [r for (p, _), r in self.rows.items() if p == pk]


class _FakeService:
    def __init__(self):
        self.tables = {}

    def create_table_if_not_exists(self, name):
        return self.tables.setdefault(name, _FakeTable())


def test_azure_backend_with_fake_client():
    b = a.AzureTableBackend(service=_FakeService())
    a.append_event(b, "t", "user:a@x", "x", "r", "1", {"v": 1})
    a.append_event(b, "t", "user:a@x", "y", "r", "1", {"v": 2})
    assert a.verify_chain(b, "t")[0] and len(a.list_events(b, "t")) == 2
    S = a.load_workspace(b, "t")
    assert len(S["audit"]) == 2
    b.set_setting("t", "k", {"a": 1})
    assert b.get_setting("t", "k") == {"a": 1} and b.get_setting("t", "nope", 5) == 5
    a.sync_state(b, "t", S)
    assert b.load_state("t")["published"] == {}


def test_get_backend_selects_by_env(tmp_path):
    assert isinstance(a.get_backend({"AUDIT_DB_PATH": str(tmp_path / "z.db")}), a.SQLiteBackend)


# ------------------------------------------------------------------ 1.2 identity
def _principal(claims):
    return base64.b64encode(json.dumps({"auth_typ": "aad", "claims": claims}).encode()).decode()


EASY = {"WEBSITE_AUTH_ENABLED": "True"}


def test_easy_auth_headers_parsed():
    h = {"X-Ms-Client-Principal-Name": "Pat@City.gov", "X-Ms-Client-Principal-Idp": "aad",
         "X-Ms-Client-Principal": _principal([{"typ": "roles", "val": "official"}, {"typ": "name", "val": "Pat P"}])}
    me = ident.parse_easy_auth(h, EASY)
    assert me.email == "Pat@City.gov" and me.name == "Pat P" and me.idp == "aad"
    assert me.roles == {"viewer", "official"} and me.actor == "user:Pat@City.gov"


def test_header_case_insensitive_and_claim_email_fallback():
    h = {"x-ms-client-principal": _principal([{"typ": "preferred_username", "val": "a@b.gov"}])}
    assert ident.parse_easy_auth(h, EASY).email == "a@b.gov"


def test_missing_headers_means_anonymous():
    assert ident.parse_easy_auth({}, EASY) is None
    assert ident.resolve_identity({}, {}) is None


def test_headers_ignored_when_not_behind_easy_auth():
    h = {"X-Ms-Client-Principal-Name": "evil@x.org"}
    assert ident.parse_easy_auth(h, {}) is None  # forged header must not grant identity
    assert ident.parse_easy_auth(h, {"TRUST_AUTH_HEADERS": "1"}).email == "evil@x.org"


def test_malformed_principal_blob_is_safe():
    h = {"X-Ms-Client-Principal-Name": "a@b.gov", "X-Ms-Client-Principal": "%%%not-base64%%%"}
    assert ident.parse_easy_auth(h, EASY).roles == {"viewer"}


def test_token_cannot_invent_unknown_roles():
    h = {"X-Ms-Client-Principal-Name": "a@b.gov", "X-Ms-Client-Principal": _principal([{"typ": "roles", "val": "root"}])}
    assert ident.parse_easy_auth(h, EASY).roles == {"viewer"}


def test_env_role_lists():
    env = {**EASY, "ROLE_ADMINS": "boss@x.gov", "ROLE_REVIEWERS": "r@x.gov, boss@x.gov"}
    assert "admin" in ident.parse_easy_auth({"X-Ms-Client-Principal-Name": "BOSS@x.gov"}, env).roles
    assert ident.parse_easy_auth({"X-Ms-Client-Principal-Name": "r@x.gov"}, env).roles == {"viewer", "reviewer"}


def test_dev_fallback_requires_allowlist():
    assert ident.dev_identity({"DEV_USER_EMAIL": "me@x.org"}) is None
    assert ident.dev_identity({"ALLOWED_EMAILS": "other@x.org", "DEV_USER_EMAIL": "me@x.org"}) is None
    me = ident.dev_identity({"ALLOWED_EMAILS": "me@x.org", "DEV_USER_EMAIL": "ME@x.org", "ROLE_ADMINS": "me@x.org"})
    assert me.source == "dev" and "admin" in me.roles


def test_easy_auth_wins_over_dev():
    env = {**EASY, "ALLOWED_EMAILS": "dev@x.org", "DEV_USER_EMAIL": "dev@x.org"}
    assert ident.resolve_identity({"X-Ms-Client-Principal-Name": "real@x.gov"}, env).email == "real@x.gov"


@pytest.mark.parametrize("role,perm,expected", [
    ("viewer", "publish_rules", False), ("viewer", "decide", False), ("viewer", "view", True),
    ("reviewer", "publish_rules", True), ("reviewer", "decide", False), ("reviewer", "upload_data", False),
    ("official", "decide", True), ("official", "publish_rules", False), ("official", "toggle_scope", False),
    ("admin", "publish_rules", True), ("admin", "decide", True), ("admin", "upload_data", True),
    ("admin", "toggle_scope", True), ("admin", "run_tamper_demo", True),
])
def test_role_gates(role, perm, expected):
    me = ident.Identity("a@b", "A", "aad", frozenset({"viewer", role}))
    assert ident.can(me, perm) is expected


def test_anonymous_and_unknown_permission():
    assert ident.can(None, "view") and not ident.can(None, "decide")
    assert not ident.can(ident.Identity("a@b", "A", "x", frozenset({"admin"})), "launch_missiles")
    with pytest.raises(PermissionError):
        ident.require(None, "decide")


# ------------------------------------------------------------------ 1.3 scope
def test_allowed_counties_default_all_and_custom():
    assert config.allowed_counties({}) == list(config.DEFAULT_COUNTIES)  # unset: behaviour unchanged
    assert config.allowed_counties({"ALLOWED_COUNTIES": "all"}) is None
    assert config.allowed_counties({"ALLOWED_COUNTIES": " Cook , Kane,"}) == ["Cook", "Kane"]
    assert config.allowed_counties({"ALLOWED_COUNTIES": " , "}) == list(config.DEFAULT_COUNTIES)


def test_scope_frame():
    df = pd.DataFrame({"county": ["Cook", "Sangamon"], "v": [1, 2]})
    assert list(config.scope_frame(df, ["Cook"])["county"]) == ["Cook"]
    assert len(config.scope_frame(df, None)) == 2
    assert len(config.scope_frame(pd.DataFrame({"x": [1]}), ["Cook"])) == 1
    assert config.tenant_id({}) == "default" and config.tenant_id({"TENANT_ID": "acme"}) == "acme"


# ------------------------------------------------------------------ 1.5 HMGP
def proj(i):
    return next(p for p in cs.PROJECTS if p["id"] == i)


def test_hmgp_outcomes_all_published():
    got = {p["id"]: cs.evaluate_project(p, ALL, TODAY)["overall"] for p in cs.PROJECTS if p["program"] == "HMGP"}
    assert got == {"p3": "pass", "p4": "review", "p6": "fail", "p7": "review", "p10": "fail"}


def test_hmgp_unpublished_rules_are_review():
    assert cs.evaluate_project(proj("p3"), {}, TODAY)["overall"] == "review"


@pytest.mark.parametrize("ratio,expected", [(None, "review"), (1.0, "pass"), (1.4, "pass"), (0.99, "fail"), ("abc", "review"), ("2", "pass")])
def test_hmgp_cost_effectiveness(ratio, expected):
    p = {**proj("p3"), "bca_ratio": ratio}
    assert cs.eval_hmgp_rule("hmgp.cost_effectiveness", p, TODAY)[0] == expected


@pytest.mark.parametrize("scope,expected", [("mitigation", "pass"), ("study", "fail"), ("planning", "review"), (None, "review"), ("x", "review")])
def test_hmgp_scope(scope, expected):
    assert cs.eval_hmgp_rule("hmgp.project_scope", {**proj("p3"), "scope": scope}, TODAY)[0] == expected


@pytest.mark.parametrize("typ,expected", [("local_government", "pass"), ("state", "pass"), ("tribal_government", "pass"),
                                          ("nonprofit", "review"), ("special_district", "review"), ("territory", "review"),
                                          ("unknown", "review"), (None, "review"), ("mystery", "review")])
def test_hmgp_entity_type_fails_closed(typ, expected):
    p = proj("p3")
    p = {**p, "sponsor": {**p["sponsor"], "type": typ}}
    assert cs.eval_hmgp_rule("hmgp.eligible_entity_type", p, TODAY)[0] == expected


@pytest.mark.parametrize("plan,exp,expected", [("fema_approved", "2028-01-01", "pass"), ("fema_approved", "", "review"),
                                               ("fema_approved", "2020-01-01", "review"), ("expired", "", "review"),
                                               ("not_on_file", "", "review"), ("unknown", "", "review")])
def test_hmgp_plan_missing_is_review_with_waiver_note(plan, exp, expected):
    p = proj("p3")
    p = {**p, "sponsor": {**p["sponsor"], "plan": plan, "expires": exp}}
    out, why = cs.eval_hmgp_rule("hmgp.mitigation_plan", p, TODAY)
    assert out == expected
    if plan in ("expired", "not_on_file"):
        assert "waiver" in why


def test_unknown_rule_id_is_review():
    assert cs.eval_hmgp_rule("hmgp.nope", proj("p3"), TODAY)[0] == "review"


def test_hmgp_rules_cite_206_434():
    assert all("206.434" in r["cite"] for r in cs.rules_for("HMGP")) and len(cs.rules_for("HMGP")) >= 3
    assert all(r["program"] == "FMA" for r in cs.rules_for("FMA"))


def test_ui_has_no_hmgp_dead_end():
    import pathlib
    src = pathlib.Path(__file__).resolve().parent.parent.joinpath("civicsignal_ui.py").read_text(encoding="utf-8")
    assert "no HMGP rules yet" not in src and "have not been written yet" not in src


def test_save_project_facts_changes_outcome_and_audits():
    S = cs.new_state()
    cs.init_outcomes(S)
    cs.publish_rules(S, [r["id"] for r in cs.RULES], "r@x")
    assert cs.evaluate_project(S["projects"][3], S["published"], TODAY)["overall"] == "review"  # p4: no ratio
    ok, _ = cs.save_project_facts(S, "p4", {"bca_ratio": "1.3"}, "r@x")
    assert ok and S["projects"][3]["bca_ratio"] == 1.3
    assert S["audit"][-1]["action"] in ("eligibility.determination.created", "project.facts_updated")
    assert any(e["action"] == "project.facts_updated" for e in S["audit"])
    assert cs.save_project_facts(S, "p4", {"bca_ratio": "abc"}, "r@x")[0] is False
    assert cs.save_project_facts(S, "p4", {"bca_ratio": -1}, "r@x")[0] is False
    assert cs.save_project_facts(S, "p4", {"scope": "bogus"}, "r@x")[0] is False
    assert cs.save_project_facts(S, "p4", {"bca_ratio": 1.3}, "r@x")[0] is False
    assert cs.verify_chain(S["audit"])[0]


# ------------------------------------------------------------------ 1.4 decision packet
def _decided_state():
    S = cs.new_state()
    cs.init_outcomes(S)
    cs.publish_rules(S, [r["id"] for r in cs.RULES], "rev@x.org")
    cs.decide(S, "p3", "approved", "Safe room serves 82 SVI tract | pipe test", "off@x.org", W, 4.0)
    cs.decide(S, "p4", "held", "Needs a BCA ratio", "off@x.org", W, 4.0)
    return S


def test_packet_contents():
    S = _decided_state()
    pk = dp.build_packet(S, W, 4.0, tenant="acme", prepared_by="off@x.org", now="2026-10-25T00:00:00+00:00")
    md = dp.to_markdown(pk)
    for needle in ("Weights and budget", "Hazard risk", "30", "FEMA National Risk Index", "44 CFR 206.434(c)(5)", "44 CFR 77.6(a)(1)",
                   "user:off@x.org", "Safe room serves 82 SVI tract \\| pipe test", "Needs a BCA ratio",
                   S["audit"][-1]["hash"], "VERIFIED", "SAMPLE DATA", "not a legal determination"):
        assert needle in md, needle
    assert len(pk["ranking"]) == len(S["projects"])
    assert all(len(r["breakdown"]) == len(cs.CRITERIA) for r in pk["ranking"])
    assert {d["action"] for d in pk["decisions"]} == {"approved", "held"}


def test_packet_reports_broken_chain():
    S = _decided_state()
    cs.tamper(S)
    md = dp.to_markdown(dp.build_packet(S, W, 4.0))
    assert "FAILED" in md


def test_packet_zero_weights_and_verified_data():
    S = _decided_state()
    pk = dp.build_packet(S, {k: 0 for k in W}, 4.0, sample_data=False)
    assert "ranking_error" in pk and "SAMPLE DATA" not in dp.to_markdown(pk)


def test_packet_pdf_is_valid():
    pdf = dp.to_pdf(dp.build_packet(_decided_state(), W, 4.0, prepared_by="off@x.org"))
    assert pdf.startswith(b"%PDF-") and len(pdf) > 3000 and b"%%EOF" in pdf[-1024:]
    assert dp.to_pdf(dp.build_packet(cs.new_state(), {k: 0 for k in W}, 1.0)).startswith(b"%PDF-")


# ------------------------------------------------------------------ 1.6 funding watch
def _fetch(kw):
    return {"data": {"oppHits": [{"id": 111, "title": f"FMA {kw}", "agencyCode": "DHS", "closeDate": "09/01/2026", "oppStatus": "posted"},
                                {"title": "no id"}]}}


def test_parse_hits_tolerates_garbage():
    assert fw.parse_hits({}) == [] and fw.parse_hits({"data": {"oppHits": None}}) == [] and fw.parse_hits({"data": []}) == []
    assert fw.parse_hits(_fetch("x"))[0]["close_date"] == "09/01/2026"


def test_refresh_caches_and_keeps_first_seen(backend):
    r1 = fw.refresh(backend, "t", _fetch, now="2026-10-01T00:00:00+00:00")
    assert r1["new"] == 1 and not r1["errors"]
    fw.refresh(backend, "t", _fetch, now="2026-10-05T00:00:00+00:00")
    rec = fw.list_cached(backend, "t")[0]
    assert rec["first_seen"].startswith("2026-10-01") and rec["last_checked"].startswith("2026-10-05")
    assert fw.last_checked(backend, "t").startswith("2026-10-05")


def test_staleness_banner_after_seven_days(backend):
    assert fw.staleness(backend, "t")[0] is True  # never checked
    fw.refresh(backend, "t", _fetch, now="2026-10-01T00:00:00+00:00")
    assert fw.staleness(backend, "t", now="2026-10-08T00:00:00+00:00")[0] is False
    stale, msg = fw.staleness(backend, "t", now="2026-10-09T00:00:00+00:00")
    assert stale and "Last checked 2026-10-01" in msg
    assert fw.staleness(backend, "t", now="2026-10-02T00:00:00+00:00")[1].startswith("Last checked:")


def test_failed_refresh_keeps_old_cache_and_timestamp(backend):
    fw.refresh(backend, "t", _fetch, now="2026-10-01T00:00:00+00:00")

    def boom(kw):
        raise OSError("offline")
    res = fw.refresh(backend, "t", boom, now="2026-10-20T00:00:00+00:00")
    assert res["errors"] and res["seen"] == 0
    assert fw.last_checked(backend, "t").startswith("2026-10-01") and len(fw.list_cached(backend, "t")) == 1
    assert backend.get_setting("t", fw.SETTING_LAST_ERROR)


def test_offline_snapshot_is_flagged():
    snap = fw.offline_snapshot()
    assert snap and all(o["snapshot"] for o in snap) and any(o["relevant"] for o in snap)


# ------------------------------------------------------------------ 1.7 accessibility
def test_text_contrast_meets_aa():
    for fg, bg in palette.PILL_PAIRS.values():
        assert palette.contrast_ratio(fg, bg) >= 4.5, (fg, bg)
    for level, bg in palette.RISK_COLORS.items():
        assert palette.contrast_ratio(palette.level_text_color(level), bg) >= 4.5, level
    for fg in ("#515154", "#0066cc", "#1d1d1f"):
        assert palette.contrast_ratio(fg, "#dcebf8") >= 4.5, fg  # on the darkest part of the page gradient


def test_contrast_math():
    assert round(palette.contrast_ratio("#000000", "#ffffff"), 1) == 21.0
    assert palette.contrast_ratio("#777777", "#777777") == 1.0


@pytest.mark.parametrize("kind", ["protanopia", "deuteranopia", "tritanopia"])
def test_risk_levels_stay_distinct_under_cvd(kind):
    cols = list(palette.RISK_COLORS.values())
    for x, y in zip(cols, cols[1:]):
        assert palette.cvd_distance(x, y, kind) > 60, (kind, x, y)


def test_old_red_green_pair_was_the_problem():
    assert palette.cvd_distance("#2e9e5b", "#c62828", "deuteranopia") < palette.cvd_distance(palette.LOW, palette.HIGH, "deuteranopia")


def test_app_uses_safe_palette_and_text_alternative():
    import pathlib
    src = pathlib.Path(__file__).resolve().parent.parent.joinpath("app.py").read_text(encoding="utf-8")
    assert "#2e9e5b" not in src and "#c62828" not in src and "ui.risk_table" in src and 'text_auto=".1f"' in src


# ------------------------------------------------------------------ 1.8 language access
def test_locales_have_identical_keys():
    assert i18n.missing_keys("es") == set()
    assert set(i18n.load_locale("es")) == set(i18n.load_locale("en"))
    en, es = i18n.load_locale("en"), i18n.load_locale("es")
    assert sum(1 for k in en if en[k] == es[k]) < 8  # nearly everything is actually translated


def test_placeholders_match_between_locales():
    pat = re.compile(r"\{(\w+)\}")
    for k, v in i18n.load_locale("en").items():
        e = "\n".join(v) if isinstance(v, list) else v
        s = i18n.load_locale("es")[k]
        s = "\n".join(s) if isinstance(s, list) else s
        assert set(pat.findall(e)) == set(pat.findall(s)), k


def test_t_fallbacks():
    assert i18n.t("no.such.key", "es") == "no.such.key"
    assert i18n.t("ui.language", "fr") == "Language"
    assert i18n.t("ui.language", "es-MX") == "Idioma"
    assert i18n.normalize_lang(None) == "en" and i18n.normalize_lang("ES_mx") == "es"


@pytest.fixture()
def frames():
    risk = pd.DataFrame({"county": ["Sangamon", "Sangamon"], "region": ["Central"] * 2, "hazard": ["Flood", "Tornado"],
                         "risk_score": [3.1, 2.0], "risk_level": ["High", "Medium"], "svi_score": [0.62, 0.62]})
    cap = pd.DataFrame({"county": ["Sangamon"], "hazard": ["Flood"], "mitigation_effort": ["Levee"], "status": ["In Progress"],
                        "people_affected": [1200], "budget_usd": [1000000.0], "amount_spent_usd": [250000.0]})
    comp = pd.DataFrame({"county": ["Sangamon"], "hazard": ["Flood"], "category": ["Drainage"], "status": ["Open"],
                         "priority": ["Critical"], "description": ["x"], "date_filed": ["2026-09-01"]})
    return risk, cap, comp


def test_spanish_chat_responses(frames):
    r, c, k = frames
    es = chat_engine.chat("nivel de riesgo de Sangamon County", r, c, k, lang="es")
    assert "Perfil de riesgo" in es and "Alto" in es and "Sangamon" in es and "queja" in es
    en = chat_engine.chat("risk level for Sangamon County", r, c, k)
    assert "Hazard Risk Profile" in en and "Perfil" not in en
    assert "Resumen de mitigación" in chat_engine.chat("mitigación", r, c, k, lang="es")
    assert "Presupuesto" in chat_engine.chat("mitigación en Sangamon County", r, c, k, lang="es")


@pytest.mark.parametrize("text,intent", [("emergencia", "emergency"), ("¡Estoy atrapado por la inundación!", "emergency"),
                                         ("emergencia centro de enfriamiento", "emergency"), ("hola", "greeting"),
                                         ("gracias", "thanks"), ("centros de enfriamiento 60639", "cooling"),
                                         ("refugios en Cook County", "shelter"), ("nivel de riesgo", "risk"),
                                         ("quejas abiertas", "complaint"), ("¿cómo debo prepararme?", "prepare"),
                                         ("emergency cooling center needed", "emergency")])
def test_spanish_and_english_intents(text, intent):
    assert chat_engine.detect_intent(text) == intent


def test_every_intent_renders_in_both_languages(frames):
    r, c, k = frames
    for lang in ("en", "es"):
        for intent in ("greeting", "thanks", "emergency", "shelter", "aid", "contact", "risk", "mitigation", "complaint", "prepare", "general"):
            for county in (None, "Sangamon", "Nowhere"):
                out = chat_engine.build_response(intent, county, r, c, k, "", lang)
                assert out
                assert not re.search(r"\{[a-z_0-9]+\}", out), (lang, intent, county, out[:120])


def test_shelter_no_records_reply_names_the_county(frames):
    """Regression: the old reply printed a literal '{county}'."""
    r, c, k = frames
    out = chat_engine.build_response("shelter", "Nowhere", r, c, k, "", "en")
    assert "{county}" not in out


# ------------------------------------------------------------------ cooling-centers page: need index and one-hue ramp
def test_need_index_blend_and_clamp():
    import heat_need as hn
    assert hn.need_index(5, 1) == 100.0 and hn.need_index(0, 0) == 0.0
    assert hn.need_index(2.5, 0.5) == 50.0
    assert hn.need_index(9, 3) == 100.0 and hn.need_index(-1, -1) == 0.0


def test_need_table_ranks_darkest_first_and_flags_gaps():
    import heat_need as hn
    risk = pd.DataFrame({"county": ["A", "B", "C", "A"], "hazard": ["Extreme Heat", "Extreme Heat", "Extreme Heat", "Flood"],
                         "risk_score": [4.0, 1.0, 3.0, 5.0], "svi_score": [0.9, 0.1, 0.6, 0.9]})
    centers = pd.DataFrame({"county": ["B", "B"]})
    t = hn.need_table(risk, centers)
    assert list(t["county"]) == ["A", "C", "B"]  # Flood rows ignored; highest need first
    assert list(t["gap"]) == [True, True, False] and list(t["centers"]) == [0, 0, 2]


def test_need_table_degrades_gracefully():
    import heat_need as hn
    assert hn.need_table(pd.DataFrame(), pd.DataFrame()).empty
    assert hn.need_table(pd.DataFrame({"county": ["A"]}), pd.DataFrame()).empty
    assert hn.need_table(pd.DataFrame({"county": ["A"], "hazard": ["Flood"], "risk_score": [1], "svi_score": [0.1]}), None).empty


def test_ramp_is_one_hue_light_to_dark():
    assert palette.ramp_color(0) == palette.NEED_RAMP[0] and palette.ramp_color(1) == palette.NEED_RAMP[-1]
    lums = [palette.relative_luminance(palette.ramp_color(f / 10)) for f in range(11)]
    assert all(x > y for x, y in zip(lums, lums[1:]))  # strictly darker as need rises
    assert palette.ramp_color(-5) == palette.NEED_RAMP[0] and palette.ramp_color(7) == palette.NEED_RAMP[-1]
    assert palette.contrast_ratio("#1d1d1f", palette.NEED_RAMP[2]) >= 4.5  # county labels stay readable on mid shades
