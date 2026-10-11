# Sonus v1.0.4


## Installare / aggiornare (tu)
Doppio click su **`INSTALLA_E_AGGIORNA.bat`**. Fa tutto da solo:
1. installa Python se manca (poi riapri il file)
2. installa/aggiorna le librerie
3. crea l'app e l'installer `installer\Sonus_Setup_vX.exe`
4. installa/aggiorna Sonus sul tuo PC (icona sul Desktop)

La prima volta Sonus si copia da solo in `%LOCALAPPDATA%\Sonus\Sorgente` (poi la cartella scaricata si può cancellare) e crea sul Desktop **"Sonus - Aggiorna"**.
L'app installata sta in `%LOCALAPPDATA%\Programs\Sonus`, con icona sul Desktop e nel menu Start.
Nuova versione → **trascina il nuovo `Sonus.zip` sopra "Sonus - Aggiorna"**: estrae, ricompila e aggiorna da solo.

## Aggiornamenti automatici con GitHub (consigliato)
Una volta sola:
1. Crea un account su **github.com** e un repository **pubblico** vuoto (es. `Sonus`)
2. Apri **`PUBBLICA_AGGIORNAMENTO.bat`**: pubblica da solo su `github.com/DaRealDante/Sonus` (la prima volta si apre il browser per il login)

Ogni nuova versione: estrai lo zip, apri `INSTALLA_E_AGGIORNA.bat` (per provarla tu) e poi `PUBBLICA_AGGIORNAMENTO.bat`.
GitHub crea l'installer da solo (10-15 min) e **tutte le app** (tua e degli amici) mostrano "È disponibile Sonus X → Aggiorna ora".
Controllo manuale: bottone **⋯** in basso a destra → *Controlla aggiornamenti* (o Impostazioni).

## Reinstallare da zero
1. Apri **`DISINSTALLA_TUTTO.bat`** (toglie app, codice e icone; ti chiede se cancellare anche playlist e canzoni)
2. Estrai `Sonus.zip` e apri **`INSTALLA_E_AGGIORNA.bat`**

## Amici
Mandagli solo **`installer\Sonus_Setup_vX.exe`**.
- Doppio click = installa (niente Python, niente admin)
- Per aggiornare: aprono il Setup nuovo, oppure dall'app → Impostazioni → **Installa aggiornamento...**
- Playlist, canzoni, loop e impostazioni non si perdono con gli aggiornamenti (`%APPDATA%\Sonus`)
- Disinstallare: Impostazioni di Windows → App → Sonus (chiede se cancellare anche i dati)
- Se vogliono crearsi l'app da soli: zip + `INSTALLA_E_AGGIORNA.bat` funziona anche da loro (installa pure Python)
- Windows potrebbe dire "PC protetto": *Ulteriori informazioni → Esegui comunque* (l'app non è firmata)

Il motore YouTube (yt-dlp) si aggiorna da solo una volta al giorno: non serve ricompilare quando YouTube cambia.

## Ascolta insieme (come funziona il "connetti")
1. Bottone **persone** in basso a destra → **Crea una stanza**: il link (`sonus://join/SONUS-XXXX-XXXX`) viene copiato da solo
2. Mandalo agli amici (anche più persone). Loro: bottone persone → incollano link o codice → **Entra**
3. Fatto: sentite la stessa canzone nello stesso punto. Tutti possono mettere play/pausa, saltare, cercare un punto, cambiare canzone, aggiungere alla coda e cambiare velocità/reverb (valgono per tutti, non toccano i tuoi effetti salvati)

- Le app non si mandano l'audio: si scambiano solo "quale canzone, a che secondo, play/pausa" (criptato col codice). Ognuno la suona dal suo PC: se ce l'ha già usa il file, sennò la prende in **streaming** da YouTube
- Il collegamento passa dal **server privato di Sonus** (EMQX, piano gratuito con Spend Limit 0: non si paga mai; se finisce la quota del mese le stanze si fermano fino al mese dopo). Se la rete blocca la porta normale, l'app prova da sola quella web
- Le stanze restano sul server 2 giorni, le playlist condivise 6 mesi dall'ultima modifica o apertura
- Restate allineati entro ~½ secondo; se uno resta indietro (internet lento) si riallinea da solo
- Profilo (nome + foto): bottone persone → *Modifica profilo* (o Impostazioni → Profilo). La prima volta hai un nome casuale
- Le canzoni messe dagli amici non finiscono nella tua libreria: se una ti piace, menu della canzone → *Salva nella libreria*

## Playlist condivise
- Tasto destro su una playlist → **Condividi playlist...**: il link è copiato. Chi lo apre (o lo incolla col bottone 🔗 accanto a "Playlist", o nel bottone persone) riceve la playlist
- Aggiunte, rimozioni, ordine, nome e copertina si sincronizzano per tutti, anche se uno era offline (si allinea quando riapre l'app). Per risparmiare la quota del server l'app controlla le novità ogni 5 minuti (le tue modifiche partono subito)
- Massimo 10 playlist condivise a testa (limite del server)
- I brani che non hai diventano canzoni in streaming: menu → *Scarica sul PC* per averli offline
- *Smetti di condividere* / *Elimina* toccano solo la tua copia

## Streaming
- Di default si scarica come sempre. Nella ricerca, bottone **+** → *Riproduci in streaming*, *Aggiungi alla coda*, *Salva in libreria (solo streaming)*
- Impostazioni → **"Non scaricare: aggiungi le canzoni solo in streaming"**: il bottone Scarica diventa *Aggiungi* (vale anche per playlist YouTube e Spotify)
- Le canzoni in streaming hanno "Streaming ·" sotto il titolo. Menu → *Scarica sul PC*; al contrario, su una canzone scaricata *Solo streaming (elimina il file)*
- Taglia audio ed "Esporta con effetti" richiedono il file: scarica prima la canzone

## Sonus 1.0.4
- **Fix "X ha messo in pausa" falso**: nella stanza play e pausa partono solo se qualcuno li clicca davvero; una pausa causata dall'app (caricamento, errore, ritardo) resta tua e l'app si rimette in pari da sola
- **Fix canzoni in streaming che caricavano 15-20 secondi**: a volte il server di YouTube non risponde alla prima richiesta; ora dopo 5 secondi riprova subito invece di aspettarne 20

## Sonus 1.0.3
- Icona senza sfondo
- Se Sonus è installato in una cartella protetta (es. C:\Program Files), l'aggiornamento chiede il permesso a Windows invece di fallire
- Fix: il bottone ▶ sulle copertine (Home/Scopri) non faceva partire la canzone
- Fix: errori ripetuti nel log quando clicchi nella finestra
- Lo streaming parte prima (ffmpeg aspetta meno dati prima di iniziare)

## Sonus 1.0.2
- Log dettagliato dello streaming: tempo di ricerca su YouTube, primo audio e avvisi del motore di YouTube


## Sonus 1.0.1
- **Nuova icona**
- Canzoni in streaming più rapide: YouTube resta "caldo" tra una canzone e l'altra, le canzoni già cercate non si ricercano più (e agli amici arriva direttamente il video), le prossime 2 della coda sono cercate in anticipo
- Fix "ha messo in pausa" falso: chi ha il Ritardo sopra 0, o non riesce a caricare la canzone, non mette più in pausa tutti
- Se uno streaming fallisce si ricarica da solo
- Niente silenzio quando si salta avanti in una canzone ancora in caricamento: parte appena arriva, al punto giusto
- I tuoi file (mp3, tagliati, con effetti) arrivano agli amici come file tuo; se un sito di caricamento non va ne prova altri 2
- Stanza → **Copia diagnostica**: incolla il testo in chat se qualcosa non va. Il log (`%APPDATA%\Sonus\log.txt`) ora tiene orari e storico

## Sonus 1.0.0
- **Sonus** è la nuova app (prima "Synth Music"): installer, cartelle e aggiornamenti tutti suoi, da `github.com/DaRealDante/Sonus`
- Al primo avvio copia libreria, playlist e impostazioni di Synth Music (l'originale resta com'è; le canzoni non occupano spazio doppio)
- Stanze e playlist condivise sul server privato di Sonus: codici `SONUS-…` / `SONUSP-…`, link `sonus://`
