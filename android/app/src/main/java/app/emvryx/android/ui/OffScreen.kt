package app.emvryx.android.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.emvryx.android.ui.theme.Emvryx
import app.emvryx.android.ui.theme.Heading
import app.emvryx.android.ui.theme.LocalPalette

@Composable
fun StartingScreen() {
    Box(Modifier.fillMaxSize().accentWash(LocalPalette.current.glow, 420.dp), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(20.dp)) {
            Logo(Modifier.size(72.dp), animate = true)
            CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 2.dp, color = LocalPalette.current.accent)
        }
    }
}

/** The PC is off (no answer at all) or resting in Gaming mode */
@Composable
fun OffScreen(s: Screen.Off, onRetry: () -> Unit, onChangeServer: () -> Unit, onLocal: (() -> Unit)? = null) {
    Box(Modifier.fillMaxSize().accentWash(LocalPalette.current.glow, 420.dp).safeDrawingPadding(), contentAlignment = Alignment.Center) {
        Column(
            Modifier.widthIn(max = 420.dp).padding(28.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Logo(Modifier.size(64.dp))
            Text(
                if (s.resting) "Emvryx is resting" else "Emvryx is off right now",
                fontFamily = Heading, fontWeight = FontWeight.SemiBold, fontSize = 26.sp, textAlign = TextAlign.Center,
            )
            Text(
                if (s.resting) "The PC is being used for something else. Please try again in a little while."
                else "It runs on a home PC, and that PC is switched off, asleep, or offline. Your chats are safe and will be here when it is back.",
                color = Emvryx.muted, textAlign = TextAlign.Center, fontSize = 16.sp,
            )
            PwaButton("Try again", onRetry, Modifier.fillMaxWidth().padding(top = 6.dp))
            // android_offline_model: the model on this phone answers while the PC is off
            if (onLocal != null) PwaButton("Chat on this phone", onLocal, Modifier.fillMaxWidth(), ghost = true)
            Text(s.server.substringAfter("://"), color = Emvryx.muted, fontSize = 14.sp,
                modifier = Modifier.clickable(onClick = onChangeServer).padding(8.dp))
        }
    }
}
