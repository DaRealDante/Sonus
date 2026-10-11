import os
import signal
import subprocess
import sys
import textwrap

from app.session_link import CodeBox, Link, linkFor, makeCode, parseCode
from tests.broker import localBroker, pump, waitFor, passwordBroker, webSocketBroker  # noqa: F401


def test_sealOpenRoundTrip():
    box = CodeBox("SONUS-ABCD-EFGH")
    payload = {"song": "Ciao", "positionMs": 1234, "photo": "x" * 20000}
    assert box.open(box.seal(payload)) == payload


def test_tamperedOrForeignMessagesRejected():
    box = CodeBox("SONUS-ABCD-EFGH")
    sealed = bytearray(box.seal({"a": 1}))
    sealed[-1] ^= 0x01
    assert box.open(bytes(sealed)) is None
    assert CodeBox("SONUS-ABCD-EFGJ").open(box.seal({"a": 1})) is None
    assert box.open(b"") is None
    assert box.open(b"garbage" * 10) is None


def test_topicDependsOnCodeAndKind():
    assert CodeBox("SONUS-ABCD-EFGH").topicBase != CodeBox("SONUS-ABCD-EFGJ").topicBase
    assert "/r/" in CodeBox("SONUS-ABCD-EFGH").topicBase
    assert "/p/" in CodeBox("SONUSP-ABCD-EFGH").topicBase
    assert "ABCD" not in CodeBox("SONUS-ABCD-EFGH").topicBase


def test_parseCodeAcceptsCodesAndLinks():
    code = makeCode()
    assert parseCode(code) == ("room", code)
    assert parseCode(linkFor(code)) == ("room", code)
    assert parseCode("  " + code.lower() + " ") == ("room", code)
    assert parseCode("Entra qui: sonus://join/SONUSP-ABCD-EFGH grazie") == ("playlist", "SONUSP-ABCD-EFGH")
    assert parseCode("SONUS-AB0D-EFGH") is None
    assert parseCode("ciao") is None
    assert parseCode("") is None
    assert makeCode("SONUSP").startswith("SONUSP-")


def test_twoLinksExchangeAndRetainedState(localBroker):
    code = makeCode()
    first, second = Link(), Link()
    received = []
    second.received.connect(lambda c, subtopic, payload: received.append((subtopic, payload)))
    first.watch(code, ["state", "msg"])
    first.start()
    assert waitFor(first.isConnected)
    first.publish(code, "state", {"version": 1}, retain=True)
    pump(0.3)
    second.watch(code, ["state", "msg", "presence/+"])
    second.start()
    assert waitFor(lambda: ("state", {"version": 1}) in received)
    first.publish(code, "msg", {"type": "ping"})
    assert waitFor(lambda: ("msg", {"type": "ping"}) in received)
    first.stop()
    second.stop()


def test_willClearsPresenceWhenAppDies(localBroker):
    code = makeCode()
    script = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {os.getcwd()!r})
        from PySide6.QtCore import QCoreApplication
        app = QCoreApplication([])
        from app.session_link import Link
        link = Link()
        link.watch({code!r}, ["presence/+"])
        link.setWill({code!r}, "presence/dying")
        link.start()
        deadline = time.time() + 5
        while not link.isConnected() and time.time() < deadline:
            app.processEvents(); time.sleep(0.01)
        link.publish({code!r}, "presence/dying", {{"name": "Luca"}}, retain=True)
        print("ready", flush=True)
        while True:
            app.processEvents(); time.sleep(0.01)
    """)
    process = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, env=dict(os.environ))
    line = b""
    for _ in range(10):
        line = process.stdout.readline().strip()
        if line == b"ready" or not line:
            break
    assert line == b"ready"
    watcher = Link()
    events = []
    watcher.received.connect(lambda c, subtopic, payload: events.append((subtopic, payload)))
    watcher.watch(code, ["presence/+"])
    watcher.start()
    assert waitFor(lambda: ("presence/dying", {"name": "Luca"}) in events)
    process.send_signal(signal.SIGKILL)
    process.wait()
    assert waitFor(lambda: ("presence/dying", None) in events, timeout=60)
    watcher.stop()


def test_failoverToSecondBroker(localBroker):
    from tests.broker import freePort
    deadPort = freePort()
    previous = os.environ["SONUS_BROKERS"]
    os.environ["SONUS_BROKERS"] = f"127.0.0.1:{deadPort}:0,{previous}"
    try:
        link = Link()
        link.watch(makeCode(), ["state"])
        link.start()
        assert waitFor(link.isConnected, timeout=20)
        assert link.brokerIndex == 1
        link.stop()
    finally:
        os.environ["SONUS_BROKERS"] = previous


def test_failoverWhenBrokerDropsBeforeConfirming(localBroker):
    import socket
    import threading
    from tests.broker import freePort
    dropPort = freePort()
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", dropPort))
    listener.listen(16)
    running = [True]

    def dropConnections():
        listener.settimeout(0.2)
        while running[0]:
            try:
                connection, _ = listener.accept()
                connection.close()
            except OSError:
                pass

    threading.Thread(target=dropConnections, daemon=True).start()
    previous = os.environ["SONUS_BROKERS"]
    os.environ["SONUS_BROKERS"] = f"127.0.0.1:{dropPort}:0,{previous}"
    try:
        link = Link()
        link.watch(makeCode(), ["state"])
        link.start()
        assert waitFor(link.isConnected, timeout=25)
        assert link.brokerIndex == 1
        link.stop()
    finally:
        os.environ["SONUS_BROKERS"] = previous
        running[0] = False
        listener.close()


def _linkFor(brokers, user=None, password=None):
    saved = {key: os.environ.get(key) for key in ("SONUS_BROKERS", "SONUS_BROKER_USER", "SONUS_BROKER_PASSWORD")}
    os.environ["SONUS_BROKERS"] = brokers
    os.environ["SONUS_BROKER_USER"] = user or ""
    os.environ["SONUS_BROKER_PASSWORD"] = password or ""
    try:
        return Link()
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_privateServerNeedsTheAppPassword(passwordBroker):
    good = _linkFor(f"127.0.0.1:{passwordBroker}:0", "SonusPlayer", "segreta")
    bad = _linkFor(f"127.0.0.1:{passwordBroker}:0", "SonusPlayer", "sbagliata")
    for link in (good, bad):
        link.watch(makeCode(), ["#"])
        link.start()
    assert waitFor(good.isConnected, 10)
    pump(2)
    assert not bad.isConnected()
    good.stop()
    bad.stop()


def test_switchesToWebSocketPortWhenNormalPortIsBlocked(webSocketBroker):
    from tests.broker import freePort
    code = makeCode()
    blocked = _linkFor(f"127.0.0.1:{freePort()}:0,127.0.0.1:{webSocketBroker}:0:/mqtt")
    friend = _linkFor(f"127.0.0.1:{webSocketBroker}:0:/mqtt")
    events = []
    friend.received.connect(lambda c, subtopic, payload: events.append((subtopic, payload)))
    friend.watch(code, ["#"])
    friend.start()
    blocked.watch(code, ["#"])
    blocked.publish(code, "presence/me", {"name": "me"}, retain=True)
    blocked.start()
    assert waitFor(blocked.isConnected, 20)
    assert "(web)" in blocked.brokerName()
    assert waitFor(lambda: ("presence/me", {"name": "me"}) in events, 10)
    blocked.stop()
    friend.stop()


def test_oldRoomsExpireOnTheServer(localBroker, monkeypatch):
    import app.session_link as sessionLink
    monkeypatch.setattr(sessionLink, "ROOM_EXPIRY_SECONDS", 1)
    code = makeCode()
    owner = Link()
    owner.watch(code, ["#"])
    owner.publish(code, "state", {"version": 1}, retain=True)
    owner.start()
    assert waitFor(owner.isConnected)
    pump(0.5)
    owner.stop()
    pump(2.5)
    late = Link()
    events = []
    late.received.connect(lambda c, subtopic, payload: events.append((subtopic, payload)))
    late.watch(code, ["#"])
    late.start()
    assert waitFor(late.isConnected)
    pump(1)
    assert ("state", {"version": 1}) not in events
    late.stop()


def test_silentServerNeverFreezesTheApp():
    import socket
    import threading
    import time
    from PySide6.QtWidgets import QApplication
    silent = socket.socket()
    silent.bind(("127.0.0.1", 0))
    silent.listen(50)
    port = silent.getsockname()[1]
    held = []

    def acceptForever():
        while True:
            try:
                held.append(silent.accept())
            except OSError:
                return

    threading.Thread(target=acceptForever, daemon=True).start()
    link = _linkFor(f"127.0.0.1:{port}:1,127.0.0.1:{port}:1:/mqtt")
    link.watch(makeCode(), ["#"])
    link.start()
    worst = 0.0
    last = time.monotonic()
    deadline = last + 5
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if link.client is not None and time.monotonic() - last < 1:
            link.restart()
        now = time.monotonic()
        worst = max(worst, now - last)
        last = now
        time.sleep(0.05)
    started = time.monotonic()
    link.stop()
    stopTime = time.monotonic() - started
    silent.close()
    assert worst < 0.5, f"UI bloccata per {worst:.1f}s"
    assert stopTime < 0.5
