import json
import os
import sqlite3

from app.migration import importOldLibrary


def makeOldLibrary(root):
    os.makedirs(os.path.join(root, "music"))
    os.makedirs(os.path.join(root, "covers"))
    os.makedirs(os.path.join(root, "temp"))
    songPath = os.path.join(root, "music", "canzone.mp3")
    coverPath = os.path.join(root, "covers", "c.jpg")
    for path in (songPath, coverPath):
        with open(path, "wb") as handle:
            handle.write(b"x" * 100)
    connection = sqlite3.connect(os.path.join(root, "library.db"))
    connection.execute("CREATE TABLE songs (id INTEGER PRIMARY KEY, path TEXT, cover TEXT, videoPath TEXT)")
    connection.execute("CREATE TABLE playlists (id INTEGER PRIMARY KEY, cover TEXT)")
    connection.execute("INSERT INTO songs (path, cover, videoPath) VALUES (?, ?, NULL)", (songPath, coverPath))
    connection.execute("INSERT INTO songs (path, cover) VALUES ('stream:https://youtu.be/x', NULL)")
    connection.execute("INSERT INTO songs (path, cover) VALUES (?, NULL)", (r"D:\Musica\mia.mp3",))
    connection.execute("INSERT INTO playlists (cover) VALUES (?)", (coverPath,))
    connection.commit()
    connection.close()
    with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as handle:
        json.dump({"musicDir": os.path.join(root, "music"), "volume": 40}, handle)
    return songPath


def test_importCopiesLibraryAndFixesPaths(tmp_path):
    oldRoot, newRoot = str(tmp_path / "SynthMusic"), str(tmp_path / "Sonus")
    oldSong = makeOldLibrary(oldRoot)
    assert importOldLibrary(newRoot, [oldRoot, str(tmp_path / "KenMusic")]) == oldRoot
    connection = sqlite3.connect(os.path.join(newRoot, "library.db"))
    paths = [row[0] for row in connection.execute("SELECT path FROM songs ORDER BY id")]
    covers = [row[0] for row in connection.execute("SELECT cover FROM playlists")]
    connection.close()
    assert paths[0] == os.path.join(newRoot, "music", "canzone.mp3") and os.path.isfile(paths[0])
    assert paths[1:] == ["stream:https://youtu.be/x", r"D:\Musica\mia.mp3"]
    assert covers == [os.path.join(newRoot, "covers", "c.jpg")]
    settings = json.load(open(os.path.join(newRoot, "settings.json"), encoding="utf-8"))
    assert settings == {"musicDir": os.path.join(newRoot, "music"), "volume": 40}
    assert not os.path.exists(os.path.join(newRoot, "temp"))
    # the old app keeps working, untouched
    old = sqlite3.connect(os.path.join(oldRoot, "library.db"))
    assert old.execute("SELECT path FROM songs ORDER BY id").fetchone()[0] == oldSong
    old.close()
    assert json.load(open(os.path.join(oldRoot, "settings.json")))["musicDir"] == os.path.join(oldRoot, "music")
    assert importOldLibrary(newRoot, [oldRoot]) is None


def test_nothingToImport(tmp_path):
    assert importOldLibrary(str(tmp_path / "Sonus"), [str(tmp_path / "nope")]) is None
