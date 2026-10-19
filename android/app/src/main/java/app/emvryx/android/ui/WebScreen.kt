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
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import app.emvryx.android.EmvryxApp
import app.emvryx.android.ui.theme.Emvryx

/**
 * A page of the Emvryx website inside the app, signed in with the app's own session: Settings, Admin, and the parts the app has no
 * screen of its own for (skills, teacher mode, connected apps, files, sharing, VryxCode's editor ...). Only your Emvryx server's pages open
 * here; any other link opens in the phone's browser. Nothing from the app is exposed to the page.
 */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun WebScreen(vm: AppViewModel, path: String, title: String) {
    val app = androidx.compose.ui.platform.LocalContext.current.applicationContext as EmvryxApp
    val server = app.api.server ?: return
    var web by remember { mutableStateOf<WebView?>(null) }
    var pending by remember { mutableStateOf<ValueCallback<Array<Uri>>?>(null) }
    val chooser = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
        pending?.onReceiveValue(if (r.resultCode == Activity.RESULT_OK) WebChromeClient.FileChooserParams.parseResult(r.resultCode, r.data) else null)
        pending = null
    }
    BackHandler { web?.let { if (it.canGoBack()) it.goBack() else vm.backToChat() } ?: vm.backToChat() }
    Column(Modifier.fillMaxSize().background(Emvryx.bg)) {
        Column(Modifier.statusBarsPadding()) {
            Row(Modifier.fillMaxWidth().height(56.dp).padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = vm::backToChat) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back to the chat", tint = Emvryx.text) }
                Text(title, fontWeight = FontWeight.SemiBold, fontSize = 17.sp)
            }
            HorizontalDivider(color = Emvryx.line)
        }
        AndroidView(
            modifier = Modifier.fillMaxWidth().weight(1f).navigationBarsPadding(),
            factory = { ctx ->
                app.session.cookieLine()?.let { CookieManager.getInstance().setCookie(server, it) }
                CookieManager.getInstance().flush()
                WebView(ctx).apply {
                    setBackgroundColor(android.graphics.Color.parseColor("#07080D"))
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
}
