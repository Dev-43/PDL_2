"""
BehaviorShield - Entry Point
==============================
Usage:
    python main.py                                      # auto-detect DB path
    python main.py --db "C:/ProgramData/SysLogger/logs.db"
    python main.py --db /opt/syslogger/logs.db
    python main.py --poll 2                             # override poll interval (seconds)
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(__file__))

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

from core.engine import get_default_db_path
from ui.main_window import MainWindow


def main():
    parser = argparse.ArgumentParser(description="BehaviorShield - Malware Detection Frontend")
    parser.add_argument("--db",   default=None,  help="Path to logs.db SQLite file")
    parser.add_argument("--poll", default=1, type=int,
                        help="DB polling interval in seconds (default: 1)")
    args = parser.parse_args()
    if args.poll <= 0:
        parser.error("--poll must be a positive integer (seconds)")

    db_path = args.db or get_default_db_path()

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("BehaviorShield")
    app.setOrganizationName("BehaviorShield")
    app.setQuitOnLastWindowClosed(False)

    window = MainWindow(db_path=db_path)

    if args.poll != 1:
        window.worker.set_interval(args.poll * 1000)

    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

