import XCTest
@testable import Emvryx

/// VryxCode's rules that run on the phone: the same cases as android/app/src/test/.../CodeProjectsTest.kt.
final class CodeTests: XCTestCase {
    func testAProjectNameComesFromTheIdea() {
        XCTAssertEqual(ideaName("A bill splitter with tip and people"), "bill-splitter")
        XCTAssertEqual(ideaName("Please can you build me a pomodoro timer, with sounds"), "pomodoro-timer")
        XCTAssertEqual(ideaName("Make a landing page for my bakery"), "landing-page")
        XCTAssertEqual(ideaName("!!!"), "new-project")
        XCTAssertEqual(ideaName("one two three four five six"), "one-two-three-four")
    }

    func testATakenNameGetsANumber() {
        XCTAssertEqual(freeName("snake", ["a", "b"]), "snake")
        XCTAssertEqual(freeName("snake", ["snake"]), "snake-2")
        XCTAssertEqual(freeName("snake", ["snake", "snake-2"]), "snake-3")
    }

    func testEventsAreReadSafely() {
        let e = CodeEvent(id: 1, raw: ["kind": "step", "tool": "write_file", "secs": 3.4, "words": 1200, "ok": true, "next": ["a", "b"]])
        XCTAssertEqual(e.kind, "step")
        XCTAssertEqual(e.str("tool"), "write_file")
        XCTAssertEqual(e.int("words"), 1200)
        XCTAssertEqual(e.num("secs"), 3.4)
        XCTAssertTrue(e.bool("ok"))
        XCTAssertEqual(e.strings("next"), ["a", "b"])
        XCTAssertEqual(e.str("missing"), "")
        XCTAssertEqual(e.int("missing"), 0)
        XCTAssertFalse(e.bool("missing"))
    }

    func testAViewOfASessionReadsItsState() {
        let v = CodeView(json: ["state": "asking", "full": true, "events": [["kind": "user"]], "pending": ["id": 4, "tool": "write_file"]])
        XCTAssertTrue(v.working)
        XCTAssertTrue(v.full)
        XCTAssertEqual(v.events.count, 1)
        XCTAssertEqual(v.pending?["id"] as? Int, 4)
        XCTAssertFalse(CodeView(json: ["state": "done"]).working)
    }
}
