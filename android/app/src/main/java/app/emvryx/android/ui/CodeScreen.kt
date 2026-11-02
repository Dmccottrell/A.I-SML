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
import androidx.compose.foundation.layout.fillMaxHeight
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
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.draw.drawBehind
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
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.emvryx.android.data.CodeSessionRow
import app.emvryx.android.data.bool
import app.emvryx.android.data.int
import app.emvryx.android.data.num
import app.emvryx.android.data.str
import app.emvryx.android.data.strings
import app.emvryx.android.ui.theme.Emvryx
import app.emvryx.android.ui.theme.Mono
import app.emvryx.android.ui.theme.Heading
import androidx.compose.foundation.layout.widthIn
import kotlinx.serialization.json.JsonObject
import kotlin.math.abs

// CodeScreen.kt: VryxCode (the coding agent) on the phone. This file draws every part of it: the sessions list and project organizer,
// one session's "feed" (the steps the agent took, its questions, its final summary), the message box, and the memory/rules dialogs.
// It is built with Jetpack Compose: a @Composable function describes a piece of screen, and a `remember { mutableStateOf(...) }`
// value makes the screen redraw by itself when it changes. The data and actions come from CodeViewModel (a ViewModel is the object
// that holds a screen's state and does its work); `app` below is the app-wide AppViewModel. Many parts are behind feature flags
// (on/off switches the server sets per person), so most blocks start with a check of vm.parity or vm.review.
// Small helper logic (grouping sessions, folding quiet steps, reading verdicts) lives in CodeReview.kt, CodeParity.kt and CodeProjects.kt.
//
// VryxCode's screens on a phone, in its electric violet (web/vryx.css): the sessions list, and one session's work feed with the message box.
// The colours: violet is VryxCode's brand colour, VioletSoft is the same at about 15% strength (the hex 26 is the transparency), Green marks added lines.
private val Violet = Color(0xFF8B5CF6)
private val VioletSoft = Color(0x268B5CF6)
private val Green = Color(0xFF34D399)

// The three working modes: the word sent to the server, then the label shown.
private val MODES = listOf("ask" to "Ask before editing", "auto" to "Edit without asking", "plan" to "Plan first")
// The / commands offered when the message starts with a slash: the command, then what it does.
private val SLASH = listOf("/plan" to "Plan first: look and plan, change nothing", "/ask" to "Ask before editing", "/auto" to "Edit without asking",
                           "/new" to "Start a new session", "/memory" to "What VryxCode remembers about you", "/permissions" to "This project's permission rules",
                           "/fixci" to "Fix what is failing on GitHub for this project", "/tour" to "Take the VryxCode tour again")

/**
 * The whole VryxCode screen: top bar (back, title, ⋯ menu), the project row, then either a sessions list (with a New session button)
 * or, inside a session, the work feed and the message box. [app] is the app-wide state, [vm] is VryxCode's own.
 */
@Composable
fun CodeScreen(app: AppViewModel, vm: CodeViewModel) {
    // LaunchedEffect runs its block when the screen first appears and again whenever the value in the brackets changes.
    // Here it copies the server's feature flags into the VryxCode state, and wires up the "open the website" and tour actions.
    LaunchedEffect(app.state) {
        vm.suggestOn = app.flag("vryxcode_suggest")
        vm.review = app.flag("vryxcode_review")
        vm.projects = app.flag("vryxcode_projects")
        vm.alerts = app.flag("phone_alerts")
        vm.homeLike = app.flag("android_vryxcode_home")           // android_vryxcode_home: the home looks like the website's
        vm.archiveOn = app.flag("vryxcode_archive")               // vryxcode_archive: archive or delete any session (the ⋯ on each row)
        // `parity` = the set of newer website features the app shows: all off unless android_vryxcode is on, then each follows its own switch.
        vm.parity = if (!app.flag("android_vryxcode")) emptySet() else PARITY_FLAGS.filter { app.flag(it) }.toSet()     // each part follows its own switch
        // Let the ViewModel open a page of the website inside the app (used by Preview, Save to GitHub, Publish).
        vm.onWeb = { title, js -> app.open(Screen.Web("/", title, js)) }
        vm.onTour = app::replayVryxTour
        app.maybeVryxTour()                                       // the VryxCode tour, the first time VryxCode opens (flag vryxcode_tour)
    }
    // Load the session list once, when the screen opens (Unit never changes, so this runs just once).
    LaunchedEffect(Unit) { vm.load() }
    LaunchedEffect(app.openSession) { app.openSession?.let { vm.openById(it); app.openSession = null } }   // a notification tapped
    // The phone's Back button: leave the open session first; from the list, go back to the chat.
    BackHandler { if (vm.inSession) vm.backToList() else app.backToChat() }
    // Whether the ⋯ menu is open.
    var more by remember { mutableStateOf(false) }
    // imePadding lifts everything above the on-screen keyboard.
    Column(Modifier.fillMaxSize().background(Emvryx.bg).imePadding()) {
        Column(Modifier.statusBarsPadding()) {
            // The top bar: back arrow, code icon, title (weight(1f) pushes the menu button to the far right), menu.
            Row(Modifier.fillMaxWidth().height(56.dp).padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = { if (vm.inSession) vm.backToList() else app.backToChat() }) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = Emvryx.text) }
                PwaIcon("code", Violet, 22.dp)
                Spacer(Modifier.width(10.dp))
                Text("VryxCode", fontFamily = Heading, fontWeight = FontWeight.SemiBold, fontSize = 19.sp, modifier = Modifier.weight(1f))
                Box {
                    IconButton(onClick = { more = true }) { Text("⋯", fontSize = 22.sp, color = Emvryx.text) }
                    DropdownMenu(more, { more = false }, containerColor = Emvryx.surface) {
                        // The menu: open the website's editor on this project, see what VryxCode remembers, or replay the tour.
                        DropdownMenuItem({ Text("Open the editor") }, { more = false; app.open(Screen.Web("/", "VryxCode editor", editorJs(vm))) },
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
        // A banner for the last error, if any.
        vm.error?.let {
            Text(it, fontSize = 14.sp, modifier = Modifier.fillMaxWidth().background(Emvryx.surface).padding(12.dp))
        }
        // Not allowed: say why and stop drawing (return@Column leaves the Column block).
        if (vm.info?.allowed == false) {
            Text("VryxCode is not open to you yet. " + (vm.info?.whyNot ?: ""), color = Emvryx.muted, modifier = Modifier.padding(24.dp))
            return@Column
        }
        // Inside a session: the feed fills the space and the message box sits under it. Otherwise: the list, plus a floating "New session" button in the bottom-right corner.
        if (vm.inSession) {
            if (Emvryx.d27) Box(Modifier.weight(1f).fillMaxWidth()) {          // design_2027: the message bar floats over the feed as glass; the feed scrolls up clear of it
                Feed(vm)
                Box(Modifier.align(Alignment.BottomCenter)) { CodeComposer(vm) }
            } else {
                Box(Modifier.weight(1f).fillMaxWidth()) { Feed(vm) }
                CodeComposer(vm)
            }
        } else {
            Box(Modifier.weight(1f).fillMaxWidth()) {
                SessionList(vm)
                Row(
                    Modifier.align(Alignment.BottomEnd).navigationBarsPadding().padding(18.dp).heightIn(min = 52.dp).clip(CircleShape)
                        .then(if (Emvryx.d27) Modifier.background(if (Emvryx.light) Color(0xCCFFFFFF) else Color(0xCC000000)).border(1.dp, d27Edge(), CircleShape)         // design_2027: a hollow ghost button
                              else Modifier.background(Violet))
                        .clickable { vm.newSession() }.padding(horizontal = 22.dp),
                    verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text("+", color = if (Emvryx.d27) D27Amethyst else Color.White, fontSize = 22.sp)
                    Text("New session", color = if (Emvryx.d27) D27Amethyst else Color.White, fontWeight = FontWeight.SemiBold, fontSize = 16.sp)
                }
            }
        }
    }
    // Dialogs that appear only while their data is set (the notes VryxCode saved, and this project's permission rules).
    vm.memory?.let { MemoryDialog(vm, it) }
    vm.menuFor?.let { SessionMenu(vm, it) }                         // vryxcode_archive: Archive / Restore / Delete
    vm.rules?.let { RulesDialog(vm) }
}

/**
 * The website's VryxCode opened on this project's files: the open session (its changes and preview too), or a new one in this project.
 * Returns a line of JavaScript for the in-app web page to run. The names are turned into safe JSON strings first so a project name
 * with quotes in it cannot break the script.
 */
private fun editorJs(vm: CodeViewModel): String {
    // The project name as a quoted, escaped JS string.
    val p = kotlinx.serialization.json.JsonPrimitive(vm.project).toString()
    // Open the current session if there is one, otherwise start a new one.
    val open = vm.sid?.let { "openSession({id: " + kotlinx.serialization.json.JsonPrimitive(it).toString() + ", project: $p, model: C.model})" } ?: "newSession()"
    // Wait for the editor to load, pick the project, open the session, then show the files drawer.
    return "openCode().then(() => { C.project = $p; $open; showDrawer(true, 'files'); })"
}

/** The project VryxCode works in: its name (tap to switch), and + New project. */
@Composable
private fun ProjectRow(vm: CodeViewModel) {
    var open by remember { mutableStateOf(false) }
    // `open`: the project dropdown is showing. `naming`: the "New project" dialog is showing.
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
        // The dropdown: every known project (distinct removes a repeat of the current one), then "+ New project".
        DropdownMenu(open, { open = false }, containerColor = Emvryx.surface) {
            (vm.info?.projects.orEmpty() + vm.project).distinct().forEach { p ->
                DropdownMenuItem({ Text(p) }, { open = false; vm.newSessionIn(p) })
            }
            DropdownMenuItem({ Text("+ New project") }, { naming = true; open = false })
        }
        }
        Text("+ New project", color = Violet, fontSize = 14.sp, fontWeight = FontWeight.Medium,
            modifier = Modifier.clip(CircleShape).clickable { naming = true }.padding(horizontal = 10.dp, vertical = 7.dp))
    }
    // The New project dialog.
    if (naming) {
        var name by remember { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = { naming = false }, containerColor = Emvryx.surface,
            title = { Text("New project") },
            // Only letters, digits, - and _ are kept, up to 40 characters, so the name is safe as a folder name.
            text = { NoteBox(name, { name = it.filter { c -> c.isLetterOrDigit() || c == '-' || c == '_' }.take(40) }, "my-new-app") },
            // Create does nothing for an empty name but always closes the dialog.
            confirmButton = { TextButton({ if (name.isNotBlank()) vm.newSessionIn(name); naming = false }) { Text("Create") } },
            dismissButton = { TextButton({ naming = false }) { Text("Cancel") } },
        )
    }
}

// ---------------------------------------------------------------- the sessions list

/** The list of past sessions: an empty welcome, the projects organizer, or cards grouped by status. */
@Composable
private fun SessionList(vm: CodeViewModel) {
    // No sessions yet: the welcome page with ideas to start from.
    if (vm.sessions.isEmpty() && vm.archived.isEmpty() && !vm.homeLike) {
        Welcome(vm, "Describe it. VryxCode plans it, writes it, runs it and checks it.")
        return
    }
    // Flag vryxcode_projects: show the organizer instead of the plain list.
    if (vm.projects) {
        Organizer(vm)
        return
    }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 6.dp, bottom = 96.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        homeHero(vm)                                                 // android_vryxcode_home: What should we build? and the starters, above the sessions
        // With the review view on, sessions are grouped (Working / Ready for review / Done); otherwise one SESSIONS group.
        val groups = if (vm.review) sessionGroups(vm.sessions, vm.reviewed) else listOf("SESSIONS" to vm.sessions)
        groups.forEach { (label, rows) ->
            // A group heading, then one card per session. `key` gives each row a stable identity so scrolling stays smooth when the list changes.
            item(key = "head-$label") {
                Text("$label · ${rows.size}", color = if (label == "READY FOR REVIEW") Violet else Emvryx.muted, fontSize = 11.sp,
                    fontWeight = FontWeight.SemiBold, letterSpacing = 1.1.sp, modifier = Modifier.padding(start = 4.dp, top = 6.dp))
            }
            items(rows, key = { it.id }) { s -> SessionCard(s, vm.review, onMore = if (vm.archiveOn && !s.live) ({ vm.menuFor = s }) else null) { vm.openSession(s) } }
        }
        archivedBlock(vm)
    }
}

/**
 * The projects organizer (flag vryxcode_projects), like Claude's list: every project with its sessions under it, newest first, numbered,
 * a spinner on the working ones, a dot on the ones ready for review, and + to start a new session in that project
 */
@Composable
private fun Organizer(vm: CodeViewModel) {
    // The states that mean "still working".
    val busy = setOf("starting", "working", "asking", "queued")
    // Pairs of (project name, its sessions), busiest project first.
    val groups = projectGroups(vm.sessions, vm.info?.projects.orEmpty())
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(start = 12.dp, end = 12.dp, top = 6.dp, bottom = 96.dp)) {
        homeHero(vm)                                                 // android_vryxcode_home: What should we build? and the starters, above the projects
        // A running counter so the sessions are numbered 1, 2, 3 down the whole list.
        var n = 0
        groups.forEach { (p, rows) ->
            item(key = "proj-$p") {
                Row(Modifier.fillMaxWidth().padding(start = 6.dp, top = 14.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                    PwaIcon("folder", Emvryx.muted, 16.dp)
                    Spacer(Modifier.width(8.dp))
                    Text(p, fontWeight = FontWeight.SemiBold, fontSize = 15.sp, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                    Box(Modifier.size(34.dp).clip(CircleShape).clickable { vm.newSessionIn(p) }, contentAlignment = Alignment.Center) {
                        Text("+", color = Emvryx.muted, fontSize = 20.sp)
                    }
                }
            }
            if (rows.isEmpty()) item(key = "empty-$p") {
                Text("No sessions yet", color = Emvryx.muted, fontSize = 13.sp, modifier = Modifier.padding(start = 30.dp, bottom = 4.dp))
            }
            rows.forEach { s ->
                n += 1
                val num = n
                item(key = s.id) {
                    // "Ready for review": finished, changed something, and not opened since it last changed.
                    val ready = s.state !in busy && s.state == "done" && (s.added > 0 || s.removed > 0 || s.files > 0) && vm.reviewed[s.id] != s.updated
                    val d27 = Emvryx.d27                           // design_2027: tighter rows with a razor-thin line between them, numbers in a monospace face
                    val mono = if (d27) androidx.compose.ui.text.font.FontFamily.Monospace else null
                    Row(Modifier.fillMaxWidth().then(if (d27) Modifier.drawBehind { drawLine(D27Hair, Offset(0f, size.height), Offset(size.width, size.height), 1.dp.toPx()) } else Modifier.clip(RoundedCornerShape(10.dp)))
                        .clickable { vm.openSession(s) }.padding(start = 8.dp, end = 8.dp, top = if (d27) 6.dp else 9.dp, bottom = if (d27) 6.dp else 9.dp),
                        verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.width(22.dp), contentAlignment = Alignment.Center) {
                            when {
                                // The status marker: ! when it needs you, a spinner while working, a dot when ready for review, a cross when it failed.
                                s.state == "asking" -> Text("!", color = Color(0xFFF5A524), fontWeight = FontWeight.Bold, fontSize = 15.sp)
                                s.state in busy -> androidx.compose.material3.CircularProgressIndicator(Modifier.size(12.dp), color = Violet, strokeWidth = 1.6.dp)
                                ready -> Box(Modifier.size(7.dp).clip(CircleShape).background(Violet))
                                s.state in setOf("failed", "interrupted") -> Text("✗", color = Emvryx.danger, fontSize = 13.sp)
                            }
                        }
                        // The title takes the free space (weight 1) and is cut with … if too long; brighter while active.
                        Text(s.title.ifBlank { "Session" }, fontSize = 15.sp, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f),
                            color = if (ready || s.state in busy) Emvryx.text else Emvryx.text.copy(alpha = 0.85f))
                        // Lines added (green) and removed (red), like a code review.
                        if (s.added > 0 || s.removed > 0) {
                            Spacer(Modifier.width(8.dp))
                            Text("+${s.added}", color = Green, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, fontFamily = mono)
                            Text(" −${s.removed}", color = Emvryx.danger, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, fontFamily = mono)
                        }
                        Spacer(Modifier.width(8.dp))
                        Text(s.age, color = Emvryx.muted, fontSize = 12.sp, fontFamily = mono)
                        // vryxcode_archive: the ⋯ opens Archive / Delete (not for a session that is still working)
                        if (vm.archiveOn && !s.live) MoreDots { vm.menuFor = s }
                        Text(num.toString(), color = Emvryx.muted, fontSize = 11.sp, modifier = Modifier.padding(start = 8.dp).widthIn(min = 16.dp), fontFamily = mono,
                            textAlign = androidx.compose.ui.text.style.TextAlign.End)
                    }
                }
            }
        }
        archivedBlock(vm)                                            // vryxcode_archive: the Archived part at the end
    }
}

/**
 * android_vryxcode_home: the top of the VryxCode home, as on the website: "What should we build?", the build box with Build it, the Effort pick,
 * where it builds ("Builds in a new project · use X instead"), and the project starters to begin from. Added as the first items of the list.
 */
private fun androidx.compose.foundation.lazy.LazyListScope.homeHero(vm: CodeViewModel) {
    if (!vm.homeLike) return
    item(key = "home-hero") {
        Column(Modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            // The big question; the word "build" is violet, as on the website.
            Text(androidx.compose.ui.text.buildAnnotatedString {
                append("What should we ")
                withStyle(androidx.compose.ui.text.SpanStyle(color = Violet)) { append("build") }
                append("?")
            }, fontFamily = Heading, fontWeight = FontWeight.Bold, fontSize = 32.sp, lineHeight = 38.sp)
            Text("Describe it. VryxCode plans it, writes it, runs it and checks it, right here.", color = Emvryx.muted, fontSize = 16.sp)
            // The build box: the words, and the Build it button (it opens a new session and sends them).
            val shape = RoundedCornerShape(22.dp)
            Row(Modifier.fillMaxWidth().clip(shape).border(1.dp, Violet.copy(alpha = 0.4f), shape).padding(start = 16.dp, end = 8.dp, top = 8.dp, bottom = 8.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.weight(1f).heightIn(min = 52.dp, max = 160.dp).padding(end = 8.dp), contentAlignment = Alignment.CenterStart) {
                    if (vm.draft.isEmpty()) Text("A bill splitter with tip, a habit tracker, a snake game...", color = Emvryx.muted, fontSize = 16.sp)
                    BasicTextField(vm.draft, { vm.draft = it }, Modifier.fillMaxWidth(), textStyle = androidx.compose.ui.text.TextStyle(color = Emvryx.text, fontSize = 16.sp),
                        cursorBrush = SolidColor(Violet))
                }
                Box(Modifier.heightIn(min = 46.dp).clip(RoundedCornerShape(18.dp)).then(if (Emvryx.d27) Modifier.border(1.dp, d27Edge(), RoundedCornerShape(18.dp)) else Modifier.background(Violet)).clickable(enabled = vm.draft.isNotBlank()) {
                    val words = vm.draft
                    vm.draft = ""
                    vm.newSession()
                    vm.send(words)
                }.padding(horizontal = 20.dp), contentAlignment = Alignment.Center) { Text("Build it", color = if (Emvryx.d27) D27Amethyst else Color.White, fontWeight = FontWeight.SemiBold, fontSize = 16.sp) }
            }
            // Effort: how hard VryxCode thinks (only when it picks the model itself).
            if (vm.oneModel) {
                var open by remember { mutableStateOf(false) }
                val name = vm.info?.effort?.levels?.firstOrNull { it.id == vm.effort }?.name ?: "Balanced"
                Box {
                    Row(Modifier.clip(RoundedCornerShape(999.dp)).border(1.dp, Violet.copy(alpha = 0.4f), RoundedCornerShape(999.dp)).clickable { open = true }
                        .padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text("Effort  ", color = Emvryx.muted, fontSize = 15.sp)
                        Text(name, color = Violet, fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
                        Text("  ▾", color = Emvryx.muted, fontSize = 12.sp)
                    }
                    DropdownMenu(open, { open = false }, containerColor = Emvryx.surface) {
                        vm.info?.effort?.levels.orEmpty().forEach { l ->
                            DropdownMenuItem({ Column { Text(l.name, fontWeight = FontWeight.Bold); Text(l.note, color = Emvryx.muted, fontSize = 13.sp) } }, { vm.effort = l.id; open = false })
                        }
                    }
                }
            }
            // Where it builds: with the projects organizer a new idea gets its own project, unless the person chose this one.
            if (vm.projects) {
                if (vm.buildHere) Text(androidx.compose.ui.text.buildAnnotatedString {
                    append("Builds in ${vm.project} · ")
                    withStyle(androidx.compose.ui.text.SpanStyle(color = Violet, textDecoration = androidx.compose.ui.text.style.TextDecoration.Underline)) { append("a new project instead") }
                }, fontSize = 15.sp, color = Emvryx.muted, modifier = Modifier.clickable { vm.buildHere = false })
                else Text(androidx.compose.ui.text.buildAnnotatedString {
                    append("Builds in a new project · ")
                    withStyle(androidx.compose.ui.text.SpanStyle(color = Violet, textDecoration = androidx.compose.ui.text.style.TextDecoration.Underline)) { append("use ${vm.project} instead") }
                }, fontSize = 15.sp, color = Emvryx.muted, modifier = Modifier.clickable { vm.buildHere = true })
            }
            // The project starters, two to a row: tap one, say what you want, press Build it.
            if (vm.templates.isNotEmpty()) {
                Text("OR START FROM A TEMPLATE", color = Emvryx.muted, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.4.sp, modifier = Modifier.padding(top = 6.dp))
                vm.templates.chunked(2).forEach { pair ->
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
                        pair.forEach { t ->
                            val on = vm.template == t.id
                            val card = RoundedCornerShape(18.dp)
                            Column(Modifier.weight(1f).heightIn(min = 120.dp).clip(card).background(if (Emvryx.d27) D27Carbon else Emvryx.surface)
                                .then(if (Emvryx.d27 && !on) Modifier.border(1.dp, d27Edge(), card) else Modifier.border(1.dp, if (on) Violet else Emvryx.line, card))
                                .clickable { vm.template = if (on) null else t.id }.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                Text(t.icon, fontSize = 26.sp)
                                Text(t.name, fontWeight = FontWeight.SemiBold, fontSize = 17.sp)
                                Text(t.desc, color = Emvryx.muted, fontSize = 14.sp)
                            }
                        }
                        if (pair.size == 1) Spacer(Modifier.weight(1f))               // an odd last card keeps its half width
                    }
                }
            }
            if (vm.sessions.isNotEmpty()) Text("YOUR SESSIONS", color = Emvryx.muted, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.4.sp, modifier = Modifier.padding(top = 10.dp))
        }
    }
}

/** A small ⋯ button at the end of a session row: opens that session's menu */
@Composable
private fun MoreDots(onClick: () -> Unit) {
    Box(Modifier.size(32.dp).clip(CircleShape).clickable(onClick = onClick), contentAlignment = Alignment.Center) {
        Text("⋯", color = Emvryx.muted, fontSize = 18.sp)
    }
}

/**
 * vryxcode_archive: the end of the list. "Archived · N" opens or closes the sessions that were tucked away; each has a ⋯ with Restore and Delete.
 * Written as an extension of the list builder so both list layouts (the organizer and the plain one) can add it as their last items.
 */
private fun androidx.compose.foundation.lazy.LazyListScope.archivedBlock(vm: CodeViewModel) {
    if (!vm.archiveOn || vm.archived.isEmpty()) return
    item(key = "archived-head") {
        Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).clickable { vm.showArchived = !vm.showArchived }.padding(start = 6.dp, top = 16.dp, bottom = 8.dp),
            verticalAlignment = Alignment.CenterVertically) {
            Text("ARCHIVED · ${vm.archived.size}", color = Emvryx.muted, fontSize = 11.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.1.sp, modifier = Modifier.weight(1f))
            Text(if (vm.showArchived) "Hide" else "Show", color = Emvryx.muted, fontSize = 12.sp, modifier = Modifier.padding(end = 8.dp))
        }
    }
    if (vm.showArchived) items(vm.archived, key = { "archived-" + it.id }) { s ->
        Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).clickable { vm.openSession(s) }.padding(start = 8.dp, end = 8.dp, top = 9.dp, bottom = 9.dp),
            verticalAlignment = Alignment.CenterVertically) {
            Text(s.title.ifBlank { "Session" }, fontSize = 15.sp, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f), color = Emvryx.muted)
            Spacer(Modifier.width(8.dp))
            Text(s.age, color = Emvryx.muted, fontSize = 12.sp)
            MoreDots { vm.menuFor = s }
        }
    }
}

/** The menu of one session (vryxcode_archive): Archive (or Restore, in the Archived list), Delete for good (asks once more), Cancel */
@Composable
private fun SessionMenu(vm: CodeViewModel, s: CodeSessionRow) {
    // The second tap on Delete is the real one: the first only changes the words.
    var sure by remember(s.id) { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = { vm.menuFor = null }, containerColor = Emvryx.surface,
        title = { Text(s.title.ifBlank { "Session" }, maxLines = 2, overflow = TextOverflow.Ellipsis, fontSize = 17.sp) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(if (sure) "Delete this session and its history for good? Your project files are kept."
                     else if (s.archived) "It is in the Archived list. Restore it to put it back, or delete it for good."
                     else "Archive tucks it away (files and history are kept; find it under Archived at the bottom). Delete removes it for good.",
                    color = Emvryx.muted, fontSize = 14.sp)
            }
        },
        confirmButton = {
            Row {
                if (!sure) TextButton({ vm.archive(s, !s.archived) }) { Text(if (s.archived) "Restore" else "Archive") }
                TextButton({ if (sure) vm.deleteSession(s) else sure = true }) { Text(if (sure) "Yes, delete" else "Delete", color = Emvryx.danger) }
            }
        },
        dismissButton = { TextButton({ vm.menuFor = null }) { Text("Cancel", color = Emvryx.muted) } },
    )
}

// Starter ideas on the welcome page: a short name, then the full request that is put into the message box when tapped.
private val IDEAS = listOf(
    "A to-do list app" to "Build a small to-do list web app: add, tick off and delete tasks, saved in the browser.",
    "A landing page" to "Make a simple landing page for a bakery with a menu section and opening hours.",
    "Fix a failing test" to "Run the tests in this project, find what fails and fix it.",
)

/** The empty home and a new session: the mark, the question, and a few ideas to start from (tap one to put it in the box). [lead] is the line under the title. */
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
            // One tappable card per idea: start a session if none is open, then put the request text in the message box.
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

/** One session in the plain list: a coloured status dot and word, title, age, project/model/place, a snippet, and counts. [review] adds the +/- line counts. */
@Composable
private fun SessionCard(s: CodeSessionRow, review: Boolean, onMore: (() -> Unit)? = null, onClick: () -> Unit) {
    val shape = RoundedCornerShape(16.dp)
    Column(Modifier.fillMaxWidth().clip(shape).background(Emvryx.surface).border(1.dp, Emvryx.line, shape).clickable(onClick = onClick).padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            // Pick the dot colour and the status word from the state.
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
            if (onMore != null) MoreDots(onMore)                         // vryxcode_archive
        }
        Text(s.project + " · " + s.model + " · " + s.env, color = Emvryx.muted, fontSize = 13.sp, maxLines = 1)
        if (s.snippet.isNotBlank()) Text(s.snippet, color = Emvryx.muted, fontSize = 14.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
        // The small facts line; empty ones are left out (listOfNotNull drops the nulls).
        val stats = listOfNotNull(if (s.steps > 0) "${s.steps} steps" else null, if (s.files > 0) "${s.files} files changed" else null,
                                  if (s.state == "queued") "Queued #${s.position}" else null, if (s.state == "asking") "Needs you" else null)
        // Show the stats row only if there is something to show.
        if (stats.isNotEmpty() || (review && (s.added > 0 || s.removed > 0))) Row(verticalAlignment = Alignment.CenterVertically) {
            if (review && (s.added > 0 || s.removed > 0)) {                 // +52 −3, like Cursor
                Text("+${s.added}", color = Green, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
                Text(" −${s.removed}", color = Emvryx.danger, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.width(8.dp))
            }
            Text(stats.joinToString(" · "), color = if (s.state == "asking") Violet else Emvryx.muted, fontSize = 13.sp)
        }
    }
}

// ---------------------------------------------------------------- one session's work feed

/**
 * One session's work feed: the plan box, then every event the agent produced (steps, results, notes, its final summary),
 * then any open question for the person or a "Working…" line. It scrolls to the newest item by itself.
 */
@Composable
private fun Feed(vm: CodeViewModel) {
    // The scroll position, so we can move it.
    val list = rememberLazyListState()
    // Whenever a new event arrives or a question appears, scroll down to the end.
    LaunchedEffect(vm.events.size, vm.pending) { if (vm.events.isNotEmpty()) list.animateScrollToItem(vm.events.size) }
    // A brand-new session with nothing in it yet: show the welcome page.
    if (vm.events.isEmpty() && vm.sid == null) {
        Welcome(vm, "Describe one task. VryxCode reads, edits, runs the tests and tries again in its own project folder, and asks before it changes anything. Type / for commands.")
        return
    }
    // The agent's to-do list, when the taskbox part is on.
    val plan = if ("vryxcode_taskbox" in vm.parity) planSteps(vm.events, vm.working) else emptyList()
    LazyColumn(Modifier.fillMaxSize(), state = list, contentPadding = if (Emvryx.d27) PaddingValues(start = 14.dp, end = 14.dp, top = 14.dp, bottom = 200.dp) else PaddingValues(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        // design_2027: while a session spins up and nothing has come back yet, shimmering lines like a code block instead of an empty page
        if (Emvryx.d27 && vm.events.isEmpty() && vm.working) item(key = "skeleton") { D27Skeleton() }
        if (plan.isNotEmpty()) item { PlanBox(plan) }
        // Review view / Claude Code style lines: events are turned into richer items (quiet lines, file chips, a "Changed N files" summary).
        if (vm.review || "vryxcode_lines" in vm.parity) {
            // With the "lines" flag, runs of quiet steps are folded into one tappable line.
            val shown = reviewItems(vm.events).let { if ("vryxcode_lines" in vm.parity) foldQuiet(it) else it }
            items(shown.size) { i ->
                // Each item kind has its own look.
                when (val r = shown[i]) {
                    is ReviewItem.Quiet -> QuietLine(r)
                    is ReviewItem.Group -> GroupLine(r)
                    is ReviewItem.File -> FileChip(r)
                    is ReviewItem.Done -> DoneLine(r)
                    is ReviewItem.Event -> EventRow(r.e, vm.events, vm)
                }
            }
        } else items(vm.events.size) { i -> EventRow(vm.events[i], vm.events, vm) }
        item {
            // The bottom of the feed: a multiple-choice question, a permission question, or the live "Working…" line.
            val q = vm.pending
            when {
                q != null && q.str("tool") == "ask_user" -> ChoiceCard(vm, q)
                q != null -> AskCard(vm, q)
                vm.working -> WorkingLine(vm)
            }
        }
    }
}

/**
 * The working line under the newest step, like Claude's: the Emvryx E with its three dots, what it is running ("Running python test.py…") and the seconds, which tick on their own.
 * It is one fixed item in the feed, so nothing about it restarts or blinks between looks at the server.
 */
@Composable
private fun WorkingLine(vm: CodeViewModel) {
    val info = vm.liveInfo
    // A clock that ticks twice a second, so the seconds count up between looks at the server.
    var now by remember { mutableStateOf(android.os.SystemClock.elapsedRealtime()) }
    LaunchedEffect(Unit) { while (true) { kotlinx.coroutines.delay(500); now = android.os.SystemClock.elapsedRealtime() } }
    val secs = if (info != null && vm.liveAt != 0L) ((now - vm.liveAt) / 1000).toInt().coerceAtLeast(0) else 0
    val words = if (info != null) liveHeadline(info, secs, vm.stopping) else if (vm.stopping) "Stopping…" else "Working…"
    val tokens = info?.int("tokens") ?: 0
    Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        WorkingMark(22.dp)
        Text(words, color = Emvryx.muted, fontSize = 14.sp, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false))
        if (info != null) Text("${secs}s" + if (tokens > 0) "  ·  %,d tokens".format(tokens) else "", color = Emvryx.muted, fontSize = 13.sp)
    }
}

/**
 * One raw event of a session drawn as a row. [e] is the event (loose JSON, read with str/bool/int helpers), [all] is every event
 * (to find whether a question was answered), [vm] gives actions. Each `kind` of event looks different; unknown kinds draw nothing.
 */
@Composable
private fun EventRow(e: JsonObject, all: List<JsonObject>, vm: CodeViewModel) {
    val shape = RoundedCornerShape(14.dp)
    // Choose the look by the event's kind.
    when (e.str("kind")) {
        // What the person asked (shown unless it was sent automatically), with a Restore button on their messages.
        "start", "user" -> if (!e.bool("auto")) Row(Modifier.fillMaxWidth().then(if (Emvryx.d27) Modifier.d27Bubble(shape) else Modifier.clip(shape).background(Emvryx.surface2)).padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            Text((if (e.bool("plan")) "[Plan] " else "") + e.str("task").ifEmpty { e.str("text") } + (if (e.bool("steer")) "  (while it worked)" else ""),
                fontSize = 15.sp, color = d27Ink(Emvryx.text), modifier = Modifier.weight(1f))
            if ("vryxcode_restore" in vm.parity && e.int("turn") > 0) RestorePill(vm, e.int("turn"))
        }
        // A tool the agent used (such as writing a file): its name, how long it took, and a preview of what it did.
        "step" -> {
          // design_2027: a step is one quiet line (no box); a change's code opens only when the line is tapped
          var open by remember { mutableStateOf(!Emvryx.d27) }
          val inkTool = d27Ink(Emvryx.text)
          val preview = e.str("preview")
          Column(Modifier.fillMaxWidth().then(if (Emvryx.d27) Modifier.clip(RoundedCornerShape(8.dp)).clickable(enabled = preview.isNotBlank()) { open = !open }.padding(vertical = 3.dp, horizontal = 2.dp)
                  else Modifier.clip(shape).background(Emvryx.surface).border(1.dp, Emvryx.line, shape).padding(12.dp)),
            verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text((if (Emvryx.d27) "" else "● ") + e.str("tool"), color = if (Emvryx.d27) inkTool else Green, fontWeight = if (Emvryx.d27) FontWeight.Medium else FontWeight.SemiBold, fontSize = 14.sp)
                // how long the step took and the tokens it wrote, as on the website (ide.js: "3s · 1,234 tokens")
                val took = listOfNotNull(e.num("secs").takeIf { e.containsKey("secs") }?.let { "${Math.round(it)}s" },
                    e.int("words").takeIf { it > 0 }?.let { "%,d tokens".format(it) }).joinToString(" · ")
                if (took.isNotEmpty()) Text("   $took", color = Emvryx.muted, fontSize = 13.sp)
            }
            // A grey code-style preview, cut at 1,500 characters, that scrolls sideways.
            if (open && preview.isNotBlank()) Text(preview.take(1500), style = Mono, color = Emvryx.muted,
                modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(Emvryx.bg).horizontalScroll(rememberScrollState()).padding(10.dp))
          }
        }
        // The tool's output, cut to 600 characters and 8 lines.
        "result" -> Text("→ " + e.str("text").take(600), style = Mono, color = Emvryx.muted, maxLines = 8, overflow = TextOverflow.Ellipsis)
        // Small grey notices: a retry, a note, being queued, earlier steps summarised, the model changing, files rewound.
        "retry" -> Text("↻ " + e.str("why"), color = Emvryx.muted, fontSize = 13.sp)
        "note", "language" -> Text(e.str("text"), color = d27Ink(Emvryx.muted), fontSize = 14.sp)
        "queued" -> Text("Queued: it starts when the session before it finishes.", color = Emvryx.muted, fontSize = 14.sp)
        "compacted" -> Text("Summarized earlier steps to make room.", color = Emvryx.muted, fontSize = 13.sp)
        "model" -> Text("Now using ${e.str("model")}.", color = Emvryx.muted, fontSize = 13.sp)
        "rewind" -> Text("↶ Rewound the files to before: " + e.str("label"), color = Emvryx.muted, fontSize = 14.sp)
        // A question that has been answered leaves a short grey trace; one still open is drawn at the bottom of the feed instead.
        "ask", "choose" -> {
            val answered = all.any { it.str("kind") == "answer" && it.str("id") == e.str("id") }
            if (answered) Text(if (e.str("kind") == "choose") "Asked: " + e.str("question") else "Asked to use " + e.str("tool"), color = Emvryx.muted, fontSize = 13.sp)
        }
        // The option the person picked.
        "answer" -> if (e.str("choice").isNotEmpty()) Text("You chose: " + e.str("choice"), color = Violet, fontSize = 14.sp)
        // The end of a message: a summary card (violet when finished). The summary text is markdown, drawn block by block: text, code, or table.
        "end" -> Column(Modifier.fillMaxWidth().then(if (Emvryx.d27) Modifier.d27Card(shape).then(if (e.bool("finished")) Modifier.border(1.dp, D27Amethyst.copy(alpha = 0.35f), shape) else Modifier)
            else Modifier.clip(shape).background(if (e.bool("finished")) VioletSoft else Emvryx.surface).border(1.dp, if (e.bool("finished")) Violet else Emvryx.line, shape)).padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Markdown.blocks(e.str("summary").ifEmpty { if (e.bool("finished")) "Done." else "Stopped." }).forEach { b ->
                when (b) {
                    is Block.Prose -> Text(Markdown.inline(b.text), fontSize = 15.sp)
                    is Block.Code -> Text(b.text, style = Mono, modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(Emvryx.bg)
                        .horizontalScroll(rememberScrollState()).padding(10.dp))
                    is Block.Table -> MdTable(b)
                }
            }
            // Suggested next steps, then the verdict / Continue / Preview buttons.
            e.strings("next").forEach { Text("→ $it", color = Emvryx.muted, fontSize = 14.sp) }
            EndExtras(e, vm)
        }
        // Anything else is ignored.
        else -> Unit
    }
}

// ---------------------------------------------------------------- the website's newer parts (flag android_vryxcode; CodeParity.kt)

/** The flags of the parts the Android app can show, each still behind its own switch ("parity" = the app matching the website) */
private val PARITY_FLAGS = listOf("vryxcode_restore", "vryxcode_taskbox", "vryxcode_autocontinue", "vryxcode_guardrails", "vryxcode_lines",
                                  "vryxcode_preview", "vryxcode_servers", "vryxcode_github", "vryxcode_publish")

/** The plan as a box, like Claude Code's: a ticked circle when done, a ring on the step it is doing, a dashed one on the steps to come */
@Composable
private fun PlanBox(steps: List<PlanStep>) {
    val shape = RoundedCornerShape(14.dp)
    Column(Modifier.fillMaxWidth().clip(shape).border(1.dp, Emvryx.line, shape).padding(horizontal = 14.dp, vertical = 12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        steps.forEach { st ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                // The mark in front of each step by its state.
                Text(when (st.state) { "done" -> "✓"; "now" -> "○"; else -> "◌" }, color = if (st.state == "now") Emvryx.text else Emvryx.muted,
                    fontSize = 14.sp, fontWeight = FontWeight.Bold, modifier = Modifier.width(22.dp))
                Text(st.text, fontSize = 14.sp, color = if (st.state == "done") Emvryx.muted else Emvryx.text)
            }
        }
    }
}

/** Quiet steps in a row as one line: "Read 3 files, ran 2 commands ›", opening to each one when tapped. A red cross shows if any of them failed. */
@Composable
private fun GroupLine(g: ReviewItem.Group) {
    var open by remember { mutableStateOf(false) }
    val bad = g.lines.any { it.bad }
    Column(Modifier.padding(horizontal = 4.dp).clickable { open = !open }) {
        Text((if (bad) "✗ " else "") + groupTitle(g) + if (open) "  ⌄" else "  ›", color = if (bad) Emvryx.danger else d27Ink(Emvryx.muted), fontSize = 13.sp)
        if (open) g.lines.forEach { QuietLine(it) }
    }
}

/** Restore on one of your messages: the files go back to just before it, after a yes. [turn] is the message's number. Disabled while the agent is working. */
@Composable
private fun RestorePill(vm: CodeViewModel, turn: Int) {
    var ask by remember { mutableStateOf(false) }
    Text("↶ Restore", fontSize = 12.sp, color = Emvryx.muted, modifier = Modifier.clip(CircleShape).border(1.dp, Emvryx.line, CircleShape)
        .clickable(enabled = !vm.working) { ask = true }.padding(horizontal = 10.dp, vertical = 6.dp))
    // The confirm dialog (a Restore removes files made after that message, so it asks first).
    if (ask) AlertDialog(onDismissRequest = { ask = false }, containerColor = Emvryx.surface,
        title = { Text("Restore the files?") }, text = { Text("The project goes back to how it was just before this message. Files made after it are removed.") },
        confirmButton = { TextButton({ ask = false; vm.restore(turn) }) { Text("Restore", color = Violet) } },
        dismissButton = { TextButton({ ask = false }) { Text("Cancel", color = Emvryx.muted) } })
}

/** Under a message's end: the review verdict with Fix them, the plain Done / Not finished line, and Preview, Save to GitHub and Publish. [e] is the end event. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun EndExtras(e: JsonObject, vm: CodeViewModel) {
    // Which optional parts are switched on.
    val on = vm.parity
    // Guardrails: the reviewer's verdict. Approved, or how many serious problems there are and a button to fix them test-first.
    if ("vryxcode_guardrails" in on) verdictOf(e)?.let { v ->
        Text(if (v.approved) "✓ Approved" + (if (v.nits > 0) " · ${v.nits} small style note" + (if (v.nits == 1) "" else "s") + ", not worked on" else " · nothing to fix")
             else "${v.blocking} serious problem" + (if (v.blocking == 1) "" else "s") + " · each one proved with a failing test before it is fixed",
            color = if (v.approved) Green else Emvryx.danger, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
        if (!v.approved && v.fix.isNotBlank()) SmallPill("Fix them, test first") { vm.send(v.fix) }
    }
    // Auto-continue: say clearly if the task finished, is waiting for you, or ran out of steps (with a Continue button).
    if ("vryxcode_autocontinue" in on) when (val st = endState(e)) {
        EndState.Finished -> Text("✓ Done: the task is finished", color = Green, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
        EndState.Waiting -> {
            val answered = justAnswered(e, vm.events)          // it only explained what the person asked: an answer, not a task waiting for them
            if (!answered) Text("● Not finished yet: it is waiting for your answer", color = Violet, fontSize = 14.sp)
            // say what you could answer: one tap sends it (the first one is also greyed in the message box)
            val replies = if (answered) followUps(lastAsked(vm.events, e), e.str("summary")) else waitingReplies(e.str("summary"))
            if (replies.isNotEmpty()) Text(if (answered) "You could ask:" else "You could answer:", color = Emvryx.muted, fontSize = 13.sp)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                replies.forEach { r ->
                    SmallPill(r) {
                        // "Show me what you changed." needs no model: the changes are opened on screen (the website does the same)
                        if (r.startsWith("Show me what you changed")) vm.onWeb?.invoke("VryxCode", editorJs(vm).removeSuffix(" })") + "; setTimeout(() => showDrawer(true, 'changes'), 1500); })")
                        else vm.send(r)
                    }
                }
            }
        }
        is EndState.OutOfSteps -> {
            Text("■ Not finished: it used all its steps" + (if (st.rounds > 0) " and carried on ${st.rounds} time" + (if (st.rounds == 1) "" else "s") + " by itself" else "") +
                ". Your files so far are kept.", fontSize = 14.sp)
            SmallPill("Continue") { vm.send("Carry on from where you stopped and finish the task.") }
        }
        null -> Unit
    }
    // The buttons below only make sense for a finished task.
    if (!e.bool("finished")) return
    // The script that opens the website's editor on this project.
    val js = editorJs(vm)
    // Each button: a label and the website function it calls. takeIf keeps it only when its flag is on.
    val pills = listOfNotNull(
        ("▶ Preview" to "openPreview()").takeIf { "vryxcode_preview" in on || "vryxcode_servers" in on },
        ("↑ Save to GitHub" to "saveToGithub()").takeIf { "vryxcode_github" in on },
        ("🌐 Publish" to "publishSite()").takeIf { "vryxcode_publish" in on },
    )
    if (pills.isNotEmpty()) FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        // Open the website editor, then 1.5 s later call the function (the delay lets the page finish loading). removeSuffix cuts the closing " })" so the call can be added inside it.
        pills.forEach { (label, call) -> SmallPill(label) { vm.onWeb?.invoke("VryxCode", js.removeSuffix(" })") + "; setTimeout(() => $call, 1500); })") } }
    }
}

// ---------------------------------------------------------------- the review view (flag vryxcode_review), like Cursor's

/** Looking around: a quiet grey line; a red mark and the first line of why when it went wrong */
@Composable
private fun QuietLine(r: ReviewItem.Quiet) {
    Column(Modifier.padding(horizontal = 4.dp)) {
        Text((if (r.bad) "✗ " else "") + r.text, color = if (r.bad) Emvryx.danger else d27Ink(Emvryx.muted), fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
        if (r.why.isNotBlank()) Text(r.why, color = Emvryx.muted, fontSize = 12.sp, style = Mono, maxLines = 2)
    }
}

/** A change: "📄 app/page.tsx  +52 −0"; tap it to see the lines */
@Composable
private fun FileChip(r: ReviewItem.File) {
    var open by remember { mutableStateOf(false) }
    val shape = RoundedCornerShape(12.dp)
    // A card with a red outline if the change failed; tapping opens or closes the diff (only when there are lines to show).
    Column(Modifier.fillMaxWidth().then(if (Emvryx.d27) Modifier.clip(RoundedCornerShape(8.dp)).then(if (r.bad) Modifier.border(1.dp, Emvryx.danger.copy(alpha = 0.6f), RoundedCornerShape(8.dp)) else Modifier)     // design_2027: a quiet row, no box
            else Modifier.clip(shape).background(Emvryx.surface).border(1.dp, if (r.bad) Emvryx.danger.copy(alpha = 0.6f) else Emvryx.line, shape))
        .clickable(enabled = r.diff.isNotEmpty()) { open = !open }.padding(horizontal = 12.dp, vertical = 10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            PwaIcon("doc", Emvryx.muted, 16.dp)
            Spacer(Modifier.width(8.dp))
            Text(r.path, style = Mono, color = d27Ink(Emvryx.text), fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
            Text("+${r.add}", color = Green, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
            Text(" −${r.del}", color = Emvryx.danger, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
        }
        if (r.why.isNotBlank()) Text(r.why, color = Emvryx.danger, fontSize = 12.sp, style = Mono, maxLines = 2)
        // The diff: the first 200 lines, green for added, red for removed, grey for unchanged context.
        if (open) Column(Modifier.padding(top = 8.dp).fillMaxWidth().clip(RoundedCornerShape(8.dp)).background(Emvryx.bg).horizontalScroll(rememberScrollState()).padding(8.dp)) {
            r.diff.take(200).forEach { l ->
                Text(l.text, style = Mono, fontSize = 12.sp, color = when (l.kind) { '+' -> Green; '-' -> Emvryx.danger; else -> Emvryx.muted })
            }
        }
    }
}

/** The end of a message: "Changed 3 files  +60 −4" and each file */
@Composable
private fun DoneLine(r: ReviewItem.Done) {
    val shape = RoundedCornerShape(14.dp)
    Column(Modifier.fillMaxWidth().then(if (Emvryx.d27) Modifier else Modifier.clip(shape).background(Emvryx.surface).border(1.dp, Emvryx.line, shape)).padding(if (Emvryx.d27) 2.dp else 12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Changed ${r.files.size} " + if (r.files.size == 1) "file" else "files", fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
            Spacer(Modifier.width(8.dp))
            Text("+${r.add}", color = Green, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
            Text(" −${r.del}", color = Emvryx.danger, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
        }
        // One line per file: path, lines added, lines removed.
        r.files.forEach { (p, a, dl) ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(p, style = Mono, fontSize = 12.sp, color = Emvryx.muted, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                Text("+$a", color = Green, fontSize = 12.sp)
                Text(" −$dl", color = Emvryx.danger, fontSize = 12.sp)
            }
        }
    }
}

/** "Allow this?": the change or command it wants to make, then Yes / Yes and don't ask again / No. The preview is cut at 2,500 characters. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun AskCard(vm: CodeViewModel, q: JsonObject) {
    val shape = RoundedCornerShape(16.dp)
    Column(Modifier.fillMaxWidth().then(if (Emvryx.d27) Modifier.d27Card(shape) else Modifier.clip(shape).background(Emvryx.surface).border(1.dp, Violet, shape)).padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("Allow this?", fontWeight = FontWeight.Bold, fontSize = 17.sp)
        Text(q.str("preview").take(2500), style = Mono, color = Emvryx.muted,
            modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(Emvryx.bg).horizontalScroll(rememberScrollState()).padding(10.dp))
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (Emvryx.d27) {                                                          // design_2027: hollow ghost answers, the first one with a soft ring
                D27GhostAnswer("Yes", { vm.answer(true) }, main = true)
                D27GhostAnswer("Yes, and don't ask again for this", { vm.answer(true, always = true) })
                D27GhostAnswer("No", { vm.answer(false) })
            } else {
                PwaButton("Yes", { vm.answer(true) })
                Chip("Yes, and don't ask again for this", { vm.answer(true, always = true) })
                Chip("No", { vm.answer(false) })
            }
        }
    }
}

/** The full agent's multiple-choice question: one tap answers, or write your own */
@Composable
private fun ChoiceCard(vm: CodeViewModel, q: JsonObject) {
    // The typed answer; `remember(q.str("id"))` starts it empty again for each new question.
    var own by remember(q.str("id")) { mutableStateOf("") }
    val shape = RoundedCornerShape(16.dp)
    Column(Modifier.fillMaxWidth().then(if (Emvryx.d27) Modifier.d27Card(shape) else Modifier.clip(shape).background(Emvryx.surface).border(1.dp, Violet, shape)).padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
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

/**
 * The message box at the bottom: slash-command menu, attached pictures/files, the "where to build" line, the text field with a greyed
 * suggested reply, the pick buttons (add file, model or effort, mode, place), Stop/Send, and the usage line.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun CodeComposer(vm: CodeViewModel) {
    val context = LocalContext.current
    // The text box content as a TextFieldValue (text plus cursor position), so the cursor can be put at the end after filling it in.
    var field by remember { mutableStateOf(TextFieldValue("")) }
    val text = field.text
    // fill(t): replace the box text with t and put the cursor at its end.
    val fill = { t: String -> field = TextFieldValue(t, TextRange(t.length)) }
    // Take the suggested reply into the box if the box is empty. Returns true if it did (so Tab/swipe know they were used).
    val takeOffer = { if (text.isEmpty() && vm.offer.isNotEmpty()) { fill(vm.offer); vm.offer = ""; true } else false }
    // When an idea is tapped on the welcome page it arrives in vm.draft: move it into the box and clear it.
    LaunchedEffect(vm.draft) { if (vm.draft.isNotEmpty()) { fill(vm.draft); vm.draft = "" } }      // an idea tapped on the welcome
    // Which dropdown is open: "add", "pick", "mode", "env", or none.
    var menu by remember { mutableStateOf<String?>(null) }
    // The system pickers: pictures (up to 3) and documents (up to 8). Each chosen item is read into bytes and attached to the message.
    val pick = rememberLauncherForActivityResult(ActivityResultContracts.PickMultipleVisualMedia(3)) { uris ->
        uris.forEach { u -> readPicked(context, u)?.let { (n, b) -> vm.addPicture(n, b) } }
    }
    val pickDoc = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        uris.take(8).forEach { u -> readPicked(context, u)?.let { (n, b) -> vm.addDoc(n, b) } }
    }
    // (Two Columns: the outer one lifts the whole box above the phone's navigation bar; the inner one is the rounded card.)
    val shape = RoundedCornerShape(22.dp)
    Column(Modifier.fillMaxWidth().navigationBarsPadding()) {
    Column(
        (if (Emvryx.d27) Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 8.dp).clip(RoundedCornerShape(26.dp)).background(D27Bar)      // design_2027: frosted carbon glass with a lit top edge
            .border(1.dp, d27Edge(), RoundedCornerShape(26.dp))
         else Modifier.fillMaxWidth().padding(start = 12.dp, end = 12.dp, top = 12.dp, bottom = 8.dp).clip(shape).background(Emvryx.surface).border(1.dp, Violet.copy(alpha = 0.6f), shape))
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        if (text.startsWith("/") && !text.contains(' ')) {         // the / menu: the app's commands and this project's own
            // The / menu, shown while the text is just a slash command being typed (no space yet).
            // Matching built-in commands plus this project's own ones (from its commands file), filtered by what is typed; at most 8 are shown.
            val items = SLASH.filter { it.first.startsWith(text.lowercase()) } + vm.commands.map { "/" + it.name to it.about.ifBlank { "This project's own command" } }
                .filter { it.first.startsWith(text.lowercase()) }
            items.take(8).forEach { (c, about) ->
                Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).clickable { fill("$c ") }.padding(6.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text(c, style = Mono, color = Violet)
                    Text(about, color = Emvryx.muted, fontSize = 13.sp, maxLines = 2)
                }
            }
        }
        // Attached pictures and files waiting to be sent; tapping a chip removes it.
        if (vm.pictures.isNotEmpty() || vm.docs.isNotEmpty()) FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            vm.pictures.forEachIndexed { i, _ -> Chip("🖼 Picture ${i + 1} ×", { vm.pictures.removeAt(i) }) }
            vm.docs.forEachIndexed { i, dc -> Chip("📄 ${dc.name} ×", { vm.docs.removeAt(i) }) }
        }
        if (vm.projects && vm.sid == null) {                          // vryxcode_projects: where this idea will be built, and the other choice
            // Where a brand-new idea will be built: in this project, or in a new one named from the idea; the violet text switches between the two.
            val here = vm.buildHere
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(if (here) "Builds in ${vm.project}" else "Builds in a new project" + if (text.isNotBlank()) ": " + vm.whereFor(text) else "",
                    color = Emvryx.muted, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false))
                Text(if (here) " · use a new project" else " · use ${vm.project}", color = Violet, fontSize = 13.sp, maxLines = 1,
                    modifier = Modifier.clip(CircleShape).clickable { vm.buildHere = !here }.padding(horizontal = 4.dp, vertical = 2.dp))
            }
        }
        // the suggested reply (flag vryxcode_suggest): greyed in the empty box; a swipe right across the box, or Tab on a keyboard, fills it in
        Box(Modifier.fillMaxWidth().heightIn(min = 24.dp, max = 160.dp).swipeRight { takeOffer() }) {
            // The grey hint: the suggested reply if there is one, otherwise a prompt that fits the situation.
            if (text.isEmpty()) Text(vm.offer.ifEmpty { if (vm.working && vm.full) "Tell it something while it works…" else "Ask, answer, or tell VryxCode what to build or fix" },
                color = Emvryx.muted, style = MaterialTheme.typography.bodyLarge)
            // The real text input. Pressing Tab on a hardware keyboard takes the suggestion (onPreviewKeyEvent sees the key first).
            BasicTextField(field, { field = it }, Modifier.fillMaxWidth().onPreviewKeyEvent { it.key == Key.Tab && it.type == KeyEventType.KeyDown && takeOffer() },
                textStyle = MaterialTheme.typography.bodyLarge.copy(color = Emvryx.text), cursorBrush = SolidColor(Violet))
        }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Box {
                // The + button: with the review view on it opens a menu (picture or document); otherwise it goes straight to the picture picker.
                IconButton({
                    if (vm.review) menu = "add" else pick.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
                }, Modifier.size(40.dp)) { Icon(Icons.Default.Add, "Add a screenshot or a document", tint = Emvryx.muted) }
                DropdownMenu(menu == "add", { menu = null }, containerColor = Emvryx.surface) {
                    DropdownMenuItem({ Text("Screenshot or picture") }, { menu = null; pick.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) })
                    // The accepted document types: PDF, Word (.docx), any text, and JSON.
                    DropdownMenuItem({ Column { Text("Document"); Text("PDF, Word or text, like a spec. Read first.", color = Emvryx.muted, fontSize = 12.sp) } },
                        { menu = null; pickDoc.launch(arrayOf("application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "text/*", "application/json")) })
                }
            }
            Row(Modifier.weight(1f).horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {     // full names; scrolls only if they do not fit
            Box {
                // The model button shows the effort level when VryxCode picks the model itself, otherwise the chosen model's name.
                val effortName = vm.info?.effort?.levels?.firstOrNull { it.id == vm.effort }?.name ?: "Balanced"
                val label = if (vm.oneModel) effortName else vm.info?.models?.firstOrNull { it.id == vm.model }?.label ?: "Model"
                SmallPill(label + " ▾") { menu = "pick" }
                DropdownMenu(menu == "pick", { menu = null }, containerColor = Emvryx.surface) {
                    // The menu lists effort levels, or models (a model that is not ready is greyed out).
                    if (vm.oneModel) vm.info?.effort?.levels.orEmpty().forEach { l ->
                        DropdownMenuItem({ Column { Text(l.name, fontWeight = FontWeight.Bold); Text(l.note, color = Emvryx.muted, fontSize = 13.sp) } }, { vm.effort = l.id; menu = null })
                    } else vm.info?.models.orEmpty().forEach { m ->
                        DropdownMenuItem({ Text(m.label.ifEmpty { m.name }) }, { vm.model = m.id; menu = null }, enabled = m.ready)
                    }
                }
            }
            Box {
                // The mode button: Ask (ask before editing), Auto (edit without asking), Plan (plan first).
                SmallPill(when (vm.mode) { "auto" -> "Auto"; "plan" -> "Plan"; else -> "Ask" } + " ▾") { menu = "mode" }
                DropdownMenu(menu == "mode", { menu = null }, containerColor = Emvryx.surface) {
                    MODES.forEach { (id, name) -> DropdownMenuItem({ Text(name) }, { vm.mode = id; menu = null }) }
                }
            }
            // The place to run (only for a new session): this computer, Docker, the cloud machine...; unavailable ones are greyed out.
            if (vm.sid == null) Box {
                SmallPill((vm.info?.environments?.firstOrNull { it.id == vm.env }?.name ?: "This computer") + " ▾") { menu = "env" }
                DropdownMenu(menu == "env", { menu = null }, containerColor = Emvryx.surface) {
                    vm.info?.environments.orEmpty().forEach { e -> DropdownMenuItem({ Text(e.name) }, { vm.env = e.id; menu = null }, enabled = e.available) }
                }
            }
            }
            // design_2027: the same glowing ring as in chat: Stop while it works, Send (also during a run if this agent can take messages) otherwise
            if (Emvryx.d27) {
                if (vm.working) SendButton(true, true) { vm.stop() }
                if (!vm.working || vm.full) SendButton(false, text.isNotBlank() || vm.pictures.isNotEmpty() || vm.docs.isNotEmpty()) { vm.send(text); fill("") }
            } else {
            // While it works: a red Stop square.
            if (vm.working) Box(Modifier.size(42.dp).clip(RoundedCornerShape(12.dp)).background(Emvryx.danger).clickable { vm.stop() }, contentAlignment = Alignment.Center) {
                Box(Modifier.size(12.dp).background(Color.White))
            }
            // The Send arrow; it also stays during a run if this agent can take messages while it works. Disabled with nothing to send.
            if (!vm.working || vm.full) Box(
                Modifier.size(42.dp).clip(RoundedCornerShape(12.dp)).background(Violet).clickable(enabled = text.isNotBlank() || vm.pictures.isNotEmpty() || vm.docs.isNotEmpty()) {
                    vm.send(text)
                    fill("")
                },
                contentAlignment = Alignment.Center,
            ) { Text("↑", color = Color.White, fontWeight = FontWeight.Bold, fontSize = 20.sp) }
            }
        }
    }
    // the usage line under the box (index.html #codeUsage): plan, how much is left and about how many coding steps that is
    vm.usage?.let { u ->
        // "Low" turns the bar and text red at 20% or less (owners have no limit).
        val low = !u.exempt && u.tankPct <= 20
        Column(Modifier.fillMaxWidth().padding(bottom = 6.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(5.dp)) {
            // A thin bar: the grey track with a filled part inside, as wide as the percent left.
            if (!u.exempt) Box(Modifier.width(200.dp).height(4.dp).clip(CircleShape).background(Emvryx.surface2)) {
                Box(Modifier.fillMaxHeight().fillMaxWidth(u.tankPct.coerceIn(0, 100) / 100f).clip(CircleShape).background(if (low) Emvryx.danger else Violet))
            }
            Text(u.label, color = if (low) Emvryx.danger else Emvryx.muted, fontSize = 13.sp)
        }
    }
    }
}

/**
 * A swipe to the right across this area (watched before the text box sees it, so typing and selecting still work).
 * `Modifier` is how Compose attaches behaviour to a piece of screen; this adds a custom touch listener.
 */
private fun Modifier.swipeRight(onSwipe: () -> Unit): Modifier = pointerInput(Unit) {
    // Watch each touch from finger-down to finger-up.
    awaitEachGesture {
        // PointerEventPass.Initial means we see the touch before the children do and do not consume it.
        val down = awaitFirstDown(requireUnconsumed = false, pass = PointerEventPass.Initial)
        // Follow the finger, remembering the last place it was, until it lifts.
        var last = down.position
        while (true) {
            val change = awaitPointerEvent(PointerEventPass.Initial).changes.firstOrNull { it.id == down.id } ?: break
            last = change.position
            if (!change.pressed) break
        }
        // A swipe = moved right more than 60dp and strayed up or down by less than 40dp (toPx converts dp to real pixels).
        if (last.x - down.position.x > 60.dp.toPx() && abs(last.y - down.position.y) < 40.dp.toPx()) onSwipe()
    }
}

/** A small outlined button-like label, used for the pick buttons and actions. */
@Composable
private fun SmallPill(text: String, onClick: () -> Unit) {
    Text(text, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis,
        modifier = Modifier.clip(CircleShape).border(1.dp, Emvryx.line, CircleShape).clickable(onClick = onClick).padding(horizontal = 12.dp, vertical = 10.dp))
}

// ---------------------------------------------------------------- /memory and /permissions

/** "What VryxCode remembers": the saved notes, each with Forget, plus Forget all. */
@Composable
private fun MemoryDialog(vm: CodeViewModel, notes: List<String>) {
    AlertDialog(
        onDismissRequest = vm::closeMemory, containerColor = Emvryx.surface,
        title = { Text("What VryxCode remembers") },
        text = {
            Column(Modifier.heightIn(max = 420.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Short notes it saved about you and how you like to work. It reads them at the start of every session.", color = Emvryx.muted, fontSize = 14.sp)
                if (notes.isEmpty()) Text("Nothing yet.")
                // One row per note; Forget removes that note by its position.
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

/** This project's permission rules: what is always allowed and what is never allowed; "Never" wins. Rules can be removed or added. */
@Composable
private fun RulesDialog(vm: CodeViewModel) {
    // No rules loaded: draw nothing.
    val r = vm.rules ?: return
    var rule by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = vm::closeRules, containerColor = Emvryx.surface,
        title = { Text("Permission rules for ${vm.project}") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("A rule is the start of a command (npm test) or a tool (write_file). \"Never\" wins.", color = Emvryx.muted, fontSize = 14.sp)
                // Two lists with the same layout: the allow rules and the deny rules.
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
                // Type a rule (the start of a command or a tool name) and add it to either list.
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
