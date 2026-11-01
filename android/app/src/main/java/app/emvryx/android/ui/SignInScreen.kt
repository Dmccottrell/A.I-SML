package app.emvryx.android.ui

import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.emvryx.android.ui.theme.Emvryx
import app.emvryx.android.ui.theme.Heading
import app.emvryx.android.ui.theme.LocalPalette

// SignInScreen.kt: the screen shown when nobody is signed in. It collects the details and hands them to the AppViewModel (vm), which talks
// to the server. The screen itself holds only what the user has typed so far. The PWA is the website version of the app.

/**
 * The PWA's sign-in card (web/index.html .auth .card): "Welcome back", name and password, or an access key.
 * Also covers the email-code way and the second step (a code from an authenticator app) when the account asks for it.
 * [vm] is the app's shared state holder (a ViewModel): it keeps the sign-in progress, errors and server address, and does the actual sign-in calls.
 */
@Composable
fun SignInScreen(vm: AppViewModel) {
    val p = LocalPalette.current
    // The screen's own state. rememberSaveable keeps it across redraws and even a screen rotation. way = how the user signs in (password, access key or emailed code); the others are what has been typed or toggled.
    var way by rememberSaveable { mutableStateOf(SignInWay.Password) }
    var id by rememberSaveable { mutableStateOf("") }
    var secret by rememberSaveable { mutableStateOf("") }
    var code by rememberSaveable { mutableStateOf("") }
    var show by rememberSaveable { mutableStateOf(false) }
    var showServer by rememberSaveable { mutableStateOf(false) }
    var email by rememberSaveable { mutableStateOf("") }
    // LaunchedEffect runs its block when the screen appears and again whenever vm.server changes. It asks the server which sign-in ways it offers.
    LaunchedEffect(vm.server) { vm.checkSignInOptions() }        // does this server send sign-in codes by email?
    // twoStep: the password was right but the account also needs a second code. codeSent: an email code has been sent and we wait for it.
    val twoStep = vm.twoStepTicket != null
    val codeSent = vm.emailSentTo != null
    // submit: what the main button and the keyboard's Done key do, depending on the step we are in.
    val submit = {
        when {
            twoStep -> vm.submitTwoStep(code)
            way == SignInWay.Email && codeSent -> vm.signInWithEmailCode(code)
            way == SignInWay.Email -> vm.sendEmailCode(email)
            else -> vm.signIn(way, id, secret)
        }
    }
    // ready: is there enough typed to press the button? (A key needs only the secret; a password also needs a name.)
    val ready = when {
        twoStep -> code.isNotBlank()
        way == SignInWay.Email -> if (codeSent) code.isNotBlank() else email.contains('@')
        else -> secret.isNotBlank() && (way == SignInWay.Key || id.isNotBlank())
    }

    // Page: soft glow behind, kept clear of system bars and the on-screen keyboard (imePadding), card centred.
    Box(Modifier.fillMaxSize().accentWash(p.glow, 420.dp).safeDrawingPadding().imePadding(), contentAlignment = Alignment.Center) {
        // Scrollable column so the card is reachable on small screens or with the keyboard open.
        Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 32.dp),
            horizontalAlignment = Alignment.CenterHorizontally) {
            Column(
                // The card: at most 420 dp wide, with a rounded outline.
                Modifier.widthIn(max = 420.dp).fillMaxWidth()
                    .border(1.dp, Emvryx.line, RoundedCornerShape(22.dp))
                    .padding(horizontal = 20.dp, vertical = 24.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    // Header row: logo and the app name.
                    Logo(Modifier.size(32.dp))
                    Spacer(Modifier.size(10.dp))
                    Text("Emvryx", fontFamily = Heading, fontWeight = FontWeight.Bold, fontSize = 22.sp)
                }
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    // Title and short explanation; the words change for the second step.
                    Text(if (twoStep) "Two-step check" else "Welcome back", fontFamily = Heading, fontWeight = FontWeight.Bold, fontSize = 28.sp)
                    Text(
                        if (twoStep) "Enter the 6-digit code from your authenticator app, or one of your recovery codes."
                        else "Sign in to keep going where you left off.",
                        color = Emvryx.muted, fontSize = 16.sp,
                    )
                }

                when {
                    // Show the input boxes that match the current step: the two-step code, name + password, the emailed code, the email address, or an access key.
                    twoStep -> Field(
                        "Code", code, { code = it }, placeholder = "123456",
                        keyboard = KeyboardOptions(keyboardType = KeyboardType.Number, imeAction = ImeAction.Done),
                        actions = KeyboardActions(onDone = { submit() }),
                    )
                    way == SignInWay.Password -> {
                        Field(
                            "Name or email", id, { id = it }, placeholder = "Name or email",
                            keyboard = KeyboardOptions(keyboardType = KeyboardType.Email, imeAction = ImeAction.Next),
                        )
                        Field(
                            // Password box. The trailing Show/Hide text toggles whether the password is readable.
                            "Password", secret, { secret = it }, placeholder = "Your password", hidden = !show,
                            keyboard = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
                            actions = KeyboardActions(onDone = { submit() }),
                        ) {
                            Text(
                                if (show) "Hide" else "Show", color = p.accentText, fontWeight = FontWeight.SemiBold,
                                modifier = Modifier.clickable { show = !show }.padding(horizontal = 10.dp, vertical = 8.dp),
                            )
                        }
                    }
                    way == SignInWay.Email && codeSent -> {
                        Text("If ${vm.emailSentTo} belongs to an account, a 6-digit code is on its way. It works for 10 minutes.", color = Emvryx.muted, fontSize = 15.sp)
                        Field(
                            "Code from the email", code, { code = it }, placeholder = "123456",
                            keyboard = KeyboardOptions(keyboardType = KeyboardType.Number, imeAction = ImeAction.Done),
                            actions = KeyboardActions(onDone = { submit() }),
                        )
                    }
                    way == SignInWay.Email -> Field(
                        "Email", email, { email = it }, placeholder = "you@example.com",
                        keyboard = KeyboardOptions(keyboardType = KeyboardType.Email, imeAction = ImeAction.Done),
                        actions = KeyboardActions(onDone = { submit() }),
                    )
                    else -> Field(
                        "Access key", secret, { secret = it }, placeholder = "emvx_…", hidden = true,
                        keyboard = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
                        actions = KeyboardActions(onDone = { submit() }),
                    )
                }

                // If the last attempt failed, show the error in red (?.let runs only when there is a message).
                vm.signInError?.let { Text(it, color = MaterialTheme.colorScheme.error) }

                // The main button's text depends on the step.
                val label = when {
                    twoStep -> "Continue"
                    way == SignInWay.Email && !codeSent -> "Email me a code"
                    else -> "Sign in"
                }
                // Main button. While a request is running (signInBusy) it shows a spinner and is disabled; also disabled until enough is typed.
                PwaButton(label, submit, Modifier.fillMaxWidth().height(50.dp), enabled = !vm.signInBusy && ready) {
                    if (vm.signInBusy) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp, color = LocalContentColor.current)
                    else Text(label, fontWeight = FontWeight.SemiBold, fontSize = 16.sp)
                }

                // In the second step offer only Back. Otherwise show the "or" divider and the other ways to sign in.
                if (twoStep) {
                    PwaButton("Back", vm::cancelTwoStep, Modifier.fillMaxWidth(), ghost = true)
                } else {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        HorizontalDivider(Modifier.weight(1f), color = Emvryx.line)
                        Text("or", color = Emvryx.muted, modifier = Modifier.padding(horizontal = 12.dp))
                        HorizontalDivider(Modifier.weight(1f), color = Emvryx.line)
                    }
                    // Each button below switches the way and clears what was typed; cancelEmailCode forgets a half-finished email-code attempt.
                    if (way != SignInWay.Password) PwaButton("Sign in with a password", { way = SignInWay.Password; secret = ""; vm.cancelEmailCode() },
                        Modifier.fillMaxWidth(), ghost = true)
                    if (way != SignInWay.Key) PwaButton("Use an access key", { way = SignInWay.Key; secret = ""; vm.cancelEmailCode() },
                        Modifier.fillMaxWidth(), ghost = true)
                    // Only offered when this server can send sign-in codes by email.
                    if (vm.emailOffered && way != SignInWay.Email) PwaButton("Email me a sign-in code", { way = SignInWay.Email; code = "" },
                        Modifier.fillMaxWidth(), ghost = true)
                    Text(
                        "Forgot your password? Ask the owner for a one-time sign-in link, then choose a new one in Settings > Security.",
                        color = Emvryx.muted, fontSize = 15.sp,
                    )
                }
                // Optional server address box (for when the app should talk to another server).
                if (showServer) {
                    Field(
                        "Server address", vm.server, { vm.server = it }, placeholder = "https://chat.emvryx.app",
                        keyboard = KeyboardOptions(keyboardType = KeyboardType.Uri),
                    )
                }
            }
            Text(
                // Small tappable line under the card: shows the current server and toggles the address box.
                if (showServer) "Hide server address" else "Server: ${vm.server.substringAfter("://")}",
                color = Emvryx.muted, fontSize = 14.sp,
                modifier = Modifier.padding(top = 14.dp).clickable { showServer = !showServer }.padding(8.dp),
            )
        }
    }
}
