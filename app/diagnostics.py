import collections
import os
import sys
import threading
import time

MAX_LOG_BYTES = 1024 * 1024
recentLines = collections.deque(maxlen=400)
_lock = threading.Lock()


class _Tee:
    """Everything the app prints: kept in memory (for "Copia diagnostica") and in log.txt, with the time."""

    def __init__(self, original, logFile):
        self.original = original
        self.logFile = logFile
        self.pending = ""

    def write(self, text):
        if self.original is not None:
            try:
                self.original.write(text)
            except Exception:
                pass
        with _lock:
            self.pending += text
            while "\n" in self.pending:
                line, self.pending = self.pending.split("\n", 1)
                if not line.strip():
                    continue
                stamped = time.strftime("%H:%M:%S ") + line
                recentLines.append(stamped)
                if self.logFile is not None:
                    try:
                        self.logFile.write(stamped + "\n")
                    except Exception:
                        pass
        return len(text)

    def flush(self):
        for stream in (self.original, self.logFile):
            try:
                if stream is not None:
                    stream.flush()
            except Exception:
                pass

    def isatty(self):
        return False


def logPath(dataDir):
    return os.path.join(dataDir, "log.txt")


def install(dataDir):
    path = logPath(dataDir)
    logFile = None
    try:
        os.makedirs(dataDir, exist_ok=True)
        if os.path.isfile(path) and os.path.getsize(path) > MAX_LOG_BYTES:
            os.replace(path, path + ".old")
        logFile = open(path, "a", encoding="utf-8", buffering=1)
        logFile.write(f"\n===== avvio {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
    except Exception:
        logFile = None
    sys.stdout = _Tee(sys.stdout, logFile)
    sys.stderr = _Tee(sys.stderr, logFile)
    if logFile is not None:
        try:
            # If the app closes by itself (a crash inside Qt/ffmpeg), where it was goes to log.txt
            import faulthandler
            faulthandler.enable(file=logFile, all_threads=True)
        except Exception:
            pass
    return path


def report(together=None, version=""):
    """Text to paste in a chat: version, servers, room, last log lines (no codes, names or songs of others)."""
    lines = [f"Synth Music {version}", time.strftime("%Y-%m-%d %H:%M:%S")]
    if together is not None:
        link = together.link
        lines.append(f"Stanza: {'sì' if together.code else 'no'} · persone: {len(together.peers)}")
        server = link.brokerName() or "?"
        error = f" · ultimo errore: {link.lastError}" if getattr(link, "lastError", "") else ""
        lines.append(f"Server {server}: {'CONNESSO' if link.isConnected() else 'non connesso'}{error}")
        state = together.state or {}
        queue = state.get("queue") or []
        lines.append(f"Coda condivisa: {len(queue)} · in riproduzione: {bool(state.get('playing'))}")
        player = together.player
        status = player.mediaPlayer.mediaStatus()
        lines.append(f"Player: caricamento={player.loading} · suona={player.isPlaying()} · stato={getattr(status, 'name', status)}")
    lines.append("----- log -----")
    with _lock:
        lines.extend(recentLines)
    return "\n".join(lines)
