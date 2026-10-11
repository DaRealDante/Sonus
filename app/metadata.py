import hashlib
import os

from .config import COVERS_DIR


def _firstTag(tags, key):
    if not tags or key not in tags:
        return ""
    value = tags[key]
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value)


def _extractCoverBytes(audioFile):
    try:
        tags = audioFile.tags
        if tags is None:
            pictures = getattr(audioFile, "pictures", None)
            return pictures[0].data if pictures else None
        for key in tags.keys():
            if str(key).startswith("APIC"):
                return tags[key].data
        if "covr" in tags and tags["covr"]:
            return bytes(tags["covr"][0])
        pictures = getattr(audioFile, "pictures", None)
        if pictures:
            return pictures[0].data
        if "metadata_block_picture" in tags:
            import base64
            from mutagen.flac import Picture
            return Picture(base64.b64decode(tags["metadata_block_picture"][0])).data
    except Exception:
        pass
    return None


def saveCoverBytes(data, extension=".jpg"):
    if not data:
        return None
    digest = hashlib.md5(data).hexdigest()
    coverPath = os.path.join(COVERS_DIR, digest + extension)
    if not os.path.exists(coverPath):
        with open(coverPath, "wb") as coverFile:
            coverFile.write(data)
    return coverPath


def readTags(path):
    info = {
        "title": os.path.splitext(os.path.basename(path))[0],
        "artist": "",
        "album": "",
        "duration": 0.0,
        "cover": None,
    }
    try:
        import mutagen
        audioFile = mutagen.File(path)
        if audioFile is not None:
            if audioFile.info is not None:
                info["duration"] = float(getattr(audioFile.info, "length", 0) or 0)
            info["cover"] = saveCoverBytes(_extractCoverBytes(audioFile))
        easyFile = mutagen.File(path, easy=True)
        if easyFile is not None and easyFile.tags is not None:
            info["title"] = _firstTag(easyFile.tags, "title") or info["title"]
            info["artist"] = _firstTag(easyFile.tags, "artist")
            info["album"] = _firstTag(easyFile.tags, "album")
    except Exception:
        pass
    if not info["artist"] and " - " in info["title"]:
        artistPart, titlePart = info["title"].split(" - ", 1)
        info["artist"], info["title"] = artistPart.strip(), titlePart.strip()
    return info


def writeMp3Tags(path, title=None, artist=None, album=None, coverPath=None):
    if not path.lower().endswith(".mp3"):
        return False
    try:
        from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1, ID3NoHeaderError
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()
        if title is not None:
            tags.setall("TIT2", [TIT2(encoding=3, text=title)])
        if artist is not None:
            tags.setall("TPE1", [TPE1(encoding=3, text=artist)])
        if album is not None:
            tags.setall("TALB", [TALB(encoding=3, text=album)])
        if coverPath and os.path.isfile(coverPath):
            with open(coverPath, "rb") as coverFile:
                coverData = coverFile.read()
            mimeType = "image/png" if coverPath.lower().endswith(".png") else "image/jpeg"
            tags.delall("APIC")
            tags.add(APIC(encoding=3, mime=mimeType, type=3, desc="Cover", data=coverData))
        tags.save(path)
        return True
    except Exception:
        return False
