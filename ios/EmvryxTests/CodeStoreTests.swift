import SwiftUI
import XCTest
@testable import Emvryx

/// Answers the app's calls with a script, so VryxCode's live parts (steps, permission questions, steering, stopping) can be checked
/// without an agent: the demo server has no model and never takes a step.
final class ScriptedServer: URLProtocol {
    static var sent: [(path: String, body: [String: Any])] = []
    static var views: [[String: Any]] = []              // the answers to the session polls, in order (the last repeats)
    static var served = 0
    static let lock = NSLock()

    static func reset(views: [[String: Any]]) { lock.lock(); sent = []; Self.views = views; served = 0; lock.unlock() }
    static func posts(to suffix: String) -> [[String: Any]] { lock.lock(); defer { lock.unlock() }; return sent.filter { $0.path.hasSuffix(suffix) }.map(\.body) }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let path = request.url?.path ?? ""
        var body: [String: Any] = [:]
        if let stream = request.httpBodyStream {
            stream.open(); var data = Data(); var buf = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable { let n = stream.read(&buf, maxLength: buf.count); if n <= 0 { break }; data.append(buf, count: n) }
            stream.close(); body = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
        } else if let data = request.httpBody { body = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:] }
        Self.lock.lock()
        var answer: [String: Any] = [:]
        if request.httpMethod == "POST" { Self.sent.append((path, body)) }
        if path.hasSuffix("/api/code/start") { answer = ["id": "s1", "queued": false] }
        else if path.hasPrefix("/api/code/sessions/s1") && request.httpMethod == "GET" {
            answer = Self.views[min(Self.served, Self.views.count - 1)]
            Self.served += 1
        }
        Self.lock.unlock()
        let data = try! JSONSerialization.data(withJSONObject: answer)
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

@MainActor
final class CodeStoreTests: XCTestCase {
    private func store() -> CodeStore {
        let base = URL(string: "http://scripted.test")!
        return CodeStore(api: ApiClient(base: base, protocolClasses: [ScriptedServer.self]), onSignedOut: {})
    }
    private func row(_ id: String = "s1") -> CodeSessionRow {
        try! JSONDecoder().decode(CodeSessionRow.self, from: Data(#"{"id":"\#(id)","title":"Zebra game","project":"zebra","state":"working"}"#.utf8))
    }
    private func eventually(_ what: String, timeout: TimeInterval = 10, _ check: () -> Bool) async {
        let end = Date().addingTimeInterval(timeout)
        while Date() < end { if check() { return }; try? await Task.sleep(nanoseconds: 50_000_000) }
        XCTFail("never: \(what)")
    }

    func testAPermissionQuestionIsShownAndAnswered() async {
        ScriptedServer.reset(views: [
            ["state": "asking", "full": true, "events": [["kind": "user", "text": "Make a zebra game", "turn": 1], ["kind": "step", "tool": "read_file"]],
             "pending": ["id": 7, "kind": "ask", "tool": "write_file", "preview": "index.html"]],
            ["state": "done", "full": true, "events": [["kind": "result", "text": "ok"], ["kind": "end", "finished": true, "summary": "Done."]], "pending": NSNull()],
        ])
        let s = store()
        s.open(row())
        await eventually("the question shows") { s.pending?.int("id") == 7 }
        XCTAssertEqual(s.events.map(\.kind), ["user", "step"])
        XCTAssertEqual(s.state, "asking")
        XCTAssertTrue(s.working)

        s.answer(allow: true, always: true)
        await eventually("the answer was sent") { !ScriptedServer.posts(to: "/answer").isEmpty }
        let body = ScriptedServer.posts(to: "/answer")[0]
        XCTAssertEqual(body["id"] as? Int, 7)
        XCTAssertEqual(body["allow"] as? Bool, true)
        XCTAssertEqual(body["always"] as? Bool, true)
        await eventually("it finishes") { s.state == "done" }
        XCTAssertNil(s.pending)
        XCTAssertEqual(s.events.last?.kind, "end")
        XCTAssertFalse(s.working)
        s.stopPolling()
    }

    func testAMultipleChoiceAnswerCarriesTheChoice() async {
        ScriptedServer.reset(views: [["state": "asking", "full": true, "events": [], "pending": ["id": 3, "kind": "choose", "question": "Which?", "options": ["A", "B"]]]])
        let s = store()
        s.open(row())
        await eventually("the question shows") { s.pending?.int("id") == 3 }
        XCTAssertEqual(s.pending?.strings("options"), ["A", "B"])
        s.choose("  B ")
        await eventually("sent") { !ScriptedServer.posts(to: "/answer").isEmpty }
        XCTAssertEqual(ScriptedServer.posts(to: "/answer")[0]["choice"] as? String, "B")
        s.stopPolling()
    }

    func testAMessageWhileTheFullAgentWorksSteersIt() async {
        ScriptedServer.reset(views: [["state": "working", "full": true, "events": [["kind": "user", "text": "Make a zebra game"]]]])
        let s = store()
        s.open(row())
        await eventually("working and full") { s.working && s.full }
        s.send("use blue")
        await eventually("steered") { !ScriptedServer.posts(to: "/steer").isEmpty }
        XCTAssertEqual(ScriptedServer.posts(to: "/steer")[0]["text"] as? String, "use blue")
        XCTAssertTrue(ScriptedServer.posts(to: "/message").isEmpty, "a nudge is not a new message")
        s.stopPolling()
    }

    func testAMessageToAFinishedSessionIsTheNextMessage() async {
        ScriptedServer.reset(views: [["state": "done", "full": false, "events": []]])
        let s = store()
        s.mode = "plan"
        s.open(row())
        await eventually("done") { s.state == "done" }
        s.send("add a score")
        await eventually("sent") { !ScriptedServer.posts(to: "/message").isEmpty }
        let b = ScriptedServer.posts(to: "/message")[0]
        XCTAssertEqual(b["text"] as? String, "add a score")
        XCTAssertEqual(b["plan"] as? Bool, true)
        XCTAssertEqual(b["auto_edits"] as? Bool, false)
        XCTAssertNotNil(b["effort"])
        s.stopPolling()
    }

    func testANewTaskGetsItsOwnProject() async {
        ScriptedServer.reset(views: [["state": "done", "events": []]])
        let s = store()
        s.mode = "auto"
        s.send("Please can you build me a pomodoro timer, with sounds")
        await eventually("started") { !ScriptedServer.posts(to: "/api/code/start").isEmpty }
        let b = ScriptedServer.posts(to: "/api/code/start")[0]
        XCTAssertEqual(b["project"] as? String, "pomodoro-timer")
        XCTAssertEqual(b["task"] as? String, "Please can you build me a pomodoro timer, with sounds")
        XCTAssertEqual(b["queue"] as? Bool, true)
        XCTAssertEqual(b["auto_edits"] as? Bool, true)
        XCTAssertEqual(b["env"] as? String, "local")
        XCTAssertEqual(s.sid, "s1")
        s.stopPolling()
    }

    func testStopAsksTheServerToStop() async {
        ScriptedServer.reset(views: [["state": "working", "events": []]])
        let s = store()
        s.open(row())
        await eventually("working") { s.working }
        s.stop()
        await eventually("stop sent") { !ScriptedServer.posts(to: "/stop").isEmpty }
        XCTAssertTrue(s.stopping)
        s.stopPolling()
    }

    /// One of each kind of event, drawn, to look at (and to be sure none of them crashes).
    func testEveryKindOfEventDraws() throws {
        let events: [[String: Any]] = [
            ["kind": "user", "text": "Make a zebra game"],
            ["kind": "language", "text": "Suggested language: HTML, CSS and JavaScript."],
            ["kind": "step", "tool": "write_file", "label": "index.html", "secs": 3.2, "words": 1234, "preview": "<html>zebra</html>"],
            ["kind": "result", "text": "wrote 214 bytes"],
            ["kind": "retry", "why": "the test failed, trying again"],
            ["kind": "model", "model": "Equinox 3"],
            ["kind": "end", "finished": true, "summary": "Built it.\n\n```\nopen index.html\n```", "next": ["Add a score"]],
        ]
        let view = VStack(alignment: .leading, spacing: 10) {
            ForEach(Array(events.enumerated()), id: \.offset) { i, raw in CodeEventPreview.row(CodeEvent(id: i, raw: raw), events.enumerated().map { CodeEvent(id: $0.offset, raw: $0.element) }) }
        }
        .padding(16).frame(width: 390).background(Emvryx.bg).environment(\.palette, .brand).preferredColorScheme(.dark)
        // Drawn in a real window (ImageRenderer leaves scrolling views, like code blocks, blank).
        let host = UIHostingController(rootView: view)
        let window = UIWindow(frame: CGRect(x: 0, y: 0, width: 390, height: 760))
        window.windowScene = UIApplication.shared.connectedScenes.first as? UIWindowScene
        window.rootViewController = host
        window.isHidden = false
        host.view.frame = window.bounds
        host.view.layoutIfNeeded()
        RunLoop.main.run(until: Date().addingTimeInterval(0.5))
        let png = try XCTUnwrap(UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }.pngData())
        window.isHidden = true
        if let dir = ProcessInfo.processInfo.environment["EMVRYX_SHOTS"], !dir.isEmpty {
            try png.write(to: URL(fileURLWithPath: dir).appendingPathComponent("code-events.png"))
        }
        XCTAssertGreaterThan(png.count, 1000)
    }
}
