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

/** On a real phone: Android finds Emvryx for Ask Emvryx on selected text, as a phone assistant, and its speech typing never loops back to itself */
@RunWith(AndroidJUnit4::class)
class NativeExtrasDeviceTest {
    private val ctx get() = InstrumentationRegistry.getInstrumentation().targetContext

    private fun ours(i: Intent, service: Boolean) = (if (service) ctx.packageManager.queryIntentServices(i, 0).map { it.serviceInfo.packageName }
        else ctx.packageManager.queryIntentActivities(i, 0).map { it.activityInfo.packageName }).contains(ctx.packageName)

    @Test
    fun askEmvryxIsOfferedOnSelectedText() {
        assertTrue(ours(Intent(Intent.ACTION_PROCESS_TEXT).setType("text/plain"), service = false))
    }

    @Test
    fun emvryxCanBePickedAsThePhonesAssistant() {
        assertTrue(ours(Intent(VoiceInteractionService.SERVICE_INTERFACE), service = true))
        assertTrue(ours(Intent(RecognitionService.SERVICE_INTERFACE), service = true))
        assertTrue(ours(Intent(Intent.ACTION_ASSIST), service = false))
    }

    @Test
    fun speechTypingGoesToThePhonesOwnService() {
        Voice.recognizer(ctx)?.let { assertNotEquals(ctx.packageName, it.packageName) }
    }
}
