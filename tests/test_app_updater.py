from app import app_updater


def test_canWriteTellsProtectedFolders(tmp_path):
    assert app_updater.canWrite(str(tmp_path))
    assert not app_updater.canWrite(str(tmp_path / "non_esiste"))


def test_launchInstallerRunsDirectlyWhenFolderIsWritable(tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(app_updater, "installFolder", lambda: str(tmp_path))
    monkeypatch.setattr(app_updater.subprocess, "Popen", lambda command, **kwargs: started.append(command))
    assert app_updater.launchInstaller("setup.exe") is None
    assert started == [["setup.exe", "/SILENT", "/NOCANCEL"]]
