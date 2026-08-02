# AI Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four opt-in, off-by-default AI-generated content features to PostureGuard —
a richer weekly summary, an on-demand Insights screen, varied real-time cue phrasing, and
personalized exercise-routine framing — without adding a network dependency to the
real-time detection loop or touching `metrics.py`/`rules.py`/`engine.py`.

**Architecture:** One shared request wrapper (`ai/client.py`) that every feature module
calls through. Every network call happens either on a background `QThread` (weekly
summary, insights, exercise context) or is pre-generated and cached to disk ahead of time
(cue variants) — the live 5-30fps loop never waits on, or even checks, network state.
`rules.py`'s `Fault.cue`/`.action` remain the untouched, guaranteed fallback everywhere.

**Tech Stack:** Python 3.10+, PySide6 (existing), `anthropic` SDK (new dependency),
`claude-opus-5` model, pytest (existing).

## Global Constraints

- Camera frames, pose landmarks, and per-frame metrics are **never** sent to the API —
  only aggregate numbers (scores, minutes, fault names) or explicit user-typed text
  (Insights questions). This is the existing privacy invariant and is non-negotiable.
- Every new feature is **off by default**; a fresh install or an upgrade from an existing
  `config.json` behaves identically to today until the user opts in from Settings.
- The real-time detection/escalation loop (`engine.py`, `rules.py`, `metrics.py`,
  `escalation.py`) is not modified and gains no import of anything under `ai/`.
- Every `ai.client.ask()` call site must handle `None` (any failure — no key, no network,
  timeout, refusal) by falling back to the existing static behavior. No feature may raise
  an exception into the Qt event loop.
- Model is always `claude-opus-5`, called with `output_config={"effort": "low", ...}` —
  every request here is short, non-agentic text generation.
- New Config fields default such that `Config.load()` on an old `config.json` (missing
  the new keys) round-trips to the same defaults as `Config()`.

---

### Task 1: Config fields and the `anthropic` dependency

**Files:**
- Modify: `pyproject.toml` (dependencies list)
- Modify: `src/postureguard/config.py` (add fields to `Config`)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Config.ai_api_key: str`, `Config.ai_weekly_summary_enabled: bool`,
  `Config.ai_insights_enabled: bool`, `Config.ai_cue_variants_enabled: bool`,
  `Config.ai_exercise_context_enabled: bool` — all consumed by every later task.

- [ ] **Step 1: Add the dependency**

Edit `pyproject.toml`, in the `dependencies` list under `[project]`:

```toml
dependencies = [
    "mediapipe>=0.10.14",
    "opencv-python>=4.9",
    "PySide6>=6.6",
    "numpy>=1.26",
    "anthropic>=0.69",
]
```

- [ ] **Step 2: Install it**

Run: `.venv/Scripts/python -m pip install -e ".[dev]"`
Expected: installs `anthropic` and its dependencies with no errors.

- [ ] **Step 3: Write the failing test**

Add to `tests/test_config.py`, inside `class TestPersistence`:

```python
    def test_ai_fields_default_off(self):
        config = Config()
        assert config.ai_api_key == ""
        assert config.ai_weekly_summary_enabled is False
        assert config.ai_insights_enabled is False
        assert config.ai_cue_variants_enabled is False
        assert config.ai_exercise_context_enabled is False

    def test_an_old_config_file_without_ai_keys_loads_ai_defaults(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text('{"sensitivity": 1.4}', encoding="utf-8")
        loaded = Config.load(path)
        assert loaded.ai_api_key == ""
        assert loaded.ai_weekly_summary_enabled is False
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_config.py -k ai_fields -v`
Expected: FAIL with `AttributeError: 'Config' object has no attribute 'ai_api_key'`

- [ ] **Step 5: Add the fields to `Config`**

In `src/postureguard/config.py`, add this block just before the `def thresholds(self)`
method (after the `# --- app ---` section):

```python
    # --- ai ---
    #: Shared by every AI feature below. Stored in plaintext in config.json, same as
    #: every other local setting — there is no OS keychain integration in this app.
    ai_api_key: str = ""
    #: A richer weekly note, generated from the same aggregates the static one uses.
    #: Off by default: this is the only AI toggle that fires unprompted (once a week).
    ai_weekly_summary_enabled: bool = False
    #: Gates the Insights screen's ability to actually answer questions. The screen
    #: itself is always present; without a key it just explains that.
    ai_insights_enabled: bool = False
    #: Alternate phrasings for the fixed correction text, regenerated at most once a
    #: day and cached to disk — the live loop never calls the network for this.
    ai_cue_variants_enabled: bool = False
    #: A short AI-written intro above the (unchanged) exercise picks, once per break.
    ai_exercise_context_enabled: bool = False
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_config.py -v`
Expected: PASS, all tests including the two new ones and the existing
`test_round_trips_through_disk` (which now also carries the new fields through
`asdict`/`json.dumps` automatically since they're plain dataclass fields).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/postureguard/config.py tests/test_config.py
git commit -m "Add ai_api_key and per-feature AI toggles to Config, add anthropic dependency"
```

---

### Task 2: Shared AI request wrapper

**Files:**
- Create: `src/postureguard/ai/__init__.py`
- Create: `src/postureguard/ai/client.py`
- Test: `tests/test_ai_client.py`

**Interfaces:**
- Produces: `ai.client.ask(system: str, user_content: str, api_key: str, *, effort: str = "low", output_format: dict | None = None) -> str | None`
  — the only function every later AI module calls to reach the network.

- [ ] **Step 1: Create the package**

Create `src/postureguard/ai/__init__.py`:

```python
"""Optional, opt-in AI-generated content, layered on the deterministic pipeline.

Nothing under this package is imported by metrics.py, rules.py, or engine.py — the
real-time detection loop has no network dependency, with or without this package
installed or configured. See docs/superpowers/specs/2026-08-02-ai-features-design.md.
"""
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_ai_client.py`:

```python
from types import SimpleNamespace
from unittest.mock import MagicMock

import anthropic
import pytest

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
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_ai_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'postureguard.ai.client'`

- [ ] **Step 4: Write the implementation**

Create `src/postureguard/ai/client.py`:

```python
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
    except anthropic.AnthropicError as exc:
        log.info("AI request failed: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001 - a network/timeout failure must never
        # propagate into the Qt event loop or a background worker thread.
        log.info("AI request failed unexpectedly: %s", exc)
        return None

    if response.stop_reason == "refusal":
        return None
    return next((block.text for block in response.content if block.type == "text"), None)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_ai_client.py -v`
Expected: PASS, all 5 tests.

- [ ] **Step 6: Commit**

```bash
git add src/postureguard/ai/__init__.py src/postureguard/ai/client.py tests/test_ai_client.py
git commit -m "Add ai/client.py, the shared Claude API request wrapper"
```

---

### Task 3: AI weekly summary — payload and message generation

**Files:**
- Create: `src/postureguard/ai/weekly_summary.py`
- Test: `tests/test_ai_weekly_summary.py`

**Interfaces:**
- Consumes: `postureguard.session.SessionStore` (`.daily_summaries`, `.hourly_profile`,
  `.fault_breakdown`, existing); `postureguard.rules.FAULT_TITLES` (existing);
  `ai.client.ask` (Task 2).
- Produces: `ai.weekly_summary.build_stats_payload(store, days=7, today=None) -> dict | None`;
  `ai.weekly_summary.generate_message(payload: dict, api_key: str) -> str | None`.
  Both consumed by Task 4 (app.py wiring) and Task 9 (Insights screen reuses
  `build_stats_payload`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ai_weekly_summary.py`:

```python
from datetime import date

import pytest

from postureguard.ai.weekly_summary import build_stats_payload, generate_message
from postureguard.session import SessionStore

TODAY = date(2026, 8, 2)


def at(day: date, hour: int = 10, second: int = 0) -> float:
    from datetime import datetime

    return datetime(day.year, day.month, day.day, hour).timestamp() + second


def fill(store: SessionStore, day: date, hour: int, seconds: int, status: str, faults=()):
    for s in range(seconds):
        store.log(status, faults, when=at(day, hour, s))


@pytest.fixture
def store():
    with SessionStore() as s:
        yield s


class TestBuildStatsPayload:
    def test_none_when_too_little_was_tracked(self, store):
        fill(store, TODAY, 10, 30, "in_tolerance")
        assert build_stats_payload(store, today=TODAY) is None

    def test_names_average_and_worst_hour(self, store):
        fill(store, TODAY, 9, 3600, "in_tolerance")
        fill(store, TODAY, 15, 3600, "fault")
        payload = build_stats_payload(store, today=TODAY)
        assert payload is not None
        assert payload["worst_hour"] == "15:00"
        assert payload["average_in_tolerance_percent"] == pytest.approx(50.0, abs=1.0)

    def test_no_camera_or_metric_data_in_the_payload(self, store):
        fill(store, TODAY, 9, 3600, "in_tolerance")
        fill(store, TODAY, 15, 3600, "fault")
        payload = build_stats_payload(store, today=TODAY)
        assert "frame" not in str(payload).lower()
        assert "landmark" not in str(payload).lower()
        assert set(payload.keys()) == {
            "days_tracked",
            "average_in_tolerance_percent",
            "worst_hour",
            "worst_hour_score_percent",
            "fault_minutes",
        }


class TestGenerateMessage:
    def test_returns_none_when_ask_fails(self, monkeypatch):
        monkeypatch.setattr("postureguard.ai.weekly_summary.ask", lambda *a, **k: None)
        assert generate_message({"average_in_tolerance_percent": 80.0}, "sk-ant-test") is None

    def test_sends_the_payload_as_json_content(self, monkeypatch):
        captured = {}

        def _fake_ask(system, content, api_key, **kwargs):
            captured["system"] = system
            captured["content"] = content
            captured["api_key"] = api_key
            return "You averaged 80% this week."

        monkeypatch.setattr("postureguard.ai.weekly_summary.ask", _fake_ask)
        payload = {"average_in_tolerance_percent": 80.0}
        result = generate_message(payload, "sk-ant-test")
        assert result == "You averaged 80% this week."
        assert captured["api_key"] == "sk-ant-test"
        assert "80.0" in captured["content"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_ai_weekly_summary.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'postureguard.ai.weekly_summary'`

- [ ] **Step 3: Write the implementation**

Create `src/postureguard/ai/weekly_summary.py`:

```python
"""Turns a week of posture history into a short, personalized note via the Claude API.

Sends aggregate numbers only — daily scores, the worst hour, minutes spent in each
fault type — never frames, landmarks, or per-frame metrics. The caller (app.py) falls
back to :func:`postureguard.weekly_summary.build_message`'s static one-liner whenever
`generate_message` returns None.
"""

from __future__ import annotations

import json
from datetime import date

from ..rules import FAULT_TITLES
from ..session import SessionStore
from ..weekly_summary import INTERVAL_DAYS, MIN_TRACKED_SECONDS
from .client import ask

_SYSTEM_PROMPT = (
    "You write a one-paragraph weekly posture note for a desk-work posture app called "
    "PostureGuard. The tone is that of a measuring instrument, not a wellness app: "
    "plain, specific, no moralizing, no exclamation points, no emoji. You are given "
    "aggregate statistics for the past week — daily in-tolerance percentages, the "
    "worst hour of the day, and minutes spent in each named fault. Write 2-4 sentences "
    "naming the pattern, not just the numbers. Do not invent numbers not present in "
    "the data. Do not give medical advice."
)


def build_stats_payload(
    store: SessionStore, days: int = INTERVAL_DAYS, today: date | None = None
) -> dict | None:
    """Pure aggregate summary of the last `days`. None when there is too little
    tracked time to say anything meaningful — the same gate
    :func:`postureguard.weekly_summary.build_message` uses.
    """
    summaries = store.daily_summaries(days=days, today=today)
    tracked_total = sum(s.tracked_seconds for s in summaries)
    if tracked_total < MIN_TRACKED_SECONDS:
        return None

    profile = [h for h in store.hourly_profile(days=days, today=today) if h.tracked_seconds > 60]
    worst = min(profile, key=lambda h: h.score, default=None)
    average = 100.0 * sum(s.in_tolerance_seconds for s in summaries) / tracked_total
    fault_minutes = {
        FAULT_TITLES[kind]: round(seconds / 60)
        for kind, seconds in store.fault_breakdown(days=days, today=today).items()
        if seconds >= 60
    }

    return {
        "days_tracked": len(summaries),
        "average_in_tolerance_percent": round(average, 1),
        "worst_hour": f"{worst.hour:02d}:00" if worst else None,
        "worst_hour_score_percent": round(worst.score, 1) if worst else None,
        "fault_minutes": fault_minutes,
    }


def generate_message(payload: dict, api_key: str) -> str | None:
    """The AI weekly note, or None on any failure — the caller falls back to the
    existing static one-liner."""
    return ask(_SYSTEM_PROMPT, json.dumps(payload), api_key, effort="low")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_ai_weekly_summary.py -v`
Expected: PASS, all 5 tests.

- [ ] **Step 5: Commit**

```bash
git add src/postureguard/ai/weekly_summary.py tests/test_ai_weekly_summary.py
git commit -m "Add ai/weekly_summary.py: aggregate payload and AI message generation"
```

---

### Task 4: Background worker + wire the AI weekly summary into the app

**Files:**
- Create: `src/postureguard/ai/worker.py`
- Modify: `src/postureguard/app.py` (`_maybe_show_weekly_summary`, imports)
- Test: `tests/test_ai_worker.py`

**Interfaces:**
- Consumes: `ai.weekly_summary.build_stats_payload`, `.generate_message` (Task 3).
- Produces: `ai.worker.AskWorker(work: Callable[[], object]) -> QThread` with a
  `finished_with = Signal(object)` emitted with `work()`'s return value (or `None` if
  `work` raised). Reused by Tasks 6, 8, 9, 10.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ai_worker.py`:

```python
from PySide6.QtCore import QEventLoop
from PySide6.QtWidgets import QApplication

from postureguard.ai.worker import AskWorker


def _qapp():
    return QApplication.instance() or QApplication([])


def _run_worker(work):
    _qapp()
    worker = AskWorker(work)
    loop = QEventLoop()
    results = []
    worker.finished_with.connect(lambda value: (results.append(value), loop.quit()))
    worker.start()
    loop.exec()
    worker.wait()
    return results[0]


class TestAskWorker:
    def test_emits_the_callables_return_value(self):
        assert _run_worker(lambda: "hello") == "hello"

    def test_emits_none_when_the_callable_raises(self):
        def _boom():
            raise RuntimeError("network exploded")

        assert _run_worker(_boom) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_ai_worker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'postureguard.ai.worker'`

- [ ] **Step 3: Write the implementation**

Create `src/postureguard/ai/worker.py`:

```python
"""A tiny QThread wrapper so AI network calls never run on the UI thread.

Every AI feature here is either a background job (weekly summary) or an on-demand
user action (Insights, exercise context, regenerating cue phrasings); none of them
may block the Qt event loop for the seconds an API round trip can take.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QThread, Signal


class AskWorker(QThread):
    """Runs one no-argument callable on a background thread and reports its result."""

    finished_with = Signal(object)

    def __init__(self, work: Callable[[], object], parent=None) -> None:
        super().__init__(parent)
        self._work = work

    def run(self) -> None:
        try:
            result = self._work()
        except Exception:  # noqa: BLE001 - a background thread must never crash
            # the app; every caller already treats None as "this failed."
            result = None
        self.finished_with.emit(result)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_ai_worker.py -v`
Expected: PASS, both tests.

- [ ] **Step 5: Wire it into the weekly summary flow**

In `src/postureguard/app.py`, add to the imports near the top (alongside the existing
`from .weekly_summary import WeeklySummaryGate, build_message`):

```python
from .ai import weekly_summary as ai_weekly_summary
from .ai.worker import AskWorker
```

Replace the existing `_maybe_show_weekly_summary` method with:

```python
    def _maybe_show_weekly_summary(self) -> None:
        if not self.config.weekly_summary_enabled:
            return
        if not self.weekly_summary.last_shown:
            # Nothing to summarize on day one. Seed the anchor so a summary becomes
            # due one interval from now rather than firing on the very first launch.
            self.weekly_summary.mark_shown()
            self.weekly_summary.save_state(paths.weekly_summary_path())
            return
        if not self.weekly_summary.due():
            return
        self.weekly_summary.mark_shown()
        self.weekly_summary.save_state(paths.weekly_summary_path())

        if self.config.ai_weekly_summary_enabled and self.config.ai_api_key:
            payload = ai_weekly_summary.build_stats_payload(self.store)
            if payload is not None:
                api_key = self.config.ai_api_key
                self._weekly_summary_worker = AskWorker(
                    lambda: ai_weekly_summary.generate_message(payload, api_key)
                )
                self._weekly_summary_worker.finished_with.connect(
                    self._on_weekly_summary_ready
                )
                self._weekly_summary_worker.start()
                return

        self._show_weekly_summary(build_message(self.store))

    def _on_weekly_summary_ready(self, message: str | None) -> None:
        # A None from the AI path (no network, refusal, timeout) falls back to the
        # same static one-liner every other launch already uses.
        self._show_weekly_summary(message if message is not None else build_message(self.store))

    def _show_weekly_summary(self, message: str | None) -> None:
        if message is not None:
            self.toast.present("Your week in posture", message, theme.IN_TOLERANCE)
```

- [ ] **Step 6: Manually verify the app still launches**

Run: `.venv/Scripts/python run.py`
Expected: the app starts, the window and tray icon appear, no traceback in the
console. (The weekly summary path is not exercised on every launch — this step is
checking the import and wiring did not break startup, per the project's own
"everything else is verified by running it" convention.)

- [ ] **Step 7: Run the full test suite**

Run: `.venv/Scripts/python -m pytest -v`
Expected: PASS, no regressions in `test_app.py` or elsewhere.

- [ ] **Step 8: Commit**

```bash
git add src/postureguard/ai/worker.py src/postureguard/app.py tests/test_ai_worker.py
git commit -m "Add AskWorker and wire the AI weekly summary into the background"
```

---

### Task 5: Cue-variant cache and generation

**Files:**
- Modify: `src/postureguard/rules.py` (export `FAULT_CUES`)
- Modify: `src/postureguard/paths.py` (add `cue_variants_path`)
- Create: `src/postureguard/ai/cue_variants.py`
- Test: `tests/test_ai_cue_variants.py`

**Interfaces:**
- Consumes: `rules.FaultKind`, `rules.FAULT_TITLES`, `rules.FAULT_ACTIONS` (existing),
  new `rules.FAULT_CUES` (this task), `ai.client.ask` (Task 2), `paths.cue_variants_path`
  (this task).
- Produces: `ai.cue_variants.CueVariantCache` (dataclass with `.variants: dict[str, dict[str, list[str]]]`,
  `.generated_at: str`, `.save(path)`, `.load(path)` classmethod);
  `ai.cue_variants.generate_variants(api_key: str) -> CueVariantCache | None`;
  `ai.cue_variants.pick(cache: CueVariantCache | None, kind: FaultKind, canonical: str, field: str = "cue", today: date | None = None) -> str`.
  All three consumed by Task 6 (controller/overlay/app wiring) and Task 10 (Settings
  "Regenerate" button).

- [ ] **Step 1: Export `FAULT_CUES` from rules.py**

In `src/postureguard/rules.py`, immediately after the existing `_CUES: dict[...] = {...}`
block (the one starting `FaultKind.FORWARD_HEAD: "Pull your chin straight back..."`),
add:

```python
#: Public alias of the canonical cue text, for callers outside this module that need
#: to read (never fire on) the correction strings — e.g. generating alternate
#: phrasings. The rules engine itself always uses `_CUES` directly; this exists so
#: that need doesn't require importing a private name.
FAULT_CUES: dict[FaultKind, str] = _CUES
```

- [ ] **Step 2: Add the cache path**

In `src/postureguard/paths.py`, add after `weekly_summary_path`:

```python
def cue_variants_path() -> Path:
    return data_dir() / "cue_variants.json"
```

- [ ] **Step 3: Write the failing tests**

Create `tests/test_ai_cue_variants.py`:

```python
from datetime import date

from postureguard.ai.cue_variants import CueVariantCache, generate_variants, pick
from postureguard.rules import FaultKind


class TestCueVariantCachePersistence:
    def test_round_trips_through_a_file(self, tmp_path):
        cache = CueVariantCache(
            variants={"forward_head": {"cue": ["Pull back."], "action": ["Pull back"]}},
            generated_at="2026-08-02",
        )
        path = tmp_path / "cue_variants.json"
        cache.save(path)
        loaded = CueVariantCache.load(path)
        assert loaded.variants == cache.variants
        assert loaded.generated_at == "2026-08-02"

    def test_missing_file_loads_an_empty_cache(self, tmp_path):
        cache = CueVariantCache.load(tmp_path / "missing.json")
        assert cache.variants == {}

    def test_corrupt_file_loads_an_empty_cache(self, tmp_path):
        path = tmp_path / "cue_variants.json"
        path.write_text("not json", encoding="utf-8")
        assert CueVariantCache.load(path).variants == {}


class TestPick:
    def test_returns_canonical_when_cache_is_none(self):
        assert pick(None, FaultKind.FORWARD_HEAD, "Pull your chin back.") == "Pull your chin back."

    def test_returns_canonical_when_no_variants_for_the_kind(self):
        cache = CueVariantCache(variants={})
        assert pick(cache, FaultKind.FORWARD_HEAD, "canonical") == "canonical"

    def test_returns_a_cached_variant_deterministically_by_day(self):
        cache = CueVariantCache(
            variants={"forward_head": {"cue": ["Variant A", "Variant B"]}}
        )
        first = pick(cache, FaultKind.FORWARD_HEAD, "canonical", today=date(2026, 8, 2))
        again = pick(cache, FaultKind.FORWARD_HEAD, "canonical", today=date(2026, 8, 2))
        assert first == again
        assert first in ("Variant A", "Variant B")

    def test_different_days_can_pick_different_variants(self):
        cache = CueVariantCache(
            variants={"forward_head": {"cue": ["Variant A", "Variant B"]}}
        )
        day_one = pick(cache, FaultKind.FORWARD_HEAD, "canonical", today=date(2026, 8, 2))
        day_two = pick(cache, FaultKind.FORWARD_HEAD, "canonical", today=date(2026, 8, 3))
        assert {day_one, day_two} == {"Variant A", "Variant B"}

    def test_reads_the_action_field_separately_from_cue(self):
        cache = CueVariantCache(
            variants={"forward_head": {"cue": ["cue variant"], "action": ["action variant"]}}
        )
        assert pick(cache, FaultKind.FORWARD_HEAD, "x", field="action") == "action variant"


class TestGenerateVariants:
    def test_returns_none_when_ask_fails(self, monkeypatch):
        monkeypatch.setattr("postureguard.ai.cue_variants.ask", lambda *a, **k: None)
        assert generate_variants("sk-ant-test") is None

    def test_returns_none_on_invalid_json(self, monkeypatch):
        monkeypatch.setattr("postureguard.ai.cue_variants.ask", lambda *a, **k: "not json")
        assert generate_variants("sk-ant-test") is None

    def test_parses_a_valid_response_into_a_cache(self, monkeypatch):
        import json

        response = json.dumps(
            {"forward_head": {"cue": ["A", "B"], "action": ["a", "b"]}}
        )
        monkeypatch.setattr("postureguard.ai.cue_variants.ask", lambda *a, **k: response)
        cache = generate_variants("sk-ant-test")
        assert cache is not None
        assert cache.variants["forward_head"]["cue"] == ["A", "B"]
        assert cache.generated_at
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_ai_cue_variants.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'postureguard.ai.cue_variants'`

- [ ] **Step 5: Write the implementation**

Create `src/postureguard/ai/cue_variants.py`:

```python
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
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_ai_cue_variants.py -v`
Expected: PASS, all tests.

- [ ] **Step 7: Run the full test suite to check `FAULT_CUES` didn't break `rules.py`**

Run: `.venv/Scripts/python -m pytest tests/test_rules.py -v`
Expected: PASS, no changes in behavior (this was a pure export addition).

- [ ] **Step 8: Commit**

```bash
git add src/postureguard/rules.py src/postureguard/paths.py \
    src/postureguard/ai/cue_variants.py tests/test_ai_cue_variants.py
git commit -m "Add ai/cue_variants.py: cached alternate phrasings for the live overlay"
```

---

### Task 6: Wire cue variants into the toast and mini window

**Files:**
- Modify: `src/postureguard/ui/controller.py` (`__init__`, `_tick`, new
  `reload_cue_variants` method)
- Modify: `src/postureguard/overlay.py` (`ViewModel`, two paint call sites)
- Modify: `src/postureguard/app.py` (`_update_mini`)
- Test: `tests/test_controller.py`, `tests/test_overlay.py` (or the closest existing
  overlay test file — see Step 1)

**Interfaces:**
- Consumes: `ai.cue_variants.CueVariantCache`, `.pick` (Task 5),
  `paths.cue_variants_path` (Task 5).
- Produces: `MonitorController.cue_variants: CueVariantCache`,
  `MonitorController.reload_cue_variants() -> None` (consumed by Task 10's "Regenerate"
  button); `overlay.ViewModel.cue_text: str`, `.action_text: str` (empty string means
  "use the fault's own `.cue`/`.action`").

- [ ] **Step 1: Confirm the existing overlay test file**

Run: `ls tests | grep -i overlay` (or `Get-ChildItem tests | Select-String overlay` on
PowerShell). If a file like `tests/test_overlay.py` exists, add the new test there
under a fitting class. If none exists, create `tests/test_overlay_view_model.py` with
the test in Step 2 — either way, the test only needs `ViewModel` and `Fault`, no Qt
widgets, so it does not need a `QApplication` fixture.

- [ ] **Step 2: Write the failing tests**

Add (to whichever file Step 1 identified):

```python
from postureguard.overlay import ViewModel
from postureguard.rules import Fault, FaultKind


class TestViewModelCueOverride:
    def test_defaults_to_empty_override(self):
        model = ViewModel()
        assert model.cue_text == ""
        assert model.action_text == ""

    def test_carries_an_explicit_override(self):
        model = ViewModel(cue_text="Custom cue.", action_text="Custom action")
        assert model.cue_text == "Custom cue."
        assert model.action_text == "Custom action"
```

Add to `tests/test_controller.py` (following that file's existing fixture/class
conventions — construct a `MonitorController(Config(), SessionStore())` the way other
tests in that file already do, and inspect `.cue_variants` without starting the camera):

```python
class TestCueVariants:
    def test_starts_with_an_empty_cache_when_no_file_exists(self, tmp_path, monkeypatch):
        monkeypatch.setattr("postureguard.ui.controller.paths.data_dir", lambda: tmp_path)
        controller = MonitorController(Config(), SessionStore())
        assert controller.cue_variants.variants == {}

    def test_reload_cue_variants_picks_up_a_saved_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr("postureguard.ui.controller.paths.data_dir", lambda: tmp_path)
        controller = MonitorController(Config(), SessionStore())
        from postureguard.ai.cue_variants import CueVariantCache
        from postureguard import paths

        CueVariantCache(variants={"forward_head": {"cue": ["X"]}}).save(
            paths.cue_variants_path()
        )
        controller.reload_cue_variants()
        assert controller.cue_variants.variants["forward_head"]["cue"] == ["X"]
```

(Check the top of `tests/test_controller.py` for the exact existing imports of
`MonitorController`, `Config`, and `SessionStore` and reuse them rather than
duplicating — this task only adds the new test class.)

- [ ] **Step 3: Run the new tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_controller.py -k CueVariants -v`
Expected: FAIL — `MonitorController` has no `cue_variants` attribute yet.

- [ ] **Step 4: Update `ViewModel` in `overlay.py`**

In `src/postureguard/overlay.py`, in the `ViewModel` dataclass (the block starting
`metrics: PostureMetrics = field(default_factory=PostureMetrics)`), add two fields
after `held_seconds: float = 0.0`:

```python
    #: A pre-resolved alternate phrasing for the primary fault's cue/action, or "" to
    #: use `fault.cue`/`fault.action` unchanged. Resolved once per app.py update
    #: (see `_update_mini`), never inside a paint method — repainting must never
    #: re-roll the text, or it would flicker.
    cue_text: str = ""
    action_text: str = ""
```

Then find the paint call site that reads `text = fault.action` (the collapsed-bar
painter) and change it to:

```python
        if fault is not None:
            painter.setPen(theme.BONE)
            text = self.model.action_text or fault.action
```

And find the paint call site that passes `fault.cue,` as the last argument to
`painter.drawText(...)` (the expanded panel's cue text) and change that argument to:

```python
            self.model.cue_text or fault.cue,
```

- [ ] **Step 5: Wire the cache into `MonitorController`**

In `src/postureguard/ui/controller.py`, add to the imports:

```python
from ..ai.cue_variants import CueVariantCache
from ..ai.cue_variants import pick as pick_cue_variant
```

In `__init__`, after `self.backoff = SnoozeBackoff.load(paths.snooze_backoff_path())`,
add:

```python
        self.cue_variants = CueVariantCache.load(paths.cue_variants_path())
```

Add a new method near `recalibrate` (in the `# --- user actions ---` section):

```python
    def reload_cue_variants(self) -> None:
        """Pick up a freshly regenerated cache without restarting the pipeline."""
        self.cue_variants = CueVariantCache.load(paths.cue_variants_path())
```

In `_tick`, replace:

```python
        if intervention.toast_now and intervention.fault is not None:
            self.toast_requested.emit(intervention.fault.title, intervention.fault.cue)
```

with:

```python
        if intervention.toast_now and intervention.fault is not None:
            fault = intervention.fault
            cue = (
                pick_cue_variant(self.cue_variants, fault.kind, fault.cue)
                if self.config.ai_cue_variants_enabled
                else fault.cue
            )
            self.toast_requested.emit(fault.title, cue)
```

- [ ] **Step 6: Wire the resolved text into the mini window in `app.py`**

In `src/postureguard/app.py`, add to the imports:

```python
from .ai.cue_variants import pick as pick_cue_variant
```

Replace the `_update_mini` method with:

```python
    def _update_mini(self, state) -> None:
        if not self.mini.isVisible():
            return
        fault = state.reading.faults[0] if state.reading.faults else None
        cue_text = ""
        action_text = ""
        if fault is not None and self.config.ai_cue_variants_enabled:
            cue_text = pick_cue_variant(self.controller.cue_variants, fault.kind, fault.cue)
            action_text = pick_cue_variant(
                self.controller.cue_variants, fault.kind, fault.action, field="action"
            )
        self.mini.show_model(
            ViewModel(
                metrics=state.reading.metrics,
                faults=state.reading.faults,
                status=state.reading.status,
                message=state.reading.message,
                urgency=int(state.intervention.level),
                held_seconds=state.intervention.held_seconds,
                cue_text=cue_text,
                action_text=action_text,
            )
        )
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_controller.py tests/test_overlay.py -v`
(substitute the actual overlay test filename from Step 1 if different)
Expected: PASS, including the new tests.

- [ ] **Step 8: Run the full test suite**

Run: `.venv/Scripts/python -m pytest -v`
Expected: PASS, no regressions — in particular `test_overlay.py`'s (or equivalent)
existing painting/behavior tests, since `cue_text`/`action_text` default to `""` and
`"" or fault.cue` reproduces `fault.cue` exactly.

- [ ] **Step 9: Manually verify with the preview tool**

Run: `.venv/Scripts/python tools/preview_overlay.py`
Expected: renders the compact overlay states exactly as before — `ai_cue_variants_enabled`
defaults to `False` and no cache file exists in a clean environment, so every fault
still shows its canonical `.cue`/`.action` text.

- [ ] **Step 10: Commit**

```bash
git add src/postureguard/ui/controller.py src/postureguard/overlay.py src/postureguard/app.py \
    tests/test_controller.py
git commit -m "Wire cue variants into the toast and mini window, gated and defaulted off"
```

---

### Task 7: AI exercise context

**Files:**
- Create: `src/postureguard/ai/exercise_context.py`
- Test: `tests/test_ai_exercise_context.py`

**Interfaces:**
- Consumes: `rules.FAULT_TITLES`, `rules.FaultKind` (existing), `session.SessionStore`
  (existing), `ai.client.ask` (Task 2).
- Produces: `ai.exercise_context.generate_intro(dominant: FaultKind | None, store: SessionStore, api_key: str) -> str | None`,
  consumed by Task 8.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ai_exercise_context.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_ai_exercise_context.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'postureguard.ai.exercise_context'`

- [ ] **Step 3: Write the implementation**

Create `src/postureguard/ai/exercise_context.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_ai_exercise_context.py -v`
Expected: PASS, all 3 tests.

- [ ] **Step 5: Commit**

```bash
git add src/postureguard/ai/exercise_context.py tests/test_ai_exercise_context.py
git commit -m "Add ai/exercise_context.py: personalized framing over the existing routine"
```

---

### Task 8: Wire exercise context into the Exercises screen

**Files:**
- Modify: `src/postureguard/ui/screens/exercises.py` (`ExercisesScreen`)
- Modify: `src/postureguard/app.py` (`_on_break_due`, imports)
- Test: `tests/test_ui_logic.py` (or wherever `ExercisesScreen` is already tested —
  see Step 1)

**Interfaces:**
- Consumes: `ai.exercise_context.generate_intro` (Task 7), `ai.worker.AskWorker`
  (Task 4).
- Produces: `ExercisesScreen.set_ai_intro(text: str | None) -> None`.

- [ ] **Step 1: Locate existing `ExercisesScreen` tests**

Run: `Select-String -Path tests\*.py -Pattern "ExercisesScreen"` (or
`grep -rl ExercisesScreen tests/` in Bash) to find which test file already constructs
`ExercisesScreen`. Add the new test there, following its existing fixture pattern for
a `QApplication` instance and a seeded `SessionStore`.

- [ ] **Step 2: Write the failing test**

Add to the file found in Step 1:

```python
class TestAiIntro:
    def test_hidden_by_default(self):
        with SessionStore() as store:
            screen = ExercisesScreen(store)
            assert screen.ai_intro.isVisible() is False

    def test_shown_when_set(self):
        with SessionStore() as store:
            screen = ExercisesScreen(store)
            screen.set_ai_intro("Because you've been craning forward.")
            assert screen.ai_intro.isVisible() is True
            assert screen.ai_intro.text() == "Because you've been craning forward."

    def test_cleared_by_none(self):
        with SessionStore() as store:
            screen = ExercisesScreen(store)
            screen.set_ai_intro("some text")
            screen.set_ai_intro(None)
            assert screen.ai_intro.isVisible() is False

    def test_refresh_clears_a_stale_intro(self):
        with SessionStore() as store:
            screen = ExercisesScreen(store)
            screen.set_ai_intro("stale text from a previous break")
            screen.refresh()
            assert screen.ai_intro.isVisible() is False
```

(Add the necessary `from postureguard.ui.screens.exercises import ExercisesScreen` and
`from postureguard.session import SessionStore` imports if the file doesn't already
have them — check first.)

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -k TestAiIntro -v`
Expected: FAIL — `ExercisesScreen` has no `ai_intro` attribute yet.

- [ ] **Step 4: Add the widget to `ExercisesScreen`**

In `src/postureguard/ui/screens/exercises.py`, in `ExercisesScreen.__init__`, find:

```python
        self.reason = Card("Why these")
        self._reason_text = label("", "Body")
        self._reason_text.setWordWrap(True)
        self.reason.add(self._reason_text)
        layout.addWidget(self.reason)
```

and add the AI intro label right after `self.reason.add(self._reason_text)`:

```python
        self.reason = Card("Why these")
        self._reason_text = label("", "Body")
        self._reason_text.setWordWrap(True)
        self.reason.add(self._reason_text)
        self.ai_intro = label("", "Body")
        self.ai_intro.setWordWrap(True)
        self.ai_intro.setVisible(False)
        self.reason.add(self.ai_intro)
        layout.addWidget(self.reason)
```

Add a new method anywhere in the class (e.g. right after `_toggle_all`):

```python
    def set_ai_intro(self, text: str | None) -> None:
        if text:
            self.ai_intro.setText(text)
            self.ai_intro.setVisible(True)
        else:
            self.ai_intro.setVisible(False)
```

In `refresh`, add `self.set_ai_intro(None)` as the very first line of the method body
(before `dominant = self.store.dominant_fault(days=7)`), so switching routines or
toggling "Show all" clears any stale intro from a previous break.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -k TestAiIntro -v`
Expected: PASS, all 4 tests.

- [ ] **Step 6: Wire it from `app.py`**

Add to the imports:

```python
from .ai import exercise_context as ai_exercise_context
```

Replace `_on_break_due` with:

```python
    def _on_break_due(self, routine) -> None:
        self.toast.present(
            "Time for a break",
            f"{routine.reason} {len(routine.exercises)} exercises, "
            f"about {routine.seconds // 60} minutes.",
        )
        self.exercises.refresh()
        if self.config.ai_exercise_context_enabled and self.config.ai_api_key:
            dominant = self.store.dominant_fault(days=7)
            api_key = self.config.ai_api_key
            self._exercise_context_worker = AskWorker(
                lambda: ai_exercise_context.generate_intro(dominant, self.store, api_key)
            )
            self._exercise_context_worker.finished_with.connect(self.exercises.set_ai_intro)
            self._exercise_context_worker.start()
```

- [ ] **Step 7: Run the full test suite**

Run: `.venv/Scripts/python -m pytest -v`
Expected: PASS, no regressions.

- [ ] **Step 8: Commit**

```bash
git add src/postureguard/ui/screens/exercises.py src/postureguard/app.py
git commit -m "Add AI exercise-routine framing, shown above the unchanged exercise list"
```

(Include the test file modified in Step 4 if it is not already staged from Step 2's edit.)

---

### Task 9: Insights screen

**Files:**
- Create: `src/postureguard/ai/insights.py`
- Create: `src/postureguard/ui/screens/insights.py`
- Modify: `src/postureguard/ui/window.py` (`SCREENS` tuple)
- Modify: `src/postureguard/app.py` (construct and wire the screen)
- Test: `tests/test_ai_insights.py`, `tests/test_ui_logic.py`

**Interfaces:**
- Consumes: `ai.weekly_summary.build_stats_payload` (Task 3), `ai.client.ask` (Task 2),
  `ai.worker.AskWorker` (Task 4).
- Produces: `ai.insights.answer_question(payload: dict, question: str, api_key: str) -> str | None`;
  `InsightsScreen` with `.asked = Signal(str)`, `.stats_payload() -> dict | None`,
  `.show_answer(text: str | None) -> None`, `.show_asking() -> None`,
  `.show_no_key() -> None`.

- [ ] **Step 1: Write the failing test for `ai/insights.py`**

Create `tests/test_ai_insights.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_ai_insights.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'postureguard.ai.insights'`

- [ ] **Step 3: Write `ai/insights.py`**

Create `src/postureguard/ai/insights.py`:

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_ai_insights.py -v`
Expected: PASS, both tests.

- [ ] **Step 5: Write the failing test for `InsightsScreen`**

Add to `tests/test_ui_logic.py` (reusing that file's existing `QApplication` fixture
pattern — check its top-of-file `qapp`-style fixture and follow the same shape):

```python
class TestInsightsScreen:
    def test_asking_a_question_emits_it(self, qapp):
        from postureguard.session import SessionStore
        from postureguard.ui.screens.insights import InsightsScreen

        with SessionStore() as store:
            screen = InsightsScreen(store)
            received = []
            screen.asked.connect(received.append)
            screen.question.setText("why do I slouch?")
            screen._ask()
            assert received == ["why do I slouch?"]

    def test_blank_question_does_not_emit(self, qapp):
        from postureguard.session import SessionStore
        from postureguard.ui.screens.insights import InsightsScreen

        with SessionStore() as store:
            screen = InsightsScreen(store)
            received = []
            screen.asked.connect(received.append)
            screen.question.setText("   ")
            screen._ask()
            assert received == []

    def test_show_answer_re_enables_the_form(self, qapp):
        from postureguard.session import SessionStore
        from postureguard.ui.screens.insights import InsightsScreen

        with SessionStore() as store:
            screen = InsightsScreen(store)
            screen.show_asking()
            assert screen.ask_button.isEnabled() is False
            screen.show_answer("an answer")
            assert screen.ask_button.isEnabled() is True
            assert screen.answer.text() == "an answer"

    def test_show_answer_none_reports_the_failure(self, qapp):
        from postureguard.session import SessionStore
        from postureguard.ui.screens.insights import InsightsScreen

        with SessionStore() as store:
            screen = InsightsScreen(store)
            screen.show_answer(None)
            assert "Settings" in screen.answer.text()
```

(If `tests/test_ui_logic.py`'s fixture for `QApplication` is not named `qapp`, use
whatever name that file already defines — check the top of the file first, per the
existing `SettingsScreen(...)` tests in that same file.)

- [ ] **Step 6: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_ui_logic.py -k Insights -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'postureguard.ui.screens.insights'`

- [ ] **Step 7: Write `ui/screens/insights.py`**

Create `src/postureguard/ui/screens/insights.py`:

```python
"""Insights: ask a question about your posture history, answered by the Claude API.

Read-only over the same aggregates History already shows. Never touches the live
detection loop, the camera, or the rules engine — the only network call this screen
can trigger is an explicit, user-initiated question.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QVBoxLayout, QWidget
from PySide6.QtCore import Signal

from ... import theme
from ...ai.weekly_summary import build_stats_payload
from ...session import SessionStore
from ..widgets import Card, PageHeader, button, label, plain

S = theme.SPACE
#: Wider than the weekly summary's 7 days — Insights is for "what's been going on
#: lately," not just last week.
INSIGHTS_DAYS = 90


class InsightsScreen(QWidget):
    #: Carries the question text; the app owns the actual API call so this widget
    #: never imports the network client itself.
    asked = Signal(str)

    def __init__(self, store: SessionStore) -> None:
        super().__init__()
        self.store = store

        layout = QVBoxLayout(self)
        layout.setContentsMargins(S["xl"], S["xl"], S["xl"], S["xl"])
        layout.setSpacing(S["lg"])
        layout.addWidget(PageHeader("Insights", "Ask a question about your posture history."))

        card = Card("Ask")
        row = QHBoxLayout()
        self.question = QLineEdit()
        self.question.setPlaceholderText("e.g. why do I slouch more after 2pm?")
        self.question.returnPressed.connect(self._ask)
        row.addWidget(self.question, 1)
        self.ask_button = button("Ask")
        self.ask_button.clicked.connect(self._ask)
        row.addWidget(self.ask_button)
        card.add(plain(row))

        self.answer = label("", "Body")
        self.answer.setWordWrap(True)
        card.add(self.answer)
        layout.addWidget(card)
        layout.addStretch(1)

    def _ask(self) -> None:
        text = self.question.text().strip()
        if not text:
            return
        self.asked.emit(text)

    def stats_payload(self) -> dict | None:
        return build_stats_payload(self.store, days=INSIGHTS_DAYS)

    def _set_ready(self, ready: bool) -> None:
        self.ask_button.setEnabled(ready)
        self.question.setEnabled(ready)

    def show_asking(self) -> None:
        self._set_ready(False)
        self.answer.setText("Thinking…")

    def show_answer(self, text: str | None) -> None:
        self._set_ready(True)
        self.answer.setText(
            text
            if text is not None
            else "Couldn't reach the API. Check the key in Settings and try again."
        )

    def show_no_key(self) -> None:
        self.answer.setText("Add an API key in Settings → AI features to use Insights.")
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_ui_logic.py -k Insights -v`
Expected: PASS, all 4 tests.

- [ ] **Step 9: Add the sidebar entry**

In `src/postureguard/ui/window.py`, change:

```python
SCREENS = (
    ("live", "Live"),
    ("history", "History"),
    ("exercises", "Exercises"),
    ("settings", "Settings"),
)
```

to:

```python
SCREENS = (
    ("live", "Live"),
    ("history", "History"),
    ("exercises", "Exercises"),
    ("insights", "Insights"),
    ("settings", "Settings"),
)
```

- [ ] **Step 10: Wire the screen into `app.py`**

Add to the imports:

```python
from .ai import insights as ai_insights
from .ui.screens.insights import InsightsScreen
```

In `Application.__init__`, right after `self.exercises = ExercisesScreen(self.store)`,
add:

```python
        self.insights = InsightsScreen(self.store)
```

Right after `self.window.add_screen("exercises", self.exercises)`, add:

```python
        self.window.add_screen("insights", self.insights)
```

In `_connect`, add near the other screen-signal connections (e.g. right after the
`self.exercises.break_taken.connect(...)` line):

```python
        self.insights.asked.connect(self._on_insights_asked)
```

Add a new handler method near `_on_break_due`:

```python
    def _on_insights_asked(self, question: str) -> None:
        if not self.config.ai_api_key:
            self.insights.show_no_key()
            return
        payload = self.insights.stats_payload()
        if payload is None:
            self.insights.show_answer(
                "Not enough tracked history yet to answer questions — check back after "
                "a few days of use."
            )
            return
        self.insights.show_asking()
        api_key = self.config.ai_api_key
        self._insights_worker = AskWorker(
            lambda: ai_insights.answer_question(payload, question, api_key)
        )
        self._insights_worker.finished_with.connect(self.insights.show_answer)
        self._insights_worker.start()
```

- [ ] **Step 11: Run the full test suite**

Run: `.venv/Scripts/python -m pytest -v`
Expected: PASS, no regressions — in particular any existing `window.py`/sidebar tests
that assert on the number or order of nav entries (search for `SCREENS` usage in
tests first if a failure appears here, and update the expected count/order to match).

- [ ] **Step 12: Manually verify**

Run: `.venv/Scripts/python run.py`
Expected: an "Insights" entry appears in the sidebar; clicking it shows the question
box; typing a question and pressing Ask (with no API key configured) shows the
"Add an API key..." message without crashing.

- [ ] **Step 13: Commit**

```bash
git add src/postureguard/ai/insights.py src/postureguard/ui/screens/insights.py \
    src/postureguard/ui/window.py src/postureguard/app.py \
    tests/test_ai_insights.py tests/test_ui_logic.py
git commit -m "Add the Insights screen: on-demand Q&A over posture history aggregates"
```

---

### Task 10: Settings — AI panel (API key, four toggles, regenerate button)

**Files:**
- Create: `src/postureguard/ui/screens/settings/ai.py`
- Modify: `src/postureguard/ui/screens/settings/screen.py` (`SettingsScreen`)
- Modify: `src/postureguard/app.py` (wire the regenerate signal)
- Test: `tests/test_ui_logic.py`

**Interfaces:**
- Consumes: `Config.ai_api_key` and the four `ai_*_enabled` fields (Task 1),
  `ai.cue_variants.generate_variants` (Task 5), `ai.worker.AskWorker` (Task 4),
  `MonitorController.reload_cue_variants` (Task 6).
- Produces: `AiPanel` with `.changed = Signal()`,
  `.regenerate_cue_variants_requested = Signal()`; `SettingsScreen.ai: AiPanel`;
  `SettingsScreen.regenerate_cue_variants_requested = Signal()` (relayed).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ui_logic.py` (near the existing `SettingsScreen(...)` tests, using
that file's existing `Config` import):

```python
class TestAiPanel:
    def test_reflects_the_configured_key_and_toggles(self, qapp):
        from postureguard.config import Config
        from postureguard.ui.screens.settings.screen import SettingsScreen

        config = Config(
            ai_api_key="sk-ant-test",
            ai_weekly_summary_enabled=True,
            ai_insights_enabled=True,
            ai_cue_variants_enabled=True,
            ai_exercise_context_enabled=True,
        )
        screen = SettingsScreen(config)
        assert screen.ai.api_key.text() == "sk-ant-test"
        assert screen.ai.weekly_summary.isChecked() is True
        assert screen.ai.insights.isChecked() is True
        assert screen.ai.cue_variants.isChecked() is True
        assert screen.ai.exercise_context.isChecked() is True

    def test_emitted_config_carries_the_ai_fields(self, qapp):
        from postureguard.config import Config
        from postureguard.ui.screens.settings.screen import SettingsScreen

        screen = SettingsScreen(Config())
        received = []
        screen.changed.connect(received.append)
        screen.ai.api_key.setText("sk-ant-new")
        screen.ai.api_key.editingFinished.emit()
        assert received
        assert received[-1].ai_api_key == "sk-ant-new"

    def test_regenerate_button_emits_a_dedicated_signal(self, qapp):
        from postureguard.config import Config
        from postureguard.ui.screens.settings.screen import SettingsScreen

        screen = SettingsScreen(Config())
        received = []
        screen.regenerate_cue_variants_requested.connect(lambda: received.append(True))
        screen.ai.regenerate.click()
        assert received == [True]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_ui_logic.py -k AiPanel -v`
Expected: FAIL — `SettingsScreen` has no `ai` attribute yet.

- [ ] **Step 3: Write `settings/ai.py`**

Create `src/postureguard/ui/screens/settings/ai.py`:

```python
"""The AI card: opt-in Claude-API-backed features, and the one key they all share."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QLineEdit

from ...widgets import Card, button, label
from .rows import Row


class AiPanel(Card):
    changed = Signal()
    regenerate_cue_variants_requested = Signal()

    def __init__(self, config) -> None:
        super().__init__("AI features")
        self.add(
            label(
                "Off by default. Each toggle below sends only aggregate numbers — "
                "never video or images — to Anthropic's API when it fires.",
                "Body",
            )
        )

        self.api_key = QLineEdit(config.ai_api_key)
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("sk-ant-…")
        self.add(Row("Anthropic API key", "Required by every toggle below.", self.api_key))

        self.weekly_summary = QCheckBox("Enabled")
        self.weekly_summary.setChecked(config.ai_weekly_summary_enabled)
        self.add(
            Row(
                "AI weekly summary",
                "A richer weekly note, sent your daily scores, worst hour, and fault "
                "minutes for the week.",
                self.weekly_summary,
            )
        )

        self.insights = QCheckBox("Enabled")
        self.insights.setChecked(config.ai_insights_enabled)
        self.add(
            Row(
                "Insights screen",
                "Ask questions about your history. Sends your question and the same "
                "aggregates as the weekly summary.",
                self.insights,
            )
        )

        self.cue_variants = QCheckBox("Enabled")
        self.cue_variants.setChecked(config.ai_cue_variants_enabled)
        self.add(
            Row(
                "Varied correction phrasing",
                "Alternate wordings of the fixed correction text, regenerated at most "
                "once a day.",
                self.cue_variants,
            )
        )
        self.regenerate = button("Regenerate phrasings now")
        self.regenerate.clicked.connect(self.regenerate_cue_variants_requested)
        self.add(Row("", "Uses today's key and toggle above.", self.regenerate))

        self.exercise_context = QCheckBox("Enabled")
        self.exercise_context.setChecked(config.ai_exercise_context_enabled)
        self.add(
            Row(
                "Exercise context",
                "A short AI-written note on why this routine, added above the fixed "
                "exercise list. Never changes which exercises appear.",
                self.exercise_context,
            )
        )

        self.api_key.editingFinished.connect(self.changed)
        self.weekly_summary.toggled.connect(self.changed)
        self.insights.toggled.connect(self.changed)
        self.cue_variants.toggled.connect(self.changed)
        self.exercise_context.toggled.connect(self.changed)
```

- [ ] **Step 4: Wire it into `SettingsScreen`**

In `src/postureguard/ui/screens/settings/screen.py`, add to the imports:

```python
from .ai import AiPanel
```

Add a class-level signal alongside the existing ones:

```python
class SettingsScreen(QWidget):
    changed = Signal(object)  # Config
    recalibrate_requested = Signal()
    regenerate_cue_variants_requested = Signal()
```

In `__init__`, right after the `self.privacy = PrivacyPanel(config, store)` /
`layout.addWidget(self.privacy)` block and before `layout.addStretch(1)`, add:

```python
        self.ai = AiPanel(config)
        self.ai.changed.connect(self._emit)
        self.ai.regenerate_cue_variants_requested.connect(
            self.regenerate_cue_variants_requested
        )
        layout.addWidget(self.ai)
```

In `_emit`, add the five new keyword arguments to the `Config(...)` constructor call
(anywhere in the argument list — e.g. right after `theme_mode=self.appearance.theme_mode.currentData() or "dark",`):

```python
            ai_api_key=self.ai.api_key.text().strip(),
            ai_weekly_summary_enabled=self.ai.weekly_summary.isChecked(),
            ai_insights_enabled=self.ai.insights.isChecked(),
            ai_cue_variants_enabled=self.ai.cue_variants.isChecked(),
            ai_exercise_context_enabled=self.ai.exercise_context.isChecked(),
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_ui_logic.py -k AiPanel -v`
Expected: PASS, all 3 tests.

- [ ] **Step 6: Wire the regenerate button in `app.py`**

Add to the imports:

```python
from .ai import cue_variants as ai_cue_variants
```

In `_connect`, add near the other `self.settings.*` connections:

```python
        self.settings.regenerate_cue_variants_requested.connect(
            self._on_regenerate_cue_variants
        )
```

Add new handler methods near `_on_recalibrate_from_settings`:

```python
    def _on_regenerate_cue_variants(self) -> None:
        if not self.config.ai_api_key:
            self.toast.present("AI features", "Add an API key first.", theme.WARNING)
            return
        api_key = self.config.ai_api_key
        self._cue_variant_worker = AskWorker(lambda: ai_cue_variants.generate_variants(api_key))
        self._cue_variant_worker.finished_with.connect(self._on_cue_variants_ready)
        self._cue_variant_worker.start()

    def _on_cue_variants_ready(self, cache) -> None:
        if cache is None:
            self.toast.present(
                "AI features", "Couldn't generate phrasings — check the API key.", theme.WARNING
            )
            return
        cache.save(paths.cue_variants_path())
        self.controller.reload_cue_variants()
        self.toast.present("AI features", "Correction phrasing refreshed.", theme.IN_TOLERANCE)
```

- [ ] **Step 7: Run the full test suite**

Run: `.venv/Scripts/python -m pytest -v`
Expected: PASS, no regressions.

- [ ] **Step 8: Manually verify**

Run: `.venv/Scripts/python run.py`
Expected: Settings shows a new "AI features" card at the bottom with the key field
and four toggles, all unchecked and the key blank on a fresh install; entering a key
and clicking "Regenerate phrasings now" without network access shows the
"Couldn't generate phrasings" toast rather than crashing.

- [ ] **Step 9: Commit**

```bash
git add src/postureguard/ui/screens/settings/ai.py src/postureguard/ui/screens/settings/screen.py \
    src/postureguard/app.py tests/test_ui_logic.py
git commit -m "Add the Settings AI panel: API key, four toggles, regenerate button"
```

---

### Task 11: README documentation

**Files:**
- Modify: `README.md`

**Interfaces:**
- None — documentation only.

- [ ] **Step 1: Add an AI features section**

In `README.md`, add a new section after `## Privacy` (at the end of the file):

```markdown
## AI features (optional)

Four features can optionally call the Claude API to generate content — a richer
weekly summary, an on-demand Insights screen, varied phrasing of the fixed
correction text, and a short personalized note above your exercise routine. All four
are off by default and require an Anthropic API key entered in Settings.

Each one sends only aggregate numbers — daily scores, the worst hour, minutes spent
in each named fault — or, for Insights, the question you type. None of them ever see
a camera frame, a landmark, or a per-frame metric; the privacy guarantee above is
unchanged. The real-time detection and correction loop has no network dependency
whether or not any of these are turned on.
```

- [ ] **Step 2: Verify the rendered file reads correctly**

Run: `.venv/Scripts/python -c "print(open('README.md', encoding='utf-8').read()[-1500:])"`
Expected: the new section appears at the end, after the existing `## Privacy` section,
with no broken Markdown.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "Document the optional AI features and what data they send"
```

---

## Final verification

- [ ] Run the entire suite once more end to end: `.venv/Scripts/python -m pytest -v`
- [ ] Run `ruff check src tests`: expect no new lint errors introduced by this plan.
- [ ] Launch the app (`.venv/Scripts/python run.py`), open Settings, confirm the AI
      panel is present with everything off/blank, open Insights and Exercises and
      confirm both work exactly as before with no key configured.
