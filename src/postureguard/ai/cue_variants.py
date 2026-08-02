"""Alternate phrasings for the fixed per-fault correction text, generated once a day
via the Claude API and cached locally.

`rules.py` is unchanged and remains the source of truth: `Fault.cue`/`.action` stay
plain, pure, network-free strings, and every check in `_CHECKS` fires exactly as
before. This module only supplies alternates that the UI layer may substitute in —
never mid-episode, only picked once per calendar day (see `pick`), so nothing here can
flicker the display or add latency to the live loop.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from ..rules import FAULT_ACTIONS, FAULT_CUES, FAULT_TITLES, FaultKind
from .client import ask

#: How many alternate phrasings to request per fault kind per field.
VARIANTS_PER_FIELD = 4

_SYSTEM_PROMPT = (
    "You write alternate phrasings of posture-correction instructions for a "
    "desk-work app called PostureGuard. For each fault name given, you are given its "
    "canonical 'cue' (a full sentence for a panel) and 'action' (a short imperative "
    f"for a compact bar). Write {VARIANTS_PER_FIELD} alternate phrasings of each, "
    "keeping the same meaning, the same verb, and the same tone: plain, direct, no "
    "exclamation points, no emoji. The cue stays a full sentence; the action stays "
    "under 6 words. Respond only with the requested JSON — one object keyed by fault "
    "name, each holding a 'cue' array and an 'action' array of alternate strings."
)


@dataclass(frozen=True)
class CueVariantCache:
    """Alternate phrasings, keyed by `FaultKind.value` then `"cue"`/`"action"`."""

    variants: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    generated_at: str = ""

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"variants": self.variants, "generated_at": self.generated_at}, indent=2
            ),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> CueVariantCache:
        """An empty cache on any problem — a missing or corrupt file just means every
        fault falls back to its canonical text via `pick`, never a crash."""
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                variants={str(k): v for k, v in raw.get("variants", {}).items()},
                generated_at=str(raw.get("generated_at", "")),
            )
        except (OSError, ValueError, AttributeError, TypeError):
            return cls()


def _schema() -> dict:
    per_kind = {
        "type": "object",
        "properties": {
            "cue": {"type": "array", "items": {"type": "string"}},
            "action": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["cue", "action"],
        "additionalProperties": False,
    }
    kind_names = [kind.value for kind in FaultKind]
    return {
        "type": "json_schema",
        "schema": {
            "type": "object",
            "properties": dict.fromkeys(kind_names, per_kind),
            "required": kind_names,
            "additionalProperties": False,
        },
    }


def generate_variants(api_key: str) -> CueVariantCache | None:
    """One API call generating alternates for every fault kind at once, or None on
    any failure — the caller keeps whatever cache (possibly empty) it already has."""
    canonical = {
        kind.value: {
            "title": FAULT_TITLES[kind],
            "cue": FAULT_CUES[kind],
            "action": FAULT_ACTIONS[kind],
        }
        for kind in FaultKind
    }
    response = ask(
        _SYSTEM_PROMPT,
        json.dumps(canonical),
        api_key,
        effort="low",
        output_format=_schema(),
    )
    if response is None:
        return None
    try:
        parsed = json.loads(response)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    return CueVariantCache(variants=parsed, generated_at=date.today().isoformat())


def pick(
    cache: CueVariantCache | None,
    kind: FaultKind,
    canonical: str,
    field: str = "cue",
    today: date | None = None,
) -> str:
    """A stable-for-the-day alternate phrasing, or `canonical` when none is cached.

    Deterministic by calendar day, not random per call: the live loop repaints many
    times a second, and a fresh random pick every frame would flicker the text.
    """
    if cache is None:
        return canonical
    variants = cache.variants.get(kind.value, {}).get(field, [])
    if not variants:
        return canonical
    index = (today or date.today()).toordinal() % len(variants)
    return variants[index]
