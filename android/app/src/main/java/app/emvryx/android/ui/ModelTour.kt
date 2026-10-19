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
private val Amber = Color(0xFFFF8A3D)
private val Ok = Color(0xFF5FD38A)

private data class Slide(val art: String, val kicker: String, val title: String, val text: String, val lines: List<String> = emptyList(),
                         val rows: List<List<String>> = emptyList())

private fun slidesFor(vm: AppViewModel, c: ModelCard): List<Slide> {
    val name = c.fullName
    val out = mutableListOf(Slide("logo", if (c.preview) "NEW MODEL · PREVIEW" else "NEW MODEL", "WELCOME to $name", c.tagline))
    val w = c.whatsNew
    val prev = w?.let { n -> vm.models.firstOrNull { it.id == n.vs }?.fullName ?: n.vs.replace('-', ' ').replaceFirstChar { it.uppercase() } }.orEmpty()
    // what is new, as a checklist, then a slide for each one, then the measured numbers beside the model before it
    out += Slide("checklist", name.uppercase(), "New in $name", if (w != null) "Everything $name adds compared with $prev." else "Everything $name brings.",
        lines = c.tour.map { it.title })
    c.tour.forEach { out += Slide(it.art, name.uppercase(), it.title, it.text) }
    if (w != null && w.scores.isNotEmpty()) out += Slide("stats", "${name.uppercase()} VS ${prev.uppercase()}", "How much better", "Measured side by side with $prev.",
        rows = listOf(listOf("", prev, name)) + w.scores.map { r -> listOf(r.getOrNull(0) ?: "", r.getOrNull(1) ?: "measuring", r.getOrNull(2) ?: "measuring") })
    if (c.vryxcode) {
        out += Slide("code", "VRYXCODE", "Build with VryxCode", "Open VryxCode from the menu and describe what you want. $name plans it, writes the files, runs them and fixes what breaks.")
        if (vm.flag("vryxcode_effort")) out += Slide("effort", "VRYXCODE", "Just pick the effort", "No models to choose: VryxCode picks the best one, and you choose how hard it works. Deep thinks before every step.")
        if (vm.flag("vryxcode_full_agent")) out += Slide("fix", "VRYXCODE", "It keeps going until it works", "After every change it runs the code and the tests and fixes what fails. It asks before anything risky, and you can tell it something while it works.")
        out += Slide("modes", "VRYXCODE", "You stay in charge", "Ask before every edit, let it edit on its own, or see the plan first. Keep or undo each file it changed, and watch the result live in the preview.")
        if (vm.flag("vryxcode_suggest")) out += Slide("suggest", "VRYXCODE", "Your next message, suggested", "When it finishes, the message box suggests what to say next. Swipe right across the box to fill it in.")
    }
    out += Slide("logo", "", "Try $name", if (c.preview) "Only you and your admins can use it until it is published." else "Pick it under the message box any time.")
    return out
}

@Composable
fun ModelTour(vm: AppViewModel, c: ModelCard) {
    val slides = remember(c.id) { slidesFor(vm, c) }
    TourPager(slides, "Use ${c.fullName}", Accent.Amber, c, close = { use -> vm.closeTour(use) })
}

/** The VryxCode tour (feature flag vryxcode_tour; web/js/tour.js vryxTourSlides): the first time VryxCode opens, again with /tour */
@Composable
fun VryxTour(vm: AppViewModel, close: () -> Unit) {
    val slides = remember { vryxTourSlides(vm) }
    TourPager(slides, "Start building", Accent.Violet, null, close = { close() })
}

private fun vryxTourSlides(vm: AppViewModel): List<Slide> {
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

private enum class Accent(val main: Color, val soft: Color, val glow: Color, val go: List<Color>, val goText: Color) {
    Amber(Color(0xFFFF8A3D), Color(0xFFFFB27A), Color(0x66FF5C23), listOf(Color(0xFFFF5C23), Color(0xFFF5A524)), Color(0xFF1A0D05)),
    Violet(Color(0xFFA78BFA), Color(0xFFC4B5FD), Color(0x668B5CF6), listOf(Color(0xFF8B5CF6), Color(0xFF6366F1)), Color.White),
}

/** The slides, dots, Back / Next, Skip, swipes and the back button, shared by the model tours and the VryxCode tour. close(true) = the last button. */
@Composable
private fun TourPager(slides: List<Slide>, lastLabel: String, accent: Accent, c: ModelCard?, close: (Boolean) -> Unit) {
    var i by remember(slides) { mutableIntStateOf(0) }
    val last = i == slides.lastIndex
    BackHandler { if (i > 0) i-- else close(false) }
    Box(
        Modifier.fillMaxSize()
            .background(Brush.radialGradient(listOf(accent.glow, Color(0xFF05060B)), radius = 1400f))
            .clickable(enabled = true, onClick = {})                              // nothing behind the tour can be tapped
            .pointerInput(slides) {
                var dx = 0f
                detectHorizontalDragGestures(onDragStart = { dx = 0f }, onDragEnd = {
                    if (dx < -60) i = (i + 1).coerceAtMost(slides.lastIndex) else if (dx > 60) i = (i - 1).coerceAtLeast(0)
                }) { _, d -> dx += d }
            },
    ) {
        Column(Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().padding(horizontal = 24.dp)) {
            Row(Modifier.fillMaxWidth().padding(top = 12.dp), horizontalArrangement = Arrangement.End) {
                Text("Skip", Modifier.clip(RoundedCornerShape(50)).background(Color(0x14FFFFFF)).clickable { close(false) }
                    .padding(horizontal = 16.dp, vertical = 8.dp), color = Color(0xFFCFD5EA), fontWeight = FontWeight.Bold)
            }
            AnimatedContent(i, Modifier.weight(1f).fillMaxWidth(), label = "slide", transitionSpec = {
                val dir = if (targetState > initialState) 1 else -1
                (slideInHorizontally { it / 4 * dir } + fadeIn()) togetherWith (slideOutHorizontally { -it / 4 * dir } + fadeOut())
            }) { k ->
                val s = slides[k]
                Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
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
                    if (s.kicker.isNotEmpty()) Text(s.kicker, color = accent.soft, fontSize = 13.sp, fontWeight = FontWeight.Bold, letterSpacing = 2.sp,
                        modifier = Modifier.padding(top = 8.dp))
                    Text(s.title, color = Color.White, fontSize = 32.sp, lineHeight = 36.sp, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center,
                        modifier = Modifier.padding(top = 8.dp))
                    if (s.text.isNotEmpty()) Text(s.text, color = Color(0xFFAAB2CC), fontSize = 18.sp, lineHeight = 26.sp, textAlign = TextAlign.Center,
                        modifier = Modifier.padding(top = 12.dp))
                }
            }
            Row(Modifier.fillMaxWidth().padding(vertical = 14.dp), horizontalArrangement = Arrangement.Center) {
                slides.indices.forEach { k ->
                    Box(Modifier.padding(horizontal = 4.dp).height(8.dp).width(if (k == i) 28.dp else 8.dp).clip(RoundedCornerShape(50))
                        .background(if (k == i) accent.go.first() else Color(0xFF3A4056)))
                }
            }
            Row(Modifier.fillMaxWidth().padding(bottom = 18.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                if (i > 0) TourButton("Back", null, Modifier.weight(1f)) { i-- }
                TourButton(if (last) lastLabel else "Next", accent, Modifier.weight(1f)) { if (last) close(true) else i++ }
            }
        }
    }
}

@Composable
private fun TourButton(label: String, accent: Accent?, modifier: Modifier, onClick: () -> Unit) {
    val shape = RoundedCornerShape(16.dp)
    Box(
        modifier.heightIn(min = 52.dp).clip(shape)
            .background(Brush.linearGradient(accent?.go ?: listOf(Color(0x12FFFFFF), Color(0x12FFFFFF))))
            .border(1.dp, if (accent != null) Color.Transparent else Color(0x29FFFFFF), shape).clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) { Text(label, color = accent?.goText ?: Color(0xFFEEF0F6), fontWeight = FontWeight.Bold, fontSize = 17.sp) }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Art(kind: String, c: ModelCard) {
    when (kind) {
        "memory" -> Big(c.contextTested?.let { if (it >= 1024) "${it / 1024}K" else "$it" } ?: "", Amber)
        "sense" -> Big("↑", Amber)
        "deeper" -> Big("+12", Amber)
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
        else -> Logo(Modifier.size(96.dp), kind = c.name, animate = true)
    }
}

@Composable
private fun Big(text: String, color: Color) = Text(text, color = color, fontSize = 64.sp, fontWeight = FontWeight.ExtraBold)

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Chips(chips: List<String>) = FlowRow(horizontalArrangement = Arrangement.spacedBy(10.dp, Alignment.CenterHorizontally), verticalArrangement = Arrangement.spacedBy(10.dp)) {
    chips.forEach {
        Text(it, Modifier.clip(RoundedCornerShape(50)).background(Color(0x14FFFFFF)).border(1.dp, Color(0x24FFFFFF), RoundedCornerShape(50))
            .padding(horizontal = 16.dp, vertical = 10.dp), color = Color.White, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
private fun Bubble(text: String, me: Boolean) = Box(Modifier.fillMaxWidth(), contentAlignment = if (me) Alignment.CenterEnd else Alignment.CenterStart) {
    Text(text, Modifier.clip(RoundedCornerShape(18.dp)).background(if (me) Color(0xE6FF5C23) else Color(0x14FFFFFF)).padding(horizontal = 16.dp, vertical = 12.dp),
        color = if (me) Color(0xFF1A0D05) else Color.White, fontWeight = if (me) FontWeight.SemiBold else FontWeight.Normal)
}

@Composable
private fun Term(lines: List<String>) = Column(
    Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(Color(0xFF0B0D16)).border(1.dp, Color(0x1FFFFFFF), RoundedCornerShape(16.dp))
        .padding(horizontal = 16.dp, vertical = 14.dp),
    verticalArrangement = Arrangement.spacedBy(4.dp),
) {
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
    rows.forEachIndexed { k, r ->
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 9.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(r[0], Modifier.weight(1.4f), color = Color.White, fontSize = 14.sp)
            Text(r[1], Modifier.weight(1f), color = Color(0xFF8A92AC), fontSize = 14.sp, textAlign = TextAlign.End, fontWeight = if (k == 0) FontWeight.SemiBold else FontWeight.Normal)
            Text(r[2], Modifier.weight(1f), color = if (k == 0) Color(0xFF8A92AC) else accent, fontSize = 14.sp, textAlign = TextAlign.End, fontWeight = FontWeight.ExtraBold)
        }
    }
}
