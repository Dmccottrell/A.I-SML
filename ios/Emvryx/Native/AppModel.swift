import Foundation
import SwiftUI

/// Which screen the app shows (android/.../ui/AppViewModel.kt Screen).
enum Screen: Equatable {
    case starting
    /// The server cannot be reached ([resting]: the PC is busy in Gaming mode).
    case off(resting: Bool)
    case signIn
    /// The native chat (feature flag ios_native).
    case chat
    /// The whole website inside the app, as version 1 (ios_native switched off).
    case website
    /// One website page inside the native app, signed in: Settings, Admin, VryxCode, Memory ... [run] opens a panel once it loads.
    case page(path: String, title: String, run: String?)
}

enum SignInWay { case password, key, email }

/// One message on screen. [streaming]: the reply is still being written; [cut]: it stopped at a length limit or was stopped.
struct Bubble: Identifiable, Equatable {
    let id: Int
    var mine: Bool
    var text: String
    var streaming = false
    var cut = false
    var model = ""
}

/// A reply that failed: what happened and what to do about it (send.js errorCard).
struct Failure: Equatable { var message: String; var action = "" }

/// The app's state and what it does, as android/.../ui/AppViewModel.kt: start-up, sign-in, the chat list, sending and the streamed reply.
@MainActor
final class AppModel: ObservableObject {
    let api: ApiClient

    @Published var screen: Screen = .starting
    @Published private(set) var state: AppState?
    @Published private(set) var chats: [ChatSummary] = []
    @Published private(set) var usage: Usage?

    // The chat on screen.
    @Published private(set) var chatId: Int64?
    @Published private(set) var title = "New chat"
    @Published private(set) var bubbles: [Bubble] = []
    @Published private(set) var streaming = false
    /// "Loading Flare 3…", "Summarizing earlier messages…": shown while no words have come yet.
    @Published private(set) var working: String?
    @Published var failure: Failure?
    @Published var model = ""
    @Published var effort = "balanced"
    @Published var draft = ""

    // Signing in.
    @Published var signInBusy = false
    @Published var signInError: String?
    @Published private(set) var twoStepTicket: String?
    @Published private(set) var emailSentTo: String?
    @Published private(set) var emailOffered = false

    private var nextKey = 0
    private var replyTask: Task<Void, Never>?

    init(api: ApiClient = ApiClient()) { self.api = api }

    var models: [ModelCard] { state?.models.all ?? [] }
    var currentModel: ModelCard? { models.first { $0.id == model } }
    var isAdmin: Bool { state?.admin == true || state?.owner == true }
    func flag(_ id: String) -> Bool { state?.on(id) == true }
    /// The current model's colours (and the violet look when it is switched on).
    var palette: Palette { Palette.forModel(currentModel?.name, violet: flag("violet_theme")) }
    /// A model may allow only some efforts (models.json "efforts"); Auto always.
    func effortAllowed(_ id: String) -> Bool { id == "auto" || (currentModel?.efforts.map { $0.contains(id) } ?? true) }
    func pickModel(_ id: String) {
        model = id
        if !effortAllowed(effort) { effort = "auto" }
        Task { await refreshChats() }                // usage is counted per model
    }
    var thinkingWord: String { state?.thinkingWords.first ?? "Thinking" }

    // MARK: Start-up and signing in

    func start() {
        screen = .starting
        Task {
            do {
                let status = try await api.status()
                if status.resting { screen = .off(resting: true); return }
                guard api.session.signedIn else { screen = .signIn; return }
                try await afterSignIn()
            } catch let e as ApiError where e.signedOut {
                api.session.forget()
                screen = .signIn
            } catch {
                screen = .off(resting: false)
            }
        }
    }

    func checkSignInOptions() {
        Task { emailOffered = (try? await api.authOptions())?.email ?? false }
    }

    func signIn(_ way: SignInWay, id: String, secret: String) {
        guard way != .email else { return }
        signInBusy = true
        signInError = nil
        Task {
            defer { signInBusy = false }
            do {
                let reply = way == .password ? try await api.signInWithPassword(id.trimmingCharacters(in: .whitespaces), secret)
                                             : try await api.signInWithKey(secret.trimmingCharacters(in: .whitespacesAndNewlines))
                if reply.mfa { twoStepTicket = reply.ticket } else { try await afterSignIn() }
            } catch {
                signInError = describe(error)
            }
        }
    }

    func submitTwoStep(_ code: String) {
        guard let ticket = twoStepTicket else { return }
        signInBusy = true
        signInError = nil
        Task {
            defer { signInBusy = false }
            do {
                _ = try await api.twoStep(ticket: ticket, code: code.trimmingCharacters(in: .whitespaces))
                twoStepTicket = nil
                try await afterSignIn()
            } catch { signInError = describe(error) }
        }
    }

    func cancelTwoStep() { twoStepTicket = nil; signInError = nil }

    func sendEmailCode(_ email: String) {
        signInBusy = true
        signInError = nil
        Task {
            defer { signInBusy = false }
            do {
                try await api.emailCode(email.trimmingCharacters(in: .whitespaces))
                emailSentTo = email.trimmingCharacters(in: .whitespaces)
            } catch { signInError = describe(error) }
        }
    }

    func signInWithEmailCode(_ code: String) {
        guard let email = emailSentTo else { return }
        signInBusy = true
        signInError = nil
        Task {
            defer { signInBusy = false }
            do {
                let reply = try await api.emailSignIn(email, code: code.trimmingCharacters(in: .whitespaces))
                if reply.mfa { twoStepTicket = reply.ticket } else { emailSentTo = nil; try await afterSignIn() }
            } catch { signInError = describe(error) }
        }
    }

    func cancelEmailCode() { emailSentTo = nil; signInError = nil }

    /// Signed in: read who you are and your chats, then the native chat (ios_native) or the website as before.
    private func afterSignIn() async throws {
        try await loadState()
        await api.session.shareWithWebPages()
        screen = flag("ios_native") ? .chat : .website
    }

    func signOut() {
        replyTask?.cancel()
        Task {
            await api.signOut()
            state = nil; chats = []; bubbles = []; chatId = nil; title = "New chat"
            screen = .signIn
        }
    }

    private func loadState() async throws {
        let s = try await api.state(model: model.isEmpty ? nil : model)
        state = s
        chats = s.chats
        usage = s.usage
        if model.isEmpty || !models.contains(where: { $0.id == model && $0.ready }) { model = s.model }
    }

    private func refreshChats() async {
        if let s = try? await api.state(model: model) { state = s; chats = s.chats; usage = s.usage }
    }

    // MARK: Pages

    /// A website page inside the app (Settings, Admin, VryxCode, Memory ...), signed in.
    func open(_ path: String, _ title: String, run: String? = nil) { screen = .page(path: path, title: title, run: run) }
    func backToChat() {
        screen = .chat
        Task { await refreshChats() }                // a page may have changed the model list, chats or usage
    }

    // MARK: The chat

    func newChat() {
        guard !streaming else { return }
        chatId = nil
        title = "New chat"
        bubbles = []
        failure = nil
    }

    func openChat(_ id: Int64) {
        guard !streaming else { return }
        failure = nil
        Task {
            do {
                let c = try await api.chat(id)
                show(c)
            } catch { handle(error) }
        }
    }

    private func show(_ c: Chat) {
        chatId = c.id
        title = c.title
        bubbles = c.messages.map { m in
            nextKey += 1
            return Bubble(id: nextKey, mine: m.role == "user", text: m.content, cut: m.cut, model: m.modelId)
        }
    }

    func send(_ text: String) {
        let words = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !words.isEmpty, !streaming else { return }
        nextKey += 1
        bubbles.append(Bubble(id: nextKey, mine: true, text: words))
        draft = ""
        reply(words)
    }

    private func reply(_ words: String) {
        failure = nil
        working = nil
        streaming = true
        nextKey += 1
        let key = nextKey
        bubbles.append(Bubble(id: key, mine: false, text: "", streaming: true, model: model))
        var got = false
        replyTask = Task {
            defer {
                update(key) { $0.streaming = false }
                bubbles.removeAll { $0.id == key && $0.text.isEmpty }
                streaming = false
                working = nil
                if failure != nil && !got { draft = words }      // refused before a word: the message goes back in the box
            }
            do {
                let id: Int64
                if let c = chatId { id = c } else { id = try await api.newChat(); chatId = id }
                for try await ev in api.send(chatId: id, text: words, model: model, effort: effort) {
                    switch ev {
                    case let .loading(m): working = "Loading \(models.first { $0.id == m }?.fullName ?? "the model")…"
                    case .compacting: working = "Summarizing earlier messages to make room…"
                    case let .research(step, done, of): working = of > 0 ? "\(step) (\(done) of \(of))" : step
                    case let .piece(t):
                        working = nil
                        got = true
                        update(key) { $0.text += t }
                    case let .done(newTitle, _, cut, newUsage):
                        if let t = newTitle { title = t }
                        if let u = newUsage { usage = u }
                        update(key) { $0.cut = cut }
                    case let .failed(_, message, action): failure = Failure(message: message, action: action)
                    case .thinking, .memory, .other: break
                    }
                }
                await refreshChats()
            } catch is CancellationError {
                await refreshChats()
            } catch {
                handle(error)
            }
        }
    }

    /// Stops the reply: the server stops writing and what was written so far is kept.
    func stop() {
        guard let id = chatId else { replyTask?.cancel(); return }
        Task {
            await api.stop(id)
            replyTask?.cancel()
        }
    }

    private func update(_ key: Int, _ change: (inout Bubble) -> Void) {
        if let i = bubbles.firstIndex(where: { $0.id == key }) { change(&bubbles[i]) }
    }

    private func handle(_ error: Error) {
        if let e = error as? ApiError, e.signedOut { api.session.forget(); screen = .signIn; return }
        failure = Failure(message: describe(error))
    }

    private func describe(_ error: Error) -> String { (error as? ApiError)?.text ?? "Something went wrong. Try again." }
}
