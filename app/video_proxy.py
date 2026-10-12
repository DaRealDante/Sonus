import hashlib
import http.server
import queue
import re
import threading
import time
import urllib.error

from . import fast_net

CHUNK_BYTES = 8 * 1024 * 1024
READ_BYTES = 256 * 1024
AHEAD_BLOCKS = 96  # ~24 MB downloaded ahead of the player: a slow piece from YouTube is never seen as a freeze
RESPONSE_TIMEOUT = 8
MAX_FAILURES = 4

_lock = threading.Lock()
_server = None
_targets = {}


def _download(url, headers, start, end, blocks, stop):
    """Worker thread: fetches the video from YouTube in pieces, as fast as it can, ahead of the player."""

    def put(item):
        while not stop.is_set():
            try:
                blocks.put(item, timeout=0.5)
                return True
            except queue.Full:
                continue
        return False

    position = start
    total = None
    failures = 0
    while not stop.is_set() and (end is None or position <= end):
        last = position + CHUNK_BYTES - 1 if end is None else min(end, position + CHUNK_BYTES - 1)
        try:
            response = fast_net.openUrl(url, {**headers, "Range": f"bytes={position}-{last}"}, timeout=RESPONSE_TIMEOUT)
        except urllib.error.HTTPError as error:
            if total is not None and error.code == 416:
                break
            failures += 1
            if total is None and (error.code in (403, 404, 410, 416) or failures > MAX_FAILURES):
                print(f"[Video] YouTube ha rifiutato il video (HTTP {error.code})")
                put(("error", error.code))
                return
            if failures > MAX_FAILURES:
                break
            time.sleep(0.5 * failures)
            continue
        except Exception as error:
            failures += 1
            if failures > MAX_FAILURES:
                print(f"[Video] YouTube non risponde: {error}")
                put(("error", 504) if total is None else ("end", None))
                return
            continue
        received = 0
        with response:
            if total is None:
                contentRange = response.headers.get("Content-Range") or ""
                if "/" in contentRange and contentRange.rsplit("/", 1)[1].strip().isdigit():
                    total = int(contentRange.rsplit("/", 1)[1])
                elif (response.headers.get("Content-Length") or "").isdigit():
                    total = position + int(response.headers["Content-Length"])
                if total is None:
                    put(("error", 502))
                    return
                end = total - 1 if end is None else min(end, total - 1)
                if not put(("meta", (total, end, response.headers.get("Content-Type") or "video/mp4"))):
                    return
            try:
                while not stop.is_set() and position <= end:
                    data = response.read(min(READ_BYTES, end - position + 1))
                    if not data:
                        break
                    if not put(("data", data)):
                        return
                    position += len(data)
                    received += len(data)
            except Exception:
                failures += 1
                if failures > MAX_FAILURES:
                    break
                continue
        if received:
            failures = 0
        elif response.status == 200:
            break
        else:
            failures += 1
            if failures > MAX_FAILURES:
                break
    put(("end", None))


class _Handler(http.server.BaseHTTPRequestHandler):
    """Gives the video player the YouTube video through 127.0.0.1: the video is fetched in pieces (YouTube slows
    down or cuts one giant request), ahead of time and without waiting for a slow Windows DNS."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        target = _targets.get(self.path.rsplit("/", 1)[-1])
        if target is None:
            self.send_error(404)
            return
        url, headers = target
        match = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
        start = int(match.group(1)) if match and match.group(1) else 0
        end = int(match.group(2)) if match and match.group(2) else None
        blocks = queue.Queue(maxsize=AHEAD_BLOCKS)
        stop = threading.Event()
        threading.Thread(target=_download, args=(url, headers, start, end, blocks, stop), daemon=True).start()
        try:
            kind, value = blocks.get(timeout=RESPONSE_TIMEOUT * (MAX_FAILURES + 1))
            if kind == "error":
                self.send_error(value)
                return
            if kind != "meta":
                self.send_error(502)
                return
            total, end, contentType = value
            self.send_response(206 if match else 200)
            self.send_header("Content-Type", contentType)
            self.send_header("Accept-Ranges", "bytes")
            if match:
                self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            while True:
                kind, value = blocks.get(timeout=RESPONSE_TIMEOUT * (MAX_FAILURES + 1))
                if kind != "data":
                    return
                self.wfile.write(value)
        except (queue.Empty, BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return
        finally:
            stop.set()


def _ensureServer():
    global _server
    with _lock:
        if _server is None:
            _server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
            _server.daemon_threads = True
            threading.Thread(target=_server.serve_forever, daemon=True).start()
        return _server


def localUrl(url, headers=None):
    """Address on this PC the video player can open instead of the YouTube one."""
    server = _ensureServer()
    if headers is None:
        from .downloader import videoHeaders
        headers = videoHeaders(url)
    token = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
    with _lock:
        _targets[token] = (url, dict(headers or {}))
        if len(_targets) > 50:
            for oldToken in list(_targets)[:10]:
                if oldToken != token:
                    _targets.pop(oldToken, None)
    return f"http://127.0.0.1:{server.server_address[1]}/video/{token}"
