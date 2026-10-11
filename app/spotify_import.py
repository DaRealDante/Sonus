import html
import re

from . import metadata


def isSpotifyUrl(text):
    text = (text or "").strip().lower()
    return "open.spotify.com/" in text or "play.spotify.com/" in text or text.startswith("spotify:")


def _bestImage(images):
    if not images:
        return None
    ordered = sorted(images, key=lambda image: (image.width or 0), reverse=True)
    return ordered[0].url


def _trackInfo(track, index, albumName=None, albumImages=()):
    artists = [artist.name for artist in (track.artists or ()) if artist.name]
    album = track.album
    image = _bestImage(track.images) or (_bestImage(album.images) if album else None) or _bestImage(albumImages)
    return {
        "spotifyId": track.id,
        "title": track.name,
        "artist": ", ".join(artists),
        "mainArtist": artists[0] if artists else "",
        "album": (album.name if album else None) or albumName or "",
        "durationMs": int(track.duration_ms or 0),
        "image": image,
        "playlistIndex": index,
    }


def fetchSpotify(url):
    from spotify_scraper import SpotifyClient, urls
    kind, _ = urls.parse(url.strip())
    with SpotifyClient(timeout=20.0) as client:
        if kind == "playlist":
            playlist = client.get_playlist(url, max_tracks=None)
            tracks = [item.track for item in playlist.tracks if item.track is not None]
            info = {"kind": "playlist", "name": playlist.name, "description": html.unescape(playlist.description or ""),
                    "image": _bestImage(playlist.images),
                    "tracks": [_trackInfo(track, index) for index, track in enumerate(tracks)]}
        elif kind == "album":
            album = client.get_album(url)
            artistNames = ", ".join(artist.name for artist in album.artists)
            info = {"kind": "album", "name": album.name, "description": f"Album di {artistNames}" if artistNames else "",
                    "image": _bestImage(album.images),
                    "tracks": [_trackInfo(track, index, album.name, album.images) for index, track in enumerate(album.tracks)]}
        elif kind == "track":
            track = client.get_track(url)
            info = {"kind": "track", "name": track.name, "description": "", "image": None, "tracks": [_trackInfo(track, 0)]}
        else:
            raise RuntimeError("Link non supportato: usa il link di una playlist, di un album o di un brano")
    info["tracks"] = [track for track in info["tracks"] if track["title"]]
    info["coverPath"] = None
    if info.get("image"):
        try:
            from .downloader import fetchBytes
            info["coverPath"] = metadata.saveCoverBytes(fetchBytes(info["image"]))
        except Exception:
            pass
    return info


_BAD_WORDS = ["live", "cover", "karaoke", "remix", "sped up", "speed up", "slowed", "nightcore", "instrumental",
              "8d", "reverb", "bass boosted", "reaction", "tutorial", "acoustic", "piano version", "extended"]


def _normalize(text):
    text = (text or "").lower()
    text = re.sub(r"\(feat[^)]*\)|\[feat[^\]]*\]|feat\..*$|ft\..*$", " ", text)
    return re.sub(r"[^\w\s]", " ", text)


def _score(entry, trackInfo):
    entryTitle = _normalize(entry.get("title"))
    channel = (entry.get("channel") or "").lower()
    wantedTitle = _normalize(trackInfo["title"])
    wantedArtist = _normalize(trackInfo["mainArtist"])
    score = 0.0
    titleWords = [word for word in wantedTitle.split() if len(word) > 1] or wantedTitle.split()
    if titleWords:
        score += 30 * sum(1 for word in titleWords if word in entryTitle) / len(titleWords)
    artistWords = wantedArtist.split()
    if artistWords and all(word in entryTitle or word in channel for word in artistWords):
        score += 15
    if "topic" in channel:
        score += 8
    if "official audio" in entryTitle or "audio ufficiale" in entryTitle:
        score += 5
    if "official video" in entryTitle or "video ufficiale" in entryTitle:
        score += 2
    originalTitle = (trackInfo["title"] + " " + trackInfo.get("album", "")).lower()
    for word in _BAD_WORDS:
        if word in entryTitle and word not in originalTitle:
            score -= 18
    wantedSeconds = trackInfo["durationMs"] / 1000
    if wantedSeconds and entry.get("duration"):
        difference = abs(entry["duration"] - wantedSeconds)
        score -= min(40, difference * 0.6) if difference > 3 else 0
        if difference > 60:
            score -= 30
    return score


def matchOnYoutube(trackInfo):
    from .downloader import searchYoutube
    query = f"{trackInfo['mainArtist']} - {trackInfo['title']}".strip(" -")
    entries = searchYoutube(query + " audio", 8)["entries"]
    if not entries:
        entries = searchYoutube(query, 8)["entries"]
    if not entries:
        raise RuntimeError(f"Nessun risultato su YouTube per \"{query}\"")
    return max(entries, key=lambda entry: _score(entry, trackInfo))
