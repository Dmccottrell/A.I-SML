// The phone-assistant feature: what appears when the person holds the power/home button and Emvryx is the chosen "digital assistant".
// Android needs three pieces: a voice-interaction service (EmvryxVoiceService), a session service (EmvryxSessionService) that makes one
// popup per request, and the popup itself (AssistBar), drawn here with plain old Android views instead of Compose. All three are listed in AndroidManifest.xml.
package app.emvryx.android.assist

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.service.voice.VoiceInteractionService
import android.service.voice.VoiceInteractionSession
import android.service.voice.VoiceInteractionSessionService
import android.text.InputType
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import app.emvryx.android.MainActivity
import app.emvryx.android.local.Command
import app.emvryx.android.local.NativeFlags
import app.emvryx.android.local.VoiceCommands
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream

/**
 * android_assistant: Emvryx as the phone's assistant, like Gemini or Bixby. Picked in Settings > Apps > Default apps > Digital assistant, holding
 * the power or home button opens a bar over whatever is on screen: ask by voice or by typing, Ask about this screen, or a phone command
 * (VoiceCommands, done by PhoneActions). Questions go to the PC (or to the phone's own model with the PC off) through [Asker].
 */
class EmvryxVoiceService : VoiceInteractionService()

/** Android calls this each time the assistant is summoned, and it answers with a fresh popup (AssistBar). It needs no other logic. */
class EmvryxSessionService : VoiceInteractionSessionService() {
    override fun onNewSession(args: Bundle?): VoiceInteractionSession = AssistBar(this)
}

/**
 * The assistant popup: a dark bar at the bottom of the screen with a text box, a microphone button, a send button, and two quick buttons
 * ("Ask about this screen", "Open Emvryx"). It shows what was heard and the answer. Everything is built in code (no layout file).
 * A VoiceInteractionSession is the window Android gives an assistant to draw in over other apps.
 */
class AssistBar(ctx: Context) : VoiceInteractionSession(ctx) {
    // Coroutines (functions that can pause) started here run in this scope; it is remade in onShow if it was cancelled by onDestroy
    private var scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    // voice = speech listening/speaking helper; screen = the screenshot Android shares; chatId = the chat the questions go into; job = the running question
    private var voice: Voice? = null
    private var screen: Bitmap? = null
    private var chatId: Long? = null
    private var job: Job? = null
    // The on-screen pieces, created later in onCreateContentView (lateinit): text box, answer text, "what I heard" text, microphone button
    private lateinit var box: EditText
    private lateinit var answer: TextView
    private lateinit var heard: TextView
    private lateinit var mic: Button

    /** Converts dp (density-independent pixels, a size that looks the same on any phone) to real pixels for this screen */
    private fun dp(v: Int) = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v.toFloat(), context.resources.displayMetrics).toInt()

    /** A rounded rectangle background of the given colour; `radius` is in dp (22 by default, nearly round ends) */
    private fun pill(color: Int, radius: Int = 22) = GradientDrawable().apply { setColor(color); cornerRadius = dp(radius).toFloat() }

    /** Makes one styled button. `primary` = purple accent with white text, otherwise a dark grey one. `onClick` runs when tapped. */
    private fun button(text: String, primary: Boolean = false, onClick: () -> Unit) = Button(context).apply {
        this.text = text
        isAllCaps = false
        setTextColor(if (primary) Color.WHITE else TEXT)
        background = pill(if (primary) ACCENT else SURFACE2)
        // Both are set because different Android versions read different ones; 44 dp is a comfortable finger size
        minHeight = dp(44); minimumHeight = dp(44)
        setPadding(dp(14), 0, dp(14), 0)
        setOnClickListener { onClick() }
    }

    /** Builds the popup layout once: a transparent full-screen root holding the bar at the bottom. Returns the root view. */
    override fun onCreateContentView(): View {
        val root = FrameLayout(context)
        root.setOnClickListener { hide() }                                             // a tap above the bar closes it
        val bar = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            // cornerRadii wants 8 numbers (x,y for each corner, starting top-left): the first 4 are the two top corners, rounded; the bottom two stay square
            background = GradientDrawable().apply { setColor(BG); cornerRadii = FloatArray(8) { i -> if (i < 4) dp(24).toFloat() else 0f } }
            setPadding(dp(16), dp(14), dp(16), dp(18))
            // so taps on the bar do not fall through to the "tap above the bar closes it" handler on the root
            isClickable = true
        }
        val title = TextView(context).apply { text = "Emvryx"; setTextColor(TEXT); textSize = 16f; paint.isFakeBoldText = true }
        heard = TextView(context).apply { setTextColor(MUTED); textSize = 14f; visibility = View.GONE }
        answer = TextView(context).apply {
            setTextColor(TEXT); textSize = 16f; visibility = View.GONE
            maxHeight = (context.resources.displayMetrics.heightPixels * 0.45).toInt()
            setTextIsSelectable(true)                                                // selectable text also scrolls when it is long
            isVerticalScrollBarEnabled = true
        }
        box = EditText(context).apply {
            hint = "Ask Emvryx"
            setHintTextColor(MUTED); setTextColor(TEXT)
            background = pill(SURFACE)
            setPadding(dp(16), dp(10), dp(16), dp(10))
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_CAP_SENTENCES
            imeOptions = EditorInfo.IME_ACTION_SEND
            // The keyboard's Send key sends the question; returning true says "handled"
            setOnEditorActionListener { _, id, _ -> if (id == EditorInfo.IME_ACTION_SEND) { go(text.toString(), false); true } else false }
        }
        // Microphone button starts listening; the arrow button sends what is typed
        mic = button("🎤", true) { listen() }
        val send = button("➤", true) { go(box.text.toString(), false) }
        // One row: text box (weight 1 = takes all spare width), then the mic and send buttons, 48 dp square
        val row = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            addView(box, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
            addView(mic, LinearLayout.LayoutParams(dp(48), dp(48)).apply { marginStart = dp(8) })
            addView(send, LinearLayout.LayoutParams(dp(48), dp(48)).apply { marginStart = dp(6) })
        }
        // The two quick-action buttons under the row
        val chips = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            addView(button("Ask about this screen") { aboutScreen() })
            addView(button("Open Emvryx") { openApp() }, LinearLayout.LayoutParams(WRAP_CONTENT, WRAP_CONTENT).apply { marginStart = dp(8) })
        }
        // Stack everything top to bottom inside the bar, then put the bar at the bottom of the screen
        bar.addView(title)
        bar.addView(heard, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT).apply { topMargin = dp(6) })
        bar.addView(answer, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT).apply { topMargin = dp(8) })
        bar.addView(row, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT).apply { topMargin = dp(10) })
        bar.addView(chips, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT).apply { topMargin = dp(10) })
        root.addView(bar, FrameLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT, Gravity.BOTTOM))
        return root
    }

    /**
     * The popup was summoned. Reset it (new coroutine scope if needed, new chat, empty box), tell the person if the feature is switched off for
     * their account, otherwise start listening right away when the microphone is allowed.
     */
    override fun onShow(args: Bundle?, showFlags: Int) {
        super.onShow(args, showFlags)
        if (!scope.isActiveScope()) scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
        voice = voice ?: Voice(context)
        chatId = null
        box.setText("")
        show("", null)
        // The feature is controlled by an account switch (feature flag); if it is off, say so and do nothing else
        if (!NativeFlags.on(context, "android_assistant")) {
            show("The Emvryx assistant is not switched on for your account yet. Open Emvryx once after it is switched on.", null)
            return
        }
        if (micAllowed()) listen()
    }

    /** Android hands over a picture of the screen underneath (if the person allowed it); kept for "Ask about this screen" */
    override fun onHandleScreenshot(screenshot: Bitmap?) { screen = screenshot }

    /** The popup closed: stop any running question and speech, and drop the screenshot so it is not kept in memory */
    override fun onHide() {
        job?.cancel()
        voice?.quiet()
        screen = null
        super.onHide()
    }

    /** The session is over for good: free the speech engine and cancel all coroutines */
    override fun onDestroy() {
        voice?.close(); voice = null
        scope.cancel()
        super.onDestroy()
    }

    // True when this scope has not been cancelled (a cancelled scope cannot start new work, so onShow replaces it)
    private fun CoroutineScope.isActiveScope() = coroutineContext[Job]?.isActive == true

    /** Has the person allowed the app to use the microphone? */
    private fun micAllowed() = context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

    /** Updates the popup: `text` is the answer area, `said` is the small line above it (what was heard or asked). Empty ones are hidden. */
    private fun show(text: String, said: String?) {
        answer.text = text
        answer.visibility = if (text.isEmpty()) View.GONE else View.VISIBLE
        heard.text = said.orEmpty()
        heard.visibility = if (said.isNullOrEmpty()) View.GONE else View.VISIBLE
    }

    /** Starts listening with the microphone. Shows hints if the feature is off or the microphone is not allowed. */
    private fun listen() {
        if (!NativeFlags.on(context, "android_assistant")) return
        if (!micAllowed()) { show("Allow the microphone for Emvryx first: open Emvryx and tap Talk once, or Settings > Apps > Emvryx > Permissions.", null); return }
        // Stop any speech that is still playing, then show "…" on the mic button while listening
        val v = voice ?: return
        voice?.quiet()
        mic.text = "…"
        show("", "Listening…")
        // Three callbacks: partial = words so far (shown live); done = the final sentence (sent on, or ignored if empty); failed = show why.
        // The button goes back to the microphone symbol in both end cases.
        v.listen(partial = { heard.text = it; heard.visibility = View.VISIBLE },
            done = { said -> mic.text = "🎤"; if (said.isEmpty()) show("", null) else go(said, true) },
            failed = { why -> mic.text = "🎤"; show(why, null) })
    }

    /**
     * What was said or typed: a phone command is done at once; anything else is asked.
     * `said` = the words, `byVoice` = true when spoken (then the answer is read out loud too).
     */
    private fun go(said: String, byVoice: Boolean) {
        val text = said.trim()
        if (text.isEmpty()) return
        if (!NativeFlags.on(context, "android_assistant")) return
        box.setText("")
        // VoiceCommands.parse decides if the words are a phone command ("set a timer...") or a question for Emvryx.
        // None = nothing to do; Ask = a question; anything else = a phone command to carry out right here.
        when (val c = VoiceCommands.parse(text)) {
            is Command.None -> return
            is Command.Ask -> ask(c.text, null, byVoice)
            else -> {
                val done = PhoneActions.run(context, c)
                show(done, text)
                // If the action opened another app, close this bar; otherwise read the result aloud (only if the person spoke)
                if (PhoneActions.opensScreen(c)) hide() else if (byVoice) voice?.speak(done)
            }
        }
    }

    /** "Ask about this screen": sends the screenshot (and any typed words) to Emvryx and shows the answer */
    private fun aboutScreen() {
        if (!NativeFlags.on(context, "android_assistant")) return
        // No screenshot means Android did not share it (the setting is off), so explain how to turn it on
        val shot = screen ?: run {
            show("Android did not share the screen. Turn on Use screenshot in Settings > Apps > Default apps > Digital assistant, then try again.", null)
            return
        }
        // Use what the person typed as the question, or a default one
        val q = box.text.toString().trim().ifEmpty { "What is on my screen? Explain it briefly, and tell me anything I should do about it." }
        box.setText("")
        scope.launch {
            // Compressing a picture is heavy work, so it is done off the main thread; JPEG at quality 85 keeps the upload small
            val jpeg = withContext(Dispatchers.Default) { ByteArrayOutputStream().also { shot.compress(Bitmap.CompressFormat.JPEG, 85, it) }.toByteArray() }
            ask(q, "screen.jpg" to jpeg, false)
        }
    }

    /**
     * Sends a question (and optionally a picture as a name + bytes pair) to Emvryx through Asker, and shows the answer.
     * Cancels a question still running first. If `byVoice`, the answer is spoken and then the mic listens again for a follow-up.
     */
    private fun ask(question: String, picture: Pair<String, ByteArray>?, byVoice: Boolean) {
        job?.cancel()
        show("Thinking…", question)
        job = scope.launch {
            // The last lambda receives text as it streams in (so the answer appears word by word); each update is shown on the main thread
            val a = Asker.ask(context, question, chatId, picture) { so -> scope.launch { show(so, question) } }
            if (a.chatId != null) chatId = a.chatId                               // the next question carries on in the same chat
            // Show the answer, or the reason it failed, or a fallback line
            val text = a.text ?: a.problem ?: "No answer came back."
            show(text, question)
            if (byVoice && a.text != null) voice?.speak(text) { if (micAllowed()) listen() }
        }
    }

    /** Opens the full Emvryx app (on the same chat if there is one) and closes this bar */
    private fun openApp() {
        val i = Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        chatId?.let { i.putExtra(app.emvryx.android.Alerts.EXTRA_CHAT, it.toString()) }
        runCatching { context.startActivity(i) }
        hide()
    }

    // The popup colours (hex #RRGGBB), a dark purple-grey theme matching the app
    companion object {
        private val BG = Color.parseColor("#17151F")
        private val SURFACE = Color.parseColor("#24212F")
        private val SURFACE2 = Color.parseColor("#2E2A3B")
        private val TEXT = Color.parseColor("#F4F2FA")
        private val MUTED = Color.parseColor("#A7A2B8")
        private val ACCENT = Color.parseColor("#8B5CF6")
    }
}
