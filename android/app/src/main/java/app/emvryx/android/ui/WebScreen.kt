// Shows a page of the Emvryx website inside the app using a WebView (a mini browser embedded in the app).
// The app signs the WebView in with its own session cookie, keeps other websites out, covers the page with the app's own colours until it is ready,
// and feeds the page small JavaScript snippets (via `eval`) to match the app's theme, turn off pop-up tours and fix heights.
package app.emvryx.android.ui

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.webkit.CookieManager
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import app.emvryx.android.EmvryxApp
import app.emvryx.android.ui.theme.Emvryx
import kotlinx.coroutines.delay
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume

/**
 * A page of the Emvryx website inside the app, signed in with the app's own session. Only your Emvryx server's pages open here; any other
 * link opens in the phone's browser. Nothing from the app is exposed to the page.
 *
 * [panel]: the page is one of the website's panels (Settings, Admin, Skills, Memory, Documents). Then the app shows a cover in its own
 * colours until the panel is open (so the website's chat never flashes up first), hides the website behind the panel, and goes back
 * to the app as soon as the panel is closed (its own × or Close); the panel's own header is the only title.
 */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun WebScreen(vm: AppViewModel, path: String, title: String, run: String = "", panel: Boolean = false) {
    // The app-wide object (holds the server client and the saved login).
    val app = androidx.compose.ui.platform.LocalContext.current.applicationContext as EmvryxApp
    // The server's web address; without one (not connected yet) there is nothing to show, so draw nothing.
    val server = app.api.server ?: return
    // Screen state, remembered across redraws. `web`: the WebView once created. `ready`: the cover has lifted. `failed`: the page did not open in time.
    // `attempt` counts "Try again" presses (it restarts the watcher below). `pending`: the callback of a file-picker request from the page.
    var web by remember { mutableStateOf<WebView?>(null) }
    var ready by remember { mutableStateOf(false) }
    var failed by remember { mutableStateOf(false) }
    var attempt by remember { mutableStateOf(0) }
    var pending by remember { mutableStateOf<ValueCallback<Array<Uri>>?>(null) }
    // The phone's file picker. When the page asks to choose a file, we launch it; its result (the chosen file, or nothing if cancelled)
    // is handed back to the page through the saved callback.
    val chooser = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
        pending?.onReceiveValue(if (r.resultCode == Activity.RESULT_OK) WebChromeClient.FileChooserParams.parseResult(r.resultCode, r.data) else null)
        pending = null
    }
    // Back button: inside a normal page go back in its history; otherwise (or in a panel) return to the app's chat.
    BackHandler { web?.let { if (!panel && it.canGoBack()) it.goBack() else vm.backToChat() } ?: vm.backToChat() }
    // The app's background colour and whether the app is in light mode, used to match the website to the app.
    val bg = Emvryx.bg
    val light = Emvryx.light

    // watch the page: ready when the website has loaded (and, for a panel, the panel is open); a panel that closes goes back to the app
    // LaunchedEffect starts a background task when the screen appears and restarts it when `web` or `attempt` changes.
    // This one polls the page about every 50 ms: it styles the page once it is up, lifts the cover when ready, and leaves a panel when it is closed.
    LaunchedEffect(web, attempt) {
        // Wait for the WebView to exist.
        val w = web ?: return@LaunchedEffect
        // `hadPanel`: a panel has been seen open at least once. `styled`: the one-time page tweaks are done. `started`: when we began (for the time-out).
        var hadPanel = false
        var styled = false
        val started = System.currentTimeMillis()
        // Check the page again and again until the cover lifts for good, it fails, or the panel closes (each of those ends with `break`).
        while (true) {
            // an object comes back as JSON text: {"up":true,"open":1,"busy":false}. Open counts the panels, pop-ups and a tour; busy is waiting on
            // the server: Settings' Memory, Usage, Documents, Apps, What's new and the tour close Settings first and open after a fetch
            val r = w.eval("({up: typeof S !== 'undefined' && !!S.state, open: (document.getElementById('dialogs') || {children: []}).children.length" +
                " + document.querySelectorAll('.tour').length, busy: (window.__emvxBusy || 0) > 0 && Date.now() - window.__emvxSince < 4000})")
            // Read the reply: is the website's app loaded (up), how many dialogs/tours are open, and is it waiting on the server (busy).
            // The Regex (a text pattern) finds the number after "open": ; \\d+ means one or more digits. A missing number counts as 0.
            val up = r.contains("\"up\":true")
            val open = Regex("\"open\":(\\d+)").find(r)?.groupValues?.get(1)?.toIntOrNull() ?: 0
            val busy = r.contains("\"busy\":true")
            // Once the page answers, inject the height fix (it does its work only once).
            if (r.isNotEmpty() && r != "null") w.eval(FIT_HEIGHT)
            // The first time the website is up: apply the one-time tweaks below.
            if (up && !styled) {
                styled = true
                // the website follows the app's light or dark choice; behind a panel the website itself is hidden
                // the app runs its own tours: the website's welcome tour, "what's new" and model tours never pop up by themselves on top of a
                // page here. Only the automatic calls (false) are stopped: Settings' "Start the tour" and "See releases" (true) still work.
                w.eval("try { S.tourChecked = true; S.tourSoon = false; window.maybeTour = window.checkWhatsNew = window.checkModelTour = window.maybeVryxTour = function () {};" +
                       " ['openTour', 'openWhatsNew', 'openVryxTour'].forEach(function (n) { var f = window[n]; if (f) window[n] = function (asked) { if (asked) return f.apply(this, arguments) } });" +
                       " var mt = window.openModelTour; if (mt) window.openModelTour = function (c, asked) { if (asked) return mt.apply(this, arguments) };" +
                       " document.querySelectorAll('.tour').forEach(function (t) { t.remove() }) } catch (e) {}")
                w.eval("try { S.theme = '${if (light) "light" else "dark"}'; localStorage.setItem('emvryx_theme', S.theme); applyTheme() } catch (e) {}" +
                       if (panel) "; var st = document.createElement('style'); st.textContent = '#app{visibility:hidden !important}'; document.head.appendChild(st)" else "")
                // Run any extra script the caller asked for (for example open a certain panel).
                if (run.isNotEmpty()) w.eval("try { $run } catch (e) {}")
            }
            // Decide what the cover should do now. Once ready, it stays ready.
            when (if (ready) Cover.Ready else coverAfter(up, panel, open, System.currentTimeMillis() - started)) {
                Cover.Ready -> if (!ready) {
                    delay(40)                                          // let the panel draw its first frame before the cover lifts
                    ready = true
                }
                // never stuck behind the cover, and never lifted onto an empty page (the black screen): say so, with Try again
                Cover.Failed -> { failed = true; break }
                Cover.Waiting -> {}
            }
            // A panel counts as closed when it was open before and now nothing is open and no request is pending: then return to the app.
            if (panel) {
                if (open > 0) hadPanel = true else if (hadPanel && !busy) { vm.backToChat(); break }    // empty and not waiting on the server: closed
            }
            // Pause (so the loop does not use all the battery) before the next look.
            delay(if (ready) 60 else 50)
        }
    }

    // Layout: a full-screen box holding the page (with a top bar unless it is a panel) and, on top, the cover.
    Box(Modifier.fillMaxSize().background(bg)) {
        Column(Modifier.fillMaxSize()) {
            // Normal pages get a top bar with a back arrow and the title; panels have their own header.
            if (!panel) Column(Modifier.statusBarsPadding()) {
                Row(Modifier.fillMaxWidth().height(56.dp).padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    IconButton(onClick = vm::backToChat) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back to the chat", tint = Emvryx.text) }
                    Text(title, fontWeight = FontWeight.SemiBold, fontSize = 17.sp)
                }
                HorizontalDivider(color = Emvryx.line)
            }
            // AndroidView embeds an old-style Android view (the WebView) inside Compose. `factory` runs once to create it.
            AndroidView(
                modifier = Modifier.fillMaxWidth().weight(1f).then(if (panel) Modifier.statusBarsPadding() else Modifier).navigationBarsPadding(),
                factory = { ctx ->
                    // Give the WebView the app's login cookie so the website sees the same signed-in person; flush() saves it right away.
                    app.session.cookieLine()?.let { CookieManager.getInstance().setCookie(server, it) }
                    CookieManager.getInstance().flush()
                    // Create and configure the WebView: background colour, JavaScript and local storage on, and a user-agent tag so the website knows it runs in the app.
                    WebView(ctx).apply {
                        setBackgroundColor(bg.toArgb())
                        settings.javaScriptEnabled = true
                        settings.domStorageEnabled = true
                        settings.userAgentString = settings.userAgentString + " Emvryx-Android"
                        // Decides what happens when a link is clicked.
                        webViewClient = object : WebViewClient() {
                            // Return false = let the WebView load it; true = we handled it ourselves.
                            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                                val u = request.url
                                // Same scheme (http/https), host and port as our server means it is our own page.
                                val home = Uri.parse(server)
                                if (u.scheme == home.scheme && u.host == home.host && u.port == home.port) return false     // the Emvryx server's own pages stay in the app
                                // Any other address opens in the phone's browser (runCatching ignores the error if no browser can open it).
                                runCatching { ctx.startActivity(Intent(Intent.ACTION_VIEW, u)) }
                                return true
                            }
                        }
                        // Handles things the page asks of the browser, here the "choose a file" dialog.
                        webChromeClient = object : WebChromeClient() {
                            override fun onShowFileChooser(view: WebView, callback: ValueCallback<Array<Uri>>, params: FileChooserParams): Boolean {
                                // Cancel any earlier unanswered request, remember this one and open the picker; if opening fails, report "not handled" (false).
                                pending?.onReceiveValue(null)
                                pending = callback
                                return runCatching { chooser.launch(params.createIntent()); true }.getOrElse { pending = null; false }
                            }
                        }
                        // Start loading the wanted page, and keep a reference so the rest of the screen can use the WebView.
                        loadUrl(server + path)
                        web = this
                    }
                },
            )
        }
        // the cover: the app's own colours and mark until the page (or its panel) is ready, then it fades away
        AnimatedVisibility(!ready, exit = fadeOut(tween(150))) {
            Box(Modifier.fillMaxSize().background(bg).statusBarsPadding(), contentAlignment = Alignment.Center) {
                // Failure: show the message with Try again (reload and restart the watcher) and Back. Otherwise show the logo and the title while loading.
                if (failed) Problem("$title did not open. Emvryx may be busy or restarting, or the connection dropped.",
                    retry = { failed = false; web?.reload(); attempt++ }, back = vm::backToChat)
                else Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(14.dp)) {
                    Logo(Modifier.size(48.dp), animate = true)
                    Text(title, color = Emvryx.muted, fontSize = 15.sp)
                }
            }
        }
    }
}

/** What the cover should do: keep waiting, lift (the page is ready), or give up (the page failed to open). */
enum class Cover { Waiting, Ready, Failed }

/** The cover over a website page: lifted once the page is up (and, for a panel, the panel is open). A page that is not ready after
 *  [COVER_GIVE_UP_MS] gets "did not open" with Try again; lifting it anyway showed a black page (the website is hidden behind a panel). */
fun coverAfter(up: Boolean, panel: Boolean, open: Int, waitedMs: Long): Cover = when {
    up && (!panel || open > 0) -> Cover.Ready
    waitedMs > COVER_GIVE_UP_MS -> Cover.Failed
    else -> Cover.Waiting
}

// How long to wait for a page before giving up: 15 000 milliseconds = 15 seconds.
const val COVER_GIVE_UP_MS = 15_000L

/**
 * In the app's WebView the website's `dvh` heights come out as 0 (measured: 100dvh = 0 while innerHeight = 867), which squashed the Memory
 * box and the other pop-ups (.dialog is max-height: 90dvh) to a strip. This puts the page's real height in --appH, kept up to date, and
 * uses it wherever index.html uses dvh. Runs on every look at the page; it does its work once.
 */
private const val FIT_HEIGHT = "(function () { if (!document.head || document.getElementById('emvx-fit')) return;" +
    // counts the page's requests still waiting on the server (see the panel watch in WebScreen)
    " var f = window.fetch; window.__emvxBusy = 0; window.fetch = function () { window.__emvxBusy++; window.__emvxSince = Date.now();" +
    " return f.apply(this, arguments).finally(function () { window.__emvxBusy-- }) };" +
    // Save the real window height in the CSS variable --appH now and again whenever the window is resized.
    " var set = function () { document.documentElement.style.setProperty('--appH', innerHeight + 'px') }; set(); addEventListener('resize', set);" +
    // Add a style sheet that uses --appH instead of the broken dvh heights for the app area, dialogs and menus (!important beats the page's own rules).
    " var st = document.createElement('style'); st.id = 'emvx-fit'; st.textContent =" +
    " '.app{height:calc(var(--appH) / var(--z, 1)) !important}' +" +
    " '.dialog{max-height:calc(var(--appH) * .9) !important}' +" +
    " '#modelMenu,#effortMenu,#ctxMenu{max-height:min(72vh, calc(var(--appH) - 190px)) !important}' +" +
    " '.code .top2 .menu{max-height:calc(var(--appH) - 90px) !important}';" +
    " document.head.appendChild(st) })()"

/** Runs a little JavaScript in the page and returns what it gave back ("" when the page is not ready) */
private suspend fun WebView.eval(js: String): String = suspendCancellableCoroutine { c ->
    // evaluateJavascript runs the script and gives the result as text later; we resume the paused coroutine with it (or "" if none),
    // but only if the coroutine was not cancelled meanwhile (c.isActive).
    evaluateJavascript(js) { r -> if (c.isActive) c.resume(r ?: "") }
}
