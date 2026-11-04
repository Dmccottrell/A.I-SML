import Foundation

/// What can go wrong talking to the server: it cannot be reached (the PC is off, no internet), or it answered with an error to show.
enum ApiError: Error, Equatable {
    case offline
    case server(http: Int, code: String, message: String, action: String)

    /// The session is gone (signed out on another device, or it ran out): back to the sign-in screen.
    var signedOut: Bool { if case let .server(http, code, _, _) = self { return http == 401 || code == "bad_key" }; return false }

    var text: String {
        switch self {
        case .offline: return "Emvryx can't be reached right now. Check your connection and try again."
        case let .server(_, _, message, action): return action.isEmpty ? message : message + " " + action
        }
    }
}

/// Talks to the Emvryx server, as android/.../data/ApiClient.kt does: JSON in and out, the session cookie on every call, and a
/// streamed reply read line by line.
final class ApiClient {
    let base: URL
    let session: SessionStore
    private let http: URLSession

    init(base: URL = Site.home, session: SessionStore? = nil) {
        self.base = base
        self.session = session ?? SessionStore(server: base)
        let config = URLSessionConfiguration.default
        config.httpShouldSetCookies = false                       // the one cookie is added by hand, from the Keychain
        config.httpCookieAcceptPolicy = .never
        config.timeoutIntervalForRequest = 30
        config.timeoutIntervalForResource = 60 * 60                // a long reply can stream for a while
        config.httpAdditionalHeaders = ["User-Agent": "Emvryx-iOS/1.0 " + Site.userAgentTag]
        http = URLSession(configuration: config)
    }

    // MARK: Calls (the website's and the Android app's)

    func status() async throws -> Status { try await get("/api/status") }
    func authOptions() async throws -> AuthOptions { try await get("/api/auth-options") }
    func signInWithPassword(_ id: String, _ password: String) async throws -> LoginReply {
        try await post("/api/login/password", ["id": id, "password": password])
    }
    func signInWithKey(_ key: String) async throws -> LoginReply { try await post("/api/login", ["key": key]) }
    func twoStep(ticket: String, code: String) async throws -> LoginReply { try await post("/api/login/mfa", ["ticket": ticket, "code": code]) }
    func emailCode(_ email: String) async throws { let _: Empty = try await post("/api/login/email/start", ["email": email]) }
    func emailSignIn(_ email: String, code: String) async throws -> LoginReply {
        try await post("/api/login/email/verify", ["email": email, "code": code])
    }
    func signOut() async {
        _ = try? await post("/api/logout", [:]) as Empty
        session.forget()
    }
    func state(model: String? = nil) async throws -> AppState {
        try await get("/api/state" + (model.map { "?model=" + ($0.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? $0) } ?? ""))
    }
    func chat(_ id: Int64) async throws -> Chat { try await get("/api/chats/\(id)") }
    func newChat(isPrivate: Bool = false, skill: String = "") async throws -> Int64 {
        var body: [String: Any] = [:]
        if isPrivate { body["private"] = true }
        if !skill.isEmpty { body["skill"] = skill }
        let made: NewChat = try await post("/api/chats", body)
        return made.id
    }
    func stop(_ id: Int64) async { _ = try? await post("/api/chats/\(id)/stop", [:]) as Empty }

    // Chats: pin, archive, delete, search, edit, branch, feedback (the same calls as android/.../data/ApiClient.kt)
    func pin(_ id: Int64, _ pinned: Bool) async throws { let _: Empty = try await post("/api/chats/\(id)/pin", ["pinned": pinned]) }
    func archive(_ id: Int64, _ on: Bool) async throws { let _: Empty = try await post("/api/chats/\(id)/archive", ["archived": on]) }
    func archived() async throws -> [ChatSummary] { try await get("/api/chats/archived", as: ChatList.self).chats }
    func deleteChat(_ id: Int64) async throws { let _: Empty = try await call(makeRequest("/api/chats/\(id)", method: "DELETE")) }
    func search(_ q: String) async throws -> [SearchHit] {
        try await get("/api/chats/search?q=" + (q.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? q), as: SearchReply.self).results
    }
    func editMessage(_ chatId: Int64, _ messageId: Int64, _ text: String) async throws {
        let _: Empty = try await post("/api/chats/\(chatId)/messages/\(messageId)/edit", ["text": text])
    }
    func branch(_ chatId: Int64, _ messageId: Int64) async throws -> Int64 {
        try await post("/api/chats/\(chatId)/branch", ["message_id": messageId], as: NewChat.self).id
    }
    /// "Right answer": the server keeps the notes it used. Returns how many were saved.
    func like(_ chatId: Int64, _ messageId: Int64) async throws -> Int {
        try await post("/api/chats/\(chatId)/messages/\(messageId)/like", [:], as: LikeReply.self).saved
    }
    func report(_ chatId: Int64, _ messageId: Int64, kind: String, note: String) async throws {
        let _: Empty = try await post("/api/chats/\(chatId)/messages/\(messageId)/feedback", ["kind": kind, "note": note])
    }
    func compact(_ chatId: Int64, model: String) async throws -> Ctx? {
        try await post("/api/chats/\(chatId)/compact", ["model": model], as: CompactReply.self).context
    }

    // Sharing and saving
    func shares() async throws -> Shares { try await get("/api/shares") }
    func share(_ chatId: Int64, days: Int) async throws -> ShareMade { try await post("/api/chats/\(chatId)/share", ["days": days]) }
    func revokeShare(_ id: String) async throws { let _: Empty = try await post("/api/shares/revoke", ["id": id]) }
    /// The text as a PDF, Word or Markdown file made on the server: its bytes.
    func exportDoc(text: String, format: String, title: String) async throws -> Data {
        try await bytes(makeRequest("/api/export-doc", body: ["text": text, "format": format, "title": title]))
    }

    // Memory, files, skills and settings
    func memory() async throws -> MemoryList { try await get("/api/memory") }
    func memoryAdd(_ text: String) async throws -> MemoryList { try await post("/api/memory/add", ["text": text]) }
    func memoryDelete(_ id: Int64) async throws { let _: Empty = try await post("/api/memory/delete", ["id": id]) }
    func memoryClear() async throws { let _: Empty = try await post("/api/memory/clear", [:]) }
    func documents() async throws -> DocList { try await get("/api/documents") }
    func deleteDocument(_ id: Int64) async throws { let _: Empty = try await call(makeRequest("/api/documents/\(id)", method: "DELETE")) }
    func skills() async throws -> [Skill] { try await get("/api/skills", as: SkillList.self).skills }
    func settings() async throws -> SettingsData { try await get("/api/settings") }
    /// Changes only what [body] names; the server checks each value and sends back all the settings.
    func saveSettings(_ body: [String: Any]) async throws -> SettingsData { try await post("/api/settings", body) }

    // Pictures and files
    /// A picture or file for the chat: uploaded once (the bytes as Base64, as the website does), then attached with [setChatDocs].
    func upload(name: String, data: Data) async throws -> DocInfo {
        try await post("/api/documents", ["name": name, "data": data.base64EncodedString()])
    }
    /// Attaches exactly these uploaded files to the chat and returns the resulting list.
    func setChatDocs(_ chatId: Int64, _ ids: [Int64]) async throws -> [DocInfo] {
        try await post("/api/chats/\(chatId)/docs", ["ids": ids], as: DocsReply.self).docs
    }
    /// The bytes of a picture that went with a message, for the thread; nil when it cannot be loaded (a broken picture just does not show).
    func picture(_ id: Int64) async -> Data? { try? await bytes(makeRequest("/api/documents/\(id)/image")) }

    /// Sends a message and reads the reply as it is written (server-sent events).
    func send(chatId: Int64, text: String, model: String, effort: String, regenerate: Bool = false, regenMode: String? = nil,
              cont: Bool = false, research: Bool = false) -> AsyncThrowingStream<ReplyEvent, Error> {
        var body: [String: Any] = ["text": text, "model": model, "effort": effort]
        if regenerate { body["regenerate"] = true }               // write the last reply again
        if let m = regenMode { body["regen_mode"] = m }
        if cont { body["continue"] = true }
        if research { body["research"] = true }                   // chat_research: search the web several ways and write a report
        let request = makeRequest("/api/chats/\(chatId)/send", body: body)
        return AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let (bytes, response) = try await http.bytes(for: request)
                    try await check(response) { var d = Data(); for try await b in bytes { d.append(b) }; return d }
                    var parser = SseParser()
                    var line = Data()
                    // Lines by hand: a blank line ends an event, and AsyncBytes.lines would skip it.
                    for try await b in bytes {
                        if b == UInt8(ascii: "\n") {
                            let text = String(decoding: line, as: UTF8.self).trimmingCharacters(in: CharacterSet(charactersIn: "\r"))
                            if let ev = parser.feed(text) { continuation.yield(ev) }
                            line.removeAll(keepingCapacity: true)
                        } else {
                            line.append(b)
                        }
                    }
                    if let ev = parser.feed("") { continuation.yield(ev) }
                    continuation.finish()
                } catch let e as URLError {
                    continuation.finish(throwing: e.code == .cancelled ? CancellationError() : ApiError.offline)
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    // MARK: Plumbing

    private struct Empty: Decodable {}
    private struct ChatList: Decodable { var chats: [ChatSummary] = []
        init(from d: Decoder) throws { chats = (try d.container(keyedBy: AnyKey.self)).value("chats") ?? [] } }
    private struct SearchReply: Decodable { var results: [SearchHit] = []
        init(from d: Decoder) throws { results = (try d.container(keyedBy: AnyKey.self)).value("results") ?? [] } }
    private struct SkillList: Decodable { var skills: [Skill] = []
        init(from d: Decoder) throws { skills = (try d.container(keyedBy: AnyKey.self)).value("skills") ?? [] } }
    private struct DocsReply: Decodable { var docs: [DocInfo] = []
        init(from d: Decoder) throws { docs = (try d.container(keyedBy: AnyKey.self)).value("docs") ?? [] } }
    private struct LikeReply: Decodable { var saved = 0
        init(from d: Decoder) throws { saved = Int((try d.container(keyedBy: AnyKey.self)).int("saved") ?? 0) } }
    private struct CompactReply: Decodable { var context: Ctx?
        init(from d: Decoder) throws { context = (try d.container(keyedBy: AnyKey.self)).value("context") } }

    private func get<T: Decodable>(_ path: String) async throws -> T { try await call(makeRequest(path)) }
    private func get<T: Decodable>(_ path: String, as: T.Type) async throws -> T { try await call(makeRequest(path)) }
    private func post<T: Decodable>(_ path: String, _ body: [String: Any]) async throws -> T { try await call(makeRequest(path, body: body)) }
    private func post<T: Decodable>(_ path: String, _ body: [String: Any], as: T.Type) async throws -> T { try await call(makeRequest(path, body: body)) }

    /// The raw bytes of an answer (a picture, a saved document).
    private func bytes(_ request: URLRequest) async throws -> Data {
        let data: Data, response: URLResponse
        do { (data, response) = try await http.data(for: request) } catch { throw ApiError.offline }
        try await check(response) { data }
        return data
    }

    private func makeRequest(_ path: String, body: [String: Any]? = nil, method: String? = nil) -> URLRequest {
        var r = URLRequest(url: URL(string: path, relativeTo: base)!)
        if let method { r.httpMethod = method }
        if let body {
            r.httpMethod = "POST"
            r.setValue("application/json", forHTTPHeaderField: "Content-Type")
            r.httpBody = try? JSONSerialization.data(withJSONObject: body)
        }
        if let c = session.cookie { r.setValue("\(c.name)=\(c.value)", forHTTPHeaderField: "Cookie") }
        return r
    }

    private func call<T: Decodable>(_ request: URLRequest) async throws -> T {
        let data: Data, response: URLResponse
        do { (data, response) = try await http.data(for: request) } catch { throw ApiError.offline }
        try await check(response) { data }
        return try JSONDecoder().decode(T.self, from: data.isEmpty ? Data("{}".utf8) : data)
    }

    /// Keeps a new session cookie, and turns a failed answer into the right error: offline when the tunnel answered for a PC that is off.
    private func check(_ response: URLResponse, body: () async throws -> Data) async throws {
        guard let r = response as? HTTPURLResponse else { throw ApiError.offline }
        if let url = r.url, let fields = r.allHeaderFields as? [String: String] {
            HTTPCookie.cookies(withResponseHeaderFields: fields, for: url).forEach(session.save)
        }
        guard !(200..<300).contains(r.statusCode) else { return }
        let text = (try? await body()) ?? Data()
        if let e = try? JSONDecoder().decode(ErrorBody.self, from: text), !e.code.isEmpty {
            throw ApiError.server(http: r.statusCode, code: e.code, message: e.message, action: e.action)
        }
        if [502, 503, 504, 530].contains(r.statusCode) { throw ApiError.offline }
        throw ApiError.server(http: r.statusCode, code: "http_\(r.statusCode)", message: "Something went wrong (\(r.statusCode)).", action: "")
    }
}
