import os
import re
import subprocess
import sys

from .config import ffmpegExe

CREATE_FLAGS = (0x08000000 | 0x00004000) if sys.platform == "win32" else 0


def runFfmpeg(arguments, captureOutput=False):
    executable = ffmpegExe()
    if not executable:
        raise RuntimeError("FFmpeg non trovato. Esegui setup.bat per installare le dipendenze.")
    command = [executable, "-hide_banner", "-loglevel", "error", "-y", *arguments]
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE if captureOutput else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=CREATE_FLAGS,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", "ignore").strip()[-600:] or "Errore FFmpeg")
    return result.stdout


def safeFileName(text, fallback="audio"):
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", text or "").strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:150] or fallback


def uniquePath(folderPath, baseName, extension):
    candidate = os.path.join(folderPath, baseName + extension)
    counter = 2
    while os.path.exists(candidate):
        candidate = os.path.join(folderPath, f"{baseName} ({counter}){extension}")
        counter += 1
    return candidate


def loadWaveform(path, bins=1600):
    import numpy
    sampleRate = 8000
    rawData = runFfmpeg(["-i", path, "-vn", "-ac", "1", "-ar", str(sampleRate), "-f", "s16le", "-"], captureOutput=True)
    samples = numpy.frombuffer(rawData, dtype=numpy.int16).astype(numpy.float32)
    durationMs = int(len(samples) / sampleRate * 1000)
    if samples.size == 0:
        return numpy.zeros(bins, dtype=numpy.float32), 0
    samples = numpy.abs(samples)
    usable = (samples.size // bins) * bins
    if usable == 0:
        peaks = numpy.pad(samples, (0, bins - samples.size))
    else:
        peaks = samples[:usable].reshape(bins, -1).max(axis=1)
    maxPeak = float(peaks.max()) or 1.0
    return (peaks / maxPeak).astype(numpy.float32), durationMs


def _encodeArgs(outputPath, quality="192"):
    extension = os.path.splitext(outputPath)[1].lower()
    if extension == ".mp3":
        return ["-c:a", "libmp3lame", "-b:a", f"{quality}k"]
    if extension == ".wav":
        return ["-c:a", "pcm_s16le"]
    if extension == ".flac":
        return ["-c:a", "flac"]
    if extension in (".m4a", ".aac"):
        return ["-c:a", "aac", "-b:a", f"{quality}k"]
    return []


def cutAudio(inputPath, outputPath, startMs, endMs, removeSelection=False, fadeInMs=0, fadeOutMs=0, quality="192"):
    startSec = max(0, startMs) / 1000.0
    endSec = max(startMs, endMs) / 1000.0
    if removeSelection:
        filterGraph = (
            f"[0:a]atrim=0:{startSec},asetpts=PTS-STARTPTS[a0];"
            f"[0:a]atrim=start={endSec},asetpts=PTS-STARTPTS[a1];"
            f"[a0][a1]concat=n=2:v=0:a=1[cut]"
        )
        resultLength = None
    else:
        filterGraph = f"[0:a]atrim={startSec}:{endSec},asetpts=PTS-STARTPTS[cut]"
        resultLength = endSec - startSec
    lastLabel = "cut"
    if fadeInMs > 0:
        filterGraph += f";[{lastLabel}]afade=t=in:st=0:d={fadeInMs / 1000.0}[fin]"
        lastLabel = "fin"
    if fadeOutMs > 0:
        if resultLength is None:
            from .metadata import readTags
            resultLength = max(0.0, readTags(inputPath)["duration"] - (endSec - startSec))
        fadeStart = max(0.0, resultLength - fadeOutMs / 1000.0)
        filterGraph += f";[{lastLabel}]afade=t=out:st={fadeStart}:d={fadeOutMs / 1000.0}[fout]"
        lastLabel = "fout"
    runFfmpeg([
        "-i", inputPath, "-filter_complex", filterGraph, "-map", f"[{lastLabel}]", "-map_metadata", "0",
        *_encodeArgs(outputPath, quality), outputPath,
    ])
    return outputPath


def mixLengthMs(clips):
    """Length of a mix: the end of the last clip."""
    return max((int(clip["posMs"]) + int(clip["endMs"]) - int(clip["startMs"]) for clip in clips), default=0)


def renderMix(clips, outputPath, quality="192", rangeStartMs=0, rangeEndMs=None):
    """Mixes songs into one file. Each clip is a dict: path, startMs/endMs (part of the song), posMs (place in the
    mix), fadeInMs, fadeOutMs, volume (percent). Clips that overlap play together. A limiter stops clipping.
    rangeStartMs/rangeEndMs render only a part of the mix (used for the preview: same sound as the final file)."""
    totalMs = mixLengthMs(clips)
    startMs = max(0, int(rangeStartMs))
    endMs = totalMs if rangeEndMs is None else min(totalMs, int(rangeEndMs))
    chosen = [clip for clip in clips
              if int(clip["posMs"]) < endMs and int(clip["posMs"]) + int(clip["endMs"]) - int(clip["startMs"]) > startMs]
    if endMs - startMs < 50 or not chosen:
        raise RuntimeError("Il mix è vuoto")
    arguments, parts = [], []
    for index, clip in enumerate(chosen):
        lengthMs = int(clip["endMs"]) - int(clip["startMs"])
        fadeInMs = min(max(0, int(clip.get("fadeInMs") or 0)), lengthMs)
        fadeOutMs = min(max(0, int(clip.get("fadeOutMs") or 0)), lengthMs)
        positionMs = max(0, int(clip["posMs"]))
        chain = [
            f"[{index}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo",
            f"atrim=start={int(clip['startMs']) / 1000.0:.3f}:end={int(clip['endMs']) / 1000.0:.3f}",
            "asetpts=PTS-STARTPTS",
            f"volume={max(0, float(clip.get('volume', 100))) / 100.0:.3f}",
        ]
        if fadeInMs:
            chain.append(f"afade=t=in:st=0:d={fadeInMs / 1000.0:.3f}:curve=qsin")
        if fadeOutMs:
            chain.append(f"afade=t=out:st={(lengthMs - fadeOutMs) / 1000.0:.3f}:d={fadeOutMs / 1000.0:.3f}:curve=qsin")
        if positionMs:
            chain.append(f"adelay={positionMs}|{positionMs}")
        # Every clip lasts the whole mix, so amix keeps one fixed gain (1/N) that "volume=N" gives back
        chain.append(f"apad=whole_dur={totalMs / 1000.0:.3f}")
        parts.append(",".join(chain) + f"[c{index}]")
        arguments += ["-i", clip["path"]]
    count = len(chosen)
    joined = "".join(f"[c{index}]" for index in range(count))
    mixed = f"{joined}amix=inputs={count}:duration=longest:dropout_transition=0,volume={count}," if count > 1 else f"{joined}"
    parts.append(f"{mixed}alimiter=limit=0.97:level=0,atrim=start={startMs / 1000.0:.3f}:end={endMs / 1000.0:.3f},"
                 f"asetpts=PTS-STARTPTS[out]")
    runFfmpeg([*arguments, "-filter_complex", ";".join(parts), "-map", "[out]", *_encodeArgs(outputPath, quality), outputPath])
    return outputPath


def convertToMp3(inputPath, outputPath, quality="192"):
    runFfmpeg(["-i", inputPath, "-vn", "-map_metadata", "-1", "-c:a", "libmp3lame", "-b:a", f"{quality}k", outputPath])
    return outputPath


def renderWithEffects(inputPath, outputPath, rate, keepPitch, reverbWet, reverbSize, quality="192", bassBoost=0.0):
    """Bakes speed / pitch / bass boost / reverb into a new file (same sound as the live player)."""
    import numpy
    import tempfile
    import wave
    from .audio_engine import CHANNELS, SAMPLE_RATE, applyBassBoostOffline, applyReverbOffline, speedFilter
    arguments = ["-i", inputPath, "-vn", "-ac", str(CHANNELS), "-ar", str(SAMPLE_RATE)]
    audioFilter = speedFilter(rate, keepPitch)
    if audioFilter:
        arguments += ["-af", audioFilter]
    rawData = runFfmpeg(arguments + ["-f", "f32le", "-acodec", "pcm_f32le", "-"], captureOutput=True)
    samples = numpy.frombuffer(rawData, dtype=numpy.float32).reshape(-1, CHANNELS)
    samples = applyBassBoostOffline(samples.copy(), bassBoost)
    samples = applyReverbOffline(samples, reverbWet, reverbSize)
    temporaryFolder = tempfile.mkdtemp()
    wavePath = os.path.join(temporaryFolder, "render.wav")
    try:
        with wave.open(wavePath, "wb") as waveFile:
            waveFile.setnchannels(CHANNELS)
            waveFile.setsampwidth(2)
            waveFile.setframerate(SAMPLE_RATE)
            waveFile.writeframes((numpy.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
        runFfmpeg(["-i", wavePath, "-c:a", "libmp3lame", "-b:a", f"{quality}k", outputPath])
    finally:
        try:
            os.remove(wavePath)
            os.rmdir(temporaryFolder)
        except OSError:
            pass
    return outputPath
