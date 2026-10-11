import base64
import hashlib
import hmac
import os
import re
import time
import urllib.request
import uuid

LITTERBOX_URL = "https://litterbox.catbox.moe/resources/internals/api.php"
MAGIC = b"SMF1"
BLOCK = 1024 * 1024
MAX_IDLE_SECONDS = 3600


MAX_DOWNLOAD_BYTES = 300 * 1024 * 1024


def validRoomFile(info):
    """Only accept well-formed file messages: real sha256, https link (or the test server), a key."""
    sha = str(info.get("sha") or "")
    url = str(info.get("url") or "")
    allowedPrefixes = ("https://",) + (("http://127.0.0.1",) if os.environ.get("SONUS_UPLOAD_URL") else ())
    return bool(re.fullmatch(r"[0-9a-f]{64}", sha)) and url.startswith(allowedPrefixes) and bool(info.get("key"))


def uploadEndpoint():
    return os.environ.get("SONUS_UPLOAD_URL") or LITTERBOX_URL


def fileSha(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(BLOCK), b""):
            digest.update(block)
    return digest.hexdigest()


def _xorBlock(data, key, nonce, index):
    stream = hashlib.shake_256(key + nonce + index.to_bytes(8, "big")).digest(len(data))
    return (int.from_bytes(data, "big") ^ int.from_bytes(stream, "big")).to_bytes(len(data), "big")


def encryptFile(path, outPath):
    """Random key per file: the upload service only ever sees unreadable bytes. Returns (keyBase64, sha256 of the original)."""
    key = os.urandom(32)
    nonce = os.urandom(16)
    plainDigest = hashlib.sha256()
    mac = hmac.new(key, nonce, hashlib.sha256)
    with open(path, "rb") as source, open(outPath + ".tmp", "wb") as target:
        target.write(MAGIC + nonce + b"\0" * 32)
        index = 0
        for block in iter(lambda: source.read(BLOCK), b""):
            plainDigest.update(block)
            cipher = _xorBlock(block, key, nonce, index)
            mac.update(cipher)
            target.write(cipher)
            index += 1
        target.seek(len(MAGIC) + 16)
        target.write(mac.digest())
    os.replace(outPath + ".tmp", outPath)
    return base64.b64encode(key).decode("ascii"), plainDigest.hexdigest()


def decryptFile(blobPath, keyBase64, outPath, expectedSha=None):
    key = base64.b64decode(keyBase64)
    with open(blobPath, "rb") as source:
        header = source.read(len(MAGIC) + 48)
        if header[:len(MAGIC)] != MAGIC:
            raise ValueError("file non valido")
        nonce, expectedMac = header[len(MAGIC):len(MAGIC) + 16], header[len(MAGIC) + 16:]
        mac = hmac.new(key, nonce, hashlib.sha256)
        for block in iter(lambda: source.read(BLOCK), b""):
            mac.update(block)
        if not hmac.compare_digest(mac.digest(), expectedMac):
            raise ValueError("file danneggiato o chiave sbagliata")
        source.seek(len(header))
        plainDigest = hashlib.sha256()
        with open(outPath + ".tmp", "wb") as target:
            index = 0
            for block in iter(lambda: source.read(BLOCK), b""):
                plain = _xorBlock(block, key, nonce, index)
                plainDigest.update(plain)
                target.write(plain)
                index += 1
    if expectedSha and plainDigest.hexdigest() != expectedSha:
        os.remove(outPath + ".tmp")
        raise ValueError("file diverso da quello atteso")
    os.replace(outPath + ".tmp", outPath)
    return outPath


def uploadTemporary(path, hours="1h", endpoint=None, timeout=300):
    """Uploads to Litterbox (free, no account, deleted by the service after `hours`). Returns the download link."""
    boundary = "----Sonus" + uuid.uuid4().hex
    with open(path, "rb") as source:
        fileData = source.read()
    parts = []
    for name, value in (("reqtype", "fileupload"), ("time", hours)):
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8"))
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"fileToUpload\"; filename=\"sonus.bin\"\r\n"
                 "Content-Type: application/octet-stream\r\n\r\n".encode("utf-8") + fileData + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)
    request = urllib.request.Request(endpoint or uploadEndpoint(), data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                                              "User-Agent": "Mozilla/5.0 Sonus"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        link = response.read().decode("utf-8", "ignore").strip()
    if not link.startswith("http"):
        raise RuntimeError(f"upload non riuscito: {link[:80]}")
    return link


def downloadFile(url, outPath, timeout=120):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Sonus"})
    received = 0
    with urllib.request.urlopen(request, timeout=timeout) as response, open(outPath + ".part", "wb") as target:
        for block in iter(lambda: response.read(BLOCK), b""):
            received += len(block)
            if received > MAX_DOWNLOAD_BYTES:
                raise RuntimeError("file troppo grande")
            target.write(block)
    os.replace(outPath + ".part", outPath)
    return outPath


class RoomFileCache:
    """Songs received from friends: kept in a temporary folder, deleted after an hour without listening."""

    def __init__(self, folder):
        self.folder = folder
        os.makedirs(folder, exist_ok=True)

    def pathFor(self, sha, extension):
        extension = extension if extension and extension.startswith(".") and len(extension) <= 6 else ".mp3"
        return os.path.join(self.folder, sha[:40] + extension)

    def fetch(self, info):
        if not validRoomFile(info):
            raise ValueError("file della stanza non valido")
        path = self.pathFor(info["sha"], info.get("ext"))
        if os.path.isfile(path):
            self.touch(path)
            return path
        blobPath = path + ".blob"
        downloadFile(info["url"], blobPath)
        try:
            decryptFile(blobPath, info["key"], path, info["sha"])
        finally:
            try:
                os.remove(blobPath)
            except OSError:
                pass
        return path

    def touch(self, path):
        try:
            os.utime(path, None)
        except OSError:
            pass

    def cleanup(self, maxIdleSeconds=MAX_IDLE_SECONDS, keep=(), nowSeconds=None):
        nowSeconds = nowSeconds or time.time()
        keep = {os.path.normcase(os.path.abspath(path)) for path in keep if path}
        removed = 0
        for name in os.listdir(self.folder):
            path = os.path.join(self.folder, name)
            if os.path.normcase(os.path.abspath(path)) in keep:
                continue
            try:
                if nowSeconds - os.path.getmtime(path) > maxIdleSeconds:
                    os.remove(path)
                    removed += 1
            except OSError:
                pass
        return removed
