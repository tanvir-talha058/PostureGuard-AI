# Building the portable executable

A single-file `PostureGuard.exe` via PyInstaller — no installer, no Start Menu entry,
no uninstaller. Double-click to run. (A real installer with those needs Inno Setup or
NSIS, neither of which is installed on this machine — see the note left in chat.)

## Build

```bash
.venv/Scripts/python -m pip install pyinstaller   # once
.venv/Scripts/pyinstaller packaging/postureguard.spec --distpath dist --workpath build --noconfirm
```

Needs UPX on PATH (or pass `--upx-dir`) for the compression step — installed via
`winget install --id UPX.UPX -e`. Not a pip package; nothing to add to the venv.

Output: `dist/PostureGuard.exe` (~90 MB — mediapipe, OpenCV and PySide6 all bundled).

## Files here

- `postureguard.spec` — the actual build recipe. Onefile: `a.binaries`/`a.datas` are
  fed straight into `EXE()` with no `COLLECT()` step, which is what makes it a single
  file rather than a folder.
- `run_postureguard.py` — trivial entry point; PyInstaller builds from a script, not
  a `module:function` target like the `pyproject.toml` console-script does.
- `icon.ico` — multi-resolution (16 through 256px) icon rendered from the same
  `alerts.app_icon()` paint routine the app uses at runtime, via Pillow, since Qt's
  own ICO writer only emits a single size.

## Keeping it small

First build was 146 MB with `collect_all("mediapipe")` and no exclusions — it works,
but `collect_all` walks every submodule under the mediapipe namespace regardless of
whether `pose.py` (the app's only mediapipe entry point) ever touches it, and one
throwaway import elsewhere pulled in far more than it needed:

- **mediapipe's own test/benchmark/audio/genai subpackages** — `pose.py` imports only
  `mediapipe.tasks.python.vision.PoseLandmarker`, never audio, LLM/genai, benchmarking,
  or mediapipe's unit tests. Dropped by path prefix in the spec.
- **`capture.available_cameras()` imports `PySide6.QtMultimedia` for exactly one
  call** — `QMediaDevices.videoInputs()`, a device-*name* lookup — which dragged in
  Qt's entire bundled FFmpeg codec stack (avcodec/avformat/avutil/swresample/swscale,
  ~19 MB) and its QML/Quick declarative engine (~13 MB), neither of which enumeration
  needs or this app uses anywhere else.
- **cv2's bundled FFmpeg DLL** (~31 MB) — `capture.py` forces the `CAP_DSHOW` backend
  for live webcam capture; that path never touches cv2's video-*file* codec support.
- **`opengl32sw.dll`** (~21 MB) — Qt's software-GL fallback for when no hardware
  context is available. This app paints with plain `QWidget`/`QPainter` throughout —
  no `QOpenGLWidget`, no QtQuick — so it never creates a GL context to fall back from.
- **Pillow's AVIF/WEBP/Tk codec plugins** (~8 MB) — Pillow is only here as a
  transitive pull from matplotlib (see the trap below); it isn't imported directly,
  and these are optional plugins Pillow already probes for and skips gracefully.

Result: 146 MB → 108 MB. Each of the four removed binary groups was verified in
isolation before trusting it into the spec — moved the actual DLLs out of the dev
venv's `site-packages` one group at a time and re-ran the exact runtime path each one
backs (`available_cameras()`, live `Camera` capture, and grabbing both the main window
and the mini overlay) to confirm nothing regressed, rather than assuming from reading
Qt's dependency graph.

**UPX is now enabled** (installed via `winget install UPX.UPX`), on top of the trimming
above: 108 MB → 90 MB. It was left off initially because compressing mediapipe's
native binary specifically is a known source of intermittent runtime crashes — its
XNNPACK/TFLite runtime does aggressive relocation and self-inspection that a
self-decompressing wrapper can upset. Rather than skip UPX entirely over that, the spec
excludes exactly the one native mediapipe binary this build actually ships
(`libmediapipe.dll` — confirmed to be the *only* one by listing the build's own binary
manifest, not assumed) plus the standard-caution list of core CRT/interpreter DLLs some
antivirus engines flag on sight when UPX-packed (`python3*.dll`, `vcruntime*.dll`,
`api-ms-win-*.dll`). UPX's own Control Flow Guard detection independently declined to
touch several PySide6 Qt DLLs on top of that — its own safety margin, not something the
spec has to configure.

Verified stable, not just "it launched": left running for 35+ seconds and confirmed the
session database logged one row per second with zero gaps the entire time (48 rows /
48.3 seconds), and working-set memory stayed flat around 66 MB rather than climbing —
the two signals most likely to catch a UPX-induced corruption that a plain "does it
open" check would miss.

## Known trap

`mediapipe.tasks.python.vision.drawing_utils` hard-imports `matplotlib` for its own
optional plotting helpers — which this app never calls — but excluding matplotlib to
save space breaks mediapipe's import chain entirely. Learned by shipping a build that
crashed on startup with `ModuleNotFoundError: No module named 'matplotlib'`. Leave it
in.

## What's not bundled

The pose model (`pose_landmarker_lite.task`, ~6 MB) is deliberately **not** included.
`postureguard.pose.ensure_model()` downloads it to the user's app-data folder on first
run and caches it there — bundling a second copy would just duplicate it for no benefit.
First launch therefore needs network access once; every launch after that is offline.

## Verification performed

Built and actually launched (not just import-checked): confirmed via the session
database that a fresh instance was writing real posture samples roughly once per
second within seconds of starting — camera, MediaPipe inference and the SQLite log
all working end to end from the frozen exe, not just from the dev checkout.

After trimming, each removed binary group was re-verified in isolation (DLLs moved
out of the dev venv, not just excluded from the spec, so the test can't accidentally
pass by falling back to a copy PyInstaller left behind): `available_cameras()` still
returns the real device name with no FFmpeg/QML present, `Camera` still reads live
frames with no FFmpeg present, and both the main window and the mini overlay still
render and `grab()` correctly with no `opengl32sw.dll`/Quick/QML present. Then the full
frozen exe was re-launched end to end once more, same as above.
