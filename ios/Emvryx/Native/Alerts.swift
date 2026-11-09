import UIKit
import UserNotifications

/// Tells the person a chat answer is ready when the app is not in front (the website's and Android's phone_alerts). These are the phone's own
/// notifications, made by the app itself, which needs no paid Apple account. What an iPhone does not allow without one: a message from the server
/// to a closed app (push), so an answer that takes longer than the little time iOS gives a closed app is shown when you open the app again.
protocol AlertSink {
    /// Asks for permission the first time (iOS shows its own question once).
    func prepare() async
    func chatAnswered(id: Int64, title: String, text: String)
}

final class LocalAlerts: NSObject, AlertSink, UNUserNotificationCenterDelegate {
    static let shared = LocalAlerts()
    private let asked = "emvryx_alerts_asked"

    func setUp() { UNUserNotificationCenter.current().delegate = self }

    func prepare() async {
        guard !UserDefaults.standard.bool(forKey: asked) else { return }
        UserDefaults.standard.set(true, forKey: asked)
        _ = try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound])
    }

    func chatAnswered(id: Int64, title: String, text: String) {
        let content = UNMutableNotificationContent()
        content.title = title.isEmpty ? "Emvryx" : title
        content.body = Self.snippet(text)
        content.sound = .default
        content.userInfo = ["chat": id]
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: "chat-\(id)", content: content, trigger: nil))
    }

    /// The first part of the answer, on one line.
    static func snippet(_ text: String) -> String {
        let one = text.replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression).trimmingCharacters(in: .whitespaces)
        return one.count > 140 ? String(one.prefix(140)) + "…" : one
    }

    // Nothing is shown while the app is in front (the answer is already on screen); a tap on one opens that chat.
    func userNotificationCenter(_ c: UNUserNotificationCenter, willPresent n: UNNotification, withCompletionHandler done: @escaping (UNNotificationPresentationOptions) -> Void) { done([]) }

    func userNotificationCenter(_ c: UNUserNotificationCenter, didReceive r: UNNotificationResponse, withCompletionHandler done: @escaping () -> Void) {
        if let id = r.notification.request.content.userInfo["chat"] as? Int64 ?? (r.notification.request.content.userInfo["chat"] as? Int).map(Int64.init) {
            Task { @MainActor in IncomingBridge.shared.openChat = id }
        }
        done()
    }
}

/// Asks iOS for a little more time to finish a reply when the app goes to the background (about half a minute, sometimes more). A longer reply
/// carries on on the server and is read back when the app is opened again.
@MainActor
final class BackgroundTime {
    private var id = UIBackgroundTaskIdentifier.invalid
    func begin() {
        guard id == .invalid else { return }
        id = UIApplication.shared.beginBackgroundTask(withName: "reply") { [weak self] in self?.end() }
    }
    func end() {
        guard id != .invalid else { return }
        UIApplication.shared.endBackgroundTask(id)
        id = .invalid
    }
}
