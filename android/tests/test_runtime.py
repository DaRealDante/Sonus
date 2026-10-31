"""Behavioral tests for the mobile serial dispatcher (no Qt dependency)."""
import importlib
from pathlib import Path
import sqlite3
import sys
import threading
import time
import unittest
import tempfile
import os

PYTHON = Path(__file__).resolve().parents[1] / "app/src/main/python"
sys.path.insert(0, str(PYTHON))


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((PYTHON / "sonus_mobile/runtime.py").is_file(), "mobile runtime is not implemented")
        self.module = importlib.import_module("sonus_mobile.runtime")
        self.runtime = self.module.Runtime().start()

    def tearDown(self):
        if hasattr(self, "runtime"):
            self.runtime.close()

    def test_state_and_sqlite_stay_on_one_owner_thread(self):
        database = self.runtime.call_sync(lambda: sqlite3.connect(":memory:"))
        self.runtime.call_sync(lambda: database.execute("create table example (value integer)"))
        completed = threading.Event()
        values = []
        def done(value):
            database.execute("insert into example values (?)", (value,))
            values.append(threading.get_ident())
            completed.set()
        self.runtime.submit(lambda: 42, callback=done)
        self.assertTrue(completed.wait(2))
        self.assertEqual(values, [self.runtime.thread_id])
        self.assertEqual(self.runtime.call_sync(lambda: database.execute("select value from example").fetchone()[0]), 42)
        with self.assertRaises(sqlite3.ProgrammingError):
            database.execute("select value from example")
        self.runtime.call_sync(database.close)

    def test_signal_instances_are_isolated_and_worker_delivery_is_queued(self):
        module = self.module
        class Source(module.QObject):
            changed = module.Signal(int)
        first, second = self.runtime.call_sync(lambda: (Source(), Source()))
        received = []
        ready = threading.Event()
        def slot(value):
            received.append((value, threading.get_ident()))
            ready.set()
        self.runtime.call_sync(first.changed.connect, slot)
        self.runtime.call_sync(second.changed.emit, 9)
        self.assertEqual(received, [])
        worker = threading.Thread(target=lambda: first.changed.emit(7))
        worker.start()
        worker.join()
        self.assertTrue(ready.wait(2))
        self.assertEqual(received, [(7, self.runtime.thread_id)])
        self.runtime.call_sync(first.changed.disconnect, slot)
        self.runtime.call_sync(first.changed.emit, 8)
        self.assertEqual(len(received), 1)

    def test_signal_forwarding_and_plain_lambda_preserve_owner(self):
        module = self.module
        class Source(module.QObject):
            changed = module.Signal(int)
        first, second = self.runtime.call_sync(lambda: (Source(), Source()))
        got = []
        finished = threading.Event()
        self.runtime.call_sync(first.changed.connect, second.changed)
        self.runtime.call_sync(second.changed.connect, lambda value: (got.append((value, threading.get_ident())), finished.set()))
        self.runtime.submit(lambda: first.changed.emit(12))
        self.assertTrue(finished.wait(2))
        self.assertEqual(got, [(12, self.runtime.thread_id)])

    def test_restarted_and_stopped_timer_cannot_fire_stale_callback(self):
        timer = self.runtime.call_sync(lambda: self.module.QTimer())
        got = []
        self.runtime.call_sync(timer.timeout.connect, lambda: got.append(threading.get_ident()))
        self.runtime.call_sync(timer.setSingleShot, True)
        self.runtime.call_sync(timer.start, 20)
        self.runtime.call_sync(timer.stop)
        time.sleep(0.06)
        self.runtime.call_sync(lambda: None)
        self.assertEqual(got, [])
        self.runtime.call_sync(timer.start, 100)
        self.runtime.call_sync(timer.start, 10)
        time.sleep(0.15)
        self.runtime.call_sync(lambda: None)
        self.assertEqual(got, [self.runtime.thread_id])
        self.assertFalse(timer.isActive())

    def test_background_errors_return_on_owner_and_do_not_kill_loop(self):
        got = []
        complete = threading.Event()
        self.runtime.submit(lambda: 1 / 0, error=lambda error: (got.append((type(error), threading.get_ident())), complete.set()))
        self.assertTrue(complete.wait(2))
        self.assertEqual(got, [(ZeroDivisionError, self.runtime.thread_id)])
        self.assertEqual(self.runtime.call_sync(lambda: 3), 3)

    def test_url_roundtrip_preserves_spaces_and_unicode(self):
        path = str(Path.cwd() / "musica è bella.wav")
        url = self.module.QUrl.fromLocalFile(path)
        self.assertTrue(url.isLocalFile())
        self.assertEqual(self.module.QUrl(url.toString()).toLocalFile(), path)
        self.assertFalse(self.module.QUrl("https://example.org/music").isLocalFile())

    def test_entry_sets_android_native_environment_without_duplicating_library_paths(self):
        import importlib.util
        self.assertTrue((PYTHON / "sonus_mobile/entry.py").is_file(), "Android entry is not implemented")
        from sonus_mobile.entry import configure_environment
        from unittest.mock import patch
        root = PYTHON.parents[3] / "app/build/entry_test"
        native, packages, data = root / "native", root / "packages", root / "data"
        with patch.dict(os.environ, {"LD_LIBRARY_PATH": "/existing/lib"}), patch.object(tempfile, "tempdir", tempfile.tempdir):
            configure_environment(str(data), str(native), str(packages))
            configure_environment(str(data), str(native), str(packages))
            self.assertEqual(os.environ["SONUS_DATA_DIR"], str(data.resolve()))
            self.assertEqual(os.environ["SONUS_NATIVE_DIR"], str(native.resolve()))
            expected = [str((packages / "ffmpeg/usr/lib").resolve()), str(native.resolve()), "/existing/lib"]
            # Android's linker uses ':' even when the build/test host is Windows.
            self.assertEqual(os.environ["LD_LIBRARY_PATH"], ":".join(expected))

    def test_closing_runtime_releases_global_pool_and_owner(self):
        import gc
        import weakref
        runtime = self.runtime
        pool = runtime.call_sync(self.module.QThreadPool.globalInstance)
        reference = weakref.ref(runtime)
        runtime.close()
        del self.runtime
        del runtime, pool
        gc.collect()
        self.assertIsNone(reference(), "closed runtime is retained by the global worker pool")


if __name__ == "__main__":
    unittest.main()
