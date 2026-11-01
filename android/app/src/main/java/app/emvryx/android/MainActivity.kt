// The app's one and only Android screen (an "Activity"). It holds no UI itself: it sets up the Compose screens (Jetpack Compose = Android's UI
// toolkit where screens are Kotlin functions), the app lock, notification taps, and things shared into the app from other apps.
// Which screen shows is decided by AppViewModel (a "view model" keeps the app's state alive across screen rotations).
package app.emvryx.android

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.SystemClock
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.biometric.BiometricManager.Authenticators.BIOMETRIC_WEAK
import androidx.biometric.BiometricManager.Authenticators.DEVICE_CREDENTIAL
import androidx.biometric.BiometricPrompt
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.ui.unit.IntOffset
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.core.content.ContextCompat
import androidx.core.content.IntentCompat
import androidx.fragment.app.FragmentActivity
import androidx.lifecycle.lifecycleScope
import app.emvryx.android.ui.ModelTour
import app.emvryx.android.ui.NativeScreen
import app.emvryx.android.ui.LocalChatScreen
import app.emvryx.android.ui.VryxTour
import app.emvryx.android.ui.AppViewModel
import app.emvryx.android.ui.ChatScreen
import app.emvryx.android.ui.CodeScreen
import app.emvryx.android.ui.CodeViewModel
import app.emvryx.android.ui.LockScreen
import app.emvryx.android.ui.OffScreen
import app.emvryx.android.ui.Screen
import app.emvryx.android.ui.SignInScreen
import app.emvryx.android.ui.StartingScreen
import app.emvryx.android.ui.WebScreen
import app.emvryx.android.ui.readPicked
import app.emvryx.android.ui.theme.Emvryx
import app.emvryx.android.ui.theme.EmvryxTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

// A FragmentActivity (still a ComponentActivity) because the fingerprint prompt needs one
/** The app's single screen host: Android creates it when the app opens, and the manifest lists its extra entry points (share, assist, shortcuts) */
class MainActivity : FragmentActivity() {
    // "by viewModels()": Android hands back the same view model after a rotation, so chat state is not lost. vm = main app state, code = VryxCode state.
    private val vm: AppViewModel by viewModels()
    private val code: CodeViewModel by viewModels()
    // When the app was last moved off screen (in milliseconds since boot); 0 = not yet. Used to decide when to ask for the fingerprint again.
    private var leftAt = 0L

    /**
     * Runs once when the screen is created. Sets up what is drawn (Compose), the notification channels, and handles whatever opened the app
     * (a share, a tapped notification, a shortcut). savedInstanceState is non-null when Android re-creates the screen (e.g. after a rotation).
     */
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // setContent: everything inside is the Compose UI. A LaunchedEffect runs its block whenever its "key" value changes.
        setContent {
            LaunchedEffect(Emvryx.light) {                      // the clock and battery icons dark on the light look, light on the dark one
                val bar = if (Emvryx.light) SystemBarStyle.light(android.graphics.Color.TRANSPARENT, android.graphics.Color.TRANSPARENT)
                          else SystemBarStyle.dark(android.graphics.Color.TRANSPARENT)
                enableEdgeToEdge(bar, bar)
            }
            // Once the app state is known (signed in, flags loaded), ask for the notification permission if the phone_alerts feature is on
            LaunchedEffect(vm.state) { if (vm.flag("phone_alerts")) askForAlerts() }
            // onUnlock = ::unlock passes this class's unlock function (a function reference) to the lock screen
            Root(vm, code, onUnlock = ::unlock)
        }
        // Make the notification channels exist (safe to repeat)
        Alerts.channels(this)
        // Only on a fresh start, not a rotation: otherwise a shared text would be sent again every time the phone turns.
        // Each of these checks the starting intent (the "why was I opened" message) for its own kind of request and ignores the rest.
        if (savedInstanceState == null) {
            shared(intent)
            tapped(intent)
            launched(intent)
        }
    }

    /** Notifications (flag phone_alerts): Android 13 and later ask once; a "no" is respected (it can be turned on in the phone's settings) */
    private fun askForAlerts() {
        // Android 12 and older have no such permission (API 33 = Android 13)
        if (android.os.Build.VERSION.SDK_INT < 33) return
        // Already allowed: nothing to ask
        if (ContextCompat.checkSelfPermission(this, android.Manifest.permission.POST_NOTIFICATIONS) == android.content.pm.PackageManager.PERMISSION_GRANTED) return
        // Remember (in a small private settings file) that we have asked once, so a "no" is never nagged about again
        val prefs = getSharedPreferences("alerts", MODE_PRIVATE)
        if (prefs.getBoolean("asked", false)) return
        prefs.edit().putBoolean("asked", true).apply()
        // asked directly: FragmentActivity refuses the result launcher's large request codes for permissions ("Can only use lower 16 bits")
        androidx.core.app.ActivityCompat.requestPermissions(this, arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), ASK_ALERTS)
    }

    /** A notification tapped: open that VryxCode session or chat */
    private fun tapped(intent: Intent?) {
        // Read which session id or chat id the tapped notification carried (see Alerts.open). The chat id arrives as text, so convert it to a number.
        val session = intent?.getStringExtra(Alerts.EXTRA_SESSION)
        val chat = intent?.getStringExtra(Alerts.EXTRA_CHAT)?.toLongOrNull()
        // Remove the values after reading, so a screen rotation or a re-delivered intent does not open the same session a second time
        intent?.removeExtra(Alerts.EXTRA_SESSION)
        intent?.removeExtra(Alerts.EXTRA_CHAT)
        // Let the view model switch to that session or chat (does nothing if both are null)
        vm.fromAlert(session, chat)
    }

    /** The app left the screen: tell Alerts (so notifications show again) and note the time for the lock check */
    override fun onStop() {
        super.onStop()
        Alerts.visible = false
        leftAt = SystemClock.elapsedRealtime()
    }

    /** The app came on screen: notifications are held back while visible, and the lock is raised if we were away over a minute */
    override fun onStart() {
        super.onStart()
        Alerts.visible = true
        if (leftAt > 0 && SystemClock.elapsedRealtime() - leftAt > LOCK_AFTER_MS) vm.lockIfOn()   // away more than a minute: ask again
    }

    /** The phone's own fingerprint, face or screen-lock check */
    private fun unlock() {
        // A BiometricPrompt is the system's fingerprint / face / screen-lock dialog. The callback runs only when the check passes.
        val prompt = BiometricPrompt(this, ContextCompat.getMainExecutor(this), object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) = vm.unlocked()
        })
        // BIOMETRIC_WEAK or DEVICE_CREDENTIAL: accept a fingerprint/face, or the phone's PIN/pattern as the fallback ("or" here combines two flags into one value)
        prompt.authenticate(BiometricPrompt.PromptInfo.Builder()
            .setTitle("Unlock Emvryx")
            .setAllowedAuthenticators(BIOMETRIC_WEAK or DEVICE_CREDENTIAL)
            .build())
    }

    /**
     * Because the manifest says singleTask, a second start (a share, a tapped notification) reuses this open screen and arrives here instead
     * of onCreate. Handle it the same way as at start-up.
     */
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        shared(intent)
        tapped(intent)
        launched(intent)
    }

    /** Opened from outside: selected text's Ask Emvryx, the assistant button, a shortcut on the icon or the widget (local/NativeExtras.kt) */
    private fun launched(intent: Intent?) {
        // "?: return" = if there is no intent, stop here
        intent ?: return
        // Work out what was asked for (Launch.from turns the action / shortcut name / selected text into a request; flags say which features are on)
        val l = app.emvryx.android.local.Launch.from(intent.action, intent.getStringExtra(app.emvryx.android.local.Launch.SHORTCUT),
            intent.getCharSequenceExtra(Intent.EXTRA_PROCESS_TEXT), app.emvryx.android.local.NativeFlags.on(this))
        // Used up: clear it so it does not run again later
        intent.removeExtra(app.emvryx.android.local.Launch.SHORTCUT)
        vm.launch(l)
    }

    /** "Share to Emvryx" from another app: text goes in the message box, pictures and files are attached to a new chat */
    private fun shared(intent: Intent?) {
        // Only handle "send" requests (one item or several); anything else is not a share
        if (intent?.action != Intent.ACTION_SEND && intent?.action != Intent.ACTION_SEND_MULTIPLE) return
        val text = intent.getStringExtra(Intent.EXTRA_TEXT)
        // The picture/file addresses (Uri = a pointer to where Android keeps the file). At most 3 are taken from a multi-share.
        val uris = if (intent.action == Intent.ACTION_SEND_MULTIPLE)
            IntentCompat.getParcelableArrayListExtra(intent, Intent.EXTRA_STREAM, Uri::class.java).orEmpty().take(3)
        else listOfNotNull(IntentCompat.getParcelableExtra(intent, Intent.EXTRA_STREAM, Uri::class.java))
        // lifecycleScope.launch starts a coroutine (a function that can pause) tied to this screen. Reading files can be slow, so it is done
        // on Dispatchers.IO (a pool of threads for disk and network work) to keep the screen smooth; files that cannot be read are skipped.
        lifecycleScope.launch {
            val files = withContext(Dispatchers.IO) { uris.mapNotNull { readPicked(this@MainActivity, it) } }
            vm.incoming(text, files)
        }
    }

    // Constants: how long away before the lock asks again (one minute), and the id that matches a permission answer to its question
    private companion object {
        const val LOCK_AFTER_MS = 60_000L
        const val ASK_ALERTS = 7
    }
}

/**
 * The top of the drawn UI: applies the colour theme, shows the lock screen if locked, otherwise the current screen, and the welcome tours on top.
 * @Composable marks a function that draws UI and is re-run automatically when the data it reads changes.
 */
@Composable
private fun Root(vm: AppViewModel, code: CodeViewModel, onUnlock: () -> Unit) {
    // the chat follows the chosen model's colours; sign-in and the "off" page are Emvryx amber (web/js/core.js applyTheme)
    EmvryxTheme(model = if (vm.screen == Screen.Chat) vm.currentModel?.name else null) {
        Surface(color = MaterialTheme.colorScheme.background) {           // gives every screen the light text colour
            // Locked: show only the unlock screen and draw nothing else (return@Surface leaves the Surface block early)
            if (vm.locked) {
                LockScreen(onUnlock)
                return@Surface
            }
            // The normal app; the two tour lines below draw over it only while their tour is active
            Screens(vm, code)
            vm.tour?.let { ModelTour(vm, it) }                            // a model's welcome tour covers whatever screen is showing
            if (vm.vryxTour && vm.screen == Screen.Code) VryxTour(vm, close = vm::closeVryxTour)
        }
    }
}

/** How deep a screen is: the chat, then VryxCode, then a website page. Going deeper slides in from the right, coming back slides the
 *  other way; sign-in, "off" and the start fade (depth -1). */
private fun depth(s: Screen) = when (s) {
    // (Screen is the list of all places the app can be.) The numbers are only compared: bigger = deeper.
    Screen.Chat -> 0
    Screen.Code -> 1
    is Screen.Web, is Screen.Native, Screen.Local -> 2
    else -> -1
}

/**
 * Shows whichever screen the view model says is current, with a slide or fade animation between screens.
 * `when (s)` below picks the right screen function for each Screen value.
 */
@Composable
private fun Screens(vm: AppViewModel, code: CodeViewModel) {
    AnimatedContent(
        targetState = vm.screen,
        contentKey = { s -> if (s is Screen.Web) "web:" + s.path + s.run else if (s is Screen.Native) "native:" + s.kind else s::class.simpleName },   // a new page gets a new WebView
        // How to animate from the old screen to the new: fade if either is a "no depth" screen or they are the same depth; slide in from the right
        // when going deeper; slide the other way when going back. "ease" and "fade" are the timings (220 ms slide, 160 ms fade). `it` is the width.
        transitionSpec = {
            val from = depth(initialState)
            val to = depth(targetState)
            val ease = tween<IntOffset>(220, easing = FastOutSlowInEasing)
            val fade = tween<Float>(160)
            when {
                from < 0 || to < 0 || from == to -> fadeIn(fade) togetherWith fadeOut(fade)
                to > from -> (slideInHorizontally(ease) { it } + fadeIn(fade)) togetherWith (slideOutHorizontally(ease) { -it / 5 } + fadeOut(fade))
                else -> (slideInHorizontally(ease) { -it / 5 } + fadeIn(fade)) togetherWith (slideOutHorizontally(ease) { it } + fadeOut(fade))
            }
        },
        label = "screens",
    ) { s ->
        when (s) {
            Screen.Starting -> StartingScreen()
            is Screen.Off -> OffScreen(s, onRetry = vm::start, onChangeServer = vm::changeServer,
                onLocal = if (vm.phoneChats) ({ vm.open(Screen.Local) }) else null, tip = vm.phoneTip)
            Screen.SignIn -> SignInScreen(vm)
            Screen.Chat -> ChatScreen(vm)
            Screen.Code -> CodeScreen(vm, code)
            is Screen.Web -> WebScreen(vm, s.path, s.title, s.run, s.panel)
            is Screen.Native -> NativeScreen(vm, s.kind)
            Screen.Local -> LocalChatScreen(vm, vm::leaveLocal)
        }
    }
}
