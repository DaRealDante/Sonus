# Sonus Android — specifica e contratto

Base PC: main 92200a81a80635d165eb5ece01104f7116402dd9. Tutti i file PC rimangono identici. Lavoro sul branch android. L'utente ha autorizzato esecuzione autonoma, test ripetuti, UI mobile e ottimizzazione.

## Architettura

UI Android Kotlin/Compose dedicata, non riduzione del layout desktop. Backend Python di Sonus riusato tramite Chaquopy. Il build copia i moduli PC in sonus_core e applica adattamenti Android riproducibili, senza cambiare i sorgenti PC. Un solo event loop Python possiede database e stato; i worker eseguono rete e conversioni. AudioTrack riproduce il PCM elaborato dal motore DSP originale. Servizio foreground, media session, audio focus, wake lock e controlli nella notifica consentono ascolto a schermo spento. Video separato e sospeso in background. ARM64 e x86_64, Android API 26+, target 35.

## Copertura richiesta

Home, ricerca YouTube e playlist, Spotify brani/album/playlist, Scopri, file/cartelle, libreria, preferiti, recenti, gestione metadati/copertine, playlist e riordino, coda e riordino, repeat/shuffle, stato salvato, download/progresso/retry, streaming/offline, testi automatici/manuali/editabili/sincronizzati, video automatici/manuali/locali e sfondo/fullscreen, colori/animazioni/visualizzatore, EQ 10 bande/preset personali/preamp/bilanciamento, velocità con/senza pitch, bass boost, riverbero, loop A-B salvati, taglio/rimozione selezione/fade, esportazione con effetti, stanze MQTT compatibili PC (anche file locali, ritardo e diagnostica), playlist condivise compatibili PC, profilo/foto, sonus://, aggiornamenti Android separati e motore YouTube. Discord escluso su richiesta esplicita successiva dell'utente. Nessun pulsante fittizio: limiti esterni e prove non eseguite vanno dichiarati.

## Contratto Android/Python

Package Kotlin `it.sonus.mobile`. Singleton `SonusHost` con `state: StateFlow<JSONObject>`, `initialize(Context)`, `command(action: String, payload: JSONObject = JSONObject())`. Oggetto callback Python riceve `onEvent(json: String)`. Interfaccia PCM `PcmSink(sampleRate: Int, channels: Int, blockSize: Int)` con `write(data: ByteArray): Int`, `close()`.

Python `sonus_mobile.entry.initialize(data_dir, native_dir, packages_dir, callback)` avvia runtime e controller; `command(action, payload_json)` accoda azione; `close()` rilascia risorse. packages_dir = noBackupFilesDir/youtubedl-android/packages, librerie FFmpeg inizializzate prima di Python.

Snapshot JSON: ready; songs/favorites/recent array Song; playlists array con songs; current Song/null; queue; index; position/duration ms; playing/loading; volume/muted/repeat/shuffle; effects {rate,keepPitch,reverbWet,reverbSize,bassBoost}; eq {enabled,gains,preamp,balance,preset,customPresets,presets}; settings; downloads; room {code,connected,peers,delayMs}; search {query,kind,entries,busy}; discover; lyricsResults; video {url,headers,loading}; loops; spectrum; message/messageId; tasks.

Azioni UI: play {ids,index}; play_entry {entry}; toggle/play_pause; pause; next; previous; seek {position}; volume {value}; mute; repeat; shuffle; queue_add/queue_next {ids}; queue_remove {indexes}; queue_move {from,to}; queue_jump {index}; queue_clear; favorite {id}; search {query}; search_play/stream_add/download {entries,playlistId?}; discover; import_files {paths,playlistId?}; playlist_create {name,description,cover?}; playlist_edit {id,name,description,cover}; playlist_delete {id}; playlist_add/playlist_remove {id,ids}; playlist_order {ids}; playlist_reorder {id,entryIds}; song_edit {id,fields}; song_delete {ids,deleteFiles}; stream_only {id}; download_song {ids}; download_retry {index}; downloads_clear; effects {values}; eq {values}; loop_save {id,name,startMs,endMs,loopId?}; loop_delete {loopId}; loop_select {loop}; loop_clear; cut {id,startMs,endMs,removeSelection,fadeInMs,fadeOutMs,title,replace}; export {id,title}; lyrics_fetch {id,force}; lyrics_search {query}; lyrics_set {id,plain,synced}; lyrics_remove {id}; video_search {query}; video_set {id,url/path}; video_remove {id}; room_create; room_join {code}; room_leave; room_delay {value}; profile {name,photo}; playlist_share {id}; playlist_join {code}; playlist_unshare {id}; settings {values}; engine_update; update_check; diagnostics; refresh.

Azioni di sistema file: il picker Android copia audio/video/immagini nella cartella privata e invia percorsi reali, mai content URI a FFmpeg. Export e condivisione usano FileProvider e document picker. Tutte le operazioni lente fuori dal thread UI. Snapshot frequenti solo per posizione/spectrum, collezioni aggiornate solo su cambiamenti.

## Verifiche

Test RED/GREEN per runtime, dati, protocolli, DSP e azioni. Suite backend PC invariata come regressione dove applicabile; suite adattata mobile contro vero backend. Build APK e Android lint/unit/instrumentation. Test ripetuti con casi validi/errori/ripristino. Device/emulatore necessari per audio reale, blocco schermo, Bluetooth, rete, video e due partecipanti: non descrivere test statici come prove sul telefono. Stato di ogni funzione nel rapporto finale.
