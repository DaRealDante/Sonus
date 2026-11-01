package app.sonus.core

import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/** Port of resolveColors() from app/ui/theme.py: the full palette from the colours chosen by the user. No Android code here. */
data class Rgb(val r: Int, val g: Int, val b: Int) {
    fun hex(): String = "#%02X%02X%02X".format(r, g, b)
    fun argb(): Long = 0xFF000000L or (r.toLong() shl 16) or (g.toLong() shl 8) or b.toLong()

    companion object {
        /** "#RRGGBB" or "#RGB"; null when the text is not a colour. */
        fun parse(text: String?): Rgb? {
            val value = text?.trim()?.removePrefix("#") ?: return null
            if (!value.all { it in '0'..'9' || it in 'a'..'f' || it in 'A'..'F' }) return null
            return when (value.length) {
                6 -> Rgb(value.substring(0, 2).toInt(16), value.substring(2, 4).toInt(16), value.substring(4, 6).toInt(16))
                3 -> Rgb(value[0].digitToInt(16) * 17, value[1].digitToInt(16) * 17, value[2].digitToInt(16) * 17)
                else -> null
            }
        }
    }
}

data class Palette(
    val accent: String, val accentHover: String, val accentText: String,
    val background: String, val sidebar: String, val panel: String, val elevated: String, val hover: String,
    val text: String, val subtext: String, val muted: String, val rowHover: String, val line: String, val raised: String,
    val accentGlow: String, val accentDim: String,
) {
    fun toMap(): Map<String, String> = linkedMapOf(
        "ACCENT" to accent, "ACCENT_HOVER" to accentHover, "ACCENT_TEXT" to accentText, "BACKGROUND" to background,
        "SIDEBAR" to sidebar, "PANEL" to panel, "ELEVATED" to elevated, "HOVER" to hover, "TEXT" to text, "SUBTEXT" to subtext,
        "MUTED" to muted, "ROW_HOVER" to rowHover, "LINE" to line, "RAISED" to raised, "ACCENT_GLOW" to accentGlow,
        "ACCENT_DIM" to accentDim,
    )

    companion object {
        val DEFAULT_COLORS = mapOf("accent" to "#1ED760", "background" to "#121212", "panel" to "#181818", "sidebar" to "#000000", "text" to "#FFFFFF")

        /** The colour presets of the PC app (same names, same colours). */
        val PRESETS: Map<String, Map<String, String>> = linkedMapOf(
            "Verde (originale)" to emptyMap(),
            "Viola" to mapOf("accent" to "#A970FF"),
            "Blu" to mapOf("accent" to "#3D91F4"),
            "Rosso" to mapOf("accent" to "#F23F42"),
            "Arancio" to mapOf("accent" to "#FF8A1F"),
            "Rosa" to mapOf("accent" to "#FF4FA0"),
            "Mezzanotte" to mapOf("accent" to "#5B8CFF", "background" to "#0F1424", "panel" to "#151B2E", "sidebar" to "#0A0E1A"),
            "Bosco" to mapOf("accent" to "#7BD88F", "background" to "#101A14", "panel" to "#15211A", "sidebar" to "#09110C"),
        )

        private fun mix(first: Rgb, second: Rgb, amount: Double): String = Rgb(
            Math.rint(first.r + (second.r - first.r) * amount).toInt(),
            Math.rint(first.g + (second.g - first.g) * amount).toInt(),
            Math.rint(first.b + (second.b - first.b) * amount).toInt(),
        ).hex()

        private fun luminance(color: Rgb): Double = 0.2126 * color.r / 255.0 + 0.7152 * color.g / 255.0 + 0.0722 * color.b / 255.0

        /** Same result as QColor.lighter(factor) of Qt (works on HSV with 16 bit values). */
        fun lighter(color: Rgb, factor: Int): Rgb {
            if (factor <= 0) return color
            val r = color.r * 257
            val g = color.g * 257
            val b = color.b * 257
            // Qt divides in 32 bit float here: the same steps give the same rounding
            val rf = (r / 65535f).toDouble()
            val gf = (g / 65535f).toDouble()
            val bf = (b / 65535f).toDouble()
            val maxValue = max(rf, max(gf, bf))
            val minValue = min(rf, min(gf, bf))
            val delta = maxValue - minValue
            var value = Math.round(maxValue * 65535.0).toInt()
            var saturation = 0
            var hueHundredths = 65535 // "no hue" (grey)
            if (abs(delta) > 1e-12) {
                saturation = Math.round(delta / maxValue * 65535.0).toInt()
                var hue = when {
                    rf == maxValue -> (gf - bf) / delta
                    gf == maxValue -> 2.0 + (bf - rf) / delta
                    else -> 4.0 + (rf - gf) / delta
                }
                hue *= 60.0
                if (hue < 0.0) hue += 360.0
                hueHundredths = Math.round(hue * 100.0).toInt()
            }
            var newValue = value.toLong() * factor / 100
            var newSaturation = saturation
            if (newValue > 65535) {
                newSaturation -= (newValue - 65535).toInt()
                if (newSaturation < 0) newSaturation = 0
                newValue = 65535
            }
            value = newValue.toInt()
            // HSV -> RGB (16 bit), then to 8 bit
            val (red, green, blue) = if (newSaturation == 0 || hueHundredths == 65535) {
                Triple(value.toDouble(), value.toDouble(), value.toDouble())
            } else {
                val h = if (hueHundredths == 36000) 0.0 else hueHundredths / 6000.0
                val s = newSaturation / 65535.0
                val v = value / 65535.0
                val i = h.toInt()
                val f = h - i
                val p = v * (1 - s)
                val q = v * (1 - s * f)
                val t = v * (1 - s * (1 - f))
                val (rr, gg, bb) = when (i) {
                    0 -> Triple(v, t, p)
                    1 -> Triple(q, v, p)
                    2 -> Triple(p, v, t)
                    3 -> Triple(p, q, v)
                    4 -> Triple(t, p, v)
                    else -> Triple(v, p, q)
                }
                Triple(rr * 65535.0, gg * 65535.0, bb * 65535.0)
            }
            fun to8(sixteen: Double) = (Math.round(sixteen).toInt() / 257.0).roundToInt().coerceIn(0, 255)
            return Rgb(to8(red), to8(green), to8(blue))
        }

        /** Full palette from the (partial) colours chosen by the user: derived shades always stay readable. */
        fun resolve(custom: Map<String, String>?): Palette {
            val chosen = (custom ?: emptyMap()).filter { (key, value) -> key in DEFAULT_COLORS && Rgb.parse(value) != null }
            if (chosen.isEmpty()) {
                return Palette(
                    "#1ED760", "#3BE477", "#000000", "#121212", "#000000", "#181818", "#242424", "#2A2A2A", "#FFFFFF", "#B3B3B3",
                    "#6A6A6A", "#1F1F1F", "#2A2A2A", "#3A3A3A", "#1F3B2C", "#10391F",
                )
            }
            val colors = DEFAULT_COLORS.mapValues { (key, default) -> Rgb.parse(chosen[key] ?: default)!! }
            val background = colors.getValue("background")
            var text = colors.getValue("text")
            if (abs(luminance(text) - luminance(background)) < 0.45) {
                text = if (luminance(background) < 0.5) Rgb(255, 255, 255) else Rgb(0, 0, 0)
            }
            val accent = colors.getValue("accent")
            val panel = colors.getValue("panel")
            return Palette(
                accent = accent.hex(), accentHover = lighter(accent, 115).hex(),
                accentText = if (luminance(accent) > 0.45) "#000000" else "#FFFFFF",
                background = background.hex(), sidebar = colors.getValue("sidebar").hex(), panel = panel.hex(),
                elevated = mix(panel, text, 0.07), hover = mix(panel, text, 0.10),
                text = text.hex(), subtext = mix(text, background, 0.30), muted = mix(text, background, 0.58),
                rowHover = mix(background, text, 0.05), line = mix(background, text, 0.10), raised = mix(panel, text, 0.16),
                accentGlow = mix(background, accent, 0.20), accentDim = mix(background, accent, 0.16),
            )
        }
    }
}
