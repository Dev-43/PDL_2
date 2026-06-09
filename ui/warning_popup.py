"""
BehaviorShield - Warning Popup
================================
Non-blocking popup that appears when one or more processes
cross the HIGH RISK threshold. Shows all flagged processes
in a single dialog. Writes to history automatically.
"""

from __future__ import annotations
from typing import Callable

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QIcon
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QFrame, QPushButton, QScrollArea, QWidget,
    QApplication,
)

from core.engine import WarningEvent, ProcessFeatures, RISK_HIGH
from ui.theme import (
    BG_BASE, BG_PANEL, BORDER, DANGER, DANGER_BG,
    WARN, WARN_BG, SAFE, SAFE_BG,
    TEXT, TEXT_DIM, FONT_DATA, FONT_UI, ACCENT,
)


class WarningPopup(QDialog):
    """
    Non-blocking threat alert dialog.

    on_response(features, response) callback fires for each
    process the user acts on. 'response' is one of:
        "confirmed" | "false_positive" | "unresolved"
    """

    # Signal emitted for each process response
    process_responded = pyqtSignal(object, str)   # (ProcessFeatures, response)
    all_dismissed     = pyqtSignal()

    def __init__(self, event: WarningEvent, parent=None):
        super().__init__(parent)
        self.event      = event
        self._responses: dict[int, str] = {}  # pid -> response
        self._dismiss_emitted = False
        self._build()
        self._play_alert()

    def _build(self):
        self.setWindowTitle("!  BehaviorShield - Threat Detected")
        self.setMinimumWidth(620)
        self.setMaximumWidth(800)
        self.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint)
        self.setModal(False)   # Non-blocking
        self.setStyleSheet(f"""
            QDialog {{
                background: {BG_BASE};
                color: {TEXT};
            }}
            QLabel {{ font-family: {FONT_UI}; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # â”€â”€ Red header bar â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        header = QFrame()
        header.setStyleSheet(f"background: {DANGER_BG}; border-bottom: 2px solid {DANGER};")
        header.setFixedHeight(72)
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(20, 0, 20, 0)

        icon_lbl = QLabel("!")
        icon_lbl.setStyleSheet(f"color:{DANGER}; font-size:28pt; border:none;")
        h_lay.addWidget(icon_lbl)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        title_lbl = QLabel("THREAT DETECTED")
        title_lbl.setStyleSheet(f"color:{DANGER}; font-family:{FONT_UI}; font-size:14pt; font-weight:bold; letter-spacing:3px; border:none;")
        text_col.addWidget(title_lbl)

        count = len(self.event.processes)
        sub = QLabel(
            f"{count} process{'es' if count > 1 else ''} flagged  |  {self.event.timestamp}"
        )
        sub.setStyleSheet(f"color:{TEXT_DIM}; font-family:{FONT_DATA}; font-size:9pt; border:none;")
        text_col.addWidget(sub)
        h_lay.addLayout(text_col)
        h_lay.addStretch()
        root.addWidget(header)

        # â”€â”€ Process list â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"background:{BG_BASE}; border:none;")
        scroll.setMaximumHeight(400)

        container = QWidget()
        container.setStyleSheet(f"background:{BG_BASE};")
        cont_lay = QVBoxLayout(container)
        cont_lay.setContentsMargins(16, 12, 16, 12)
        cont_lay.setSpacing(10)

        for f in self.event.processes:
            cont_lay.addWidget(self._make_process_card(f))

        scroll.setWidget(container)
        root.addWidget(scroll)

        # â”€â”€ Footer buttons â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        footer = QFrame()
        footer.setStyleSheet(f"background:{BG_PANEL}; border-top:1px solid {BORDER};")
        f_lay = QHBoxLayout(footer)
        f_lay.setContentsMargins(16, 10, 16, 10)

        note = QLabel("v1 - Detection only. Quarantine/removal available in v2.")
        note.setStyleSheet(f"color:{TEXT_DIM}; font-family:{FONT_UI}; font-size:8pt; border:none;")
        f_lay.addWidget(note)
        f_lay.addStretch()

        view_btn = QPushButton("View in Dashboard")
        view_btn.setStyleSheet(self._btn_style(ACCENT, BG_BASE))
        view_btn.clicked.connect(self._go_to_dashboard)
        f_lay.addWidget(view_btn)

        dismiss_btn = QPushButton("Dismiss")
        dismiss_btn.setStyleSheet(self._btn_style(TEXT_DIM, BG_BASE))
        dismiss_btn.clicked.connect(self._dismiss_all)
        f_lay.addWidget(dismiss_btn)

        root.addWidget(footer)

    def _make_process_card(self, f: ProcessFeatures) -> QFrame:
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background:{BG_PANEL};
                border:1px solid {DANGER};
                border-radius:5px;
            }}
        """)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)

        # Top row: name + score
        top = QHBoxLayout()
        name = QLabel(f.process_name)
        name.setStyleSheet(f"color:{DANGER}; font-family:{FONT_DATA}; font-size:12pt; font-weight:bold; border:none;")
        top.addWidget(name)
        top.addStretch()
        score_lbl = QLabel(f"Risk: {f.risk_score:.2f}")
        score_lbl.setStyleSheet(f"color:{DANGER}; font-family:{FONT_DATA}; font-size:10pt; font-weight:bold; border:none;")
        top.addWidget(score_lbl)
        lay.addLayout(top)

        # Details grid
        details = QGridLayout()
        details.setSpacing(4)
        details.setColumnMinimumWidth(0, 90)

        fields = [
            ("PID",     str(f.pid)),
            ("Verdict", f.verdict),
            ("Window",  f.window_start),
        ]
        if f.parent_pid is not None:
            fields.append(("Parent PID", str(f.parent_pid)))
        if f.is_elevated:
            fields.append(("Elevated", "YES !"))

        for row_i, (lbl, val) in enumerate(fields):
            k = QLabel(lbl + ":")
            k.setStyleSheet(f"color:{TEXT_DIM}; font-family:{FONT_UI}; font-size:8pt; border:none;")
            v = QLabel(val)
            v.setStyleSheet(f"color:{TEXT}; font-family:{FONT_DATA}; font-size:8pt; border:none;")
            if lbl == "Elevated":
                v.setStyleSheet(f"color:{DANGER}; font-family:{FONT_DATA}; font-size:8pt; border:none;")
            details.addWidget(k, row_i, 0)
            details.addWidget(v, row_i, 1)

        lay.addLayout(details)

        # Executable Path - shown if logger has exe_path column
        if f.exe_path:
            path_frame = QFrame()
            path_frame.setStyleSheet(
                f"background:{BG_BASE}; border:1px solid {BORDER}; border-radius:3px;"
            )
            p_lay = QVBoxLayout(path_frame)
            p_lay.setContentsMargins(8, 6, 8, 6)
            p_lay.setSpacing(2)

            path_lbl_title = QLabel("File Path:")
            path_lbl_title.setStyleSheet(
                f"color:{TEXT_DIM}; font-family:{FONT_UI}; font-size:8pt; border:none;"
            )
            p_lay.addWidget(path_lbl_title)

            path_lbl_val = QLabel(f.exe_path)
            path_lbl_val.setWordWrap(True)
            path_lbl_val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            path_lbl_val.setStyleSheet(
                f"color:{ACCENT}; font-family:{FONT_DATA}; font-size:8pt; border:none;"
            )
            p_lay.addWidget(path_lbl_val)

            lay.addWidget(path_frame)

        # Cause
        if f.top_signal:
            cause_frame = QFrame()
            cause_frame.setStyleSheet(f"background:{DANGER_BG}; border:1px solid {DANGER}; border-radius:3px;")
            c_lay = QHBoxLayout(cause_frame)
            c_lay.setContentsMargins(8, 5, 8, 5)
            cause_lbl = QLabel(f"Cause: {f.top_signal}")
            cause_lbl.setWordWrap(True)
            cause_lbl.setStyleSheet(f"color:{DANGER}; font-family:{FONT_UI}; font-size:8pt; border:none;")
            c_lay.addWidget(cause_lbl)
            lay.addWidget(cause_frame)

        # Response buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        responses = [
            ("Confirm Malware",  "confirmed",      DANGER,  DANGER_BG),
            ("False Positive",   "false_positive", SAFE,    SAFE_BG),
            ("? Not Sure",           "unresolved",     WARN,    WARN_BG),
        ]

        self._btn_states: dict[int, list[QPushButton]] = {}
        btns = []
        for label, resp, fg, bg in responses:
            btn = QPushButton(label)
            btn.setFixedHeight(28)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background:{bg}; color:{fg};
                    border:1px solid {fg}; border-radius:3px;
                    padding:2px 10px; font-size:8pt;
                    font-family:{FONT_UI};
                }}
                QPushButton:hover {{ background:{fg}; color:{BG_BASE}; font-weight:bold; }}
                QPushButton:disabled {{ opacity:0.4; }}
            """)
            btn.clicked.connect(
                lambda checked, _f=f, _r=resp, _btns=btns: self._respond(_f, _r, _btns)
            )
            btns.append(btn)
            btn_row.addWidget(btn)

        lay.addLayout(btn_row)
        return card

    def _respond(self, f: ProcessFeatures, response: str, all_btns: list):
        """Disable all buttons for this card, emit signal."""
        for btn in all_btns:
            btn.setEnabled(False)
        self._responses[f.pid] = response
        self.process_responded.emit(f, response)
        self._check_all_done()

    def _check_all_done(self):
        if len(self._responses) == len(self.event.processes):
            self._emit_dismissed_once()
            QTimer.singleShot(800, self.close)

    def _dismiss_all(self):
        """Mark all unresponded processes as unresolved."""
        for f in self.event.processes:
            if f.pid not in self._responses:
                self._responses[f.pid] = "unresolved"
                self.process_responded.emit(f, "unresolved")
        self._emit_dismissed_once()
        self.close()

    def _go_to_dashboard(self):
        self._emit_dismissed_once()
        self.close()

    def closeEvent(self, event):
        # Treat window-close as dismiss-all so alerts are not silently dropped.
        for f in self.event.processes:
            if f.pid not in self._responses:
                self._responses[f.pid] = "unresolved"
                self.process_responded.emit(f, "unresolved")
        self._emit_dismissed_once()
        super().closeEvent(event)

    def _play_alert(self):
        """Cross-platform alert sound."""
        try:
            import platform
            if platform.system() == "Windows":
                import winsound
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            else:
                QApplication.beep()
        except:
            QApplication.beep()

    @staticmethod
    def _btn_style(fg: str, bg: str) -> str:
        return f"""
            QPushButton {{
                background:{bg}; color:{fg};
                border:1px solid {fg}; border-radius:4px;
                padding:5px 14px; font-family:{FONT_UI}; font-size:9pt;
            }}
            QPushButton:hover {{ background:{fg}; color:{BG_BASE}; }}
        """

    def _emit_dismissed_once(self):
        if not self._dismiss_emitted:
            self._dismiss_emitted = True
            self.all_dismissed.emit()


