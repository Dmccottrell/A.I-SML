import SwiftUI
import WebKit

@main
struct EmvryxApp: App {
    var body: some Scene {
        WindowGroup { ContentView() }
    }
}

/// The whole app: the website full screen, the dark colour behind it (status bar and home bar areas too), and the
/// "No connection" page on top when the site cannot be reached.
struct ContentView: View {
    @StateObject private var web = WebController()

    var body: some View {
        ZStack {
            Color(uiColor: Site.background).ignoresSafeArea()
            // The page stays inside the safe area (clear of the notch and home bar); the web view moves for the keyboard by itself.
            WebView(webView: web.webView).ignoresSafeArea(.keyboard)
            if web.offline { OffScreen(phoneOnline: web.phoneOnline, retry: web.retry) }
        }
        .preferredColorScheme(.dark)
    }
}

/// Puts the controller's web view on screen.
struct WebView: UIViewRepresentable {
    let webView: WKWebView
    func makeUIView(context: Context) -> WKWebView { webView }
    func updateUIView(_ uiView: WKWebView, context: Context) {}
}
