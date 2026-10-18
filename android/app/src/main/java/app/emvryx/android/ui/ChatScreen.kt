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
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ExitToApp
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.NavigationDrawerItem
import androidx.compose.material3.NavigationDrawerItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.emvryx.android.ui.theme.Emvryx
import app.emvryx.android.ui.theme.Mono
import kotlinx.coroutines.launch

@Composable
fun ChatScreen(vm: AppViewModel) {
    val drawer = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    BackHandler(drawer.isOpen) { scope.launch { drawer.close() } }

    ModalNavigationDrawer(
        drawerState = drawer,
        drawerContent = {
            ChatList(vm, onPicked = { scope.launch { drawer.close() } })
        },
    ) {
        Scaffold(
            containerColor = Emvryx.bg,
            topBar = {
                TopBar(vm, onMenu = {
                    vm.refreshChats()
                    scope.launch { drawer.open() }
                })
            },
        ) { pad ->
            Column(Modifier.fillMaxSize().padding(pad).imePadding()) {
                Messages(vm, Modifier.weight(1f))
                vm.notice?.let {
                    Text(
                        it, color = Emvryx.text, style = MaterialTheme.typography.bodyMedium,
                        modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp)
                            .background(Emvryx.surface2, RoundedCornerShape(12.dp)).padding(12.dp),
                    )
                }
                Composer(vm)
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun TopBar(vm: AppViewModel, onMenu: () -> Unit) {
    var open by remember { mutableStateOf(false) }
    TopAppBar(
        colors = TopAppBarDefaults.topAppBarColors(containerColor = Emvryx.bg),
        navigationIcon = { IconButton(onClick = onMenu) { Icon(Icons.Default.Menu, "Chats") } },
        title = {
            Box {
                Row(
                    Modifier.clip12().clickable { open = true }.padding(horizontal = 8.dp, vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(vm.currentModel?.name ?: "Emvryx", fontWeight = FontWeight.SemiBold)
                    Icon(Icons.Default.ArrowDropDown, null, tint = Emvryx.muted)
                }
                DropdownMenu(open, { open = false }, containerColor = Emvryx.surface2) {
                    vm.models.forEach { m ->
                        DropdownMenuItem(
                            text = {
                                Column {
                                    Text(m.name, fontWeight = FontWeight.SemiBold)
                                    if (m.tagline.isNotBlank()) Text(m.tagline, color = Emvryx.muted, style = MaterialTheme.typography.bodySmall)
                                }
                            },
                            trailingIcon = { if (m.id == vm.model) Icon(Icons.Default.Check, null, tint = Emvryx.accent) },
                            onClick = {
                                vm.pickModel(m.id)
                                open = false
                            },
                        )
                    }
                }
            }
        },
        actions = {
            IconButton(onClick = vm::newChat, enabled = !vm.streaming) { Icon(Icons.Default.Edit, "New chat") }
        },
    )
}

@Composable
private fun ChatList(vm: AppViewModel, onPicked: () -> Unit) {
    ModalDrawerSheet(drawerContainerColor = Emvryx.side, modifier = Modifier.widthIn(max = 320.dp)) {
        Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
            Logo(Modifier.size(28.dp))
            Spacer(Modifier.size(10.dp))
            Text("Emvryx", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
        }
        NavigationDrawerItem(
            label = { Text("New chat") }, selected = false,
            icon = { Icon(Icons.Default.Add, null) },
            onClick = {
                vm.newChat()
                onPicked()
            },
            modifier = Modifier.padding(NavigationDrawerItemDefaults.ItemPadding),
        )
        HorizontalDivider(Modifier.padding(vertical = 8.dp), color = Emvryx.line)
        LazyColumn(Modifier.weight(1f)) {
            items(vm.chats, key = { it.id }) { c ->
                NavigationDrawerItem(
                    label = { Text(c.title, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                    selected = c.id == vm.chatId,
                    onClick = {
                        vm.openChat(c.id)
                        onPicked()
                    },
                    colors = NavigationDrawerItemDefaults.colors(selectedContainerColor = Emvryx.surface2, unselectedContainerColor = Color.Transparent),
                    modifier = Modifier.padding(NavigationDrawerItemDefaults.ItemPadding),
                )
            }
        }
        HorizontalDivider(color = Emvryx.line)
        NavigationDrawerItem(
            label = {
                Column {
                    Text(vm.state?.user ?: "")
                    Text("Sign out", color = Emvryx.muted, style = MaterialTheme.typography.bodySmall)
                }
            },
            selected = false,
            icon = { Icon(Icons.AutoMirrored.Filled.ExitToApp, null) },
            onClick = vm::signOut,
            modifier = Modifier.padding(NavigationDrawerItemDefaults.ItemPadding).navigationBarsPadding(),
        )
    }
}

@Composable
private fun Messages(vm: AppViewModel, modifier: Modifier) {
    val list = rememberLazyListState()
    val last = vm.bubbles.lastOrNull()
    LaunchedEffect(vm.bubbles.size, last?.text?.length) {
        if (vm.bubbles.isNotEmpty()) list.scrollToItem(vm.bubbles.lastIndex, Int.MAX_VALUE / 2)
    }
    if (vm.bubbles.isEmpty()) {
        Box(modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
            Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(14.dp)) {
                Logo(Modifier.size(48.dp))
                Text("What can I help with?", style = MaterialTheme.typography.titleLarge)
                if (vm.state?.demo == true) Text("Demo mode: no model is connected.", color = Emvryx.muted)
            }
        }
        return
    }
    LazyColumn(modifier.fillMaxWidth(), state = list, contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)) {
        items(vm.bubbles, key = { it.key }) { b ->
            if (b.mine) UserBubble(b.text) else Reply(b, if (b.streaming && b.text.isEmpty()) vm.working else null)
        }
    }
}

@Composable
private fun UserBubble(text: String) {
    Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterEnd) {
        SelectionContainer {
            Text(
                text,
                modifier = Modifier.widthIn(max = 320.dp).background(Emvryx.surface2, RoundedCornerShape(20.dp)).padding(horizontal = 16.dp, vertical = 10.dp),
                style = MaterialTheme.typography.bodyLarge,
            )
        }
    }
}

@Composable
private fun Reply(b: Bubble, working: String?) {
    if (working != null) {
        Text(working, color = Emvryx.muted, style = MaterialTheme.typography.bodyLarge)
        return
    }
    SelectionContainer {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            val blocks = Markdown.blocks(b.text + if (b.streaming) " ▍" else "")
            blocks.forEach { block ->
                when (block) {
                    is Block.Prose -> Text(Markdown.inline(block.text), style = MaterialTheme.typography.bodyLarge)
                    is Block.Code -> Text(
                        block.text, style = Mono, color = Emvryx.text,
                        modifier = Modifier.fillMaxWidth().background(Emvryx.surface, RoundedCornerShape(12.dp))
                            .border(1.dp, Emvryx.line, RoundedCornerShape(12.dp))
                            .horizontalScroll(rememberScrollState()).padding(12.dp),
                    )
                }
            }
            if (b.cut) Text("Stopped.", color = Emvryx.muted, style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
private fun Composer(vm: AppViewModel) {
    var text by rememberSaveable { mutableStateOf("") }
    Column(
        Modifier.fillMaxWidth().navigationBarsPadding().padding(12.dp)
            .background(Emvryx.surface, RoundedCornerShape(24.dp)).border(1.dp, Emvryx.line, RoundedCornerShape(24.dp))
            .padding(start = 4.dp, end = 8.dp, top = 4.dp, bottom = 8.dp),
    ) {
        TextField(
            text, { text = it },
            modifier = Modifier.fillMaxWidth(),
            placeholder = { Text("Message Emvryx", color = Emvryx.muted) },
            maxLines = 6,
            colors = TextFieldDefaults.colors(
                focusedContainerColor = Color.Transparent, unfocusedContainerColor = Color.Transparent, disabledContainerColor = Color.Transparent,
                focusedIndicatorColor = Color.Transparent, unfocusedIndicatorColor = Color.Transparent,
            ),
        )
        Row(verticalAlignment = Alignment.CenterVertically) {
            Spacer(Modifier.size(8.dp))
            if (vm.currentModel?.supportsEffort == true) EffortPicker(vm)
            Spacer(Modifier.weight(1f))
            if (vm.streaming) {
                FilledIconButton(onClick = vm::stop, colors = IconButtonDefaults.filledIconButtonColors(containerColor = Emvryx.text)) {
                    Box(Modifier.size(12.dp).background(Emvryx.bg, RoundedCornerShape(2.dp)))   // the stop square
                }
            } else {
                FilledIconButton(
                    onClick = {
                        vm.send(text)
                        text = ""
                    },
                    enabled = text.isNotBlank(),
                ) { Icon(Icons.AutoMirrored.Filled.Send, "Send", Modifier.size(20.dp)) }
            }
        }
    }
}

@Composable
private fun EffortPicker(vm: AppViewModel) {
    var open by remember { mutableStateOf(false) }
    val efforts = vm.state?.efforts.orEmpty()
    Box {
        Row(
            Modifier.clip(CircleShape).border(1.dp, Emvryx.line, CircleShape).clickable { open = true }.padding(horizontal = 12.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(efforts.firstOrNull { it.id == vm.effort }?.name ?: "Balanced", style = MaterialTheme.typography.labelLarge, color = Emvryx.muted)
            Icon(Icons.Default.ArrowDropDown, null, tint = Emvryx.muted, modifier = Modifier.size(18.dp))
        }
        DropdownMenu(open, { open = false }, containerColor = Emvryx.surface2) {
            efforts.forEach { e ->
                DropdownMenuItem(
                    text = {
                        Column {
                            Text(e.name, fontWeight = FontWeight.SemiBold)
                            Text(e.use, color = Emvryx.muted, style = MaterialTheme.typography.bodySmall)
                        }
                    },
                    trailingIcon = { if (e.id == vm.effort) Icon(Icons.Default.Check, null, tint = Emvryx.accent) },
                    onClick = {
                        vm.pickEffort(e.id)
                        open = false
                    },
                )
            }
        }
    }
}

private fun Modifier.clip12() = clip(RoundedCornerShape(12.dp))
