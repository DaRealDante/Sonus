import json
import os
import random
import re
import time
import urllib.parse
import urllib.request

from .together_sync import normalizeText, youtubeId

DEEZER_API = "https://api.deezer.com"
NEW_RELEASE_DAYS = 90
CACHE_SECONDS = 6 * 3600


def fetchJson(url, timeout=12):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Sonus"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(str(data["error"].get("message") if isinstance(data["error"], dict) else data["error"]))
    return data


def mainArtist(artist):
    return re.split(r"\s*(?:,|&|\bfeat\.?|\bft\.?|\bx\b)\s*", str(artist or ""), maxsplit=1, flags=re.IGNORECASE)[0].strip()


def trackKeyOf(title, artist):
    return normalizeText(re.sub(r"\s*[\(\[].*?[\)\]]", "", str(title or ""))) + "|" + normalizeText(mainArtist(artist))


def deezerTrack(item):
    album = item.get("album") or {}
    artist = item.get("artist") or {}
    return {
        "title": item.get("title_short") or item.get("title") or "",
        "artist": artist.get("name") or "",
        "album": album.get("title") or "",
        "duration": float(item.get("duration") or 0),
        "image": album.get("cover_xl") or album.get("cover_big") or album.get("cover_medium") or "",
        "url": None,
    }


def deezerArtist(item):
    return {
        "id": item.get("id"),
        "name": item.get("name") or "",
        "image": item.get("picture_xl") or item.get("picture_big") or item.get("picture_medium") or "",
    }


def playTarget(track):
    """What the player streams for a discovered track."""
    if track.get("url") and youtubeId(track["url"]):
        return track["url"]
    query = f"{mainArtist(track.get('artist'))} - {track.get('title')}".strip(" -")
    return f"ytsearch1:{query} audio"


class DeezerClient:
    def __init__(self, fetch=fetchJson):
        self.fetch = fetch

    def _get(self, path, **params):
        query = urllib.parse.urlencode(params)
        return self.fetch(f"{DEEZER_API}{path}" + (f"?{query}" if query else ""))

    def searchArtist(self, name):
        data = self._get("/search/artist", q=name, limit=1).get("data") or []
        return deezerArtist(data[0]) if data else None

    def relatedArtists(self, artistId, limit=10):
        return [deezerArtist(item) for item in (self._get(f"/artist/{artistId}/related", limit=limit).get("data") or [])]

    def topTracks(self, artistId, limit=10):
        return [deezerTrack(item) for item in (self._get(f"/artist/{artistId}/top", limit=limit).get("data") or [])]

    def artistAlbums(self, artistId, limit=30):
        return self._get(f"/artist/{artistId}/albums", limit=limit).get("data") or []

    def albumTracks(self, albumId, album=None):
        tracks = []
        for item in self._get(f"/album/{albumId}/tracks", limit=100).get("data") or []:
            track = deezerTrack(item)
            if album:
                track["album"] = album.get("title") or track["album"]
                track["image"] = track["image"] or album.get("image") or ""
            tracks.append(track)
        return tracks

    def chart(self, limit=25):
        return [deezerTrack(item) for item in (self._get("/chart/0/tracks", limit=limit).get("data") or [])]

    def topItaly(self, limit=25):
        playlists = self._get("/search/playlist", q="Top Italia", limit=10).get("data") or []
        chosen = next((item for item in playlists if "deezer" in str((item.get("user") or {}).get("name", "")).lower()), None)
        chosen = chosen or (playlists[0] if playlists else None)
        if not chosen:
            return []
        return [deezerTrack(item) for item in (self._get(f"/playlist/{chosen['id']}/tracks", limit=limit).get("data") or [])]


def youtubeMix(videoId, limit=20):
    """YouTube's own "radio" of a song: songs similar to it."""
    import yt_dlp
    from .downloader import _baseOptions, _normalizeEntry, _splitArtistTitle
    options = _baseOptions()
    options.update({"extract_flat": "in_playlist", "playlistend": limit + 1})
    with yt_dlp.YoutubeDL(options) as youtube:
        info = youtube.extract_info(f"https://www.youtube.com/watch?v={videoId}&list=RD{videoId}", download=False)
    tracks = []
    for entry in info.get("entries") or []:
        if not entry or entry.get("id") == videoId:
            continue
        normalized = _normalizeEntry(entry)
        artist, title = _splitArtistTitle(normalized["title"], normalized["channel"])
        tracks.append({"title": title, "artist": artist, "album": "", "duration": normalized["duration"],
                       "image": normalized["thumbnail"] or "", "url": normalized["url"]})
    return tracks[:limit]


def libraryProfile(database):
    """What the user listens to: top artists by plays, recent YouTube songs, songs already owned."""
    rows = database._rows("SELECT title, artist, url, playCount, lastPlayed, hidden FROM songs")
    playsByArtist = {}
    for row in rows:
        name = mainArtist(row["artist"])
        if name and (row["playCount"] or 0) > 0:
            playsByArtist[name] = playsByArtist.get(name, 0) + (row["playCount"] or 0)
    if not playsByArtist:
        for row in rows:
            name = mainArtist(row["artist"])
            if name and not row["hidden"]:
                playsByArtist[name] = playsByArtist.get(name, 0) + 1
    topArtists = [name for name, plays in sorted(playsByArtist.items(), key=lambda item: -item[1])][:6]
    recent = sorted((row for row in rows if row["lastPlayed"] and youtubeId(row["url"])), key=lambda row: -row["lastPlayed"])
    seen, recentYoutube = set(), []
    for row in recent:
        if mainArtist(row["artist"]) not in seen:
            seen.add(mainArtist(row["artist"]))
            recentYoutube.append({"title": row["title"], "artist": row["artist"], "videoId": youtubeId(row["url"])})
        if len(recentYoutube) == 2:
            break
    ownedKeys = {trackKeyOf(row["title"], row["artist"]) for row in rows if not row["hidden"]}
    return {"topArtists": topArtists, "recentYoutube": recentYoutube, "ownedKeys": sorted(ownedKeys)}


def _notOwned(tracks, ownedKeys, seen=None):
    seen = seen if seen is not None else set()
    result = []
    for track in tracks:
        key = trackKeyOf(track["title"], track["artist"])
        if key in ownedKeys or key in seen:
            continue
        seen.add(key)
        result.append(track)
    return result


def buildDiscover(profile, client, mixProvider=None, nowSeconds=None, shuffleSeed=None):
    """All the Scopri sections. Every source is optional: a failing one just leaves its section out."""
    nowSeconds = nowSeconds or time.time()
    mixProvider = mixProvider or youtubeMix
    randomizer = random.Random(shuffleSeed)
    ownedKeys = set(profile.get("ownedKeys") or [])
    sections = []
    yourArtists, similarArtists, recommended, releases = [], [], [], []
    knownNames = {normalizeText(name) for name in profile.get("topArtists") or []}
    for name in (profile.get("topArtists") or [])[:5]:
        try:
            artist = client.searchArtist(name)
        except Exception:
            artist = None
        if not artist:
            continue
        yourArtists.append(artist)
        try:
            for related in client.relatedArtists(artist["id"], 6):
                if normalizeText(related["name"]) not in knownNames and all(item["id"] != related["id"] for item in similarArtists):
                    similarArtists.append(related)
        except Exception:
            pass
        try:
            cutoff = time.strftime("%Y-%m-%d", time.localtime(nowSeconds - NEW_RELEASE_DAYS * 86400))
            for album in client.artistAlbums(artist["id"]):
                if str(album.get("release_date") or "") >= cutoff:
                    releases.append({"id": album.get("id"), "title": album.get("title") or "", "artist": artist["name"],
                                     "image": album.get("cover_xl") or album.get("cover_big") or album.get("cover_medium") or "",
                                     "releaseDate": album.get("release_date"), "type": album.get("record_type") or "album"})
        except Exception:
            pass
    seen = set()
    for related in similarArtists[:8]:
        try:
            recommended.extend(_notOwned(client.topTracks(related["id"], 3), ownedKeys, seen))
        except Exception:
            pass
    randomizer.shuffle(recommended)
    if recommended:
        sections.append({"id": "forYou", "title": "Consigliati per te", "kind": "tracks", "items": recommended[:24]})
    for recentSong in (profile.get("recentYoutube") or [])[:2]:
        try:
            mix = _notOwned(mixProvider(recentSong["videoId"], 20), ownedKeys)
        except Exception:
            mix = []
        if mix:
            sections.append({"id": "because:" + recentSong["videoId"], "title": f"Perché hai ascoltato \"{recentSong['title']}\"",
                             "kind": "tracks", "items": mix})
    if similarArtists:
        sections.append({"id": "similarArtists", "title": "Artisti che potrebbero piacerti", "kind": "artists", "items": similarArtists[:16]})
    if yourArtists:
        sections.append({"id": "yourArtists", "title": "I tuoi artisti", "kind": "artists", "items": yourArtists})
    if releases:
        releases.sort(key=lambda album: str(album.get("releaseDate") or ""), reverse=True)
        sections.append({"id": "releases", "title": "Novità per te", "kind": "albums", "items": releases[:16]})
    for sectionId, title, loader in (("chart", "Classifica mondiale", client.chart), ("italy", "Top Italia", client.topItaly)):
        try:
            tracks = loader(25)
        except Exception:
            tracks = []
        if tracks:
            sections.append({"id": sectionId, "title": title, "kind": "tracks", "items": tracks})
    return {"sections": sections, "builtAt": nowSeconds}


class DiscoverCache:
    def __init__(self, path, ttlSeconds=CACHE_SECONDS):
        self.path = path
        self.ttlSeconds = ttlSeconds

    def load(self, nowSeconds=None):
        try:
            with open(self.path, "r", encoding="utf-8") as cacheFile:
                data = json.load(cacheFile)
        except (OSError, ValueError):
            return None
        if (nowSeconds or time.time()) - float(data.get("builtAt") or 0) > self.ttlSeconds:
            return None
        return data

    def save(self, data):
        temporaryPath = self.path + ".tmp"
        try:
            with open(temporaryPath, "w", encoding="utf-8") as cacheFile:
                json.dump(data, cacheFile)
            os.replace(temporaryPath, self.path)
        except OSError:
            pass
