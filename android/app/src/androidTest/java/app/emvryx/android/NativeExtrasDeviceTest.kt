// Device tests (they run on a real phone or emulator, not on the PC): they ask Android's package manager whether it can "see" Emvryx for the
// phone-integration features declared in AndroidManifest.xml. If someone breaks the manifest, these fail.
package app.emvryx.android

import android.content.Intent
import android.service.voice.VoiceInteractionService
import android.speech.RecognitionService
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import app.emvryx.android.assist.Voice
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * On a real phone: Android finds Emvryx for Ask Emvryx on selected text, as a phone assistant, and its speech typing never loops back to itself.
 * @RunWith(AndroidJUnit4::class) tells JUnit (the test framework) to run these tests on the Android device.
 */
@RunWith(AndroidJUnit4::class)
class NativeExtrasDeviceTest {
    // The app's own Context (a handle to the running app and the phone's services), taken from the test framework.
    // "get()" makes it read fresh each time it is used.
    private val ctx get() = InstrumentationRegistry.getInstrumentation().targetContext

    /**
     * True when Android lists THIS app among the apps/services that can answer the intent `i` (an intent is a request such as "someone handle
     * selected text"). `service` picks whether to look at background services or at screens (activities). Compares package names, the app's ID.
     */
    private fun ours(i: Intent, service: Boolean) = (if (service) ctx.packageManager.queryIntentServices(i, 0).map { it.serviceInfo.packageName }
        else ctx.packageManager.queryIntentActivities(i, 0).map { it.activityInfo.packageName }).contains(ctx.packageName)

    /** Proves: selecting text in any app offers "Ask Emvryx" (the PROCESS_TEXT filter in the manifest works) */
    @Test
    fun askEmvryxIsOfferedOnSelectedText() {
        assertTrue(ours(Intent(Intent.ACTION_PROCESS_TEXT).setType("text/plain"), service = false))
    }

    /** Proves: Emvryx shows in Android's list of assistant apps: it has a voice-interaction service, a speech-recognition service and an ASSIST screen */
    @Test
    fun emvryxCanBePickedAsThePhonesAssistant() {
        assertTrue(ours(Intent(VoiceInteractionService.SERVICE_INTERFACE), service = true))
        assertTrue(ours(Intent(RecognitionService.SERVICE_INTERFACE), service = true))
        assertTrue(ours(Intent(Intent.ACTION_ASSIST), service = false))
    }

    /**
     * Proves: the speech engine Voice picks is never Emvryx's own pass-through service (that would loop forever: Emvryx asking Emvryx).
     * If the phone has no engine at all (null) there is nothing to check and the test passes.
     */
    @Test
    fun speechTypingGoesToThePhonesOwnService() {
        Voice.recognizer(ctx)?.let { assertNotEquals(ctx.packageName, it.packageName) }
    }
}
