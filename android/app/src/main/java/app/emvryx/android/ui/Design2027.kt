package app.emvryx.android.ui

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.material3.Text
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.LinearOutSlowInEasing
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.emvryx.android.ui.theme.Emvryx

// design_2027 (feature flag, owner only until it has been reviewed): the pieces of the 2027 look that several screens share.
// The same look as the website (web/design2027.css). Everything here is only used while Emvryx.d27 is on, so the normal look is untouched.

// Light mode (the website's `html[data-mode="light"] body.d27` block): the carbon cards become soft white cards with a fine grey edge and the violet is deeper so it can be
// read on white. Each of these is a getter that picks light or dark at the moment it is read, so the screen redraws when the theme changes.

/** The glowing amethyst used for tags, the send ring and highlights (the website's --d-amethyst); a deeper violet on the light theme */
val D27Amethyst: Color get() = if (Emvryx.light) Color(0xFF6D28D9) else Color(0xFFB79CFF)

/** The matte carbon of cards (#0C0C10) and the razor-thin translucent border (white at 8%) */
val D27Carbon: Color get() = if (Emvryx.light) Color(0xFFFFFFFF) else Color(0xFF0C0C10)
val D27Hair: Color get() = if (Emvryx.light) Color(0x1A19193C) else Color(0x14FFFFFF)

/** Text and small marks on those cards: the muted grey of quiet buttons, the usual text colour when touched, the empty track of a bar, a sunken well (code, skeletons) */
val D27Soft: Color get() = if (Emvryx.light) Color(0xFF6B6B78) else Color(0xFF7C7C86)
val D27Touched: Color get() = if (Emvryx.light) Emvryx.text else Color(0xFFE4E4E7)
val D27Track: Color get() = if (Emvryx.light) Color(0x1A19193C) else Color(0x1AFFFFFF)
val D27Well: Color get() = if (Emvryx.light) Color(0xFFF4F4F9) else Color.Black
val D27Paper: Color get() = if (Emvryx.light) Color(0xFFF1F0F9) else Color(0xFF16161D)
val D27Shadow: Color get() = if (Emvryx.light) Color(0xFF3A2F7A) else Color.Black

/** The lit top edge of a card or a ghost button: a border that is brighter at the top and fades down the sides */
fun d27Edge() = if (Emvryx.light) Brush.verticalGradient(listOf(Color(0x2619193C), Color(0x1019193C))) else Brush.verticalGradient(listOf(Color(0x40FFFFFF), Color(0x14FFFFFF)))

/** Glass for small pills: carbon at 70% (rgba(12, 12, 16, 0.7)) */
val D27Glass: Color get() = if (Emvryx.light) Color(0xCCFFFFFF) else Color(0xB30C0C10)

/** The message bar: highly translucent carbon (rgba(10, 10, 14, 0.4)). Android cannot blur what is behind a view, so on the phone it is translucency and the lit edge only */
val D27Bar: Color get() = if (Emvryx.light) Color(0xB8FFFFFF) else Color(0x660A0A0E)

/**
 * The ambient glow at the top of the screen: a heavily soft radial gradient that drifts slowly sideways. Cool violet at rest; warm amber
 * while the model is working. [busy] is true while a reply is being written.
 */
@Composable
fun Modifier.d27Glow(busy: Boolean): Modifier {
    // The colour eases between violet and amber over about 0.8 s.
    val tint by animateColorAsState(if (busy) Color(0xFFF5A524) else Color(0xFF8B5CF6), tween(800), label = "d27glow")
    // A very slow back-and-forth drift of the glow's centre (a quarter of the screen width over 20 s).
    val drift by rememberInfiniteTransition(label = "d27drift").animateFloat(-0.12f, 0.12f, infiniteRepeatable(tween(20000, easing = LinearEasing), RepeatMode.Reverse), label = "x")
    return this.drawBehind {
        val centre = Offset(size.width * (0.5f + drift), -size.height * 0.04f)
        drawRect(Brush.radialGradient(listOf(tint.copy(alpha = 0.30f), tint.copy(alpha = 0.08f), Color.Transparent), centre, size.width * 0.9f))
    }
}

/**
 * The usage as a sleek pill (the website's .d27-pill): a short bar and the words in a monospace face with steady digits.
 * [fraction] is how much is left (0 to 1); [label] the words; [low] turns the bar red.
 */
@Composable
fun D27UsagePill(fraction: Float, label: String, low: Boolean, modifier: Modifier = Modifier) {
    Row(
        modifier.clip(RoundedCornerShape(999.dp)).background(D27Glass).border(1.dp, d27Edge(), RoundedCornerShape(999.dp)).padding(horizontal = 10.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Box(Modifier.width(40.dp).height(4.dp).clip(RoundedCornerShape(4.dp)).background(D27Track)) {
            Box(Modifier.fillMaxWidth(fraction.coerceIn(0f, 1f)).height(4.dp).background(if (low) Color(0xFFF87171) else D27Amethyst))
        }
        Text(label, color = if (low) Color(0xFFF87171) else (if (Emvryx.light) Emvryx.muted else Color(0xFF9AA3BC)), fontSize = 11.sp,
            fontFamily = FontFamily.Monospace, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

/** The inference telemetry text under a finished reply: "~64 tok/s · Flare 3 · first word 120 ms". Tokens are estimated from the length (about 4 letters each). */
object D27Telemetry {
    fun line(chars: Int, firstMs: Long, totalMs: Long, model: String): String? {
        if (chars <= 0 || totalMs <= 0) return null
        // Time spent writing = total minus the wait for the first word, never below 50 ms so a very short reply cannot divide by nearly zero.
        val writingMs = (totalMs - firstMs).coerceAtLeast(50)
        val rate = Math.round(Math.max(1.0, chars / 4.0) / (writingMs / 1000.0))
        return "~$rate tok/s" + (if (model.isNotBlank()) " · $model" else "") + " · first word $firstMs ms"
    }
}

/** The loading skeleton: shimmering bars like the lines of a code block, shown while a session spins up */
@Composable
fun D27Skeleton(modifier: Modifier = Modifier) {
    val shimmer by rememberInfiniteTransition(label = "d27shim").animateFloat(0.06f, 0.18f, infiniteRepeatable(tween(900), RepeatMode.Reverse), label = "a")
    Column(modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(D27Well).border(1.dp, D27Hair, RoundedCornerShape(14.dp)).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        listOf(0.86f, 0.62f, 0.74f, 0.48f, 0.8f).forEach { w ->
            Box(Modifier.fillMaxWidth(w).height(11.dp).clip(RoundedCornerShape(6.dp)).background(Color.White.copy(alpha = shimmer)))
        }
    }
}

/**
 * A nearly invisible action (Copy, Regenerate...): no pill, muted grey (#7C7C86) that lights up (#E4E4E7) while it is touched.
 * Used under replies when the 2027 look is on.
 */
@Composable
fun QuietAction(text: String, onClick: () -> Unit, modifier: Modifier = Modifier) {
    val source = androidx.compose.runtime.remember { androidx.compose.foundation.interaction.MutableInteractionSource() }
    val pressed by source.collectIsPressedAsState()
    Box(modifier.heightIn(min = 36.dp).clip(RoundedCornerShape(999.dp)).clickable(interactionSource = source, indication = null, onClick = onClick).padding(horizontal = 10.dp, vertical = 6.dp),
        contentAlignment = Alignment.Center) {
        Text(text, color = if (pressed) D27Touched else D27Soft, fontSize = 14.sp)
    }
}

/** A matte carbon card with the lit top edge: the fill plus the razor-thin border (the website's tactile card). [fill] is carbon unless a screen wants another */
fun Modifier.d27Card(shape: Shape, fill: Color = D27Carbon): Modifier = this.clip(shape).background(fill).border(1.dp, d27Edge(), shape)

/** Your own message in a session: solid matte carbon (#16161D) with a lit top edge and a soft shadow, like the chat bubble */
fun Modifier.d27Bubble(shape: Shape): Modifier = this.shadow(10.dp, shape, ambientColor = D27Shadow, spotColor = D27Shadow).clip(shape).background(D27Paper).border(1.dp, d27Edge(), shape)

/** The answer buttons of a question card: a hairline pill with plain text; only the main answer ([main]) is amethyst, so the card stays calm */
@Composable
fun D27GhostAnswer(text: String, onClick: () -> Unit, main: Boolean = false, modifier: Modifier = Modifier) {
    Box(modifier.heightIn(min = 40.dp).clip(CircleShape).border(1.dp, if (main) D27Amethyst.copy(alpha = 0.5f) else D27Hair, CircleShape)
        .clickable(onClick = onClick).padding(horizontal = 16.dp), contentAlignment = Alignment.Center) {
        Text(text, color = if (main) D27Amethyst else D27Touched, fontSize = 15.sp, fontWeight = if (main) FontWeight.SemiBold else FontWeight.Normal)
    }
}

/**
 * New things print in VryxCode's colour: text that has just appeared starts amethyst and settles to its normal colour over about 1.8 s (like the website's d27ink).
 * [normal] is the colour it settles to. It plays once per line (rememberSaveable keeps that across scrolling), and only while the 2027 look is on.
 */
@Composable
fun d27Ink(normal: Color): Color {
    var played by rememberSaveable { mutableStateOf(false) }
    val fade = remember { Animatable(0f) }
    LaunchedEffect(Unit) {
        if (Emvryx.d27 && !played) { played = true; fade.snapTo(1f); fade.animateTo(0f, tween(1800, easing = LinearOutSlowInEasing)) }
    }
    return lerp(normal, D27Amethyst, fade.value)
}
