import os
import random
import re

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QMediaPlayer

from .audio_engine import AudioEngine
from .database import isStreamPath, streamTarget
from .workers import runInBackground


def _defaultStreamResolver(target, useCache=True):
    from .downloader import resolveStream
    return resolveStream(target, useCache)


def _shortError(message):
    text = re.sub(r"https?://\S+", "", str(message or ""))
    text = re.sub(r"^\s*ERROR:\s*", "", text.strip().splitlines()[0] if text.strip() else "")
    text = re.sub(r"\s*\(caused by.*$", "", text)
    text = text.strip(" :;")
    return (text[:120] + "...") if len(text) > 120 else (text or "errore sconosciuto")


def _defaultStreamFallback(target):
    from .downloader import downloadTempAudio
    return downloadTempAudio(target)


def _forgetStream(target):
    from .downloader import forgetStream
    forgetStream(target)

REPEAT_OFF, REPEAT_ALL, REPEAT_ONE = 0, 1, 2


class Player(QObject):
    songChanged = Signal(object)
    playingChanged = Signal(bool)
    positionChanged = Signal(int)
    durationChanged = Signal(int)
    queueChanged = Signal()
    modesChanged = Signal()
    loopChanged = Signal(object)
    volumeChanged = Signal(int, bool)
    playbackError = Signal(str)
    songStarted = Signal(int)
    effectsApplied = Signal(object)
    loadingChanged = Signal(bool)
    seeked = Signal(int)
    songLoaded = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mediaPlayer = AudioEngine(self)
        self.audioOutput = self.mediaPlayer

        self.queue = []
        self.originalQueue = []
        self.currentIndex = -1
        self.repeatMode = REPEAT_OFF
        self.shuffle = False
        self.activeLoop = None
        self.volume = 70
        self.muted = False
        self.stopAfterCurrent = False
        self.pendingSeek = None
        self.consecutiveErrors = 0
        self.effectsProvider = None
        self.streamResolver = _defaultStreamResolver
        self.loading = False
        self.loadGeneration = 0
        self.loadAutoplay = False
        self.streamRetriedFor = None
        self.streamFallbackFor = None
        self.streamFallback = _defaultStreamFallback
        self.roomFileResolver = None
        from PySide6.QtCore import QThreadPool
        self.resolvePool = QThreadPool(self)
        self.resolvePool.setMaxThreadCount(3)
        self.skipOnError = True

        self.loopTimer = QTimer(self)
        self.loopTimer.setInterval(15)
        self.loopTimer.timeout.connect(self._checkLoop)

        self.mediaPlayer.positionChanged.connect(self._onPosition)
        self.mediaPlayer.durationChanged.connect(lambda duration: self.durationChanged.emit(int(duration)))
        self.mediaPlayer.playbackStateChanged.connect(self._onState)
        self.mediaPlayer.mediaStatusChanged.connect(self._onMediaStatus)
        self.mediaPlayer.errorOccurred.connect(self._onError)

    # ---------- state ----------
    def currentSong(self):
        if 0 <= self.currentIndex < len(self.queue):
            return self.queue[self.currentIndex]
        return None

    def isPlaying(self):
        return self.mediaPlayer.playbackState() == QMediaPlayer.PlayingState

    def position(self):
        return self.mediaPlayer.position()

    def duration(self):
        return self.mediaPlayer.duration()

    # ---------- queue ----------
    def playSongs(self, songs, startIndex=0, shuffled=None):
        songs = [dict(song) for song in songs]
        if not songs:
            return
        if shuffled is not None:
            self.shuffle = shuffled
            self.modesChanged.emit()
        self.originalQueue = list(songs)
        startSong = songs[startIndex] if startIndex is not None and 0 <= startIndex < len(songs) else None
        if self.shuffle:
            if startSong is None:
                startSong = random.choice(songs)
            remaining = [song for song in songs if song is not startSong]
            random.shuffle(remaining)
            self.queue = [startSong] + remaining
            self.currentIndex = 0
        else:
            self.queue = songs
            self.currentIndex = startIndex or 0
        self.queueChanged.emit()
        self._loadCurrent(autoplay=True)

    def addToQueue(self, songs):
        songs = [dict(song) for song in songs]
        if not self.queue:
            self.playSongs(songs, 0)
            return
        self.queue.extend(songs)
        self.originalQueue.extend(songs)
        self.queueChanged.emit()

    def playNext(self, songs):
        songs = [dict(song) for song in songs]
        if not self.queue:
            self.playSongs(songs, 0)
            return
        insertAt = self.currentIndex + 1
        self.queue[insertAt:insertAt] = songs
        self.originalQueue.extend(songs)
        self.queueChanged.emit()

    def removeFromQueue(self, indexes):
        for index in sorted(set(indexes), reverse=True):
            if index == self.currentIndex or not (0 <= index < len(self.queue)):
                continue
            removed = self.queue.pop(index)
            if removed in self.originalQueue:
                self.originalQueue.remove(removed)
            if index < self.currentIndex:
                self.currentIndex -= 1
        self.queueChanged.emit()

    def moveInQueue(self, fromIndex, toIndex):
        if not (0 <= fromIndex < len(self.queue)):
            return
        toIndex = max(0, min(toIndex, len(self.queue) - 1))
        currentSong = self.currentSong()
        song = self.queue.pop(fromIndex)
        self.queue.insert(toIndex, song)
        if currentSong is not None:
            self.currentIndex = next(i for i, item in enumerate(self.queue) if item is currentSong)
        self.queueChanged.emit()

    def clearUpcoming(self):
        if self.currentIndex >= 0:
            self.queue = self.queue[: self.currentIndex + 1]
            self.originalQueue = list(self.queue)
        self.queueChanged.emit()

    def jumpTo(self, index):
        if 0 <= index < len(self.queue):
            self.currentIndex = index
            self._loadCurrent(autoplay=True)
            self.queueChanged.emit()

    def updateSongData(self, songData):
        for song in self.queue + self.originalQueue:
            if song.get("id") == songData.get("id"):
                song.update(songData)
        current = self.currentSong()
        if current and current.get("id") == songData.get("id"):
            self.songChanged.emit(current)
        self.queueChanged.emit()

    def removeSongIds(self, songIds):
        songIds = set(songIds)
        current = self.currentSong()
        if current and current.get("id") in songIds:
            self.mediaPlayer.stop()
            self.mediaPlayer.setSource(QUrl())
        self.queue = [song for song in self.queue if song.get("id") not in songIds]
        self.originalQueue = [song for song in self.originalQueue if song.get("id") not in songIds]
        if current and current.get("id") not in songIds:
            self.currentIndex = next(i for i, song in enumerate(self.queue) if song is current)
        else:
            self.currentIndex = -1 if not self.queue else min(self.currentIndex, len(self.queue) - 1)
            self.setLoop(None)
            self.songChanged.emit(self.currentSong())
            if self.currentSong():
                self._loadCurrent(autoplay=False)
        self.queueChanged.emit()

    # ---------- playback ----------
    def _loadCurrent(self, autoplay=True, startPosition=0):
        song = self.currentSong()
        if song is None:
            return
        self.setLoop(None)
        self.loadGeneration += 1
        if self.streamRetriedFor is not None and self.streamRetriedFor != song.get("id"):
            self.streamRetriedFor = None
        if self.streamFallbackFor is not None and self.streamFallbackFor != song.get("id"):
            self.streamFallbackFor = None
        if isStreamPath(song["path"]):
            self._loadStream(song, autoplay, startPosition, self.loadGeneration)
            return
        self._setLoading(False)
        if not os.path.isfile(song["path"]):
            self.playbackError.emit(f"File non trovato: {song['path']}")
            self.songChanged.emit(song)
            if autoplay and self.skipOnError:
                self.consecutiveErrors += 1
                if self.consecutiveErrors < len(self.queue):
                    QTimer.singleShot(50, self.next)
            return
        self._startSource(song, QUrl.fromLocalFile(os.path.abspath(song["path"])), autoplay, startPosition)

    def _startSource(self, song, url, autoplay, startPosition, headers=None, durationHintMs=0):
        self.pendingSeek = startPosition if startPosition > 0 else None
        if self.effectsProvider is not None:
            effects = self.effectsProvider(song)
            self.mediaPlayer.presetRate(effects["rate"], effects["keepPitch"])
            self.mediaPlayer.setReverb(effects["reverbWet"], effects["reverbSize"])
            self.mediaPlayer.setBassBoost(effects.get("bassBoost", 0.0))
            self.effectsApplied.emit(effects)
        self.mediaPlayer.sourceHeaders = dict(headers or {})
        self.mediaPlayer.durationHintMs = int(durationHintMs or 0)
        self.mediaPlayer.setSource(url)
        self.songChanged.emit(song)
        if autoplay:
            self.mediaPlayer.play()
            self.songStarted.emit(song["id"])
        self.songLoaded.emit(song)

    def _setLoading(self, loading):
        if loading != self.loading:
            self.loading = loading
            self.loadingChanged.emit(loading)

    def _loadStream(self, song, autoplay, startPosition, generation, useCache=True):
        self.loadAutoplay = autoplay
        if not self.mediaPlayer.source().isEmpty():
            self.mediaPlayer.stop()
            self.mediaPlayer.setSource(QUrl())
        self._setLoading(True)
        self.songChanged.emit(song)
        target = streamTarget(song["path"])
        resolver = self.streamResolver
        if target.startswith("roomfile:") and self.roomFileResolver is not None:
            resolver = self.roomFileResolver
        runInBackground(
            resolver, target, useCache, pool=self.resolvePool,
            onFinished=lambda info: self._onStreamResolved(generation, song, info, startPosition),
            onError=lambda message: self._onStreamFailed(generation, song, message),
        )

    def _loadFallback(self, song, startPosition):
        self.loadGeneration += 1
        generation = self.loadGeneration
        self.loadAutoplay = True
        self._setLoading(True)
        target = streamTarget(song["path"])
        runInBackground(
            self.streamFallback, target, pool=self.resolvePool,
            onFinished=lambda path: self._onFallbackReady(generation, song, path, startPosition),
            onError=lambda message: self._onStreamFailed(generation, song, message),
        )

    def _onFallbackReady(self, generation, song, path, startPosition):
        if generation != self.loadGeneration or self.currentSong() is not song:
            return
        self._setLoading(False)
        self._startSource(song, QUrl.fromLocalFile(os.path.abspath(path)), self.loadAutoplay, startPosition)

    def _onStreamResolved(self, generation, song, info, startPosition):
        if generation != self.loadGeneration or self.currentSong() is not song:
            return
        self._setLoading(False)
        durationHintMs = int((info.get("duration") or song.get("duration") or 0) * 1000)
        self._startSource(song, QUrl(info["url"]), self.loadAutoplay, startPosition, info.get("headers"), durationHintMs)

    def _onStreamFailed(self, generation, song, message):
        if generation != self.loadGeneration or self.currentSong() is not song:
            return
        self._setLoading(False)
        autoplay = self.loadAutoplay
        if autoplay:
            self.playbackError.emit(f"Streaming non disponibile: {_shortError(message)}")
            self.consecutiveErrors += 1
            if self.skipOnError and self.consecutiveErrors < len(self.queue):
                QTimer.singleShot(50, self.next)

    def restoreSession(self, songs, currentIndex, position):
        self.queue = [dict(song) for song in songs]
        self.originalQueue = list(self.queue)
        self.currentIndex = currentIndex if 0 <= currentIndex < len(self.queue) else (0 if self.queue else -1)
        self.queueChanged.emit()
        self._loadCurrent(autoplay=False, startPosition=position)

    def togglePlay(self):
        if self.currentSong() is None:
            return
        if self.loading:
            self.loadAutoplay = not self.loadAutoplay
            return
        if self.isPlaying():
            self.mediaPlayer.pause()
        else:
            if self.mediaPlayer.source().isEmpty():
                self._loadCurrent(autoplay=True)
            else:
                self.mediaPlayer.play()

    def play(self):
        if not self.isPlaying():
            self.togglePlay()

    def pause(self):
        if self.loading:
            self.loadAutoplay = False
        self.mediaPlayer.pause()

    def next(self, automatic=False):
        if not self.queue:
            return
        if self.currentIndex + 1 < len(self.queue):
            self.currentIndex += 1
        elif self.repeatMode == REPEAT_ALL or not automatic:
            if self.shuffle and len(self.queue) > 1:
                current = self.currentSong()
                random.shuffle(self.queue)
                if self.queue[0] is current:
                    self.queue.append(self.queue.pop(0))
            self.currentIndex = 0
            if not automatic and self.repeatMode != REPEAT_ALL:
                self.queueChanged.emit()
                self._loadCurrent(autoplay=False)
                return
        else:
            self.mediaPlayer.stop()
            return
        self.queueChanged.emit()
        self._loadCurrent(autoplay=True)

    def previous(self):
        if not self.queue:
            return
        if self.mediaPlayer.position() > 3000 or self.currentIndex == 0:
            self.seek(self.activeLoop["startMs"] if self.activeLoop else 0)
            return
        self.currentIndex -= 1
        self.queueChanged.emit()
        self._loadCurrent(autoplay=True)

    def seek(self, positionMs):
        self.mediaPlayer.setPosition(max(0, int(positionMs)))
        self.seeked.emit(max(0, int(positionMs)))

    def seekRelative(self, deltaMs):
        self.seek(self.mediaPlayer.position() + deltaMs)

    def setVolume(self, volume):
        self.volume = max(0, min(100, int(volume)))
        self.audioOutput.setVolume((self.volume / 100.0) ** 2)
        if self.muted and self.volume > 0:
            self.muted = False
            self.audioOutput.setMuted(False)
        self.volumeChanged.emit(self.volume, self.muted)

    def setMuted(self, muted):
        self.muted = muted
        self.audioOutput.setMuted(muted)
        self.volumeChanged.emit(self.volume, self.muted)

    def setPlaybackRate(self, rate, keepPitch=None):
        self.mediaPlayer.setPlaybackRate(rate, keepPitch)
        if self.activeLoop:
            self.mediaPlayer.setLoopRange(self.activeLoop["startMs"], self.activeLoop["endMs"])

    def setReverb(self, wet, decaySeconds):
        self.mediaPlayer.setReverb(wet, decaySeconds)

    def setBassBoost(self, amount):
        self.mediaPlayer.setBassBoost(amount)

    def setEqualizer(self, gains, preampDb, enabled):
        self.mediaPlayer.setEqualizer(gains, preampDb, enabled)

    def shutdown(self):
        self.mediaPlayer.shutdown()

    def playbackRate(self):
        return self.mediaPlayer.playbackRate()

    def cycleRepeat(self):
        self.repeatMode = (self.repeatMode + 1) % 3
        self.modesChanged.emit()

    def setRepeat(self, mode):
        self.repeatMode = mode
        self.modesChanged.emit()

    def setShuffle(self, enabled):
        if enabled == self.shuffle:
            return
        self.shuffle = enabled
        current = self.currentSong()
        if self.queue:
            if enabled:
                upcoming = self.queue[self.currentIndex + 1:]
                random.shuffle(upcoming)
                self.queue = self.queue[: self.currentIndex + 1] + upcoming
            else:
                self.queue = list(self.originalQueue)
                if current is not None:
                    self.currentIndex = next((i for i, song in enumerate(self.queue) if song is current), 0)
            self.queueChanged.emit()
        self.modesChanged.emit()

    # ---------- A-B loop ----------
    def setLoop(self, loopData):
        if loopData is not None and loopData["endMs"] - loopData["startMs"] < 100:
            loopData = None
        self.activeLoop = dict(loopData) if loopData else None
        if self.activeLoop:
            self.mediaPlayer.setLoopRange(self.activeLoop["startMs"], self.activeLoop["endMs"])
            position = self.mediaPlayer.position()
            if position < self.activeLoop["startMs"] or position >= self.activeLoop["endMs"]:
                self.mediaPlayer.setPosition(self.activeLoop["startMs"])
        else:
            self.mediaPlayer.setLoopRange(None)
        self.loopChanged.emit(self.activeLoop)

    def _checkLoop(self):
        if self.activeLoop and self.mediaPlayer.position() >= self.activeLoop["endMs"]:
            self.mediaPlayer.setPosition(self.activeLoop["startMs"])

    # ---------- internal ----------
    def _onPosition(self, position):
        self.positionChanged.emit(position)

    def _onState(self, state):
        self.playingChanged.emit(state == QMediaPlayer.PlayingState)

    def _onMediaStatus(self, status):
        if status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia) and self.pendingSeek is not None:
            self.mediaPlayer.setPosition(self.pendingSeek)
            self.pendingSeek = None
        if status == QMediaPlayer.BufferedMedia:
            self.consecutiveErrors = 0
        if status == QMediaPlayer.EndOfMedia:
            if self.activeLoop:
                self.mediaPlayer.setPosition(self.activeLoop["startMs"])
                self.mediaPlayer.play()
                return
            if self.stopAfterCurrent:
                self.stopAfterCurrent = False
                self.mediaPlayer.pause()
                self.mediaPlayer.setPosition(0)
                return
            if self.repeatMode == REPEAT_ONE:
                self.mediaPlayer.setPosition(0)
                self.mediaPlayer.play()
                self.seeked.emit(0)
                self.songStarted.emit(self.currentSong()["id"])
            else:
                self.next(automatic=True)

    def _onError(self, error, message):
        if error == QMediaPlayer.NoError:
            return
        song = self.currentSong()
        if song is not None and isStreamPath(song["path"]) and error != QMediaPlayer.ResourceError \
                and self.streamRetriedFor != song.get("id"):
            self.streamRetriedFor = song.get("id")
            _forgetStream(streamTarget(song["path"]))
            self.loadGeneration += 1
            self._loadStream(song, True, self.mediaPlayer.position(), self.loadGeneration, useCache=False)
            return
        if song is not None and isStreamPath(song["path"]) and error != QMediaPlayer.ResourceError \
                and self.streamFallbackFor != song.get("id") and not streamTarget(song["path"]).startswith("roomfile:"):
            self.streamFallbackFor = song.get("id")
            self._loadFallback(song, self.mediaPlayer.position())
            return
        self.playbackError.emit(message or "Errore di riproduzione")
        if error == QMediaPlayer.ResourceError:
            return
        self.consecutiveErrors += 1
        if self.skipOnError and self.consecutiveErrors < max(2, len(self.queue)):
            QTimer.singleShot(300, lambda: self.next(automatic=True))
