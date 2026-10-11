import socket
import threading
import time

import pytest


@pytest.fixture(autouse=True)
def emptyCache():
    from app import fast_net
    fast_net._dnsCache.clear()
    yield
    fast_net._dnsCache.clear()


def test_slowWindowsDnsLosesTheRace(monkeypatch):
    from app import fast_net

    def slowSystem(host, family):
        time.sleep(4)
        return ["9.9.9.9"]

    monkeypatch.setattr(fast_net, "_systemLookup", slowSystem)
    monkeypatch.setattr(fast_net, "_dohLookup", lambda host, template, headers: ["1.2.3.4"])
    startedAt = time.monotonic()
    assert fast_net.resolveHost("rr1---sn-test.googlevideo.com") == ["1.2.3.4"]
    assert time.monotonic() - startedAt < 1
    assert fast_net.resolveHost("rr1---sn-test.googlevideo.com") == ["1.2.3.4"]


def test_ipv4FirstAndFailuresIgnored(monkeypatch):
    from app import fast_net

    def system(host, family):
        if family == socket.AF_INET:
            raise OSError("nessuna risposta")
        return ["2001:db8::1", "5.6.7.8"]

    monkeypatch.setattr(fast_net, "_systemLookup", system)
    monkeypatch.setattr(fast_net, "_dohLookup", lambda host, template, headers: (_ for _ in ()).throw(OSError("bloccato")))
    assert fast_net.resolveHost("example.test") == ["5.6.7.8", "2001:db8::1"]


def test_nothingAnswersRaises(monkeypatch):
    from app import fast_net
    monkeypatch.setattr(fast_net, "_systemLookup", lambda host, family: (_ for _ in ()).throw(OSError("no")))
    monkeypatch.setattr(fast_net, "_dohLookup", lambda host, template, headers: [])
    with pytest.raises(OSError):
        fast_net.resolveHost("nowhere.test", timeout=1)


def test_deadAddressIsSkippedQuickly(monkeypatch):
    from app import fast_net
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(4)
    port = server.getsockname()[1]
    realConnect = socket.socket.connect

    def connect(sock, address):
        if address[0] == "127.0.0.2":
            time.sleep(5)
            raise TimeoutError("timed out")
        return realConnect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    startedAt = time.monotonic()
    sock = fast_net._connectFirst(["127.0.0.2", "127.0.0.1"], port, 5)
    assert time.monotonic() - startedAt < 1.5
    assert sock.getpeername()[0] == "127.0.0.1"
    sock.close()
    server.close()


def test_httpStillWorksThroughUrllib():
    import http.server
    from app import fast_net

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ciao")

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with fast_net.openUrl(f"http://127.0.0.1:{server.server_address[1]}/x", timeout=5) as response:
        assert response.read() == b"ciao"
    server.shutdown()
