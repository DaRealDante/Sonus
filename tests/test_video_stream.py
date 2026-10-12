import os
import re
import subprocess
import tempfile
import threading
import time
import http.server

import pytest
from PySide6.QtWidgets import QApplication

from app.config import ffmpegExe


class RangeHandler(http.server.BaseHTTPRequestHandler):
    """A tiny YouTube: answers byte ranges and refuses requests bigger than 8 MB like googlevideo throttles them."""
    data = b""
    requests = []
    hang = False

    def log_message(self, *args):
        pass

    def do_GET(self):
        RangeHandler.requests.append(self.headers.get("Range"))
        if RangeHandler.hang:
            time.sleep(30)
            return
        match = re.match(r"bytes=(\d+)-(\d*)", self.headers.get("Range") or "")
        start = int(match.group(1)) if match else 0
        end = int(match.group(2)) if match and match.group(2) else len(self.data) - 1
        end = min(end, len(self.data) - 1)
        body = self.data[start:end + 1]
        self.send_response(206)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Range", f"bytes {start}-{end}/{len(self.data)}")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


@pytest.fixture(scope="module")
def videoServer():
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "video.mp4")
    subprocess.run([ffmpegExe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=20",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", path], check=True)
    RangeHandler.data = open(path, "rb").read()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/videoplayback"
    server.shutdown()


class FakePlayer:
    def __init__(self):
        self.startedAt = time.monotonic()
        self.playing = True

    def isPlaying(self):
        return self.playing

    def position(self):
        return int((time.monotonic() - self.startedAt) * 1000)

    def playbackRate(self):
        return 1.0


def waitFor(condition, timeout):
    application = QApplication.instance()
    deadline = time.time() + timeout
    while time.time() < deadline:
        application.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    return False


def test_proxyServesRangesInPieces(videoServer, monkeypatch):
    import urllib.request
    from app import video_proxy
    monkeypatch.setattr(video_proxy, "CHUNK_BYTES", 20 * 1024)
    RangeHandler.requests = []
    local = video_proxy.localUrl(videoServer)
    request = urllib.request.Request(local, headers={"Range": "bytes=100-"})
    with urllib.request.urlopen(request, timeout=10) as response:
        body = response.read()
        assert response.status == 206
        assert response.headers["Content-Range"] == f"bytes 100-{len(RangeHandler.data) - 1}/{len(RangeHandler.data)}"
    assert body == RangeHandler.data[100:]
    assert len(RangeHandler.requests) >= 2
    assert all(re.match(r"bytes=\d+-\d+$", value) for value in RangeHandler.requests)


def test_streamingVideoPlaysThroughTheProxy(videoServer):
    from app.ui.video_controller import VideoController
    RangeHandler.hang = False
    controller = VideoController(FakePlayer())
    controller.request("pane", videoServer)
    assert waitFor(lambda: controller.hasFrames(), 15)
    firstFrameAt = controller.lastFrameTime
    assert waitFor(lambda: controller.lastFrameTime > firstFrameAt + 1, 10)
    assert not controller.failed
    controller.unload()


def test_frozenVideoGivesUpAndShowsTheCover(videoServer, monkeypatch):
    import app.ui.video_controller as video_controller
    monkeypatch.setattr(video_controller, "FIRST_FRAME_SECONDS", 1.5)
    RangeHandler.hang = True
    try:
        controller = video_controller.VideoController(FakePlayer())
        controller.request("pane", videoServer + "?frozen=1")
        assert waitFor(lambda: controller.failed, 15)
        assert video_controller.videoImage(controller) is None
        controller.unload()
    finally:
        RangeHandler.hang = False


def _countSeeks(controller):
    seeks = []
    original = controller.mediaPlayer.setPosition
    controller.mediaPlayer.setPosition = lambda position: (seeks.append(position), original(position))
    return seeks


def _frameGaps(controller, seconds):
    application = QApplication.instance()
    gaps, last = [], None
    deadline = time.time() + seconds
    while time.time() < deadline:
        application.processEvents()
        if controller.lastFrameTime != last:
            if last:
                gaps.append(controller.lastFrameTime - last)
            last = controller.lastFrameTime
        time.sleep(0.005)
    return gaps


def test_slowYoutubeDoesNotFreezeTheVideo(videoServer, monkeypatch):
    """YouTube answering each piece late made the video jump every 2 s, and every jump was a freeze."""
    from app import video_proxy
    from app.ui.video_controller import VideoController
    monkeypatch.setattr(video_proxy, "CHUNK_BYTES", 256 * 1024)
    original = RangeHandler.do_GET
    monkeypatch.setattr(RangeHandler, "do_GET", lambda self: (time.sleep(0.6), original(self)))
    controller = VideoController(FakePlayer())
    seeks = _countSeeks(controller)
    controller.request("pane", videoServer + "?slow=1")
    assert waitFor(lambda: controller.hasFrames(), 15)
    gaps = _frameGaps(controller, 10)
    assert seeks == []
    assert max(gaps) < 0.4, max(gaps)
    assert abs(controller.mediaPlayer.position() - controller.player.position()) < 700
    controller.unload()


def test_realJumpMovesTheVideoOnce(videoServer):
    from app.ui.video_controller import VideoController
    player = FakePlayer()
    controller = VideoController(player)
    seeks = _countSeeks(controller)
    controller.request("pane", videoServer + "?jump=1")
    assert waitFor(lambda: controller.hasFrames(), 15)
    _frameGaps(controller, 1)
    player.startedAt -= 9
    assert waitFor(lambda: len(seeks) == 1, 3)
    _frameGaps(controller, 2)
    assert len(seeks) == 1
    assert waitFor(lambda: abs(controller.mediaPlayer.position() - player.position()) < 700, 6)
    controller.unload()
