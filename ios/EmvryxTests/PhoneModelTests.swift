import CryptoKit
import XCTest
@testable import Emvryx

/// Plays the PC for the phone model: the kit, the model file (with Range, in chunks), and the sync, so the whole path can be checked
/// without a model or a server.
final class PhoneScript: URLProtocol {
    static let lock = NSLock()
    static var file = Data()
    static var kit: [String: Any] = [:]
    static var rangeHeaders: [String?] = []
    static var syncs: [[String: Any]] = []
    static var chats: [Int: [String: Any]] = [:]
    static var ignoreRange = false           // the PC sends the whole file even when a Range was asked
    static var corruptByte = false
    static var syncAnswer = 41

    static func reset(size: Int = 3 * 1024 * 1024 + 123) {
        lock.lock(); defer { lock.unlock() }
        file = Data((0..<size).map { UInt8(truncatingIfNeeded: $0 &* 31 &+ 7) })
        let sum = SHA256.hash(data: file).map { String(format: "%02x", $0) }.joined()
        kit = ["available": true, "id": "flare-3", "name": "Flare", "version": 3, "size": size, "sha256": sum, "preparing": false,
               "file": "/api/phone-model/file?model=flare-3", "context": 4096, "max_reply_tokens": 256, "min_ram_gb": 1,
               "format": ["stop": ["<|im_end|>"]], "sampling": ["temperature": 0.7], "hints": "", "memory": ["on": false, "title": "", "facts": [], "personal": ""],
               "choices": [["id": "flare-3", "name": "Flare", "version": 3, "size": size, "min_ram_gb": 1, "tagline": "Fastest"]]]
        rangeHeaders = []; syncs = []; chats = [:]; ignoreRange = false; corruptByte = false; syncAnswer = 41
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let path = request.url?.path ?? ""
        Self.lock.lock()
        defer { Self.lock.unlock() }
        func send(_ code: Int, _ data: Data, _ headers: [String: String] = [:], chunk: Int = 0) {
            client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: code, httpVersion: nil, headerFields: headers)!, cacheStoragePolicy: .notAllowed)
            if chunk > 0 { var i = 0; while i < data.count { client?.urlProtocol(self, didLoad: data.subdata(in: i..<min(i + chunk, data.count))); i += chunk } }
            else { client?.urlProtocol(self, didLoad: data) }
            client?.urlProtocolDidFinishLoading(self)
        }
        func json(_ o: Any) -> Data { try! JSONSerialization.data(withJSONObject: o) }
        if path == "/api/phone-model" { return send(200, json(Self.kit)) }
        if path == "/api/phone-model/file" {
            let range = request.value(forHTTPHeaderField: "Range")
            Self.rangeHeaders.append(range)
            var bytes = Self.file
            if Self.corruptByte { bytes[bytes.count / 2] ^= 0xFF }
            if let r = range, !Self.ignoreRange, let from = Int(r.replacingOccurrences(of: "bytes=", with: "").replacingOccurrences(of: "-", with: "")) {
                return send(206, bytes.subdata(in: from..<bytes.count), ["Content-Range": "bytes \(from)-\(bytes.count - 1)/\(bytes.count)"], chunk: 64 * 1024)
            }
            return send(200, bytes, chunk: 64 * 1024)
        }
        if path == "/api/phone-sync" {
            var body = Data()
            if let s = request.httpBodyStream { s.open(); var buf = [UInt8](repeating: 0, count: 4096); while s.hasBytesAvailable { let n = s.read(&buf, maxLength: buf.count); if n <= 0 { break }; body.append(buf, count: n) }; s.close() }
            Self.syncs.append((try? JSONSerialization.jsonObject(with: body)) as? [String: Any] ?? [:])
            return send(200, json(["chat": Self.syncAnswer]))
        }
        if let m = path.range(of: #"^/api/chats/(\d+)$"#, options: .regularExpression), let id = Int(path[m].split(separator: "/").last!) , let chat = Self.chats[id] {
            return send(200, json(chat))
        }
        send(404, json(["code": "nope", "message": "no"]))
    }
    override func stopLoading() {}
}

@MainActor
final class PhoneModelTests: XCTestCase {
    private var dir: URL!
    private var defaults: UserDefaults!

    override func setUp() {
        PhoneScript.reset()
        dir = FileManager.default.temporaryDirectory.appendingPathComponent("phone-\(UUID().uuidString)")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defaults = UserDefaults(suiteName: "phone-test-\(UUID().uuidString)")!
    }
    override func tearDown() { try? FileManager.default.removeItem(at: dir) }

    private func phone(engine: LocalEngine = ScriptedEngine()) -> PhoneModel {
        let api = ApiClient(base: URL(string: "http://pc.test")!, protocolClasses: [PhoneScript.self])
        let p = PhoneModel(api: api, directory: dir, defaults: defaults, engine: engine)
        p.rememberAllowed(true)
        return p
    }
    private func eventually(_ what: String, timeout: TimeInterval = 20, _ check: () -> Bool) async {
        let end = Date().addingTimeInterval(timeout)
        while Date() < end { if check() { return }; try? await Task.sleep(nanoseconds: 50_000_000) }
        XCTFail("never: \(what)")
    }
    private func done(_ p: PhoneModel) async {
        await eventually("the download ends") { if case .downloading = p.status { return false }; return p.status != .checking }
    }

    func testTheModelIsDownloadedCheckedAndKept() async {
        let p = phone()
        p.download()
        await eventually("ready") { p.status == .ready }
        XCTAssertTrue(p.ready)
        XCTAssertEqual(p.kit?.fullName, "Flare 3")
        XCTAssertEqual(try? Data(contentsOf: dir.appendingPathComponent("model.gguf")), PhoneScript.file)
        XCTAssertFalse(FileManager.default.fileExists(atPath: dir.appendingPathComponent("model.gguf.part").path))
        XCTAssertEqual(PhoneScript.rangeHeaders.count, 1); XCTAssertNil(PhoneScript.rangeHeaders[0])
        // It is still there for the next start of the app.
        let again = PhoneModel(api: ApiClient(base: URL(string: "http://pc.test")!, protocolClasses: [PhoneScript.self]), directory: dir, defaults: defaults, engine: ScriptedEngine())
        XCTAssertEqual(again.status, .ready)
    }

    func testADownloadThatStoppedCarriesOnWhereItWas() async throws {
        let part = dir.appendingPathComponent("model.gguf.part")
        try PhoneScript.file.prefix(1_000_000).write(to: part)
        defaults.set(PhoneScript.kit["sha256"] as? String, forKey: "emvryx_phone_part_sha")        // the same model as the part
        let p = phone()
        p.download()
        await eventually("ready") { p.status == .ready }
        XCTAssertEqual(PhoneScript.rangeHeaders, ["bytes=1000000-"])
        XCTAssertEqual(try Data(contentsOf: dir.appendingPathComponent("model.gguf")), PhoneScript.file)
    }

    func testAPartOfAnotherModelIsStartedOver() async throws {
        try Data(repeating: 9, count: 500_000).write(to: dir.appendingPathComponent("model.gguf.part"))
        defaults.set("some-other-model", forKey: "emvryx_phone_part_sha")
        let p = phone()
        p.download()
        await eventually("ready") { p.status == .ready }
        XCTAssertEqual(PhoneScript.rangeHeaders.count, 1); XCTAssertNil(PhoneScript.rangeHeaders[0], "a new model is not asked for from a byte offset")
        XCTAssertEqual(try Data(contentsOf: dir.appendingPathComponent("model.gguf")), PhoneScript.file)
    }

    func testThePcSendingEverythingAgainStartsOver() async throws {
        try PhoneScript.file.prefix(700_000).write(to: dir.appendingPathComponent("model.gguf.part"))
        defaults.set(PhoneScript.kit["sha256"] as? String, forKey: "emvryx_phone_part_sha")
        PhoneScript.ignoreRange = true
        let p = phone()
        p.download()
        await eventually("ready") { p.status == .ready }
        XCTAssertEqual(try Data(contentsOf: dir.appendingPathComponent("model.gguf")), PhoneScript.file, "the part was not thrown away")
    }

    func testADamagedDownloadIsRemoved() async {
        PhoneScript.corruptByte = true
        let p = phone()
        p.download()
        await eventually("failed") { if case .failed = p.status { return true }; return false }
        guard case let .failed(message) = p.status else { return }
        XCTAssertTrue(message.contains("damaged"), message)
        XCTAssertFalse(FileManager.default.fileExists(atPath: dir.appendingPathComponent("model.gguf.part").path))
        XCTAssertFalse(p.ready)
    }

    func testAPhoneWithTooLittleMemoryIsToldSo() async {
        PhoneScript.kit["min_ram_gb"] = 99_999
        let p = phone()
        p.download()
        await eventually("failed") { if case .failed = p.status { return true }; return false }
        guard case let .failed(message) = p.status else { return }
        XCTAssertTrue(message.contains("less memory"), message)
        XCTAssertTrue(PhoneScript.rangeHeaders.isEmpty, "nothing was downloaded")
    }

    func testABuildWithoutAnEngineSaysSoBeforeDownloading() async {
        let p = phone(engine: NoEngine())
        p.download()
        await eventually("failed") { if case .failed = p.status { return true }; return false }
        guard case let .failed(message) = p.status else { return }
        XCTAssertTrue(message.contains("no model engine"), message)
        XCTAssertTrue(PhoneScript.rangeHeaders.isEmpty)
    }

    func testAnAnswerStreamsInAndIsKept() async {
        let engine = ScriptedEngine()
        let p = phone(engine: engine)
        p.download()
        await eventually("ready") { p.status == .ready }
        let chat = p.newChat()
        var seen: [String] = []
        let problem = await p.answer(chatId: chat.id, question: "Why is the sky blue") { seen.append($0) }
        XCTAssertNil(problem)
        XCTAssertEqual(p.chats.first?.turns.map(\.text), ["Why is the sky blue", "Phone answer to: Why is the sky blue"])
        XCTAssertEqual(p.chats.first?.title, "Why is the sky blue")
        XCTAssertEqual(seen.last, "Phone answer to: Why is the sky blue")
        XCTAssertEqual(engine.loaded?.hasSuffix("model.gguf"), true)
        // The second question carries the first as history, in the PC's own prompt shape.
        _ = await p.answer(chatId: chat.id, question: "And the sunset") { _ in }
        XCTAssertTrue(engine.prompts[1].contains("<|im_start|>user\nWhy is the sky blue<|im_end|>\n<|im_start|>assistant\nPhone answer to: Why is the sky blue<|im_end|>\n"))
        XCTAssertEqual(p.chats.first?.turns.count, 4)
    }

    func testWhatWasWrittenOnThePhoneIsSentWhenThePcIsBack() async {
        let p = phone()
        p.download()
        await eventually("ready") { p.status == .ready }
        let chat = p.newChat()
        _ = await p.answer(chatId: chat.id, question: "Hello there") { _ in }
        XCTAssertEqual(p.chats[0].pending.count, 2)
        let sent = await p.syncUp()
        XCTAssertEqual(sent, 1)
        let body = PhoneScript.syncs[0]
        XCTAssertEqual(body["title"] as? String, "Hello there")
        XCTAssertEqual(body["model"] as? String, "flare-3")
        XCTAssertEqual((body["messages"] as? [[String: String]])?.map { $0["role"]! }, ["user", "assistant"])
        XCTAssertNotNil(body["sync_id"])
        XCTAssertEqual(p.chats[0].serverId, 41)
        XCTAssertTrue(p.chats[0].pending.isEmpty)
        let again = await p.syncUp()
        XCTAssertEqual(again, 0, "nothing is sent twice")
    }

    func testACopyOfThePcChatCanBeCarriedOnHere() async {
        let p = phone()
        p.download()
        await eventually("ready") { p.status == .ready }
        p.carryOn(serverId: 12, title: "Tides", turns: [LocalTurn(mine: true, text: "why"), LocalTurn(mine: false, text: "moon")], question: "and the sun?")
        XCTAssertEqual(p.chats.count, 1)
        XCTAssertEqual(p.chats[0].serverId, 12)
        XCTAssertEqual(p.openChat, p.chats[0].id)
        XCTAssertEqual(p.ask, "and the sun?")
    }

    func testRecentChatsAreKeptForReadingOffline() async throws {
        PhoneScript.chats[5] = ["id": 5, "title": "Zebras", "messages": [["id": 1, "role": "user", "content": "stripes?"], ["id": 2, "role": "assistant", "content": "camouflage"]]]
        let p = phone()
        await p.keepRecent([ChatSummary(id: 5, title: "Zebras"), ChatSummary(id: -3, title: "private")], force: true)
        XCTAssertEqual(p.chats.count, 1, "a private chat is never copied")
        XCTAssertEqual(p.chats[0].title, "Zebras")
        XCTAssertEqual(p.chats[0].turns.map(\.text), ["stripes?", "camouflage"])
        XCTAssertTrue(p.chats[0].pending.isEmpty)
        // Kept for the next start.
        let again = PhoneModel(api: ApiClient(base: URL(string: "http://pc.test")!, protocolClasses: [PhoneScript.self]), directory: dir, defaults: defaults, engine: ScriptedEngine())
        XCTAssertEqual(again.chats.count, 1)
    }

    func testRemovingTheModelKeepsTheChats() async {
        let p = phone()
        p.download()
        await eventually("ready") { p.status == .ready }
        p.newChat()
        p.remove()
        XCTAssertEqual(p.status, .none)
        XCTAssertFalse(FileManager.default.fileExists(atPath: dir.appendingPathComponent("model.gguf").path))
        XCTAssertEqual(p.chats.count, 1)
    }
}
