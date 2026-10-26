"""Mobile operations tested against the generated PC database, player and protocols."""
import importlib
import json
import os
import threading
import time
import wave
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "android/app/src/main/python"), str(REPO / "android/app/build/generated/python")]


@pytest.fixture
def mobile(tmp_path, monkeypatch):
    monkeypatch.setenv("SONUS_DATA_DIR", str(tmp_path))
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    from sonus_mobile.runtime import Runtime
    from sonus_core import config
    monkeypatch.setattr(config, "SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "library.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "TEMP_DIR", str(tmp_path))
    monkeypatch.setattr(config, "DEFAULT_MUSIC_DIR", str(tmp_path))
    monkeypatch.setattr(config, "COVERS_DIR", str(tmp_path))
    monkeypatch.setattr(config, "settings", config.Settings())
    config.settings.set("musicDir", str(tmp_path))
    config.settings.set("autoLyrics", False)
    config.settings.set("autoVideo", False)
    config.settings.set("streamVideo", False)
    config.settings.set("autoCheckUpdates", False)
    for name in ("downloader", "together", "playlist_sync", "session_link"):
        module = importlib.import_module("sonus_core." + name)
        if hasattr(module, "settings"):
            monkeypatch.setattr(module, "settings", config.settings)
        for key in ("TEMP_DIR", "COVERS_DIR"):
            if hasattr(module, key):
                monkeypatch.setattr(module, key, str(tmp_path))
    from sonus_core import metadata
    monkeypatch.setattr(metadata, "COVERS_DIR", str(tmp_path))
    from sonus_mobile.controller import Controller
    runtime = Runtime().start()
    events = []
    controller = runtime.call_sync(lambda: Controller(runtime, lambda state: events.append(state)))
    yield runtime, controller, events, tmp_path
    runtime.call_sync(controller.close)
    runtime.close()


def act(mobile, action, **payload):
    runtime, controller, *_ = mobile
    return runtime.call_sync(controller.dispatch, action, payload)


def snap(mobile):
    runtime, controller, *_ = mobile
    return runtime.call_sync(controller.snapshot)


def add(mobile, title="Test", **fields):
    runtime, controller, _, folder = mobile
    def create():
        song_id = controller.database.addSong(str(folder / (title + ".wav")), title, "Artist", duration=10)
        controller.database.updateSong(song_id, **fields)
        return song_id
    return runtime.call_sync(create)


def wait_for(mobile, condition, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        state = snap(mobile)
        if condition(state):
            return state
        time.sleep(.02)
    raise AssertionError(snap(mobile))


def test_library_playlist_duplicates_entry_removal_and_order(mobile):
    first, second = add(mobile, "First"), add(mobile, "Second")
    act(mobile, "playlist_create", name="Mix", description="Mobile")
    playlist_id = snap(mobile)["playlists"][0]["id"]
    act(mobile, "playlist_add", id=playlist_id, ids=[first, second, first], allowDuplicates=True)
    rows = snap(mobile)["playlists"][0]["songs"]
    assert [row["id"] for row in rows] == [first, second, first]
    act(mobile, "playlist_reorder", id=playlist_id, entryIds=[r["entryId"] for r in reversed(rows)])
    act(mobile, "playlist_remove", id=playlist_id, entryIds=[rows[0]["entryId"]])
    assert [r["id"] for r in snap(mobile)["playlists"][0]["songs"]] == [first, second]
    act(mobile, "favorite", id=first)
    assert snap(mobile)["favorites"][0]["id"] == first
    act(mobile, "song_edit", id=first, fields={"title": "Renamed", "lyricsAuto": 0})
    assert next(r for r in snap(mobile)["songs"] if r["id"] == first)["title"] == "Renamed"
    act(mobile, "song_delete", ids=[second], deleteFiles=False)
    assert len(snap(mobile)["songs"]) == 1


def test_lyrics_loops_effects_equalizer_and_validation(mobile):
    song_id = add(mobile)
    act(mobile, "lyrics_set", id=song_id, plain="One\nTwo", synced="[00:01.00]One\n[00:03.00]Two")
    act(mobile, "loop_save", id=song_id, name="Verse", startMs=1000, endMs=4000)
    row = snap(mobile)["songs"][0]
    assert row["syncedLyrics"].endswith("Two")
    assert snap(mobile)["songLoops"][str(song_id)][0]["startMs"] == 1000
    act(mobile, "effects", values={"rate": .85, "keepPitch": False, "reverbWet": .4, "bassBoost": .3})
    act(mobile, "eq", values={"preset": "Rock", "balance": -25, "preamp": -3, "savePreset": "Personal"})
    state = snap(mobile)
    assert state["effects"]["rate"] == .85
    assert state["eq"]["enabled"] and state["eq"]["customPresets"]["Personal"] == state["eq"]["gains"]
    act(mobile, "eq", values={"gains": [0]})
    assert snap(mobile)["error"]["action"] == "eq"
    act(mobile, "loop_save", id=song_id, startMs=4000, endMs=1000)
    assert snap(mobile)["error"]["action"] == "loop_save"
    act(mobile, "lyrics_remove", id=song_id)
    assert snap(mobile)["songs"][0]["lyricsChecked"] == 1


def test_import_worker_and_owner_thread(mobile):
    runtime, controller, _, folder = mobile
    path = folder / "audio.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\0\0" * 8000)
    act(mobile, "import_files", paths=[str(path)])
    state = wait_for(mobile, lambda s: len(s["songs"]) == 1)
    assert state["songs"][0]["duration"] == pytest.approx(1)
    assert state["ready"]
    json.dumps(state)
    assert runtime.call_sync(lambda: controller.database.connection.execute("SELECT COUNT(*) FROM songs").fetchone()[0]) == 1


def test_unknown_and_invalid_actions_report_errors(mobile):
    act(mobile, "unknown")
    assert snap(mobile)["error"]["action"] == "unknown"
    act(mobile, "song_edit", id=9999, fields={"title": "x"})
    assert snap(mobile)["error"]["action"] == "song_edit"
    act(mobile, "handle_code", code="bad")
    assert snap(mobile)["error"]["action"] == "handle_code"


def test_search_network_boundary_and_stale_results(mobile, monkeypatch):
    from sonus_core import downloader
    gate = threading.Event()
    def search(query, maxResults=25):
        if query == "old":
            gate.wait(2)
        return {"entries": [{"title": query, "url": "https://youtube.com/watch?v=test"}]}
    monkeypatch.setattr(downloader, "searchYoutube", search)
    act(mobile, "search", query="old")
    act(mobile, "search", query="new")
    wait_for(mobile, lambda s: s["search"]["entries"] and s["search"]["entries"][0]["title"] == "new")
    gate.set()
    time.sleep(.1)
    assert snap(mobile)["search"]["entries"][0]["title"] == "new"


def test_tick_is_small_and_settings_persist(mobile):
    runtime, controller, events, folder = mobile
    act(mobile, "volume", value=42)
    act(mobile, "settings", values={"autoLyrics": False, "songColorCustom": "#123456"})
    events.clear()
    time.sleep(.6)
    assert any(event.get("tick") and "songs" not in event for event in events)
    runtime.call_sync(controller._persist)
    saved = json.loads((folder / "settings.json").read_text())
    assert saved["volume"] == 42 and saved["songColorCustom"] == "#123456"


@pytest.fixture
def real_audio(mobile, monkeypatch):
    from sonus_core import audio_engine, audio_tools, config, downloader
    from sonus_mobile import android_audio
    import imageio_ffmpeg
    executable = imageio_ffmpeg.get_ffmpeg_exe()
    monkeypatch.setattr(audio_engine, "ffmpegExe", lambda: executable)
    monkeypatch.setattr(audio_tools, "ffmpegExe", lambda: executable)
    monkeypatch.setattr(config, "ffmpegExe", lambda: executable)
    monkeypatch.setattr(downloader, "ffmpegExe", lambda: executable)
    # These are the native executable and PCM hardware boundaries only.
    monkeypatch.setattr(downloader, "denoExe", lambda: None)
    class Sink:
        def write(self, data):
            return len(data)
        def close(self):
            pass
    monkeypatch.setattr(android_audio, "_android_sink", lambda *args: Sink())
    monkeypatch.setattr(android_audio, "_java_bytes", lambda data: data)
    return executable


def make_wav(folder, name="Song", seconds=2):
    import struct
    import math
    path = folder / (name + ".wav")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(44100)
        output.writeframes(b"".join(struct.pack("<hh", int(math.sin(i * 2 * math.pi * 120 / 44100) * 4000), 0) for i in range(int(seconds * 44100))))
    return path


def test_real_cut_fades_export_lyrics_and_waveform(mobile, real_audio):
    runtime, controller, _, folder = mobile
    path = make_wav(folder)
    act(mobile, "import_files", paths=[str(path)])
    song_id = wait_for(mobile, lambda s: len(s["songs"]) == 1)["songs"][0]["id"]
    act(mobile, "lyrics_set", id=song_id, plain="One\nTwo", synced="[00:00.50]One\n[00:01.50]Two")
    act(mobile, "waveform", id=song_id)
    state = wait_for(mobile, lambda s: s.get("waveformSongId") == song_id)
    assert len(state["waveform"]) == 600 and max(state["waveform"]) == pytest.approx(1)
    act(mobile, "cut", id=song_id, startMs=400, endMs=1400, fadeInMs=50, fadeOutMs=50, title="Cut", format="wav")
    state = wait_for(mobile, lambda s: len(s["songs"]) == 2)
    cut = next(song for song in state["songs"] if song["title"] == "Cut")
    assert cut["duration"] == pytest.approx(1, abs=.04)
    assert "One" in cut["syncedLyrics"] and "Two" not in cut["syncedLyrics"]
    assert json.loads(cut["cutInfo"])["operations"][0]["mode"] == "keep"
    act(mobile, "effects", values={"rate": 2., "keepPitch": True, "bassBoost": .3})
    act(mobile, "export", id=song_id, title="Rendered")
    state = wait_for(mobile, lambda s: len(s["songs"]) == 3)
    rendered = next(song for song in state["songs"] if song["title"] == "Rendered")
    assert rendered["duration"] == pytest.approx(1, abs=.12)
    assert "[00:00.25]One" in rendered["syncedLyrics"]
    assert Path(state["exportPath"]).is_file()


def test_playback_queue_seek_loop_and_restore(mobile, real_audio):
    runtime, controller, _, folder = mobile
    paths = [make_wav(folder, name, 4) for name in ("A", "B", "C")]
    act(mobile, "import_files", paths=[str(path) for path in paths])
    songs = wait_for(mobile, lambda s: len(s["songs"]) == 3)["songs"]
    ids = [song["id"] for song in songs]
    act(mobile, "play", ids=ids, index=0)
    wait_for(mobile, lambda s: s["playing"] and s["duration"] > 0)
    act(mobile, "pause")
    act(mobile, "seek", position=1250)
    act(mobile, "loop_save", id=ids[0], startMs=1000, endMs=2500, name="Verse")
    loop = snap(mobile)["loops"][0]
    act(mobile, "loop_select", loop=loop)
    assert snap(mobile)["activeLoop"]["id"] == loop["id"]
    act(mobile, "loop_clear")
    act(mobile, "queue_move", **{"from": 2, "to": 1})
    assert [s["id"] for s in snap(mobile)["queue"]] == [ids[0], ids[2], ids[1]]
    act(mobile, "queue_remove", indexes=[2])
    assert len(snap(mobile)["queue"]) == 2
    runtime.call_sync(controller._persist)
    saved = json.loads((folder / "settings.json").read_text())
    assert saved["lastQueue"] == [ids[0], ids[2]]
    assert 1100 <= saved["lastPosition"] <= 1400


def test_real_download_conversion_retry_and_identity(mobile, real_audio, monkeypatch):
    from sonus_core import downloader
    runtime, controller, _, folder = mobile
    source = make_wav(folder)
    calls = []
    def remote(options, target, download):
        calls.append(target)
        if len(calls) == 1:
            raise RuntimeError("network unavailable")
        if download:
            output = options["outtmpl"].replace("%(ext)s", "wav")
            Path(output).write_bytes(source.read_bytes())
            for hook in options.get("progress_hooks", []):
                hook({"status": "finished"})
        return {"title": "Artist - Remote", "duration": 2, "webpage_url": target}
    monkeypatch.setattr(downloader, "_runYoutube", remote)
    url = "https://www.youtube.com/watch?v=abcdefghijk"
    song_id = runtime.call_sync(controller.database.addStreamSong, url, "My title", "My artist")
    act(mobile, "download_song", ids=[song_id])
    wait_for(mobile, lambda s: s["downloads"] and s["downloads"][0]["status"] == "error")
    act(mobile, "download_retry", index=0)
    state = wait_for(mobile, lambda s: s["downloads"] and s["downloads"][0]["status"] == "done")
    song = next(song for song in state["songs"] if song["id"] == song_id)
    assert song["title"] == "My title" and Path(song["path"]).is_file()
    assert song["duration"] == pytest.approx(2, abs=.1)
    act(mobile, "stream_only", id=song_id)
    wait_for(mobile, lambda s: not s["tasks"])
    assert snap(mobile)["songs"][0]["path"] == "stream:" + url


def test_room_shared_playlist_profile_protocol(mobile, monkeypatch):
    from sonus_core.session_link import Link, CodeBox
    from PIL import Image
    runtime, controller, _, folder = mobile
    # Prevent the MQTT transport from connecting; use its real encrypted queues.
    monkeypatch.setattr(Link, "_connect", lambda self: None)
    act(mobile, "room_create")
    room = snap(mobile)["room"]
    assert room["code"].startswith("SONUS-")
    act(mobile, "room_delay", value=120)
    assert snap(mobile)["room"]["delayMs"] == 120
    photo = folder / "photo.png"
    Image.new("RGB", (200, 150), "green").save(photo)
    act(mobile, "profile", name="Mobile", photo=str(photo))
    state = wait_for(mobile, lambda s: s["profile"]["name"] == "Mobile")
    import base64
    assert len(base64.b64decode(state["profile"]["photo"])) < 12000
    act(mobile, "playlist_create", name="Shared")
    playlist_id = snap(mobile)["playlists"][0]["id"]
    act(mobile, "playlist_share", id=playlist_id)
    playlist = snap(mobile)["playlists"][0]
    assert playlist["code"].startswith("SONUSP-") and playlist["link"].startswith("sonus://")
    def decode():
        raw = controller.shared.link.retainedOut[(playlist["code"], "snapshot")]
        return CodeBox(playlist["code"]).open(raw)
    assert runtime.call_sync(decode)["name"] == "Shared"
    act(mobile, "playlist_unshare", id=playlist_id)
    assert snap(mobile)["playlists"][0]["code"] is None
    act(mobile, "room_leave")
    assert snap(mobile)["room"]["code"] is None


def test_android_update_ignores_windows_assets(mobile, monkeypatch):
    releases = [{"tag_name": "v99.0.0", "assets": [{"name": "Sonus_Setup.exe"}]},
                {"tag_name": "android-v1.1.0", "html_url": "https://github.com/release", "assets":
                 [{"name": "Sonus.apk", "browser_download_url": "https://github.com/release/Sonus.apk", "size": 10}]}]
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return json.dumps(releases).encode()
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
    act(mobile, "update_check")
    state = wait_for(mobile, lambda s: s["update"] is not None)
    assert state["update"]["version"] == "android-v1.1.0" and state["update"]["available"]


def test_ui_payload_aliases_and_playlist_entries(mobile, monkeypatch):
    act(mobile, "shuffle", enabled=True)
    assert snap(mobile)["shuffle"] is True
    act(mobile, "settings", values={"stopAfterCurrent": True})
    assert snap(mobile)["settings"]["stopAfterCurrent"] is True
    act(mobile, "playlist_create", name="Search mix", entries=[{"title": "Track", "artist": "Person", "duration": 30}])
    state = wait_for(mobile, lambda s: s["playlists"] and len(s["playlists"][0]["songs"]) == 1)
    assert state["playlists"][0]["songs"][0]["path"].startswith("stream:ytsearch1:")
    assert isinstance(state["room"]["peers"], list)
    act(mobile, "repeat", value="one")
    assert snap(mobile)["repeat"] == 2


def test_cached_collections_and_partial_mutation_events(mobile, monkeypatch):
    runtime, controller, events, _ = mobile
    add(mobile)
    runtime.call_sync(controller._publish)
    events.clear()
    reads = []
    original = controller.database.allSongs
    def counted():
        reads.append(1)
        return original()
    monkeypatch.setattr(controller.database, "allSongs", counted)
    act(mobile, "volume", value=35)
    time.sleep(.12)
    assert not reads
    mutation = next(event for event in events if "volume" in event)
    assert mutation["tick"] and "songs" not in mutation
    act(mobile, "song_edit", id=1, fields={"title": "Updated"})
    time.sleep(.12)
    assert len(reads) == 1
    assert any("songs" in event for event in events)


def test_lyrics_network_fetch_cut_adaptation_and_manual_search(mobile, monkeypatch):
    from sonus_core import lyrics
    song_id = add(mobile, "Cut", cutInfo=json.dumps({"sourceTitle": "Original", "sourceArtist": "Artist", "sourceDuration": 5,
                     "operations": [{"mode": "keep", "startMs": 1000, "endMs": 4000}]}))
    def request(url, attempts=3):
        item = {"trackName": "Original", "artistName": "Artist", "duration": 5,
                "plainLyrics": "One\nTwo", "syncedLyrics": "[00:00.50]One\n[00:02.00]Two"}
        return [item] if "/search?" in url else item
    monkeypatch.setattr(lyrics, "_getJson", request)
    act(mobile, "lyrics_fetch", id=song_id, force=True)
    state = wait_for(mobile, lambda s: s["songs"][0]["lyricsChecked"] == 1)
    assert "[00:01.00]Two" in state["songs"][0]["syncedLyrics"]
    act(mobile, "lyrics_search", query="Original Artist")
    assert wait_for(mobile, lambda s: bool(s["lyricsResults"]))["lyricsResults"][0]["title"] == "Original"


def test_spotify_client_boundary_and_discovery_http(mobile, monkeypatch):
    import spotify_scraper
    from types import SimpleNamespace as Object
    track = Object(id="abc", name="Spotify song", artists=[Object(name="Artist")],
                   album=Object(name="Album", images=[]), images=[], duration_ms=120000)
    class Client:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def get_track(self, url):
            return track
    monkeypatch.setattr(spotify_scraper, "SpotifyClient", Client)
    act(mobile, "search", query="https://open.spotify.com/track/0VjIjW4GlUZAMYd2vXMi3b")
    state = wait_for(mobile, lambda s: not s["search"]["busy"] and bool(s["search"]["entries"]))
    assert state["search"]["kind"] == "spotify"
    assert state["search"]["entries"][0]["spotify"]["durationMs"] == 120000
    item = {"id": 11, "title": "Discover song", "artist": {"name": "Artist"}, "duration": 100, "album": {"title": "Album"}}
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return json.dumps({"data": [item]}).encode()
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
    act(mobile, "discover_artist", id=11)
    state = wait_for(mobile, lambda s: s["search"]["kind"] == "discover")
    assert state["search"]["entries"][0]["title"] == "Discover song"
    act(mobile, "discover")
    assert wait_for(mobile, lambda s: bool(s["discover"].get("sections")))["discover"]["builtAt"] > 0


def test_video_search_url_headers_download_local_and_remove(mobile, real_audio, monkeypatch):
    from sonus_core import downloader
    runtime, controller, _, folder = mobile
    path = make_wav(folder, "VideoSong", 4)
    act(mobile, "import_files", paths=[str(path)])
    song_id = wait_for(mobile, lambda s: bool(s["songs"]))["songs"][0]["id"]
    target = "https://www.youtube.com/watch?v=abcdefghijk"
    def remote(options, url, download):
        if download:
            Path(options["outtmpl"].replace("%(ext)s", "mp4")).write_bytes(b"video transport bytes")
        return {"id": "abcdefghijk", "title": "Video", "url": "https://example.test/video.mp4", "webpage_url": target,
                "http_headers": {"Referer": "https://youtube.com"}}
    monkeypatch.setattr(downloader, "_runYoutube", remote)
    act(mobile, "video_search", query=target)
    assert wait_for(mobile, lambda s: bool(s["videoResults"]))["videoResults"][0]["url"] == target
    act(mobile, "play", ids=[song_id])
    wait_for(mobile, lambda s: s["playing"])
    act(mobile, "settings", values={"streamVideo": True})
    act(mobile, "video_set", id=song_id, url=target)
    state = wait_for(mobile, lambda s: s["video"]["url"] == "https://example.test/video.mp4")
    assert state["video"]["headers"]["Referer"] == "https://youtube.com"
    act(mobile, "video_download", id=song_id)
    state = wait_for(mobile, lambda s: s["songs"][0]["videoPath"] is not None)
    local = Path(state["songs"][0]["videoPath"])
    assert local.is_file()
    act(mobile, "video_remove", id=song_id)
    state = wait_for(mobile, lambda s: not s["tasks"])
    assert state["songs"][0]["videoAuto"] == 0 and not local.exists()


def test_late_lyrics_result_cannot_overwrite_manual_edit(mobile, monkeypatch):
    from sonus_core import lyrics
    song_id = add(mobile)
    gate = threading.Event()
    def request(url, attempts=3):
        gate.wait(2)
        return {"plainLyrics": "Old", "syncedLyrics": ""}
    monkeypatch.setattr(lyrics, "_getJson", request)
    act(mobile, "lyrics_fetch", id=song_id, force=True)
    act(mobile, "lyrics_set", id=song_id, plain="Edited", synced="")
    gate.set()
    state = wait_for(mobile, lambda s: not s["lyricsPending"])
    assert state["songs"][0]["lyrics"] == "Edited"


def test_controller_reopens_real_database_and_saved_session(mobile, real_audio):
    from sonus_mobile.controller import Controller
    runtime, controller, events, folder = mobile
    path = make_wav(folder, seconds=4)
    act(mobile, "import_files", paths=[str(path)])
    song_id = wait_for(mobile, lambda s: bool(s["songs"]))["songs"][0]["id"]
    act(mobile, "play", ids=[song_id])
    wait_for(mobile, lambda s: s["playing"] and s["duration"] > 0)
    act(mobile, "pause")
    act(mobile, "seek", position=1000)
    runtime.call_sync(controller.close)
    def reopen():
        controller.settings.values.update(json.loads((folder / "settings.json").read_text()))
        return Controller(runtime, events.append)
    reopened = runtime.call_sync(reopen)
    try:
        state = runtime.call_sync(reopened.snapshot)
        assert state["current"]["id"] == song_id and not state["playing"]
        assert len(state["songs"]) == 1 and state["position"] >= 900
    finally:
        runtime.call_sync(reopened.close)


def test_dsp_ranges_match_engine_and_invalid_settings_are_atomic(mobile):
    runtime, controller, _, folder = mobile
    act(mobile, "effects", values={"rate": 3, "reverbSize": 10})
    state = snap(mobile)
    assert state["effects"]["rate"] == runtime.call_sync(controller.player.playbackRate) == 2
    assert state["effects"]["reverbSize"] == 6
    runtime.call_sync(controller._persist)
    before = (folder / "settings.json").read_text()
    act(mobile, "settings", values={"songColorCustom": "#abcdef", "effects": {"rate": "bad"}})
    assert snap(mobile)["error"]["action"] == "settings"
    assert (folder / "settings.json").read_text() == before
    act(mobile, "settings", values={"eqGains": [1]})
    assert snap(mobile)["error"]["action"] == "settings"
    assert (folder / "settings.json").read_text() == before


def test_rapid_same_title_exports_create_distinct_files(mobile, real_audio):
    _, _, _, folder = mobile
    path = make_wav(folder)
    act(mobile, "import_files", paths=[str(path)])
    song_id = wait_for(mobile, lambda s: bool(s["songs"]))["songs"][0]["id"]
    act(mobile, "export", id=song_id, title="Same")
    act(mobile, "export", id=song_id, title="Same")
    state = wait_for(mobile, lambda s: not s["tasks"])
    exported = [row for row in state["songs"] if row["title"] == "Same"]
    assert len(exported) == 2
    assert exported[0]["path"] != exported[1]["path"]


def test_background_stops_visual_work_and_preserves_playback(mobile, real_audio, monkeypatch):
    from sonus_core import downloader
    monkeypatch.setattr(downloader, "resolveVideoStream", lambda *args: "https://example.test/video.mp4")
    runtime, controller, events, folder = mobile
    path = make_wav(folder, seconds=4)
    act(mobile, "import_files", paths=[str(path)])
    song_id = wait_for(mobile, lambda s: bool(s["songs"]))["songs"][0]["id"]
    act(mobile, "play", ids=[song_id])
    wait_for(mobile, lambda s: s["playing"])
    act(mobile, "foreground", active=False)
    spectrum_calls = []
    monkeypatch.setattr(controller.player.mediaPlayer, "spectrum", lambda: spectrum_calls.append(1) or [1])
    events.clear()
    act(mobile, "settings", values={"streamVideo": True})
    act(mobile, "video_set", id=song_id, url="https://youtu.be/abcdefghijk")
    time.sleep(.6)
    assert snap(mobile)["playing"]
    assert not spectrum_calls and not snap(mobile)["video"]["loading"]
    assert any(event.get("tick") and event.get("spectrum") == [] for event in events)


def test_remove_selection_replace_preserves_identity_and_repairs_loops(mobile, real_audio):
    _, _, _, folder = mobile
    path = make_wav(folder, seconds=3)
    act(mobile, "import_files", paths=[str(path)])
    song_id = wait_for(mobile, lambda s: bool(s["songs"]))["songs"][0]["id"]
    act(mobile, "lyrics_set", id=song_id, plain="A\nB\nC", synced="[00:00.25]A\n[00:01.50]B\n[00:02.50]C")
    act(mobile, "loop_save", id=song_id, name="Long", startMs=500, endMs=2800)
    act(mobile, "loop_save", id=song_id, name="Past end", startMs=2500, endMs=2900)
    act(mobile, "cut", id=song_id, startMs=1000, endMs=2000, removeSelection=True, replace=True)
    state = wait_for(mobile, lambda s: not s["tasks"])
    assert len(state["songs"]) == 1 and state["songs"][0]["id"] == song_id
    assert state["songs"][0]["path"] == str(path)
    assert state["songs"][0]["duration"] == pytest.approx(2, abs=.05)
    assert "B" not in state["songs"][0]["syncedLyrics"]
    assert "[00:01.50]C" in state["songs"][0]["syncedLyrics"]
    loops = state["songLoops"][str(song_id)]
    assert len(loops) == 1 and loops[0]["endMs"] == 2000


def test_background_video_resolution_setting_is_honored(mobile, real_audio, monkeypatch):
    from sonus_core import downloader
    calls = []
    monkeypatch.setattr(downloader, "resolveVideoStream", lambda *args: calls.append(args) or "https://example.test/video.mp4")
    _, _, _, folder = mobile
    path = make_wav(folder, seconds=4)
    act(mobile, "import_files", paths=[str(path)])
    song_id = wait_for(mobile, lambda s: bool(s["songs"]))["songs"][0]["id"]
    act(mobile, "play", ids=[song_id])
    wait_for(mobile, lambda s: s["playing"])
    act(mobile, "foreground", active=False)
    act(mobile, "settings", values={"streamVideo": True, "pauseVideoInBackground": False})
    act(mobile, "video_set", id=song_id, url="https://youtu.be/abcdefghijk")
    assert wait_for(mobile, lambda s: s["video"]["url"] == "https://example.test/video.mp4")
    assert calls


def test_close_releases_resources_even_when_persistence_fails(mobile, monkeypatch):
    runtime, controller, _, _ = mobile
    def fail_save():
        raise OSError("storage full")
    monkeypatch.setattr(controller.settings, "save", fail_save)
    with pytest.raises(OSError, match="storage full"):
        runtime.call_sync(controller.close)
    assert controller.closed
    with pytest.raises(Exception, match="closed"):
        runtime.call_sync(controller.database.allSongs)
    assert runtime.call_sync(lambda: controller.player.mediaPlayer.source().isEmpty())


def test_two_controllers_over_real_local_mqtt(mobile, real_audio, monkeypatch):
    """Real Mosquitto TCP transport, original encryption, two SQLite/player owners.

    CI installs Mosquitto. No production server, YouTube request or personal file
    is involved: both members own the generated WAV fixtures by title/artist.
    """
    import shutil
    executable = os.environ.get("SONUS_TEST_MOSQUITTO") or shutil.which("mosquitto")
    if not executable or not Path(executable).is_file():
        pytest.skip("Mosquitto executable is required for real MQTT integration")
    monkeypatch.setenv("PATH", str(Path(executable).parent) + os.pathsep + os.environ.get("PATH", ""))
    from tests.broker import startMosquitto
    from sonus_core import config
    from sonus_mobile.controller import Controller
    from sonus_mobile.runtime import Runtime
    runtime, controller, _, folder = mobile
    port, broker = startMosquitto("allow_anonymous true\n")
    monkeypatch.setenv("SONUS_BROKERS", f"127.0.0.1:{port}:0")
    second_runtime = Runtime().start()
    second = None
    try:
        broker_spec = [("127.0.0.1", port, False, None, None, None)]
        def setup_first():
            controller.together.clientId = "alice"
            controller.together.profileOverride = {"name": "Alice", "photo": ""}
            controller.together.delayOverride = 0
            controller.together.link.brokers = broker_spec
            controller.shared.link.brokers = broker_spec
        runtime.call_sync(setup_first)
        # The production settings module is process-global. These two protocol
        # clients share a test process; avoid unrelated periodic writes racing
        # for that one global settings path. Close still saves each client.
        runtime.call_sync(controller._save_handle.cancel)
        second_folder = folder / "second"
        second_folder.mkdir()
        monkeypatch.setattr(config, "DB_PATH", str(second_folder / "library.db"))
        second_settings = config.Settings()
        second_settings.values.update(controller.settings.values)
        second_settings.set("musicDir", str(second_folder))
        monkeypatch.setattr(config, "settings", second_settings)
        def make_second():
            result = Controller(second_runtime, lambda event: None)
            result.together.clientId = "bruno"
            result.together.profileOverride = {"name": "Bruno", "photo": ""}
            result.together.delayOverride = 0
            return result
        second = second_runtime.call_sync(make_second)
        second_runtime.call_sync(second._save_handle.cancel)
        peer = (second_runtime, second, [], second_folder)
        audio = make_wav(folder, "Fixture", 30)
        def songs_for(member):
            ids = []
            for index, title in enumerate(("First", "Second", "Third")):
                path = folder / (title + ".wav")
                if not path.exists():
                    shutil.copy2(audio, path)
                ids.append(member.database.addSong(str(path), title, "Fixtures", duration=30,
                           url="https://fixtures.invalid/" + str(index)))
            return ids
        first_ids = runtime.call_sync(songs_for, controller)
        second_runtime.call_sync(songs_for, second)
        act(mobile, "play", ids=first_ids, index=0)
        wait_for(mobile, lambda s: s["playing"])
        act(mobile, "room_create")
        room_code = wait_for(mobile, lambda s: s["room"]["connected"])["room"]["code"]
        act(peer, "room_join", code=room_code)
        remote = wait_for(peer, lambda s: s["playing"] and s["current"] and s["current"]["title"] == "First", 20)
        assert [song["title"] for song in remote["queue"]] == ["First", "Second", "Third"]
        wait_for(mobile, lambda s: len(s["room"]["peers"]) == 1)
        act(mobile, "pause")
        wait_for(peer, lambda s: not s["playing"])
        act(mobile, "seek", position=5000)
        wait_for(peer, lambda s: abs(s["position"] - 5000) < 700)
        act(mobile, "effects", values={"rate": 1.25, "keepPitch": True, "reverbWet": 0, "reverbSize": 1.8})
        wait_for(peer, lambda s: abs(s["effects"]["rate"] - 1.25) < .001)
        assert second_runtime.call_sync(second.player.playbackRate) == pytest.approx(1.25)
        act(mobile, "play_pause", playing=True)
        wait_for(peer, lambda s: s["playing"])
        wait_for(peer, lambda s: abs(s["position"] - snap(mobile)["position"]) < 700)
        act(peer, "pause")
        wait_for(mobile, lambda s: not s["playing"])
        act(mobile, "playlist_create", name="Shared fixtures", ids=first_ids)
        playlist_id = snap(mobile)["playlists"][0]["id"]
        act(mobile, "playlist_share", id=playlist_id)
        code = snap(mobile)["playlists"][0]["code"]
        act(peer, "playlist_join", code=code)
        shared = wait_for(peer, lambda s: s["playlists"] and len(s["playlists"][0]["songs"]) == 3)
        remote_playlist = shared["playlists"][0]
        assert remote_playlist["name"] == "Shared fixtures"
        reversed_entries = list(reversed(remote_playlist["songs"]))
        act(peer, "playlist_reorder", id=remote_playlist["id"], entryIds=[song["entryId"] for song in reversed_entries])
        wait_for(mobile, lambda s: [song["title"] for song in s["playlists"][0]["songs"]] == ["Third", "Second", "First"])
        act(peer, "playlist_remove", id=remote_playlist["id"], entryIds=[reversed_entries[0]["entryId"]])
        wait_for(mobile, lambda s: len(s["playlists"][0]["songs"]) == 2)
        act(peer, "playlist_add", id=remote_playlist["id"], ids=[reversed_entries[0]["id"]])
        final = wait_for(mobile, lambda s: len(s["playlists"][0]["songs"]) == 3)
        assert [song["title"] for song in final["playlists"][0]["songs"]] == ["Second", "First", "Third"]
    finally:
        if second is not None:
            second_runtime.call_sync(second.close)
        second_runtime.close()
        runtime.call_sync(controller.together.leaveRoom)
        runtime.call_sync(controller.shared.stopAll)
        broker.terminate()
        broker.wait(5)
