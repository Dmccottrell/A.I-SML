package app.emvryx.android

import app.emvryx.android.local.Launch
import app.emvryx.android.local.NativeFlags
import org.junit.Assert.assertEquals
import org.junit.Test

/** The ways into the app from outside it: selected text, the assistant button, the icon's shortcuts and the widget (flags android_text_menu,
 *  android_quick_launch), each only when its switch was on the last time the PC answered */
class NativeExtrasTest {
    private val on = setOf("android_text_menu", "android_quick_launch")

    @Test
    fun selectedTextBecomesANewChatsMessage() {
        assertEquals(Launch.Text("What does this mean?"), Launch.from("android.intent.action.PROCESS_TEXT", null, "  What does this mean?  ", on))
        assertEquals(Launch.None, Launch.from("android.intent.action.PROCESS_TEXT", null, "   ", on))           // nothing selected
        assertEquals(Launch.Text("x".repeat(Launch.MAX_TEXT)), Launch.from("android.intent.action.PROCESS_TEXT", null, "x".repeat(20_000), on))
    }

    @Test
    fun theAssistantButtonAndTheShortcuts() {
        assertEquals(Launch.Talk, Launch.from("android.intent.action.ASSIST", null, null, on))
        assertEquals(Launch.Talk, Launch.from("android.intent.action.VOICE_COMMAND", null, null, on))
        assertEquals(Launch.NewChat, Launch.from("android.intent.action.VIEW", "new", null, on))
        assertEquals(Launch.Talk, Launch.from("android.intent.action.VIEW", "talk", null, on))
        assertEquals(Launch.Code, Launch.from("android.intent.action.VIEW", "code", null, on))
        assertEquals(Launch.Local, Launch.from("android.intent.action.VIEW", "local", null, on))
        assertEquals(Launch.None, Launch.from("android.intent.action.VIEW", "nonsense", null, on))
        assertEquals(Launch.None, Launch.from("android.intent.action.MAIN", null, null, on))                    // the icon itself: as always
    }

    @Test
    fun withTheSwitchOffTheAppJustOpens() {
        assertEquals(Launch.None, Launch.from("android.intent.action.PROCESS_TEXT", null, "hello", emptySet()))
        assertEquals(Launch.None, Launch.from("android.intent.action.ASSIST", null, null, emptySet()))
        assertEquals(Launch.None, Launch.from("android.intent.action.VIEW", "talk", null, setOf("android_text_menu")))
    }

    @Test
    fun theRememberedSwitchesAreOnlyThePhonesOwn() {
        assertEquals(setOf("android_text_menu", "android_offline_talk"),
            NativeFlags.pick(mapOf("android_text_menu" to true, "android_offline_talk" to true, "android_camera_scan" to false, "chat_research" to true)))
    }
}
