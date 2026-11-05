import Foundation

// VryxCode, the coding agent: the data and the calls behind the native screens (android/.../data/Code.kt and CodeViewModel.kt).

/// One model VryxCode can use.
struct CodeModel: Decodable, Equatable, Identifiable {
    var id = "", name = "", label = "", state = "", badge = "", outside = false, note = ""
    var ready: Bool { state == "ready" }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        id = c.string("id") ?? ""; name = c.string("name") ?? ""; label = c.string("label") ?? ""; state = c.string("state") ?? ""
        badge = c.string("badge") ?? ""; outside = c.bool("outside"); note = c.string("note") ?? ""
    }
}

/// A place VryxCode can run code: real commands run only in Docker or the cloud machine.
struct CodeEnv: Decodable, Equatable, Identifiable {
    var id = "", name = "", available = false, note = ""
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        id = c.string("id") ?? ""; name = c.string("name") ?? ""; available = c.bool("available"); note = c.string("note") ?? ""
    }
}

/// The effort levels that replace the model picker (flag vryxcode_effort): VryxCode picks the model itself.
struct CodeEffort: Decodable, Equatable {
    var auto: String?, levels: [Level] = []
    struct Level: Decodable, Equatable, Identifiable {
        var id = "", name = "", note = ""
        init(from d: Decoder) throws {
            let c = try d.container(keyedBy: AnyKey.self)
            id = c.string("id") ?? ""; name = c.string("name") ?? ""; note = c.string("note") ?? ""
        }
    }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        auto = c.string("auto"); levels = c.value("levels") ?? []
    }
}

/// VryxCode's usage in coding steps: one step is one model call at Balanced.
struct CodeUsage: Decodable, Equatable {
    var exempt = false, plan = "", tankPct = 100, stepsLeft = 0
    var label: String {
        exempt ? "Owner: no limits"
               : plan.prefix(1).uppercased() + plan.dropFirst() + " · \(tankPct)% left · about " + NumberFormatter.localizedString(from: NSNumber(value: stepsLeft), number: .decimal) + " coding steps"
    }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        exempt = c.bool("exempt"); plan = c.string("plan") ?? ""; tankPct = Int(c.int("tank_pct") ?? 100); stepsLeft = Int(c.int("steps_left") ?? 0)
    }
}

/// GET /api/code: what the VryxCode screen needs to start.
struct CodeInfo: Decodable, Equatable {
    var allowed = true, whyNot = "", models: [CodeModel] = [], projects: [String] = [], environments: [CodeEnv] = []
    var effort: CodeEffort?, running: String?, project: String?, usage: CodeUsage?
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        allowed = c.bool("allowed", true); whyNot = c.string("why_not") ?? ""; models = c.value("models") ?? []
        projects = c.value("projects") ?? []; environments = c.value("environments") ?? []; effort = c.value("effort")
        running = c.string("running"); project = c.string("project"); usage = c.value("usage")
    }
}

/// One row in the list of sessions.
struct CodeSessionRow: Decodable, Equatable, Identifiable {
    var id = "", title = "", project = "", model = "", state = "", age = "", snippet = "", env = "local"
    var steps = 0, files = 0, added = 0, removed = 0, archived = false
    var live: Bool { ["starting", "working", "asking", "queued"].contains(state) }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        id = c.string("id") ?? ""; title = c.string("title") ?? ""; project = c.string("project") ?? ""; model = c.string("model") ?? ""
        state = c.string("state") ?? ""; age = c.string("age") ?? ""; snippet = c.string("snippet") ?? ""; env = c.string("env") ?? "local"
        steps = Int(c.int("steps") ?? 0); files = Int(c.int("files") ?? 0); added = Int(c.int("added") ?? 0); removed = Int(c.int("removed") ?? 0)
        archived = c.bool("archived")
    }
}

/// A project starter on the VryxCode home.
struct CodeTemplate: Decodable, Equatable, Identifiable {
    var id = "", name = "", icon = "", desc = "", idea = ""
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        id = c.string("id") ?? ""; name = c.string("name") ?? ""; icon = c.string("icon") ?? ""; desc = c.string("desc") ?? ""; idea = c.string("idea") ?? ""
    }
}

/// One event of a session, as loose JSON: the feed has about twenty kinds (web/js/ide.js renderEvent), read with the helpers below.
struct CodeEvent: Identifiable, Equatable {
    let id: Int
    let raw: [String: Any]
    var kind: String { str("kind") }
    func str(_ k: String) -> String {
        switch raw[k] { case let s as String: return s; case let n as NSNumber: return n.stringValue; default: return "" }
    }
    func bool(_ k: String) -> Bool { (raw[k] as? Bool) ?? ((raw[k] as? NSNumber)?.boolValue ?? false) }
    func int(_ k: String) -> Int { (raw[k] as? NSNumber)?.intValue ?? Int(str(k)) ?? 0 }
    func num(_ k: String) -> Double? { (raw[k] as? NSNumber)?.doubleValue }
    func strings(_ k: String) -> [String] { (raw[k] as? [Any])?.compactMap { $0 as? String } ?? [] }
    static func == (a: CodeEvent, b: CodeEvent) -> Bool { a.id == b.id && NSDictionary(dictionary: a.raw).isEqual(to: b.raw) }
}

/// One look at a session (GET /api/code/sessions/{id}?after=N): what happened since N, its state, and an open question.
struct CodeView {
    var events: [[String: Any]] = [], state = "", pending: [String: Any]?, full = false, usage: CodeUsage?
    var working: Bool { ["starting", "working", "asking", "queued"].contains(state) }
    init(json: [String: Any]) {
        events = json["events"] as? [[String: Any]] ?? []
        state = json["state"] as? String ?? ""
        pending = json["pending"] as? [String: Any]
        full = json["full"] as? Bool ?? false
        usage = (json["usage"] as? [String: Any]).flatMap { try? JSONSerialization.data(withJSONObject: $0) }.flatMap { try? JSONDecoder().decode(CodeUsage.self, from: $0) }
    }
}

/// The answer after starting or messaging a session: its id, and whether it waits in a queue.
struct CodeStarted: Decodable {
    var id = "", queued = false, note: String?, message: String?
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        id = c.string("id") ?? ""; queued = c.bool("queued"); note = c.string("note"); message = c.string("message")
    }
}

extension ApiClient {
    func codeInfo() async throws -> CodeInfo { try await getJSON("/api/code") }
    func codeSessions(archived: Bool = false) async throws -> [CodeSessionRow] {
        let r: [String: [CodeSessionRow]] = try await getJSON("/api/code/sessions" + (archived ? "?archived=1" : ""))
        return r["sessions"] ?? []
    }
    func codeTemplates() async throws -> [CodeTemplate] {
        let r: [String: [CodeTemplate]] = try await getJSON("/api/code/templates")
        return r["templates"] ?? []
    }
    func codeView(_ id: String, after: Int) async throws -> CodeView { CodeView(json: try await rawJSON("GET", "/api/code/sessions/\(id)?after=\(after)")) }
    func codeStart(_ body: [String: Any]) async throws -> CodeStarted { try await postJSON("/api/code/start", body) }
    func codeMessage(_ id: String, _ body: [String: Any]) async throws -> CodeStarted { try await postJSON("/api/code/sessions/\(id)/message", body) }
    /// A nudge to the agent while it works.
    func codeSteer(_ id: String, _ text: String) async throws { _ = try await rawJSON("POST", "/api/code/sessions/\(id)/steer", ["text": text]) }
    /// Answers the agent's question or permission request: allow or not, optionally "always", or a chosen option.
    func codeAnswer(_ id: String, question: Int, allow: Bool, always: Bool = false, choice: String? = nil) async throws {
        var body: [String: Any] = ["id": question, "allow": allow, "always": always]
        if let choice { body["choice"] = choice }
        _ = try await rawJSON("POST", "/api/code/sessions/\(id)/answer", body)
    }
    func codeStop(_ id: String) async throws { _ = try await rawJSON("POST", "/api/code/sessions/\(id)/stop", [:]) }
    func codeArchive(_ id: String, _ on: Bool) async throws { _ = try await rawJSON("POST", "/api/code/sessions/\(id)/archive", ["archived": on]) }
    func codeDeleteSession(_ id: String) async throws { _ = try await rawJSON("POST", "/api/code/sessions/\(id)/delete", [:]) }
}
