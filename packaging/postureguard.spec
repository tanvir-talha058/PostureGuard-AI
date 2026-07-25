# PyInstaller spec for a portable, single-file PostureGuard.exe.
#
# Build with (from the repo root, using the project venv):
#   .venv/Scripts/pyinstaller packaging/postureguard.spec --distpath dist --workpath build --noconfirm
#
# Deliberately onefile — achieved by feeding a.binaries/a.datas straight into EXE()
# and never calling COLLECT(). The ask was a single double-click-to-run executable,
# not an installer; the accepted trade is that every launch unpacks into a temp dir
# first, a few seconds of startup cost, for "one file, no install step".
#
# The pose model is NOT bundled. postureguard.pose.ensure_model() downloads it to the
# user's app-data folder on first run and caches it there — bundling a second copy
# into the exe would just duplicate ~6 MB for no benefit.

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

# SPECPATH is injected by PyInstaller into the spec's exec namespace: the directory
# containing this file. Anchoring paths to it (rather than the current working
# directory) means the build works the same regardless of where it is invoked from.
ROOT = Path(SPECPATH).parent
SCRIPT = Path(SPECPATH) / "run_postureguard.py"

# mediapipe ships compiled extension modules and internal graph/resource files with no
# PyInstaller hook of its own (unlike cv2, which pyinstaller-hooks-contrib covers) —
# collect_all is the blunt-but-reliable way to make sure nothing it needs at import
# time gets left behind.
mp_datas, mp_binaries, mp_hidden = collect_all("mediapipe")

# collect_all walks every submodule under the mediapipe namespace regardless of
# whether this app's own import path (mediapipe.tasks.python.vision.PoseLandmarker,
# see pose.py) ever touches it. That swept in mediapipe's own unit tests, its audio
# and generative-AI (genai/LLM) task families, and its benchmark harness — none of
# which pose.py imports. Dropped by path prefix rather than trying to enumerate an
# exact keep-list, since mediapipe's internal layout is not something to chase release
# to release.
_MEDIAPIPE_DROP_PREFIXES = (
    "mediapipe.tasks.python.test",
    "mediapipe.tasks.python.benchmark",
    "mediapipe.tasks.python.audio",
    "mediapipe.tasks.python.genai",
)


def _mediapipe_unused(dotted_or_path: str) -> bool:
    normalized = dotted_or_path.replace("\\", "/").replace("/", ".")
    return any(prefix in normalized for prefix in _MEDIAPIPE_DROP_PREFIXES)


mp_hidden = [name for name in mp_hidden if not _mediapipe_unused(name)]
mp_datas = [(dest, src) for dest, src in mp_datas if not _mediapipe_unused(dest)]

a = Analysis(
    [str(SCRIPT)],
    pathex=[str(ROOT / "src")],
    binaries=mp_binaries,
    datas=mp_datas,
    hiddenimports=mp_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        # capture.available_cameras() imports QtMultimedia for exactly one call —
        # QMediaDevices.videoInputs(), a device-name lookup — never QtMultimediaWidgets.
        "PySide6.QtMultimediaWidgets",
    ],
    # matplotlib is a hard import inside mediapipe.tasks.python.vision.drawing_utils
    # (its own drawing-style helpers, which this app never calls) — excluding *it*
    # broke mediapipe's import chain even though nothing here uses plotting, so it
    # stays, unlike the exclusions above.
    noarchive=False,
    optimize=0,
)

# Native DLLs pulled in by real dependencies but never exercised by anything this app
# actually does, identified by comparing the build's own binary manifest against what
# postureguard imports (see packaging/README.md for the measurements behind each one):
#
#   cv2 ffmpeg backend       — capture.py forces CAP_DSHOW; live webcam capture never
#                               goes through cv2's video-file FFmpeg codecs.
#   PySide6 multimedia codecs — QMediaDevices.videoInputs() enumerates device names;
#                               it does not decode anything, so the codec DLLs behind
#                               actual playback/capture pipelines are dead weight.
#   PySide6 Quick/QML        — only reachable through QtMultimedia's optional
#                               declarative integration; this app has no QML anywhere.
#   opengl32sw.dll            — Qt's software-rasterizer fallback for when no hardware
#                               GL context is available; this app never creates one
#                               in the first place (plain QWidget painting throughout).
#   Pillow optional codecs    — AVIF/WEBP/Tk plugins Pillow probes for and silently
#                               skips if absent; Pillow itself is only here as a
#                               transitive pull from matplotlib, not used directly.
_UNUSED_BINARY_MARKERS = (
    "ffmpeg",  # cv2's ffmpeg dll + PySide6's ffmpegmediaplugin.dll
    "avcodec-", "avformat-", "avutil-", "swresample-", "swscale-", "avdevice-", "avfilter-",
    "qt6quick", "qt6qml",
    "opengl32sw.dll",
    "pil\\_avif", "pil\\_webp", "pil\\_imagingtk",
)


def _is_unused_binary(dest: str) -> bool:
    lowered = dest.lower()
    return any(marker in lowered for marker in _UNUSED_BINARY_MARKERS)


a.binaries = [entry for entry in a.binaries if not _is_unused_binary(entry[0])]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PostureGuard",
    icon=str(ROOT / "packaging" / "icon.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # libmediapipe.dll is the one native binary in this bundle actually known to be
    # crash-prone under UPX (its XNNPACK/TFLite runtime does aggressive relocation and
    # self-inspection that a self-decompressing wrapper can upset) — verified as the
    # *only* native mediapipe binary in this build, so excluding it by name is precise,
    # not a guess. python3*.dll/vcruntime*.dll/api-ms-win-*.dll are excluded on the
    # same standard caution: core CRT/interpreter binaries that some antivirus engines
    # flag on sight when UPX-packed, for a cost too small to be worth the risk.
    upx_exclude=["*mediapipe*", "python3*.dll", "vcruntime*.dll", "api-ms-win-*.dll"],
    runtime_tmpdir=None,
    # Windowed: a console window sitting behind the GUI would serve no purpose here,
    # and stdout is only ever log messages.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
