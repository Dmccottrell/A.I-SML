import Foundation
import UIKit

/// The rules for which website the app shows and what it may do there. Plain logic, so EmvryxTests can check it.
enum Site {
    static let host = "chat.emvryx.app"
    static let home = URL(string: "https://\(host)")!
    /// Added to the end of Safari's user agent so the website knows it runs in the iPhone app.
    static let userAgentTag = "EmvryxiOS/1.0"
    /// What WebKit puts at the end of an iPhone user agent by default, kept so the website still sees a phone.
    static let applicationName = "Mobile/15E148 \(userAgentTag)"
    static let background = UIColor(red: 0x07 / 255, green: 0x08 / 255, blue: 0x0D / 255, alpha: 1)

    /// Whether this address is the Emvryx website itself.
    static func isOurs(_ url: URL?) -> Bool {
        url?.scheme?.lowercased() == "https" && url?.host?.lowercased() == host
    }

    /// Whether a navigation should leave the app. [userTapped]: the person tapped a link; [newWindow]: the page asked for a new window.
    /// Other sites open in Safari only when the person asked for them, so sign-in redirects that come back to Emvryx stay inside the app.
    /// Addresses like mailto:, tel: and maps always go to their own app; WebKit's own kinds (about:, blob:, data:) stay inside.
    static func opensOutside(_ url: URL, userTapped: Bool, newWindow: Bool) -> Bool {
        let scheme = url.scheme?.lowercased() ?? ""
        if ["about", "blob", "data", "javascript"].contains(scheme) { return false }
        if scheme != "http" && scheme != "https" { return true }
        if isOurs(url) { return false }
        return userTapped || newWindow
    }

    /// The microphone (voice button) and camera are only for the Emvryx website, never for another site shown inside the app.
    static func mayUseMicAndCamera(scheme: String, host: String) -> Bool {
        scheme.lowercased() == "https" && host.lowercased() == Site.host
    }

    /// Whether a failed page load means there is no connection (show the "No connection" page) rather than something to ignore,
    /// like a load that was stopped because another one started.
    static func isNoConnection(_ error: Error) -> Bool {
        let e = error as NSError
        guard e.domain == NSURLErrorDomain else { return false }
        return [
            NSURLErrorNotConnectedToInternet, NSURLErrorNetworkConnectionLost, NSURLErrorTimedOut, NSURLErrorCannotFindHost,
            NSURLErrorCannotConnectToHost, NSURLErrorDNSLookupFailed, NSURLErrorInternationalRoamingOff, NSURLErrorDataNotAllowed,
            NSURLErrorSecureConnectionFailed,
        ].contains(e.code)
    }
}
