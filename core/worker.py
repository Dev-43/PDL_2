"""
BehaviorShield - Worker Thread
==============================
Polls logs.db on a background QThread.
Emits typed signals so the main thread never touches the DB directly.
"""

from __future__ import annotations

import time
from typing import List

from PyQt5.QtCore import QMutex, QMutexLocker, QThread, pyqtSignal

from core.engine import (
    POPUP_THRESHOLD,
    RISK_HIGH,
    DBReader,
    FeatureEngine,
    ProcessFeatures,
    SYSTEM_PROCESSES,
    SystemSnapshot,
    WarningEvent,
    Whitelist,
)

UI_THROTTLE_MS = 1000


class PollWorker(QThread):
    """
    Background thread that polls DB every `interval_ms` milliseconds.

    Warning events use POPUP_THRESHOLD (0.95) not RISK_HIGH (0.70):
      - RISK_HIGH (0.70): process appears in table and confirmation queue
      - POPUP_THRESHOLD (0.95): triggers popup alert
    Known system processes never trigger popups.
    """

    features_ready = pyqtSignal(list)  # list[ProcessFeatures]
    snapshot_ready = pyqtSignal(object)  # SystemSnapshot
    warning_ready = pyqtSignal(object)  # WarningEvent
    status_changed = pyqtSignal(str, str)  # (message, level)
    row_count_ready = pyqtSignal(int)

    def __init__(
        self,
        db_reader: DBReader,
        engine: FeatureEngine,
        whitelist: Whitelist,
        interval_ms: int = 1000,
        parent=None,
    ):
        super().__init__(parent)
        self.db_reader = db_reader
        self.engine = engine
        self.whitelist = whitelist
        self.interval_ms = interval_ms
        self._running = True
        self._mutex = QMutex()
        self._popups_enabled = True

        self._warned_keys: dict[tuple[int, str, str], float] = {}
        self._last_ui_emit = 0.0

    def run(self):
        while self._running:
            try:
                self._poll()
            except Exception as e:
                self.status_changed.emit(f"Poll error: {e}", "error")
            self.msleep(self.interval_ms)

    def stop(self):
        with QMutexLocker(self._mutex):
            self._running = False

    def set_interval(self, ms: int):
        with QMutexLocker(self._mutex):
            self.interval_ms = ms

    def set_popups_enabled(self, enabled: bool):
        with QMutexLocker(self._mutex):
            self._popups_enabled = enabled

    def _poll(self):
        if not self.db_reader.exists:
            self.status_changed.emit(f"Database not found: {self.db_reader.db_path}", "error")
            return

        df = self.db_reader.read_recent(limit=5000)
        if df.empty:
            self.status_changed.emit("Database empty - logger may not be running", "warn")
            return

        self.row_count_ready.emit(self.db_reader.row_count())

        features: List[ProcessFeatures] = self.engine.compute(df)
        features = [f for f in features if not self.whitelist.is_trusted(f.process_name)]
        self.features_ready.emit(features)

        now_ms = time.time() * 1000
        if now_ms - self._last_ui_emit >= UI_THROTTLE_MS:
            snapshot = self.engine.compute_system_snapshot(df)
            if snapshot:
                self.snapshot_ready.emit(snapshot)
            self._last_ui_emit = now_ms

        if self._popups_enabled:
            new_threats = self._detect_popup_threats(features)
            if new_threats:
                from datetime import datetime

                event = WarningEvent(
                    timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    processes=new_threats,
                )
                self.warning_ready.emit(event)

        model_tag = "ML active" if self._model_active() else "Heuristic"
        popup_tag = f"popups {'ON' if self._popups_enabled else 'OFF'}"
        self.status_changed.emit(
            f"Updated: {self._now()} - {len(features)} processes - {model_tag} - {popup_tag}",
            "info",
        )

    def _detect_popup_threats(self, features: List[ProcessFeatures]) -> List[ProcessFeatures]:
        new_threats = []
        for f in features:
            if f.risk_score < POPUP_THRESHOLD:
                continue
            if f.process_name.lower() in SYSTEM_PROCESSES:
                continue
            key = (f.pid, f.process_name.lower(), f.exe_path.lower())
            prev = self._warned_keys.get(key, 0.0)
            if prev < POPUP_THRESHOLD or (f.risk_score - prev) > 0.10:
                new_threats.append(f)
                self._warned_keys[key] = f.risk_score
        return new_threats

    @staticmethod
    def _model_active() -> bool:
        from core.engine import _MODEL

        return _MODEL is not None

    @staticmethod
    def _now() -> str:
        from datetime import datetime

        return datetime.now().strftime("%H:%M:%S")
