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

/// The usage line under the message box (app usage_snapshot; web/js/chat.js renderUsage), and the numbers behind it for the Usage sheet.
struct Usage: Decodable, Equatable {
    var exempt = false, canSend = 0, tankPct = 100.0, weekPctLeft = 100.0
    var tankMessagesLeft = 0, tankFullAt = 0.0, tankRefillHours = 0.0, weekMessagesLeft = 0, weekResetsAt = 0.0
    var models: [ModelLeft] = []
    struct ModelLeft: Equatable { var model = "", messagesLeft = 0 }
    init() {}
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        exempt = c.bool("exempt"); canSend = Int(c.int("can_send") ?? 0)
        let tank = try? c.nestedContainer(keyedBy: AnyKey.self, forKey: AnyKey("tank"))
        let week = try? c.nestedContainer(keyedBy: AnyKey.self, forKey: AnyKey("week"))
        tankPct = tank?.double("pct") ?? 100; weekPctLeft = week?.double("pct_left") ?? 100
        tankMessagesLeft = Int(tank?.int("messages_left") ?? 0); tankFullAt = tank?.double("full_at") ?? 0
        tankRefillHours = tank?.double("refill_hours") ?? 0
        weekMessagesLeft = Int(week?.int("messages_left") ?? 0); weekResetsAt = week?.double("resets_at") ?? 0
        let rows: [[String: AnyCodable]] = c.value("models") ?? []
        models = rows.map { ModelLeft(model: $0["model"]?.string ?? "", messagesLeft: Int($0["messages_left"]?.number ?? 0)) }
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

/// A JSON value that is a string or a number, for the few lists whose rows mix both.
struct AnyCodable: Decodable, Equatable {
    var string: String?, number: Double?
    init(from d: Decoder) throws {
        let c = try d.singleValueContainer()
        string = try? c.decode(String.self)
        number = (try? c.decode(Double.self)) ?? nil
    }
}

/// GET /api/state: who you are, your plan, the models, your chats, usage and the feature flags as they apply to you.
struct AppState: Decodable, Equatable {
    var user = "", plan = "", demo = false, owner = false, admin = false
    var models = Catalog(), model = "", efforts: [Effort] = [], chats: [ChatSummary] = []
    var usage: Usage?, features: [String: Bool] = [:], thinkingWords: [String] = [], regenOptions: [RegenOption] = []
    var planName: String { plan.prefix(1).uppercased() + plan.dropFirst() + " plan" }
    func on(_ flag: String) -> Bool { features[flag] == true }
    init() {}
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        user = c.string("user") ?? ""; plan = c.string("plan") ?? ""; demo = c.bool("demo"); owner = c.bool("owner"); admin = c.bool("admin")
        models = c.value("models") ?? Catalog(); model = c.string("model") ?? ""; efforts = c.value("efforts") ?? []
        chats = c.value("chats") ?? []; usage = c.value("usage"); features = c.value("features") ?? [:]
        thinkingWords = c.value("thinking_words") ?? []; regenOptions = c.value("regen_options") ?? []
    }
}

/// "Regenerate" with a choice of how the new answer should differ (app/regen_modes.py).
struct RegenOption: Decodable, Equatable, Identifiable {
    var id = "", label = "", blurb = ""
    init(id: String, label: String, blurb: String = "") { self.id = id; self.label = label; self.blurb = blurb }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        id = c.string("id") ?? ""; label = c.string("label") ?? ""; blurb = c.string("blurb") ?? ""
    }
}

/// How full the model's memory (context window) is: the ring by the message box (feature flag context_meter).
struct Ctx: Decodable, Equatable {
    var used: Int64 = 0, window: Int64 = 1, pct = 0.0, compactAt: Int64 = 0
    init() {}
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        used = c.int("used") ?? 0; window = c.int("window") ?? 1; pct = c.double("pct") ?? 0; compactAt = c.int("compact_at") ?? 0
    }
}

/// A picture or file attached to a chat (app/documents.py).
struct DocInfo: Decodable, Equatable, Identifiable, Hashable {
    var id: Int64 = 0, name = "", kind = ""
    static let pictureKinds: Set<String> = ["png", "jpg", "jpeg", "webp", "bmp", "gif", "heic"]
    var isPicture: Bool { Self.pictureKinds.contains(kind.lowercased()) }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        id = c.int("id") ?? 0; name = c.string("name") ?? ""; kind = c.string("kind") ?? ""
    }
}

/// One hit of the search inside chats (GET /api/chats/search).
struct SearchHit: Decodable, Equatable, Identifiable {
    var id: Int64 = 0, title = "", snippet = ""
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        id = c.int("id") ?? 0; title = c.string("title") ?? ""; snippet = c.string("snippet") ?? ""
    }
}

/// A read-only link to a copy of a chat (POST /api/chats/{id}/share, GET /api/shares); [expires] is a Unix time in seconds.
struct ShareRow: Decodable, Equatable, Identifiable {
    var id = "", title = "", expires = 0.0
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        id = c.string("id") ?? ""; title = c.string("title") ?? ""; expires = c.double("expires") ?? 0
    }
}
struct Shares: Decodable, Equatable {
    var shares: [ShareRow] = [], on = false
    init() {}
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        shares = c.value("shares") ?? []; on = c.bool("on")
    }
}
struct ShareMade: Decodable { var url = "", shares: [ShareRow] = []
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        url = c.string("url") ?? ""; shares = c.value("shares") ?? []
    }
}

/// One message in a chat: who wrote it ([role] user or assistant), its words, and whether the reply was cut off.
struct Message: Decodable, Equatable {
    var id: Int64 = 0, role = "", content = "", modelId = "", status = "done", cut = false, fb = ""
    var docs: [DocInfo] = []
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        id = c.int("id") ?? 0; role = c.string("role") ?? ""; content = c.string("content") ?? ""
        modelId = c.string("model_id") ?? ""; status = c.string("status") ?? "done"; cut = c.bool("cut")
        fb = c.string("fb") ?? ""; docs = c.value("docs") ?? []
    }
}

/// GET /api/chats/{id}: its messages, and whether a reply is still being written.
struct Chat: Decodable, Equatable {
    var id: Int64 = 0, title = "New chat", messages: [Message] = [], generating = false, isPrivate = false, pinned = false
    var ctx: Ctx?, docs: [DocInfo] = []
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        id = c.int("id") ?? 0; title = c.string("title") ?? "New chat"; messages = c.value("messages") ?? []
        generating = c.bool("generating"); isPrivate = c.bool("private"); pinned = c.bool("pinned")
        ctx = c.value("ctx"); docs = c.value("docs") ?? []
    }
}

/// POST /api/chats/{id}/compact: the new memory reading.
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


// MARK: - Memory, files, skills and settings (android/.../data/Native.kt)

/// GET /api/memory: what Emvryx remembers about you, and whether memory is on.
struct MemoryList: Decodable, Equatable {
    var facts: [Fact] = [], on = true
    struct Fact: Decodable, Equatable, Identifiable {
        var id: Int64 = 0, text = "", created = 0.0, slot = ""
        init(from d: Decoder) throws {
            let c = try d.container(keyedBy: AnyKey.self)
            id = c.int("id") ?? 0; text = c.string("text") ?? ""; created = c.double("created") ?? 0; slot = c.string("slot") ?? ""
        }
    }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        facts = c.value("facts") ?? []; on = c.bool("on", true)
    }
}

/// GET /api/documents: your files, and the size limit in megabytes.
struct DocList: Decodable, Equatable {
    var documents: [DocRow] = [], maxMb = 0
    struct DocRow: Decodable, Equatable, Identifiable {
        var id: Int64 = 0, name = "", kind = "", chars: Int64 = 0, created = 0.0
        var isPicture: Bool { DocInfo.pictureKinds.contains(kind.lowercased()) }
        /// "40 words", "3,400 words" ("" for nothing): the characters the server read, at a rough 6 per word.
        var size: String {
            if chars <= 0 { return "" }
            if chars < 6_000 { return "\(max(1, chars / 6)) words" }
            return NumberFormatter.localizedString(from: NSNumber(value: chars / 6), number: .decimal) + " words"
        }
        init(from d: Decoder) throws {
            let c = try d.container(keyedBy: AnyKey.self)
            id = c.int("id") ?? 0; name = c.string("name") ?? ""; kind = c.string("kind") ?? ""; chars = c.int("chars") ?? 0; created = c.double("created") ?? 0
        }
    }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        documents = c.value("documents") ?? []; maxMb = Int(c.int("max_mb") ?? 0)
    }
}

/// One skill: a saved set of instructions a chat can start from.
struct Skill: Decodable, Equatable, Identifiable {
    var id = "", name = "", forWho = "", icon = "", does = "", tryThis = ""
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        id = c.string("id") ?? ""; name = c.string("name") ?? ""; forWho = c.string("for") ?? ""; icon = c.string("icon") ?? ""
        does = c.string("does") ?? ""; tryThis = c.string("try") ?? ""
    }
}

/// GET /api/settings: the everyday settings the app's own Settings screen shows (app/state_settings.py get_settings).
struct SettingsData: Decodable, Equatable {
    var windowMode = "everyday", showTokens = false, webSearch = "auto", memory = true, thinkingPause = "short"
    var liveData = true, connectedApps = true, customInstructions = ""
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        windowMode = c.string("window_mode") ?? "everyday"; showTokens = c.bool("show_tokens"); webSearch = c.string("web_search") ?? "auto"
        memory = c.bool("memory", true); thinkingPause = c.string("thinking_pause") ?? "short"; liveData = c.bool("live_data", true)
        connectedApps = c.bool("connected_apps", true); customInstructions = c.string("custom_instructions") ?? ""
    }
}
