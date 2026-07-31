"""Convenience launcher: runs PostureGuard straight from a checkout.

Equivalent to `python -m postureguard.app` after `pip install -e .`, but works
without that install step — this just puts src/ on the path first. CLI flags
(--camera, --recalibrate, --verbose) pass straight through to main().
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from postureguard.app import main

if __name__ == "__main__":
    raise SystemExit(main())
