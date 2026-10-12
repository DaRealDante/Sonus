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
