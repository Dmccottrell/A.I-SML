// The full-screen "tour" the app shows: a welcome tour for a model (its new features) and the VryxCode tour (the coding agent).
// A tour is a list of slides (Slide) shown one at a time by TourPager, with dots, Back / Next / Skip buttons and swipes.
// The screens are written with Jetpack Compose: functions marked @Composable that describe what to draw, and Android redraws them when data changes.
package app.emvryx.android.ui

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.emvryx.android.data.ModelCard

// A model's welcome tour (feature flag model_tours; web/js/tour.js openModelTour): "WELCOME to Flare 3", the slides from models.json "tour"
// (only what that model brings), VryxCode's part for the models VryxCode can use (only what is switched on for this person), then "Try it".
// Two colours used by the slide pictures: orange (Amber) and green (Ok). 0xFFRRGGBB: the first FF means fully solid, then red, green, blue.
private val Amber = Color(0xFFFF8A3D)
private val Ok = Color(0xFF5FD38A)

/**
 * One slide of a tour. [art] picks the picture ("logo", "checklist", "lines", "stats", "big:TEXT", "chips:A|B|C" or a name like "code");
 * [kicker] is the small heading above the title; [title] and [text] are the big and the normal text;
 * [lines] are the terminal-style lines (for "lines" and "checklist"); [rows] are the table rows (for "stats").
 */
private data class Slide(val art: String, val kicker: String, val title: String, val text: String, val lines: List<String> = emptyList(),
                         val rows: List<List<String>> = emptyList())

/**
 * Builds the slides of the welcome tour for model [c]: welcome, what is new, one slide per new thing, the score table against the
 * previous model, VryxCode slides (only for models VryxCode can use, and only for features switched on for this person), then "Try it".
 * [vm] is the app's shared data holder (used for the model list and feature flags). Returns the list in the order they are shown.
 */
private fun slidesFor(vm: AppViewModel, c: ModelCard): List<Slide> {
    // Start the list with the welcome slide; "mutableListOf" is a list we can add to. Preview models get a different label.
    val name = c.fullName
    val out = mutableListOf(Slide("logo", if (c.preview) "NEW MODEL · PREVIEW" else "NEW MODEL", "WELCOME to $name", c.tagline))
    // `w` holds the "what's new compared with an earlier model" data, or null if there is none.
    val w = c.whatsNew
    // The name of the model being compared with: its full name if we know that model, otherwise its id made readable (dashes to spaces, first letter capital).
    // `?.let` runs only when w is not null; `.orEmpty()` turns a null result into an empty text.
    val prev = w?.let { n -> vm.models.firstOrNull { it.id == n.vs }?.fullName ?: n.vs.replace('-', ' ').replaceFirstChar { it.uppercase() } }.orEmpty()
    // what is new, as a checklist, then a slide for each one, then the measured numbers beside the model before it
    // Slide: a checklist of everything new (one line per tour item).
    out += Slide("checklist", name.uppercase(), "New in $name", if (w != null) "Everything $name adds compared with $prev." else "Everything $name brings.",
        lines = c.tour.map { it.title })
    // One slide for each new thing.
    c.tour.forEach { out += Slide(it.art, name.uppercase(), it.title, it.text) }
    // A table of measured scores against the previous model. The first row holds the column names; each score row is padded with "measuring" when a number is missing (getOrNull gives null past the end).
    if (w != null && w.scores.isNotEmpty()) out += Slide("stats", "${name.uppercase()} VS ${prev.uppercase()}", "How much better", "Measured side by side with $prev.",
        rows = listOf(listOf("", prev, name)) + w.scores.map { r -> listOf(r.getOrNull(0) ?: "", r.getOrNull(1) ?: "measuring", r.getOrNull(2) ?: "measuring") })
    // Models that VryxCode can use also get slides about VryxCode; the optional ones appear only if their feature flag is on.
    if (c.vryxcode) {
        out += Slide("code", "VRYXCODE", "Build with VryxCode", "Open VryxCode from the menu and describe what you want. $name plans it, writes the files, runs them and fixes what breaks.")
        if (vm.flag("vryxcode_effort")) out += Slide("effort", "VRYXCODE", "Just pick the effort", "No models to choose: VryxCode picks the best one, and you choose how hard it works. Deep thinks before every step.")
        if (vm.flag("vryxcode_full_agent")) out += Slide("fix", "VRYXCODE", "It keeps going until it works", "After every change it runs the code and the tests and fixes what fails. It asks before anything risky, and you can tell it something while it works.")
        out += Slide("modes", "VRYXCODE", "You stay in charge", "Ask before every edit, let it edit on its own, or see the plan first. Keep or undo each file it changed, and watch the result live in the preview.")
        if (vm.flag("vryxcode_suggest")) out += Slide("suggest", "VRYXCODE", "Your next message, suggested", "When it finishes, the message box suggests what to say next. Swipe right across the box to fill it in.")
    }
    // Last slide: invites the person to try the model.
    out += Slide("logo", "", "Try $name", if (c.preview) "Only you and your admins can use it until it is published." else "Pick it under the message box any time.")
    return out
}

/** The welcome tour for model [c]. Closing it (or pressing the last button, which means "use this model") calls vm.closeTour. */
@Composable
fun ModelTour(vm: AppViewModel, c: ModelCard) {
    // `remember` keeps the slide list between redraws, rebuilding it only when the model changes.
    val slides = remember(c.id) { slidesFor(vm, c) }
    TourPager(slides, "Use ${c.fullName}", Accent.Amber, c, close = { use -> vm.closeTour(use) })
}

/** The VryxCode tour (feature flag vryxcode_tour; web/js/tour.js vryxTourSlides): the first time VryxCode opens, again with /tour */
@Composable
fun VryxTour(vm: AppViewModel, close: () -> Unit) {
    // Built once and kept between redraws. No model card is passed (null), and the violet colours are used.
    val slides = remember { vryxTourSlides(vm) }
    TourPager(slides, "Start building", Accent.Violet, null, close = { close() })
}

/** Builds the slides of the VryxCode tour; some wording depends on which VryxCode features are switched on for this person. */
private fun vryxTourSlides(vm: AppViewModel): List<Slide> {
    // `k` is the kicker text most slides share. `full` tells if the full agent feature is on (changes the wording of one slide).
    val k = "VRYXCODE"
    val full = vm.flag("vryxcode_full_agent")
    val out = mutableListOf(
        Slide("big:</>", "YOUR CODING PARTNER", "WELCOME to VryxCode", "Describe what you want to build or fix. VryxCode plans it, writes the files, runs them and shows you the result."),
        Slide("lines", k, "Just describe it", "Type an idea, pick a starter template, or open one of your projects. Each piece of work is a session you can come back to.",
            lines = listOf("> A bill splitter with tip", "Planned 3 steps", "Wrote index.html, app.js", "Opened the preview")),
        if (vm.flag("vryxcode_effort")) Slide("chips:Quick|Balanced|Deep", k, "Pick the effort", "No models to choose: VryxCode uses its best one. Quick for small fixes, Balanced for most work, Deep thinks before every step.")
        else Slide("chips:Equinox|Solstice|Apogee", k, "Pick a model", "Bigger models take on bigger jobs. Small ones are best for one function or one file."),
        Slide("chips:Ask|Auto|Plan first", k, "You stay in charge", "Ask before every edit, let it edit on its own, or have it plan first and change nothing until you say go."),
        Slide("lines", k, if (full) "It keeps going until it works" else "It checks its own work",
            if (full) "After every change it runs the code and the tests and fixes what fails, for as many steps as it takes. Type while it works and it reads it before its next step."
            else "It runs what it wrote and fixes what breaks, one small step at a time.",
            lines = listOf("Changed app.js", "! Ran the tests: 1 failed", "Fixed it", "Ran the tests: all pass")),
        Slide("lines", k, "It asks before anything risky", "Running a command or changing files outside the plan needs your yes. \"Yes, always\" remembers it for this project; /permissions shows the rules.",
            lines = listOf("> Allow this?  npm test", "Yes", "Yes, always", "! No")),
        Slide("chips:Preview|Editor|Keep / Undo|Rewind", k, "See it, check it, undo it", "Watch the result in the preview, open the files in the Editor, keep or undo each file it changed, or rewind to an earlier point."),
        Slide("chips:/plan|/memory|/permissions|/fixci|/new", k, "Slash commands", "Type / for shortcuts: plan first, what it remembers, saved permissions, fix what fails on GitHub, and more. Add a screenshot with + to show it a problem."),
    )
    if (vm.flag("vryxcode_suggest")) out += Slide("lines", k, "Your next message, suggested", "When it finishes, the empty message box suggests what to say next. Swipe right across the box to fill it in.",
        lines = listOf("> Add a dark mode toggle", "Swipe right → to use it"))
    out += Slide("big:✓", "", "Ready to build", "Type /tour any time to see this again.")
    return out
}

/**
 * The colour set of a tour: [main] the big accent, [soft] a lighter tint for small headings, [glow] the translucent background glow,
 * [go] the two colours of the main button's gradient, [goText] the button text colour. Amber is for model tours, Violet for VryxCode.
 */
private enum class Accent(val main: Color, val soft: Color, val glow: Color, val go: List<Color>, val goText: Color) {
    Amber(Color(0xFFFF8A3D), Color(0xFFFFB27A), Color(0x66FF5C23), listOf(Color(0xFFFF5C23), Color(0xFFF5A524)), Color(0xFF1A0D05)),
    Violet(Color(0xFFA78BFA), Color(0xFFC4B5FD), Color(0x668B5CF6), listOf(Color(0xFF8B5CF6), Color(0xFF6366F1)), Color.White),
}

/** The slides, dots, Back / Next, Skip, swipes and the back button, shared by the model tours and the VryxCode tour. close(true) = the last button. */
@Composable
private fun TourPager(slides: List<Slide>, lastLabel: String, accent: Accent, c: ModelCard?, close: (Boolean) -> Unit) {
    // `i` is the slide number now showing. mutableIntStateOf makes it observable (changing it redraws), and `remember(slides)` keeps it across redraws.
    var i by remember(slides) { mutableIntStateOf(0) }
    // True on the final slide (the main button then says the last label and closes the tour).
    val last = i == slides.lastIndex
    // The phone's Back button goes to the previous slide, and closes the tour from the first slide.
    BackHandler { if (i > 0) i-- else close(false) }
    // Whole-screen container. Its Modifier chain: fill the screen, paint a solid dark colour, paint a soft radial glow over it, block taps from reaching
    // the chat behind, and read horizontal swipes (a swipe left of more than 60 pixels goes forward, right goes back).
    Box(
        Modifier.fillMaxSize()
            .background(Color(0xFF05060B))                         // solid first: the glow alone is see-through in the middle and the chat showed through
            .background(Brush.radialGradient(listOf(accent.glow, Color(0xFF05060B)), radius = 1400f))
            .clickable(enabled = true, onClick = {})                              // nothing behind the tour can be tapped
            .pointerInput(slides) {
                var dx = 0f
                detectHorizontalDragGestures(onDragStart = { dx = 0f }, onDragEnd = {
                    if (dx < -60) i = (i + 1).coerceAtMost(slides.lastIndex) else if (dx > 60) i = (i - 1).coerceAtLeast(0)
                }) { _, d -> dx += d }
            },
    ) {
        // Content column, kept clear of the phone's status bar and navigation bar.
        Column(Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().padding(horizontal = 24.dp)) {
            // Top row with the Skip button on the right: closes the tour without choosing "use".
            Row(Modifier.fillMaxWidth().padding(top = 12.dp), horizontalArrangement = Arrangement.End) {
                Text("Skip", Modifier.clip(RoundedCornerShape(50)).background(Color(0x14FFFFFF)).clickable { close(false) }
                    .padding(horizontal = 16.dp, vertical = 8.dp), color = Color(0xFFCFD5EA), fontWeight = FontWeight.Bold)
            }
            // The slide area. AnimatedContent animates when `i` changes: the new slide slides in and fades, the old one slides out the other way.
            // `dir` is 1 when going forward and -1 when going back; `it / 4` is a quarter of the width.
            AnimatedContent(i, Modifier.weight(1f).fillMaxWidth(), label = "slide", transitionSpec = {
                val dir = if (targetState > initialState) 1 else -1
                (slideInHorizontally { it / 4 * dir } + fadeIn()) togetherWith (slideOutHorizontally { -it / 4 * dir } + fadeOut())
            }) { k ->
                // `k` is the slide number being drawn (during animation both the old and new one are drawn).
                val s = slides[k]
                Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
                    // The picture area: the art kind decides what is drawn (terminal lines, score table, big text, chips, or a model picture).
                    Box(Modifier.fillMaxWidth().heightIn(min = 180.dp), contentAlignment = Alignment.Center) {
                        when {
                            s.art == "checklist" -> Term(s.lines.map { "+ $it" })
                            s.art == "lines" -> Term(s.lines)
                            s.art == "stats" -> Stats(s.rows, accent.main)
                            s.art.startsWith("big:") -> Big(s.art.removePrefix("big:"), accent.main)
                            s.art.startsWith("chips:") -> Chips(s.art.removePrefix("chips:").split('|'))
                            c != null -> Art(s.art, c)
                        }
                    }
                    // Small heading, big title and normal text, each shown only if it is not empty.
                    if (s.kicker.isNotEmpty()) Text(s.kicker, color = accent.soft, fontSize = 13.sp, fontWeight = FontWeight.Bold, letterSpacing = 2.sp,
                        modifier = Modifier.padding(top = 8.dp))
                    Text(s.title, color = Color.White, fontSize = 32.sp, lineHeight = 36.sp, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center,
                        modifier = Modifier.padding(top = 8.dp))
                    if (s.text.isNotEmpty()) Text(s.text, color = Color(0xFFAAB2CC), fontSize = 18.sp, lineHeight = 26.sp, textAlign = TextAlign.Center,
                        modifier = Modifier.padding(top = 12.dp))
                }
            }
            // Progress dots, one per slide; the current one is a longer bar (28 dp instead of 8 dp) in the button colour.
            Row(Modifier.fillMaxWidth().padding(vertical = 14.dp), horizontalArrangement = Arrangement.Center) {
                slides.indices.forEach { k ->
                    Box(Modifier.padding(horizontal = 4.dp).height(8.dp).width(if (k == i) 28.dp else 8.dp).clip(RoundedCornerShape(50))
                        .background(if (k == i) accent.go.first() else Color(0xFF3A4056)))
                }
            }
            // Bottom buttons: Back (not on the first slide) and Next / the last label. On the last slide, close(true) tells the caller the person chose to continue.
            Row(Modifier.fillMaxWidth().padding(bottom = 18.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                if (i > 0) TourButton("Back", null, Modifier.weight(1f)) { i-- }
                TourButton(if (last) lastLabel else "Next", accent, Modifier.weight(1f)) { if (last) close(true) else i++ }
            }
        }
    }
}

/** A big rounded button. [accent] null makes the quiet grey version (Back); otherwise the gradient version. [onClick] runs when tapped. */
@Composable
private fun TourButton(label: String, accent: Accent?, modifier: Modifier, onClick: () -> Unit) {
    // One shape reused for clipping the corners and drawing the border.
    val shape = RoundedCornerShape(16.dp)
    Box(
        modifier.heightIn(min = 52.dp).clip(shape)
            .background(Brush.linearGradient(accent?.go ?: listOf(Color(0x12FFFFFF), Color(0x12FFFFFF))))
            .border(1.dp, if (accent != null) Color.Transparent else Color(0x29FFFFFF), shape).clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) { Text(label, color = accent?.goText ?: Color(0xFFEEF0F6), fontWeight = FontWeight.Bold, fontSize = 17.sp) }
}

/**
 * The picture of a model-tour slide, chosen by [kind] (the slide's art name from models.json). [c] is the model; unknown kinds fall back to its animated logo.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Art(kind: String, c: ModelCard) {
    when (kind) {
        // Memory: the tested context size as a big number: 1024 or more is shown in K (thousands, 1024 per K), else the plain number; empty if unknown.
        "memory" -> Big(c.contextTested?.let { if (it >= 1024) "${it / 1024}K" else "$it" } ?: "", Amber)
        "sense" -> Big("↑", Amber)
        "deeper" -> Big("+12", Amber)
        // Eyes: a fake chat: the person sends a picture question and the model answers.
        "eyes" -> Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Bubble("🖼️ What does this sign say?", me = true)
            Bubble("“Platform 4: trains to the airport.”", me = false)
        }
        "fast" -> Term(listOf("It drafts a few words ahead", "checks them all at once", "the same answer, sooner"))
        "code" -> Term(listOf("> Make a habit tracker", "Planned it", "Wrote the files", "Ran the tests: all pass"))
        "fix" -> Term(listOf("Changed app.js", "! Ran the tests: 1 failed", "Fixed it", "Ran the tests: all pass"))
        "suggest" -> Term(listOf("> Add a dark mode toggle", "Swipe right → to use it"))
        "think" -> Chips(listOf("Quick", "Balanced", "Deep ✓"))
        "effort" -> Chips(listOf("Quick", "Balanced", "Deep"))
        "modes" -> Chips(listOf("Ask", "Auto", "Plan first"))
        // Anything else: the model's animated logo.
        else -> Logo(Modifier.size(96.dp), kind = c.name, animate = true)
    }
}

/** One very large piece of text (a number or a symbol) used as a slide picture. */
@Composable
private fun Big(text: String, color: Color) = Text(text, color = color, fontSize = 64.sp, fontWeight = FontWeight.ExtraBold)

/** Rounded "pills" with the given words, wrapping onto new lines when they do not fit (FlowRow). */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Chips(chips: List<String>) = FlowRow(horizontalArrangement = Arrangement.spacedBy(10.dp, Alignment.CenterHorizontally), verticalArrangement = Arrangement.spacedBy(10.dp)) {
    chips.forEach {
        Text(it, Modifier.clip(RoundedCornerShape(50)).background(Color(0x14FFFFFF)).border(1.dp, Color(0x24FFFFFF), RoundedCornerShape(50))
            .padding(horizontal = 16.dp, vertical = 10.dp), color = Color.White, fontWeight = FontWeight.SemiBold)
    }
}

/** A chat bubble for the fake chat: orange and on the right when [me] is true (the person), grey and on the left otherwise (the model). */
@Composable
private fun Bubble(text: String, me: Boolean) = Box(Modifier.fillMaxWidth(), contentAlignment = if (me) Alignment.CenterEnd else Alignment.CenterStart) {
    Text(text, Modifier.clip(RoundedCornerShape(18.dp)).background(if (me) Color(0xE6FF5C23) else Color(0x14FFFFFF)).padding(horizontal = 16.dp, vertical = 12.dp),
        color = if (me) Color(0xFF1A0D05) else Color.White, fontWeight = if (me) FontWeight.SemiBold else FontWeight.Normal)
}

/**
 * A little fake terminal box. Each line's start decides how it looks: ">" a typed command (grey), "+ " a checklist item (green plus),
 * "!" a warning (orange), anything else a finished step (green tick).
 */
@Composable
private fun Term(lines: List<String>) = Column(
    Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(Color(0xFF0B0D16)).border(1.dp, Color(0x1FFFFFFF), RoundedCornerShape(16.dp))
        .padding(horizontal = 16.dp, vertical = 14.dp),
    verticalArrangement = Arrangement.spacedBy(4.dp),
) {
    // Draw each line in a monospace font (every letter the same width), styled by its first characters.
    lines.forEach { l ->
        when {
            l.startsWith(">") -> Text(l, color = Color(0xFF7C849E), fontFamily = FontFamily.Monospace, fontSize = 14.sp)
            l.startsWith("+ ") -> Row { Text("+ ", color = Ok, fontFamily = FontFamily.Monospace, fontSize = 14.sp); Text(l.removePrefix("+ "), color = Color(0xFFCFD5EA), fontFamily = FontFamily.Monospace, fontSize = 14.sp) }
            l.startsWith("!") -> Text(l, color = Color(0xFFFFB27A), fontFamily = FontFamily.Monospace, fontSize = 14.sp)
            else -> Row { Text("✓ ", color = Ok, fontFamily = FontFamily.Monospace, fontSize = 14.sp); Text(l, color = Color(0xFFCFD5EA), fontFamily = FontFamily.Monospace, fontSize = 14.sp) }
        }
    }
}

/** The measured numbers: [what, before, now] rows, the first one the two names */
@Composable
private fun Stats(rows: List<List<String>>, accent: Color) = Column(
    Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(Color(0x0DFFFFFF)).border(1.dp, Color(0x1FFFFFFF), RoundedCornerShape(16.dp)),
) {
    // `k` is the row number (0 = the header with the two model names, which is drawn quieter), `r` is the row: [what, before, now].
    rows.forEachIndexed { k, r ->
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 9.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(r[0], Modifier.weight(1.4f), color = Color.White, fontSize = 14.sp)
            Text(r[1], Modifier.weight(1f), color = Color(0xFF8A92AC), fontSize = 14.sp, textAlign = TextAlign.End, fontWeight = if (k == 0) FontWeight.SemiBold else FontWeight.Normal)
            Text(r[2], Modifier.weight(1f), color = if (k == 0) Color(0xFF8A92AC) else accent, fontSize = 14.sp, textAlign = TextAlign.End, fontWeight = FontWeight.ExtraBold)
        }
    }
}
