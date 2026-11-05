import CryptoKit
import Foundation

/// android_offline_model: your small Flare model on the phone (android/.../local/PhoneModel.kt). It is downloaded from your PC once (and carries on
/// where it stopped), checked against the PC's checksum, and then answers chats here when the PC is off. Your instructions and what Emvryx
/// remembers come with it and are refreshed whenever the PC answers. The chats written here stay on the phone until the PC is back.
@MainActor
final class PhoneModel: ObservableObject {
    enum Status: Equatable {
        case none
        case downloading(done: Int64, total: Int64)
        case checking
        case ready
        case failed(String)
    }

    private let api: ApiClient
    private let defaults: UserDefaults
    private let dir: URL
    private let modelFile: URL, partFile: URL, kitFile: URL, chatsFile: URL
    var engine: LocalEngine

    /// The switch as it was the last time the PC answered (offline, it cannot be asked).
    @Published private(set) var allowed: Bool
    @Published private(set) var kit: PhoneKit?
    @Published private(set) var status: Status = .none
    /// A newer model is on the PC than the one on this phone (Settings offers to download it).
    @Published private(set) var newer: PhoneKit?
    @Published private(set) var choices: [PhoneChoice] = []
    @Published private(set) var wanted: String?
    @Published private(set) var chats: [LocalChat] = []
    @Published private(set) var writing = false
    /// The chat the phone's chat screen opens next, and a question to answer there at once (the PC dropped while it was being sent).
    @Published var openChat: Int64?
    @Published var ask: String?
    /// Words for the phone chat's message box (shared from another app with the PC off).
    @Published var draft: String?

    private var downloadTask: Task<Void, Never>?
    private let maxChats = 50
    private let keepRecentCount = 10
    private var stopping = false
    private var loadedId = ""

    /// [directory]: where the model and the chats are kept (the app's own folder; tests pass their own).
    init(api: ApiClient, directory: URL? = nil, defaults: UserDefaults = .standard, engine: LocalEngine? = nil) {
        self.api = api
        self.defaults = defaults
        self.engine = engine ?? PhoneModel.defaultEngine()
        let base = directory ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("phone-model", isDirectory: true)
        dir = base
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        var values = URLResourceValues(); values.isExcludedFromBackup = true          // 2 GB must not go into the iCloud backup
        var d = dir; try? d.setResourceValues(values)
        modelFile = dir.appendingPathComponent("model.gguf"); partFile = dir.appendingPathComponent("model.gguf.part")
        kitFile = dir.appendingPathComponent("kit.json"); chatsFile = dir.appendingPathComponent("chats.json")
        allowed = defaults.bool(forKey: "emvryx_phone_allowed")
        wanted = defaults.string(forKey: "emvryx_phone_wanted")
        kit = (try? Data(contentsOf: kitFile)).flatMap { try? JSONDecoder().decode(PhoneKit.self, from: $0) }
        chats = (try? Data(contentsOf: chatsFile)).flatMap { try? JSONDecoder().decode([LocalChat].self, from: $0) } ?? []
        status = FileManager.default.fileExists(atPath: modelFile.path) && kit != nil ? .ready : .none
    }

    /// The llama.cpp engine when it is built into the app, a stand-in when a test asks for one (EMVRYX_FAKE_ENGINE, debug builds), otherwise none.
    static func defaultEngine() -> LocalEngine {
        #if DEBUG
        if ProcessInfo.processInfo.environment["EMVRYX_FAKE_ENGINE"] == "1" { return ScriptedEngine() }
        #endif
        #if canImport(llama)
        return LlamaEngine()
        #else
        return NoEngine()
        #endif
    }

    var ready: Bool { status == .ready && kit != nil }
    var canRun: Bool { engine.canRun }

    func rememberAllowed(_ on: Bool) { allowed = on; defaults.set(on, forKey: "emvryx_phone_allowed") }

    // MARK: Keeping up with the PC

    /// The PC answered: keep the newest instructions, memory and format (the model file itself only changes with Download).
    func refresh() async {
        guard allowed, let k = try? await api.phoneKit(kit?.id ?? wanted) else { return }
        choices = k.choices
        guard k.available, let have = kit else { return }
        if have.id != k.id || (k.sha256 != nil && k.sha256 != have.sha256) { newer = k; return }
        var fresh = k
        fresh.sha256 = have.sha256; fresh.size = have.size
        kit = fresh
        try? JSONEncoder().encode(fresh).write(to: kitFile)
    }

    func loadChoices() async {
        guard allowed, choices.isEmpty, let k = try? await api.phoneKit(kit?.id ?? wanted) else { return }
        choices = k.choices
    }

    func pick(_ id: String) { wanted = id; defaults.set(id, forKey: "emvryx_phone_wanted") }

    func enoughRam(_ gb: Double) -> Bool { Double(ProcessInfo.processInfo.physicalMemory) >= gb * 0.9 * 1_073_741_824 }

    func freeSpace() -> Int64 {
        (try? dir.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey]).volumeAvailableCapacityForImportantUsage) ?? 0
    }

    // MARK: Download

    /// Downloads the model from the PC, carrying on from what is already here, then checks it. Keep the app open while it runs: it carries on
    /// where it stopped the next time.
    func download() {
        guard downloadTask == nil else { return }
        downloadTask = Task {
            defer { downloadTask = nil }
            do { try await runDownload() }
            catch is CancellationError { status = ready ? .ready : .none }
            catch let e as ApiError { status = .failed(e == .offline ? "The PC could not be reached. Try again when it is on: the download carries on where it stopped." : e.text) }
            catch { status = .failed((error as? LocalEngineError)?.message ?? error.localizedDescription) }
        }
    }

    private func runDownload() async throws {
        var k = try await api.phoneKit(wanted)
        choices = k.choices
        guard k.available else { status = .failed(k.message.isEmpty ? "The PC has no model for phones." : k.message); return }
        while k.sha256 == nil {                                          // the PC works out the checksum the first time (a few seconds)
            status = .checking
            try await Task.sleep(nanoseconds: 3_000_000_000)
            k = try await api.phoneKit(wanted)
        }
        guard engine.canRun else { status = .failed("This build of the app has no model engine inside (see ios/README.md: the model on the phone)."); return }
        guard enoughRam(k.minRamGb) else { status = .failed("This phone has less memory than the model needs (\(Int(k.minRamGb)) GB)."); return }
        let fm = FileManager.default
        var have = (try? fm.attributesOfItem(atPath: partFile.path)[.size] as? Int64) ?? 0
        if freeSpace() < k.size - have + 200 * 1024 * 1024 {
            status = .failed("Not enough free space: about \((k.size + (1 << 29)) / (1 << 30)) GB is needed.")
            return
        }
        if have > k.size || defaults.string(forKey: "emvryx_phone_part_sha") != k.sha256 { try? fm.removeItem(at: partFile); have = 0 }     // a part of another model
        defaults.set(k.sha256, forKey: "emvryx_phone_part_sha")
        status = .downloading(done: have, total: k.size)
        if have < k.size {
            if !fm.fileExists(atPath: partFile.path) { fm.createFile(atPath: partFile.path, contents: nil) }
            let total = k.size
            try await api.download(path: k.file, to: partFile, from: have) { [weak self] done in
                Task { @MainActor in self?.status = .downloading(done: done, total: total) }
            }
        }
        try Task.checkCancellation()
        let size = (try? fm.attributesOfItem(atPath: partFile.path)[.size] as? Int64) ?? 0
        guard size == k.size else { throw LocalEngineError(message: "The download stopped early. Try again: it carries on where it was.") }
        status = .checking
        let sum = try await Task.detached { try PhoneModel.sha256(of: self.partFile) }.value
        guard sum == k.sha256 else {
            try? fm.removeItem(at: partFile)
            status = .failed("The download arrived damaged and was removed. Please download it again.")
            return
        }
        close()
        try? fm.removeItem(at: modelFile)
        try fm.moveItem(at: partFile, to: modelFile)
        try JSONEncoder().encode(k).write(to: kitFile)
        kit = k
        newer = nil
        status = .ready
    }

    nonisolated static func sha256(of file: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: file)
        defer { try? handle.close() }
        var hasher = SHA256()
        while let chunk = try handle.read(upToCount: 1 << 20), !chunk.isEmpty { hasher.update(data: chunk) }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }

    func cancel() {
        downloadTask?.cancel()
        status = ready ? .ready : .none
    }

    /// Removes the model from the phone (the chats written here stay).
    func remove() {
        cancel()
        close()
        try? FileManager.default.removeItem(at: modelFile)
        try? FileManager.default.removeItem(at: partFile)
        try? FileManager.default.removeItem(at: kitFile)
        kit = nil
        status = .none
    }

    func close() { engine.close(); loadedId = "" }

    // MARK: The phone's chats

    private func saveChats() {
        chats = LocalSync.keep(chats, max: maxChats)
        try? JSONEncoder().encode(chats).write(to: chatsFile)
    }

    @discardableResult
    func newChat() -> LocalChat {
        let now = Int64(Date().timeIntervalSince1970 * 1000)
        let c = LocalChat(id: now, title: "New chat", turns: [], updated: now)
        chats.append(c)
        saveChats()
        return c
    }

    func deleteChat(_ id: Int64) { chats.removeAll { $0.id == id }; saveChats() }

    /// A copy of one of the PC's chats, to read and carry on here; returns the phone's id for it.
    @discardableResult
    func keepCopy(_ c: Chat) -> Int64 {
        let turns = c.messages.filter { ($0.role == "user" || $0.role == "assistant") && !$0.content.isBlank }.map { LocalTurn(mine: $0.role == "user", text: $0.content) }
        let i = chats.firstIndex { $0.serverId == c.id }
        let merged = LocalSync.merge(i.map { chats[$0] }, serverId: c.id, title: c.title, serverTurns: turns, now: Int64(Date().timeIntervalSince1970 * 1000))
        if let i { chats[i] = merged } else { chats.append(merged) }
        saveChats()
        return merged.id
    }

    /// The PC is there: copies of the most recent chats (at most every 10 minutes, unless [force]).
    func keepRecent(_ list: [ChatSummary], force: Bool = false) async {
        guard allowed else { return }
        let now = Date().timeIntervalSince1970
        if !force && now - defaults.double(forKey: "emvryx_phone_kept_at") < 600 { return }
        defaults.set(now, forKey: "emvryx_phone_kept_at")
        for s in list.filter({ $0.id >= 0 }).prefix(keepRecentCount) {
            guard let c = try? await api.chat(s.id) else { break }          // the PC went away: stop, try again next time
            keepCopy(c)
        }
    }

    /// Sends what was written on the phone to the PC. Returns how many chats were sent.
    @discardableResult
    func syncUp() async -> Int {
        guard allowed, !writing else { return 0 }
        var sent = 0
        for c in chats.filter({ !$0.pending.isEmpty }) {
            var body: [String: Any] = ["sync_id": LocalSync.syncId(c), "title": c.title, "model": kit?.id ?? "phone",
                                       "messages": c.pending.map { ["role": $0.mine ? "user" : "assistant", "content": $0.text] }]
            if let s = c.serverId { body["chat"] = s }
            guard let id = try? await api.phoneSync(body) else { break }
            if let j = chats.firstIndex(where: { $0.id == c.id }) { chats[j].serverId = id; chats[j].synced = c.turns.count }
            saveChats()
            sent += 1
        }
        return sent
    }

    /// Carries a chat on here: the PC's chat [serverId] with the [turns] it has (or a new chat), then [question] is answered on the phone.
    func carryOn(serverId: Int64?, title: String, turns: [LocalTurn], question: String) {
        if let s = serverId, s >= 0 {
            let i = chats.firstIndex { $0.serverId == s }
            let merged = LocalSync.merge(i.map { chats[$0] }, serverId: s, title: title, serverTurns: turns, now: Int64(Date().timeIntervalSince1970 * 1000))
            if let i { chats[i] = merged } else { chats.append(merged) }
            saveChats()
            openChat = merged.id
        } else {
            openChat = newChat().id
        }
        ask = question
    }

    // MARK: Answering

    func stop() { stopping = true; engine.stop() }

    /// Answers [question] in chat [chatId], calling [onText] with the answer so far. Returns nil when it went well, else what went wrong.
    func answer(chatId: Int64, question: String, onText: @escaping (String) -> Void) async -> String? {
        guard let k = kit else { return "The model is not on this phone yet." }
        guard let i = chats.firstIndex(where: { $0.id == chatId }) else { return "That chat is gone." }
        let history = chats[i].turns
        chats[i].turns = history + [LocalTurn(mine: true, text: question), LocalTurn(mine: false, text: "")]
        if history.isEmpty { chats[i].title = String(question.prefix(48)) }
        chats[i].updated = Int64(Date().timeIntervalSince1970 * 1000)
        writing = true
        stopping = false
        defer { writing = false }
        let engine = self.engine, path = modelFile.path, needsLoad = loadedId != k.id
        let result: Result<(String, LocalEnd), LocalEngineError> = await Task.detached(priority: .userInitiated) {
            do {
                if needsLoad { try engine.load(path: path, context: k.context) }
                let prompt = LocalPrompt.build(k, history, question) { engine.count($0) }
                var joiner = Utf8Joiner()
                var lastShown = Date.distantPast
                let end = engine.generate(prompt: prompt, maxTokens: k.maxReplyTokens, sampling: k.sampling) { bytes in
                    joiner.add(bytes)
                    let (text, done) = LocalPrompt.shown(joiner.text, k.format.stop)
                    if Date().timeIntervalSince(lastShown) > 0.05 { lastShown = Date(); DispatchQueue.main.async { onText(text) } }
                    return !done
                }
                return .success((LocalPrompt.shown(joiner.text, k.format.stop).text.trimmingCharacters(in: .whitespacesAndNewlines), end))
            } catch let e as LocalEngineError { return .failure(e) } catch { return .failure(LocalEngineError(message: "The phone's model stopped. Please try again.")) }
        }.value
        switch result {
        case let .failure(e):
            if let j = chats.firstIndex(where: { $0.id == chatId }) { chats[j].turns = history }                        // nothing was written
            saveChats()
            return e.message
        case let .success((shown, end)):
            loadedId = k.id
            if let j = chats.firstIndex(where: { $0.id == chatId }) { chats[j].turns = history + [LocalTurn(mine: true, text: question), LocalTurn(mine: false, text: shown.isEmpty ? "…" : shown)] }
            saveChats()
            onText(shown)
            switch end {
            case .tooLong: return "That message is too long for the phone's model."
            case .failed: return "The phone's model stopped. Please try again."
            case .done: return nil
            }
        }
    }
}
