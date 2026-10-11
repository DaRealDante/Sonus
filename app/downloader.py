import glob
import os
import re
import threading
import time
import urllib.request

from PySide6.QtCore import QObject, QThreadPool, Signal

from . import audio_tools, metadata
from .config import TEMP_DIR, denoExe, settings
from .workers import runInBackground


def _baseOptions():
    options = {"quiet": True, "no_warnings": True, "noprogress": True, "ignoreerrors": False}
    denoPath = denoExe()
    if denoPath:
        options["js_runtimes"] = {"deno": {"path": denoPath}}
    return options


def isUrl(text):
    return bool(re.match(r"^https?://", text.strip(), re.IGNORECASE))


def _thumbnailFor(entry):
    videoId = entry.get("id")
    if videoId and re.fullmatch(r"[\w-]{11}", str(videoId)):
        return f"https://i.ytimg.com/vi/{videoId}/hqdefault.jpg"
    thumbnails = entry.get("thumbnails") or []
    if thumbnails:
        return thumbnails[-1].get("url")
    return entry.get("thumbnail")


def _normalizeEntry(entry):
    videoId = entry.get("id")
    url = entry.get("webpage_url") or entry.get("url") or (f"https://www.youtube.com/watch?v={videoId}" if videoId else None)
    if url and not isUrl(url) and videoId:
        url = f"https://www.youtube.com/watch?v={videoId}"
    return {
        "id": videoId,
        "title": entry.get("title") or "Senza titolo",
        "channel": entry.get("channel") or entry.get("uploader") or "",
        "duration": float(entry.get("duration") or 0),
        "url": url,
        "thumbnail": _thumbnailFor(entry),
        "views": entry.get("view_count"),
    }


def searchYoutube(query, maxResults=25):
    import yt_dlp
    options = _baseOptions()
    options["extract_flat"] = "in_playlist"
    with yt_dlp.YoutubeDL(options) as youtube:
        if isUrl(query):
            info = youtube.extract_info(query.strip(), download=False)
            if info.get("_type") == "playlist" or info.get("entries"):
                entries = [_normalizeEntry(entry) for entry in (info.get("entries") or []) if entry]
                return {"playlistTitle": info.get("title") or "Playlist importata", "entries": entries}
            return {"playlistTitle": None, "entries": [_normalizeEntry(info)]}
        info = youtube.extract_info(f"ytsearch{maxResults}:{query}", download=False)
        entries = [_normalizeEntry(entry) for entry in (info.get("entries") or []) if entry and entry.get("id")]
        return {"playlistTitle": None, "entries": entries}


STREAM_CACHE_SECONDS = 4 * 3600
_streamCache = {}
_streamCacheLock = threading.Lock()


def resolveStream(target, useCache=True):
    """Direct audio URL for a YouTube link or a `ytsearch1:` query, without downloading."""
    import yt_dlp
    target = target.strip()
    if useCache:
        with _streamCacheLock:
            cached = _streamCache.get(target)
        if cached and time.time() - cached[0] < STREAM_CACHE_SECONDS:
            return dict(cached[1])
    options = _baseOptions()
    options.update({"format": "bestaudio[ext=m4a]/bestaudio/best", "noplaylist": True})
    with yt_dlp.YoutubeDL(options) as youtube:
        info = youtube.extract_info(target, download=False)
    if info.get("entries") is not None:
        entries = [entry for entry in (info.get("entries") or []) if entry]
        if not entries:
            raise RuntimeError("Nessun risultato su YouTube")
        info = entries[0]
    streamUrl = info.get("url")
    headers = info.get("http_headers") or {}
    if not streamUrl and info.get("requested_formats"):
        streamUrl = info["requested_formats"][0].get("url")
        headers = info["requested_formats"][0].get("http_headers") or headers
    if not streamUrl:
        raise RuntimeError("Stream non trovato")
    result = {
        "url": streamUrl,
        "headers": dict(headers),
        "duration": float(info.get("duration") or 0),
        "title": info.get("title") or "",
        "webpageUrl": info.get("webpage_url") or (target if isUrl(target) else ""),
    }
    with _streamCacheLock:
        _streamCache[target] = (time.time(), dict(result))
    return result


STREAM_CACHE_FILES = 8


def resolveVideoStream(target, height=720):
    """Direct URL of the song's video (no audio needed: the app plays it muted) at the chosen quality."""
    import yt_dlp
    options = _baseOptions()
    options.update({
        "format": (f"bestvideo[height<={height}][ext=mp4][vcodec^=avc1]/bestvideo[height<={height}][ext=mp4]/"
                   f"best[height<={height}][ext=mp4]/bestvideo[height<={height}]/best[height<={height}]/best"),
        "noplaylist": True,
    })
    with yt_dlp.YoutubeDL(options) as youtube:
        info = youtube.extract_info(target, download=False)
    if info.get("entries") is not None:
        entries = [entry for entry in (info.get("entries") or []) if entry]
        if not entries:
            raise RuntimeError("Nessun video trovato")
        info = entries[0]
    streamUrl = info.get("url") or ((info.get("requested_formats") or [{}])[0].get("url"))
    if not streamUrl:
        raise RuntimeError("Video non trovato")
    return streamUrl


def downloadTempAudio(target):
    """Last resort when streaming is refused: yt-dlp downloads the audio to a temporary cache (not to the library)."""
    import hashlib
    import yt_dlp
    cacheDir = os.path.join(TEMP_DIR, "stream_cache")
    os.makedirs(cacheDir, exist_ok=True)
    baseName = hashlib.sha1(target.encode("utf-8")).hexdigest()[:16]
    existing = [path for path in glob.glob(os.path.join(cacheDir, baseName + ".*")) if not path.endswith(".part")]
    if existing:
        return existing[0]
    options = _baseOptions()
    options.update({"format": "bestaudio[ext=m4a]/bestaudio/best", "noplaylist": True,
                    "outtmpl": os.path.join(cacheDir, baseName + ".%(ext)s")})
    with yt_dlp.YoutubeDL(options) as youtube:
        youtube.extract_info(target, download=True)
    files = [path for path in glob.glob(os.path.join(cacheDir, baseName + ".*")) if not path.endswith(".part")]
    if not files:
        raise RuntimeError("download temporaneo fallito")
    cached = sorted(glob.glob(os.path.join(cacheDir, "*")), key=os.path.getmtime, reverse=True)
    for oldPath in cached[STREAM_CACHE_FILES:]:
        try:
            os.remove(oldPath)
        except OSError:
            pass
    return files[0]


def forgetStream(target):
    with _streamCacheLock:
        _streamCache.pop((target or "").strip(), None)


def streamSongInfo(entry):
    """Library data for a YouTube result that will only be streamed: same title/artist/cover logic as a download."""
    artistName, songTitle = _splitArtistTitle(entry.get("title") or "Senza titolo", entry.get("channel") or "")
    coverPath = None
    videoId = entry.get("id")
    candidateUrls = []
    if videoId and re.fullmatch(r"[\w-]{11}", str(videoId)):
        candidateUrls.append(f"https://i.ytimg.com/vi/{videoId}/maxresdefault.jpg")
    candidateUrls.append(entry.get("thumbnail"))
    for candidateUrl in candidateUrls:
        if not candidateUrl:
            continue
        try:
            coverPath = metadata.saveCoverBytes(_squareCover(fetchBytes(candidateUrl)))
            break
        except Exception:
            continue
    return {
        "url": entry.get("url"),
        "title": songTitle,
        "artist": artistName,
        "album": "",
        "duration": float(entry.get("duration") or 0),
        "cover": coverPath,
    }


def fetchBytes(url, timeout=15):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _splitArtistTitle(title, channel):
    cleanTitle = re.sub(
        r"\s*[\(\[][^\)\]]*(official|video|audio|lyrics?|testo|visualizer|hd|4k|mv)[^\)\]]*[\)\]]",
        "", title, flags=re.IGNORECASE,
    ).strip()
    if " - " in cleanTitle:
        artistPart, titlePart = cleanTitle.split(" - ", 1)
        return artistPart.strip(), titlePart.strip()
    artistName = re.sub(r"\s*(- Topic|VEVO|Official)$", "", channel or "", flags=re.IGNORECASE).strip()
    return artistName, cleanTitle or title


def _squareCover(imageBytes):
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRect
    from PySide6.QtGui import QImage
    image = QImage.fromData(QByteArray(imageBytes))
    if image.isNull():
        return imageBytes
    side = min(image.width(), image.height())
    if abs(image.width() / max(1, image.height()) - 4 / 3) < 0.05:
        side = int(image.width() * 9 / 16)
    left = (image.width() - side) // 2
    top = (image.height() - side) // 2
    cropped = image.copy(QRect(left, top, side, side))
    byteArray = QByteArray()
    buffer = QBuffer(byteArray)
    buffer.open(QIODevice.WriteOnly)
    cropped.save(buffer, "JPG", 92)
    return bytes(byteArray)


def downloadAudio(entry, musicDir, quality="192", progressCallback=None):
    import yt_dlp
    report = progressCallback or (lambda value: None)
    spotifyInfo = entry.get("spotify")
    if spotifyInfo and not entry.get("url"):
        report({"stage": "search", "percent": 0})
        from .spotify_import import matchOnYoutube
        entry = {**entry, **matchOnYoutube(spotifyInfo), "spotify": spotifyInfo}
    downloadId = entry.get("id") or str(abs(hash(entry.get("url"))))
    tempPattern = os.path.join(TEMP_DIR, f"dl_{downloadId}.%(ext)s")

    def hook(status):
        if status.get("status") == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
            done = status.get("downloaded_bytes") or 0
            report({"stage": "download", "percent": int(done * 100 / total) if total else 0})
        elif status.get("status") == "finished":
            report({"stage": "convert", "percent": 100})

    options = _baseOptions()
    options.update({
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": tempPattern,
        "noplaylist": True,
        "progress_hooks": [hook],
    })
    report({"stage": "download", "percent": 0})
    with yt_dlp.YoutubeDL(options) as youtube:
        info = youtube.extract_info(entry["url"], download=True)
    tempFiles = [path for path in glob.glob(os.path.join(TEMP_DIR, f"dl_{downloadId}.*")) if not path.endswith(".part")]
    if not tempFiles:
        raise RuntimeError("Download fallito: file non trovato")
    tempFile = tempFiles[0]

    fullTitle = info.get("track") or info.get("title") or entry.get("title") or "Senza titolo"
    channelName = info.get("artist") or info.get("channel") or info.get("uploader") or entry.get("channel") or ""
    if spotifyInfo:
        artistName, songTitle = spotifyInfo["artist"], spotifyInfo["title"]
    elif info.get("track") and info.get("artist"):
        artistName, songTitle = info["artist"].split(",")[0].strip(), info["track"]
    else:
        artistName, songTitle = _splitArtistTitle(fullTitle, channelName)

    baseName = audio_tools.safeFileName(f"{artistName} - {songTitle}" if artistName else songTitle)
    outputPath = audio_tools.uniquePath(musicDir, baseName, ".mp3")
    report({"stage": "convert", "percent": 100})
    try:
        audio_tools.convertToMp3(tempFile, outputPath, quality)
    finally:
        for path in tempFiles:
            try:
                os.remove(path)
            except OSError:
                pass

    coverPath = None
    if spotifyInfo and spotifyInfo.get("image"):
        try:
            coverPath = metadata.saveCoverBytes(fetchBytes(spotifyInfo["image"]))
        except Exception:
            coverPath = None
    thumbnailUrl = _thumbnailFor(info) or entry.get("thumbnail")
    if info.get("id") and re.fullmatch(r"[\w-]{11}", str(info["id"])):
        candidateUrls = [f"https://i.ytimg.com/vi/{info['id']}/maxresdefault.jpg", thumbnailUrl]
    else:
        candidateUrls = [thumbnailUrl]
    for candidateUrl in ([] if coverPath else candidateUrls):
        if not candidateUrl:
            continue
        try:
            coverPath = metadata.saveCoverBytes(_squareCover(fetchBytes(candidateUrl)))
            break
        except Exception:
            continue

    albumName = (spotifyInfo or {}).get("album") or info.get("album") or ""
    metadata.writeMp3Tags(outputPath, songTitle, artistName, albumName, coverPath)
    duration = metadata.readTags(outputPath)["duration"] or float(info.get("duration") or 0)
    videoResult = {}
    if entry.get("withVideo"):
        try:
            videoResult = downloadVideo(info.get("webpage_url") or entry["url"], musicDir,
                                        os.path.splitext(os.path.basename(outputPath))[0], entry.get("videoQuality") or "720", report)
        except Exception as error:
            videoResult = {"videoError": str(error)}
    return {
        **videoResult,
        "path": outputPath,
        "title": songTitle,
        "artist": artistName,
        "album": albumName,
        "duration": duration,
        "cover": coverPath,
        "url": info.get("webpage_url") or entry.get("url"),
        "playlistIndex": (spotifyInfo or {}).get("playlistIndex"),
        "replaceSongId": entry.get("replaceSongId"),
    }


def videosDir(musicDir):
    folderPath = os.path.join(musicDir, "video")
    os.makedirs(folderPath, exist_ok=True)
    return folderPath


def downloadVideo(url, musicDir, baseName, quality="720", progressCallback=None):
    import yt_dlp
    report = progressCallback or (lambda value: None)
    height = int(quality or 720)
    targetFolder = videosDir(musicDir)
    baseName = audio_tools.safeFileName(baseName, "video")
    outputBase = os.path.splitext(audio_tools.uniquePath(targetFolder, baseName, ".mp4"))[0]

    def hook(status):
        if status.get("status") == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
            done = status.get("downloaded_bytes") or 0
            report({"stage": "video", "percent": int(done * 100 / total) if total else 0})

    options = _baseOptions()
    options.update({
        "format": (f"bestvideo[height<={height}][ext=mp4][vcodec^=avc1]/bestvideo[height<={height}][ext=mp4]/"
                   f"bestvideo[height<={height}]/best[height<={height}]/best"),
        "outtmpl": outputBase + ".%(ext)s",
        "noplaylist": True,
        "progress_hooks": [hook],
    })
    report({"stage": "video", "percent": 0})
    with yt_dlp.YoutubeDL(options) as youtube:
        info = youtube.extract_info(url, download=True)
    candidates = [path for path in glob.glob(glob.escape(outputBase) + ".*") if not path.endswith(".part")]
    if not candidates:
        raise RuntimeError("Download del video fallito")
    return {"videoPath": candidates[0], "videoUrl": info.get("webpage_url") or url}


def downloadVideoJob(entry, musicDir, quality="720", progressCallback=None):
    result = downloadVideo(entry["url"], musicDir, entry.get("baseName") or entry.get("title") or "video", quality, progressCallback)
    result["songId"] = entry["songId"]
    return result


class DownloadManager(QObject):
    jobAdded = Signal(dict)
    jobUpdated = Signal(dict)
    songDownloaded = Signal(dict, object)
    videoDownloaded = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.jobs = []
        self.nextJobId = 1

    def enqueue(self, entry, playlistId=None):
        entryKey = jobKey(entry)
        for job in self.jobs:
            if jobKey(job["entry"]) == entryKey and job["status"] in ("queued", "search", "download", "convert"):
                return job
        job = {
            "jobId": self.nextJobId,
            "entry": entry,
            "playlistId": playlistId,
            "status": "queued",
            "percent": 0,
            "error": "",
            "result": None,
        }
        self.nextJobId += 1
        self.jobs.append(job)
        self.jobAdded.emit(job)

        def onProgress(value):
            job["status"] = value["stage"]
            job["percent"] = value["percent"]
            self.jobUpdated.emit(job)

        def onFinished(result):
            job["status"] = "done"
            job["percent"] = 100
            job["result"] = result
            self.jobUpdated.emit(job)
            self.songDownloaded.emit(result, job["playlistId"])

        def onError(message):
            job["status"] = "error"
            job["error"] = message
            self.jobUpdated.emit(job)

        if entry.get("kind") == "video":
            def onVideoFinished(result):
                job["status"] = "done"
                job["percent"] = 100
                job["result"] = {"path": result["videoPath"]}
                self.jobUpdated.emit(job)
                self.videoDownloaded.emit(result)

            runInBackground(
                downloadVideoJob, entry, settings.musicDir(), settings.get("videoQuality"),
                onFinished=onVideoFinished, onError=onError, onProgress=onProgress, pool=self.pool, withProgress=True,
            )
            return job
        entry.setdefault("withVideo", bool(settings.get("autoVideo")))
        entry["videoQuality"] = settings.get("videoQuality")
        runInBackground(
            downloadAudio, entry, settings.musicDir(), settings.get("audioQuality"),
            onFinished=onFinished, onError=onError, onProgress=onProgress, pool=self.pool, withProgress=True,
        )
        return job

    def retry(self, job):
        self.jobs.remove(job)
        return self.enqueue(job["entry"], job["playlistId"])

    def activeCount(self):
        return sum(1 for job in self.jobs if job["status"] in ACTIVE_STATES)

    def clearFinished(self):
        self.jobs = [job for job in self.jobs if job["status"] in ACTIVE_STATES]


ACTIVE_STATES = ("queued", "search", "download", "convert", "video")


def jobKey(entry):
    if entry.get("kind") == "video":
        return f"video:{entry.get('songId')}:{entry.get('url')}"
    if entry.get("spotify"):
        return "spotify:" + str(entry["spotify"].get("spotifyId") or entry["spotify"].get("title"))
    return entry.get("url")
