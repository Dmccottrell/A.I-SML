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
    private var rec: SpeechRecognizer? = null

    override fun onStartListening(intent: Intent, cb: Callback) {
        runCatching { rec?.destroy() }
        val target = Voice.recognizer(this)
        if (target == null) { runCatching { cb.error(SpeechRecognizer.ERROR_CLIENT) }; return }
        val r = SpeechRecognizer.createSpeechRecognizer(this, target)
        rec = r
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

    private fun pass(block: () -> Unit) {
        try { block() } catch (_: RemoteException) {}
    }

    override fun onStopListening(cb: Callback) { runCatching { rec?.stopListening() } }

    override fun onCancel(cb: Callback) { runCatching { rec?.cancel() } }

    override fun onDestroy() {
        runCatching { rec?.destroy() }
        rec = null
        super.onDestroy()
    }
}
