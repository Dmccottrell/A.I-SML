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

    private var seen = 0
    private var nextId = 0
    private var poller: Task<Void, Never>?

    init(api: ApiClient, onSignedOut: @escaping () -> Void) { self.api = api; self.onSignedOut = onSignedOut }

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
        events = []; seen = 0; state = row.state; pending = nil; error = nil; stopping = false
        poll()
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
                    for e in v.events { events.append(CodeEvent(id: nextEvent(), raw: e)) }
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
        guard !words.isEmpty else { return }
        error = nil
        events.append(CodeEvent(id: nextEvent(), raw: ["kind": "user", "text": words, "pending": true]))       // on screen at once
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
        return b
    }

    private func fail(_ error: Error) {
        if let e = error as? ApiError, e.signedOut { onSignedOut(); return }
        self.error = (error as? ApiError)?.text ?? "Something went wrong. Try again."
    }
    private func describe(_ error: Error) -> String { (error as? ApiError)?.text ?? "Something went wrong. Try again." }
}
