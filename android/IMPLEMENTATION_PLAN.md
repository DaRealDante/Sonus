# Sonus Android Implementation Plan

**Goal:** port completo su branch android con UI mobile e riproduzione in background.
**Architecture:** vedi PORTING.md, autorità per interfacce e copertura.
**Execution:** skill writing-plans, subagent-driven-development e dispatching-parallel-agents; task con file distinti, integrazione e revisione finale.

## Task 1 — Runtime e motore portabile

Create android/tools/prepare_core.py; android/app/src/main/python/sonus_mobile/{runtime,android_audio,entry}.py; android/tests/test_runtime.py e test_core.py. Leggere tutti i moduli core necessari in una passata. Scrivere test di isolamento segnali, event loop, timer annullati, thread confinement SQLite e identità protocollo; osservare RED, implementare, verificare GREEN. Generare sonus_core da app/*.py con adattamenti circoscritti; nessuna modifica PC. Riutilizzare motore DSP, player, database, download, condivisione, testi e discovery. Runtime reale e seriale, non stub Qt. L'entry carica controller dall'altro task. Audio PCM attraverso PcmSink.

## Task 2 — Controller completo

Create android/app/src/main/python/sonus_mobile/controller.py e android/tests/test_controller.py. Leggere operazioni di MainWindow, viste, dialoghi e core pertinenti in una passata. Controller posseduto dall'event loop Task 1. Implementare tutti i comandi PORTING.md, snapshot, persistenza, aggiornamenti e lavori asincroni. Testare dati, comandi, errori, persistenza, testi/loop/tagli/export e protocolli; dipendenze di rete/hardware simulate solo ai confini. Documentare contratti aggiuntivi in android/ACTIONS.md. Nessun stub o funzione esclusa.

## Task 3 — Host e servizio Android

Create build Gradle, wrapper, manifest, risorse, SonusHost.kt, PcmSink.kt, PlaybackService.kt, SonusApplication.kt, provider e test nativi. Usa contratto PORTING.md. Python 3.12 con numpy/scipy/Pillow/mutagen/yt-dlp/yt-dlp-ejs/spotifyscraper/paho-mqtt/certifi. Dipendenze Python compilabili verificate prima di fissarle. Pacchetti nativi FFmpeg/QuickJS da youtubedl-android 0.18.1. Servizio, media session, controlli hardware, audio focus/duck, noisy intent, wake lock solo in riproduzione, ripristino, notifica. Host inoltra eventi a UI e servizio, non serializza lavoro lento sul main thread. Build wiring genera core da task 1. Nessuna release Windows modificata.

## Task 4 — Interfaccia mobile

Create MainActivity.kt, MobileUi.kt e moduli UI. Root implementa. Nav Home/Cerca/Libreria/Scopri, mini player e player espandibile. Pagine accessibili per coda, download, effetti, equalizzatore, loop/taglio, testi, video, stanze, profilo, impostazioni, editing e condivisione. Touch target 48dp, scorrimento, safe area, font leggibili. Picker file/cartella/immagini e condivisione Android. Funzioni UI mappate a tutti i comandi. Nessun layout desktop ristretto.

## Task 5 — Integrazione, ottimizzazione e rilascio branch

Preparare toolchain locale, test RED/GREEN, build ripetuto, lint, regressioni, prove su emulatore se disponibile. Aggiornamenti collezioni separati da tick posizione, cap spectrum, pause video background, memoria audio e download limitati. Verifica diff PC vuoto. Pubblica soltanto branch android con workflow CI dedicato e artefatti APK. Nessun merge main. Rapporto onesto con funzionalità presenti, test eseguiti, e prove bloccate. Revisione indipendente finale secondo skill.
