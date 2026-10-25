"""Smoke test for civicsignal_ui with a stubbed ``streamlit`` module (the real one is not needed to run the logic paths)."""
import sys
import types
from unittest.mock import MagicMock

import pytest

import audit_store
import identity as ident


class _Session(dict):
    def __getattr__(self, k):
        return self[k]

    def __setattr__(self, k, v):
        self[k] = v


def _make_stub():
    st = MagicMock(name="streamlit")
    st.session_state = _Session()
    def _col():
        c = MagicMock()
        c.button.side_effect = lambda *a, **k: st.button(*a, **k)  # column buttons behave like st.button
        return c

    st.columns.side_effect = lambda spec, **kw: [_col() for _ in range(spec if isinstance(spec, int) else len(spec))]
    st.tabs.side_effect = lambda names: [MagicMock() for _ in names]
    st.button.return_value = False
    st.toggle.return_value = False
    st.download_button.return_value = False
    st.number_input.side_effect = lambda *a, **k: k.get("value", 0.0)
    st.slider.side_effect = lambda label, lo, hi, d, **k: d
    st.text_input.side_effect = lambda *a, **k: k.get("value", "")
    st.text_area.return_value = ""
    st.selectbox.side_effect = lambda label, options, **k: list(options)[k.get("index", 0)]
    return st


@pytest.fixture()
def ui(tmp_path, monkeypatch):
    stub = _make_stub()
    class _Mod(types.ModuleType):
        def __getattr__(self, name):
            return getattr(stub, name)

    mod = _Mod("streamlit")
    monkeypatch.setitem(sys.modules, "streamlit", mod)
    sys.modules.pop("civicsignal_ui", None)
    import civicsignal_ui
    yield civicsignal_ui, stub, audit_store.SQLiteBackend(str(tmp_path / "ui.db"))
    sys.modules.pop("civicsignal_ui", None)


@pytest.mark.parametrize("roles", [None, {"viewer"}, {"viewer", "reviewer"}, {"viewer", "official"}, {"viewer", "admin"}])
def test_render_for_each_role(ui, roles):
    mod, st, backend = ui
    me = ident.Identity("a@b.gov", "A", "aad", frozenset(roles)) if roles else None
    mod.render(me, backend, "t", sample_data=True)
    assert st.markdown.called


def test_anonymous_cannot_publish_or_decide(ui):
    mod, st, backend = ui
    st.button.side_effect = lambda *a, **k: True  # click everything
    mod.render(None, backend, "t")
    assert audit_store.list_events(backend, "t") == []


def test_reviewer_publish_is_recorded_under_verified_identity(ui):
    mod, st, backend = ui
    me = ident.Identity("rev@city.gov", "Rev", "aad", frozenset({"viewer", "reviewer"}))
    st.button.side_effect = lambda label, *a, **k: label == "Approve all rules"
    mod.render(me, backend, "t")
    events = audit_store.list_events(backend, "t")
    assert events and {e["actor"] for e in events if e["action"] == "rule.published"} == {"user:rev@city.gov"}
    assert audit_store.verify_chain(backend, "t")[0]


def test_reviewer_cannot_decide(ui):
    mod, st, backend = ui
    me = ident.Identity("rev@city.gov", "Rev", "aad", frozenset({"viewer", "reviewer"}))
    st.button.side_effect = lambda label, *a, **k: label in ("Approve", "Hold")
    mod.render(me, backend, "t")
    assert not any(e["action"].startswith("project.decision") for e in audit_store.list_events(backend, "t"))


def test_official_decision_persists_after_reload(ui):
    mod, st, backend = ui
    boss = ident.Identity("boss@city.gov", "B", "aad", frozenset({"viewer", "admin"}))
    st.button.side_effect = lambda label, *a, **k: label == "Approve all rules"
    mod.render(boss, backend, "t")
    st.session_state.clear()
    st.session_state["cs_note_p3"] = "ok"
    st.text_area.side_effect = lambda *a, **k: "Meets criteria"
    st.selectbox.side_effect = lambda label, options, **k: "p3" if "Pick a project" in label else list(options)[k.get("index", 0)]
    st.button.side_effect = lambda label, *a, **k: label == "Approve"
    mod.render(boss, backend, "t")
    assert any(e["action"] == "project.decision.approved" for e in audit_store.list_events(backend, "t"))
    st.session_state.clear()  # a fresh browser session
    st.button.side_effect = lambda *a, **k: False
    mod.render(boss, backend, "t")
    assert st.session_state["cs::t"]["decisions"]["p3"]["action"] == "approved"
