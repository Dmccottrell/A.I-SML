import XCTest
@testable import Emvryx

final class SiteTests: XCTestCase {
    private func url(_ s: String) -> URL { URL(string: s)! }

    func testEmvryxLinksStayInTheApp() {
        XCTAssertFalse(Site.opensOutside(url("https://chat.emvryx.app/settings"), userTapped: true, newWindow: false))
        XCTAssertFalse(Site.opensOutside(url("https://CHAT.emvryx.app/"), userTapped: true, newWindow: true))
    }

    func testOtherSitesTappedOpenInSafari() {
        XCTAssertTrue(Site.opensOutside(url("https://example.com/"), userTapped: true, newWindow: false))
        XCTAssertTrue(Site.opensOutside(url("https://example.com/"), userTapped: false, newWindow: true))
        // Plain http to our own name is not ours: the site is https only.
        XCTAssertTrue(Site.opensOutside(url("http://chat.emvryx.app/"), userTapped: true, newWindow: false))
    }

    func testRedirectsTheSiteMakesStayInside() {
        // A sign-in page the site sends you to (not a tap) loads in the app, so it can come back signed in.
        XCTAssertFalse(Site.opensOutside(url("https://accounts.google.com/o/oauth2/v2/auth"), userTapped: false, newWindow: false))
    }

    func testOtherAppsAndWebKitAddresses() {
        XCTAssertTrue(Site.opensOutside(url("mailto:a@example.com"), userTapped: false, newWindow: false))
        XCTAssertTrue(Site.opensOutside(url("tel:123"), userTapped: true, newWindow: false))
        XCTAssertFalse(Site.opensOutside(url("about:blank"), userTapped: false, newWindow: false))
        XCTAssertFalse(Site.opensOutside(url("blob:https://chat.emvryx.app/1234"), userTapped: true, newWindow: true))
    }

    func testMicAndCameraOnlyForEmvryx() {
        XCTAssertTrue(Site.mayUseMicAndCamera(scheme: "https", host: "chat.emvryx.app"))
        XCTAssertFalse(Site.mayUseMicAndCamera(scheme: "http", host: "chat.emvryx.app"))
        XCTAssertFalse(Site.mayUseMicAndCamera(scheme: "https", host: "evil.example"))
        XCTAssertFalse(Site.mayUseMicAndCamera(scheme: "https", host: "chat.emvryx.app.evil.example"))
    }

    @MainActor
    func testNoConnectionErrors() {
        XCTAssertTrue(Site.isNoConnection(NSError(domain: NSURLErrorDomain, code: NSURLErrorNotConnectedToInternet)))
        XCTAssertTrue(Site.isNoConnection(NSError(domain: NSURLErrorDomain, code: NSURLErrorCannotFindHost)))
        // A load stopped because another started is not "no connection".
        XCTAssertFalse(Site.isNoConnection(NSError(domain: NSURLErrorDomain, code: NSURLErrorCancelled)))
        XCTAssertFalse(Site.isNoConnection(NSError(domain: "WebKitErrorDomain", code: 102)))
    }

    func testUserAgentEndsWithTheAppTag() {
        XCTAssertTrue(Site.applicationName.hasSuffix("EmvryxiOS/1.0"))
    }
}

final class WebControllerTests: XCTestCase {
    @MainActor
    func testTheWebViewSendsTheAppUserAgent() async throws {
        let web = WebController()
        let agent = try await web.webView.evaluateJavaScript("navigator.userAgent") as? String ?? ""
        XCTAssertTrue(agent.hasSuffix("Mobile/15E148 EmvryxiOS/1.0"), agent)
    }

    @MainActor
    func testNoConnectionShowsTheOfflinePageAndRetryHidesIt() {
        let web = WebController()
        let error = NSError(domain: NSURLErrorDomain, code: NSURLErrorNotConnectedToInternet,
                            userInfo: [NSURLErrorFailingURLErrorKey: Site.home])
        web.webView(web.webView, didFailProvisionalNavigation: nil, withError: error)
        XCTAssertTrue(web.offline)
        web.retry()
        XCTAssertFalse(web.offline)
    }

    @MainActor
    func testAStoppedLoadDoesNotShowTheOfflinePage() {
        let web = WebController()
        web.webView(web.webView, didFailProvisionalNavigation: nil, withError: NSError(domain: NSURLErrorDomain, code: NSURLErrorCancelled))
        XCTAssertFalse(web.offline)
    }
}

final class LookTests: XCTestCase {
    /// The off screen uses Android's fonts by these names; if one is missing iOS silently falls back to its own font.
    func testAndroidFontsAreInTheApp() {
        for name in ["Sora-Regular_SemiBold", "DMSans-9ptRegular_Regular", "DMSans-9ptRegular_SemiBold"] {
            XCTAssertNotNil(UIFont(name: name, size: 16), name)
        }
    }
}
