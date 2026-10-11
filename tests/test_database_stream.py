import os
import tempfile

from app.database import Database, isStreamPath


def makeDatabase():
    return Database(os.path.join(tempfile.mkdtemp(), "library.db"))


def test_streamSongCreatedAndFoundByUrl():
    database = makeDatabase()
    songId = database.addStreamSong("https://www.youtube.com/watch?v=abcdefghijk", "Titolo", "Artista", "", 200, None)
    song = database.getSong(songId)
    assert song["path"] == "stream:https://www.youtube.com/watch?v=abcdefghijk"
    assert isStreamPath(song["path"])
    assert not isStreamPath("C:/musica/file.mp3")
    assert database.findSongByUrl("https://www.youtube.com/watch?v=abcdefghijk")["id"] == songId
    assert database.addStreamSong("https://www.youtube.com/watch?v=abcdefghijk", "Altro", "", "", 0, None) == songId


def test_hiddenSongsNotInLibraryLists():
    database = makeDatabase()
    visibleId = database.addStreamSong("https://youtu.be/aaaaaaaaaaa", "Visibile", "A", "", 1, None)
    hiddenId = database.addStreamSong("https://youtu.be/bbbbbbbbbbb", "Nascosta", "B", "", 1, None, hidden=True)
    database.registerPlay(hiddenId)
    listedIds = {song["id"] for song in database.allSongs()}
    assert visibleId in listedIds and hiddenId not in listedIds
    assert hiddenId not in {song["id"] for song in database.searchSongs("Nascosta")}
    assert hiddenId not in {song["id"] for song in database.recentlyPlayed()}
    assert hiddenId not in {song["id"] for song in database.mostPlayed()}
    database.updateSong(hiddenId, hidden=0)
    assert hiddenId in {song["id"] for song in database.allSongs()}


def test_playlistListenerCalledForEveryChange():
    database = makeDatabase()
    calls = []
    database.playlistListener = calls.append
    playlistId = database.createPlaylist("Condivisa")
    songIds = [database.addStreamSong(f"https://youtu.be/{index:011d}", f"S{index}", "", "", 1, None) for index in range(3)]
    database.addToPlaylist(playlistId, songIds)
    entries = database.playlistSongs(playlistId)
    database.setPlaylistOrder([entry["entryId"] for entry in reversed(entries)])
    database.removeEntries([entries[0]["entryId"]])
    database.updatePlaylist(playlistId, "Nuovo nome", "", None)
    database.deleteSongs([songIds[1]])
    assert calls == [playlistId] * 5


def test_sharedPlaylistStorage():
    database = makeDatabase()
    playlistId = database.createPlaylist("P")
    database.setShared(playlistId, "SONUSP-AAAA-BBBB", '{"tracks": []}')
    assert database.sharedPlaylist(playlistId)["code"] == "SONUSP-AAAA-BBBB"
    assert [row["playlistId"] for row in database.sharedPlaylists()] == [playlistId]
    database.unshare(playlistId)
    assert database.sharedPlaylist(playlistId) is None
    database.setShared(playlistId, "SONUSP-AAAA-BBBB", "{}")
    database.deletePlaylist(playlistId)
    assert database.sharedPlaylists() == []
