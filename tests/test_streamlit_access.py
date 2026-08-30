"""Regression tests for the Streamlit password gate."""

import streamlit_app


class _FakeStreamlit:
    def __init__(self):
        self.session_state = {}
        self.errors = []
        self.titles = []
        self.password_input = None

    def title(self, value):
        self.titles.append(value)

    def error(self, value):
        self.errors.append(value)

    def text_input(self, label, **kwargs):
        self.password_input = {"label": label, **kwargs}


def test_password_matching_requires_a_nonempty_exact_value():
    assert streamlit_app._password_matches("correct password", "correct password")
    assert not streamlit_app._password_matches("incorrect password", "correct password")
    assert not streamlit_app._password_matches("anything", "")


def test_password_gate_blocks_then_remembers_a_successful_session(monkeypatch):
    fake_streamlit = _FakeStreamlit()
    monkeypatch.setattr(streamlit_app, "st", fake_streamlit)
    monkeypatch.setattr(streamlit_app, "_get_config_value", lambda key: "correct password")

    assert not streamlit_app._require_access()
    assert fake_streamlit.password_input == {
        "label": "Password",
        "type": "password",
        "key": "app_password_entry",
        "on_change": streamlit_app._authenticate,
    }

    fake_streamlit.session_state["app_password_entry"] = "correct password"
    streamlit_app._authenticate()

    assert fake_streamlit.session_state["app_authenticated"] is True
    assert "app_password_entry" not in fake_streamlit.session_state
    assert streamlit_app._require_access()
