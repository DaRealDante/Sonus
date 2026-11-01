# Sonus per Android: mappa del porting dal PC

Tecnologie: **Kotlin + Jetpack Compose** (interfaccia), **Media3/ExoPlayer** (riproduzione in background, notifica, schermata di blocco),
**Room** (database), **youtubedl-android** (yt-dlp + ffmpeg dentro l'app). La logica pura (senza Android) sta in `app/sonus/core` e si
controlla sul PC con i confronti in `checks/` (la palette dei colori è identica a quella del PC su 418 casi).

Saltato: Discord (`discord_presence.py`). Non servono su Android: tasti multimediali (`media_keys.py` -> MediaSession), istanza unica
(`single_instance.py`), installer (`installer.iss`), `migration.py`.

## Fasi

| Fase | Contenuto | Moduli del PC |
|---|---|---|
| 0 (fatta) | Scheletro, tema/colori, navigazione, mini-player, APK creato da GitHub, aggiornamento automatico dell'app | `theme.py`, `config.py`, `app_updater.py` |
| 1 | Database, importa file, riproduzione in background, coda/shuffle/repeat, Libreria, Preferiti, Recenti, Playlist, Home, Cerca locale, schermata In riproduzione, impostazioni e temi | `database.py`, `player.py`, `metadata.py`, `views.py`, `song_table.py`, `player_bar.py`, `now_playing*.py`, `dialogs.py` (Playlist, Info brano, Impostazioni) |
| 2 | YouTube: cerca, streaming, download, pagina Download, video (sfondo + pannello), qualità, Scopri, import Spotify | `downloader.py`, `fast_net.py`, `video_proxy.py`, `video_controller.py`, `discover*.py`, `spotify_import.py` |
| 3 | Testi sincronizzati (+ modifica e ricerca), effetti (velocità, tono, riverbero, bassi), equalizzatore, visualizer, loop A-B, forma d'onda | `lyrics.py`, `audio_engine.py`, `effects*.py`, `equalizer_page.py`, `waveform.py` |
| 4 | Taglia audio e Crea mix (con la timeline per il telefono) | `audio_tools.py`, `CutDialog`, `mix_dialog.py` |
| 5 | Insieme (stanze, file condivisi, link sessione, sync playlist), aggiornamento del motore YouTube, rifiniture | `together*.py`, `room_files.py`, `session_link.py`, `playlist_sync.py`, `updater.py` (motore yt-dlp) |

## Navigazione sul telefono

Barra in basso: **Home, Cerca, Scopri, Libreria** (Libreria contiene Brani, Preferiti, Recenti, Playlist, Download).
Sopra la barra: il mini-player. Un tocco lo apre a schermo intero (**In riproduzione**: copertina/testi/video, coda, effetti, equalizzatore).
Impostazioni e Insieme: icone in alto nella Home.
