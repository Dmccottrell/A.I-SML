package app.emvryx.android.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.emvryx.android.ui.theme.Emvryx
import app.emvryx.android.ui.theme.LocalPalette

// Kit.kt: a small toolkit of reusable screen pieces (button, chip, text field, background glows) used by the sign-in, chat and other screens.
// The PWA is the website version of the app (web/index.html). Its CSS class names (.btn, .btn.ghost, .chip, .field) are used here
// as the names so the phone app and the site look the same. A "@Composable" function is a Compose function: Android's way of
// describing a piece of screen as code; a "Modifier" is a chain of tweaks (size, padding, colour, click) applied to it.
// Colours come from ui/theme/Theme.kt: LocalPalette is the current model's accent colours, Emvryx holds the fixed page colours.

/**
 * .btn: the accent button. [ghost] is .btn.ghost, a line round a transparent button.
 * [text] is the label, [onClick] runs on tap, [enabled] = false fades it and ignores taps, and [content] (optional) replaces
 * the plain text label with your own Compose UI (for example a spinner).
 */
@Composable
fun PwaButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    ghost: Boolean = false,
    content: (@Composable () -> Unit)? = null,
) {
    // The current palette (colours chosen by the active model).
    val p = LocalPalette.current
    // Corner radius 12 dp (dp = density-independent pixels: the same physical size on any screen).
    val shape = RoundedCornerShape(12.dp)
    Box(
        modifier
            // Never shorter than 48 dp, the usual minimum comfortable size for a finger tap.
            .heightIn(min = 48.dp)
            // A disabled button is drawn faded (45 percent opaque).
            .alpha(if (enabled) 1f else 0.45f)
            // Cut everything drawn after this to the rounded shape, so the fill and the tap ripple do not spill past the corners.
            .clip(shape)
            // Ghost = just an outline; normal = filled with the accent colour.
            .then(if (ghost) Modifier.border(1.dp, Emvryx.line, shape) else Modifier.background(p.accent))
            // Make the whole box tappable (does nothing when disabled).
            .clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = 18.dp),
        contentAlignment = Alignment.Center,
    ) {
        // Set the default text colour for whatever is drawn inside: normal text on a ghost button, the "on accent" colour (readable on the fill) otherwise.
        CompositionLocalProvider(LocalContentColor provides if (ghost) Emvryx.text else p.onAccent) {
            // Draw the custom content if there is some; otherwise (the ?: "else") draw the plain label.
            content?.invoke() ?: Text(text, fontWeight = FontWeight.SemiBold, fontSize = 16.sp)
        }
    }
}

/**
 * .chip: a small rounded button with a line round it (Copy, Regenerate).
 * Takes the label [text] and the [onClick] action. In the "modern" look it has a soft fill instead of an outline.
 */
@Composable
fun Chip(text: String, onClick: () -> Unit, modifier: Modifier = Modifier) {
    Box(
        modifier
            .heightIn(min = 36.dp)
            // A radius far larger than the height makes a pill shape.
            .clip(RoundedCornerShape(999.dp))
            .then(if (Emvryx.modern) Modifier.background(Emvryx.surface2.copy(alpha = 0.55f))    // modern: a soft fill, no outline
                  else Modifier.border(1.dp, Emvryx.line, RoundedCornerShape(999.dp)))
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 6.dp),
        contentAlignment = Alignment.Center,
    ) { Text(text, color = Emvryx.muted, fontSize = 14.sp) }
}

/**
 * .field: a label above a rounded box; the box takes the accent outline while typing. [trailing] sits at the right (Show).
 * [value] is the current text and [onChange] gets the new text on every key press (the caller owns the state).
 * [hidden] shows dots instead of letters (passwords). [keyboard] and [actions] choose the keyboard type and what the Enter key does.
 */
@Composable
fun Field(
    label: String,
    value: String,
    onChange: (String) -> Unit,
    placeholder: String = "",
    hidden: Boolean = false,
    keyboard: KeyboardOptions = KeyboardOptions.Default,
    actions: KeyboardActions = KeyboardActions.Default,
    trailing: (@Composable () -> Unit)? = null,
) {
    val p = LocalPalette.current
    // focused remembers whether the user is typing in this box. remember keeps the value between redraws; mutableStateOf makes Compose redraw when it changes.
    var focused by remember { mutableStateOf(false) }
    Column {
        Text(label, fontWeight = FontWeight.SemiBold, fontSize = 14.sp, modifier = Modifier.padding(bottom = 6.dp))
        val shape = RoundedCornerShape(12.dp)
        Row(
            // The box: full width, rounded, dark fill, and a border that is thicker and accent coloured while it has focus.
            // With a trailing item the right padding is smaller so that item sits close to the edge.
            Modifier.fillMaxWidth().heightIn(min = 48.dp).clip(shape).background(Emvryx.surface)
                .border(if (focused) 2.dp else 1.dp, if (focused) p.accent else Emvryx.line, shape)
                .padding(start = 14.dp, end = if (trailing != null) 6.dp else 14.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(Modifier.weight(1f).padding(vertical = 12.dp)) {
                // Show the grey hint text only while nothing is typed; the real text input is drawn on top of it.
                if (value.isEmpty()) Text(placeholder, color = Emvryx.muted, fontSize = 16.sp)
                BasicTextField(
                    // BasicTextField is Compose's bare text input (no built-in styling). onFocusChanged keeps [focused] up to date.
                    value, onChange, Modifier.fillMaxWidth().onFocusChanged { focused = it.isFocused },
                    singleLine = true,
                    textStyle = MaterialTheme.typography.bodyLarge.copy(color = Emvryx.text),
                    cursorBrush = SolidColor(p.accent),
                    // For passwords, show dots instead of the characters.
                    visualTransformation = if (hidden) androidx.compose.ui.text.input.PasswordVisualTransformation() else VisualTransformation.None,
                    keyboardOptions = keyboard,
                    keyboardActions = actions,
                )
            }
            // Draw the optional right-hand item (for example the Show button), if one was given.
            trailing?.invoke()
        }
    }
}

// (The soft accent glow the PWA puts behind its pages is the accentWash function at the bottom of this file.)
/** The modern look's colours, all made from the model's accent as web/modern.css does: an edge a little tinted, a soft fill, a halo */
object Look {
    // The outline colour: the normal line colour mixed 22 percent of the way toward the accent (lerp = blend between two colours).
    fun edge(accent: Color) = androidx.compose.ui.graphics.lerp(Emvryx.line, accent, 0.22f)
    // A faint fill: the accent at 12 percent opacity.
    fun soft(accent: Color) = accent.copy(alpha = 0.12f)
    // A stronger, glow-like colour: the accent at 38 percent opacity.
    fun halo(accent: Color) = accent.copy(alpha = 0.38f)
    /** The send and new-chat buttons: the accent a little lighter top left, a little darker bottom right */
    fun shine(accent: Color) = Brush.linearGradient(
        0f to androidx.compose.ui.graphics.lerp(accent, Color.White, 0.08f),
        0.55f to accent,
        1f to androidx.compose.ui.graphics.lerp(accent, Color.Black, 0.2f),
    )
}

/**
 * body.ml's background: the accent glowing in from the top right and, fainter, the bottom left.
 * Used by the "modern" look. A radial gradient is a colour that fades out evenly in a circle from a centre point.
 */
fun Modifier.modernGlow(accent: Color) = drawBehind {
    // drawBehind lets us paint on the canvas behind the content. size is the width and height of the area in pixels.
    val w = size.width
    val h = size.height
    // Big glow centred just above the top-right corner (78 percent across, 8 percent above the top); its radius is 60 percent of the longer side.
    drawRect(Brush.radialGradient(listOf(accent.copy(alpha = 0.20f), Color.Transparent), center = Offset(w * 0.78f, -h * 0.08f), radius = maxOf(w, h) * 0.6f))
    // Fainter glow just outside the bottom-left corner.
    drawRect(Brush.radialGradient(listOf(accent.copy(alpha = 0.12f), Color.Transparent), center = Offset(-w * 0.06f, h * 1.08f), radius = maxOf(w, h) * 0.5f))
}

/**
 * The soft accent glow the PWA puts behind its pages (body.ml radial gradients, toned down for a phone): a glow of colour [glow]
 * fading to clear, centred near the top right, drawn behind the content. [height] is roughly how tall the glow is.
 */
fun Modifier.accentWash(glow: Color, height: Dp = 260.dp) = drawBehind {
    // Convert the requested height from dp to real pixels.
    val h = height.toPx()
    drawRect(
        // Fade from the glow colour to clear, centred near the top right, only as tall as the area allows (at most 1.6 times the height).
        Brush.radialGradient(listOf(glow, Color.Transparent), center = Offset(size.width * 0.78f, -h * 0.15f), radius = h * 1.4f),
        size = size.copy(height = minOf(size.height, h * 1.6f)),
    )
}
