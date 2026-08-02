import pytest

from postureguard.ai.exercise_context import generate_intro
from postureguard.rules import FaultKind
from postureguard.session import SessionStore


@pytest.fixture
def store():
    with SessionStore() as s:
        yield s


class TestGenerateIntro:
    def test_none_when_no_dominant_fault(self, store):
        assert generate_intro(None, store, "sk-ant-test") is None

    def test_none_when_ask_fails(self, store, monkeypatch):
        monkeypatch.setattr("postureguard.ai.exercise_context.ask", lambda *a, **k: None)
        assert generate_intro(FaultKind.FORWARD_HEAD, store, "sk-ant-test") is None

    def test_sends_the_fault_name_and_minutes(self, store, monkeypatch):
        for s in range(120):
            store.log(
                "fault",
                [__import__("postureguard.rules", fromlist=["Fault"]).Fault(
                    kind=FaultKind.FORWARD_HEAD, severity=1.0, cue="c"
                )],
                when=1_700_000_000 + s,
            )
        captured = {}

        def _fake_ask(system, content, api_key, **kwargs):
            captured["content"] = content
            return "You've been craning forward a lot."

        monkeypatch.setattr("postureguard.ai.exercise_context.ask", _fake_ask)
        result = generate_intro(FaultKind.FORWARD_HEAD, store, "sk-ant-test")
        assert result == "You've been craning forward a lot."
        assert "Forward head" in captured["content"]
        assert "2" in captured["content"]  # 120 seconds = 2 minutes
