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

// ChatMore.kt: extra pieces of the chat screen. First come small pure text helpers (clock, lookup line, timing line, number
// formats), then Compose widgets (a Composable is a function that draws part of the screen): notes, the thinking row, the error card,
// "Your day", memory and usage details, and the share / save / archive / folder dialogs plus the lock screen.
// ChatScreen.kt puts these pieces together. The "send.js", "chat.js" names point to the website file each piece copies.
// The rest of the PWA's chat (web/js/chat.js, send.js, core.js) that the app did not have yet: the lock, usage details, the
// chat's menu (share a link, save as, archive), archived chats, folders, what an answer looked up, the owner's timing line,
// the error card, "Your day", the thinking words with their clock, and the memory (context window) details.

// ---------------------------------------------------------------- the words (pure, so they are tested)

/**
 * Formats a number of seconds as a clock: 12 -> "12s", 65 -> "1m 05s". Under 1 second gives an empty string (nothing to show yet).
 * [s] is whole seconds since the message was sent. Used by the thinking row (send.js clockText).
 */
fun clockText(s: Long): String = when {
    // Less than one second: show nothing.
    s < 1 -> ""
    s < 60 -> "${s}s"
    // Minutes, then the leftover seconds padded to two digits with a leading zero ("05").
    else -> "${s / 60}m ${(s % 60).toString().padStart(2, '0')}s"
}

/**
 * Builds the one-line summary of what the model was given before answering (send.js lookupLine).
 * [n] is the lookup record the server sent (counts of pictures, saved notes, Wikipedia notes, web results, live data, connected apps, errors).
 * Returns the sentence to show, or null when nothing was looked up (so no note is drawn).
 */
fun lookupText(n: LookupNotes?): String? {
    // No lookup record, or no lookup was asked for: nothing to say.
    if (n == null || !n.asked) return null
    // Messages for things that could not be read: unreadable files, and connected apps that returned an error.
    val cant = n.unreadable.map { "Couldn't read $it" } + n.appErrors.map { "Couldn't read your ${it.app}: ${it.message}" }
    // Pictures take priority: say how many pictures were looked at (and extra ones where only text was read), or that only text could be read from the picture.
    if (n.pictures > 0 || n.ocr > 0) return if (n.pictures > 0)
        "Looked at ${n.pictures} " + (if (n.pictures == 1) "picture" else "pictures") + (if (n.ocr > 0) " and read the text in ${n.ocr} more" else "")
    else "Read the text in the picture (it can't see photos yet)"
    // Total number of lookups of every kind (including the failures), to see if anything happened at all.
    val total = n.saved + n.wiki + n.web + n.live + n.apps.size + cant.size
    // Extra hint added when the web search only used Wikipedia because no web search key is turned on.
    val noKey = if (n.webSource == "wikipedia") " Only Wikipedia was searched: no web search key is active (Settings > Live facts > See which sources are on)." else ""
    // Nothing found: if a web search was tried, say so; otherwise there is nothing to report (null).
    if (total == 0) return if (n.webTried) "Searched, but found nothing useful.$noKey" else null
    // Build the sentence from pieces, only adding the parts that apply.
    val parts = mutableListOf<String>()
    if (n.apps.isNotEmpty()) parts += "Looked in your " + n.apps.joinToString(" and ") + "."
    if (cant.isNotEmpty()) parts += cant.joinToString(" ")
    if (n.live > 0) parts += "Used live data: " + n.names.joinToString(", ")
    // Saved notes (with Wikipedia notes added to the same sentence), or only Wikipedia notes. The singular/plural word is chosen by the count.
    if (n.saved > 0) parts += "Read ${n.saved} " + (if (n.saved == 1) "saved note" else "saved notes") + (if (n.wiki > 0) " and ${n.wiki} from Wikipedia" else "")
    else if (n.wiki > 0) parts += "Read ${n.wiki} " + (if (n.wiki == 1) "note" else "notes") + " from Wikipedia"
    // The web part starts with "and searched" if something was already said before it, otherwise "Searched".
    if (n.web > 0) parts += (if (n.wiki > 0 || n.saved > 0) "and searched" else "Searched") + " the web: ${n.web} " + if (n.web == 1) "source" else "sources"
    return parts.joinToString(" ") + noKey
}

/**
 * Builds the owner-and-admin timing line, for example "9.8s in all · loading the model 2.1s · first word at 6.1s" (send.js timingLine).
 * [t] holds the timings in seconds measured by the server. Parts that were too small to matter (under 0.3s) are left out.
 */
fun timingText(t: Timing): String {
    // Local helper: under 10 seconds show one decimal ("2.1s"), otherwise round to a whole number ("12s").
    // Locale.US forces a dot as the decimal mark whatever the phone's language is.
    fun sec(x: Double) = if (x < 10) String.format(Locale.US, "%.1fs", x) else "${Math.round(x)}s"
    // A growing list of the parts of the line, starting with the total time.
    val bits = mutableListOf(sec(t.total) + " in all")
    if (t.lookup >= 0.3) bits += "looking it up " + sec(t.lookup)
    if (t.load >= 0.3) bits += "loading the model " + sec(t.load)
    bits += "first word at " + sec(t.firstWord)
    if (t.thought) bits += "thought first (Deep)"
    if (t.tries > 1) bits += "answered twice (searched after \"I don't know\")"
    // Join the parts with a middle dot; the stopwatch sign leads the line.
    return "⏱ " + bits.joinToString(" · ")
}

/**
 * Says how long until a time, such as "5 h 20 min" (chat.js untilText).
 * [epochSeconds] is the target time as seconds since 1970 (a Unix time); [now] is the current time in milliseconds (a parameter so tests can fix it).
 */
fun untilText(epochSeconds: Double, now: Long = System.currentTimeMillis()): String {
    // Minutes left, rounded; never below zero (a time already past counts as 0). 60000.0 = milliseconds in a minute; the decimal point forces a decimal division.
    val m = maxOf(0L, Math.round((epochSeconds * 1000 - now) / 60000.0))
    // 60 minutes or more: show hours and leftover minutes (/ and % are whole division and remainder).
    return if (m >= 60) "${m / 60} h ${m % 60} min" else "$m min"
}

/** Rounds a number and writes it with thousands commas, as the website does: 12345.4 -> "12,345" */
fun fmt(n: Double): String = String.format(Locale.US, "%,d", Math.round(n))

/** Writes a token count short: 1234 -> "1.2K", 150000 -> "150K", 800 -> "800" (chat.js kTok). A token is a small chunk of text the model counts in. */
fun kTok(n: Long): String = if (n >= 1000) {
    // Thousands as a decimal number.
    val k = n / 1000.0
    // From 100,000 up show no decimals, below that one decimal; then drop a useless ".0" ("2.0" -> "2") and add K. 100_000 is just 100000 (underscores help reading).
    (if (n >= 100_000) String.format(Locale.US, "%.0f", k) else String.format(Locale.US, "%.1f", k)).removeSuffix(".0") + "K"
} else n.toString()

// ---------------------------------------------------------------- small pieces of the thread

/** A grey note in the thread: what it looked up, memory updated, the timing line, "Private chat". [text] is shown in a small rounded grey box; [modifier] lets the caller add layout rules. */
@Composable
fun Note(text: String, modifier: Modifier = Modifier) {
    // A Modifier is a chain of settings for how a widget is laid out and drawn; here: clip to rounded corners, fill with the surface colour, add a thin border, then padding inside.
    Text(text, color = Emvryx.muted, fontSize = 13.sp, modifier = modifier.clip(RoundedCornerShape(12.dp)).background(Emvryx.surface)
        .border(1.dp, Emvryx.line, RoundedCornerShape(12.dp)).padding(horizontal = 12.dp, vertical = 8.dp))
}

/**
 * The row shown while the model is thinking: the logo mark, a word that changes every few seconds, and a clock that counts up (send.js thinkingNode).
 * [vm] is the app's ViewModel (the object holding the app's data and logic).
 */
@Composable
fun ThinkingRow(vm: AppViewModel) {
    // The list of thinking words to cycle through.
    val words = vm.thinkingWords
    // `i` = which word is showing; `now` = the current clock time. Changing a remember { mutableStateOf } value makes Compose redraw the row.
    var i by remember { mutableIntStateOf(0) }
    var now by remember { mutableLongStateOf(SystemClock.elapsedRealtime()) }
    // A LaunchedEffect starts a coroutine (a function that can pause without blocking the screen) when this row appears, and stops it when it leaves.
    // This one moves to the next word every thinkSwitchS seconds (default 2.5), never faster than 800 ms; it restarts if the word list changes.
    LaunchedEffect(words) {
        while (true) {
            delay((vm.state?.thinkSwitchS ?: 2.5).times(1000).toLong().coerceAtLeast(800))
            i++
        }
    }
    // A second coroutine refreshes `now` four times a second (every 250 ms) so the clock text keeps ticking.
    // SystemClock.elapsedRealtime() counts milliseconds since the phone started and is not affected by clock changes.
    LaunchedEffect(Unit) {
        while (true) {
            now = SystemClock.elapsedRealtime()
            delay(250)
        }
    }
    // Whole seconds since the message was sent (0 if it was not recorded).
    val since = if (vm.sentAt > 0) (now - vm.sentAt) / 1000 else 0
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        // The animated logo; its look follows the current model's name (defaults to "flare").
        Logo(Modifier.size(30.dp), kind = vm.currentModel?.name ?: "flare", animate = true)
        // The status text if there is one, otherwise the current thinking word (`%` wraps around so the index never runs past the list) plus an ellipsis.
        Text(vm.working ?: (words[i % words.size] + "…"), color = Emvryx.muted, fontSize = 16.sp)
        Text(clockText(since), color = Emvryx.muted, fontSize = 13.sp)
    }
}

/**
 * The error card: what went wrong, what to do, and buttons to try again or dismiss (send.js errorCard).
 * [vm] is the app ViewModel; [f] is the failure description (message, action advice, "later" hint).
 */
@Composable
fun FailureCard(vm: AppViewModel, f: Failure) {
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(20.dp)).background(Emvryx.surface)
            .border(1.dp, Emvryx.danger.copy(alpha = 0.5f), RoundedCornerShape(20.dp)).padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text(f.message, fontWeight = FontWeight.SemiBold)
        // Show the optional lines only when they have text.
        if (f.action.isNotBlank()) Text(f.action)
        if (f.later.isNotBlank()) Text(f.later, color = Emvryx.muted, fontSize = 14.sp)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            // "Try again" only makes sense in a saved chat whose last message is the user's: dismiss the card, then ask for the answer again.
            if (vm.chatId != null && vm.bubbles.lastOrNull()?.mine == true) Chip("Try again", { vm.dismissFailure(); vm.regenerate() })
            Chip("Dismiss", vm::dismissFailure)
        }
    }
}

/**
 * "Your day": a card with a button that reads today's calendar, tasks and mail from the connected apps (chat.js dayCard).
 * Nothing is read until the user taps. [vm] holds the loaded briefing, if any.
 */
@Composable
fun YourDayCard(vm: AppViewModel) {
    // `b` is the loaded briefing, or null before the user has tapped the button.
    val b = vm.briefing
    Column(
        Modifier.widthIn(max = 560.dp).fillMaxWidth().padding(top = 18.dp).clip(RoundedCornerShape(18.dp)).background(Emvryx.surface)
            .border(1.dp, Emvryx.line, RoundedCornerShape(18.dp)).padding(horizontal = 16.dp, vertical = 14.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text("Your day", fontWeight = FontWeight.Bold)
        // Not loaded yet: explain, and show the button (disabled while it is loading).
        if (b == null) {
            Text("See today's calendar, open tasks and newest mail from the apps you connected. Nothing is read until you tap.", color = Emvryx.muted, fontSize = 14.sp)
            PwaButton(if (vm.briefingBusy) "Reading your apps…" else "Show my day", vm::readMyDay, enabled = !vm.briefingBusy)
        } else {
            // Turn the briefing into plain text (one block per app section) to hand to the model when the user asks it to plan the day.
            val text = b.sections.joinToString("\n") { s ->
                s.kind + " (" + s.app + "):\n" + (if (s.items.isNotEmpty()) s.items.joinToString("\n") { "- " + it.title + (if (it.text.isNotBlank()) " (${it.text})" else "") }
                else if (s.error.isNotBlank()) "- (could not be read: ${s.error})" else "- nothing")
            }
            // Draw each section: a heading, then either its items, an error or "Nothing.".
            b.sections.forEach { s ->
                Column {
                    Text(s.kind + "  ·  " + s.app, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                    if (s.items.isEmpty()) Text(if (s.error.isNotBlank()) "Could not read it: ${s.error}" else "Nothing.",
                        color = if (s.error.isNotBlank()) Emvryx.danger else Emvryx.muted, fontSize = 14.sp)
                    s.items.forEach { Text("•  " + it.title + (if (it.text.isNotBlank()) "  (${it.text})" else ""), color = Emvryx.muted, fontSize = 14.sp) }
                }
            }
            // If no apps are connected say so; otherwise offer to send the text above to Emvryx for a plan.
            if (b.sections.isEmpty()) Text("No connected apps to read. Connect them on the website: Settings > Connected apps.", color = Emvryx.muted, fontSize = 14.sp)
            else Chip("Plan my day with Emvryx", { vm.planMyDay(text) })
        }
    }
}

// ---------------------------------------------------------------- memory (context window) and usage details

/**
 * The memory ring's details (chat.js ctxMenuNodes): how much of the context window is used and free, when older messages get summarized,
 * and a Compact now button. The context window is how much text the model can keep in mind at once, counted in tokens.
 * [c] is the usage data; [close] closes the menu this is shown in.
 */
@Composable
fun MemoryDetails(vm: AppViewModel, c: Ctx, close: () -> Unit) {
    // The colour palette in use.
    val p = LocalPalette.current
    // Tokens still available before the automatic summary (never below zero).
    val left = maxOf(0L, c.compactAt - c.used)
    Text("MEMORY (CONTEXT WINDOW)", color = Emvryx.muted, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.2.sp, modifier = Modifier.padding(6.dp))
    // A progress bar: the outer box is the grey track; the inner box is filled to pct percent of the width (0 to 1, clamped so it cannot overflow).
    Box(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp).height(8.dp).clip(CircleShape).background(Emvryx.line)) {
        Box(Modifier.fillMaxHeight().fillMaxWidth((c.pct / 100).toFloat().coerceIn(0f, 1f)).background(p.accent))
    }
    KV("${Math.round(c.pct)}% used", "${kTok(c.used)} of ${kTok(c.window)} tokens", bold = true)
    KV("Free", kTok(maxOf(0L, c.window - c.used)))
    // Show the summary threshold only when the server gave one.
    if (c.compactAt > 0) KV("Summarizes older messages at", kTok(c.compactAt) + if (left > 0) " (${kTok(left)} to go)" else " (next step)")
    Text("When it gets there, the older messages are summarized so the chat can keep going. Compact now does it straight away.",
        color = Emvryx.muted, fontSize = 13.sp, modifier = Modifier.padding(horizontal = 12.dp, vertical = 4.dp))
    // Compact now works only in a saved, non-private chat and not while an answer is streaming.
    if (vm.chatId != null && !vm.isPrivate) PwaButton("Compact now", onClick = { vm.compact(); close() }, enabled = !vm.streaming,
        modifier = Modifier.fillMaxWidth().padding(top = 6.dp))
}

// A label on the left and a value on the right in one row. [bold] makes the label heavier. Private to this file.
@Composable
private fun KV(k: String, v: String, bold: Boolean = false) {
    Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(k, fontSize = 14.sp, fontWeight = if (bold) FontWeight.Bold else FontWeight.Normal)
        Spacer(Modifier.size(12.dp))
        Text(v, fontSize = 14.sp, color = Emvryx.muted, textAlign = TextAlign.End)
    }
}

/**
 * The usage dialog (chat.js openUsage): the token tank, when it is full again, this week's allowance, and messages left per model.
 * [u] is the usage data from the server; [onClose] is called to dismiss the dialog.
 */
@Composable
fun UsageDialog(u: Usage, onClose: () -> Unit) {
    val p = LocalPalette.current
    // Two time formats: short weekday for the tank, full weekday for the weekly reset, in the phone's language.
    val day = SimpleDateFormat("EEE h:mm a", Locale.getDefault())
    val week = SimpleDateFormat("EEEE h:mm a", Locale.getDefault())
    // A little local bar widget: pct percent of the width filled with the accent colour.
    @Composable
    fun Bar(pct: Double) = Box(Modifier.fillMaxWidth().padding(vertical = 4.dp).height(8.dp).clip(CircleShape).background(Emvryx.line)) {
        Box(Modifier.fillMaxHeight().fillMaxWidth((pct / 100).toFloat().coerceIn(0f, 1f)).background(p.accent))
    }
    // AlertDialog is the standard pop-up box: a title, content, and buttons.
    AlertDialog(
        onDismissRequest = onClose, containerColor = Emvryx.surface,
        title = { Text("Usage", fontFamily = Heading) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                // Owners are not limited, so show only that; others see the tank and the week.
                if (u.status.isNotBlank()) Text("Status: " + u.status, color = Emvryx.muted)
                if (u.exempt) Text("You are the owner, so nothing is limited or counted.")
                else {
                    Text("Right now", fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 8.dp))
                    Bar(u.tank.pct)
                    KV("Left in your tank", fmt(u.tank.left) + " of " + fmt(u.tank.cap) + " tokens")
                    KV("About", fmt(u.tank.messagesLeft.toDouble()) + " messages")
                    KV("Refills", if (u.tank.mode == "window") "All at once, ${fmt(u.tank.refillHours)} hours after your first message" else fmt(u.tank.refillPerHour) + " tokens an hour")
                    // "Window" mode refills all at once, so it is full when nothing is used; otherwise it counts as full at 99.5% or more.
                    val full = if (u.tank.mode == "window") u.tank.left >= u.tank.cap else u.tank.pct >= 99.5
                    // fullAt is seconds since 1970; multiply by 1000 for the Date (milliseconds) constructor.
                    KV("Full again", if (full) "Already full" else day.format(Date((u.tank.fullAt * 1000).toLong())) + " (in " + untilText(u.tank.fullAt) + ")")
                    Text("This week", fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 8.dp))
                    Bar(u.week.pctLeft)
                    KV("Left this week", fmt(u.week.left) + " of " + fmt(u.week.cap) + " tokens")
                    KV("About", fmt(u.week.messagesLeft.toDouble()) + " messages")
                    KV("Resets", week.format(Date((u.week.resetsAt * 1000).toLong())))
                    if (u.models.isNotEmpty()) {
                        Text("Messages left, by model", fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 8.dp))
                        // One row per model, with its name capitalised.
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

/** Share a link to a copy of this chat (chat.js shareDialog): choose 1, 7 or 30 days, then make a link; links already made are listed, each with Cancel link. [vm] holds the share state. */
@Composable
fun ShareDialog(vm: AppViewModel) {
    // No share data loaded: draw nothing (`?: return` leaves the function).
    val s = vm.shares ?: return
    // The system clipboard, used by the Copy link button.
    val clip = LocalClipboardManager.current
    // Remembered UI state: the days the link works for (7 by default) and whether the link was just copied.
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
                        // One selectable pill per length; clicking sets `days`.
                        listOf(1 to "1 day", 7 to "7 days", 30 to "30 days").forEach { (d, t) -> Seg(t, days == d) { days = d } }
                    }
                    // Ask the server for a link and reset the "Copied" label.
                    PwaButton("Make a link", { vm.makeShare(days); copied = false }, Modifier.fillMaxWidth())
                    // If a new link exists, show it with a button that copies it to the clipboard.
                    vm.shareUrl?.let { url ->
                        Text(url, fontSize = 14.sp)
                        Chip(if (copied) "Copied" else "Copy link", { clip.setText(AnnotatedString(url)); copied = true })
                    }
                }
                if (s.shares.isNotEmpty()) Text("Your links", fontWeight = FontWeight.Bold)
                // The links already made, each with its expiry date (the server sends seconds, hence * 1000) and a button to cancel it.
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

// A small pill button used to pick one option. [on] says whether it is the chosen one (filled with the accent colour). Private to this file.
@Composable
private fun Seg(text: String, on: Boolean, onClick: () -> Unit) {
    val p = LocalPalette.current
    Text(text, fontSize = 14.sp, color = if (on) p.onAccent else Emvryx.text,
        modifier = Modifier.clip(CircleShape).background(if (on) p.accent else Emvryx.surface2).clickable(onClick = onClick).padding(horizontal = 14.dp, vertical = 8.dp))
}

/** Save as (documents.js saveAs): PDF, Word or Markdown, made on the server; or just copy the text. [onPick] gets "pdf", "docx" or "md"; [text] is what gets copied. */
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

/** Archived chats (chat.js openArchived): out of the list, but kept, searchable and still remembered. [onOpen] is called with the chat id the user wants to open. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ArchivedDialog(vm: AppViewModel, onOpen: (Long) -> Unit) {
    // The list of archived chats; null means not loaded or not showing, so draw nothing.
    val list = vm.archivedChats ?: return
    // Which chat the user is about to delete (null = none), so we can ask "are you sure?" first.
    var confirm by remember { mutableStateOf<app.emvryx.android.data.ChatSummary?>(null) }
    AlertDialog(
        onDismissRequest = vm::closeArchived, containerColor = Emvryx.surface,
        title = { Text("Archived chats", fontFamily = Heading) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("Out of your chat list, but kept, searchable and still remembered.", color = Emvryx.muted, fontSize = 14.sp)
                if (list.isEmpty()) Text("Nothing archived. Archive a chat from its ⋯ menu.", color = Emvryx.muted)
                // One bordered card per archived chat with its title, last-change date and Open / Unarchive / Delete buttons.
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
    // A second dialog confirming deletion; it appears only while `confirm` holds a chat. Delete then reloads the archive list.
    confirm?.let { c ->
        AlertDialog(
            onDismissRequest = { confirm = null }, containerColor = Emvryx.surface,
            title = { Text("Delete this chat?") }, text = { Text("\"${c.title}\" and its messages are deleted. This can't be undone.") },
            confirmButton = { TextButton({ vm.delete(c); confirm = null; vm.loadArchived() }) { Text("Delete", color = Emvryx.danger) } },
            dismissButton = { TextButton({ confirm = null }) { Text("Cancel") } },
        )
    }
}

/** Move a chat to a folder (core.js chatMenu): type a name, or leave it empty to take the chat out of its folder. [start] is the current folder name. */
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

/** Shown when the fingerprint lock is on and the app opens (or comes back after a minute away). [onUnlock] starts the phone's fingerprint / face / screen-lock check. */
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
