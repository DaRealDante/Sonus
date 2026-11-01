package app.sonus.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.remember
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import app.sonus.core.Palette
import app.sonus.core.Rgb

private fun String.toColor(): Color = Color(Rgb.parse(this)!!.argb())

/** The colours of the PC app (theme.py), ready for Compose. */
class SonusColors(palette: Palette) {
    val accent = palette.accent.toColor()
    val accentHover = palette.accentHover.toColor()
    val accentText = palette.accentText.toColor()
    val background = palette.background.toColor()
    val sidebar = palette.sidebar.toColor()
    val panel = palette.panel.toColor()
    val elevated = palette.elevated.toColor()
    val hover = palette.hover.toColor()
    val text = palette.text.toColor()
    val subtext = palette.subtext.toColor()
    val muted = palette.muted.toColor()
    val rowHover = palette.rowHover.toColor()
    val line = palette.line.toColor()
    val raised = palette.raised.toColor()
    val accentGlow = palette.accentGlow.toColor()
    val accentDim = palette.accentDim.toColor()
}

val LocalSonusColors = staticCompositionLocalOf { SonusColors(Palette.resolve(null)) }

@Composable
fun SonusTheme(palette: Palette = Palette.resolve(null), content: @Composable () -> Unit) {
    val colors = remember(palette) { SonusColors(palette) }
    val scheme = darkColorScheme(
        primary = colors.accent,
        onPrimary = colors.accentText,
        secondaryContainer = colors.accentDim,
        onSecondaryContainer = colors.accent,
        background = colors.background,
        onBackground = colors.text,
        surface = colors.panel,
        onSurface = colors.text,
        surfaceVariant = colors.elevated,
        onSurfaceVariant = colors.subtext,
        outline = colors.line,
        outlineVariant = colors.line,
    )
    CompositionLocalProvider(LocalSonusColors provides colors) {
        MaterialTheme(colorScheme = scheme, content = content)
    }
}
