# PostureGuard-AI

Real-time posture tracking and correction for desk work. Watches you through your
webcam, names the specific fault, tells you what to do about it, and escalates if you
ignore it.

Runs entirely on your machine. Video is never written to disk and never leaves the
device.

## Install

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"     # Windows
# .venv/bin/python -m pip install -e ".[dev]"       # macOS / Linux
```

Requires Python 3.10+. The pose model (~6 MB) downloads on first run and is cached.

## Run

```bash
postureguard                 # or: python -m postureguard.app
postureguard --recalibrate   # discard the baseline and capture a new one
postureguard --camera 1      # pick a different camera
```

On first launch it records a five-second baseline of you sitting up straight. Every
threshold afterwards is a deviation from *that*, not from a textbook ideal.

Recalibrate whenever the camera or your chair moves.

## What it detects

| Fault | Signal |
|---|---|
| Forward head | ear-to-shoulder gap closes **and** face grows, both relative to shoulder width |
| Slouching | shoulders sink in frame, or the torso vector tilts when hips are visible |
| Too close to the screen | inter-ocular distance grows in absolute terms |
| Leaning to one side | eye line or shoulder line rolls away from your baseline |
| Drift | a 10-minute rolling median degrades without ever crossing a threshold |

### The head-on camera problem

A desk webcam faces you, so forward-head posture is movement *toward* the lens — the
clinical side-view craniovertebral angle is not measurable. Copying side-view formulas
onto a front view is the usual reason this class of tool is inaccurate.

Forward head is therefore inferred from two signals that *are* front-observable, and
only fires when both move. Either alone is ambiguous: pushing your chair back changes
both absolute scales, which is exactly why both are normalized by shoulder width first.

Hips are routinely hidden by a desk. When they are, `torso_angle` is reported as
unavailable rather than as a plausible-looking zero, and the spine check falls back to
how far the shoulders have sunk.

## The intervention ladder

1. **Overlay cue** — the offending joints turn red and a specific instruction appears.
2. **Notification** — after the fault is sustained.
3. **Screen dimming** — ramps in if still ignored. Click-through; it is a prompt, not a lock.
4. **Stretch break** — periodically, with exercises chosen by your dominant fault.

Every rung clears the moment posture is corrected. Time only counts while the fault is
continuously present, and a fix-then-reslip within the cooldown is one lapse, not two.

## Screens

**Live** — camera view with the skeleton, plumb line and tolerance band; the current
correction; today's score. **History** — daily scores, where the time goes, and which
hour of the day your posture falls apart. **Exercises** — a routine picked from what has
actually been going wrong, with a guided timer. **Settings** — calibration, sensitivity,
how hard it pushes.

## Design notes

The visual language is a **measuring instrument**, not a wellness app — the reference
points are the plumb line and goniometer a physiotherapist assesses posture with.

Good posture reads **steel blue, not green**. Green/red is the health-app reflex and it
moralizes at you all day; blue says *within tolerance*, which is a measurement rather
than a verdict.

The signature element is the **tolerance band**: a horizontal band drawn where your ears
should sit, computed from your own calibration and the same threshold the rule engine
checks. Ears inside means in tolerance; ears below means craning. It shows you where to
move to, which is the difference between an alarm and a correction.

Chart colours were validated for the OKLCH lightness band, chroma floor, colour-vision
separation and contrast rather than chosen by eye.

## Architecture

```
capture → pose → metrics → rules → escalation → {overlay, alerts}
                    │        │
             calibration   session
```

`metrics.py` and `rules.py` carry the real logic and have no camera or UI dependency, so
they are unit-tested against synthetic poses. Everything else is verified by running it.

## Development

```bash
.venv/Scripts/python -m pytest          # 154 tests
python tools/preview_app.py             # render every screen with seeded data
python tools/preview_overlay.py         # render the compact overlay states
```

The preview tools use synthetic poses and a fake camera scene. **Never** save a real
camera frame or a Live-screen grab to disk — it would break the privacy guarantee the
app makes and that `test_session.py` asserts.

## Privacy

Frames live in memory and are overwritten. The session database stores a status, an
optional fault name and a severity number, once per second — the schema has no column
that could hold image data, and there is a test asserting it. Everything is under a
single local folder, shown in Settings.
