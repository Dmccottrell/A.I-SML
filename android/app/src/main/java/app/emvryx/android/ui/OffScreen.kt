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

// OffScreen.kt: the two "waiting" screens. StartingScreen shows while the app checks the server. OffScreen shows when the server
// (the owner's home PC) cannot be reached. offTip builds the hint line about the phone's own offline model.

/** The first screen on launch: the pulsing logo and a spinner, shown while the app works out whether the server is up and who is signed in. */
@Composable
fun StartingScreen() {
    // Full-screen box with the soft colour glow behind it, content in the middle.
    Box(Modifier.fillMaxSize().accentWash(LocalPalette.current.glow, 420.dp), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(20.dp)) {
            // The logo pulses to show the app is alive.
            Logo(Modifier.size(72.dp), animate = true)
            CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 2.dp, color = LocalPalette.current.accent)
        }
    }
}

/**
 * The PC is off (no answer at all) or resting in Gaming mode.
 * [s] says which (resting or off) and which server address was tried. [onRetry] checks again, [onChangeServer] opens the server
 * address screen, [onLocal] (optional) opens the on-phone chat, and [tip] (optional) is an extra hint line from [offTip].
 */
@Composable
fun OffScreen(s: Screen.Off, onRetry: () -> Unit, onChangeServer: () -> Unit, onLocal: (() -> Unit)? = null, tip: String? = null) {
    // safeDrawingPadding keeps the content away from the status bar, notch and keyboard.
    Box(Modifier.fillMaxSize().accentWash(LocalPalette.current.glow, 420.dp).safeDrawingPadding(), contentAlignment = Alignment.Center) {
        Column(
            // Cap the width at 420 dp so it reads well on tablets.
            Modifier.widthIn(max = 420.dp).padding(28.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Logo(Modifier.size(64.dp))
            Text(
                // Title: resting means the PC is busy with a game (Gaming mode); otherwise it is simply off or unreachable.
                if (s.resting) "Emvryx is resting" else "Emvryx is off right now",
                fontFamily = Heading, fontWeight = FontWeight.SemiBold, fontSize = 26.sp, textAlign = TextAlign.Center,
            )
            Text(
                if (s.resting) "The PC is being used for something else. Please try again in a little while."
                else "It runs on a home PC, and that PC is switched off, asleep, or offline. Your chats are safe and will be here when it is back.",
                color = Emvryx.muted, textAlign = TextAlign.Center, fontSize = 16.sp,
            )
            // Ask the app to check the server again.
            PwaButton("Try again", onRetry, Modifier.fillMaxWidth().padding(top = 6.dp))
            // android_offline_model: the model on this phone answers while the PC is off
            if (onLocal != null) PwaButton("Chat on this phone", onLocal, Modifier.fillMaxWidth(), ghost = true)
            // Optional hint about the phone model.
            if (tip != null) Text(tip, color = Emvryx.muted, textAlign = TextAlign.Center, fontSize = 14.sp)
            // Show the server address without https://; tapping it lets the user change the server.
            Text(s.server.substringAfter("://"), color = Emvryx.muted, fontSize = 14.sp,
                modifier = Modifier.clickable(onClick = onChangeServer).padding(8.dp))
        }
    }
}

/**
 * android_offline_model: what the "off" screen says about the phone's own model when it cannot answer yet (null: nothing to say)
 * [allowed] = the feature is on for this user, [ready] = the phone model is downloaded, [downloading] = a download is in progress.
 */
fun offTip(allowed: Boolean, ready: Boolean, downloading: Boolean): String? = when {
    // Nothing to say if the feature is not allowed, or the phone model is already ready.
    !allowed || ready -> null
    downloading -> "The phone model is still downloading: it carries on when the PC is back, and then Emvryx answers here even with the PC off."
    else -> "Tip: download the phone model while the PC is on (Settings > This phone), so Emvryx answers here next time the PC is off."
}
