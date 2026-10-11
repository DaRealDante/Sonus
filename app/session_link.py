import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import uuid
import zlib

from PySide6.QtCore import QObject, QTimer, Signal

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
ROOM_PREFIX = "SONUS"
PLAYLIST_PREFIX = "SONUSP"
LINK_SCHEME = "sonus://join/"
MAX_PAYLOAD = 2 * 1024 * 1024
_CODE_PATTERN = re.compile(r"(SONUSP|SONUS)-([A-Z0-9]{4})-([A-Z0-9]{4})")


def makeCode(prefix=ROOM_PREFIX):
    groups = ["".join(secrets.choice(CODE_ALPHABET) for _ in range(4)) for _ in range(2)]
    return f"{prefix}-{groups[0]}-{groups[1]}"


def parseCode(text):
    """Accepts a code or a sonus:// link (any case, extra spaces). Returns ("room"|"playlist", code) or None."""
    if not text:
        return None
    cleaned = re.sub(r"\s+", "", str(text)).upper()
    match = _CODE_PATTERN.search(cleaned)
    if not match:
        return None
    prefix, first, second = match.groups()
    if any(character not in CODE_ALPHABET for character in first + second):
        return None
    code = f"{prefix}-{first}-{second}"
    return ("playlist" if prefix == PLAYLIST_PREFIX else "room"), code


def linkFor(code):
    return LINK_SCHEME + code


# Old rooms and playlists stay on the server for a while, then the server deletes them by itself
# (the free plan keeps at most 2000 saved messages).
ROOM_EXPIRY_SECONDS = 2 * 24 * 3600
PLAYLIST_EXPIRY_SECONDS = 180 * 24 * 3600


def brokerList():
    """Ways to reach the Sonus server: (host, port, tls, websocketPath, username, password).
    The normal TLS port first, then the WebSocket one (like a website) for networks that block it.
    SONUS_BROKERS="host:port:tls[:wspath],..." replaces them (tests)."""
    configured = os.environ.get("SONUS_BROKERS", "").strip()
    if configured:
        brokers = []
        for item in configured.split(","):
            parts = item.split(":")
            host, port, useTls = (parts + ["1"])[:3]
            path = parts[3] if len(parts) > 3 and parts[3] else None
            brokers.append((host, int(port), useTls not in ("0", "false", ""), path,
                            os.environ.get("SONUS_BROKER_USER") or None, os.environ.get("SONUS_BROKER_PASSWORD") or None))
        return brokers
    from .config import BROKER_HOST, BROKER_PASSWORD, BROKER_PORT, BROKER_USERNAME, BROKER_WEBSOCKET_PORT
    credentials = (BROKER_USERNAME or None, BROKER_PASSWORD or None)
    return [(BROKER_HOST, BROKER_PORT, True, None, *credentials),
            (BROKER_HOST, BROKER_WEBSOCKET_PORT, True, "/mqtt", *credentials)]


def _expiryFor(code):
    return PLAYLIST_EXPIRY_SECONDS if code.startswith(PLAYLIST_PREFIX + "-") else ROOM_EXPIRY_SECONDS


def _tlsCertificates():
    try:
        import certifi
        return certifi.where()
    except Exception:
        return None


def _publishProperties(code, retain):
    if not retain:
        return None
    from paho.mqtt.packettypes import PacketTypes
    from paho.mqtt.properties import Properties
    properties = Properties(PacketTypes.PUBLISH)
    properties.MessageExpiryInterval = _expiryFor(code)
    return properties


class CodeBox:
    """Encrypts and signs messages with a key derived from the code: without the code nobody can read or forge them."""

    def __init__(self, code):
        self.code = code
        keyMaterial = hashlib.pbkdf2_hmac("sha256", code.encode("utf-8"), b"sonus-v1", 20000, 64)
        self.encryptionKey = keyMaterial[:32]
        self.macKey = keyMaterial[32:]
        kind = "p" if code.startswith(PLAYLIST_PREFIX + "-") else "r"
        self.topicBase = f"sonus/v1/{kind}/" + hashlib.sha256(b"topic:" + code.encode("utf-8")).hexdigest()[:24]

    def _keystream(self, nonce, length):
        blocks = []
        for counter in range((length + 31) // 32):
            blocks.append(hashlib.sha256(self.encryptionKey + nonce + counter.to_bytes(8, "big")).digest())
        return b"".join(blocks)[:length]

    def _xor(self, data, nonce):
        stream = self._keystream(nonce, len(data))
        return (int.from_bytes(data, "big") ^ int.from_bytes(stream, "big")).to_bytes(len(data), "big") if data else b""

    def seal(self, payload):
        plain = zlib.compress(json.dumps(payload, separators=(",", ":")).encode("utf-8"), 6)
        nonce = os.urandom(16)
        cipher = self._xor(plain, nonce)
        mac = hmac.new(self.macKey, nonce + cipher, hashlib.sha256).digest()[:16]
        return b"\x01" + nonce + mac + cipher

    def open(self, data):
        try:
            if not data or len(data) < 33 or data[0] != 1:
                return None
            nonce, mac, cipher = data[1:17], data[17:33], data[33:]
            expected = hmac.new(self.macKey, nonce + cipher, hashlib.sha256).digest()[:16]
            if not hmac.compare_digest(mac, expected):
                return None
            decompressor = zlib.decompressobj()
            plain = decompressor.decompress(self._xor(cipher, nonce), MAX_PAYLOAD)
            if decompressor.unconsumed_tail:
                return None
            return json.loads(plain.decode("utf-8"))
        except Exception:
            return None


class Link(QObject):
    """One MQTT connection to the Sonus server; reconnects by itself and switches to the WebSocket port if needed."""

    received = Signal(str, str, object)
    connectedChanged = Signal(bool)
    _connectResult = Signal(int, str)
    _incoming = Signal(str, bytes)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.boxes = {}
        self.subtopics = {}
        self.retainedOut = {}
        self.unsent = {}
        self.republishOnConnect = True
        self.will = None
        self.client = None
        self.brokers = brokerList()
        self.brokerIndex = 0
        self.attempt = 0
        self.connected = False
        self.running = False
        self.failures = 0
        self.lastError = ""
        self._connectResult.connect(self._onConnectResult)
        self._incoming.connect(self._onIncoming)
        self.retryTimer = QTimer(self)
        self.retryTimer.setSingleShot(True)
        self.retryTimer.timeout.connect(self._connect)

    # ---------- public API ----------
    def start(self):
        if self.running:
            return
        self.running = True
        self._connect()

    def stop(self):
        self.running = False
        self.retryTimer.stop()
        self._dropClient(graceful=True)
        self._setConnected(False)

    def restart(self):
        self._dropClient(graceful=True)
        self._setConnected(False)
        if self.running:
            self._connect()

    def watch(self, code, subtopics):
        box = self.boxes.get(code) or CodeBox(code)
        self.boxes[code] = box
        self.subtopics[code] = list(subtopics)
        if self.connected and self.client is not None:
            for subtopic in subtopics:
                self.client.subscribe(f"{box.topicBase}/{subtopic}", qos=1)

    def unwatch(self, code):
        box = self.boxes.pop(code, None)
        subtopics = self.subtopics.pop(code, [])
        for key in [key for key in self.retainedOut if key[0] == code]:
            del self.retainedOut[key]
        for key in [key for key in self.unsent if key[0] == code]:
            del self.unsent[key]
        if box is not None and self.connected and self.client is not None:
            for subtopic in subtopics:
                self.client.unsubscribe(f"{box.topicBase}/{subtopic}")

    def setWill(self, code, subtopic):
        """Empty retained message the broker publishes if this app disappears (crash, internet down)."""
        self.will = (code, subtopic) if code else None

    def publish(self, code, subtopic, payload, retain=False):
        box = self.boxes.get(code) or CodeBox(code)
        self.boxes.setdefault(code, box)
        data = box.seal(payload)
        if retain:
            self.retainedOut[(code, subtopic)] = data
        if self.client is not None:
            self.client.publish(f"{box.topicBase}/{subtopic}", data, qos=1, retain=retain,
                                properties=_publishProperties(code, retain))
        elif retain or not self.republishOnConnect:
            self.unsent[(code, subtopic)] = (data, retain)

    def clearRetained(self, code, subtopic):
        self.retainedOut.pop((code, subtopic), None)
        self.unsent.pop((code, subtopic), None)
        box = self.boxes.get(code) or CodeBox(code)
        if self.client is not None and self.connected:
            info = self.client.publish(f"{box.topicBase}/{subtopic}", b"", qos=1, retain=True)
            try:
                info.wait_for_publish(1.0)
            except Exception:
                pass

    def isConnected(self):
        return self.connected

    def brokerName(self):
        if not self.brokers:
            return ""
        host, port, _, path = self.brokers[self.brokerIndex % len(self.brokers)][:4]
        return f"{host}:{port}" + (" (web)" if path else "")

    # ---------- connection ----------
    def _connect(self):
        if not self.running:
            return
        import paho.mqtt.client as mqtt
        self._dropClient(graceful=False)
        self.attempt += 1
        attempt = self.attempt
        host, port, useTls, path, username, password = self.brokers[self.brokerIndex % len(self.brokers)]
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"sonus-{uuid.uuid4().hex[:16]}",
                             protocol=mqtt.MQTTv5, transport="websockets" if path else "tcp")
        if path:
            client.ws_set_options(path=path)
        client.max_queued_messages_set(200)
        if username:
            client.username_pw_set(username, password)
        if useTls:
            client.tls_set(ca_certs=_tlsCertificates())
        if self.will:
            box = self.boxes.get(self.will[0]) or CodeBox(self.will[0])
            client.will_set(f"{box.topicBase}/{self.will[1]}", b"", qos=1, retain=True)
        client.reconnect_delay_set(1, 20)

        attemptState = {"confirmed": False}

        def onConnect(clientRef, userdata, flags, reasonCode, properties):
            attemptState["confirmed"] = not reasonCode.is_failure
            if reasonCode.is_failure:
                self.lastError = f"rifiutato dal server ({reasonCode})"
                print(f"[Link] il server ha rifiutato la connessione: {reasonCode}")
            self._connectResult.emit(attempt, "failed" if reasonCode.is_failure else "connected")

        def onConnectFail(clientRef, userdata):
            self.lastError = "connessione fallita (porta bloccata o server giù)"
            self._connectResult.emit(attempt, "failed")

        def onDisconnect(clientRef, userdata, flags, reasonCode, properties):
            confirmed = attemptState["confirmed"]
            attemptState["confirmed"] = False
            self._connectResult.emit(attempt, "lost" if confirmed else "failed")

        def onMessage(clientRef, userdata, message):
            self._incoming.emit(message.topic, bytes(message.payload))

        client.on_connect = onConnect
        client.on_connect_fail = onConnectFail
        client.on_disconnect = onDisconnect
        client.on_message = onMessage
        self.client = client
        try:
            client.connect_async(host, port, keepalive=30, clean_start=True)
            client.loop_start()
        except Exception as error:
            self.lastError = repr(error)
            print(f"[Link] {host}:{port} non raggiungibile: {error!r}")
            self._connectResult.emit(attempt, "failed")

    def _onConnectResult(self, attempt, result):
        if attempt != self.attempt or not self.running:
            return
        if result == "connected":
            self.failures = 0
            self.lastError = ""
            for code, subtopics in self.subtopics.items():
                box = self.boxes[code]
                for subtopic in subtopics:
                    self.client.subscribe(f"{box.topicBase}/{subtopic}", qos=1)
            outgoing = {key: (data, True) for key, data in self.retainedOut.items()} if self.republishOnConnect else {}
            outgoing.update(self.unsent)
            self.unsent = {}
            for (code, subtopic), (data, retain) in outgoing.items():
                box = self.boxes.get(code) or CodeBox(code)
                self.client.publish(f"{box.topicBase}/{subtopic}", data, qos=1, retain=retain,
                                    properties=_publishProperties(code, retain))
            print(f"[Link] connesso a {self.brokerName()}")
            self._setConnected(True)
            return
        self._setConnected(False)
        if result == "lost":
            return
        self.failures += 1
        print(f"[Link] {self.brokerName()}: {self.lastError or 'non risponde'}")
        if self.failures >= 2:
            self.failures = 0
            self.brokerIndex = (self.brokerIndex + 1) % len(self.brokers)
            print(f"[Link] provo {self.brokerName()}")
            self.retryTimer.start(500)

    def _dropClient(self, graceful):
        client = self.client
        self.client = None
        self.attempt += 1
        if client is None:
            return
        client.on_connect = None
        client.on_connect_fail = None
        client.on_disconnect = None
        client.on_message = None

        def close():
            # In the background: a server that never answers keeps paho's thread stuck in the handshake,
            # and waiting for it here froze the whole app for up to 30 seconds.
            try:
                if graceful:
                    client.disconnect()
                client.loop_stop()
            except Exception:
                pass

        threading.Thread(target=close, daemon=True).start()

    def _setConnected(self, connected):
        if connected != self.connected:
            self.connected = connected
            self.connectedChanged.emit(connected)

    def _onIncoming(self, topic, data):
        for code, box in list(self.boxes.items()):
            prefix = box.topicBase + "/"
            if topic.startswith(prefix):
                subtopic = topic[len(prefix):]
                if not data:
                    self.received.emit(code, subtopic, None)
                    return
                payload = box.open(data)
                if payload is not None:
                    self.received.emit(code, subtopic, payload)
                return
