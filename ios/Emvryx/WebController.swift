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

    override init() {
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

        webView.load(URLRequest(url: Site.home))
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

    /// The website asks for the microphone or camera: yes for Emvryx (iOS still asks the person the first time), no for anyone else.
    func webView(_ webView: WKWebView, requestMediaCapturePermissionFor origin: WKSecurityOrigin, initiatedByFrame frame: WKFrameInfo,
                 type: WKMediaCaptureType, decisionHandler: @escaping (WKPermissionDecision) -> Void) {
        decisionHandler(Site.mayUseMicAndCamera(scheme: origin.protocol, host: origin.host) ? .grant : .deny)
    }
}
