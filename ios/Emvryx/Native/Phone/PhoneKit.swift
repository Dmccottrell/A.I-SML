import Foundation

// The phone model (android_offline_model): one of your own models runs on the phone itself, so the app still answers when the PC is off.
// These are the data and the rules, with no network or files: the same as android/.../local/LocalPrompt.kt and PhoneModel.kt (LocalSync).

/// The chat markers a model expects (ChatML), so the phone writes the prompt exactly as the PC does (core/chat.py).
struct ChatFormat: Codable, Equatable {
    var userOpen = "<|im_start|>user\n"
    var turnEnd = "<|im_end|>\n"
    var assistantOpen = "<|im_start|>assistant\n"
    var stop = ["<|im_end|>", "<|im_start|>", "<|endoftext|>"]
    var notesIntro = "Notes:\n"
    var questionIntro = "\n\nQuestion: "

    init(assistantOpen: String = "<|im_start|>assistant\n") { self.assistantOpen = assistantOpen }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        userOpen = c.string("user_open") ?? userOpen; turnEnd = c.string("turn_end") ?? turnEnd
        assistantOpen = c.string("assistant_open") ?? assistantOpen; stop = c.value("stop") ?? stop
        notesIntro = c.string("notes_intro") ?? notesIntro; questionIntro = c.string("question_intro") ?? questionIntro
    }
    func encode(to e: Encoder) throws {
        var c = e.container(keyedBy: AnyKey.self)
        try c.encode(userOpen, forKey: AnyKey("user_open")); try c.encode(turnEnd, forKey: AnyKey("turn_end"))
        try c.encode(assistantOpen, forKey: AnyKey("assistant_open")); try c.encode(stop, forKey: AnyKey("stop"))
        try c.encode(notesIntro, forKey: AnyKey("notes_intro")); try c.encode(questionIntro, forKey: AnyKey("question_intro"))
    }
}

/// What Emvryx remembers about the person, copied to the phone: [personal] is the pattern that says when a question is about them.
struct PhoneMemory: Codable, Equatable {
    var on = false, title = "", facts: [String] = [], personal = ""
    init(on: Bool = false, title: String = "", facts: [String] = [], personal: String = "") { self.on = on; self.title = title; self.facts = facts; self.personal = personal }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        on = c.bool("on"); title = c.string("title") ?? ""; facts = c.value("facts") ?? []; personal = c.string("personal") ?? ""
    }
    func encode(to e: Encoder) throws {
        var c = e.container(keyedBy: AnyKey.self)
        try c.encode(on, forKey: AnyKey("on")); try c.encode(title, forKey: AnyKey("title"))
        try c.encode(facts, forKey: AnyKey("facts")); try c.encode(personal, forKey: AnyKey("personal"))
    }
}

/// A model the phone may pick (Flare: fast; Equinox: smarter, needs a phone with more memory).
struct PhoneChoice: Codable, Equatable, Identifiable {
    var id = "", name = "", version: Double?, size: Int64 = 0, minRamGb = 4.0, tagline = ""
    var fullName: String { PhoneKit.fullName(name, version) }
    var sizeText: String { String(format: "%.1f GB", Double(size) / 1_073_741_824) }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        id = c.string("id") ?? ""; name = c.string("name") ?? ""; version = c.double("version"); size = c.int("size") ?? 0
        minRamGb = c.double("min_ram_gb") ?? 4; tagline = c.string("tagline") ?? ""
    }
    func encode(to e: Encoder) throws {
        var c = e.container(keyedBy: AnyKey.self)
        try c.encode(id, forKey: AnyKey("id")); try c.encode(name, forKey: AnyKey("name")); try c.encodeIfPresent(version, forKey: AnyKey("version"))
        try c.encode(size, forKey: AnyKey("size")); try c.encode(minRamGb, forKey: AnyKey("min_ram_gb")); try c.encode(tagline, forKey: AnyKey("tagline"))
    }
}

/// GET /api/phone-model (app/phone_model.py): the model file for this phone and how to answer with it, as the PC does.
struct PhoneKit: Codable, Equatable {
    var available = false, message = "", id = "", name = "", version: Double?, size: Int64 = 0, sha256: String?
    var preparing = false, file = "/api/phone-model/file", format = ChatFormat(), sampling: [String: Double] = [:]
    var maxReplyTokens = 1024, context = 4096, minRamGb = 4.0, hints = "", memory = PhoneMemory(), choices: [PhoneChoice] = []

    var fullName: String { Self.fullName(name.isEmpty ? "Flare" : name, version) }

    /// "Flare 3": the name with its version, a whole number without ".0".
    static func fullName(_ name: String, _ version: Double?) -> String {
        let n = name.isEmpty ? "Flare" : name
        guard let v = version else { return n }
        return n + " " + (v.rounded() == v ? String(Int(v)) : String(v))
    }

    init(available: Bool = false, id: String = "", name: String = "", version: Double? = nil, format: ChatFormat = ChatFormat(), hints: String = "",
         memory: PhoneMemory = PhoneMemory(), context: Int = 4096, maxReplyTokens: Int = 1024) {
        self.available = available; self.id = id; self.name = name; self.version = version; self.format = format; self.hints = hints
        self.memory = memory; self.context = context; self.maxReplyTokens = maxReplyTokens
    }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: AnyKey.self)
        available = c.bool("available"); message = c.string("message") ?? ""; id = c.string("id") ?? ""; name = c.string("name") ?? ""
        version = c.double("version"); size = c.int("size") ?? 0; sha256 = c.string("sha256"); preparing = c.bool("preparing")
        file = c.string("file") ?? file; format = c.value("format") ?? ChatFormat(); sampling = c.value("sampling") ?? [:]
        maxReplyTokens = Int(c.int("max_reply_tokens") ?? 1024); context = Int(c.int("context") ?? 4096); minRamGb = c.double("min_ram_gb") ?? 4
        hints = c.string("hints") ?? ""; memory = c.value("memory") ?? PhoneMemory(); choices = c.value("choices") ?? []
    }
    func encode(to e: Encoder) throws {
        var c = e.container(keyedBy: AnyKey.self)
        try c.encode(available, forKey: AnyKey("available")); try c.encode(message, forKey: AnyKey("message")); try c.encode(id, forKey: AnyKey("id"))
        try c.encode(name, forKey: AnyKey("name")); try c.encodeIfPresent(version, forKey: AnyKey("version")); try c.encode(size, forKey: AnyKey("size"))
        try c.encodeIfPresent(sha256, forKey: AnyKey("sha256")); try c.encode(preparing, forKey: AnyKey("preparing")); try c.encode(file, forKey: AnyKey("file"))
        try c.encode(format, forKey: AnyKey("format")); try c.encode(sampling, forKey: AnyKey("sampling"))
        try c.encode(maxReplyTokens, forKey: AnyKey("max_reply_tokens")); try c.encode(context, forKey: AnyKey("context"))
        try c.encode(minRamGb, forKey: AnyKey("min_ram_gb")); try c.encode(hints, forKey: AnyKey("hints")); try c.encode(memory, forKey: AnyKey("memory"))
        try c.encode(choices, forKey: AnyKey("choices"))
    }
}

/// One message of a chat on the phone: [mine] is the person's message, otherwise the model's answer.
struct LocalTurn: Codable, Equatable { var mine: Bool, text: String }

/// A chat on the phone. [serverId]: the PC's id for it once they have met; [synced]: how many turns the PC has.
struct LocalChat: Codable, Equatable, Identifiable {
    var id: Int64, title: String, turns: [LocalTurn], serverId: Int64? = nil, synced = 0, updated: Int64 = 0
    /// Written on the phone and not on the PC yet.
    var pending: [LocalTurn] { turns.dropFirst(synced).filter { !$0.text.isBlank && $0.text != "…" } }
}

/// The rules for keeping the phone's chats and the PC's in step (plain code, so it is tested on its own).
enum LocalSync {
    /// The PC's copy of a chat, kept on the phone: what was written on the phone and not synced yet stays at the end.
    static func merge(_ existing: LocalChat?, serverId: Int64, title: String, serverTurns: [LocalTurn], now: Int64) -> LocalChat {
        let extra = existing.map { Array($0.turns.dropFirst($0.synced)) } ?? []
        return LocalChat(id: existing?.id ?? (now * 1000 + (serverId % 1000)), title: title, turns: serverTurns + extra, serverId: serverId,
                         synced: serverTurns.count, updated: extra.isEmpty ? now : existing!.updated)
    }

    /// The same sync id for the same turns, so a sync sent again after a lost answer is not added twice.
    static func syncId(_ c: LocalChat) -> String { "\(c.id)-\(c.synced)-\(c.turns.count)" }

    /// Which chats to keep: every chat with something not synced, then the newest, up to [max].
    static func keep(_ chats: [LocalChat], max: Int) -> [LocalChat] {
        let must = chats.filter { !$0.pending.isEmpty }
        let rest = chats.filter { $0.pending.isEmpty }.sorted { $0.updated > $1.updated }.prefix(Swift.max(0, max - must.count))
        return chats.filter { c in must.contains { $0.id == c.id } || rest.contains { $0.id == c.id } }
    }
}

/// The prompt the phone's model reads, written exactly like the PC writes it for the same model (core/chat.py, ChatML): every earlier turn,
/// then the new question with what Emvryx remembers about the person in front (only when the question is about them) and their own
/// instructions after it. Oldest turns are left out first when it does not fit.
enum LocalPrompt {
    private static let memoryChars = 700

    /// A person's text can never contain a control marker: "<|im_end|>" typed in a message stays ordinary characters (a zero-width space is
    /// slipped between the two characters).
    static func clean(_ text: String) -> String { text.replacingOccurrences(of: "<|", with: "<\u{200B}|") }

    /// The remembered facts to show with this question, or nil for none.
    static func memoryNote(_ kit: PhoneKit, _ question: String) -> String? {
        let m = kit.memory
        guard m.on, !m.facts.isEmpty, !m.personal.isEmpty, let personal = try? NSRegularExpression(pattern: m.personal, options: .caseInsensitive),
              personal.firstMatch(in: question, range: NSRange(question.startIndex..., in: question)) != nil else { return nil }
        var text = ""
        for f in m.facts.reversed() {                                      // the newest facts first, as many as fit
            if text.count + f.count + 1 > memoryChars { break }
            text = text.isEmpty ? f : f + " " + text
        }
        return text.isEmpty ? nil : text
    }

    /// The text of the person's new message as the model should read it.
    static func question(_ kit: PhoneKit, _ question: String) -> String {
        let q = clean(question.trimmingCharacters(in: .whitespacesAndNewlines)) + (kit.hints.isBlank ? "" : "\n\n" + kit.hints)
        guard let note = memoryNote(kit, question) else { return q }
        return kit.format.notesIntro + "[1] " + kit.memory.title + ": " + clean(note) + kit.format.questionIntro + q
    }

    /// The whole prompt for answering [question] after [history]; [count] gives a text's length in tokens (the model's own tokenizer).
    static func build(_ kit: PhoneKit, _ history: [LocalTurn], _ question: String, count: (String) -> Int = { $0.count / 3 }) -> String {
        let f = kit.format
        let last = f.userOpen + Self.question(kit, question) + f.turnEnd + f.assistantOpen
        var pairs: [String] = []
        var i = 0
        while i < history.count {
            let u = history[i]
            if u.mine, i + 1 < history.count, !history[i + 1].mine {
                pairs.append(f.userOpen + clean(u.text) + f.turnEnd + f.assistantOpen + clean(history[i + 1].text) + f.turnEnd)
                i += 2
            } else { i += 1 }
        }
        let room = kit.context - kit.maxReplyTokens
        var start = 0
        var prompt = pairs.joined() + last
        while start < pairs.count && count(prompt) > room {                // the oldest turns are forgotten first
            start += 1
            prompt = pairs[start...].joined() + last
        }
        return prompt
    }

    /// What to show of what the model has written so far: a thinking block left out, and nothing from a stop marker on. `done` is true when
    /// a stop marker was reached. Called again and again while the answer streams in, so it copes with half-arrived markers.
    static func shown(_ raw: String, _ stops: [String]) -> (text: String, done: Bool) {
        var text = raw
        var done = false
        if let cut = stops.compactMap({ s in text.range(of: s)?.lowerBound }).min() { text = String(text[..<cut]); done = true }
        text = text.replacingOccurrences(of: "<think>[\\s\\S]*?</think>", with: "", options: .regularExpression)
        if let open = text.range(of: "<think>") { text = String(text[..<open.lowerBound]) }          // still thinking: nothing to show yet
        let hold = stops.map { s in (1..<max(s.count, 1)).reversed().first { n in text.hasSuffix(String(s.prefix(n))) } ?? 0 }.max() ?? 0
        let shown = String(text.dropLast(hold))
        return (String(shown.drop(while: { $0.isWhitespace })), done)
    }
}

/// Turns the model's pieces (UTF-8 bytes; a letter can be split across two pieces) into text, keeping an unfinished last letter for next time.
struct Utf8Joiner {
    private var pending: [UInt8] = []
    private(set) var text = ""

    mutating func add(_ bytes: [UInt8]) {
        let all = pending + bytes
        var cut = all.count
        for back in 1...min(3, max(all.count, 1)) where all.count >= back {
            let b = all[all.count - back]
            if b & 0xC0 == 0x80 { continue }                               // a continuation byte: look further back
            let need = b & 0x80 == 0 ? 1 : b & 0xE0 == 0xC0 ? 2 : b & 0xF0 == 0xE0 ? 3 : b & 0xF8 == 0xF0 ? 4 : 1
            if need > back { cut = all.count - back }
            break
        }
        text += String(decoding: all[..<cut], as: UTF8.self)
        pending = Array(all[cut...])
    }
}
