import XCTest

/// With ios_native on: the app's own Memory, Documents, Skills and Settings screens (android/.../ui/NativeScreens.kt).
final class NativePanelsUITests: ServerUITestCase {
    /// Opens a screen from the chat list; [viaAccount]: it is under the account menu.
    private func open(_ name: String, viaAccount: Bool = false) {
        XCTAssertTrue(box.waitForExistence(timeout: 30), "the native chat did not open signed in")
        app.buttons["Chats"].tap()
        if viaAccount { tapCentre(app.buttons["Account"]) }
        let link = app.buttons[name]
        XCTAssertTrue(link.waitForExistence(timeout: 5), "no \(name) link")
        link.tap()
        XCTAssertTrue(app.buttons["Back to chat"].waitForExistence(timeout: 10), "\(name) did not open")
    }

    func testMemoryAddDeleteForgetAll() throws {
        try launch(native: true)
        open("Memory", viaAccount: true)
        let field = app.textFields["Add a fact"]
        XCTAssertTrue(field.waitForExistence(timeout: 10))
        field.tap()
        field.typeText("I live in Leeds")
        app.buttons["Remember this"].tap()
        // The server words the fact its own way ("The user lives in Leeds."), so match on a word.
        func fact(_ word: String) -> XCUIElement { app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", word)).firstMatch }
        XCTAssertTrue(fact("Leeds").waitForExistence(timeout: 10), "the fact was not listed")
        let facts = (try TestServer.json("GET", "/api/memory"))["facts"] as? [[String: Any]] ?? []
        XCTAssertGreaterThanOrEqual(facts.count, 1, "the server did not keep it")
        shot("memory")
        app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Delete ' AND label CONTAINS 'Leeds'")).firstMatch.tap()
        let gone = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: fact("Leeds"))
        XCTAssertEqual(XCTWaiter().wait(for: [gone], timeout: 10), .completed, "the fact stayed in the list")
        // Forget everything asks first.
        field.tap(); field.typeText("My cat is Tom"); app.buttons["Remember this"].tap()
        XCTAssertTrue(fact("Tom").waitForExistence(timeout: 10))
        app.buttons["Forget everything"].tap()
        XCTAssertTrue(app.alerts["Forget everything?"].waitForExistence(timeout: 5))
        app.alerts.buttons["Forget"].tap()
        XCTAssertTrue(app.staticTexts["Nothing remembered yet"].waitForExistence(timeout: 10) || app.staticTexts["NOTHING REMEMBERED YET"].waitForExistence(timeout: 5))
        app.buttons["Back to chat"].tap()
        XCTAssertTrue(box.waitForExistence(timeout: 10))
    }

    func testDocumentsListAndDelete() throws {
        try launch(native: true)
        // A file added through the server, as the + by the message box does.
        let text = Data("A short note about zebras.".utf8)
        let made = try TestServer.json("POST", "/api/documents", ["name": "zebras.txt", "data": text.base64EncodedString()])
        XCTAssertNotNil(made["id"], "the test file was not added: \(made)")
        open("Documents")
        XCTAssertTrue(app.staticTexts["zebras.txt"].waitForExistence(timeout: 10), "the file was not listed")
        shot("documents")
        app.buttons["Delete zebras.txt"].tap()
        XCTAssertTrue(app.alerts["Delete this file?"].waitForExistence(timeout: 5))
        app.alerts.buttons["Delete"].tap()
        let gone = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: app.staticTexts["zebras.txt"])
        XCTAssertEqual(XCTWaiter().wait(for: [gone], timeout: 10), .completed, "the file stayed in the list")
        XCTAssertTrue(app.staticTexts["No documents yet."].waitForExistence(timeout: 5))
    }

    func testSkillsStartAChat() throws {
        try launch(native: true)
        open("Skills")
        let start = app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Start '")).firstMatch
        XCTAssertTrue(start.waitForExistence(timeout: 10), "no skills listed")
        shot("skills")
        let name = String(start.label.dropFirst("Start ".count))
        start.tap()
        // Back in the chat, in a new chat named for the skill.
        XCTAssertTrue(box.waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts[name].waitForExistence(timeout: 5), "the new chat is not named \(name)")
    }

    func testSettingsSaveOnTheServer() throws {
        try launch(native: true)
        open("Settings", viaAccount: true)
        let tokens = app.switches["Show word counts"]
        XCTAssertTrue(tokens.waitForExistence(timeout: 10))
        shot("settings")
        let before = (try TestServer.json("GET", "/api/settings"))["show_tokens"] as? Bool ?? false
        tokens.tap()
        let flipped = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in ((try? TestServer.json("GET", "/api/settings"))?["show_tokens"] as? Bool) == !before }, object: nil)
        XCTAssertEqual(XCTWaiter().wait(for: [flipped], timeout: 10), .completed, "the setting was not saved on the server")
        tokens.tap()
        // Pills: Pause before the answer.
        app.buttons["Natural"].tap()
        let natural = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in ((try? TestServer.json("GET", "/api/settings"))?["thinking_pause"] as? String) == "natural" }, object: nil)
        XCTAssertEqual(XCTWaiter().wait(for: [natural], timeout: 10), .completed)
        app.buttons["Short"].tap()
        // More settings opens the website's Settings inside the app.
        app.buttons["More settings"].tap()
        XCTAssertTrue(app.webViews.firstMatch.waitForExistence(timeout: 10))
    }
}
