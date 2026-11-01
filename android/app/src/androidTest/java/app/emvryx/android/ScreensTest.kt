// Not a normal pass/fail test: a robot that walks through the app's main screens on an emulator and takes a screenshot of each one, so the
// pictures can be looked at after every build. It only really runs in the CI "screens" job, where a demo key is passed in.
package app.emvryx.android

import android.os.SystemClock
import androidx.lifecycle.ViewModelProvider
import androidx.test.ext.junit.rules.ActivityScenarioRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import app.emvryx.android.local.LocalChat
import app.emvryx.android.local.LocalTurn
import app.emvryx.android.local.PhoneKit
import app.emvryx.android.ui.AppViewModel
import app.emvryx.android.ui.CodeViewModel
import app.emvryx.android.ui.Screen
import app.emvryx.android.ui.SignInWay
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Screenshots of the app's main screens against a demo Emvryx server (.github/workflows/android.yml, job "screens"). It signs in with the key the
 * workflow passes in, opens each screen through the app's own view models, and saves a picture of the whole phone screen to
 * /data/local/tmp/emvryx-screens, which the workflow pulls and uploads. Without a key (any other run) it is skipped.
 */
@RunWith(AndroidJUnit4::class)
class ScreensTest {
    // Starts MainActivity (the app's one screen) before the test and closes it after
    @get:Rule
    val rule = ActivityScenarioRule(MainActivity::class.java)

    // The test framework's handle for running things on the device (and as the shell user)
    private val instrumentation get() = InstrumentationRegistry.getInstrumentation()

    /**
     * Walks the app screen by screen: sign in, chat, VryxCode (the coding agent), settings, admin, and the offline phone chat, taking a numbered
     * picture at each stop. It "proves" only that none of these screens crash or hang (a wait that times out simply moves on; the pictures are the result).
     */
    @Test
    fun mainScreens() {
        // The key arrives as a test argument from the workflow; a normal run has none
        val key = InstrumentationRegistry.getArguments().getString("key").orEmpty()
        // assumeTrue stops the test as "skipped" (not failed) when the condition is false
        assumeTrue("no key: not the screenshot run", key.isNotEmpty())
        // Make the folder the pictures go into
        shell("mkdir -p $DIR")
        shell("settings put global hide_error_dialogs 1")      // a slow CI emulator otherwise covers the pictures with "System UI isn't responding"
        // "Allow notifications?" is answered before it is asked: it covered every picture after signing in
        shell("pm grant ${instrumentation.targetContext.packageName} android.permission.POST_NOTIFICATIONS")
        // lateinit: filled in a moment later (below) instead of at declaration.
        // The "view models" hold the app's state (which screen is open, the chat messages), so the test can steer the app directly.
        lateinit var vm: AppViewModel
        lateinit var code: CodeViewModel
        // Hand shot() a way to reach the view model (it needs it to close the welcome tours)
        this.vm = { vm }
        // Fetch both view models from the running screen; this runs on the app's main (UI) thread
        rule.scenario.onActivity {
            vm = ViewModelProvider(it)[AppViewModel::class.java]
            code = ViewModelProvider(it)[CodeViewModel::class.java]
        }
        // Wait up to 20 s for the app to settle on either the sign-in screen or (if a login is already saved) the chat
        waitFor(20_000) { vm.screen == Screen.SignIn || vm.screen == Screen.Chat }
        shot("01-sign-in")
        // Sign in with the demo key (the real key text is never written in this file)
        main { vm.signIn(SignInWay.Key, "", key) }
        waitFor(20_000) { vm.screen == Screen.Chat }
        pause(2500)
        shot("02-chat-new")
        main { vm.pickModel("ember-2") }                         // the smallest: the CI machine has little memory left beside the emulator
        // Send a message, then wait up to a minute until the reply has finished streaming in (2+ bubbles: ours and the answer)
        main { vm.send("Write a short poem about the sea, please.") }
        waitFor(60_000) { !vm.streaming && vm.bubbles.size >= 2 }
        pause(2500)
        shot("03-chat-reply")
        // Open the VryxCode list, then start a new coding session
        main { vm.open(Screen.Code) }
        pause(4000)
        shot("04-vryxcode-sessions")
        main { code.newSession() }
        pause(2000)
        shot("05-vryxcode-new-session")
        // Settings and Admin are web pages shown inside the app; the long pauses give the pages time to load over the network
        main { vm.open(Screen.Web("/#settings", "Settings")) }
        pause(15000)
        shot("06-settings-in-app")
        main { vm.open(Screen.Web("/#admin", "Admin")) }
        pause(15000)
        shot("07-admin-in-app")
        // the phone's own chats (android_offline_model): first the download card, then the chats as they look once the model is on the phone
        main { vm.open(Screen.Local) }
        pause(3000)
        shot("08-offline-download")
        // Fake a downloaded offline model and one finished chat on the phone, so the screenshot shows how the chats look when the model is installed
        val phone = (instrumentation.targetContext.applicationContext as EmvryxApp).phone
        main {
            phone.showForScreens(PhoneKit(available = true, id = "flare-3", name = "Flare", version = 3.0),
                LocalChat(1L, "Packing for a weekend hike", listOf(
                    LocalTurn(true, "What should I pack for a weekend hike?"),
                    // (the answer text is joined from two string pieces with +)
                    LocalTurn(false, "Here is a simple list:\n\n- **Water**: 2 litres a day\n- **Food**: easy snacks and two simple meals\n" +
                        "- **Clothes**: a warm layer and a rain jacket\n- **Map** and a charged phone\n\nCheck the weather the day before you go."),
                ), updated = System.currentTimeMillis()))
            vm.open(Screen.Chat)
        }
        pause(500)
        main { vm.open(Screen.Local) }
        pause(3000)
        shot("09-offline-chat")
        main { vm.backToChat() }
        pause(1500)
    }

    // A function that returns the view model (or null before it exists); shot() calls it. Starts out returning null.
    private var vm: () -> AppViewModel? = { null }

    /** Runs `block` on the app's main (UI) thread and waits for it: only that thread may touch the screen state */
    private fun main(block: () -> Unit) = instrumentation.runOnMainSync(block)

    /** Sleeps `ms` milliseconds so the screen has time to draw or the network to answer */
    private fun pause(ms: Long) = SystemClock.sleep(ms)

    /** Polls `check` (on the main thread) every 250 ms until it is true, or gives up quietly after `ms` milliseconds */
    private fun waitFor(ms: Long, check: () -> Boolean) {
        // uptimeMillis: a clock that only counts forward (not changed by the phone's date setting)
        val end = SystemClock.uptimeMillis() + ms
        while (SystemClock.uptimeMillis() < end) {
            var ok = false
            main { ok = check() }
            if (ok) return
            pause(250)
        }
    }

    /** The whole phone screen, as the shell's screencap sees it (status bar included) */
    private fun shot(name: String) {
        // Close the first-run welcome tours of the chat and of VryxCode if they are showing
        main { vm()?.let { if (it.tour != null) it.closeTour(false); if (it.vryxTour) it.closeVryxTour() } }     // the welcome tours cover the screens
        pause(800)
        // Dismiss any system pop-up that would sit on top of the picture, then capture the screen as a PNG
        shell("am broadcast -a android.intent.action.CLOSE_SYSTEM_DIALOGS")
        pause(500)
        shell("screencap -p $DIR/$name.png")
    }

    /** Runs one Android shell command as the shell user and waits for it to finish */
    private fun shell(cmd: String) {
        instrumentation.uiAutomation.executeShellCommand(cmd).use { pfd ->
            android.os.ParcelFileDescriptor.AutoCloseInputStream(pfd).use { it.readBytes() }       // waits until the command is done
        }
    }

    // Constants shared by the whole class (a companion object is Kotlin's version of "static")
    private companion object {
        // Where the pictures go on the device; the CI workflow pulls this folder off afterwards
        const val DIR = "/data/local/tmp/emvryx-screens"
    }
}
