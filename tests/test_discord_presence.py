import json
import os
import socket
import struct
import tempfile
import threading
import time

from app.discord_presence import DiscordPresence, buildActivity


def fakeDiscord(path, frames):
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(1)

    def serve():
        connection, _ = server.accept()
        while True:
            header = connection.recv(8)
            if len(header) < 8:
                return
            opcode, length = struct.unpack("<II", header)
            body = b""
            while len(body) < length:
                body += connection.recv(length - len(body))
            payload = json.loads(body)
            frames.append((opcode, payload))
            reply = json.dumps({"cmd": payload.get("cmd", "DISPATCH"), "evt": "READY" if opcode == 0 else None}).encode()
            connection.sendall(struct.pack("<II", 1, len(reply)) + reply)

    threading.Thread(target=serve, daemon=True).start()
    return server


def test_activityShowsSongProgressAndPause():
    song = {"title": "Tango", "artist": "Tananai", "album": "Rave", "url": "https://youtu.be/abcdefghijk"}
    activity = buildActivity(song, 30000, 180000, True, 1.0, nowSeconds=1000)
    assert activity["type"] == 2 and activity["details"] == "Tango" and activity["state"] == "Tananai"
    assert activity["timestamps"] == {"start": 970000, "end": 1150000}
    assert activity["assets"]["large_image"] == "https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg"
    paused = buildActivity(song, 30000, 180000, False)
    assert "timestamps" not in paused and paused["state"].startswith("In pausa")
    slowed = buildActivity(song, 30000, 180000, True, 0.5, nowSeconds=1000)
    assert slowed["timestamps"]["end"] - slowed["timestamps"]["start"] == 360000
    assert buildActivity(None, 0, 0, False) is None


def test_presenceTalksToDiscordPipe(monkeypatch):
    folder = tempfile.mkdtemp()
    monkeypatch.setenv("XDG_RUNTIME_DIR", folder)
    frames = []
    server = fakeDiscord(os.path.join(folder, "discord-ipc-0"), frames)
    presence = DiscordPresence("123456789")
    assert presence.start()
    presence.update(buildActivity({"title": "A", "artist": "B"}, 0, 1000, True))
    deadline = time.time() + 5
    while len(frames) < 2 and time.time() < deadline:
        time.sleep(0.05)
    assert frames[0] == (0, {"v": 1, "client_id": "123456789"})
    assert frames[1][1]["cmd"] == "SET_ACTIVITY" and frames[1][1]["args"]["activity"]["details"] == "A "[:2].strip().ljust(2)
    presence.stop()
    server.close()


def test_noClientIdDoesNothing():
    assert DiscordPresence("").start() is False
