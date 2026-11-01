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

class EmvryxSessionService : VoiceInteractionSessionService() {
    override fun onNewSession(args: Bundle?): VoiceInteractionSession = AssistBar(this)
}

class AssistBar(ctx: Context) : VoiceInteractionSession(ctx) {
    private var scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var voice: Voice? = null
    private var screen: Bitmap? = null
    private var chatId: Long? = null
    private var job: Job? = null
    private lateinit var box: EditText
    private lateinit var answer: TextView
    private lateinit var heard: TextView
    private lateinit var mic: Button

    private fun dp(v: Int) = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v.toFloat(), context.resources.displayMetrics).toInt()

    private fun pill(color: Int, radius: Int = 22) = GradientDrawable().apply { setColor(color); cornerRadius = dp(radius).toFloat() }

    private fun button(text: String, primary: Boolean = false, onClick: () -> Unit) = Button(context).apply {
        this.text = text
        isAllCaps = false
        setTextColor(if (primary) Color.WHITE else TEXT)
        background = pill(if (primary) ACCENT else SURFACE2)
        minHeight = dp(44); minimumHeight = dp(44)
        setPadding(dp(14), 0, dp(14), 0)
        setOnClickListener { onClick() }
    }

    override fun onCreateContentView(): View {
        val root = FrameLayout(context)
        root.setOnClickListener { hide() }                                             // a tap above the bar closes it
        val bar = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            background = GradientDrawable().apply { setColor(BG); cornerRadii = FloatArray(8) { i -> if (i < 4) dp(24).toFloat() else 0f } }
            setPadding(dp(16), dp(14), dp(16), dp(18))
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
            setOnEditorActionListener { _, id, _ -> if (id == EditorInfo.IME_ACTION_SEND) { go(text.toString(), false); true } else false }
        }
        mic = button("🎤", true) { listen() }
        val send = button("➤", true) { go(box.text.toString(), false) }
        val row = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            addView(box, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
            addView(mic, LinearLayout.LayoutParams(dp(48), dp(48)).apply { marginStart = dp(8) })
            addView(send, LinearLayout.LayoutParams(dp(48), dp(48)).apply { marginStart = dp(6) })
        }
        val chips = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            addView(button("Ask about this screen") { aboutScreen() })
            addView(button("Open Emvryx") { openApp() }, LinearLayout.LayoutParams(WRAP_CONTENT, WRAP_CONTENT).apply { marginStart = dp(8) })
        }
        bar.addView(title)
        bar.addView(heard, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT).apply { topMargin = dp(6) })
        bar.addView(answer, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT).apply { topMargin = dp(8) })
        bar.addView(row, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT).apply { topMargin = dp(10) })
        bar.addView(chips, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT).apply { topMargin = dp(10) })
        root.addView(bar, FrameLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT, Gravity.BOTTOM))
        return root
    }

    override fun onShow(args: Bundle?, showFlags: Int) {
        super.onShow(args, showFlags)
        if (!scope.isActiveScope()) scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
        voice = voice ?: Voice(context)
        chatId = null
        box.setText("")
        show("", null)
        if (!NativeFlags.on(context, "android_assistant")) {
            show("The Emvryx assistant is not switched on for your account yet. Open Emvryx once after it is switched on.", null)
            return
        }
        if (micAllowed()) listen()
    }

    override fun onHandleScreenshot(screenshot: Bitmap?) { screen = screenshot }

    override fun onHide() {
        job?.cancel()
        voice?.quiet()
        screen = null
        super.onHide()
    }

    override fun onDestroy() {
        voice?.close(); voice = null
        scope.cancel()
        super.onDestroy()
    }

    private fun CoroutineScope.isActiveScope() = coroutineContext[Job]?.isActive == true

    private fun micAllowed() = context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

    private fun show(text: String, said: String?) {
        answer.text = text
        answer.visibility = if (text.isEmpty()) View.GONE else View.VISIBLE
        heard.text = said.orEmpty()
        heard.visibility = if (said.isNullOrEmpty()) View.GONE else View.VISIBLE
    }

    private fun listen() {
        if (!NativeFlags.on(context, "android_assistant")) return
        if (!micAllowed()) { show("Allow the microphone for Emvryx first: open Emvryx and tap Talk once, or Settings > Apps > Emvryx > Permissions.", null); return }
        val v = voice ?: return
        voice?.quiet()
        mic.text = "…"
        show("", "Listening…")
        v.listen(partial = { heard.text = it; heard.visibility = View.VISIBLE },
            done = { said -> mic.text = "🎤"; if (said.isEmpty()) show("", null) else go(said, true) },
            failed = { why -> mic.text = "🎤"; show(why, null) })
    }

    /** What was said or typed: a phone command is done at once; anything else is asked */
    private fun go(said: String, byVoice: Boolean) {
        val text = said.trim()
        if (text.isEmpty()) return
        if (!NativeFlags.on(context, "android_assistant")) return
        box.setText("")
        when (val c = VoiceCommands.parse(text)) {
            is Command.None -> return
            is Command.Ask -> ask(c.text, null, byVoice)
            else -> {
                val done = PhoneActions.run(context, c)
                show(done, text)
                if (PhoneActions.opensScreen(c)) hide() else if (byVoice) voice?.speak(done)
            }
        }
    }

    private fun aboutScreen() {
        if (!NativeFlags.on(context, "android_assistant")) return
        val shot = screen ?: run {
            show("Android did not share the screen. Turn on Use screenshot in Settings > Apps > Default apps > Digital assistant, then try again.", null)
            return
        }
        val q = box.text.toString().trim().ifEmpty { "What is on my screen? Explain it briefly, and tell me anything I should do about it." }
        box.setText("")
        scope.launch {
            val jpeg = withContext(Dispatchers.Default) { ByteArrayOutputStream().also { shot.compress(Bitmap.CompressFormat.JPEG, 85, it) }.toByteArray() }
            ask(q, "screen.jpg" to jpeg, false)
        }
    }

    private fun ask(question: String, picture: Pair<String, ByteArray>?, byVoice: Boolean) {
        job?.cancel()
        show("Thinking…", question)
        job = scope.launch {
            val a = Asker.ask(context, question, chatId, picture) { so -> scope.launch { show(so, question) } }
            if (a.chatId != null) chatId = a.chatId                               // the next question carries on in the same chat
            val text = a.text ?: a.problem ?: "No answer came back."
            show(text, question)
            if (byVoice && a.text != null) voice?.speak(text) { if (micAllowed()) listen() }
        }
    }

    private fun openApp() {
        val i = Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        chatId?.let { i.putExtra(app.emvryx.android.Alerts.EXTRA_CHAT, it.toString()) }
        runCatching { context.startActivity(i) }
        hide()
    }

    companion object {
        private val BG = Color.parseColor("#17151F")
        private val SURFACE = Color.parseColor("#24212F")
        private val SURFACE2 = Color.parseColor("#2E2A3B")
        private val TEXT = Color.parseColor("#F4F2FA")
        private val MUTED = Color.parseColor("#A7A2B8")
        private val ACCENT = Color.parseColor("#8B5CF6")
    }
}
