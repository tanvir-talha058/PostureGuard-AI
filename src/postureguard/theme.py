"""Visual tokens.

The design register is a **measuring instrument**, not a wellness app — the reference
points are the plumb line and the goniometer a physiotherapist actually assesses posture
with. Everything downstream follows from that: squared-off reticle markers rather than
soft dots, tabular monospace readings, and a DIN-derived label face.

One deliberate departure from convention: good posture reads *steel blue*, not green.
Green/red is the health-app reflex and it moralizes at the user all day. Blue reads as
"within tolerance", which is instrument language — a measurement, not a verdict.

## Light mode

The palette below is swappable via :func:`set_mode` — every module reads these as
`theme.INK`, `theme.BONE` and so on at paint time rather than importing the names
directly, so reassigning them here is visible everywhere immediately. The light
variant mirrors the dark one's structure (same roles, same relative contrast) rather
than being a straight inversion, but it has **not** been through the same OKLCH /
colour-vision-deficiency validation pass the dark palette and the `SERIES` chart
colours document above went through — treat it as a good-faith first pass, not a
re-validated design token set.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont

# --- Colour ----------------------------------------------------------------------

_DARK = {
    "SIDEBAR": "#0E1116",       # recessed navigation rail
    "INK": "#12151A",           # deep blue-charcoal ground, never pure black
    "PANEL": "#1C2027",         # raised surface
    "PANEL_HOVER": "#232833",
    "RULE": "#2C323C",          # hairline dividers
    "BONE": "#E8E4DA",          # skeleton and primary text, warm off-white
    "MUTED": "#7C8698",         # labels, secondary readings
    "FAINT": "#4C5567",         # disabled, axis ticks
    "IN_TOLERANCE": "#4A90A4",  # calm state, plumb line, tolerance band
    "WARNING": "#E4933F",       # drifting, or a mild fault
    "FAULT": "#D64545",         # active fault
}

_LIGHT = {
    "SIDEBAR": "#EDE9E0",       # recessed navigation rail, a shade off the ground
    "INK": "#F6F3EC",           # warm paper ground, never pure white
    "PANEL": "#FFFFFF",         # raised surface
    "PANEL_HOVER": "#F1ECE1",
    "RULE": "#DAD3C3",          # hairline dividers
    "BONE": "#211E19",          # skeleton and primary text, warm near-black
    "MUTED": "#5B6472",         # labels, secondary readings
    "FAINT": "#A9ADB6",         # disabled, axis ticks
    "IN_TOLERANCE": "#3D7A8B",  # deepened from the dark value for contrast on paper
    "WARNING": "#B5661F",
    "FAULT": "#B23A3A",
}

# Categorical series colours, for charts that encode *identity* (which fault) rather
# than *state* (how bad). Kept strictly separate from the status colours above: reusing
# the fault red as "series 4" would make a neutral breakdown chart read as an alarm.
#
# Assigned in fixed order. Validated against the #1C2027 card surface for the OKLCH
# lightness band, chroma floor, adjacent-pair separation under protanopia / deuteranopia
# / tritanopia, and 3:1 contrast — see docs for the validator invocation.
#
# Only 5 entries have been through that validation. `rules.FaultKind` has since grown
# past 5 members (history.py's breakdown chart indexes in with `% len(SERIES)`), so a
# 6th+ fault kind cycles back to an already-used colour rather than getting a genuinely
# distinct one. Extending this list needs the validator re-run, not five more hex codes
# typed by hand — a hand-picked addition is exactly the kind of "looks fine to me" call
# this list exists to not depend on.
SERIES = [
    QColor("#4A9ACB"),  # blue
    QColor("#B08A22"),  # gold
    QColor("#9C7DD4"),  # violet
    QColor("#2AA294"),  # teal
    QColor("#D26A56"),  # coral
]


def mode() -> str:
    """The active palette: "dark" or "light"."""
    return _mode


def set_mode(new_mode: str) -> None:
    """Swap every base colour token in place. Anything but "light" means dark.

    Reassigns the module globals rather than mutating the existing `QColor`
    objects — every consumer reads `theme.INK` etc. fresh at paint time (never
    `from .theme import INK`), so a plain reassignment here is exactly as visible
    to them as a mutation would be, without needing to parse a colour string back
    into an object that already exists.

    Two things this does *not* do on its own, because they are not colour state:
    the application stylesheet (`ui.design.stylesheet()`) is a string baked at
    `setStyleSheet()` time and needs regenerating and reapplying; and already-
    painted widgets need a repaint requested. Both are the caller's job — see
    `app.Application._apply_theme_mode`.
    """
    global _mode, SIDEBAR, INK, PANEL, PANEL_HOVER, RULE, BONE, MUTED, FAINT
    global IN_TOLERANCE, WARNING, FAULT, STATE_COLORS

    palette = _LIGHT if new_mode == "light" else _DARK
    _mode = "light" if new_mode == "light" else "dark"

    SIDEBAR = QColor(palette["SIDEBAR"])
    INK = QColor(palette["INK"])
    PANEL = QColor(palette["PANEL"])
    PANEL_HOVER = QColor(palette["PANEL_HOVER"])
    RULE = QColor(palette["RULE"])
    BONE = QColor(palette["BONE"])
    MUTED = QColor(palette["MUTED"])
    FAINT = QColor(palette["FAINT"])
    IN_TOLERANCE = QColor(palette["IN_TOLERANCE"])
    WARNING = QColor(palette["WARNING"])
    FAULT = QColor(palette["FAULT"])
    STATE_COLORS = {
        "calibrating": MUTED,
        "searching": MUTED,
        "camera_lost": WARNING,
        "paused": MUTED,
        "in_tolerance": IN_TOLERANCE,
        "drifting": WARNING,
        "fault": FAULT,
    }


# Establishes SIDEBAR, INK, ..., STATE_COLORS and _mode on first import — the one
# assignment of these globals, rather than a separate copy here plus what set_mode()
# does, so a new token added to _DARK/_LIGHT only has one place to also wire up.
set_mode("dark")


def with_alpha(color: QColor, alpha: int) -> QColor:
    faded = QColor(color)
    faded.setAlpha(alpha)
    return faded


# --- Type ------------------------------------------------------------------------
#
# Bahnschrift ships with Windows 10+ and descends from DIN 1451 — the typeface of
# machinery plates and road signage. It carries the technical register without a
# download. Consolas gives tabular figures so readings do not jitter as digits change.

DISPLAY_FAMILY = "Bahnschrift"
DISPLAY_FALLBACKS = ["Bahnschrift Condensed", "Segoe UI Semibold", "DIN Alternate"]
MONO_FAMILY = "Consolas"
MONO_FALLBACKS = ["Cascadia Mono", "Menlo", "DejaVu Sans Mono"]
BODY_FAMILY = "Segoe UI"


def _font(family: str, fallbacks: list[str], size: int, weight: QFont.Weight) -> QFont:
    font = QFont(family, size)
    font.setWeight(weight)
    font.setFamilies([family, *fallbacks])
    return font


def eyebrow_font() -> QFont:
    """Small, wide-tracked labels. Set the letter spacing at the call site."""
    font = _font(DISPLAY_FAMILY, DISPLAY_FALLBACKS, 8, QFont.Weight.DemiBold)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.6)
    font.setCapitalization(QFont.Capitalization.AllUppercase)
    return font


def fault_title_font() -> QFont:
    font = _font(DISPLAY_FAMILY, DISPLAY_FALLBACKS, 13, QFont.Weight.DemiBold)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.3)
    return font


def cue_font() -> QFont:
    return _font(BODY_FAMILY, ["Inter", "Helvetica Neue"], 10, QFont.Weight.Normal)


def reading_font() -> QFont:
    """Tabular figures for the metric strip."""
    return _font(MONO_FAMILY, MONO_FALLBACKS, 9, QFont.Weight.Medium)


def reading_label_font() -> QFont:
    font = _font(MONO_FAMILY, MONO_FALLBACKS, 7, QFont.Weight.Normal)
    font.setCapitalization(QFont.Capitalization.AllUppercase)
    return font


# --- Metrics ---------------------------------------------------------------------

PANEL_WIDTH = 320
VIDEO_HEIGHT = 240
GUTTER = 14
HAIRLINE = 1

#: A 4pt spacing scale. Every margin and gap in the app is one of these, which is what
#: keeps a multi-screen layout feeling like one product rather than four.
SPACE = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "2xl": 32, "3xl": 48}
RADIUS = {"sm": 4, "md": 8, "lg": 12}

SIDEBAR_WIDTH = 216
WINDOW_SIZE = (1180, 780)
