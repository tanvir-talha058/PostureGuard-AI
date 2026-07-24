# PostureGuard-AI — Design Spec

Date: 2026-07-25

## Purpose

A desk-work posture tool that does more than notice bad posture: it traces posture live,
names the specific fault, tells you what to do about it, and escalates if you ignore it.

Everything runs locally on the user's machine. Camera frames are never written to disk and
never leave the device; only derived scalar metrics are persisted.

## Scope

**In scope:** four fault types (forward head, spine flexion, screen too close, lateral
tilt), a four-stage intervention ladder, personal calibration with intra-session drift
tracking, session history, stretch breaks, tray-resident operation.

**Out of scope:** cloud sync, multi-user accounts, mobile, video recording, medical or
diagnostic claims.

## Stack

Python 3.10+ · MediaPipe Pose Landmarker · OpenCV (capture only) · PySide6 (overlay, tray,
dim layer) · SQLite · pytest.

## The head-on camera problem

A desk webcam faces the user head-on. Forward-head posture is translation *toward* the
camera, so the clinical side-view craniovertebral angle is not directly observable.
Porting side-view formulas to a front view is the common failure mode in this class of tool.

Forward head is therefore inferred from two front-view signals in combination:

| Metric | Definition | Behavior |
|---|---|---|
| `head_shoulder_gap` | `(shoulder_mid_y − ear_mid_y) / shoulder_width` | falls as the head cranes forward-and-down |
| `face_scale` | `inter_ocular_dist / shoulder_width` | rises as the head translates toward the screen |
| `screen_distance` | `inter_ocular_dist` in raw image units | rises when the whole torso leans in |
| `shoulder_roll` | angle of the shoulder line from horizontal | non-zero on uneven shoulders |
| `eye_roll` | angle of the eye line from horizontal | non-zero on head tilt |
| `torso_angle` | angle of `shoulder_mid → hip_mid` from vertical | rises with spine flexion |

The fault fires only when `head_shoulder_gap` falls **and** `face_scale` rises relative to
baseline. Either signal alone is ambiguous: pushing the chair back changes both scales
together, and the ratio pair is what separates head translation from body distance.

Hip landmarks are frequently occluded by a desk. When hip visibility is below threshold,
`torso_angle` is reported as unavailable rather than as a garbage value, and the rules
engine skips the spine-flexion check instead of guessing.

## Architecture

```
capture → pose → metrics → rules → escalation → {overlay, alerts}
                     │        │
              calibration   session
```

| Module | Responsibility | Depends on |
|---|---|---|
| `capture` | threaded webcam reader; drops stale frames so latency cannot accumulate | OpenCV |
| `pose` | MediaPipe wrapper producing a `Landmarks` dataclass with per-joint visibility | MediaPipe |
| `metrics` | **pure**: `Landmarks → PostureMetrics` | none |
| `calibration` | 5s good-posture capture → `Baseline` (JSON); rolling drift tracker | metrics |
| `rules` | **pure**: `PostureMetrics + Baseline → list[Fault]`; owns debounce + hysteresis | metrics |
| `escalation` | fault stream over time → intervention level; cooldowns, snooze | rules |
| `overlay` | always-on-top Qt window: skeleton, faulty joints in red, cue text | PySide6 |
| `alerts` | desktop toast, full-screen dim layer | PySide6 |
| `stretches` | break timer; exercise selected by dominant fault | session |
| `session` | SQLite per-second fault log → daily stats | sqlite3 |
| `app` | wiring, tray icon, config | all |

`metrics` and `rules` carry the real logic and have no camera or UI dependency, so they are
unit-testable from fixture landmark sets. This is where TDD applies; the rest is verified by
running the app.

## Signal conditioning

Raw per-frame threshold checks flicker. Three mechanisms prevent that:

- **Smoothing** — EWMA on landmark positions, median filter on metrics.
- **Debounce** — a fault must persist N consecutive frames before it is emitted.
- **Hysteresis** — a fault begins at threshold `T` and only clears below `0.8·T`.
- **Cooldowns** — escalation cannot retrigger immediately after a fix-then-reslip.

## Calibration and drift

First run captures 5 seconds of deliberate good posture and stores the median of each metric
as the personal `Baseline`. Thresholds are expressed as fractional deviations from baseline
rather than absolute anatomical constants.

Separately, a rolling 10-minute median of each metric is compared against the baseline. Slow
all-day sinking degrades this rolling median without ever crossing an instantaneous
threshold, so drift is reported as its own fault class.

## Intervention ladder

1. **Overlay cue** — offending joints drawn red with a specific instruction ("pull your chin back").
2. **Toast** — after the fault is sustained past a configurable duration.
3. **Dim** — progressive screen tint if the fault continues past the toast.
4. **Stretch break** — periodic, with the exercise chosen by the session's dominant fault.

Each stage clears immediately when posture is corrected. Snooze suspends stages 2–4.

## Milestones

- **M1** capture + pose + skeleton overlay
- **M2** metrics + calibration + live readout
- **M3** rules engine with debounce/hysteresis
- **M4** correction cues + escalation ladder
- **M5** session history + stretches
- **M6** tray, config, autostart

## Verification

- `pytest` covers metrics and rules, including occluded-hip degradation and an anti-flapping
  sequence that must not emit repeated faults.
- Manual: sit straight (no faults) → slump (correct fault named) → hold (ladder fires) →
  correct (alerts clear).
- Regression: move the chair back without slumping; forward head must **not** fire.
- Privacy: confirm no image files appear under the app data directory.
