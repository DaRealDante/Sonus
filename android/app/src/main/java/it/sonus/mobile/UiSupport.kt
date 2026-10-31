package it.sonus.mobile

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

fun JSONObject.str(key: String, default: String = ""): String = if (isNull(key)) default else optString(key, default)
fun JSONObject.int(key: String, default: Int = 0) = optInt(key, default)
fun JSONObject.num(key: String, default: Double = 0.0) = optDouble(key, default)
fun JSONObject.flag(key: String, default: Boolean = false): Boolean = when (val value = opt(key)) { is Boolean -> value; is Number -> value.toInt() != 0; is String -> value.equals("true", true) || value == "1"; else -> default }
fun JSONObject.obj(key: String) = optJSONObject(key) ?: JSONObject()
fun JSONObject.list(key: String): List<JSONObject> = (optJSONArray(key) ?: JSONArray()).objects()
fun JSONArray.objects(): List<JSONObject> = (0 until length()).mapNotNull { optJSONObject(it) }
fun json(vararg pairs: Pair<String, Any?>): JSONObject = JSONObject().apply { pairs.forEach { (key, value) -> put(key, value ?: JSONObject.NULL) } }
fun seconds(ms: Number): String { val total = ms.toLong().coerceAtLeast(0) / 1000; return "%d:%02d".format(total / 60, total % 60) }
fun ids(songs: List<JSONObject>) = JSONArray(songs.map { it.int("id") })
typealias Send = (String, JSONObject) -> Unit

@Composable fun SonusTheme(settings: JSONObject = JSONObject(), content: @Composable () -> Unit) {
    val colors = settings.obj("themeColors")
    fun color(key: String, fallback: String) = runCatching { Color(android.graphics.Color.parseColor(colors.str(key, fallback))) }.getOrDefault(Color(android.graphics.Color.parseColor(fallback)))
    MaterialTheme(colorScheme = darkColorScheme(primary = color("accent", "#1ED760"), onPrimary = Color(0xFF07140A), background = color("background", "#090B0E"), surface = color("panel", "#15191E"), surfaceVariant = color("sidebar", "#21262D"), onSurface = color("text", "#F5F7F8"), onBackground = color("text", "#F5F7F8"), onSurfaceVariant = Color(0xFFA5ADB8)), content = content)
}

@Composable fun Artwork(song: JSONObject, modifier: Modifier = Modifier.size(52.dp)) {
    val cover = song.str("cover").ifEmpty { song.str("image").ifEmpty { song.str("thumbnail") } }
    Box(modifier.clip(RoundedCornerShape(8.dp)).background(MaterialTheme.colorScheme.surfaceVariant), contentAlignment = Alignment.Center) {
        if (cover.isNotEmpty()) AsyncImage(model = if (cover.startsWith("http")) cover else File(cover), contentDescription = null, modifier = Modifier.fillMaxSize(), contentScale = ContentScale.Crop)
        else Text("♫", color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.headlineMedium)
    }
}

@Composable fun Title(text: String, subtitle: String = "") {
    Column(Modifier.padding(vertical = 10.dp)) {
        Text(text, style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
        if (subtitle.isNotEmpty()) Text(subtitle, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodyMedium)
    }
}

@Composable fun Action(label: String, enabled: Boolean = true, click: () -> Unit) {
    FilledTonalButton(onClick = click, enabled = enabled, modifier = Modifier.defaultMinSize(minHeight = 48.dp)) { Text(label) }
}

@Composable fun ToggleRow(label: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().heightIn(min = 56.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(label, Modifier.weight(1f).padding(end = 12.dp))
        Switch(checked, onCheckedChange = onChange)
    }
}

@Composable fun ValueSlider(label: String, value: Float, range: ClosedFloatingPointRange<Float>, display: String = "%.1f".format(value), onDone: (Float) -> Unit) {
    var draft by remember(value) { mutableFloatStateOf(value.coerceIn(range)) }
    Row { Text(label, Modifier.weight(1f)); Text(display, color = MaterialTheme.colorScheme.primary) }
    Slider(value = draft, onValueChange = { draft = it }, valueRange = range, onValueChangeFinished = { onDone(draft) })
}
