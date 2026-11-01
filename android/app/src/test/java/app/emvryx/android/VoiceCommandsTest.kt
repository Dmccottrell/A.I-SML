package app.emvryx.android

import app.emvryx.android.local.Command
import app.emvryx.android.local.VoiceCommands
import org.junit.Assert.assertEquals
import org.junit.Test

/** android_assistant: what is said to the assistant bar becomes a phone action, like Bixby or Gemini, or a question for Emvryx */
class VoiceCommandsTest {
    private fun p(s: String) = VoiceCommands.parse(s)

    @Test
    fun openingApps() {
        assertEquals(Command.OpenApp("youtube"), p("Open YouTube"))
        assertEquals(Command.OpenApp("google maps"), p("launch google maps please"))
        assertEquals(Command.OpenApp("spotify"), p("start Spotify."))
    }

    @Test
    fun timersInDigitsOrWords() {
        assertEquals(Command.Timer(600), p("set a timer for 10 minutes"))
        assertEquals(Command.Timer(90), p("Set timer for one minute and thirty seconds"))
        assertEquals(Command.Timer(5400), p("timer for an hour and a half"))
        assertEquals(Command.Timer(45), p("start a 45 second timer"))
    }

    @Test
    fun alarms() {
        assertEquals(Command.Alarm(7, 0), p("set an alarm for 7"))
        assertEquals(Command.Alarm(6, 30), p("wake me up at 6:30 am"))
        assertEquals(Command.Alarm(19, 15), p("set an alarm for 7:15 pm"))
        assertEquals(Command.Alarm(0, 5), p("alarm at 12:05 am"))
    }

    @Test
    fun flashlightNavigationSearchAndMore() {
        assertEquals(Command.Torch(true), p("turn on the flashlight"))
        assertEquals(Command.Torch(false), p("Flashlight off"))
        assertEquals(Command.Navigate("the nearest gas station"), p("navigate to the nearest gas station"))
        assertEquals(Command.Navigate("Chicago"), p("directions to Chicago"))
        assertEquals(Command.Search("cheap flights to Denver"), p("search for cheap flights to Denver"))
        assertEquals(Command.Search("weather tomorrow"), p("google weather tomorrow"))
        assertEquals(Command.YouTube("lofi beats"), p("play lofi beats on YouTube"))
        assertEquals(Command.Dial("8475551234"), p("call 847 555 1234"))
        assertEquals(Command.Camera, p("take a picture"))
        assertEquals(Command.Settings("wifi"), p("open wifi settings"))
        assertEquals(Command.Settings("bluetooth"), p("turn on bluetooth"))
    }

    @Test
    fun everythingElseIsAQuestionForEmvryx() {
        assertEquals(Command.Ask("what is the tallest mountain"), p("what is the tallest mountain"))
        assertEquals(Command.Ask("open a bank account how do I do it"), p("open a bank account how do I do it"))   // a sentence, not an app
        assertEquals(Command.Ask("call my mom"), p("call my mom"))                       // no number: Emvryx cannot see contacts
        assertEquals(Command.None, p("   "))
    }
}

class PhoneActionWordsTest {
    @Test
    fun whatTheBarSaysBack() {
        assertEquals("1 hour 30 minutes", app.emvryx.android.assist.PhoneActions.duration(5400))
        assertEquals("1 minute 30 seconds", app.emvryx.android.assist.PhoneActions.duration(90))
        assertEquals("7:05 PM", app.emvryx.android.assist.PhoneActions.clock(19, 5))
        assertEquals("12:00 AM", app.emvryx.android.assist.PhoneActions.clock(0, 0))
    }
}

class AssistantPartsTest {
    @Test
    fun speechTypingIsNeverPassedBackToEmvryxItself() {
        val own = "app.emvryx.android"
        val found = listOf(own to "app.emvryx.android.assist.EmvryxRecognition", "com.samsung.voice" to "S",
            "com.google.android.googlequicksearchbox" to "G")
        assertEquals("com.google.android.googlequicksearchbox", app.emvryx.android.assist.Voice.pickRecognizer(found, own)?.first)
        assertEquals("com.samsung.voice", app.emvryx.android.assist.Voice.pickRecognizer(found.take(2), own)?.first)
        assertEquals(null, app.emvryx.android.assist.Voice.pickRecognizer(found.take(1), own))
    }

    @Test
    fun theBarStepsAsideOnlyForAnotherAppsScreen() {
        val a = app.emvryx.android.assist.PhoneActions
        assertEquals(true, a.opensScreen(app.emvryx.android.local.Command.OpenApp("maps")))
        assertEquals(true, a.opensScreen(app.emvryx.android.local.Command.Navigate("home")))
        assertEquals(false, a.opensScreen(app.emvryx.android.local.Command.Timer(60)))
        assertEquals(false, a.opensScreen(app.emvryx.android.local.Command.Torch(true)))
        assertEquals(false, a.opensScreen(app.emvryx.android.local.Command.Ask("why is the sky blue")))
    }

    @Test
    fun aFailedConnectionTriesTheOfflineSpeechOnceBeforeGivingUp() {
        val v = app.emvryx.android.assist.Voice
        assertEquals(true, v.retryOffline(android.speech.SpeechRecognizer.ERROR_NETWORK, false))
        assertEquals(true, v.retryOffline(android.speech.SpeechRecognizer.ERROR_SERVER, false))
        assertEquals(false, v.retryOffline(android.speech.SpeechRecognizer.ERROR_NETWORK, true))      // already offline: say so, do not loop
        assertEquals(false, v.retryOffline(android.speech.SpeechRecognizer.ERROR_NO_MATCH, false))
    }
}
