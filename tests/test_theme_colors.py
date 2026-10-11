from app.ui import theme


def test_defaultsAreTheOriginalColors():
    palette = theme.resolveColors({})
    assert palette["ACCENT"] == "#1ED760" and palette["BACKGROUND"] == "#121212" and palette["SUBTEXT"] == "#B3B3B3"


def test_customColorsStayReadable():
    palette = theme.resolveColors({"accent": "#FFFF00", "background": "#101010", "text": "#121212"})
    assert palette["TEXT"] == "#FFFFFF"
    assert palette["ACCENT_TEXT"] == "#000000"
    assert theme.resolveColors({"accent": "#202060"})["ACCENT_TEXT"] == "#FFFFFF"
    assert theme.resolveColors({"accent": "non-un-colore"})["ACCENT"] == "#1ED760"


def test_settingsDialogHasTabsAndSavesColors(monkeypatch):
    from app.config import settings
    from app.ui.dialogs import SettingsDialog
    dialog = SettingsDialog()
    assert [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())] == ["Generale", "Aspetto", "Animazioni"]
    dialog._applyPreset(theme.COLOR_PRESETS["Viola"])
    dialog.effectChecks["fxVisualizer"].setChecked(False)
    dialog._save()
    assert settings.get("themeColors") == {"accent": "#A970FF"}
    assert settings.get("fxVisualizer") is False
    assert dialog.restartForColors
    settings.set("themeColors", {})
    settings.set("fxVisualizer", True)


def test_restartLaunchesNewInstance(monkeypatch):
    from PySide6.QtCore import QProcess
    launched = []
    monkeypatch.setattr(QProcess, "startDetached", staticmethod(lambda program, arguments: launched.append(arguments) or True))
    from app.ui.main_window import MainWindow
    window = MainWindow()
    window.restartApp()
    assert launched and launched[0][-1] == "--restarted"
