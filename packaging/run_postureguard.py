"""PyInstaller entry point.

PyInstaller builds from a script, not a `package.module:function` target, so this
exists purely to call the real one. Keep it empty of logic — anything worth doing
belongs in `postureguard.app.main`, not here.

No sys.path manipulation needed: the spec's `pathex` points Analysis at `src/` for
package discovery at build time, and the bundled `postureguard` package is importable
directly once frozen — a relative `sys.path` entry would point nowhere useful inside
the packaged exe anyway.
"""

from postureguard.app import main

if __name__ == "__main__":
    raise SystemExit(main())
