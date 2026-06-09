"""
BehaviorShield - Main Application Window
========================================
Ties all tabs, worker thread, tray icon, and popups together.
"""

from __future__ import annotations

from PyQt5.QtCore import QPoint, Qt, pyqtSlot
from PyQt5.QtGui import QColor, QIcon, QPainter, QPixmap, QPolygon
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QSystemTrayIcon,
    QTabWidget,
)

from core.engine import (
    DBReader,
    FeatureEngine,
    HistoryLog,
    ProcessFeatures,
    RISK_HIGH,
    WarningEvent,
    Whitelist,
    _MODEL,
    _MODEL_LOAD_STATUS,
)
from core.worker import PollWorker
from ui.tab_dashboard import DashboardTab
from ui.tab_graphs_history import HistoryTab, LiveGraphsTab
from ui.theme import (
    ACCENT,
    BG_BASE,
    BG_PANEL,
    BORDER,
    DANGER,
    FONT_DATA,
    FONT_UI,
    SAFE,
    STYLESHEET,
    TEXT_DIM,
    WARN,
)
from ui.warning_popup import WarningPopup


def _make_tray_icon(color: str) -> QIcon:
    px = QPixmap(32, 32)
    px.fill(Qt.transparent)
    painter = QPainter(px)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.NoPen)
    shield = QPolygon(
        [
            QPoint(16, 2),
            QPoint(30, 8),
            QPoint(30, 18),
            QPoint(16, 30),
            QPoint(2, 18),
            QPoint(2, 8),
        ]
    )
    painter.drawPolygon(shield)
    painter.end()
    return QIcon(px)


class MainWindow(QMainWindow):
    POLL_INTERVAL_MS = 1000

    def __init__(self, db_path: str):
        super().__init__()

        self.db_reader = DBReader(db_path)
        self.engine = FeatureEngine()
        self.whitelist = Whitelist(self._data_path("whitelist.txt"))
        self.history = HistoryLog(self._data_path("warning_history.csv"))
        self._active_popup: WarningPopup | None = None
        self._pending_warning_events: list[WarningEvent] = []

        model_status = (
            "ML: Isolation Forest ACTIVE"
            if _MODEL is not None
            else f"ML: Heuristic ({_MODEL_LOAD_STATUS})"
        )
        self.setWindowTitle(f"BehaviorShield - Behavioral Malware Detection [{model_status}]")
        self.setMinimumSize(1200, 750)
        self.resize(1400, 860)
        self.setStyleSheet(STYLESHEET)

        self._build_tabs()
        self._build_statusbar()
        self._build_tray()
        self._start_worker()

    def _build_tabs(self):
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        self.tab_dashboard = DashboardTab(self.db_reader)
        self.tab_dashboard.process_whitelisted.connect(self._on_whitelisted)
        self.tab_dashboard.warning_logged.connect(self._on_warning_logged)
        self.tabs.addTab(self.tab_dashboard, "  Dashboard  ")

        self.tab_graphs = LiveGraphsTab()
        self.tabs.addTab(self.tab_graphs, "  Live Graphs  ")

        self.tab_history = HistoryTab(self.history)
        self.tabs.addTab(self.tab_history, "  Warning History  ")

        self.setCentralWidget(self.tabs)

    def _build_statusbar(self):
        sb = self.statusBar()
        sb.setStyleSheet(
            f"""
            QStatusBar {{
                background:{BG_PANEL}; border-top:1px solid {BORDER};
                font-family:{FONT_DATA}; font-size:8pt; color:{TEXT_DIM};
            }}
        """
        )

        self._status_lbl = QLabel("Initializing...")
        self._status_lbl.setStyleSheet(f"color:{TEXT_DIM}; padding:0 8px;")
        sb.addWidget(self._status_lbl)

        self._db_lbl = QLabel(f"DB: {self.db_reader.db_path}")
        self._db_lbl.setStyleSheet(
            f"color:{TEXT_DIM}; padding:0 8px; font-family:{FONT_DATA}; font-size:8pt;"
        )
        sb.addPermanentWidget(self._db_lbl)

        model_color = SAFE if _MODEL is not None else WARN
        model_text = "ML Active" if _MODEL is not None else "Heuristic"
        self._model_lbl = QLabel(model_text)
        self._model_lbl.setStyleSheet(
            f"color:{model_color}; padding:0 8px; font-family:{FONT_DATA}; font-size:8pt;"
        )
        self._model_lbl.setToolTip(f"Model load status: {_MODEL_LOAD_STATUS}")
        sb.addPermanentWidget(self._model_lbl)

        self._popup_btn = QPushButton("Popups ON")
        self._popup_btn.setFixedHeight(22)
        self._popup_btn.setCheckable(True)
        self._popup_btn.setChecked(True)
        self._popup_btn.setToolTip(
            "Toggle alert popups.\n"
            "Popups only appear for risk score >= 0.95.\n"
            "The table and confirmation queue are always active."
        )
        self._popup_btn.setStyleSheet(
            f"""
            QPushButton {{
                background:{BG_BASE}; color:{SAFE};
                border:1px solid {SAFE}; border-radius:3px;
                padding:1px 8px; font-size:8pt; font-family:{FONT_UI};
            }}
            QPushButton:checked {{
                background:{SAFE}22; color:{SAFE};
            }}
            QPushButton:!checked {{
                background:{BG_BASE}; color:{TEXT_DIM};
                border-color:{BORDER};
            }}
            QPushButton:hover {{ border-color:{ACCENT}; }}
        """
        )
        self._popup_btn.toggled.connect(self._on_popup_toggle)
        sb.addPermanentWidget(self._popup_btn)

        self._live_dot = QLabel("*")
        self._live_dot.setStyleSheet(f"color:{TEXT_DIM}; padding:0 8px;")
        sb.addPermanentWidget(self._live_dot)

        self._rows_lbl = QLabel("0 rows")
        self._rows_lbl.setStyleSheet(f"color:{TEXT_DIM}; padding:0 8px;")
        sb.addPermanentWidget(self._rows_lbl)

    def _build_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(_make_tray_icon(SAFE))
        self._tray.setToolTip("BehaviorShield - All clear")

        menu = QMenu()
        menu.setStyleSheet(
            f"""
            QMenu {{ background:{BG_PANEL}; color:{TEXT_DIM}; border:1px solid {BORDER}; }}
            QMenu::item:selected {{ background:{ACCENT}; color:{BG_BASE}; }}
        """
        )
        show_action = QAction("Open BehaviorShield", self)
        show_action.triggered.connect(self.show_window)
        menu.addAction(show_action)
        menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(QApplication.quit)
        menu.addAction(quit_action)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _start_worker(self):
        self.worker = PollWorker(
            db_reader=self.db_reader,
            engine=self.engine,
            whitelist=self.whitelist,
            interval_ms=self.POLL_INTERVAL_MS,
        )
        self.worker.features_ready.connect(self._on_features)
        self.worker.snapshot_ready.connect(self._on_snapshot)
        self.worker.warning_ready.connect(self._on_warning)
        self.worker.status_changed.connect(self._on_status)
        self.worker.row_count_ready.connect(self._on_row_count)
        self.worker.start()

    @pyqtSlot(bool)
    def _on_popup_toggle(self, checked: bool):
        self.worker.set_popups_enabled(checked)
        if checked:
            self._popup_btn.setText("Popups ON")
            self._on_status("Alert popups enabled (threshold: score >= 0.95)", "info")
        else:
            self._popup_btn.setText("Popups OFF")
            self._on_status("Alert popups silenced - table and queue still active", "warn")

    @pyqtSlot(list)
    def _on_features(self, features: list):
        self.tab_dashboard.update_features(features)
        self.tab_graphs.update_features(features)

        if features:
            max_risk = max(f.risk_score for f in features)
            if max_risk >= RISK_HIGH:
                self._set_tray_danger()
            else:
                self._set_tray_safe()

    @pyqtSlot(object)
    def _on_snapshot(self, snapshot):
        self.tab_dashboard.update_snapshot(snapshot)
        self.tab_graphs.update_snapshot(snapshot)

    @pyqtSlot(object)
    def _on_warning(self, event: WarningEvent):
        if self._active_popup and self._active_popup.isVisible():
            self._pending_warning_events.append(event)
            return

        popup = WarningPopup(event, parent=self)
        popup.process_responded.connect(self._on_popup_response)
        popup.all_dismissed.connect(self._on_popup_dismissed)
        self._active_popup = popup

        if hasattr(self, "_tray"):
            names = ", ".join(f.process_name for f in event.processes[:3])
            self._tray.showMessage(
                "Threat Detected",
                f"{names} flagged as HIGH RISK",
                QSystemTrayIcon.Critical,
                5000,
            )
        popup.show()
        popup.raise_()

    @pyqtSlot(str, str)
    def _on_status(self, message: str, level: str):
        color = {"info": TEXT_DIM, "warn": WARN, "error": DANGER}.get(level, TEXT_DIM)
        self._status_lbl.setText(message)
        self._status_lbl.setStyleSheet(f"color:{color}; padding:0 8px;")
        dot = {"info": SAFE, "warn": WARN, "error": DANGER}.get(level, TEXT_DIM)
        self._live_dot.setStyleSheet(f"color:{dot}; padding:0 8px;")

    @pyqtSlot(int)
    def _on_row_count(self, count: int):
        self._rows_lbl.setText(f"{count:,} rows")

    @pyqtSlot(object, str)
    def _on_popup_response(self, features: ProcessFeatures, response: str):
        self.history.append(features, response)
        self.tab_history.refresh()

    @pyqtSlot()
    def _on_popup_dismissed(self):
        self._active_popup = None
        if self._pending_warning_events:
            next_event = self._pending_warning_events.pop(0)
            self._on_warning(next_event)
            return
        self._set_tray_safe()

    @pyqtSlot(str)
    def _on_whitelisted(self, process_name: str):
        self.whitelist.add(process_name)
        self._on_status(f"'{process_name}' added to whitelist", "info")

    @pyqtSlot(object, str)
    def _on_warning_logged(self, features: ProcessFeatures, response: str):
        self.history.append(features, response)
        self.tab_history.refresh()

    def _set_tray_danger(self):
        if hasattr(self, "_tray"):
            self._tray.setIcon(_make_tray_icon(DANGER))
            self._tray.setToolTip("BehaviorShield - THREAT DETECTED")

    def _set_tray_safe(self):
        if hasattr(self, "_tray"):
            self._tray.setIcon(_make_tray_icon(SAFE))
            self._tray.setToolTip("BehaviorShield - All clear")

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.show_window()

    def show_window(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        if hasattr(self, "_tray") and self._tray.isVisible():
            self.hide()
            self._tray.showMessage(
                "BehaviorShield",
                "Still running in background. Right-click tray icon to quit.",
                QSystemTrayIcon.Information,
                3000,
            )
            event.ignore()
        else:
            self._shutdown()
            event.accept()

    def _shutdown(self):
        if hasattr(self, "worker"):
            self.worker.stop()
            self.worker.wait(2000)

    @staticmethod
    def _data_path(filename: str) -> str:
        return filename
