import XCTest
@testable import Emvryx

/// The same cases as android/app/src/test/.../SseParserTest.kt, so both apps read a streamed reply the same way.
final class SseParserTests: XCTestCase {
    /// Feeds a whole text, one line at a time, with a blank line at the end so the last event is closed.
    private func parse(_ text: String) -> [ReplyEvent] {
        var p = SseParser()
        return (text.components(separatedBy: "\n") + [""]).compactMap { p.feed($0) }
    }

    func testAWholeReplyAsTheServerSendsIt() {
        let events = parse("""
            event: thinking
            data: {"min_first_s": 0.48, "effort": "balanced", "auto": false, "reason": "", "temperature": null}

            : keep-alive
            event: loading
            data: {"model": "solstice-2"}

            event: piece
            data: {"t": "Hello"}

            event: piece
            data: {"t": " there"}

            event: done
            data: {"reason": "stop", "message_id": 7, "title": "Greetings", "cut": false, "usage": {"plan": "pro"}}
            """)
        XCTAssertEqual(events, [
            .thinking(effort: "balanced", auto: false),
            .loading(model: "solstice-2"),
            .piece("Hello"),
            .piece(" there"),
            .done(title: "Greetings", messageId: 7, cut: false, usage: Usage()),
        ])
    }

    func testAnErrorPartWay() {
        let events = parse("event: error\ndata: {\"code\": \"timeout\", \"message\": \"The model took too long.\", \"action\": \"Try again.\", \"http\": 504}\n")
        XCTAssertEqual(events, [.failed(code: "timeout", message: "The model took too long.", action: "Try again.")])
    }

    func testPiecesKeepTheirSpacesAndNewlines() {
        XCTAssertEqual(parse("event: piece\ndata: {\"t\": \"  two spaces\\nand a line\"}\n"), [.piece("  two spaces\nand a line")])
    }

    func testKeepAlivesAndBlankLinesAloneMakeNothing() {
        var p = SseParser()
        XCTAssertNil(p.feed(": keep-alive"))
        XCTAssertNil(p.feed(""))
        XCTAssertNil(p.feed(""))
    }

    func testAnUnknownEventIsPassedOnByName() {
        XCTAssertEqual(parse("event: something_new\ndata: {\"used\": 3}\n"), [.other("something_new")])
    }

    func testDeepResearchStepsAreReadOneByOne() {
        XCTAssertEqual(parse("event: research\ndata: {\"step\": \"Searching: tallest mountains\", \"done\": 2, \"of\": 7}\n"),
                       [.research(step: "Searching: tallest mountains", done: 2, of: 7)])
    }

    func testStateReadsWithDefaultsAndZeroOneFlags() throws {
        let json = #"""
            {"user": "sam", "plan": "pro", "models": {"cards": [{"id": "flare-3", "name": "Flare", "version": 3, "state": "ready"}]},
             "model": "flare-3", "chats": [{"id": 4, "title": "Hi", "pinned": 1}], "features": {"ios_native": true},
             "usage": {"exempt": false, "can_send": 397, "tank": {"pct": 99.5}, "week": {"pct_left": 100}}, "something_new": [1]}
            """#
        let s = try JSONDecoder().decode(AppState.self, from: Data(json.utf8))
        XCTAssertEqual(s.planName, "Pro plan")
        XCTAssertEqual(s.models.cards.first?.fullName, "Flare 3")
        XCTAssertEqual(s.chats.first?.pinned, true)
        XCTAssertTrue(s.on("ios_native"))
        XCTAssertFalse(s.on("missing"))
        XCTAssertEqual(s.usage?.label, "Usage: 99.5% · about 397 messages left")
    }
}
