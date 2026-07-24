"""Application stylesheet, generated from the tokens in :mod:`postureguard.theme`.

Every colour and dimension here is read from the token module rather than written as a
literal, so the instrument palette stays a single source of truth across the painted
surfaces (skeleton, charts) and the styled ones (buttons, inputs).

Selectors are kept to class names and object names, never bare element types. Styling
``QPushButton`` globally and then trying to override it for one variant is how Qt
stylesheets end up in specificity fights that are invisible until a screen renders wrong.
"""

from __future__ import annotations

from .. import theme

S = theme.SPACE
R = theme.RADIUS


def _hex(colour) -> str:
    return colour.name()


def stylesheet() -> str:
    ink = _hex(theme.INK)
    sidebar = _hex(theme.SIDEBAR)
    panel = _hex(theme.PANEL)
    panel_hover = _hex(theme.PANEL_HOVER)
    rule = _hex(theme.RULE)
    bone = _hex(theme.BONE)
    muted = _hex(theme.MUTED)
    faint = _hex(theme.FAINT)
    accent = _hex(theme.IN_TOLERANCE)
    warning = _hex(theme.WARNING)
    fault = _hex(theme.FAULT)

    return f"""
    QWidget {{
        background: {ink};
        color: {bone};
        font-family: "{theme.BODY_FAMILY}", "Inter", sans-serif;
        font-size: 13px;
    }}

    /* Labels inherit the window ground otherwise, which paints an opaque ink
       rectangle over whatever card they sit on. */
    QLabel, QCheckBox {{
        background: transparent;
    }}

    /* Grouping containers created via widgets.plain() — see the note there. */
    QWidget#Plain, QScrollArea, QScrollArea > QWidget > QWidget {{
        background: transparent;
    }}

    QToolTip {{
        background: {panel};
        color: {bone};
        border: 1px solid {rule};
        padding: {S['xs']}px {S['sm']}px;
    }}

    /* --- navigation rail --------------------------------------------------- */

    QFrame#Sidebar {{
        background: {sidebar};
        border-right: 1px solid {rule};
    }}

    QLabel#WordMark {{
        font-family: "{theme.DISPLAY_FAMILY}";
        font-size: 17px;
        font-weight: 600;
        letter-spacing: 2px;
        color: {bone};
    }}

    QLabel#WordMarkSub {{
        font-family: "{theme.MONO_FAMILY}";
        font-size: 9px;
        letter-spacing: 1px;
        color: {faint};
    }}

    QPushButton#NavItem {{
        background: transparent;
        border: none;
        border-left: 2px solid transparent;
        padding: {S['md']}px {S['lg']}px;
        text-align: left;
        font-family: "{theme.DISPLAY_FAMILY}";
        font-size: 14px;
        letter-spacing: 0.5px;
        color: {muted};
    }}
    QPushButton#NavItem:hover {{
        background: {panel};
        color: {bone};
    }}
    QPushButton#NavItem:checked {{
        background: {panel};
        border-left: 2px solid {accent};
        color: {bone};
    }}

    /* --- surfaces ---------------------------------------------------------- */

    QFrame#Card {{
        background: {panel};
        border: 1px solid {rule};
        border-radius: {R['md']}px;
    }}

    QFrame#Divider {{
        background: {rule};
        max-height: 1px;
        border: none;
    }}

    /* --- type roles -------------------------------------------------------- */

    QLabel#PageTitle {{
        font-family: "{theme.DISPLAY_FAMILY}";
        font-size: 24px;
        font-weight: 600;
        letter-spacing: 0.3px;
        color: {bone};
    }}
    QLabel#PageSubtitle {{
        font-size: 13px;
        color: {muted};
    }}
    QLabel#Eyebrow {{
        font-family: "{theme.MONO_FAMILY}";
        font-size: 9px;
        letter-spacing: 1.4px;
        color: {muted};
    }}
    QLabel#CardTitle {{
        font-family: "{theme.DISPLAY_FAMILY}";
        font-size: 14px;
        font-weight: 600;
        letter-spacing: 0.4px;
        color: {bone};
    }}
    QLabel#Body {{
        font-size: 13px;
        color: {muted};
    }}
    QLabel#Metric {{
        font-family: "{theme.MONO_FAMILY}";
        font-size: 30px;
        font-weight: 500;
        color: {bone};
    }}
    QLabel#MetricUnit {{
        font-family: "{theme.MONO_FAMILY}";
        font-size: 12px;
        color: {muted};
    }}

    /* --- buttons ----------------------------------------------------------- */

    QPushButton#Primary {{
        background: {accent};
        color: {ink};
        border: none;
        border-radius: {R['sm']}px;
        padding: {S['sm']}px {S['lg']}px;
        font-family: "{theme.DISPLAY_FAMILY}";
        font-size: 13px;
        font-weight: 600;
        letter-spacing: 0.4px;
    }}
    QPushButton#Primary:hover {{ background: #5AA6BC; }}
    QPushButton#Primary:pressed {{ background: #3D7A8B; }}
    QPushButton#Primary:disabled {{ background: {rule}; color: {faint}; }}

    QPushButton#Secondary {{
        background: transparent;
        color: {bone};
        border: 1px solid {rule};
        border-radius: {R['sm']}px;
        padding: {S['sm']}px {S['lg']}px;
        font-family: "{theme.DISPLAY_FAMILY}";
        font-size: 13px;
        letter-spacing: 0.4px;
    }}
    QPushButton#Secondary:hover {{ background: {panel_hover}; border-color: {muted}; }}
    QPushButton#Secondary:disabled {{ color: {faint}; border-color: {rule}; }}

    QPushButton#Ghost {{
        background: transparent;
        color: {muted};
        border: none;
        padding: {S['xs']}px {S['sm']}px;
        font-size: 12px;
    }}
    QPushButton#Ghost:hover {{ color: {bone}; }}

    /* --- inputs ------------------------------------------------------------ */

    QSlider::groove:horizontal {{
        height: 3px;
        background: {rule};
        border-radius: 1px;
    }}
    QSlider::sub-page:horizontal {{
        background: {accent};
        border-radius: 1px;
    }}
    QSlider::handle:horizontal {{
        background: {bone};
        width: 12px;
        height: 12px;
        margin: -5px 0;
        border-radius: 6px;
    }}
    QSlider::handle:horizontal:hover {{ background: #FFFFFF; }}

    QCheckBox {{ spacing: {S['sm']}px; color: {bone}; }}
    QCheckBox::indicator {{
        width: 15px; height: 15px;
        border: 1px solid {rule};
        border-radius: 3px;
        background: {ink};
    }}
    QCheckBox::indicator:hover {{ border-color: {muted}; }}
    QCheckBox::indicator:checked {{
        background: {accent};
        border-color: {accent};
    }}

    QComboBox {{
        background: {ink};
        border: 1px solid {rule};
        border-radius: {R['sm']}px;
        padding: {S['xs']}px {S['sm']}px;
        min-height: 20px;
        color: {bone};
    }}
    QComboBox:hover {{ border-color: {muted}; }}
    QComboBox::drop-down {{ border: none; width: 18px; }}
    QComboBox QAbstractItemView {{
        background: {panel};
        border: 1px solid {rule};
        selection-background-color: {accent};
        selection-color: {ink};
        outline: none;
    }}

    QSpinBox {{
        background: {ink};
        border: 1px solid {rule};
        border-radius: {R['sm']}px;
        padding: {S['xs']}px {S['sm']}px;
        color: {bone};
    }}

    /* --- scrolling --------------------------------------------------------- */

    QScrollArea {{ border: none; }}
    QScrollBar:vertical {{
        background: transparent; width: 8px; margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {rule}; border-radius: 4px; min-height: 28px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {muted}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

    /* --- status accents ---------------------------------------------------- */

    QLabel#StatusGood  {{ color: {accent}; }}
    QLabel#StatusWarn  {{ color: {warning}; }}
    QLabel#StatusFault {{ color: {fault}; }}
    """ + path_field_style()


def path_field_style() -> str:
    """Read-only path display: a field, but visually a caption."""
    return f"""
    QLineEdit#PathField {{
        background: {_hex(theme.INK)};
        border: 1px solid {_hex(theme.RULE)};
        border-radius: {R['sm']}px;
        padding: {S['xs']}px {S['sm']}px;
        color: {_hex(theme.MUTED)};
        font-family: "{theme.MONO_FAMILY}";
        font-size: 10px;
    }}
    """
