import LocalAuthentication
import SwiftUI

/// The app lock (android/.../ui/ChatMore.kt LockScreen): Face ID (or the passcode) when the app opens and when you come back to it.
/// It is only a lock on the screen: the sign-in stays in the Keychain. Switched on and off in the account menu.
@MainActor
final class AppLock: ObservableObject {
    static let shared = AppLock()
    private let key = "emvryx_app_lock"

    @Published private(set) var enabled: Bool
    @Published private(set) var locked: Bool
    @Published private(set) var problem: String?

    init() {
        #if DEBUG
        // UI tests start without the lock (EMVRYX_APP_LOCK=reset); debug builds started by hand keep what was chosen.
        if ProcessInfo.processInfo.environment["EMVRYX_APP_LOCK"] == "reset" { UserDefaults.standard.removeObject(forKey: key) }
        #endif
        let on = UserDefaults.standard.bool(forKey: key)
        enabled = on
        locked = on
    }

    func toggle() {
        enabled.toggle()
        UserDefaults.standard.set(enabled, forKey: key)
        UserDefaults.standard.synchronize()                        // written now, in case the app is closed straight away
        locked = false
        problem = nil
    }

    /// Called when the app goes to the background: it asks again next time.
    func lockNow() { if enabled { locked = true } }

    /// Asks Face ID (or the passcode when Face ID is not set up). Unlocks on success.
    func unlock() async {
        guard locked else { return }
        let context = LAContext()
        var error: NSError?
        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else {
            // No Face ID and no passcode on this phone: nothing to ask, so the lock cannot protect anything; let the person in.
            locked = false
            return
        }
        do {
            if try await context.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: "Unlock Emvryx") { locked = false; problem = nil }
        } catch {
            problem = "Not unlocked. Try again."
        }
    }
}

/// Shown over everything while the app is locked.
struct LockScreen: View {
    @ObservedObject var lock: AppLock
    var body: some View {
        ZStack {
            Emvryx.bg.ignoresSafeArea()
            AccentWash(glow: Emvryx.glow, height: 420).ignoresSafeArea()
            VStack(spacing: 14) {
                Logo().frame(width: 64, height: 64)
                Text("Emvryx is locked").font(Emvryx.heading(26)).foregroundStyle(Emvryx.text)
                Text("Unlock it with Face ID or your passcode.").font(Emvryx.body(16)).foregroundStyle(Emvryx.muted).multilineTextAlignment(.center)
                if let p = lock.problem { Text(p).font(Emvryx.body(15)).foregroundStyle(Emvryx.danger) }
                PwaButton(text: "Unlock") { Task { await lock.unlock() } }.padding(.top, 6)
            }
            .frame(maxWidth: 420).padding(28)
        }
    }
}
