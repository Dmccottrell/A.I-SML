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

// The PWA's small building blocks (web/index.html): .btn, .btn.ghost, .chip, .field and the accent wash behind the page.

/** .btn: the accent button. [ghost] is .btn.ghost, a line round a transparent button. */
@Composable
fun PwaButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    ghost: Boolean = false,
    content: (@Composable () -> Unit)? = null,
) {
    val p = LocalPalette.current
    val shape = RoundedCornerShape(12.dp)
    Box(
        modifier
            .heightIn(min = 48.dp)
            .alpha(if (enabled) 1f else 0.45f)
            .clip(shape)
            .then(if (ghost) Modifier.border(1.dp, Emvryx.line, shape) else Modifier.background(p.accent))
            .clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = 18.dp),
        contentAlignment = Alignment.Center,
    ) {
        CompositionLocalProvider(LocalContentColor provides if (ghost) Emvryx.text else p.onAccent) {
            content?.invoke() ?: Text(text, fontWeight = FontWeight.SemiBold, fontSize = 16.sp)
        }
    }
}

/** .chip: a small rounded button with a line round it (Copy, Regenerate) */
@Composable
fun Chip(text: String, onClick: () -> Unit, modifier: Modifier = Modifier) {
    Box(
        modifier
            .heightIn(min = 36.dp)
            .clip(RoundedCornerShape(999.dp))
            .border(1.dp, Emvryx.line, RoundedCornerShape(999.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 6.dp),
        contentAlignment = Alignment.Center,
    ) { Text(text, color = Emvryx.muted, fontSize = 14.sp) }
}

/** .field: a label above a rounded box; the box takes the accent outline while typing. [trailing] sits at the right (Show). */
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
    var focused by remember { mutableStateOf(false) }
    Column {
        Text(label, fontWeight = FontWeight.SemiBold, fontSize = 14.sp, modifier = Modifier.padding(bottom = 6.dp))
        val shape = RoundedCornerShape(12.dp)
        Row(
            Modifier.fillMaxWidth().heightIn(min = 48.dp).clip(shape).background(Emvryx.surface)
                .border(if (focused) 2.dp else 1.dp, if (focused) p.accent else Emvryx.line, shape)
                .padding(start = 14.dp, end = if (trailing != null) 6.dp else 14.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(Modifier.weight(1f).padding(vertical = 12.dp)) {
                if (value.isEmpty()) Text(placeholder, color = Emvryx.muted, fontSize = 16.sp)
                BasicTextField(
                    value, onChange, Modifier.fillMaxWidth().onFocusChanged { focused = it.isFocused },
                    singleLine = true,
                    textStyle = MaterialTheme.typography.bodyLarge.copy(color = Emvryx.text),
                    cursorBrush = SolidColor(p.accent),
                    visualTransformation = if (hidden) androidx.compose.ui.text.input.PasswordVisualTransformation() else VisualTransformation.None,
                    keyboardOptions = keyboard,
                    keyboardActions = actions,
                )
            }
            trailing?.invoke()
        }
    }
}

/** The soft accent glow the PWA puts behind its pages (body.ml radial gradients, toned down for a phone) */
fun Modifier.accentWash(glow: Color, height: Dp = 260.dp) = drawBehind {
    val h = height.toPx()
    drawRect(
        Brush.radialGradient(listOf(glow, Color.Transparent), center = Offset(size.width * 0.78f, -h * 0.15f), radius = h * 1.4f),
        size = size.copy(height = minOf(size.height, h * 1.6f)),
    )
}
