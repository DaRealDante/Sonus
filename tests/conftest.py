import os
import sys
import tempfile

_dataDir = tempfile.mkdtemp(prefix="synthtest_")
os.environ.setdefault("SONUS_DATA_DIR", _dataDir)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

_application = QApplication.instance() or QApplication([])
