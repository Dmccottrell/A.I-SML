// The app's own (native) settings-type screens: Memory, Documents, Skills, Settings (plus Admin and Scheduled tasks, drawn in other files).
// "Native" means drawn by the app itself with Jetpack Compose (functions marked @Composable that describe the screen and redraw when data changes),
// instead of loading the website in a WebView. Each pane loads its data from the server, shows it, and sends changes back.
// Variables made with `remember { mutableStateOf(...) }` hold screen state: changing one redraws the parts of the screen that read it.
package app.emvryx.android.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.emvryx.android.EmvryxApp
import app.emvryx.android.data.ApiClient
import app.emvryx.android.data.DocList
import app.emvryx.android.data.MemoryList
import app.emvryx.android.data.SettingsData
import app.emvryx.android.data.Skill
import app.emvryx.android.data.docSize
import app.emvryx.android.ui.theme.Emvryx
import app.emvryx.android.ui.theme.LocalPalette
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * The app's own screens for Memory, Files, Skills and Settings (feature flag android_native), instead of the website's panels in a WebView:
 * they open at once, follow the app's theme, and never show a black page when the PC is slow. They make the same calls as the website.
 * Everything else in Settings (connected apps, data controls, the Android app link) is one tap away under "More settings".
 */
@Composable
fun NativeScreen(vm: AppViewModel, kind: String) {
    // The phone's Back button leaves this panel.
    BackHandler { vm.backFromPanel() }
    // The top bar title for this kind of screen (a fallback of "Emvryx" if the kind is unknown).
    val title = NATIVE_TITLES[kind] ?: "Emvryx"
    // Page layout: a top bar (back arrow and title, kept below the status bar) above the content area.
    Column(Modifier.fillMaxSize().background(Emvryx.bg)) {
        Column(Modifier.statusBarsPadding()) {
            Row(Modifier.fillMaxWidth().height(56.dp).padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = vm::backFromPanel) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = Emvryx.text) }
                Text(title, fontWeight = FontWeight.SemiBold, fontSize = 17.sp)
            }
            HorizontalDivider(color = Emvryx.line)
        }
        // The content area takes the rest of the height; which pane to draw depends on [kind].
        Box(Modifier.weight(1f).fillMaxWidth().navigationBarsPadding()) {
            when (kind) {
                "memory" -> MemoryPane(vm)
                "files" -> FilesPane(vm)
                "skills" -> SkillsPane(vm)
                "admin" -> AdminPane(vm)
                "schedules" -> SchedulesPane(vm)
                else -> SettingsPane(vm)
            }
        }
    }
}

// Screen kind -> title shown in the top bar.
val NATIVE_TITLES = mapOf("memory" to "Memory", "files" to "Documents", "skills" to "Skills", "settings" to "Settings", "admin" to "Admin", "schedules" to "Scheduled tasks")

/** Loads [what] once (and again when [reload] changes); shows a spinner, then the content or the error with Try again */
// How it works: `what` is a function run on the API client (e.g. { memory() }) that returns the data of type T. T is a "generic" placeholder
// for whatever kind of data that is. `content` is the screen to draw once the data arrived.
@Composable
private fun <T> Loaded(vm: AppViewModel, reload: Int, what: suspend ApiClient.() -> T, retry: () -> Unit, content: @Composable (T) -> Unit) {
    val api = (LocalContext.current.applicationContext as EmvryxApp).api
    // `got` = the data once loaded (null until then); `error` = a plain-words problem message, or null.
    var got by remember { mutableStateOf<T?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    // Runs in the background when the screen appears, and again each time `reload` changes (the Try again button bumps it).
    LaunchedEffect(reload) {
        error = null
        try {
            got = api.what()
        } catch (e: Exception) {
            // If the failure means the person was signed out, handleSignedOut deals with it; otherwise show the error text.
            if (!vm.handleSignedOut(e)) error = vm.describe(e)
        }
    }
    // Pick what to show: the content when loaded, the error with Try again, or a small spinner while waiting.
    val v = got
    when {
        v != null -> content(v)
        error != null -> Problem(error!!, retry)
        else -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 2.dp, color = LocalPalette.current.accent)
        }
    }
}

/** What went wrong, and Try again: never a blank or black page */
@Composable
fun Problem(message: String, retry: () -> Unit, back: (() -> Unit)? = null) {
    // Centred column: logo, the message, Try again, and (when [back] is given) a Back to the chat button.
    Box(Modifier.fillMaxSize().padding(28.dp), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Logo(Modifier.size(48.dp))
            Text(message, color = Emvryx.muted, fontSize = 16.sp)
            PwaButton("Try again", retry, Modifier.fillMaxWidth())
            if (back != null) PwaButton("Back to the chat", back, Modifier.fillMaxWidth(), ghost = true)
        }
    }
}

/** A small grey all-capitals heading that starts a group of settings. */
@Composable
private fun Section(text: String) {
    Text(text.uppercase(), color = Emvryx.muted.copy(alpha = 0.8f), fontSize = 11.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.1.sp,
        modifier = Modifier.padding(start = 4.dp, top = 18.dp, bottom = 6.dp))
}

/** A rounded grey box that holds a group of related controls ([content] is what goes inside). */
@Composable
private fun Card(content: @Composable () -> Unit) {
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(Emvryx.surface).padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        content()
    }
}

// ---------------------------------------------------------------- Memory: what Emvryx remembers about you (web/js/settings.js openMemory)

/**
 * The Memory screen: shows the facts Emvryx remembers about the person, lets them add a fact, delete one or forget all.
 * [vm] is the app's shared data holder (used for navigation and error handling).
 */
@Composable
private fun MemoryPane(vm: AppViewModel) {
    // Screen state: `reload` is bumped to load again; `list` is the newest copy of the facts after a change (null = still use the first load);
    // `text` is what is typed in the box; `note` is an error message; `clearing` shows the "Forget everything?" dialog.
    var reload by remember { mutableIntStateOf(0) }
    val api = (LocalContext.current.applicationContext as EmvryxApp).api
    val scope = rememberCoroutineScope()
    var list by remember { mutableStateOf<MemoryList?>(null) }
    var text by remember { mutableStateOf("") }
    var note by remember { mutableStateOf<String?>(null) }
    var clearing by remember { mutableStateOf(false) }
    // Helper: run an action in the background (a coroutine), clearing the old message first, and show any error. `scope` ties it to this screen's life.
    fun act(block: suspend () -> Unit) = scope.launch {
        note = null
        try { block() } catch (e: Exception) { if (!vm.handleSignedOut(e)) note = vm.describe(e) }
    }
    // Load the facts; `first` is the loaded data.
    Loaded(vm, reload, { memory() }, { reload++ }) { first ->
        // Use the updated list if we changed something, otherwise what was first loaded.
        val m = list ?: first
        // LazyColumn is a scrolling list that draws only the rows on screen.
        LazyColumn(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
            item {
                Text(if (m.on) "Facts you tell Emvryx are kept here and given to whichever model you talk to. Private chats never save or read them."
                     else "Memory is off (Settings > Remember things about me): nothing new is kept.",
                    color = Emvryx.muted, fontSize = 14.sp, modifier = Modifier.padding(top = 14.dp))
                Spacer(Modifier.height(12.dp))
                Field("Add a fact", text, { text = it }, placeholder = "I live in Leeds and have two cats")
                Spacer(Modifier.height(8.dp))
                // Save the typed fact (trimmed); the server replies with the new list, which we keep, then clear the box.
                PwaButton("Remember this", { val t = text.trim(); if (t.isNotEmpty()) act { list = api.memoryAdd(t).copy(on = m.on); text = "" } },
                    Modifier.fillMaxWidth(), enabled = text.isNotBlank())
                note?.let { Text(it, color = Emvryx.muted, fontSize = 14.sp, modifier = Modifier.padding(top = 8.dp)) }
                Section(if (m.facts.isEmpty()) "Nothing remembered yet" else "${m.facts.size} remembered")
            }
            // One row per remembered fact; `key` (the fact's id) lets the list keep rows steady when items change.
            items(m.facts, key = { it.id }) { f ->
                Row(Modifier.fillMaxWidth().padding(vertical = 4.dp).clip(RoundedCornerShape(12.dp)).background(Emvryx.surface).padding(start = 14.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    Text(f.text, Modifier.weight(1f).padding(vertical = 12.dp), fontSize = 15.sp)
                    // Delete on the server, then remove it from the list on screen without reloading.
                    TextButton(onClick = { act { api.memoryDelete(f.id); list = m.copy(facts = m.facts.filter { it.id != f.id }) } }) {
                        Text("Delete", color = Emvryx.muted)
                    }
                }
            }
            // "Forget everything" is offered only when there is something to forget; it opens the confirmation dialog.
            if (m.facts.isNotEmpty()) item {
                Spacer(Modifier.height(10.dp))
                PwaButton("Forget everything", { clearing = true }, Modifier.fillMaxWidth(), ghost = true)
                Spacer(Modifier.height(20.dp))
            }
        }
        // The confirmation pop-up for forgetting everything.
        if (clearing) AlertDialog(
            onDismissRequest = { clearing = false },
            containerColor = Emvryx.surface,
            title = { Text("Forget everything?") },
            text = { Text("Emvryx forgets every fact above. Your chats are not deleted.") },
            confirmButton = { TextButton(onClick = { clearing = false; act { api.memoryClear(); list = m.copy(facts = emptyList()) } }) { Text("Forget") } },
            dismissButton = { TextButton(onClick = { clearing = false }) { Text("Cancel") } },
        )
    }
}

// ---------------------------------------------------------------- Documents: the files and pictures you added (web/js/documents.js)

/** The Documents screen: lists the files and pictures the person added to chats and lets them delete one (after a confirmation). */
@Composable
private fun FilesPane(vm: AppViewModel) {
    var reload by remember { mutableIntStateOf(0) }
    val api = (LocalContext.current.applicationContext as EmvryxApp).api
    val scope = rememberCoroutineScope()
    var list by remember { mutableStateOf<DocList?>(null) }
    // `asking` is the id of the document whose delete confirmation is open (null = no dialog).
    var asking by remember { mutableStateOf<Long?>(null) }
    var note by remember { mutableStateOf<String?>(null) }
    // Load the document list; `list` takes over after a delete.
    Loaded(vm, reload, { documents() }, { reload++ }) { first ->
        val d = list ?: first
        LazyColumn(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
            item {
                // The note at the top mentions the size limit only when the server reports one (maxMb above 0).
                Text("Files and pictures you added to chats. Add new ones with the + by the message box" +
                     (if (d.maxMb > 0) " (up to ${d.maxMb} MB each)." else "."), color = Emvryx.muted, fontSize = 14.sp, modifier = Modifier.padding(top = 14.dp))
                note?.let { Text(it, color = Emvryx.muted, fontSize = 14.sp, modifier = Modifier.padding(top = 8.dp)) }
                if (d.documents.isEmpty()) Text("No documents yet.", color = Emvryx.muted, modifier = Modifier.padding(top = 18.dp))
                Spacer(Modifier.height(10.dp))
            }
            items(d.documents, key = { it.id }) { f ->
                Row(Modifier.fillMaxWidth().padding(vertical = 4.dp).clip(RoundedCornerShape(12.dp)).background(Emvryx.surface).padding(start = 14.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    // A picture icon for picture types, a document icon for the rest.
                    PwaIcon(if (f.kind.lowercase() in app.emvryx.android.data.DocInfo.PICTURE_KINDS) "image" else "doc", Emvryx.muted, 18.dp)
                    Spacer(Modifier.width(10.dp))
                    Column(Modifier.weight(1f).padding(vertical = 10.dp)) {
                        Text(f.name, maxLines = 1, overflow = TextOverflow.Ellipsis, fontSize = 15.sp)
                        // The file type and size, joined by a middle dot (empty parts skipped).
                        Text(listOf(f.kind.uppercase(), docSize(f.chars)).filter { it.isNotBlank() }.joinToString(" · "), color = Emvryx.muted, fontSize = 13.sp)
                    }
                    TextButton(onClick = { asking = f.id }) { Text("Delete", color = Emvryx.muted) }
                }
            }
        }
        // When a delete was asked for, show the confirmation dialog for that document.
        asking?.let { id ->
            AlertDialog(
                onDismissRequest = { asking = null },
                containerColor = Emvryx.surface,
                title = { Text("Delete this file?") },
                text = { Text(d.documents.firstOrNull { it.id == id }?.name.orEmpty()) },
                confirmButton = { TextButton(onClick = {
                    asking = null
                    scope.launch {
                        // Delete on the server, then drop it from the list on screen; errors are shown unless they mean the person was signed out.
                        try { api.deleteDocument(id); list = d.copy(documents = d.documents.filter { it.id != id }) }
                        catch (e: Exception) { if (!vm.handleSignedOut(e)) note = vm.describe(e) }
                    }
                }) { Text("Delete") } },
                dismissButton = { TextButton(onClick = { asking = null }) { Text("Cancel") } },
            )
        }
    }
}

// ---------------------------------------------------------------- Skills: a chat that answers in one way (web/js/core.js openSkills)

/** The Skills screen: each skill is a way of answering (for example a Teacher); tapping Start opens a new chat that uses it. */
@Composable
private fun SkillsPane(vm: AppViewModel) {
    var reload by remember { mutableIntStateOf(0) }
    Loaded(vm, reload, { skills() }, { reload++ }) { skills ->
        LazyColumn(Modifier.fillMaxSize().padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            item { Text("Start a chat where every answer is shaped for one job.", color = Emvryx.muted, fontSize = 14.sp, modifier = Modifier.padding(top = 14.dp)) }
            // Starting a skill creates a new chat with it and goes back to the chat screen.
            items(skills, key = { it.id }) { s -> SkillRow(s) { vm.newChat(skill = s.id, skillName = s.name); vm.backToChat() } }
            item { Spacer(Modifier.height(16.dp)) }
        }
    }
}

/** One skill card: icon, name, who it is for, what it does, an example to try, and a Start label. Tapping anywhere calls [start]. */
@Composable
private fun SkillRow(s: Skill, start: () -> Unit) {
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(Emvryx.surface).clickable(onClick = start).padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            PwaIcon(s.icon.ifBlank { "spark" }, LocalPalette.current.accentText, 22.dp)
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(s.name, fontWeight = FontWeight.SemiBold, fontSize = 16.sp)
                if (s.forWho.isNotBlank()) Text(s.forWho, color = Emvryx.muted, fontSize = 13.sp)
            }
            Text("Start", color = LocalPalette.current.accentText, fontWeight = FontWeight.SemiBold)
        }
        if (s.does.isNotBlank()) Text(s.does, fontSize = 14.sp)
        if (s.tryThis.isNotBlank()) Text("Try: " + s.tryThis, color = Emvryx.muted, fontSize = 13.sp)
    }
}

// ---------------------------------------------------------------- Settings: the everyday choices (web/js/settings.js)

/**
 * A row of pill buttons where exactly one is selected. [options] are (id, label) pairs, [value] is the selected id,
 * and [pick] is called with the id of the pill tapped. Pills wrap to new lines if they do not fit (FlowRow).
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun Choice(options: List<Pair<String, String>>, value: String, pick: (String) -> Unit) {
    // The colours of the app's current accent/theme.
    val p = LocalPalette.current
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        options.forEach { (id, label) ->
            val on = id == value
            Box(Modifier.clip(RoundedCornerShape(999.dp)).background(if (on) p.accent else Emvryx.surface2).clickable { pick(id) }
                .padding(horizontal = 14.dp, vertical = 8.dp)) {
                Text(label, color = if (on) p.onAccent else Emvryx.text, fontSize = 14.sp)
            }
        }
    }
}

/** An on/off switch row with a title and a small description. [flip] is called with the new value when it is toggled. */
@Composable
private fun Toggle(title: String, desc: String, on: Boolean, flip: (Boolean) -> Unit) {
    val p = LocalPalette.current
    Row(verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f).padding(end = 10.dp)) {
            Text(title, fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
            Text(desc, color = Emvryx.muted, fontSize = 13.sp)
        }
        Switch(on, flip, colors = SwitchDefaults.colors(checkedTrackColor = p.accent, checkedThumbColor = p.onAccent))
    }
}

/**
 * The Settings screen with the everyday choices. Every change is saved at once on the server and the reply replaces what is on screen.
 * Everything else lives in the website's full Settings, reached by the "More settings" button.
 */
@Composable
private fun SettingsPane(vm: AppViewModel) {
    var reload by remember { mutableIntStateOf(0) }
    val api = (LocalContext.current.applicationContext as EmvryxApp).api
    val scope = rememberCoroutineScope()
    // `now` is the newest settings after a save (null = use the first load); `how` is the unsaved text of "How you like answers" while typing.
    var now by remember { mutableStateOf<SettingsData?>(null) }
    var note by remember { mutableStateOf<String?>(null) }
    var how by remember { mutableStateOf<String?>(null) }
    // Helper: save one setting. [key] is the server's name for it; [value] is a Boolean or any other value, which is sent as text.
    // The server answers with all the settings, which we keep.
    fun save(key: String, value: Any) = scope.launch {
        note = null
        try {
            // Booleans go as true/false, everything else as text.
            val v = when (value) { is Boolean -> JsonPrimitive(value); else -> JsonPrimitive(value.toString()) }
            // Send a single-key JSON object such as {"memory": true}.
            now = api.saveSettings(JsonObject(mapOf(key to v)))
        } catch (e: Exception) { if (!vm.handleSignedOut(e)) note = vm.describe(e) }
    }
    Loaded(vm, reload, { settings() }, { reload++ }) { first ->
        // `s` = the settings to draw; `text` = the instructions text (what is being typed, else the saved value).
        val s = now ?: first
        val text = how ?: s.customInstructions
        LazyColumn(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
            item {
                note?.let { Text(it, color = Emvryx.muted, fontSize = 14.sp, modifier = Modifier.padding(top = 10.dp)) }
                Section("Answers")
                Card {
                    Text("Where answers come from", fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
                    Text("Auto looks things up in Wikipedia first and searches the web for recent things. Private chats never search the web.", color = Emvryx.muted, fontSize = 13.sp)
                    // Each pair is (value sent to the server, label shown). Tapping a pill saves that value.
                    Choice(listOf("auto" to "Auto", "off" to "Wikipedia only", "always" to "Always search the web", "none" to "Model only"), s.webSearch) { save("web_search", it) }
                }
                Spacer(Modifier.height(8.dp))
                Card {
                    Toggle("Live facts", "Sums, dates, prices, rates, scores and news come from code and free public services, not from the model’s memory.", s.liveData) { save("live_data", it) }
                }
                Spacer(Modifier.height(8.dp))
                Card {
                    Text("Pause before the answer", fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
                    Choice(listOf("off" to "None", "short" to "Short", "natural" to "Natural"), s.thinkingPause) { save("thinking_pause", it) }
                }
                Spacer(Modifier.height(8.dp))
                Card {
                    Text("How long a chat can be", fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
                    Choice(listOf("everyday" to "Everyday (about 8K)", "long" to "Long (if allowed)"), s.windowMode) { save("window_mode", it) }
                }
                Spacer(Modifier.height(8.dp))
                Card { Toggle("Show word counts", "The tokens each answer used, under it.", s.showTokens) { save("show_tokens", it) } }

                Section("Make it yours")
                Card {
                    // A text box limited to 400 characters (take(400) cuts anything longer).
                    Field("How you like answers", text, { how = it.take(400) }, placeholder = "Keep answers short. I am a nurse.")
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        // The Save button works only when the text differs from what is saved; after saving the draft is cleared.
                        PwaButton("Save", { save("custom_instructions", text); how = null }, enabled = text != s.customInstructions)
                        Text("${text.length}/400", color = Emvryx.muted, fontSize = 13.sp, modifier = Modifier.align(Alignment.CenterVertically))
                    }
                }
                Spacer(Modifier.height(8.dp))
                Card {
                    Toggle("Remember things about me", "Facts you tell it are kept and given to whichever model you talk to. Passwords and card numbers are never kept.", s.memory) { save("memory", it) }
                    Chip("What it remembers", { vm.open(Screen.Native("memory")) })
                }
                Spacer(Modifier.height(8.dp))
                Card { Toggle("Use my connected apps in chats", "When a question is clearly about one (“what is on my calendar”), the few matching items are read. Read-only.", s.connectedApps) { save("connected_apps", it) } }

                // The "This phone" section appears only when the on-phone model is allowed for this person.
                val phone = (LocalContext.current.applicationContext as EmvryxApp).phone
                if (phone.allowed) {
                    Section("This phone")
                    PhoneModelCard(phone, vm.online)
                    if (phone.status == app.emvryx.android.local.PhoneModel.Status.Ready) Chip("Open the chats on this phone", { vm.open(Screen.Local) })
                    // The picture-reading model card shows only once the phone model is ready and vision is allowed.
                    val vision = (LocalContext.current.applicationContext as EmvryxApp).vision
                    if (vision.allowed && phone.status == app.emvryx.android.local.PhoneModel.Status.Ready) {
                        Spacer(Modifier.height(8.dp))
                        PhoneVisionCard(vision, vm.online)
                    }
                }

                Section("More")
                Card {
                    Text("Connected apps, data controls, notifications and everything else are in the full Settings.", color = Emvryx.muted, fontSize = 13.sp)
                    Chip("More settings", { vm.open(Screen.Web("/#settings", "Settings", panel = true)) })
                }
                Spacer(Modifier.height(24.dp))
            }
        }
    }
}
