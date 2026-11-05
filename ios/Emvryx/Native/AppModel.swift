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
    /// One website page inside the native app, signed in: Settings, Admin, Connected apps ... [run] opens a panel once it loads.
    case page(path: String, title: String, run: String?)
    /// A screen of the app's own: memory, files, skills, settings, VryxCode.
    case memory, files, skills, settings, code
    /// "On this phone": the chats written here with the model on the phone (the PC is off, or you opened them).
    case local
}

enum SignInWay { case password, key, email }

/// One message on screen. [id] is local; [serverId] is the saved message's id (0 until the chat is read back). [streaming]: the reply is
/// still being written; [cut]: it stopped at a length limit or was stopped.
struct Bubble: Identifiable, Equatable {
    let id: Int
    var serverId: Int64 = 0
    var mine: Bool
    var text: String
    var streaming = false
    var cut = false
    var model = ""
    var docs: [DocInfo] = []
    var liked: String?
    var fb = ""
    var autoNote: String?
    var memory: String?
}

/// A reply that failed: what happened and what to do about it (send.js errorCard).
struct Failure: Equatable { var message: String; var action = "" }

/// The app's state and what it does, as android/.../ui/AppViewModel.kt: start-up, sign-in, the chat list, sending and the streamed reply.
@MainActor
final class AppModel: ObservableObject {
    let api: ApiClient
    /// The model on the phone (android_offline_model): its download, its chats and what is sent back when the PC returns.
    let phone: PhoneModel

    @Published var screen: Screen = .starting
    @Published private(set) var state: AppState?
    @Published private(set) var chats: [ChatSummary] = []
    @Published private(set) var usage: Usage?

    // The chat on screen.
    @Published private(set) var chatId: Int64?
    @Published private(set) var title = "New chat"
    @Published private(set) var isPrivate = false
    @Published private(set) var bubbles: [Bubble] = []
    @Published private(set) var streaming = false
    @Published private(set) var ctx: Ctx?
    /// "Loading Flare 3…", "Summarizing earlier messages…": shown while no words have come yet.
    @Published private(set) var working: String?
    @Published var failure: Failure?
    @Published var model = ""
    @Published var effort = "balanced"
    @Published var draft = ""
    @Published var research = false
    /// The light look instead of the dark one (the moon button; Android's toggleLight). Kept on the phone.
    @Published var light = UserDefaults.standard.bool(forKey: "emvryx_light") { didSet { UserDefaults.standard.set(light, forKey: "emvryx_light") } }

    // Pictures and files waiting to go with the next message.
    @Published private(set) var attached: [DocInfo] = []
    @Published private(set) var uploading = false

    // Search, sharing, archive, small messages.
    @Published private(set) var hits: [SearchHit]?
    @Published private(set) var shares: Shares?
    @Published private(set) var shareUrl: String?
    @Published private(set) var archivedChats: [ChatSummary]?
    @Published var toast: String?

    // Signing in.
    @Published var signInBusy = false
    @Published var signInError: String?
    @Published private(set) var twoStepTicket: String?
    @Published private(set) var emailSentTo: String?
    @Published private(set) var emailOffered = false

    /// Words that came from outside (Share to Emvryx, the Siri Shortcut), waiting for the chat to be on screen.
    private var incoming: Incoming?

    /// Whether the app is in front (the answer is on screen); tests say it is not. Alerts go to [alerts].
    var isActive: () -> Bool = { UIApplication.shared.applicationState == .active }
    var alerts: AlertSink = LocalAlerts.shared
    private var followTask: Task<Void, Never>?

    private var nextKey = 0
    private var replyTask: Task<Void, Never>?
    private var searchTask: Task<Void, Never>?

    init(api: ApiClient = ApiClient(), phone: PhoneModel? = nil) { self.api = api; self.phone = phone ?? PhoneModel(api: api) }

    var models: [ModelCard] { state?.models.all ?? [] }
    var currentModel: ModelCard? { models.first { $0.id == model } }
    var isAdmin: Bool { state?.admin == true || state?.owner == true }
    func flag(_ id: String) -> Bool { state?.on(id) == true }
    /// The current model's colours (and the violet look when it is switched on).
    var palette: Palette { Palette.forModel(currentModel?.name, violet: flag("violet_theme")) }
    var canResearch: Bool { flag("chat_research") && !isPrivate }

    /// A model may allow only some efforts (models.json "efforts"); Auto always.
    func effortAllowed(_ id: String) -> Bool { id == "auto" || (currentModel?.efforts.map { $0.contains(id) } ?? true) }
    func pickModel(_ id: String) {
        model = id
        if !effortAllowed(effort) { effort = "auto" }
        Task { await refreshChats() }                // usage is counted per model
    }
    var thinkingWord: String { state?.thinkingWords.first ?? "Thinking" }

    /// The next stronger model than [id], for "Ask <stronger model>" (the ready model with the higher version of the same family, else any higher one).
    func strongerModel(than id: String) -> ModelCard? {
        let order = ["flare", "equinox", "solstice", "apogee"]
        guard let me = models.first(where: { $0.id == id }), let rank = order.firstIndex(of: me.name.lowercased()) else { return nil }
        return models.filter { $0.ready && (order.firstIndex(of: $0.name.lowercased()) ?? -1) > rank && ($0.version ?? 0) >= (me.version ?? 0) }
            .min { (order.firstIndex(of: $0.name.lowercased()) ?? 0) < (order.firstIndex(of: $1.name.lowercased()) ?? 0) }
    }

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
                // With the model on the phone, the phone's chats open instead of "Emvryx is off".
                screen = phone.allowed && phone.ready ? .local : .off(resting: false)
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
        applyIncoming()
    }

    func signOut() {
        replyTask?.cancel()
        followTask?.cancel()
        Task {
            await api.signOut()
            state = nil; chats = []; bubbles = []; chatId = nil; title = "New chat"; attached = []; ctx = nil
            screen = .signIn
        }
    }

    private func loadState() async throws {
        let s = try await api.state(model: model.isEmpty ? nil : model)
        state = s
        chats = s.chats
        usage = s.usage
        if model.isEmpty || !models.contains(where: { $0.id == model && $0.ready }) { model = s.model }
        // The PC answered: remember whether the phone model is allowed, keep its instructions and memory fresh, send what was written on the
        // phone while the PC was off, and keep copies of the recent chats to read with the PC off.
        phone.rememberAllowed(s.on("android_offline_model"))
        if phone.allowed {
            Task {
                await phone.refresh()
                if await phone.syncUp() > 0 { await refreshChats() }
                await phone.keepRecent(s.chats)
            }
        }
    }

    func refreshChats() async {
        if let s = try? await api.state(model: model) { state = s; chats = s.chats; usage = s.usage }
    }

    // MARK: From outside the app

    /// Words from Share to Emvryx or the Siri Shortcut: they open a new chat (in the message box, or sent at once) as soon as the chat is showing.
    func receive(_ words: Incoming) {
        incoming = words
        applyIncoming()
    }

    func receive(_ url: URL) { if let i = Incoming(url: url) { receive(i) } }

    private func applyIncoming() {
        guard screen == .chat, !streaming, let i = incoming else { return }
        incoming = nil
        newChat()
        if i.send { send(i.text) } else { draft = i.text }
    }

    // MARK: Pages

    /// A website page inside the app (Settings, Admin, VryxCode, Memory ...), signed in.
    func open(_ path: String, _ title: String, run: String? = nil) { screen = .page(path: path, title: title, run: run) }
    func backToChat() {
        screen = .chat
        applyIncoming()
        Task { await refreshChats() }                // a page may have changed the model list, chats or usage
    }

    // MARK: The chat

    /// The skill the chat that is about to start uses (Skills > Start), shaping every answer.
    private var skill = ""

    func newChat(isPrivate: Bool = false, skill: String = "", skillName: String = "") {
        guard !streaming else { return }
        chatId = nil
        self.skill = skill
        title = isPrivate ? "Private chat" : (skillName.isEmpty ? "New chat" : skillName)
        self.isPrivate = isPrivate
        bubbles = []
        attached = []
        ctx = nil
        failure = nil
        toast = nil
    }

    func openChat(_ id: Int64) {
        guard !streaming else { return }
        failure = nil
        Task {
            do { show(try await api.chat(id)) } catch { handle(error) }
        }
    }

    /// Puts a whole chat on screen. What is attached to the chat but not yet in any message is waiting for the next one.
    private func show(_ c: Chat) {
        chatId = c.id
        title = c.title
        isPrivate = c.isPrivate || c.id < 0
        ctx = c.ctx
        let sent = Set(c.messages.flatMap { $0.docs.map(\.id) })
        attached = c.docs.filter { !sent.contains($0.id) }
        bubbles = c.messages.map { m in
            nextKey += 1
            return Bubble(id: nextKey, serverId: m.id, mine: m.role == "user", text: m.content, cut: m.cut, model: m.modelId, docs: m.docs, fb: m.fb)
        }
    }

    func send(_ text: String) {
        let words = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !streaming, !uploading, !words.isEmpty || !attached.isEmpty else { return }
        nextKey += 1
        bubbles.append(Bubble(id: nextKey, mine: true, text: words, docs: attached))
        attached = []
        draft = ""
        let deep = research && canResearch
        research = false
        reply(words, research: deep)
    }

    /// Writes the last reply again, with the model and effort picked now; [mode] is how it should differ (Regenerate options).
    func regenerate(_ mode: String? = nil) {
        guard !streaming, chatId != nil, let last = bubbles.last else { return }
        if !last.mine { bubbles.removeLast() }
        reply("", regenerate: true, mode: mode)
    }

    /// The answer stopped at its length limit: carry on from there.
    func continueReply() {
        guard !streaming, chatId != nil else { return }
        nextKey += 1
        bubbles.append(Bubble(id: nextKey, mine: true, text: "Continue"))
        reply("Continue", cont: true)
    }

    /// Asks the same thing again of a stronger model.
    func askStronger(_ m: ModelCard) {
        pickModel(m.id)
        regenerate()
    }

    /// Change what you asked: the answers after it are forgotten and it is asked again.
    func edit(_ b: Bubble, _ text: String) {
        guard let id = chatId, !streaming, b.serverId > 0, !text.isBlank else { return }
        Task {
            do {
                try await api.editMessage(id, b.serverId, text.trimmingCharacters(in: .whitespacesAndNewlines))
                show(try await api.chat(id))
                if bubbles.last?.mine == true { reply("", regenerate: true) }
            } catch { handle(error) }
        }
    }

    private func reply(_ words: String, regenerate: Bool = false, mode: String? = nil, cont: Bool = false, research: Bool = false) {
        failure = nil
        working = nil
        streaming = true
        nextKey += 1
        let key = nextKey
        bubbles.append(Bubble(id: key, mine: false, text: "", streaming: true, model: model))
        var got = false
        var finished = false
        var lost = false
        let background = BackgroundTime()
        background.begin()
        if flag("phone_alerts") && !isPrivate { Task { await alerts.prepare() } }
        replyTask = Task {
            defer {
                update(key) { $0.streaming = false }
                bubbles.removeAll { $0.id == key && $0.text.isEmpty }
                streaming = false
                working = nil
                background.end()
                if failure != nil && !got && !regenerate && !words.isBlank { draft = words }      // refused before a word: back in the box
                if lost, chatId != nil { follow() }                                                // cut off: the reply carries on at the PC, read it back
            }
            do {
                let id: Int64
                if let c = chatId { id = c } else { id = try await api.newChat(isPrivate: isPrivate, skill: skill); chatId = id; skill = "" }
                for try await ev in api.send(chatId: id, text: words, model: model, effort: effort, regenerate: regenerate, regenMode: mode,
                                             cont: cont, research: research) {
                    switch ev {
                    case let .thinking(e, auto): if auto { update(key) { $0.autoNote = "Auto chose " + e.prefix(1).uppercased() + e.dropFirst() } }
                    case let .loading(m): working = "Loading \(models.first { $0.id == m }?.fullName ?? "the model")…"
                    case .compacting: working = "Summarizing earlier messages to make room…"
                    case let .research(step, done, of): working = of > 0 ? "\(step) (\(done) of \(of))" : step
                    case let .memory(saved, forgot):
                        let bits = saved.map { $0.replacingOccurrences(of: "User ", with: "").trimmingCharacters(in: CharacterSet(charactersIn: ".")) }
                            + (forgot > 0 ? ["forgot \(forgot) " + (forgot == 1 ? "thing" : "things")] : [])
                        if !bits.isEmpty { update(key) { $0.memory = "📖 Memory updated: " + bits.joined(separator: "; ") } }
                    case let .piece(t):
                        working = nil
                        got = true
                        update(key) { $0.text += t }
                    case let .done(newTitle, _, cut, newUsage, context):
                        finished = true
                        if let t = newTitle { title = t }
                        if let u = newUsage { usage = u }
                        if let c = context { ctx = c }
                        update(key) { $0.cut = cut }
                        if !isActive() && flag("phone_alerts") && !isPrivate {                      // answered while the app was away
                            alerts.chatAnswered(id: id, title: title, text: bubbles.first { $0.id == key }?.text ?? "")
                        }
                    case let .failed(_, message, action): failure = Failure(message: message, action: action)
                    case .other: break
                    }
                }
                if !finished && failure == nil && got { lost = true }                           // the line ended without "done": iOS cut it, the reply goes on
                if !lost { await refreshChats(); await readBack() }
            } catch is CancellationError {
                await refreshChats()
                await readBack()
            } catch ApiError.offline where !got && phone.ready && flag("android_auto_offline") && !isPrivate && !words.isBlank && !regenerate && !cont {
                carryOnOnPhone(words)
            } catch ApiError.lost {
                lost = true                                                                     // the connection dropped mid-reply (the app was in the background)
            } catch {
                handle(error)
            }
        }
    }

    /// The app is in front again: a chat that was streaming when it went away is read again, in case its reply was cut off.
    func cameBack() {
        guard screen == .chat, streaming == false, let last = bubbles.last, !last.mine, last.text.isEmpty == false || last.streaming else { return }
        if last.streaming { follow() }
    }

    /// A reply that was cut off while it was being written (the app went to the background): the PC carries on writing it, so read the chat
    /// again until it is finished, showing what is written so far.
    func follow() {
        guard let id = chatId, id >= 0 else { return }
        followTask?.cancel()
        streaming = true
        followTask = Task {
            defer { streaming = false; working = nil }
            var misses = 0
            while !Task.isCancelled {
                guard let c = try? await api.chat(id), chatId == id else {
                    misses += 1
                    if misses > 40 { break }                                                    // about two minutes without an answer: give up quietly
                    try? await Task.sleep(nanoseconds: 3_000_000_000)
                    continue
                }
                misses = 0
                show(c)
                if c.generating, !bubbles.isEmpty { bubbles[bubbles.count - 1].streaming = true }
                if !c.generating {
                    if !isActive() && flag("phone_alerts") && !isPrivate, let last = c.messages.last(where: { $0.role == "assistant" }) {
                        alerts.chatAnswered(id: id, title: c.title, text: last.content)
                    }
                    break
                }
                try? await Task.sleep(nanoseconds: 1_000_000_000)
            }
            await refreshChats()
        }
    }

    /// The saved messages: their ids (edit, report, branch), and the memory ring. Only when the same messages are on screen.
    private func readBack() async {
        guard let id = chatId, id >= 0, let c = try? await api.chat(id), chatId == c.id else { return }
        if c.messages.count == bubbles.count {
            for (i, m) in c.messages.enumerated() { bubbles[i].serverId = m.id; bubbles[i].fb = m.fb }
        }
        if let cx = c.ctx { ctx = cx }
    }

    /// The PC dropped before a word came back: the chat carries on with the model on the phone, which answers the same question.
    private func carryOnOnPhone(_ question: String) {
        let earlier = bubbles.dropLast(2).filter { !$0.text.isBlank }.map { LocalTurn(mine: $0.mine, text: $0.text) }
        phone.carryOn(serverId: chatId, title: title, turns: Array(earlier), question: question)
        screen = .local
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

    // MARK: Chat actions

    func like(_ b: Bubble) {
        guard let id = chatId, b.serverId > 0 else { return }
        Task {
            do {
                let saved = try await api.like(id, b.serverId)
                update(b.id) { $0.liked = saved > 0 ? "Saved" : "Thanks" }
            } catch { handle(error) }
        }
    }

    func report(_ b: Bubble, kind: String, note: String) {
        guard let id = chatId, b.serverId > 0 else { return }
        Task {
            do { try await api.report(id, b.serverId, kind: kind, note: note); update(b.id) { $0.fb = kind } } catch { handle(error) }
        }
    }

    /// "Branch": copies the chat up to this message into a new chat and opens it.
    func branch(_ b: Bubble) {
        guard let id = chatId, b.serverId > 0 else { return }
        Task {
            do {
                let newId = try await api.branch(id, b.serverId)
                show(try await api.chat(newId))
                await refreshChats()
            } catch { handle(error) }
        }
    }

    func pin(_ c: ChatSummary) { Task { try? await api.pin(c.id, !c.pinned); await refreshChats() } }
    func archive(_ c: ChatSummary, _ on: Bool = true) {
        Task {
            try? await api.archive(c.id, on)
            if on && chatId == c.id { newChat() }
            await refreshChats()
            if archivedChats != nil { await loadArchived() }
        }
    }
    func archiveThis() { if let id = chatId { archive(ChatSummary(id: id, title: title)) } }
    func delete(_ c: ChatSummary) {
        Task {
            try? await api.deleteChat(c.id)
            if chatId == c.id { newChat() }
            await refreshChats()
        }
    }
    func deleteThis() { if let id = chatId { delete(ChatSummary(id: id, title: title)) } }

    func loadArchived() async { archivedChats = (try? await api.archived()) ?? [] }
    func closeArchived() { archivedChats = nil }

    /// Searches the words inside every chat on the server (titles are matched on the phone as you type).
    func search(_ q: String) {
        searchTask?.cancel()
        guard !q.isBlank else { hits = nil; return }
        searchTask = Task {
            try? await Task.sleep(nanoseconds: 300_000_000)                       // wait for a pause in typing
            guard !Task.isCancelled else { return }
            let found = (try? await api.search(q)) ?? []
            if !Task.isCancelled { hits = found }
        }
    }

    // MARK: Memory ring

    func compact() {
        guard let id = chatId else { return }
        Task {
            do {
                if let c = try await api.compact(id, model: model) { ctx = c }
                show(try await api.chat(id))
                toast = "Older messages were summarized."
            } catch { handle(error) }
        }
    }

    // MARK: Sharing and saving

    func loadShares() {
        shareUrl = nil
        Task { shares = (try? await api.shares()) ?? Shares() }
    }
    func closeShares() { shares = nil; shareUrl = nil }

    func makeShare(days: Int) {
        guard let id = chatId else { return }
        Task {
            do {
                let r = try await api.share(id, days: days)
                shareUrl = api.base.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + r.url
                shares?.shares = r.shares
            } catch { toast = describe(error) }
        }
    }
    func revokeShare(_ r: ShareRow) {
        Task {
            try? await api.revokeShare(r.id)
            shares = (try? await api.shares()) ?? shares
        }
    }

    /// Makes a PDF, Word or Markdown file of [text] on the server and returns where it was saved, ready to share.
    func saveAs(_ format: String, text: String) async -> URL? {
        do {
            let data = try await api.exportDoc(text: text, format: format, title: title)
            let safe = title.replacingOccurrences(of: "[^A-Za-z0-9 _-]", with: "", options: .regularExpression)
            let url = FileManager.default.temporaryDirectory.appendingPathComponent((safe.isBlank ? "Emvryx" : safe) + "." + format)
            try data.write(to: url)
            return url
        } catch { toast = describe(error); return nil }
    }

    // MARK: Pictures and files

    /// Uploads picked pictures and files and attaches them to the chat (making the chat first if there is none yet).
    func attach(_ files: [(name: String, data: Data)]) {
        guard !files.isEmpty, !streaming else { return }
        uploading = true
        Task {
            defer { uploading = false }
            do {
                let id: Int64
                if let c = chatId { id = c } else { id = try await api.newChat(isPrivate: isPrivate); chatId = id }
                var ids = attached.map(\.id)
                var skipped: [String] = []
                for f in files {
                    if f.data.count > 10_000_000 { skipped.append(f.name + " (over 10 MB)"); continue }
                    do { ids.append(try await api.upload(name: f.name, data: f.data).id) }
                    catch let e as ApiError { skipped.append(f.name + " (" + e.shortText + ")") }
                }
                attached = try await api.setChatDocs(id, ids)
                if !skipped.isEmpty { toast = (attached.isEmpty ? "Nothing was added. " : "") + "Skipped \(skipped.count): " + skipped.prefix(4).joined(separator: "; ") }
            } catch { handle(error) }
        }
    }

    func unattach(_ d: DocInfo) {
        let left = attached.filter { $0.id != d.id }
        attached = left
        guard let id = chatId else { return }
        Task { if let docs = try? await api.setChatDocs(id, left.map(\.id)) { attached = docs } }
    }

    // MARK: Errors

    func handle(_ error: Error) {
        if let e = error as? ApiError, e.signedOut { api.session.forget(); screen = .signIn; return }
        failure = Failure(message: describe(error))
    }

    func describe(_ error: Error) -> String { (error as? ApiError)?.text ?? "Something went wrong. Try again." }
}

extension ApiError {
    /// The server's reason without the "what to do" part, for a short list ("I couldn't find any text in that picture").
    var shortText: String {
        if case let .server(_, _, message, _) = self { return message.trimmingCharacters(in: CharacterSet(charactersIn: ".")) }
        return text
    }
}
