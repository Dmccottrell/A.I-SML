import Foundation
import SwiftUI

/// A short folder-style project name from what was typed ("A bill splitter with tip and people" becomes "bill-splitter"), as
/// android/.../ui/CodeProjects.kt ideaName does, so each new idea gets its own readable project folder.
func ideaName(_ text: String) -> String {
    let lead = try! NSRegularExpression(pattern: #"^(please\s+)?((can|could) you\s+)?((make|build|create|write|code|give)( me)?\s+)?((a|an|the|my|me)\s+)?"#)
    let lower = text.lowercased()
    var t = lower
    if let m = lead.firstMatch(in: lower, range: NSRange(lower.startIndex..., in: lower)), let r = Range(m.range, in: lower) { t = String(lower[r.upperBound...]) }
    let cut = try! NSRegularExpression(pattern: #"\s(?:with|that|which|where|for|using|in|so|to)\s|[,.;:!?()]"#)
    if let m = cut.firstMatch(in: t, range: NSRange(t.startIndex..., in: t)), let r = Range(m.range, in: t) { t = String(t[..<r.lowerBound]) }
    let cleaned = t.replacingOccurrences(of: #"[^a-z0-9\s-]"#, with: " ", options: .regularExpression)
    let words = cleaned.split(whereSeparator: { $0.isWhitespace }).prefix(4).map(String.init)
    var name = String(words.joined(separator: "-").prefix(32))
    while name.hasSuffix("-") { name.removeLast() }
    return name.isEmpty ? "new-project" : name
}

/// A project name that is not taken yet: [base], else base-2, base-3 ...
func freeName(_ base: String, _ have: [String]) -> String {
    var n = base, i = 2
    while have.contains(n) { n = "\(base)-\(i)"; i += 1 }
    return n
}

/// What the VryxCode screens show and do (android/.../ui/CodeViewModel.kt): the sessions, the open session's live feed, and sending.
@MainActor
final class CodeStore: ObservableObject {
    let api: ApiClient
    private let onSignedOut: () -> Void

    @Published private(set) var info: CodeInfo?
    @Published private(set) var sessions: [CodeSessionRow] = []
    @Published private(set) var archived: [CodeSessionRow] = []
    @Published private(set) var templates: [CodeTemplate] = []
    @Published private(set) var loaded = false
    @Published var error: String?

    // The open session (nil sid: the sessions list).
    @Published private(set) var sid: String?
    @Published private(set) var events: [CodeEvent] = []
    @Published private(set) var state = ""
    @Published private(set) var pending: CodeEvent?
    @Published private(set) var full = false
    @Published private(set) var usage: CodeUsage?
    @Published private(set) var stopping = false
    @Published private(set) var title = ""

    // What the next message uses.
    @Published var mode = "ask"                 // ask before editing, edit without asking, or plan first
    @Published var model = ""
    @Published var effort = "balanced"
    @Published var env = "local"
    @Published var project = ""
    /// A starter picked on the home: the server writes its files first.
    @Published var template: String?

    // The newer parts (flag ios_vryxcode, and each part's own VryxCode flag): which of them are on, set by the screen from the server's switches.
    @Published private(set) var parity: Set<String> = []
    /// Pictures (data: addresses) and documents sent with the next message.
    @Published private(set) var pictures: [String] = []
    @Published private(set) var docs: [DocInfo] = []
    /// What the project's saved /commands are, the notes VryxCode remembers and the project's rules (nil while their sheets are closed).
    @Published private(set) var commands: [CodeCommand] = []
    @Published var memory: [String]?
    @Published var rules: CodeRules?
    /// A suggested next message after a turn ends (flag vryxcode_suggest); empty when there is none.
    @Published var offer = ""
    /// When you last opened each session (its "updated" time then), so "Ready for review" knows what is new.
    @Published private(set) var reviewed: [String: Double]
    var suggestOn = true

    private var seen = 0
    private var nextId = 0
    private var poller: Task<Void, Never>?
    private static let reviewedKey = "emvryx_code_reviewed"
    static let partFlags = ["vryxcode_restore", "vryxcode_taskbox", "vryxcode_autocontinue", "vryxcode_guardrails", "vryxcode_lines", "vryxcode_review"]

    init(api: ApiClient, onSignedOut: @escaping () -> Void) {
        self.api = api; self.onSignedOut = onSignedOut
        reviewed = (UserDefaults.standard.dictionary(forKey: Self.reviewedKey) as? [String: Double]) ?? [:]
    }

    /// Which newer parts are on: all of them follow ios_vryxcode, and each its own flag. [on] answers for one flag.
    func setParity(_ on: (String) -> Bool) {
        parity = on("ios_vryxcode") ? Set(Self.partFlags.filter(on)) : []
        extras = on("ios_vryxcode")
        suggestOn = on("vryxcode_suggest")
    }
    /// The parts that need no flag of their own (/commands, /memory, /permissions, pictures and documents) are on with ios_vryxcode.
    @Published private(set) var extras = false

    var working: Bool { ["starting", "working", "asking", "queued"].contains(state) }
    var oneModel: Bool { info?.effort != nil }                 // the effort picker chooses the model (flag vryxcode_effort)
    var usageLabel: String? { (usage ?? info?.usage)?.label }

    // MARK: Lists

    func load() async {
        do {
            let i = try await api.codeInfo()
            info = i
            if project.isEmpty { project = i.project ?? i.projects.first ?? "" }
            // With the effort picker on (vryxcode_effort) one automatic model is used: effort.auto is its id.
            if let auto = i.effort?.auto { model = auto } else if model.isEmpty { model = i.models.first(where: \.ready)?.id ?? "" }
            if let e = i.environments.first(where: { $0.id == env && $0.available }) ?? i.environments.first(where: \.available) { env = e.id }
            sessions = (try? await api.codeSessions()) ?? sessions
            templates = (try? await api.codeTemplates()) ?? templates
            error = nil
            loaded = true
        } catch { fail(error); loaded = true }
    }

    func refreshLists() async { sessions = (try? await api.codeSessions()) ?? sessions }
    func loadArchived() async { archived = (try? await api.codeSessions(archived: true)) ?? [] }

    func archive(_ s: CodeSessionRow, _ on: Bool) {
        Task { do { try await api.codeArchive(s.id, on); await refreshLists(); await loadArchived() } catch { fail(error) } }
    }

    /// Deletes a session and its history for good (the project's files stay).
    func deleteSession(_ s: CodeSessionRow) {
        Task { do { try await api.codeDeleteSession(s.id); await refreshLists(); await loadArchived() } catch { fail(error) } }
    }

    // MARK: The open session

    func open(_ row: CodeSessionRow) {
        stopPolling()
        sid = row.id
        title = row.title
        project = row.project.isEmpty ? project : row.project
        if info?.models.contains(where: { $0.id == row.model && $0.ready }) == true, !oneModel { model = row.model }
        events = []; seen = 0; state = row.state; pending = nil; error = nil; stopping = false; offer = ""
        markReviewed(row)
        poll()
    }

    private func markReviewed(_ row: CodeSessionRow) {
        reviewed[row.id] = row.updated
        UserDefaults.standard.set(reviewed, forKey: Self.reviewedKey)
    }

    /// Back to the sessions list.
    func close() {
        stopPolling()
        sid = nil; events = []; pending = nil; state = ""; seen = 0; title = ""
        Task { await refreshLists() }
    }

    func stopPolling() { poller?.cancel(); poller = nil }

    /// Reads what happened since the last look; keeps reading while it works (every 0.4 s, 1.5 s while it waits for an answer).
    private func poll() {
        guard let id = sid else { return }
        poller?.cancel()
        poller = Task {
            var fails = 0
            while !Task.isCancelled {
                do {
                    let v = try await api.codeView(id, after: seen)
                    fails = 0
                    if !v.events.isEmpty { events.removeAll { $0.bool("pending") } }          // the server's copy replaces what was shown at once
                    for e in v.events { let ev = CodeEvent(id: nextEvent(), raw: e); events.append(ev); offerFrom(ev) }
                    seen += v.events.count
                    state = v.state
                    pending = v.pending.map { CodeEvent(id: -1, raw: $0) }
                    full = v.full
                    if let u = v.usage { usage = u }
                    if !v.working { stopping = false; await refreshLists(); break }                // "Stopping…" stays until the run has ended
                    try await Task.sleep(nanoseconds: state == "asking" ? 1_500_000_000 : 400_000_000)
                } catch is CancellationError {
                    return
                } catch {
                    if let e = error as? ApiError, e.signedOut { onSignedOut(); return }
                    fails += 1
                    if fails >= 3 { self.error = describe(error) }                            // one dropped answer on a phone network is normal
                    try? await Task.sleep(nanoseconds: 3_000_000_000)
                }
            }
        }
    }

    private func nextEvent() -> Int { nextId += 1; return nextId }

    // MARK: Sending

    /// The send button: a new session, the next message, or (the full agent, while it works) a message it reads before its next step.
    func send(_ text: String) {
        let words = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !words.isEmpty || !pictures.isEmpty else { return }
        error = nil
        if extras, words.hasPrefix("/"), let slash = Slash.parse(words) { run(slash); return }
        offer = ""
        if !words.isEmpty { events.append(CodeEvent(id: nextEvent(), raw: ["kind": "user", "text": words, "pending": true])) }       // on screen at once
        Task {
            do {
                if let id = sid, working, full {
                    try await api.codeSteer(id, words)
                } else if let id = sid {
                    _ = try await api.codeMessage(id, body(words, start: false))
                } else {
                    let all = info?.projects ?? []
                    let where_ = freeName(ideaName(words), all)                                // a new idea gets its own project
                    project = where_
                    let r = try await api.codeStart(body(words, start: true))
                    sid = r.id
                    title = words.count > 60 ? String(words.prefix(60)) + "…" : words
                    events = [CodeEvent(id: nextEvent(), raw: ["kind": "user", "text": words, "pending": true])]
                    seen = 0
                    if var i = info { i.projects.append(where_); info = i }
                }
                pictures = []; docs = []
                state = "working"
                poll()
            } catch { events.removeAll { $0.bool("pending") }; fail(error) }
        }
    }

    func stop() {
        guard let id = sid else { return }
        stopping = true
        Task { _ = try? await api.codeStop(id); poll() }
    }

    /// A permission question: Yes / Yes and don't ask again / No.
    func answer(allow: Bool, always: Bool = false) {
        guard let id = sid, let q = pending?.int("id") else { return }
        Task { try? await api.codeAnswer(id, question: q, allow: allow, always: always); pending = nil; poll() }
    }

    /// A multiple-choice question: the option picked, or the person's own words.
    func choose(_ text: String) {
        guard let id = sid, let q = pending?.int("id"), !text.isBlank else { return }
        Task { try? await api.codeAnswer(id, question: q, allow: true, choice: text.trimmingCharacters(in: .whitespacesAndNewlines)); pending = nil; poll() }
    }

    private func body(_ text: String, start: Bool) -> [String: Any] {
        var b: [String: Any] = [:]
        if start {
            b["project"] = project; b["task"] = text; b["env"] = env; b["queue"] = true
            if let t = template { b["template"] = t; template = nil }
        } else { b["text"] = text }
        b["model"] = model; b["effort"] = effort
        b["auto_edits"] = mode == "auto"; b["plan"] = mode == "plan"
        if !pictures.isEmpty { b["images"] = pictures }
        if !docs.isEmpty { b["docs"] = docs.map(\.id) }
        return b
    }

    // MARK: Slash commands, memory, rules, Restore

    private func run(_ c: Slash) {
        switch c {
        case let .mode(m): mode = m
        case .newSession: close()
        case .memory: showMemory()
        case .permissions: showRules()
        }
    }

    func loadCommands() async { if extras { commands = (try? await api.codeCommands(project)) ?? commands } }

    /// What to suggest typing after "/": the app's own commands and the project's saved ones that start with what was typed.
    func slashMatches(_ typed: String) -> [(name: String, about: String)] {
        guard extras, typed.hasPrefix("/"), !typed.contains(" ") else { return [] }
        let word = typed.lowercased()
        return (Slash.builtIn + commands.map { ($0.name.hasPrefix("/") ? $0.name : "/" + $0.name, $0.about) }).filter { $0.name.lowercased().hasPrefix(word) }
    }

    func showMemory() {
        Task { do { memory = try await api.codeMemory().notes } catch { fail(error) } }
    }
    func forget(_ index: Int) { Task { if let m = try? await api.codeForget(index) { memory = m.notes } } }

    func showRules() {
        Task { do { rules = try await api.codeRules(project) } catch { fail(error) } }
    }
    func addRule(_ kind: String, _ rule: String) {
        let r = rule.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !r.isEmpty else { return }
        Task { do { rules = try await api.codeRule(project, add: (kind, r)) } catch { fail(error) } }
    }
    func removeRule(_ rule: String) { Task { if let r = try? await api.codeRule(project, remove: rule) { rules = r } } }

    /// Restore on a message (flag vryxcode_restore): the files go back to just before it.
    func restore(turn: Int) {
        guard let id = sid else { return }
        Task {
            do { try await api.codeRewind(id, turn: turn); error = nil } catch { fail(error) }
            poll()
        }
    }

    // MARK: Pictures and documents

    /// A picture for the next message: at most 3, each under 5 MB, as JPEG (Picked.picture makes it one).
    func addPicture(name: String, data: Data) {
        guard pictures.count < 3, data.count <= 5_000_000 else { error = "Up to 3 pictures, 5 MB each."; return }
        pictures.append("data:image/jpeg;base64," + data.base64EncodedString())
    }
    func removePicture(_ i: Int) { if pictures.indices.contains(i) { pictures.remove(at: i) } }

    /// A PDF, Word or text file for VryxCode to read with the next message: kept in your Documents.
    func addDoc(name: String, data: Data) {
        guard docs.count < 8 else { return }
        guard data.count <= 10_000_000 else { error = "\(name) is over 10 MB."; return }
        Task { do { docs.append(try await api.upload(name: name, data: data)) } catch { self.error = name + " was not attached: " + describe(error) } }
    }
    func removeDoc(_ i: Int) { if docs.indices.contains(i) { docs.remove(at: i) } }

    // MARK: Suggested replies

    /// What to suggest next, as the website does: "build it" after a plan, otherwise the model's first suggested next step.
    private func offerFrom(_ e: CodeEvent) {
        switch e.kind {
        case "user", "start": offer = ""
        case "end":
            if e.bool("finished") || e.bool("plan") {
                offer = !suggestOn ? "" : e.bool("plan") ? "Go ahead and build it as planned." : String((e.strings("next").first ?? "").prefix(200))
            } else if endState(e) == .waiting, parity.contains("vryxcode_autocontinue") {
                offer = !suggestOn ? "" : justAnswered(e, events) ? (followUps(last: lastAsked(events, before: e), text: e.str("summary")).first ?? "") : (waitingReplies(e.str("summary")).first ?? "")
            }
        default: break
        }
    }

    private func fail(_ error: Error) {
        if let e = error as? ApiError, e.signedOut { onSignedOut(); return }
        self.error = (error as? ApiError)?.text ?? "Something went wrong. Try again."
    }
    private func describe(_ error: Error) -> String { (error as? ApiError)?.text ?? "Something went wrong. Try again." }
}
