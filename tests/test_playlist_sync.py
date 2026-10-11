import os
import tempfile

from app.playlist_sync import SharedPlaylists, assignKeys, buildSnapshot, mergeSnapshots, sameContent
from tests.broker import localBroker, pump, waitFor  # noqa: F401

META = {"name": "Estate", "description": "", "cover": ""}


def track(title):
    return {"title": title, "artist": "A", "album": "", "duration": 100, "url": None, "query": None}


def snapshotOf(titles, previous=None, at=1000, meta=META):
    return buildSnapshot(meta, [(f"t:{title}", track(title)) for title in titles], previous, at)


def titles(snapshot):
    return [key[2:] for key in snapshot["order"]]


def test_assignKeysForDuplicates():
    assert assignKeys(["a", "a", "b", "a"], [None, None, None, None]) == ["a", "a#2", "b", "a#3"]
    assert assignKeys(["a", "a"], ["a#2", None]) == ["a#2", "a"]


def test_additionsFromBothKept():
    base = snapshotOf(["uno", "due"])
    mine = snapshotOf(["uno", "due", "tre"], base, at=2000)
    theirs = snapshotOf(["uno", "due", "quattro"], base, at=2100)
    merged = mergeSnapshots(mine, theirs)
    assert set(titles(merged)) == {"uno", "due", "tre", "quattro"}
    assert sameContent(merged, mergeSnapshots(theirs, mine))


def test_removalAfterAdditionWinsAndReAddWins():
    base = snapshotOf(["uno", "due"])
    removed = snapshotOf(["uno"], base, at=2000)
    assert titles(mergeSnapshots(base, removed)) == ["uno"]
    readded = snapshotOf(["uno", "due"], removed, at=3000)
    assert titles(mergeSnapshots(removed, readded)) == ["uno", "due"]


def test_orderFromLatestEditAndMergeIdempotent():
    base = snapshotOf(["uno", "due", "tre"])
    reordered = snapshotOf(["tre", "uno", "due"], base, at=2000)
    added = snapshotOf(["uno", "due", "tre", "quattro"], base, at=1500)
    merged = mergeSnapshots(added, reordered)
    assert titles(merged) == ["tre", "uno", "due", "quattro"]
    assert sameContent(mergeSnapshots(merged, merged), merged)
    assert sameContent(mergeSnapshots(merged, reordered), mergeSnapshots(reordered, merged))


def test_renameFromLatest():
    base = snapshotOf(["uno"])
    renamed = snapshotOf(["uno"], base, at=5000, meta={"name": "Inverno", "description": "", "cover": ""})
    assert mergeSnapshots(base, renamed)["name"] == "Inverno"
    unchanged = snapshotOf(["uno"], base, at=9000)
    assert unchanged["metaAt"] == base["metaAt"] and unchanged["orderAt"] == base["orderAt"]


def makeLibrary():
    from app.database import Database
    database = Database(os.path.join(tempfile.mkdtemp(), "library.db"))
    notices = []
    return database, SharedPlaylists(database, notices.append), notices


def playlistTitles(database, playlistId):
    return [song["title"] for song in database.playlistSongs(playlistId)]


def test_sharedPlaylistSyncsBothWaysIncludingOffline(localBroker):
    aliceDb, aliceShared, _ = makeLibrary()
    brunoDb, brunoShared, brunoNotices = makeLibrary()
    songIds = [aliceDb.addStreamSong(f"https://youtu.be/{index:011d}", f"Brano {index}", "Band", "", 100, None) for index in range(3)]
    localFile = aliceDb.addSong("/musica/mia.mp3", "Mia Canzone", "Ken", "", 120)
    playlistId = aliceDb.createPlaylist("Viaggio")
    aliceDb.addToPlaylist(playlistId, songIds + [localFile])
    code = aliceShared.share(playlistId)
    assert code.startswith("SONUSP-")

    brunoPlaylist = brunoShared.addShared(code)
    assert waitFor(lambda: playlistTitles(brunoDb, brunoPlaylist) == ["Brano 0", "Brano 1", "Brano 2", "Mia Canzone"], 10)
    assert brunoDb.getPlaylist(brunoPlaylist)["name"] == "Viaggio"
    mine = brunoDb.playlistSongs(brunoPlaylist)[3]
    assert mine["path"].startswith("stream:ytsearch1:")
    assert any("aggiunta" in notice for notice in brunoNotices)

    newSong = brunoDb.addStreamSong("https://youtu.be/zzzzzzzzzzz", "Da Bruno", "B", "", 90, None)
    brunoDb.addToPlaylist(brunoPlaylist, [newSong])
    assert waitFor(lambda: "Da Bruno" in playlistTitles(aliceDb, playlistId), 10)

    entries = aliceDb.playlistSongs(playlistId)
    aliceDb.removeEntries([entries[0]["entryId"]])
    assert waitFor(lambda: "Brano 0" not in playlistTitles(brunoDb, brunoPlaylist), 10)

    brunoShared.stopAll()
    pump(0.5)
    offlineSong = brunoDb.addStreamSong("https://youtu.be/yyyyyyyyyyy", "Offline", "B", "", 90, None)
    brunoDb.addToPlaylist(brunoPlaylist, [offlineSong])
    aliceDb.updatePlaylist(playlistId, "Viaggio 2026", "", None)
    pump(1.5)
    brunoShared.start()
    assert waitFor(lambda: "Offline" in playlistTitles(aliceDb, playlistId) and brunoDb.getPlaylist(brunoPlaylist)["name"] == "Viaggio 2026", 12)
    pump(2)
    assert playlistTitles(aliceDb, playlistId) == playlistTitles(brunoDb, brunoPlaylist)
    assert len(playlistTitles(aliceDb, playlistId)) == len(set(playlistTitles(aliceDb, playlistId)))
    aliceShared.stopAll()
    brunoShared.stopAll()


def countPublishes(shared, counts, name):
    original = shared.link.publish

    def wrapper(*args, **kwargs):
        counts[name] += 1
        return original(*args, **kwargs)

    shared.link.publish = wrapper


def test_noEndlessRepublishWhenCopiesDiffer(localBroker):
    aliceDb, aliceShared, _ = makeLibrary()
    brunoDb, brunoShared, _ = makeLibrary()
    brunoDb.addSong("/m/brano.mp3", "Brano", "Band", "", 101.3, None, "youtube", "https://youtu.be/aaaaaaaaaaa")
    streamId = aliceDb.addStreamSong("https://youtu.be/aaaaaaaaaaa", "Brano", "Band", "", 100, None)
    localId = aliceDb.addSong("/musica/solo-mia.mp3", "Solo Mia", "Ken", "", 120)
    playlistId = aliceDb.createPlaylist("P")
    aliceDb.addToPlaylist(playlistId, [streamId, localId])
    counts = {"alice": 0, "bruno": 0}
    countPublishes(aliceShared, counts, "alice")
    countPublishes(brunoShared, counts, "bruno")
    brunoPlaylist = brunoShared.addShared(aliceShared.share(playlistId))
    assert waitFor(lambda: len(brunoDb.playlistSongs(brunoPlaylist)) == 2, 10)
    extraId = brunoDb.addStreamSong("https://youtu.be/bbbbbbbbbbb", "Altro", "X", "", 90, None)
    brunoDb.addToPlaylist(brunoPlaylist, [extraId])
    assert waitFor(lambda: len(aliceDb.playlistSongs(playlistId)) == 3, 10)
    pump(4)
    assert counts["alice"] + counts["bruno"] <= 6, counts
    aliceShared.stopAll()
    brunoShared.stopAll()


def test_placeholderNeverOverwritesOwnerPlaylist(localBroker):
    import json
    aliceDb, aliceShared, _ = makeLibrary()
    songId = aliceDb.addStreamSong("https://youtu.be/ccccccccccc", "Uno", "A", "", 100, None)
    playlistId = aliceDb.createPlaylist("Originale")
    aliceDb.addToPlaylist(playlistId, [songId])
    code = aliceShared.share(playlistId)
    pump(0.5)
    aliceShared.stopAll()
    aliceShared.link.clearRetained = lambda *args: None
    from app.session_link import Link
    eraser = Link()
    eraser.start()
    assert waitFor(eraser.isConnected)
    eraser.clearRetained(code, "snapshot")
    eraser.stop()

    brunoDb, brunoShared, _ = makeLibrary()
    brunoPlaylist = brunoShared.addShared(code)
    pump(1)
    brunoShared.stopAll()
    brunoShared.start()
    pump(1)
    assert json.loads(brunoDb.sharedPlaylist(brunoPlaylist)["snapshot"]).get("_awaiting")

    aliceShared.start()
    assert waitFor(lambda: brunoDb.getPlaylist(brunoPlaylist)["name"] == "Originale", 10)
    pump(1)
    assert aliceDb.getPlaylist(playlistId)["name"] == "Originale"
    aliceShared.stopAll()
    brunoShared.stopAll()


def test_sharedPlaylistsDisconnectWhenIdleAndStillSync(localBroker, monkeypatch):
    """The free server counts connection minutes: shared playlists connect only for a while, then check now and then."""
    import app.playlist_sync as playlistSync
    monkeypatch.setattr(playlistSync, "AWAKE_MS", 1500)
    monkeypatch.setattr(playlistSync, "CHECK_EVERY_MS", 2500)
    monkeypatch.setattr(playlistSync, "CHECK_AWAKE_MS", 800)
    aliceDb, aliceShared, _ = makeLibrary()
    brunoDb, brunoShared, _ = makeLibrary()
    songId = aliceDb.addStreamSong("https://youtu.be/aaaaaaaaaaa", "Prima", "Band", "", 100, None)
    playlistId = aliceDb.createPlaylist("Idle")
    aliceDb.addToPlaylist(playlistId, [songId])
    code = aliceShared.share(playlistId)
    brunoPlaylist = brunoShared.addShared(code)
    assert waitFor(lambda: playlistTitles(brunoDb, brunoPlaylist) == ["Prima"], 10)
    assert waitFor(lambda: not aliceShared.link.running, 8)
    assert waitFor(lambda: not brunoShared.link.running, 8)

    newSong = aliceDb.addStreamSong("https://youtu.be/bbbbbbbbbbb", "Seconda", "Band", "", 100, None)
    aliceDb.addToPlaylist(playlistId, [newSong])
    assert aliceShared.link.running
    assert waitFor(lambda: playlistTitles(brunoDb, brunoPlaylist) == ["Prima", "Seconda"], 12)
    aliceShared.stopAll()
    brunoShared.stopAll()
    assert not aliceShared.link.running
