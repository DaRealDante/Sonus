import os
import queue
import sys
import threading

from PySide6.QtCore import QObject, Signal


def _enumValue(enumClass, name):
    for candidate in (name.upper(), name, name.capitalize()):
        if hasattr(enumClass, candidate):
            return getattr(enumClass, candidate)
    raise AttributeError(name)


class MediaSession(QObject):
    """Windows media session (SMTC): media keys (Fn+F9 etc.), the volume overlay and the lock screen control Sonus."""

    playPausePressed = Signal()
    playPressed = Signal()
    pausePressed = Signal()
    nextPressed = Signal()
    previousPressed = Signal()
    stopPressed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.commands = queue.Queue()
        self.ready = threading.Event()
        self.available = False
        self.worker = None

    def start(self, timeoutSeconds=4.0):
        if sys.platform != "win32":
            return False
        self.worker = threading.Thread(target=self._run, name="MediaSession", daemon=True)
        self.worker.start()
        self.ready.wait(timeoutSeconds)
        return self.available

    def setPlaying(self, isPlaying):
        if self.available:
            self.commands.put(("state", isPlaying))

    def setStopped(self):
        if self.available:
            self.commands.put(("state", None))

    def setSong(self, title, artist, album, coverPath):
        if self.available:
            self.commands.put(("song", (title or "", artist or "", album or "", coverPath or "")))

    def shutdown(self):
        if self.available:
            self.commands.put(("quit", None))

    def _run(self):
        try:
            try:
                from winrt.runtime import MTA, init_apartment
                init_apartment(MTA)
            except Exception:
                pass
            from winrt.windows.media import MediaPlaybackStatus, MediaPlaybackType, SystemMediaTransportControlsButton
            from winrt.windows.media.playback import MediaPlayer
            self.mediaPlayer = MediaPlayer()
            self.mediaPlayer.command_manager.is_enabled = False
            controls = self.mediaPlayer.system_media_transport_controls
            controls.is_enabled = True
            controls.is_play_enabled = True
            controls.is_pause_enabled = True
            controls.is_next_enabled = True
            controls.is_previous_enabled = True
            controls.is_stop_enabled = True
            buttonSignals = {
                _enumValue(SystemMediaTransportControlsButton, "Play"): self.playPressed,
                _enumValue(SystemMediaTransportControlsButton, "Pause"): self.pausePressed,
                _enumValue(SystemMediaTransportControlsButton, "Next"): self.nextPressed,
                _enumValue(SystemMediaTransportControlsButton, "Previous"): self.previousPressed,
                _enumValue(SystemMediaTransportControlsButton, "Stop"): self.stopPressed,
            }

            def onButton(sender, args):
                signal = buttonSignals.get(args.button)
                if signal is not None:
                    signal.emit()

            self.buttonToken = controls.add_button_pressed(onButton)
            statusPlaying = _enumValue(MediaPlaybackStatus, "Playing")
            statusPaused = _enumValue(MediaPlaybackStatus, "Paused")
            statusStopped = _enumValue(MediaPlaybackStatus, "Stopped")
            musicType = _enumValue(MediaPlaybackType, "Music")
            controls.playback_status = statusStopped
            self.controls = controls
            self.available = True
        except Exception as error:
            print(f"[MediaSession] non disponibile: {error!r}")
            self.available = False
            self.ready.set()
            return
        self.ready.set()

        while True:
            command, value = self.commands.get()
            try:
                if command == "quit":
                    controls.is_enabled = False
                    return
                if command == "state":
                    controls.playback_status = statusStopped if value is None else (statusPlaying if value else statusPaused)
                elif command == "song":
                    title, artist, album, coverPath = value
                    updater = controls.display_updater
                    updater.clear_all()
                    updater.type = musicType
                    updater.music_properties.title = title
                    updater.music_properties.artist = artist
                    updater.music_properties.album_title = album
                    thumbnail = self._thumbnail(coverPath)
                    if thumbnail is not None:
                        updater.thumbnail = thumbnail
                    updater.update()
            except Exception as error:
                print(f"[MediaSession] {command}: {error!r}")

    def _thumbnail(self, coverPath):
        if not coverPath or not os.path.isfile(coverPath):
            return None
        try:
            import asyncio
            from winrt.windows.storage import StorageFile
            from winrt.windows.storage.streams import RandomAccessStreamReference

            async def load():
                return await StorageFile.get_file_from_path_async(os.path.abspath(coverPath))

            return RandomAccessStreamReference.create_from_file(asyncio.run(load()))
        except Exception as error:
            print(f"[MediaSession] copertina: {error!r}")
            return None
