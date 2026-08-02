"""Thin wrapper around the Claude API — the one place in this codebase that touches
the network for AI-generated content.

Every caller gets the same contract: pass a system prompt and user content, get text
back or None. None covers every failure mode uniformly (no key, no network, timeout,
refusal) so callers never need to distinguish them — they all mean "fall back to
whatever this would have enhanced."
"""

from __future__ import annotations

import logging

import anthropic

log = logging.getLogger(__name__)

MODEL = "claude-opus-5"
#: Seconds. Every call site here is either backgrounded (QThread) or already an
#: on-demand user action, so this only bounds worst-case wait — it never blocks a
#: frame loop.
TIMEOUT_SECONDS = 15.0
MAX_TOKENS = 1024


def ask(
    system: str,
    user_content: str,
    api_key: str,
    *,
    effort: str = "low",
    output_format: dict | None = None,
) -> str | None:
    """One-shot text request. Returns None on any failure — no key, network error,
    timeout, or refusal — so every caller has a single, uniform fallback path.
    """
    if not api_key:
        return None

    output_config: dict = {"effort": effort}
    if output_format is not None:
        output_config["format"] = output_format

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.with_options(timeout=TIMEOUT_SECONDS).messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            output_config=output_config,
            messages=[{"role": "user", "content": user_content}],
        )
        if response.stop_reason == "refusal":
            return None
        return next((block.text for block in response.content if block.type == "text"), None)
    except anthropic.AnthropicError as exc:
        log.info("AI request failed: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001 - a network/timeout failure must never
        # propagate into the Qt event loop or a background worker thread.
        log.info("AI request failed unexpectedly: %s", exc)
        return None
