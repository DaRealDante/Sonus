import base64
import json
import os

from PySide6.QtCore import QObject, QTimer, Signal

from .session_link import PLAYLIST_PREFIX, Link, makeCode
from .together_sync import nowMs, trackFromSong

TOMBSTONE_DAYS = 90
TRACK_FIELDS = ("title", "artist", "album", "duration", "url", "query")
SNAPSHOT_WAIT_MS = 15000
# The free server counts minutes of connection: shared playlists connect only for a while, then check every few minutes
AWAKE_MS = 3 * 60 * 1000
CHECK_EVERY_MS = 5 * 60 * 1000
CHECK_AWAKE_MS = 45 * 1000
COVER_SIZE = 200
AWAITING = {"_awaiting": True}


def _contentKey(snapshot):
    if not snapshot:
        return ""
    visible = {key: value for key, value in snapshot.items() if not key.startswith("_")}
    return json.dumps(visible, sort_keys=True, separators=(",", ":"))


def assignKeys(baseKeys, storedKeys):
    """Stable key per playlist entry; the same song twice becomes key, key#2, key#3."""
    used = {key for key in storedKeys if key}
    result = []
    for baseKey, storedKey in zip(baseKeys, storedKeys):
        if storedKey:
            result.append(storedKey)
            continue
        candidate, occurrence = baseKey, 1
        while candidate in used:
            occurrence += 1
            candidate = f"{baseKey}#{occurrence}"
        used.add(candidate)
        result.append(candidate)
    return result


def buildSnapshot(meta, entries, previous, currentMs):
    """meta: {name, description, cover}; entries: [(key, track)] in playlist order; previous: last synced snapshot or None."""
    previous = previous or {}
    previousTracks = previous.get("tracks") or {}
    removed = dict(previous.get("removed") or {})
    tracks = {}
    for key, track in entries:
        if key in previousTracks:
            tracks[key] = dict(previousTracks[key])
        else:
            tracks[key] = {field: track.get(field) for field in TRACK_FIELDS}
            tracks[key]["addedAt"] = currentMs
        removed.pop(key, None)
    for key in previousTracks:
        if key not in tracks:
            removed[key] = currentMs
    oldest = currentMs - TOMBSTONE_DAYS * 86400000
    removed = {key: when for key, when in removed.items() if when >= oldest}
    order = [key for key, track in entries]
    previousOrder = [key for key in previous.get("order") or [] if key in tracks]
    orderAt = previous.get("orderAt", currentMs) if order == previousOrder and previous else currentMs
    metaChanged = not previous or any(previous.get(field) != meta.get(field) for field in ("name", "description", "cover"))
    return {
        "name": meta.get("name") or "", "description": meta.get("description") or "", "cover": meta.get("cover") or "",
        "metaAt": currentMs if metaChanged else previous.get("metaAt", currentMs),
        "tracks": tracks, "removed": removed, "order": order, "orderAt": orderAt,
    }


def _trackRank(track):
    return track.get("addedAt", 0), json.dumps(track, sort_keys=True)


def _winner(first, second, timeField, tieField):
    firstTime, secondTime = first.get(timeField, 0), second.get(timeField, 0)
    if firstTime != secondTime:
        return (first, second) if firstTime > secondTime else (second, first)
    firstTie = json.dumps(first.get(tieField), sort_keys=True)
    secondTie = json.dumps(second.get(tieField), sort_keys=True)
    return (first, second) if firstTie >= secondTie else (second, first)


def mergeSnapshots(first, second):
    """Union of both edits: additions from both kept, a removal wins over an older addition, order and name from the latest edit."""
    if not first:
        return json.loads(json.dumps(second))
    if not second:
        return json.loads(json.dumps(first))
    allTracks = {}
    for snapshot in (first, second):
        for key, track in (snapshot.get("tracks") or {}).items():
            if key not in allTracks or _trackRank(track) > _trackRank(allTracks[key]):
                allTracks[key] = dict(track)
    removed = {}
    for snapshot in (first, second):
        for key, when in (snapshot.get("removed") or {}).items():
            removed[key] = max(removed.get(key, 0), when)
    tracks = {key: track for key, track in allTracks.items() if removed.get(key, -1) < track.get("addedAt", 0)}
    for key in tracks:
        removed.pop(key, None)
    orderWinner, orderLoser = _winner(first, second, "orderAt", "order")
    order = [key for key in orderWinner.get("order") or [] if key in tracks]
    for key in orderLoser.get("order") or []:
        if key in tracks and key not in order:
            order.append(key)
    for key in sorted((key for key in tracks if key not in order), key=lambda key: (tracks[key].get("addedAt", 0), key)):
        order.append(key)
    metaWinner, _ = _winner(first, second, "metaAt", "name")
    return {
        "name": metaWinner.get("name") or "", "description": metaWinner.get("description") or "",
        "cover": metaWinner.get("cover") or "", "metaAt": metaWinner.get("metaAt", 0),
        "tracks": tracks, "removed": removed, "order": order,
        "orderAt": max(first.get("orderAt", 0), second.get("orderAt", 0)),
    }


def sameContent(first, second):
    return _contentKey(first) == _contentKey(second)


def coverToBase64(coverPath):
    if not coverPath or not os.path.isfile(coverPath):
        return ""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from PySide6.QtGui import QImage
    image = QImage(coverPath)
    if image.isNull():
        return ""
    image = image.scaled(COVER_SIZE, COVER_SIZE, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "JPG", 80)
    return base64.b64encode(bytes(data)).decode("ascii")


class SharedPlaylists(QObject):
    """Playlists shared with a code: every copy receives additions, removals, order and name changes."""

    playlistsChanged = Signal(int)

    def __init__(self, database, notify=None, parent=None):
        super().__init__(parent)
        self.database = database
        self.notify = notify or (lambda text: None)
        self.link = Link(self)
        self.link.republishOnConnect = False
        self.stopped = False
        self.link.received.connect(self._onReceived)
        self.sleepTimer = QTimer(self)
        self.sleepTimer.setSingleShot(True)
        self.sleepTimer.timeout.connect(self._sleep)
        self.checkTimer = QTimer(self)
        self.checkTimer.setInterval(CHECK_EVERY_MS)
        self.checkTimer.timeout.connect(lambda: self._wake(CHECK_AWAKE_MS))
        self.applying = False
        self.pending = set()
        self.waiting = {}
        self.publishTimer = QTimer(self)
        self.publishTimer.setSingleShot(True)
        self.publishTimer.setInterval(1000)
        self.publishTimer.timeout.connect(self._publishPending)
        database.playlistListener = self.onPlaylistChanged

    # ---------- public ----------
    def start(self):
        self.stopped = False
        shared = self.database.sharedPlaylists()
        for row in shared:
            self.link.watch(row["code"], ["snapshot"])
            self._publishLocal(row["playlistId"], force=bool(row["snapshot"]))
        if shared:
            self._wake()
            self.checkTimer.start()

    def stopAll(self):
        self.stopped = True
        self.publishTimer.stop()
        self.sleepTimer.stop()
        self.checkTimer.stop()
        self._publishPending()
        self.link.stop()

    def _wake(self, awakeMs=None):
        if self.stopped or not self.database.sharedPlaylists():
            return
        awakeMs = awakeMs or AWAKE_MS
        self.link.start()
        if not self.sleepTimer.isActive() or self.sleepTimer.remainingTime() < awakeMs:
            self.sleepTimer.start(awakeMs)
        if not self.checkTimer.isActive():
            self.checkTimer.start()

    def _sleep(self):
        if self.waiting or self.pending or self.link.unsent:
            self.sleepTimer.start(CHECK_AWAKE_MS)
            return
        self.link.stop()

    def isShared(self, playlistId):
        return self.database.sharedPlaylist(playlistId) is not None

    def codeOf(self, playlistId):
        row = self.database.sharedPlaylist(playlistId)
        return row["code"] if row else None

    def share(self, playlistId):
        existing = self.codeOf(playlistId)
        if existing:
            return existing
        code = makeCode(PLAYLIST_PREFIX)
        self.database.setShared(playlistId, code, None)
        self.link.watch(code, ["snapshot"])
        self._publishLocal(playlistId, force=True)
        self._wake()
        return code

    def addShared(self, code):
        row = self.database.sharedPlaylistByCode(code)
        if row:
            self.playlistsChanged.emit(row["playlistId"])
            self.notify("Hai già questa playlist condivisa")
            return row["playlistId"]
        playlistId = self.database.createPlaylist("Playlist condivisa", "Caricamento...")
        self.database.setShared(playlistId, code, json.dumps(AWAITING))
        self.link.watch(code, ["snapshot"])
        self._wake()
        self.waiting[code] = playlistId
        QTimer.singleShot(SNAPSHOT_WAIT_MS, lambda: self._checkWaiting(code))
        self.notify("Cerco la playlist condivisa...")
        self.playlistsChanged.emit(playlistId)
        return playlistId

    def stopSharing(self, playlistId):
        code = self.codeOf(playlistId)
        if not code:
            return
        self.database.unshare(playlistId)
        self.link.unwatch(code)
        self.pending.discard(playlistId)

    def onPlaylistChanged(self, playlistId):
        if self.applying or not self.isShared(playlistId):
            return
        self.pending.add(playlistId)
        self.publishTimer.start()
        self._wake()

    # ---------- local → remote ----------
    def _publishPending(self):
        pending, self.pending = self.pending, set()
        for playlistId in pending:
            self._publishLocal(playlistId)

    def _localSnapshot(self, playlistId, previous):
        playlist = self.database.getPlaylist(playlistId)
        if playlist is None:
            return None
        songs = self.database.playlistSongs(playlistId)
        tracks = [trackFromSong(song) for song in songs]
        keys = assignKeys([track["key"] for track in tracks], [song.get("shareKey") for song in songs])
        missing = [(song["entryId"], key) for song, key in zip(songs, keys) if song.get("shareKey") != key]
        if missing:
            self.database.setEntryKeys(missing)
        previous = previous or {}
        coverPath = playlist.get("cover") or ""
        if previous and previous.get("_coverSource") == coverPath:
            cover = previous.get("cover") or ""
        else:
            cover = coverToBase64(coverPath)
        meta = {"name": playlist["name"], "description": playlist.get("description") or "", "cover": cover}
        snapshot = buildSnapshot(meta, list(zip(keys, tracks)), previous if previous else None, nowMs())
        snapshot["_coverSource"] = coverPath
        return snapshot

    def _storedSnapshot(self, playlistId):
        row = self.database.sharedPlaylist(playlistId)
        if not row or not row["snapshot"]:
            return None
        try:
            return json.loads(row["snapshot"])
        except ValueError:
            return None

    def _publishLocal(self, playlistId, force=False):
        row = self.database.sharedPlaylist(playlistId)
        if not row:
            return
        previous = self._storedSnapshot(playlistId)
        if previous and previous.get("_awaiting"):
            return
        snapshot = self._localSnapshot(playlistId, previous)
        if snapshot is None:
            return
        if not force and previous and sameContent(snapshot, previous):
            return
        self.database.setShared(playlistId, row["code"], json.dumps(snapshot))
        self.link.publish(row["code"], "snapshot", {key: value for key, value in snapshot.items() if not key.startswith("_")},
                          retain=True)

    # ---------- remote → local ----------
    def _onReceived(self, code, subtopic, payload):
        if subtopic != "snapshot" or not isinstance(payload, dict) or not isinstance(payload.get("tracks"), dict):
            return
        row = self.database.sharedPlaylistByCode(code)
        if row is None:
            return
        playlistId = row["playlistId"]
        self.waiting.pop(code, None)
        previous = self._storedSnapshot(playlistId)
        firstTime = bool(previous and previous.get("_awaiting"))
        if firstTime or previous is None:
            local = None
        else:
            local = self._localSnapshot(playlistId, previous)
        merged = mergeSnapshots(local, payload)
        currentCover = (local or previous or {}).get("cover") or ""
        self._applyToDatabase(playlistId, merged, currentCover)
        stored = dict(merged)
        stored["_coverSource"] = (self.database.getPlaylist(playlistId) or {}).get("cover") or ""
        self.database.setShared(playlistId, code, json.dumps(stored))
        if not sameContent(merged, payload):
            self.link.publish(code, "snapshot", merged, retain=True)
        if firstTime:
            self.notify(f"Playlist condivisa \"{merged.get('name')}\" aggiunta")
        self.playlistsChanged.emit(playlistId)

    def _applyToDatabase(self, playlistId, snapshot, currentCover):
        self.applying = True
        try:
            songs = self.database.playlistSongs(playlistId)
            entryByKey = {}
            for song in songs:
                if song.get("shareKey"):
                    entryByKey.setdefault(song["shareKey"], song)
            tracks = snapshot.get("tracks") or {}
            wanted = [key for key in snapshot.get("order") or [] if key in tracks]
            removeIds = [song["entryId"] for song in songs if song.get("shareKey") not in tracks or entryByKey.get(song.get("shareKey")) is not song]
            if removeIds:
                self.database.removeEntries(removeIds)
            orderedEntryIds = []
            for key in wanted:
                if key in entryByKey and entryByKey[key]["entryId"] not in removeIds:
                    orderedEntryIds.append(entryByKey[key]["entryId"])
                    continue
                songId = self._songIdFor(tracks[key])
                orderedEntryIds.append(self.database.addEntry(playlistId, songId, key))
            self.database.setPlaylistOrder(orderedEntryIds)
            playlist = self.database.getPlaylist(playlistId)
            coverPath = playlist.get("cover")
            remoteCover = snapshot.get("cover") or ""
            if remoteCover != (currentCover or ""):
                coverPath = None
                if remoteCover:
                    try:
                        from .metadata import saveCoverBytes
                        coverPath = saveCoverBytes(base64.b64decode(remoteCover))
                    except Exception:
                        coverPath = playlist.get("cover")
            name = snapshot.get("name") or playlist["name"]
            description = snapshot.get("description") or ""
            if (playlist["name"], playlist.get("description") or "", playlist.get("cover")) != (name, description, coverPath):
                self.database.updatePlaylist(playlistId, name, description, coverPath)
        finally:
            self.applying = False

    def _songIdFor(self, track):
        song = None
        if track.get("url"):
            song = self.database.findSongByUrl(track["url"])
        if song is None and track.get("title"):
            song = self.database.findSong(track["title"], track.get("artist") or "")
        if song is not None:
            if song.get("hidden"):
                self.database.updateSong(song["id"], hidden=0)
            return song["id"]
        target = track.get("url") or track.get("query") or \
            f"ytsearch1:{track.get('artist') or ''} - {track.get('title') or ''} audio".replace("ytsearch1: - ", "ytsearch1:")
        return self.database.addStreamSong(target, track.get("title") or "Senza titolo", track.get("artist") or "",
                                           track.get("album") or "", track.get("duration") or 0, None)

    def _checkWaiting(self, code):
        playlistId = self.waiting.pop(code, None)
        if playlistId is not None:
            self.notify("Playlist non ancora trovata: arriverà appena il tuo amico apre Sonus (controlla il codice)")
