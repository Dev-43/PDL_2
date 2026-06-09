"""
BehaviorShield - Dashboard Tab
================================
Tab 1: Live metric cards + process risk table + false positive queue.

Performance optimizations vs original:
  â€¢ MAX_POINTS = 60 (was 120) - half the chart data, 2x faster redraws
  â€¢ numpy arrays instead of Python lists for chart data - avoids list copy on every push
  â€¢ setData called with pre-built ndarray - avoids repeated list() conversion
  â€¢ Table items batch-built before setItem() to minimize Qt redraws
  â€¢ Metric cards only redraw when value actually changes (delta threshold)
"""

from __future__ import annotations
from typing import List, Optional

import numpy as np

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QBrush
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QTableWidget, QTableWidgetItem,
    QHeaderView, QPushButton, QSplitter,
    QScrollArea, QSizePolicy, QAbstractItemView,
)

from core.engine import ProcessFeatures, RISK_HIGH, RISK_MEDIUM
from ui.theme import (
    BG_PANEL, BG_BASE, BORDER, ACCENT, DANGER, WARN, SAFE,
    TEXT, TEXT_DIM, FONT_DATA, FONT_UI,
    DANGER_BG, WARN_BG, SAFE_BG,
    risk_color, verdict_color,
    CHART_CPU, CHART_RAM, CHART_SENT, CHART_RECV,
)

import pyqtgraph as pg
pg.setConfigOption("background", "#050810")
pg.setConfigOption("foreground", "#64748b")
pg.setConfigOption("antialias", False)   # Disable antialiasing - major speed win


# â”€â”€ Metric Card â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class MetricCard(QFrame):
    """
    Task-Manager style scrolling filled area chart.
    Uses numpy ring-buffer for O(1) append; only redraws when value changes.
    """
    MAX_POINTS = 60   # 60 pts x 1s = 1 minute of history

    def __init__(self, title: str, unit: str, color: str, y_max: float = 100.0, parent=None):
        super().__init__(parent)
        self.title  = title
        self.unit   = unit
        self.color  = color
        self.y_max  = y_max
        self._buf   = np.zeros(self.MAX_POINTS, dtype=np.float32)
        self._idx   = 0      # ring-buffer write pointer
        self._count = 0      # filled count
        self._prev  = -1.0   # last emitted value (skip redraw if unchanged)
        self._x     = np.arange(self.MAX_POINTS, dtype=np.float32)
        self._available = True
        self._build()

    def _build(self):
        self.setMinimumHeight(160)
        self.setMinimumWidth(180)
        self.setStyleSheet(f"""
            MetricCard {{
                background: {BG_PANEL};
                border: 1px solid {BORDER};
                border-radius: 6px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        # Title row
        title_row = QHBoxLayout()
        self._title_lbl = QLabel(self.title.upper())
        self._title_lbl.setStyleSheet(
            f"color:{TEXT_DIM}; font-family:{FONT_UI}; font-size:8pt; letter-spacing:2px;"
        )
        title_row.addWidget(self._title_lbl)
        title_row.addStretch()
        self._peak_lbl = QLabel("peak: --")
        self._peak_lbl.setStyleSheet(
            f"color:{TEXT_DIM}; font-family:{FONT_DATA}; font-size:8pt;"
        )
        title_row.addWidget(self._peak_lbl)
        layout.addLayout(title_row)

        # Current value label
        self._value_lbl = QLabel("--")
        self._value_lbl.setStyleSheet(
            f"color:{self.color}; font-family:{FONT_DATA}; font-size:18pt; font-weight:bold;"
        )
        layout.addWidget(self._value_lbl)

        # Chart - minimal setup for speed
        self._pw = pg.PlotWidget()
        self._pw.setMinimumHeight(80)
        self._pw.setMaximumHeight(110)
        self._pw.showAxis("left", False)
        self._pw.showAxis("bottom", False)
        self._pw.setMouseEnabled(False, False)
        self._pw.setMenuEnabled(False)
        self._pw.setYRange(0, self.y_max, padding=0.05)
        self._pw.getViewBox().setBackgroundColor("#050810")
        self._pw.showGrid(x=False, y=True, alpha=0.15)
        # Disable auto-range - prevents expensive recalculation on each push
        self._pw.getViewBox().disableAutoRange()

        pen   = pg.mkPen(color=self.color, width=1.5)
        brush = pg.mkBrush(color=self.color + "40")
        self._curve = self._pw.plot(
            self._x, self._buf,
            pen=pen, fillLevel=0, brush=brush,
        )
        layout.addWidget(self._pw)

        # Unavailable overlay
        self._unavail_lbl = QLabel("Logger expansion required\nfor this metric")
        self._unavail_lbl.setAlignment(Qt.AlignCenter)
        self._unavail_lbl.setStyleSheet(
            f"color:{TEXT_DIM}; font-size:8pt; font-family:{FONT_UI};"
        )
        self._unavail_lbl.setVisible(False)
        layout.addWidget(self._unavail_lbl)

    def push(self, value: float):
        """Push value into ring-buffer and redraw. Skips redraw if value unchanged."""
        # Write into ring buffer
        self._buf[self._idx] = value
        self._idx = (self._idx + 1) % self.MAX_POINTS
        self._count = min(self._count + 1, self.MAX_POINTS)

        # Skip chart redraw if value hasn't meaningfully changed
        if abs(value - self._prev) < 0.05 and self._count > 1:
            return
        self._prev = value

        # Ordered view: roll buffer so newest is last
        if self._count < self.MAX_POINTS:
            view = self._buf[:self._count]
        else:
            view = np.roll(self._buf, -self._idx)

        self._curve.setData(self._x[:len(view)], view)
        self._value_lbl.setText(f"{value:.1f}{self.unit}")
        peak = float(np.max(view))
        self._peak_lbl.setText(f"peak: {peak:.1f}{self.unit}")

    def set_unavailable(self, msg: str = "Logger expansion required"):
        self._available = False
        self._pw.setVisible(False)
        self._unavail_lbl.setText(msg)
        self._unavail_lbl.setVisible(True)
        self._value_lbl.setText("--")
        self._peak_lbl.setText("")

    def set_available(self):
        self._available = True
        self._pw.setVisible(True)
        self._unavail_lbl.setVisible(False)


# â”€â”€ Process Table â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class ProcessTable(QWidget):
    row_selected = pyqtSignal(object)   # ProcessFeatures

    DEFAULT_COLS = ["process_name", "pid", "risk_score", "verdict"]
    EXTRA_COLS   = ["ram_avg_kb", "cpu_avg", "thread_growth", "handle_avg",
                    "connections_max", "is_elevated", "window_start"]
    COL_LABELS   = {
        "process_name":    "Process",
        "pid":             "PID",
        "risk_score":      "Risk Score",
        "verdict":         "Verdict",
        "ram_avg_kb":      "RAM (KB avg)",
        "cpu_avg":         "CPU %",
        "thread_growth":   "Thread Delta",
        "handle_avg":      "Handles",
        "connections_max": "Connections",
        "is_elevated":     "Elevated",
        "window_start":    "Window",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._expanded = False
        self._features: List[ProcessFeatures] = []
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setStyleSheet(f"background:{BG_PANEL}; border-bottom: 1px solid {BORDER};")
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(12, 8, 12, 8)

        title = QLabel("PROCESS RISK TABLE")
        title.setStyleSheet(
            f"color:{ACCENT}; font-family:{FONT_UI}; font-size:9pt; font-weight:bold; letter-spacing:2px;"
        )
        h_lay.addWidget(title)
        h_lay.addStretch()

        self._count_lbl = QLabel("0 windows")
        self._count_lbl.setStyleSheet(f"color:{TEXT_DIM}; font-family:{FONT_DATA}; font-size:8pt;")
        h_lay.addWidget(self._count_lbl)

        self._expand_btn = QPushButton("+ Expand Columns")
        self._expand_btn.setFixedHeight(26)
        self._expand_btn.setStyleSheet(f"""
            QPushButton {{
                background:{BG_BASE}; color:{TEXT_DIM};
                border:1px solid {BORDER}; border-radius:3px;
                padding:2px 10px; font-size:8pt;
            }}
            QPushButton:hover {{ color:{ACCENT}; border-color:{ACCENT}; }}
        """)
        self._expand_btn.clicked.connect(self._toggle_expand)
        h_lay.addWidget(self._expand_btn)
        layout.addWidget(header)

        # Table - configured for performance
        self._table = QTableWidget()
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table.setShowGrid(False)
        # Disable sorting during bulk updates
        self._table.setSortingEnabled(False)
        self._table.cellClicked.connect(self._on_click)
        layout.addWidget(self._table)
        self._set_columns()

    def _current_cols(self) -> list[str]:
        if self._expanded:
            return self.DEFAULT_COLS + self.EXTRA_COLS
        return self.DEFAULT_COLS

    def _set_columns(self):
        cols = self._current_cols()
        self._table.setColumnCount(len(cols))
        self._table.setHorizontalHeaderLabels(
            [self.COL_LABELS.get(c, c).upper() for c in cols]
        )
        col_widths = {
            "process_name": 160, "pid": 60, "risk_score": 150,
            "verdict": 100, "ram_avg_kb": 90, "cpu_avg": 70,
            "thread_growth": 80, "handle_avg": 80,
            "connections_max": 100, "is_elevated": 70, "window_start": 80,
        }
        for i, col in enumerate(cols):
            if col in col_widths:
                self._table.setColumnWidth(i, col_widths[col])

    def update_features(self, features: List[ProcessFeatures]):
        self._features = features
        self._count_lbl.setText(f"{len(features)} windows")
        cols  = self._current_cols()
        table = self._table

        # Batch update: suspend signals + layouts during rebuild
        table.setUpdatesEnabled(False)
        table.setRowCount(len(features))

        for row, f in enumerate(features):
            table.setRowHeight(row, 30)
            if f.risk_score >= RISK_HIGH:
                row_bg = QColor(DANGER_BG)
            elif f.risk_score >= RISK_MEDIUM:
                row_bg = QColor(WARN_BG)
            else:
                row_bg = QColor(BG_PANEL)
            bg_brush = QBrush(row_bg)

            for col_idx, col in enumerate(cols):
                item = self._make_item(f, col, bg_brush)
                table.setItem(row, col_idx, item)

        table.setUpdatesEnabled(True)

    def _make_item(self, f: ProcessFeatures, col: str, bg: QBrush) -> QTableWidgetItem:
        if col == "risk_score":
            pct = int(f.risk_score * 100)
            item = QTableWidgetItem(f"  {f.risk_score:.2f}  ({pct}%)")
            item.setForeground(QBrush(QColor(risk_color(f.risk_score))))
        elif col == "verdict":
            item = QTableWidgetItem(f"  {f.verdict}")
            item.setForeground(QBrush(QColor(verdict_color(f.verdict))))
        elif col == "process_name":
            item = QTableWidgetItem(f.process_name)
            item.setForeground(QBrush(QColor(ACCENT)))
        elif col == "pid":
            item = QTableWidgetItem(str(f.pid))
            item.setForeground(QBrush(QColor(TEXT_DIM)))
        elif col == "is_elevated":
            val = f.is_elevated
            item = QTableWidgetItem("YES !" if val else ("--" if val is None else "no"))
            if val:
                item.setForeground(QBrush(QColor(DANGER)))
            else:
                item.setForeground(QBrush(QColor(TEXT)))
        else:
            raw = getattr(f, col, None)
            if raw is None:
                text = "--"
            elif isinstance(raw, float):
                text = f"{raw:.1f}"
            else:
                text = str(raw)
            item = QTableWidgetItem(text)
            item.setForeground(QBrush(QColor(TEXT)))

        item.setBackground(bg)
        item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        return item

    def _toggle_expand(self):
        self._expanded = not self._expanded
        self._expand_btn.setText("- Collapse" if self._expanded else "+ Expand Columns")
        self._set_columns()
        self.update_features(self._features)

    def _on_click(self, row: int, _col: int):
        if row < len(self._features):
            self.row_selected.emit(self._features[row])


# â”€â”€ False Positive Queue â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class FalsePositiveQueue(QWidget):
    response_given = pyqtSignal(object, str)   # (ProcessFeatures, response)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pending: List[ProcessFeatures] = []
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setStyleSheet(f"background:{BG_PANEL}; border-bottom:1px solid {BORDER};")
        h = QHBoxLayout(header)
        h.setContentsMargins(12, 8, 12, 8)
        title = QLabel("CONFIRMATION QUEUE")
        title.setStyleSheet(
            f"color:{WARN}; font-family:{FONT_UI}; font-size:9pt; font-weight:bold; letter-spacing:2px;"
        )
        h.addWidget(title)
        h.addStretch()
        self._queue_count = QLabel("0")
        self._queue_count.setStyleSheet(
            f"color:{WARN}; font-family:{FONT_DATA}; font-size:10pt; font-weight:bold;"
        )
        h.addWidget(self._queue_count)
        layout.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"background:{BG_BASE}; border:none;")

        self._cards_widget = QWidget()
        self._cards_widget.setStyleSheet(f"background:{BG_BASE};")
        self._cards_layout = QVBoxLayout(self._cards_widget)
        self._cards_layout.setContentsMargins(8, 8, 8, 8)
        self._cards_layout.setSpacing(8)

        self._empty_lbl = QLabel("No flagged processes\nAll clear")
        self._empty_lbl.setAlignment(Qt.AlignCenter)
        self._empty_lbl.setStyleSheet(
            f"color:{TEXT_DIM}; font-family:{FONT_UI}; font-size:9pt;"
        )
        self._cards_layout.addWidget(self._empty_lbl)
        self._cards_layout.addStretch()

        scroll.setWidget(self._cards_widget)
        layout.addWidget(scroll)

    def add_process(self, f: ProcessFeatures):
        if any(p.pid == f.pid for p in self._pending):
            return
        self._pending.append(f)
        self._empty_lbl.setVisible(False)
        self._add_card(f)
        self._queue_count.setText(str(len(self._pending)))

    def _add_card(self, f: ProcessFeatures):
        card = QFrame()
        border_color = DANGER if f.risk_score >= RISK_HIGH else WARN
        card.setStyleSheet(f"""
            QFrame {{
                background:{BG_PANEL};
                border:1px solid {border_color};
                border-radius:5px;
            }}
        """)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(10, 10, 10, 10)
        cl.setSpacing(6)

        name = QLabel(f.process_name)
        name.setStyleSheet(
            f"color:{DANGER}; font-family:{FONT_DATA}; font-size:10pt; font-weight:bold; border:none;"
        )
        cl.addWidget(name)

        info = QLabel(f"PID {f.pid}  |  Risk {f.risk_score:.2f}  |  {f.verdict}")
        info.setStyleSheet(
            f"color:{TEXT_DIM}; font-family:{FONT_DATA}; font-size:8pt; border:none;"
        )
        cl.addWidget(info)

        if f.top_signal:
            cause = QLabel(f"! {f.top_signal}")
            cause.setWordWrap(True)
            cause.setStyleSheet(
                f"color:{WARN}; font-family:{FONT_UI}; font-size:8pt; border:none;"
            )
            cl.addWidget(cause)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        for label, cls, resp in [
            ("Confirm Malware", "danger", "confirmed"),
            ("False Positive",  "safe",   "false_positive"),
            ("? Not Sure",   "warn",   "unresolved"),
        ]:
            btn = QPushButton(label)
            btn.setFixedHeight(26)
            btn.setStyleSheet(self._btn_style(cls))
            btn.clicked.connect(lambda _, fr=f, r=resp, c=card: self._respond(fr, r, c))
            btn_row.addWidget(btn)
        cl.addLayout(btn_row)

        self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)

    def _respond(self, f: ProcessFeatures, response: str, card: QFrame):
        card.setVisible(False)
        self._pending = [p for p in self._pending if p.pid != f.pid]
        self._queue_count.setText(str(len(self._pending)))
        if not self._pending:
            self._empty_lbl.setVisible(True)
        self.response_given.emit(f, response)

    @staticmethod
    def _btn_style(cls: str) -> str:
        colors = {"danger": (DANGER, DANGER_BG), "safe": (SAFE, SAFE_BG), "warn": (WARN, WARN_BG)}
        fg, bg = colors.get(cls, (TEXT, BG_PANEL))
        return f"""
            QPushButton {{
                background:{bg}; color:{fg};
                border:1px solid {fg}; border-radius:3px;
                padding:2px 6px; font-size:8pt;
            }}
            QPushButton:hover {{ background:{fg}; color:{BG_BASE}; }}
        """


# â”€â”€ Dashboard Tab â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class DashboardTab(QWidget):
    process_whitelisted = pyqtSignal(str)
    warning_logged      = pyqtSignal(object, str)

    def __init__(self, db_reader, parent=None):
        super().__init__(parent)
        self.db_reader = db_reader
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # Metric Cards
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(10)
        self.card_cpu  = MetricCard("CPU",      "%",     CHART_CPU,  100.0)
        self.card_ram  = MetricCard("RAM",      " MB",   CHART_RAM,  32768.0)
        self.card_sent = MetricCard("Net Sent", " KB/s", CHART_SENT, 10240.0)
        self.card_recv = MetricCard("Net Recv", " KB/s", CHART_RECV, 10240.0)
        for card in [self.card_cpu, self.card_ram, self.card_sent, self.card_recv]:
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            cards_layout.addWidget(card)
        root.addLayout(cards_layout)

        # Table + FP queue split
        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet(f"QSplitter::handle {{ background:{BORDER}; width:2px; }}")

        table_frame = QFrame()
        table_frame.setStyleSheet(
            f"background:{BG_PANEL}; border:1px solid {BORDER}; border-radius:6px;"
        )
        tf_lay = QVBoxLayout(table_frame)
        tf_lay.setContentsMargins(0, 0, 0, 0)
        self.process_table = ProcessTable()
        tf_lay.addWidget(self.process_table)
        splitter.addWidget(table_frame)

        self.fp_queue = FalsePositiveQueue()
        self.fp_queue.setMinimumWidth(240)
        self.fp_queue.setMaximumWidth(320)
        self.fp_queue.response_given.connect(self._on_fp_response)
        splitter.addWidget(self.fp_queue)
        splitter.setSizes([900, 280])
        root.addWidget(splitter, stretch=1)

        # Schema warning banner
        self._schema_banner = QLabel()
        self._schema_banner.setStyleSheet(f"""
            background:{WARN_BG}; color:{WARN};
            border:1px solid {WARN}; border-radius:4px;
            padding:6px 12px; font-family:{FONT_UI}; font-size:9pt;
        """)
        self._schema_banner.setVisible(False)
        root.addWidget(self._schema_banner)

        self._check_schema()

    def _check_schema(self):
        cols = set(self.db_reader.columns)
        missing = sorted(self.db_reader.ALL_EXPECTED - cols)
        if missing:
            self._schema_banner.setText(
                f"Logger expansion needed for full detection. Missing columns: {', '.join(missing)}"
            )
            self._schema_banner.setVisible(True)
        else:
            self._schema_banner.setVisible(False)

        if "cpu_usage" in cols:
            self.card_cpu.set_available()
        else:
            self.card_cpu.set_unavailable("Needs cpu_usage column")

        if "net_sent" in cols:
            self.card_sent.set_available()
        else:
            self.card_sent.set_unavailable("Needs net_sent column")

        if "net_recv" in cols:
            self.card_recv.set_available()
        else:
            self.card_recv.set_unavailable("Needs net_recv column")

    # â”€â”€ Public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def update_features(self, features: List[ProcessFeatures]):
        self._check_schema()
        self.process_table.update_features(features)
        for f in features:
            if f.risk_score >= RISK_HIGH:
                self.fp_queue.add_process(f)

    def update_snapshot(self, snapshot):
        self.card_cpu.push(float(snapshot.cpu_avg or 0.0))
        self.card_ram.push(float((snapshot.ram_total_kb or 0.0) / 1024.0))
        self.card_sent.push(float((snapshot.net_sent_total or 0.0) / 1024.0))
        self.card_recv.push(float((snapshot.net_recv_total or 0.0) / 1024.0))

    def _on_fp_response(self, features: ProcessFeatures, response: str):
        if response == "false_positive":
            self.process_whitelisted.emit(features.process_name)
        self.warning_logged.emit(features, response)


