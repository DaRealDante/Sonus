"""AudioTrack boundary and disk-backed decoder storage for the original DSP."""
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import weakref

import numpy

_pcm_lock = threading.Lock()
_pcm_files = {}
MAX_PCM_FILE_BYTES = 1024 * 1024 * 1024
MAX_PCM_TOTAL_BYTES = 2 * MAX_PCM_FILE_BYTES
MIN_FREE_BYTES = 64 * 1024 * 1024


def _remove_pcm(path, mapping):
    try:
        mapping.close()
    finally:
        with _pcm_lock:
            _pcm_files.pop(path, None)
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def cleanup_stale_pcm():
    """Only called at process initialization, before a decoder can own a file."""
    directory = Path(os.environ["SONUS_DATA_DIR"]) / "temp" / "pcm"
    directory.mkdir(parents=True, exist_ok=True)
    with _pcm_lock:
        live = set(_pcm_files)
    for path in directory.glob("decode_*.pcm"):
        if str(path) not in live:
            try:
                path.unlink()
            except OSError:
                pass


def allocate_pcm(frames, channels):
    """Keep complete decoded audio seekable without allocating it on Android's heap.

    A single mapping is capped at 1 GiB; concurrent growth at 2 GiB and available
    space minus 64 MiB. Fail explicitly before filling private app storage.
    """
    size = int(frames) * int(channels) * numpy.dtype(numpy.int16).itemsize
    directory = Path(os.environ["SONUS_DATA_DIR"]) / "temp" / "pcm"
    directory.mkdir(parents=True, exist_ok=True)
    with _pcm_lock:
        if size <= 0 or size > MAX_PCM_FILE_BYTES or sum(_pcm_files.values()) + size > MAX_PCM_TOTAL_BYTES:
            raise RuntimeError("Audio troppo lungo per la memoria temporanea Android")
        if shutil.disk_usage(directory).free - size < MIN_FREE_BYTES:
            raise RuntimeError("Spazio insufficiente per decodificare l'audio")
        descriptor, path = tempfile.mkstemp(prefix="decode_", suffix=".pcm", dir=directory)
        os.close(descriptor)
        try:
            array = numpy.memmap(path, dtype=numpy.int16, mode="w+", shape=(int(frames), int(channels)))
        except Exception:
            os.unlink(path)
            raise
        _pcm_files[path] = size
    weakref.finalize(array, _remove_pcm, path, array._mmap)
    return array


def _android_sink(sample_rate, channels, block_size):
    from java import jclass
    return jclass("it.sonus.mobile.PcmSink")(sample_rate, channels, block_size)


def _java_bytes(data):
    # Explicit jbyte[] conversion avoids Chaquopy-version-dependent bytes overloads.
    from java import jarray, jbyte
    return jarray(jbyte)(data)


class OutputStream:
    """Push the unchanged Sonus float32 callback into a blocking AudioTrack sink."""
    def __init__(self, samplerate, channels, blocksize, callback, dtype="float32",
                 latency=0.3, finished_callback=None, sink_factory=None):
        if dtype != "float32":
            raise ValueError("Android PCM requires float32")
        self.samplerate = int(samplerate)
        self.channels = int(channels)
        self.blocksize = int(blocksize)
        self.callback = callback
        self.finished_callback = finished_callback
        self.latency = float(latency)
        self.sink_factory = sink_factory or _android_sink
        self._native = sink_factory is None
        self.sink = None
        self.error = None
        self._stop = threading.Event()
        self._thread = None
        self._close_lock = threading.Lock()
        self._sink_closed = False

    def start(self):
        if self._thread is not None:
            return self
        self.sink = self.sink_factory(self.samplerate, self.channels, self.blocksize)
        self._thread = threading.Thread(target=self._run, name="SonusAudioTrack", daemon=True)
        self._thread.start()
        return self

    def _run(self):
        block = numpy.zeros((self.blocksize, self.channels), dtype=numpy.float32)
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                self.callback(block, self.blocksize, None, None)
                data = block.astype("<f4", copy=False).tobytes()
                offset = 0
                while offset < len(data) and not self._stop.is_set():
                    payload = data[offset:]
                    written = int(self.sink.write(_java_bytes(payload) if self._native else payload))
                    if written <= 0 or written > len(payload):
                        raise OSError("AudioTrack non ha accettato il blocco PCM")
                    offset += written
                # AudioTrack blocks when its device buffer is full. This also
                # avoids busy looping before the first buffer fills or in tests.
                self._stop.wait(max(0, self.blocksize / self.samplerate - (time.monotonic() - started)))
        except Exception as error:
            if not self._stop.is_set():
                self.error = error
        finally:
            self.abort()
            if self.finished_callback:
                self.finished_callback()

    def abort(self):
        self._stop.set()
        # Closing AudioTrack wakes a blocked write before joining the thread.
        with self._close_lock:
            if self.sink is not None and not self._sink_closed:
                self._sink_closed = True
                try:
                    self.sink.close()
                except Exception:
                    pass

    def close(self):
        self.abort()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)

