"""Android application operations. All mutable state belongs to Runtime's event loop.

The generated sonus_core is the PC implementation: database, player/DSP,
downloads, lyrics, discovery and the encrypted collaboration protocols are reused.
Network, tag reads, imports and conversions run in bounded background workers.
"""
import base64
import io
import json
import math
import os
import shutil
import time
import urllib.error
import urllib.request


DEFAULT_EFFECTS = {"rate": 1.0, "keepPitch": True, "reverbWet": 0.0,
                   "reverbSize": 1.8, "bassBoost": 0.0}


def _number(value, low, high):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("Valore non valido")
    return max(low, min(high, value))


def _inside(path, folder):
    try:
        return os.path.commonpath([os.path.realpath(path), os.path.realpath(folder)]) == os.path.realpath(folder)
    except ValueError:
        return False


def _cut_info(song):
    try:
        return json.loads(song.get("cutInfo") or "null")
    except (TypeError, ValueError):
        return None


class Controller:
    def __init__(self, runtime, emit):
        from sonus_core import config, downloader, lyrics, metadata, audio_tools, discover
        from sonus_core.database import Database
        from sonus_core.player import Player
        from sonus_core.together import TogetherController
        from sonus_core.playlist_sync import SharedPlaylists
        from sonus_mobile.runtime import QThreadPool
        self.runtime, self.emit = runtime, emit
        self.config, self.settings = config, config.settings
        self.downloader, self.lyrics = downloader, lyrics
        self.metadata, self.audio_tools, self.discover_core = metadata, audio_tools, discover
        self.database = Database(config.DB_PATH)
        self.player = Player()
        self.downloads = downloader.DownloadManager()
        self.closed, self.ready, self._initializing = False, False, True
        self._dirty_handle = self._tick_handle = self._save_handle = None
        self._collections, self._collection_revision, self._published_state = None, -1, None
        self.message, self.message_id, self.error = "", 0, None
        self.tasks, self._task_id, self._serials = {}, 0, {}
        self.render_pool = QThreadPool()
        self.render_pool.setMaxThreadCount(1)
        self.search = {"query": "", "kind": "youtube", "entries": [], "busy": False}
        self.lyrics_results, self.video_results = [], []
        self.waveform, self.waveform_song_id = [], None
        self.video = {"url": None, "headers": {}, "loading": False}
        self._video_key, self._video_cache, self._video_pending = None, {}, set()
        self._lyrics_pending, self._lyrics_retries, self._lyrics_versions = set(), {}, {}
        self._retry_handles = []
        self._foreground = True
        self.pending_order = {}
        self.export_path, self.update, self.diagnostics_text = None, None, ""
        self.discover_cache = discover.DiscoverCache(os.path.join(config.DATA_DIR, "discover.json"))
        self.discover = self.discover_cache.load() or {"sections": []}
        self.together = TogetherController(self.player, self.database, self.song_effects, notify=self._notify)
        self.shared = SharedPlaylists(self.database, notify=self._notify)
        self.player.effectsProvider = self.effects_for_song
        self.downloads.songDownloaded.connect(self._downloaded)
        self.downloads.videoDownloaded.connect(self._video_downloaded)
        self.downloads.jobAdded.connect(lambda *_: self._dirty())
        self.downloads.jobUpdated.connect(lambda *_: self._dirty())
        self.player.songStarted.connect(self._song_started)
        self.player.songChanged.connect(self._song_changed)
        self.player.playbackError.connect(self._notify)
        for signal in (self.player.queueChanged, self.player.playingChanged, self.player.loadingChanged,
                       self.player.modesChanged, self.player.volumeChanged, self.player.loopChanged,
                       self.player.durationChanged, self.together.roomChanged, self.together.peersChanged,
                       self.together.connectionChanged, self.together.effectsChanged,
                       self.shared.playlistsChanged):
            signal.connect(lambda *_: self._dirty())
        self._apply_eq()
        self._apply_effects(self.song_effects())
        self.player.setVolume(self.settings.get("volume"))
        self.player.setMuted(bool(self.settings.get("muted")))
        self.player.setRepeat(int(self.settings.get("repeatMode") or 0))
        self.player.shuffle = bool(self.settings.get("shuffle"))
        self.player.stopAfterCurrent = bool(self.settings.get("stopAfterCurrent", False))
        songs = self.database.getSongs(self.settings.get("lastQueue") or [])
        if songs:
            index = next((i for i, song in enumerate(songs) if song["id"] == self.settings.get("lastSongId")), 0)
            self.player.restoreSession(songs, index, int(self.settings.get("lastPosition") or 0))
        self.shared.start()
        self._initializing, self.ready = False, True
        self._tick_handle = runtime.call_later(.5, self._tick)
        self._save_handle = runtime.call_later(10, self._periodic_save)
        self._retry_handles.append(runtime.call_later(3, self._startup_updates))
        self._dirty()

    def _notify(self, text):
        if self.closed:
            return
        self.message, self.message_id = str(text), self.message_id + 1
        self._dirty()

    def _fail(self, action, error):
        if self.closed:
            return
        self.error = {"action": action, "message": str(error) or type(error).__name__}
        self._notify(self.error["message"])

    def _dirty(self):
        if self.closed or self._initializing or self._dirty_handle is not None:
            return
        self._dirty_handle = self.runtime.call_later(.04, self._publish)

    def _publish(self):
        self._dirty_handle = None
        if not self.closed:
            state = self.snapshot(detached=False)
            changed = state if self._published_state is None else {
                key: value for key, value in state.items() if value != self._published_state.get(key)}
            if changed:
                event = json.loads(json.dumps(changed, ensure_ascii=False))
                if self._published_state is None:
                    self._published_state = dict(event)
                else:
                    self._published_state.update(event)
                    event["tick"] = True
                self.emit(event)

    def _tick(self):
        if self.closed:
            return
        spectrum = self.player.mediaPlayer.spectrum() if self.settings.get("fxVisualizer") and self._foreground else []
        self.emit({"tick": True, "position": int(self.player.position()), "duration": int(self.player.duration()),
                   "playing": bool(self.player.isPlaying()), "loading": bool(self.player.loading),
                   "spectrum": [float(value) for value in spectrum][:48]})
        self._tick_handle = self.runtime.call_later(.5, self._tick)

    def _async(self, action, work, done=None, failed=None, pool=None):
        self._task_id += 1
        task_id = self._task_id
        self.tasks[task_id] = {"id": task_id, "action": action}
        self._dirty()
        def success(value):
            if self.closed:
                return
            self.tasks.pop(task_id, None)
            try:
                if done:
                    done(value)
            except Exception as error:
                self._fail(action, error)
            self._dirty()
        def failure(error):
            if self.closed:
                return
            self.tasks.pop(task_id, None)
            if failed:
                failed(error)
            else:
                self._fail(action, error)
            self._dirty()
        if pool is not None:
            from sonus_core.workers import runInBackground
            return runInBackground(work, onFinished=success, onError=failure, pool=pool)
        return self.runtime.submit(work, callback=success, error=failure)

    def _song(self, song_id=None):
        current = self.player.currentSong()
        song = self.database.getSong(song_id if song_id is not None else (current or {}).get("id"))
        if song is None:
            raise ValueError("Brano non trovato")
        return song

    def _playlist(self, playlist_id):
        playlist = self.database.getPlaylist(playlist_id)
        if playlist is None:
            raise ValueError("Playlist non trovata")
        return playlist

    def _updated(self, song_id):
        if self.closed:
            return
        song = self.database.getSong(song_id)
        if song:
            self.player.updateSongData(song)
        self._dirty()

    def song_effects(self, song=None):
        saved = self.settings.get("effects") or {}
        return {key: saved.get(key, default) for key, default in DEFAULT_EFFECTS.items()}

    def effects_for_song(self, song):
        return self.together.effectsFor(song) or self.song_effects(song)

    def _apply_effects(self, effects):
        self.player.setPlaybackRate(effects["rate"], effects["keepPitch"])
        self.player.setReverb(effects["reverbWet"], effects["reverbSize"])
        self.player.setBassBoost(effects.get("bassBoost", 0))

    def _apply_eq(self):
        self.player.setEqualizer(self.settings.get("eqGains") or [0.] * 10,
                                 float(self.settings.get("eqPreamp") or 0), bool(self.settings.get("eqEnabled")))
        self.player.mediaPlayer.setBalance(float(self.settings.get("eqBalance") or 0) / 100.)

    def _collection_snapshot(self):
        # SQLite's counter changes for every mutation, including incoming shared data.
        # Progress, volume and playback messages reuse these collections.
        revision = self.database.connection.total_changes
        if self._collections is None or revision != self._collection_revision:
            from sonus_core.session_link import linkFor
            playlists = []
            for row in self.database.playlists():
                code = self.shared.codeOf(row["id"])
                playlists.append(dict(row, songs=self.database.playlistSongs(row["id"]), code=code,
                                      link=linkFor(code) if code else None))
            loops = {}
            for loop in self.database._rows("SELECT * FROM loops ORDER BY startMs"):
                loops.setdefault(str(loop["songId"]), []).append(loop)
            self._collections = {"songs": self.database.allSongs(), "favorites": self.database.favoriteSongs(),
                                 "recent": self.database.recentlyPlayed(30), "recentAdded": self.database.recentSongs(),
                                 "mostPlayed": self.database.mostPlayed(), "playlists": playlists, "songLoops": loops}
            self._collection_revision = revision
        return self._collections

    def snapshot(self, detached=True):
        from sonus_core.audio_engine import EQ_PRESETS, EQ_LABELS
        from sonus_core.session_link import linkFor
        current = self.player.currentSong()
        collections = self._collection_snapshot()
        state = dict(collections, **{"ready": self.ready,
                 "current": dict(current) if current else None, "queue": list(self.player.queue),
                 "index": self.player.currentIndex, "position": int(self.player.position()),
                 "duration": int(self.player.duration()), "playing": bool(self.player.isPlaying()),
                 "loading": bool(self.player.loading), "volume": self.player.volume, "muted": self.player.muted,
                 "repeat": self.player.repeatMode, "shuffle": self.player.shuffle,
                 "effects": self.effects_for_song(current),
                 "eq": {"enabled": bool(self.settings.get("eqEnabled")), "gains": self.settings.get("eqGains") or [0.] * 10,
                        "preamp": self.settings.get("eqPreamp"), "balance": self.settings.get("eqBalance"),
                        "preset": self.settings.get("eqPreset"), "customPresets": self.settings.get("eqCustomPresets") or {},
                        "presets": EQ_PRESETS, "labels": EQ_LABELS},
                 "settings": dict(self.settings.values, stopAfterCurrent=self.player.stopAfterCurrent), "downloads": list(self.downloads.jobs),
                 "room": {"code": self.together.code, "connected": self.together.link.isConnected(),
                          "peers": [dict(peer, id=peer_id) for peer_id, peer in self.together.otherPeers().items()], "delayMs": self.together.delayMs(),
                          "link": linkFor(self.together.code) if self.together.code else None,
                          "broker": self.together.link.brokerName(),
                          "error": getattr(self.together.link, "lastError", "")},
                 "profile": self.together.profile(), "search": dict(self.search), "discover": self.discover,
                 "lyricsResults": self.lyrics_results, "lyricsPending": list(self._lyrics_pending),
                 "videoResults": self.video_results, "video": dict(self.video),
                 "waveform": self.waveform, "waveformSongId": self.waveform_song_id,
                 "loops": collections["songLoops"].get(str(current["id"]), []) if current else [],
                 "activeLoop": self.player.activeLoop, "spectrum": [], "message": self.message,
                 "messageId": self.message_id, "error": self.error, "tasks": list(self.tasks.values()),
                 "update": self.update, "diagnostics": self.diagnostics_text, "exportPath": self.export_path})
        # Make detached objects: the host and queued callbacks must not see later mutations.
        return json.loads(json.dumps(state, ensure_ascii=False)) if detached else state

    def dispatch(self, action, payload=None):
        if self.closed:
            return
        payload = payload or {}
        try:
            if not isinstance(payload, dict):
                raise ValueError("Parametri non validi")
            self.error = None
            self._dispatch(action, payload)
            self._dirty()
        except Exception as error:
            self._fail(action, error)

    def _dispatch(self, action, p):
        from sonus_core.database import isStreamPath, streamTarget
        player, db = self.player, self.database
        if action == "play":
            songs = db.getSongs(p.get("ids") or [])
            index = p.get("index", 0)
            if songs and index is not None and not 0 <= int(index) < len(songs):
                raise ValueError("Indice non valido")
            player.playSongs(songs, index, shuffled=p.get("shuffled"))
        elif action in ("toggle", "play_pause"):
            if "playing" in p:
                if not p["playing"]:
                    player.pause()
                elif player.loading:
                    if not player.loadAutoplay:
                        player.togglePlay()
                else:
                    player.play()
            else:
                player.togglePlay()
        elif action == "pause":
            player.pause()
        elif action == "resume":
            player.play()
        elif action == "next":
            player.next()
        elif action == "previous":
            player.previous()
        elif action == "seek":
            player.seek(int(_number(p["position"], 0, max(player.duration(), 0))))
        elif action == "volume":
            player.setVolume(_number(p["value"], 0, 100))
            self._save_playback_settings()
        elif action == "mute":
            player.setMuted(bool(p.get("value", not player.muted)))
            self._save_playback_settings()
        elif action == "repeat":
            if "value" in p:
                modes = {"off": 0, "all": 1, "one": 2}
                value = p["value"]
                player.setRepeat(modes[value] if isinstance(value, str) and value in modes else int(value) % 3)
            else:
                player.cycleRepeat()
            self._save_playback_settings()
        elif action == "shuffle":
            player.setShuffle(bool(p.get("value", p.get("enabled", not player.shuffle))))
            self._save_playback_settings()
        elif action in ("queue_add", "queue_next"):
            (player.addToQueue if action == "queue_add" else player.playNext)(db.getSongs(p.get("ids") or []))
        elif action == "queue_remove":
            player.removeFromQueue([int(i) for i in p.get("indexes", [])])
        elif action == "queue_move":
            player.moveInQueue(int(p["from"]), int(p["to"]))
        elif action == "queue_jump":
            player.jumpTo(int(p["index"]))
        elif action == "queue_clear":
            player.clearUpcoming()
        elif action == "favorite":
            song = self._song(p["id"])
            favorite = db.toggleFavorite(song["id"])
            if favorite:
                db.updateSong(song["id"], hidden=0)
            self._updated(song["id"])
        elif action == "search":
            self._search(str(p.get("query") or "").strip())
        elif action in ("play_entry", "search_play", "stream_add", "download"):
            entries = [p["entry"]] if action == "play_entry" else p.get("entries", [])
            if p.get("playlistId"):
                self._playlist(p["playlistId"])
            if action == "download":
                self._enqueue_entries(entries, p.get("playlistId"))
            else:
                self._stream_entries(entries, p.get("playlistId"), play=action in ("play_entry", "search_play"),
                                     hidden=action == "play_entry", queue=p.get("queue", False), index=p.get("index", 0))
        elif action == "discover":
            profile = self.discover_core.libraryProfile(db)
            def saved(value):
                self.discover = value
                self.discover_cache.save(value)
            self._async(action, lambda: self.discover_core.buildDiscover(profile, self.discover_core.DeezerClient()), saved)
        elif action in ("discover_artist", "discover_album"):
            client = self.discover_core.DeezerClient()
            work = (lambda: client.topTracks(p["id"], 50)) if action == "discover_artist" else (lambda: client.albumTracks(p["id"], p))
            self._async(action, work, lambda tracks: self._discovery_tracks(tracks, p.get("name") or p.get("title") or "Scopri"))
        elif action == "import_files":
            self._import(p.get("paths") or [], p.get("playlistId"))
        elif action.startswith("playlist_"):
            self._playlist_action(action, p)
        elif action == "song_edit":
            song = self._song(p["id"])
            fields = dict(p.get("fields") or {})
            # Files and provenance are managed by dedicated operations.
            allowed = {"title", "artist", "album", "cover", "favorite", "lyricsAuto", "videoAuto", "hidden"}
            if set(fields) - allowed:
                raise ValueError("Campo del brano non modificabile")
            db.updateSong(song["id"], **fields)
            self._updated(song["id"])
            if p.get("writeTags") and not isStreamPath(song["path"]):
                fresh = self._song(song["id"])
                def tags_done(ok):
                    if not ok:
                        self._notify("Dati salvati nell'app; tag del file non scritti")
                self._async(action, lambda: self.metadata.writeMp3Tags(fresh["path"], fresh["title"], fresh["artist"], fresh["album"], fresh["cover"]), tags_done)
            if fields.get("lyricsAuto") and self.settings.get("autoLyrics"):
                self._fetch_lyrics(self._song(song["id"]))
        elif action == "song_delete":
            songs = db.getSongs(p.get("ids") or [])
            player.removeSongIds([s["id"] for s in songs])
            db.deleteSongs([s["id"] for s in songs])
            if p.get("deleteFiles"):
                paths = [s["path"] for s in songs if not isStreamPath(s["path"])]
                self._async(action, lambda: self._remove_files(paths))
        elif action == "stream_only":
            song = self._song(p["id"])
            if not song.get("url"):
                raise ValueError("Il brano non ha un URL di streaming")
            if not isStreamPath(song["path"]):
                if player.currentSong() and player.currentSong()["id"] == song["id"]:
                    player.pause()
                duplicate = db.songByPath("stream:" + song["url"])
                if duplicate and duplicate["id"] != song["id"]:
                    db.mergeSongInto(duplicate["id"], song["id"])
                db.updateSong(song["id"], path="stream:" + song["url"], source="stream")
                self._updated(song["id"])
                self._async(action, lambda: self._remove_files([song["path"]]))
        elif action == "download_song":
            for song in db.getSongs(p.get("ids") or []):
                if isStreamPath(song["path"]):
                    if streamTarget(song["path"]).startswith("roomfile:"):
                        self._local_audio(song, lambda local, song=song: self._save_room_audio(song, local))
                    else:
                        entry = self._entry_for_song(song)
                        self.downloads.enqueue(entry)
        elif action == "download_retry":
            job = next((j for j in self.downloads.jobs if j["jobId"] == p.get("jobId")), None) if "jobId" in p else self.downloads.jobs[int(p["index"])]
            if not job or job["status"] != "error":
                raise ValueError("Download non ripetibile")
            self.downloads.retry(job)
        elif action == "downloads_clear":
            self.downloads.clearFinished()
        elif action == "effects":
            self._effects(p.get("values") or {})
        elif action == "eq":
            self._eq(p.get("values") or {})
        elif action.startswith("loop_"):
            self._loop(action, p)
        elif action in ("cut", "export"):
            song = self._song(p.get("id"))
            self._local_audio(song, lambda local: self._render(action, song, local, p))
        elif action == "waveform":
            song = self._song(p.get("id"))
            def prepared(local):
                def done(result):
                    self.waveform = [float(value) for value in result[0]]
                    self.waveform_song_id = song["id"]
                self._latest_query("waveform", lambda: self.audio_tools.loadWaveform(local["path"], bins=600), done)
            self._local_audio(song, prepared)
        elif action == "lyrics_fetch":
            self._fetch_lyrics(self._song(p.get("id")), force=p.get("force", False))
        elif action == "lyrics_search":
            self._latest_query("lyrics", lambda: self.lyrics.searchLyrics(str(p.get("query") or ""), float(p.get("duration") or 0)),
                               lambda results: setattr(self, "lyrics_results", results))
        elif action in ("lyrics_set", "lyrics_remove"):
            song = self._song(p.get("id"))
            self._lyrics_versions[song["id"]] = self._lyrics_versions.get(song["id"], 0) + 1
            plain, synced = p.get("plain") or "", p.get("synced") or ""
            if p.get("adaptToCut"):
                adapted = self.lyrics.adaptToCut({"plain": plain, "synced": synced}, _cut_info(song))
                plain, synced = adapted["plain"], adapted["synced"]
            db.updateSong(song["id"], lyrics=plain if action == "lyrics_set" else None,
                          syncedLyrics=synced if action == "lyrics_set" else None, lyricsChecked=1)
            self._updated(song["id"])
        elif action == "video_search":
            self._latest_query("video", lambda: self.downloader.searchYoutube(str(p.get("query") or ""), 20),
                               lambda result: setattr(self, "video_results", result["entries"]))
        elif action in ("video_set", "video_remove", "video_download"):
            self._video_action(action, p)
        elif action == "room_create":
            self.together.createRoom()
        elif action in ("room_join", "handle_code"):
            self._join_code(p.get("code"), "room" if action == "room_join" else None)
        elif action == "room_leave":
            self.together.leaveRoom()
            self._apply_effects(self.song_effects())
        elif action == "room_delay":
            self.together.setDelay(p["value"])
        elif action == "profile":
            self._profile(p)
        elif action == "settings":
            self._settings(p.get("values") or {})
        elif action == "engine_update":
            from sonus_core.updater import checkForEngineUpdate
            self._async(action, lambda: checkForEngineUpdate(True),
                        lambda updated: self._notify("Motore aggiornato: riavvia l'app" if updated else "Motore già aggiornato"))
        elif action == "update_check":
            self._async(action, self._check_android_release, lambda info: self._update_info(info, True))
        elif action == "diagnostics":
            from sonus_core.diagnostics import report
            self.diagnostics_text = report(self.together, self.config.VERSION).replace("Synth Music", "Sonus Android", 1) + "\nPiattaforma: Android"
        elif action == "foreground":
            self._foreground = bool(p.get("active", p.get("value", True)))
            if self._foreground:
                self._refresh_video()
        elif action == "refresh":
            self._published_state = None
            self._refresh_video()
        else:
            raise ValueError("Comando non supportato: " + str(action))

    def _latest_query(self, kind, work, done):
        serial = self._serials[kind] = self._serials.get(kind, 0) + 1
        def finished(value):
            if self._serials[kind] == serial:
                done(value)
        def failure(error):
            if self._serials[kind] == serial:
                if kind == "search":
                    self.search["busy"] = False
                self._fail(kind, error)
        self._async(kind, work, finished, failure)

    def _search(self, query):
        from sonus_core.spotify_import import isSpotifyUrl, fetchSpotify
        if not query:
            self._serials["search"] = self._serials.get("search", 0) + 1
            self.search = {"query": "", "entries": [], "busy": False, "kind": "youtube"}
            return
        spotify = isSpotifyUrl(query)
        self.search = {"query": query, "kind": "spotify" if spotify else "youtube", "entries": [], "busy": True}
        def done(result):
            if spotify:
                self.search.update(result)
                self.search["entries"] = [dict(track, spotify=track) for track in result["tracks"]]
                self.search["kind"] = "spotify"
            else:
                self.search.update(result)
            self.search["busy"] = False
        self._latest_query("search", lambda: fetchSpotify(query) if spotify else self.downloader.searchYoutube(query, int(self.settings.get("searchResults") or 25)), done)

    def _discovery_tracks(self, tracks, name):
        self.search = {"query": name, "kind": "discover", "entries": tracks, "busy": False}

    def _stream_entries(self, entries, playlist_id=None, play=False, hidden=False, queue=False, index=0):
        music = []
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("title"):
                raise ValueError("Brano non valido")
        def collect():
            for entry in entries:
                spotify = entry.get("spotify")
                if spotify or entry.get("artist"):
                    track = spotify or entry
                    image = track.get("image")
                    cover = None
                    if image:
                        try:
                            cover = self.metadata.saveCoverBytes(self.downloader.fetchBytes(image))
                        except Exception:
                            pass
                    music.append({"url": self.discover_core.playTarget(track), "title": track["title"],
                                  "artist": track.get("artist") or "", "album": track.get("album") or "",
                                  "duration": float(track.get("durationMs") or 0) / 1000 if spotify else float(track.get("duration") or 0), "cover": cover})
                elif entry.get("url"):
                    music.append(self.downloader.streamSongInfo(entry))
                else:
                    raise ValueError("URL del brano mancante")
            return music
        # Use a separate finalizer so only the owner thread accesses SQLite.
        def finish(infos):
            normalized = []
            for info in infos:
                song = self.database.findSongByUrl(info["url"]) or self.database.findSong(info["title"], info["artist"])
                song_id = song["id"] if song else self.database.addStreamSong(info["url"], info["title"], info["artist"], info["album"], info["duration"], info["cover"], hidden=hidden)
                if not hidden:
                    self.database.updateSong(song_id, hidden=0)
                normalized.append(song_id)
            if playlist_id and self.database.getPlaylist(playlist_id):
                self.database.addToPlaylist(playlist_id, normalized)
            songs = self.database.getSongs(normalized)
            if play and songs:
                self.player.playSongs(songs, max(0, min(int(index), len(songs) - 1)))
            elif queue:
                self.player.addToQueue(songs)
        self._async("stream_add", collect, finish)

    def _enqueue_entries(self, entries, playlist_id=None):
        if playlist_id:
            self._playlist(playlist_id)
            self.pending_order.setdefault(playlist_id, {})
        for order, item in enumerate(entries):
            entry = dict(item)
            if entry.get("artist") and not entry.get("spotify"):
                entry = {"title": entry["title"], "spotify": dict(entry, mainArtist=self.discover_core.mainArtist(entry.get("artist")),
                         durationMs=int(float(entry.get("duration") or 0) * 1000), spotifyId=str(entry.get("id") or entry["title"]), playlistIndex=order), "url": None}
            if entry.get("spotify"):
                entry["spotify"] = dict(entry["spotify"], playlistIndex=order)
            if not entry.get("url") and not entry.get("spotify"):
                raise ValueError("URL del download mancante")
            self.downloads.enqueue(entry, playlist_id)

    def _entry_for_song(self, song):
        if song.get("url"):
            return {"url": song["url"], "title": song["title"], "channel": song.get("artist") or "",
                    "duration": song.get("duration") or 0, "replaceSongId": song["id"]}
        track = {"title": song["title"], "artist": song.get("artist") or "", "mainArtist": song.get("artist") or "",
                 "album": song.get("album") or "", "durationMs": int(float(song.get("duration") or 0) * 1000),
                 "spotifyId": "stream-" + str(song["id"]), "playlistIndex": None}
        return {"url": None, "title": song["title"], "replaceSongId": song["id"], "spotify": track}

    def _downloaded(self, result, playlist_id):
        if self.closed:
            return
        from sonus_core.database import isStreamPath
        db = self.database
        song = db.getSong(result.get("replaceSongId")) if result.get("replaceSongId") else None
        song = song or (db.songByPath("stream:" + result["url"]) if result.get("url") else None)
        if song and isStreamPath(song["path"]):
            song_id = song["id"]
            duplicate = db.songByPath(result["path"])
            if duplicate and duplicate["id"] != song_id:
                db.mergeSongInto(duplicate["id"], song_id)
            fields = {key: result[key] for key in ("title", "artist", "album")} if song.get("hidden") else {}
            db.updateSong(song_id, path=result["path"], source="youtube", hidden=0, url=result.get("url") or song.get("url"),
                          duration=result.get("duration") or song.get("duration") or 0, cover=song.get("cover") or result.get("cover"), **fields)
        else:
            song_id = db.addSong(result["path"], result["title"], result.get("artist") or "", result.get("album") or "",
                                 result.get("duration") or 0, result.get("cover"), "youtube", result.get("url"))
        if result.get("videoPath"):
            db.updateSong(song_id, videoPath=result["videoPath"], videoUrl=result.get("videoUrl"), videoChecked=1)
        if playlist_id and db.getPlaylist(playlist_id):
            entry_id = db.addEntry(playlist_id, song_id)
            order = result.get("playlistIndex")
            if order is not None:
                self.pending_order.setdefault(playlist_id, {})[entry_id] = order
                orders = self.pending_order[playlist_id]
                entries = db.playlistSongs(playlist_id)
                unchanged = [r["entryId"] for r in entries if r["entryId"] not in orders]
                db.setPlaylistOrder(unchanged + sorted(orders, key=lambda key: orders[key]))
        self._updated(song_id)
        if self.settings.get("autoLyrics"):
            self._fetch_lyrics(self._song(song_id))
        if result.get("videoError"):
            self._notify("Audio pronto. Video: " + result["videoError"])

    def _import(self, paths, playlist_id):
        if playlist_id:
            self._playlist(playlist_id)
        folder, copy_files = self.settings.musicDir(), bool(self.settings.get("copyImported"))
        def read():
            found, seen, infos = [], set(), []
            for path in paths:
                if str(path).startswith("content:"):
                    raise ValueError("Copia prima il file nella cartella privata dell'app")
                if os.path.isdir(path):
                    for root, dirs, files in os.walk(path):
                        dirs.sort()
                        found.extend(os.path.join(root, name) for name in sorted(files) if os.path.splitext(name)[1].lower() in self.config.AUDIO_EXTENSIONS)
                elif os.path.isfile(path) and os.path.splitext(path)[1].lower() in self.config.AUDIO_EXTENSIONS:
                    found.append(path)
            for path in found:
                path = os.path.abspath(path)
                if path in seen:
                    continue
                seen.add(path)
                if copy_files and not _inside(path, folder):
                    name, extension = os.path.splitext(os.path.basename(path))
                    target = self.audio_tools.uniquePath(folder, name, extension)
                    shutil.copy2(path, target)
                    path = target
                infos.append(dict(self.metadata.readTags(path), path=path))
            return infos
        def done(infos):
            ids = [self.database.addSong(**info) for info in infos]
            if playlist_id and self.database.getPlaylist(playlist_id):
                self.database.addToPlaylist(playlist_id, ids)
            if self.settings.get("autoLyrics"):
                for song in self.database.getSongs(ids):
                    self._fetch_lyrics(song)
            self._notify(f"Importati {len(ids)} brani" if ids else "Nessun file audio trovato")
        self._async("import_files", read, done)

    def _playlist_action(self, action, p):
        db = self.database
        if action == "playlist_create":
            name = str(p.get("name") or "").strip()
            if not name:
                raise ValueError("Nome della playlist mancante")
            playlist_id = db.createPlaylist(name, p.get("description") or "", p.get("cover"))
            if p.get("ids"):
                db.addToPlaylist(playlist_id, [s["id"] for s in db.getSongs(p["ids"])])
            if p.get("entries"):
                if self.settings.get("streamOnly"):
                    self._stream_entries(p["entries"], playlist_id)
                else:
                    self._enqueue_entries(p["entries"], playlist_id)
            return
        if action == "playlist_order":
            ids = p.get("ids") or []
            if len(ids) != len(set(ids)) or set(ids) != {row["id"] for row in db.playlists()}:
                raise ValueError("Ordine delle playlist non valido")
            db.setPlaylistsOrder(ids)
            return
        if action == "playlist_join":
            self._join_code(p.get("code"), "playlist")
            return
        playlist = self._playlist(p["id"])
        playlist_id = playlist["id"]
        if action == "playlist_edit":
            name = str(p.get("name", playlist["name"])).strip()
            if not name:
                raise ValueError("Nome della playlist mancante")
            db.updatePlaylist(playlist_id, name, p.get("description", playlist["description"]), p.get("cover", playlist["cover"]))
        elif action == "playlist_delete":
            self.shared.stopSharing(playlist_id)
            db.deletePlaylist(playlist_id)
        elif action == "playlist_add":
            ids = [song["id"] for song in db.getSongs(p.get("ids") or [])]
            if not p.get("allowDuplicates"):
                existing = {song["id"] for song in db.playlistSongs(playlist_id)}
                ids = [i for i in dict.fromkeys(ids) if i not in existing]
            for song_id in ids:
                db.updateSong(song_id, hidden=0)
            db.addToPlaylist(playlist_id, ids)
        elif action == "playlist_remove":
            entries = db.playlistSongs(playlist_id)
            ids, entry_ids = set(p.get("ids") or []), set(p.get("entryIds") or [])
            db.removeEntries([song["entryId"] for song in entries if song["entryId"] in entry_ids or song["id"] in ids])
        elif action == "playlist_reorder":
            entry_ids = p.get("entryIds") or []
            if len(entry_ids) != len(set(entry_ids)) or set(entry_ids) != {song["entryId"] for song in db.playlistSongs(playlist_id)}:
                raise ValueError("Ordine dei brani non valido")
            db.setPlaylistOrder(entry_ids)
        elif action == "playlist_share":
            self.shared.share(playlist_id)
        elif action == "playlist_unshare":
            self.shared.stopSharing(playlist_id)
        else:
            raise ValueError("Comando playlist non supportato")

    def _effects(self, values):
        effects = self._validated_effects(values, self.effects_for_song(self.player.currentSong()))
        if self.together.inRoom():
            self.settings.set("effects", dict(self.song_effects(), bassBoost=effects["bassBoost"]))
            self.together.setLocalEffects(effects)
        else:
            self.settings.set("effects", effects)
        self._apply_effects(effects)
        self.settings.save()

    @staticmethod
    def _validated_effects(values, base=None):
        if not isinstance(values, dict):
            raise ValueError("Effetti non validi")
        effects = dict(base or DEFAULT_EFFECTS)
        limits = {"rate": (.5, 2.), "reverbWet": (0., 1.), "reverbSize": (.2, 6.), "bassBoost": (0., 1.)}
        for key, value in values.items():
            if key == "keepPitch":
                effects[key] = bool(value)
            elif key in limits:
                effects[key] = _number(value, *limits[key])
            else:
                raise ValueError("Effetto non valido")
        return effects

    def _eq(self, values):
        from sonus_core.audio_engine import EQ_PRESETS
        gains = list(self.settings.get("eqGains") or [0.] * 10)
        custom = dict(self.settings.get("eqCustomPresets") or {})
        preset = values.get("preset", self.settings.get("eqPreset"))
        if "preset" in values:
            if preset in EQ_PRESETS:
                gains = list(EQ_PRESETS[preset])
            elif preset in custom:
                gains = list(custom[preset])
            elif preset != "Personalizzato":
                raise ValueError("Preset non trovato")
        if "gains" in values:
            if not isinstance(values["gains"], list) or len(values["gains"]) != 10:
                raise ValueError("Servono 10 bande")
            gains = [_number(value, -12, 12) for value in values["gains"]]
            preset = "Personalizzato"
        shapes = {"bass": [1., 1., .8, .4, .1, 0, 0, 0, 0, 0],
                  "mid": [0, 0, 0, .3, .8, 1., .8, .3, 0, 0],
                  "treble": [0, 0, 0, 0, 0, 0, .3, .7, 1., 1.]}
        for name, delta in (values.get("macro") or {}).items():
            if name not in shapes:
                raise ValueError("Controllo EQ non valido")
            delta = _number(delta, -24, 24)
            gains = [max(-12, min(12, gain + weight * delta)) for gain, weight in zip(gains, shapes[name])]
            preset = "Personalizzato"
        if values.get("savePreset"):
            preset = str(values["savePreset"]).strip()
            if not preset or preset in EQ_PRESETS or preset == "Personalizzato":
                raise ValueError("Nome preset riservato")
            custom[preset] = list(gains)
        if values.get("deletePreset"):
            custom.pop(str(values["deletePreset"]), None)
            if preset == values["deletePreset"]:
                preset = "Personalizzato"
        enabled = bool(values.get("enabled", True if values.get("macro") or ("preset" in values and preset != "Piatto") else self.settings.get("eqEnabled")))
        preamp = _number(values.get("preamp", self.settings.get("eqPreamp") or 0), -12, 12)
        balance = int(_number(values.get("balance", self.settings.get("eqBalance") or 0), -100, 100))
        for key, value in {"eqGains": gains, "eqEnabled": enabled, "eqPreamp": preamp, "eqBalance": balance,
                           "eqPreset": preset, "eqCustomPresets": custom}.items():
            self.settings.set(key, value)
        self._apply_eq()
        self.settings.save()

    def _loop(self, action, p):
        if action == "loop_clear":
            self.player.setLoop(None)
            return
        if action == "loop_select":
            loop = p.get("loop")
            if not isinstance(loop, dict):
                raise ValueError("Loop non valido")
            self._validate_range(loop, self._song(loop.get("songId")))
            song = self._song(loop.get("songId"))
            if not self.player.currentSong() or self.player.currentSong()["id"] != song["id"]:
                self.player.playSongs([song], 0)
            self.player.setLoop(loop)
            return
        if action == "loop_delete":
            self.database.deleteLoop(p["loopId"])
            if self.player.activeLoop and self.player.activeLoop.get("id") == p["loopId"]:
                self.player.setLoop(None)
            return
        if action != "loop_save":
            raise ValueError("Comando loop non supportato")
        song = self._song(p.get("id"))
        start, end = self._validate_range(p, song)
        name = str(p.get("name") or "Loop A-B").strip()
        if p.get("loopId"):
            if p["loopId"] not in {loop["id"] for loop in self.database.loops(song["id"])}:
                raise ValueError("Loop non trovato")
            self.database.updateLoop(p["loopId"], name, start, end)
            if self.player.activeLoop and self.player.activeLoop.get("id") == p["loopId"]:
                self.player.setLoop(dict(self.player.activeLoop, name=name, startMs=start, endMs=end))
        else:
            self.database.addLoop(song["id"], name, start, end)

    def _validate_range(self, p, song):
        start, end = int(p["startMs"]), int(p["endMs"])
        duration = float(song.get("duration") or 0) * 1000
        if start < 0 or end - start < 100 or (duration and end > duration + 20):
            raise ValueError("Selezione non valida: servono almeno 100 ms entro il brano")
        return start, end

    def _local_audio(self, song, done):
        from sonus_core.database import isStreamPath, streamTarget
        if not isStreamPath(song["path"]):
            if not os.path.isfile(song["path"]):
                raise ValueError("File audio non trovato")
            done(song)
            return
        target = streamTarget(song["path"])
        if target.startswith("roomfile:"):
            path = self.together.roomFilePaths.get(target[len("roomfile:"):].partition("|")[0])
            if not path or not os.path.isfile(path):
                raise ValueError("Il file della stanza non è ancora arrivato")
            done(dict(song, path=path, streamOrigin=song["path"]))
        else:
            self._async("prepare_audio", lambda: self.downloader.downloadTempAudio(target),
                        lambda path: done(dict(song, path=path, streamOrigin=song["path"])))

    def _render(self, action, source, local, p):
        start, end = self._validate_range(p, source) if action == "cut" else (0, 0)
        remove = bool(p.get("removeSelection"))
        if action == "cut" and remove and start <= 5 and end >= float(source.get("duration") or 0) * 1000 - 5:
            raise ValueError("Non puoi rimuovere tutto il brano")
        replace = action == "cut" and bool(p.get("replace"))
        title = source["title"] if replace else str(p.get("title") or source["title"] + (" (taglio)" if action == "cut" else " (effetti)"))
        extension = os.path.splitext(local["path"])[1] if replace else str(p.get("format") or ".mp3")
        if not extension.startswith("."):
            extension = "." + extension
        if extension not in (".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".webm"):
            raise ValueError("Formato audio non supportato")
        if action == "export":
            extension = ".mp3"
        output = None
        output_folder = self.config.TEMP_DIR if replace else self.settings.musicDir()
        effects = dict(self.effects_for_song(source))
        quality = self.settings.get("audioQuality")
        operation = {"mode": "remove" if remove else "keep", "startMs": start, "endMs": end}
        if replace and self.player.currentSong() and self.player.currentSong()["id"] == source["id"]:
            self.player.pause()
        def work():
            nonlocal output
            # The render worker is serial: choose a name when work actually starts,
            # after previous output files exist, rather than when commands enqueue.
            output = self.audio_tools.uniquePath(output_folder, self.audio_tools.safeFileName(title), extension)
            try:
                if action == "cut":
                    self.audio_tools.cutAudio(local["path"], output, start, end, remove,
                                               int(p.get("fadeInMs") or 0), int(p.get("fadeOutMs") or 0), quality)
                else:
                    self.audio_tools.renderWithEffects(local["path"], output, effects["rate"], effects["keepPitch"],
                                                       effects["reverbWet"], effects["reverbSize"], quality, effects["bassBoost"])
                self.metadata.writeMp3Tags(output, title, source.get("artist") or "", source.get("album") or "", source.get("cover"))
                return self.metadata.readTags(output)
            except Exception:
                self._remove_files([output])
                raise
        def done(info):
            fresh = self.database.getSong(source["id"])
            if fresh is None:
                self._remove_files([output])
                raise ValueError("Il brano originale è stato eliminato durante l'elaborazione")
            fields = {}
            if action == "cut":
                cut_info = _cut_info(fresh) or {"sourceTitle": fresh["title"], "sourceArtist": fresh.get("artist"),
                            "sourceAlbum": fresh.get("album"), "sourceDuration": fresh.get("duration"), "operations": []}
                cut_info["operations"] = list(cut_info.get("operations") or []) + [operation]
                fields["cutInfo"] = json.dumps(cut_info)
                synced = self.lyrics.applyCutsToSynced(fresh.get("syncedLyrics") or "", [operation])
                fields.update(syncedLyrics=synced or None, lyrics=self.lyrics.plainFromSynced(synced) if synced else None,
                              lyricsChecked=1 if synced else 0)
            else:
                synced = self.lyrics.scaleSynced(fresh.get("syncedLyrics") or "", effects["rate"])
                fields.update(syncedLyrics=synced or None, lyrics=self.lyrics.plainFromSynced(synced) if synced else fresh.get("lyrics"),
                              lyricsChecked=fresh.get("lyricsChecked", 0))
            if replace:
                target = self.audio_tools.uniquePath(self.settings.musicDir(), self.audio_tools.safeFileName(title), extension) if local.get("streamOrigin") else source["path"]
                current = self.player.currentSong()
                is_current = current and current["id"] == source["id"]
                if is_current:
                    from sonus_mobile.runtime import QUrl
                    self.player.mediaPlayer.stop()
                    self.player.mediaPlayer.setSource(QUrl())
                os.replace(output, target)
                self.database.updateSong(source["id"], path=target, duration=info["duration"], source="cut", hidden=0, **fields)
                for loop in self.database.loops(source["id"]):
                    if loop["startMs"] >= info["duration"] * 1000:
                        self.database.deleteLoop(loop["id"])
                    elif loop["endMs"] > info["duration"] * 1000:
                        self.database.updateLoop(loop["id"], endMs=int(info["duration"] * 1000))
                self._updated(source["id"])
                if is_current:
                    self.player._loadCurrent(autoplay=False)
            else:
                song_id = self.database.addSong(output, title, source.get("artist") or "", source.get("album") or "",
                                                info["duration"], source.get("cover"), "cut", source.get("url"))
                self.database.updateSong(song_id, **fields)
                if p.get("playlistId") and self.database.getPlaylist(p["playlistId"]):
                    self.database.addToPlaylist(p["playlistId"], [song_id])
            self.export_path = target if replace else output
            self._notify("Audio pronto: " + title)
        self._async(action, work, done, pool=self.render_pool)

    def _save_room_audio(self, song, local):
        target = self.audio_tools.uniquePath(self.settings.musicDir(), self.audio_tools.safeFileName(song["title"]), os.path.splitext(local["path"])[1] or ".mp3")
        self._async("download_song", lambda: shutil.copy2(local["path"], target),
                    lambda _: (self.database.updateSong(song["id"], path=target, source="local", hidden=0), self._updated(song["id"])))

    def _fetch_lyrics(self, song, force=False):
        song_id = song["id"]
        if song_id in self._lyrics_pending or (not force and (song.get("lyricsChecked") or not song.get("lyricsAuto", 1))):
            return
        self._lyrics_pending.add(song_id)
        version = self._lyrics_versions.get(song_id, 0)
        cut = _cut_info(song)
        title = (cut or {}).get("sourceTitle") or song["title"]
        artist = (cut or {}).get("sourceArtist") or song.get("artist") or ""
        album = (cut or {}).get("sourceAlbum") or song.get("album") or ""
        duration = (cut or {}).get("sourceDuration") or song.get("duration") or 0
        def done(result):
            self._lyrics_pending.discard(song_id)
            self._lyrics_retries.pop(song_id, None)
            if version != self._lyrics_versions.get(song_id, 0) or not self.database.getSong(song_id):
                return
            self.database.updateSong(song_id, lyrics=result["plain"] if result else None,
                                     syncedLyrics=result["synced"] if result else None, lyricsChecked=1)
            self._updated(song_id)
            if force and not result:
                self._notify("Testo non trovato")
        def failure(error):
            self._lyrics_pending.discard(song_id)
            count = self._lyrics_retries.get(song_id, 0)
            if count < 3 and version == self._lyrics_versions.get(song_id, 0):
                self._lyrics_retries[song_id] = count + 1
                def retry():
                    fresh = self.database.getSong(song_id)
                    if fresh and not self.closed and version == self._lyrics_versions.get(song_id, 0):
                        self._fetch_lyrics(fresh, force)
                self._retry_handles.append(self.runtime.call_later(90 * (count + 1), retry))
            if force:
                self._fail("lyrics_fetch", "Servizio testi non disponibile: " + str(error))
        self._async("lyrics_fetch", lambda: self.lyrics.adaptToCut(self.lyrics.fetchLyrics(title, artist, album, duration), cut), done, failure)

    def _song_started(self, song_id):
        if self.closed:
            return
        self.database.registerPlay(song_id)
        if self.settings.get("autoLyrics"):
            self._fetch_lyrics(self._song(song_id))
        self._dirty()

    def _song_changed(self, song):
        if self.closed:
            return
        if not self._initializing:
            self._refresh_video()
        self._dirty()

    def _video_action(self, action, p):
        song = self._song(p.get("id"))
        if action == "video_remove":
            old = song.get("videoPath")
            self.database.updateSong(song["id"], videoPath=None, videoUrl=None, videoChecked=1, videoAuto=0)
            self._video_key = None
            self._updated(song["id"])
            if old and _inside(old, self.settings.musicDir()):
                self._async(action, lambda: self._remove_files([old]))
        elif action == "video_download":
            url = p.get("url") or song.get("videoUrl") or song.get("url")
            if not url:
                raise ValueError("URL del video mancante")
            self.downloads.enqueue({"kind": "video", "songId": song["id"], "url": url,
                                    "title": "Video: " + song["title"], "baseName": song["title"]})
        else:
            path, url = p.get("path"), p.get("url")
            if path and not os.path.isfile(path):
                raise ValueError("File video non trovato")
            if not path and not url:
                raise ValueError("Video mancante")
            self.database.updateSong(song["id"], videoPath=path, videoUrl=url, videoChecked=1, videoAuto=1)
            self._video_key = None
            self._updated(song["id"])
        self._refresh_video()

    def _video_downloaded(self, result):
        if self.closed:
            return
        song = self.database.getSong(result["songId"])
        if not song:
            return
        self.database.updateSong(song["id"], videoPath=result["videoPath"], videoUrl=result.get("videoUrl"), videoChecked=1)
        old = song.get("videoPath")
        if old and old != result["videoPath"] and _inside(old, self.settings.musicDir()):
            self._async("video_cleanup", lambda: self._remove_files([old]))
        self._video_key = None
        self._updated(song["id"])
        self._refresh_video()

    def _refresh_video(self):
        self._video_key = None
        song = self.player.currentSong()
        if not song:
            self.video = {"url": None, "headers": {}, "loading": False}
            return
        song = self.database.getSong(song["id"]) or song
        if not song.get("videoAuto", 1):
            self.video = {"url": None, "headers": {}, "loading": False}
            return
        path = song.get("videoPath")
        if path and os.path.isfile(path):
            self.video = {"url": path, "headers": {}, "loading": False}
            return
        target = song.get("videoUrl") or song.get("url")
        if not target and str(song.get("path") or "").startswith("stream:"):
            target = song["path"][len("stream:"):]
        if not target or not self.settings.get("streamVideo") or (not self._foreground and self.settings.get("pauseVideoInBackground")):
            self.video = {"url": None, "headers": {}, "loading": False}
            return
        key = str(self.settings.get("videoQuality")) + ":" + target
        self._video_key = key
        cached = self._video_cache.get(key)
        if cached and time.monotonic() - cached[0] < (14400 if cached[1] else 600):
            self.video = {"url": cached[1], "headers": self.downloader.videoHeaders(cached[1]), "loading": False}
            return
        self.video = {"url": None, "headers": {}, "loading": True}
        if key in self._video_pending:
            return
        self._video_pending.add(key)
        def done(url):
            self._video_pending.discard(key)
            self._video_cache[key] = (time.monotonic(), url)
            if self._video_key == key:
                self.video = {"url": url, "headers": self.downloader.videoHeaders(url), "loading": False}
        def failure(error):
            done(None)
            self._notify("Video non disponibile: " + str(error))
        self._async("video_stream", lambda: self.downloader.resolveVideoStream(target, int(self.settings.get("videoQuality") or 720)), done, failure)

    def _join_code(self, text, expected=None):
        from sonus_core.session_link import parseCode
        parsed = parseCode(text)
        if not parsed or (expected and parsed[0] != expected):
            raise ValueError("Codice di condivisione non valido")
        kind, code = parsed
        if kind == "room":
            self.together.joinRoom(code)
        else:
            self.shared.addShared(code)

    def _profile(self, p):
        name = str(p.get("name", self.together.profile()["name"]) or "").strip()[:48]
        if not name:
            raise ValueError("Nome profilo mancante")
        def done(photo):
            self.settings.set("profileName", name)
            self.settings.set("profilePhoto", photo)
            self.settings.save()
            self.together.updateProfile()
        photo = p.get("photo", self.settings.get("profilePhoto") or "")
        if photo and os.path.isfile(photo):
            def read():
                from PIL import Image, ImageOps
                with Image.open(photo) as image:
                    image = ImageOps.fit(image.convert("RGB"), (96, 96))
                    buffer = io.BytesIO()
                    image.save(buffer, "JPEG", quality=75)
                    return base64.b64encode(buffer.getvalue()).decode("ascii")
            self._async("profile", read, done)
        else:
            if photo:
                raw = base64.b64decode(photo, validate=True)
                if len(raw) > 12000:
                    raise ValueError("Foto profilo troppo grande")
            done(photo)

    def _settings(self, values):
        allowed = (set(self.config.DEFAULT_SETTINGS) | {"stopAfterCurrent"}) - {"lastQueue", "lastSongId", "lastPosition", "windowGeometry", "musicDir"}
        if set(values) - allowed:
            raise ValueError("Impostazione non supportata")
        values = self._validated_settings(values)
        for key, value in values.items():
            self.settings.set(key, value)
        self.settings.save()
        self._apply_eq()
        self._apply_effects(self.effects_for_song(self.player.currentSong()))
        if "volume" in values:
            self.player.setVolume(values["volume"])
        if "muted" in values:
            self.player.setMuted(bool(values["muted"]))
        if "repeatMode" in values:
            self.player.setRepeat(int(values["repeatMode"]) % 3)
        if "shuffle" in values:
            self.player.setShuffle(bool(values["shuffle"]))
        if "stopAfterCurrent" in values:
            self.player.stopAfterCurrent = bool(values["stopAfterCurrent"])
        if values.get("autoLyrics") and self.player.currentSong():
            self._fetch_lyrics(self._song())
        self._video_key = None
        self._refresh_video()

    def _validated_settings(self, values):
        from sonus_core.audio_engine import EQ_PRESETS
        normalized = dict(values)
        ranges = {"volume": (0, 100), "repeatMode": (0, 2), "playbackRate": (.5, 2),
                  "eqPreamp": (-12, 12), "eqBalance": (-100, 100), "roomDelayMs": (0, 3000),
                  "searchResults": (1, 100), "videoFps": (0, 60)}
        def gains(value):
            if not isinstance(value, list) or len(value) != 10:
                raise ValueError("Servono 10 bande EQ")
            return [_number(gain, -12, 12) for gain in value]
        for key, value in values.items():
            default = self.config.DEFAULT_SETTINGS.get(key)
            if key == "effects":
                normalized[key] = self._validated_effects(value, self.song_effects())
            elif key == "eqGains":
                normalized[key] = gains(value) if value is not None else None
            elif key == "eqCustomPresets":
                if not isinstance(value, dict) or any(not isinstance(name, str) or name in EQ_PRESETS for name in value):
                    raise ValueError("Preset EQ non validi")
                normalized[key] = {name: gains(curve) for name, curve in value.items()}
            elif key == "themeColors":
                if not isinstance(value, dict) or any(not isinstance(name, str) or not isinstance(color, str) for name, color in value.items()):
                    raise ValueError("Colori non validi")
            elif key in ranges:
                number = _number(value, *ranges[key])
                normalized[key] = number if key in ("playbackRate", "eqPreamp") else int(number)
            elif isinstance(default, bool) or key == "stopAfterCurrent":
                if not isinstance(value, (bool, int)) or value not in (True, False, 0, 1):
                    raise ValueError("Impostazione booleana non valida: " + key)
                normalized[key] = bool(value)
            elif isinstance(default, str) and not isinstance(value, str):
                raise ValueError("Impostazione di testo non valida: " + key)
        return normalized

    def _check_android_release(self):
        # Android release tags/assets are deliberately separate from Sonus_Setup.exe.
        from sonus_core.app_updater import versionTuple
        request = urllib.request.Request(f"https://api.github.com/repos/{self.config.UPDATE_REPO}/releases?per_page=50",
                                         headers={"User-Agent": "Sonus-Android/" + self.config.VERSION,
                                                  "Accept": "application/vnd.github+json"})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                releases = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return {"available": False, "channel": "android", "message": "Nessuna release Android pubblicata"}
            raise
        candidates = []
        for release in releases:
            if release.get("draft") or release.get("prerelease") or not str(release.get("tag_name") or "").lower().startswith("android-"):
                continue
            asset = next((asset for asset in release.get("assets", []) if asset.get("name", "").lower().endswith(".apk")), None)
            if asset:
                candidates.append((versionTuple(release["tag_name"]), release, asset))
        if not candidates:
            return {"available": False, "channel": "android", "message": "Nessuna release Android pubblicata"}
        version, release, asset = max(candidates, key=lambda item: item[0])
        return {"available": version > versionTuple(self.config.VERSION), "channel": "android", "version": release["tag_name"],
                "url": asset["browser_download_url"], "page": release["html_url"], "notes": release.get("body") or "",
                "size": asset.get("size") or 0, "name": asset["name"]}

    def _update_info(self, info, manual=False):
        self.update = info
        if manual or info.get("available"):
            self._notify(info.get("message") or ("Aggiornamento Android disponibile" if info.get("available") else "Versione Android già aggiornata"))

    def _startup_updates(self):
        if self.closed or not self.settings.get("autoCheckUpdates"):
            return
        from sonus_core.updater import checkForEngineUpdate
        self._async("engine_check", lambda: checkForEngineUpdate(False),
                    lambda updated: self._notify("Motore YouTube aggiornato: riavvia l'app") if updated else None,
                    lambda error: None)
        self._async("update_check", self._check_android_release, self._update_info, lambda error: None)

    @staticmethod
    def _remove_files(paths):
        failures = []
        for path in paths:
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except OSError as error:
                failures.append(str(error))
        if failures:
            raise OSError("; ".join(failures))

    def _save_playback_settings(self):
        for key, value in {"volume": self.player.volume, "muted": self.player.muted,
                           "repeatMode": self.player.repeatMode, "shuffle": self.player.shuffle,
                           "stopAfterCurrent": self.player.stopAfterCurrent}.items():
            self.settings.set(key, value)
        self.settings.save()

    def _persist(self):
        current = self.player.currentSong()
        self.settings.set("lastQueue", [song["id"] for song in self.player.queue][:2000])
        self.settings.set("lastSongId", (current or {}).get("id"))
        self.settings.set("lastPosition", int(self.player.position()))
        self._save_playback_settings()

    def _periodic_save(self):
        if self.closed:
            return
        self._persist()
        self._save_handle = self.runtime.call_later(10, self._periodic_save)

    def close(self):
        if self.closed:
            return
        close_error = None
        try:
            self._persist()
        except Exception as error:
            close_error = error
        self.closed, self.ready = True, False
        for handle in [self._dirty_handle, self._tick_handle, self._save_handle] + self._retry_handles:
            if handle:
                handle.cancel()
        operations = [self.shared.stopAll, self.together.leaveRoom, self.together.fileTimer.stop,
                      self.player.shutdown, self.render_pool.deleteLater, self.database.close]
        operations.extend(obj.deleteLater for obj in (self.shared, self.together, self.downloads, self.player))
        for cleanup in operations:
            try:
                cleanup()
            except Exception as error:
                close_error = close_error or error
        if close_error is not None:
            raise close_error
