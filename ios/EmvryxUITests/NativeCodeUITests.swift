import XCTest

/// With ios_native on: VryxCode as the app's own screens (android/.../ui/CodeScreen.kt). The demo test server has no model, so a session
/// starts, writes its first events and ends saying so, which is enough to see the whole screen work.
final class NativeCodeUITests: ServerUITestCase {
    private func openVryxCode() {
        XCTAssertTrue(box.waitForExistence(timeout: 30), "the native chat did not open signed in")
        app.buttons["Chats"].tap()
        let link = app.buttons["VryxCode"]
        XCTAssertTrue(link.waitForExistence(timeout: 5))
        link.tap()
        XCTAssertTrue(app.buttons["Back to chat"].waitForExistence(timeout: 10), "VryxCode did not open")
    }

    private var taskBox: XCUIElement { app.textViews["Message VryxCode"].exists ? app.textViews["Message VryxCode"] : app.textFields["Message VryxCode"] }

    func testStartASessionSeeItsFeedAndManageIt() throws {
        try launch(native: true)
        openVryxCode()
        XCTAssertTrue(taskBox.waitForExistence(timeout: 15))
        shot("code home")
        taskBox.tap()
        taskBox.typeText("Make a zebra game")
        app.buttons["Send"].tap()
        // The session opens: my message, VryxCode's first notes, and how it ended.
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH 'Make a zebra'")).firstMatch.waitForExistence(timeout: 15), "my task is not in the feed")
        let note = app.staticTexts.matching(NSPredicate(format: "label CONTAINS 'Suggested language'")).firstMatch
        if !note.waitForExistence(timeout: 20) { shot("no note") }
        XCTAssertTrue(note.exists, "no first note in the feed")
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label CONTAINS 'could not finish'")).firstMatch.waitForExistence(timeout: 20), "no end card")
        shot("code session")
        // Back to the list: the session is there; hold it to archive, then put it back, then delete it.
        app.buttons["Back to sessions"].tap()
        let row = app.buttons.matching(identifier: "codesession").firstMatch
        XCTAssertTrue(row.waitForExistence(timeout: 15), "the session is not listed")
        shot("code list")
        row.press(forDuration: 1.2)
        app.buttons["Archive"].tap()
        let gone = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: app.buttons.matching(identifier: "codesession").firstMatch)
        let archivedAway = XCTWaiter().wait(for: [gone], timeout: 15)
        if archivedAway != .completed { shot("after archive") }
        XCTAssertEqual(archivedAway, .completed, "the archived session stayed in the list")
        app.buttons["Archived"].tap()
        XCTAssertTrue(app.buttons.matching(identifier: "codesession").firstMatch.waitForExistence(timeout: 15), "the archived session is not under Archived")
        app.buttons.matching(identifier: "codesession").firstMatch.press(forDuration: 1.2)
        app.buttons["Delete"].tap()
        XCTAssertEqual(XCTWaiter().wait(for: [XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: app.buttons.matching(identifier: "codesession").firstMatch)], timeout: 15), .completed)
        app.buttons["Back to chat"].tap()
        XCTAssertTrue(box.waitForExistence(timeout: 10))
    }

    func testAStarterFillsTheBox() throws {
        try launch(native: true)
        openVryxCode()
        let starter = app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Starter '")).firstMatch
        XCTAssertTrue(starter.waitForExistence(timeout: 15), "no starters on the VryxCode home")
        starter.tap()
        XCTAssertTrue(((taskBox.value as? String) ?? "").contains("to-do list"), "the starter's idea is not in the box: \(String(describing: taskBox.value))")
        shot("starter")
    }
}
