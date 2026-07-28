"""Palette mode switching.

Every test restores "dark" afterward — theme.py's colour tokens are process-global
module state, and leaving "light" active would bleed into whatever test runs next.
"""

from __future__ import annotations

import pytest

from postureguard import theme


@pytest.fixture(autouse=True)
def restore_dark_mode():
    yield
    theme.set_mode("dark")


class TestMode:
    def test_starts_dark(self):
        # Other test modules may have already exercised set_mode(); the autouse
        # fixture above guarantees whatever ran before this left it "dark".
        assert theme.mode() == "dark"

    def test_switches_to_light(self):
        theme.set_mode("light")
        assert theme.mode() == "light"

    def test_anything_other_than_light_is_dark(self):
        theme.set_mode("light")
        theme.set_mode("sepia")
        assert theme.mode() == "dark"


class TestPaletteSwap:
    def test_light_mode_has_a_light_ground_and_dark_text(self):
        theme.set_mode("light")
        # Lightness by sum-of-channels is a crude proxy, but enough to catch a
        # palette that was not actually inverted.
        assert sum(theme.INK.getRgb()[:3]) > sum(theme.BONE.getRgb()[:3])

    def test_dark_mode_has_a_dark_ground_and_light_text(self):
        theme.set_mode("dark")
        assert sum(theme.BONE.getRgb()[:3]) > sum(theme.INK.getRgb()[:3])

    def test_state_colors_are_rebuilt_against_the_new_palette(self):
        theme.set_mode("light")
        assert theme.STATE_COLORS["fault"].name() == theme.FAULT.name()
        assert theme.STATE_COLORS["in_tolerance"].name() == theme.IN_TOLERANCE.name()

    def test_series_is_untouched_by_mode(self):
        """SERIES was validated against the dark card surface specifically and is
        not part of what set_mode swaps — see theme.py's own caveat about it."""
        before = [c.name() for c in theme.SERIES]
        theme.set_mode("light")
        after = [c.name() for c in theme.SERIES]
        assert before == after

    def test_switching_back_to_dark_restores_the_original_values(self):
        original = theme.INK.name()
        theme.set_mode("light")
        theme.set_mode("dark")
        assert theme.INK.name() == original
