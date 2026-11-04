import Network
import SwiftUI
import WebKit

/// Owns the one web view that shows chat.emvryx.app, and decides what it may do: which links leave the app, who gets the microphone
/// and camera, and when to show the "No connection" page instead of the site.
@MainActor
final class WebController: NSObject, ObservableObject {
    @Published private(set) var offline = false
    /// Whether the phone has any internet at all, so the off page can say which end the problem is at.
    @Published private(set) var phoneOnline = true
    let webView: WKWebView
    /// The address that failed to load, so Retry goes back to it rather than to the start page.
    private var failedURL: URL?
    private let network = NWPathMonitor()
    /// The site's own function to open a panel once the page has loaded (openMemory(), openDocs() ...), as Android's in-app pages do.
    private var run: String?

    /// [start]: the page to open (the site, or Settings, Admin, VryxCode inside the native app); [run]: JavaScript to run once it loads.
    init(start: URL = Site.start, run: String? = nil) {
        self.run = run
        let config = WKWebViewConfiguration()
        config.applicationNameForUserAgent = Site.applicationName
        config.allowsInlineMediaPlayback = true
        config.mediaTypesRequiringUserActionForPlayback = []
        webView = WKWebView(frame: .zero, configuration: config)
        super.init()

        // The dark colour behind the page, so nothing flashes white while it loads or when it bounces.
        webView.isOpaque = false
        webView.backgroundColor = Site.background
        webView.scrollView.backgroundColor = Site.background
        webView.underPageBackgroundColor = Site.background
        webView.allowsBackForwardNavigationGestures = true
        webView.navigationDelegate = self
        webView.uiDelegate = self
        #if DEBUG
        // Lets Safari's Develop menu on the Mac look inside the page while testing.
        webView.isInspectable = true
        #endif

        // Pull down to reload.
        let refresh = UIRefreshControl()
        refresh.tintColor = .white
        refresh.addTarget(self, action: #selector(pulled), for: .valueChanged)
        webView.scrollView.refreshControl = refresh
        webView.scrollView.alwaysBounceVertical = true

        // When the connection comes back while the "No connection" page shows, try again by itself.
        network.pathUpdateHandler = { [weak self] path in
            guard let self else { return }
            let online = path.status == .satisfied
            Task { @MainActor in
                self.phoneOnline = online
                if online && self.offline { self.retry() }
            }
        }
        network.start(queue: .main)

        webView.load(URLRequest(url: start))
    }

    deinit { network.cancel() }

    /// Load again: the page that failed, or the current page, or the start page.
    func retry() {
        offline = false
        if let url = failedURL ?? webView.url {
            webView.load(URLRequest(url: url))
        } else {
            webView.load(URLRequest(url: Site.home))
        }
    }

    @objc private func pulled() {
        if webView.url == nil || offline { retry() } else { webView.reload() }
    }

    private func loadFailed(_ error: Error) {
        webView.scrollView.refreshControl?.endRefreshing()
        guard Site.isNoConnection(error) else { return }
        failedURL = (error as NSError).userInfo[NSURLErrorFailingURLErrorKey] as? URL
        offline = true
    }
}

extension WebController: WKNavigationDelegate {
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { return decisionHandler(.allow) }
        if Site.opensOutside(url, userTapped: action.navigationType == .linkActivated, newWindow: action.targetFrame == nil) {
            UIApplication.shared.open(url)
            return decisionHandler(.cancel)
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        webView.scrollView.refreshControl?.endRefreshing()
        if let js = run {
            run = nil
            webView.evaluateJavaScript(js)
        }
        failedURL = nil
        offline = false
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        loadFailed(error)
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        loadFailed(error)
    }

    /// iOS closed the page in the background to save memory: load it again rather than leave a blank screen.
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        webView.reload()
    }
}

extension WebController: WKUIDelegate {
    /// A link that asks for a new window (target="_blank", window.open): other sites go to Safari, Emvryx pages open here.
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url {
            if Site.opensOutside(url, userTapped: true, newWindow: true) {
                UIApplication.shared.open(url)
            } else {
                webView.load(action.request)
            }
        }
        return nil
    }

    // The site's alert(), confirm() and prompt() (Skipped files, "Delete this chat?") as iPhone alerts. WKWebView shows nothing unless the
    // app does it; Android's web view shows its own dialogs. Each completion handler runs exactly once.

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping () -> Void) {
        let alert = UIAlertController(title: nil, message: message, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler() })
        present(alert, over: webView, otherwise: completionHandler)
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping (Bool) -> Void) {
        let alert = UIAlertController(title: nil, message: message, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "Cancel", style: .cancel) { _ in completionHandler(false) })
        alert.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler(true) })
        present(alert, over: webView) { completionHandler(false) }
    }

    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String, defaultText: String?, initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping (String?) -> Void) {
        let alert = UIAlertController(title: nil, message: prompt, preferredStyle: .alert)
        alert.addTextField { $0.text = defaultText }
        alert.addAction(UIAlertAction(title: "Cancel", style: .cancel) { _ in completionHandler(nil) })
        alert.addAction(UIAlertAction(title: "OK", style: .default) { [weak alert] _ in completionHandler(alert?.textFields?.first?.text ?? "") })
        present(alert, over: webView) { completionHandler(nil) }
    }

    /// Show [alert] over whatever is on top; with nothing on screen to show it over, answer straight away with [otherwise].
    private func present(_ alert: UIAlertController, over webView: WKWebView, otherwise: () -> Void) {
        guard var top = webView.window?.rootViewController else { return otherwise() }
        while let next = top.presentedViewController { top = next }
        top.present(alert, animated: true)
    }

    /// The website asks for the microphone or camera: yes for Emvryx (iOS still asks the person the first time), no for anyone else.
    func webView(_ webView: WKWebView, requestMediaCapturePermissionFor origin: WKSecurityOrigin, initiatedByFrame frame: WKFrameInfo,
                 type: WKMediaCaptureType, decisionHandler: @escaping (WKPermissionDecision) -> Void) {
        decisionHandler(Site.mayUseMicAndCamera(scheme: origin.protocol, host: origin.host) ? .grant : .deny)
    }
}
