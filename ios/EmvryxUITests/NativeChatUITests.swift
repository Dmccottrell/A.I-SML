import XCTest

/// With ios_native on: the app's own chat, as the Android app's (needs the local test server, which answers in demo mode).
final class NativeChatUITests: ServerUITestCase {
    override func setUpWithError() throws {
        try launch(native: true)
        if !box.waitForExistence(timeout: 30) { shot("after sign in") }
        XCTAssertTrue(box.exists, "the native chat did not open signed in")
    }

    func testSendAMessageAndTheReplyIsWrittenIn() {
        app.buttons["New chat"].tap()
        XCTAssertTrue(app.staticTexts["How can I help?"].waitForExistence(timeout: 5))
        shot("native empty chat")
        box.tap()
        box.typeText("Hello from the iPhone")
        app.buttons["Send"].tap()
        // My words in a bubble, then the reply written in; Copy shows once it is finished.
        XCTAssertTrue(bubble("Hello from").waitForExistence(timeout: 10), "my message did not show")
        XCTAssertTrue(app.buttons["Copy"].waitForExistence(timeout: 60), "the reply did not finish")
        XCTAssertTrue(app.buttons["Send"].exists, "the Stop button should be Send again")
        shot("native reply")
    }

    func testModelMenuChatListAndSettingsPage() {
        app.buttons["Choose model"].tap()
        XCTAssertTrue(app.staticTexts["SELECT MODEL"].waitForExistence(timeout: 5))
        shot("native model menu")
        app.buttons["Choose model"].tap()
        let closed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: app.staticTexts["SELECT MODEL"])
        wait(for: [closed], timeout: 5)

        app.buttons["Chats"].tap()
        XCTAssertTrue(app.buttons["Account"].waitForExistence(timeout: 5), "the chat list did not open")
        shot("native chat list")
        app.buttons["Account"].tap()
        let settings = app.buttons["Settings"]
        XCTAssertTrue(settings.waitForExistence(timeout: 5))
        settings.tap()
        // The app's own Settings (not a web page), with a way back to the chat; "More settings" is the website's.
        XCTAssertTrue(app.buttons["Back to chat"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.switches["Show word counts"].waitForExistence(timeout: 10))
        XCTAssertFalse(app.webViews.firstMatch.exists)
        shot("native settings page")
        app.buttons["Back to chat"].tap()
        XCTAssertTrue(box.waitForExistence(timeout: 10))
    }
}
