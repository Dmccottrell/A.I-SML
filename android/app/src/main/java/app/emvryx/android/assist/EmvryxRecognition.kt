// A "speech recognition service" that Android requires every assistant app to offer. It does no listening itself: it forwards each request
// to the phone's real speech engine and relays the results straight back, so voice typing elsewhere keeps working.
package app.emvryx.android.assist

import android.content.Intent
import android.os.Bundle
import android.os.RemoteException
import android.speech.RecognitionListener
import android.speech.RecognitionService
import android.speech.SpeechRecognizer

/**
 * Android asks every phone assistant for a speech typing service too, and makes it the phone's one when Emvryx is picked as the assistant. So
 * that speech typing keeps working everywhere as before (the keyboard's microphone, other apps), this one only passes the work on to the phone's
 * own service (Google's), and the words straight back. Emvryx keeps nothing of it.
 */
class EmvryxRecognition : RecognitionService() {
    // The real speech recognizer we forward to (null when idle)
    private var rec: SpeechRecognizer? = null

    /**
     * A caller (e.g. the keyboard microphone) wants to start listening. `intent` carries its settings; `cb` is how we send results back to it.
     * We create the phone's own recognizer, give it the same request, and copy each of its events to `cb`.
     */
    override fun onStartListening(intent: Intent, cb: Callback) {
        // Drop any earlier recognizer still around (errors ignored)
        runCatching { rec?.destroy() }
        // Find the phone's own engine (never this service itself, or it would loop); none means we report a client error
        val target = Voice.recognizer(this)
        if (target == null) { runCatching { cb.error(SpeechRecognizer.ERROR_CLIENT) }; return }
        val r = SpeechRecognizer.createSpeechRecognizer(this, target)
        rec = r
        // Each listener method below is called by the real recognizer; every one is just copied to the caller through pass().
        // Missing data (null) is replaced by an empty Bundle because the callback does not accept null.
        r.setRecognitionListener(object : RecognitionListener {
            override fun onReadyForSpeech(params: Bundle?) = pass { cb.readyForSpeech(params ?: Bundle()) }
            override fun onBeginningOfSpeech() = pass { cb.beginningOfSpeech() }
            override fun onRmsChanged(rmsdB: Float) = pass { cb.rmsChanged(rmsdB) }
            override fun onBufferReceived(buffer: ByteArray?) = pass { if (buffer != null) cb.bufferReceived(buffer) }
            override fun onEndOfSpeech() = pass { cb.endOfSpeech() }
            override fun onError(error: Int) = pass { cb.error(error) }
            override fun onResults(results: Bundle?) = pass { cb.results(results ?: Bundle()) }
            override fun onPartialResults(partialResults: Bundle?) = pass { cb.partialResults(partialResults ?: Bundle()) }
            override fun onEvent(eventType: Int, params: Bundle?) {}
        })
        r.startListening(intent)
    }

    /** Runs one forwarding step and ignores RemoteException, which means the caller has already gone away (nothing left to tell) */
    private fun pass(block: () -> Unit) {
        try { block() } catch (_: RemoteException) {}
    }

    // The caller says "stop" or "cancel": relay to the real recognizer (errors ignored)
    override fun onStopListening(cb: Callback) { runCatching { rec?.stopListening() } }

    override fun onCancel(cb: Callback) { runCatching { rec?.cancel() } }

    /** The service ends: release the real recognizer */
    override fun onDestroy() {
        runCatching { rec?.destroy() }
        rec = null
        super.onDestroy()
    }
}
