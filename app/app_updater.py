"""Checks GitHub Releases for a newer Sonus and downloads the installer."""
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

from .config import TEMP_DIR, UPDATE_REPO, VERSION

USER_AGENT = f"Sonus/{VERSION}"


def versionTuple(text):
    numbers = re.findall(r"\d+", str(text))
    return tuple(int(number) for number in numbers[:4]) or (0,)


def isConfigured():
    return bool(UPDATE_REPO and "/" in UPDATE_REPO)


def checkLatestRelease():
    """Returns {"version", "notes", "url", "size", "name"} if a newer version exists, otherwise None."""
    if not isConfigured():
        raise RuntimeError("Aggiornamenti online non configurati")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest",
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            release = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise
    latestVersion = (release.get("tag_name") or "").lstrip("vV")
    if versionTuple(latestVersion) <= versionTuple(VERSION):
        return None
    asset = next((item for item in release.get("assets", [])
                  if item.get("name", "").lower().startswith("sonus_setup") and item.get("name", "").lower().endswith(".exe")), None)
    if not asset:
        return None
    return {
        "version": latestVersion,
        "notes": (release.get("body") or "").strip(),
        "url": asset["browser_download_url"],
        "size": asset.get("size") or 0,
        "name": asset["name"],
    }


def downloadInstaller(info, progressCallback=None):
    targetPath = os.path.join(TEMP_DIR, info["name"])
    partialPath = targetPath + ".part"
    request = urllib.request.Request(info["url"], headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response, open(partialPath, "wb") as handle:
        total = int(response.headers.get("Content-Length") or info.get("size") or 0)
        done = 0
        while True:
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            done += len(chunk)
            if progressCallback and total:
                progressCallback(int(done * 100 / total))
    if info.get("size") and os.path.getsize(partialPath) != info["size"]:
        os.remove(partialPath)
        raise RuntimeError("Download incompleto, riprova")
    os.replace(partialPath, targetPath)
    return targetPath


def installFolder():
    return os.path.dirname(os.path.abspath(sys.executable))


def canWrite(folder):
    """True if this user can change the app folder without administrator rights (Programs in AppData: yes,
    C:\\Program Files: no)."""
    probe = os.path.join(folder, f".sonus_write_test_{os.getpid()}")
    try:
        with open(probe, "w") as handle:
            handle.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def launchInstaller(path):
    """Starts the installer. If the app sits in a protected folder, Windows asks for permission (UAC) first.
    Returns None when it started, otherwise a short reason."""
    arguments = ["/SILENT", "/NOCANCEL"]
    if sys.platform != "win32" or canWrite(installFolder()):
        try:
            subprocess.Popen([path, *arguments], close_fds=True)
            return None
        except OSError as error:
            return str(error)
    import ctypes
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", path, " ".join(arguments), None, 1)
    if result > 32:
        return None
    if result == 5:
        return "Permesso negato: per aggiornare serve cliccare Sì nella finestra di Windows"
    return f"Windows non ha avviato l'aggiornamento (codice {result})"
