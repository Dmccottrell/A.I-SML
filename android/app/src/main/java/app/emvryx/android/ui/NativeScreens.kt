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
    BackHandler { vm.backToChat() }
    val title = NATIVE_TITLES[kind] ?: "Emvryx"
    Column(Modifier.fillMaxSize().background(Emvryx.bg)) {
        Column(Modifier.statusBarsPadding()) {
            Row(Modifier.fillMaxWidth().height(56.dp).padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = vm::backToChat) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back to the chat", tint = Emvryx.text) }
                Text(title, fontWeight = FontWeight.SemiBold, fontSize = 17.sp)
            }
            HorizontalDivider(color = Emvryx.line)
        }
        Box(Modifier.weight(1f).fillMaxWidth().navigationBarsPadding()) {
            when (kind) {
                "memory" -> MemoryPane(vm)
                "files" -> FilesPane(vm)
                "skills" -> SkillsPane(vm)
                else -> SettingsPane(vm)
            }
        }
    }
}

val NATIVE_TITLES = mapOf("memory" to "Memory", "files" to "Documents", "skills" to "Skills", "settings" to "Settings")

/** Loads [what] once (and again when [reload] changes); shows a spinner, then the content or the error with Try again */
@Composable
private fun <T> Loaded(vm: AppViewModel, reload: Int, what: suspend ApiClient.() -> T, retry: () -> Unit, content: @Composable (T) -> Unit) {
    val api = (LocalContext.current.applicationContext as EmvryxApp).api
    var got by remember { mutableStateOf<T?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(reload) {
        error = null
        try {
            got = api.what()
        } catch (e: Exception) {
            if (!vm.handleSignedOut(e)) error = vm.describe(e)
        }
    }
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
    Box(Modifier.fillMaxSize().padding(28.dp), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Logo(Modifier.size(48.dp))
            Text(message, color = Emvryx.muted, fontSize = 16.sp)
            PwaButton("Try again", retry, Modifier.fillMaxWidth())
            if (back != null) PwaButton("Back to the chat", back, Modifier.fillMaxWidth(), ghost = true)
        }
    }
}

@Composable
private fun Section(text: String) {
    Text(text.uppercase(), color = Emvryx.muted.copy(alpha = 0.8f), fontSize = 11.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.1.sp,
        modifier = Modifier.padding(start = 4.dp, top = 18.dp, bottom = 6.dp))
}

@Composable
private fun Card(content: @Composable () -> Unit) {
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(Emvryx.surface).padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        content()
    }
}

// ---------------------------------------------------------------- Memory: what Emvryx remembers about you (web/js/settings.js openMemory)

@Composable
private fun MemoryPane(vm: AppViewModel) {
    var reload by remember { mutableIntStateOf(0) }
    val api = (LocalContext.current.applicationContext as EmvryxApp).api
    val scope = rememberCoroutineScope()
    var list by remember { mutableStateOf<MemoryList?>(null) }
    var text by remember { mutableStateOf("") }
    var note by remember { mutableStateOf<String?>(null) }
    var clearing by remember { mutableStateOf(false) }
    fun act(block: suspend () -> Unit) = scope.launch {
        note = null
        try { block() } catch (e: Exception) { if (!vm.handleSignedOut(e)) note = vm.describe(e) }
    }
    Loaded(vm, reload, { memory() }, { reload++ }) { first ->
        val m = list ?: first
        LazyColumn(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
            item {
                Text(if (m.on) "Facts you tell Emvryx are kept here and given to whichever model you talk to. Private chats never save or read them."
                     else "Memory is off (Settings > Remember things about me): nothing new is kept.",
                    color = Emvryx.muted, fontSize = 14.sp, modifier = Modifier.padding(top = 14.dp))
                Spacer(Modifier.height(12.dp))
                Field("Add a fact", text, { text = it }, placeholder = "I live in Leeds and have two cats")
                Spacer(Modifier.height(8.dp))
                PwaButton("Remember this", { val t = text.trim(); if (t.isNotEmpty()) act { list = api.memoryAdd(t).copy(on = m.on); text = "" } },
                    Modifier.fillMaxWidth(), enabled = text.isNotBlank())
                note?.let { Text(it, color = Emvryx.muted, fontSize = 14.sp, modifier = Modifier.padding(top = 8.dp)) }
                Section(if (m.facts.isEmpty()) "Nothing remembered yet" else "${m.facts.size} remembered")
            }
            items(m.facts, key = { it.id }) { f ->
                Row(Modifier.fillMaxWidth().padding(vertical = 4.dp).clip(RoundedCornerShape(12.dp)).background(Emvryx.surface).padding(start = 14.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    Text(f.text, Modifier.weight(1f).padding(vertical = 12.dp), fontSize = 15.sp)
                    TextButton(onClick = { act { api.memoryDelete(f.id); list = m.copy(facts = m.facts.filter { it.id != f.id }) } }) {
                        Text("Delete", color = Emvryx.muted)
                    }
                }
            }
            if (m.facts.isNotEmpty()) item {
                Spacer(Modifier.height(10.dp))
                PwaButton("Forget everything", { clearing = true }, Modifier.fillMaxWidth(), ghost = true)
                Spacer(Modifier.height(20.dp))
            }
        }
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

@Composable
private fun FilesPane(vm: AppViewModel) {
    var reload by remember { mutableIntStateOf(0) }
    val api = (LocalContext.current.applicationContext as EmvryxApp).api
    val scope = rememberCoroutineScope()
    var list by remember { mutableStateOf<DocList?>(null) }
    var asking by remember { mutableStateOf<Long?>(null) }
    var note by remember { mutableStateOf<String?>(null) }
    Loaded(vm, reload, { documents() }, { reload++ }) { first ->
        val d = list ?: first
        LazyColumn(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
            item {
                Text("Files and pictures you added to chats. Add new ones with the + by the message box" +
                     (if (d.maxMb > 0) " (up to ${d.maxMb} MB each)." else "."), color = Emvryx.muted, fontSize = 14.sp, modifier = Modifier.padding(top = 14.dp))
                note?.let { Text(it, color = Emvryx.muted, fontSize = 14.sp, modifier = Modifier.padding(top = 8.dp)) }
                if (d.documents.isEmpty()) Text("No documents yet.", color = Emvryx.muted, modifier = Modifier.padding(top = 18.dp))
                Spacer(Modifier.height(10.dp))
            }
            items(d.documents, key = { it.id }) { f ->
                Row(Modifier.fillMaxWidth().padding(vertical = 4.dp).clip(RoundedCornerShape(12.dp)).background(Emvryx.surface).padding(start = 14.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    PwaIcon(if (f.kind.lowercase() in app.emvryx.android.data.DocInfo.PICTURE_KINDS) "image" else "doc", Emvryx.muted, 18.dp)
                    Spacer(Modifier.width(10.dp))
                    Column(Modifier.weight(1f).padding(vertical = 10.dp)) {
                        Text(f.name, maxLines = 1, overflow = TextOverflow.Ellipsis, fontSize = 15.sp)
                        Text(listOf(f.kind.uppercase(), docSize(f.chars)).filter { it.isNotBlank() }.joinToString(" · "), color = Emvryx.muted, fontSize = 13.sp)
                    }
                    TextButton(onClick = { asking = f.id }) { Text("Delete", color = Emvryx.muted) }
                }
            }
        }
        asking?.let { id ->
            AlertDialog(
                onDismissRequest = { asking = null },
                containerColor = Emvryx.surface,
                title = { Text("Delete this file?") },
                text = { Text(d.documents.firstOrNull { it.id == id }?.name.orEmpty()) },
                confirmButton = { TextButton(onClick = {
                    asking = null
                    scope.launch {
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

@Composable
private fun SkillsPane(vm: AppViewModel) {
    var reload by remember { mutableIntStateOf(0) }
    Loaded(vm, reload, { skills() }, { reload++ }) { skills ->
        LazyColumn(Modifier.fillMaxSize().padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            item { Text("Start a chat where every answer is shaped for one job.", color = Emvryx.muted, fontSize = 14.sp, modifier = Modifier.padding(top = 14.dp)) }
            items(skills, key = { it.id }) { s -> SkillRow(s) { vm.newChat(skill = s.id, skillName = s.name); vm.backToChat() } }
            item { Spacer(Modifier.height(16.dp)) }
        }
    }
}

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

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Choice(options: List<Pair<String, String>>, value: String, pick: (String) -> Unit) {
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

@Composable
private fun SettingsPane(vm: AppViewModel) {
    var reload by remember { mutableIntStateOf(0) }
    val api = (LocalContext.current.applicationContext as EmvryxApp).api
    val scope = rememberCoroutineScope()
    var now by remember { mutableStateOf<SettingsData?>(null) }
    var note by remember { mutableStateOf<String?>(null) }
    var how by remember { mutableStateOf<String?>(null) }
    fun save(key: String, value: Any) = scope.launch {
        note = null
        try {
            val v = when (value) { is Boolean -> JsonPrimitive(value); else -> JsonPrimitive(value.toString()) }
            now = api.saveSettings(JsonObject(mapOf(key to v)))
        } catch (e: Exception) { if (!vm.handleSignedOut(e)) note = vm.describe(e) }
    }
    Loaded(vm, reload, { settings() }, { reload++ }) { first ->
        val s = now ?: first
        val text = how ?: s.customInstructions
        LazyColumn(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
            item {
                note?.let { Text(it, color = Emvryx.muted, fontSize = 14.sp, modifier = Modifier.padding(top = 10.dp)) }
                Section("Answers")
                Card {
                    Text("Where answers come from", fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
                    Text("Auto looks things up in Wikipedia first and searches the web for recent things. Private chats never search the web.", color = Emvryx.muted, fontSize = 13.sp)
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
                    Field("How you like answers", text, { how = it.take(400) }, placeholder = "Keep answers short. I am a nurse.")
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
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
