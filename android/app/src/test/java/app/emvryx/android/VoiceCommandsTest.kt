// Unit tests for the assistant bar (the voice / typed command box): local/VoiceCommands.kt turns a spoken sentence into a phone action, and
// assist/PhoneActions.kt and assist/Voice.kt hold small helpers for what the bar says back and which speech service to use.
package app.emvryx.android

import app.emvryx.android.local.Command
import app.emvryx.android.local.VoiceCommands
import org.junit.Assert.assertEquals
import org.junit.Test

/** android_assistant: what is said to the assistant bar becomes a phone action, like Bixby or Gemini, or a question for Emvryx */
class VoiceCommandsTest {
    // Short name for the function under test, so each line below stays easy to read.
    private fun p(s: String) = VoiceCommands.parse(s)

    /** Proves "open / launch / start" plus an app name gives OpenApp, ignoring capitals, "please" and a final full stop. */
    @Test
    fun openingApps() {
        assertEquals(Command.OpenApp("youtube"), p("Open YouTube"))
        assertEquals(Command.OpenApp("google maps"), p("launch google maps please"))
        assertEquals(Command.OpenApp("spotify"), p("start Spotify."))
    }

    /** Proves timers are understood with digits or number words, several units together, "and a half", and a number placed before "second". */
    @Test
    fun timersInDigitsOrWords() {
        assertEquals(Command.Timer(600), p("set a timer for 10 minutes"))             // 10 x 60 seconds
        assertEquals(Command.Timer(90), p("Set timer for one minute and thirty seconds"))   // 60 + 30
        assertEquals(Command.Timer(5400), p("timer for an hour and a half"))          // 3600 + 1800
        assertEquals(Command.Timer(45), p("start a 45 second timer"))
    }

    /** Proves alarms read hours and minutes, with am/pm turning into a 24-hour clock (7:15 pm -> 19:15, 12:05 am -> 0:05). */
    @Test
    fun alarms() {
        assertEquals(Command.Alarm(7, 0), p("set an alarm for 7"))                    // no minutes means :00
        assertEquals(Command.Alarm(6, 30), p("wake me up at 6:30 am"))
        assertEquals(Command.Alarm(19, 15), p("set an alarm for 7:15 pm"))
        assertEquals(Command.Alarm(0, 5), p("alarm at 12:05 am"))                     // 12 am is just after midnight
    }

    /** Proves the other command types: flashlight, directions, web search, YouTube, dialling, camera and settings pages. */
    @Test
    fun flashlightNavigationSearchAndMore() {
        assertEquals(Command.Torch(true), p("turn on the flashlight"))
        assertEquals(Command.Torch(false), p("Flashlight off"))
        assertEquals(Command.Navigate("the nearest gas station"), p("navigate to the nearest gas station"))
        assertEquals(Command.Navigate("Chicago"), p("directions to Chicago"))        // the capital letter is kept
        assertEquals(Command.Search("cheap flights to Denver"), p("search for cheap flights to Denver"))
        assertEquals(Command.Search("weather tomorrow"), p("google weather tomorrow"))
        assertEquals(Command.YouTube("lofi beats"), p("play lofi beats on YouTube"))
        // only the digits are kept from a spoken phone number
        assertEquals(Command.Dial("8475551234"), p("call 847 555 1234"))
        assertEquals(Command.Camera, p("take a picture"))
        assertEquals(Command.Settings("wifi"), p("open wifi settings"))
        assertEquals(Command.Settings("bluetooth"), p("turn on bluetooth"))
    }

    /** Proves anything that is not clearly a command is sent on as a question (Ask), and an empty sentence is None. */
    @Test
    fun everythingElseIsAQuestionForEmvryx() {
        assertEquals(Command.Ask("what is the tallest mountain"), p("what is the tallest mountain"))
        assertEquals(Command.Ask("open a bank account how do I do it"), p("open a bank account how do I do it"))   // a sentence, not an app
        assertEquals(Command.Ask("call my mom"), p("call my mom"))                       // no number: Emvryx cannot see contacts
        assertEquals(Command.None, p("   "))
    }
}

/** Tests the plain-words helpers the assistant bar uses to say what it did. */
class PhoneActionWordsTest {
    /** Proves duration() and clock() write seconds and clock times as people say them. */
    @Test
    fun whatTheBarSaysBack() {
        assertEquals("1 hour 30 minutes", app.emvryx.android.assist.PhoneActions.duration(5400))         // singular "hour", plural "minutes"
        assertEquals("1 minute 30 seconds", app.emvryx.android.assist.PhoneActions.duration(90))
        assertEquals("7:05 PM", app.emvryx.android.assist.PhoneActions.clock(19, 5))                    // 24-hour 19 becomes 7 PM
        assertEquals("12:00 AM", app.emvryx.android.assist.PhoneActions.clock(0, 0))                    // hour 0 is 12 AM, not 0
    }
}

/** Tests small decisions in the assistant bar: which speech service to use, when it opens another app, and when to retry offline. */
class AssistantPartsTest {
    /** Proves pickRecognizer() never chooses Emvryx's own speech service (it would loop back), and prefers Google's, then any other. */
    @Test
    fun speechTypingIsNeverPassedBackToEmvryxItself() {
        // The setup: the app's own package name, and three speech services found on the phone as (package, class) pairs:
        // Emvryx's own, a Samsung one and Google's.
        val own = "app.emvryx.android"
        val found = listOf(own to "app.emvryx.android.assist.EmvryxRecognition", "com.samsung.voice" to "S",
            "com.google.android.googlequicksearchbox" to "G")
        // all three present: Google's is picked
        assertEquals("com.google.android.googlequicksearchbox", app.emvryx.android.assist.Voice.pickRecognizer(found, own)?.first)
        // Google's removed: the Samsung one is picked, not Emvryx's own
        assertEquals("com.samsung.voice", app.emvryx.android.assist.Voice.pickRecognizer(found.take(2), own)?.first)
        // only Emvryx's own is left: there is nothing safe to use, so the answer is null
        assertEquals(null, app.emvryx.android.assist.Voice.pickRecognizer(found.take(1), own))
    }

    /** Proves opensScreen() is true only for commands that show another app's screen (so the bar steps aside) and false for in-place actions. */
    @Test
    fun theBarStepsAsideOnlyForAnotherAppsScreen() {
        val a = app.emvryx.android.assist.PhoneActions
        assertEquals(true, a.opensScreen(app.emvryx.android.local.Command.OpenApp("maps")))
        assertEquals(true, a.opensScreen(app.emvryx.android.local.Command.Navigate("home")))
        assertEquals(false, a.opensScreen(app.emvryx.android.local.Command.Timer(60)))
        assertEquals(false, a.opensScreen(app.emvryx.android.local.Command.Torch(true)))
        assertEquals(false, a.opensScreen(app.emvryx.android.local.Command.Ask("why is the sky blue")))
    }

    /** Proves a connection or server error in online speech recognition triggers one retry with offline speech, and nothing else does. */
    @Test
    fun aFailedConnectionTriesTheOfflineSpeechOnceBeforeGivingUp() {
        val v = app.emvryx.android.assist.Voice
        assertEquals(true, v.retryOffline(android.speech.SpeechRecognizer.ERROR_NETWORK, false))
        assertEquals(true, v.retryOffline(android.speech.SpeechRecognizer.ERROR_SERVER, false))
        assertEquals(false, v.retryOffline(android.speech.SpeechRecognizer.ERROR_NETWORK, true))      // already offline: say so, do not loop
        // "no match" means nothing was understood, which is not a connection problem
        assertEquals(false, v.retryOffline(android.speech.SpeechRecognizer.ERROR_NO_MATCH, false))
    }
}
