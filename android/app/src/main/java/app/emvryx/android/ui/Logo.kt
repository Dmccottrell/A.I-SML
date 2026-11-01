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

// Logo.kt: draws the Emvryx logo with code (no image file), so it can change colour and shape with the chosen model and can pulse.
// It mirrors the website's SVG logo (web/js/core.js `logo()`), which is drawn on a 64 x 64 grid.

/**
 * The Emvryx mark, drawn the way web/js/core.js `logo()` draws it: an E whose middle arm runs into a glowing ring, and
 * the ring grows with the model (Ember a coal, Flare a ring, Equinox ticks, Solstice rays, Apogee halos).
 * [kind] is a model name, or null for Emvryx's own amber mark (sign-in, the drawer). [animate] makes the ring pulse.
 */
@Composable
fun Logo(modifier: Modifier = Modifier, kind: String? = null, animate: Boolean = false) {
    // k is the variant to draw: the model name in lower case if we know it, "brand" when no model was given (Emvryx's own mark), else "flare".
    val k = kind?.lowercase()?.takeIf { it in KINDS } ?: if (kind == null) "brand" else "flare"
    // p = the colours to use: Emvryx's own palette for the brand mark, otherwise the current model's palette.
    val p = if (k == "brand") Palettes.forModel(null, Emvryx.light, Emvryx.violet) else LocalPalette.current     // Emvryx's own mark: amber, or violet
    // pulse goes 0 -> 1 -> 0 over and over (800 ms each way) when animate is on; otherwise it stays 0 and nothing moves.
    val pulse = if (animate) {
        val t = rememberInfiniteTransition(label = "logo")
        t.animateFloat(0f, 1f, infiniteRepeatable(tween(800), RepeatMode.Reverse), label = "pulse").value
    } else 0f
    // Canvas gives us a surface to draw shapes on.
    Canvas(modifier) {
        // u = how many real pixels one grid unit is, so a drawing made on a 64 x 64 grid fits any size.
        val u = size.minDimension / 64f
        // o(x, y) turns a grid point into a pixel position. r(from, to) is a radius that grows from [from] to [to] with the pulse.
        fun o(x: Float, y: Float) = Offset(x * u, y * u)
        fun r(from: Float, to: Float) = (from + (to - from) * pulse) * u
        // sun = the bright accent colour; main = the colour of the E (white-ish, except Apogee, where the E is the accent too).
        val sun = p.sun
        val main = if (k == "apogee") sun else Emvryx.text

        // A faint glow disc behind the ring (a little smaller for Ember, bigger for Apogee).
        drawCircle(sun.copy(alpha = 0.16f), (if (k == "ember") 9f else if (k == "apogee") 15f else 12f) * u, o(46f, 32f))
        // The letter E: top bar, bottom bar, then the vertical stroke.
        line(main, o(17f, 16f), o(41f, 16f), 6 * u)
        line(main, o(17f, 48f), o(41f, 48f), 6 * u)
        line(main, o(17f, 16f), o(17f, 48f), 6 * u)
        // The middle arm of the E in the accent colour; it reaches into the ring (a touch shorter for Ember).
        line(sun, o(17f, 32f), o(if (k == "ember") 36f else 37f, 32f), 6 * u)

        // Now the ring at the arm's end, which differs per model.
        when (k) {
            // Brand: a ring with a dot in the middle. When animated the ring size follows the pulse; the takeIf trick means "use the pulsing size only if animate is on".
            "brand" -> {
                drawCircle(p.core, r(4.5f, 7f).takeIf { animate } ?: (5.5f * u), o(46f, 32f), style = Stroke(3 * u))
                drawCircle(sun, 1.8f * u, o(46f, 32f))
            }
            // Ember: just a small glowing coal (a filled dot).
            "ember" -> drawCircle(sun, r(2.6f, 4.4f).takeIf { animate } ?: (3.4f * u), o(45f, 32f))
            // Apogee: a filled centre plus two thin outer halo rings.
            "apogee" -> {
                core(p.core, sun, r(4f, 6f).takeIf { animate } ?: (4.5f * u), o(46f, 32f), 2.5f * u)
                drawCircle(sun.copy(alpha = 0.7f), 8.5f * u, o(46f, 32f), style = Stroke(1.6f * u))
                drawCircle(sun.copy(alpha = 0.4f), 12f * u, o(46f, 32f), style = Stroke(1.2f * u))
            }
            // Flare, Equinox and Solstice: a filled centre with a ring, plus spokes for Equinox (4 white) and Solstice (8 accent).
            else -> {
                core(p.core, sun, r(4.5f, 7f).takeIf { animate } ?: (5.5f * u), o(46f, 32f), 3 * u)
                if (k == "equinox") rays(8.5f, 11f, 4, Emvryx.text, u)
                if (k == "solstice") rays(8.5f, 11.5f, 8, sun, u)
            }
        }
    }
}

// The model names that have their own logo variant. Anything else falls back to the "flare" look.
private val KINDS = setOf("ember", "flare", "equinox", "solstice", "apogee")

// Shortcut: draw a straight line from [a] to [b], [w] pixels thick, with round ends (a DrawScope is the canvas we paint on).
private fun DrawScope.line(c: Color, a: Offset, b: Offset, w: Float) = drawLine(c, a, b, w, StrokeCap.Round)

/** A filled centre with a ring round it (the SVG's `.core` circle: fill var(--core), stroke var(--sun)) */
private fun DrawScope.core(fill: Color, ring: Color, radius: Float, at: Offset, width: Float) {
    // Fill the disc first, then draw its outline ring on top.
    drawCircle(fill, radius, at)
    drawCircle(ring, radius, at, style = Stroke(width))
}

/**
 * Draws [n] short spokes around the ring centre (46, 32), evenly spread round the circle, each running from distance [r1] to [r2]
 * from the centre, in colour [c]. [u] is the scale from the 64-grid to real pixels. Equinox uses 4 spokes, Solstice 8.
 */
private fun DrawScope.rays(r1: Float, r2: Float, n: Int, c: Color, u: Float) {
    // Do the body once for each spoke, i = 0 .. n-1.
    repeat(n) { i ->
        // The angle of this spoke in radians: a full turn (2 * PI) split evenly into n parts.
        val a = i * 2 * PI / n
        // A point on a circle is (centre + radius * cos(angle), centre + radius * sin(angle)); draw from the inner radius to the outer radius.
        line(c, Offset((46 + r1 * cos(a)).toFloat() * u, (32 + r1 * sin(a)).toFloat() * u),
            Offset((46 + r2 * cos(a)).toFloat() * u, (32 + r2 * sin(a)).toFloat() * u), 2 * u)
    }
}
