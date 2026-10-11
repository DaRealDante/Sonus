from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QLinearGradient, QPainter, QPainterPath, QPixmap

from ..config import settings

DEFAULT_COLORS = {"accent": "#1ED760", "background": "#121212", "panel": "#181818", "sidebar": "#000000", "text": "#FFFFFF"}
COLOR_PRESETS = {
    "Verde (originale)": {},
    "Viola": {"accent": "#A970FF"},
    "Blu": {"accent": "#3D91F4"},
    "Rosso": {"accent": "#F23F42"},
    "Arancio": {"accent": "#FF8A1F"},
    "Rosa": {"accent": "#FF4FA0"},
    "Mezzanotte": {"accent": "#5B8CFF", "background": "#0F1424", "panel": "#151B2E", "sidebar": "#0A0E1A"},
    "Bosco": {"accent": "#7BD88F", "background": "#101A14", "panel": "#15211A", "sidebar": "#09110C"},
}


def _mix(first, second, amount):
    first, second = QColor(first), QColor(second)
    return QColor(round(first.red() + (second.red() - first.red()) * amount),
                  round(first.green() + (second.green() - first.green()) * amount),
                  round(first.blue() + (second.blue() - first.blue()) * amount)).name().upper()


def _luminance(color):
    color = QColor(color)
    return 0.2126 * color.redF() + 0.7152 * color.greenF() + 0.0722 * color.blueF()


def resolveColors(custom):
    """Full palette from the (partial) colours chosen by the user: derived shades always stay readable."""
    custom = {key: value for key, value in (custom or {}).items() if key in DEFAULT_COLORS and QColor(str(value)).isValid()}
    if not custom:
        return {"ACCENT": "#1ED760", "ACCENT_HOVER": "#3BE477", "ACCENT_TEXT": "#000000", "BACKGROUND": "#121212",
                "SIDEBAR": "#000000", "PANEL": "#181818", "ELEVATED": "#242424", "HOVER": "#2A2A2A", "TEXT": "#FFFFFF",
                "SUBTEXT": "#B3B3B3", "MUTED": "#6A6A6A"}
    colors = dict(DEFAULT_COLORS, **{key: QColor(str(value)).name().upper() for key, value in custom.items()})
    background = colors["background"]
    text = colors["text"]
    if abs(_luminance(text) - _luminance(background)) < 0.45:
        text = "#FFFFFF" if _luminance(background) < 0.5 else "#000000"
    accent = colors["accent"]
    return {
        "ACCENT": accent, "ACCENT_HOVER": QColor(accent).lighter(115).name().upper(),
        "ACCENT_TEXT": "#000000" if _luminance(accent) > 0.45 else "#FFFFFF",
        "BACKGROUND": background, "SIDEBAR": colors["sidebar"], "PANEL": colors["panel"],
        "ELEVATED": _mix(colors["panel"], text, 0.07), "HOVER": _mix(colors["panel"], text, 0.10),
        "TEXT": text, "SUBTEXT": _mix(text, background, 0.30), "MUTED": _mix(text, background, 0.58),
    }


_palette = resolveColors(settings.get("themeColors") or {})
ACCENT = _palette["ACCENT"]
ACCENT_HOVER = _palette["ACCENT_HOVER"]
ACCENT_TEXT = _palette["ACCENT_TEXT"]
BACKGROUND = _palette["BACKGROUND"]
SIDEBAR = _palette["SIDEBAR"]
PANEL = _palette["PANEL"]
ELEVATED = _palette["ELEVATED"]
HOVER = _palette["HOVER"]
TEXT = _palette["TEXT"]
SUBTEXT = _palette["SUBTEXT"]
MUTED = _palette["MUTED"]

STYLESHEET = f"""
* {{ font-family: "Segoe UI Variable Text", "Segoe UI", "Inter", sans-serif; font-size: 10pt; color: {TEXT}; outline: none; }}
QMainWindow {{ background: {SIDEBAR}; }}
QWidget#page, QStackedWidget#pages {{ background: {BACKGROUND}; border-radius: 10px; }}
QFrame#sidebarBox, QFrame#rightPanel {{ background: {PANEL}; border-radius: 10px; }}
QFrame#playerBar {{ background: {SIDEBAR}; }}
QLabel {{ background: transparent; }}
QLabel#h1 {{ font-size: 26pt; font-weight: 800; }}
QLabel#h2 {{ font-size: 15pt; font-weight: 700; }}
QLabel#h3 {{ font-size: 11pt; font-weight: 700; }}
QLabel#sub {{ color: {SUBTEXT}; }}
QLabel#small {{ color: {SUBTEXT}; font-size: 9pt; }}
QLabel#songTitle {{ font-weight: 600; }}

QPushButton {{ background: {ELEVATED}; border: none; border-radius: 16px; padding: 7px 16px; font-weight: 600; }}
QPushButton:hover {{ background: {HOVER}; }}
QPushButton:pressed {{ background: #1A1A1A; }}
QPushButton:disabled {{ color: {MUTED}; }}
QPushButton#accent {{ background: {ACCENT}; color: {ACCENT_TEXT}; }}
QPushButton#accent:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#outline {{ background: transparent; border: 1px solid {MUTED}; }}
QPushButton#outline:hover {{ border-color: {TEXT}; }}
QPushButton#nav {{ background: transparent; text-align: left; padding: 9px 12px; border-radius: 6px; color: {SUBTEXT}; font-weight: 700; font-size: 10.5pt; }}
QPushButton#nav:hover {{ color: {TEXT}; }}
QPushButton#nav:checked {{ color: {TEXT}; background: {ELEVATED}; }}
QToolButton {{ background: transparent; border: none; border-radius: 16px; padding: 4px; }}
QToolButton:hover {{ background: {HOVER}; }}
QToolButton::menu-indicator {{ image: none; }}
QToolButton#playButton {{ background: {TEXT}; border-radius: 18px; }}
QToolButton#playButton:hover {{ background: #E8E8E8; }}
QToolButton#bigPlay {{ background: {ACCENT}; border-radius: 28px; }}
QToolButton#bigPlay:hover {{ background: {ACCENT_HOVER}; }}

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {ELEVATED}; border: 1px solid transparent; border-radius: 6px; padding: 6px 10px; selection-background-color: {ACCENT}; selection-color: {ACCENT_TEXT};
}}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border: 1px solid {MUTED}; }}
QLineEdit#searchBox {{ border-radius: 20px; padding: 9px 16px; font-size: 10.5pt; background: {ELEVATED}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {ELEVATED}; border: 1px solid {HOVER}; selection-background-color: {HOVER}; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}

QTableView, QListWidget, QTreeWidget {{ background: transparent; border: none; alternate-background-color: transparent; selection-background-color: {HOVER}; selection-color: {TEXT}; }}
QTableView::item {{ padding: 4px 8px; border: none; }}
QTableView::item:hover, QListWidget::item:hover {{ background: #1F1F1F; }}
QTableView::item:selected, QListWidget::item:selected {{ background: {HOVER}; }}
QListWidget::item {{ border-radius: 6px; padding: 4px; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: transparent; color: {SUBTEXT}; border: none; border-bottom: 1px solid #2A2A2A; padding: 6px 8px; font-weight: 600; }}
QTableCornerButton::section {{ background: transparent; border: none; }}

QScrollBar:vertical {{ background: transparent; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: rgba(255,255,255,0.18); min-height: 30px; border-radius: 4px; margin: 2px 3px; }}
QScrollBar::handle:vertical:hover {{ background: rgba(255,255,255,0.32); }}
QScrollBar:horizontal {{ background: transparent; height: 12px; }}
QScrollBar::handle:horizontal {{ background: rgba(255,255,255,0.18); min-width: 30px; border-radius: 4px; margin: 3px 2px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: none; width: 0; height: 0; }}

QSlider::groove:horizontal {{ height: 4px; background: #4D4D4D; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {TEXT}; border-radius: 2px; margin: 6px 0; }}
QSlider::add-page:horizontal {{ background: #4D4D4D; border-radius: 2px; margin: 6px 0; }}
QSlider:hover::sub-page:horizontal {{ background: {ACCENT}; }}
QSlider::handle:horizontal {{ background: transparent; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px; }}
QSlider:hover::handle:horizontal {{ background: {TEXT}; }}

QMenu {{ background: {ELEVATED}; border: 1px solid #333; border-radius: 6px; padding: 4px; }}
QMenu::item {{ padding: 7px 26px 7px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: #3A3A3A; }}
QMenu::item:disabled {{ color: {MUTED}; }}
QMenu::separator {{ height: 1px; background: #3A3A3A; margin: 4px 6px; }}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: {ELEVATED}; color: {TEXT}; padding: 6px 16px; margin-right: 8px; border-radius: 15px; font-weight: 600; }}
QTabBar::tab:selected {{ background: {TEXT}; color: #000; }}
QTabBar::tab:hover:!selected {{ background: {HOVER}; }}

QProgressBar {{ background: #3A3A3A; border: none; border-radius: 3px; height: 6px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 14px; height: 14px; border: 1px solid #8A8A8A; background: transparent; }}
QCheckBox::indicator {{ border-radius: 3px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QCheckBox::indicator:disabled {{ border-color: #444; }}
QToolTip {{ background: {ELEVATED}; color: {TEXT}; border: 1px solid #3A3A3A; padding: 4px 8px; border-radius: 4px; }}
QDialog {{ background: {PANEL}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QSplitter::handle {{ background: {SIDEBAR}; }}
QStatusBar {{ background: {SIDEBAR}; color: {SUBTEXT}; }}
"""

AMBIENT_STYLESHEET = """
QWidget#page, QStackedWidget#pages { background: rgba(18, 18, 18, 165); }
QFrame#sidebarBox, QFrame#rightPanel { background: rgba(20, 20, 20, 170); }
QFrame#playerBar { background: rgba(0, 0, 0, 150); }
QSplitter::handle { background: transparent; }
"""

ICON_CODES = {
    "play": ("", "▶"), "pause": ("", "⏸"), "prev": ("", "⏮"), "next": ("", "⏭"),
    "shuffle": ("", "⤮"), "repeat": ("", "↻"), "repeatOne": ("", "↺"),
    "volume": ("", "🔊"), "volumeLow": ("", "🔉"), "mute": ("", "🔇"),
    "heart": ("", "♡"), "heartFill": ("", "♥"), "search": ("", "⌕"),
    "home": ("", "⌂"), "library": ("", "▤"), "add": ("", "+"), "delete": ("", "🗑"),
    "edit": ("", "✎"), "download": ("", "⭳"), "music": ("", "♪"), "cut": ("", "✂"),
    "loop": ("", "⟲"), "settings": ("", "⚙"), "queue": ("", "☰"), "folder": ("", "📁"),
    "globe": ("", "🌐"), "more": ("", "⋯"), "clock": ("", "🕒"), "picture": ("", "🖼"),
    "close": ("", "✕"), "check": ("", "✓"), "panel": ("", "▣"), "speed": ("", "⏩"),
    "timer": ("", "⏲"), "file": ("", "📄"), "refresh": ("", "⟳"), "back": ("", "←"),
    "link": ("", "🔗"), "mic": ("", "🎤"), "flagA": ("", "A"), "info": ("", "ⓘ"), "eq": ("\uE9E9", "≋"),
    "cloud": ("\uE753", "☁"), "people": ("\uE716", "👥"), "person": ("\uE77B", "👤"), "share": ("\uE72D", "⇪"), "star": ("\uE734", "★"),
}

_iconCache = {}
_hasSymbolFont = None


def hasSymbolFont():
    global _hasSymbolFont
    if _hasSymbolFont is None:
        families = set(QFontDatabase.families())
        _hasSymbolFont = "Segoe Fluent Icons" if "Segoe Fluent Icons" in families else (
            "Segoe MDL2 Assets" if "Segoe MDL2 Assets" in families else "")
    return _hasSymbolFont


def icon(name, color=TEXT, size=20):
    cacheKey = (name, color, size)
    if cacheKey in _iconCache:
        return _iconCache[cacheKey]
    glyph, fallback = ICON_CODES.get(name, ("", "?"))
    symbolFamily = hasSymbolFont()
    scale = 2
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)
    painter.setPen(QColor(color))
    if symbolFamily:
        font = QFont(symbolFamily)
        font.setPixelSize(int(size * scale * 0.8))
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignCenter, glyph)
    else:
        font = QFont("Segoe UI Symbol")
        font.setPixelSize(int(size * scale * 0.75))
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignCenter, fallback)
    painter.end()
    pixmap.setDevicePixelRatio(scale)
    result = QIcon(pixmap)
    _iconCache[cacheKey] = result
    return result


_pixmapCache = {}

_PLACEHOLDER_COLORS = [
    ("#450AF5", "#8E8EE5"), ("#1E3264", "#4F7BD6"), ("#8C1932", "#E8115B"), ("#056952", "#27856A"),
    ("#BA5D07", "#F59B23"), ("#503750", "#AF2896"), ("#283C46", "#477D95"), ("#7D4B32", "#D84000"),
]


def placeholderCover(size, seed=0, glyph="music"):
    cacheKey = ("placeholder", size, seed % len(_PLACEHOLDER_COLORS), glyph)
    if cacheKey in _pixmapCache:
        return _pixmapCache[cacheKey]
    colorStart, colorEnd = _PLACEHOLDER_COLORS[seed % len(_PLACEHOLDER_COLORS)]
    pixmap = QPixmap(size, size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    gradient = QLinearGradient(QPointF(0, 0), QPointF(size, size))
    gradient.setColorAt(0, QColor(colorStart))
    gradient.setColorAt(1, QColor(colorEnd))
    painter.fillRect(pixmap.rect(), gradient)
    iconSize = max(12, int(size * 0.42))
    iconPixmap = icon(glyph, "#FFFFFF", iconSize).pixmap(iconSize, iconSize)
    painter.setOpacity(0.85)
    painter.drawPixmap((size - iconSize) // 2, (size - iconSize) // 2, iconPixmap)
    painter.end()
    _pixmapCache[cacheKey] = pixmap
    return pixmap


def roundedPixmap(pixmap, radius):
    if radius <= 0:
        return pixmap
    result = QPixmap(pixmap.size())
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, pixmap.width(), pixmap.height()), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return result


def coverPixmap(path, size, seed=0, radius=4, glyph="music"):
    cacheKey = (path, size, radius, seed if not path else 0, glyph)
    if cacheKey in _pixmapCache:
        return _pixmapCache[cacheKey]
    pixmap = QPixmap(path) if path else QPixmap()
    if pixmap.isNull():
        pixmap = placeholderCover(size, seed, glyph)
    else:
        pixmap = pixmap.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        if pixmap.width() != size or pixmap.height() != size:
            pixmap = pixmap.copy((pixmap.width() - size) // 2, (pixmap.height() - size) // 2, size, size)
    pixmap = roundedPixmap(pixmap, radius)
    _pixmapCache[cacheKey] = pixmap
    return pixmap


def mosaicPixmap(paths, size, seed=0, radius=4):
    paths = [path for path in paths if path][:4]
    if len(paths) < 4:
        return coverPixmap(paths[0] if paths else None, size, seed, radius, "queue" if not paths else "music")
    cacheKey = ("mosaic", tuple(paths), size, radius)
    if cacheKey in _pixmapCache:
        return _pixmapCache[cacheKey]
    half = size // 2
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(ELEVATED))
    painter = QPainter(pixmap)
    for index, path in enumerate(paths):
        tile = coverPixmap(path, half, radius=0)
        painter.drawPixmap((index % 2) * half, (index // 2) * half, tile)
    painter.end()
    pixmap = roundedPixmap(pixmap, radius)
    _pixmapCache[cacheKey] = pixmap
    return pixmap


def clearCoverCache(path=None):
    if path is None:
        _pixmapCache.clear()
        return
    for key in [key for key in _pixmapCache if path in key or (key and key[0] == "mosaic" and path in key[1])]:
        _pixmapCache.pop(key, None)


def formatTime(milliseconds):
    totalSeconds = max(0, int(milliseconds // 1000))
    hours, remainder = divmod(totalSeconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def formatTimePrecise(milliseconds):
    milliseconds = max(0, int(milliseconds))
    minutes, remainder = divmod(milliseconds, 60000)
    return f"{minutes}:{remainder / 1000:06.3f}"


def formatTotal(seconds):
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours} h {minutes} min"
    return f"{minutes} min {seconds % 60} s"


_arrowPath = None


def arrowDownPath():
    global _arrowPath
    if _arrowPath is None:
        import os
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QPolygonF
        from ..config import DATA_DIR
        _arrowPath = os.path.join(DATA_DIR, "arrow_down.png").replace("\\", "/")
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(SUBTEXT))
        painter.drawPolygon(QPolygonF([QPointF(3, 6), QPointF(13, 6), QPointF(8, 11)]))
        painter.end()
        pixmap.save(_arrowPath)
    return _arrowPath
