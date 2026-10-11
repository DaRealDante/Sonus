import http.server
import os
import re
import subprocess
import tempfile
import threading
import time

import pytest

from app.config import ffmpegExe
from app.room_files import RoomFileCache, decryptFile, encryptFile, fileSha, uploadTemporary
from tests.broker import localBroker, pump, waitFor  # noqa: F401
from tests.test_together import FakeOutputStream, fakeSoundCard, makeMember, shutdown, toneUrl  # noqa: F401


class FakeLitterbox(http.server.BaseHTTPRequestHandler):
    files = {}
    uploads = 0

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        boundary = re.search(r"boundary=(.+)", self.headers["Content-Type"]).group(1).encode()
        part = [chunk for chunk in body.split(b"--" + boundary) if b'name="fileToUpload"' in chunk][0]
        data = part.split(b"\r\n\r\n", 1)[1][:-2]
        assert b'name="time"\r\n\r\n1h' in body
        name = f"f{len(self.files)}.bin"
        FakeLitterbox.files[name] = data
        FakeLitterbox.uploads += 1
        reply = f"http://127.0.0.1:{self.server.server_address[1]}/{name}".encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    def do_GET(self):
        data = self.files.get(self.path.strip("/"))
        if data is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture(scope="module")
def litterbox():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeLitterbox)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    os.environ["SONUS_UPLOAD_URL"] = f"http://127.0.0.1:{server.server_address[1]}/api"
    yield server
    server.shutdown()


def test_encryptDecryptRoundTrip(tmp_path):
    original = tmp_path / "mia.mp3"
    original.write_bytes(os.urandom(3 * 1024 * 1024 + 123))
    blob = tmp_path / "blob"
    key, sha = encryptFile(str(original), str(blob))
    assert sha == fileSha(str(original))
    assert original.read_bytes()[:1000] not in blob.read_bytes()
    out = tmp_path / "out.mp3"
    decryptFile(str(blob), key, str(out), sha)
    assert out.read_bytes() == original.read_bytes()
    corrupted = bytearray(blob.read_bytes())
    corrupted[-5] ^= 1
    blob.write_bytes(bytes(corrupted))
    with pytest.raises(ValueError):
        decryptFile(str(blob), key, str(tmp_path / "x.mp3"), sha)


def test_cleanupRemovesFilesIdleForAnHour(tmp_path):
    cache = RoomFileCache(str(tmp_path / "cache"))
    old = cache.pathFor("a" * 40, ".mp3")
    playing = cache.pathFor("b" * 40, ".mp3")
    fresh = cache.pathFor("c" * 40, ".mp3")
    for path in (old, playing, fresh):
        open(path, "wb").write(b"x")
    past = time.time() - 4000
    os.utime(old, (past, past))
    os.utime(playing, (past, past))
    assert cache.cleanup(keep=[playing]) == 1
    assert not os.path.exists(old) and os.path.exists(playing) and os.path.exists(fresh)


def test_uploadToFakeLitterbox(litterbox, tmp_path):
    path = tmp_path / "x.bin"
    path.write_bytes(b"ciao")
    link = uploadTemporary(str(path))
    assert link.startswith("http://127.0.0.1")


def test_friendHearsMyPersonalMp3(localBroker, litterbox, toneUrl, fakeSoundCard, tmp_path):
    alice, bruno = makeMember("Alice", toneUrl), makeMember("Bruno", toneUrl)
    mp3 = tmp_path / "Ken - Demo Personale.mp3"
    subprocess.run([ffmpegExe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=700:duration=40", str(mp3)], check=True)
    songId = alice.database.addSong(str(mp3), "Demo Personale", "Ken", "", 40)
    alice.player.playSongs([alice.database.getSong(songId)], 0)
    code = alice.controller.createRoom()
    bruno.controller.joinRoom(code)
    assert waitFor(lambda: bruno.player.currentSong() is not None, 10)
    assert bruno.player.currentSong()["path"].startswith("stream:roomfile:")
    assert waitFor(lambda: bruno.player.isPlaying() and bruno.player.mediaPlayer.source().isLocalFile(), 25)
    received = bruno.player.mediaPlayer.source().toLocalFile()
    assert fileSha(received) == fileSha(str(mp3))
    assert waitFor(lambda: abs(alice.player.position() - bruno.player.position()) < 700, 8)
    assert FakeLitterbox.uploads >= 1
    assert bruno.database.allSongs() == []
    shutdown(alice, bruno)


def test_hostileFileMessagesRejected(tmp_path):
    from app.room_files import validRoomFile
    good = {"sha": "a" * 64, "url": "https://litter.catbox.moe/x.bin", "key": "k"}
    assert validRoomFile(good)
    assert not validRoomFile(dict(good, sha="../../evil"))
    assert not validRoomFile(dict(good, url="file:///C:/Windows/win.ini"))
    assert not validRoomFile(dict(good, url="http://192.168.1.1/x"))
    with pytest.raises(ValueError):
        RoomFileCache(str(tmp_path)).fetch(dict(good, sha="../../evil"))


def test_failedUploadFallsBackQuickly(localBroker, toneUrl, fakeSoundCard, tmp_path, monkeypatch):
    monkeypatch.setenv("SONUS_UPLOAD_URL", "http://127.0.0.1:9/nothing")
    alice, bruno = makeMember("Alice", toneUrl), makeMember("Bruno", toneUrl)
    mp3 = tmp_path / "Ken - Fallita.mp3"
    subprocess.run([ffmpegExe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=30", str(mp3)], check=True)
    songId = alice.database.addSong(str(mp3), "Fallita", "Ken", "", 30)
    alice.player.playSongs([alice.database.getSong(songId)], 0)
    code = alice.controller.createRoom()
    from app import downloader
    monkeypatch.setattr(downloader, "resolveStream", lambda target, useCache=True: {"url": toneUrl, "headers": {}, "duration": 90})
    started = time.time()
    bruno.controller.joinRoom(code)
    assert waitFor(lambda: bruno.player.isPlaying(), 20)
    assert time.time() - started < 15
    assert bruno.player.mediaPlayer.source().toString() == toneUrl
    assert sum("Non riesco a mandare" in notice for notice in alice.notices) == 1
    shutdown(alice, bruno)


def test_friendHearsMyModifiedSongNotTheOriginal(localBroker, litterbox, toneUrl, fakeSoundCard, tmp_path, monkeypatch):
    monkeypatch.setenv("SONUS_UPLOAD_URL", f"http://127.0.0.1:{litterbox.server_address[1]}/api")
    alice, bruno = makeMember("Alice", toneUrl), makeMember("Bruno", toneUrl)
    mp3 = tmp_path / "Ken - Brano (slowed + reverb).mp3"
    subprocess.run([ffmpegExe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=40", str(mp3)], check=True)
    songId = alice.database.addSong(str(mp3), "Brano (slowed + reverb)", "Ken", "", 40, None, "cut",
                                    "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    alice.player.playSongs([alice.database.getSong(songId)], 0)
    code = alice.controller.createRoom()
    bruno.controller.joinRoom(code)
    assert waitFor(lambda: bruno.player.currentSong() is not None, 10)
    assert bruno.player.currentSong()["path"].startswith("stream:roomfile:")
    assert waitFor(lambda: bruno.player.mediaPlayer.source().isLocalFile(), 25)
    assert fileSha(bruno.player.mediaPlayer.source().toLocalFile()) == fileSha(str(mp3))
    shutdown(alice, bruno)
