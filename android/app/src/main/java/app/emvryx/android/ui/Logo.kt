package app.emvryx.android.ui

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import app.emvryx.android.ui.theme.Emvryx
import app.emvryx.android.ui.theme.LocalPalette
import app.emvryx.android.ui.theme.Palettes
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

/**
 * The Emvryx mark, drawn the way web/js/core.js `logo()` draws it: an E whose middle arm runs into a glowing ring, and
 * the ring grows with the model (Ember a coal, Flare a ring, Equinox ticks, Solstice rays, Apogee halos).
 * [kind] is a model name, or null for Emvryx's own amber mark (sign-in, the drawer). [animate] makes the ring pulse.
 */
@Composable
fun Logo(modifier: Modifier = Modifier, kind: String? = null, animate: Boolean = false) {
    val k = kind?.lowercase()?.takeIf { it in KINDS } ?: if (kind == null) "brand" else "flare"
    val p = if (k == "brand") Palettes.forModel(null, Emvryx.light, Emvryx.violet) else LocalPalette.current     // Emvryx's own mark: amber, or violet
    val pulse = if (animate) {
        val t = rememberInfiniteTransition(label = "logo")
        t.animateFloat(0f, 1f, infiniteRepeatable(tween(800), RepeatMode.Reverse), label = "pulse").value
    } else 0f
    Canvas(modifier) {
        val u = size.minDimension / 64f
        fun o(x: Float, y: Float) = Offset(x * u, y * u)
        fun r(from: Float, to: Float) = (from + (to - from) * pulse) * u
        val sun = p.sun
        val main = if (k == "apogee") sun else Emvryx.text

        drawCircle(sun.copy(alpha = 0.16f), (if (k == "ember") 9f else if (k == "apogee") 15f else 12f) * u, o(46f, 32f))
        line(main, o(17f, 16f), o(41f, 16f), 6 * u)
        line(main, o(17f, 48f), o(41f, 48f), 6 * u)
        line(main, o(17f, 16f), o(17f, 48f), 6 * u)
        line(sun, o(17f, 32f), o(if (k == "ember") 36f else 37f, 32f), 6 * u)

        when (k) {
            "brand" -> {
                drawCircle(p.core, r(4.5f, 7f).takeIf { animate } ?: (5.5f * u), o(46f, 32f), style = Stroke(3 * u))
                drawCircle(sun, 1.8f * u, o(46f, 32f))
            }
            "ember" -> drawCircle(sun, r(2.6f, 4.4f).takeIf { animate } ?: (3.4f * u), o(45f, 32f))
            "apogee" -> {
                core(p.core, sun, r(4f, 6f).takeIf { animate } ?: (4.5f * u), o(46f, 32f), 2.5f * u)
                drawCircle(sun.copy(alpha = 0.7f), 8.5f * u, o(46f, 32f), style = Stroke(1.6f * u))
                drawCircle(sun.copy(alpha = 0.4f), 12f * u, o(46f, 32f), style = Stroke(1.2f * u))
            }
            else -> {
                core(p.core, sun, r(4.5f, 7f).takeIf { animate } ?: (5.5f * u), o(46f, 32f), 3 * u)
                if (k == "equinox") rays(8.5f, 11f, 4, Emvryx.text, u)
                if (k == "solstice") rays(8.5f, 11.5f, 8, sun, u)
            }
        }
    }
}

private val KINDS = setOf("ember", "flare", "equinox", "solstice", "apogee")

private fun DrawScope.line(c: Color, a: Offset, b: Offset, w: Float) = drawLine(c, a, b, w, StrokeCap.Round)

/** A filled centre with a ring round it (the SVG's `.core` circle: fill var(--core), stroke var(--sun)) */
private fun DrawScope.core(fill: Color, ring: Color, radius: Float, at: Offset, width: Float) {
    drawCircle(fill, radius, at)
    drawCircle(ring, radius, at, style = Stroke(width))
}

private fun DrawScope.rays(r1: Float, r2: Float, n: Int, c: Color, u: Float) {
    repeat(n) { i ->
        val a = i * 2 * PI / n
        line(c, Offset((46 + r1 * cos(a)).toFloat() * u, (32 + r1 * sin(a)).toFloat() * u),
            Offset((46 + r2 * cos(a)).toFloat() * u, (32 + r2 * sin(a)).toFloat() * u), 2 * u)
    }
}
