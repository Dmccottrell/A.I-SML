package app.emvryx.android.ui

import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.emvryx.android.data.CodeSessionRow
import app.emvryx.android.data.bool
import app.emvryx.android.data.str
import app.emvryx.android.data.strings
import app.emvryx.android.ui.theme.Emvryx
import app.emvryx.android.ui.theme.Mono
import app.emvryx.android.ui.theme.Heading
import androidx.compose.foundation.layout.widthIn
import kotlinx.serialization.json.JsonObject
import kotlin.math.abs

// VryxCode's screens on a phone, in its electric violet (web/vryx.css): the sessions list, and one session's work feed with the message box.
private val Violet = Color(0xFF8B5CF6)
private val VioletSoft = Color(0x268B5CF6)
private val Green = Color(0xFF34D399)

private val MODES = listOf("ask" to "Ask before editing", "auto" to "Edit without asking", "plan" to "Plan first")
private val SLASH = listOf("/plan" to "Plan first: look and plan, change nothing", "/ask" to "Ask before editing", "/auto" to "Edit without asking",
                           "/new" to "Start a new session", "/memory" to "What VryxCode remembers about you", "/permissions" to "This project's permission rules",
                           "/fixci" to "Fix what is failing on GitHub for this project", "/tour" to "Take the VryxCode tour again")

@Composable
fun CodeScreen(app: AppViewModel, vm: CodeViewModel) {
    LaunchedEffect(app.state) {
        vm.suggestOn = app.flag("vryxcode_suggest")
        vm.onTour = app::replayVryxTour
        app.maybeVryxTour()                                       // the VryxCode tour, the first time VryxCode opens (flag vryxcode_tour)
    }
    LaunchedEffect(Unit) { vm.load() }
    BackHandler { if (vm.inSession) vm.backToList() else app.backToChat() }
    var more by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxSize().background(Emvryx.bg).imePadding()) {
        Column(Modifier.statusBarsPadding()) {
            Row(Modifier.fillMaxWidth().height(56.dp).padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = { if (vm.inSession) vm.backToList() else app.backToChat() }) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = Emvryx.text) }
                PwaIcon("code", Violet, 22.dp)
                Spacer(Modifier.width(10.dp))
                Text("VryxCode", fontFamily = Heading, fontWeight = FontWeight.SemiBold, fontSize = 19.sp, modifier = Modifier.weight(1f))
                Box {
                    IconButton(onClick = { more = true }) { Text("⋯", fontSize = 22.sp, color = Emvryx.text) }
                    DropdownMenu(more, { more = false }, containerColor = Emvryx.surface) {
                        DropdownMenuItem({ Text("Open the editor") }, { more = false; app.open(Screen.Web("/", "VryxCode editor", "openCode()")) },
                            leadingIcon = { PwaIcon("doc", Emvryx.muted, 18.dp) })
                        DropdownMenuItem({ Text("What VryxCode remembers") }, { more = false; vm.showMemory() },
                            leadingIcon = { PwaIcon("brain", Emvryx.muted, 18.dp) })
                        DropdownMenuItem({ Text("Take the tour again") }, { more = false; app.replayVryxTour() },
                            leadingIcon = { PwaIcon("spark", Emvryx.muted, 18.dp) })
                    }
                }
            }
            HorizontalDivider(color = Emvryx.line)
            if (vm.info?.allowed != false) ProjectRow(vm)                  // which project VryxCode works in, and + New project
        }
        vm.error?.let {
            Text(it, fontSize = 14.sp, modifier = Modifier.fillMaxWidth().background(Emvryx.surface).padding(12.dp))
        }
        if (vm.info?.allowed == false) {
            Text("VryxCode is not open to you yet. " + (vm.info?.whyNot ?: ""), color = Emvryx.muted, modifier = Modifier.padding(24.dp))
            return@Column
        }
        if (vm.inSession) {
            Box(Modifier.weight(1f).fillMaxWidth()) { Feed(vm) }
            CodeComposer(vm)
        } else {
            Box(Modifier.weight(1f).fillMaxWidth()) {
                SessionList(vm)
                Row(
                    Modifier.align(Alignment.BottomEnd).navigationBarsPadding().padding(18.dp).heightIn(min = 52.dp).clip(CircleShape)
                        .background(Violet).clickable { vm.newSession() }.padding(horizontal = 22.dp),
                    verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text("+", color = Color.White, fontSize = 22.sp)
                    Text("New session", color = Color.White, fontWeight = FontWeight.SemiBold, fontSize = 16.sp)
                }
            }
        }
    }
    vm.memory?.let { MemoryDialog(vm, it) }
    vm.rules?.let { RulesDialog(vm) }
}

/** The project VryxCode works in: its name (tap to switch), and + New project */
@Composable
private fun ProjectRow(vm: CodeViewModel) {
    var open by remember { mutableStateOf(false) }
    var naming by remember { mutableStateOf(false) }
    Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        Text("PROJECT", color = Emvryx.muted, fontSize = 11.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.1.sp)
        Spacer(Modifier.width(10.dp))
        Box(Modifier.weight(1f)) {
            Row(
                Modifier.clip(CircleShape).background(Emvryx.surface).border(1.dp, Emvryx.line, CircleShape).clickable { open = true }
                    .padding(horizontal = 12.dp, vertical = 7.dp),
                verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                PwaIcon("folder", Violet, 16.dp)
                Text(vm.project, fontSize = 14.sp, fontWeight = FontWeight.Medium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text("▾", color = Emvryx.muted, fontSize = 12.sp)
            }
        DropdownMenu(open, { open = false }, containerColor = Emvryx.surface) {
            (vm.info?.projects.orEmpty() + vm.project).distinct().forEach { p ->
                DropdownMenuItem({ Text(p) }, { vm.project = p; open = false; vm.newSession() })
            }
            DropdownMenuItem({ Text("+ New project") }, { naming = true; open = false })
        }
        }
        Text("+ New project", color = Violet, fontSize = 14.sp, fontWeight = FontWeight.Medium,
            modifier = Modifier.clip(CircleShape).clickable { naming = true }.padding(horizontal = 10.dp, vertical = 7.dp))
    }
    if (naming) {
        var name by remember { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = { naming = false }, containerColor = Emvryx.surface,
            title = { Text("New project") },
            text = { NoteBox(name, { name = it.filter { c -> c.isLetterOrDigit() || c == '-' || c == '_' }.take(40) }, "my-new-app") },
            confirmButton = { TextButton({ if (name.isNotBlank()) { vm.project = name; vm.newSession() }; naming = false }) { Text("Create") } },
            dismissButton = { TextButton({ naming = false }) { Text("Cancel") } },
        )
    }
}

// ---------------------------------------------------------------- the sessions list

@Composable
private fun SessionList(vm: CodeViewModel) {
    if (vm.sessions.isEmpty()) {
        Welcome(vm, "Describe it. VryxCode plans it, writes it, runs it and checks it.")
        return
    }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 6.dp, bottom = 96.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item(key = "head") {
            Text("SESSIONS · ${vm.sessions.size}", color = Emvryx.muted, fontSize = 11.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.1.sp,
                modifier = Modifier.padding(start = 4.dp, top = 6.dp))
        }
        items(vm.sessions, key = { it.id }) { s -> SessionCard(s) { vm.openSession(s) } }
    }
}

private val IDEAS = listOf(
    "A to-do list app" to "Build a small to-do list web app: add, tick off and delete tasks, saved in the browser.",
    "A landing page" to "Make a simple landing page for a bakery with a menu section and opening hours.",
    "Fix a failing test" to "Run the tests in this project, find what fails and fix it.",
)

/** The empty home and a new session: the mark, the question, and a few ideas to start from (tap one to put it in the box) */
@Composable
private fun Welcome(vm: CodeViewModel, lead: String) {
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 24.dp, vertical = 24.dp),
        verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(Modifier.size(72.dp).clip(CircleShape).background(VioletSoft), contentAlignment = Alignment.Center) { PwaIcon("code", Violet, 36.dp) }
        Text("What should we build?", fontFamily = Heading, fontWeight = FontWeight.SemiBold, fontSize = 28.sp,
            textAlign = androidx.compose.ui.text.style.TextAlign.Center, modifier = Modifier.padding(top = 18.dp))
        Text(lead, color = Emvryx.muted, fontSize = 15.sp, textAlign = androidx.compose.ui.text.style.TextAlign.Center, modifier = Modifier.padding(top = 8.dp))
        Column(Modifier.padding(top = 22.dp).widthIn(max = 420.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            IDEAS.forEach { (name, task) ->
                Row(
                    Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(Emvryx.surface).border(1.dp, Emvryx.line, RoundedCornerShape(16.dp))
                        .clickable { if (!vm.inSession) vm.newSession(); vm.draft = task }.padding(horizontal = 16.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f)) {
                        Text(name, fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
                        Text(task, color = Emvryx.muted, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                    Text("›", color = Emvryx.muted, fontSize = 20.sp)
                }
            }
        }
    }
}

@Composable
private fun SessionCard(s: CodeSessionRow, onClick: () -> Unit) {
    val shape = RoundedCornerShape(16.dp)
    Column(Modifier.fillMaxWidth().clip(shape).background(Emvryx.surface).border(1.dp, Emvryx.line, shape).clickable(onClick = onClick).padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            val (dot, word) = when {
                s.live && s.state == "asking" -> Color(0xFFF5A524) to "Needs you"
                s.live -> Violet to "Working"
                s.state == "queued" -> Emvryx.muted to "Queued"
                s.state in setOf("failed", "interrupted") -> Emvryx.danger to "Stopped"
                else -> Green to "Done"
            }
            Box(Modifier.size(8.dp).clip(CircleShape).background(dot))
            Spacer(Modifier.width(8.dp))
            Text(s.title, fontWeight = FontWeight.SemiBold, fontSize = 16.sp, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
            Spacer(Modifier.width(8.dp))
            Text(word + " · " + s.age, color = Emvryx.muted, fontSize = 12.sp)
        }
        Text(s.project + " · " + s.model + " · " + s.env, color = Emvryx.muted, fontSize = 13.sp, maxLines = 1)
        if (s.snippet.isNotBlank()) Text(s.snippet, color = Emvryx.muted, fontSize = 14.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
        val stats = listOfNotNull(if (s.steps > 0) "${s.steps} steps" else null, if (s.files > 0) "${s.files} files changed" else null,
                                  if (s.state == "queued") "Queued #${s.position}" else null, if (s.state == "asking") "Needs you" else null)
        if (stats.isNotEmpty()) Text(stats.joinToString(" · "), color = if (s.state == "asking") Violet else Emvryx.muted, fontSize = 13.sp)
    }
}

// ---------------------------------------------------------------- one session's work feed

@Composable
private fun Feed(vm: CodeViewModel) {
    val list = rememberLazyListState()
    LaunchedEffect(vm.events.size, vm.pending) { if (vm.events.isNotEmpty()) list.animateScrollToItem(vm.events.size) }
    if (vm.events.isEmpty() && vm.sid == null) {
        Welcome(vm, "Describe one task. VryxCode reads, edits, runs the tests and tries again in its own project folder, and asks before it changes anything. Type / for commands.")
        return
    }
    LazyColumn(Modifier.fillMaxSize(), state = list, contentPadding = PaddingValues(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        items(vm.events.size) { i -> EventRow(vm.events[i], vm.events) }
        item {
            val q = vm.pending
            when {
                q != null && q.str("tool") == "ask_user" -> ChoiceCard(vm, q)
                q != null -> AskCard(vm, q)
                vm.working -> Text("● " + (vm.liveLine?.ifBlank { null } ?: "Working…"), color = Violet, fontSize = 14.sp)
            }
        }
    }
}

@Composable
private fun EventRow(e: JsonObject, all: List<JsonObject>) {
    val shape = RoundedCornerShape(14.dp)
    when (e.str("kind")) {
        "start", "user" -> if (!e.bool("auto")) Text(
            (if (e.bool("plan")) "[Plan] " else "") + e.str("task").ifEmpty { e.str("text") } + (if (e.bool("steer")) "  (while it worked)" else ""),
            fontSize = 15.sp, modifier = Modifier.fillMaxWidth().clip(shape).background(Emvryx.surface2).padding(12.dp),
        )
        "step" -> Column(Modifier.fillMaxWidth().clip(shape).background(Emvryx.surface).border(1.dp, Emvryx.line, shape).padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("● " + e.str("tool"), color = Green, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
            val preview = e.str("preview")
            if (preview.isNotBlank()) Text(preview.take(1500), style = Mono, color = Emvryx.muted,
                modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(Emvryx.bg).horizontalScroll(rememberScrollState()).padding(10.dp))
        }
        "result" -> Text("→ " + e.str("text").take(600), style = Mono, color = Emvryx.muted, maxLines = 8, overflow = TextOverflow.Ellipsis)
        "retry" -> Text("↻ " + e.str("why"), color = Emvryx.muted, fontSize = 13.sp)
        "note", "language" -> Text(e.str("text"), color = Emvryx.muted, fontSize = 14.sp)
        "queued" -> Text("Queued: it starts when the session before it finishes.", color = Emvryx.muted, fontSize = 14.sp)
        "compacted" -> Text("Summarized earlier steps to make room.", color = Emvryx.muted, fontSize = 13.sp)
        "model" -> Text("Now using ${e.str("model")}.", color = Emvryx.muted, fontSize = 13.sp)
        "rewind" -> Text("↶ Rewound the files to before: " + e.str("label"), color = Emvryx.muted, fontSize = 14.sp)
        "ask", "choose" -> {
            val answered = all.any { it.str("kind") == "answer" && it.str("id") == e.str("id") }
            if (answered) Text(if (e.str("kind") == "choose") "Asked: " + e.str("question") else "Asked to use " + e.str("tool"), color = Emvryx.muted, fontSize = 13.sp)
        }
        "answer" -> if (e.str("choice").isNotEmpty()) Text("You chose: " + e.str("choice"), color = Violet, fontSize = 14.sp)
        "end" -> Column(Modifier.fillMaxWidth().clip(shape).background(if (e.bool("finished")) VioletSoft else Emvryx.surface)
            .border(1.dp, if (e.bool("finished")) Violet else Emvryx.line, shape).padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Markdown.blocks(e.str("summary").ifEmpty { if (e.bool("finished")) "Done." else "Stopped." }).forEach { b ->
                when (b) {
                    is Block.Prose -> Text(Markdown.inline(b.text), fontSize = 15.sp)
                    is Block.Code -> Text(b.text, style = Mono, modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(Emvryx.bg)
                        .horizontalScroll(rememberScrollState()).padding(10.dp))
                }
            }
            e.strings("next").forEach { Text("→ $it", color = Emvryx.muted, fontSize = 14.sp) }
        }
        else -> Unit
    }
}

/** "Allow this?": the change or command it wants to make, then Yes / Yes and don't ask again / No */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun AskCard(vm: CodeViewModel, q: JsonObject) {
    val shape = RoundedCornerShape(16.dp)
    Column(Modifier.fillMaxWidth().clip(shape).background(Emvryx.surface).border(1.dp, Violet, shape).padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("Allow this?", fontWeight = FontWeight.Bold, fontSize = 17.sp)
        Text(q.str("preview").take(2500), style = Mono, color = Emvryx.muted,
            modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(Emvryx.bg).horizontalScroll(rememberScrollState()).padding(10.dp))
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            PwaButton("Yes", { vm.answer(true) })
            Chip("Yes, and don't ask again for this", { vm.answer(true, always = true) })
            Chip("No", { vm.answer(false) })
        }
    }
}

/** The full agent's multiple-choice question: one tap answers, or write your own */
@Composable
private fun ChoiceCard(vm: CodeViewModel, q: JsonObject) {
    var own by remember(q.str("id")) { mutableStateOf("") }
    val shape = RoundedCornerShape(16.dp)
    Column(Modifier.fillMaxWidth().clip(shape).background(Emvryx.surface).border(1.dp, Violet, shape).padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(q.str("question"), fontWeight = FontWeight.Bold, fontSize = 17.sp)
        q.strings("options").forEach { o ->
            Text(o, fontSize = 15.sp, modifier = Modifier.fillMaxWidth().clip(CircleShape).border(1.dp, Emvryx.line, CircleShape).clickable { vm.choose(o) }
                .padding(horizontal = 16.dp, vertical = 12.dp))
        }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Box(Modifier.weight(1f)) { NoteBox(own, { own = it }, "Or write your own answer") }
            PwaButton("Send", { vm.choose(own) }, enabled = own.isNotBlank())
        }
    }
}

// ---------------------------------------------------------------- the message box

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun CodeComposer(vm: CodeViewModel) {
    val context = LocalContext.current
    var field by remember { mutableStateOf(TextFieldValue("")) }
    val text = field.text
    val fill = { t: String -> field = TextFieldValue(t, TextRange(t.length)) }
    val takeOffer = { if (text.isEmpty() && vm.offer.isNotEmpty()) { fill(vm.offer); vm.offer = ""; true } else false }
    LaunchedEffect(vm.draft) { if (vm.draft.isNotEmpty()) { fill(vm.draft); vm.draft = "" } }      // an idea tapped on the welcome
    var menu by remember { mutableStateOf<String?>(null) }
    val pick = rememberLauncherForActivityResult(ActivityResultContracts.PickMultipleVisualMedia(3)) { uris ->
        uris.forEach { u -> readPicked(context, u)?.let { (n, b) -> vm.addPicture(n, b) } }
    }
    val shape = RoundedCornerShape(22.dp)
    Column(
        Modifier.fillMaxWidth().navigationBarsPadding().padding(12.dp).clip(shape).background(Emvryx.surface).border(1.dp, Violet.copy(alpha = 0.6f), shape)
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        if (text.startsWith("/") && !text.contains(' ')) {         // the / menu: the app's commands and this project's own
            val items = SLASH.filter { it.first.startsWith(text.lowercase()) } + vm.commands.map { "/" + it.name to it.about.ifBlank { "This project's own command" } }
                .filter { it.first.startsWith(text.lowercase()) }
            items.take(8).forEach { (c, about) ->
                Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).clickable { fill("$c ") }.padding(6.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text(c, style = Mono, color = Violet)
                    Text(about, color = Emvryx.muted, fontSize = 13.sp, maxLines = 2)
                }
            }
        }
        if (vm.pictures.isNotEmpty()) FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            vm.pictures.forEachIndexed { i, _ -> Chip("🖼 Picture ${i + 1} ×", { vm.pictures.removeAt(i) }) }
        }
        // the suggested reply (flag vryxcode_suggest): greyed in the empty box; a swipe right across the box, or Tab on a keyboard, fills it in
        Box(Modifier.fillMaxWidth().heightIn(min = 24.dp, max = 160.dp).swipeRight { takeOffer() }) {
            if (text.isEmpty()) Text(vm.offer.ifEmpty { if (vm.working && vm.full) "Tell it something while it works…" else "Ask, answer, or tell VryxCode what to build or fix" },
                color = Emvryx.muted, style = MaterialTheme.typography.bodyLarge)
            BasicTextField(field, { field = it }, Modifier.fillMaxWidth().onPreviewKeyEvent { it.key == Key.Tab && it.type == KeyEventType.KeyDown && takeOffer() },
                textStyle = MaterialTheme.typography.bodyLarge.copy(color = Emvryx.text), cursorBrush = SolidColor(Violet))
        }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            IconButton({ pick.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) }, Modifier.size(40.dp)) {
                Icon(Icons.Default.Add, "Add a screenshot", tint = Emvryx.muted)
            }
            Box(Modifier.weight(1f, fill = false)) {
                val effortName = vm.info?.effort?.levels?.firstOrNull { it.id == vm.effort }?.name ?: "Balanced"
                val label = if (vm.oneModel) effortName else vm.info?.models?.firstOrNull { it.id == vm.model }?.label ?: "Model"
                SmallPill(label + " ▾") { menu = "pick" }
                DropdownMenu(menu == "pick", { menu = null }, containerColor = Emvryx.surface) {
                    if (vm.oneModel) vm.info?.effort?.levels.orEmpty().forEach { l ->
                        DropdownMenuItem({ Column { Text(l.name, fontWeight = FontWeight.Bold); Text(l.note, color = Emvryx.muted, fontSize = 13.sp) } }, { vm.effort = l.id; menu = null })
                    } else vm.info?.models.orEmpty().forEach { m ->
                        DropdownMenuItem({ Text(m.label.ifEmpty { m.name }) }, { vm.model = m.id; menu = null }, enabled = m.ready)
                    }
                }
            }
            Box(Modifier.weight(1f, fill = false)) {
                SmallPill(when (vm.mode) { "auto" -> "Auto"; "plan" -> "Plan"; else -> "Ask" } + " ▾") { menu = "mode" }
                DropdownMenu(menu == "mode", { menu = null }, containerColor = Emvryx.surface) {
                    MODES.forEach { (id, name) -> DropdownMenuItem({ Text(name) }, { vm.mode = id; menu = null }) }
                }
            }
            if (vm.sid == null) Box(Modifier.weight(1f, fill = false)) {
                SmallPill((vm.info?.environments?.firstOrNull { it.id == vm.env }?.name ?: "This computer") + " ▾") { menu = "env" }
                DropdownMenu(menu == "env", { menu = null }, containerColor = Emvryx.surface) {
                    vm.info?.environments.orEmpty().forEach { e -> DropdownMenuItem({ Text(e.name) }, { vm.env = e.id; menu = null }, enabled = e.available) }
                }
            }
            Spacer(Modifier.weight(1f))
            if (vm.working) Box(Modifier.size(42.dp).clip(RoundedCornerShape(12.dp)).background(Emvryx.danger).clickable { vm.stop() }, contentAlignment = Alignment.Center) {
                Box(Modifier.size(12.dp).background(Color.White))
            }
            if (!vm.working || vm.full) Box(
                Modifier.size(42.dp).clip(RoundedCornerShape(12.dp)).background(Violet).clickable(enabled = text.isNotBlank() || vm.pictures.isNotEmpty()) {
                    vm.send(text)
                    fill("")
                },
                contentAlignment = Alignment.Center,
            ) { Text("↑", color = Color.White, fontWeight = FontWeight.Bold, fontSize = 20.sp) }
        }
    }
}

/** A swipe to the right across this area (watched before the text box sees it, so typing and selecting still work) */
private fun Modifier.swipeRight(onSwipe: () -> Unit): Modifier = pointerInput(Unit) {
    awaitEachGesture {
        val down = awaitFirstDown(requireUnconsumed = false, pass = PointerEventPass.Initial)
        var last = down.position
        while (true) {
            val change = awaitPointerEvent(PointerEventPass.Initial).changes.firstOrNull { it.id == down.id } ?: break
            last = change.position
            if (!change.pressed) break
        }
        if (last.x - down.position.x > 60.dp.toPx() && abs(last.y - down.position.y) < 40.dp.toPx()) onSwipe()
    }
}

@Composable
private fun SmallPill(text: String, onClick: () -> Unit) {
    Text(text, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis,
        modifier = Modifier.clip(CircleShape).border(1.dp, Emvryx.line, CircleShape).clickable(onClick = onClick).padding(horizontal = 12.dp, vertical = 10.dp))
}

// ---------------------------------------------------------------- /memory and /permissions

@Composable
private fun MemoryDialog(vm: CodeViewModel, notes: List<String>) {
    AlertDialog(
        onDismissRequest = vm::closeMemory, containerColor = Emvryx.surface,
        title = { Text("What VryxCode remembers") },
        text = {
            Column(Modifier.heightIn(max = 420.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Short notes it saved about you and how you like to work. It reads them at the start of every session.", color = Emvryx.muted, fontSize = 14.sp)
                if (notes.isEmpty()) Text("Nothing yet.")
                notes.forEachIndexed { i, n ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(n, modifier = Modifier.weight(1f), fontSize = 15.sp)
                        TextButton({ vm.forget(i) }) { Text("Forget") }
                    }
                }
            }
        },
        confirmButton = { TextButton(vm::closeMemory) { Text("Close") } },
        dismissButton = { if (notes.isNotEmpty()) TextButton({ vm.forget(null) }) { Text("Forget all", color = Emvryx.danger) } },
    )
}

@Composable
private fun RulesDialog(vm: CodeViewModel) {
    val r = vm.rules ?: return
    var rule by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = vm::closeRules, containerColor = Emvryx.surface,
        title = { Text("Permission rules for ${vm.project}") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("A rule is the start of a command (npm test) or a tool (write_file). \"Never\" wins.", color = Emvryx.muted, fontSize = 14.sp)
                listOf("allow" to "Always allow", "deny" to "Never allow").forEach { (kind, title) ->
                    Text(title, fontWeight = FontWeight.Bold)
                    val list = if (kind == "allow") r.allow else r.deny
                    if (list.isEmpty()) Text("None.", color = Emvryx.muted)
                    list.forEach { x ->
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(x, style = Mono, modifier = Modifier.weight(1f))
                            TextButton({ vm.removeRule(x) }) { Text("Remove") }
                        }
                    }
                }
                NoteBox(rule, { rule = it }, "npm test, git push, write_file …")
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Chip("Always", { vm.addRule("allow", rule); rule = "" })
                    Chip("Never", { vm.addRule("deny", rule); rule = "" })
                }
            }
        },
        confirmButton = { TextButton(vm::closeRules) { Text("Close") } },
    )
}
