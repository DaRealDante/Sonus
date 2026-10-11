import functools
import http.server
import os
import subprocess
import tempfile
import threading
import time

import numpy
import pytest

from app.config import ffmpegExe
from tests.broker import localBroker, pump, waitFor  # noqa: F401


class FakeOutputStream:
    """Stands in for the sound card: pulls audio from the engine in real time."""

    def __init__(self, samplerate, channels, dtype, blocksize, latency, callback, finished_callback):
        self.callback = callback
        self.blocksize = blocksize
        self.samplerate = samplerate
        self.channels = channels
        self.running = False

    def start(self):
        self.running = True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        output = numpy.zeros((self.blocksize, self.channels), dtype=numpy.float32)
        nextTime = time.time()
        while self.running:
            self.callback(output, self.blocksize, None, None)
            nextTime += self.blocksize / self.samplerate
            time.sleep(max(0.0, nextTime - time.time()))

    def abort(self):
        self.running = False

    def close(self):
        self.running = False


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            pass


@pytest.fixture(scope="module")
def toneUrl():
    folder = tempfile.mkdtemp()
    subprocess.run([ffmpegExe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=330:duration=90",
                    os.path.join(folder, "tone.mp3")], check=True)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=folder))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/tone.mp3"
    server.shutdown()


@pytest.fixture
def fakeSoundCard(monkeypatch):
    import sounddevice
    monkeypatch.setattr(sounddevice, "OutputStream", FakeOutputStream)


def makeMember(name, toneUrl):
    from app.database import Database
    from app.player import Player
    from app.together import TogetherController
    database = Database(os.path.join(tempfile.mkdtemp(), "library.db"))
    player = Player()
    player.streamResolver = lambda target, useCache=True: {"url": toneUrl, "headers": {}, "duration": 90}
    savedEffects = {}

    def songEffects(song):
        return dict(savedEffects.get(song.get("title"), {"rate": 1.0, "keepPitch": True, "reverbWet": 0.0, "reverbSize": 1.8}))

    notices = []
    controller = TogetherController(player, database, songEffects, notices.append, clientId=name.lower(),
                                    profile={"name": name, "photo": ""})
    player.effectsProvider = lambda song: controller.effectsFor(song) or songEffects(song)
    member = type("Member", (), {})()
    member.database, member.player, member.controller, member.notices, member.savedEffects = database, player, controller, notices, savedEffects
    return member


def shutdown(*members):
    for member in members:
        member.controller.leaveRoom()
        member.player.shutdown()


def test_roomSyncAcrossThreePeople(localBroker, toneUrl, fakeSoundCard):
    alice, bruno, carla = (makeMember(name, toneUrl) for name in ("Alice", "Bruno", "Carla"))
    songIds = [alice.database.addStreamSong(f"https://www.youtube.com/watch?v={videoId}", title, "Band", "", 90, None)
               for videoId, title in (("aaaaaaaaaaa", "Prima"), ("bbbbbbbbbbb", "Seconda"))]
    alice.savedEffects["Prima"] = {"rate": 0.85, "keepPitch": False, "reverbWet": 0.4, "reverbSize": 3.0}
    alice.player.playSongs(alice.database.getSongs(songIds), 0)
    assert waitFor(lambda: alice.player.isPlaying(), 10)
    code = alice.controller.createRoom()
    assert code.startswith("SONUS-")

    bruno.controller.joinRoom(code)
    carla.controller.joinRoom(code)
    assert waitFor(lambda: bruno.player.isPlaying() and carla.player.isPlaying(), 15)
    assert bruno.player.currentSong()["title"] == "Prima"
    assert [song["title"] for song in carla.player.queue] == ["Prima", "Seconda"]
    assert abs(bruno.player.playbackRate() - 0.85) < 0.001
    assert bruno.database.allSongs() == []
    assert waitFor(lambda: len(alice.controller.peers) == 3 and len(bruno.controller.peers) == 3, 10)
    assert any("entrato" in notice for notice in alice.notices)

    pump(2.5)
    positions = [member.player.position() for member in (alice, bruno, carla)]
    assert max(positions) - min(positions) < 700, positions

    carla.player.pause()
    assert waitFor(lambda: not alice.player.isPlaying() and not bruno.player.isPlaying(), 8)
    assert any("pausa" in notice for notice in alice.notices)

    bruno.player.play()
    assert waitFor(lambda: alice.player.isPlaying() and carla.player.isPlaying(), 8)
    bruno.player.seek(40000)
    assert waitFor(lambda: abs(alice.player.position() - bruno.player.position()) < 700
                   and abs(carla.player.position() - bruno.player.position()) < 700 and alice.player.position() > 35000, 10)

    effects = {"rate": 1.25, "keepPitch": True, "reverbWet": 0.0, "reverbSize": 1.8}
    alice.controller.setLocalEffects(effects)
    alice.player.setPlaybackRate(1.25, True)
    assert waitFor(lambda: abs(bruno.player.playbackRate() - 1.25) < 0.001 and abs(carla.player.playbackRate() - 1.25) < 0.001, 8)

    carla.player.next()
    assert waitFor(lambda: alice.player.currentSong()["title"] == "Seconda" and bruno.player.currentSong()["title"] == "Seconda", 10)
    pump(1.5)
    # Effects are general: the room keeps them when the song changes
    assert abs(alice.player.playbackRate() - 1.25) < 0.001 and abs(bruno.player.playbackRate() - 1.25) < 0.001

    carla.controller.leaveRoom()
    assert waitFor(lambda: "carla" not in alice.controller.peers, 8)
    shutdown(alice, bruno, carla)


def test_simultaneousCommandsConverge(localBroker, toneUrl, fakeSoundCard):
    alice, bruno = makeMember("Alice", toneUrl), makeMember("Bruno", toneUrl)
    songIds = [alice.database.addStreamSong(f"https://youtu.be/{index:011d}", f"Brano {index}", "X", "", 90, None) for index in range(3)]
    alice.player.playSongs(alice.database.getSongs(songIds), 0)
    code = alice.controller.createRoom()
    bruno.controller.joinRoom(code)
    assert waitFor(lambda: bruno.player.isPlaying(), 15)
    alice.player.jumpTo(1)
    bruno.player.jumpTo(2)
    assert waitFor(lambda: alice.player.currentSong()["title"] == bruno.player.currentSong()["title"]
                   and not alice.player.loading and not bruno.player.loading, 12)
    pump(2)
    assert alice.player.currentSong()["title"] == bruno.player.currentSong()["title"]
    assert alice.controller.state["version"] == bruno.controller.state["version"]
    shutdown(alice, bruno)


def test_streamFailureInRoomDoesNotSkipOrPauseOthers(localBroker, toneUrl, fakeSoundCard):
    alice, bruno = makeMember("Alice", toneUrl), makeMember("Bruno", toneUrl)
    songIds = [alice.database.addStreamSong(f"https://youtu.be/{index:011d}", f"Pezzo {index}", "X", "", 90, None) for index in range(2)]
    alice.player.playSongs(alice.database.getSongs(songIds), 0)
    code = alice.controller.createRoom()

    def brokenResolver(target, useCache=True):
        raise RuntimeError("bloccato")

    bruno.player.streamResolver = brokenResolver
    bruno.controller.joinRoom(code)
    assert waitFor(lambda: bruno.player.currentSong() is not None and not bruno.player.loading, 10)
    bruno.player.queueChanged.emit()
    pump(3)
    assert alice.player.currentSong()["title"] == "Pezzo 0"
    assert alice.player.isPlaying()
    assert bruno.player.currentIndex == 0
    shutdown(alice, bruno)


def test_personalDelayKeepsMeBehind(localBroker, toneUrl, fakeSoundCard):
    alice, bruno = makeMember("Alice", toneUrl), makeMember("Bruno", toneUrl)
    bruno.controller.delayOverride = 0
    songIds = [alice.database.addStreamSong("https://youtu.be/ddddddddddd", "Ritardata", "X", "", 90, None)]
    alice.player.playSongs(alice.database.getSongs(songIds), 0)
    code = alice.controller.createRoom()
    bruno.controller.joinRoom(code)
    assert waitFor(lambda: bruno.player.isPlaying(), 15)
    pump(1.5)
    bruno.controller.setDelay(1500)
    assert waitFor(lambda: 1000 < alice.player.position() - bruno.player.position() < 2000, 8)
    alice.player.seek(30000)
    assert waitFor(lambda: 27500 < bruno.player.position() < 29500 and alice.player.position() >= 30000, 8)
    bruno.player.pause()
    assert waitFor(lambda: not alice.player.isPlaying(), 8)
    assert abs(alice.controller.state["positionMs"] - (bruno.player.position() + 1500)) < 300
    shutdown(alice, bruno)


def test_bassBoostStaysPersonalInRoom(localBroker, toneUrl, fakeSoundCard):
    alice, bruno = makeMember("Alice", toneUrl), makeMember("Bruno", toneUrl)
    alice.savedEffects["Bassi"] = {"rate": 1.1, "keepPitch": True, "reverbWet": 0.0, "reverbSize": 1.8, "bassBoost": 0.6}
    bruno.savedEffects["Bassi"] = {"rate": 1.0, "keepPitch": True, "reverbWet": 0.0, "reverbSize": 1.8, "bassBoost": 0.2}
    songIds = [alice.database.addStreamSong("https://youtu.be/bbbbbbbbbbb", "Bassi", "X", "", 90, None)]
    alice.player.playSongs(alice.database.getSongs(songIds), 0)
    code = alice.controller.createRoom()
    bruno.controller.joinRoom(code)
    assert waitFor(lambda: bruno.player.isPlaying() and abs(bruno.player.playbackRate() - 1.1) < 0.001, 15)
    assert abs(bruno.player.mediaPlayer.bassBoost - 0.2) < 0.001
    alice.controller.setLocalEffects({"rate": 1.1, "keepPitch": True, "reverbWet": 0.3, "reverbSize": 1.8, "bassBoost": 0.9})
    assert waitFor(lambda: abs(bruno.player.mediaPlayer.reverbWet - 0.3) < 0.001, 8)
    assert abs(bruno.player.mediaPlayer.bassBoost - 0.2) < 0.001
    assert "bassBoost" not in alice.controller.state["effects"]
    shutdown(alice, bruno)


def test_chooserStartsTheSongWhenReadyInsteadOfSkippingTheLoad(localBroker, toneUrl, fakeSoundCard):
    """The song I choose takes a while to load: when it is ready it starts from the beginning for the room."""
    alice, bruno = makeMember("Alice", toneUrl), makeMember("Bruno", toneUrl)
    songIds = [alice.database.addStreamSong(f"https://youtu.be/{index:011d}", f"Lenta {index}", "X", "", 90, None) for index in range(2)]
    alice.player.playSongs(alice.database.getSongs(songIds), 0)
    code = alice.controller.createRoom()
    bruno.controller.joinRoom(code)
    assert waitFor(lambda: bruno.player.isPlaying(), 15)

    def slowResolver(target, useCache=True):
        time.sleep(3)
        return {"url": toneUrl, "headers": {}, "duration": 90}

    alice.player.streamResolver = slowResolver
    alice.player.next()
    assert waitFor(lambda: alice.player.currentSong()["title"] == "Lenta 1" and not alice.player.loading and alice.player.isPlaying(), 10)
    assert alice.player.position() < 1500
    assert waitFor(lambda: bruno.player.currentSong()["title"] == "Lenta 1" and bruno.player.isPlaying(), 10)
    pump(2)
    assert abs(alice.player.position() - bruno.player.position()) < 700
    assert alice.player.position() < 4000
    assert not any("pausa" in notice for notice in alice.notices + bruno.notices)
    shutdown(alice, bruno)


def test_friendStillLoadingTheSameSongKeepsLoading(localBroker, toneUrl, fakeSoundCard):
    alice, bruno = makeMember("Alice", toneUrl), makeMember("Bruno", toneUrl)
    songIds = [alice.database.addStreamSong("https://youtu.be/ggggggggggg", "Attesa", "X", "", 90, None)]
    alice.player.playSongs(alice.database.getSongs(songIds), 0)
    code = alice.controller.createRoom()
    calls = []

    def slowResolver(target, useCache=True):
        calls.append(target)
        time.sleep(3)
        return {"url": toneUrl, "headers": {}, "duration": 90}

    bruno.player.streamResolver = slowResolver
    bruno.controller.joinRoom(code)
    assert waitFor(lambda: bruno.player.loading, 10)
    pump(0.5)
    alice.player.seek(20000)
    assert waitFor(lambda: bruno.player.isPlaying(), 10)
    assert len(calls) == 1
    assert waitFor(lambda: abs(alice.player.position() - bruno.player.position()) < 700 and bruno.player.position() > 20000, 8)
    shutdown(alice, bruno)


def test_friendsSongGetsItsCover(localBroker, toneUrl, fakeSoundCard, monkeypatch, tmp_path):
    import app.downloader as downloader
    coverPath = str(tmp_path / "cover.jpg")
    open(coverPath, "wb").write(b"jpg")
    asked = []
    monkeypatch.setattr(downloader, "youtubeCover", lambda videoId: asked.append(videoId) or coverPath)
    alice, bruno = makeMember("Alice", toneUrl), makeMember("Bruno", toneUrl)
    songIds = [alice.database.addStreamSong("https://www.youtube.com/watch?v=ccccccccccc", "Copertina", "X", "", 90, None)]
    alice.player.playSongs(alice.database.getSongs(songIds), 0)
    code = alice.controller.createRoom()
    bruno.controller.joinRoom(code)
    assert waitFor(lambda: (bruno.player.currentSong() or {}).get("cover") == coverPath, 15)
    assert asked == ["ccccccccccc"]
    assert bruno.database.getSong(bruno.player.currentSong()["id"])["cover"] == coverPath
    shutdown(alice, bruno)


def test_roomSongRecoversWhenStreamingFailsAtFirst(localBroker, toneUrl, fakeSoundCard, monkeypatch):
    import app.together as together
    monkeypatch.setattr(together, "RECOVER_FIRST_DELAY_SECONDS", 0.5)
    monkeypatch.setattr(together, "RECOVER_RETRY_SECONDS", 1)
    alice, bruno = makeMember("Alice", toneUrl), makeMember("Bruno", toneUrl)
    songIds = [alice.database.addStreamSong("https://youtu.be/eeeeeeeeeee", "Ostinata", "X", "", 90, None)]
    alice.player.playSongs(alice.database.getSongs(songIds), 0)
    code = alice.controller.createRoom()
    failures = [0]

    def flakyResolver(target, useCache=True):
        if failures[0] < 2:
            failures[0] += 1
            raise RuntimeError("rete instabile")
        return {"url": toneUrl, "headers": {}, "duration": 90}

    bruno.player.streamResolver = flakyResolver
    bruno.player.streamFallback = lambda target: (_ for _ in ()).throw(RuntimeError("niente download"))
    bruno.controller.joinRoom(code)
    assert waitFor(lambda: bruno.player.isPlaying(), 20)
    assert waitFor(lambda: abs(alice.player.position() - bruno.player.position()) < 700, 8)
    assert waitFor(lambda: not bruno.player.mediaPlayer.isSeekPending(), 8)
    shutdown(alice, bruno)




def test_delayDoesNotPauseTheRoomAtSongStart(localBroker, toneUrl, fakeSoundCard):
    """Bruno has a personal delay: at the start of a song he waits a moment, but must not pause everybody."""
    alice, bruno = makeMember("Alice", toneUrl), makeMember("Bruno", toneUrl)
    bruno.controller.delayOverride = 2500
    songIds = [alice.database.addStreamSong(f"https://youtu.be/{index:011d}", f"Inizio {index}", "X", "", 90, None) for index in range(2)]
    alice.player.playSongs(alice.database.getSongs(songIds), 0)
    code = alice.controller.createRoom()
    bruno.controller.joinRoom(code)
    assert waitFor(lambda: bruno.player.isPlaying(), 15)
    alice.player.next()
    pump(4)
    assert alice.player.isPlaying()
    assert alice.controller.state["playing"]
    assert not any("pausa" in notice for notice in alice.notices)
    assert waitFor(lambda: bruno.player.isPlaying() and bruno.player.currentSong()["title"] == "Inizio 1", 8)
    shutdown(alice, bruno)


def test_pauseNobodyClickedIsNotSentToTheRoom(localBroker, toneUrl, fakeSoundCard):
    """A pause caused by the app (loading, error...) and not by a click must not pause everybody."""
    alice, bruno = makeMember("Alice", toneUrl), makeMember("Bruno", toneUrl)
    songIds = [alice.database.addStreamSong("https://youtu.be/fffffffffff", "Sola", "X", "", 90, None)]
    alice.player.playSongs(alice.database.getSongs(songIds), 0)
    code = alice.controller.createRoom()
    bruno.controller.joinRoom(code)
    assert waitFor(lambda: bruno.player.isPlaying(), 15)
    pump(3)
    bruno.player.mediaPlayer.pause()
    pump(3)
    assert alice.player.isPlaying() and alice.controller.state["playing"]
    assert not any("pausa" in notice for notice in alice.notices)
    assert waitFor(lambda: bruno.player.isPlaying(), 5)
    bruno.player.pause()
    assert waitFor(lambda: not alice.player.isPlaying(), 8)
    shutdown(alice, bruno)
