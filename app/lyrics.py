import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import APP_NAME, VERSION

API_BASE = "https://lrclib.net/api"
USER_AGENT = f"{APP_NAME.replace(' ', '')}/{VERSION} (desktop music player)"
LRC_LINE = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")


class LyricsServiceDown(Exception):
    pass


def _getJson(url, attempts=3):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    lastError = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            if error.code not in (429, 500, 502, 503, 504):
                raise
            lastError = error
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            lastError = error
        if attempt < attempts - 1:
            time.sleep(1.5 * (attempt + 1) ** 2)
    raise LyricsServiceDown(str(lastError))


def _request(path, params):
    return _getJson(f"{API_BASE}/{path}?{urllib.parse.urlencode(params)}")


def _fetchLyricsOvh(title, artist):
    if not title or not artist:
        return None
    url = f"https://api.lyrics.ovh/v1/{urllib.parse.quote(artist)}/{urllib.parse.quote(title)}"
    data = _getJson(url, attempts=2)
    text = (data or {}).get("lyrics") or ""
    text = re.sub(r"^Paroles de la chanson.*?\r?\n", "", text).strip()
    return {"plain": text, "synced": ""} if text else None


def _cleanTitle(title):
    title = re.sub(r"\s*[\(\[][^\)\]]*(feat|ft\.|official|video|audio|lyrics?|testo|remaster|hd|4k|taglio)[^\)\]]*[\)\]]", "",
                   title or "", flags=re.IGNORECASE)
    title = re.sub(r"\s+-\s+(remaster(ed)?|live|radio edit).*$", "", title, flags=re.IGNORECASE)
    return title.strip()


def _mainArtist(artist):
    return re.split(r",|&| feat\.? | ft\.? | x ", artist or "", flags=re.IGNORECASE)[0].strip()


def _pick(item):
    if not item or item.get("instrumental"):
        return {"plain": "[Strumentale]", "synced": ""} if item and item.get("instrumental") else None
    plain = item.get("plainLyrics") or ""
    synced = item.get("syncedLyrics") or ""
    if not plain and synced:
        plain = "\n".join(LRC_LINE.sub("", line).strip() for line in synced.splitlines())
    if not plain and not synced:
        return None
    return {"plain": plain.strip(), "synced": synced.strip()}


def fetchLyrics(title, artist, album="", durationSeconds=0):
    """Returns {"plain": str, "synced": str} or None. Raises LyricsServiceDown if every source is unreachable."""
    lrclibDown = None
    try:
        result = _fetchLrclib(title, artist, album, durationSeconds)
        if result:
            return result
    except LyricsServiceDown as error:
        lrclibDown = error
    try:
        result = _fetchLyricsOvh(_cleanTitle(title), _mainArtist(artist))
        if result:
            return result
    except (LyricsServiceDown, urllib.error.HTTPError, ValueError):
        if lrclibDown:
            raise lrclibDown
    if lrclibDown:
        raise lrclibDown
    return None


def _fetchLrclib(title, artist, album="", durationSeconds=0):
    cleanTitle = _cleanTitle(title)
    mainArtist = _mainArtist(artist)
    if mainArtist and cleanTitle:
        params = {"track_name": cleanTitle, "artist_name": mainArtist}
        if album:
            params["album_name"] = album
        if durationSeconds:
            params["duration"] = int(round(durationSeconds))
        result = _pick(_request("get", params))
        if result:
            return result
        params.pop("album_name", None)
        params.pop("duration", None)
        result = _pick(_request("get", params))
        if result:
            return result
    query = f"{mainArtist} {cleanTitle}".strip()
    results = _request("search", {"q": query}) or []
    if durationSeconds:
        results.sort(key=lambda item: (not item.get("syncedLyrics"), abs((item.get("duration") or 0) - durationSeconds)))
    for item in results[:5]:
        if durationSeconds and item.get("duration") and abs(item["duration"] - durationSeconds) > 20:
            continue
        result = _pick(item)
        if result:
            return result
    return None


def parseSynced(syncedText):
    """Returns sorted list of (milliseconds, text)."""
    lines = []
    for rawLine in (syncedText or "").splitlines():
        stamps = LRC_LINE.findall(rawLine)
        if not stamps:
            continue
        text = LRC_LINE.sub("", rawLine).strip()
        for minutes, seconds in stamps:
            lines.append((int((int(minutes) * 60 + float(seconds)) * 1000), text))
    lines.sort(key=lambda line: line[0])
    return lines


def searchLyrics(query, durationSeconds=0):
    """Returns a list of candidates for the manual search dialog."""
    items = _request("search", {"q": query.strip()}) or []
    results = []
    for item in items:
        picked = _pick(item)
        if not picked:
            continue
        results.append({
            "title": item.get("trackName") or item.get("name") or "",
            "artist": item.get("artistName") or "",
            "album": item.get("albumName") or "",
            "duration": float(item.get("duration") or 0),
            "plain": picked["plain"],
            "synced": picked["synced"],
        })
    results.sort(key=lambda result: (not result["synced"],
                                     abs(result["duration"] - durationSeconds) if durationSeconds and result["duration"] else 9999))
    return results[:40]


def defaultQuery(title, artist):
    return f"{_mainArtist(artist)} {_cleanTitle(title)}".strip()


def _formatStamp(milliseconds):
    minutes, rest = divmod(max(0, int(milliseconds)), 60000)
    return f"[{minutes:02d}:{rest / 1000:05.2f}]"


def applyCutsToSynced(syncedText, operations):
    """Shifts/drops LRC lines so they match an audio file that was cut with the given operations (in order)."""
    lines = parseSynced(syncedText)
    if not lines:
        return syncedText
    for operation in operations:
        startMs, endMs = int(operation["startMs"]), int(operation["endMs"])
        if operation.get("mode") == "keep":
            kept = [(stamp - startMs, text) for stamp, text in lines if startMs <= stamp < endMs]
            before = [line for line in lines if line[0] < startMs]
            if before and before[-1][1].strip() and (not kept or kept[0][0] > 400):
                kept.insert(0, (0, before[-1][1]))
            lines = kept
        else:
            removedLength = endMs - startMs
            lines = [(stamp, text) for stamp, text in lines if stamp < startMs] + \
                    [(stamp - removedLength, text) for stamp, text in lines if stamp >= endMs]
    return "\n".join(f"{_formatStamp(stamp)}{text}" for stamp, text in lines)


def plainFromSynced(syncedText):
    return "\n".join(text for _, text in parseSynced(syncedText))


def adaptToCut(result, cutInfo):
    """result from fetchLyrics for the ORIGINAL song -> lyrics for the cut file."""
    if not result or not cutInfo:
        return result
    operations = cutInfo.get("operations") or []
    if result.get("synced"):
        synced = applyCutsToSynced(result["synced"], operations)
        return {"plain": plainFromSynced(synced), "synced": synced}
    return result


def scaleSynced(syncedText, rate):
    """Timestamps for a file played/rendered at `rate` speed."""
    lines = parseSynced(syncedText)
    if not lines or rate <= 0:
        return syncedText
    return "\n".join(f"{_formatStamp(stamp / rate)}{text}" for stamp, text in lines)
