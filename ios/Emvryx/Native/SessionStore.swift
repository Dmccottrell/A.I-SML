import Foundation
import Security
import WebKit

/// The sign-in session, kept in the iPhone's Keychain (encrypted, readable only by this app), as android/.../data/SessionStore.kt keeps it
/// encrypted on Android. It is the website's own session cookie (emvryx_session), so signing out on the website's Devices list signs
/// this phone out too, and the website pages inside the app open signed in.
final class SessionStore {
    static let cookieName = "emvryx_session"
    private let account: String

    /// One session per server address (a debug build may talk to a test server).
    init(server: URL = Site.home) { account = "session:" + (server.host ?? "") + ":" + String(server.port ?? 0) }

    /// The saved cookie, or nil when there is none or it has run out.
    var cookie: HTTPCookie? {
        guard let data = read(), let props = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        var p: [HTTPCookiePropertyKey: Any] = [:]
        for (k, v) in props { p[HTTPCookiePropertyKey(k)] = k == HTTPCookiePropertyKey.expires.rawValue ? Date(timeIntervalSince1970: v as? Double ?? 0) : v }
        guard let c = HTTPCookie(properties: p) else { return nil }
        if let e = c.expiresDate, e < Date() { return nil }
        return c
    }

    var signedIn: Bool { cookie != nil }

    /// Keeps a session cookie the server sent; an empty or run-out one is how it says "signed out".
    func save(_ c: HTTPCookie) {
        guard c.name == Self.cookieName else { return }
        if c.value.isEmpty || (c.expiresDate.map { $0 < Date() } ?? false) { return forget() }
        var props: [String: Any] = [:]
        for (k, v) in c.properties ?? [:] { props[k.rawValue] = (v as? Date).map { $0.timeIntervalSince1970 } ?? "\(v)" }
        if let data = try? JSONSerialization.data(withJSONObject: props) { write(data) }
    }

    /// Signs out on the phone: deletes the cookie, here and in the website pages.
    func forget() {
        SecItemDelete(query() as CFDictionary)
        Self.memoryLock.lock(); Self.memory[account] = nil; Self.memoryLock.unlock()
        Task { @MainActor in                                       // WebKit's stores are used on the main thread only
            let store = WKWebsiteDataStore.default().httpCookieStore
            store.getAllCookies { all in all.filter { $0.name == Self.cookieName }.forEach { store.delete($0) } }
        }
    }

    /// Gives the website pages inside the app the same session, so they open signed in.
    @MainActor
    func shareWithWebPages() async {
        guard let c = cookie else { return }
        await WKWebsiteDataStore.default().httpCookieStore.setCookie(c)
    }

    // MARK: Keychain

    private func query() -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "app.emvryx.ios", kSecAttrAccount as String: account]
    }

    /// Where the cookie waits when the Keychain refuses it (a simulator without Keychain access, as on GitHub's Macs): only until the app closes.
    private static var memory: [String: Data] = [:]
    private static let memoryLock = NSLock()

    private func read() -> Data? {
        if let d = readKeychain() { return d }
        Self.memoryLock.lock(); defer { Self.memoryLock.unlock() }
        return Self.memory[account]
    }

    private func readKeychain() -> Data? {
        var q = query()
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: CFTypeRef?
        return SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess ? out as? Data : nil
    }

    private func write(_ data: Data) {
        SecItemDelete(query() as CFDictionary)
        var q = query()
        q[kSecValueData as String] = data
        q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly     // never copied to another phone or a backup
        let kept = SecItemAdd(q as CFDictionary, nil) == errSecSuccess
        Self.memoryLock.lock(); defer { Self.memoryLock.unlock() }
        Self.memory[account] = kept ? nil : data
    }
}
