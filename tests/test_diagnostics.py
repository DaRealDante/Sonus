import io

from app import diagnostics


def test_teeWritesTimestampedLinesToFileAndMemory(tmp_path):
    logFile = open(tmp_path / "log.txt", "a", encoding="utf-8")
    original = io.StringIO()
    tee = diagnostics._Tee(original, logFile)
    tee.write("[Link] connesso a server:8883\nmezza ")
    tee.write("riga\n")
    tee.flush()
    content = (tmp_path / "log.txt").read_text(encoding="utf-8")
    assert "[Link] connesso a server:8883" in content and "mezza riga" in content
    assert original.getvalue() == "[Link] connesso a server:8883\nmezza riga\n"
    assert any("mezza riga" in line for line in diagnostics.recentLines)


def test_teeWorksWithoutConsole(tmp_path):
    tee = diagnostics._Tee(None, None)
    assert tee.write("niente console\n") == len("niente console\n")
    tee.flush()


def test_installKeepsOldLogAndRotates(tmp_path, monkeypatch):
    import sys
    path = tmp_path / "log.txt"
    path.write_text("x" * (diagnostics.MAX_LOG_BYTES + 10), encoding="utf-8")
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    diagnostics.install(str(tmp_path))
    print("dopo avvio")
    sys.stdout.flush()
    assert (tmp_path / "log.txt.old").exists()
    assert "dopo avvio" in path.read_text(encoding="utf-8")
