from postureguard.ai.insights import answer_question


class TestAnswerQuestion:
    def test_returns_none_when_ask_fails(self, monkeypatch):
        monkeypatch.setattr("postureguard.ai.insights.ask", lambda *a, **k: None)
        assert answer_question({"average_in_tolerance_percent": 80.0}, "why?", "sk-ant-test") is None

    def test_sends_the_payload_and_question(self, monkeypatch):
        captured = {}

        def _fake_ask(system, content, api_key, **kwargs):
            captured["content"] = content
            return "Because you slouch more after lunch."

        monkeypatch.setattr("postureguard.ai.insights.ask", _fake_ask)
        result = answer_question(
            {"average_in_tolerance_percent": 80.0}, "why do I slouch?", "sk-ant-test"
        )
        assert result == "Because you slouch more after lunch."
        assert "why do I slouch?" in captured["content"]
        assert "80.0" in captured["content"]
