package app.emvryx.android.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
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
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.emvryx.android.EmvryxApp
import app.emvryx.android.local.PhoneModel
import app.emvryx.android.ui.theme.Emvryx
import app.emvryx.android.ui.theme.LocalPalette
import app.emvryx.android.ui.theme.Mono
import kotlinx.coroutines.launch

/**
 * android_offline_model: chats answered by the model on this phone, for when the PC is off or there is no signal. They stay on the phone.
 * Until the model is here, this screen is where it is downloaded.
 */
@Composable
fun LocalChatScreen(vm: AppViewModel, onBack: () -> Unit) {
    BackHandler(onBack = onBack)
    val phone = (LocalContext.current.applicationContext as EmvryxApp).phone
    Column(Modifier.fillMaxSize().background(Emvryx.bg)) {
        Column(Modifier.statusBarsPadding()) {
            Row(Modifier.fillMaxWidth().height(56.dp).padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = Emvryx.text) }
                Column(Modifier.weight(1f)) {
                    Text("On this phone", fontWeight = FontWeight.SemiBold, fontSize = 17.sp)
                    phone.kit?.let { Text(it.fullName + " · works without the PC", color = Emvryx.muted, fontSize = 12.sp) }
                }
            }
            HorizontalDivider(color = Emvryx.line)
        }
        if (!vm.online) OfflineBar(vm)
        Box(Modifier.weight(1f).fillMaxWidth().navigationBarsPadding().imePadding()) {
            if (phone.status == PhoneModel.Status.Ready) LocalChats(phone) else Column(Modifier.padding(16.dp)) { PhoneModelCard(phone, vm.online) }
        }
    }
}

/** The PC is off: everything here is answered on the phone; it looks for the PC every half minute and goes back by itself */
@Composable
private fun OfflineBar(vm: AppViewModel) {
    LaunchedEffect(Unit) {
        while (true) {
            kotlinx.coroutines.delay(OFFLINE_CHECK_MS)
            vm.checkPc()
        }
    }
    Row(Modifier.fillMaxWidth().background(Emvryx.surface2).padding(horizontal = 16.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Text("Offline: the PC is off, so answers are written on this phone. Your chats sync when it is back.", color = Emvryx.muted, fontSize = 13.sp,
            modifier = Modifier.weight(1f))
        TextButton(onClick = vm::checkPc) { Text("Try the PC") }
    }
}

const val OFFLINE_CHECK_MS = 30_000L

/** Flare (fast) or Equinox (smarter, needs a phone with more memory): only what this phone can run can be picked */
@Composable
private fun ModelChoice(phone: PhoneModel) {
    LaunchedEffect(Unit) { phone.loadChoices() }
    if (phone.choices.size < 2) return
    val p = LocalPalette.current
    val picked = phone.wanted ?: phone.choices.first().id
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        phone.choices.forEach { c ->
            val fits = phone.enoughRam(c.minRamGb)
            val on = c.id == picked
            Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).border(1.dp, if (on) p.accent else Emvryx.line, RoundedCornerShape(12.dp))
                .clickable(enabled = fits) { phone.pick(c.id) }.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(c.fullName + "  ·  " + c.sizeText, fontWeight = FontWeight.SemiBold, fontSize = 14.sp, color = if (fits) Emvryx.text else Emvryx.muted)
                    Text(if (fits) (if (c.id == phone.choices.first().id) "Fastest on a phone." else "Smarter, but slower on a phone.")
                         else "Needs a phone with about ${c.minRamGb.toInt()} GB of memory.", color = Emvryx.muted, fontSize = 12.sp)
                }
                if (on) Text("✓", color = p.accentText, fontWeight = FontWeight.Bold)
            }
        }
    }
}

/** Download, progress, remove: the model on this phone (also in Settings) */
@Composable
fun PhoneModelCard(phone: PhoneModel, online: Boolean) {
    val p = LocalPalette.current
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(Emvryx.surface).padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Answers with the PC off", fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
        Text("Your small Flare model runs on the phone itself: when the PC is off or there is no signal, chats still get answers. It does not search the " +
             "web, and the chats stay on the phone. It uses your instructions and what Emvryx remembers about you.", color = Emvryx.muted, fontSize = 13.sp)
        when (val s = phone.status) {
            PhoneModel.Status.None -> {
                ModelChoice(phone)
                Text("Downloaded once from your PC.", color = Emvryx.muted, fontSize = 13.sp)
                PwaButton("Download", phone::download, Modifier.fillMaxWidth(), enabled = online)
                if (!online) Text("The PC has to be on to download it.", color = Emvryx.muted, fontSize = 13.sp)
            }
            is PhoneModel.Status.Downloading -> {
                val f = if (s.total > 0) s.done.toFloat() / s.total else 0f
                LinearProgressIndicator(progress = { f }, Modifier.fillMaxWidth(), color = p.accent, trackColor = Emvryx.surface2)
                Text("Downloading: ${s.done / (1 shl 20)} of ${s.total / (1 shl 20)} MB. You can leave this screen; if it stops, it carries on where it was.",
                    color = Emvryx.muted, fontSize = 13.sp)
                Chip("Stop", phone::cancel)
            }
            PhoneModel.Status.Checking -> Text("Checking the download…", color = Emvryx.muted, fontSize = 13.sp)
            PhoneModel.Status.Ready -> {
                Text("${phone.kit?.fullName ?: "The model"} is on this phone.", fontSize = 14.sp)
                phone.newer?.let { Chip("Get the newer ${it.fullName}", phone::download) }
                phone.choices.firstOrNull { it.id != phone.kit?.id && phone.enoughRam(it.minRamGb) }?.let { other ->
                    Chip("Switch to ${other.fullName} (${other.sizeText})", { phone.pick(other.id); phone.download() })
                }
                Chip("Remove it from this phone", phone::remove)
            }
            is PhoneModel.Status.Failed -> {
                ModelChoice(phone)
                Text(s.message, color = Emvryx.muted, fontSize = 13.sp)
                PwaButton("Try again", phone::download, Modifier.fillMaxWidth(), enabled = online)
            }
        }
    }
}

@Composable
private fun LocalChats(phone: PhoneModel) {
    val scope = rememberCoroutineScope()
    var chatId by remember { mutableLongStateOf(phone.openChat ?: phone.chats.maxByOrNull { it.updated }?.id ?: phone.newChat().id) }
    var live by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var text by remember { mutableStateOf("") }
    var menu by remember { mutableStateOf(false) }
    val chat = phone.chats.firstOrNull { it.id == chatId } ?: phone.chats.lastOrNull() ?: phone.newChat().also { chatId = it.id }
    val list = rememberLazyListState()
    val turns = chat.turns
    LaunchedEffect(turns.size, live.length / 80) { if (turns.isNotEmpty()) list.scrollToItem(turns.size - 1) }
    LaunchedEffect(phone.ask) {                                      // the PC dropped while this was being sent: it is answered here
        val q = phone.ask ?: return@LaunchedEffect
        phone.openChat?.let { chatId = it }
        phone.ask = null
        phone.openChat = null
        error = null
        live = ""
        error = phone.answer(chatId, q) { live = it }
    }

    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.weight(1f)) {
                Text(chat.title, maxLines = 1, overflow = TextOverflow.Ellipsis, color = Emvryx.muted, fontSize = 14.sp,
                    modifier = Modifier.clickable { menu = true }.padding(6.dp))
                DropdownMenu(menu, { menu = false }, containerColor = Emvryx.surface) {
                    phone.chats.sortedByDescending { it.updated }.forEach { c ->
                        DropdownMenuItem(text = { Text(c.title, maxLines = 1, overflow = TextOverflow.Ellipsis) }, onClick = { menu = false; chatId = c.id },
                            trailingIcon = { if (c.pending.isNotEmpty()) Text("not synced", color = Emvryx.muted, fontSize = 11.sp) })
                    }
                    if (turns.isNotEmpty()) DropdownMenuItem(text = { Text("Delete this chat", color = Emvryx.muted) },
                        onClick = { menu = false; phone.deleteChat(chat.id); chatId = phone.chats.lastOrNull()?.id ?: phone.newChat().id })
                }
            }
            TextButton(onClick = { if (!phone.writing) chatId = phone.newChat().id }) { Text("New chat") }
        }
        LazyColumn(Modifier.weight(1f).fillMaxWidth().padding(horizontal = 14.dp), state = list, verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (turns.isEmpty()) item {
                Text("Ask anything. This model is small and has no internet, so for facts that change (news, prices) wait for the PC.",
                    color = Emvryx.muted, fontSize = 14.sp, modifier = Modifier.padding(vertical = 18.dp))
            }
            itemsIndexed(turns) { i, t ->
                val streaming = !t.mine && i == turns.size - 1 && phone.writing
                LocalBubble(t.mine, if (streaming) live else t.text, streaming)
            }
            error?.let { item { Text(it, color = Emvryx.muted, fontSize = 14.sp) } }
        }
        val p = LocalPalette.current
        Row(Modifier.fillMaxWidth().padding(12.dp).clip(RoundedCornerShape(20.dp)).background(Emvryx.surface).border(1.dp, Emvryx.line, RoundedCornerShape(20.dp))
            .padding(start = 16.dp, end = 8.dp, top = 8.dp, bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.weight(1f).heightIn(min = 24.dp, max = 140.dp)) {
                if (text.isEmpty()) Text("Message the phone's model…", color = Emvryx.muted, style = MaterialTheme.typography.bodyLarge)
                BasicTextField(text, { text = it }, Modifier.fillMaxWidth(), textStyle = MaterialTheme.typography.bodyLarge.copy(color = Emvryx.text),
                    cursorBrush = SolidColor(p.accent))
            }
            Box(Modifier.size(40.dp).clip(CircleShape).background(if (phone.writing || text.isNotBlank()) p.accent else Emvryx.surface2)
                .clickable {
                    if (phone.writing) { phone.stop(); return@clickable }
                    val q = text.trim()
                    if (q.isEmpty()) return@clickable
                    text = ""
                    error = null
                    live = ""
                    scope.launch { error = phone.answer(chatId, q) { live = it } }
                }, contentAlignment = Alignment.Center) {
                Text(if (phone.writing) "■" else "↑", color = p.onAccent, fontWeight = FontWeight.Bold, fontSize = 18.sp)
            }
        }
    }
}

@Composable
private fun LocalBubble(mine: Boolean, text: String, streaming: Boolean) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = if (mine) Arrangement.End else Arrangement.Start) {
        Column(
            Modifier.widthIn(max = 560.dp).clip(RoundedCornerShape(18.dp)).background(if (mine) Emvryx.surface2 else Emvryx.surface)
                .padding(horizontal = 14.dp, vertical = 10.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            if (mine) Text(text, style = MaterialTheme.typography.bodyLarge)
            else if (streaming && text.isEmpty()) Text("Thinking on the phone…", color = Emvryx.muted)
            else SelectionContainer {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Markdown.blocks(text + if (streaming) " ▍" else "").forEach { b ->
                        when (b) {
                            is Block.Prose -> Text(Markdown.inline(b.text), style = MaterialTheme.typography.bodyLarge)
                            is Block.Code -> Text(b.text, style = Mono, color = Emvryx.text,
                                modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(Emvryx.bg)
                                    .horizontalScroll(rememberScrollState()).padding(10.dp))
                            is Block.Table -> MdTable(b)
                        }
                    }
                }
            }
        }
    }
    Spacer(Modifier.height(2.dp))
}
