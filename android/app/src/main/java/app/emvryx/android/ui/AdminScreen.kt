// AdminScreen.kt: the app's own Admin page for the owner/admins (Overview, Previews, PC, People, Crashes).
// It is drawn with Jetpack Compose, Android's way of building screens from Kotlin functions marked @Composable:
// each function describes what to show, and when a value it reads changes (a "state"), Compose redraws it automatically.
// Data comes from ApiClient.kt (admin calls) and is kept for offline use by local/AdminCache.kt.

package app.emvryx.android.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.emvryx.android.EmvryxApp
import app.emvryx.android.local.AdminFlags
import app.emvryx.android.local.AdminRules
import app.emvryx.android.local.AdminSnapshot
import app.emvryx.android.ui.theme.Emvryx
import app.emvryx.android.ui.theme.LocalPalette
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * The app's own Admin (android_native): Overview, Previews (the switches), PC, People and Crashes, read from the PC and kept on the phone.
 * With the PC off it shows how things were last time, and switch changes wait and are made as soon as the PC is back. Everything else is in
 * the full Admin (More).
 * [vm] is the app's main ViewModel (the object that holds the app's state and shared actions).
 */
@Composable
fun AdminPane(vm: AppViewModel) {
    // Get hold of the running app object, which owns the server client (api) and the offline cache.
    val app = LocalContext.current.applicationContext as EmvryxApp
    val api = app.api
    val cache = app.admin
    // `remember { mutableStateOf(...) }` below makes a value that survives redraws and makes the screen redraw when it changes.
    // A coroutine scope lets button taps start background work (a coroutine is a function that can pause while waiting).
    val scope = rememberCoroutineScope()
    // Which tab is showing.
    var tab by remember { mutableStateOf("overview") }
    var live by remember { mutableStateOf(false) }               // read from the PC just now (false: the last state kept on the phone)
    // A message to show the person (an error, or "Published."), or null.
    var note by remember { mutableStateOf<String?>(null) }
    var publishing by remember { mutableStateOf<String?>(null) }        // "features" or "fixes": the Publish dialog is open
    // Counting this up makes the loader below run again (the Refresh button).
    var reload by remember { mutableStateOf(0) }

    // LaunchedEffect runs its block once when the screen appears, and again whenever `reload` or `vm.online` changes.
    // Here: read everything from the PC and keep it.
    LaunchedEffect(reload, vm.online) {
        // PC off: nothing to read, show the kept copy.
        if (!vm.online) { live = false; return@LaunchedEffect }
        // Anything that goes wrong (PC off, signed out) lands in the catch below.
        try {
            cache.queued.toList().forEach { q ->                      // switch changes made with the PC off go first
                runCatching { api.adminSetFlag(q.id, q.audience) }.onSuccess { cache.sent(q.id) }
            }
            // Ask for all five pages at the same time (async starts each one running) and wait for all of them; the crashes page may not exist for this person, so it gives null instead of failing.
            val s = coroutineScope {
                val o = async { api.adminOverview() }
                val f = async { api.adminFlags() }
                val p = async { api.adminPc() }
                val u = async { api.adminUsers() }
                val c = async { runCatching { api.adminCrashes() }.getOrNull() }
                AdminSnapshot(System.currentTimeMillis(), o.await(), f.await(), p.await(), u.await(), c.await())
            }
            // Save the fresh copy on the phone and mark the screen as live.
            cache.keep(s)
            live = true
        } catch (e: Exception) {
            live = false
            // If the session expired, the app goes to the sign-in screen; otherwise show a readable message.
            if (!vm.handleSignedOut(e)) note = vm.describe(e)
        }
    }
    // The data to draw: the last copy kept (fresh if we just read it).
    val s = cache.snap
    // Runs an action in the background, clearing the old message first; on failure it shows the message (or goes to sign-in).
    fun act(block: suspend () -> Unit) = scope.launch {
        note = null
        try { block() } catch (e: Exception) { if (!vm.handleSignedOut(e)) note = vm.describe(e) }
    }

    // The whole page: a banner (if offline), the tab row, a message, then the list for the chosen tab.
    Column(Modifier.fillMaxSize()) {
        // Banner shown while the PC is not answering: never read yet, or how long ago the kept copy is from.
        if (!live) Text(
            if (s.at == 0L) "Admin has not been read from the PC yet. Open it once while the PC is on."
            else "The PC is not answering: this is how things were " + ago(s.at) + ". Switch changes are saved and made when the PC is back.",
            color = Emvryx.muted, fontSize = 13.sp, modifier = Modifier.fillMaxWidth().background(Emvryx.surface2).padding(horizontal = 16.dp, vertical = 8.dp))
        // The tab choices; Crashes appears only when the PC sent crash data (listOfNotNull drops the null).
        val tabs = listOfNotNull("overview" to "Overview", "previews" to "Previews", "pc" to "PC", "people" to "People",
                                 if (s.crashes != null) "crashes" to "Crashes" else null)
        // A row of tabs that scrolls sideways if the screen is narrow.
        LazyRow(Modifier.padding(horizontal = 12.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            items(tabs) { (id, label) -> AdminTab(label, tab == id) { tab = id } }
        }
        note?.let { Text(it, color = Emvryx.muted, fontSize = 13.sp, modifier = Modifier.padding(horizontal = 16.dp)) }
        // A scrolling list; `when (tab)` fills it with the chosen tab's cards.
        LazyColumn(Modifier.fillMaxSize().padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            when (tab) {
                // Overview: counts, health numbers and the checklist.
                "overview" -> {
                    val o = s.overview
                    // Nothing read yet: say so. Otherwise one summary card, then one card per checklist line.
                    if (o == null) item { Text("Nothing kept yet.", color = Emvryx.muted) } else {
                        item {
                            AdminCard {
                                // People, blocked count (shown only if above 0) and the sign-up mode.
                                Text("${o.people} people" + (if (o.banned > 0) " · ${o.banned} blocked" else "") + " · sign-ups ${o.signupMode}", fontWeight = FontWeight.SemiBold)
                                // How many people are on each plan.
                                Text(o.plans.entries.joinToString(" · ") { "${it.value} ${it.key}" }, color = Emvryx.muted, fontSize = 13.sp)
                                // Health numbers in one line.
                                Text("Up ${o.health.uptimeMinutes} min · ${o.health.serverErrors} server errors · ${o.health.devices} devices signed in · " +
                                     "${o.health.codingRunning} VryxCode running · sandbox: ${o.health.codeSandbox}", color = Emvryx.muted, fontSize = 13.sp)
                            }
                        }
                        // A tick or cross per check; a failing check also shows how to fix it. `key` lets Compose keep each row's identity when the list changes.
                        items(o.checklist, key = { it.id }) { c ->
                            AdminCard {
                                Text((if (c.ok) "✓  " else "✗  ") + c.title, fontWeight = FontWeight.SemiBold, fontSize = 14.sp,
                                    color = if (c.ok) Emvryx.text else LocalPalette.current.accentText)
                                if (!c.ok) Text(c.how, color = Emvryx.muted, fontSize = 13.sp)
                            }
                        }
                    }
                }
                // Previews: who gets each new feature (the audience switches), plus the Publish buttons.
                "previews" -> {
                    // The switches with any waiting (offline) changes applied on top.
                    val flags = AdminRules.shown(s.flags?.flags.orEmpty(), cache.queued)
                    item {
                        AdminCard {
                            Text("Who gets each new feature. Changes here are made at once" + (if (live) "." else " when the PC is back."), color = Emvryx.muted, fontSize = 13.sp)
                            // new features and bug fixes go out separately: features add 0.5 to the version, fixes 0.1
                            // nf = features in preview, nx = fixes waiting, next = the version numbers a release would get.
                            val nf = AdminRules.inPreview(flags, "feature")
                            val nx = AdminRules.fixesWaiting(s.flags ?: AdminFlags())
                            val next = s.flags?.next.orEmpty()
                            // Publish buttons: only with the PC on, and only when there is something to publish. They open the confirm dialog below.
                            if (live && nf > 0) Chip("Publish new features ($nf)" + (next["features"]?.let { " · v$it" } ?: ""), { publishing = "features" })
                            if (live && nx > 0) Chip("Publish bug fixes ($nx)" + (next["fixes"]?.let { " · v$it" } ?: ""), { publishing = "fixes" })
                            // Say how many offline changes are waiting (and pick "change" or "changes").
                            if (cache.queued.isNotEmpty()) Text("${cache.queued.size} change${if (cache.queued.size == 1) "" else "s"} waiting for the PC",
                                color = LocalPalette.current.accentText, fontSize = 13.sp)
                        }
                    }
                    // One card per switch: title, description, a "waiting" note, and the audience choice.
                    items(flags, key = { it.id }) { f ->
                        AdminCard {
                            Text(f.title, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                            Text(f.desc, color = Emvryx.muted, fontSize = 12.sp, maxLines = 3)
                            if (cache.queued.any { it.id == f.id }) Text("Waiting for the PC", color = LocalPalette.current.accentText, fontSize = 12.sp)
                            // Picking an audience: with the PC on, send it now and keep the reply; with the PC off, put it in the queue to send later.
                            Choice(AdminRules.AUDIENCES, f.audience) { a ->
                                if (live) act { cache.keep(cache.snap.copy(flags = api.adminSetFlag(f.id, a))) } else cache.queue(f.id, a)
                            }
                        }
                    }
                }
                // PC: the loaded model, idle time, Gaming mode and when to free the graphics card.
                "pc" -> {
                    val p = s.pc
                    // Nothing kept yet, or one card with the PC's details.
                    if (p == null) item { Text("Nothing kept yet.", color = Emvryx.muted) } else item {
                        AdminCard {
                            // Which model is in memory and whether it is answering now.
                            Text("Model loaded: " + (p.loaded ?: "none") + if (p.busy) " · answering now" else "", fontWeight = FontWeight.SemiBold)
                            // Idle time in minutes (shown only if the PC reported it).
                            p.idleSeconds?.let { Text("Idle for ${it / 60} min", color = Emvryx.muted, fontSize = 13.sp) }
                            Text("Gaming mode " + if (p.gaming) "is on: models stay unloaded and chats say Emvryx is resting." else "is off.", fontSize = 14.sp)
                            // Gaming mode frees the PC for games. The button flips it, and only works with the PC on.
                            if (live) Chip(if (p.gaming) "Turn Gaming mode off" else "Turn Gaming mode on", {
                                act { cache.keep(cache.snap.copy(pc = api.adminSetPc(buildJsonObject { put("gaming", !p.gaming) }))) }
                            })
                            Text("Free the graphics card after", fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                            // How many idle minutes before the model is unloaded from the graphics card (0 = never). Needs the PC on.
                            Choice(listOf("0" to "Never", "5" to "5 min", "15" to "15 min", "30" to "30 min", "60" to "1 hour"), p.idleUnloadMinutes.toString()) { m ->
                                if (live) act { cache.keep(cache.snap.copy(pc = api.adminSetPc(buildJsonObject { put("idle_unload_minutes", m.toInt()) }))) }
                                else note = "The PC has to be on to change this."
                            }
                        }
                    }
                }
                // People: one card per account, with roles, plan and last seen.
                "people" -> items(s.users?.users.orEmpty(), key = { it.user }) { u ->
                    AdminCard {
                        // Name plus any of owner / admin / blocked.
                        Text(u.user + listOfNotNull(if (u.owner) "owner" else null, if (u.admin) "admin" else null, if (u.banned) "blocked" else null)
                            .joinToString("") { " · $it" }, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                        // Plan, whether it has no limits, and when last seen (the server sends seconds, ago() wants milliseconds, so times 1000).
                        Text(u.tier + (if (u.unlimited) " · no limits" else "") + " · last seen " + (u.lastSeen?.let { ago((it * 1000).toLong()) } ?: "never"),
                            color = Emvryx.muted, fontSize = 13.sp)
                    }
                }
                // Crashes: what went wrong, how often and where.
                "crashes" -> {
                    val list = s.crashes?.crashes.orEmpty()
                    if (list.isEmpty()) item { Text("No crashes in the log.", color = Emvryx.muted) }
                    items(list, key = { it.id }) { c ->
                        AdminCard {
                            Text("${c.kind} · ${c.count}×", fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                            Text(c.where, color = Emvryx.muted, fontSize = 13.sp)
                            Text(c.error, fontSize = 13.sp, maxLines = 4)
                        }
                    }
                }
            }
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(vertical = 8.dp)) {
                    // These buttons need the PC: reload everything, or open the website's full Admin inside the app.
                    if (vm.online) Chip("Refresh", { reload++ })
                    if (vm.online) Chip("More in the full Admin", { vm.open(Screen.Web("/#admin", "Admin", panel = true)) })
                }
                Spacer(Modifier.height(20.dp))
            }
        }
    }
    // The confirm dialog for Publish; it exists only while `publishing` holds "features" or "fixes".
    publishing?.let { kind ->
        val fixes = kind == "fixes"
        AlertDialog(
            // Tapping outside closes it without publishing.
            onDismissRequest = { publishing = null },
            containerColor = Emvryx.surface,
            title = { Text(if (fixes) "Publish the bug fixes to everyone?" else "Publish the new features to everyone?") },
            text = { Text((if (fixes) "Every bug fix in preview goes to everyone now" else "Every new feature in preview goes to everyone now") +
                (cache.snap.flags?.next?.get(kind)?.let { ", as v$it" } ?: "") + ", one release in What's new.") },
            // Publish: close the dialog, send the request, keep the reply, and say "Published."
            confirmButton = { TextButton(onClick = { publishing = null; act { cache.keep(cache.snap.copy(flags = api.adminPublish(kind))); note = "Published." } }) { Text("Publish") } },
            dismissButton = { TextButton(onClick = { publishing = null }) { Text("Cancel") } },
        )
    }
}

/** One tab button: a pill filled with the accent colour when [on], otherwise grey; tapping calls [onClick]. 999.dp rounds the ends fully. */
@Composable
private fun AdminTab(label: String, on: Boolean, onClick: () -> Unit) {
    val p = LocalPalette.current
    Text(label, color = if (on) p.onAccent else Emvryx.text, fontSize = 14.sp,
        modifier = Modifier.clip(RoundedCornerShape(999.dp)).background(if (on) p.accent else Emvryx.surface2).clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 7.dp))
}

/** A rounded box that groups related lines on the Admin page; the lines are passed in as [content]. */
@Composable
private fun AdminCard(content: @Composable () -> Unit) {
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(Emvryx.surface).padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        content()
    }
}

/**
 * "5 min ago", "3 hours ago": how long ago the time [ms] (milliseconds since 1970) was, compared with [now].
 * Under 90 s is "just now", under 90 min counts minutes, under 36 hours counts hours, and beyond that days.
 */
fun ago(ms: Long, now: Long = System.currentTimeMillis()): String {
    // Seconds since then; never negative (a clock that is slightly off must not give "-5 min").
    val s = maxOf(0L, (now - ms) / 1000)
    // 5400 s = 90 min; 129_600 s = 36 h; 3600 s = 1 h; 86400 s = 1 day.
    return when {
        s < 90 -> "just now"
        s < 5400 -> "${s / 60} min ago"
        s < 129_600 -> "${s / 3600} hours ago"
        else -> "${s / 86400} days ago"
    }
}
