from types import SimpleNamespace
from unittest.mock import MagicMock

import anthropic

from postureguard.ai.client import ask


class _FakeStream:
    def __init__(self, response):
        self._response = response

    def with_options(self, **_kwargs):
        return self

    @property
    def messages(self):
        return SimpleNamespace(create=lambda **_kwargs: self._response)


def _text_response(text: str, stop_reason: str = "end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=text)],
    )


class TestAsk:
    def test_returns_none_without_a_key(self):
        assert ask("system", "content", "") is None

    def test_returns_the_response_text(self, monkeypatch):
        fake_client = _FakeStream(_text_response("hello there"))
        monkeypatch.setattr(
            "postureguard.ai.client.anthropic.Anthropic", lambda **_kwargs: fake_client
        )
        assert ask("system", "content", "sk-ant-test") == "hello there"

    def test_returns_none_on_refusal(self, monkeypatch):
        fake_client = _FakeStream(_text_response("", stop_reason="refusal"))
        monkeypatch.setattr(
            "postureguard.ai.client.anthropic.Anthropic", lambda **_kwargs: fake_client
        )
        assert ask("system", "content", "sk-ant-test") is None

    def test_returns_none_on_max_tokens_truncation(self, monkeypatch):
        fake_client = _FakeStream(
            _text_response("this got cut off mid-sen", stop_reason="max_tokens")
        )
        monkeypatch.setattr(
            "postureguard.ai.client.anthropic.Anthropic", lambda **_kwargs: fake_client
        )
        assert ask("system", "content", "sk-ant-test") is None

    def test_returns_none_on_api_error(self, monkeypatch):
        def _raise(**_kwargs):
            raise anthropic.APIConnectionError(request=MagicMock())

        monkeypatch.setattr(
            "postureguard.ai.client.anthropic.Anthropic",
            lambda **_kwargs: SimpleNamespace(with_options=lambda **_k: SimpleNamespace(
                messages=SimpleNamespace(create=_raise)
            )),
        )
        assert ask("system", "content", "sk-ant-test") is None

    def test_passes_effort_and_format_through(self, monkeypatch):
        captured = {}

        def _create(**kwargs):
            captured.update(kwargs)
            return _text_response("ok")

        fake_client = SimpleNamespace(
            with_options=lambda **_k: SimpleNamespace(messages=SimpleNamespace(create=_create))
        )
        monkeypatch.setattr(
            "postureguard.ai.client.anthropic.Anthropic", lambda **_kwargs: fake_client
        )
        ask("sys", "content", "sk-ant-test", effort="low", output_format={"type": "json_schema"})
        assert captured["output_config"] == {
            "effort": "low",
            "format": {"type": "json_schema"},
        }
        assert captured["model"] == "claude-opus-5"

    def test_disables_thinking_for_structured_output_requests(self, monkeypatch):
        captured = {}

        def _create(**kwargs):
            captured.update(kwargs)
            return _text_response("ok")

        fake_client = SimpleNamespace(
            with_options=lambda **_k: SimpleNamespace(messages=SimpleNamespace(create=_create))
        )
        monkeypatch.setattr(
            "postureguard.ai.client.anthropic.Anthropic", lambda **_kwargs: fake_client
        )
        ask("sys", "content", "sk-ant-test", output_format={"type": "json_schema"})
        assert captured["thinking"] == {"type": "disabled"}

    def test_leaves_thinking_unset_for_freeform_requests(self, monkeypatch):
        captured = {}

        def _create(**kwargs):
            captured.update(kwargs)
            return _text_response("ok")

        fake_client = SimpleNamespace(
            with_options=lambda **_k: SimpleNamespace(messages=SimpleNamespace(create=_create))
        )
        monkeypatch.setattr(
            "postureguard.ai.client.anthropic.Anthropic", lambda **_kwargs: fake_client
        )
        ask("sys", "content", "sk-ant-test")
        assert "thinking" not in captured
