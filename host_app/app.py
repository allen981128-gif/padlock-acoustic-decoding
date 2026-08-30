from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from app_window import MainWindow


def _center_window(
    app: QApplication,
    window: MainWindow,
) -> None:
    screen = app.primaryScreen()

    if screen is None:
        return

    available = screen.availableGeometry()
    frame = window.frameGeometry()
    frame.moveCenter(available.center())
    window.move(frame.topLeft())


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Padlock Collector")
    app.setOrganizationName("Graduation Project")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI Variable", 10))

    window = MainWindow()

    # Open as a normal resizable window rather than maximized.
    # The current UI has a minimum size of 1180 x 760.
    window.resize(1240, 800)
    window.show()

    QTimer.singleShot(
        0,
        lambda: _center_window(app, window),
    )
    QTimer.singleShot(
        0,
        window._apply_native_dark_frame,
    )

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
