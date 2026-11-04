import Foundation

// The server's answers the native screens read, as android/.../data/Api.kt has them. Every field has a default, so a server that
// sends more (or a little less) never stops the app: decoding is by name, and a missing field takes its default.

/// GET /api/status: is the server up, paused, resting (Gaming mode) or in demo mode.
struct Status: Decodable, Equatable {
    var up = false, paused = false, resting = false, demo = false
    init() {}
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        up = c.bool("up"); paused = c.bool("paused"); resting = c.bool("resting"); demo = c.bool("demo")
    }
}

/// A sign-in try: [ok] signed in; [mfa] a second step (a code) is needed, with [ticket] to send back with it.
struct LoginReply: Decodable, Equatable {
    var ok = false, mfa = false, ticket: String?
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        ok = c.bool("ok"); mfa = c.bool("mfa"); ticket = c.string("ticket")
    }
}

/// GET /api/auth-options: which ways of signing in this server offers.
struct AuthOptions: Decodable, Equatable {
    var email = false, password = true, passkeys = false
    init() {}
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        email = c.bool("email"); password = c.bool("password", true); passkeys = c.bool("passkeys")
    }
}

/// One model in the picker. [fullName] is "Flare 3", "Solstice 2.5", as the website shows it (core.js mname).
struct ModelCard: Decodable, Equatable, Identifiable {
    var id = "", name = "", version: Double?, tagline = "", state = "", efforts: [String]?
    var ready: Bool { state == "ready" }
    var fullName: String {
        guard let v = version else { return name }
        return name + " " + (v.rounded() == v ? String(Int(v)) : String(v))
    }
    init(id: String, name: String, version: Double? = nil, state: String = "ready") {
        self.id = id; self.name = name; self.version = version; self.state = state
    }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        id = c.string("id") ?? ""; name = c.string("name") ?? ""; version = c.double("version")
        tagline = c.string("tagline") ?? ""; state = c.string("state") ?? ""; efforts = c.value("efforts")
    }
}

/// The model list: [cards] the main models, [other] the rest.
struct Catalog: Decodable, Equatable {
    var cards: [ModelCard] = [], other: [ModelCard] = []
    var all: [ModelCard] { cards + other }
    init() {}
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        cards = c.value("cards") ?? []; other = c.value("other") ?? []
    }
}

/// One thinking-effort choice (Auto, Quick, Balanced, Deep ...).
struct Effort: Decodable, Equatable, Identifiable {
    var id = "", name = "", use = "", blurb = ""
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        id = c.string("id") ?? ""; name = c.string("name") ?? ""; use = c.string("use") ?? ""; blurb = c.string("blurb") ?? ""
    }
}

/// One row of the chat list.
struct ChatSummary: Decodable, Equatable, Identifiable {
    var id: Int64 = 0, title = "New chat", updated = 0.0, pinned = false, skill = "", folder = ""
    init(id: Int64, title: String) { self.id = id; self.title = title }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        id = c.int("id") ?? 0; title = c.string("title") ?? "New chat"; updated = c.double("updated") ?? 0
        pinned = c.bool("pinned"); skill = c.string("skill") ?? ""; folder = c.string("folder") ?? ""
    }
}

/// The usage line under the message box (app usage_snapshot; web/js/chat.js renderUsage).
struct Usage: Decodable, Equatable {
    var exempt = false, canSend = 0, tankPct = 100.0, weekPctLeft = 100.0
    init() {}
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        exempt = c.bool("exempt"); canSend = Int(c.int("can_send") ?? 0)
        let tank = try? c.nestedContainer(keyedBy: AnyKey.self, forKey: AnyKey("tank"))
        let week = try? c.nestedContainer(keyedBy: AnyKey.self, forKey: AnyKey("week"))
        tankPct = tank?.double("pct") ?? 100; weekPctLeft = week?.double("pct_left") ?? 100
    }
    var fraction: Double { exempt ? 1 : min(tankPct, weekPctLeft) / 100 }
    var label: String {
        if exempt { return "Usage: no limit (owner)" }
        if canSend <= 0 { return "Usage: out for now" }
        let n = NumberFormatter.localizedString(from: NSNumber(value: canSend), number: .decimal)
        return "Usage: \(Usage.percent(fraction)) · about \(n) messages left"
    }
    /// "87%"; near full one decimal, so a small message shows (web chat.js pctText).
    static func percent(_ frac: Double) -> String {
        let p = frac * 100
        return (p >= 99.95 ? "100" : p >= 90 ? String(format: "%.1f", p) : String(Int(p.rounded()))) + "%"
    }
}

/// GET /api/state: who you are, your plan, the models, your chats, usage and the feature flags as they apply to you.
struct AppState: Decodable, Equatable {
    var user = "", plan = "", demo = false, owner = false, admin = false
    var models = Catalog(), model = "", efforts: [Effort] = [], chats: [ChatSummary] = []
    var usage: Usage?, features: [String: Bool] = [:], thinkingWords: [String] = []
    var planName: String { plan.prefix(1).uppercased() + plan.dropFirst() + " plan" }
    func on(_ flag: String) -> Bool { features[flag] == true }
    init() {}
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        user = c.string("user") ?? ""; plan = c.string("plan") ?? ""; demo = c.bool("demo"); owner = c.bool("owner"); admin = c.bool("admin")
        models = c.value("models") ?? Catalog(); model = c.string("model") ?? ""; efforts = c.value("efforts") ?? []
        chats = c.value("chats") ?? []; usage = c.value("usage"); features = c.value("features") ?? [:]
        thinkingWords = c.value("thinking_words") ?? []
    }
}

/// One message in a chat: who wrote it ([role] user or assistant), its words, and whether the reply was cut off.
struct Message: Decodable, Equatable {
    var id: Int64 = 0, role = "", content = "", modelId = "", status = "done", cut = false
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        id = c.int("id") ?? 0; role = c.string("role") ?? ""; content = c.string("content") ?? ""
        modelId = c.string("model_id") ?? ""; status = c.string("status") ?? "done"; cut = c.bool("cut")
    }
}

/// GET /api/chats/{id}: its messages, and whether a reply is still being written.
struct Chat: Decodable, Equatable {
    var id: Int64 = 0, title = "New chat", messages: [Message] = [], generating = false, isPrivate = false
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        id = c.int("id") ?? 0; title = c.string("title") ?? "New chat"; messages = c.value("messages") ?? []
        generating = c.bool("generating"); isPrivate = c.bool("private")
    }
}

/// POST /api/chats: the new chat's id.
struct NewChat: Decodable { var id: Int64 = 0
    init(from d: Decoder) throws { id = (try d.container(keyedBy: AnyKey.self)).int("id") ?? 0 }
}

/// The server's error body: a code to act on, a message to show, and what to do about it.
struct ErrorBody: Decodable {
    var code = "", message = "", action = ""
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        code = c.string("code") ?? ""; message = c.string("message") ?? ""; action = c.string("action") ?? ""
    }
}

// MARK: - Reading JSON by name, with defaults

/// A key made from any string, so each type reads exactly the names it wants and ignores the rest.
struct AnyKey: CodingKey {
    var stringValue: String
    var intValue: Int? { nil }
    init(_ s: String) { stringValue = s }
    init?(stringValue: String) { self.stringValue = stringValue }
    init?(intValue: Int) { nil }
}

extension KeyedDecodingContainer where K == AnyKey {
    func value<T: Decodable>(_ key: String) -> T? { (try? decodeIfPresent(T.self, forKey: AnyKey(key))) ?? nil }
    func string(_ key: String) -> String? { value(key) }
    func double(_ key: String) -> Double? { value(key) ?? (value(key) as Int64?).map(Double.init) }
    func int(_ key: String) -> Int64? { value(key) ?? (value(key) as Double?).map { Int64($0) } }
    /// A yes/no the server may send as true/false or as 0/1 (GET /api/chats/{id} sends pinned as 0 or 1).
    func bool(_ key: String, _ fallback: Bool = false) -> Bool {
        if let b: Bool = value(key) { return b }
        if let n: Int64 = value(key) { return n != 0 }
        return fallback
    }
}
