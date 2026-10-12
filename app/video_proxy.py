import hashlib
import http.server
import re
import threading
import time
import urllib.error

from . import fast_net

CHUNK_BYTES = 8 * 1024 * 1024
READ_BYTES = 64 * 1024
RESPONSE_TIMEOUT = 8
MAX_FAILURES = 4

_lock = threading.Lock()
_server = None
_targets = {}


class _Handler(http.server.BaseHTTPRequestHandler):
    """Gives the video player the YouTube video through 127.0.0.1: the video is fetched in pieces (YouTube slows
    down or cuts one giant request, and the video froze) and without waiting for a slow Windows DNS."""

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
        position = start
        total = None
        failures = 0
        sentHeaders = False
        while not sentHeaders or position <= end:
            last = position + CHUNK_BYTES - 1 if end is None else min(end, position + CHUNK_BYTES - 1)
            try:
                response = fast_net.openUrl(url, {**headers, "Range": f"bytes={position}-{last}"}, timeout=RESPONSE_TIMEOUT)
            except urllib.error.HTTPError as error:
                if error.code == 416 and sentHeaders:
                    return
                if not sentHeaders and (error.code in (403, 404, 410, 416) or failures >= MAX_FAILURES):
                    print(f"[Video] YouTube ha rifiutato il video (HTTP {error.code})")
                    self.send_error(error.code)
                    return
                failures += 1
                time.sleep(0.5 * failures)
                if failures > MAX_FAILURES:
                    return
                continue
            except Exception as error:
                failures += 1
                if failures > MAX_FAILURES:
                    print(f"[Video] YouTube non risponde: {error}")
                    if not sentHeaders:
                        self.send_error(504)
                    return
                continue
            with response:
                if not sentHeaders:
                    contentRange = response.headers.get("Content-Range") or ""
                    if "/" in contentRange and contentRange.rsplit("/", 1)[1].strip().isdigit():
                        total = int(contentRange.rsplit("/", 1)[1])
                    elif response.headers.get("Content-Length", "").isdigit():
                        total = int(response.headers["Content-Length"])
                    if total is None:
                        self.send_error(502)
                        return
                    end = total - 1 if end is None else min(end, total - 1)
                    self.send_response(206 if match else 200)
                    self.send_header("Content-Type", response.headers.get("Content-Type") or "video/mp4")
                    self.send_header("Accept-Ranges", "bytes")
                    if match:
                        self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
                    self.send_header("Content-Length", str(end - start + 1))
                    self.end_headers()
                    sentHeaders = True
                received = 0
                try:
                    while position <= end:
                        data = response.read(min(READ_BYTES, end - position + 1))
                        if not data:
                            break
                        self.wfile.write(data)
                        position += len(data)
                        received += len(data)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError) as error:
                    if isinstance(error, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
                        return
                    failures += 1
                    if failures > MAX_FAILURES:
                        return
                    continue
            if received:
                failures = 0
            elif response.status == 200:
                return
            else:
                failures += 1
                if failures > MAX_FAILURES:
                    return


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
    token = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
    with _lock:
        _targets[token] = (url, dict(headers or {}))
        if len(_targets) > 50:
            for oldToken in list(_targets)[:10]:
                if oldToken != token:
                    _targets.pop(oldToken, None)
    return f"http://127.0.0.1:{server.server_address[1]}/video/{token}"
