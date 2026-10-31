package it.sonus.mobile

import android.content.Context
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.media3.common.MediaItem
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.ui.PlayerView
import org.json.JSONObject
import java.io.File

@androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)
@Composable fun VideoSurface(state: JSONObject, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val video = state.obj("video")
    val url = video.str("url")
    if (url.isEmpty()) return
    val headers = remember(video.opt("headers")) { video.obj("headers").let { h -> h.keys().asSequence().associateWith { h.str(it) } } }
    val fps = state.obj("settings").int("videoFps")
    val allowBackground = !state.obj("settings").flag("pauseVideoInBackground", true)
    val player = remember(url, headers, fps) {
        val http = DefaultHttpDataSource.Factory().setDefaultRequestProperties(headers)
        ExoPlayer.Builder(context, SonusVideoRenderers(context, fps)).setMediaSourceFactory(DefaultMediaSourceFactory(DefaultDataSource.Factory(context, http))).build().apply {
            volume = 0f
            setMediaItem(MediaItem.fromUri(if (url.startsWith("/")) android.net.Uri.fromFile(File(url)) else android.net.Uri.parse(url)))
            prepare()
        }
    }
    DisposableEffect(player, lifecycle, allowBackground) {
        val observer = LifecycleEventObserver { _, event -> if (event == Lifecycle.Event.ON_STOP && !allowBackground) player.pause() }
        lifecycle.addObserver(observer)
        onDispose { lifecycle.removeObserver(observer); player.release() }
    }
    LaunchedEffect(player, state.opt("position"), state.opt("playing")) {
        if (kotlin.math.abs(player.currentPosition - state.num("position").toLong()) > 900) player.seekTo(state.num("position").toLong())
        player.setPlaybackSpeed(state.obj("effects").num("rate", 1.0).toFloat())
        player.playWhenReady = state.flag("playing") && (allowBackground || lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED))
    }
    AndroidView(factory = { PlayerView(it).apply { this.player = player; useController = false } }, update = { it.player = player }, modifier = modifier)
}

@Composable fun VideoScreen(state: JSONObject, send: Send, pick: (JSONObject) -> Unit) = ScrollPage {
    val song = state.optJSONObject("current")
    if (song == null) { Text("Avvia un brano per mostrare il video."); return@ScrollPage }
    var query by remember(song.int("id")) { mutableStateOf(song.str("title") + " " + song.str("artist")) }
    var fullscreen by remember { mutableStateOf(false) }
    Title(song.str("title"), "Video sincronizzato con la musica")
    if (state.obj("video").str("url").isNotEmpty()) VideoSurface(state, Modifier.fillMaxWidth().aspectRatio(16f / 9f))
    else { Artwork(song, Modifier.fillMaxWidth().aspectRatio(1f)); if (state.obj("video").flag("loading")) LinearProgressIndicator(Modifier.fillMaxWidth()) }
    Action("Schermo intero") { fullscreen = true }
    Text("Video di sfondo", style = MaterialTheme.typography.titleLarge)
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { listOf("off" to "Spento", "background" to "Sfondo", "fullscreen" to "Intero").forEach { (mode, label) -> Action(label) { send("settings", json("values" to json("ambientMode" to mode, "ambientVideo" to (mode != "off")))) ; if (mode == "fullscreen") fullscreen = true } } }
    ToggleRow("Video automatico per questo brano", song.flag("videoAuto", true)) { send("song_edit", json("id" to song.int("id"), "fields" to json("videoAuto" to if (it) 1 else 0))) }
    Action("Scarica video originale") { send("video_download", json("id" to song.int("id"))) }
    Action("Scegli un video dal telefono") { pick(json("kind" to "video", "id" to song.int("id"))) }
    Action("Rimuovi video") { send("video_remove", json("id" to song.int("id"))) }
    OutlinedTextField(query, { query = it }, Modifier.fillMaxWidth(), label = { Text("Cerca un altro video") })
    Action("Cerca video") { send("video_search", json("query" to query)) }
    state.list("videoResults").forEach { result ->
        ElevatedCard(onClick = { send("video_set", json("id" to song.int("id"), "url" to result.str("url"))) }, modifier = Modifier.fillMaxWidth()) {
            Row(Modifier.padding(12.dp)) { Artwork(result); Column(Modifier.padding(start = 12.dp)) { Text(result.str("title")); TextButton(onClick = { send("video_download", json("id" to song.int("id"), "url" to result.str("url"))) }) { Text("Scarica video") } } }
        }
    }
    if (fullscreen) Dialog(onDismissRequest = { fullscreen = false }, properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false)) {
        Box(Modifier.fillMaxSize().background(androidx.compose.ui.graphics.Color.Black)) {
            VideoSurface(state, Modifier.fillMaxSize())
            TextButton(onClick = { fullscreen = false }, modifier = Modifier.statusBarsPadding()) { Text("Chiudi schermo intero") }
        }
    }
}

@Composable fun RoomScreen(state: JSONObject, send: Send, share: (String) -> Unit, profile: () -> Unit) = ScrollPage {
    val room = state.obj("room")
    var code by remember { mutableStateOf("") }
    Title("Ascolta insieme", "La stessa musica, nello stesso momento. Anche tra PC e telefono.")
    if (room.str("code").isEmpty()) {
        Button(onClick = { send("room_create", json()) }, modifier = Modifier.fillMaxWidth()) { Text("Crea una stanza") }
        OutlinedTextField(code, { code = it }, Modifier.fillMaxWidth(), label = { Text("Codice o link Sonus") })
        Action("Entra", code.isNotBlank()) { send("handle_code", json("code" to code)) }
    } else {
        Text(room.str("code"), style = MaterialTheme.typography.headlineSmall)
        Text(if (room.flag("connected")) "● Connesso" else "Connessione in corso…", color = MaterialTheme.colorScheme.primary)
        Action("Condividi invito") { share(room.str("link", "sonus://join/${room.str("code")}")) }
        Text("Nella stanza", style = MaterialTheme.typography.titleLarge)
        val peers = room.list("peers")
        peers.forEach { peer -> Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) { Text("◉"); Text(peer.str("name", peer.str("id", "Amico"))) } }
        Text("${peers.size + 1} partecipanti", color = MaterialTheme.colorScheme.onSurfaceVariant)
        ValueSlider("Ritardo personale", room.num("delayMs").toFloat(), 0f..3000f, "${room.int("delayMs")} ms") { send("room_delay", json("value" to it.toInt())) }
        Action("Esci dalla stanza") { send("room_leave", json()) }
    }
    Action("Modifica profilo", true, profile)
    Action("Diagnostica stanza") { send("diagnostics", json()) }
    if (state.str("diagnostics").isNotEmpty()) {
        Text(state.str("diagnostics"), style = MaterialTheme.typography.bodySmall)
        Action("Condividi diagnostica") { share(state.str("diagnostics")) }
    }
}

@Composable fun SettingsScreen(state: JSONObject, send: Send, pick: (JSONObject) -> Unit, open: (String) -> Unit, share: (String) -> Unit, prompt: Prompt) = ScrollPage {
    val values = state.obj("settings")
    fun set(key: String, value: Any) { send("settings", json("values" to json(key to value))) }
    Title("Ascolto")
    ToggleRow("Aggiungi i brani solo in streaming", values.flag("streamOnly", true)) { set("streamOnly", it) }
    ToggleRow("Salva automaticamente i testi", values.flag("autoLyrics", true)) { set("autoLyrics", it) }
    ToggleRow("Salva il video dei brani scaricati", values.flag("autoVideo", true)) { set("autoVideo", it) }
    ToggleRow("Video in streaming", values.flag("streamVideo", true)) { set("streamVideo", it) }
    ToggleRow("Pausa video quando l'app è in background", values.flag("pauseVideoInBackground", true)) { set("pauseVideoInBackground", it) }
    Text("Qualità MP3", style = MaterialTheme.typography.titleMedium)
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { listOf("128", "192", "256", "320").forEach { quality -> FilterChip(selected = values.str("audioQuality") == quality, onClick = { set("audioQuality", quality) }, label = { Text(quality) }) } }
    Text("Qualità video", style = MaterialTheme.typography.titleMedium)
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { listOf("480", "720", "1080").forEach { quality -> FilterChip(selected = values.str("videoQuality") == quality, onClick = { set("videoQuality", quality) }, label = { Text("${quality}p") }) } }
    ValueSlider("Risultati ricerca", values.num("searchResults", 25.0).toFloat(), 5f..50f, values.int("searchResults", 25).toString()) { set("searchResults", it.toInt()) }
    Text("FPS video", style = MaterialTheme.typography.titleMedium)
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { listOf(0, 12, 24, 30, 60).forEach { fps -> FilterChip(selected = values.int("videoFps") == fps, onClick = { set("videoFps", fps) }, label = { Text(if (fps == 0) "Auto" else fps.toString()) }) } }
    Title("Aspetto")
    listOf("fxTransitions" to "Transizioni", "fxCoverColors" to "Colori dalla copertina", "fxVisualizer" to "Visualizzatore audio", "fxMicro" to "Animazioni dei controlli", "fxSongFade" to "Dissolvenza tra i brani").forEach { (key, label) -> ToggleRow(label, values.flag(key, true)) { set(key, it) } }
    Text("Colore del brano", style = MaterialTheme.typography.titleMedium)
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { listOf("cover" to "Copertina", "custom" to "Personale", "video" to "Video").forEach { (key, label) -> FilterChip(selected = values.str("songColorSource", "cover") == key, onClick = { set("songColorSource", key) }, label = { Text(label) }) } }
    Action("Scegli colore principale") { prompt("Colore principale", listOf("Colore esadecimale" to values.str("songColorCustom", "#1ED760"))) { set("songColorCustom", it["Colore esadecimale"].orEmpty()) } }
    Action("Personalizza colori del tema") { prompt("Colori del tema", listOf("Accento" to values.obj("themeColors").str("accent", "#1ED760"), "Sfondo" to values.obj("themeColors").str("background", "#090B0E"), "Pannelli" to values.obj("themeColors").str("panel", "#15191E"), "Barre" to values.obj("themeColors").str("sidebar", "#21262D"), "Testo" to values.obj("themeColors").str("text", "#F5F7F8"))) { colors ->
        colors.values.forEach { android.graphics.Color.parseColor(it) }
        set("themeColors", json("accent" to colors["Accento"], "background" to colors["Sfondo"], "panel" to colors["Pannelli"], "sidebar" to colors["Barre"], "text" to colors["Testo"]))
    } }
    Title("Aggiornamenti")
    ToggleRow("Controlla aggiornamenti automaticamente", values.flag("autoCheckUpdates", true)) { set("autoCheckUpdates", it) }
    Action("Aggiorna motore YouTube") { send("engine_update", json()) }
    Action("Controlla aggiornamenti Android") { send("update_check", json()) }
    val update = state.obj("update")
    if (update.str("url").isNotEmpty()) Action("Scarica ${update.str("version", "aggiornamento")}") { open(update.str("url")) }
    Action("Installa aggiornamento da file APK") { pick(json("kind" to "apk")) }
    Title("File e dati")
    Action("Importa file audio") { pick(json("kind" to "audio")) }
    Action("Importa cartella") { pick(json("kind" to "folder")) }
    if (state.str("exportPath").isNotEmpty()) Action("Condividi ultima esportazione") { share(state.str("exportPath")) }
    Text("Musica e impostazioni restano salvate sul telefono anche dopo gli aggiornamenti.", color = MaterialTheme.colorScheme.onSurfaceVariant)
    Text("Sonus Android · ${state.str("version", "1.0.11")}", style = MaterialTheme.typography.bodySmall)
}
