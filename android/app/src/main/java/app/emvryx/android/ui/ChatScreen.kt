package app.emvryx.android.ui

import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.ui.platform.LocalContext
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ExitToApp
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.Text
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.emvryx.android.data.ChatSummary
import app.emvryx.android.ui.theme.Emvryx
import app.emvryx.android.ui.theme.Heading
import app.emvryx.android.ui.theme.LocalPalette
import app.emvryx.android.ui.theme.Mono
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

// The PWA's chat screen (web/index.html, web/js/chat.js) on a phone: the top bar with the chat's title, the thread,
// the message box with the model and effort pills under it, the usage line, and the chat list sliding in from the left.

private enum class Menu { Model, Effort, Memory, Regen, Attach }

@Composable
fun ChatScreen(vm: AppViewModel) {
    val drawer = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    var menu by remember { mutableStateOf<Menu?>(null) }
    var editing by remember { mutableStateOf<Bubble?>(null) }
    var reporting by remember { mutableStateOf<Bubble?>(null) }
    // the pickers live here, not in the menu: the menu closes as soon as one opens, and its result must still arrive
    val context = LocalContext.current
    val pickPicture = rememberLauncherForActivityResult(ActivityResultContracts.PickMultipleVisualMedia(3)) { uris ->
        uris.forEach { u -> readPicked(context, u)?.let { (n, b) -> vm.attach(n, b) } }
    }
    val pickFile = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { u ->
        u?.let { readPicked(context, it)?.let { (n, b) -> vm.attach(n, b) } }
    }
    BackHandler(drawer.isOpen) { scope.launch { drawer.close() } }
    BackHandler(menu != null) { menu = null }

    ModalNavigationDrawer(
        drawerState = drawer,
        scrimColor = Color.Black.copy(alpha = 0.55f),
        drawerContent = { Sidebar(vm, onDone = { scope.launch { drawer.close() } }) },
    ) {
        val p = LocalPalette.current
        Column(Modifier.fillMaxSize().background(Emvryx.bg).accentWash(p.glow).imePadding()) {
            TopBar(vm, onMenu = {
                menu = null
                vm.refreshChats()
                scope.launch { drawer.open() }
            })
            if (vm.state?.demo == true) DemoBanner()
            Box(Modifier.weight(1f).fillMaxWidth()) {
                Thread(vm, onRegen = { menu = Menu.Regen }, onEdit = { editing = it }, onReport = { reporting = it })
                if (menu != null) {
                    // tapping anywhere else closes the menu, as on the website
                    Box(Modifier.fillMaxSize().clickable(remember { MutableInteractionSource() }, null) { menu = null })
                    PopMenu(Modifier.align(Alignment.BottomCenter)) {
                        when (menu) {
                            Menu.Model -> ModelMenu(vm) { menu = null }
                            Menu.Effort -> EffortMenu(vm) { menu = null }
                            Menu.Memory -> MemoryMenuBody(vm) { menu = null }
                            Menu.Regen -> RegenMenuBody(vm) { menu = null }
                            Menu.Attach -> AttachMenu(
                                onPicture = { pickPicture.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) },
                                onFile = { pickFile.launch(arrayOf("*/*")) },
                            ) { menu = null }
                            null -> Unit
                        }
                    }
                }
            }
            Composer(vm, menu, onMenu = { menu = if (menu == it) null else it })
            UsageLine(vm)
        }
    }
    editing?.let { b ->
        EditDialog(b.text, laterAnswers = vm.bubbles.indexOf(b) < vm.bubbles.lastIndex, onSave = { vm.edit(b, it) }, onClose = { editing = null })
    }
    reporting?.let { b -> ReportDialog(onSend = { kind, note -> vm.report(b, kind, note) }, onClose = { reporting = null }) }
}

/** + by the message box: a picture from the phone, a photo, or a file (web/js/documents.js) */
@Composable
private fun AttachMenu(onPicture: () -> Unit, onFile: () -> Unit, close: () -> Unit) {
    MenuHead("ADD TO YOUR MESSAGE")
    Opt(selected = false, onClick = { onPicture(); close() }) {
        Text("🖼", fontSize = 20.sp)
        Column(Modifier.weight(1f)) {
            Text("Picture or screenshot", fontWeight = FontWeight.Bold, fontSize = 16.sp)
            Text("Up to 3. Emvryx looks at it and answers.", color = Emvryx.muted, fontSize = 14.sp)
        }
    }
    Opt(selected = false, onClick = { onFile(); close() }) {
        Text("📄", fontSize = 20.sp)
        Column(Modifier.weight(1f)) {
            Text("File", fontWeight = FontWeight.Bold, fontSize = 16.sp)
            Text("PDF, Word, a spreadsheet, text or code: ask about it.", color = Emvryx.muted, fontSize = 14.sp)
        }
    }
}

// ---------------------------------------------------------------- top

@Composable
private fun TopBar(vm: AppViewModel, onMenu: () -> Unit) {
    Column(Modifier.statusBarsPadding()) {
        Row(Modifier.fillMaxWidth().height(60.dp).padding(horizontal = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onMenu) { Icon(Icons.Default.Menu, "Chats", tint = Emvryx.text) }
            Text(
                vm.title, fontWeight = FontWeight.SemiBold, fontSize = 17.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f).padding(horizontal = 8.dp),
            )
            IconButton(onClick = vm::newChat, enabled = !vm.streaming) { Icon(Icons.Default.Add, "New chat", tint = Emvryx.text) }
        }
        HorizontalDivider(color = Emvryx.line)
    }
}

@Composable
private fun DemoBanner() {
    val p = LocalPalette.current
    Column {
        Text(
            buildAnnotatedString {
                withStyle(SpanStyle(color = p.accentText, fontWeight = FontWeight.SemiBold)) { append("Demo mode.") }
                append(" No model is attached, so replies are a stand-in. Start the server with --llama to use a real model.")
            },
            color = Emvryx.muted, fontSize = 14.sp, textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth().background(Emvryx.surface).padding(horizontal = 16.dp, vertical = 8.dp),
        )
        HorizontalDivider(color = Emvryx.line)
    }
}

// ---------------------------------------------------------------- the thread

@Composable
private fun Thread(vm: AppViewModel, onRegen: () -> Unit, onEdit: (Bubble) -> Unit, onReport: (Bubble) -> Unit) {
    val list = rememberLazyListState()
    val last = vm.bubbles.lastOrNull()
    LaunchedEffect(vm.bubbles.size, last?.text?.length) {
        if (vm.bubbles.isNotEmpty()) list.scrollToItem(vm.bubbles.lastIndex, Int.MAX_VALUE / 2)
    }
    if (vm.bubbles.isEmpty()) {
        Empty(vm)
        return
    }
    val lastReply = vm.bubbles.indexOfLast { !it.mine }
    LazyColumn(
        Modifier.fillMaxSize(), state = list,
        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 24.dp, bottom = 8.dp),
        verticalArrangement = Arrangement.spacedBy(22.dp),
    ) {
        items(vm.bubbles.size, key = { vm.bubbles[it].key }) { i ->
            val b = vm.bubbles[i]
            if (b.mine) UserMessage(vm, b, onEdit)
            else AiMessage(vm, b, isLast = i == lastReply && i == vm.bubbles.lastIndex, onRegen = onRegen, onReport = onReport)
        }
        vm.notice?.let { n ->
            item(key = "notice") {
                Text(
                    n, fontSize = 15.sp,
                    modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(Emvryx.surface)
                        .border(1.dp, Emvryx.danger.copy(alpha = 0.5f), RoundedCornerShape(16.dp)).padding(14.dp),
                )
            }
        }
    }
}

@Composable
private fun Empty(vm: AppViewModel) {
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 24.dp),
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center,
    ) {
        Logo(Modifier.size(64.dp), kind = vm.currentModel?.name ?: "flare")
        Text("How can I help?", fontFamily = Heading, fontWeight = FontWeight.SemiBold, fontSize = 32.sp, letterSpacing = (-0.6).sp,
            textAlign = TextAlign.Center, modifier = Modifier.padding(top = 12.dp, bottom = 6.dp))
        Text("Ask anything. Pick a model and how much it should think under the box.", color = Emvryx.muted, fontSize = 16.sp, textAlign = TextAlign.Center)
        vm.notice?.let { Text(it, color = Emvryx.danger, textAlign = TextAlign.Center, modifier = Modifier.padding(top = 16.dp)) }
        Spacer(Modifier.height(24.dp))
    }
}

/** .msg.user .bubble: your words in a filled bubble on the right, with the pictures and files that went with them. Hold it to edit it. */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun UserMessage(vm: AppViewModel, b: Bubble, onEdit: (Bubble) -> Unit) {
    val clip = LocalClipboardManager.current
    var menu by remember { mutableStateOf(false) }
    BoxWithConstraints(Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterEnd) {
        Column(Modifier.widthIn(max = maxWidth * 0.8f), horizontalAlignment = Alignment.End, verticalArrangement = Arrangement.spacedBy(6.dp)) {
            DocRow(vm, b.docs)
            if (b.text.isNotBlank() && b.text != "(sent a picture)" && b.text != "(sent a file)") Box {
                Text(
                    b.text, style = MaterialTheme.typography.bodyLarge,
                    modifier = Modifier                                // as wide as the words, at most 80%
                        .clip(RoundedCornerShape(18.dp, 18.dp, 4.dp, 18.dp)).background(Emvryx.surface2)
                        .combinedClickable(onClick = {}, onLongClick = { menu = true })
                        .padding(horizontal = 16.dp, vertical = 12.dp),
                )
                DropdownMenu(menu, { menu = false }, containerColor = Emvryx.surface) {
                    DropdownMenuItem({ Text("Copy") }, { clip.setText(AnnotatedString(b.text)); menu = false })
                    if (b.id > 0 && !vm.streaming) DropdownMenuItem({ Text("Edit and ask again") }, { onEdit(b); menu = false })
                }
            }
        }
    }
}

/** .msg.ai: the model's name over a bordered card, then Copy / Regenerate */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun AiMessage(vm: AppViewModel, b: Bubble, isLast: Boolean, onRegen: () -> Unit, onReport: (Bubble) -> Unit) {
    val clip = LocalClipboardManager.current
    val who = vm.modelById(b.model)
    Column(Modifier.fillMaxWidth(0.94f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Logo(Modifier.size(16.dp), kind = who?.name ?: "flare")
            Spacer(Modifier.width(6.dp))
            Text(who?.fullName ?: "Emvryx", color = Emvryx.muted, fontSize = 14.sp)
        }
        Column(
            Modifier.clip(RoundedCornerShape(18.dp, 18.dp, 18.dp, 4.dp)).background(Emvryx.surface)
                .border(1.dp, Emvryx.line, RoundedCornerShape(18.dp, 18.dp, 18.dp, 4.dp))
                .padding(horizontal = 18.dp, vertical = 14.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            if (b.streaming && b.text.isEmpty()) {
                Thinking(vm.working ?: "Thinking…")
            } else SelectionContainer {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Markdown.blocks(b.text + if (b.streaming) " ▍" else "").forEach { block ->
                        when (block) {
                            is Block.Prose -> Text(Markdown.inline(block.text), style = MaterialTheme.typography.bodyLarge)
                            is Block.Code -> Text(
                                block.text, style = Mono, color = Emvryx.text,
                                modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Emvryx.bg)
                                    .border(1.dp, Emvryx.line, RoundedCornerShape(12.dp))
                                    .horizontalScroll(rememberScrollState()).padding(12.dp),
                            )
                        }
                    }
                    if (b.cut) Text("Stopped.", color = Emvryx.muted, fontSize = 13.sp)
                }
            }
        }
        if (!b.streaming && b.text.isNotEmpty()) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Chip("Copy", { clip.setText(AnnotatedString(b.text)) })
                if (isLast && !vm.streaming && b.cut) Chip("Continue →", vm::continueReply)
                if (isLast && !vm.streaming) Chip("Regenerate", onRegen)
                if (b.id > 0 && !vm.streaming) {
                    if (b.fb.isEmpty()) Chip("Report", { onReport(b) }) else Text("Reported", color = Emvryx.muted, fontSize = 13.sp)
                    Chip("New chat from here", { vm.branch(b) })
                }
            }
        }
    }
}

@Composable
private fun Thinking(word: String) {
    val t = rememberInfiniteTransition(label = "thinking")
    val a by t.animateFloat(0.45f, 1f, infiniteRepeatable(tween(900), RepeatMode.Reverse), label = "a")
    Text(word, color = Emvryx.muted, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.alpha(a))
}

// ---------------------------------------------------------------- the message box

@Composable
private fun Composer(vm: AppViewModel, open: Menu?, onMenu: (Menu) -> Unit) {
    val p = LocalPalette.current
    var text by rememberSaveable { mutableStateOf("") }
    LaunchedEffect(vm.draft) { if (vm.draft.isNotEmpty()) text = vm.draft }          // shared from another app
    val shape = RoundedCornerShape(20.dp)
    Column(
        Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 8.dp)
            .clip(shape).background(Emvryx.surface).border(1.dp, Emvryx.line, shape)
            .padding(start = 16.dp, end = 10.dp, top = 12.dp, bottom = 10.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        DocRow(vm, vm.attached, onRemove = vm::unattach)
        if (vm.uploading) Text("Adding…", color = Emvryx.muted, fontSize = 13.sp)
        Box(Modifier.fillMaxWidth().heightIn(min = 24.dp, max = 160.dp)) {
            if (text.isEmpty()) Text("Message Emvryx…", color = Emvryx.muted, style = MaterialTheme.typography.bodyLarge)
            BasicTextField(
                text, { text = it }, Modifier.fillMaxWidth(),
                textStyle = MaterialTheme.typography.bodyLarge.copy(color = Emvryx.text),
                cursorBrush = SolidColor(p.accent),
            )
        }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            // + and the two pills share everything left of the send button; the pills only shorten their words when it really runs out
            // (a Spacer weighted alongside them took a third of the room and cut them to "F…" and "Bala…")
            Row(Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Box(
                    Modifier.size(40.dp).clip(CircleShape).border(1.dp, if (open == Menu.Attach) p.accent else Emvryx.line, CircleShape)
                        .clickable { onMenu(Menu.Attach) },
                    contentAlignment = Alignment.Center,
                ) { Icon(Icons.Default.Add, "Add a picture or file", tint = Emvryx.muted) }
                Pill(open == Menu.Model, filled = true, onClick = { onMenu(Menu.Model) }, Modifier.weight(1f, fill = false)) {
                    Logo(Modifier.size(20.dp), kind = vm.currentModel?.name ?: "flare")
                    Text(vm.currentModel?.fullName ?: "Model", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f, fill = false))
                }
                Pill(open == Menu.Effort, filled = false, onClick = { onMenu(Menu.Effort) }, Modifier.weight(1f, fill = false)) {
                    Text(vm.state?.efforts?.firstOrNull { it.id == vm.effort }?.name ?: "Balanced", fontSize = 14.sp, color = Emvryx.muted, maxLines = 1,
                        overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false))
                }
            }
            val c = vm.ctx
            if (c != null && vm.flag("context_meter")) MemoryRing(c) { onMenu(Menu.Memory) }
            SendButton(stop = vm.streaming, enabled = vm.streaming || ((text.isNotBlank() || vm.attached.isNotEmpty()) && !vm.uploading)) {
                if (vm.streaming) vm.stop() else {
                    vm.send(text)
                    text = ""
                }
            }
        }
    }
}

/** .pill: the model (filled) and effort (plain) buttons under the box */
@Composable
private fun Pill(open: Boolean, filled: Boolean, onClick: () -> Unit, modifier: Modifier = Modifier, content: @Composable RowScope.() -> Unit) {
    val p = LocalPalette.current
    Row(
        modifier.heightIn(min = 44.dp).clip(CircleShape)
            .then(if (filled) Modifier.background(Emvryx.surface2) else Modifier)
            .border(1.dp, if (open) p.accent else Emvryx.line, CircleShape)
            .clickable(onClick = onClick).padding(start = 8.dp, end = 6.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        content()
        Icon(Icons.Default.ArrowDropDown, null, tint = Emvryx.muted, modifier = Modifier.size(18.dp))
    }
}

/** .send: a rounded square in the model's colour with an up arrow; while a reply is written it is .send.stop */
@Composable
private fun SendButton(stop: Boolean, enabled: Boolean, onClick: () -> Unit) {
    val p = LocalPalette.current
    val shape = RoundedCornerShape(12.dp)
    Box(
        Modifier.size(44.dp).alpha(if (enabled) 1f else 0.45f).clip(shape)    // .send[disabled]: faded until there is something to send
            .then(if (stop) Modifier.background(Emvryx.surface2).border(1.dp, Emvryx.line, shape) else Modifier.background(p.accent))
            .clickable(enabled = enabled, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        if (stop) Box(Modifier.size(12.dp).clip(RoundedCornerShape(2.dp)).background(Emvryx.text))
        else Canvas(Modifier.size(20.dp)) {
            val w = 2.4.dp.toPx()
            val c = p.onAccent
            drawLine(c, Offset(size.width / 2, size.height * 0.85f), Offset(size.width / 2, size.height * 0.15f), w, StrokeCap.Round)
            drawLine(c, Offset(size.width / 2, size.height * 0.15f), Offset(size.width * 0.2f, size.height * 0.45f), w, StrokeCap.Round)
            drawLine(c, Offset(size.width / 2, size.height * 0.15f), Offset(size.width * 0.8f, size.height * 0.45f), w, StrokeCap.Round)
        }
    }
}

/** .usage: a thin bar in the model's colour and "Usage: 99.5% · about 397 messages left" */
@Composable
private fun UsageLine(vm: AppViewModel) {
    val p = LocalPalette.current
    val u = vm.usage
    Column(
        Modifier.fillMaxWidth().navigationBarsPadding().padding(top = 10.dp, bottom = 8.dp),
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        if (u != null) {
            val low = !u.exempt && u.fraction <= 0.2
            Box(Modifier.width(220.dp).height(5.dp).clip(CircleShape).background(Emvryx.surface2)) {
                Box(Modifier.fillMaxHeight().fillMaxWidth(u.fraction.toFloat().coerceIn(0f, 1f)).clip(CircleShape)
                    .background(if (low) Emvryx.danger else p.accent))
            }
            Text(u.label, color = if (low) Emvryx.danger else Emvryx.muted, fontSize = 13.sp)
        }
    }
}

// ---------------------------------------------------------------- the menus above the box (.menu, .opt)

@Composable
private fun PopMenu(modifier: Modifier, content: @Composable () -> Unit) {
    Column(
        modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, bottom = 10.dp).heightIn(max = 560.dp)
            .clip(RoundedCornerShape(20.dp)).background(Emvryx.surface).border(1.dp, Emvryx.line, RoundedCornerShape(20.dp))
            .clickable(remember { MutableInteractionSource() }, null) {}
            .verticalScroll(rememberScrollState()).padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) { content() }
}

@Composable
private fun MenuHead(text: String) {
    Text(text, color = Emvryx.muted, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.2.sp,
        modifier = Modifier.padding(horizontal = 6.dp, vertical = 4.dp))
}

@Composable
private fun Opt(selected: Boolean, enabled: Boolean = true, onClick: () -> Unit, content: @Composable RowScope.() -> Unit) {
    val p = LocalPalette.current
    val shape = RoundedCornerShape(14.dp)
    Row(
        Modifier.fillMaxWidth().heightIn(min = 44.dp).alpha(if (enabled) 1f else 0.5f).clip(shape)
            .border(1.dp, if (selected) p.accent else Emvryx.line, shape).clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) { content() }
}

@Composable
private fun ModelMenu(vm: AppViewModel, close: () -> Unit) {
    MenuHead("SELECT MODEL")
    vm.models.forEach { m ->
        Opt(selected = m.id == vm.model, enabled = m.ready, onClick = { vm.pickModel(m.id); close() }) {
            Logo(Modifier.size(30.dp), kind = m.name)
            Column(Modifier.weight(1f)) {
                Text(m.fullName, fontWeight = FontWeight.Bold, fontSize = 16.sp)
                if (m.tagline.isNotBlank()) Text(m.tagline, color = Emvryx.muted, fontSize = 14.sp)
            }
            if (m.badge.isNotBlank()) Text(m.badge, color = Emvryx.muted, fontSize = 13.sp)
        }
    }
    val tours = if (vm.flag("model_tours")) vm.models.filter { it.tour.isNotEmpty() } else emptyList()
    if (tours.isNotEmpty()) {
        MenuHead("TOURS")
        tours.forEach { m ->
            Opt(selected = false, onClick = { close(); vm.replayTour(m) }) {
                Logo(Modifier.size(30.dp), kind = m.name)
                Text("Take the tour of ${m.fullName}", Modifier.weight(1f), fontWeight = FontWeight.Bold, fontSize = 16.sp)
                Text("›", color = Emvryx.muted, fontSize = 18.sp)
            }
        }
    }
}

@Composable
private fun EffortMenu(vm: AppViewModel, close: () -> Unit) {
    MenuHead("HOW MUCH SHOULD IT THINK?")
    vm.state?.efforts.orEmpty().forEach { e ->
        val allowed = vm.effortAllowed(e.id)
        Opt(selected = e.id == vm.effort, enabled = allowed, onClick = { vm.pickEffort(e.id); close() }) {
            Column(Modifier.weight(1f)) {
                Text(buildAnnotatedString {
                    withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append(e.name) }
                    withStyle(SpanStyle(color = Emvryx.muted, fontSize = 14.sp)) { append(" · " + e.use) }
                }, fontSize = 16.sp)
                Text(if (allowed) e.blurb else "Needs Flare or a bigger model.", color = Emvryx.muted, fontSize = 14.sp)
            }
            if (e.id == vm.effort) Text("✓", fontSize = 16.sp)
        }
    }
    Text("Thinking longer is slower and uses more of your usage.", color = Emvryx.muted, fontSize = 12.sp,
        modifier = Modifier.padding(horizontal = 6.dp, vertical = 4.dp))
}

// ---------------------------------------------------------------- the chat list (.side)

@Composable
private fun Sidebar(vm: AppViewModel, onDone: () -> Unit) {
    val p = LocalPalette.current
    var query by rememberSaveable { mutableStateOf("") }
    LaunchedEffect(query) { vm.search(query) }                   // the words inside chats too, from the server (core.js search)
    ModalDrawerSheet(
        drawerContainerColor = Emvryx.side,
        drawerShape = RoundedCornerShape(0.dp),
        windowInsets = androidx.compose.foundation.layout.WindowInsets(0),
        modifier = Modifier.widthIn(max = 312.dp).fillMaxWidth(0.86f)
            .drawBehind { drawLine(Emvryx.line, Offset(size.width, 0f), Offset(size.width, size.height), 1.dp.toPx()) },
    ) {
        Column(Modifier.fillMaxHeight().statusBarsPadding().navigationBarsPadding()) {
            Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 8.dp, top = 12.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                Logo(Modifier.size(32.dp))
                Spacer(Modifier.width(10.dp))
                Text("Emvryx", fontFamily = Heading, fontWeight = FontWeight.SemiBold, fontSize = 20.sp, letterSpacing = (-0.4).sp, modifier = Modifier.weight(1f))
                IconButton(onClick = vm::signOut) { Icon(Icons.AutoMirrored.Filled.ExitToApp, "Sign out", tint = Emvryx.muted) }
            }
            Box(
                Modifier.fillMaxWidth().padding(start = 14.dp, end = 14.dp, top = 12.dp, bottom = 6.dp).heightIn(min = 46.dp)
                    .clip(RoundedCornerShape(14.dp)).background(p.accent)
                    .clickable { vm.newChat(); onDone() },
                contentAlignment = Alignment.Center,
            ) { Text("+ New chat", color = p.onAccent, fontWeight = FontWeight.SemiBold, fontSize = 16.sp) }
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 6.dp).heightIn(min = 40.dp)
                    .clip(RoundedCornerShape(12.dp)).background(Emvryx.surface).border(1.dp, Emvryx.line, RoundedCornerShape(12.dp))
                    .padding(horizontal = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(Icons.Default.Search, null, tint = Emvryx.muted, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(8.dp))
                Box(Modifier.weight(1f).padding(vertical = 8.dp)) {
                    if (query.isEmpty()) Text("Search chats", color = Emvryx.muted, fontSize = 15.sp)
                    BasicTextField(query, { query = it }, Modifier.fillMaxWidth(), singleLine = true,
                        textStyle = MaterialTheme.typography.bodyMedium.copy(color = Emvryx.text, fontSize = 15.sp), cursorBrush = SolidColor(p.accent))
                }
            }
            val shown = vm.chats.filter { query.isBlank() || it.title.contains(query.trim(), ignoreCase = true) }
            LazyColumn(Modifier.weight(1f).padding(horizontal = 14.dp)) {
                groups(shown).forEach { (label, rows) ->
                    item(key = "label-$label") {
                        Text(label, color = Emvryx.muted.copy(alpha = 0.8f), fontSize = 11.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.1.sp,
                            modifier = Modifier.padding(start = 6.dp, top = 14.dp, bottom = 2.dp))
                    }
                    items(rows, key = { it.id }) { c -> ChatRow(vm, c, c.id == vm.chatId) { vm.openChat(c.id); onDone() } }
                }
                val inside = vm.hits.orEmpty().filter { h -> shown.none { it.id == h.id } }
                if (query.isNotBlank() && inside.isNotEmpty()) {
                    item(key = "label-inside") {
                        Text("IN MESSAGES", color = Emvryx.muted.copy(alpha = 0.8f), fontSize = 11.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.1.sp,
                            modifier = Modifier.padding(start = 6.dp, top = 14.dp, bottom = 2.dp))
                    }
                    items(inside, key = { "hit-${it.id}" }) { h ->
                        Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).clickable { vm.openChat(h.id); onDone() }.padding(horizontal = 12.dp, vertical = 8.dp)) {
                            Text(h.title, maxLines = 1, overflow = TextOverflow.Ellipsis, fontSize = 16.sp)
                            if (h.snippet.isNotBlank()) Text(h.snippet, color = Emvryx.muted, fontSize = 13.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
                        }
                    }
                }
                if (shown.isEmpty() && inside.isEmpty()) item {
                    Text(if (query.isBlank()) "No chats yet." else "No chats match.", color = Emvryx.muted, modifier = Modifier.padding(6.dp, 14.dp))
                }
            }
            HorizontalDivider(color = Emvryx.line)
            Column(Modifier.padding(horizontal = 8.dp, vertical = 6.dp)) {          // the rest of Emvryx, as in the website's menu
                SideLink("⌨", "VryxCode") { vm.open(Screen.Code); onDone() }
                SideLink("⚙", "Settings") { vm.open(Screen.Web("/#settings", "Settings")); onDone() }
                if (vm.isAdmin) SideLink("🛡", "Admin") { vm.open(Screen.Web("/#admin", "Admin")); onDone() }
                SideLink("◎", "Everything else (skills, teacher, apps, files)") { vm.open(Screen.Web("/", "Emvryx")); onDone() }
            }
            HorizontalDivider(color = Emvryx.line)
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                val name = vm.state?.user.orEmpty()
                Box(Modifier.size(34.dp).clip(CircleShape).background(p.accent), contentAlignment = Alignment.Center) {
                    Text(name.take(1).uppercase(), color = p.onAccent, fontWeight = FontWeight.Bold)
                }
                Spacer(Modifier.width(10.dp))
                Column {
                    Text(name, fontWeight = FontWeight.SemiBold)
                    vm.state?.let { Text(it.planName, color = Emvryx.muted, fontSize = 14.sp) }
                }
            }
        }
    }
}

/** .row: the current chat has a soft fill and an accent edge on the left. Hold it to pin or delete it. */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun ChatRow(vm: AppViewModel, c: ChatSummary, current: Boolean, onClick: () -> Unit) {
    val p = LocalPalette.current
    var menu by remember { mutableStateOf(false) }
    var confirm by remember { mutableStateOf(false) }
    Box(
        Modifier.fillMaxWidth().heightIn(min = 40.dp).clip(RoundedCornerShape(12.dp))
            .then(if (current) Modifier.background(Emvryx.surface2).drawBehind {
                drawRect(p.accent, size = size.copy(width = 3.dp.toPx()))
            } else Modifier)
            .combinedClickable(onClick = onClick, onLongClick = { menu = true }).padding(horizontal = 12.dp, vertical = 8.dp),
        contentAlignment = Alignment.CenterStart,
    ) {
        Text((if (c.pinned) "📌 " else "") + c.title, maxLines = 1, overflow = TextOverflow.Ellipsis, fontSize = 16.sp)
        DropdownMenu(menu, { menu = false }, containerColor = Emvryx.surface) {
            DropdownMenuItem({ Text(if (c.pinned) "Unpin" else "Pin to the top") }, { vm.pin(c); menu = false })
            DropdownMenuItem({ Text("Delete", color = Emvryx.danger) }, { confirm = true; menu = false })
        }
    }
    if (confirm) androidx.compose.material3.AlertDialog(
        onDismissRequest = { confirm = false }, containerColor = Emvryx.surface,
        title = { Text("Delete this chat?") }, text = { Text("\"${c.title}\" and its messages are deleted. This can't be undone.") },
        confirmButton = { androidx.compose.material3.TextButton({ vm.delete(c); confirm = false }) { Text("Delete", color = Emvryx.danger) } },
        dismissButton = { androidx.compose.material3.TextButton({ confirm = false }) { Text("Cancel") } },
    )
}

/** Today / Yesterday / Previous 7 days / Older, by when each chat was last used */
internal fun groups(chats: List<ChatSummary>, today: LocalDate = LocalDate.now()): List<Pair<String, List<ChatSummary>>> {
    fun day(c: ChatSummary) = Instant.ofEpochMilli((c.updated * 1000).toLong()).atZone(ZoneId.systemDefault()).toLocalDate()
    val sorted = chats.sortedWith(compareByDescending<ChatSummary> { it.pinned }.thenByDescending { it.updated })
    return sorted.groupBy { c ->
        val d = day(c)
        when {
            c.pinned -> "PINNED"
            d >= today -> "TODAY"
            d >= today.minusDays(1) -> "YESTERDAY"
            d >= today.minusDays(7) -> "PREVIOUS 7 DAYS"
            else -> "OLDER"
        }
    }.toList()
}
