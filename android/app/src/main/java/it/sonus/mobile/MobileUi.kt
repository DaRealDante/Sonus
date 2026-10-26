package it.sonus.mobile

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.draw.alpha
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.tween
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.json.JSONArray
import org.json.JSONObject

private data class FormSpec(val title: String, val fields: List<Pair<String, String>>, val save: (Map<String, String>) -> Unit)

@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable fun SonusApp(state: JSONObject, send: Send, pick: (JSONObject) -> Unit, share: (String) -> Unit, open: (String) -> Unit) {
    var route by rememberSaveable { mutableStateOf("Home") }
    var previous by rememberSaveable { mutableStateOf("Home") }
    var playlistId by rememberSaveable { mutableIntStateOf(-1) }
    var songMenu by remember { mutableStateOf<JSONObject?>(null) }
    var form by remember { mutableStateOf<FormSpec?>(null) }
    var formError by remember { mutableStateOf("") }
    var selected by remember { mutableStateOf(setOf<Int>()) }
    var query by rememberSaveable { mutableStateOf("") }
    var filter by rememberSaveable { mutableStateOf("") }
    val songs = remember(state.opt("songs")) { state.list("songs") }
    val playlists = remember(state.opt("playlists")) { state.list("playlists") }
    val current = state.optJSONObject("current")
    val snack = remember { SnackbarHostState() }
    val pageOpacity = remember { Animatable(1f) }
    val nav = listOf("Home" to "⌂", "Cerca" to "⌕", "Libreria" to "▤", "Scopri" to "✧")
    fun go(page: String) { previous = route; route = page; filter = "" }
    fun prompt(title: String, vararg fields: Pair<String, String>, save: (Map<String, String>) -> Unit) { form = FormSpec(title, fields.toList(), save) }
    fun play(list: List<JSONObject>, index: Int = 0) { send("play", json("ids" to ids(list), "index" to index)) }
    fun showSong(song: JSONObject) { songMenu = song }
    fun setting(key: String, value: Any) { send("settings", json("values" to json(key to value))) }
    BackHandler(route !in nav.map { it.first }) { route = previous.takeIf { it in nav.map { n -> n.first } } ?: "Home" }
    LaunchedEffect(state.opt("messageId")) { state.str("message").takeIf { it.isNotBlank() }?.let { snack.showSnackbar(it) } }
    LaunchedEffect(route, state.obj("settings").flag("fxTransitions", true)) { if (state.obj("settings").flag("fxTransitions", true)) { pageOpacity.snapTo(.3f); pageOpacity.animateTo(1f, tween(160)) } else pageOpacity.snapTo(1f) }
    LaunchedEffect(form) { formError = "" }

    Scaffold(containerColor = MaterialTheme.colorScheme.background, snackbarHost = { SnackbarHost(snack) }, topBar = {
        CenterAlignedTopAppBar(title = { Text(if (route == "Playlist") playlists.find { it.int("id") == playlistId }?.str("name") ?: "Playlist" else if (route == "Player") "In riproduzione" else route, maxLines = 1, overflow = TextOverflow.Ellipsis, fontWeight = FontWeight.Bold) },
            navigationIcon = { if (route !in nav.map { it.first }) IconButton(onClick = { route = "Home" }) { Text("‹", fontSize = 32.sp) } else IconButton(onClick = { go("Profilo") }) { Text("◉", color = MaterialTheme.colorScheme.primary, fontSize = 24.sp) } },
            actions = { IconButton(onClick = { go("Stanza") }) { Text("♧", Modifier.semantics { contentDescription = "Ascolta insieme" }, fontSize = 26.sp) }; IconButton(onClick = { go("Impostazioni") }) { Text("⚙", Modifier.semantics { contentDescription = "Impostazioni" }, fontSize = 24.sp) } })
    }, bottomBar = {
        Column {
            if (current != null && route != "Player") MiniPlayer(current, state, { go("Player") }, { send("toggle", json()) })
            if (route in nav.map { it.first }) NavigationBar(containerColor = MaterialTheme.colorScheme.background) {
                nav.forEach { (label, icon) -> NavigationBarItem(selected = route == label, onClick = { go(label); if (label == "Scopri" && state.obj("discover").list("sections").isEmpty()) send("discover", json()) }, icon = { Text(icon, fontSize = 25.sp) }, label = { Text(label) }, modifier = Modifier.testTag("nav_$label")) }
            }
        }
    }) { padding ->
        Box(Modifier.fillMaxSize().padding(padding).alpha(pageOpacity.value)) {
            if (route != "Video" && state.obj("settings").str("ambientMode") == "background" && state.obj("video").str("url").isNotEmpty()) VideoSurface(state, Modifier.matchParentSize().alpha(.18f))
            if (!state.flag("ready")) {
                Column(Modifier.align(Alignment.Center), horizontalAlignment = Alignment.CenterHorizontally) { CircularProgressIndicator(); Spacer(Modifier.height(16.dp)); Text(state.str("error", "Avvio di Sonus…")) }
            } else when (route) {
                "Home" -> LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    item { Title("La tua musica.", "Sempre con te.") }
                    if (state.obj("room").str("code").isNotEmpty()) item { ElevatedCard(onClick = { go("Stanza") }, Modifier.fillMaxWidth()) { Column(Modifier.padding(18.dp)) { Text("Stai ascoltando insieme", fontWeight = FontWeight.Bold); Text(state.obj("room").str("code"), color = MaterialTheme.colorScheme.primary) } } }
                    item { LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) { item { Action("Preferiti") { go("Preferiti") } }; item { Action("Recenti") { go("Recenti") } }; item { Action("Download") { go("Download") } }; item { Action("Coda") { go("Coda") } } } }
                    item { Text("Ascoltati di recente", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold) }
                    item { LazyRow(horizontalArrangement = Arrangement.spacedBy(14.dp)) { itemsIndexed(state.list("recent").take(16)) { _, song -> Column(Modifier.width(142.dp).clickable { play(listOf(song)) }) { Artwork(song, Modifier.size(142.dp)); Text(song.str("title"), maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 8.dp)); Text(song.str("artist"), color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1) } } } }
                    item { Text("Le tue playlist", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold) }
                    itemsIndexed(playlists) { _, playlist -> PlaylistRow(playlist, { playlistId = playlist.int("id"); go("Playlist") }, { playlistId = playlist.int("id"); go("Gestisci playlist") }) }
                    if (songs.isEmpty()) item { EmptyCard("Porta qui la tua musica", "Cerca un brano oppure importa i tuoi file.") { go("Cerca") } }
                }
                "Cerca" -> Column(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
                    OutlinedTextField(query, { query = it }, label = { Text("Artisti, brani o link YouTube/Spotify") }, modifier = Modifier.fillMaxWidth().testTag("search_input"), singleLine = true)
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(onClick = { send("search", json("query" to query)) }, modifier = Modifier.weight(1f).testTag("search_submit"), enabled = query.isNotBlank()) { Text("Cerca") }
                        Action("Importa") { pick(json("kind" to "audio")) }
                    }
                    if (state.obj("search").flag("busy")) LinearProgressIndicator(Modifier.fillMaxWidth())
                    val entries = state.obj("search").list("entries")
                    if (entries.isNotEmpty()) LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        item { Action("Riproduci tutto") { send("search_play", json("entries" to JSONArray(entries))) } }
                        item { Action("Salva tutto") { send("stream_add", json("entries" to JSONArray(entries))) } }
                        item { Action("Scarica tutto") { send("download", json("entries" to JSONArray(entries))) } }
                        item { Action("Crea playlist") { prompt("Importa in una playlist", "Nome" to state.obj("search").str("title", query)) { send("playlist_create", json("name" to it["Nome"], "entries" to JSONArray(entries))) } } }
                    }
                    LazyColumn(Modifier.weight(1f)) { itemsIndexed(entries) { _, entry -> EntryRow(entry, { send("play_entry", json("entry" to entry)) }, { songMenu = json("entry" to entry, "title" to entry.str("title"), "artist" to entry.str("artist", entry.str("channel"))) }) } }
                }
                "Libreria", "Preferiti", "Recenti", "Playlist" -> {
                    val playlist = playlists.find { it.int("id") == playlistId } ?: JSONObject()
                    val list = when (route) { "Preferiti" -> state.list("favorites"); "Recenti" -> state.list("recent"); "Playlist" -> playlist.list("songs"); else -> songs }
                    Column(Modifier.fillMaxSize()) {
                        if (route == "Libreria") LazyRow(Modifier.padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            item { Action("Playlist") { go("Playlist salvate") } }; item { Action("Preferiti") { go("Preferiti") } }; item { Action("Recenti") { go("Recenti") } }; item { Action("Download") { go("Download") } }; item { Action("Importa file") { pick(json("kind" to "audio")) } }; item { Action("Importa cartella") { pick(json("kind" to "folder")) } }
                        }
                        Row(Modifier.padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Button(onClick = { play(list) }, enabled = list.isNotEmpty()) { Text("Riproduci") }
                            Action("Casuale", list.isNotEmpty()) { send("shuffle", json("enabled" to true)); play(list) }
                            if (route == "Playlist") IconButton(onClick = { go("Gestisci playlist") }) { Text("⋯", fontSize = 28.sp) }
                            Text("${list.size} brani", color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        if (route == "Playlist" && playlist.str("description").isNotEmpty()) Text(playlist.str("description"), Modifier.padding(horizontal = 20.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
                        OutlinedTextField(filter, { filter = it }, Modifier.fillMaxWidth().padding(16.dp, 4.dp), label = { Text("Filtra i brani") }, singleLine = true)
                        if (selected.isNotEmpty()) LazyRow(Modifier.padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            item { Action("${selected.size} selezionati · annulla") { selected = emptySet() } }
                            item { Action("In coda") { send("queue_add", json("ids" to JSONArray(selected.toList()))); selected = emptySet() } }
                            item { Action("A playlist") { songMenu = json("selection" to JSONArray(selected.toList()), "title" to "${selected.size} brani selezionati") } }
                            item { Action("Scarica") { send("download_song", json("ids" to JSONArray(selected.toList()))) } }
                        }
                        LazyColumn(Modifier.weight(1f)) {
                            itemsIndexed(list.filter { "${it.str("title")} ${it.str("artist")}".contains(filter, true) }) { index, song ->
                                SongRow(song, selected.contains(song.int("id")), { if (selected.isNotEmpty()) selected = if (song.int("id") in selected) selected - song.int("id") else selected + song.int("id") else play(list, list.indexOf(song)) }, { showSong(song) }, { selected = selected + song.int("id") })
                            }
                            if (list.isEmpty()) item { Text("Qui troverai i tuoi brani.", Modifier.padding(24.dp), color = MaterialTheme.colorScheme.onSurfaceVariant) }
                        }
                    }
                }
                "Playlist salvate" -> ScrollPage {
                    Action("Crea playlist") { prompt("Nuova playlist", "Nome" to "", "Descrizione" to "") { send("playlist_create", json("name" to it["Nome"], "description" to it["Descrizione"])) } }
                    Action("Aggiungi playlist condivisa") { prompt("Playlist condivisa", "Codice o link" to "") { send("playlist_join", json("code" to it["Codice o link"])) } }
                    playlists.forEachIndexed { index, playlist ->
                        PlaylistRow(playlist, { playlistId = playlist.int("id"); go("Playlist") }, { playlistId = playlist.int("id"); go("Gestisci playlist") })
                        OrderButtons(index, playlists.size) { from, to -> val order = playlists.toMutableList(); order.add(to, order.removeAt(from)); send("playlist_order", json("ids" to ids(order))) }
                    }
                }
                "Gestisci playlist" -> ScrollPage {
                    val playlist = playlists.find { it.int("id") == playlistId } ?: JSONObject()
                    Artwork(playlist, Modifier.size(160.dp).align(Alignment.CenterHorizontally))
                    Action("Modifica dettagli") { prompt("Dettagli playlist", "Nome" to playlist.str("name"), "Descrizione" to playlist.str("description")) { send("playlist_edit", json("id" to playlistId, "name" to it["Nome"], "description" to it["Descrizione"], "cover" to playlist.opt("cover"))) } }
                    Action("Cambia copertina") { pick(json("kind" to "playlist_cover", "id" to playlistId, "name" to playlist.str("name"), "description" to playlist.str("description"))) }
                    Action("Importa file") { pick(json("kind" to "audio", "playlistId" to playlistId)) }
                    Action("Aggiungi alla coda") { send("queue_add", json("ids" to ids(playlist.list("songs")))) }
                    if (playlist.str("code").isNotEmpty()) {
                        Action("Condividi link") { share(playlist.str("link", "sonus://join/${playlist.str("code")}")) }
                        Action("Smetti di condividere") { send("playlist_unshare", json("id" to playlistId)) }
                    } else Action("Condividi playlist") { send("playlist_share", json("id" to playlistId)) }
                    Action("Elimina playlist") { prompt("Elimina playlist", "Scrivi ELIMINA" to "") { if (it["Scrivi ELIMINA"] == "ELIMINA") { send("playlist_delete", json("id" to playlistId)); go("Libreria") } } }
                    Text("Ordine dei brani", style = MaterialTheme.typography.titleLarge)
                    val entries = playlist.list("songs")
                    entries.forEachIndexed { index, song ->
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(song.str("title"), Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                            OrderButtons(index, entries.size) { from, to -> val order = entries.toMutableList(); order.add(to, order.removeAt(from)); send("playlist_reorder", json("id" to playlistId, "entryIds" to JSONArray(order.map { it.int("entryId", it.int("id")) }))) }
                            IconButton(onClick = { send("playlist_remove", json("id" to playlistId, "entryIds" to JSONArray().put(song.int("entryId", song.int("id")))) ) }) { Text("×") }
                        }
                    }
                }
                "Scopri" -> LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(20.dp)) {
                    item { Title("Trova il prossimo brano", "Mix e consigli dai tuoi ascolti") ; Action("Aggiorna consigli") { send("discover", json()) } }
                    state.obj("discover").list("sections").forEach { section ->
                        item { Text(section.str("title"), style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, modifier = Modifier.padding(vertical = 18.dp)) }
                        item { LazyRow(horizontalArrangement = Arrangement.spacedBy(14.dp)) { itemsIndexed(section.list("items")) { _, entry ->
                            Column(Modifier.width(144.dp).clickable {
                                when (section.str("kind")) { "artists" -> { send("discover_artist", json("id" to entry.opt("id"))); go("Risultati Scopri") }; "albums" -> { send("discover_album", json("id" to entry.opt("id"))); go("Risultati Scopri") }; else -> send("play_entry", json("entry" to entry)) }
                            }) { Artwork(entry, Modifier.size(144.dp)); Text(entry.str("title", entry.str("name")), maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 8.dp)); Text(entry.str("artist"), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                        } } }
                    }
                }
                "Risultati Scopri" -> ScrollPage { state.obj("search").list("entries").forEach { entry -> EntryRow(entry, { send("play_entry", json("entry" to entry)) }, { songMenu = json("entry" to entry, "title" to entry.str("title")) }) } }
                "Player" -> FullPlayer(state, send, ::go, { current?.let(::showSong) })
                "Coda" -> ScrollPage {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { Action("Svuota prossimi") { send("queue_clear", json()) }; ToggleRow("Ferma a fine brano", state.obj("settings").flag("stopAfterCurrent")) { setting("stopAfterCurrent", it) } }
                    state.list("queue").forEachIndexed { index, song ->
                        SongRow(song, index == state.int("index"), { send("queue_jump", json("index" to index)) }, { showSong(song) })
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                            OrderButtons(index, state.list("queue").size) { from, to -> send("queue_move", json("from" to from, "to" to to)) }
                            TextButton(onClick = { send("queue_remove", json("indexes" to JSONArray().put(index))) }) { Text("Rimuovi") }
                        }
                    }
                }
                "Download" -> ScrollPage {
                    Action("Rimuovi completati") { send("downloads_clear", json()) }
                    state.list("downloads").forEachIndexed { index, job ->
                        Text(job.obj("entry").str("title", job.str("title", "Download")), fontWeight = FontWeight.Bold)
                        Text(job.str("status"), color = MaterialTheme.colorScheme.onSurfaceVariant)
                        LinearProgressIndicator(progress = { (job.num("percent") / 100).toFloat().coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth())
                        if (job.str("error").isNotEmpty()) { Text(job.str("error")); Action("Riprova") { send("download_retry", json("index" to index)) } }
                    }
                    if (state.list("downloads").isEmpty()) Text("Nessun download. Cerca un brano per salvarlo offline.")
                }
                "Effetti" -> EffectsScreen(state, send) { title -> prompt("Salva con effetti", "Titolo" to title) { send("export", json("id" to current?.int("id"), "title" to it["Titolo"])) } }
                "Equalizzatore" -> EqualizerScreen(state, send) { callback -> prompt("Salva preset", "Nome" to "") { callback(it["Nome"].orEmpty()) } }
                "Loop e taglio" -> EditAudioScreen(state, send, { title, fields, callback -> form = FormSpec(title, fields, callback) })
                "Testi" -> LyricsScreen(state, send, { title, fields, callback -> form = FormSpec(title, fields, callback) })
                "Video" -> VideoScreen(state, send, pick)
                "Stanza" -> RoomScreen(state, send, share) { go("Profilo") }
                "Profilo" -> ScrollPage {
                    val profile = state.obj("profile")
                    Title("Come ti vedono gli amici")
                    var name by remember(profile.str("name")) { mutableStateOf(profile.str("name")) }
                    OutlinedTextField(name, { name = it }, Modifier.fillMaxWidth(), label = { Text("Nome") })
                    Action("Salva nome") { send("profile", json("name" to name)) }
                    Action("Scegli foto") { pick(json("kind" to "profile")) }
                    Action("Rimuovi foto") { send("profile", json("photo" to "")) }
                }
                "Impostazioni" -> SettingsScreen(state, send, pick, open, share, { title, fields, callback -> form = FormSpec(title, fields, callback) })
            }
            if (state.list("tasks").isNotEmpty()) LinearProgressIndicator(Modifier.fillMaxWidth().align(Alignment.TopCenter))
        }
    }

    if (songMenu != null) {
        val song = songMenu!!
        val entry = song.optJSONObject("entry")
        val selectedIds = song.optJSONArray("selection") ?: JSONArray().put(song.int("id"))
        ModalBottomSheet(onDismissRequest = { songMenu = null }) {
            Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(song.str("title"), style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                if (entry != null) {
                    Action("Riproduci in streaming") { send("play_entry", json("entry" to entry)); songMenu = null }
                    Action("Salva nella libreria") { send("stream_add", json("entries" to JSONArray().put(entry))); songMenu = null }
                    Action("Aggiungi alla coda") { send("stream_add", json("entries" to JSONArray().put(entry), "queue" to true)); songMenu = null }
                    Action("Scarica sul telefono") { send("download", json("entries" to JSONArray().put(entry))); songMenu = null }
                } else {
                    Action("Riproduci") { send("play", json("ids" to selectedIds, "index" to 0)); songMenu = null }
                    Action("Riproduci dopo") { send("queue_next", json("ids" to selectedIds)); songMenu = null }
                    Action("Aggiungi alla coda") { send("queue_add", json("ids" to selectedIds)); songMenu = null }
                    if (song.int("id") > 0) Action(if (song.flag("favorite")) "Rimuovi dai preferiti" else "Salva nei preferiti") { send("favorite", json("id" to song.int("id"))); songMenu = null }
                    Text("Aggiungi a playlist", fontWeight = FontWeight.Bold)
                    Action("Nuova playlist") { songMenu = null; prompt("Nuova playlist", "Nome" to "") { send("playlist_create", json("name" to it["Nome"], "ids" to selectedIds)) } }
                    playlists.forEach { playlist -> TextButton(onClick = { send("playlist_add", json("id" to playlist.int("id"), "ids" to selectedIds)); songMenu = null }) { Text(playlist.str("name")) } }
                    Action("Scarica per l'ascolto offline") { send("download_song", json("ids" to selectedIds)); songMenu = null }
                    if (song.int("id") > 0) {
                        Action("Solo streaming · elimina file scaricato") { songMenu = null; prompt("Passa allo streaming", "Scrivi CONFERMA" to "") { if (it["Scrivi CONFERMA"] == "CONFERMA") send("stream_only", json("id" to song.int("id"))) } }
                        Action("Modifica informazioni") { songMenu = null; prompt("Informazioni brano", "Titolo" to song.str("title"), "Artista" to song.str("artist"), "Album" to song.str("album")) { send("song_edit", json("id" to song.int("id"), "fields" to json("title" to it["Titolo"], "artist" to it["Artista"], "album" to it["Album"]))) } }
                        Action("Cambia copertina") { pick(json("kind" to "song_cover", "id" to song.int("id"))); songMenu = null }
                        Action("Loop, taglio ed esportazione") { play(listOf(song)); go("Loop e taglio"); songMenu = null }
                        Action("Testi e video") { play(listOf(song)); go("Testi"); songMenu = null }
                        if (!song.str("path").startsWith("stream:")) Action("Condividi file audio") { share(song.str("path")); songMenu = null }
                        if (song.str("url").isNotEmpty()) Action("Apri su YouTube") { open(song.str("url")); songMenu = null }
                        Action("Seleziona più brani") { selected = selected + song.int("id"); songMenu = null }
                    }
                    Action("Elimina dalla libreria") { songMenu = null; prompt("Elimina dalla libreria", "Scrivi ELIMINA" to "", "Eliminare anche i file? sì/no" to "no") { if (it["Scrivi ELIMINA"] == "ELIMINA") send("song_delete", json("ids" to selectedIds, "deleteFiles" to (it["Eliminare anche i file? sì/no"].orEmpty().lowercase() in listOf("sì", "si")))) } }
                }
                Spacer(Modifier.height(20.dp))
            }
        }
    }
    form?.let { spec ->
        val values = remember(spec) { spec.fields.associate { it.first to mutableStateOf(it.second) } }
        AlertDialog(onDismissRequest = { form = null }, title = { Text(spec.title) }, text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                if (formError.isNotEmpty()) Text(formError, color = MaterialTheme.colorScheme.error)
                spec.fields.forEach { (label, _) -> OutlinedTextField(values.getValue(label).value, { values.getValue(label).value = it }, label = { Text(label) }, modifier = Modifier.fillMaxWidth(), minLines = if (label.contains("Testo") || label.contains("LRC")) 5 else 1) }
            }
        }, confirmButton = { TextButton(onClick = { runCatching { spec.save(values.mapValues { it.value.value }) }.onSuccess { form = null }.onFailure { formError = it.message ?: "Controlla i valori inseriti" } }) { Text("Conferma") } }, dismissButton = { TextButton(onClick = { form = null }) { Text("Annulla") } })
    }
}

@Composable fun ScrollPage(content: @Composable ColumnScope.() -> Unit) { Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp), content = content) }

@Composable private fun EmptyCard(title: String, text: String, click: () -> Unit) { ElevatedCard(Modifier.fillMaxWidth()) { Column(Modifier.padding(20.dp)) { Text(title, style = MaterialTheme.typography.titleLarge); Text(text, Modifier.padding(vertical = 12.dp)); Button(onClick = click) { Text("Trova musica") } } } }

@Composable private fun PlaylistRow(playlist: JSONObject, click: () -> Unit, menu: () -> Unit) { Row(Modifier.fillMaxWidth().heightIn(min = 76.dp).clickable(onClick = click), verticalAlignment = Alignment.CenterVertically) { Artwork(playlist); Column(Modifier.weight(1f).padding(horizontal = 14.dp)) { Text(playlist.str("name"), fontWeight = FontWeight.SemiBold); Text(if (playlist.str("code").isNotEmpty()) "Playlist condivisa" else "Playlist · ${playlist.list("songs").size} brani", color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall) }; IconButton(onClick = menu) { Text("⋯", fontSize = 26.sp) } } }

@OptIn(ExperimentalFoundationApi::class)
@Composable fun SongRow(song: JSONObject, selected: Boolean = false, click: () -> Unit, menu: () -> Unit, longClick: () -> Unit = menu) {
    Row(Modifier.fillMaxWidth().background(if (selected) MaterialTheme.colorScheme.primary.copy(alpha = .12f) else Color.Transparent).combinedClickable(onClick = click, onLongClick = longClick).padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        Artwork(song)
        Column(Modifier.weight(1f).padding(horizontal = 12.dp)) { Text(song.str("title"), maxLines = 1, overflow = TextOverflow.Ellipsis, fontWeight = FontWeight.Medium); Text((if (song.str("path").startsWith("stream:")) "Streaming · " else "") + song.str("artist"), maxLines = 1, overflow = TextOverflow.Ellipsis, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall) }
        IconButton(onClick = menu) { Text("⋯", Modifier.semantics { contentDescription = "Opzioni di ${song.str("title")}" }, fontSize = 26.sp) }
    }
}

@Composable private fun EntryRow(entry: JSONObject, click: () -> Unit, menu: () -> Unit) { SongRow(entry, false, click, menu) }

@Composable fun OrderButtons(index: Int, size: Int, move: (Int, Int) -> Unit) { Row { IconButton(onClick = { move(index, index - 1) }, enabled = index > 0) { Text("↑", Modifier.semantics { contentDescription = "Sposta su" }) }; IconButton(onClick = { move(index, index + 1) }, enabled = index < size - 1) { Text("↓", Modifier.semantics { contentDescription = "Sposta giù" }) } } }
