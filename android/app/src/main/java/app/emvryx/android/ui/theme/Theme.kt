package app.emvryx.android.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.sp

// The website's dark colours (web/index.html) with the violet accent (web/vryx.css)
object Emvryx {
    val bg = Color(0xFF07080D)
    val side = Color(0xFF0A0B11)
    val surface = Color(0xFF0F1119)
    val surface2 = Color(0xFF161926)
    val line = Color(0xFF232739)
    val text = Color(0xFFEEF0F6)
    val muted = Color(0xFF9AA3BC)
    val accent = Color(0xFF8B5CF6)
    val accentText = Color(0xFFB8A1FF)
    val danger = Color(0xFFF87171)
}

private val colors = darkColorScheme(
    primary = Emvryx.accent,
    onPrimary = Color.White,
    primaryContainer = Emvryx.surface2,
    onPrimaryContainer = Emvryx.accentText,
    secondary = Emvryx.accentText,
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

private val type = Typography().run {
    copy(
        bodyLarge = bodyLarge.copy(fontSize = 16.sp, lineHeight = 24.sp),
        titleMedium = titleMedium.copy(fontSize = 17.sp),
    )
}

@Composable
fun EmvryxTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = colors, typography = type, content = content)
}

val Mono = TextStyle(fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace, fontSize = 14.sp, lineHeight = 20.sp)
