"""
BehaviorShield - Live Graphs Tab + History Tab
===============================================
Tab 2: Task-Manager style live scrolling charts for all logged fields.
Tab 3: Permanent warning history log with filter + CSV export.

Performance optimizations:
  â€¢ antialias=False - biggest single win for GPU-less machines
  â€¢ numpy ring-buffer in LiveChart instead of list.pop(0)
  â€¢ disableAutoRange() - no recalculation of Y axis bounds per push
  â€¢ MAX_POINTS = 60 (was 120)
  â€¢ History table: setUpdatesEnabled(False/True) around bulk fill
"""

from __future__ import annotations
from typing import List

import numpy as np
import pandas as pd

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QBrush
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QFrame, QTableWidget, QTableWidgetItem,
    QHeaderView, QPushButton, QComboBox, QFileDialog,
    QAbstractItemView,
)

from core.engine import ProcessFeatures, SystemSnapshot, HistoryLog, RISK_HIGH, RISK_MEDIUM
from ui.theme import (
    BG_PANEL, BG_BASE, BORDER, ACCENT, DANGER, WARN, SAFE,
    TEXT, TEXT_DIM, FONT_DATA, FONT_UI,
    DANGER_BG, WARN_BG, SAFE_BG,
    CHART_CPU, CHART_RAM, CHART_SENT, CHART_RECV,
    CHART_THREAD, CHART_HANDLE, CHART_CONN, CHART_RISK,
    verdict_color, risk_color,
)

import pyqtgraph as pg
pg.setConfigOption("background", "#050810")
pg.setConfigOption("foreground", "#64748b")
pg.setConfigOption("antialias", False)   # OFF - major speed-up on CPU rendering


# â”€â”€ Single Live Chart Widget â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class LiveChart(QFrame):
    """
    One scrolling filled area chart - Task Manager style.
    Uses numpy ring-buffer: O(1) insert, no list copies.
    """
    MAX_POINTS = 60   # 1 minute at 1s poll

    def __init__(self, title: str, unit: str, color: str, y_max: float = 100.0, parent=None):
        super().__init__(parent)
        self.title  = title
        self.unit   = unit
        self.color  = color
        self.y_max  = y_max
        self._buf   = np.zeros(self.MAX_POINTS, dtype=np.float32)
        self._idx   = 0
        self._count = 0
        self._x     = np.arange(self.MAX_POINTS, dtype=np.float32)
        self._build()

    def _build(self):
        self.setStyleSheet(f"""
            LiveChart {{
                background:{BG_PANEL};
                border:1px solid {BORDER};
                border-radius:6px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)

        top = QHBoxLayout()
        t = QLabel(self.title.upper())
        t.setStyleSheet(
            f"color:{TEXT_DIM}; font-family:{FONT_UI}; font-size:8pt; letter-spacing:1px;"
        )
        top.addWidget(t)
        top.addStretch()
        self._val_lbl = QLabel("-")
        self._val_lbl.setStyleSheet(
            f"color:{self.color}; font-family:{FONT_DATA}; font-size:9pt; font-weight:bold;"
        )
        top.addWidget(self._val_lbl)
        layout.addLayout(top)

        self._pw = pg.PlotWidget()
        self._pw.showAxis("left", False)
        self._pw.showAxis("bottom", False)
        self._pw.setMouseEnabled(False, False)
        self._pw.setMenuEnabled(False)
        self._pw.setYRange(0, self.y_max, padding=0.1)
        self._pw.showGrid(x=False, y=True, alpha=0.12)
        self._pw.getViewBox().setBackgroundColor("#050810")
        self._pw.getViewBox().disableAutoRange()  # prevents Y-axis recalc on every push

        pen   = pg.mkPen(color=self.color, width=1.5)
        brush = pg.mkBrush(color=self.color + "35")
        self._curve = self._pw.plot(
            self._x, self._buf,
            pen=pen, fillLevel=0, brush=brush,
        )
        layout.addWidget(self._pw)

        minmax = QHBoxLayout()
        self._min_lbl = QLabel("min: 0")
        self._max_lbl = QLabel("max: 0")
        for lbl in [self._min_lbl, self._max_lbl]:
            lbl.setStyleSheet(
                f"color:{TEXT_DIM}; font-family:{FONT_DATA}; font-size:7pt;"
            )
        minmax.addWidget(self._min_lbl)
        minmax.addStretch()
        minmax.addWidget(self._max_lbl)
        layout.addLayout(minmax)

    def push(self, value: float):
        self._buf[self._idx] = value
        self._idx   = (self._idx + 1) % self.MAX_POINTS
        self._count = min(self._count + 1, self.MAX_POINTS)

        if self._count < self.MAX_POINTS:
            view = self._buf[:self._count]
        else:
            view = np.roll(self._buf, -self._idx)

        self._curve.setData(self._x[:len(view)], view)
        self._val_lbl.setText(f"{value:.2f} {self.unit}")

        nonzero = view[view > 0]
        if len(nonzero):
            self._min_lbl.setText(f"min: {float(nonzero.min()):.1f}")
            self._max_lbl.setText(f"max: {float(nonzero.max()):.1f}")
        else:
            self._min_lbl.setText("min: 0")
            self._max_lbl.setText("max: 0")

    def set_unavailable(self):
        self._val_lbl.setText("-")
        self._pw.setVisible(False)


# â”€â”€ Live Graphs Tab â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class LiveGraphsTab(QWidget):
    """3x3 grid of live scrolling charts - system-wide aggregates."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        hdr = QHBoxLayout()
        title = QLabel("LIVE SYSTEM GRAPHS")
        title.setStyleSheet(
            f"color:{ACCENT}; font-family:{FONT_UI}; font-size:10pt; font-weight:bold; letter-spacing:2px;"
        )
        hdr.addWidget(title)
        hdr.addStretch()
        note = QLabel("System-wide aggregates | 1 min rolling window")
        note.setStyleSheet(f"color:{TEXT_DIM}; font-family:{FONT_UI}; font-size:8pt;")
        hdr.addWidget(note)
        root.addLayout(hdr)

        grid = QGridLayout()
        grid.setSpacing(10)

        self.charts = {
            "cpu":         LiveChart("CPU Usage",      "%",    CHART_CPU,    100.0),
            "ram":         LiveChart("RAM Total",      "MB",   CHART_RAM,    32768.0),
            "net_sent":    LiveChart("Net Sent",       "KB/s", CHART_SENT,   10240.0),
            "net_recv":    LiveChart("Net Recv",       "KB/s", CHART_RECV,   10240.0),
            "threads":     LiveChart("Thread Count",   "",     CHART_THREAD, 5000.0),
            "handles":     LiveChart("Open Handles",   "",     CHART_HANDLE, 50000.0),
            "connections": LiveChart("Connections",    "",     CHART_CONN,   1000.0),
            "risk_avg":    LiveChart("Avg Risk Score", "",     CHART_RISK,   1.0),
            "processes":   LiveChart("Process Count",  "",     ACCENT,       500.0),
        }

        positions = [
            ("cpu", 0, 0), ("ram", 0, 1), ("net_sent", 0, 2),
            ("net_recv", 1, 0), ("threads", 1, 1), ("handles", 1, 2),
            ("connections", 2, 0), ("risk_avg", 2, 1), ("processes", 2, 2),
        ]
        for key, row, col in positions:
            c = self.charts[key]
            c.setMinimumHeight(170)
            grid.addWidget(c, row, col)

        root.addLayout(grid, stretch=1)

    def update_snapshot(self, snap: SystemSnapshot):
        self.charts["cpu"].push(float(snap.cpu_avg or 0.0))
        self.charts["ram"].push(float((snap.ram_total_kb or 0.0) / 1024.0))
        self.charts["net_sent"].push(float((snap.net_sent_total or 0.0) / 1024.0))
        self.charts["net_recv"].push(float((snap.net_recv_total or 0.0) / 1024.0))
        self.charts["threads"].push(float(snap.thread_total or 0))
        self.charts["handles"].push(float(snap.handle_total or 0))
        self.charts["connections"].push(float(snap.connections_total or 0))
        self.charts["processes"].push(float(snap.process_count or 0))

    def update_features(self, features: List[ProcessFeatures]):
        if features:
            avg_risk = sum(f.risk_score for f in features) / len(features)
            self.charts["risk_avg"].push(avg_risk)
        else:
            self.charts["risk_avg"].push(0.0)


# â”€â”€ History Tab â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class HistoryTab(QWidget):
    """Permanent, append-only warning history. Filterable. CSV exportable."""

    COLUMNS    = ["timestamp", "process_name", "pid", "risk_score",
                  "verdict", "top_signal", "user_response"]
    COL_LABELS = ["Timestamp", "Process", "PID", "Risk Score",
                  "Verdict", "Cause", "User Response"]

    def __init__(self, history_log: HistoryLog, parent=None):
        super().__init__(parent)
        self.history_log = history_log
        self._build()
        self.refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # Toolbar
        toolbar = QHBoxLayout()
        title = QLabel("WARNING HISTORY")
        title.setStyleSheet(
            f"color:{ACCENT}; font-family:{FONT_UI}; font-size:10pt; font-weight:bold; letter-spacing:2px;"
        )
        toolbar.addWidget(title)
        toolbar.addStretch()

        filter_lbl = QLabel("Filter:")
        filter_lbl.setStyleSheet(f"color:{TEXT_DIM}; font-family:{FONT_UI}; font-size:9pt;")
        toolbar.addWidget(filter_lbl)

        self._filter = QComboBox()
        self._filter.addItems(["All", "Confirmed Malware", "False Positive", "Unresolved"])
        self._filter.setFixedWidth(160)
        self._filter.currentIndexChanged.connect(self.refresh)
        toolbar.addWidget(self._filter)

        ref_btn = QPushButton("Refresh")
        ref_btn.setFixedWidth(90)
        ref_btn.clicked.connect(self.refresh)
        toolbar.addWidget(ref_btn)

        exp_btn = QPushButton("Export CSV")
        exp_btn.setFixedWidth(110)
        exp_btn.clicked.connect(self._export)
        toolbar.addWidget(exp_btn)
        root.addLayout(toolbar)

        # Stats row
        stats = QHBoxLayout()
        self._stat_total     = self._make_stat("Total Alerts",    "0", ACCENT)
        self._stat_confirmed = self._make_stat("Confirmed",        "0", DANGER)
        self._stat_fp        = self._make_stat("False Positives",  "0", SAFE)
        self._stat_open      = self._make_stat("Unresolved",       "0", WARN)
        for w in [self._stat_total, self._stat_confirmed, self._stat_fp, self._stat_open]:
            stats.addWidget(w)
        stats.addStretch()
        root.addLayout(stats)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(len(self.COLUMNS))
        self._table.setHorizontalHeaderLabels([l.upper() for l in self.COL_LABELS])
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table.setShowGrid(False)
        self._table.setSortingEnabled(False)
        for i, w in enumerate([145, 140, 55, 80, 95, 250, 120]):
            self._table.setColumnWidth(i, w)
        root.addWidget(self._table, stretch=1)

        note = QLabel(
            "!  This log is permanent and cannot be deleted. It serves as the security audit trail."
        )
        note.setStyleSheet(
            f"color:{TEXT_DIM}; font-family:{FONT_UI}; font-size:8pt; padding:4px;"
        )
        root.addWidget(note)

    def _make_stat(self, label: str, value: str, color: str) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            f"background:{BG_PANEL}; border:1px solid {BORDER}; border-radius:5px;"
        )
        frame.setFixedHeight(60)
        frame.setMinimumWidth(120)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(2)
        val_lbl = QLabel(value)
        val_lbl.setStyleSheet(
            f"color:{color}; font-family:{FONT_DATA}; font-size:16pt; font-weight:bold; border:none;"
        )
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color:{TEXT_DIM}; font-family:{FONT_UI}; font-size:8pt; border:none;")
        lay.addWidget(val_lbl)
        lay.addWidget(lbl)
        return frame

    def add_entry(self, features: ProcessFeatures, user_response: str):
        self.history_log.append(features, user_response)
        self.refresh()

    def refresh(self):
        df = self.history_log.load()

        total      = len(df)
        confirmed  = int((df["user_response"] == "confirmed").sum())      if not df.empty else 0
        fp         = int((df["user_response"] == "false_positive").sum()) if not df.empty else 0
        unresolved = int((df["user_response"] == "unresolved").sum())     if not df.empty else 0

        for frame, val in [
            (self._stat_total, str(total)),
            (self._stat_confirmed, str(confirmed)),
            (self._stat_fp, str(fp)),
            (self._stat_open, str(unresolved)),
        ]:
            frame.findChildren(QLabel)[0].setText(val)

        filter_map = {
            "Confirmed Malware": "confirmed",
            "False Positive":    "false_positive",
            "Unresolved":        "unresolved",
        }
        sel = self._filter.currentText()
        if sel in filter_map and not df.empty:
            df = df[df["user_response"] == filter_map[sel]]

        if not df.empty:
            df = df.sort_values("timestamp", ascending=False)

        table = self._table
        table.setUpdatesEnabled(False)
        table.setRowCount(len(df))

        for row_idx, (_, row) in enumerate(df.iterrows()):
            table.setRowHeight(row_idx, 28)
            response = str(row.get("user_response", ""))

            if response == "confirmed":
                row_bg = QBrush(QColor(DANGER_BG))
            elif response == "false_positive":
                row_bg = QBrush(QColor(SAFE_BG))
            else:
                row_bg = QBrush(QColor(BG_PANEL))

            for col_idx, col in enumerate(self.COLUMNS):
                val = str(row.get(col, ""))
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                item.setBackground(row_bg)

                if col == "verdict":
                    item.setForeground(QBrush(QColor(verdict_color(val))))
                elif col == "user_response":
                    c = {"confirmed": DANGER, "false_positive": SAFE, "unresolved": WARN}.get(val, TEXT_DIM)
                    item.setForeground(QBrush(QColor(c)))
                elif col == "risk_score":
                    try:
                        item.setForeground(QBrush(QColor(risk_color(float(val)))))
                    except Exception:
                        pass
                elif col == "process_name":
                    item.setForeground(QBrush(QColor(ACCENT)))
                else:
                    item.setForeground(QBrush(QColor(TEXT)))

                table.setItem(row_idx, col_idx, item)

        table.setUpdatesEnabled(True)

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Warning History", "warning_history_export.csv",
            "CSV Files (*.csv)"
        )
        if path:
            self.history_log.export(path)


