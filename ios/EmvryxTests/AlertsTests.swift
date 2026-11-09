import XCTest
@testable import Emvryx

/// A chat server that answers from a script: the state, a new chat, a reply that can be cut off half way (as iOS does to an app that goes to the
/// background), and the chat read back while it is still being written and then finished.
final class ChatScript: URLProtocol {
    static let lock = NSLock()
    static var cutOff = false                // the reply stops after its first piece with the connection lost
    static var reads: [[String: Any]] = []   // answers to GET /api/chats/9, in order (the last repeats)
    static var served = 0
    static var features: [String: Bool] = ["phone_alerts": true, "ios_native": true]

    static func reset() {
        lock.lock(); defer { lock.unlock() }
        cutOff = false; served = 0; features = ["phone_alerts": true, "ios_native": true]
        reads = [["id": 9, "title": "Zebras", "generating": false, "messages": [["id": 1, "role": "user", "content": "Tell me"], ["id": 2, "role": "assistant", "content": "Hello there, all done."]]]]
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let path = request.url?.path ?? ""
        Self.lock.lock()
        defer { Self.lock.unlock() }
        func send(_ data: Data, code: Int = 200) {
            client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: code, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        }
        func json(_ o: Any) -> Data { try! JSONSerialization.data(withJSONObject: o) }
        switch path {
        case "/api/status": send(json(["up": true]))
        case "/api/state":
            send(json(["user": "sam", "plan": "pro", "model": "flare-3", "features": Self.features, "chats": [],
                       "models": ["cards": [["id": "flare-3", "name": "Flare", "version": 3, "state": "ready"]]], "efforts": [["id": "balanced", "name": "Balanced"]]]))
        case "/api/chats" where request.httpMethod == "POST": send(json(["id": 9]))
        case "/api/chats/9/send":
            client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: ["Content-Type": "text/event-stream"])!, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: Data("event: piece\ndata: {\"t\": \"Hello\"}\n\n".utf8))
            if Self.cutOff { client?.urlProtocol(self, didFailWithError: URLError(.networkConnectionLost)); return }
            client?.urlProtocol(self, didLoad: Data("event: piece\ndata: {\"t\": \" there, all done.\"}\n\nevent: done\ndata: {\"title\": \"Zebras\", \"message_id\": 2, \"cut\": false}\n\n".utf8))
            client?.urlProtocolDidFinishLoading(self)
        case "/api/chats/9":
            send(json(Self.reads[min(Self.served, Self.reads.count - 1)]))
            Self.served += 1
        default: send(json(["code": "nope", "message": "no"]), code: 404)
        }
    }
    override func stopLoading() {}
}

final class SpyAlerts: AlertSink {
    var calls: [(id: Int64, title: String, text: String)] = []
    var prepared = 0
    func prepare() async { prepared += 1 }
    func chatAnswered(id: Int64, title: String, text: String) { calls.append((id, title, text)) }
}

@MainActor
final class AlertsTests: XCTestCase {
    private let server = URL(string: "http://chat-\(UUID().uuidString.prefix(8)).test")!

    override func setUp() { ChatScript.reset() }

    private func model(active: Bool, spy: SpyAlerts) async -> AppModel {
        let session = SessionStore(server: server)
        session.save(HTTPCookie(properties: [.name: "emvryx_session", .value: "x", .domain: server.host!, .path: "/", .expires: Date().addingTimeInterval(3600)])!)
        let m = AppModel(api: ApiClient(base: server, session: session, protocolClasses: [ChatScript.self]))
        m.alerts = spy
        m.isActive = { active }
        m.start()
        await eventually("signed in and in the chat") { m.screen == .chat }
        return m
    }

    private func eventually(_ what: String, timeout: TimeInterval = 15, _ check: () -> Bool) async {
        let end = Date().addingTimeInterval(timeout)
        while Date() < end { if check() { return }; try? await Task.sleep(nanoseconds: 50_000_000) }
        XCTFail("never: \(what)")
    }

    func testAnAnswerThatArrivesWhileTheAppIsAwayIsAnnounced() async {
        let spy = SpyAlerts()
        let m = await model(active: false, spy: spy)
        m.send("Tell me")
        await eventually("the alert") { !spy.calls.isEmpty }
        XCTAssertEqual(spy.calls.count, 1)
        XCTAssertEqual(spy.calls[0].id, 9)
        XCTAssertEqual(spy.calls[0].title, "Zebras")
        XCTAssertEqual(spy.calls[0].text, "Hello there, all done.")
        XCTAssertEqual(spy.prepared, 1, "iOS is asked for permission once the first answer is on its way")
    }

    func testNothingIsAnnouncedWhileTheAppIsInFront() async {
        let spy = SpyAlerts()
        let m = await model(active: true, spy: spy)
        m.send("Tell me")
        await eventually("finished") { !m.streaming && m.bubbles.last?.text == "Hello there, all done." }
        XCTAssertTrue(spy.calls.isEmpty)
    }

    func testAPrivateChatIsNeverAnnounced() async {
        let spy = SpyAlerts()
        let m = await model(active: false, spy: spy)
        m.newChat(isPrivate: true)
        m.send("Tell me")
        await eventually("finished") { !m.streaming && m.bubbles.last?.text == "Hello there, all done." }
        XCTAssertTrue(spy.calls.isEmpty)
        XCTAssertEqual(spy.prepared, 0)
    }

    func testTheSwitchOffMeansNoAlerts() async {
        ChatScript.features["phone_alerts"] = false
        let spy = SpyAlerts()
        let m = await model(active: false, spy: spy)
        m.send("Tell me")
        await eventually("finished") { !m.streaming && m.bubbles.last?.text == "Hello there, all done." }
        XCTAssertTrue(spy.calls.isEmpty)
    }

    func testAReplyCutOffInTheBackgroundIsReadBackWhenItIsFinished() async {
        ChatScript.cutOff = true
        ChatScript.reads = [
            ["id": 9, "title": "Zebras", "generating": true, "messages": [["id": 1, "role": "user", "content": "Tell me"], ["id": 2, "role": "assistant", "content": "Hello there,"]]],
            ["id": 9, "title": "Zebras", "generating": false, "messages": [["id": 1, "role": "user", "content": "Tell me"], ["id": 2, "role": "assistant", "content": "Hello there, all done."]]],
        ]
        let spy = SpyAlerts()
        let m = await model(active: false, spy: spy)
        m.send("Tell me")
        await eventually("the cut-off reply is finished from the server") { !m.streaming && m.bubbles.last?.text == "Hello there, all done." }
        XCTAssertNil(m.failure, "a dropped connection while a reply is written is not an error to show")
        XCTAssertEqual(m.bubbles.map(\.mine), [true, false])
        XCTAssertEqual(spy.calls.count, 1)
        XCTAssertEqual(spy.calls[0].text, "Hello there, all done.")
    }

    func testTheSnippetIsOneShortLine() {
        XCTAssertEqual(LocalAlerts.snippet("  Hello \n\n there \t world  "), "Hello there world")
        let long = LocalAlerts.snippet(String(repeating: "word ", count: 100))
        XCTAssertEqual(long.count, 141)
        XCTAssertTrue(long.hasSuffix("…"))
    }
}
