// Unit tests for local/NativeExtras.kt: Launch.from() decides why the Android app was opened from outside (selected text, the assistant
// button, an icon shortcut or the widget), and NativeFlags.pick() chooses which feature switches the phone remembers.
package app.emvryx.android

import app.emvryx.android.local.Launch
import app.emvryx.android.local.NativeFlags
import org.junit.Assert.assertEquals
import org.junit.Test

/** The ways into the app from outside it: selected text, the assistant button, the icon's shortcuts and the widget (flags android_text_menu,
 *  android_quick_launch), each only when its switch was on the last time the PC answered */
class NativeExtrasTest {
    // The setup: the set of feature switches that are on. Tests pass this to Launch.from as its last argument.
    private val on = setOf("android_text_menu", "android_quick_launch")

    /** Proves text selected in another app is trimmed, ignored when empty, and cut to the maximum length. */
    @Test
    fun selectedTextBecomesANewChatsMessage() {
        // spaces around the text are trimmed
        assertEquals(Launch.Text("What does this mean?"), Launch.from("android.intent.action.PROCESS_TEXT", null, "  What does this mean?  ", on))
        assertEquals(Launch.None, Launch.from("android.intent.action.PROCESS_TEXT", null, "   ", on))           // nothing selected
        // 20,000 characters is far too many: only the first MAX_TEXT are kept
        assertEquals(Launch.Text("x".repeat(Launch.MAX_TEXT)), Launch.from("android.intent.action.PROCESS_TEXT", null, "x".repeat(20_000), on))
    }

    /** Proves the assistant button and the shortcut words each open the right screen, and unknown or plain launches open normally. */
    @Test
    fun theAssistantButtonAndTheShortcuts() {
        // the phone's assistant button, or a voice command, opens Talk
        assertEquals(Launch.Talk, Launch.from("android.intent.action.ASSIST", null, null, on))
        assertEquals(Launch.Talk, Launch.from("android.intent.action.VOICE_COMMAND", null, null, on))
        // icon shortcuts and widget buttons send a word that says which screen to open
        assertEquals(Launch.NewChat, Launch.from("android.intent.action.VIEW", "new", null, on))
        assertEquals(Launch.Talk, Launch.from("android.intent.action.VIEW", "talk", null, on))
        assertEquals(Launch.Code, Launch.from("android.intent.action.VIEW", "code", null, on))
        assertEquals(Launch.Local, Launch.from("android.intent.action.VIEW", "local", null, on))
        // a word nobody knows is ignored
        assertEquals(Launch.None, Launch.from("android.intent.action.VIEW", "nonsense", null, on))
        assertEquals(Launch.None, Launch.from("android.intent.action.MAIN", null, null, on))                    // the icon itself: as always
    }

    /** Proves that when a feature switch is off, the matching way in is ignored and the app just opens. */
    @Test
    fun withTheSwitchOffTheAppJustOpens() {
        // no switches on at all
        assertEquals(Launch.None, Launch.from("android.intent.action.PROCESS_TEXT", null, "hello", emptySet()))
        assertEquals(Launch.None, Launch.from("android.intent.action.ASSIST", null, null, emptySet()))
        // the text-menu switch is on but the shortcut needs the quick-launch switch, so the shortcut is ignored
        assertEquals(Launch.None, Launch.from("android.intent.action.VIEW", "talk", null, setOf("android_text_menu")))
    }

    /** Proves NativeFlags.pick() keeps only the phone's own switches that are on, and ignores switches that are off or unknown to the phone. */
    @Test
    fun theRememberedSwitchesAreOnlyThePhonesOwn() {
        // android_camera_scan is a phone switch but false; chat_research is on but is not one of the phone's switches: both are left out
        assertEquals(setOf("android_text_menu", "android_offline_talk"),
            NativeFlags.pick(mapOf("android_text_menu" to true, "android_offline_talk" to true, "android_camera_scan" to false, "chat_research" to true)))
    }
}
