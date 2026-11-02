package app.emvryx.android.ui

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import app.emvryx.android.EmvryxApp
import app.emvryx.android.local.ScheduleForm
import app.emvryx.android.local.Schedule
import app.emvryx.android.local.Schedules
import app.emvryx.android.local.Speech
import app.emvryx.android.ui.theme.Emvryx
import app.emvryx.android.ui.theme.LocalPalette
import kotlinx.coroutines.launch
import java.text.DateFormat
import java.util.Date
import java.util.TimeZone

// AssistScreens.kt: the screens for three assistant features: the Research and Talk buttons above the message box,
// the full-screen Talk conversation (speak, hear the answer read out, speak again), and the Scheduled tasks page.
// Built with Jetpack Compose: @Composable functions describe the screen, and a `remember { mutableStateOf(...) }` value
// makes the screen redraw whenever it changes. Helper logic (form checks, cleaning text for speech) is in local/Assist.kt.
//
// Deep Research, Talk and Scheduled tasks in the app (flags chat_research, chat_live_voice, chat_schedule), as on the website (web/js/assist.js).

/** The Research and Talk buttons above the message box, each shown only when its switch (feature flag) is on. [vm] is the app's main ViewModel, which holds the app's state. */
@Composable
fun AssistChips(vm: AppViewModel) {
    // Research needs its flag and a chat that is not private; Talk needs its flag and a speech recogniser on this phone.
    val research = vm.canResearch
    val talk = vm.flag("chat_live_voice") && SpeechRecognizer.isRecognitionAvailable(LocalContext.current)
    // Nothing to show: draw nothing at all.
    if (!research && !talk) return
    val p = LocalPalette.current
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        // Research is a toggle: filled with the accent colour when on.
        if (research) {
            val on = vm.research
            Box(Modifier.heightIn(min = 34.dp).clip(RoundedCornerShape(999.dp)).background(if (on) p.accent else Emvryx.surface2)
                .clickable { vm.research = !vm.research }.padding(horizontal = 12.dp, vertical = 6.dp), contentAlignment = Alignment.Center) {
                Text("🔎 Research", color = if (on) p.onAccent else Emvryx.text, fontSize = 13.sp)
            }
        }
        // Talk opens the full-screen Talk overlay.
        if (talk) Box(Modifier.heightIn(min = 34.dp).clip(RoundedCornerShape(999.dp)).background(Emvryx.surface2)
            .clickable { vm.talking = true }.padding(horizontal = 12.dp, vertical = 6.dp), contentAlignment = Alignment.Center) {
            Text("🗣 Talk", color = Emvryx.text, fontSize = 13.sp)
        }
    }
}

// ---------------------------------------------------------------- Talk: speak, hear the answer, speak again

/**
 * The full-screen Talk mode: it listens through the phone's speech recogniser, sends what you said as a chat message,
 * waits for the answer, reads it out loud (text-to-speech), then listens again, until you tap End.
 * Phases: "listen", "think", "speak", "stopped". Tapping the circle while it speaks interrupts it.
 */
@Composable
fun TalkOverlay(vm: AppViewModel) {
    val context = LocalContext.current
    // A Handler on the main thread lets us run something a moment later (postDelayed) on the thread that owns the screen.
    val main = remember { Handler(Looper.getMainLooper()) }
    // [state] is the line shown to the person; [heard] is the words recognised so far.
    var state by remember { mutableStateOf("Listening…") }
    var heard by remember { mutableStateOf("") }
    var phase by remember { mutableStateOf("listen") }           // listen, think, speak, stopped
    var waiting by remember { mutableStateOf(false) }            // a message was sent: speak the answer when it is written
    // Do we already have the microphone permission?
    var allowed by remember { mutableStateOf(ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) }
    // Asks Android for the microphone permission, then records the answer; if refused, explain how to allow it and stop.
    val ask = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        allowed = ok
        if (!ok) { state = "Emvryx needs the microphone to talk. Allow it in the phone's Settings > Apps > Emvryx."; phase = "stopped" }
    }
    // The speech recogniser (voice to words) and the text-to-speech engine (words to voice); ttsReady turns true once the engine has started.
    val rec = remember { SpeechRecognizer.createSpeechRecognizer(context) }
    var ttsReady by remember { mutableStateOf(false) }
    val tts = remember { TextToSpeech(context) { ttsReady = it == TextToSpeech.SUCCESS } }
    // `listen` is declared first and given its body below, because speak() and the recogniser callbacks need to call it (they refer to each other).
    var listen: () -> Unit = {}
    // Ends Talk mode: stop listening and speaking, stop a reply still being written, and close the overlay.
    fun end() {
        phase = "stopped"
        // runCatching ignores a failure here (the engine may already be stopped).
        runCatching { rec.cancel() }
        runCatching { tts.stop() }
        if (vm.streaming) vm.stop()
        vm.talking = false
    }
    // Start listening once. `return@listen` leaves this block early.
    listen = listen@{
        // Do nothing if the person ended Talk or has not allowed the microphone.
        if (phase == "stopped" || !allowed) return@listen
        phase = "listen"; state = "Listening…"; heard = ""
        // The callbacks Android calls as it hears you. Only some matter here; the empty ones are required by the interface.
        rec.setRecognitionListener(object : RecognitionListener {
            // Final result: the full sentence was heard.
            override fun onResults(results: Bundle?) {
                val said = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty().trim()
                if (phase == "stopped") return
                // Nothing recognised: try again in 0.3 s (300 ms).
                if (said.isEmpty()) { main.postDelayed({ listen() }, 300); return }
                // Show it, send it as a message, and remember to speak the answer once it is written.
                heard = said
                phase = "think"; state = "Thinking…"
                waiting = true
                vm.send(said)
            }
            // Live words while you are still talking: show them as they come.
            override fun onPartialResults(partial: Bundle?) {
                partial?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.let { heard = it }
            }
            // Errors are common (no speech heard, recogniser busy). Only a permission error ends Talk.
            override fun onError(error: Int) {
                if (phase == "stopped") return
                if (error == SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS) { allowed = false; state = "The microphone is blocked for Emvryx."; phase = "stopped"; return }
                main.postDelayed({ listen() }, 500)                     // nothing heard, or the recognizer was busy: listen again
            }
            override fun onReadyForSpeech(params: Bundle?) {}
            override fun onBeginningOfSpeech() {}
            override fun onRmsChanged(rmsdB: Float) {}
            override fun onBufferReceived(buffer: ByteArray?) {}
            override fun onEndOfSpeech() {}
            override fun onEvent(eventType: Int, params: Bundle?) {}
        })
        // Start the recogniser with free-form speech and partial results turned on.
        rec.startListening(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
        })
    }
    // Reads the answer out loud, and goes back to listening when it finishes.
    fun speak(text: String) {
        phase = "speak"; state = "Speaking… (tap the circle to interrupt)"
        // When the voice finishes (or fails), listen again. post{} runs it on the main thread.
        tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) {}
            override fun onDone(utteranceId: String?) { main.post { listen() } }
            @Deprecated("Deprecated in Java")
            override fun onError(utteranceId: String?) { main.post { listen() } }
        })
        // Speech.plain removes code, links and markdown marks. QUEUE_FLUSH drops anything already queued. The last text is just an id for this utterance.
        tts.speak(Speech.plain(text), TextToSpeech.QUEUE_FLUSH, null, "emvryx-talk")
    }
    // LaunchedEffect runs when the screen appears (Unit = just once): start listening, or ask for the microphone first.
    LaunchedEffect(Unit) { if (allowed) listen() else ask.launch(Manifest.permission.RECORD_AUDIO) }
    // If the permission arrives later, start listening then.
    LaunchedEffect(allowed) { if (allowed && phase == "listen") listen() }
    // Runs each time the reply starts or stops being written. When it has just finished, speak the new answer (or listen again if there is nothing to say).
    LaunchedEffect(vm.streaming) {
        // Only act if we sent something and it is no longer streaming.
        if (!waiting || vm.streaming || phase == "stopped") return@LaunchedEffect
        waiting = false
        val last = vm.bubbles.lastOrNull()
        if (last == null || last.mine || last.text.isBlank() || !ttsReady) listen() else speak(last.text)
    }
    // When the overlay leaves the screen, release the recogniser and the voice engine so they do not leak.
    DisposableEffect(Unit) { onDispose { phase = "stopped"; runCatching { rec.destroy() }; runCatching { tts.shutdown() } } }
    // The phone's Back button ends Talk.
    BackHandler { end() }

    val p = LocalPalette.current
    // A nearly opaque full-screen cover; clickable(enabled = false) swallows taps so nothing underneath is pressed.
    Box(Modifier.fillMaxSize().background(Emvryx.bg.copy(alpha = 0.97f)).clickable(enabled = false) {}, contentAlignment = Alignment.Center) {
        Column(Modifier.padding(28.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(16.dp)) {
            // The circle's ring colour shows the phase: bright while listening, softer while speaking, grey otherwise.
            val ring = when (phase) { "listen" -> p.accent; "speak" -> p.accent.copy(alpha = 0.6f); else -> Emvryx.line }
            // The big circle; tapping it while speaking cuts the voice off and listens straight away.
            Box(Modifier.size(150.dp).clip(CircleShape).background(p.accent.copy(alpha = if (phase == "think") 0.08f else 0.18f)).border(3.dp, ring, CircleShape)
                .clickable { if (phase == "speak") { tts.stop(); listen() } })
            Text(state, fontSize = 18.sp, fontWeight = FontWeight.SemiBold, textAlign = TextAlign.Center)
            Text(heard, color = Emvryx.muted, fontSize = 16.sp, textAlign = TextAlign.Center)
            Text("Your phone turns your voice into words. Pause when you are done; Emvryx answers out loud, then listens again.",
                color = Emvryx.muted, fontSize = 13.sp, textAlign = TextAlign.Center)
            PwaButton("End", { end() }, Modifier.fillMaxWidth())
        }
    }
}

// ---------------------------------------------------------------- Scheduled tasks: messages Emvryx answers by itself at a set time

/**
 * The Scheduled tasks page: the list of tasks (open, run now, pause, delete) and a form to add one.
 * The server runs each task by itself at its time and writes the answer into its own chat.
 */
@Composable
fun SchedulesPane(vm: AppViewModel) {
    // The server client, and a scope for starting background work from taps.
    val api = (LocalContext.current.applicationContext as EmvryxApp).api
    val scope = rememberCoroutineScope()
    // [tasks] is null until the first load. [error] is a load failure, [note] a message after an action, [reload] re-runs the loader when counted up.
    var tasks by remember { mutableStateOf<List<Schedule>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    var note by remember { mutableStateOf<String?>(null) }
    // The "new task" form fields: what to do, a name, how often, the time, a date (for "once"), and the chosen weekdays (0 = Monday ... 4 = Friday).
    var prompt by remember { mutableStateOf("") }
    var name by remember { mutableStateOf("") }
    var kind by remember { mutableStateOf("daily") }
    var time by remember { mutableStateOf("07:30") }
    var date by remember { mutableStateOf("") }
    var days by remember { mutableStateOf(setOf(0, 1, 2, 3, 4)) }
    // The task waiting on a delete confirmation, if any.
    var deleting by remember { mutableStateOf<Schedule?>(null) }
    // Runs a server call that returns the updated list, in the background, and shows the new list (or an error message).
    fun act(block: suspend () -> Schedules) = scope.launch {
        note = null
        try { tasks = block().tasks } catch (e: Exception) { if (!vm.handleSignedOut(e)) note = vm.describe(e) }
    }
    // Load the list when the page opens and each time `reload` changes.
    LaunchedEffect(reload) {
        error = null
        try { tasks = api.schedules().tasks } catch (e: Exception) { if (!vm.handleSignedOut(e)) error = vm.describe(e) }
    }
    // Still loading (or failed): show only the problem with a Try again button, otherwise draw the page.
    val list = tasks
    if (list == null) {
        error?.let { Problem(it, { reload++ }) }
        return
    }
    // A scrolling list: an intro, one card per task, then the new-task form.
    LazyColumn(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
        item {
            Text("Emvryx answers these by itself at the time you pick, each into a chat of its own. The PC has to be on then. They count on your plan like any message.",
                color = Emvryx.muted, fontSize = 14.sp, modifier = Modifier.padding(top = 14.dp, bottom = 10.dp))
            if (list.isEmpty()) Text("No scheduled tasks yet. For example: every morning at 7:30, “Give me a short summary of today’s news”.", color = Emvryx.muted, fontSize = 14.sp)
        }
        // One card per task. `key` keeps each card's identity when the list changes.
        items(list, key = { it.id }) { t ->
            Column(Modifier.fillMaxWidth().padding(vertical = 4.dp).clip(RoundedCornerShape(12.dp)).background(Emvryx.surface).padding(14.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(t.name, fontWeight = FontWeight.SemiBold, fontSize = 15.sp, color = if (t.on) Emvryx.text else Emvryx.muted)
                // "Every weekday at 07:30", plus "off" if paused and the last run time (the server sends seconds; Date wants milliseconds).
                Text(t.said + (if (t.on) "" else " · off") + (t.lastRun?.let { " · last ran " + DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT).format(Date((it * 1000).toLong())) } ?: ""),
                    color = Emvryx.muted, fontSize = 13.sp)
                if (t.lastError.isNotBlank()) Text(t.lastError, color = Emvryx.danger, fontSize = 13.sp)
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    // Open the chat the task last wrote into (only if there is one).
                    t.chat?.let { c -> Chip("Open", { vm.backToChat(); vm.openChat(c) }) }
                    // Run now / Pause or Resume / Delete (Delete only asks first, see the dialog below).
                    Chip("Run now", { act { api.scheduleDo(t.id, "run").also { note = "Running now: it appears in its chat in a moment." } } })
                    Chip(if (t.on) "Pause" else "Resume", { act { api.scheduleDo(t.id, "on", !t.on) } })
                    Chip("Delete", { deleting = t })
                }
            }
        }
        item {
            Text("NEW TASK", color = Emvryx.muted.copy(alpha = 0.8f), fontSize = 11.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.1.sp,
                modifier = Modifier.padding(start = 4.dp, top = 18.dp, bottom = 6.dp))
            // The form. Extra inputs appear only for the kinds that need them: a date for "once", day buttons for "weekly".
            Field("What should Emvryx do?", prompt, { prompt = it }, placeholder = "Give me a short summary of today’s news")
            Spacer(Modifier.height(10.dp))
            Field("Name (optional)", name, { name = it }, placeholder = "Morning news")
            Spacer(Modifier.height(10.dp))
            Choice(ScheduleForm.KINDS, kind) { kind = it }
            Spacer(Modifier.height(10.dp))
            Field("Time (24-hour)", time, { time = it }, placeholder = "07:30")
            if (kind == "once") {
                Spacer(Modifier.height(10.dp))
                Field("Date", date, { date = it }, placeholder = "2026-05-03")
            }
            if (kind == "weekly") {
                Spacer(Modifier.height(10.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    // One small button per weekday; tapping toggles it in the chosen set.
                    ScheduleForm.DAYS.forEachIndexed { i, d ->
                        val on = i in days
                        Box(Modifier.weight(1f).clip(RoundedCornerShape(10.dp)).background(if (on) LocalPalette.current.accent else Emvryx.surface2)
                            .clickable { days = if (on) days - i else days + i }.padding(vertical = 8.dp), contentAlignment = Alignment.Center) {
                            Text(d, fontSize = 12.sp, color = if (on) LocalPalette.current.onAccent else Emvryx.text)
                        }
                    }
                }
            }
            Spacer(Modifier.height(12.dp))
            // Add: check the form first (show the first problem if any), otherwise send it.
            PwaButton("Add", {
                val bad = ScheduleForm.problem(prompt, kind, time, date, days)
                if (bad != null) note = bad else act {
                    // The phone's offset from UTC in minutes, so the server runs the task at the person's local time.
                    val tz = TimeZone.getDefault().getOffset(System.currentTimeMillis()) / 60000
                    api.scheduleAdd(ScheduleForm.body(prompt, name, kind, time, date, days, tz, vm.model, vm.effort)).also { r ->
                        prompt = ""; name = ""
                        note = "Added: " + (r.task?.said ?: "") + ". You get a notification when it is ready."
                    }
                }
            }, Modifier.fillMaxWidth())
            note?.let { Text(it, color = Emvryx.muted, fontSize = 14.sp, modifier = Modifier.padding(top = 8.dp)) }
            Spacer(Modifier.height(24.dp))
        }
    }
    // The delete confirmation dialog.
    deleting?.let { t ->
        AlertDialog(
            onDismissRequest = { deleting = null },
            containerColor = Emvryx.surface,
            title = { Text("Delete “${t.name}”?") },
            confirmButton = { TextButton(onClick = { deleting = null; act { api.scheduleDo(t.id, "delete") } }) { Text("Delete") } },
            dismissButton = { TextButton(onClick = { deleting = null }) { Text("Cancel") } },
        )
    }
}
