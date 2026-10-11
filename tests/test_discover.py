import os
import tempfile
import time

from app.discover import DeezerClient, DiscoverCache, buildDiscover, libraryProfile, mainArtist, playTarget, trackKeyOf


def fakeFetch(routes, calls=None):
    def fetch(url):
        if calls is not None:
            calls.append(url)
        for prefix, payload in routes.items():
            if prefix in url:
                if isinstance(payload, Exception):
                    raise payload
                return payload
        raise RuntimeError("offline")
    return fetch


def track(title, artist, album="A"):
    return {"title": title, "duration": 200, "artist": {"name": artist}, "album": {"title": album, "cover_xl": "http://img/" + title}}


ROUTES = {
    "/search/artist?q=Ultimo": {"data": [{"id": 1, "name": "Ultimo", "picture_xl": "http://img/ultimo"}]},
    "/artist/1/related": {"data": [{"id": 2, "name": "Tananai"}, {"id": 3, "name": "Olly"}]},
    "/artist/1/albums": {"data": [{"id": 50, "title": "Nuovo", "release_date": time.strftime("%Y-%m-%d"), "cover_xl": "x"},
                                  {"id": 51, "title": "Vecchio", "release_date": "2019-01-01"}]},
    "/artist/2/top": {"data": [track("Tango", "Tananai"), track("Già Mia", "Tananai")]},
    "/artist/3/top": {"data": [track("Balorda nostalgia", "Olly")]},
    "/chart/0/tracks": {"data": [track("Hit", "Star")]},
    "/search/playlist": {"data": [{"id": 99, "title": "Top Italia", "user": {"name": "Deezer Charts Italia"}}]},
    "/playlist/99/tracks": {"data": [track("Hit IT", "Cantante")]},
}


def test_buildDiscoverSectionsAndExclusions():
    profile = {"topArtists": ["Ultimo"], "recentYoutube": [{"title": "Altrove", "artist": "Ultimo", "videoId": "abcdefghijk"}],
               "ownedKeys": [trackKeyOf("Tango", "Tananai")]}
    mix = lambda videoId, limit: [{"title": "Simile", "artist": "Qualcuno", "album": "", "duration": 1, "image": "", "url": "https://youtu.be/zzzzzzzzzzz"}]
    result = buildDiscover(profile, DeezerClient(fakeFetch(ROUTES)), mix, shuffleSeed=1)
    sections = {section["id"]: section for section in result["sections"]}
    assert [item["title"] for item in sections["forYou"]["items"]].count("Tango") == 0
    assert {item["title"] for item in sections["forYou"]["items"]} == {"Già Mia", "Balorda nostalgia"}
    assert sections["because:abcdefghijk"]["title"] == "Perché hai ascoltato \"Altrove\""
    assert [artist["name"] for artist in sections["similarArtists"]["items"]] == ["Tananai", "Olly"]
    assert [artist["name"] for artist in sections["yourArtists"]["items"]] == ["Ultimo"]
    assert [album["title"] for album in sections["releases"]["items"]] == ["Nuovo"]
    assert sections["chart"]["items"][0]["title"] == "Hit"
    assert sections["italy"]["items"][0]["title"] == "Hit IT"


def test_offlineGivesEmptyButValidResult():
    result = buildDiscover({"topArtists": ["Ultimo"], "recentYoutube": [], "ownedKeys": []}, DeezerClient(fakeFetch({})),
                           lambda videoId, limit: [])
    assert result["sections"] == []


def test_emptyLibraryStillShowsCharts():
    result = buildDiscover({"topArtists": [], "recentYoutube": [], "ownedKeys": []}, DeezerClient(fakeFetch(ROUTES)), lambda *a: [])
    assert [section["id"] for section in result["sections"]] == ["chart", "italy"]


def test_cacheExpires(tmp_path):
    cache = DiscoverCache(str(tmp_path / "c.json"), ttlSeconds=100)
    cache.save({"sections": [1], "builtAt": 1000})
    assert cache.load(nowSeconds=1050)["sections"] == [1]
    assert cache.load(nowSeconds=1200) is None


def test_helpers():
    assert mainArtist("Anna x Guè feat. Sfera") == "Anna"
    assert mainArtist("Earth, Wind & Fire") == "Earth"
    assert playTarget({"title": "Tango", "artist": "Tananai", "url": None}) == "ytsearch1:Tananai - Tango audio"
    assert playTarget({"title": "x", "artist": "y", "url": "https://youtu.be/abcdefghijk"}) == "https://youtu.be/abcdefghijk"


def test_libraryProfileFromDatabase():
    from app.database import Database
    database = Database(os.path.join(tempfile.mkdtemp(), "library.db"))
    first = database.addStreamSong("https://youtu.be/aaaaaaaaaaa", "Altrove", "Ultimo", "", 1, None)
    second = database.addSong("/m/x.mp3", "Pezzo", "Tananai feat. X", "", 1)
    for _ in range(3):
        database.registerPlay(first)
    database.registerPlay(second)
    profile = libraryProfile(database)
    assert profile["topArtists"] == ["Ultimo", "Tananai"]
    assert profile["recentYoutube"][0]["videoId"] == "aaaaaaaaaaa"
    assert trackKeyOf("Altrove", "Ultimo") in profile["ownedKeys"]
