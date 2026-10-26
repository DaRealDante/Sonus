"""A serial Python dispatcher for Sonus core objects, signals, timers and workers.

This is an event loop, not a Qt shim installed into sys.modules. Every object
belongs to an actual dispatcher. A worker's signal is queued back to the thread
which connected its callback, preserving SQLite's default thread protection.
"""
import collections
from concurrent.futures import Future
import enum
import heapq
import itertools
import queue
import threading
import time
import traceback
import urllib.parse
import urllib.request
import weakref
from pathlib import Path

_local = threading.local()
_default = None
_default_lock = threading.Lock()


class Handle:
    def __init__(self, callback, args=()):
        self.callback = callback
        self.args = args
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class _Workers:
    """Bounded daemon workers: unfinished network calls cannot keep Android alive."""
    def __init__(self, count=4):
        self.count = count
        self.tasks = queue.Queue()
        self.threads = []
        self.lock = threading.Lock()
        self.closed = False

    def submit(self, function, *args):
        future = Future()
        with self.lock:
            if self.closed:
                raise RuntimeError("Worker pool is closed")
            self.tasks.put((future, function, args))
            if len(self.threads) < self.count:
                thread = threading.Thread(target=self._work, name="SonusWorker", daemon=True)
                self.threads.append(thread)
                thread.start()
        return future

    def _work(self):
        while True:
            item = self.tasks.get()
            try:
                if item is None:
                    return
                future, function, args = item
                if future.set_running_or_notify_cancel():
                    try:
                        future.set_result(function(*args))
                    except BaseException as error:
                        future.set_exception(error)
            finally:
                self.tasks.task_done()

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            while True:
                try:
                    item = self.tasks.get_nowait()
                except queue.Empty:
                    break
                if item is not None:
                    item[0].cancel()
                self.tasks.task_done()
            for _ in self.threads:
                self.tasks.put(None)


class Runtime:
    def __init__(self, on_error=None, max_workers=4):
        self.thread_id = None
        self.on_error = on_error
        self._condition = threading.Condition()
        self._ready = collections.deque()
        self._timers = []
        self._sequence = itertools.count()
        self._thread = None
        self._started = threading.Event()
        self._closed = False
        self._objects = weakref.WeakSet()
        self._workers = _Workers(max_workers)

    def start(self):
        with self._condition:
            if self._closed:
                raise RuntimeError("Runtime is closed")
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="SonusRuntime", daemon=True)
                self._thread.start()
        self._started.wait()
        return self

    def is_owner_thread(self):
        return self.thread_id == threading.get_ident()

    def call_soon(self, function, *args):
        handle = Handle(function, args)
        with self._condition:
            if self._closed:
                handle.cancel()
                return handle
            self._ready.append(handle)
            self._condition.notify()
        return handle

    def call_later(self, seconds, function, *args):
        handle = Handle(function, args)
        with self._condition:
            if self._closed:
                handle.cancel()
                return handle
            heapq.heappush(self._timers, (time.monotonic() + max(0, float(seconds)), next(self._sequence), handle))
            self._condition.notify()
        return handle

    def call_sync(self, function, *args, timeout=30):
        if self.is_owner_thread():
            return function(*args)
        self.start()
        result = Future()
        def invoke():
            if not result.set_running_or_notify_cancel():
                return
            try:
                result.set_result(function(*args))
            except BaseException as error:
                result.set_exception(error)
        handle = self.call_soon(invoke)
        if handle.cancelled:
            raise RuntimeError("Runtime is closed")
        return result.result(timeout=timeout)

    def submit(self, worker, callback=None, error=None):
        future = self._workers.submit(worker)
        def finished(result):
            if result.cancelled():
                return
            exception = result.exception()
            if exception is not None:
                self.call_soon(error or self._report_error, exception)
            elif callback is not None:
                self.call_soon(callback, result.result())
        future.add_done_callback(finished)
        return future

    def _report_error(self, error):
        if self.on_error:
            self.on_error(error)
        else:
            traceback.print_exception(type(error), error, error.__traceback__)

    def _run(self):
        self.thread_id = threading.get_ident()
        _local.runtime = self
        self._started.set()
        while True:
            with self._condition:
                while True:
                    if self._closed:
                        return
                    now = time.monotonic()
                    while self._timers and self._timers[0][0] <= now:
                        self._ready.append(heapq.heappop(self._timers)[2])
                    if self._ready:
                        handle = self._ready.popleft()
                        break
                    delay = max(0, self._timers[0][0] - now) if self._timers else None
                    self._condition.wait(delay)
            if not handle.cancelled:
                try:
                    handle.callback(*handle.args)
                except Exception as error:
                    try:
                        self._report_error(error)
                    except Exception:
                        traceback.print_exc()

    def close(self):
        if self._closed:
            return
        if self._thread is not None:
            self.call_sync(self._dispose)
        with self._condition:
            self._closed = True
            for handle in self._ready:
                handle.cancel()
            for _, _, handle in self._timers:
                handle.cancel()
            self._ready.clear()
            self._timers.clear()
            self._condition.notify_all()
        self._workers.close()
        if self._thread is not None and not self.is_owner_thread():
            self._thread.join(timeout=5)

    def _dispose(self):
        for obj in list(self._objects):
            obj._dispose()
        # WeakKeyDictionary values must not retain their own weak key through
        # pool._runtime after shutdown.
        with QThreadPool._global_lock:
            QThreadPool._global.pop(self, None)


def current_runtime():
    runtime = getattr(_local, "runtime", None)
    if runtime is not None:
        return runtime
    global _default
    with _default_lock:
        if _default is None or _default._closed:
            _default = Runtime().start()
        return _default


class QObject:
    def __init__(self, parent=None):
        self._runtime = parent._runtime if isinstance(parent, QObject) else current_runtime()
        self._parent = parent
        self._children = []
        self._deleted = False
        self._signals_blocked = False
        self._runtime._objects.add(self)
        if isinstance(parent, QObject):
            parent._children.append(self)

    def blockSignals(self, block):
        previous = self._signals_blocked
        self._signals_blocked = bool(block)
        return previous

    def deleteLater(self):
        self._runtime.call_soon(self._dispose)

    def _dispose(self):
        if self._deleted:
            return
        self._deleted = True
        for child in list(self._children):
            child._dispose()
        self._children.clear()
        for value in list(self.__dict__.values()):
            if isinstance(value, _BoundSignal):
                value.disconnect()
        if isinstance(self._parent, QObject):
            try:
                self._parent._children.remove(self)
            except ValueError:
                pass
        self._parent = None


class Signal:
    def __init__(self, *types):
        self.name = None

    def __set_name__(self, owner, name):
        self.name = "_signal_" + name

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        signal = instance.__dict__.get(self.name)
        if signal is None:
            signal = instance.__dict__[self.name] = _BoundSignal(instance)
        return signal


class _BoundSignal:
    def __init__(self, owner):
        self.owner = weakref.ref(owner)
        self.connections = []
        self.lock = threading.RLock()

    def connect(self, callback, *unused):
        if not callable(callback):
            raise TypeError("Signal callback must be callable")
        receiver = callback.owner() if isinstance(callback, _BoundSignal) else getattr(callback, "__self__", None)
        owner = self.owner()
        runtime = getattr(receiver, "_runtime", None) or getattr(_local, "runtime", None) or owner._runtime
        connection = [callback, runtime, True]
        with self.lock:
            self.connections.append(connection)
        return connection

    def disconnect(self, callback=None):
        with self.lock:
            for connection in self.connections:
                if callback is None or connection[0] == callback:
                    connection[2] = False
            self.connections = [item for item in self.connections if item[2]]

    def emit(self, *args):
        owner = self.owner()
        if owner is None or owner._deleted or owner._signals_blocked:
            return
        with self.lock:
            connections = list(self.connections)
        for connection in connections:
            if not connection[2]:
                continue
            runtime = connection[1]
            if runtime.is_owner_thread():
                self._deliver(connection, args, owner)
            else:
                # The completed QRunnable may be collected before the owner loop
                # gets to this event. The event must keep its sender alive.
                runtime.call_soon(self._deliver, connection, args, owner)

    __call__ = emit

    def _deliver(self, connection, args, owner):
        if not connection[2] or owner is None or owner._deleted:
            return
        callback = connection[0]
        receiver = getattr(callback, "__self__", None)
        if isinstance(receiver, QObject) and receiver._deleted:
            return
        callback(*args)


class QTimer(QObject):
    timeout = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._interval = 0
        self._single = False
        self._handle = None
        self._generation = 0
        self._deadline = None

    def setInterval(self, milliseconds):
        self._interval = max(0, int(milliseconds))
        if self.isActive():
            self.start()

    def interval(self):
        return self._interval

    def setSingleShot(self, single):
        self._single = bool(single)

    def isSingleShot(self):
        return self._single

    def isActive(self):
        return self._handle is not None and not self._handle.cancelled

    def remainingTime(self):
        return max(0, int((self._deadline - time.monotonic()) * 1000)) if self.isActive() else -1

    def start(self, milliseconds=None):
        self.stop()
        if self._deleted:
            return
        if milliseconds is not None:
            self._interval = max(0, int(milliseconds))
        self._schedule(self._generation)

    def _schedule(self, generation):
        delay = max(0.001, self._interval / 1000)
        self._deadline = time.monotonic() + delay
        self._handle = self._runtime.call_later(delay, self._fire, generation)

    def _fire(self, generation):
        if generation != self._generation or self._deleted:
            return
        self._handle = None
        if not self._single:
            self._schedule(generation)
        self.timeout.emit()

    def stop(self):
        self._generation += 1
        if self._handle:
            self._handle.cancel()
        self._handle = None
        self._deadline = None

    @staticmethod
    def singleShot(milliseconds, callback):
        receiver = getattr(callback, "__self__", None)
        runtime = getattr(receiver, "_runtime", None) or current_runtime()
        def deliver():
            if not isinstance(receiver, QObject) or not receiver._deleted:
                callback()
        return runtime.call_later(max(0, milliseconds) / 1000, deliver)

    def _dispose(self):
        self.stop()
        super()._dispose()


class QRunnable:
    def setAutoDelete(self, enabled):
        self.auto_delete = bool(enabled)

    def run(self):
        raise NotImplementedError


class QThreadPool(QObject):
    _global = weakref.WeakKeyDictionary()
    _global_lock = threading.Lock()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._workers = _Workers(4)
        self._futures = set()
        self._lock = threading.Lock()

    @classmethod
    def globalInstance(cls):
        runtime = current_runtime()
        with cls._global_lock:
            instance = cls._global.get(runtime)
            if instance is None or instance._deleted:
                instance = cls()
                cls._global[runtime] = instance
            return instance

    def setMaxThreadCount(self, count):
        self._workers.count = max(1, int(count))

    def maxThreadCount(self):
        return self._workers.count

    def start(self, runnable):
        future = self._workers.submit(runnable.run if hasattr(runnable, "run") else runnable)
        with self._lock:
            self._futures.add(future)
        def done(result):
            with self._lock:
                self._futures.discard(result)
            if not result.cancelled() and result.exception() is not None:
                self._runtime.call_soon(self._runtime._report_error, result.exception())
        future.add_done_callback(done)
        return future

    def waitForDone(self, milliseconds=-1):
        from concurrent.futures import wait
        with self._lock:
            futures = set(self._futures)
        return not wait(futures, timeout=None if milliseconds < 0 else milliseconds / 1000).not_done

    def activeThreadCount(self):
        with self._lock:
            return sum(future.running() for future in self._futures)

    def _dispose(self):
        self._workers.close()
        super()._dispose()


class QUrl:
    def __init__(self, value=""):
        self.value = value.value if isinstance(value, QUrl) else str(value or "")

    @classmethod
    def fromLocalFile(cls, path):
        return cls(Path(path).absolute().as_uri())

    def toLocalFile(self):
        parts = urllib.parse.urlsplit(self.value)
        if parts.scheme != "file":
            return ""
        path = urllib.request.url2pathname(parts.path)
        return "//" + parts.netloc + path if parts.netloc and parts.netloc != "localhost" else path

    def toString(self):
        return self.value

    def isLocalFile(self):
        return self.value.lower().startswith("file:")

    def isEmpty(self):
        return not self.value


class QMediaPlayer:
    """State constants consumed by the original DSP engine; no media implementation."""
    class PlaybackState(enum.IntEnum):
        StoppedState = 0
        PlayingState = 1
        PausedState = 2
    class MediaStatus(enum.IntEnum):
        NoMedia = 0
        LoadingMedia = 1
        LoadedMedia = 2
        StalledMedia = 3
        BufferingMedia = 4
        BufferedMedia = 5
        EndOfMedia = 6
        InvalidMedia = 7
    class Error(enum.IntEnum):
        NoError = 0
        ResourceError = 1
        FormatError = 2
        NetworkError = 3
        AccessDeniedError = 4


for _group in (QMediaPlayer.PlaybackState, QMediaPlayer.MediaStatus, QMediaPlayer.Error):
    for _member in _group:
        setattr(QMediaPlayer, _member.name, _member)
