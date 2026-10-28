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
 */
@Composable
fun AdminPane(vm: AppViewModel) {
    val app = LocalContext.current.applicationContext as EmvryxApp
    val api = app.api
    val cache = app.admin
    val scope = rememberCoroutineScope()
    var tab by remember { mutableStateOf("overview") }
    var live by remember { mutableStateOf(false) }               // read from the PC just now (false: the last state kept on the phone)
    var note by remember { mutableStateOf<String?>(null) }
    var publishing by remember { mutableStateOf(false) }
    var reload by remember { mutableStateOf(0) }

    LaunchedEffect(reload, vm.online) {
        if (!vm.online) { live = false; return@LaunchedEffect }
        try {
            cache.queued.toList().forEach { q ->                      // switch changes made with the PC off go first
                runCatching { api.adminSetFlag(q.id, q.audience) }.onSuccess { cache.sent(q.id) }
            }
            val s = coroutineScope {
                val o = async { api.adminOverview() }
                val f = async { api.adminFlags() }
                val p = async { api.adminPc() }
                val u = async { api.adminUsers() }
                val c = async { runCatching { api.adminCrashes() }.getOrNull() }
                AdminSnapshot(System.currentTimeMillis(), o.await(), f.await(), p.await(), u.await(), c.await())
            }
            cache.keep(s)
            live = true
        } catch (e: Exception) {
            live = false
            if (!vm.handleSignedOut(e)) note = vm.describe(e)
        }
    }
    val s = cache.snap
    fun act(block: suspend () -> Unit) = scope.launch {
        note = null
        try { block() } catch (e: Exception) { if (!vm.handleSignedOut(e)) note = vm.describe(e) }
    }

    Column(Modifier.fillMaxSize()) {
        if (!live) Text(
            if (s.at == 0L) "Admin has not been read from the PC yet. Open it once while the PC is on."
            else "The PC is not answering: this is how things were " + ago(s.at) + ". Switch changes are saved and made when the PC is back.",
            color = Emvryx.muted, fontSize = 13.sp, modifier = Modifier.fillMaxWidth().background(Emvryx.surface2).padding(horizontal = 16.dp, vertical = 8.dp))
        val tabs = listOfNotNull("overview" to "Overview", "previews" to "Previews", "pc" to "PC", "people" to "People",
                                 if (s.crashes != null) "crashes" to "Crashes" else null)
        LazyRow(Modifier.padding(horizontal = 12.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            items(tabs) { (id, label) -> AdminTab(label, tab == id) { tab = id } }
        }
        note?.let { Text(it, color = Emvryx.muted, fontSize = 13.sp, modifier = Modifier.padding(horizontal = 16.dp)) }
        LazyColumn(Modifier.fillMaxSize().padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            when (tab) {
                "overview" -> {
                    val o = s.overview
                    if (o == null) item { Text("Nothing kept yet.", color = Emvryx.muted) } else {
                        item {
                            AdminCard {
                                Text("${o.people} people" + (if (o.banned > 0) " · ${o.banned} blocked" else "") + " · sign-ups ${o.signupMode}", fontWeight = FontWeight.SemiBold)
                                Text(o.plans.entries.joinToString(" · ") { "${it.value} ${it.key}" }, color = Emvryx.muted, fontSize = 13.sp)
                                Text("Up ${o.health.uptimeMinutes} min · ${o.health.serverErrors} server errors · ${o.health.devices} devices signed in · " +
                                     "${o.health.codingRunning} VryxCode running · sandbox: ${o.health.codeSandbox}", color = Emvryx.muted, fontSize = 13.sp)
                            }
                        }
                        items(o.checklist, key = { it.id }) { c ->
                            AdminCard {
                                Text((if (c.ok) "✓  " else "✗  ") + c.title, fontWeight = FontWeight.SemiBold, fontSize = 14.sp,
                                    color = if (c.ok) Emvryx.text else LocalPalette.current.accentText)
                                if (!c.ok) Text(c.how, color = Emvryx.muted, fontSize = 13.sp)
                            }
                        }
                    }
                }
                "previews" -> {
                    val flags = AdminRules.shown(s.flags?.flags.orEmpty(), cache.queued)
                    item {
                        AdminCard {
                            Text("Who gets each new feature. Changes here are made at once" + (if (live) "." else " when the PC is back."), color = Emvryx.muted, fontSize = 13.sp)
                            val n = AdminRules.inPreview(flags)
                            if (live && n > 0) Chip("Publish all ($n) to everyone", { publishing = true })
                            if (cache.queued.isNotEmpty()) Text("${cache.queued.size} change${if (cache.queued.size == 1) "" else "s"} waiting for the PC",
                                color = LocalPalette.current.accentText, fontSize = 13.sp)
                        }
                    }
                    items(flags, key = { it.id }) { f ->
                        AdminCard {
                            Text(f.title, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                            Text(f.desc, color = Emvryx.muted, fontSize = 12.sp, maxLines = 3)
                            if (cache.queued.any { it.id == f.id }) Text("Waiting for the PC", color = LocalPalette.current.accentText, fontSize = 12.sp)
                            Choice(AdminRules.AUDIENCES, f.audience) { a ->
                                if (live) act { cache.keep(cache.snap.copy(flags = api.adminSetFlag(f.id, a))) } else cache.queue(f.id, a)
                            }
                        }
                    }
                }
                "pc" -> {
                    val p = s.pc
                    if (p == null) item { Text("Nothing kept yet.", color = Emvryx.muted) } else item {
                        AdminCard {
                            Text("Model loaded: " + (p.loaded ?: "none") + if (p.busy) " · answering now" else "", fontWeight = FontWeight.SemiBold)
                            p.idleSeconds?.let { Text("Idle for ${it / 60} min", color = Emvryx.muted, fontSize = 13.sp) }
                            Text("Gaming mode " + if (p.gaming) "is on: models stay unloaded and chats say Emvryx is resting." else "is off.", fontSize = 14.sp)
                            if (live) Chip(if (p.gaming) "Turn Gaming mode off" else "Turn Gaming mode on", {
                                act { cache.keep(cache.snap.copy(pc = api.adminSetPc(buildJsonObject { put("gaming", !p.gaming) }))) }
                            })
                            Text("Free the graphics card after", fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                            Choice(listOf("0" to "Never", "5" to "5 min", "15" to "15 min", "30" to "30 min", "60" to "1 hour"), p.idleUnloadMinutes.toString()) { m ->
                                if (live) act { cache.keep(cache.snap.copy(pc = api.adminSetPc(buildJsonObject { put("idle_unload_minutes", m.toInt()) }))) }
                                else note = "The PC has to be on to change this."
                            }
                        }
                    }
                }
                "people" -> items(s.users?.users.orEmpty(), key = { it.user }) { u ->
                    AdminCard {
                        Text(u.user + listOfNotNull(if (u.owner) "owner" else null, if (u.admin) "admin" else null, if (u.banned) "blocked" else null)
                            .joinToString("") { " · $it" }, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                        Text(u.tier + (if (u.unlimited) " · no limits" else "") + " · last seen " + (u.lastSeen?.let { ago((it * 1000).toLong()) } ?: "never"),
                            color = Emvryx.muted, fontSize = 13.sp)
                    }
                }
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
                    if (vm.online) Chip("Refresh", { reload++ })
                    if (vm.online) Chip("More in the full Admin", { vm.open(Screen.Web("/#admin", "Admin", panel = true)) })
                }
                Spacer(Modifier.height(20.dp))
            }
        }
    }
    if (publishing) AlertDialog(
        onDismissRequest = { publishing = false },
        containerColor = Emvryx.surface,
        title = { Text("Publish all to everyone?") },
        text = { Text("Every feature in preview goes to everyone now, as one release in What's new.") },
        confirmButton = { TextButton(onClick = { publishing = false; act { cache.keep(cache.snap.copy(flags = api.adminPublishAll())); note = "Published." } }) { Text("Publish") } },
        dismissButton = { TextButton(onClick = { publishing = false }) { Text("Cancel") } },
    )
}

@Composable
private fun AdminTab(label: String, on: Boolean, onClick: () -> Unit) {
    val p = LocalPalette.current
    Text(label, color = if (on) p.onAccent else Emvryx.text, fontSize = 14.sp,
        modifier = Modifier.clip(RoundedCornerShape(999.dp)).background(if (on) p.accent else Emvryx.surface2).clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 7.dp))
}

@Composable
private fun AdminCard(content: @Composable () -> Unit) {
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(Emvryx.surface).padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        content()
    }
}

/** "5 min ago", "3 hours ago" */
fun ago(ms: Long, now: Long = System.currentTimeMillis()): String {
    val s = maxOf(0L, (now - ms) / 1000)
    return when {
        s < 90 -> "just now"
        s < 5400 -> "${s / 60} min ago"
        s < 129_600 -> "${s / 3600} hours ago"
        else -> "${s / 86400} days ago"
    }
}
