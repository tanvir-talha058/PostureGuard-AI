# AI Features — Design Spec

Date: 2026-08-02

## Purpose

Add optional, opt-in AI-generated content to PostureGuard, layered on top of the existing
deterministic pipeline without weakening its guarantees: camera frames never leave the
device, the real-time detection loop has no network dependency, and every feature here is
off by default.

Four features, sharing one client:

1. **AI weekly summary** — a richer version of the existing one-line weekly note.
2. **Insights screen** — a new screen for on-demand questions about posture history.
3. **AI-varied real-time cues** — alternate phrasings of the existing fixed correction text.
4. **AI exercise context** — a short personalized intro on top of the existing exercise picks.

## Scope

**In scope:** the four features above; a shared `ai/client.py` request wrapper; new Config
fields, all opt-in; Settings UI to enter an API key and toggle each feature; tests for every
pure function and for graceful fallback on API failure.

**Out of scope:** AI-authored exercise steps (safety/liability — the vetted exercise library
in `stretches.py` is unchanged), AI involvement in fault detection or the rules engine
(`metrics.py`/`rules.py` stay pure and network-free), any feature that blocks the live
detection loop on a network call, local/offline LLM inference.

## Privacy stance

Camera frames and pose landmarks are never sent anywhere — this is unchanged and
non-negotiable per the existing privacy guarantee (see `test_session.py`). What each AI
feature sends, when explicitly enabled:

| Feature | Data sent | Frequency |
|---|---|---|
| Weekly summary | Daily scores, worst hour, per-fault-kind minutes (all aggregate numbers) | Once a week |
| Insights | Same aggregates, wider date range, plus the user's typed question | On demand |
| Cue variants | The 8 fault kinds' existing canonical cue/action strings | Once a day, or manually |
| Exercise context | Dominant fault name, recent adherence stats | Once per break, when enabled |

No feature sends video, images, or raw per-frame metrics. All four require an API key the
user enters themselves in Settings; none are reachable without one.

## Architecture

```
                         ┌─ weekly_summary.py ─┐
config.ai_api_key ──▶ ai/client.py ◀── cue_variants.py
                         └─ exercise_context.py ┘
                                  ▲
                        ui/screens/insights.py
```

`ai/client.py` owns the only network call in the AI surface:

```python
def ask(system: str, user_content: str, api_key: str, effort: str = "low") -> str | None:
    """One-shot text request. Returns None on any failure — auth, network, timeout,
    refusal — so every caller has a single, uniform fallback path."""
```

Model: `claude-opus-5`. Effort `low` (short, non-agentic text generation). No thinking
configuration is set explicitly (adaptive default is fine at this scale). A short client-side
timeout (~15s) bounds worst-case latency since every call site either runs in the background
or is already an on-demand action.

Each feature module depends only on `ai/client.py` plus whatever local data it summarizes
(`SessionStore`, `rules.FaultKind`, `stretches.py`) — none of them import from `metrics.py`,
`rules.py`, `engine.py`, or `capture.py`, keeping the real-time path untouched.

## Feature 1 — AI weekly summary

`ai/weekly_summary.py`:

- `build_stats_payload(store, days=7, today=None) -> dict` — pure, built from
  `SessionStore.daily_summaries`, `.hourly_profile`, `.fault_breakdown` (the same aggregates
  `weekly_summary.build_message` already uses). Unit-tested like `metrics.py`.
- `generate_message(payload, api_key) -> str | None` — calls `ai/client.ask()` with a system
  prompt matching the app's existing voice (plain, measurement-toned, no moralizing) and the
  payload as user content. Returns `None` on any failure.

Wiring in `app.py`: `_maybe_show_weekly_summary()` tries the AI path first only when
`config.ai_weekly_summary_enabled` and `config.ai_api_key` are both set, via a small
`QThread` worker (network call must not block the Qt main thread even for a once-a-week
call). On `None`, falls straight back to the existing `weekly_summary.build_message()` —
today's behavior is the floor, not something this replaces.

## Feature 2 — Insights screen

New `ui/screens/insights.py`, added to the sidebar (`window.py`'s nav list gets an
`("insights", "Insights")` entry, gated behind `config.ai_insights_enabled`). A question
input, an "Ask" button, and a response area. On ask:

1. Build a stats payload via `ai/weekly_summary.build_stats_payload()` with a wider date
   range (e.g. 90 days) than the weekly summary uses.
2. Send the payload plus the user's question to `ai/client.ask()` on a background `QThread`.
3. Render the response, or an inline error if the call failed or no key is configured (with
   a link to Settings).

No caching, no write path — purely a read-only view over existing History data plus one
network call per question. Does not touch `engine.py` or the live loop at all.

## Feature 3 — AI-varied real-time cues

`ai/cue_variants.py`:

- `generate_variants(api_key) -> dict[FaultKind, list[str]] | None` — one call to
  `ai/client.ask()` with structured output (`output_config.format`, JSON schema) asking for
  ~4 alternate phrasings of each fault kind's existing `cue`/`action` strings from
  `rules.FAULT_TITLES`/`_CUES`/`FAULT_ACTIONS`, same meaning and verb, just varied wording.
- `CueVariantCache` — loads/saves `cue_variants.json` under the existing local data folder
  (`paths.py`), same JSON-with-`None`-on-corruption pattern as `Baseline.load`. Refreshed at
  most once a day, either from a "Regenerate phrasings" button in Settings or opportunistically
  from the existing daily retention timer in `app.py`, when
  `config.ai_cue_variants_enabled` is on.

**What does not change:** `rules.py`'s `Fault.cue`/`.action` remain the canonical, guaranteed
strings — pure, synchronous, no I/O. The overlay/mini-window/toast layer (`overlay.py`,
`alerts.py`) is the only thing that changes: when a cached variant exists for the current
fault kind, it picks one at random instead of the literal `fault.cue`/`fault.action`; when the
cache is empty (feature off, or not yet generated), behavior is byte-identical to today. This
keeps the "everything else verified by running it" invariant intact — the live loop never
waits on, or even checks for, network state.

## Feature 4 — AI exercise context

`ai/exercise_context.py`:

- `generate_intro(dominant_fault, store, api_key) -> str | None` — sends the dominant fault
  name and a short adherence summary (from `SessionStore`) to `ai/client.ask()`, asking for a
  2-3 sentence contextual framing of *why* this routine, referencing the actual pattern
  observed. Returns `None` on failure.

**Explicitly not in scope:** the AI does not choose, generate, or modify exercises or their
steps. `stretches.routine_for()` remains the sole source of which exercises appear, exactly
as today. The generated text is additive framing only, shown above the existing routine in
`ui/screens/exercises.py`, and the screen works identically with or without it.

## Config additions

```python
# --- ai ---
ai_api_key: str = ""
ai_weekly_summary_enabled: bool = False
ai_insights_enabled: bool = False
ai_cue_variants_enabled: bool = False
ai_exercise_context_enabled: bool = False
```

All off by default; a fresh install or an upgrade from an older config file behaves exactly
as before. Existing `weekly_summary_enabled` — the static version — is unaffected and stays
the default path when the AI toggle is off or unconfigured.

## Settings UI

A new panel (or a section appended to `PrivacyPanel`) with the API key field
(`QLineEdit`, password-echo mode) and the four toggles above, each with a one-line
disclosure of what data that toggle sends (per the Privacy stance table). The "Regenerate
phrasings" button for cue variants lives here too.

## Dependency

Add `anthropic` to `pyproject.toml` `dependencies`.

## Testing

- `build_stats_payload()` — unit-tested against a seeded `SessionStore`, pure, no network
  (same pattern as `test_weekly_summary.py`).
- `generate_message()`, `generate_variants()`, `generate_intro()` — each tested by
  monkeypatching `ai.client.ask` to verify: (a) the payload/prompt shape sent, and (b)
  graceful fallback (`None` propagates correctly, callers fall back to existing static
  behavior) when `ask()` raises or returns `None`.
- `CueVariantCache` — load/save round-trip and corrupt-file handling, same shape as
  `test_calibration.py`'s `Baseline.load` tests.
- Overlay/alerts cue-selection — test that a populated cache changes the displayed string
  and an empty cache reproduces today's exact output.
- No test ever makes a real network call — `ai.client.ask` is the one seam every test mocks.
