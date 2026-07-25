"""Visual tokens.

The design register is a **measuring instrument**, not a wellness app — the reference
points are the plumb line and the goniometer a physiotherapist actually assesses posture
with. Everything downstream follows from that: squared-off reticle markers rather than
soft dots, tabular monospace readings, and a DIN-derived label face.

One deliberate departure from convention: good posture reads *steel blue*, not green.
Green/red is the health-app reflex and it moralizes at the user all day. Blue reads as
"within tolerance", which is instrument language — a measurement, not a verdict.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont

# --- Colour ----------------------------------------------------------------------

SIDEBAR = QColor("#0E1116")  # recessed navigation rail
INK = QColor("#12151A")  # deep blue-charcoal ground, never pure black
PANEL = QColor("#1C2027")  # raised surface
PANEL_HOVER = QColor("#232833")
RULE = QColor("#2C323C")  # hairline dividers
BONE = QColor("#E8E4DA")  # skeleton and primary text, warm off-white
MUTED = QColor("#7C8698")  # labels, secondary readings
FAINT = QColor("#4C5567")  # disabled, axis ticks

IN_TOLERANCE = QColor("#4A90A4")  # calm state, plumb line, tolerance band
WARNING = QColor("#E4933F")  # drifting, or a mild fault
FAULT = QColor("#D64545")  # active fault

# Categorical series colours, for charts that encode *identity* (which fault) rather
# than *state* (how bad). Kept strictly separate from the status colours above: reusing
# the fault red as "series 4" would make a neutral breakdown chart read as an alarm.
#
# Assigned in fixed order and never cycled. Validated against the #1C2027 card surface
# for the OKLCH lightness band, chroma floor, adjacent-pair separation under protanopia
# / deuteranopia / tritanopia, and 3:1 contrast — see docs for the validator invocation.
SERIES = [
    QColor("#4A9ACB"),  # blue
    QColor("#B08A22"),  # gold
    QColor("#9C7DD4"),  # violet
    QColor("#2AA294"),  # teal
    QColor("#D26A56"),  # coral
]

STATE_COLORS = {
    "calibrating": MUTED,
    "searching": MUTED,
    "camera_lost": WARNING,
    "paused": MUTED,
    "in_tolerance": IN_TOLERANCE,
    "drifting": WARNING,
    "fault": FAULT,
}


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
    font = _font(DISPLAY_FAMILY, DISPLAY_FALLBACKS, 15, QFont.Weight.DemiBold)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.4)
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

PANEL_WIDTH = 360
VIDEO_HEIGHT = 240
GUTTER = 14
HAIRLINE = 1

#: A 4pt spacing scale. Every margin and gap in the app is one of these, which is what
#: keeps a multi-screen layout feeling like one product rather than four.
SPACE = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "2xl": 32, "3xl": 48}
RADIUS = {"sm": 4, "md": 8, "lg": 12}

SIDEBAR_WIDTH = 216
WINDOW_SIZE = (1180, 780)
