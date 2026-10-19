package app.emvryx.android

import android.os.SystemClock
import androidx.lifecycle.ViewModelProvider
import androidx.test.ext.junit.rules.ActivityScenarioRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
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
    @get:Rule
    val rule = ActivityScenarioRule(MainActivity::class.java)

    private val instrumentation get() = InstrumentationRegistry.getInstrumentation()

    @Test
    fun mainScreens() {
        val key = InstrumentationRegistry.getArguments().getString("key").orEmpty()
        assumeTrue("no key: not the screenshot run", key.isNotEmpty())
        shell("mkdir -p $DIR")
        lateinit var vm: AppViewModel
        lateinit var code: CodeViewModel
        rule.scenario.onActivity {
            vm = ViewModelProvider(it)[AppViewModel::class.java]
            code = ViewModelProvider(it)[CodeViewModel::class.java]
        }
        waitFor(20_000) { vm.screen == Screen.SignIn || vm.screen == Screen.Chat }
        shot("01-sign-in")
        main { vm.signIn(SignInWay.Key, "", key) }
        waitFor(20_000) { vm.screen == Screen.Chat }
        pause(2500)
        shot("02-chat-new")
        main { vm.send("Write a short poem about the sea, please.") }
        waitFor(60_000) { !vm.streaming && vm.bubbles.size >= 2 }
        pause(2500)
        shot("03-chat-reply")
        main { vm.open(Screen.Code) }
        pause(4000)
        shot("04-vryxcode-sessions")
        main { code.newSession() }
        pause(2000)
        shot("05-vryxcode-new-session")
        main { vm.open(Screen.Web("/#settings", "Settings")) }
        pause(6000)
        shot("06-settings-in-app")
        main { vm.open(Screen.Web("/#admin", "Admin")) }
        pause(6000)
        shot("07-admin-in-app")
        main { vm.backToChat() }
        pause(1500)
    }

    private fun main(block: () -> Unit) = instrumentation.runOnMainSync(block)

    private fun pause(ms: Long) = SystemClock.sleep(ms)

    private fun waitFor(ms: Long, check: () -> Boolean) {
        val end = SystemClock.uptimeMillis() + ms
        while (SystemClock.uptimeMillis() < end) {
            var ok = false
            main { ok = check() }
            if (ok) return
            pause(250)
        }
    }

    /** The whole phone screen, as the shell's screencap sees it (status bar included) */
    private fun shot(name: String) = shell("screencap -p $DIR/$name.png")

    private fun shell(cmd: String) {
        instrumentation.uiAutomation.executeShellCommand(cmd).use { pfd ->
            android.os.ParcelFileDescriptor.AutoCloseInputStream(pfd).use { it.readBytes() }       // waits until the command is done
        }
    }

    private companion object {
        const val DIR = "/data/local/tmp/emvryx-screens"
    }
}
