package app.emvryx.android.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import app.emvryx.android.ui.theme.Emvryx

/** The Emvryx mark (web/icon.svg) drawn in violet. */
@Composable
fun Logo(modifier: Modifier = Modifier) {
    Canvas(modifier) {
        val u = size.minDimension / 64f
        val w = 8 * u
        fun line(x1: Float, y1: Float, x2: Float, y2: Float, c: androidx.compose.ui.graphics.Color) =
            drawLine(c, Offset(x1 * u, y1 * u), Offset(x2 * u, y2 * u), w, StrokeCap.Round)
        line(15f, 15f, 42f, 15f, Emvryx.text)
        line(15f, 49f, 42f, 49f, Emvryx.text)
        line(15f, 15f, 15f, 49f, Emvryx.text)
        line(15f, 32f, 34f, 32f, Emvryx.accent)
        drawCircle(Emvryx.accent, 6.5f * u, Offset(49 * u, 32 * u))
    }
}

@Composable
fun StartingScreen() {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(20.dp)) {
            Logo(Modifier.size(72.dp))
            CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 2.dp)
        }
    }
}

/** The PC is off (no answer at all) or resting in Gaming mode: the same wording as the website's offline page. */
@Composable
fun OffScreen(s: Screen.Off, onRetry: () -> Unit, onChangeServer: () -> Unit) {
    Box(Modifier.fillMaxSize().safeDrawingPadding(), contentAlignment = Alignment.Center) {
        Column(
            Modifier.widthIn(max = 420.dp).padding(28.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Logo(Modifier.size(64.dp))
            Text(if (s.resting) "Emvryx is resting" else "Emvryx is off right now", style = MaterialTheme.typography.headlineSmall)
            Text(
                if (s.resting) "The PC is being used for something else. Please try again in a little while."
                else "It runs on a home PC, and that PC is switched off, asleep, or offline. Your chats are safe and will be here when it is back.",
                color = Emvryx.muted, textAlign = TextAlign.Center,
            )
            Button(onClick = onRetry) { Text("Try again") }
            TextButton(onClick = onChangeServer) { Text(s.server.substringAfter("://"), color = Emvryx.muted) }
        }
    }
}
