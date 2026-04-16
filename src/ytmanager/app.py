from __future__ import annotations

import os
import sys


def main() -> int:
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        from ytmanager.ui.main_window import MainWindow
    except ImportError as exc:
        print("PySide6가 설치되어 있지 않습니다. `python -m pip install -e .` 후 다시 실행하세요.", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1

    app = QApplication(sys.argv)
    app.setApplicationName("YTmanager")
    app.setOrganizationName("YTmanager")
    try:
        window = MainWindow()
        window.show()
        return app.exec()
    except Exception as exc:  # GUI 진입 전 치명 오류를 한국어로 표시한다.
        QMessageBox.critical(None, "YTmanager 오류", f"앱을 시작할 수 없습니다.\n\n{exc}")
        return 1
