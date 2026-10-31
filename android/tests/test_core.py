"""Exercise generated original Sonus code with Android adapters."""
import base64
import hashlib
import importlib
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import subprocess
import textwrap
import ast

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "android/app/src/main/python"))


class PortableCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (REPO / "android/app/build").mkdir(parents=True, exist_ok=True)
        cls.directory = tempfile.TemporaryDirectory(prefix="core_test_", dir=REPO / "android/app/build", ignore_cleanup_errors=True)
        cls.root = Path(cls.directory.name)
        os.environ["SONUS_DATA_DIR"] = str(cls.root / "data")
        os.environ["SONUS_NATIVE_DIR"] = str(cls.root / "native")
        os.environ["SONUS_PACKAGES_DIR"] = str(cls.root / "packages")

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def setUp(self):
        generator = REPO / "android/tools/prepare_core.py"
        self.assertTrue(generator.is_file(), "Android core generator is not implemented")
        spec = importlib.util.spec_from_file_location("prepare_core", generator)
        self.generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.generator)
        self.generator.prepare_core(REPO, self.root / "generated")
        sys.path.insert(0, str(self.root / "generated"))

    def test_generated_core_imports_without_qt_and_leaves_pc_sources_unchanged(self):
        before = {p.name: hashlib.sha256(p.read_bytes()).digest() for p in (REPO / "app").glob("*.py")}
        self.generator.prepare_core(REPO, self.root / "generated")
        for name in ("config", "database", "workers", "player", "audio_engine", "downloader", "metadata", "lyrics", "discover", "session_link", "playlist_sync", "together", "room_files", "diagnostics", "updater", "migration", "spotify_import", "app_updater", "video_proxy"):
            importlib.import_module("sonus_core." + name)
        after = {p.name: hashlib.sha256(p.read_bytes()).digest() for p in (REPO / "app").glob("*.py")}
        self.assertEqual(before, after)
        # The entry subprocess below checks import isolation from a clean process;
        # the combined PC regression suite may itself import Qt legitimately.

    def test_real_database_roundtrip_is_confined_to_runtime(self):
        from sonus_mobile.runtime import Runtime
        from sonus_core.database import Database
        runtime = Runtime().start()
        try:
            database = runtime.call_sync(Database, str(self.root / "library.db"))
            song = runtime.call_sync(database.addStreamSong, "https://youtu.be/abcdefghijk", "Brano Android", "Artista")
            self.assertEqual(runtime.call_sync(database.getSong, song)["title"], "Brano Android")
            with self.assertRaises(Exception):
                database.allSongs()
            runtime.call_sync(database.close)
        finally:
            runtime.close()

    def test_pc_and_mobile_encrypted_room_protocol_interoperate(self):
        from sonus_core.session_link import CodeBox, parseCode
        pc_path = REPO / "app/session_link.py"
        # The protocol itself has no UI imports: execute only the definitions preceding Link.
        source = pc_path.read_text(encoding="utf-8").split("class Link(QObject):")[0]
        source = source.replace("from PySide6.QtCore import QObject, QTimer, Signal", "")
        pc = {"__name__": "pc_protocol"}
        exec(compile(source, str(pc_path), "exec"), pc)
        mobile = CodeBox("SONUS-ABCD-EFGH")
        desktop = pc["CodeBox"]("SONUS-ABCD-EFGH")
        payload = {"title": "Canzone è", "position": 1234, "queue": [1, 2]}
        self.assertEqual(desktop.open(mobile.seal(payload)), payload)
        self.assertEqual(mobile.open(desktop.seal(payload)), payload)
        self.assertEqual(parseCode("sonus://join/sonus-abcd-efgh"), ("room", "SONUS-ABCD-EFGH"))
        sealed = bytearray(mobile.seal(payload))
        sealed[-1] ^= 1
        self.assertIsNone(desktop.open(bytes(sealed)))

    def test_pillow_covers_are_square_and_shared_cover_is_readable(self):
        from PIL import Image
        from sonus_core.downloader import _squareCover
        from sonus_core.playlist_sync import coverToBase64
        image = io.BytesIO()
        Image.new("RGB", (640, 480), "red").save(image, "PNG")
        cropped = _squareCover(image.getvalue())
        with Image.open(io.BytesIO(cropped)) as result:
            self.assertEqual(result.size, (360, 360))
        cover = self.root / "cover.png"
        cover.write_bytes(image.getvalue())
        with Image.open(io.BytesIO(base64.b64decode(coverToBase64(str(cover))))) as result:
            self.assertGreaterEqual(min(result.size), 200)
        self.assertEqual(_squareCover(b"invalid"), b"invalid")

    def test_ffmpeg_and_quickjs_use_native_libraries(self):
        from sonus_core.config import ffmpegExe
        from sonus_core.downloader import _baseOptions
        native = Path(os.environ["SONUS_NATIVE_DIR"])
        native.mkdir(exist_ok=True)
        (native / "libffmpeg.so").write_bytes(b"native-binary")
        (native / "libqjs.so").write_bytes(b"native-binary")
        self.assertEqual(ffmpegExe(), str(native / "libffmpeg.so"))
        options = _baseOptions()
        self.assertEqual(options["js_runtimes"], {"quickjs": {"path": str(native / "libqjs.so")}})
        self.assertEqual(options["ffmpeg_location"], str(native / "libffmpeg.so"))
        (native / "libffmpeg.so").unlink()
        with self.assertRaises(FileNotFoundError):
            ffmpegExe()

    def test_original_dsp_applies_eq_and_bass_without_desktop_audio(self):
        import numpy as np
        from sonus_core.audio_engine import applyBassBoostOffline, buildEqSos, speedFilter
        from scipy.signal import sosfreqz
        sos = buildEqSos([6.0] + [0.0] * 9)
        _, response = sosfreqz(sos, worN=[32], fs=44100)
        self.assertGreater(abs(response[0]), 1.5)
        samples = np.sin(np.arange(4096) * 2 * np.pi * 50 / 44100).astype(np.float32)[:, None] * 0.05
        self.assertGreater(float(np.max(np.abs(applyBassBoostOffline(samples, 1)))), 0.1)
        self.assertIn("atempo", speedFilter(1.5, True))
        self.assertIn("asetrate", speedFilter(1.5, False))

    def test_android_output_writes_full_float_pcm_when_hardware_accepts_partial_blocks(self):
        import numpy as np
        from sonus_mobile.android_audio import OutputStream
        completed = threading.Event()
        written = bytearray()
        class Sink:
            def __init__(self, rate, channels, size):
                self.closed = False
            def write(self, data):
                count = min(8, len(data))
                written.extend(data[:count])
                if len(written) >= 32:
                    completed.set()
                return count
            def close(self):
                self.closed = True
        def callback(output, frames, info, status):
            output[:] = 0.25
        stream = OutputStream(samplerate=8000, channels=2, blocksize=4, callback=callback, sink_factory=Sink)
        stream.start()
        self.assertTrue(completed.wait(2))
        stream.close()
        self.assertTrue(stream.sink.closed)
        self.assertEqual(np.frombuffer(bytes(written[:32]), dtype="<f4").tolist(), [0.25] * 8)

    def test_mapped_decoder_storage_has_independent_files_and_reclaims_them(self):
        import gc
        import numpy as np
        from sonus_mobile.android_audio import allocate_pcm
        first = allocate_pcm(20, 2)
        second = allocate_pcm(20, 2)
        first[:] = 7
        self.assertTrue(np.all(second == 0))
        path = Path(first.filename)
        self.assertTrue(path.is_file())
        del first
        gc.collect()
        self.assertFalse(path.exists())

    def test_cancelled_decoder_cannot_reattach_storage_after_shutdown(self):
        import gc
        from unittest.mock import patch
        from sonus_mobile.runtime import Runtime, QUrl
        from sonus_mobile.android_audio import allocate_pcm
        from sonus_core import audio_engine
        allocating, release = threading.Event(), threading.Event()
        created = []
        def delayed_allocate(frames, channels):
            allocating.set()
            release.wait(2)
            result = allocate_pcm(100, channels)
            created.append(Path(result.filename))
            return result
        class Process:
            def __init__(self, *args, **kwargs):
                self.stdout, self.stderr = io.BytesIO(b""), io.BytesIO(b"")
                self.returncode = None
            def poll(self):
                return self.returncode
            def kill(self):
                self.returncode = -9
            def wait(self):
                self.returncode = 0
        runtime = Runtime().start()
        engine = runtime.call_sync(audio_engine.AudioEngine)
        try:
            with patch.object(audio_engine, "ffmpegExe", return_value="ffmpeg"), patch.object(audio_engine.subprocess, "Popen", Process), patch.object(audio_engine, "allocate_pcm", delayed_allocate):
                runtime.call_sync(engine.setSource, QUrl.fromLocalFile(str(self.root / "cancel.wav")))
                self.assertTrue(allocating.wait(2))
                decoder = engine.decoder
                runtime.call_sync(engine.shutdown)
                release.set()
                decoder.join(2)
                self.assertFalse(decoder.is_alive())
                self.assertIsNone(engine.buffer)
                gc.collect()
                self.assertTrue(created)
                self.assertTrue(all(not path.exists() for path in created))
        finally:
            release.set()
            runtime.call_sync(engine.shutdown)
            runtime.close()

    def test_async_audio_device_failure_stops_and_reports_once_on_owner(self):
        import time
        from unittest.mock import patch
        from sonus_mobile.runtime import Runtime, QUrl, QMediaPlayer
        from sonus_mobile import android_audio
        from sonus_core.audio_engine import AudioEngine
        original = android_audio.OutputStream
        opened = []
        errors, complete = [], threading.Event()
        class FailedSink:
            def __init__(self, *args):
                opened.append(1)
            def write(self, data):
                raise OSError("device disconnected")
            def close(self):
                pass
        runtime = Runtime().start()
        engine = runtime.call_sync(AudioEngine)
        def error(kind, message):
            errors.append((kind, message, threading.get_ident()))
            complete.set()
        runtime.call_sync(engine.errorOccurred.connect, error)
        try:
            with patch.object(android_audio, "OutputStream", lambda **kwargs: original(**kwargs, sink_factory=FailedSink)):
                runtime.call_sync(lambda: setattr(engine, "_source", QUrl("file:///already-decoded.wav")))
                runtime.call_sync(engine.play)
                self.assertTrue(complete.wait(1), "asynchronous hardware error was swallowed")
                time.sleep(.1)
                self.assertEqual(engine.playbackState(), QMediaPlayer.StoppedState)
                self.assertEqual(len(opened), 1)
                self.assertEqual(len(errors), 1)
                self.assertEqual(errors[0][0], QMediaPlayer.ResourceError)
                self.assertIn("device disconnected", errors[0][1])
                self.assertEqual(errors[0][2], runtime.thread_id)
                runtime.call_sync(engine.play)
                deadline = time.monotonic() + 1
                while len(errors) < 2 and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual(len(opened), 2, "explicit retry reused the dead AudioTrack")
                self.assertEqual(len(errors), 2)
        finally:
            runtime.call_sync(engine.shutdown)
            runtime.close()

    def test_short_lived_worker_senders_deliver_all_queued_completions(self):
        import gc
        import time
        from sonus_mobile.runtime import Runtime, QThreadPool
        from sonus_core.workers import runInBackground
        runtime = Runtime().start()
        pool = runtime.call_sync(QThreadPool)
        pool.setMaxThreadCount(1)
        produced, received = threading.Event(), []
        def work(value):
            if value == 2:
                produced.set()
            return value
        def produce_while_owner_is_busy():
            for value in (1, 2):
                runInBackground(work, value, onFinished=lambda result: received.append((result, threading.get_ident())), pool=pool)
            self.assertTrue(produced.wait(2))
            time.sleep(.03)
            # Worker1 has finished and the pool is processing Worker2: no live
            # worker reference remains for its signal sender, only the queued event.
            gc.collect()
        try:
            runtime.call_sync(produce_while_owner_is_busy)
            runtime.call_sync(lambda: None)
            self.assertEqual(received, [(1, runtime.thread_id), (2, runtime.thread_id)])
        finally:
            runtime.close()

    def test_runtime_shutdown_releases_audio_even_without_controller_cleanup(self):
        from unittest.mock import patch
        from sonus_mobile.runtime import Runtime, QUrl
        from sonus_mobile import android_audio
        from sonus_core.audio_engine import AudioEngine
        original = android_audio.OutputStream
        sinks = []
        class Sink:
            def __init__(self, *args):
                self.closed = False
                sinks.append(self)
            def write(self, data):
                return len(data)
            def close(self):
                self.closed = True
        runtime = Runtime().start()
        engine = runtime.call_sync(AudioEngine)
        try:
            with patch.object(android_audio, "OutputStream", lambda **kwargs: original(**kwargs, sink_factory=Sink)):
                runtime.call_sync(lambda: setattr(engine, "_source", QUrl("file:///already-decoded.wav")))
                runtime.call_sync(engine.play)
                self.assertEqual(len(sinks), 1)
                runtime.close()
                self.assertTrue(sinks[0].closed, "runtime disposal left Android audio running")
                self.assertIsNone(engine.stream)
        finally:
            engine.shutdown()
            runtime.close()

    def test_original_queue_reordering_repeat_and_loop_keep_playing_song(self):
        from unittest.mock import patch
        from sonus_mobile.runtime import Runtime
        from sonus_core.player import Player, REPEAT_ALL
        runtime = Runtime().start()
        player = runtime.call_sync(Player)
        songs = [{"id": index, "title": str(index), "path": str(self.root / f"{index}.wav")} for index in range(1, 4)]
        try:
            # This test exercises queue logic; file decode/device output are the boundary.
            with patch.object(player, "_loadCurrent"):
                runtime.call_sync(player.playSongs, songs, 1)
                runtime.call_sync(player.moveInQueue, 0, 2)
                self.assertEqual(player.currentSong()["id"], 2)
                self.assertEqual([song["id"] for song in player.queue], [2, 3, 1])
                runtime.call_sync(player.removeFromQueue, [0, 2])
                self.assertEqual([song["id"] for song in player.queue], [2, 3])
                runtime.call_sync(player.setRepeat, REPEAT_ALL)
                runtime.call_sync(player.next, True)
                self.assertEqual(player.currentSong()["id"], 3)
                runtime.call_sync(player.next, True)
                self.assertEqual(player.currentSong()["id"], 2)
                runtime.call_sync(player.setLoop, {"startMs": 500, "endMs": 1500})
                self.assertEqual(player.activeLoop, {"startMs": 500, "endMs": 1500})
                self.assertEqual(player.mediaPlayer.loopFrames, (22050, 66150))
        finally:
            runtime.call_sync(player.shutdown)
            runtime.close()

    def test_real_entry_initialization_commands_errors_and_reopen_persist_without_qt(self):
        data = self.root / "entry_data"
        native = self.root / "entry_native"
        packages = self.root / "entry_packages"
        script = textwrap.dedent('''
            import builtins, json, sys, threading, time
            original_import = builtins.__import__
            def guarded(name, *args, **kwargs):
                if name.startswith("PySide6"):
                    raise AssertionError("Android must not import Qt: " + name)
                return original_import(name, *args, **kwargs)
            builtins.__import__ = guarded
            from sonus_mobile import entry
            class Callback:
                def __init__(self):
                    self.events = []
                def onEvent(self, value):
                    self.events.append((json.loads(value), threading.current_thread().name))
            callback = Callback()
            initial = json.loads(entry.initialize(*sys.argv[1:], callback))
            assert initial["ready"] is True
            assert entry.command("playlist_create", '{"name":"Entry persistence"}') is True
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline and not any(any(p["name"] == "Entry persistence" for p in state.get("playlists", [])) for state, thread in callback.events):
                time.sleep(.02)
            assert any(any(p["name"] == "Entry persistence" for p in state.get("playlists", [])) for state, thread in callback.events), callback.events
            assert entry.command("playlist_create", "[]") is False
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not any(state.get("error") for state, thread in callback.events):
                time.sleep(.02)
            assert any(state.get("error") for state, thread in callback.events)
            assert all(thread == "SonusRuntime" for state, thread in callback.events)
            entry.close()
            restored = json.loads(entry.initialize(*sys.argv[1:], callback))
            assert restored["playlists"][0]["name"] == "Entry persistence"
            entry.close()
            assert not any(name.startswith("PySide6") for name in sys.modules)
            print("entry_ok")
        ''')
        environment = dict(os.environ)
        environment["PYTHONPATH"] = os.pathsep.join([str(self.root / "generated"), str(REPO / "android/app/src/main/python")] + sys.path)
        result = subprocess.run([sys.executable, "-c", script, str(data), str(native), str(packages)], env=environment, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("entry_ok", result.stdout)


def _original_regression(path, name, helpers=()):
    """Run unmodified assertions, replacing only their platform import boundary.

    Broker/desktop UI fixtures are deliberately excluded. These cases cover
    encrypted files, playlist CRDT merges, timing, visualizer DSP and stream seek.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    selected = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("tests"):
                continue
            if node.module == "PySide6.QtCore":
                continue  # Selected assertions never use a Qt application.
            selected.append(node)
        elif isinstance(node, (ast.Import, ast.Assign)):
            selected.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in {name, *helpers}:
            selected.append(node)
    module = ast.Module(body=selected, type_ignores=[])
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "app" or node.module.startswith("app."):
                node.module = "sonus_core" + node.module[3:]
            elif node.module.startswith("PySide6."):
                node.module = "sonus_mobile.runtime"
    namespace = {"__name__": "original_mobile_regression"}
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace[name]


def _make_original_case(filename, name, helpers):
    def case(self):
        from sonus_mobile.runtime import Runtime
        function = _original_regression(REPO / "tests" / filename, name, helpers)
        directory = self.root / name
        directory.mkdir(exist_ok=True)
        arguments = {"tmp_path": directory, "application": None}
        kwargs = {argument: arguments[argument] for argument in function.__code__.co_varnames[:function.__code__.co_argcount]}
        runtime = Runtime().start()
        try:
            runtime.call_sync(lambda: function(**kwargs))
        finally:
            runtime.close()
    return case


_REGRESSIONS = {
    "test_together_sync.py": (
        ["test_trackKeyUsesYoutubeIdOrNormalizedNames", "test_trackFromStreamSearchSongKeepsQuery", "test_isNewerOrdersByVersionThenSender", "test_expectedPositionWithRateAndOffset", "test_clockSyncPrefersShortestRoundTrip", "test_modifiedSongIsSharedAsPersonalFile"], ()),
    "test_playlist_sync.py": (
        ["test_assignKeysForDuplicates", "test_additionsFromBothKept", "test_removalAfterAdditionWinsAndReAddWins", "test_orderFromLatestEditAndMergeIdempotent", "test_renameFromLatest"], ("track", "snapshotOf", "titles")),
    "test_room_files.py": (
        ["test_encryptDecryptRoundTrip", "test_cleanupRemovesFilesIdleForAnHour", "test_hostileFileMessagesRejected"], ()),
    "test_effects.py": (
        ["test_spectrumPeaksInRightBand", "test_fadeInAndOut", "test_bassBoostRaisesLowsNotHighs"], ()),
    "test_streaming.py": (
        ["test_shortErrorHidesUrls", "test_seekPastDecodedAudioWaitsAndKeepsTime"], ()),
}
for _filename, (_names, _helpers) in _REGRESSIONS.items():
    for _name in _names:
        setattr(PortableCoreTests, "test_pc_" + _filename[5:-3] + "_" + _name[5:], _make_original_case(_filename, _name, _helpers))


if __name__ == "__main__":
    unittest.main()
