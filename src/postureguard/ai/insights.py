"""Answers a free-form question about posture history via the Claude API.

Read-only and stateless: no caching, no write path. The payload is the same
aggregate shape the weekly summary and History screen already compute — never
frames, never raw per-frame metrics.
"""

from __future__ import annotations

import json

from .client import ask

_SYSTEM_PROMPT = (
    "You answer questions about a user's posture history for a desk-work posture app "
    "called PostureGuard. You are given aggregate statistics (daily scores, worst "
    "hour, minutes per fault type) and a question. Answer only from the given data — "
    "if the data does not support an answer, say so plainly. Plain, direct tone, no "
    "medical advice, 2-4 sentences."
)


def answer_question(payload: dict, question: str, api_key: str) -> str | None:
    content = json.dumps({"stats": payload, "question": question})
    return ask(_SYSTEM_PROMPT, content, api_key, effort="low")
