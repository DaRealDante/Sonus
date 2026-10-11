from app.together_sync import ClockSync, expectedPosition, isNewer, trackFromSong, trackKey


def test_trackKeyUsesYoutubeIdOrNormalizedNames():
    assert trackKey("X", "Y", "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=3") == "yt:dQw4w9WgXcQ"
    assert trackKey("X", "Y", "https://youtu.be/dQw4w9WgXcQ") == "yt:dQw4w9WgXcQ"
    assert trackKey("Perché  Sì!", "Ultimo") == trackKey("perche si", "ULTIMO")


def test_trackFromStreamSearchSongKeepsQuery():
    track = trackFromSong({"title": "Brano", "artist": "Artista", "path": "stream:ytsearch1:Artista - Brano audio", "duration": 200})
    assert track["query"] == "ytsearch1:Artista - Brano audio"
    assert track["url"] is None
    assert track["key"] == "t:brano|artista"


def test_isNewerOrdersByVersionThenSender():
    current = {"version": 5, "by": "bbb"}
    assert isNewer({"version": 6, "by": "zzz"}, current)
    assert not isNewer({"version": 4, "by": "aaa"}, current)
    assert isNewer({"version": 5, "by": "aaa"}, current)
    assert not isNewer({"version": 5, "by": "ccc"}, current)
    assert not isNewer({"version": 5, "by": "bbb"}, current)
    assert isNewer({"version": 1, "by": "x"}, None)


def test_expectedPositionWithRateAndOffset():
    state = {"positionMs": 10000, "playing": True, "at": 50000, "effects": {"rate": 0.85}}
    assert expectedPosition(state, 52000, offsetMs=0) == 11700
    assert expectedPosition(state, 52000, offsetMs=1000) == 12550
    paused = dict(state, playing=False)
    assert expectedPosition(paused, 99999) == 10000
    capped = dict(state, queue=[{"duration": 10.5}], index=0)
    assert expectedPosition(capped, 60000) == 10500


def test_clockSyncPrefersShortestRoundTrip():
    clock = ClockSync()
    assert clock.offset("peer") == 0
    clock.onPong("peer", 1000, 5600, 1200)
    clock.onPong("peer", 2000, 6050, 2100)
    clock.onPong("peer", 3000, 9000, 3900)
    assert clock.offset("peer") == 4000
    clock.forget("peer")
    assert clock.offset("peer") == 0
