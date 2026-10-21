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
    val app = androidx.compose.ui.platform.LocalContext.current.applicationContext as EmvryxApp
    val server = app.api.server ?: return
    var web by remember { mutableStateOf<WebView?>(null) }
    var ready by remember { mutableStateOf(false) }
    var pending by remember { mutableStateOf<ValueCallback<Array<Uri>>?>(null) }
    val chooser = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
        pending?.onReceiveValue(if (r.resultCode == Activity.RESULT_OK) WebChromeClient.FileChooserParams.parseResult(r.resultCode, r.data) else null)
        pending = null
    }
    BackHandler { web?.let { if (!panel && it.canGoBack()) it.goBack() else vm.backToChat() } ?: vm.backToChat() }
    val bg = Emvryx.bg
    val light = Emvryx.light

    // watch the page: ready when the website has loaded (and, for a panel, the panel is open); a panel that closes goes back to the app
    LaunchedEffect(web) {
        val w = web ?: return@LaunchedEffect
        var hadPanel = false
        var styled = false
        val started = System.currentTimeMillis()
        while (true) {
            // an object comes back as JSON text: {"up":true,"open":1,"busy":false}. Open counts the panels, pop-ups and a tour; busy is waiting on
            // the server: Settings' Memory, Usage, Documents, Apps, What's new and the tour close Settings first and open after a fetch
            val r = w.eval("({up: typeof S !== 'undefined' && !!S.state, open: (document.getElementById('dialogs') || {children: []}).children.length" +
                " + document.querySelectorAll('.tour').length, busy: (window.__emvxBusy || 0) > 0 && Date.now() - window.__emvxSince < 4000})")
            val up = r.contains("\"up\":true")
            val open = Regex("\"open\":(\\d+)").find(r)?.groupValues?.get(1)?.toIntOrNull() ?: 0
            val busy = r.contains("\"busy\":true")
            if (r.isNotEmpty() && r != "null") w.eval(FIT_HEIGHT)
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
                if (run.isNotEmpty()) w.eval("try { $run } catch (e) {}")
            }
            if (!ready && up && (!panel || open > 0)) {
                delay(40)                                              // let the panel draw its first frame before the cover lifts
                ready = true
            }
            if (!ready && System.currentTimeMillis() - started > 8000) ready = true      // never stuck behind the cover
            if (panel) {
                if (open > 0) hadPanel = true else if (hadPanel && !busy) { vm.backToChat(); break }    // empty and not waiting on the server: closed
            }
            delay(if (ready) 60 else 50)
        }
    }

    Box(Modifier.fillMaxSize().background(bg)) {
        Column(Modifier.fillMaxSize()) {
            if (!panel) Column(Modifier.statusBarsPadding()) {
                Row(Modifier.fillMaxWidth().height(56.dp).padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    IconButton(onClick = vm::backToChat) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back to the chat", tint = Emvryx.text) }
                    Text(title, fontWeight = FontWeight.SemiBold, fontSize = 17.sp)
                }
                HorizontalDivider(color = Emvryx.line)
            }
            AndroidView(
                modifier = Modifier.fillMaxWidth().weight(1f).then(if (panel) Modifier.statusBarsPadding() else Modifier).navigationBarsPadding(),
                factory = { ctx ->
                    app.session.cookieLine()?.let { CookieManager.getInstance().setCookie(server, it) }
                    CookieManager.getInstance().flush()
                    WebView(ctx).apply {
                        setBackgroundColor(bg.toArgb())
                        settings.javaScriptEnabled = true
                        settings.domStorageEnabled = true
                        settings.userAgentString = settings.userAgentString + " Emvryx-Android"
                        webViewClient = object : WebViewClient() {
                            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                                val u = request.url
                                val home = Uri.parse(server)
                                if (u.scheme == home.scheme && u.host == home.host && u.port == home.port) return false     // the Emvryx server's own pages stay in the app
                                runCatching { ctx.startActivity(Intent(Intent.ACTION_VIEW, u)) }
                                return true
                            }
                        }
                        webChromeClient = object : WebChromeClient() {
                            override fun onShowFileChooser(view: WebView, callback: ValueCallback<Array<Uri>>, params: FileChooserParams): Boolean {
                                pending?.onReceiveValue(null)
                                pending = callback
                                return runCatching { chooser.launch(params.createIntent()); true }.getOrElse { pending = null; false }
                            }
                        }
                        loadUrl(server + path)
                        web = this
                    }
                },
            )
        }
        // the cover: the app's own colours and mark until the page (or its panel) is ready, then it fades away
        AnimatedVisibility(!ready, exit = fadeOut(tween(150))) {
            Box(Modifier.fillMaxSize().background(bg), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(14.dp)) {
                    Logo(Modifier.size(48.dp), animate = true)
                    Text(title, color = Emvryx.muted, fontSize = 15.sp)
                }
            }
        }
    }
}

/**
 * In the app's WebView the website's `dvh` heights come out as 0 (measured: 100dvh = 0 while innerHeight = 867), which squashed the Memory
 * box and the other pop-ups (.dialog is max-height: 90dvh) to a strip. This puts the page's real height in --appH, kept up to date, and
 * uses it wherever index.html uses dvh. Runs on every look at the page; it does its work once.
 */
private const val FIT_HEIGHT = "(function () { if (!document.head || document.getElementById('emvx-fit')) return;" +
    // counts the page's requests still waiting on the server (see the panel watch in WebScreen)
    " var f = window.fetch; window.__emvxBusy = 0; window.fetch = function () { window.__emvxBusy++; window.__emvxSince = Date.now();" +
    " return f.apply(this, arguments).finally(function () { window.__emvxBusy-- }) };" +
    " var set = function () { document.documentElement.style.setProperty('--appH', innerHeight + 'px') }; set(); addEventListener('resize', set);" +
    " var st = document.createElement('style'); st.id = 'emvx-fit'; st.textContent =" +
    " '.app{height:calc(var(--appH) / var(--z, 1)) !important}' +" +
    " '.dialog{max-height:calc(var(--appH) * .9) !important}' +" +
    " '#modelMenu,#effortMenu,#ctxMenu{max-height:min(72vh, calc(var(--appH) - 190px)) !important}' +" +
    " '.code .top2 .menu{max-height:calc(var(--appH) - 90px) !important}';" +
    " document.head.appendChild(st) })()"

/** Runs a little JavaScript in the page and returns what it gave back ("" when the page is not ready) */
private suspend fun WebView.eval(js: String): String = suspendCancellableCoroutine { c ->
    evaluateJavascript(js) { r -> if (c.isActive) c.resume(r ?: "") }
}
