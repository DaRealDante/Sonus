"""Keeps the YouTube engine (yt-dlp) fresh without rebuilding the app.

Newer pure-Python wheels are downloaded from PyPI into the data folder and
put in front of sys.path at the next start (wheels are zip-importable).
"""
import glob
import importlib.abc
import importlib.machinery
import json
import os
import sys
import time
import urllib.request

from .config import DATA_DIR

ENGINE_DIR = os.path.join(DATA_DIR, "engine")
STAMP_PATH = os.path.join(ENGINE_DIR, "lastcheck.json")
PACKAGES = {"yt-dlp": "yt_dlp", "yt-dlp-ejs": "yt_dlp_ejs"}
CHECK_INTERVAL = 24 * 3600


def _versionTuple(text):
    parts = []
    for piece in str(text).replace("-", ".").split("."):
        digits = "".join(character for character in piece if character.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _installedWheel(distribution):
    wheelPrefix = distribution.replace("-", "_")
    wheels = glob.glob(os.path.join(ENGINE_DIR, f"{wheelPrefix}-*-py3-none-any.whl"))
    if not wheels:
        return None, None
    best = max(wheels, key=lambda path: _versionTuple(os.path.basename(path).split("-")[1]))
    return best, os.path.basename(best).split("-")[1]


def _bundledVersion(moduleName):
    try:
        if moduleName == "yt_dlp":
            from yt_dlp.version import __version__
            return __version__
        module = __import__(moduleName)
        return getattr(module, "__version__", None) or getattr(__import__(f"{moduleName}._version", fromlist=["x"]), "version", "0")
    except Exception:
        return "0"


class _WheelFinder(importlib.abc.MetaPathFinder):
    def __init__(self, wheels):
        self.wheels = wheels

    def find_spec(self, fullname, path=None, target=None):
        topName = fullname.partition(".")[0]
        if topName not in self.wheels:
            return None
        searchPath = [self.wheels[topName]] if fullname == topName else path
        return importlib.machinery.PathFinder.find_spec(fullname, searchPath)


def activateDownloadedEngine():
    """Call before anything imports yt_dlp. Falls back to the bundled engine if the download is broken."""
    if not os.path.isdir(ENGINE_DIR):
        return None
    wheels = {}
    for distribution, moduleName in PACKAGES.items():
        wheelPath, _ = _installedWheel(distribution)
        if wheelPath:
            wheels[moduleName] = wheelPath
    if not wheels:
        return None
    finder = _WheelFinder(wheels)
    sys.meta_path.insert(0, finder)
    try:
        import yt_dlp  # noqa: F401
        from yt_dlp.version import __version__
        return __version__
    except Exception:
        sys.meta_path.remove(finder)
        for moduleName in [name for name in sys.modules if name.partition(".")[0] in wheels]:
            del sys.modules[moduleName]
        for wheelPath in wheels.values():
            try:
                os.remove(wheelPath)
            except OSError:
                pass
        return None


def checkForEngineUpdate(force=False):
    """Runs in a worker thread. Returns list of updated package names."""
    os.makedirs(ENGINE_DIR, exist_ok=True)
    if not force:
        try:
            with open(STAMP_PATH, "r", encoding="utf-8") as stampFile:
                if time.time() - json.load(stampFile).get("time", 0) < CHECK_INTERVAL:
                    return []
        except (OSError, ValueError):
            pass
    updated = []
    for distribution, moduleName in PACKAGES.items():
        request = urllib.request.Request(f"https://pypi.org/pypi/{distribution}/json", headers={"User-Agent": "Sonus"})
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
        latest = data["info"]["version"]
        wheelUrl = next((item["url"] for item in data["urls"] if item["filename"].endswith("py3-none-any.whl")), None)
        if not wheelUrl:
            continue
        _, downloadedVersion = _installedWheel(distribution)
        currentVersion = max([_bundledVersion(moduleName), downloadedVersion or "0"], key=_versionTuple)
        if _versionTuple(latest) <= _versionTuple(currentVersion):
            continue
        fileName = os.path.join(ENGINE_DIR, wheelUrl.rsplit("/", 1)[-1])
        tempName = fileName + ".part"
        request = urllib.request.Request(wheelUrl, headers={"User-Agent": "Sonus"})
        with urllib.request.urlopen(request, timeout=60) as response, open(tempName, "wb") as wheelFile:
            wheelFile.write(response.read())
        os.replace(tempName, fileName)
        for oldWheel in glob.glob(os.path.join(ENGINE_DIR, f"{distribution.replace('-', '_')}-*.whl")):
            if oldWheel != fileName:
                try:
                    os.remove(oldWheel)
                except OSError:
                    pass
        updated.append(f"{distribution} {latest}")
    with open(STAMP_PATH, "w", encoding="utf-8") as stampFile:
        json.dump({"time": time.time()}, stampFile)
    return updated
