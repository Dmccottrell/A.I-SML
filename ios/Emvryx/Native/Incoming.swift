import AppIntents
import Foundation

/// Words that arrive from outside the app: Share to Emvryx (an `emvryx://ask?text=` link from the share extension) and the Siri Shortcut
/// "Ask Emvryx". The Android app's share target and assistant do the same (android/.../MainActivity.kt, assist/Asker.kt).
struct Incoming: Equatable {
    var text: String
    /// Send it at once (the Siri Shortcut: you spoke the question) or only put it in the message box (a link or a share: nothing is
    /// ever sent without a tap, so a web page that opens `emvryx://` cannot make the app send messages).
    var send: Bool

    /// `emvryx://ask?text=…`: the words go in the message box of a new chat.
    init?(url: URL) {
        guard let text = EmvryxLink.words(in: url) else { return nil }
        self.text = text
        send = false
    }

    init(text: String, send: Bool) { self.text = String(text.prefix(EmvryxLink.longest)); self.send = send }
}

/// Where the Shortcut hands its words to the screen that is showing (the Shortcut runs in the app's process).
@MainActor
final class IncomingBridge: ObservableObject {
    static let shared = IncomingBridge()
    @Published var pending: Incoming?
    /// A notification was tapped: this chat opens.
    @Published var openChat: Int64?
}

/// "Hey Siri, ask Emvryx": Siri asks for the question, opens Emvryx and sends it in a new chat.
struct AskEmvryxIntent: AppIntent {
    static var title: LocalizedStringResource = "Ask Emvryx"
    static var description = IntentDescription("Asks Emvryx a question in a new chat and shows the answer.")
    static var openAppWhenRun = true

    @Parameter(title: "Question", requestValueDialog: "What do you want to ask Emvryx?")
    var question: String

    @MainActor
    func perform() async throws -> some IntentResult {
        IncomingBridge.shared.pending = Incoming(text: question, send: true)
        return .result()
    }
}

/// The Shortcut shows up in the Shortcuts app and answers to Siri by name, with nothing to set up.
struct EmvryxShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(intent: AskEmvryxIntent(), phrases: ["Ask \(.applicationName)", "Ask \(.applicationName) a question"],
                    shortTitle: "Ask Emvryx", systemImageName: "bubble.left")
    }
}
