import XCTest
@testable import Emvryx

/// VryxCode's newer parts: what the pure functions work out from a session's events (the same cases as Android's CodeParityTest and CodeReviewTest),
/// and what the store sends to the server for Restore, /memory, /permissions, /commands, pictures and documents (against a scripted server).
final class CodeParityTests: XCTestCase {
    private func ev(_ raws: [[String: Any]]) -> [CodeEvent] { raws.enumerated().map { CodeEvent(id: $0.offset, raw: $0.element) } }

    func testThePlanMarksTheFirstUnfinishedStepAsNowOnlyWhileWorking() {
        let todo: [String: Any] = ["kind": "step", "tool": "todo", "preview": #"todo {"items":[{"text":"Write it","done":true},{"text":"Test it","done":false},{"text":"Ship it"}]}"#]
        XCTAssertEqual(planSteps(ev([todo]), working: true).map(\.state), ["done", "now", "todo"])
        XCTAssertEqual(planSteps(ev([todo]), working: false).map(\.state), ["done", "todo", "todo"])
        XCTAssertEqual(planSteps(ev([todo]), working: true).map(\.text), ["Write it", "Test it", "Ship it"])
    }

    func testAPlanThatCannotBeReadIsNoPlan() {
        XCTAssertTrue(planSteps(ev([["kind": "step", "tool": "todo", "preview": "todo not json"]]), working: true).isEmpty)
        XCTAssertTrue(planSteps(ev([["kind": "user", "text": "hi"]]), working: true).isEmpty)
    }

    func testTheNewestPlanWins() {
        let a: [String: Any] = ["kind": "step", "tool": "todo", "preview": #"todo {"items":[{"text":"Old","done":false}]}"#]
        let b: [String: Any] = ["kind": "step", "tool": "todo", "preview": #"todo {"items":[{"text":"New","done":true}]}"#]
        XCTAssertEqual(planSteps(ev([a, b]), working: true).map(\.text), ["New"])
    }

    func testHowAMessageEnded() {
        func end(_ raw: [String: Any]) -> EndState? { endState(CodeEvent(id: 0, raw: raw.merging(["kind": "end"]) { a, _ in a })) }
        XCTAssertEqual(end(["finished": true]), .finished)
        XCTAssertEqual(end(["reason": "steps", "rounds": 5]), .outOfSteps(rounds: 5))
        XCTAssertEqual(end(["said": true]), .waiting)
        XCTAssertNil(end(["said": true, "plan": true]))
        XCTAssertNil(endState(CodeEvent(id: 0, raw: ["kind": "user"])))
    }

    func testTheReviewVerdict() {
        let v = verdictOf(CodeEvent(id: 0, raw: ["kind": "end", "verdict": ["status": "CHANGES", "blocking": 2, "nits": 1, "fix": "Fix it, test first"]]))
        XCTAssertEqual(v, Verdict(approved: false, blocking: 2, nits: 1, fix: "Fix it, test first"))
        XCTAssertEqual(verdictOf(CodeEvent(id: 0, raw: ["verdict": ["status": "APPROVED"]]))?.approved, true)
        XCTAssertNil(verdictOf(CodeEvent(id: 0, raw: ["kind": "end"])))
    }

    func testSuggestedRepliesFollowTheWebsite() {
        XCTAssertTrue(asksYou("Which file should I change?"))
        XCTAssertTrue(asksYou("Done. Let me know if you want more"))
        XCTAssertFalse(asksYou("The tests pass."))
        XCTAssertTrue(isQuestion("Why did it fail"))
        XCTAssertTrue(isQuestion("show me the diff"))
        XCTAssertFalse(isQuestion("Make a zebra game"))
        XCTAssertEqual(waitingReplies("Should I go on?").first, "Yes, go ahead.")
        XCTAssertTrue(waitingReplies("I changed things.").first!.hasPrefix("Please save the fix"))
        XCTAssertEqual(followUps(last: "show me what you changed.", text: "I changed the file").count, 3)
        XCTAssertFalse(followUps(last: "show me what you changed.", text: "I changed the file").contains("Show me what you changed."))
    }

    func testAPlainAnswerToAQuestionIsNotAWaitingBanner() {
        let events = ev([["kind": "user", "text": "Why is it slow?"], ["kind": "end", "said": true, "summary": "It loads every image."]])
        XCTAssertTrue(justAnswered(events[1], events))
        let task = ev([["kind": "user", "text": "Fix the bug"], ["kind": "end", "said": true, "summary": "It loads every image."]])
        XCTAssertFalse(justAnswered(task[1], task))
    }

    func testToolPartsSayWhatWasDoneToWhat() {
        XCTAssertEqual(toolParts(preview: "write main.py\n+ print(1)", tool: "write_file").verb, "Wrote")
        XCTAssertEqual(toolParts(preview: "write main.py\n+ print(1)", tool: "write_file").arg, "main.py")
        XCTAssertEqual(toolParts(preview: "edit a/b.js", tool: "edit_file").verb, "Edited")
        let r = toolParts(preview: #"read_file {"path": "app/page.tsx"}"#, tool: "read_file")
        XCTAssertEqual(r.verb, "Read"); XCTAssertEqual(r.arg, "app/page.tsx")
        XCTAssertEqual(toolParts(preview: String(repeating: "x", count: 120), tool: "run").arg.count, 93)
    }

    func testDiffLinesKeepTheirSign() {
        let d = diffLines("edit a.py\n- old\n+ new\n  same")
        XCTAssertEqual(d.map { String($0.kind) }, ["-", "+", " "])
        XCTAssertEqual(d[1].text, "+ new")
    }

    func testTheReviewFeedTurnsStepsIntoLinesChipsAndASummary() {
        let events = ev([
            ["kind": "user", "text": "Make it"],
            ["kind": "step", "tool": "read_file", "preview": #"read_file {"path": "a.py"}"#, "secs": 3.0],
            ["kind": "result", "text": "contents"],
            ["kind": "step", "tool": "write_file", "preview": "write b.py\n+ x", "add": 4, "del": 1],
            ["kind": "result", "text": "ok"],
            ["kind": "step", "tool": "write_file", "preview": "write c.py\n+ y", "add": 2, "del": 0],
            ["kind": "result", "text": "error: disk full"],
            ["kind": "end", "finished": true, "summary": "Done"],
        ])
        let items = reviewItems(events)
        guard case let .quiet(thought) = items[1], case let .quiet(read) = items[2] else { return XCTFail("quiet lines") }
        XCTAssertEqual(thought.text, "Thought 3s"); XCTAssertEqual(read.text, "Read a.py"); XCTAssertFalse(read.bad)
        guard case let .file(path, add, del, _, bad, _) = items[3] else { return XCTFail("a file chip") }
        XCTAssertEqual([path, "\(add)", "\(del)", "\(bad)"], ["b.py", "4", "1", "false"])
        guard case let .file(_, _, _, _, failed, why) = items[4] else { return XCTFail("the failed chip") }
        XCTAssertTrue(failed); XCTAssertEqual(why, "error: disk full")
        guard case let .done(files) = items[5] else { return XCTFail("the summary comes before the end") }
        XCTAssertEqual(files.map(\.path), ["b.py"], "a change that failed is not counted")
        XCTAssertEqual(items.count, 7)
    }

    func testQuietLinesInARowFoldIntoOne() {
        let items: [ReviewItem] = [.quiet(QuietLine(text: "Thought 3s")), .quiet(QuietLine(text: "Read a.py")), .quiet(QuietLine(text: "Read b.py")),
                                   .quiet(QuietLine(text: "Ran npm test")), .quiet(QuietLine(text: "Looked around")),
                                   .event(CodeEvent(id: 1, raw: ["kind": "end"])), .quiet(QuietLine(text: "Read c.py"))]
        let folded = foldQuiet(items)
        XCTAssertEqual(folded.count, 3)
        guard case let .group(g) = folded[0] else { return XCTFail("a group") }
        XCTAssertEqual(g.count, 5)
        XCTAssertEqual(groupTitle(g), "Thought, read 2 files, ran a command, looked around")
        guard case .quiet = folded[2] else { return XCTFail("a lone quiet line stays one") }
    }

    func testSessionsAreGroupedWorkingReadyAndDone() {
        func row(_ id: String, _ state: String, files: Int = 0, updated: Double = 1) -> CodeSessionRow {
            try! JSONDecoder().decode(CodeSessionRow.self, from: Data(#"{"id":"\#(id)","state":"\#(state)","files":\#(files),"updated":\#(updated)}"#.utf8))
        }
        let rows = [row("a", "working"), row("b", "done", files: 2), row("c", "done"), row("d", "done", files: 1, updated: 5)]
        let g = sessionGroups(rows, seen: ["d": 5])
        XCTAssertEqual(g.map(\.title), ["WORKING", "READY FOR REVIEW", "DONE"])
        XCTAssertEqual(g[1].sessions.map(\.id), ["b"], "d was opened after its last update")
        XCTAssertEqual(g[2].sessions.map(\.id), ["c", "d"])
        XCTAssertEqual(sessionGroups([row("c", "done")], seen: [:]).map(\.title), ["DONE"], "empty groups are left out")
    }

    func testSlashCommands() {
        XCTAssertEqual(Slash.parse("/plan"), .mode("plan"))
        XCTAssertEqual(Slash.parse("/AUTO now"), .mode("auto"))
        XCTAssertEqual(Slash.parse("/memory"), .memory)
        XCTAssertEqual(Slash.parse("/permissions"), .permissions)
        XCTAssertEqual(Slash.parse("/new"), .newSession)
        XCTAssertNil(Slash.parse("/deploy"), "a project's own command goes to VryxCode as written")
        XCTAssertNil(Slash.parse("write a plan"))
    }
}

@MainActor
final class CodeExtrasStoreTests: XCTestCase {
    private func store(parity on: Bool = true) -> CodeStore {
        let s = CodeStore(api: ApiClient(base: URL(string: "http://scripted.test")!, protocolClasses: [ScriptedServer.self]), onSignedOut: {})
        s.setParity { on && ($0 == "ios_vryxcode" || $0.hasPrefix("vryxcode_")) }
        return s
    }
    private func row() -> CodeSessionRow { try! JSONDecoder().decode(CodeSessionRow.self, from: Data(#"{"id":"s1","title":"Zebra game","project":"zebra","state":"done"}"#.utf8)) }
    private func eventually(_ what: String, timeout: TimeInterval = 10, _ check: () -> Bool) async {
        let end = Date().addingTimeInterval(timeout)
        while Date() < end { if check() { return }; try? await Task.sleep(nanoseconds: 50_000_000) }
        XCTFail("never: \(what)")
    }
    private let quiet: [[String: Any]] = [["state": "done", "full": true, "events": [], "pending": NSNull()]]

    func testRestoreSendsTheMessagesTurn() async {
        ScriptedServer.reset(views: quiet)
        let s = store(); s.open(row())
        s.restore(turn: 3)
        await eventually("the rewind was sent") { !ScriptedServer.posts(to: "/rewind").isEmpty }
        XCTAssertEqual(ScriptedServer.posts(to: "/rewind")[0]["turn"] as? Int, 3)
    }

    func testMemoryCanBeReadAndForgotten() async {
        ScriptedServer.reset(views: quiet, answers: ["/api/code/memory": ["notes": ["Uses tabs", "Likes zebras"]]])
        let s = store()
        s.showMemory()
        await eventually("the notes show") { s.memory == ["Uses tabs", "Likes zebras"] }
        s.forget(1)
        await eventually("forget was sent") { !ScriptedServer.posts(to: "/api/code/memory").isEmpty }
        XCTAssertEqual(ScriptedServer.posts(to: "/api/code/memory")[0]["forget"] as? Int, 1)
    }

    func testRulesAreReadAddedAndRemovedPerProject() async {
        ScriptedServer.reset(views: quiet, answers: ["/api/code/rules": ["allow": ["npm test"], "deny": ["rm -rf"]]])
        let s = store(); s.open(row())
        s.showRules()
        await eventually("the rules show") { s.rules?.allow == ["npm test"] && s.rules?.deny == ["rm -rf"] }
        XCTAssertTrue(ScriptedServer.gets.contains { $0.contains("/api/code/rules?project=zebra") })
        s.addRule("deny", "  curl  ")
        await eventually("add was sent") { !ScriptedServer.posts(to: "/api/code/rules").isEmpty }
        let add = ScriptedServer.posts(to: "/api/code/rules")[0]
        XCTAssertEqual(add["project"] as? String, "zebra")
        XCTAssertEqual((add["add"] as? [String: String]) ?? [:], ["kind": "deny", "rule": "curl"])
        s.removeRule("npm test")
        await eventually("remove was sent") { ScriptedServer.posts(to: "/api/code/rules").count == 2 }
        XCTAssertEqual(ScriptedServer.posts(to: "/api/code/rules")[1]["remove"] as? String, "npm test")
    }

    func testSlashSuggestionsListTheProjectsCommandsToo() async {
        ScriptedServer.reset(views: quiet, answers: ["/api/code/commands": ["commands": [["name": "deploy", "about": "Ship it"]]]])
        let s = store(); s.open(row())
        await s.loadCommands()
        XCTAssertEqual(s.slashMatches("/de").map(\.name), ["/deploy"])
        XCTAssertEqual(s.slashMatches("/p").map(\.name).sorted(), ["/permissions", "/plan"])
        XCTAssertTrue(s.slashMatches("plan").isEmpty, "only after a slash")
        XCTAssertTrue(s.slashMatches("/plan now").isEmpty, "not once there is a space")
    }

    func testASlashCommandIsAnsweredByTheAppAndNotSent() async {
        ScriptedServer.reset(views: quiet)
        let s = store(); s.open(row())
        s.send("/plan")
        XCTAssertEqual(s.mode, "plan")
        s.send("/auto")
        XCTAssertEqual(s.mode, "auto")
        try? await Task.sleep(nanoseconds: 300_000_000)
        XCTAssertTrue(ScriptedServer.posts(to: "/message").isEmpty)
        XCTAssertFalse(s.events.contains { $0.kind == "user" })
        s.send("/deploy now")
        await eventually("an unknown command goes to VryxCode") { !ScriptedServer.posts(to: "/message").isEmpty }
    }

    func testSlashCommandsAreOffWithoutTheFlag() async {
        ScriptedServer.reset(views: quiet)
        let s = store(parity: false); s.open(row())
        s.send("/plan")
        await eventually("it is sent as an ordinary message") { !ScriptedServer.posts(to: "/message").isEmpty }
        XCTAssertEqual(s.mode, "ask")
        XCTAssertTrue(s.slashMatches("/p").isEmpty)
    }

    func testPicturesAndDocumentsGoWithTheNextMessage() async {
        ScriptedServer.reset(views: quiet, answers: ["/api/documents": ["id": 42, "name": "spec.pdf", "kind": "pdf"]])
        let s = store(); s.open(row())
        s.addPicture(name: "a.jpg", data: Data([1, 2, 3]))
        s.addDoc(name: "spec.pdf", data: Data([4, 5]))
        await eventually("the document was uploaded") { s.docs.count == 1 }
        s.send("Use these")
        await eventually("the message was sent") { !ScriptedServer.posts(to: "/message").isEmpty }
        let body = ScriptedServer.posts(to: "/message")[0]
        XCTAssertEqual(body["images"] as? [String], ["data:image/jpeg;base64," + Data([1, 2, 3]).base64EncodedString()])
        XCTAssertEqual(body["docs"] as? [Int], [42])
        await eventually("they are cleared") { s.pictures.isEmpty && s.docs.isEmpty }
    }

    func testAtMostThreePicturesAndNoBigOnes() {
        let s = store()
        for _ in 0..<4 { s.addPicture(name: "a.jpg", data: Data([1])) }
        XCTAssertEqual(s.pictures.count, 3)
        XCTAssertNotNil(s.error)
        let t = store()
        t.addPicture(name: "big.jpg", data: Data(count: 5_000_001))
        XCTAssertTrue(t.pictures.isEmpty)
    }

    func testAfterAFinishedTurnTheNextStepIsSuggested() async {
        ScriptedServer.reset(views: [["state": "done", "full": true, "pending": NSNull(),
                                      "events": [["kind": "user", "text": "Build it", "turn": 1], ["kind": "end", "finished": true, "summary": "Done", "next": ["Add a score board"]]]]])
        let s = store(); s.open(row())
        await eventually("a suggestion") { s.offer == "Add a score board" }
    }

    func testAPlanIsAnsweredWithGoAhead() async {
        ScriptedServer.reset(views: [["state": "done", "full": true, "pending": NSNull(), "events": [["kind": "end", "plan": true, "summary": "Plan"]]]])
        let s = store(); s.open(row())
        await eventually("go ahead") { s.offer == "Go ahead and build it as planned." }
    }
}
