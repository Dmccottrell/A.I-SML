package app.emvryx.android

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.key
import androidx.core.content.IntentCompat
import androidx.lifecycle.lifecycleScope
import app.emvryx.android.ui.AppViewModel
import app.emvryx.android.ui.ChatScreen
import app.emvryx.android.ui.CodeScreen
import app.emvryx.android.ui.CodeViewModel
import app.emvryx.android.ui.OffScreen
import app.emvryx.android.ui.Screen
import app.emvryx.android.ui.SignInScreen
import app.emvryx.android.ui.StartingScreen
import app.emvryx.android.ui.WebScreen
import app.emvryx.android.ui.readPicked
import app.emvryx.android.ui.theme.EmvryxTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : ComponentActivity() {
    private val vm: AppViewModel by viewModels()
    private val code: CodeViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge(SystemBarStyle.dark(android.graphics.Color.TRANSPARENT), SystemBarStyle.dark(android.graphics.Color.TRANSPARENT))
        setContent { Root(vm, code) }
        if (savedInstanceState == null) shared(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        shared(intent)
    }

    /** "Share to Emvryx" from another app: text goes in the message box, pictures and files are attached to a new chat */
    private fun shared(intent: Intent?) {
        if (intent?.action != Intent.ACTION_SEND && intent?.action != Intent.ACTION_SEND_MULTIPLE) return
        val text = intent.getStringExtra(Intent.EXTRA_TEXT)
        val uris = if (intent.action == Intent.ACTION_SEND_MULTIPLE)
            IntentCompat.getParcelableArrayListExtra(intent, Intent.EXTRA_STREAM, Uri::class.java).orEmpty().take(3)
        else listOfNotNull(IntentCompat.getParcelableExtra(intent, Intent.EXTRA_STREAM, Uri::class.java))
        lifecycleScope.launch {
            val files = withContext(Dispatchers.IO) { uris.mapNotNull { readPicked(this@MainActivity, it) } }
            vm.incoming(text, files)
        }
    }
}

@Composable
private fun Root(vm: AppViewModel, code: CodeViewModel) {
    // the chat follows the chosen model's colours; sign-in and the "off" page are Emvryx amber (web/js/core.js applyTheme)
    EmvryxTheme(model = if (vm.screen == Screen.Chat) vm.currentModel?.name else null) {
        Surface(color = MaterialTheme.colorScheme.background) { Screens(vm, code) }   // gives every screen the light text colour
    }
}

@Composable
private fun Screens(vm: AppViewModel, code: CodeViewModel) {
    when (val s = vm.screen) {
        Screen.Starting -> StartingScreen()
        is Screen.Off -> OffScreen(s, onRetry = vm::start, onChangeServer = vm::changeServer)
        Screen.SignIn -> SignInScreen(vm)
        Screen.Chat -> ChatScreen(vm)
        Screen.Code -> CodeScreen(vm, code)
        is Screen.Web -> key(s.path) { WebScreen(vm, s.path, s.title) }      // a new page gets a new WebView (the old one would keep showing the last page)
    }
}
