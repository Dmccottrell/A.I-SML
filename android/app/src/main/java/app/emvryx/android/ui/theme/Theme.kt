package app.emvryx.android.ui.theme

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.tween
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.ExperimentalTextApi
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import app.emvryx.android.R

// The PWA's dark colours (web/index.html :root) and each model's own palette (web/js/core.js MODEL). The app follows the
// chosen model the way the website does: Flare is orange-red, Solstice gold, Apogee ice blue, Equinox white; before a model
// is known (sign-in, "off") it is the Emvryx amber.
object Emvryx {
    val bg = Color(0xFF07080D)
    val side = Color(0xFF0A0B11)
    val surface = Color(0xFF0F1119)
    val surface2 = Color(0xFF161926)
    val line = Color(0xFF232739)
    val text = Color(0xFFEEF0F6)
    val muted = Color(0xFF9AA3BC)
    val danger = Color(0xFFF87171)
}

@Immutable
data class Palette(
    val accent: Color,
    val onAccent: Color,
    val accentText: Color,
    val sun: Color,
    val core: Color,
    val glow: Color,
)

object Palettes {
    val brand = Palette(Color(0xFFF5A524), Color(0xFF1A1204), Color(0xFFF5A524), Color(0xFFF5A524), Color(0xFFFFD27A), Color(0x24F5A524))
    private val ember = Palette(Color(0xFFC8431F), Color(0xFFFFFFFF), Color(0xFFF0734F), Color(0xFFC8431F), Color(0xFFFFB05A), Color(0x33C8431F))
    private val flare = Palette(Color(0xFFFF4B1F), Color(0xFF1A0500), Color(0xFFFF6B3D), Color(0xFFFF4B1F), Color(0xFFFFF3E6), Color(0x33FF4B1F))
    private val equinox = Palette(Color(0xFFEEF0F6), Color(0xFF07080D), Color(0xFFEEF0F6), Color(0xFFEEF0F6), Color(0xFF07080D), Color(0x14EEF0F6))
    private val solstice = Palette(Color(0xFFF2A60C), Color(0xFF1F1400), Color(0xFFFFBE3B), Color(0xFFF2A60C), Color(0xFFFFE7A0), Color(0x2EF2A60C))
    private val apogee = Palette(Color(0xFFA8D1F5), Color(0xFF06121F), Color(0xFFB5D8F8), Color(0xFFA8D1F5), Color(0xFFF4F9FF), Color(0x26A8D1F5))

    /** The palette for a model by its name (Flare, Solstice...); unknown names get Flare's, as on the website. */
    fun forModel(name: String?): Palette = when (name?.lowercase()) {
        null, "" -> brand
        "ember" -> ember
        "equinox" -> equinox
        "solstice" -> solstice
        "apogee" -> apogee
        else -> flare
    }
}

val LocalPalette = staticCompositionLocalOf { Palettes.brand }

// one variable font file per family; each weight is a setting on it (Android 8+)
@OptIn(ExperimentalTextApi::class)
private val Sora = FontFamily(
    listOf(500, 600, 700).map { w ->
        Font(R.font.sora, FontWeight(w), variationSettings = FontVariation.Settings(FontVariation.weight(w)))
    },
)
@OptIn(ExperimentalTextApi::class)
private val DmSans = FontFamily(
    listOf(400, 500, 600, 700).map { w ->
        Font(R.font.dm_sans, FontWeight(w), variationSettings = FontVariation.Settings(FontVariation.weight(w)))
    },
)

/** Sora for headings and titles, as the PWA does */
val Heading = Sora

private val type = Typography().run {
    copy(
        displaySmall = displaySmall.copy(fontFamily = Sora),
        headlineLarge = headlineLarge.copy(fontFamily = Sora, fontWeight = FontWeight.SemiBold),
        headlineMedium = headlineMedium.copy(fontFamily = Sora, fontWeight = FontWeight.SemiBold),
        headlineSmall = headlineSmall.copy(fontFamily = Sora, fontWeight = FontWeight.SemiBold),
        titleLarge = titleLarge.copy(fontFamily = Sora, fontWeight = FontWeight.SemiBold),
        titleMedium = titleMedium.copy(fontFamily = DmSans, fontWeight = FontWeight.SemiBold, fontSize = 16.sp),
        titleSmall = titleSmall.copy(fontFamily = DmSans),
        bodyLarge = bodyLarge.copy(fontFamily = DmSans, fontSize = 16.sp, lineHeight = 24.sp, letterSpacing = 0.sp),
        bodyMedium = bodyMedium.copy(fontFamily = DmSans, fontSize = 14.sp, lineHeight = 21.sp, letterSpacing = 0.sp),
        bodySmall = bodySmall.copy(fontFamily = DmSans, fontSize = 13.sp, letterSpacing = 0.sp),
        labelLarge = labelLarge.copy(fontFamily = DmSans, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.sp),
        labelMedium = labelMedium.copy(fontFamily = DmSans, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.sp),
        labelSmall = labelSmall.copy(fontFamily = DmSans),
    )
}

/** [model] is the chosen model's name, or null for the Emvryx amber. Colours ease from one model to the next, like the website. */
@Composable
fun EmvryxTheme(model: String? = null, content: @Composable () -> Unit) {
    val target = Palettes.forModel(model)
    val ease = tween<Color>(600)
    val accent by animateColorAsState(target.accent, ease, label = "accent")
    val onAccent by animateColorAsState(target.onAccent, ease, label = "onAccent")
    val accentText by animateColorAsState(target.accentText, ease, label = "accentText")
    val sun by animateColorAsState(target.sun, ease, label = "sun")
    val core by animateColorAsState(target.core, ease, label = "core")
    val glow by animateColorAsState(target.glow, ease, label = "glow")
    val p = Palette(accent, onAccent, accentText, sun, core, glow)
    val colors = darkColorScheme(
        primary = p.accent,
        onPrimary = p.onAccent,
        primaryContainer = Emvryx.surface2,
        onPrimaryContainer = p.accentText,
        secondary = p.accentText,
        background = Emvryx.bg,
        onBackground = Emvryx.text,
        surface = Emvryx.bg,
        onSurface = Emvryx.text,
        surfaceVariant = Emvryx.surface,
        onSurfaceVariant = Emvryx.muted,
        surfaceContainer = Emvryx.surface,
        surfaceContainerHigh = Emvryx.surface2,
        surfaceContainerHighest = Emvryx.surface2,
        surfaceContainerLow = Emvryx.side,
        outline = Emvryx.line,
        outlineVariant = Emvryx.line,
        error = Emvryx.danger,
    )
    CompositionLocalProvider(LocalPalette provides p) {
        MaterialTheme(colorScheme = colors, typography = type, content = content)
    }
}

val Mono = TextStyle(fontFamily = FontFamily.Monospace, fontSize = 14.sp, lineHeight = 20.sp)
