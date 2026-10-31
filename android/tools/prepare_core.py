"""Generate Android-compatible Sonus core without changing any desktop source.

Only imports and documented platform boundaries are rewritten. Protocol, data,
playback, DSP, synchronization and network behavior retain the desktop code.
"""
import argparse
import ast
from pathlib import Path
import textwrap

EXCLUDED = {"single_instance.py", "media_keys.py"}


def _replace_function(source, name, replacement):
    tree = ast.parse(source)
    matches = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name]
    if len(matches) != 1:
        raise ValueError(f"Expected one {name} boundary, found {len(matches)}")
    node = matches[0]
    lines = source.splitlines(keepends=True)
    indent = " " * node.col_offset
    lines[node.lineno - 1:node.end_lineno] = [textwrap.indent(textwrap.dedent(replacement).strip() + "\n", indent)]
    return "".join(lines)


def _replace_imports(source):
    replacements = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("PySide6"):
            if node.module not in ("PySide6.QtCore", "PySide6.QtMultimedia"):
                raise ValueError(f"Unhandled Android Qt boundary: {node.module}")
            names = ", ".join(item.name + (" as " + item.asname if item.asname else "") for item in node.names)
            replacements.append((node.lineno, node.end_lineno, " " * node.col_offset + "from sonus_mobile.runtime import " + names + "\n"))
    lines = source.splitlines(keepends=True)
    for start, end, value in sorted(replacements, reverse=True):
        lines[start - 1:end] = [value]
    return "".join(lines)


def adapt_source(name, source):
    if name == "config.py":
        source = _replace_function(source, "ffmpegExe", '''
            def ffmpegExe():
                native = os.environ.get("SONUS_NATIVE_DIR", "")
                executable = os.path.join(native, "libffmpeg.so")
                if not native or not os.path.isfile(executable):
                    raise FileNotFoundError("Motore FFmpeg Android non inizializzato")
                return executable
        ''')
        source = _replace_function(source, "denoExe", '''
            def denoExe():
                # Kept as an internal compatibility name; Android uses QuickJS.
                native = os.environ.get("SONUS_NATIVE_DIR", "")
                executable = os.path.join(native, "libqjs.so")
                if not native or not os.path.isfile(executable):
                    raise FileNotFoundError("Motore QuickJS Android non inizializzato")
                return executable
        ''')
    elif name == "downloader.py":
        source = source.replace("from .config import TEMP_DIR, denoExe, settings", "from .config import TEMP_DIR, denoExe, ffmpegExe, settings")
        source = source.replace('options["js_runtimes"] = {"deno": {"path": denoPath}}', 'options["js_runtimes"] = {"quickjs": {"path": denoPath}}\n    options["ffmpeg_location"] = ffmpegExe()')
        source = _replace_function(source, "_squareCover", '''
            def _squareCover(imageBytes):
                import io
                from PIL import Image
                try:
                    with Image.open(io.BytesIO(imageBytes)) as image:
                        image.load()
                        side = min(image.width, image.height)
                        if abs(image.width / max(1, image.height) - 4 / 3) < 0.05:
                            side = int(image.width * 9 / 16)
                        left = (image.width - side) // 2
                        top = (image.height - side) // 2
                        cropped = image.crop((left, top, left + side, top + side)).convert("RGB")
                        output = io.BytesIO()
                        cropped.save(output, "JPEG", quality=92)
                        return output.getvalue()
                except (OSError, ValueError):
                    return imageBytes
        ''')
    elif name == "playlist_sync.py":
        source = _replace_function(source, "coverToBase64", '''
            def coverToBase64(coverPath):
                if not coverPath or not os.path.isfile(coverPath):
                    return ""
                import io
                import math
                from PIL import Image
                try:
                    with Image.open(coverPath) as image:
                        image.load()
                        scale = max(COVER_SIZE / image.width, COVER_SIZE / image.height)
                        size = (max(COVER_SIZE, math.ceil(image.width * scale)), max(COVER_SIZE, math.ceil(image.height * scale)))
                        resized = image.convert("RGB").resize(size, Image.Resampling.LANCZOS)
                        output = io.BytesIO()
                        resized.save(output, "JPEG", quality=80)
                        return base64.b64encode(output.getvalue()).decode("ascii")
                except (OSError, ValueError):
                    return ""
        ''')
    elif name == "audio_engine.py":
        source = source.replace("import sounddevice", "from sonus_mobile import android_audio as sounddevice")
        source = source.replace("import numpy\n", "import numpy\nfrom sonus_mobile.android_audio import allocate_pcm\n", 1)
        source = source.replace("numpy.zeros((self.estimatedFrames, CHANNELS), dtype=numpy.int16)", "allocate_pcm(self.estimatedFrames, CHANNELS)")
        source = source.replace("numpy.zeros((max(len(buffer) * 2, decodedFrames + len(frames)), CHANNELS), dtype=numpy.int16)", "allocate_pcm(max(len(buffer) * 2, decodedFrames + len(frames)), CHANNELS)")
        # A device can fail on the first write, before start() returns. Reset
        # before starting so the worker's completion flag cannot be overwritten.
        source = source.replace("            self.stream.start()\n            self.streamError = None", "            self.streamError = None\n            self.stream.start()")
        source = source.replace('        if self.streamError and self._state == QMediaPlayer.PlayingState:\n            self._ensureStream()', '''        if self.streamError and self._state == QMediaPlayer.PlayingState:
            outputError = getattr(self.stream, "error", None)
            if outputError is not None:
                self.streamError = str(outputError)
                self._setState(QMediaPlayer.StoppedState)
                self.errorOccurred.emit(QMediaPlayer.ResourceError, f"Errore uscita audio Android: {outputError}")
            else:
                self._ensureStream()''')
        source = _replace_function(source, "shutdown", '''
            def shutdown(self):
                self.pollTimer.stop()
                # Invalidate worker callbacks before cancel: allocation may be
                # finishing concurrently and must never reattach old storage.
                with self.lock:
                    self.generation += 1
                self._cancelDecoder()
                self._closeStream()
                with self.lock:
                    self.buffer = None
                    self.decodedFrames = 0
        ''')
        # An allocation/decode failure must be reported to the owner thread.
        tree = ast.parse(source)
        decoder = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "_Decoder")
        run = next(node for node in decoder.body if isinstance(node, ast.FunctionDef) and node.name == "run")
        lines = source.splitlines(keepends=True)
        body = "".join(lines[run.lineno:run.end_lineno])
        wrapper = '    def run(self):\n        try:\n' + textwrap.indent(body, "    ") + '\n        except Exception as error:\n            self._kill()\n            if not self.cancelled:\n                self.engine._decoderFailed(self.generation, str(error))\n'
        lines[run.lineno - 1:run.end_lineno] = [wrapper]
        source = "".join(lines)
        source = source.replace('        if failMessage:\n            self._setStatus', '        if failMessage:\n            with self.lock:\n                self.buffer = None\n                self.decodedFrames = 0\n            self._setStatus')
        # Runtime disposal is the final resource boundary, including when
        # controller persistence raises (for example on full app storage).
        source += '\n    def _dispose(self):\n        self.shutdown()\n        super()._dispose()\n'
    elif name == "app_updater.py":
        # Android updates have their own release feed and APK assets; desktop EXE
        # selection and execution must never leak into the Android path.
        source = source.replace('f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest"', 'f"https://api.github.com/repos/{UPDATE_REPO}/releases?per_page=30"')
        source = source.replace('release = json.loads(response.read().decode("utf-8"))', 'releases = json.loads(response.read().decode("utf-8"))\n            release = next((item for item in releases if any(asset.get("name", "").lower().endswith(".apk") for asset in item.get("assets", [])) and not item.get("draft")), {})')
        source = source.replace('if item.get("name", "").lower().startswith("sonus_setup") and item.get("name", "").lower().endswith(".exe")', 'if item.get("name", "").lower().endswith(".apk")')
        source = _replace_function(source, "launchInstaller", '''
            def launchInstaller(path):
                # PackageInstaller intent is owned by the Kotlin host.
                return "Apri il pacchetto APK dal sistema Android per installare l'aggiornamento"
        ''')
    source = _replace_imports(source)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("PySide6"):
            raise ValueError(f"Qt import remains in {name}")
    compile(source, name, "exec")
    return '# Generated by android/tools/prepare_core.py; edit platform adapters, not this file.\n' + source


def prepare_core(source, output):
    root = Path(source).resolve()
    app = root / "app" if (root / "app").is_dir() else root
    target = Path(output).resolve() / "sonus_core"
    if target == app or app in target.parents:
        raise ValueError("Generated output must not be inside desktop app sources")
    target.mkdir(parents=True, exist_ok=True)
    prepared = {}
    for path in sorted(app.glob("*.py")):
        if path.name not in EXCLUDED:
            prepared[path.name] = adapt_source(path.name, path.read_text(encoding="utf-8"))
    if "database.py" not in prepared or "player.py" not in prepared:
        raise ValueError(f"Sonus app sources not found: {app}")
    for name, content in prepared.items():
        destination = target / name
        if not destination.exists() or destination.read_text(encoding="utf-8") != content:
            destination.write_text(content, encoding="utf-8", newline="\n")
    # Delete only obsolete generated modules, never arbitrary output contents.
    for path in target.glob("*.py"):
        if path.name not in prepared and path.read_text(encoding="utf-8").startswith("# Generated by android/tools/prepare_core.py;"):
            path.unlink()
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(prepare_core(args.source, args.output))


if __name__ == "__main__":
    main()
