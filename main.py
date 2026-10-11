import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from app.config import APP_NAME, DATA_DIR

from app import diagnostics

diagnostics.install(DATA_DIR)

from app.updater import activateDownloadedEngine

activateDownloadedEngine()

from app.session_link import parseCode
from app.single_instance import InstanceServer, sendToRunning, waitForPreviousInstance
from app.ui import theme
from app.ui.main_window import MainWindow


def main():
    sys.setswitchinterval(0.002)
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x00008000)
        except Exception:
            pass
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("KenHD.Sonus")
        except Exception:
            pass
    os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")
    application = QApplication(sys.argv)
    application.setApplicationName(APP_NAME)
    application.setOrganizationName("KenHD")
    application.setStyle("Fusion")
    application.setStyleSheet(theme.STYLESHEET)
    application.setFont(QFont("Segoe UI", 10))
    linkArgument = next((argument for argument in sys.argv[1:] if parseCode(argument)), None)
    if "--restarted" in sys.argv:
        waitForPreviousInstance()
    elif sendToRunning(linkArgument or "show"):
        sys.exit(0)
    instanceServer = InstanceServer(parent=application)
    instanceServer.listen()
    window = MainWindow()
    window.show()
    instanceServer.messageReceived.connect(lambda message: window.handleExternalMessage(message))
    if linkArgument:
        QTimer.singleShot(1200, lambda: window.handleCode(linkArgument))
    sys.exit(application.exec())


if __name__ == "__main__":
    main()
