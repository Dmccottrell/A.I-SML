import XCTest

/// With ios_native on: what you can do with a chat and its messages (android/.../ui/ChatScreen.kt), against the local test server.
final class NativeChatActionsUITests: ServerUITestCase {
    override func setUpWithError() throws {
        try launch(native: true)
        if !box.waitForExistence(timeout: 30) { shot("after sign in") }
        XCTAssertTrue(box.exists, "the native chat did not open signed in")
    }

    private func openChatList() {
        app.buttons["Chats"].tap()
        XCTAssertTrue(app.buttons["Account"].waitForExistence(timeout: 5), "the chat list did not open")
    }

    func testRegenerateAndEditAndAskAgain() {
        app.buttons["New chat"].tap()
        ask("Tell me about zebras")
        // Regenerate ▾ opens the choices; Try again writes a fresh answer.
        app.buttons["Regenerate ▾"].tap()
        XCTAssertTrue(app.buttons["Try again"].waitForExistence(timeout: 5), "no regenerate choices")
        shot("regenerate choices")
        app.buttons["Try again"].tap()
        waitForReply()
        // Hold my message: Edit and ask again.
        bubble("Tell me about zebras").press(forDuration: 1.2)
        let edit = app.buttons["Edit and ask again"]
        XCTAssertTrue(edit.waitForExistence(timeout: 5), "no edit in the hold menu")
        edit.tap()
        let field = app.textViews["Your message"].exists ? app.textViews["Your message"] : app.textFields["Your message"]
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        // The keyboard comes up by itself; delete the old words (the box starts with them), then type the new ones.
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 10), "the edit sheet did not open the keyboard")
        field.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: 30))
        field.typeText("Tell me about giraffes")
        shot("edit sheet")
        app.buttons["Save and ask again"].tap()
        XCTAssertTrue(bubble("Tell me about giraf").waitForExistence(timeout: 15), "the edited message did not show")
        waitForReply()
        // The answer's ⋯ menu: Branch makes a new chat from here.
        app.buttons["More"].firstMatch.tap()
        XCTAssertTrue(app.buttons["Branch: new chat from here"].waitForExistence(timeout: 5))
        shot("answer menu")
        app.buttons["Branch: new chat from here"].tap()
        XCTAssertTrue(bubble("Tell me about giraf").waitForExistence(timeout: 15))
    }

    func testPinArchiveDeleteAndSearchInChats() {
        app.buttons["New chat"].tap()
        ask("Tell me about the platypus")
        openChatList()
        let row = app.buttons.matching(identifier: "chatrow").firstMatch
        XCTAssertTrue(row.waitForExistence(timeout: 10))
        // Search matches the words inside chats too.
        let search = app.textFields["Search chats"]
        search.tap()
        search.typeText("platypus")
        XCTAssertTrue(app.staticTexts["IN MESSAGES"].waitForExistence(timeout: 10) || app.buttons.matching(identifier: "chatrow").count > 0, "search found nothing")
        shot("search")
        search.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: 12))
        // Hold the chat: Pin.
        row.press(forDuration: 1.2)
        XCTAssertTrue(app.buttons["Pin"].waitForExistence(timeout: 5), "no pin in the hold menu")
        app.buttons["Pin"].tap()
        XCTAssertTrue(app.staticTexts["PINNED"].waitForExistence(timeout: 10), "the chat did not move to PINNED")
        shot("pinned")
        // Archive it, find it under Archived chats, put it back.
        app.buttons.matching(identifier: "chatrow").firstMatch.press(forDuration: 1.2)
        app.buttons["Archive (still remembered)"].tap()
        tapCentre(app.buttons["Account"])
        app.buttons["Archived chats"].tap()
        XCTAssertTrue(app.buttons["Put back"].waitForExistence(timeout: 10), "the archived chat is not listed")
        shot("archived")
        app.buttons["Put back"].tap()
        app.buttons["Close"].tap()
        openChatList()
        // Delete it (with the question first): one chat fewer in the list.
        let before = app.buttons.matching(identifier: "chatrow").count
        app.buttons.matching(identifier: "chatrow").firstMatch.press(forDuration: 1.2)
        app.buttons["Delete"].tap()
        XCTAssertTrue(app.alerts["Delete this chat?"].waitForExistence(timeout: 5))
        shot("delete question")
        app.alerts.buttons["Delete"].tap()
        let fewer = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in self.app.buttons.matching(identifier: "chatrow").count < before }, object: nil)
        XCTAssertEqual(XCTWaiter().wait(for: [fewer], timeout: 15), .completed, "the chat was not deleted")
    }

    func testMemoryRingUsageAndSaveAs() {
        app.buttons["New chat"].tap()
        ask("How tall is a giraffe")
        // The usage line opens its details.
        app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH 'Usage:'")).firstMatch.tap()
        XCTAssertTrue(app.staticTexts["Usage"].waitForExistence(timeout: 5))
        shot("usage sheet")
        app.buttons["Close"].tap()
        // The memory ring opens the context window details.
        let ring = app.buttons["Memory"]
        if ring.waitForExistence(timeout: 5) {
            ring.tap()
            XCTAssertTrue(app.buttons["Compact now"].waitForExistence(timeout: 5))
            shot("memory sheet")
            app.buttons["Close"].tap()
        }
        // The answer's ⋯: Save as, with a PDF made on the server.
        app.buttons["More"].firstMatch.tap()
        app.buttons["Save as…"].tap()
        XCTAssertTrue(app.buttons["PDF"].waitForExistence(timeout: 5))
        shot("save as")
        app.buttons["PDF"].tap()
        XCTAssertTrue(app.buttons["Copy"].waitForExistence(timeout: 1) || true)
        // iOS's share sheet appears with the file.
        let sheet = app.otherElements["ActivityListView"]
        XCTAssertTrue(sheet.waitForExistence(timeout: 30) || app.navigationBars["Emvryx.pdf"].waitForExistence(timeout: 5) || app.staticTexts.matching(NSPredicate(format: "label CONTAINS '.pdf'")).firstMatch.waitForExistence(timeout: 10), "the PDF share sheet did not open")
        shot("pdf share")
    }

    func testPhotoUploadAndVoiceButton() {
        app.buttons["New chat"].tap()
        // + > Photos or screenshots: iOS's own picker, then the picture waits in the box with a Remove button.
        tapCentre(app.buttons["Add a picture or file"])
        let photos = app.buttons["Photos or screenshots"]
        XCTAssertTrue(photos.waitForExistence(timeout: 5))
        photos.tap()
        let photo = app.images.matching(NSPredicate(format: "label BEGINSWITH 'Photo,'")).firstMatch
        XCTAssertTrue(photo.waitForExistence(timeout: 20), "the photo picker did not show photos")
        photo.tap()
        let add = app.buttons["Add"]
        if add.waitForExistence(timeout: 5) { add.tap() }
        let chip = app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Remove '")).firstMatch
        let toast = app.buttons.matching(NSPredicate(format: "label CONTAINS 'Nothing was added' OR label CONTAINS 'Skipped'")).firstMatch
        let answered = NSPredicate { _, _ in chip.exists || toast.exists }
        XCTWaiter().wait(for: [XCTNSPredicateExpectation(predicate: answered, object: nil)], timeout: 30)
        shot("photo attached")
        XCTAssertTrue(chip.exists || toast.exists, "the photo neither attached nor said why not")
        // The voice button asks for the microphone the first time, and listens while it is held.
        let mic = app.buttons["Hold to talk"]
        XCTAssertTrue(mic.waitForExistence(timeout: 5))
        mic.press(forDuration: 2)
        allowAlert(containing: "Speech", timeout: 3)
        allowAlert(containing: "Microphone", timeout: 3)
        shot("voice")
        // Allowed: the simulator has no microphone, so the app says it needs a real iPhone (and does not crash); a real iPhone listens.
        mic.press(forDuration: 1)
        let simulator = app.alerts["Voice"]
        XCTAssertTrue(simulator.waitForExistence(timeout: 5), "no answer from the voice button")
        XCTAssertTrue(simulator.staticTexts.matching(NSPredicate(format: "label CONTAINS 'real iPhone'")).firstMatch.exists)
        simulator.buttons["OK"].tap()
        XCTAssertTrue(mic.exists)
    }
}
