package app.emvryx.android

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.lifecycle.viewmodel.compose.viewModel
import app.emvryx.android.ui.AppViewModel
import app.emvryx.android.ui.ChatScreen
import app.emvryx.android.ui.OffScreen
import app.emvryx.android.ui.Screen
import app.emvryx.android.ui.SignInScreen
import app.emvryx.android.ui.StartingScreen
import app.emvryx.android.ui.theme.EmvryxTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge(SystemBarStyle.dark(android.graphics.Color.TRANSPARENT), SystemBarStyle.dark(android.graphics.Color.TRANSPARENT))
        setContent { Root() }
    }
}

@Composable
private fun Root(vm: AppViewModel = viewModel()) {
    // the chat follows the chosen model's colours; sign-in and the "off" page are Emvryx amber (web/js/core.js applyTheme)
    EmvryxTheme(model = if (vm.screen == Screen.Chat) vm.currentModel?.name else null) {
        Surface(color = MaterialTheme.colorScheme.background) { Screens(vm) }   // gives every screen the light text colour
    }
}

@Composable
private fun Screens(vm: AppViewModel) {
    when (val s = vm.screen) {
        Screen.Starting -> StartingScreen()
        is Screen.Off -> OffScreen(s, onRetry = vm::start, onChangeServer = vm::changeServer)
        Screen.SignIn -> SignInScreen(vm)
        Screen.Chat -> ChatScreen(vm)
    }
}
