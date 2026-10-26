"""Chaquopy entry points. Kotlin calls these off its main thread."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import traceback

from .runtime import Runtime

_lock = threading.RLock()
_runtime = None
_controller = None
_callback = None
_paths = None
_error_id = 0


def configure_environment(data_dir, native_dir, packages_dir):
    data = Path(str(data_dir)).resolve()
    native = Path(str(native_dir)).resolve()
    packages = Path(str(packages_dir)).resolve()
    data.mkdir(parents=True, exist_ok=True)
    temporary = data / "temp"
    temporary.mkdir(parents=True, exist_ok=True)
    os.environ["SONUS_DATA_DIR"] = str(data)
    os.environ["SONUS_NATIVE_DIR"] = str(native)
    os.environ["SONUS_PACKAGES_DIR"] = str(packages)
    os.environ["TMPDIR"] = str(temporary)
    tempfile.tempdir = str(temporary)
    # youtubedl-android extracts FFmpeg's dependent shared libraries here.
    # They must be inherited by native child processes, not only loaded into JVM.
    libraries = str(packages / "ffmpeg/usr/lib") + ":" + str(native)
    previous = os.environ.get("LD_LIBRARY_PATH", "")
    if previous != libraries and not previous.startswith(libraries + ":"):
        os.environ["LD_LIBRARY_PATH"] = libraries + (":" + previous if previous else "")
    try:
        import certifi
        os.environ["SSL_CERT_FILE"] = certifi.where()
    except ImportError:
        pass
    return str(data), str(native), str(packages)


def _emit(state):
    callback = _callback
    if callback is None:
        return
    payload = state if isinstance(state, str) else json.dumps(state, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    try:
        callback.onEvent(payload)
    except Exception:
        # A detached Activity/JVM callback must not recursively crash the loop.
        traceback.print_exc()


def _on_error(error, action="runtime"):
    global _error_id
    _error_id += 1
    state = _controller.snapshot() if _controller is not None else {"ready": False}
    state.update(message=str(error) or type(error).__name__, messageId=_error_id,
                 error={"action": action, "message": str(error) or type(error).__name__})
    _emit(state)


def initialize(data_dir, native_dir, packages_dir, callback):
    """Create all core state and SQLite connections on the serial runtime thread."""
    global _runtime, _controller, _callback, _paths
    with _lock:
        paths = (str(Path(str(data_dir)).resolve()), str(Path(str(native_dir)).resolve()), str(Path(str(packages_dir)).resolve()))
        if _runtime is not None:
            if paths != _paths:
                raise RuntimeError("Sonus è già inizializzato con un'altra cartella dati")
            _callback = callback
            snapshot = _runtime.call_sync(_controller.snapshot)
            _runtime.call_soon(_emit, snapshot)
            return json.dumps(snapshot, ensure_ascii=False, allow_nan=False)
        existing_config = sys.modules.get("sonus_core.config")
        if existing_config is not None and os.path.normcase(os.path.realpath(existing_config.DATA_DIR)) != os.path.normcase(paths[0]):
            raise RuntimeError("La cartella Sonus non può cambiare nello stesso processo Python")
        _paths = configure_environment(*paths)
        _callback = callback
        runtime = Runtime(on_error=_on_error).start()
        _runtime = runtime
        try:
            def create():
                global _controller
                from .android_audio import cleanup_stale_pcm
                cleanup_stale_pcm()
                # Apply downloaded pure-Python YouTube updates before importing
                # the controller and downloader, exactly as on desktop startup.
                from sonus_core.updater import activateDownloadedEngine
                activateDownloadedEngine()
                from .controller import Controller
                _controller = Controller(runtime=runtime, emit=_emit)
                state = _controller.snapshot()
                _emit(state)
                return state
            state = runtime.call_sync(create)
        except Exception:
            _runtime = None
            runtime.close()
            _controller = None
            _callback = None
            _paths = None
            raise
        return json.dumps(state, ensure_ascii=False, allow_nan=False)


def command(action, payload_json="{}"):
    with _lock:
        runtime = _runtime
        if runtime is None:
            raise RuntimeError("Sonus non è inizializzato")
        try:
            payload = json.loads(str(payload_json or "{}"))
            if not isinstance(payload, dict):
                raise ValueError("Il comando richiede un oggetto JSON")
            if not isinstance(action, str) or not action.strip():
                raise ValueError("Azione non valida")
        except (ValueError, TypeError) as error:
            runtime.call_soon(_on_error, error, str(action))
            return False
        runtime.call_soon(_controller.dispatch, str(action), payload)
        return True


def close():
    global _runtime, _controller, _callback, _paths
    with _lock:
        runtime, controller = _runtime, _controller
        if runtime is None:
            return
        try:
            if controller is not None:
                runtime.call_sync(controller.close)
        finally:
            runtime.close()
            _runtime = None
            _controller = None
            _callback = None
            _paths = None
