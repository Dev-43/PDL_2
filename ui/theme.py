"""
BehaviorShield — Theme
======================
All colors, fonts, and stylesheet strings in one place.
Import this everywhere — never hardcode colors in UI files.
"""

# ── Colors ────────────────────────────────────────────────────────────────────

BG_BASE      = "#0a0e14"
BG_PANEL     = "#111827"
BG_INPUT     = "#0d1520"
BORDER       = "#1f2937"
BORDER_LIGHT = "#2d3f55"

ACCENT       = "#00d4ff"
ACCENT_DIM   = "#0088aa"

DANGER       = "#ef4444"
DANGER_DIM   = "#7f1d1d"
DANGER_BG    = "#1f0a0a"

WARN         = "#f59e0b"
WARN_DIM     = "#78350f"
WARN_BG      = "#1f1500"

SAFE         = "#10b981"
SAFE_DIM     = "#065f46"
SAFE_BG      = "#001f14"

TEXT         = "#e2e8f0"
TEXT_DIM     = "#64748b"
TEXT_MUTED   = "#374151"

# ── Chart Colors ──────────────────────────────────────────────────────────────

CHART_CPU    = "#00d4ff"   # cyan  — CPU
CHART_RAM    = "#818cf8"   # indigo — RAM
CHART_SENT   = "#f59e0b"   # amber — Net sent
CHART_RECV   = "#10b981"   # green — Net recv
CHART_THREAD = "#a78bfa"   # violet — Threads
CHART_HANDLE = "#fb7185"   # rose — Handles
CHART_CONN   = "#34d399"   # emerald — Connections
CHART_RISK   = "#ef4444"   # red — Risk score
CHART_BG     = "#050810"   # chart background

# ── Fonts ─────────────────────────────────────────────────────────────────────

import platform

_system = platform.system()

if _system == "Windows":
    FONT_DATA   = "Consolas"
    FONT_UI     = "Segoe UI"
elif _system == "Linux":
    FONT_DATA   = "Fira Mono,DejaVu Sans Mono,Courier New"
    FONT_UI     = "Ubuntu,DejaVu Sans,Sans"
else:
    FONT_DATA   = "Courier New"
    FONT_UI     = "Sans"

FONT_SIZE_SMALL  = 9
FONT_SIZE_NORMAL = 10
FONT_SIZE_LARGE  = 12
FONT_SIZE_TITLE  = 14

# ── Risk Colors ───────────────────────────────────────────────────────────────

def risk_color(score: float) -> str:
    if score >= 0.70: return DANGER
    if score >= 0.40: return WARN
    return SAFE

def risk_bg(score: float) -> str:
    if score >= 0.70: return DANGER_BG
    if score >= 0.40: return WARN_BG
    return SAFE_BG

def verdict_color(verdict: str) -> str:
    if verdict == "HIGH RISK":  return DANGER
    if verdict == "SUSPICIOUS": return WARN
    return SAFE

# ── Master Stylesheet ─────────────────────────────────────────────────────────

STYLESHEET = f"""
/* ── Base ── */
QMainWindow, QDialog, QWidget {{
    background-color: {BG_BASE};
    color: {TEXT};
    font-family: {FONT_UI};
    font-size: {FONT_SIZE_NORMAL}pt;
}}

/* ── Tab Bar ── */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    background: {BG_BASE};
    top: -1px;
}}
QTabBar::tab {{
    background: {BG_PANEL};
    color: {TEXT_DIM};
    border: 1px solid {BORDER};
    border-bottom: none;
    padding: 8px 22px;
    font-family: {FONT_UI};
    font-size: {FONT_SIZE_NORMAL}pt;
    min-width: 110px;
}}
QTabBar::tab:selected {{
    background: {BG_BASE};
    color: {ACCENT};
    border-top: 2px solid {ACCENT};
}}
QTabBar::tab:hover:!selected {{
    color: {TEXT};
    background: {BG_BASE};
}}

/* ── Panels / Frames ── */
QFrame[class="panel"] {{
    background: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 6px;
}}

/* ── Labels ── */
QLabel[class="panel-title"] {{
    font-family: {FONT_UI};
    font-size: {FONT_SIZE_NORMAL}pt;
    font-weight: bold;
    color: {ACCENT};
    letter-spacing: 1px;
}}
QLabel[class="stat-value"] {{
    font-family: {FONT_DATA};
    font-size: 22pt;
    font-weight: bold;
}}
QLabel[class="stat-label"] {{
    font-family: {FONT_UI};
    font-size: {FONT_SIZE_SMALL}pt;
    color: {TEXT_DIM};
}}
QLabel[class="mono"] {{
    font-family: {FONT_DATA};
    font-size: {FONT_SIZE_SMALL}pt;
    color: {TEXT_DIM};
}}

/* ── Table ── */
QTableWidget {{
    background: {BG_PANEL};
    alternate-background-color: {BG_BASE};
    gridline-color: {BORDER};
    border: none;
    font-family: {FONT_DATA};
    font-size: {FONT_SIZE_SMALL}pt;
    selection-background-color: {ACCENT_DIM};
    selection-color: {TEXT};
}}
QTableWidget::item {{
    padding: 4px 10px;
    border-bottom: 1px solid {BORDER};
}}
QHeaderView::section {{
    background: {BG_BASE};
    color: {TEXT_DIM};
    font-family: {FONT_UI};
    font-size: {FONT_SIZE_SMALL}pt;
    font-weight: bold;
    padding: 6px 10px;
    border: none;
    border-bottom: 1px solid {BORDER};
    border-right: 1px solid {BORDER};
    letter-spacing: 1px;
}}
QHeaderView::section:last {{
    border-right: none;
}}

/* ── Scrollbar ── */
QScrollBar:vertical {{
    background: {BG_BASE};
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER_LIGHT};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {ACCENT_DIM};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: {BG_BASE};
    height: 8px;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER_LIGHT};
    border-radius: 4px;
}}

/* ── Buttons ── */
QPushButton {{
    background: {BG_PANEL};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 6px 16px;
    font-family: {FONT_UI};
    font-size: {FONT_SIZE_NORMAL}pt;
}}
QPushButton:hover {{
    border-color: {ACCENT};
    color: {ACCENT};
}}
QPushButton:pressed {{
    background: {ACCENT_DIM};
}}
QPushButton[class="danger"] {{
    background: {DANGER_BG};
    border-color: {DANGER};
    color: {DANGER};
}}
QPushButton[class="safe"] {{
    background: {SAFE_BG};
    border-color: {SAFE};
    color: {SAFE};
}}
QPushButton[class="warn"] {{
    background: {WARN_BG};
    border-color: {WARN};
    color: {WARN};
}}
QPushButton[class="accent"] {{
    background: {ACCENT_DIM};
    border-color: {ACCENT};
    color: {BG_BASE};
    font-weight: bold;
}}

/* ── ComboBox ── */
QComboBox {{
    background: {BG_INPUT};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px 10px;
    font-size: {FONT_SIZE_NORMAL}pt;
}}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {BG_PANEL};
    color: {TEXT};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT_DIM};
}}

/* ── Line Edit ── */
QLineEdit {{
    background: {BG_INPUT};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 5px 10px;
    font-family: {FONT_DATA};
    font-size: {FONT_SIZE_NORMAL}pt;
}}
QLineEdit:focus {{
    border-color: {ACCENT};
}}

/* ── Tooltip ── */
QToolTip {{
    background: {BG_PANEL};
    color: {TEXT};
    border: 1px solid {ACCENT};
    font-size: {FONT_SIZE_SMALL}pt;
    padding: 4px 8px;
}}

/* ── Status Bar ── */
QStatusBar {{
    background: {BG_PANEL};
    color: {TEXT_DIM};
    border-top: 1px solid {BORDER};
    font-family: {FONT_DATA};
    font-size: {FONT_SIZE_SMALL}pt;
}}

/* ── Splitter ── */
QSplitter::handle {{
    background: {BORDER};
}}
"""
