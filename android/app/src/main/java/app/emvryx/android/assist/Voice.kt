package app.emvryx.android.assist

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognitionService
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.os.Handler
import android.os.Looper
import app.emvryx.android.local.Speech

/**
 * Listening and speaking for the assistant bar (android_assistant) and Talk in the phone's own chats (android_offline_talk): the phone's own speech
 * typing turns the voice into words, the phone's own voice reads the answer. When Emvryx is the phone's assistant, Android also makes it the speech
 * typing service ([EmvryxRecognition] passes that on); here the phone's real one is always asked directly, never Emvryx's own.
 */
class Voice(private val ctx: Context, private val offline: Boolean = false) {
    private val main = Handler(Looper.getMainLooper())
    private var rec: SpeechRecognizer? = null
    private var ttsReady = false
    private val tts = TextToSpeech(ctx) { ttsReady = it == TextToSpeech.SUCCESS }

    /** Listen once: [partial] while the person speaks, [done] with what was said ("" for nothing), [failed] with a plain reason */
    fun listen(partial: (String) -> Unit, done: (String) -> Unit, failed: (String) -> Unit) =
        start(offline || !hasInternet(ctx), partial, done, failed)          // no internet: ask for the phone's offline speech first

    private fun start(preferOffline: Boolean, partial: (String) -> Unit, done: (String) -> Unit, failed: (String) -> Unit) {
        main.post {
            runCatching { rec?.destroy() }
            val r = Voice.recognizer(ctx)?.let { SpeechRecognizer.createSpeechRecognizer(ctx, it) } ?: SpeechRecognizer.createSpeechRecognizer(ctx)
            rec = r
            r.setRecognitionListener(object : RecognitionListener {
                override fun onResults(results: Bundle?) = done(results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty().trim())
                override fun onPartialResults(p: Bundle?) { p?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.let(partial) }
                override fun onError(error: Int) = if (retryOffline(error, preferOffline)) start(true, partial, done, failed) else when (error) {
                    SpeechRecognizer.ERROR_NO_MATCH, SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> done("")
                    SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> failed("Emvryx needs the microphone. Allow it in the phone's Settings > Apps > Emvryx > Permissions.")
                    SpeechRecognizer.ERROR_NETWORK, SpeechRecognizer.ERROR_NETWORK_TIMEOUT, SpeechRecognizer.ERROR_SERVER ->
                        failed("Speech typing needs the internet on this phone. Type instead, or download the phone's offline speech (Settings > Google > Voice).")
                    else -> failed("The phone's speech typing did not hear that. Try again, or type.")
                }
                override fun onReadyForSpeech(params: Bundle?) {}
                override fun onBeginningOfSpeech() {}
                override fun onRmsChanged(rmsdB: Float) {}
                override fun onBufferReceived(buffer: ByteArray?) {}
                override fun onEndOfSpeech() {}
                override fun onEvent(eventType: Int, params: Bundle?) {}
            })
            r.startListening(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
                if (preferOffline) putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
            })
        }
    }

    /** Read [text] out (without code, source numbers or marks); [done] when it has finished or could not */
    fun speak(text: String, done: () -> Unit = {}) {
        if (!ttsReady) { done(); return }
        tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) {}
            override fun onDone(utteranceId: String?) { main.post(done) }
            @Deprecated("Deprecated in Java")
            override fun onError(utteranceId: String?) { main.post(done) }
        })
        tts.speak(Speech.plain(text), TextToSpeech.QUEUE_FLUSH, null, "emvryx-voice")
    }

    fun quiet() {
        runCatching { rec?.cancel() }
        runCatching { tts.stop() }
    }

    fun close() {
        quiet()
        main.post { runCatching { rec?.destroy() }; rec = null }
        runCatching { tts.shutdown() }
    }

    companion object {
        /** The online speech failed on the connection (or the server): try once more asking for the phone's offline speech */
        fun retryOffline(error: Int, alreadyOffline: Boolean): Boolean = !alreadyOffline &&
            (error == SpeechRecognizer.ERROR_NETWORK || error == SpeechRecognizer.ERROR_NETWORK_TIMEOUT || error == SpeechRecognizer.ERROR_SERVER)

        /**
         * Ask the phone to download its offline speech pack (Android 13 and later can be asked; if the phone's speech typing says no, or it is older,
         * [openSettings] opens the Settings page for it). Call from the main thread. Returns true when the phone took the request.
         */
        fun getOfflineSpeech(ctx: Context, openSettings: Boolean): Boolean {
            if (android.os.Build.VERSION.SDK_INT >= 33) {
                val target = recognizer(ctx)
                val r = runCatching { if (target != null) SpeechRecognizer.createSpeechRecognizer(ctx, target) else SpeechRecognizer.createSpeechRecognizer(ctx) }.getOrNull()
                if (r != null) {
                    val ok = runCatching {
                        r.triggerModelDownload(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
                            .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                            .putExtra(RecognizerIntent.EXTRA_LANGUAGE, java.util.Locale.getDefault().toLanguageTag()))
                    }.isSuccess
                    Handler(Looper.getMainLooper()).postDelayed({ runCatching { r.destroy() } }, 120_000)       // let it start the download first
                    if (ok) return true
                    runCatching { r.destroy() }
                }
            }
            if (openSettings) runCatching { ctx.startActivity(Intent("android.settings.VOICE_INPUT_SETTINGS").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
            return false
        }

        @Suppress("DEPRECATION")
        fun hasInternet(ctx: Context): Boolean = runCatching {
            val cm = ctx.getSystemService(android.net.ConnectivityManager::class.java)
            cm.getNetworkCapabilities(cm.activeNetwork)?.hasCapability(android.net.NetworkCapabilities.NET_CAPABILITY_INTERNET) == true
        }.getOrDefault(true)

        /** Does the phone have speech typing at all? */
        fun canListen(ctx: Context): Boolean = recognizer(ctx) != null || SpeechRecognizer.isRecognitionAvailable(ctx)

        /** The phone's own speech typing service, never Emvryx's: Google's first when it is there */
        fun recognizer(ctx: Context): ComponentName? {
            val found = ctx.packageManager.queryIntentServices(Intent(RecognitionService.SERVICE_INTERFACE), 0)
                .mapNotNull { it.serviceInfo }.filter { it.packageName != ctx.packageName }
                .map { ComponentName(it.packageName, it.name) }
            return pickRecognizer(found.map { it.packageName to it.className }, ctx.packageName)?.let { (p, c) -> ComponentName(p, c) }
        }

        /** Of the speech typing services on the phone ((package, class)), the one to use: never [own], Google's first */
        fun pickRecognizer(found: List<Pair<String, String>>, own: String): Pair<String, String>? {
            val others = found.filter { it.first != own }
            return others.firstOrNull { it.first == "com.google.android.googlequicksearchbox" }
                ?: others.firstOrNull { it.first.startsWith("com.google.") }
                ?: others.firstOrNull()
        }
    }
}
