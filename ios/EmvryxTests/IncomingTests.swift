import AppIntents
import XCTest
@testable import Emvryx

/// Words from outside: Share to Emvryx (a link) and the Siri Shortcut.
final class IncomingTests: XCTestCase {
    func testALinkCarriesTheWordsExactly() throws {
        for text in ["Hello", "two words", "a & b = c + d # e", "https://example.com/x?y=1&z=2", "line one\nline two", "café 🦓", "100% sure"] {
            let url = try XCTUnwrap(EmvryxLink.ask(text), text)
            XCTAssertEqual(url.scheme, "emvryx")
            XCTAssertEqual(EmvryxLink.words(in: url), text, "round trip of \(text)")
        }
    }

    func testOnlyAskLinksWithWordsAreRead() {
        XCTAssertNil(EmvryxLink.words(in: URL(string: "emvryx://ask")!))
        XCTAssertNil(EmvryxLink.words(in: URL(string: "emvryx://ask?text=%20%20")!))
        XCTAssertNil(EmvryxLink.words(in: URL(string: "emvryx://other?text=hi")!))
        XCTAssertNil(EmvryxLink.words(in: URL(string: "https://chat.emvryx.app/ask?text=hi")!))
    }

    func testALongShareIsCut() throws {
        let url = try XCTUnwrap(EmvryxLink.ask(String(repeating: "a", count: 9000)))
        XCTAssertEqual(EmvryxLink.words(in: url)?.count, EmvryxLink.longest)
    }

    func testALinkNeverSendsAnything() throws {
        let incoming = try XCTUnwrap(Incoming(url: URL(string: "emvryx://ask?text=hi%20there&send=1")!))
        XCTAssertEqual(incoming.text, "hi there")
        XCTAssertFalse(incoming.send, "a web page must not be able to make the app send a message")
    }

    @MainActor
    func testWordsFromALinkWaitInTheBoxOfANewChat() throws {
        let model = AppModel()
        model.screen = .chat
        model.receive(try XCTUnwrap(URL(string: "emvryx://ask?text=Explain%20zebras")))
        XCTAssertEqual(model.draft, "Explain zebras")
        XCTAssertFalse(model.streaming)
        XCTAssertTrue(model.bubbles.isEmpty)
    }

    @MainActor
    func testWordsThatArriveBeforeSignInWaitForTheChat() throws {
        let model = AppModel()
        model.screen = .signIn
        model.receive(try XCTUnwrap(URL(string: "emvryx://ask?text=Later")))
        XCTAssertEqual(model.draft, "", "not before the chat is on screen")
        model.screen = .chat
        model.backToChat()
        XCTAssertEqual(model.draft, "Later")
    }

    @MainActor
    func testTheSiriShortcutHandsItsQuestionToTheApp() async throws {
        var intent = AskEmvryxIntent()
        intent.question = "What is the tallest animal?"
        IncomingBridge.shared.pending = nil
        _ = try await intent.perform()
        XCTAssertEqual(IncomingBridge.shared.pending, Incoming(text: "What is the tallest animal?", send: true))
        IncomingBridge.shared.pending = nil
    }

    func testTheShortcutIsOfferedToSiri() {
        XCTAssertEqual(EmvryxShortcuts.appShortcuts.count, 1)
    }
}
