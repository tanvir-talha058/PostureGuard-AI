"""Optional, opt-in AI-generated content, layered on the deterministic pipeline.

Nothing under this package is imported by metrics.py, rules.py, or engine.py — the
real-time detection loop has no network dependency, with or without this package
installed or configured. See docs/superpowers/specs/2026-08-02-ai-features-design.md.
"""
