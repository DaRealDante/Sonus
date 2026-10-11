"""First start of Sonus: brings over the library of Synth Music (or Ken Music) without touching the original."""
import json
import os
import shutil
import sqlite3

SKIP_NAMES = {"temp", "log.txt", "log.txt.old"}
PATH_COLUMNS = (("songs", "path"), ("songs", "cover"), ("songs", "videoPath"), ("playlists", "cover"))


MEDIA_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".webm", ".mp4", ".mkv",
                    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


def _linkOrCopy(sourcePath, destinationPath):
    """Songs, videos and pictures: hard link when possible (no extra space on disk, deleting one app keeps the other
    working; they are never edited in place). Everything else is a real copy."""
    if os.path.splitext(sourcePath)[1].lower() in MEDIA_EXTENSIONS:
        try:
            os.link(sourcePath, destinationPath)
            return destinationPath
        except OSError:
            pass
    return shutil.copy2(sourcePath, destinationPath)


def _rewritePaths(databasePath, oldRoot, newRoot):
    connection = sqlite3.connect(databasePath)
    try:
        for table, column in PATH_COLUMNS:
            try:
                connection.execute(
                    f"UPDATE {table} SET {column} = ? || substr({column}, ?) WHERE substr({column}, 1, ?) = ?",
                    (newRoot, len(oldRoot) + 1, len(oldRoot), oldRoot))
            except sqlite3.Error:
                pass
        connection.commit()
    finally:
        connection.close()


def _rewriteSettings(settingsPath, oldRoot, newRoot):
    try:
        with open(settingsPath, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return

    def fix(value):
        if isinstance(value, str) and value.startswith(oldRoot):
            return newRoot + value[len(oldRoot):]
        if isinstance(value, list):
            return [fix(item) for item in value]
        if isinstance(value, dict):
            return {key: fix(item) for key, item in value.items()}
        return value

    with open(settingsPath, "w", encoding="utf-8") as handle:
        json.dump(fix(data), handle, ensure_ascii=False, indent=2)


def importOldLibrary(newRoot, oldRoots):
    """Copies the first old data folder that has a library into newRoot. Returns the folder used, or None."""
    if os.path.isfile(os.path.join(newRoot, "library.db")):
        return None
    oldRoot = next((folder for folder in oldRoots if os.path.isfile(os.path.join(folder, "library.db"))), None)
    if oldRoot is None:
        return None
    partialRoot = newRoot + ".importing"
    shutil.rmtree(partialRoot, ignore_errors=True)
    shutil.copytree(oldRoot, partialRoot, copy_function=_linkOrCopy,
                    ignore=lambda folder, names: [name for name in names if name in SKIP_NAMES])
    # The database and settings get rewritten: those must be real copies, never links to the old app's files.
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            os.remove(os.path.join(partialRoot, "library.db" + suffix))
        except OSError:
            pass
    source = sqlite3.connect(os.path.join(oldRoot, "library.db"))
    target = sqlite3.connect(os.path.join(partialRoot, "library.db"))
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    settingsCopy = os.path.join(partialRoot, "settings.json")
    if os.path.isfile(settingsCopy):
        os.remove(settingsCopy)
        shutil.copy2(os.path.join(oldRoot, "settings.json"), settingsCopy)
    _rewritePaths(os.path.join(partialRoot, "library.db"), oldRoot, newRoot)
    _rewriteSettings(os.path.join(partialRoot, "settings.json"), oldRoot, newRoot)
    if os.path.isdir(newRoot):
        for name in os.listdir(partialRoot):
            target = os.path.join(newRoot, name)
            if not os.path.exists(target):
                os.replace(os.path.join(partialRoot, name), target)
        shutil.rmtree(partialRoot, ignore_errors=True)
    else:
        os.replace(partialRoot, newRoot)
    return oldRoot
