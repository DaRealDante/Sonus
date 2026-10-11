import hashlib
import os
import random
import time
import uuid

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtMultimedia import QMediaPlayer

from .config import TEMP_DIR, settings
from .database import isStreamPath
from .room_files import RoomFileCache, encryptFile, uploadTemporary, validRoomFile
from .workers import runInBackground
from .session_link import Link, makeCode
from .together_sync import ClockSync, expectedPosition, isNewer, nowMs, trackFromSong

DRIFT_TOLERANCE_MS = 700
ROOM_FILE_WAIT_SECONDS = 20
FILE_ID_CACHE_SECONDS = 120
REUPLOAD_AFTER_SECONDS = 50 * 60
MAX_SHARED_QUEUE = 400
STATE_WAIT_MS = 4000
RECOVER_FIRST_DELAY_SECONDS = 2
RECOVER_RETRY_SECONDS = 15

_ANIMALS = ["Volpe", "Lupo", "Gufo", "Panda", "Tigre", "Delfino", "Falco", "Koala", "Lince", "Orso", "Puma", "Corvo",
            "Fenice", "Drago", "Gatto", "Riccio", "Squalo", "Cobra", "Lemure", "Bisonte"]
_COLORS = ["Viola", "Blu", "Rosso", "Verde", "Nero", "Dorato", "Argento", "Cremisi", "Celeste", "Arancio", "Smeraldo", "Neon"]


def randomName():
    return f"{random.choice(_ANIMALS)} {random.choice(_COLORS)} {random.randint(10, 99)}"


def ensureProfile():
    changed = False
    if not settings.get("clientId"):
        settings.set("clientId", uuid.uuid4().hex[:12])
        changed = True
    if not (settings.get("profileName") or "").strip():
        settings.set("profileName", randomName())
        changed = True
    if changed:
        settings.save()


def _effectsEqual(first, second):
    if not first or not second:
        return first == second
    return (abs(float(first["rate"]) - float(second["rate"])) < 0.001 and bool(first["keepPitch"]) == bool(second["keepPitch"])
            and abs(float(first["reverbWet"]) - float(second["reverbWet"])) < 0.001
            and abs(float(first["reverbSize"]) - float(second["reverbSize"])) < 0.001
            and abs(float(first.get("bassBoost", 0.0)) - float(second.get("bassBoost", 0.0))) < 0.001)


class TogetherController(QObject):
    """Ascolta insieme: everybody in the room hears the same song at the same point; anybody can control it."""

    roomChanged = Signal()
    peersChanged = Signal()
    connectionChanged = Signal(bool)
    effectsChanged = Signal(object)

    def __init__(self, player, database, songEffects, notify=None, clientId=None, profile=None, parent=None):
        super().__init__(parent)
        self.player = player
        self.database = database
        self.songEffects = songEffects
        self.notify = notify or (lambda text: None)
        self.clientId = clientId
        self.profileOverride = profile
        self.delayOverride = None
        self.link = Link(self)
        self.link.received.connect(self._onReceived)
        self.link.connectedChanged.connect(self.connectionChanged)
        self.code = None
        self.state = None
        self.version = 0
        self.peers = {}
        self.clock = ClockSync()
        self.applying = 0
        self.waitingForState = False
        self.roomEffects = None
        self.pendingSeek = False
        self.joinedAt = 0
        self.recovery = None

        self.publishTimer = QTimer(self)
        self.publishTimer.setSingleShot(True)
        self.publishTimer.setInterval(80)
        self.publishTimer.timeout.connect(self._publishIfChanged)
        self.driftTimer = QTimer(self)
        self.driftTimer.setInterval(1000)
        self.driftTimer.timeout.connect(self._checkDrift)
        self.pingTimer = QTimer(self)
        self.pingTimer.setInterval(20000)
        self.pingTimer.timeout.connect(self._pingAll)
        self.waitTimer = QTimer(self)
        self.waitTimer.setSingleShot(True)
        self.waitTimer.timeout.connect(self._onStateWaitTimeout)
        self.fileInfos = {}
        self.uploads = {}
        self.failedUploads = {}
        self.fileIdCache = {}
        self.roomFilePaths = {}
        self.currentRoomFile = None
        self.roomCache = RoomFileCache(os.path.join(TEMP_DIR, "room_files"))
        self.roomCache.cleanup()
        self.fileTimer = QTimer(self)
        self.fileTimer.setInterval(5 * 60 * 1000)
        self.fileTimer.timeout.connect(self._fileMaintenance)
        self.fileTimer.start()
        player.roomFileResolver = self.resolveRoomFile
        from PySide6.QtCore import QThreadPool
        self.uploadPool = QThreadPool(self)
        self.uploadPool.setMaxThreadCount(2)

        player.songChanged.connect(lambda song: self._onLocalChange())
        player.playingChanged.connect(lambda playing: self._onLocalChange())
        player.queueChanged.connect(self._onLocalChange)
        player.songLoaded.connect(lambda song: self._onSongLoaded())
        player.seeked.connect(self._onLocalSeek)

    # ---------- identity ----------
    def myId(self):
        if self.clientId:
            return self.clientId
        ensureProfile()
        return settings.get("clientId")

    def profile(self):
        if self.profileOverride:
            return dict(self.profileOverride)
        ensureProfile()
        return {"name": settings.get("profileName"), "photo": settings.get("profilePhoto") or ""}

    # ---------- room ----------
    def inRoom(self):
        return self.code is not None

    def createRoom(self):
        self._enter(makeCode(), waitForState=False)
        self._publishState(seek=True)
        return self.code

    def joinRoom(self, code):
        if code == self.code:
            return
        self._enter(code, waitForState=True)

    def _enter(self, code, waitForState):
        if self.code:
            self.leaveRoom()
        self.code = code
        self.state = None
        self.version = 0
        self.peers = {}
        self.roomEffects = None
        self.joinedAt = nowMs()
        self.waitingForState = waitForState
        self.player.skipOnError = False
        self.link.watch(code, ["#"])  # one subscription: the server allows 10 per connection
        self.link.setWill(code, f"presence/{self.myId()}")
        self._publishPresence()
        if self.link.running:
            self.link.restart()
        else:
            self.link.start()
        if waitForState:
            self.waitTimer.start(STATE_WAIT_MS)
        self.driftTimer.start()
        self.pingTimer.start()
        self.roomChanged.emit()
        self.peersChanged.emit()

    def leaveRoom(self):
        if not self.code:
            return
        code = self.code
        self.link.clearRetained(code, f"presence/{self.myId()}")
        self.link.unwatch(code)
        self.link.setWill(None, None)
        self.link.stop()
        self.code = None
        self.state = None
        self.peers = {}
        self.fileInfos = {}
        self.uploads = {}
        self.waitingForState = False
        self.player.skipOnError = True
        self.driftTimer.stop()
        self.pingTimer.stop()
        self.waitTimer.stop()
        self.publishTimer.stop()
        hadRoomEffects = self.roomEffects is not None
        self.roomEffects = None
        if hadRoomEffects and self.player.currentSong():
            self._applyEffects(self.songEffects(self.player.currentSong()))
        self.roomChanged.emit()
        self.peersChanged.emit()

    def updateProfile(self):
        if self.code:
            self._publishPresence()

    def _publishPresence(self):
        profile = self.profile()
        self.link.publish(self.code, f"presence/{self.myId()}",
                          {"id": self.myId(), "name": profile["name"], "photo": profile.get("photo") or "", "joinedAt": self.joinedAt},
                          retain=True)

    def otherPeers(self):
        return {peerId: peer for peerId, peer in self.peers.items() if peerId != self.myId()}

    # ---------- effects ----------
    def effectsFor(self, song):
        """Effects the player should use for `song` while in a room, or None outside rooms."""
        if not self.code:
            return None
        if self.roomEffects and self.state and self._currentTrackKey(self.state) == self._keyOf(song):
            return dict(self.roomEffects)
        return None

    def setLocalEffects(self, effects):
        self.roomEffects = dict(effects)
        self._publishState(seek=False)

    def _applyEffects(self, effects):
        if not effects:
            return
        self.player.setPlaybackRate(effects["rate"], effects["keepPitch"])
        self.player.setReverb(effects["reverbWet"], effects["reverbSize"])
        self.player.setBassBoost(effects.get("bassBoost", 0.0))
        self.effectsChanged.emit(dict(effects))

    # ---------- local changes ----------
    def _onLocalChange(self):
        if self.code and not self.applying and not self.waitingForState:
            self.publishTimer.start()

    def _onLocalSeek(self, positionMs):
        if self.code and not self.applying and not self.waitingForState:
            self.pendingSeek = True
            self.publishTimer.start()

    def _onSongLoaded(self):
        if self.code and not self.applying:
            QTimer.singleShot(0, self._checkDrift)
            self._onLocalChange()

    def _localSnapshot(self):
        queue = self.player.queue
        start = max(0, self.player.currentIndex - 100)
        window = queue[start:start + MAX_SHARED_QUEUE]
        tracks = [self._trackOf(song) for song in window]
        for song, track in zip(window, tracks):
            if track.get("query") and not track.get("url") and not song.get("_roomTrack"):
                # Already found on YouTube once: friends get the video directly and skip the search
                from .downloader import knownVideoUrl
                from .together_sync import youtubeId
                knownUrl = knownVideoUrl(track["query"])
                if youtubeId(knownUrl):
                    track["url"] = knownUrl
            fileId = self._localFileId(song)
            if fileId and not track.get("url"):
                track["fileId"] = fileId
                track["fileExt"] = os.path.splitext(song["path"])[1].lower()
        index = self.player.currentIndex - start if self.player.currentIndex >= 0 else -1
        playing = self.player.isPlaying() or (self.player.loading and self.player.loadAutoplay)
        current = self.player.currentSong()
        if not playing and current is not None and self.state and self._currentTrackKey(self.state) == self._keyOf(current):
            # Not playing only because of the app, not because of me: the song could not load, it is still
            # loading, or my personal delay makes me wait a moment. Never tell the others "pause" for that.
            couldNotLoad = not self.player.loading and (self.player.mediaPlayer.source().isEmpty()
                                                         or self.player.mediaPlayer.mediaStatus() == QMediaPlayer.InvalidMedia)
            waitingForMyDelay = bool(self.state.get("playing")) and self._targetPosition(self.state) < 0
            if couldNotLoad or waitingForMyDelay:
                playing = bool(self.state.get("playing"))
        return tracks, index, playing

    def _publishIfChanged(self):
        if not self.code or self.waitingForState:
            return
        tracks, index, playing = self._localSnapshot()
        seek = self.pendingSeek
        self.pendingSeek = False
        if self.state and not seek:
            sameQueue = [track["key"] for track in tracks] == [track["key"] for track in self.state.get("queue") or []]
            if sameQueue and index == self.state.get("index") and playing == bool(self.state.get("playing")) \
                    and _effectsEqual(self.roomEffects, self.state.get("effects")):
                return
        self._publishState(seek=seek, snapshot=(tracks, index, playing))

    def _publishState(self, seek, snapshot=None):
        if not self.code:
            return
        tracks, index, playing = snapshot or self._localSnapshot()
        currentKey = tracks[index]["key"] if 0 <= index < len(tracks) else None
        current = self.player.currentSong()
        if current is not None and (self.roomEffects is None or self._currentTrackKey(self.state) != currentKey):
            self.roomEffects = self.songEffects(current)
        if self.player.loading:
            positionMs = 0
            if self.state and self._currentTrackKey(self.state) == currentKey:
                positionMs = expectedPosition(self.state, nowMs(), self.clock.offset(self.state.get("by")))
        else:
            positionMs = self.player.position() + self.delayMs()
        self.version += 1
        self.state = {
            "queue": tracks, "index": index, "positionMs": int(positionMs), "playing": bool(playing), "at": nowMs(),
            "effects": dict(self.roomEffects) if self.roomEffects else None, "version": self.version, "by": self.myId(),
        }
        self.link.publish(self.code, "state", self.state, retain=True)
        current = tracks[index]["title"] if 0 <= index < len(tracks) else None
        print(f"[Stanza] io: {current!r} {'play' if playing else 'pausa'} a {int(positionMs) // 1000}s (v{self.version})")
        self._ensureUploads()

    # ---------- remote changes ----------
    def _onReceived(self, code, subtopic, payload):
        if code != self.code:
            return
        if subtopic == "state":
            self._onRemoteState(payload)
        elif subtopic.startswith("presence/"):
            self._onPresence(subtopic[len("presence/"):], payload)
        elif subtopic == "msg" and isinstance(payload, dict):
            self._onMessage(payload)
        elif subtopic.startswith("files/") and isinstance(payload, dict):
            if payload.get("failed") or (validRoomFile(payload)):
                self.fileInfos[subtopic[len("files/"):]] = payload

    def _onRemoteState(self, state):
        if not isinstance(state, dict) or not isinstance(state.get("queue"), list):
            return
        self.version = max(self.version, int(state.get("version") or 0))
        if state.get("by") == self.myId() and not self.waitingForState:
            return
        if not self.waitingForState and not isNewer(state, self.state):
            return
        previous = self.state
        queue = state.get("queue") or []
        index = state.get("index", -1)
        title = queue[index].get("title") if 0 <= index < len(queue) else None
        print(f"[Stanza] da {state.get('by')}: {title!r} {'play' if state.get('playing') else 'pausa'} "
              f"a {int(state.get('positionMs') or 0) // 1000}s (v{state.get('version')})")
        self.waitingForState = False
        self.waitTimer.stop()
        self.state = state
        self.publishTimer.stop()
        self.pendingSeek = False
        self._applyState(state)
        self._announce(previous, state)

    def _announce(self, previous, state):
        who = (self.peers.get(state.get("by")) or {}).get("name") or "Qualcuno"
        if state.get("by") == self.myId():
            return
        queue = state.get("queue") or []
        index = state.get("index", -1)
        track = queue[index] if 0 <= index < len(queue) else None
        if previous is None:
            return
        if track and self._currentTrackKey(previous) != track["key"]:
            self.notify(f"{who} ha messo \"{track['title']}\"")
        elif bool(previous.get("playing")) != bool(state.get("playing")):
            self.notify(f"{who} ha {'ripreso' if state.get('playing') else 'messo in pausa'}")

    def _applyState(self, state):
        self.applying += 1
        try:
            queue = state.get("queue") or []
            index = int(state.get("index", -1))
            effects = state.get("effects")
            if effects:
                self.roomEffects = dict(effects)
            if not queue or not (0 <= index < len(queue)):
                if self.player.isPlaying() and not state.get("playing"):
                    self.player.pause()
                return
            current = self.player.currentSong()
            targetKey = queue[index]["key"]
            sameSong = current is not None and self._keyOf(current) == targetKey and not self.player.loading
            songs = []
            for position, track in enumerate(queue):
                if position == index and sameSong:
                    songs.append(current)
                else:
                    songs.append(self._songForTrack(track))
            localKeys = [self._keyOf(song) for song in self.player.queue]
            if localKeys != [track["key"] for track in queue] or self.player.currentIndex != index or not sameSong:
                self.player.queue = songs
                self.player.originalQueue = list(songs)
                self.player.currentIndex = index
                self.player.queueChanged.emit()
            expected = self._targetPosition(state)
            if not sameSong:
                self.player._loadCurrent(autoplay=bool(state.get("playing")) and expected >= 0, startPosition=max(0, expected))
                return
            if effects and not _effectsEqual(effects, {"rate": self.player.playbackRate(), "keepPitch": self.player.mediaPlayer.keepPitch(),
                                                       "reverbWet": self.player.mediaPlayer.reverbWet,
                                                       "reverbSize": self.player.mediaPlayer.reverbSize,
                                                       "bassBoost": self.player.mediaPlayer.bassBoost}):
                self._applyEffects(effects)
            if self._couldNotLoad():
                self._recoverPlayback(state, expected)
                return
            if expected < 0:
                if self.player.isPlaying():
                    self.player.mediaPlayer.pause()
                self.player.mediaPlayer.setPosition(0)
                return
            if abs(self.player.position() - expected) > DRIFT_TOLERANCE_MS:
                self.player.mediaPlayer.setPosition(expected)
            if state.get("playing") and not self.player.isPlaying():
                self.player.mediaPlayer.play()
            elif not state.get("playing") and self.player.isPlaying():
                self.player.mediaPlayer.pause()
        finally:
            self.applying -= 1

    def _songForTrack(self, track):
        """The same song in my library (YouTube link, then title + artist), otherwise a hidden streaming copy."""
        song = None
        if track.get("url"):
            song = self.database.findSongByUrl(track["url"])
        if song is None and track.get("title"):
            song = self.database.findSong(track["title"], track.get("artist") or "")
        if song is None and track.get("fileId") and not track.get("url"):
            query = track.get("query") or f"ytsearch1:{track.get('artist') or ''} - {track.get('title') or ''} audio"
            songId = self.database.addStreamSong(f"roomfile:{track['fileId']}|{query}", track.get("title") or "Senza titolo",
                                                 track.get("artist") or "", track.get("album") or "", track.get("duration") or 0,
                                                 None, hidden=True)
            song = self.database.getSong(songId)
        if song is None:
            target = track.get("url") or track.get("query") or \
                f"ytsearch1:{track.get('artist') or ''} - {track.get('title') or ''} audio".replace("ytsearch1: - ", "ytsearch1:")
            songId = self.database.addStreamSong(target, track.get("title") or "Senza titolo", track.get("artist") or "",
                                                 track.get("album") or "", track.get("duration") or 0, None, hidden=True)
            song = self.database.getSong(songId)
        mapped = dict(song)
        mapped["_roomTrack"] = dict(track)
        return mapped

    def _checkDrift(self):
        state = self.state
        if not self.code or not state or self.applying or self.player.loading or self.player.activeLoop or self.publishTimer.isActive():
            return
        current = self.player.currentSong()
        if current is None or self._keyOf(current) != self._currentTrackKey(state):
            return
        expected = self._targetPosition(state)
        if self._couldNotLoad():
            self._recoverPlayback(state, expected)
            return
        self.recovery = None
        self.applying += 1
        try:
            if expected < 0:
                if self.player.isPlaying():
                    self.player.mediaPlayer.pause()
                if self.player.position() > DRIFT_TOLERANCE_MS:
                    self.player.mediaPlayer.setPosition(0)
                return
            if state.get("playing") and not self.player.isPlaying():
                duration = self.player.duration()
                if not duration or expected < duration - 1500:
                    self.player.mediaPlayer.play()
            if abs(self.player.position() - expected) > DRIFT_TOLERANCE_MS and (state.get("playing") or not self.player.isPlaying()):
                self.player.mediaPlayer.setPosition(expected)
        finally:
            self.applying -= 1

    def _couldNotLoad(self):
        """The room's song is selected but nothing is loaded (streaming failed): moving the position would only
        move the bar in silence."""
        media = self.player.mediaPlayer
        return not self.player.loading and (media.source().isEmpty() or media.mediaStatus() == QMediaPlayer.InvalidMedia)

    def _recoverPlayback(self, state, expected):
        """Retries the room's song by itself: first a fresh link, then a temporary download, then every few seconds."""
        current = self.player.currentSong()
        if current is None:
            return
        key = self._keyOf(current)
        now = time.monotonic()
        if self.recovery is None or self.recovery["key"] != key:
            self.recovery = {"key": key, "attempts": 0, "nextAt": now + RECOVER_FIRST_DELAY_SECONDS}
            return
        if now < self.recovery["nextAt"]:
            return
        attempts = self.recovery["attempts"] = self.recovery["attempts"] + 1
        self.recovery["nextAt"] = now + RECOVER_RETRY_SECONDS
        if attempts == 2:
            self.notify(f"Non riesco a riprodurre \"{current.get('title') or 'la canzone'}\": riprovo da solo")
        print(f"[Stanza] riprovo a caricare {current.get('title')!r} (tentativo {attempts})")
        startPosition = max(0, expected)
        autoplay = bool(state.get("playing")) and expected >= 0
        path = str(current.get("path") or "")
        self.applying += 1
        try:
            if isStreamPath(path) and attempts % 2 == 0 and "roomfile:" not in path:
                self.player._loadFallback(current, startPosition)
            else:
                if isStreamPath(path):
                    from .player import _forgetStream
                    from .database import streamTarget
                    _forgetStream(streamTarget(path))
                self.player._loadCurrent(autoplay=autoplay, startPosition=startPosition)
        finally:
            self.applying -= 1

    def _onStateWaitTimeout(self):
        if self.waitingForState:
            self.waitingForState = False
            self._publishState(seek=True)

    # ---------- presence and clocks ----------
    def _onPresence(self, peerId, payload):
        if payload is None:
            peer = self.peers.pop(peerId, None)
            self.clock.forget(peerId)
            if peer and peerId != self.myId():
                self.notify(f"{peer.get('name') or 'Qualcuno'} è uscito dalla stanza")
            self.peersChanged.emit()
            return
        if not isinstance(payload, dict):
            return
        isNew = peerId not in self.peers
        self.peers[peerId] = {"id": peerId, "name": str(payload.get("name") or "Ospite")[:40], "photo": payload.get("photo") or "",
                              "joinedAt": payload.get("joinedAt") or 0}
        if isNew and peerId != self.myId():
            if (payload.get("joinedAt") or 0) > self.joinedAt:
                self.notify(f"{self.peers[peerId]['name']} è entrato nella stanza")
            self._ping(peerId)
            QTimer.singleShot(500, self._ensureUploads)
        self.peersChanged.emit()

    def _ping(self, peerId):
        if self.code:
            self.link.publish(self.code, "msg", {"type": "ping", "from": self.myId(), "to": peerId, "t0": nowMs()})

    def _pingAll(self):
        for peerId in self.otherPeers():
            self._ping(peerId)

    def _onMessage(self, message):
        if message.get("to") != self.myId():
            return
        if message.get("type") == "ping":
            self.link.publish(self.code, "msg", {"type": "pong", "from": self.myId(), "to": message.get("from"),
                                                 "t0": message.get("t0"), "t1": nowMs()})
        elif message.get("type") == "pong":
            try:
                self.clock.onPong(message.get("from"), int(message["t0"]), int(message["t1"]), nowMs())
            except (KeyError, TypeError, ValueError):
                pass

    # ---------- personal files (mp3 not on YouTube) ----------
    def _localFileId(self, song):
        path = str(song.get("path") or "")
        if not path or isStreamPath(path) or (song.get("url") and song.get("source") != "cut"):
            return None
        cached = self.fileIdCache.get(path)
        if cached and time.time() - cached[0] < FILE_ID_CACHE_SECONDS:
            return cached[1]
        try:
            stats = os.stat(path)
            fileId = hashlib.sha1(f"{os.path.abspath(path)}|{stats.st_size}|{int(stats.st_mtime)}".encode("utf-8")).hexdigest()[:24]
        except OSError:
            fileId = None
        self.fileIdCache[path] = (time.time(), fileId)
        return fileId

    def _ensureUploads(self):
        """Uploads (encrypted, 1 hour) the current and the next song if they are your own files and someone else is here."""
        if not self.code or not self.otherPeers():
            return
        queue = self.player.queue
        index = self.player.currentIndex
        for song in queue[max(0, index):max(0, index) + 2]:
            fileId = self._localFileId(song)
            if not fileId:
                continue
            if time.time() - self.failedUploads.get(fileId, 0) < 600:
                continue
            upload = self.uploads.get(fileId)
            if upload and (upload["state"] == "uploading" or time.time() - upload["at"] < REUPLOAD_AFTER_SECONDS):
                continue
            self.uploads[fileId] = {"state": "uploading", "at": time.time()}
            code = self.code
            runInBackground(self._uploadFile, song["path"], fileId, pool=self.uploadPool,
                            onFinished=lambda info, code=code: self._onUploaded(code, info),
                            onError=lambda message, fileId=fileId, code=code: self._onUploadFailed(code, fileId, message))

    @staticmethod
    def _uploadFile(path, fileId):
        blobPath = os.path.join(TEMP_DIR, f"room_upload_{fileId}.blob")
        try:
            key, sha = encryptFile(path, blobPath)
            url = uploadTemporary(blobPath)
        finally:
            try:
                os.remove(blobPath)
            except OSError:
                pass
        return {"id": fileId, "url": url, "key": key, "sha": sha, "ext": os.path.splitext(path)[1].lower(), "at": int(time.time())}

    def _onUploaded(self, code, info):
        print(f"[Stanza] mio file inviato agli altri ({info.get('id', '')[:8]})")
        self.uploads[info["id"]] = {"state": "done", "at": time.time()}
        if code == self.code:
            self.link.publish(code, f"files/{info['id']}", info, retain=True)

    def _onUploadFailed(self, code, fileId, message):
        print(f"[Stanza] invio del mio file non riuscito: {message}")
        self.uploads.pop(fileId, None)
        alreadyFailed = fileId in self.failedUploads
        self.failedUploads[fileId] = time.time()
        if code == self.code:
            self.link.publish(code, f"files/{fileId}", {"id": fileId, "failed": True}, retain=True)
        if not alreadyFailed:
            self.notify("Non riesco a mandare la canzone agli altri: la cercheranno su YouTube")

    def resolveRoomFile(self, target, useCache=True):
        """Runs in a worker thread: waits for the friend's upload, downloads and decrypts it; falls back to YouTube."""
        body = target[len("roomfile:"):]
        fileId, _, query = body.partition("|")
        startedAt = time.time()
        deadline = startedAt + ROOM_FILE_WAIT_SECONDS
        info = self.fileInfos.get(fileId)
        while info is None and time.time() < deadline and self.code:
            time.sleep(0.5)
            info = self.fileInfos.get(fileId)
        if info is not None and not info.get("failed"):
            try:
                fetchInfo = dict(info, sha=info.get("sha") or fileId)
                path = self.roomCache.fetch(fetchInfo)
                print(f"[Stanza] file dell'amico pronto in {time.time() - startedAt:.1f}s")
                self.currentRoomFile = path
                self.roomFilePaths[fileId] = path
                from PySide6.QtCore import QUrl
                return {"url": QUrl.fromLocalFile(path).toString(), "headers": {}, "duration": 0}
            except Exception as error:
                print(f"[Together] file della stanza non scaricato: {error!r}")
        print(f"[Stanza] file dell'amico non arrivato dopo {time.time() - startedAt:.1f}s: la cerco su YouTube")
        if not query:
            raise RuntimeError("canzone non disponibile")
        from .downloader import resolveStream
        return resolveStream(query, useCache)

    def _fileMaintenance(self):
        current = self.currentRoomFile
        song = self.player.currentSong()
        if current and song and str(song.get("path") or "").startswith("stream:roomfile:"):
            self.roomCache.touch(current)
        self.roomCache.cleanup(keep=[current] if current else [])
        self._ensureUploads()

    # ---------- personal delay ----------
    def delayMs(self):
        """Extra delay chosen by this person (e.g. to match what friends hear on a Discord call)."""
        value = self.delayOverride if self.delayOverride is not None else settings.get("roomDelayMs")
        try:
            return max(0, min(3000, int(value or 0)))
        except (TypeError, ValueError):
            return 0

    def setDelay(self, delayMs):
        delayMs = max(0, min(3000, int(delayMs)))
        if self.delayOverride is not None:
            self.delayOverride = delayMs
        else:
            settings.set("roomDelayMs", delayMs)
            settings.save()
        if self.code:
            QTimer.singleShot(0, self._checkDrift)

    def _targetPosition(self, state):
        """Where MY player should be: the room position minus my delay (negative = not started yet for me)."""
        return expectedPosition(state, nowMs(), self.clock.offset(state.get("by"))) - self.delayMs()

    # ---------- helpers ----------
    @staticmethod
    def _trackOf(song):
        return dict(song["_roomTrack"]) if song.get("_roomTrack") else trackFromSong(song)

    @classmethod
    def _keyOf(cls, song):
        return cls._trackOf(song)["key"] if song else None

    @staticmethod
    def _currentTrackKey(state):
        queue = (state or {}).get("queue") or []
        index = (state or {}).get("index", -1)
        return queue[index]["key"] if 0 <= index < len(queue) else None
