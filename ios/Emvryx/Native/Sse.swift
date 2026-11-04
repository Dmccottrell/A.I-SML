import Foundation

/// One step of a streamed reply (POST /api/chats/{id}/send, api_send in app/routes_chat.py), as android/.../data/Sse.kt reads it.
enum ReplyEvent: Equatable {
    /// The model started thinking. [auto]: Auto chose the effort.
    case thinking(effort: String, auto: Bool)
    /// The model is being loaded into memory (slow the first time).
    case loading(model: String)
    /// The next bit of the answer.
    case piece(String)
    /// Old messages are being folded into a summary to make room.
    case compacting
    /// What it remembered about you, and how many things it forgot.
    case memory(saved: [String], forgot: Int)
    /// Finished: the chat's title, the message id, and whether it was cut at a length limit.
    case done(title: String?, messageId: Int64?, cut: Bool, usage: Usage?)
    /// Deep Research: one search or page read, [done] of [of].
    case research(step: String, done: Int, of: Int)
    /// The server reported an error inside the stream.
    case failed(code: String, message: String, action: String)
    /// An event this app version does not know (a newer server may add some): ignored.
    case other(String)
}

/// Turns server-sent-event lines into [ReplyEvent]s. Feed it every line without its newline; a blank line ends an event.
struct SseParser {
    private var event = "message"
    private var data = ""

    /// Takes one line. Returns a finished event when this was the blank line that ends one, otherwise nil.
    mutating func feed(_ line: String) -> ReplyEvent? {
        if line.isEmpty { return flush() }
        if line.hasPrefix(":") { return nil }                         // keep-alive comment
        let name = line.prefix { $0 != ":" }
        var value = line.dropFirst(name.count)
        if value.hasPrefix(":") { value = value.dropFirst() }
        if value.hasPrefix(" ") { value = value.dropFirst() }
        switch name {
        case "event": event = String(value)
        case "data": data += (data.isEmpty ? "" : "\n") + value
        default: break
        }
        return nil
    }

    private mutating func flush() -> ReplyEvent? {
        defer { event = "message"; data = "" }
        guard !data.isEmpty else { return nil }
        let body = (try? JSONSerialization.jsonObject(with: Data(data.utf8))) as? [String: Any] ?? [:]
        func s(_ k: String) -> String? { body[k].map { "\($0)" }.flatMap { $0 == "<null>" ? nil : $0 } }
        func b(_ k: String) -> Bool { (body[k] as? Bool) ?? ((body[k] as? NSNumber)?.boolValue ?? false) }
        func i(_ k: String) -> Int { (body[k] as? NSNumber)?.intValue ?? Int(s(k) ?? "") ?? 0 }
        switch event {
        case "thinking": return .thinking(effort: s("effort") ?? "", auto: b("auto"))
        case "loading": return .loading(model: s("model") ?? "")
        case "piece": return .piece(body["t"] as? String ?? "")
        case "compacting": return .compacting
        case "memory": return .memory(saved: body["saved"] as? [String] ?? [], forgot: i("forgot"))
        case "done":
            let usage = (body["usage"] as? [String: Any]).flatMap { try? JSONSerialization.data(withJSONObject: $0) }
                .flatMap { try? JSONDecoder().decode(Usage.self, from: $0) }
            return .done(title: body["title"] as? String, messageId: (body["message_id"] as? NSNumber)?.int64Value, cut: b("cut"), usage: usage)
        case "research": return .research(step: s("step") ?? "", done: i("done"), of: i("of"))
        case "error":
            return .failed(code: s("code") ?? "error", message: s("message") ?? "Something went wrong.", action: s("action") ?? "")
        default: return .other(event)
        }
    }
}
