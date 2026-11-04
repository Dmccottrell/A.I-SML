import XCTest

/// The local Emvryx test server the UI tests drive: EMVRYX_TEST_SERVER (its address) and EMVRYX_TEST_KEY (an admin tester's access key).
/// These are the test runner's own names: the unit tests run inside the app and must still see chat.emvryx.app. Run from ios/ (see README):
///   TEST_RUNNER_EMVRYX_TEST_SERVER=http://127.0.0.1:8765 TEST_RUNNER_EMVRYX_TEST_KEY=<the key> xcodebuild test ...
enum TestServer {
    static var url: String { ProcessInfo.processInfo.environment["EMVRYX_TEST_SERVER"] ?? "" }
    static var key: String { ProcessInfo.processInfo.environment["EMVRYX_TEST_KEY"] ?? "" }

    /// Sets who sees a feature (Admin > Previews) on the test server, signed in as the tester: "admins", "everyone" or "off".
    static func setFlag(_ id: String, _ audience: String) throws {
        let session = URLSession(configuration: .ephemeral)
        func post(_ path: String, _ body: [String: Any]) throws -> Int {
            var r = URLRequest(url: URL(string: url + path)!)
            r.httpMethod = "POST"
            r.setValue("application/json", forHTTPHeaderField: "Content-Type")
            r.httpBody = try JSONSerialization.data(withJSONObject: body)
            let done = DispatchSemaphore(value: 0)
            var status = 0
            session.dataTask(with: r) { _, response, _ in status = (response as? HTTPURLResponse)?.statusCode ?? 0; done.signal() }.resume()
            done.wait()
            return status
        }
        XCTAssertEqual(try post("/api/login", ["key": key]), 200, "the test key did not sign in")
        XCTAssertEqual(try post("/api/admin/flags", ["id": id, "audience": audience]), 200, "could not set \(id)")
    }
}

/// Drives the app like a person against the local test server. Skips without one.
class ServerUITestCase: XCTestCase {
    var app: XCUIApplication!
    let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")

    /// Opens the app with the server's ios_native switch on ([native]) or off, signing in with the access key if it asks.
    func launch(native: Bool) throws {
        try XCTSkipIf(TestServer.url.isEmpty || TestServer.key.isEmpty, "needs a test server (EMVRYX_TEST_SERVER and EMVRYX_TEST_KEY)")
        continueAfterFailure = false
        try TestServer.setFlag("ios_native", native ? "admins" : "off")
        app = XCUIApplication()
        app.launchEnvironment["EMVRYX_SERVER"] = TestServer.url
        app.launch()
        let useKey = app.buttons["Use an access key"]
        if useKey.waitForExistence(timeout: 10) {
            shot("sign in")
            useKey.tap()
            let field = app.secureTextFields["Access key"]
            XCTAssertTrue(field.waitForExistence(timeout: 5))
            field.tap()
            field.typeText(TestServer.key)
            app.buttons["Sign in"].tap()
        }
    }

    /// A screenshot kept in the test results, and also saved as a PNG in EMVRYX_SHOTS when that folder is given.
    func shot(_ name: String) {
        let image = XCUIScreen.main.screenshot()
        let a = XCTAttachment(screenshot: image)
        a.name = name
        a.lifetime = .keepAlways
        add(a)
        if let dir = ProcessInfo.processInfo.environment["EMVRYX_SHOTS"], !dir.isEmpty {
            let file = name.replacingOccurrences(of: "[^A-Za-z0-9]+", with: "-", options: .regularExpression)
            try? image.pngRepresentation.write(to: URL(fileURLWithPath: dir).appendingPathComponent("\(file).png"))
            try? app.debugDescription.write(to: URL(fileURLWithPath: dir).appendingPathComponent("\(file).txt"), atomically: true, encoding: .utf8)
        }
    }

    /// Tap Allow on an iOS permission alert whose text contains [words], if it shows within [timeout]. Returns whether it showed.
    @discardableResult
    func allowAlert(containing words: String, timeout: TimeInterval) -> Bool {
        let alert = springboard.alerts.containing(NSPredicate(format: "label CONTAINS[c] %@", words)).firstMatch
        guard alert.waitForExistence(timeout: timeout) else { return false }
        shot("alert: \(words)")
        let allow = alert.buttons.matching(NSPredicate(format: "label BEGINSWITH[c] 'Allow' OR label == 'OK'")).firstMatch
        allow.tap()
        return true
    }
}

/// With ios_native off the app is the website, as version 1: its voice button and photo upload.
final class EmvryxUITests: ServerUITestCase {
    override func setUpWithError() throws {
        try launch(native: false)
        // A new account first sees the website's welcome tour.
        let skip = app.buttons["Skip"]
        if skip.waitForExistence(timeout: 8) { skip.tap() }
        // Signed in: the message box's + button is there.
        XCTAssertTrue(plus.waitForExistence(timeout: 30), "the chat page did not open signed in")
    }

    /// The message box's + button (iOS lists it as a menu button, so match it by name whatever its kind).
    private var plus: XCUIElement { app.webViews.descendants(matching: .any)["Add files or photos"] }

    func test2VoiceButtonListens() {
        // Hold to talk: iOS asks for the microphone and speech recognition the first time on a real iPhone (the simulator does not ask).
        let mic = app.webViews.buttons["Hold to talk"]
        XCTAssertTrue(mic.waitForExistence(timeout: 15), "no voice button on the page")
        mic.press(forDuration: 2)
        allowAlert(containing: "Microphone", timeout: 3)
        allowAlert(containing: "Speech", timeout: 3)
        mic.press(forDuration: 2)
        shot("talking")
        // Still on the chat page afterwards (whether it heard words is checked in WebControllerTests, without a server).
        XCTAssertTrue(plus.exists)
    }

    func test3PhotoUploadAttachesAPicture() {
        plus.tap()
        let choice = app.webViews.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS[c] 'Photos or screenshots'")).firstMatch
        XCTAssertTrue(choice.waitForExistence(timeout: 10))
        choice.tap()
        // iOS's own choice: Photo Library, Take Photo or Choose File.
        let library = app.buttons["Photo Library"]
        XCTAssertTrue(library.waitForExistence(timeout: 10), "iOS's photo menu did not open")
        shot("photo menu")
        library.tap()
        // Pick the newest photo (the picker lists it first), then Add (several can be picked).
        let photo = app.images.matching(NSPredicate(format: "label BEGINSWITH 'Photo,'")).firstMatch
        XCTAssertTrue(photo.waitForExistence(timeout: 15), "the photo picker did not show photos")
        shot("photo picker")
        photo.tap()
        let add = app.buttons["Add"]
        if add.waitForExistence(timeout: 5) { add.tap() }
        // The photo goes to the server, and the page answers: the picture waits in the box to go with the next message
        // (its "Remove <name>" button), or the site says why it was not added (as an iPhone alert, like Android's dialog).
        let chip = app.webViews.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Remove '")).firstMatch
        let message = app.alerts.firstMatch
        let answered = NSPredicate { _, _ in chip.exists || message.exists }
        wait(for: [XCTNSPredicateExpectation(predicate: answered, object: nil)], timeout: 30)
        shot("attached")
        if message.exists {
            XCTAssertTrue(message.label.contains("Skipped") || message.staticTexts.containing(NSPredicate(format: "label CONTAINS 'Skipped'")).count > 0,
                          "unexpected message: \(message.debugDescription)")
            message.buttons.firstMatch.tap()
        }
    }
}

/// The off screen, with no server needed: the app is pointed at an address where nothing answers.
final class OffScreenUITests: XCTestCase {
    func testServerNotAnsweringShowsTheOffScreenAndTryAgainWorks() {
        let app = XCUIApplication()
        app.launchEnvironment["EMVRYX_SERVER"] = "http://127.0.0.1:8799"   // nothing listens there (port 9 would be refused by WebKit itself)
        app.launch()
        XCTAssertTrue(app.staticTexts["Emvryx is off right now"].waitForExistence(timeout: 30))
        XCTAssertTrue(app.staticTexts["127.0.0.1"].exists, "the server address under the button")
        let again = app.buttons["Try again"]
        XCTAssertTrue(again.exists)
        let a = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        a.lifetime = .keepAlways
        add(a)
        if let dir = ProcessInfo.processInfo.environment["EMVRYX_SHOTS"], !dir.isEmpty {
            try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: dir).appendingPathComponent("off-screen.png"))
        }
        // Try again checks again: still nothing there, so the off screen comes back.
        again.tap()
        XCTAssertTrue(app.staticTexts["Emvryx is off right now"].waitForExistence(timeout: 30))
    }
}
