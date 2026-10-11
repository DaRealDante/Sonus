import json
import os
import queue
import struct
import sys
import threading
import time
import uuid

OP_HANDSHAKE, OP_FRAME, OP_CLOSE = 0, 1, 2
ACTIVITY_LISTENING = 2


def _pipeCandidates():
    if sys.platform == "win32":
        return [rf"\\?\pipe\discord-ipc-{index}" for index in range(10)]
    base = os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("TMPDIR") or "/tmp"
    folders = [base, os.path.join(base, "app/com.discordapp.Discord"), os.path.join(base, "snap.discord")]
    return [os.path.join(folder, f"discord-ipc-{index}") for folder in folders for index in range(10)]


class _Connection:
    def __init__(self):
        self.handle = None
        self.socket = None

    def open(self):
        for path in _pipeCandidates():
            try:
                if sys.platform == "win32":
                    self.handle = open(path, "r+b", buffering=0)
                else:
                    import socket
                    if not os.path.exists(path):
                        continue
                    self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    self.socket.settimeout(5)
                    self.socket.connect(path)
                return True
            except OSError:
                self.handle = self.socket = None
        return False

    def send(self, opcode, payload):
        data = json.dumps(payload).encode("utf-8")
        packet = struct.pack("<II", opcode, len(data)) + data
        if self.handle is not None:
            self.handle.write(packet)
        else:
            self.socket.sendall(packet)

    def receive(self):
        header = self._read(8)
        opcode, length = struct.unpack("<II", header)
        return opcode, json.loads(self._read(length).decode("utf-8") or "{}")

    def _read(self, size):
        data = b""
        while len(data) < size:
            chunk = self.handle.read(size - len(data)) if self.handle is not None else self.socket.recv(size - len(data))
            if not chunk:
                raise OSError("Discord ha chiuso la connessione")
            data += chunk
        return data

    def close(self):
        for resource in (self.handle, self.socket):
            try:
                if resource is not None:
                    resource.close()
            except OSError:
                pass
        self.handle = self.socket = None


def buildActivity(song, positionMs, durationMs, playing, rate=1.0, nowSeconds=None):
    """What Discord shows: "Listening to Sonus", title, artist, cover and the progress bar."""
    if not song:
        return None
    nowSeconds = nowSeconds or time.time()
    title = (song.get("title") or "Senza titolo")[:128]
    artist = (song.get("artist") or "Artista sconosciuto")[:128]
    activity = {"type": ACTIVITY_LISTENING, "details": title.ljust(2), "state": (artist if playing else f"In pausa · {artist}").ljust(2)[:128],
                "assets": {"large_text": (song.get("album") or title)[:128]}}
    from .together_sync import youtubeId
    videoId = youtubeId(song.get("url"))
    if videoId:
        activity["assets"]["large_image"] = f"https://i.ytimg.com/vi/{videoId}/hqdefault.jpg"
        activity["buttons"] = [{"label": "Ascolta su YouTube", "url": f"https://www.youtube.com/watch?v={videoId}"}]
    else:
        activity["assets"]["large_image"] = "logo"
    if playing and durationMs > 0:
        rate = rate or 1.0
        startSeconds = nowSeconds - positionMs / 1000 / rate
        activity["timestamps"] = {"start": int(startSeconds * 1000), "end": int((startSeconds + durationMs / 1000 / rate) * 1000)}
    return activity


class DiscordPresence:
    """Discord status via the local IPC pipe of the Discord app (no login, no token). Runs in its own thread."""

    def __init__(self, clientId, connectionFactory=_Connection, retrySeconds=15):
        self.clientId = str(clientId or "").strip()
        self.connectionFactory = connectionFactory
        self.retrySeconds = retrySeconds
        self.commands = queue.Queue()
        self.thread = None
        self.connected = False
        self.lastActivity = None

    def start(self):
        if not self.clientId or self.thread is not None:
            return False
        self.thread = threading.Thread(target=self._run, name="DiscordPresence", daemon=True)
        self.thread.start()
        return True

    def update(self, activity):
        if self.thread is not None:
            self.commands.put(("activity", activity))

    def stop(self):
        if self.thread is not None:
            self.commands.put(("quit", None))

    def _run(self):
        connection = None
        pending = None
        nextAttempt = 0.0
        while True:
            try:
                command, value = self.commands.get(timeout=1.0)
            except queue.Empty:
                command, value = None, None
            if command == "quit":
                if connection is not None:
                    try:
                        self._setActivity(connection, None)
                    except Exception:
                        pass
                    connection.close()
                return
            if command == "activity":
                pending = ("set", value)
            if connection is None and pending is not None and time.time() >= nextAttempt:
                connection = self._connect()
                if connection is None:
                    nextAttempt = time.time() + self.retrySeconds
            if connection is not None and pending is not None:
                try:
                    self._setActivity(connection, pending[1])
                    self.lastActivity = pending[1]
                    pending = None
                except Exception:
                    connection.close()
                    connection = None
                    self.connected = False
                    nextAttempt = time.time() + 2

    def _connect(self):
        connection = self.connectionFactory()
        try:
            if not connection.open():
                return None
            connection.send(OP_HANDSHAKE, {"v": 1, "client_id": self.clientId})
            opcode, reply = connection.receive()
            if opcode == OP_CLOSE or reply.get("evt") == "ERROR":
                connection.close()
                return None
            self.connected = True
            return connection
        except Exception:
            connection.close()
            return None

    def _setActivity(self, connection, activity):
        payload = {"cmd": "SET_ACTIVITY", "args": {"pid": os.getpid()}, "nonce": uuid.uuid4().hex}
        if activity:
            payload["args"]["activity"] = activity
        connection.send(OP_FRAME, payload)
        connection.receive()
