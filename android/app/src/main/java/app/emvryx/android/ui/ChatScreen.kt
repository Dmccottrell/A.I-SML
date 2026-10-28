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
import androidx.compose.animation.animateColorAsState
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
import androidx.compose.runtime.derivedStateOf
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
import app.emvryx.android.ui.theme.Palettes
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.LinearOutSlowInEasing
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.compositeOver
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.text.TextStyle
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
    var showUsage by remember { mutableStateOf(false) }
    var saving by remember { mutableStateOf<String?>(null) }           // the text "Save as" was opened for
    var folderFor by remember { mutableStateOf<ChatSummary?>(null) }
    var saveText by remember { mutableStateOf("") }
    var saveFormat by remember { mutableStateOf("pdf") }
    val saveFile = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/octet-stream")) { uri ->
        uri?.let { vm.saveAs(it, saveText, saveFormat) }
    }
    val onSaveAs: (String) -> Unit = { saving = it }
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
    LaunchedEffect(Unit) { vm.checkSignInOptions() }

    ModalNavigationDrawer(
        drawerState = drawer,
        scrimColor = Color.Black.copy(alpha = 0.55f),
        drawerContent = { Sidebar(vm, onDone = { scope.launch { drawer.close() } }, onFolder = { folderFor = it }) },
    ) {
        val p = LocalPalette.current
        Box(Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize().background(Emvryx.bg).then(if (Emvryx.modern) Modifier.modernGlow(p.accent) else Modifier.accentWash(p.glow)).imePadding()) {
            TopBar(vm, onMenu = {
                menu = null
                scope.launch {
                    drawer.open()                                    // slide in first, then fetch: the list was already loaded
                    vm.refreshChats()
                }
            }, onSaveAs = { onSaveAs(vm.chatAsText()) })
            if (vm.state?.demo == true) DemoBanner()
            Box(Modifier.weight(1f).fillMaxWidth()) {
                Thread(vm, onRegen = { menu = Menu.Regen }, onEdit = { editing = it }, onReport = { reporting = it }, onSaveAs = onSaveAs)
                if (menu != null) {
                    // tapping anywhere else closes the menu, as on the website
                    Box(Modifier.fillMaxSize().clickable(remember { MutableInteractionSource() }, null) { menu = null })
                    PopMenu(Modifier.align(Alignment.BottomCenter)) {
                        when (menu) {
                            Menu.Model -> ModelMenu(vm) { menu = null }
                            Menu.Effort -> EffortMenu(vm) { menu = null }
                            Menu.Memory -> vm.shownCtx?.let { c -> MemoryDetails(vm, c) { menu = null } }
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
            UsageLine(vm, onClick = { showUsage = true })
        }
        ModelWash(vm.washes, vm.currentModel?.name)
        }
    }
    if (showUsage) vm.usage?.let { UsageDialog(it) { showUsage = false } }
    saving?.let { text ->
        SaveAsDialog(text, onPick = { f ->
            saveText = text
            saveFormat = f
            saveFile.launch(vm.title.replace(Regex("[^A-Za-z0-9 _-]"), "").trim().ifEmpty { "document" }.take(60) + "." + f)
        }, onClose = { saving = null })
    }
    ShareDialog(vm)
    ArchivedDialog(vm, onOpen = vm::openChat)
    folderFor?.let { c -> FolderDialog(c.folder, onSave = { vm.moveToFolder(c, it) }, onClose = { folderFor = null }) }
    vm.toast?.let { t ->
        LaunchedEffect(t) { kotlinx.coroutines.delay(3000); vm.toast = null }
        Box(Modifier.fillMaxSize().navigationBarsPadding().padding(bottom = 90.dp), contentAlignment = Alignment.BottomCenter) {
            Text(t, color = Emvryx.text, modifier = Modifier.clip(RoundedCornerShape(14.dp)).background(Emvryx.surface2)
                .border(1.dp, Emvryx.line, RoundedCornerShape(14.dp)).padding(horizontal = 16.dp, vertical = 10.dp))
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
private fun TopBar(vm: AppViewModel, onMenu: () -> Unit, onSaveAs: () -> Unit) {
    var more by remember { mutableStateOf(false) }
    var confirm by remember { mutableStateOf(false) }
    Column(Modifier.statusBarsPadding()) {
        Row(Modifier.fillMaxWidth().height(60.dp).padding(horizontal = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onMenu) { Icon(Icons.Default.Menu, "Chats", tint = Emvryx.text) }
            Text(
                vm.title, fontWeight = FontWeight.SemiBold, fontSize = 17.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f).padding(horizontal = 8.dp),
            )
            IconButton(onClick = vm::toggleLight) {                  // the website's moon: switch dark or light
                val ink = Emvryx.text
                Canvas(Modifier.size(20.dp)) {                       // a crescent: a disc with a second disc taken out of it
                    val r = size.minDimension * 0.42f
                    val c = Offset(size.width / 2, size.height / 2)
                    val moon = androidx.compose.ui.graphics.Path().apply {
                        op(
                            androidx.compose.ui.graphics.Path().apply { addOval(androidx.compose.ui.geometry.Rect(c, r)) },
                            androidx.compose.ui.graphics.Path().apply { addOval(androidx.compose.ui.geometry.Rect(Offset(c.x + r * 0.55f, c.y - r * 0.45f), r * 0.85f)) },
                            androidx.compose.ui.graphics.PathOperation.Difference,
                        )
                    }
                    drawPath(moon, ink, style = androidx.compose.ui.graphics.drawscope.Stroke(1.8.dp.toPx()))
                }
            }
            if (vm.chatId != null && vm.bubbles.isNotEmpty()) Box {
                IconButton(onClick = { more = true }) { Text("⋯", fontSize = 22.sp, color = Emvryx.text) }
                DropdownMenu(more, { more = false }, containerColor = Emvryx.surface) {
                    if (!vm.isPrivate) DropdownMenuItem({ Text("Share a link…") }, { more = false; vm.loadShares() })
                    DropdownMenuItem({ Text("Save as PDF or Word…") }, { more = false; onSaveAs() })
                    if (!vm.isPrivate) DropdownMenuItem({ Text("Archive (still remembered)") }, { more = false; vm.archiveThis() })
                    if (!vm.isPrivate) DropdownMenuItem({ Text("Delete this chat", color = Emvryx.danger) }, { more = false; confirm = true })
                }
            }
            IconButton(onClick = { vm.newChat() }, enabled = !vm.streaming) { Icon(Icons.Default.Add, "New chat", tint = Emvryx.text) }
        }
        if (confirm) androidx.compose.material3.AlertDialog(
            onDismissRequest = { confirm = false }, containerColor = Emvryx.surface,
            title = { Text("Delete this chat?") }, text = { Text("\"${vm.title}\" and its messages are deleted. This can't be undone.") },
            confirmButton = { androidx.compose.material3.TextButton({ vm.chatId?.let { vm.delete(ChatSummary(it, vm.title)) }; confirm = false }) { Text("Delete", color = Emvryx.danger) } },
            dismissButton = { androidx.compose.material3.TextButton({ confirm = false }) { Text("Cancel") } },
        )
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
private fun Thread(vm: AppViewModel, onRegen: () -> Unit, onEdit: (Bubble) -> Unit, onReport: (Bubble) -> Unit, onSaveAs: (String) -> Unit) {
    val list = rememberLazyListState()
    val scope = rememberCoroutineScope()
    val last = vm.bubbles.lastOrNull()
    // follow the newest words while you are at the bottom; once you scroll up to read, it stays put and offers "Jump to the newest"
    val atEnd by remember { derivedStateOf { list.layoutInfo.visibleItemsInfo.lastOrNull()?.let { it.index >= list.layoutInfo.totalItemsCount - 2 } ?: true } }
    LaunchedEffect(vm.bubbles.size, last?.text?.length, vm.failure) {
        if (vm.bubbles.isNotEmpty() && (atEnd || last?.mine == true)) list.scrollToItem(list.layoutInfo.totalItemsCount.coerceAtLeast(1) - 1, Int.MAX_VALUE / 2)
    }
    if (vm.bubbles.isEmpty()) {
        Empty(vm)
        return
    }
    val lastReply = vm.bubbles.indexOfLast { !it.mine }
    Box(Modifier.fillMaxSize()) {
    LazyColumn(
        Modifier.fillMaxSize(), state = list,
        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 24.dp, bottom = 8.dp),
        verticalArrangement = Arrangement.spacedBy(22.dp),
    ) {
        if (vm.isPrivate) item(key = "private") { Note("Private chat: not saved, and gone when you leave it") }
        items(vm.bubbles.size, key = { vm.bubbles[it].key }) { i ->
            val b = vm.bubbles[i]
            if (b.mine) {
                if (b.text.startsWith(AppViewModel.SUMMARY_MARK)) Note("Earlier messages were summarized to save room")
                else UserMessage(vm, b, onEdit)
            }
            else AiMessage(vm, b, isLast = i == lastReply && i == vm.bubbles.lastIndex, onRegen = onRegen, onReport = onReport, onSaveAs = onSaveAs)
        }
        vm.failure?.let { f -> item(key = "failure") { FailureCard(vm, f) } }
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
    if (!atEnd) Box(                                                    // "Jump to the newest message"
        Modifier.align(Alignment.BottomEnd).padding(16.dp).size(44.dp).clip(CircleShape).background(Emvryx.surface2)
            .border(1.dp, Emvryx.line, CircleShape).clickable { scope.launch { list.animateScrollToItem(list.layoutInfo.totalItemsCount.coerceAtLeast(1) - 1) } },
        contentAlignment = Alignment.Center,
    ) { Text("↓", fontSize = 20.sp, color = Emvryx.text) }
    }
}

@Composable
private fun Empty(vm: AppViewModel) {
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 24.dp),
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center,
    ) {
        val p = LocalPalette.current
        if (Emvryx.modern) {
            // modern: the mark floats with a glow, and the greeting is bold with the accent in its lower half (modern.css .empty)
            val t = rememberInfiniteTransition(label = "float")
            val y by t.animateFloat(0f, -6f, infiniteRepeatable(tween(2500), RepeatMode.Reverse), label = "y")
            Box(Modifier.size(96.dp).graphicsLayer { translationY = y.dp.toPx() }
                .drawBehind { drawCircle(Brush.radialGradient(listOf(Look.halo(p.accent), Color.Transparent)), size.minDimension / 2) },
                contentAlignment = Alignment.Center) { Logo(Modifier.size(64.dp), kind = vm.currentModel?.name ?: "flare") }
            Text("How can I help?", fontFamily = Heading, fontWeight = FontWeight.Bold, fontSize = 34.sp, letterSpacing = (-1.2).sp, textAlign = TextAlign.Center,
                style = TextStyle(brush = Brush.verticalGradient(listOf(Emvryx.text, androidx.compose.ui.graphics.lerp(Emvryx.text, p.accent, 0.38f)))),
                modifier = Modifier.padding(top = 4.dp, bottom = 6.dp))
        } else {
            Logo(Modifier.size(64.dp), kind = vm.currentModel?.name ?: "flare")
            Text("How can I help?", fontFamily = Heading, fontWeight = FontWeight.SemiBold, fontSize = 32.sp, letterSpacing = (-0.6).sp,
                textAlign = TextAlign.Center, modifier = Modifier.padding(top = 12.dp, bottom = 6.dp))
        }
        Text(if (vm.isPrivate) "Private chat: not saved, never searched on the web, and it uses no memory. Gone when you leave it."
             else "Ask anything. Pick a model and how much it should think under the box.", color = Emvryx.muted, fontSize = 16.sp, textAlign = TextAlign.Center)
        vm.notice?.let { Text(it, color = Emvryx.danger, textAlign = TextAlign.Center, modifier = Modifier.padding(top = 16.dp)) }
        vm.failure?.let { Box(Modifier.padding(top = 16.dp)) { FailureCard(vm, it) } }
        if (vm.state?.briefing == true && !vm.isPrivate) YourDayCard(vm)
        if (Emvryx.modern && !vm.isPrivate && vm.failure == null) Ideas { vm.draft = it }
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
                        .then(if (Emvryx.modern) {
                            // modern: a bubble tinted with the model's colour, with a fine edge (modern.css .msg.user .bubble)
                            val p = LocalPalette.current
                            val s = RoundedCornerShape(22.dp, 22.dp, 6.dp, 22.dp)
                            Modifier.clip(s).background(Brush.linearGradient(listOf(
                                androidx.compose.ui.graphics.lerp(Emvryx.surface2, p.accent, 0.22f), androidx.compose.ui.graphics.lerp(Emvryx.surface2, p.accent, 0.10f))))
                                .border(1.dp, Look.edge(p.accent), s)
                        } else Modifier.clip(RoundedCornerShape(18.dp, 18.dp, 4.dp, 18.dp)).background(Emvryx.surface2))
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
private fun AiMessage(vm: AppViewModel, b: Bubble, isLast: Boolean, onRegen: () -> Unit, onReport: (Bubble) -> Unit, onSaveAs: (String) -> Unit) {
    val clip = LocalClipboardManager.current
    val who = vm.modelById(b.model)
    var more by remember { mutableStateOf(false) }
    var copied by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxWidth(0.94f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Logo(Modifier.size(16.dp), kind = who?.name ?: "flare")
            Spacer(Modifier.width(6.dp))
            Text((who?.fullName ?: "Emvryx") + (if (b.cut && !b.streaming) " · stopped" else "") + (b.autoNote?.let { " · $it" } ?: ""),
                color = if (Emvryx.modern) LocalPalette.current.accentText else Emvryx.muted, fontSize = 14.sp,
                fontWeight = if (Emvryx.modern) FontWeight.SemiBold else FontWeight.Normal)
        }
        lookupText(b.notes)?.let { Note(it) }
        val bar = LocalPalette.current.accent
        Column(
            if (Emvryx.modern) Modifier.drawBehind {                 // modern: the answer sits on the page, a thin accent line down its left
                    val w = 2.dp.toPx()
                    val top = 6.dp.toPx()
                    drawRoundRect(Brush.verticalGradient(listOf(bar.copy(alpha = 0.7f), Color.Transparent), startY = top, endY = size.height - top),
                        topLeft = Offset(0f, top), size = androidx.compose.ui.geometry.Size(w, size.height - 2 * top),
                        cornerRadius = androidx.compose.ui.geometry.CornerRadius(w))
                }.padding(start = 14.dp, top = 2.dp, bottom = 2.dp, end = 2.dp)
            else Modifier.clip(RoundedCornerShape(18.dp, 18.dp, 18.dp, 4.dp)).background(Emvryx.surface)
                .border(1.dp, Emvryx.line, RoundedCornerShape(18.dp, 18.dp, 18.dp, 4.dp))
                .padding(horizontal = 18.dp, vertical = 14.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            if (b.streaming && b.text.isEmpty()) {
                ThinkingRow(vm)
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
                            is Block.Table -> MdTable(block)
                        }
                    }
                    if (b.cut) Text("Stopped.", color = Emvryx.muted, fontSize = 13.sp)
                }
            }
        }
        if (!b.streaming && b.text.isNotEmpty()) {
            // the answer's buttons as on the website: Copy, Right, Continue, Regenerate, and the less-used ones behind ⋯ (chat.js bubble)
            val saved = vm.chatId?.let { it >= 0 } == true && b.id > 0
            val stronger = if (isLast && !vm.streaming) vm.strongerModel(b.model) else null
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Chip(if (copied) "Copied" else "Copy", { clip.setText(AnnotatedString(b.text)); copied = true })
                if (saved) Chip(b.liked ?: "👍 Right", { if (b.liked == null) vm.like(b) })
                if (isLast && !vm.streaming && b.cut) Chip("Continue →", vm::continueReply)
                if (isLast && !vm.streaming) Chip("Regenerate ▾", onRegen)
                Box {
                    Chip("⋯", { more = true })
                    DropdownMenu(more, { more = false }, containerColor = Emvryx.surface) {
                        DropdownMenuItem({ Text("Save as…") }, { more = false; onSaveAs(b.text) })
                        stronger?.let { m -> DropdownMenuItem({ Text("Ask ${m.name} (a stronger model)") }, { more = false; vm.askStronger(m) }) }
                        if (b.id > 0 && !vm.streaming && vm.chatId != null) DropdownMenuItem({ Text("Branch: new chat from here") }, { more = false; vm.branch(b) })
                        if (saved) DropdownMenuItem({ Text(if (b.fb.isEmpty()) "Report a problem…" else "Reported (thanks)") },
                            { more = false; if (b.fb.isEmpty()) onReport(b) })
                    }
                }
            }
        }
        b.memory?.let { Note(it) }
        b.timing?.let { Note(timingText(it)) }
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
    val modern = Emvryx.modern
    val shape = RoundedCornerShape(if (modern) 28.dp else 20.dp)
    val typing = remember { MutableInteractionSource() }
    val focused by typing.collectIsFocusedAsState()
    // model_bar: the box's edge and glow in the chosen model's own colour (index.html body.mbar .composer .card), easing to the next model's,
    // and a pulse of it when a model is picked (the mbarSwap animation); the rest of the app keeps its colours
    val bar by animateColorAsState(if (Emvryx.modelBar) Palettes.own(vm.currentModel?.name, Emvryx.light).accent else p.accent, tween(600), label = "bar")
    val pulse = remember { Animatable(0f) }
    var seenWash by remember { mutableStateOf(vm.washes) }
    LaunchedEffect(vm.washes) {
        if (vm.washes == seenWash) return@LaunchedEffect
        seenWash = vm.washes
        if (!Emvryx.modelBar) return@LaunchedEffect
        pulse.snapTo(1f)
        pulse.animateTo(0f, tween(1200, easing = LinearOutSlowInEasing))
    }
    val ring = if (pulse.value > 0.01f) Modifier.border((2 + 6 * pulse.value).dp, bar.copy(alpha = 0.45f * pulse.value), RoundedCornerShape(32.dp)) else Modifier
    Column(
        if (modern) Modifier.fillMaxWidth().padding(start = 12.dp, end = 12.dp, top = 8.dp).then(ring)
            // modern: a glass card with an edge in the model's colour; it lights up while you type (modern.css .composer .card)
            .then(if (focused) Modifier.border(4.dp, Look.soft(bar), RoundedCornerShape(32.dp)).padding(4.dp) else Modifier.padding(4.dp))
            .shadow(if (focused) 18.dp else 12.dp, shape, ambientColor = if (focused || Emvryx.modelBar) bar else Color.Black, spotColor = if (focused || Emvryx.modelBar) bar else Color.Black)
            .clip(shape).background(Emvryx.surface.copy(alpha = 0.94f).compositeOver(Emvryx.bg))
            .border(1.dp, if (focused) bar else if (Emvryx.modelBar) androidx.compose.ui.graphics.lerp(Emvryx.line, bar, 0.55f) else Look.edge(bar), shape)
            .padding(start = 18.dp, end = 10.dp, top = 14.dp, bottom = 10.dp)
        else Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 8.dp).then(ring)
            .clip(shape).background(Emvryx.surface)
            .border(1.dp, if (Emvryx.modelBar) (if (focused) bar else androidx.compose.ui.graphics.lerp(Emvryx.line, bar, 0.55f)) else Emvryx.line, shape)
            .padding(start = 16.dp, end = 10.dp, top = 12.dp, bottom = 10.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        DocRow(vm, vm.attached, onRemove = vm::unattach)
        if (vm.uploading) Text("Adding…", color = Emvryx.muted, fontSize = 13.sp)
        Box(Modifier.fillMaxWidth().heightIn(min = 24.dp, max = 160.dp)) {
            if (text.isEmpty()) Text("Message Emvryx…", color = Emvryx.muted, style = MaterialTheme.typography.bodyLarge)
            BasicTextField(
                text, { text = it }, Modifier.fillMaxWidth(), interactionSource = typing,
                textStyle = MaterialTheme.typography.bodyLarge.copy(color = Emvryx.text),
                cursorBrush = SolidColor(p.accent),
            )
        }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            // + and the two pills share everything left of the send button; the pills only shorten their words when it really runs out
            // (a Spacer weighted alongside them took a third of the room and cut them to "F…" and "Bala…")
            Row(Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Box(
                    Modifier.size(36.dp).clip(CircleShape).border(1.dp, if (open == Menu.Attach) p.accent else Emvryx.line, CircleShape)
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
            val c = vm.shownCtx
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
            .then(if (Emvryx.modern) {                                 // modern: soft round pills with no outline (modern.css .pill)
                Modifier.background(if (open) Look.soft(p.accent) else if (filled) Emvryx.surface2.copy(alpha = 0.6f) else Color.Transparent)
                    .then(if (open) Modifier.border(1.dp, p.accent, CircleShape) else Modifier)
            } else Modifier.then(if (filled) Modifier.background(Emvryx.surface2) else Modifier)
                .border(1.dp, if (open) p.accent else Emvryx.line, CircleShape))
            .clickable(onClick = onClick).padding(start = 8.dp, end = 2.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        content()
        Icon(Icons.Default.ArrowDropDown, null, tint = Emvryx.muted, modifier = Modifier.size(16.dp))
    }
}

/** .send: a rounded square in the model's colour with an up arrow; while a reply is written it is .send.stop */
@Composable
private fun SendButton(stop: Boolean, enabled: Boolean, onClick: () -> Unit) {
    val p = LocalPalette.current
    val modern = Emvryx.modern
    val shape = if (modern) CircleShape else RoundedCornerShape(12.dp)
    val lit = modern && enabled && !stop
    Box(
        Modifier.size(44.dp)
            .then(if (lit) Modifier.shadow(10.dp, shape, ambientColor = p.accent, spotColor = p.accent) else Modifier)   // modern: a round button with a halo
            .alpha(if (enabled) 1f else if (modern) 0.8f else 0.45f).clip(shape)    // .send[disabled]: faded until there is something to send
            .then(when {
                stop -> Modifier.background(Emvryx.surface2).border(1.dp, Emvryx.line, shape)
                lit -> Modifier.background(Look.shine(p.accent))
                modern -> Modifier.background(Emvryx.surface2)
                else -> Modifier.background(p.accent)
            })
            .clickable(enabled = enabled, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        if (stop) Box(Modifier.size(12.dp).clip(RoundedCornerShape(2.dp)).background(Emvryx.text))
        else Canvas(Modifier.size(20.dp)) {
            val w = 2.4.dp.toPx()
            val c = if (modern && !enabled) Emvryx.muted else p.onAccent
            drawLine(c, Offset(size.width / 2, size.height * 0.85f), Offset(size.width / 2, size.height * 0.15f), w, StrokeCap.Round)
            drawLine(c, Offset(size.width / 2, size.height * 0.15f), Offset(size.width * 0.2f, size.height * 0.45f), w, StrokeCap.Round)
            drawLine(c, Offset(size.width / 2, size.height * 0.15f), Offset(size.width * 0.8f, size.height * 0.45f), w, StrokeCap.Round)
        }
    }
}

/** .usage: a thin bar in the model's colour and "Usage: 99.5% · about 397 messages left" */
@Composable
private fun UsageLine(vm: AppViewModel, onClick: () -> Unit) {
    val p = LocalPalette.current
    val u = vm.usage
    Column(
        Modifier.fillMaxWidth().navigationBarsPadding().clickable(enabled = u != null, onClick = onClick).padding(top = 10.dp, bottom = 8.dp),
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        if (u != null) {
            val low = !u.exempt && u.fraction <= 0.2
            Box(Modifier.width(220.dp).height(5.dp).clip(CircleShape).background(Emvryx.surface2)) {
                Box(Modifier.fillMaxHeight().fillMaxWidth(u.fraction.toFloat().coerceIn(0f, 1f)).clip(CircleShape)
                    .then(if (low) Modifier.background(Emvryx.danger)
                          else if (Emvryx.modern) Modifier.background(Brush.horizontalGradient(listOf(p.accent, androidx.compose.ui.graphics.lerp(p.accent, Color.White, 0.4f))))
                          else Modifier.background(p.accent)))
            }
            Text(u.label, color = if (low) Emvryx.danger else Emvryx.muted, fontSize = 13.sp)
        }
    }
}

// ---------------------------------------------------------------- the menus above the box (.menu, .opt)

@Composable
private fun PopMenu(modifier: Modifier, content: @Composable () -> Unit) {
    val p = LocalPalette.current
    val shape = RoundedCornerShape(if (Emvryx.modern) 24.dp else 20.dp)
    Column(
        modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, bottom = 10.dp).heightIn(max = 560.dp)
            .then(if (Emvryx.modern) Modifier.shadow(24.dp, shape) else Modifier)
            .clip(shape).background(Emvryx.surface).border(1.dp, if (Emvryx.modern) Look.edge(p.accent) else Emvryx.line, shape)
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
    val modern = Emvryx.modern
    val shape = RoundedCornerShape(if (modern) 16.dp else 14.dp)
    Row(
        Modifier.fillMaxWidth().heightIn(min = 44.dp).alpha(if (enabled) 1f else 0.5f).clip(shape)
            .then(if (modern) Modifier.background(if (selected) Look.soft(p.accent) else Emvryx.surface2.copy(alpha = 0.45f))     // modern: soft fills
                .then(if (selected) Modifier.border(1.dp, p.accent, shape) else Modifier)
                else Modifier.border(1.dp, if (selected) p.accent else Emvryx.line, shape)).clickable(enabled = enabled, onClick = onClick)
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
private fun Sidebar(vm: AppViewModel, onDone: () -> Unit, onFolder: (ChatSummary) -> Unit) {
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
                Text("Emvryx", fontFamily = Heading, fontWeight = if (Emvryx.modern) FontWeight.Bold else FontWeight.SemiBold, fontSize = 20.sp,
                    letterSpacing = if (Emvryx.modern) (-0.6).sp else (-0.4).sp, modifier = Modifier.weight(1f))
            }
            Box(
                Modifier.fillMaxWidth().padding(start = 14.dp, end = 14.dp, top = 12.dp, bottom = 6.dp).heightIn(min = if (Emvryx.modern) 48.dp else 46.dp)
                    .then(if (Emvryx.modern) Modifier.shadow(12.dp, RoundedCornerShape(16.dp), ambientColor = p.accent, spotColor = p.accent)
                        .clip(RoundedCornerShape(16.dp)).background(Look.shine(p.accent))       // modern: a shining button with a halo
                        else Modifier.clip(RoundedCornerShape(14.dp)).background(p.accent))
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
            val shown = remember(vm.chats, query) { vm.chats.filter { query.isBlank() || it.title.contains(query.trim(), ignoreCase = true) } }
            val grouped = remember(shown) { groups(shown) }
            LazyColumn(Modifier.weight(1f).padding(horizontal = 14.dp)) {
                grouped.forEach { (label, rows) ->
                    item(key = "label-$label") {
                        Text(label, color = Emvryx.muted.copy(alpha = 0.8f), fontSize = 11.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.1.sp,
                            modifier = Modifier.padding(start = 6.dp, top = 14.dp, bottom = 2.dp))
                    }
                    items(rows, key = { it.id }) { c -> ChatRow(vm, c, c.id == vm.chatId, onFolder) { vm.openChat(c.id); onDone() } }
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
            // the tools, as in the website's menu (tour.js renderLinks); Usage, Memory, Settings and Admin are under your name
            Column(Modifier.padding(horizontal = 8.dp, vertical = 6.dp)) {
                SideLink("lock", "Private chat", "Never saved") { vm.newChat(private = true); onDone() }
                SideLink("code", "VryxCode") { vm.open(Screen.Code); onDone() }
                SideLink("spark", "Skills") { vm.open(vm.panel("skills", Screen.Web("/", "Skills", "openSkills()", panel = true))); onDone() }
                SideLink("pencil", "Teacher mode") { vm.open(Screen.Web("/", "Teacher mode", "newChat(false, 'teacher')")); onDone() }
                SideLink("doc", "Documents") { vm.open(vm.panel("files", Screen.Web("/", "Documents", "openDocs()", panel = true))); onDone() }
            }
            HorizontalDivider(color = Emvryx.line)
            Account(vm, onDone)
        }
    }
}

/** Your name at the bottom of the menu; tapping it opens Usage, Memory, Settings (archived chats are under Data controls there),
 *  Admin, the app lock and Sign out, as the website's account menu does (tour.js acctMenu) */
@Composable
private fun Account(vm: AppViewModel, onDone: () -> Unit) {
    val p = LocalPalette.current
    var open by remember { mutableStateOf(false) }
    var usage by remember { mutableStateOf(false) }
    val name = vm.state?.user.orEmpty()
    Box {
        Row(
            Modifier.fillMaxWidth().clickable { open = !open }.padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(Modifier.size(34.dp).clip(CircleShape).background(p.accent), contentAlignment = Alignment.Center) {
                Text(name.take(1).uppercase(), color = p.onAccent, fontWeight = FontWeight.Bold)
            }
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(name, fontWeight = FontWeight.SemiBold)
                vm.state?.let { Text(it.planName, color = Emvryx.muted, fontSize = 14.sp) }
            }
            PwaIcon("chevron", Emvryx.muted, 18.dp)
        }
        DropdownMenu(open, { open = false }, containerColor = Emvryx.surface) {
            AccountItem("chart", "Usage") { open = false; usage = true }
            AccountItem("brain", "Memory") { open = false; vm.open(vm.panel("memory", Screen.Web("/", "Memory", "openMemory()", panel = true))); onDone() }
            AccountItem("gear", "Settings") { open = false; vm.open(vm.panel("settings", Screen.Web("/#settings", "Settings", panel = true))); onDone() }
            if (vm.isAdmin) AccountItem("shield", "Admin") { open = false; vm.open(Screen.Web("/#admin", "Admin", panel = true)); onDone() }
            AccountItem("lock", "App lock", if (vm.lockOn) "On" else "Off") { vm.setLock(!vm.lockOn) }     // fingerprint, face or screen lock
            AccountItem("signout", "Sign out") { open = false; vm.signOut() }
        }
    }
    if (usage) vm.usage?.let { UsageDialog(it) { usage = false } }
}

@Composable
private fun AccountItem(icon: String, label: String, note: String = "", action: () -> Unit) {
    DropdownMenuItem(
        text = {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(label)
                if (note.isNotBlank()) Text("   $note", color = Emvryx.muted, fontSize = 13.sp)
            }
        },
        leadingIcon = { PwaIcon(icon, Emvryx.muted, 18.dp) },
        onClick = action,
    )
}

/** .row: the current chat has a soft fill and an accent edge on the left. Hold it to pin or delete it. */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun ChatRow(vm: AppViewModel, c: ChatSummary, current: Boolean, onFolder: (ChatSummary) -> Unit, onClick: () -> Unit) {
    val p = LocalPalette.current
    var menu by remember { mutableStateOf(false) }
    var confirm by remember { mutableStateOf(false) }
    Box(
        Modifier.fillMaxWidth().heightIn(min = 40.dp).clip(RoundedCornerShape(12.dp))
            .then(if (current && Emvryx.modern) Modifier.background(Emvryx.surface2.copy(alpha = 0.7f))   // modern: a soft glow from the left, a fine accent edge
                .background(Brush.horizontalGradient(0f to Look.soft(p.accent), 0.92f to Color.Transparent))
                .drawBehind { drawRect(p.accent, size = size.copy(width = 2.dp.toPx())) }
            else if (current) Modifier.background(Emvryx.surface2).drawBehind {
                drawRect(p.accent, size = size.copy(width = 3.dp.toPx()))
            } else Modifier)
            .combinedClickable(onClick = onClick, onLongClick = { menu = true }).padding(horizontal = 12.dp, vertical = 8.dp),
        contentAlignment = Alignment.CenterStart,
    ) {
        Text((if (c.pinned) "📌 " else "") + c.title, maxLines = 1, overflow = TextOverflow.Ellipsis, fontSize = 16.sp)
        DropdownMenu(menu, { menu = false }, containerColor = Emvryx.surface) {
            DropdownMenuItem({ Text(if (c.pinned) "Unpin" else "📌 Pin to the top") }, { vm.pin(c); menu = false })
            DropdownMenuItem({ Text("Move to a folder…") }, { menu = false; onFolder(c) })
            DropdownMenuItem({ Text("🗄️ Archive (still remembered)") }, { menu = false; vm.archive(c) })
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

/** The chat list as the website groups it (core.js renderChats): pinned, then each folder, then by day, then chats started from a
 *  skill or Teacher mode in their own groups at the end */
internal fun groups(chats: List<ChatSummary>, today: LocalDate = LocalDate.now()): List<Pair<String, List<ChatSummary>>> {
    fun day(c: ChatSummary) = Instant.ofEpochMilli((c.updated * 1000).toLong()).atZone(ZoneId.systemDefault()).toLocalDate()
    val sorted = chats.sortedByDescending { it.updated }
    val out = mutableListOf<Pair<String, List<ChatSummary>>>()
    fun add(label: String, list: List<ChatSummary>) { if (list.isNotEmpty()) out += label to list }
    add("PINNED", sorted.filter { it.pinned })
    sorted.filter { it.folder.isNotBlank() && !it.pinned }.map { it.folder }.distinct().forEach { f ->
        add(f.uppercase(), sorted.filter { it.folder == f && !it.pinned })
    }
    val plain = sorted.filter { !it.pinned && it.folder.isBlank() && it.skill.isBlank() }
    plain.groupBy { c ->
        val d = day(c)
        when {
            d >= today -> "TODAY"
            d >= today.minusDays(1) -> "YESTERDAY"
            d >= today.minusDays(7) -> "PREVIOUS 7 DAYS"
            else -> "OLDER"
        }
    }.forEach { (k, v) -> add(k, v) }
    val names = mapOf("teacher" to "TEACHER MODE", "study" to "STUDY HELPER")
    sorted.filter { it.skill.isNotBlank() && !it.pinned && it.folder.isBlank() }.map { it.skill }.distinct().forEach { k ->
        add(names[k] ?: k.uppercase(), sorted.filter { it.skill == k && !it.pinned && it.folder.isBlank() })
    }
    return out
}

/** core.js wash(): when you pick another model its colours swell out from the middle of the screen and fade, over a second.
 *  Drawn in the new model's own colours (its core inside, its accent round it), whatever the screen is still fading from. */
@Composable
private fun ModelWash(count: Int, model: String?) {
    val t = remember { Animatable(1f) }
    var seen by remember { mutableStateOf(count) }
    LaunchedEffect(count) {
        if (count == seen) return@LaunchedEffect
        seen = count
        t.snapTo(0f)
        t.animateTo(1f, tween(1000, easing = LinearOutSlowInEasing))
    }
    val f = t.value
    if (f >= 1f) return
    val p = if (Emvryx.modelBar) Palettes.own(model, Emvryx.light) else Palettes.forModel(model, Emvryx.light, Emvryx.violet)     // model_bar: the wash in the model's own colour
    // @keyframes swell: opacity 0 -> .55 at 45% -> 0, scale .3 -> 2.2
    val a = if (f < 0.45f) 0.55f * f / 0.45f else 0.55f * (1 - (f - 0.45f) / 0.55f)
    val scale = 0.3f + 1.9f * f
    Canvas(Modifier.fillMaxSize()) {
        val r = 500.dp.toPx() * scale
        val c = Offset(size.width / 2, size.height * 0.55f)
        drawCircle(Brush.radialGradient(0f to p.core, 0.30f to p.accent, 0.66f to Color.Transparent, center = c, radius = r), r, c, alpha = a.coerceIn(0f, 1f))
    }
}

/** The modern look's things to try under the greeting (chat.js ML_IDEAS): tap one and it is put in the box */
@Composable
private fun Ideas(onPick: (String) -> Unit) {
    val p = LocalPalette.current
    val ideas = listOf(
        "Explain something" to "Explain how vaccines work like I am twelve.",
        "Plan my day" to "Help me plan a productive day around three things I need to get done.",
        "Write for me" to "Write a short, friendly message asking my landlord to fix the heating.",
        "Look it up" to "What is in the news today?",
    )
    Column(Modifier.padding(top = 22.dp).widthIn(max = 560.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        ideas.chunked(2).forEach { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                row.forEach { (name, text) ->
                    val s = RoundedCornerShape(20.dp)
                    Column(
                        Modifier.weight(1f).clip(s).background(Emvryx.surface.copy(alpha = 0.62f)).border(1.dp, Look.edge(p.accent), s)
                            .clickable { onPick(text) }.padding(horizontal = 16.dp, vertical = 14.dp),
                        verticalArrangement = Arrangement.spacedBy(3.dp),
                    ) {
                        Text(name, fontWeight = FontWeight.Bold, fontSize = 15.sp)
                        Text(text, color = Emvryx.muted, fontSize = 13.sp, maxLines = 3, overflow = TextOverflow.Ellipsis)
                    }
                }
            }
        }
    }
}
