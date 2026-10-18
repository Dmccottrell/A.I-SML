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
        setContent {
            EmvryxTheme {
                Surface(color = MaterialTheme.colorScheme.background) { Root() }   // gives every screen the light text colour
            }
        }
    }
}

@Composable
private fun Root(vm: AppViewModel = viewModel()) {
    when (val s = vm.screen) {
        Screen.Starting -> StartingScreen()
        is Screen.Off -> OffScreen(s, onRetry = vm::start, onChangeServer = vm::changeServer)
        Screen.SignIn -> SignInScreen(vm)
        Screen.Chat -> ChatScreen(vm)
    }
}
