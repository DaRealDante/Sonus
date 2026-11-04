package app.sonus.ui

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import app.sonus.data.Library
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** Reads from the library in the background, and again every time the library changes (or a key changes). */
@Composable
fun <T> rememberQuery(initial: T, vararg keys: Any?, query: () -> T): T {
    val version = Library.version
    var value by remember { mutableStateOf(initial) }
    LaunchedEffect(version, *keys) {
        value = withContext(Dispatchers.IO) { query() }
    }
    return value
}
