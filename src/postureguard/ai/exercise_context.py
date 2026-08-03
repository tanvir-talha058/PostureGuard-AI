"""A short, AI-written introduction for the exercise routine already chosen by
:func:`postureguard.stretches.routine_for`.

The AI never selects or writes exercises, and never touches `stretches.py`'s vetted
library — it only frames why *this* routine, given the user's own recent history.
Generating unvetted physical-movement instructions is out of scope on purpose; see
the design spec.
"""

from __future__ import annotations

import json

from ..rules import FAULT_TITLES, FaultKind
from ..session import SessionStore
from .client import ask

_SYSTEM_PROMPT = (
    "You write a 2-3 sentence introduction to a stretch-break routine in a desk-work "
    "posture app called PostureGuard. You are told which posture fault has been most "
    "frequent recently and how many minutes it has cost this week. Explain briefly "
    "why this routine, in plain language. No exclamation points, no emoji, no medical "
    "claims — these are mobility drills, not treatment. Do not name or suggest any "
    "specific exercise; a fixed routine is shown separately."
)


def generate_intro(dominant: FaultKind | None, store: SessionStore, api_key: str) -> str | None:
    """A short personalized framing sentence, or None when there is no dominant
    fault to explain, or on any API failure."""
    if dominant is None:
        return None
    minutes = round(store.fault_breakdown(days=7).get(dominant, 0) / 60)
    payload = {"fault": FAULT_TITLES[dominant], "minutes_this_week": minutes}
    return ask(_SYSTEM_PROMPT, json.dumps(payload), api_key, effort="low")
