import functools
import http.server
import os
import subprocess
import tempfile
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication, QUrl
from PySide6.QtMultimedia import QMediaPlayer

from app.config import ffmpegExe


@pytest.fixture(scope="module")
def application():
    return QCoreApplication.instance() or QCoreApplication([])


@pytest.fixture(scope="module")
def httpAudio():
    folder = tempfile.mkdtemp()
    subprocess.run([ffmpegExe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
                    os.path.join(folder, "tone.mp3")], check=True)
    handler = functools.partial(QuietHandler, directory=folder)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/tone.mp3"
    server.shutdown()


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            pass


def waitFor(application, condition, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        application.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    return False


def test_engineDecodesHttpSource(application, httpAudio):
    from app.audio_engine import AudioEngine
    engine = AudioEngine()
    statuses = []
    engine.mediaStatusChanged.connect(statuses.append)
    engine.durationHintMs = 6000
    engine.setSource(QUrl(httpAudio))
    assert engine.duration() == 6000
    assert waitFor(application, lambda: QMediaPlayer.BufferedMedia in statuses)
    assert abs(engine.duration() - 6000) < 150
    engine.shutdown()


def makePlayerWithStreamSong(resolver, songs):
    from app.player import Player
    player = Player()
    player.streamResolver = resolver
    player.restoreSession(songs, 0, 0)
    return player


def test_playerLoadsStreamSongWithStartPosition(application, httpAudio):
    calls = []

    def resolver(target, useCache=True):
        calls.append((target, useCache))
        return {"url": httpAudio, "headers": {"User-Agent": "test"}, "duration": 6}

    song = {"id": 1, "path": "stream:https://www.youtube.com/watch?v=abcdefghijk", "title": "Tono", "duration": 6}
    loadingStates, loaded = [], []
    from app.player import Player
    player = Player()
    player.streamResolver = resolver
    player.loadingChanged.connect(loadingStates.append)
    player.songLoaded.connect(loaded.append)
    player.restoreSession([song], 0, 2500)
    assert player.loading
    assert waitFor(application, lambda: loaded)
    assert loadingStates == [True, False]
    assert calls == [("https://www.youtube.com/watch?v=abcdefghijk", True)]
    assert player.mediaPlayer.source().toString() == httpAudio
    assert player.mediaPlayer.sourceHeaders == {"User-Agent": "test"}
    assert waitFor(application, lambda: player.position() == 2500)
    player.shutdown()


def test_resolverFailureReportsErrorAndSkips(application, httpAudio):
    def resolver(target, useCache=True):
        if "bad" in target:
            raise RuntimeError("video non disponibile")
        return {"url": httpAudio, "headers": {}, "duration": 6}

    songs = [{"id": 1, "path": "stream:https://youtu.be/bad", "title": "Rotta", "duration": 6},
             {"id": 2, "path": "stream:https://youtu.be/ok", "title": "Buona", "duration": 6}]
    from app.player import Player
    player = Player()
    player.streamResolver = resolver
    errors = []
    player.playbackError.connect(errors.append)
    player.playSongs(songs, 0)
    assert waitFor(application, lambda: player.currentIndex == 1 and not player.loading)
    assert errors and "Streaming non disponibile" in errors[0]
    player.shutdown()


def test_togglePlayWhileLoadingDoesNotRestartResolve(application, httpAudio):
    calls = []

    def resolver(target, useCache=True):
        calls.append(target)
        time.sleep(0.3)
        return {"url": httpAudio, "headers": {}, "duration": 6}

    from app.player import Player
    player = Player()
    player.streamResolver = resolver
    player.restoreSession([{"id": 5, "path": "stream:https://youtu.be/x", "title": "X", "duration": 6}], 0, 0)
    player.togglePlay()
    assert player.loadAutoplay is True
    player.togglePlay()
    assert player.loadAutoplay is False
    assert waitFor(application, lambda: not player.loading)
    assert len(calls) == 1
    player.shutdown()


def test_playAfterFailedStartupResolveRetries(application, httpAudio):
    attempts = []

    def resolver(target, useCache=True):
        attempts.append(target)
        if len(attempts) == 1:
            raise RuntimeError("offline")
        return {"url": httpAudio, "headers": {}, "duration": 6}

    from app.player import Player
    player = Player()
    player.streamResolver = resolver
    player.restoreSession([{"id": 9, "path": "stream:https://youtu.be/z", "title": "Z", "duration": 6}], 0, 0)
    assert waitFor(application, lambda: not player.loading and attempts)
    player.togglePlay()
    assert waitFor(application, lambda: len(attempts) == 2 and not player.loading)
    assert player.mediaPlayer.source().toString() == httpAudio
    player.shutdown()


class RangeHandler(http.server.BaseHTTPRequestHandler):
    payload = b""
    requests = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/forbidden"):
            self.send_response(403)
            self.end_headers()
            return
        rangeHeader = self.headers.get("Range")
        RangeHandler.requests.append(rangeHeader)
        if self.path.startswith("/breaking") and rangeHeader and not rangeHeader.startswith("bytes=0-"):
            self.send_response(403)
            self.end_headers()
            return
        start, end = 0, len(self.payload) - 1
        if rangeHeader:
            first, last = rangeHeader.replace("bytes=", "").split("-")
            start = int(first)
            end = min(int(last), len(self.payload) - 1) if last else len(self.payload) - 1
        body = self.payload[start:end + 1]
        try:
            self.send_response(206 if rangeHeader else 200)
            self.send_header("Accept-Ranges", "bytes")
            if rangeHeader:
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(self.payload)}")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


@pytest.fixture(scope="module")
def rangeServer():
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "tone.m4a")
    subprocess.run([ffmpegExe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
                    "-c:a", "aac", "-movflags", "+frag_keyframe+empty_moov", path], check=True)
    RangeHandler.payload = open(path, "rb").read()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_streamIsFetchedInRangeChunks(application, rangeServer, monkeypatch):
    from app import audio_engine
    monkeypatch.setattr(audio_engine, "STREAM_CHUNK_BYTES", 20000)
    RangeHandler.requests = []
    engine = audio_engine.AudioEngine()
    statuses = []
    engine.mediaStatusChanged.connect(statuses.append)
    engine.setSource(QUrl(rangeServer + "/tone.m4a"))
    assert waitFor(application, lambda: QMediaPlayer.BufferedMedia in statuses)
    assert abs(engine.duration() - 8000) < 200
    assert len(RangeHandler.requests) >= len(RangeHandler.payload) // 20000
    assert all(header and header.startswith("bytes=") for header in RangeHandler.requests)
    engine.shutdown()


def test_forbiddenStreamGivesShortMessage(application, rangeServer):
    from app.audio_engine import AudioEngine
    engine = AudioEngine()
    errors = []
    engine.errorOccurred.connect(lambda error, message: errors.append(message))
    engine.setSource(QUrl(rangeServer + "/forbidden?expire=1&sig=" + "x" * 300))
    assert waitFor(application, lambda: errors)
    assert errors[0] == "YouTube ha rifiutato lo streaming (403)"
    engine.shutdown()


def test_refusedStreamFallsBackToTemporaryDownload(application, rangeServer, httpAudio, tmp_path, monkeypatch):
    import sounddevice
    from tests.test_together import FakeOutputStream
    monkeypatch.setattr(sounddevice, "OutputStream", FakeOutputStream)
    localCopy = tmp_path / "copy.mp3"
    import urllib.request
    localCopy.write_bytes(urllib.request.urlopen(httpAudio).read())
    resolves, fallbacks, errors = [], [], []
    from app.player import Player
    player = Player()
    player.streamResolver = lambda target, useCache=True: resolves.append(useCache) or {
        "url": rangeServer + "/forbidden", "headers": {}, "duration": 6}
    player.streamFallback = lambda target: fallbacks.append(target) or str(localCopy)
    player.playbackError.connect(errors.append)
    player.playSongs([{"id": 3, "path": "stream:https://youtu.be/q", "title": "Q", "duration": 6}], 0)
    assert waitFor(application, lambda: fallbacks and not player.loading and player.mediaPlayer.source().isLocalFile(), 15)
    assert resolves == [True, False]
    assert fallbacks == ["https://youtu.be/q"]
    assert errors == []
    player.shutdown()


def test_shortErrorHidesUrls():
    from app.player import _shortError
    message = ("ERROR: [youtube] abc: Unable to download https://rr1---sn.googlevideo.com/videoplayback?expire=1&" + "x" * 500 +
               " (caused by ProxyError('boom'))\nTraceback...")
    cleaned = _shortError(message)
    assert "http" not in cleaned and len(cleaned) <= 123 and cleaned.startswith("[youtube] abc")


def test_streamCutMidSongReportsError(application, rangeServer, monkeypatch):
    from app import audio_engine
    monkeypatch.setattr(audio_engine, "STREAM_CHUNK_BYTES", 30000)
    engine = audio_engine.AudioEngine()
    errors = []
    engine.errorOccurred.connect(lambda error, message: errors.append(message))
    engine.setSource(QUrl(rangeServer + "/breaking/tone.m4a"))
    assert waitFor(application, lambda: errors, 10)
    assert "403" in errors[0]
    engine.shutdown()
