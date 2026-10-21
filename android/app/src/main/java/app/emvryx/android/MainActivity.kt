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
class MainActivity : FragmentActivity() {
    private val vm: AppViewModel by viewModels()
    private val code: CodeViewModel by viewModels()
    private var leftAt = 0L
    private val askAlerts = registerForActivityResult(androidx.activity.result.contract.ActivityResultContracts.RequestPermission()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            LaunchedEffect(Emvryx.light) {                      // the clock and battery icons dark on the light look, light on the dark one
                val bar = if (Emvryx.light) SystemBarStyle.light(android.graphics.Color.TRANSPARENT, android.graphics.Color.TRANSPARENT)
                          else SystemBarStyle.dark(android.graphics.Color.TRANSPARENT)
                enableEdgeToEdge(bar, bar)
            }
            LaunchedEffect(vm.state) { if (vm.flag("phone_alerts")) askForAlerts() }
            Root(vm, code, onUnlock = ::unlock)
        }
        Alerts.channels(this)
        if (savedInstanceState == null) {
            shared(intent)
            tapped(intent)
        }
    }

    /** Notifications (flag phone_alerts): Android 13 and later ask once; a "no" is respected (it can be turned on in the phone's settings) */
    private fun askForAlerts() {
        if (android.os.Build.VERSION.SDK_INT < 33) return
        if (ContextCompat.checkSelfPermission(this, android.Manifest.permission.POST_NOTIFICATIONS) == android.content.pm.PackageManager.PERMISSION_GRANTED) return
        val prefs = getSharedPreferences("alerts", MODE_PRIVATE)
        if (prefs.getBoolean("asked", false)) return
        prefs.edit().putBoolean("asked", true).apply()
        askAlerts.launch(android.Manifest.permission.POST_NOTIFICATIONS)
    }

    /** A notification tapped: open that VryxCode session or chat */
    private fun tapped(intent: Intent?) {
        val session = intent?.getStringExtra(Alerts.EXTRA_SESSION)
        val chat = intent?.getStringExtra(Alerts.EXTRA_CHAT)?.toLongOrNull()
        intent?.removeExtra(Alerts.EXTRA_SESSION)
        intent?.removeExtra(Alerts.EXTRA_CHAT)
        vm.fromAlert(session, chat)
    }

    override fun onStop() {
        super.onStop()
        Alerts.visible = false
        leftAt = SystemClock.elapsedRealtime()
    }

    override fun onStart() {
        super.onStart()
        Alerts.visible = true
        if (leftAt > 0 && SystemClock.elapsedRealtime() - leftAt > LOCK_AFTER_MS) vm.lockIfOn()   // away more than a minute: ask again
    }

    /** The phone's own fingerprint, face or screen-lock check */
    private fun unlock() {
        val prompt = BiometricPrompt(this, ContextCompat.getMainExecutor(this), object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) = vm.unlocked()
        })
        prompt.authenticate(BiometricPrompt.PromptInfo.Builder()
            .setTitle("Unlock Emvryx")
            .setAllowedAuthenticators(BIOMETRIC_WEAK or DEVICE_CREDENTIAL)
            .build())
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        shared(intent)
        tapped(intent)
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

    private companion object {
        const val LOCK_AFTER_MS = 60_000L
    }
}

@Composable
private fun Root(vm: AppViewModel, code: CodeViewModel, onUnlock: () -> Unit) {
    // the chat follows the chosen model's colours; sign-in and the "off" page are Emvryx amber (web/js/core.js applyTheme)
    EmvryxTheme(model = if (vm.screen == Screen.Chat) vm.currentModel?.name else null) {
        Surface(color = MaterialTheme.colorScheme.background) {           // gives every screen the light text colour
            if (vm.locked) {
                LockScreen(onUnlock)
                return@Surface
            }
            Screens(vm, code)
            vm.tour?.let { ModelTour(vm, it) }                            // a model's welcome tour covers whatever screen is showing
            if (vm.vryxTour && vm.screen == Screen.Code) VryxTour(vm, close = vm::closeVryxTour)
        }
    }
}

/** How deep a screen is: the chat, then VryxCode, then a website page. Going deeper slides in from the right, coming back slides the
 *  other way; sign-in, "off" and the start fade (depth -1). */
private fun depth(s: Screen) = when (s) {
    Screen.Chat -> 0
    Screen.Code -> 1
    is Screen.Web -> 2
    else -> -1
}

@Composable
private fun Screens(vm: AppViewModel, code: CodeViewModel) {
    AnimatedContent(
        targetState = vm.screen,
        contentKey = { s -> if (s is Screen.Web) "web:" + s.path + s.run else s::class.simpleName },   // a new page gets a new WebView
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
            is Screen.Off -> OffScreen(s, onRetry = vm::start, onChangeServer = vm::changeServer)
            Screen.SignIn -> SignInScreen(vm)
            Screen.Chat -> ChatScreen(vm)
            Screen.Code -> CodeScreen(vm, code)
            is Screen.Web -> WebScreen(vm, s.path, s.title, s.run, s.panel)
        }
    }
}
