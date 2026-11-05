import XCTest

/// Things that happen from outside the app. Each needs the test harness to do its part from the command line while the test waits
/// (TEST_RUNNER_EMVRYX_TEST_OUTSIDE=1): `xcrun simctl openurl` for the link, `notifyutil` for the simulator's Face ID.
final class OutsideUITests: ServerUITestCase {
    override func setUpWithError() throws {
        try XCTSkipIf(ProcessInfo.processInfo.environment["EMVRYX_TEST_OUTSIDE"] != "1", "needs the harness (EMVRYX_TEST_OUTSIDE=1)")
    }

    func testALinkPutsItsWordsInTheBoxOfANewChat() throws {
        try launch(native: true)
        XCTAssertTrue(box.waitForExistence(timeout: 30))
        // The harness opens emvryx://ask?text=Hello%20from%20a%20link now; iOS asks "Open in Emvryx?" first, as it does for any link from outside.
        let ask = springboard.alerts.containing(NSPredicate(format: "label CONTAINS 'Open in'")).firstMatch
        if ask.waitForExistence(timeout: 90) {
            shot("open in")
            sleep(1)
            let open = ask.buttons["Open"]
            if open.isHittable { open.tap() } else { open.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap() }
            if ask.exists { app.coordinate(withNormalizedOffset: CGVector(dx: 0.66, dy: 0.55)).tap() }     // where Open sits in iOS's question
        }
        let got = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in ((self.box.value as? String) ?? "").contains("Hello from a link") }, object: nil)
        if XCTWaiter().wait(for: [got], timeout: 90) != .completed { shot("link not received") }
        XCTAssertTrue(((box.value as? String) ?? "").contains("Hello from a link"), "the words of the link are not in the box")
        // Put in the box, not sent.
        XCTAssertFalse(app.buttons["Copy"].exists, "a link must not send anything")
        shot("link words")
    }

    func testAppLockLocksAndFaceIDUnlocks() throws {
        try launch(native: true)
        XCTAssertTrue(box.waitForExistence(timeout: 30))
        app.buttons["Chats"].tap()
        tapCentre(app.buttons["Account"])
        let lockRow = app.buttons["App lock"]
        XCTAssertTrue(lockRow.waitForExistence(timeout: 5))
        lockRow.tap()
        shot("lock on")
        // Away and back: it asks for Face ID. The harness sends Face ID matches meanwhile.
        XCUIDevice.shared.press(.home)
        sleep(2)
        app.activate()
        let locked = app.staticTexts["Emvryx is locked"]
        XCTAssertTrue(locked.waitForExistence(timeout: 15), "the app did not lock when it went to the background")
        shot("locked")
        // The first time, iOS asks to allow Face ID for the app.
        allowAlert(containing: "Face ID", timeout: 5)
        let gone = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: locked)
        XCTAssertEqual(XCTWaiter().wait(for: [gone], timeout: 60), .completed, "Face ID did not unlock it")
        XCTAssertTrue(box.waitForExistence(timeout: 10), "the chat is not back after unlocking")
        // Switch it off again.
        app.buttons["Chats"].tap()
        tapCentre(app.buttons["Account"])
        app.buttons["App lock"].tap()
    }

    /// Run WITHOUT Face ID matches: a cold start with the lock on stays locked (and says so) until Face ID is shown.
    func testAppLockHoldsOnAColdStart() throws {
        try launch(native: true)
        XCTAssertTrue(box.waitForExistence(timeout: 30))
        app.buttons["Chats"].tap()
        tapCentre(app.buttons["Account"])
        app.buttons["App lock"].tap()
        sleep(1)
        app.terminate()
        app.launchEnvironment["EMVRYX_APP_LOCK"] = "keep"
        app.launch()
        if !app.staticTexts["Emvryx is locked"].waitForExistence(timeout: 20) { shot("cold start") }
        XCTAssertTrue(app.staticTexts["Emvryx is locked"].exists, "no lock on a cold start")
        shot("cold start locked")
        XCTAssertFalse(box.exists, "the chat is showing behind the lock")
    }
}
