package it.sonus.mobile

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import org.json.JSONArray
import org.json.JSONObject

typealias Prompt = (String, List<Pair<String, String>>, (Map<String, String>) -> Unit) -> Unit

@Composable fun MiniPlayer(song: JSONObject, state: JSONObject, expand: () -> Unit, toggle: () -> Unit) {
    val tint = songTint(song, state.obj("settings"))
    Column(Modifier.padding(horizontal = 8.dp).background(tint.copy(alpha = .22f), RoundedCornerShape(10.dp)).clickable(onClick = expand).testTag("mini_player")) {
        Row(Modifier.padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
            Artwork(song, Modifier.size(46.dp))
            Column(Modifier.weight(1f).padding(horizontal = 12.dp)) { Text(song.str("title"), fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis); Text(song.str("artist"), color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall, maxLines = 1) }
            IconButton(onClick = toggle) { if (state.flag("loading")) CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp) else Text(if (state.flag("playing")) "Ⅱ" else "▶", fontSize = 25.sp, modifier = Modifier.semantics { contentDescription = "Riproduci o pausa" }) }
        }
        LinearProgressIndicator(progress = { (state.num("position") / state.num("duration", 1.0).coerceAtLeast(1.0)).toFloat().coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth().height(2.dp), trackColor = Color.Transparent)
    }
}

@Composable fun FullPlayer(state: JSONObject, send: Send, go: (String) -> Unit, menu: () -> Unit) {
    val current = state.optJSONObject("current") ?: JSONObject()
    val tint = songTint(current, state.obj("settings"))
    Column(Modifier.fillMaxSize().background(Brush.verticalGradient(listOf(tint.copy(alpha = .3f), MaterialTheme.colorScheme.background))).verticalScroll(rememberScrollState()).padding(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Artwork(current, Modifier.fillMaxWidth().aspectRatio(1f))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) { Text(current.str("title", "Scegli una canzone"), style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold); Text(current.str("artist"), color = MaterialTheme.colorScheme.onSurfaceVariant) }
            IconButton(onClick = { send("favorite", json("id" to current.int("id"))) }) { Text(if (current.flag("favorite")) "♥" else "♡", fontSize = 29.sp, color = MaterialTheme.colorScheme.primary) }
            IconButton(onClick = menu) { Text("⋯", fontSize = 26.sp) }
        }
        val duration = state.num("duration").coerceAtLeast(1.0)
        var seek by remember(state.opt("position")) { mutableFloatStateOf(state.num("position").toFloat().coerceIn(0f, duration.toFloat())) }
        Column {
            Slider(seek, { seek = it }, valueRange = 0f..duration.toFloat(), onValueChangeFinished = { send("seek", json("position" to seek.toLong())) })
            Row(Modifier.fillMaxWidth()) { Text(seconds(seek), color = MaterialTheme.colorScheme.onSurfaceVariant); Spacer(Modifier.weight(1f)); Text(seconds(duration), color = MaterialTheme.colorScheme.onSurfaceVariant) }
        }
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
            IconButton(onClick = { send("shuffle", json()) }) { Text("⤨", fontSize = 28.sp, color = if (state.flag("shuffle")) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface, modifier = Modifier.semantics { contentDescription = "Ordine casuale" }) }
            IconButton(onClick = { send("previous", json()) }) { Text("|◀", fontSize = 23.sp, modifier = Modifier.semantics { contentDescription = "Brano precedente" }) }
            FilledIconButton(onClick = { send("toggle", json()) }, modifier = Modifier.size(72.dp)) { Text(if (state.flag("playing")) "Ⅱ" else "▶", fontSize = 32.sp, modifier = Modifier.semantics { contentDescription = "Riproduci o pausa" }) }
            IconButton(onClick = { send("next", json()) }) { Text("▶|", fontSize = 23.sp, modifier = Modifier.semantics { contentDescription = "Brano successivo" }) }
            IconButton(onClick = { send("repeat", json()) }) { Text(if (state.int("repeat") == 2) "↻₁" else "↻", fontSize = 28.sp, color = if (state.int("repeat") != 0) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface, modifier = Modifier.semantics { contentDescription = "Ripetizione" }) }
        }
        if (state.obj("settings").flag("fxVisualizer", true)) Spectrum(state)
        ValueSlider("Volume", state.num("volume", 70.0).toFloat(), 0f..100f, "${state.int("volume", 70)}%") { send("volume", json("value" to it.toInt())) }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { Action(if (state.flag("muted")) "Riattiva audio" else "Silenzia") { send("mute", json()) }; Action("Condividi ascolto") { go("Stanza") } }
        listOf("Coda", "Effetti", "Equalizzatore", "Loop e taglio", "Testi", "Video", "Stanza").forEach { title ->
            ElevatedCard(onClick = { go(title) }, modifier = Modifier.fillMaxWidth()) { Row(Modifier.fillMaxWidth().padding(18.dp)) { Text(title, Modifier.weight(1f), fontWeight = FontWeight.SemiBold); Text("›") } }
        }
    }
}

@Composable private fun Spectrum(state: JSONObject) {
    val bins = state.optJSONArray("spectrum") ?: JSONArray()
    val color = MaterialTheme.colorScheme.primary
    Canvas(Modifier.fillMaxWidth().height(42.dp)) {
        val count = bins.length().coerceAtMost(32)
        if (count > 0) for (i in 0 until count) {
            val h = bins.optDouble(i).coerceIn(0.0, 1.0).toFloat() * size.height
            drawLine(color.copy(alpha = .65f), Offset((i + .5f) * size.width / count, size.height), Offset((i + .5f) * size.width / count, size.height - h), size.width / count * .58f)
        }
    }
}

@Composable fun EffectsScreen(state: JSONObject, send: Send, export: (String) -> Unit) = ScrollPage {
    val effects = state.obj("effects")
    fun set(key: String, value: Any) { send("effects", json("values" to JSONObject(effects.toString()).put(key, value))) }
    Title("Il tuo suono", "Gli effetti si applicano a tutti i brani.")
    LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        items(listOf("Normale", "Slowed + Reverb", "Sped up", "Nightcore")) { name -> Action(name) {
            val values = when (name) {
                "Slowed + Reverb" -> json("rate" to .85, "keepPitch" to false, "reverbWet" to .45, "reverbSize" to 3.0)
                "Sped up" -> json("rate" to 1.25, "keepPitch" to false, "reverbWet" to 0.0)
                "Nightcore" -> json("rate" to 1.35, "keepPitch" to false, "reverbWet" to .1, "reverbSize" to 1.2)
                else -> json("rate" to 1.0, "keepPitch" to true, "reverbWet" to 0.0)
            }
            values.put("bassBoost", effects.num("bassBoost")); send("effects", json("values" to values))
        } }
    }
    ValueSlider("Velocità", effects.num("rate", 1.0).toFloat(), .5f..2f, "%.2f×".format(effects.num("rate", 1.0))) { set("rate", it) }
    ToggleRow("Mantieni il pitch · voce naturale", effects.flag("keepPitch", true)) { set("keepPitch", it) }
    ValueSlider("Bass boost", effects.num("bassBoost").toFloat(), 0f..1f, "+%.1f dB".format(effects.num("bassBoost") * 12)) { set("bassBoost", it) }
    ValueSlider("Riverbero", effects.num("reverbWet").toFloat(), 0f..1f, "${(effects.num("reverbWet") * 100).toInt()}%") { set("reverbWet", it) }
    ValueSlider("Grandezza stanza", effects.num("reverbSize", 1.8).toFloat(), .2f..6f, "%.1f s".format(effects.num("reverbSize", 1.8))) { set("reverbSize", it) }
    if (state.obj("room").str("code").isNotEmpty()) Text("Velocità e riverbero sono condivisi nella stanza. Il bass boost resta personale.", color = MaterialTheme.colorScheme.onSurfaceVariant)
    Action("Ripristina effetti") { send("effects", json("values" to json("rate" to 1, "keepPitch" to true, "reverbWet" to 0, "reverbSize" to 1.8, "bassBoost" to 0))) }
    Action("Salva come nuova canzone", state.optJSONObject("current") != null) { export(state.obj("current").str("title") + " (effetti)") }
}

@Composable fun EqualizerScreen(state: JSONObject, send: Send, askName: ((String) -> Unit) -> Unit) = ScrollPage {
    val eq = state.obj("eq")
    val gains = eq.optJSONArray("gains") ?: JSONArray(List(10) { 0 })
    fun update(values: JSONObject) { send("eq", json("values" to values)) }
    ToggleRow("Equalizzatore attivo", eq.flag("enabled")) { update(json("enabled" to it)) }
    Text("Preset", style = MaterialTheme.typography.titleLarge)
    val presets = eq.optJSONObject("presets") ?: JSONObject()
    val custom = eq.optJSONObject("customPresets") ?: JSONObject()
    LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        items((presets.keys().asSequence().toList() + custom.keys().asSequence().toList()).distinct().ifEmpty { listOf("Piatto", "Bass Boost", "Rock", "Pop", "Voce", "Elettronica", "Jazz", "Classica") }) { name -> Action(name) { update(json("preset" to name)) } }
    }
    val color = MaterialTheme.colorScheme.primary
    Canvas(Modifier.fillMaxWidth().height(100.dp).background(MaterialTheme.colorScheme.surface, RoundedCornerShape(12.dp))) {
        drawLine(Color.Gray.copy(alpha = .4f), Offset(0f, size.height / 2), Offset(size.width, size.height / 2))
        for (i in 0 until 9) drawLine(color, Offset(i * size.width / 9, size.height / 2 - gains.optDouble(i).toFloat() / 24 * size.height), Offset((i + 1) * size.width / 9, size.height / 2 - gains.optDouble(i + 1).toFloat() / 24 * size.height), 3.dp.toPx())
    }
    ValueSlider("Preamp", eq.num("preamp").toFloat(), -12f..12f, "%.1f dB".format(eq.num("preamp"))) { update(json("preamp" to it)) }
    listOf("32 Hz", "64 Hz", "125 Hz", "250 Hz", "500 Hz", "1 kHz", "2 kHz", "4 kHz", "8 kHz", "16 kHz").forEachIndexed { index, label ->
        ValueSlider(label, gains.optDouble(index).toFloat(), -12f..12f, "%.1f dB".format(gains.optDouble(index))) { value -> val changed = JSONArray(gains.toString()); changed.put(index, value); update(json("gains" to changed)) }
    }
    listOf("Bassi" to (0..3), "Medi" to (4..6), "Alti" to (7..9)).forEach { (label, bands) ->
        var macro by remember { mutableFloatStateOf(0f) }
        ValueSlider(label, macro, -12f..12f, "%.1f dB".format(macro)) { value -> val delta = value - macro; macro = value; val changed = JSONArray(gains.toString()); bands.forEach { changed.put(it, (gains.optDouble(it) + delta).coerceIn(-12.0, 12.0)) }; update(json("gains" to changed)) }
    }
    ValueSlider("Bilanciamento L / R", eq.num("balance").toFloat(), -100f..100f, if (eq.int("balance") == 0) "Centro" else eq.int("balance").toString()) { update(json("balance" to it.toInt())) }
    Action("Salva preset personale") { askName { update(json("savePreset" to it)) } }
    Action("Elimina preset personale", custom.has(eq.str("preset"))) { update(json("deletePreset" to eq.str("preset"))) }
    Action("Ripristina") { update(json("preset" to "Piatto", "preamp" to 0, "balance" to 0)) }
}

@Composable fun EditAudioScreen(state: JSONObject, send: Send, prompt: Prompt) = ScrollPage {
    val current = state.optJSONObject("current")
    if (current == null) { Text("Avvia un brano per creare un loop o tagliare l'audio."); return@ScrollPage }
    var a by remember(current.int("id")) { mutableStateOf("0.0") }
    var b by remember(current.int("id")) { mutableStateOf((state.num("duration") / 1000).toString()) }
    var fadeIn by remember { mutableStateOf("0") }
    var fadeOut by remember { mutableStateOf("0") }
    var remove by remember { mutableStateOf(false) }
    var replace by remember { mutableStateOf(false) }
    LaunchedEffect(current.int("id")) { send("waveform", json("id" to current.int("id"))) }
    Title(current.str("title"), "Seleziona l'inizio A e la fine B.")
    val waveform = state.optJSONArray("waveform") ?: JSONArray()
    val color = MaterialTheme.colorScheme.primary
    Canvas(Modifier.fillMaxWidth().height(112.dp).background(MaterialTheme.colorScheme.surface, RoundedCornerShape(8.dp)).pointerInput(state.num("duration")) { detectTapGestures { pos -> send("seek", json("position" to (pos.x / size.width * state.num("duration")).toLong())) } }) {
        val count = waveform.length()
        for (i in 0 until count) {
            val entry = waveform.opt(i)
            val value = when (entry) { is Number -> kotlin.math.abs(entry.toFloat()); is JSONArray -> kotlin.math.abs(entry.optDouble(0)).toFloat(); else -> .0f }.coerceIn(0f, 1f)
            drawLine(color, Offset(i * size.width / count, size.height / 2 - value * size.height / 2), Offset(i * size.width / count, size.height / 2 + value * size.height / 2), (size.width / count).coerceAtLeast(1f))
        }
    }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { OutlinedTextField(a, { a = it }, Modifier.weight(1f), label = { Text("Inizio A · secondi") }); OutlinedTextField(b, { b = it }, Modifier.weight(1f), label = { Text("Fine B · secondi") }) }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Action("A = ora") { a = "%.3f".format(java.util.Locale.US, state.num("position") / 1000) }
        Action("B = ora") { b = "%.3f".format(java.util.Locale.US, state.num("position") / 1000) }
        Action("Anteprima") { send("seek", json("position" to ((a.toDoubleOrNull() ?: 0.0) * 1000).toLong())); send("loop_select", json("loop" to json("startMs" to ((a.toDoubleOrNull() ?: 0.0) * 1000).toLong(), "endMs" to ((b.toDoubleOrNull() ?: 0.0) * 1000).toLong()))); send("play_pause", json("playing" to true)) }
    }
    Action("Salva loop A-B") { prompt("Salva loop", listOf("Nome" to "Loop")) { send("loop_save", json("id" to current.int("id"), "name" to it["Nome"], "startMs" to ((a.toDoubleOrNull() ?: 0.0) * 1000).toLong(), "endMs" to ((b.toDoubleOrNull() ?: 0.0) * 1000).toLong())) } }
    Action("Disattiva loop") { send("loop_clear", json()) }
    state.list("loops").forEach { loop -> Row(verticalAlignment = Alignment.CenterVertically) {
        TextButton(onClick = { send("loop_select", json("loop" to loop)) }, Modifier.weight(1f)) { Text(loop.str("name") + " · " + seconds(loop.num("startMs")) + " – " + seconds(loop.num("endMs"))) }
        IconButton(onClick = { prompt("Modifica loop", listOf("Nome" to loop.str("name"), "Inizio (s)" to (loop.num("startMs") / 1000).toString(), "Fine (s)" to (loop.num("endMs") / 1000).toString())) { send("loop_save", json("id" to current.int("id"), "loopId" to loop.int("id"), "name" to it["Nome"], "startMs" to ((it["Inizio (s)"]?.toDoubleOrNull() ?: 0.0) * 1000).toLong(), "endMs" to ((it["Fine (s)"]?.toDoubleOrNull() ?: 0.0) * 1000).toLong())) } }) { Text("✎") }
        IconButton(onClick = { send("loop_delete", json("loopId" to loop.int("id"))) }) { Text("×") }
    } }
    HorizontalDivider()
    Text("Taglia audio", style = MaterialTheme.typography.titleLarge)
    ToggleRow("Rimuovi la selezione A-B", remove) { remove = it }
    ToggleRow("Sostituisci il file originale", replace) { replace = it }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { OutlinedTextField(fadeIn, { fadeIn = it }, Modifier.weight(1f), label = { Text("Fade in · ms") }); OutlinedTextField(fadeOut, { fadeOut = it }, Modifier.weight(1f), label = { Text("Fade out · ms") }) }
    Action("Salva taglio") { prompt("Salva taglio", listOf("Titolo" to current.str("title") + " (taglio)")) { send("cut", json("id" to current.int("id"), "startMs" to ((a.toDoubleOrNull() ?: 0.0) * 1000).toLong(), "endMs" to ((b.toDoubleOrNull() ?: 0.0) * 1000).toLong(), "removeSelection" to remove, "fadeInMs" to (fadeIn.toIntOrNull() ?: 0), "fadeOutMs" to (fadeOut.toIntOrNull() ?: 0), "title" to it["Titolo"], "replace" to replace)) } }
}

@Composable fun LyricsScreen(state: JSONObject, send: Send, prompt: Prompt) = ScrollPage {
    val song = state.optJSONObject("current")
    if (song == null) { Text("Avvia un brano per vedere i testi."); return@ScrollPage }
    var query by remember(song.int("id")) { mutableStateOf(song.str("title") + " " + song.str("artist")) }
    Title(song.str("title"), song.str("artist"))
    val synced = remember(song.str("syncedLyrics")) {
        Regex("\\[(\\d+):(\\d+(?:\\.\\d+)?)\\]([^\\n]*)").findAll(song.str("syncedLyrics")).map { ((it.groupValues[1].toLong() * 60 + it.groupValues[2].toDouble()) * 1000).toLong() to it.groupValues[3] }.toList()
    }
    if (synced.isNotEmpty()) {
        val position = state.num("position").toLong()
        val active = synced.indexOfLast { it.first <= position }
        synced.forEachIndexed { index, (ms, text) -> Text(text.ifBlank { "♪" }, fontSize = 25.sp, fontWeight = FontWeight.Bold, color = if (index == active) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface.copy(alpha = .4f), modifier = Modifier.fillMaxWidth().clickable { send("seek", json("position" to ms)) }.padding(vertical = 8.dp)) }
    } else Text(song.str("lyrics", "Testo non ancora disponibile."), style = MaterialTheme.typography.bodyLarge)
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { Action("Cerca automaticamente") { send("lyrics_fetch", json("id" to song.int("id"), "force" to true)) }; Action("Modifica") { prompt("Modifica testo", listOf("Testo" to song.str("lyrics"), "LRC sincronizzato" to song.str("syncedLyrics"))) { send("lyrics_set", json("id" to song.int("id"), "plain" to it["Testo"], "synced" to it["LRC sincronizzato"])) } } }
    ToggleRow("Testo automatico per questo brano", song.flag("lyricsAuto", true)) { send("song_edit", json("id" to song.int("id"), "fields" to json("lyricsAuto" to if (it) 1 else 0))) }
    Action("Rimuovi testo") { send("lyrics_remove", json("id" to song.int("id"))) }
    OutlinedTextField(query, { query = it }, Modifier.fillMaxWidth(), label = { Text("Cerca un testo diverso") })
    Action("Cerca testi") { send("lyrics_search", json("query" to query)) }
    state.list("lyricsResults").forEach { result -> ElevatedCard(onClick = { send("lyrics_set", json("id" to song.int("id"), "plain" to result.str("plain", result.str("plainLyrics")), "synced" to result.str("synced", result.str("syncedLyrics")), "adaptToCut" to true)) }) { Column(Modifier.padding(16.dp)) { Text(result.str("name", result.str("trackName", result.str("title")))); Text(result.str("artistName", result.str("artist")), color = MaterialTheme.colorScheme.onSurfaceVariant) } } }
}
