package app.emvryx.android.ui

import android.os.SystemClock
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.emvryx.android.data.Ctx
import app.emvryx.android.data.LookupNotes
import app.emvryx.android.data.Timing
import app.emvryx.android.data.Usage
import app.emvryx.android.ui.theme.Emvryx
import app.emvryx.android.ui.theme.Heading
import app.emvryx.android.ui.theme.LocalPalette
import kotlinx.coroutines.delay
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

// The rest of the PWA's chat (web/js/chat.js, send.js, core.js) that the app did not have yet: the lock, usage details, the
// chat's menu (share a link, save as, archive), archived chats, folders, what an answer looked up, the owner's timing line,
// the error card, "Your day", the thinking words with their clock, and the memory (context window) details.

// ---------------------------------------------------------------- the words (pure, so they are tested)

/** "12s", "1m 05s": how long it has been thinking (send.js clockText) */
fun clockText(s: Long): String = when {
    s < 1 -> ""
    s < 60 -> "${s}s"
    else -> "${s / 60}m ${(s % 60).toString().padStart(2, '0')}s"
}

/** "Read 2 notes from Wikipedia and searched the web: 1 source": what the model was given before it answered (send.js lookupLine) */
fun lookupText(n: LookupNotes?): String? {
    if (n == null || !n.asked) return null
    val cant = n.unreadable.map { "Couldn't read $it" } + n.appErrors.map { "Couldn't read your ${it.app}: ${it.message}" }
    if (n.pictures > 0 || n.ocr > 0) return if (n.pictures > 0)
        "Looked at ${n.pictures} " + (if (n.pictures == 1) "picture" else "pictures") + (if (n.ocr > 0) " and read the text in ${n.ocr} more" else "")
    else "Read the text in the picture (it can't see photos yet)"
    val total = n.saved + n.wiki + n.web + n.live + n.apps.size + cant.size
    val noKey = if (n.webSource == "wikipedia") " Only Wikipedia was searched: no web search key is active (Settings > Live facts > See which sources are on)." else ""
    if (total == 0) return if (n.webTried) "Searched, but found nothing useful.$noKey" else null
    val parts = mutableListOf<String>()
    if (n.apps.isNotEmpty()) parts += "Looked in your " + n.apps.joinToString(" and ") + "."
    if (cant.isNotEmpty()) parts += cant.joinToString(" ")
    if (n.live > 0) parts += "Used live data: " + n.names.joinToString(", ")
    if (n.saved > 0) parts += "Read ${n.saved} " + (if (n.saved == 1) "saved note" else "saved notes") + (if (n.wiki > 0) " and ${n.wiki} from Wikipedia" else "")
    else if (n.wiki > 0) parts += "Read ${n.wiki} " + (if (n.wiki == 1) "note" else "notes") + " from Wikipedia"
    if (n.web > 0) parts += (if (n.wiki > 0 || n.saved > 0) "and searched" else "Searched") + " the web: ${n.web} " + if (n.web == 1) "source" else "sources"
    return parts.joinToString(" ") + noKey
}

/** "⏱ 9.8s in all · loading the model 2.1s · first word at 6.1s": for the owner and admins (send.js timingLine) */
fun timingText(t: Timing): String {
    fun sec(x: Double) = if (x < 10) String.format(Locale.US, "%.1fs", x) else "${Math.round(x)}s"
    val bits = mutableListOf(sec(t.total) + " in all")
    if (t.lookup >= 0.3) bits += "looking it up " + sec(t.lookup)
    if (t.load >= 0.3) bits += "loading the model " + sec(t.load)
    bits += "first word at " + sec(t.firstWord)
    if (t.thought) bits += "thought first (Deep)"
    if (t.tries > 1) bits += "answered twice (searched after \"I don't know\")"
    return "⏱ " + bits.joinToString(" · ")
}

/** "5 h 20 min": how long until a time (chat.js untilText) */
fun untilText(epochSeconds: Double, now: Long = System.currentTimeMillis()): String {
    val m = maxOf(0L, Math.round((epochSeconds * 1000 - now) / 60000.0))
    return if (m >= 60) "${m / 60} h ${m % 60} min" else "$m min"
}

/** "12,345": numbers as the website writes them */
fun fmt(n: Double): String = String.format(Locale.US, "%,d", Math.round(n))

/** "1.2K": a token count (chat.js kTok) */
fun kTok(n: Long): String = if (n >= 1000) {
    val k = n / 1000.0
    (if (n >= 100_000) String.format(Locale.US, "%.0f", k) else String.format(Locale.US, "%.1f", k)).removeSuffix(".0") + "K"
} else n.toString()

// ---------------------------------------------------------------- small pieces of the thread

/** A grey note in the thread: what it looked up, memory updated, the timing line, "Private chat" */
@Composable
fun Note(text: String, modifier: Modifier = Modifier) {
    Text(text, color = Emvryx.muted, fontSize = 13.sp, modifier = modifier.clip(RoundedCornerShape(12.dp)).background(Emvryx.surface)
        .border(1.dp, Emvryx.line, RoundedCornerShape(12.dp)).padding(horizontal = 12.dp, vertical = 8.dp))
}

/** While it thinks: the mark, the word that changes every few seconds, and the clock that only goes up (send.js thinkingNode) */
@Composable
fun ThinkingRow(vm: AppViewModel) {
    val words = vm.thinkingWords
    var i by remember { mutableIntStateOf(0) }
    var now by remember { mutableLongStateOf(SystemClock.elapsedRealtime()) }
    LaunchedEffect(words) {
        while (true) {
            delay((vm.state?.thinkSwitchS ?: 2.5).times(1000).toLong().coerceAtLeast(800))
            i++
        }
    }
    LaunchedEffect(Unit) {
        while (true) {
            now = SystemClock.elapsedRealtime()
            delay(250)
        }
    }
    val since = if (vm.sentAt > 0) (now - vm.sentAt) / 1000 else 0
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Logo(Modifier.size(30.dp), kind = vm.currentModel?.name ?: "flare", animate = true)
        Text(vm.working ?: (words[i % words.size] + "…"), color = Emvryx.muted, fontSize = 16.sp)
        Text(clockText(since), color = Emvryx.muted, fontSize = 13.sp)
    }
}

/** The error card: what went wrong, what to do, and "Ask a stronger model" when there is one (send.js errorCard) */
@Composable
fun FailureCard(vm: AppViewModel, f: Failure) {
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(20.dp)).background(Emvryx.surface)
            .border(1.dp, Emvryx.danger.copy(alpha = 0.5f), RoundedCornerShape(20.dp)).padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text(f.message, fontWeight = FontWeight.SemiBold)
        if (f.action.isNotBlank()) Text(f.action)
        if (f.later.isNotBlank()) Text(f.later, color = Emvryx.muted, fontSize = 14.sp)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (vm.chatId != null && vm.bubbles.lastOrNull()?.mine == true) Chip("Try again", { vm.dismissFailure(); vm.regenerate() })
            Chip("Dismiss", vm::dismissFailure)
        }
    }
}

/** "Your day": one tap reads today from the connected apps (chat.js dayCard); nothing is read until then */
@Composable
fun YourDayCard(vm: AppViewModel) {
    val b = vm.briefing
    Column(
        Modifier.widthIn(max = 560.dp).fillMaxWidth().padding(top = 18.dp).clip(RoundedCornerShape(18.dp)).background(Emvryx.surface)
            .border(1.dp, Emvryx.line, RoundedCornerShape(18.dp)).padding(horizontal = 16.dp, vertical = 14.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text("Your day", fontWeight = FontWeight.Bold)
        if (b == null) {
            Text("See today's calendar, open tasks and newest mail from the apps you connected. Nothing is read until you tap.", color = Emvryx.muted, fontSize = 14.sp)
            PwaButton(if (vm.briefingBusy) "Reading your apps…" else "Show my day", vm::readMyDay, enabled = !vm.briefingBusy)
        } else {
            val text = b.sections.joinToString("\n") { s ->
                s.kind + " (" + s.app + "):\n" + (if (s.items.isNotEmpty()) s.items.joinToString("\n") { "- " + it.title + (if (it.text.isNotBlank()) " (${it.text})" else "") }
                else if (s.error.isNotBlank()) "- (could not be read: ${s.error})" else "- nothing")
            }
            b.sections.forEach { s ->
                Column {
                    Text(s.kind + "  ·  " + s.app, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                    if (s.items.isEmpty()) Text(if (s.error.isNotBlank()) "Could not read it: ${s.error}" else "Nothing.",
                        color = if (s.error.isNotBlank()) Emvryx.danger else Emvryx.muted, fontSize = 14.sp)
                    s.items.forEach { Text("•  " + it.title + (if (it.text.isNotBlank()) "  (${it.text})" else ""), color = Emvryx.muted, fontSize = 14.sp) }
                }
            }
            if (b.sections.isEmpty()) Text("No connected apps to read. Connect them on the website: Settings > Connected apps.", color = Emvryx.muted, fontSize = 14.sp)
            else Chip("Plan my day with Emvryx", { vm.planMyDay(text) })
        }
    }
}

// ---------------------------------------------------------------- memory (context window) and usage details

/** The memory ring's details (chat.js ctxMenuNodes): used, free, when older messages get summarized, Compact now */
@Composable
fun MemoryDetails(vm: AppViewModel, c: Ctx, close: () -> Unit) {
    val p = LocalPalette.current
    val left = maxOf(0L, c.compactAt - c.used)
    Text("MEMORY (CONTEXT WINDOW)", color = Emvryx.muted, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.2.sp, modifier = Modifier.padding(6.dp))
    Box(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp).height(8.dp).clip(CircleShape).background(Emvryx.line)) {
        Box(Modifier.fillMaxHeight().fillMaxWidth((c.pct / 100).toFloat().coerceIn(0f, 1f)).background(p.accent))
    }
    KV("${Math.round(c.pct)}% used", "${kTok(c.used)} of ${kTok(c.window)} tokens", bold = true)
    KV("Free", kTok(maxOf(0L, c.window - c.used)))
    if (c.compactAt > 0) KV("Summarizes older messages at", kTok(c.compactAt) + if (left > 0) " (${kTok(left)} to go)" else " (next step)")
    Text("When it gets there, the older messages are summarized so the chat can keep going. Compact now does it straight away.",
        color = Emvryx.muted, fontSize = 13.sp, modifier = Modifier.padding(horizontal = 12.dp, vertical = 4.dp))
    if (vm.chatId != null && !vm.isPrivate) PwaButton("Compact now", onClick = { vm.compact(); close() }, enabled = !vm.streaming,
        modifier = Modifier.fillMaxWidth().padding(top = 6.dp))
}

@Composable
private fun KV(k: String, v: String, bold: Boolean = false) {
    Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(k, fontSize = 14.sp, fontWeight = if (bold) FontWeight.Bold else FontWeight.Normal)
        Spacer(Modifier.size(12.dp))
        Text(v, fontSize = 14.sp, color = Emvryx.muted, textAlign = TextAlign.End)
    }
}

/** Tapping the usage line: the tank, when it is full again, this week, and messages left on each model (chat.js openUsage) */
@Composable
fun UsageDialog(u: Usage, onClose: () -> Unit) {
    val p = LocalPalette.current
    val day = SimpleDateFormat("EEE h:mm a", Locale.getDefault())
    val week = SimpleDateFormat("EEEE h:mm a", Locale.getDefault())
    @Composable
    fun Bar(pct: Double) = Box(Modifier.fillMaxWidth().padding(vertical = 4.dp).height(8.dp).clip(CircleShape).background(Emvryx.line)) {
        Box(Modifier.fillMaxHeight().fillMaxWidth((pct / 100).toFloat().coerceIn(0f, 1f)).background(p.accent))
    }
    AlertDialog(
        onDismissRequest = onClose, containerColor = Emvryx.surface,
        title = { Text("Usage", fontFamily = Heading) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                if (u.status.isNotBlank()) Text("Status: " + u.status, color = Emvryx.muted)
                if (u.exempt) Text("You are the owner, so nothing is limited or counted.")
                else {
                    Text("Right now", fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 8.dp))
                    Bar(u.tank.pct)
                    KV("Left in your tank", fmt(u.tank.left) + " of " + fmt(u.tank.cap) + " tokens")
                    KV("About", fmt(u.tank.messagesLeft.toDouble()) + " messages")
                    KV("Refills", if (u.tank.mode == "window") "All at once, ${fmt(u.tank.refillHours)} hours after your first message" else fmt(u.tank.refillPerHour) + " tokens an hour")
                    val full = if (u.tank.mode == "window") u.tank.left >= u.tank.cap else u.tank.pct >= 99.5
                    KV("Full again", if (full) "Already full" else day.format(Date((u.tank.fullAt * 1000).toLong())) + " (in " + untilText(u.tank.fullAt) + ")")
                    Text("This week", fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 8.dp))
                    Bar(u.week.pctLeft)
                    KV("Left this week", fmt(u.week.left) + " of " + fmt(u.week.cap) + " tokens")
                    KV("About", fmt(u.week.messagesLeft.toDouble()) + " messages")
                    KV("Resets", week.format(Date((u.week.resetsAt * 1000).toLong())))
                    if (u.models.isNotEmpty()) {
                        Text("Messages left, by model", fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 8.dp))
                        u.models.forEach { KV(it.model.replaceFirstChar { c -> c.uppercase() }, "≈ " + fmt(it.messagesLeft.toDouble())) }
                    }
                    Text("A normal message is about 500 tokens on Flare. Bigger models and Deep thinking use more. Models running on your own device are never counted.",
                        color = Emvryx.muted, fontSize = 13.sp, modifier = Modifier.padding(top = 8.dp))
                }
            }
        },
        confirmButton = { TextButton(onClose) { Text("Close") } },
    )
}

// ---------------------------------------------------------------- the chat's menu: share a link, save as, archived chats, folders

/** Share a link to a copy of this chat (chat.js shareDialog): 1, 7 or 30 days, and the links already made, each with Cancel link */
@Composable
fun ShareDialog(vm: AppViewModel) {
    val s = vm.shares ?: return
    val clip = LocalClipboardManager.current
    var days by remember { mutableIntStateOf(7) }
    var copied by remember { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = vm::closeShares, containerColor = Emvryx.surface,
        title = { Text("Share a link", fontFamily = Heading) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                if (!s.on) Text("Sharing links is switched off on this Emvryx. The owner can turn it on in Settings > Owner > Overview.", color = Emvryx.muted)
                else {
                    Text("Anyone who has the link can read a copy of this chat as it is now: only the words, not pictures, files or later messages. You can cancel the link any time.",
                        color = Emvryx.muted, fontSize = 14.sp)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        listOf(1 to "1 day", 7 to "7 days", 30 to "30 days").forEach { (d, t) -> Seg(t, days == d) { days = d } }
                    }
                    PwaButton("Make a link", { vm.makeShare(days); copied = false }, Modifier.fillMaxWidth())
                    vm.shareUrl?.let { url ->
                        Text(url, fontSize = 14.sp)
                        Chip(if (copied) "Copied" else "Copy link", { clip.setText(AnnotatedString(url)); copied = true })
                    }
                }
                if (s.shares.isNotEmpty()) Text("Your links", fontWeight = FontWeight.Bold)
                s.shares.forEach { r ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(r.title, fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
                            Text("Works until " + SimpleDateFormat("d MMM yyyy", Locale.getDefault()).format(Date((r.expires * 1000).toLong())), color = Emvryx.muted, fontSize = 13.sp)
                        }
                        Chip("Cancel link", { vm.revokeShare(r) })
                    }
                }
            }
        },
        confirmButton = { TextButton(vm::closeShares) { Text("Close") } },
    )
}

@Composable
private fun Seg(text: String, on: Boolean, onClick: () -> Unit) {
    val p = LocalPalette.current
    Text(text, fontSize = 14.sp, color = if (on) p.onAccent else Emvryx.text,
        modifier = Modifier.clip(CircleShape).background(if (on) p.accent else Emvryx.surface2).clickable(onClick = onClick).padding(horizontal = 14.dp, vertical = 8.dp))
}

/** Save as (documents.js saveAs): PDF, Word or Markdown, made on the server; or just copy the text */
@Composable
fun SaveAsDialog(text: String, onPick: (String) -> Unit, onClose: () -> Unit) {
    val clip = LocalClipboardManager.current
    AlertDialog(
        onDismissRequest = onClose, containerColor = Emvryx.surface,
        title = { Text("Save as", fontFamily = Heading) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Worksheets keep the answer key and teacher notes on their own pages, so you can print page 1 for the class.", color = Emvryx.muted, fontSize = 14.sp)
                PwaButton("PDF", { onPick("pdf"); onClose() }, Modifier.fillMaxWidth())
                PwaButton("Word", { onPick("docx"); onClose() }, Modifier.fillMaxWidth())
                PwaButton("Markdown", { onPick("md"); onClose() }, Modifier.fillMaxWidth(), ghost = true)
                PwaButton("Copy text", { clip.setText(AnnotatedString(text)); onClose() }, Modifier.fillMaxWidth(), ghost = true)
            }
        },
        confirmButton = { TextButton(onClose) { Text("Close") } },
    )
}

/** Archived chats (chat.js openArchived): out of the list, but kept, searchable and still remembered */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ArchivedDialog(vm: AppViewModel, onOpen: (Long) -> Unit) {
    val list = vm.archivedChats ?: return
    var confirm by remember { mutableStateOf<app.emvryx.android.data.ChatSummary?>(null) }
    AlertDialog(
        onDismissRequest = vm::closeArchived, containerColor = Emvryx.surface,
        title = { Text("Archived chats", fontFamily = Heading) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("Out of your chat list, but kept, searchable and still remembered.", color = Emvryx.muted, fontSize = 14.sp)
                if (list.isEmpty()) Text("Nothing archived. Archive a chat from its ⋯ menu.", color = Emvryx.muted)
                list.forEach { c ->
                    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).border(1.dp, Emvryx.line, RoundedCornerShape(12.dp)).padding(10.dp)) {
                        Text(c.title.ifBlank { "Untitled" }, fontWeight = FontWeight.SemiBold)
                        Text(SimpleDateFormat("d MMM yyyy", Locale.getDefault()).format(Date((c.updated * 1000).toLong())), color = Emvryx.muted, fontSize = 13.sp)
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(top = 6.dp)) {
                            Chip("Open", { vm.closeArchived(); onOpen(c.id) })
                            Chip("Unarchive", { vm.archive(c, false) })
                            Chip("Delete", { confirm = c })
                        }
                    }
                }
            }
        },
        confirmButton = { TextButton(vm::closeArchived) { Text("Close") } },
    )
    confirm?.let { c ->
        AlertDialog(
            onDismissRequest = { confirm = null }, containerColor = Emvryx.surface,
            title = { Text("Delete this chat?") }, text = { Text("\"${c.title}\" and its messages are deleted. This can't be undone.") },
            confirmButton = { TextButton({ vm.delete(c); confirm = null; vm.loadArchived() }) { Text("Delete", color = Emvryx.danger) } },
            dismissButton = { TextButton({ confirm = null }) { Text("Cancel") } },
        )
    }
}

/** Move a chat to a folder (core.js chatMenu): a name, or empty to take it out */
@Composable
fun FolderDialog(start: String, onSave: (String) -> Unit, onClose: () -> Unit) {
    var name by remember { mutableStateOf(start) }
    AlertDialog(
        onDismissRequest = onClose, containerColor = Emvryx.surface,
        title = { Text("Move to a folder") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                NoteBox(name, { name = it }, "Folder name")
                Text("Leave it empty to take the chat out of its folder.", color = Emvryx.muted, fontSize = 13.sp)
            }
        },
        confirmButton = { TextButton({ onSave(name); onClose() }) { Text("Move") } },
        dismissButton = { TextButton(onClose) { Text("Cancel") } },
    )
}

// ---------------------------------------------------------------- the lock

/** Shown when the fingerprint lock is on and the app opens (or comes back after a minute away) */
@Composable
fun LockScreen(onUnlock: () -> Unit) {
    LaunchedEffect(Unit) { onUnlock() }                       // ask straight away; the button is there if it was dismissed
    Box(Modifier.fillMaxSize().background(Emvryx.bg), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(16.dp), modifier = Modifier.padding(28.dp)) {
            Logo(Modifier.size(64.dp))
            Text("Emvryx is locked", fontFamily = Heading, fontWeight = FontWeight.SemiBold, fontSize = 24.sp)
            Text("Use your fingerprint, face or screen lock to open it.", color = Emvryx.muted, textAlign = TextAlign.Center)
            PwaButton("Unlock", onUnlock, Modifier.fillMaxWidth().heightIn(min = 48.dp))
        }
    }
}
