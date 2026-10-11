import collections
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import numpy
from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QMediaPlayer

from .config import ffmpegExe

SAMPLE_RATE = 44100
CHANNELS = 2
BLOCK_SIZE = 4096
OUTPUT_LATENCY = 0.3
CREATE_FLAGS = (0x08000000 | 0x00004000) if sys.platform == "win32" else 0

EQ_FREQUENCIES = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
EQ_LABELS = ["32", "64", "125", "250", "500", "1K", "2K", "4K", "8K", "16K"]

EQ_PRESETS = {
    "Piatto": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    "Bass Boost": [6, 5, 4, 2, 0, 0, 0, 0, 0, 0],
    "Bass Extreme": [10, 8, 6, 3, 0, -1, -1, 0, 0, 0],
    "Bassi + Alti": [6, 5, 3, 0, -1, -1, 0, 3, 5, 6],
    "Alti": [0, 0, 0, 0, 0, 1, 3, 5, 6, 7],
    "Voce": [-2, -2, -1, 1, 3, 4, 4, 3, 1, 0],
    "Rock": [5, 4, 3, 1, -1, -1, 1, 3, 4, 5],
    "Pop": [-1, 0, 2, 3, 4, 3, 1, 0, -1, -1],
    "Hip-Hop": [6, 5, 2, 3, -1, -1, 1, 0, 2, 3],
    "Elettronica": [5, 4, 1, 0, -2, 1, 0, 1, 4, 5],
    "Jazz": [3, 2, 1, 2, -1, -1, 0, 1, 2, 3],
    "Classica": [4, 3, 2, 1, -1, -1, 0, 2, 3, 4],
    "Acustica": [4, 3, 2, 1, 2, 2, 3, 3, 2, 1],
    "Loudness": [5, 4, 1, 0, -1, 0, -1, 1, 4, 5],
    "Notte (bassi soft)": [-4, -3, -2, 0, 1, 2, 2, 1, 0, -1],
}


def _biquadSos(kind, frequency, gainDb, q=1.0):
    gainFactor = 10 ** (gainDb / 40.0)
    omega = 2 * numpy.pi * frequency / SAMPLE_RATE
    sinOmega, cosOmega = numpy.sin(omega), numpy.cos(omega)
    if kind == "peak":
        alpha = sinOmega / (2 * q)
        b0, b1, b2 = 1 + alpha * gainFactor, -2 * cosOmega, 1 - alpha * gainFactor
        a0, a1, a2 = 1 + alpha / gainFactor, -2 * cosOmega, 1 - alpha / gainFactor
    else:
        slope = 1.0
        alpha = sinOmega / 2 * numpy.sqrt((gainFactor + 1 / gainFactor) * (1 / slope - 1) + 2)
        sqrtTerm = 2 * numpy.sqrt(gainFactor) * alpha
        if kind == "lowshelf":
            b0 = gainFactor * ((gainFactor + 1) - (gainFactor - 1) * cosOmega + sqrtTerm)
            b1 = 2 * gainFactor * ((gainFactor - 1) - (gainFactor + 1) * cosOmega)
            b2 = gainFactor * ((gainFactor + 1) - (gainFactor - 1) * cosOmega - sqrtTerm)
            a0 = (gainFactor + 1) + (gainFactor - 1) * cosOmega + sqrtTerm
            a1 = -2 * ((gainFactor - 1) + (gainFactor + 1) * cosOmega)
            a2 = (gainFactor + 1) + (gainFactor - 1) * cosOmega - sqrtTerm
        else:
            b0 = gainFactor * ((gainFactor + 1) + (gainFactor - 1) * cosOmega + sqrtTerm)
            b1 = -2 * gainFactor * ((gainFactor - 1) + (gainFactor + 1) * cosOmega)
            b2 = gainFactor * ((gainFactor + 1) + (gainFactor - 1) * cosOmega - sqrtTerm)
            a0 = (gainFactor + 1) - (gainFactor - 1) * cosOmega + sqrtTerm
            a1 = 2 * ((gainFactor - 1) - (gainFactor + 1) * cosOmega)
            a2 = (gainFactor + 1) - (gainFactor - 1) * cosOmega - sqrtTerm
    return [b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]


def buildEqSos(gains):
    sections = []
    for index, (frequency, gainDb) in enumerate(zip(EQ_FREQUENCIES, gains)):
        if abs(gainDb) < 0.05:
            continue
        if index == 0:
            sections.append(_biquadSos("lowshelf", frequency * 1.4, gainDb))
        elif index == len(EQ_FREQUENCIES) - 1:
            sections.append(_biquadSos("highshelf", frequency * 0.7, gainDb))
        else:
            sections.append(_biquadSos("peak", frequency, gainDb, 1.1))
    return numpy.array(sections, dtype=numpy.float64) if sections else None


def eqResponse(gains, preampDb, frequencies):
    from scipy.signal import sosfreqz
    sos = buildEqSos(gains)
    if sos is None:
        return numpy.full(len(frequencies), preampDb)
    _, response = sosfreqz(sos, worN=numpy.asarray(frequencies), fs=SAMPLE_RATE)
    return 20 * numpy.log10(numpy.maximum(numpy.abs(response), 1e-6)) + preampDb


def _softLimit(samples):
    threshold = 0.85
    magnitude = numpy.abs(samples)
    over = magnitude > threshold
    if over.any():
        samples[over] = numpy.sign(samples[over]) * (threshold + (1 - threshold) * numpy.tanh((magnitude[over] - threshold) / (1 - threshold)))
    return samples


def speedFilter(rate, keepPitch=True):
    """ffmpeg filter for a speed change: keepPitch=True time-stretches, False changes the pitch too (like a record)."""
    if abs(rate - 1.0) < 0.001:
        return None
    if keepPitch:
        return f"atempo={rate:.4f}"
    return f"aresample={SAMPLE_RATE},asetrate={int(round(SAMPLE_RATE * rate))},aresample={SAMPLE_RATE}"


def makeImpulseResponse(decaySeconds=1.8, seed=7):
    """Synthetic stereo room impulse response (decaying filtered noise + early reflections), unit energy."""
    from scipy.signal import lfilter
    decaySeconds = max(0.2, min(6.0, float(decaySeconds)))
    length = int(SAMPLE_RATE * decaySeconds * 1.1)
    generator = numpy.random.default_rng(seed)
    times = numpy.arange(length) / SAMPLE_RATE
    envelope = numpy.exp(-6.9 * times / decaySeconds)
    response = generator.standard_normal((length, CHANNELS)) * envelope[:, None]
    smoothing = 0.35 + min(0.5, decaySeconds / 10)
    response = lfilter([1 - smoothing], [1, -smoothing], response, axis=0)
    preDelay = int(0.018 * SAMPLE_RATE)
    response = numpy.vstack([numpy.zeros((preDelay, CHANNELS)), response])
    for delay, gain in ((0.011, 0.6), (0.019, 0.45), (0.027, 0.35), (0.041, 0.25)):
        index = int(delay * SAMPLE_RATE)
        response[index, 0] += gain
        response[index + 37, 1] += gain
    response /= numpy.sqrt(numpy.sum(response ** 2) / CHANNELS)
    return response.astype(numpy.float32)


def applyReverbOffline(samples, wet, decaySeconds):
    """Same reverb as the live one, for exporting a file. samples: float32 [n, 2]."""
    from scipy.signal import oaconvolve
    if wet <= 0.001:
        return samples
    response = makeImpulseResponse(decaySeconds)
    wetSignal = numpy.stack([oaconvolve(samples[:, channel], response[:, channel])[:len(samples)] for channel in range(CHANNELS)], axis=1)
    mixed = samples * (1.0 - 0.45 * wet) + wetSignal * (0.6 * wet)
    peak = float(numpy.max(numpy.abs(mixed))) or 1.0
    return (mixed / max(1.0, peak / 0.98)).astype(numpy.float32)


SPECTRUM_BANDS = 32
BASS_BOOST_MAX_DB = 12.0
BASS_BOOST_FREQUENCY = 100.0


def lowShelfSos(gainDb, frequency=BASS_BOOST_FREQUENCY, sampleRate=SAMPLE_RATE):
    """RBJ low-shelf biquad (one SOS row): boosts everything below `frequency` by `gainDb`."""
    if abs(gainDb) < 0.05:
        return None
    amplitude = 10 ** (gainDb / 40)
    omega = 2 * numpy.pi * frequency / sampleRate
    alpha = numpy.sin(omega) / 2 * numpy.sqrt(2)
    cosine = numpy.cos(omega)
    rootTerm = 2 * numpy.sqrt(amplitude) * alpha
    b0 = amplitude * ((amplitude + 1) - (amplitude - 1) * cosine + rootTerm)
    b1 = 2 * amplitude * ((amplitude - 1) - (amplitude + 1) * cosine)
    b2 = amplitude * ((amplitude + 1) - (amplitude - 1) * cosine - rootTerm)
    a0 = (amplitude + 1) + (amplitude - 1) * cosine + rootTerm
    a1 = -2 * ((amplitude - 1) + (amplitude + 1) * cosine)
    a2 = (amplitude + 1) + (amplitude - 1) * cosine - rootTerm
    return numpy.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]])


def applyBassBoostOffline(samples, amount):
    sos = lowShelfSos(float(amount) * BASS_BOOST_MAX_DB)
    if sos is None:
        return samples
    from scipy.signal import sosfilt
    boosted = sosfilt(sos, samples, axis=0)
    peak = float(numpy.max(numpy.abs(boosted))) or 1.0
    return (boosted / max(1.0, peak / 0.98)).astype(numpy.float32)
FADE_IN_SECONDS = 1.0
FADE_OUT_SECONDS = 2.0
STREAM_CHUNK_BYTES = 10 * 1024 * 1024
STREAM_READ_BYTES = 64 * 1024


def friendlyStreamError(message):
    """ffmpeg/HTTP errors contain the whole (very long) stream URL: keep only what a person can understand."""
    text = re.sub(r"https?://\S+", "", str(message or "")).strip(" :\n")
    if "403" in text or "Forbidden" in text:
        return "YouTube ha rifiutato lo streaming (403)"
    if "404" in text or "410" in text:
        return "Lo stream non è più disponibile"
    if not text or len(text) > 160:
        return "Streaming non riuscito (connessione)"
    return text


def isRemote(path):
    return bool(path) and str(path).lower().startswith(("http://", "https://"))


class _Decoder(threading.Thread):
    def __init__(self, engine, path, rate, generation, estimatedSeconds, keepPitch=True, headers=None):
        super().__init__(daemon=True)
        self.engine = engine
        self.path = path
        self.headers = headers or {}
        self.rate = rate
        self.keepPitch = keepPitch
        self.generation = generation
        self.estimatedFrames = int(max(30.0, estimatedSeconds / rate + 5) * SAMPLE_RATE)
        self.process = None
        self.cancelled = False

    def run(self):
        executable = ffmpegExe()
        command = [executable, "-nostdin", "-hide_banner", "-loglevel", "error"]
        remote = isRemote(self.path)
        command += ["-i", "pipe:0" if remote else self.path, "-vn", "-ac", str(CHANNELS), "-ar", str(SAMPLE_RATE)]
        audioFilter = speedFilter(self.rate, self.keepPitch)
        if audioFilter:
            command += ["-af", audioFilter]
        command += ["-f", "s16le", "-acodec", "pcm_s16le", "-"]
        try:
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE if remote else subprocess.DEVNULL, stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE, creationflags=CREATE_FLAGS)
        except Exception as error:
            self.engine._decoderFailed(self.generation, str(error))
            return
        self.feedError = None
        if remote:
            threading.Thread(target=self._feed, args=(self.process.stdin,), daemon=True).start()
        buffer = numpy.zeros((self.estimatedFrames, CHANNELS), dtype=numpy.int16)
        self.engine._attachBuffer(self.generation, buffer)
        frameBytes = 2 * CHANNELS
        decodedFrames = 0
        leftover = b""
        while not self.cancelled:
            chunk = self.process.stdout.read(SAMPLE_RATE * frameBytes // 2)
            if not chunk:
                break
            chunk = leftover + chunk
            usable = len(chunk) - len(chunk) % frameBytes
            leftover = chunk[usable:]
            frames = numpy.frombuffer(chunk[:usable], dtype=numpy.int16).reshape(-1, CHANNELS)
            if decodedFrames + len(frames) > len(buffer):
                newBuffer = numpy.zeros((max(len(buffer) * 2, decodedFrames + len(frames)), CHANNELS), dtype=numpy.int16)
                newBuffer[:decodedFrames] = buffer[:decodedFrames]
                buffer = newBuffer
                self.engine._attachBuffer(self.generation, buffer)
            buffer[decodedFrames:decodedFrames + len(frames)] = frames
            decodedFrames += len(frames)
            self.engine._setDecoded(self.generation, decodedFrames)
        if self.cancelled:
            self._kill()
            return
        self.process.wait()
        errorText = self.process.stderr.read().decode("utf-8", "ignore").strip()
        if remote and (self.feedError or decodedFrames == 0):
            errorText = friendlyStreamError(self.feedError or errorText)
        if decodedFrames == 0 or (remote and self.feedError):
            self.engine._decoderFailed(self.generation, errorText or "Impossibile decodificare il file")
        else:
            self.engine._decodeFinished(self.generation, decodedFrames)

    def _feed(self, pipe):
        """Downloads the stream in 10 MB ranges (like yt-dlp does) and hands it to ffmpeg: YouTube refuses or throttles one giant request."""
        position = 0
        total = None
        failures = 0
        try:
            while not self.cancelled:
                if total is not None and position >= total:
                    return
                request = urllib.request.Request(
                    self.path, headers={**self.headers, "Range": f"bytes={position}-{position + STREAM_CHUNK_BYTES - 1}"})
                try:
                    response = urllib.request.urlopen(request, timeout=20)
                except urllib.error.HTTPError as error:
                    if error.code == 416:
                        return
                    failures += 1
                    if error.code in (403, 404, 410) or failures > 4:
                        self.feedError = f"HTTP {error.code} {error.reason}"
                        return
                    time.sleep(0.6 * failures)
                    continue
                except Exception as error:
                    failures += 1
                    if failures > 4:
                        self.feedError = str(error)
                        return
                    time.sleep(0.6 * failures)
                    continue
                received = 0
                with response:
                    contentRange = response.headers.get("Content-Range") or ""
                    if "/" in contentRange and contentRange.rsplit("/", 1)[1].strip().isdigit():
                        total = int(contentRange.rsplit("/", 1)[1])
                    wholeFile = response.status == 200
                    try:
                        while not self.cancelled:
                            data = response.read(STREAM_READ_BYTES)
                            if not data:
                                break
                            pipe.write(data)
                            received += len(data)
                    except (BrokenPipeError, ValueError):
                        return
                    except Exception as error:
                        failures += 1
                        if failures > 4:
                            self.feedError = str(error)
                            return
                position += received
                if received:
                    failures = 0
                if wholeFile and received:
                    return
                if received == 0:
                    failures += 1
                    if total is None or failures > 4:
                        return
        except (BrokenPipeError, ValueError):
            pass
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    def _kill(self):
        try:
            if self.process and self.process.poll() is None:
                self.process.kill()
        except Exception:
            pass

    def cancel(self):
        self.cancelled = True
        self._kill()


class AudioEngine(QObject):
    """Drop-in replacement for the parts of QMediaPlayer + QAudioOutput used by Player, with a realtime EQ."""

    positionChanged = Signal(int)
    durationChanged = Signal(int)
    playbackStateChanged = Signal(object)
    mediaStatusChanged = Signal(object)
    errorOccurred = Signal(object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lock = threading.RLock()
        self._source = QUrl()
        self._path = None
        self.sourceHeaders = {}
        self.durationHintMs = 0
        self._state = QMediaPlayer.StoppedState
        self._status = QMediaPlayer.NoMedia
        self._rate = 1.0
        self._keepPitch = True
        self.reverbWet = 0.0
        self.reverbSize = 1.8
        self.reverbSpectra = {}
        self.reverbResponse = None
        self.reverbTail = None
        self._volume = 0.5
        self._muted = False
        self._balance = 0.0
        self.buffer = None
        self.decodedFrames = 0
        self.decodeDone = False
        self.frame = 0
        self.generation = 0
        self.decoder = None
        self.reachedEnd = False
        self.loopFrames = None
        self.loopMs = None
        self.pendingSeekMs = None
        self.durationMs = 0
        self.lastEmittedPosition = -1
        self.failMessage = None
        self.pendingStatus = []

        self.eqEnabled = True
        self.eqGains = [0.0] * len(EQ_FREQUENCIES)
        self.preampDb = 0.0
        self.sos = None
        self.zi = None
        self.preampFactor = 1.0

        self.stream = None
        self.streamError = None
        self.spectrumEnabled = True
        self.bassBoost = 0.0
        self.bassSos = None
        self.bassZi = None
        self.fadeEnabled = True
        self.spectrumQueue = collections.deque(maxlen=32)
        self.spectrumLevels = [0.0] * SPECTRUM_BANDS
        self.bandEdges = {}

        self.pollTimer = QTimer(self)
        self.pollTimer.setInterval(40)
        self.pollTimer.timeout.connect(self._poll)
        self.pollTimer.start()

    # ---------- QMediaPlayer-like API ----------
    def source(self):
        return self._source

    def setSource(self, url):
        self._cancelDecoder()
        with self.lock:
            self.generation += 1
            self.buffer = None
            self.decodedFrames = 0
            self.decodeDone = False
            self.frame = 0
            self.reachedEnd = False
            self.loopFrames = None
            self.loopMs = None
            self.pendingSeekMs = None
            self.failMessage = None
            self.zi = None
        self._source = QUrl(url) if url is not None else QUrl()
        wasPlaying = self._state == QMediaPlayer.PlayingState
        if self._source.isEmpty():
            self._path = None
            self._setDuration(0)
            self._setState(QMediaPlayer.StoppedState)
            self._setStatus(QMediaPlayer.NoMedia)
            return
        self._path = self._source.toLocalFile() if self._source.isLocalFile() else self._source.toString()
        self._startDecoder(self._path, 0)
        self._setStatus(QMediaPlayer.LoadingMedia)
        if wasPlaying:
            self._setState(QMediaPlayer.StoppedState)

    def _startDecoder(self, path, startMs):
        estimatedSeconds = 0
        if isRemote(path):
            estimatedSeconds = (self.durationHintMs or 0) / 1000
        else:
            try:
                from .metadata import readTags
                estimatedSeconds = readTags(path)["duration"]
            except Exception:
                pass
        if estimatedSeconds:
            self._setDuration(int(estimatedSeconds * 1000))
        self.decoder = _Decoder(self, path, self._rate, self.generation, estimatedSeconds or 300, self._keepPitch,
                                self.sourceHeaders if isRemote(path) else None)
        if startMs:
            self.pendingSeekMs = startMs
        self.decoder.start()

    def _cancelDecoder(self):
        if self.decoder is not None:
            self.decoder.cancel()
            self.decoder = None

    def play(self):
        if self._source.isEmpty():
            return
        if not self._ensureStream():
            return
        with self.lock:
            if self.reachedEnd:
                self.reachedEnd = False
                self.frame = 0
        self._setState(QMediaPlayer.PlayingState)

    def pause(self):
        if self._state == QMediaPlayer.PlayingState:
            self._setState(QMediaPlayer.PausedState)

    def stop(self):
        with self.lock:
            self.frame = 0
        self._setState(QMediaPlayer.StoppedState)
        self.positionChanged.emit(0)

    def playbackState(self):
        return self._state

    def mediaStatus(self):
        return self._status

    def position(self):
        with self.lock:
            if self.pendingSeekMs is not None:
                return int(self.pendingSeekMs)
            return int(self.frame / SAMPLE_RATE * 1000 * self._rate)

    def duration(self):
        return self.durationMs

    def setPosition(self, positionMs):
        positionMs = max(0, int(positionMs))
        with self.lock:
            targetFrame = int(positionMs / 1000 / self._rate * SAMPLE_RATE)
            if self.decodeDone and targetFrame >= self.decodedFrames:
                targetFrame = max(0, self.decodedFrames - 1)
            self.frame = targetFrame
            self.reachedEnd = False
            self.pendingSeekMs = None
        self.lastEmittedPosition = positionMs
        self.positionChanged.emit(positionMs)

    def presetRate(self, rate, keepPitch=True):
        """Sets speed/pitch mode for the NEXT source without re-decoding the current one."""
        self._rate = max(0.5, min(2.0, float(rate)))
        self._keepPitch = bool(keepPitch)

    def keepPitch(self):
        return self._keepPitch

    def setPlaybackRate(self, rate, keepPitch=None):
        rate = max(0.5, min(2.0, float(rate)))
        keepPitch = self._keepPitch if keepPitch is None else bool(keepPitch)
        if abs(rate - self._rate) < 0.001 and keepPitch == self._keepPitch:
            return
        currentMs = self.position()
        self._rate = rate
        self._keepPitch = keepPitch
        if self._path:
            self._cancelDecoder()
            with self.lock:
                self.generation += 1
                self.buffer = None
                self.decodedFrames = 0
                self.decodeDone = False
                self.frame = 0
                self.zi = None
                if self.loopMs:
                    self.loopFrames = self._msRangeToFrames(*self.loopMs)
            self._startDecoder(self._path, currentMs)
            self.setPosition(currentMs)

    def playbackRate(self):
        return self._rate

    def setLoopRange(self, startMs=None, endMs=None):
        with self.lock:
            if startMs is None:
                self.loopMs = None
                self.loopFrames = None
            else:
                self.loopMs = (int(startMs), int(endMs))
                self.loopFrames = self._msRangeToFrames(startMs, endMs)

    def _msRangeToFrames(self, startMs, endMs):
        return (int(startMs / 1000 / self._rate * SAMPLE_RATE), int(endMs / 1000 / self._rate * SAMPLE_RATE))

    # ---------- QAudioOutput-like API ----------
    def setVolume(self, volume):
        self._volume = max(0.0, min(1.0, float(volume)))

    def volume(self):
        return self._volume

    def setMuted(self, muted):
        self._muted = bool(muted)

    def isMuted(self):
        return self._muted

    def setBalance(self, balance):
        self._balance = max(-1.0, min(1.0, float(balance)))

    # ---------- equalizer ----------
    def setEqualizer(self, gains, preampDb, enabled):
        gains = [float(value) for value in gains]
        newSos = buildEqSos(gains) if enabled else None
        with self.lock:
            self.eqGains = gains
            self.preampDb = float(preampDb)
            self.eqEnabled = bool(enabled)
            self.preampFactor = 10 ** (self.preampDb / 20.0) if enabled else 1.0
            if newSos is None or self.sos is None or newSos.shape != self.sos.shape:
                self.zi = None
            self.sos = newSos

    # ---------- bass boost ----------
    def setBassBoost(self, amount):
        amount = max(0.0, min(1.0, float(amount or 0)))
        sos = lowShelfSos(amount * BASS_BOOST_MAX_DB)
        with self.lock:
            self.bassBoost = amount
            if sos is None or self.bassSos is None:
                self.bassZi = None
            self.bassSos = sos

    # ---------- reverb ----------
    def setReverb(self, wet, decaySeconds):
        wet = max(0.0, min(1.0, float(wet)))
        decaySeconds = max(0.2, min(6.0, float(decaySeconds)))
        response = None
        if wet > 0.001:
            if self.reverbResponse is not None and abs(decaySeconds - self.reverbSize) < 0.01:
                response = self.reverbResponse
            else:
                response = makeImpulseResponse(decaySeconds)
        with self.lock:
            if response is not self.reverbResponse:
                self.reverbSpectra = {}
                self.reverbTail = None
            self.reverbResponse = response
            self.reverbWet = wet
            self.reverbSize = decaySeconds

    def _prepareReverb(self, blockSize):
        response = self.reverbResponse
        partitions = int(numpy.ceil(len(response) / blockSize))
        padded = numpy.zeros((partitions * blockSize, CHANNELS), dtype=numpy.float32)
        padded[:len(response)] = response
        spectra = numpy.empty((partitions, blockSize + 1, CHANNELS), dtype=numpy.complex64)
        for index in range(partitions):
            segment = numpy.zeros((2 * blockSize, CHANNELS), dtype=numpy.float32)
            segment[:blockSize] = padded[index * blockSize:(index + 1) * blockSize]
            spectra[index] = numpy.fft.rfft(segment, axis=0)
        self.reverbSpectra = {"blockSize": blockSize, "spectra": spectra,
                              "history": numpy.zeros((partitions, blockSize + 1, CHANNELS), dtype=numpy.complex64),
                              "position": 0, "previous": numpy.zeros((blockSize, CHANNELS), dtype=numpy.float32)}

    def _applyReverb(self, samples):
        """Uniformly partitioned overlap-save convolution: cheap enough for the audio callback."""
        if self.reverbResponse is None or self.reverbWet <= 0.001:
            return samples
        blockSize = len(samples)
        state = self.reverbSpectra
        if not state or state.get("blockSize") != blockSize:
            self._prepareReverb(blockSize)
            state = self.reverbSpectra
        current = samples.astype(numpy.float32)
        inputSpectrum = numpy.fft.rfft(numpy.vstack([state["previous"], current]), axis=0)
        state["previous"] = current
        partitions = len(state["spectra"])
        position = (state["position"] + 1) % partitions
        state["position"] = position
        state["history"][position] = inputSpectrum
        order = (position - numpy.arange(partitions)) % partitions
        outputSpectrum = numpy.einsum("kfc,kfc->fc", state["history"][order], state["spectra"])
        wetSignal = numpy.fft.irfft(outputSpectrum, 2 * blockSize, axis=0)[blockSize:]
        wet = self.reverbWet
        return samples * (1.0 - 0.45 * wet) + wetSignal * (0.6 * wet)

    # ---------- visualizer and fades ----------
    def _applyFade(self, samples, startFrame):
        fadeInFrames = FADE_IN_SECONDS * SAMPLE_RATE
        fadeOutFrames = FADE_OUT_SECONDS * SAMPLE_RATE
        endFrame = startFrame + len(samples)
        needsFadeIn = startFrame < fadeInFrames
        needsFadeOut = self.decodeDone and self.decodedFrames - endFrame < fadeOutFrames
        if not needsFadeIn and not needsFadeOut:
            return samples
        indexes = numpy.arange(startFrame, endFrame, dtype=numpy.float32)
        envelope = numpy.ones(len(samples), dtype=numpy.float32)
        if needsFadeIn:
            envelope *= numpy.clip(indexes / fadeInFrames, 0.0, 1.0)
        if needsFadeOut:
            envelope *= numpy.clip((self.decodedFrames - indexes) / fadeOutFrames, 0.0, 1.0)
        return samples * envelope[:, None]

    def _measureSpectrum(self, samples):
        count = len(samples)
        if count < 256:
            return
        edges = self.bandEdges.get(count)
        if edges is None:
            frequencies = numpy.fft.rfftfreq(count, 1.0 / SAMPLE_RATE)
            limits = numpy.geomspace(40, 16000, SPECTRUM_BANDS + 1)
            edges = [(int(numpy.searchsorted(frequencies, limits[index])), max(int(numpy.searchsorted(frequencies, limits[index + 1])),
                                                                                int(numpy.searchsorted(frequencies, limits[index])) + 1))
                     for index in range(SPECTRUM_BANDS)]
            self.bandEdges[count] = (edges, numpy.hanning(count).astype(numpy.float32))
            edges = self.bandEdges[count]
        bandRanges, window = edges
        mono = samples.mean(axis=1) * window
        magnitudes = numpy.abs(numpy.fft.rfft(mono)) / (count / 4)
        levels = []
        for start, end in bandRanges:
            peak = float(magnitudes[start:end].max()) if end > start else 0.0
            decibels = 20 * numpy.log10(peak + 1e-9)
            levels.append(float(min(1.0, max(0.0, (decibels + 60) / 60))))
        latency = OUTPUT_LATENCY
        try:
            latency = float(self.stream.latency) if self.stream is not None else OUTPUT_LATENCY
        except Exception:
            pass
        self.spectrumQueue.append((time.monotonic() + latency, levels))

    def spectrum(self):
        """Levels 0..1 of the bands you are hearing right now (delayed by the sound card latency)."""
        now = time.monotonic()
        with self.lock:
            while self.spectrumQueue and self.spectrumQueue[0][0] <= now:
                self.spectrumLevels = self.spectrumQueue.popleft()[1]
            if self._state != QMediaPlayer.PlayingState:
                self.spectrumLevels = [0.0] * SPECTRUM_BANDS
            return list(self.spectrumLevels)

    # ---------- output stream ----------
    def _ensureStream(self):
        if self.stream is not None and self.streamError is None:
            return True
        self._closeStream()
        try:
            import sounddevice
            self.stream = sounddevice.OutputStream(
                samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="float32", blocksize=BLOCK_SIZE,
                latency=OUTPUT_LATENCY, callback=self._callback, finished_callback=self._onStreamFinished,
            )
            self.stream.start()
            self.streamError = None
            return True
        except Exception as error:
            self.stream = None
            self.errorOccurred.emit(QMediaPlayer.ResourceError, f"Dispositivo audio non disponibile: {error}")
            return False

    def _closeStream(self):
        if self.stream is not None:
            try:
                self.stream.abort()
                self.stream.close()
            except Exception:
                pass
        self.stream = None

    def _onStreamFinished(self):
        self.streamError = "finished"

    def shutdown(self):
        self._cancelDecoder()
        self._closeStream()

    def _readFrames(self, count):
        """Returns (frames float32 [count, 2], reachedEnd). Called with lock held."""
        output = numpy.zeros((count, CHANNELS), dtype=numpy.float32)
        buffer = self.buffer
        if buffer is None:
            return output, False
        written = 0
        endReached = False
        guard = 0
        while written < count and guard < 8:
            guard += 1
            limit = self.decodedFrames
            if self.loopFrames:
                if self.frame >= self.loopFrames[1]:
                    self.frame = self.loopFrames[0]
                limit = min(limit, self.loopFrames[1])
            available = limit - self.frame
            if available <= 0:
                if self.decodeDone:
                    if self.loopFrames and self.loopFrames[0] < self.decodedFrames:
                        self.frame = self.loopFrames[0]
                        continue
                    endReached = True
                break
            take = min(available, count - written)
            output[written:written + take] = buffer[self.frame:self.frame + take].astype(numpy.float32) * (1.0 / 32768.0)
            written += take
            self.frame += take
            if self.loopFrames and self.frame >= self.loopFrames[1]:
                self.frame = self.loopFrames[0]
        return output, endReached

    def _callback(self, outdata, frames, timeInfo, status):
        with self.lock:
            if self._state != QMediaPlayer.PlayingState or self.pendingSeekMs is not None and self.buffer is None:
                outdata.fill(0)
                return
            if self.pendingSeekMs is not None:
                targetFrame = int(self.pendingSeekMs / 1000 / self._rate * SAMPLE_RATE)
                if targetFrame < self.decodedFrames or self.decodeDone:
                    self.frame = min(targetFrame, max(0, self.decodedFrames - 1))
                    self.pendingSeekMs = None
                else:
                    outdata.fill(0)
                    return
            startFrame = self.frame
            samples, endReached = self._readFrames(frames)
            if endReached:
                self.reachedEnd = True
            if self.fadeEnabled and not self.loopFrames:
                samples = self._applyFade(samples, startFrame)
            sos = self.sos
            if sos is not None:
                from scipy.signal import sosfilt
                if self.zi is None or self.zi.shape[0] != sos.shape[0]:
                    self.zi = numpy.zeros((sos.shape[0], 2, CHANNELS))
                samples, self.zi = sosfilt(sos, samples, axis=0, zi=self.zi)
            bassSos = self.bassSos
            if bassSos is not None:
                from scipy.signal import sosfilt
                if self.bassZi is None:
                    self.bassZi = numpy.zeros((1, 2, CHANNELS))
                samples, self.bassZi = sosfilt(bassSos, samples, axis=0, zi=self.bassZi)
            samples = self._applyReverb(samples)
            if self.spectrumEnabled:
                self._measureSpectrum(samples)
            gain = 0.0 if self._muted else self._volume * self.preampFactor
            samples = samples * gain
            if self._balance:
                samples[:, 0] *= min(1.0, 1.0 - self._balance)
                samples[:, 1] *= min(1.0, 1.0 + self._balance)
            outdata[:] = _softLimit(samples).astype(numpy.float32)

    # ---------- decoder callbacks (worker thread) ----------
    def _attachBuffer(self, generation, buffer):
        with self.lock:
            if generation == self.generation:
                self.buffer = buffer
                if self.decodedFrames == 0:
                    self.pendingStatus.append(QMediaPlayer.LoadedMedia)

    def _setDecoded(self, generation, decodedFrames):
        with self.lock:
            if generation == self.generation:
                self.decodedFrames = decodedFrames

    def _decodeFinished(self, generation, decodedFrames):
        with self.lock:
            if generation == self.generation:
                self.decodedFrames = decodedFrames
                self.decodeDone = True
                self.pendingStatus.append(("duration", int(decodedFrames / SAMPLE_RATE * 1000 * self._rate)))
                self.pendingStatus.append(QMediaPlayer.BufferedMedia)

    def _decoderFailed(self, generation, message):
        with self.lock:
            if generation == self.generation:
                self.failMessage = message or "Errore di decodifica"

    # ---------- main-thread polling ----------
    def _poll(self):
        with self.lock:
            pending = self.pendingStatus
            self.pendingStatus = []
            failMessage = self.failMessage
            self.failMessage = None
            reachedEnd = self.reachedEnd and self._state == QMediaPlayer.PlayingState
        for item in pending:
            if isinstance(item, tuple) and item[0] == "duration":
                self._setDuration(item[1])
            else:
                self._setStatus(item)
        if failMessage:
            self._setStatus(QMediaPlayer.InvalidMedia)
            self._setState(QMediaPlayer.StoppedState)
            self.errorOccurred.emit(QMediaPlayer.FormatError, failMessage)
            return
        if self.streamError and self._state == QMediaPlayer.PlayingState:
            self._ensureStream()
        if self._state == QMediaPlayer.PlayingState:
            position = self.position()
            if position != self.lastEmittedPosition:
                self.lastEmittedPosition = position
                self.positionChanged.emit(position)
        if reachedEnd:
            with self.lock:
                self.reachedEnd = False
            self._setState(QMediaPlayer.StoppedState)
            self._setStatus(QMediaPlayer.EndOfMedia)

    def _setState(self, state):
        if state != self._state:
            self._state = state
            self.playbackStateChanged.emit(state)

    def _setStatus(self, status):
        if status != self._status or status == QMediaPlayer.EndOfMedia:
            self._status = status
            self.mediaStatusChanged.emit(status)

    def _setDuration(self, durationMs):
        if durationMs != self.durationMs:
            self.durationMs = durationMs
            self.durationChanged.emit(durationMs)
