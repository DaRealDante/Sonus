import re
import time
import unicodedata

_YOUTUBE_ID = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/)([\w-]{11})")


def nowMs():
    return int(time.time() * 1000)


def normalizeText(text):
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def youtubeId(url):
    match = _YOUTUBE_ID.search(url or "")
    return match.group(1) if match else None


def trackKey(title, artist, url=None):
    videoId = youtubeId(url)
    if videoId:
        return "yt:" + videoId
    return "t:" + normalizeText(title) + "|" + normalizeText(artist)


def trackFromSong(song):
    """What other people need to find the same song: its YouTube link, or title + artist to search it."""
    url = song.get("url") or None
    path = str(song.get("path") or "")
    query = path[len("stream:"):] if path.startswith("stream:ytsearch") else None
    return {
        "key": trackKey(song.get("title"), song.get("artist"), url),
        "title": song.get("title") or "",
        "artist": song.get("artist") or "",
        "album": song.get("album") or "",
        "duration": float(song.get("duration") or 0),
        "url": url if youtubeId(url) else None,
        "query": query,
    }


def isNewer(candidate, current):
    """Every change gets version + 1; on a tie the smaller sender id wins, so everybody converges to the same state."""
    if not candidate:
        return False
    if not current:
        return True
    if candidate.get("version", 0) != current.get("version", 0):
        return candidate.get("version", 0) > current.get("version", 0)
    return str(candidate.get("by", "")) < str(current.get("by", ""))


def expectedPosition(state, currentMs, offsetMs=0):
    """Where the song should be now. offsetMs = sender clock - my clock."""
    position = float(state.get("positionMs") or 0)
    if state.get("playing"):
        senderTimeInMyClock = float(state.get("at") or currentMs) - offsetMs
        rate = float((state.get("effects") or {}).get("rate") or 1.0)
        position += max(0.0, currentMs - senderTimeInMyClock) * rate
    queue = state.get("queue") or []
    index = state.get("index", -1)
    if 0 <= index < len(queue) and queue[index].get("duration"):
        position = min(position, queue[index]["duration"] * 1000)
    return max(0, int(position))


class ClockSync:
    """Estimates how far each person's clock is from ours with ping/pong: the sample with the shortest round trip wins."""

    def __init__(self, keep=5):
        self.keep = keep
        self.samples = {}

    def onPong(self, peerId, sentAt, peerTime, receivedAt):
        roundTrip = receivedAt - sentAt
        if roundTrip < 0 or roundTrip > 20000:
            return
        offset = peerTime - (sentAt + receivedAt) / 2
        samples = self.samples.setdefault(peerId, [])
        samples.append((roundTrip, offset))
        del samples[:-self.keep]

    def offset(self, peerId):
        samples = self.samples.get(peerId)
        if not samples:
            return 0
        return min(samples)[1]

    def forget(self, peerId):
        self.samples.pop(peerId, None)
