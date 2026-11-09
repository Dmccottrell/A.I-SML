import XCTest

/// The model on the phone (android_offline_model), with a stand-in model file and engine. Needs the second test server, which offers a
/// stand-in file for flare-3 (see ios/README.md). The two harness tests need the server switched off and on from the command line.
final class PhoneUITests: ServerUITestCase {
    private func openSettings() {
        XCTAssertTrue(box.waitForExistence(timeout: 30), "the native chat did not open signed in")
        app.buttons["Chats"].tap()
        tapCentre(app.buttons["Account"])
        app.buttons["Settings"].tap()
        XCTAssertTrue(app.buttons["Back to chat"].waitForExistence(timeout: 10))
    }

    private var phoneBox: XCUIElement { app.descendants(matching: .any).matching(NSPredicate(format: "label == 'Message the phone'")).firstMatch }

    /// Asks the model on the phone [text] in the open phone chat and waits for the stand-in engine's answer.
    private func askThePhone(_ text: String) {
        XCTAssertTrue(phoneBox.waitForExistence(timeout: 10))
        phoneBox.tap()
        phoneBox.typeText(text)
        app.buttons["Send to the phone"].tap()
        let answer = app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH 'Phone answer to: ' AND label CONTAINS %@", String(text.prefix(5)))).firstMatch
        if !answer.waitForExistence(timeout: 30) { shot("no phone answer") }
        XCTAssertTrue(answer.exists, "the model on the phone did not answer")
    }

    func testDownloadTheModelThenChatOnThePhone() throws {
        try launch(native: true)
        openSettings()
        let download = app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Download '")).firstMatch
        var tries = 0
        while !download.waitForExistence(timeout: 3) && tries < 10 { app.swipeUp(); tries += 1 }
        XCTAssertTrue(download.exists, "no Download button under This phone")
        shot("this phone")
        download.tap()
        let ready = app.staticTexts.matching(NSPredicate(format: "label CONTAINS 'is on this phone'")).firstMatch
        if !ready.waitForExistence(timeout: 90) { shot("download not finished") }
        XCTAssertTrue(ready.exists, "the model did not arrive")
        shot("model on the phone")
        // The chats on this phone.
        app.swipeUp()
        app.buttons["Open the chats on this phone"].tap()
        XCTAssertTrue(app.buttons["New chat on this phone"].waitForExistence(timeout: 10))
        app.buttons["New chat on this phone"].firstMatch.tap()
        askThePhone("Hello phone")
        shot("phone chat")
        // Back to the list: the chat is there, waiting to be sent.
        app.buttons["Back to the phone's chats"].tap()
        XCTAssertTrue(app.buttons.matching(identifier: "phonechat").firstMatch.waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["waiting to send"].exists)
        shot("phone list")
    }

    /// Harness: the PC is switched off (EMVRYX_TEST_OUTSIDE=1). The app opens on the phone's chats by itself.
    func testWithThePcOffThePhoneAnswers() throws {
        try XCTSkipIf(ProcessInfo.processInfo.environment["EMVRYX_TEST_OUTSIDE"] != "1", "needs the harness: the PC switched off")
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchEnvironment["EMVRYX_SERVER"] = TestServer.url
        app.launchEnvironment["EMVRYX_FAKE_ENGINE"] = "1"
        app.launchEnvironment["EMVRYX_APP_LOCK"] = "reset"
        app.launch()
        XCTAssertTrue(app.buttons["New chat on this phone"].waitForExistence(timeout: 30), "the phone's chats did not open by themselves")
        shot("pc off")
        app.buttons["New chat on this phone"].firstMatch.tap()
        askThePhone("Written offline")
        shot("pc off answer")
    }

    /// Harness: the PC is back (EMVRYX_TEST_OUTSIDE=1). What was written on the phone joins the PC's chats.
    func testWhenThePcIsBackThePhonesChatsAreSent() throws {
        try XCTSkipIf(ProcessInfo.processInfo.environment["EMVRYX_TEST_OUTSIDE"] != "1", "needs the harness: the PC switched back on")
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchEnvironment["EMVRYX_SERVER"] = TestServer.url
        app.launchEnvironment["EMVRYX_FAKE_ENGINE"] = "1"
        app.launchEnvironment["EMVRYX_APP_LOCK"] = "reset"
        app.launch()
        XCTAssertTrue(box.waitForExistence(timeout: 30), "the native chat did not open")
        let found = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            let chats = (try? TestServer.json("GET", "/api/state"))?["chats"] as? [[String: Any]] ?? []
            return chats.contains { ($0["title"] as? String ?? "").contains("Written offline") }
        }, object: nil)
        XCTAssertEqual(XCTWaiter().wait(for: [found], timeout: 40), .completed, "the chat written on the phone did not reach the PC")
        // And it opens on the PC's side with both messages.
        app.buttons["Chats"].tap()
        XCTAssertTrue(app.buttons.matching(identifier: "chatrow").firstMatch.waitForExistence(timeout: 10))
        shot("synced list")
    }
}
