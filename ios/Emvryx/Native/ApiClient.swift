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
    func newChat(isPrivate: Bool = false) async throws -> Int64 {
        let made: NewChat = try await post("/api/chats", isPrivate ? ["private": true] : [:])
        return made.id
    }
    func stop(_ id: Int64) async { _ = try? await post("/api/chats/\(id)/stop", [:]) as Empty }

    /// Sends a message and reads the reply as it is written (server-sent events).
    func send(chatId: Int64, text: String, model: String, effort: String) -> AsyncThrowingStream<ReplyEvent, Error> {
        let request = makeRequest("/api/chats/\(chatId)/send", body: ["text": text, "model": model, "effort": effort])
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

    private func get<T: Decodable>(_ path: String) async throws -> T { try await call(makeRequest(path)) }
    private func post<T: Decodable>(_ path: String, _ body: [String: Any]) async throws -> T { try await call(makeRequest(path, body: body)) }

    private func makeRequest(_ path: String, body: [String: Any]? = nil) -> URLRequest {
        var r = URLRequest(url: URL(string: path, relativeTo: base)!)
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
