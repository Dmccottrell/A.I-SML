import XCTest

/// Drives the app like a person against a local Emvryx server: the voice button and a photo upload.
/// Needs a test server, so it skips without one. Run from ios/ (see README):
///   TEST_RUNNER_EMVRYX_TEST_SERVER=http://127.0.0.1:8765 TEST_RUNNER_EMVRYX_TEST_START=<a one-time /pair/ link> xcodebuild test ...
/// (the runner's own names: the unit tests run inside the app and must still see chat.emvryx.app).
final class EmvryxUITests: XCTestCase {
    private var app: XCUIApplication!
    private let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")

    override func setUpWithError() throws {
        let env = ProcessInfo.processInfo.environment
        let server = env["EMVRYX_TEST_SERVER"] ?? ""
        try XCTSkipIf(server.isEmpty, "needs a test server (EMVRYX_TEST_SERVER)")
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchEnvironment["EMVRYX_SERVER"] = server
        if let start = env["EMVRYX_TEST_START"], !start.isEmpty { app.launchEnvironment["EMVRYX_START"] = start }
        app.launch()
        // The first run opens the one-time sign-in link: tap its button. Later runs are still signed in (the app keeps its cookies).
        let pair = app.buttons["Sign in on this device"]
        if pair.waitForExistence(timeout: 10) { pair.tap() }
        // A new account first sees the welcome tour.
        let skip = app.buttons["Skip"]
        if skip.waitForExistence(timeout: 8) { skip.tap() }
        // Signed in: the message box's + button is there.
        XCTAssertTrue(plus.waitForExistence(timeout: 30), "the chat page did not open signed in")
    }

    /// The message box's + button (iOS lists it as a menu button, so match it by name whatever its kind).
    private var plus: XCUIElement { app.webViews.descendants(matching: .any)["Add files or photos"] }

    /// A screenshot kept in the test results, and also saved as a PNG in EMVRYX_SHOTS when that folder is given.
    private func shot(_ name: String) {
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
    private func allowAlert(containing words: String, timeout: TimeInterval) -> Bool {
        let alert = springboard.alerts.containing(NSPredicate(format: "label CONTAINS[c] %@", words)).firstMatch
        guard alert.waitForExistence(timeout: timeout) else { return false }
        shot("alert: \(words)")
        let allow = alert.buttons.matching(NSPredicate(format: "label BEGINSWITH[c] 'Allow' OR label == 'OK'")).firstMatch
        allow.tap()
        return true
    }

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
