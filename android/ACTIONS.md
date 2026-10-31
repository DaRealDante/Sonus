# Android controller contract

`sonus_mobile.controller.Controller(runtime, emit)` is constructed, called and closed
on the runtime owner thread. `dispatch(action, payload)` accepts a dictionary.
`snapshot()` returns a detached complete JSON-compatible dictionary. `close()` saves
the session, cancels timers, stops collaboration and closes the audio engine/database.
Only generated `sonus_core` modules are imported; the PC sources are unchanged.

`emit` receives a dictionary. Initialization and `refresh` publish a complete state.
Later mutation events contain only changed top-level fields and `tick: true`.
The host replaces each supplied top-level value, including nested objects; it must
not merge the old keys of `customPresets`, `songLoops`, or other maps into replacements.
Position events every 500 ms contain only `tick`, `position`, `duration`, `playing`,
`loading`, and at most 48 spectrum values. Background spectrum is empty.
The event loop caches library/playlist/loop collections using SQLite `total_changes`;
volume, room status and download progress do not reread or resend these collections.

The state schema in `PORTING.md` applies. Additional fields are `recentAdded`,
`mostPlayed`, `songLoops` (song ID string to loops), `activeLoop`, `profile`,
`videoResults`, `waveform` (600 normalized peaks), `waveformSongId`, `lyricsPending`,
`error`, `exportPath`, `diagnostics`, and `update`. Each playlist includes its
ordered `songs`, `code`, and `link`; songs in a playlist include original `entryId`.
`room.peers` is an array of profile objects with `id`, and room state includes
`link`, `broker` and `error`. Song durations use seconds; player position, loop,
cut, fade and seek values use milliseconds.

An invalid operation sets `error: {action, message}` and increments `messageId`.
Asynchronous operations appear in `tasks` until their callback finishes.
Network, imports, tag writes, waveform reads, downloads, video resolution,
conversions, photo encoding and update checks execute in bounded workers.
All callbacks which change database/player/state run on the runtime owner.
Conversions use a dedicated single-worker pool. Completion errors remain visible;
work is not reported as successful before the real operation completes.

## Playback and queue

| Action | Payload |
| --- | --- |
| `play` | `ids`, optional `index=0`, optional `shuffled` |
| `play_entry` | `entry`, optional `index=0`; plays a hidden stream until saved/favorited |
| `toggle`, `play_pause` | Empty to toggle; optional `playing` requests a state explicitly |
| `resume`, `pause`, `next`, `previous` | Empty |
| `seek` | `position` in ms |
| `volume` | `value` 0–100 |
| `mute` | Optional `value`; otherwise toggles |
| `repeat` | Optional `value`: 0/off, 1/all, 2/one; otherwise cycles |
| `shuffle` | Optional `value` or `enabled`; otherwise toggles |
| `queue_add`, `queue_next` | `ids` |
| `queue_remove` | `indexes`; the active item is preserved, as on PC |
| `queue_move` | `from`, `to` |
| `queue_jump` | `index` |
| `queue_clear` | Empty; removes upcoming items, as on PC |
| `favorite` | `id` |

Queue, last song, position, volume, mute, repeat and shuffle save every 10 seconds
and on close. Restoration loads the queue and position paused. The player retains
its original stream resolver, prefetch, retry, fallback, repeat and A–B engine behavior.
`settings.values.stopAfterCurrent` controls the original player flag and reflects
its actual value after the track ends.

## Search, import, discovery and download

| Action | Payload |
| --- | --- |
| `search` | `query`: text, YouTube video/playlist, Spotify public track/album/playlist |
| `search_play`, `stream_add`, `download` | `entries`, optional `playlistId`; `stream_add` also accepts `queue` |
| `discover` | Empty; builds original personalized/chart sections and saves cache |
| `discover_artist`, `discover_album` | `id`, optional `name`/`title`; tracks appear in `search.entries` |
| `import_files` | `paths` of audio files and/or folders, optional `playlistId` |
| `download_song` | `ids`; updates a stream row in place, preserving favorites/playlists/loops/lyrics |
| `download_retry` | `jobId` or displayed `index`; failed jobs only |
| `downloads_clear` | Empty; active jobs remain |
| `stream_only` | `id`; requires an original URL; removes local audio and preserves row identity |

Entries are original YouTube results, Spotify results with nested `spotify`, or
discovery tracks with `title`/`artist`. Latest search results win if requests finish
out of order. Original `DownloadManager` handles progress, failures and real FFmpeg
conversion. Spotify playlist download completion is reordered by original index.
Folder import is recursive and deduplicates repeated paths. Android's picker must
copy `content://` input into private real files before calling the controller.

## Library and playlists

| Action | Payload |
| --- | --- |
| `playlist_create` | `name`, optional `description`, `cover`, `ids`, `entries`; entries follow `streamOnly` setting |
| `playlist_edit` | `id`, optional `name`, `description`, `cover` |
| `playlist_delete` | `id`; removes this local playlist, keeps songs |
| `playlist_add` | `id`, `ids`, optional `allowDuplicates=false` |
| `playlist_remove` | `id`, `entryIds` for specific duplicates, or `ids` for all matching song occurrences |
| `playlist_order` | All playlist `ids` in the desired order |
| `playlist_reorder` | `id`, all playlist `entryIds` in desired order |
| `song_edit` | `id`, `fields`, optional `writeTags=false` |
| `song_delete` | `ids`, optional `deleteFiles=false` |

Song editable fields: `title`, `artist`, `album`, `cover`, `favorite`, `lyricsAuto`,
`videoAuto`, `hidden`. Tag writes use original MP3 metadata code and report an
unwritable file separately from successfully saved in-app metadata. Cover values
are private local image paths. Explicit deletion with `deleteFiles=true` removes
audio files permanently on Android; the UI must explain and confirm that choice.

## Effects, EQ, loops and audio files

| Action | Payload |
| --- | --- |
| `effects` | `values`: any of `rate`, `keepPitch`, `reverbWet`, `reverbSize`, `bassBoost` |
| `eq` | `values`: `enabled`, ten `gains`, `preamp`, `balance`, `preset`, `savePreset`, `deletePreset`, `macro` |
| `loop_save` | Song `id`, `name`, `startMs`, `endMs`, optional `loopId` to edit |
| `loop_delete` | `loopId` |
| `loop_select` | `loop` object; absent `songId` uses current song for temporary preview |
| `loop_clear` | Empty |
| `waveform` | Song `id`; obtains temporary audio for streams, then returns 600 peaks |
| `cut` | `id`, `startMs`, `endMs`, `removeSelection`, `fadeInMs`, `fadeOutMs`, `title`, `replace`, optional `format`, `playlistId` |
| `export` | `id`, optional `title`, `playlistId`; renders current speed/pitch/bass/reverb into a new MP3 |

Speed uses the engine's actual 0.5–2.0 range; reverb decay uses 0.2–6 seconds.
EQ gains/preamp use dB (−12 to +12); balance uses −100 to +100. `macro` maps
`bass`, `mid`, `treble` to a delta in dB using the original weighted band shapes.
Preset names and gains come from the actual PC DSP module. Effects are global;
room speed/pitch/reverb are shared by the original protocol, bass stays personal.
Selections must last at least 100 ms. Removing the entire song is rejected.
Streaming audio is downloaded temporarily for editing; received local room files
use the original room cache. Cut operations retain `cutInfo` and adjust synchronized
lyrics; effect export scales lyric timestamps with rate. New audio is registered
only after FFmpeg succeeds; `exportPath` is a real private file for FileProvider.
Original offline export buffers the decoded track in RAM. One conversion runs at a
time, but very long exports retain that original memory limitation.

## Lyrics and video

| Action | Payload |
| --- | --- |
| `lyrics_fetch` | `id`, optional `force=false` |
| `lyrics_search` | `query`, optional `duration` in seconds |
| `lyrics_set` | `id`, `plain`, `synced`, optional `adaptToCut=false` |
| `lyrics_remove` | `id`; records checked status to avoid immediate auto replacement |
| `video_search` | `query` |
| `video_set` | `id`, `url` or local `path` |
| `video_download` | `id`, optional `url`; otherwise saved/original video URL |
| `video_remove` | `id`; removes managed video file and disables this song's automatic video |

Automatic lyrics run on playback/import/download according to global/per-song
settings and retry temporary failures up to three times. Late automatic results
cannot overwrite manual edits. Search selection should send `adaptToCut=true`;
manual editor content already uses the edited audio timeline and must not set it.
Video resolution supplies original YouTube-required HTTP headers. Valid cached
URLs are reused; stale completions cannot replace the next song's source.
Kotlin owns muted video playback, synchronization, foreground/background and rendering.

## Rooms, sharing and settings

| Action | Payload |
| --- | --- |
| `room_create`, `room_leave` | Empty |
| `room_join` | `code`; accepts only a room code/link |
| `room_delay` | `value` in ms, clamped by original protocol to 0–3000 |
| `profile` | Optional `name`, `photo`; photo is a real image path, base64 JPEG, or empty to clear |
| `playlist_share`, `playlist_unshare` | Playlist `id` |
| `playlist_join` | `code`; accepts only playlist code/link |
| `handle_code` | `code`; routes original `SONUS`/`SONUSP` code or `sonus://join/` |
| `settings` | `values` using existing PC setting names, plus `stopAfterCurrent` |
| `foreground` | `active` (or `value` alias); suppresses spectrum; defers new video resolution when `pauseVideoInBackground` is enabled |
| `engine_update` | Empty; original pure-Python YouTube engine update, activated next launch |
| `update_check` | Empty; checks only `android-*` GitHub releases containing APK assets |
| `diagnostics`, `refresh` | Empty |

Rooms, local-file transfers, presence, synchronization, encrypted MQTT messages,
shared playlist merge and ordering reuse original `TogetherController`,
`SharedPlaylists`, `Link` and room-file modules. Profile photos are square 96×96
JPEG images matching the PC protocol. Settings cannot override session identity,
database path or private music directory. Background automatic checks honor
`autoCheckUpdates`; Windows EXE assets are never offered. Android handles APK
downloads/installation through its normal browser/package installer permission flow.
Discord is excluded from this Android task at the user's explicit request.

## Verification

`android/tests/test_controller.py` uses the real generated database, player, engine,
lyrics, discovery, metadata, downloader and encrypted sharing code. Only PCM output,
native executable location, external HTTP/scraper/MQTT transport are injected.
Real FFmpeg WAV cutting/fades, speed/bass MP3 export, download conversion, seek/loop,
and real database/session reopen are exercised. RED/GREEN evidence includes missing
controller, new waveform behavior, then the passing implementation.
Tests also cover duplicate playlist entries/order, errors, retries, input bounds,
manual lyrics protection, streaming identity, profile photo encoding, changed-field
events, collection cache, Spotify/YouTube/discovery/video results and Android-only
release selection. It also checks simultaneous same-title exports, invalid-setting
atomicity, actual DSP parameter bounds, background visual suppression and cleanup
when saving fails. `test_two_controllers_over_real_local_mqtt` starts Mosquitto via
the original `tests/broker.py`, then exercises real two-client play/pause/seek/effects
and playlist add/order/remove. It skips only if Mosquitto is absent; install Mosquitto
on CI or provide `SONUS_TEST_MOSQUITTO` pointing to its executable. This test adds no
application dependency (Paho is already used by the original core).
Real phone audio/Bluetooth/background lifecycle, live providers,
MQTT participants on separate PC/Android devices and very long exports still require
their corresponding device/network validation; these unit tests do not claim it.
