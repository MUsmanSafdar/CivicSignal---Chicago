"""Phase 2 tests: rate limiting, observability, security hardening, packaging files."""
import ast
import json
import logging
import pathlib
import re
import sys
import types
from unittest.mock import MagicMock

import pytest

import audit_store
import identity as ident
import observability as obs
import rate_limit as rl

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY_FILES = sorted(p for p in ROOT.glob("*.py"))


# ------------------------------------------------------------------ rate limit
class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_limiter_blocks_after_max_then_recovers():
    clock = _Clock()
    lim = rl.SlidingWindowLimiter(max_events=3, window_s=60, clock=clock)
    assert [lim.allow() for _ in range(4)] == [True, True, True, False]
    assert lim.retry_after() == 60
    clock.t = 30
    assert lim.allow() is False and round(lim.retry_after()) == 30
    clock.t = 60
    assert lim.allow() is True


def test_blocked_calls_are_not_recorded():
    clock = _Clock()
    lim = rl.SlidingWindowLimiter(max_events=1, window_s=10, clock=clock)
    assert lim.allow()
    for _ in range(50):
        assert not lim.allow()
    clock.t = 10
    assert lim.allow()  # hammering while blocked did not extend the block


def test_limiter_rejects_bad_config():
    with pytest.raises(ValueError):
        rl.SlidingWindowLimiter(max_events=0)
    with pytest.raises(ValueError):
        rl.SlidingWindowLimiter(window_s=0)


def test_clean_chat_input():
    assert rl.clean_chat_input("  hi\x00 there\x07\n ") == "hi there"
    assert len(rl.clean_chat_input("a" * 5000)) == rl.MAX_CHAT_CHARS
    assert rl.clean_chat_input("   ") == ""


def test_chat_inputs_use_the_limiter():
    for name in ("app.py", "heat_ui.py"):
        src = (ROOT / name).read_text(encoding="utf-8")
        assert "SlidingWindowLimiter" in src and "clean_chat_input" in src and ".allow()" in src, name


# ------------------------------------------------------------------ observability
def test_event_line_is_json_and_drops_free_text():
    line = obs.format_event("project.decision.approved", "user:a@b.gov", "t", rank=2, note="patient John Smith 555-1234", eligibility="pass")
    body = json.loads(line)
    assert body["event"] == "project.decision.approved" and body["actor"] == "user:a@b.gov" and body["rank"] == 2
    assert "note" not in body and "John" not in line


def test_roles_are_serialised_sorted():
    assert json.loads(obs.format_event("login", roles=frozenset({"viewer", "admin"})))["roles"] == ["admin", "viewer"]


def test_log_event_emits_one_line(caplog):
    logger = obs._logger()  # creates the handler (and sets propagate False) before we let caplog see it
    logger.propagate = True
    try:
        with caplog.at_level(logging.INFO, logger=obs.LOGGER_NAME):
            obs.log_event("rule.published", "user:r@x", "t", rule="fma.nfip_participation")
    finally:
        logger.propagate = False
    assert len(caplog.records) == 1 and json.loads(caplog.records[0].message)["rule"] == "fma.nfip_participation"


def test_app_insights_is_off_without_connection_string():
    assert obs.setup_app_insights({}) is False


def test_app_insights_failure_never_breaks_the_app(monkeypatch):
    monkeypatch.setattr(obs, "_configured", False)
    assert obs.setup_app_insights({"APPLICATIONINSIGHTS_CONNECTION_STRING": "InstrumentationKey=x"}) is False  # package not installed here


def test_app_insights_enabled_when_package_present(monkeypatch):
    calls = []
    fake = types.ModuleType("azure.monitor.opentelemetry")
    fake.configure_azure_monitor = lambda **kw: calls.append(kw)
    for name in ("azure", "azure.monitor"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "azure.monitor.opentelemetry", fake)
    monkeypatch.setattr(obs, "_configured", False)
    assert obs.setup_app_insights({"APPLICATIONINSIGHTS_CONNECTION_STRING": "InstrumentationKey=x"}) is True
    assert calls and calls[0]["connection_string"] == "InstrumentationKey=x"
    monkeypatch.setattr(obs, "_configured", False)


# ------------------------------------------------------------------ UI actions are logged
@pytest.fixture()
def ui(tmp_path, monkeypatch):
    stub = MagicMock(name="streamlit")
    stub.session_state = {}
    stub.columns.side_effect = lambda spec, **kw: [MagicMock() for _ in range(spec if isinstance(spec, int) else len(spec))]
    stub.tabs.side_effect = lambda names: [MagicMock() for _ in names]
    stub.button.return_value = False
    stub.number_input.side_effect = lambda *a, **k: k.get("value", 0.0)
    stub.slider.side_effect = lambda label, lo, hi, d, **k: d
    stub.text_input.side_effect = lambda *a, **k: k.get("value", "")
    stub.text_area.return_value = ""
    stub.selectbox.side_effect = lambda label, options, **k: list(options)[k.get("index", 0)]

    class _Mod(types.ModuleType):
        def __getattr__(self, name):
            return getattr(stub, name)

    monkeypatch.setitem(sys.modules, "streamlit", _Mod("streamlit"))
    sys.modules.pop("civicsignal_ui", None)
    import civicsignal_ui
    yield civicsignal_ui, stub, audit_store.SQLiteBackend(str(tmp_path / "u.db"))
    sys.modules.pop("civicsignal_ui", None)


def test_rule_publication_is_logged_without_free_text(ui, monkeypatch):
    mod, st, backend = ui
    lines = []
    monkeypatch.setattr(obs, "_logger", lambda: types.SimpleNamespace(info=lines.append, warning=lines.append))
    me = ident.Identity("rev@city.gov", "R", "aad", frozenset({"viewer", "reviewer"}))
    st.button.side_effect = lambda label, *a, **k: label == "Approve all rules"
    mod.render(me, backend, "t")
    events = [json.loads(x) for x in lines]
    assert events and all(e["event"] == "rule.published" and e["actor"] == "user:rev@city.gov" for e in events)
    assert len(events) == 7  # one per rule, FMA 3 plus HMGP 4


def test_decision_is_logged(ui, monkeypatch):
    mod, st, backend = ui
    lines = []
    monkeypatch.setattr(obs, "_logger", lambda: types.SimpleNamespace(info=lines.append, warning=lines.append))
    boss = ident.Identity("boss@city.gov", "B", "aad", frozenset({"viewer", "admin"}))
    st.button.side_effect = lambda label, *a, **k: label == "Approve all rules"
    mod.render(boss, backend, "t")
    st.session_state.clear()
    lines.clear()
    st.text_area.side_effect = lambda *a, **k: "Reason: Jane Doe at 12 Elm St"
    st.selectbox.side_effect = lambda label, options, **k: "p3" if "Pick a project" in label else list(options)[k.get("index", 0)]
    st.button.side_effect = lambda label, *a, **k: label == "Approve"
    mod.render(boss, backend, "t")
    decided = [json.loads(x) for x in lines if "project.decision" in x]
    assert decided and decided[0]["event"] == "project.decision.approved" and "Jane" not in "".join(lines)


# ------------------------------------------------------------------ security hardening
@pytest.fixture()
def su(monkeypatch):
    """security_utils imports streamlit at module level; stub it only when it is not installed."""
    try:
        import streamlit  # noqa: F401
    except ImportError:
        monkeypatch.setitem(sys.modules, "streamlit", MagicMock())
    sys.modules.pop("security_utils", None)
    import security_utils
    yield security_utils
    sys.modules.pop("security_utils", None)


def test_safe_equals_is_correct_and_constant_time_api(su):
    assert su.safe_equals("s3cret", "s3cret") and not su.safe_equals("s3cret", "s3cre") and not su.safe_equals("a", "")
    assert su.safe_equals("é", "é")
    src = (ROOT / "security_utils.py").read_text(encoding="utf-8")
    assert "compare_digest" in src


def test_no_admin_password_mechanism_remains():
    for p in PY_FILES:
        text = p.read_text(encoding="utf-8")
        assert "ADMIN_PASSWORD" not in text and "_pw ==" not in text, p.name
    assert "ADMIN_PASSWORD" not in (ROOT / ".env.example").read_text(encoding="utf-8")


def _calls(tree, names):
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in names]


def test_no_eval_exec_or_shell_in_source():
    for p in PY_FILES:
        tree = ast.parse(p.read_text(encoding="utf-8"))
        assert not _calls(tree, {"eval", "exec", "compile", "__import__"}), p.name
        src = p.read_text(encoding="utf-8")
        assert "os.system" not in src and "shell=True" not in src and "pickle.load" not in src, p.name


def test_ranked_table_escapes_hostile_text(ui):
    mod, _, _ = ui
    import civicsignal as cs
    S = cs.new_state()
    S["projects"][0]["name"] = "<script>alert(1)</script>"
    S["projects"][0]["sponsor"]["name"] = '<img src=x onerror="steal()">'
    rk = cs.ranked(S["projects"], {k: d for k, _, d, _ in cs.CRITERIA}, S["published"])
    html_out = mod._table_html(rk, set(), S)
    assert "<script>" not in html_out and "<img" not in html_out and "&lt;script&gt;" in html_out


def test_every_dynamic_unsafe_html_f_string_uses_escape():
    """Any f-string passed to unsafe_allow_html in our UI modules must go through html.escape or be static."""
    for name in ("civicsignal_ui.py", "heat_ui.py"):
        src = (ROOT / name).read_text(encoding="utf-8")
        for m in re.finditer(r"st\.markdown\(\s*f[\"']", src):
            snippet = src[m.start(): m.start() + 400]
            if "unsafe_allow_html=True" in snippet:
                assert "html.escape" in snippet or "_pill(" in snippet, (name, snippet[:80])


def test_decision_packet_pdf_escapes_markup():
    import civicsignal as cs
    import decision_packet as dp
    S = cs.new_state()
    cs.init_outcomes(S)
    cs.publish_rules(S, [r["id"] for r in cs.RULES], "r@x")
    cs.decide(S, "p3", "held", "<b>bold</b> & <para>x", "o@x", {k: d for k, _, d, _ in cs.CRITERIA}, 4.0)
    assert dp.to_pdf(dp.build_packet(S, {k: d for k, _, d, _ in cs.CRITERIA}, 4.0)).startswith(b"%PDF-")


def test_forged_auth_headers_do_not_grant_admin_by_themselves():
    me = ident.parse_easy_auth({"X-Ms-Client-Principal-Name": "x@y.org"}, {"WEBSITE_AUTH_ENABLED": "True"})
    assert me is not None and not ident.can(me, "upload_data") and not ident.can(me, "decide")


# ------------------------------------------------------------------ packaging
def test_required_files_exist():
    for name in ("security_utils.py", "heat_ui.py", "startup.sh", "requirements.txt", "requirements-dev.txt", ".env.example",
                 ".github/workflows/ci.yml", "pyproject.toml", "TRACEABILITY.md", "locales/en.json", "locales/es.json"):
        assert (ROOT / name).exists(), name


def test_security_utils_exports_every_name_the_app_imports():
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    wanted = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "security_utils" for a in n.names}
    have = {n.name for n in ast.parse((ROOT / "security_utils.py").read_text(encoding="utf-8")).body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    have |= {t.id for n in ast.parse((ROOT / "security_utils.py").read_text(encoding="utf-8")).body if isinstance(n, ast.Assign)
             for t in n.targets if isinstance(t, ast.Name)}
    assert wanted and wanted <= have, wanted - have


def test_requirements_are_bounded_and_have_the_new_dependencies():
    lines = [x.strip() for x in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines() if x.strip() and not x.startswith("#")]
    assert all("," in x or "==" in x for x in lines), lines
    names = {re.split(r"[<>=!~]", x)[0] for x in lines}
    assert {"streamlit", "pandas", "plotly", "reportlab", "azure-data-tables", "pdfplumber", "openpyxl", "python-dotenv"} <= names


def test_env_example_has_no_real_secrets():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert not re.search(r"AccountKey=|SharedAccessSignature|InstrumentationKey=[0-9a-f]{8}-", text)


def test_ci_workflow_runs_ruff_mypy_pytest():
    wf = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for needle in ("ruff check", "mypy", "pytest", "pip-audit"):
        assert needle in wf


def test_startup_command_runs_the_app():
    s = (ROOT / "startup.sh").read_text(encoding="utf-8")
    assert "streamlit run app.py" in s and "--server.headless true" in s
