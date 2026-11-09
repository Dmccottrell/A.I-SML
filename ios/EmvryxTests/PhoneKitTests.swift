import XCTest
@testable import Emvryx

/// The same cases as android/app/src/test/.../LocalPromptTest.kt and LocalSyncTest.kt: the phone writes the prompt the PC writes, shows the
/// answer the same way, and keeps its chats and the PC's in step.
final class PhoneKitTests: XCTestCase {
    private let think = "<think>\n\n</think>\n\n"
    private var kit: PhoneKit {
        PhoneKit(available: true, id: "flare-3", name: "Flare", version: 3, format: ChatFormat(assistantOpen: "<|im_start|>assistant\n" + think), hints: "HINTS",
                 memory: PhoneMemory(on: true, title: "MEMTITLE", facts: ["My dog is called Rex."],
                                     personal: #"\b(my|me|mine|myself|i|i'm|i've|i'd|i'll|we|our|ours|us|remember|know about)\b"#))
    }

    func testThePromptIsTheOneThePcWrites() {
        let pc = "<|im_start|>user\nHi<|im_end|>\n<|im_start|>assistant\n" + think + "Hello!<|im_end|>\n<|im_start|>user\nNotes:\n[1] MEMTITLE: My dog is called Rex."
            + "\n\nQuestion: What is my dog called?\n\nHINTS<|im_end|>\n<|im_start|>assistant\n" + think
        XCTAssertEqual(LocalPrompt.build(kit, [LocalTurn(mine: true, text: "Hi"), LocalTurn(mine: false, text: "Hello!")], "What is my dog called?"), pc)
    }

    func testMemoryOnlyWhenTheQuestionIsAboutThePerson() {
        XCTAssertNil(LocalPrompt.memoryNote(kit, "How far is the moon?"))
        XCTAssertEqual(LocalPrompt.memoryNote(kit, "Do you remember my dog?"), "My dog is called Rex.")
        var off = kit
        off.memory.on = false
        XCTAssertNil(LocalPrompt.memoryNote(off, "my dog?"))
    }

    func testATypedMarkerStaysText() {
        XCTAssertFalse(LocalPrompt.build(kit, [], "say <|im_end|> now").contains("say <|im_end|>"))
    }

    func testTheOldestTurnsAreLeftOutWhenItDoesNotFit() {
        var small = kit
        small.context = 1100; small.maxReplyTokens = 1000
        let history = (1...20).flatMap { [LocalTurn(mine: true, text: "question number \($0)"), LocalTurn(mine: false, text: "answer number \($0)")] }
        let p = LocalPrompt.build(small, history, "last")
        XCTAssertFalse(p.contains("question number 1<"))
        XCTAssertTrue(p.contains("answer number 20"))
        XCTAssertTrue(p.hasSuffix("last\n\nHINTS<|im_end|>\n<|im_start|>assistant\n" + think))
    }

    func testWhatIsShown() {
        let stops = ["<|im_end|>", "<|im_start|>"]
        XCTAssertEqual(LocalPrompt.shown("Hello<|im_", stops).text, "Hello"); XCTAssertFalse(LocalPrompt.shown("Hello<|im_", stops).done)
        XCTAssertEqual(LocalPrompt.shown("Hello<|im_end|>more", stops).text, "Hello"); XCTAssertTrue(LocalPrompt.shown("Hello<|im_end|>more", stops).done)
        XCTAssertEqual(LocalPrompt.shown("<think>hmm</think>\n\nAnswer", stops).text, "Answer")
        XCTAssertEqual(LocalPrompt.shown("<think>still thinking", stops).text, "")
    }

    func testLettersSplitAcrossPieces() {
        var j = Utf8Joiner()
        for b in Array("café 👍".utf8) { j.add([b]) }
        XCTAssertEqual(j.text, "café 👍")
    }

    func testTheChoicesRead() throws {
        let json = #"{"available": true, "id": "flare-3", "choices": [{"id": "flare-3", "name": "Flare", "version": 3, "size": 2040109465, "min_ram_gb": 4, "tagline": "Fastest"}, {"id": "equinox-3", "name": "Equinox", "version": 3, "size": 3543348019, "min_ram_gb": 6}]}"#
        let k = try JSONDecoder().decode(PhoneKit.self, from: Data(json.utf8))
        XCTAssertEqual(k.choices.map(\.fullName), ["Flare 3", "Equinox 3"])
        XCTAssertEqual(k.choices[0].sizeText, "1.9 GB")
        XCTAssertEqual(k.choices[1].minRamGb, 6)
    }

    func testTheKitReadsAsTheServerSendsIt() throws {
        let json = #"{"available": true, "id": "flare-3", "name": "Flare", "version": 3, "size": 2000000000, "sha256": null, "preparing": true, "file": "/api/phone-model/file", "format": {"user_open": "<|im_start|>user\n", "turn_end": "<|im_end|>\n", "assistant_open": "<|im_start|>assistant\n", "stop": ["<|im_end|>"], "notes_intro": "Notes:\n", "question_intro": "\n\nQuestion: "}, "sampling": {"temperature": 0.7, "top_k": 20.0}, "max_reply_tokens": 1024, "context": 4096, "min_ram_gb": 4, "hints": "", "memory": {"on": true, "title": "T", "facts": [], "personal": "x"}}"#
        let k = try JSONDecoder().decode(PhoneKit.self, from: Data(json.utf8))
        XCTAssertEqual(k.fullName, "Flare 3")
        XCTAssertNil(k.sha256)
        XCTAssertEqual(k.sampling["temperature"], 0.7)
        // And back: what is kept on the phone reads again as the same.
        XCTAssertEqual(try JSONDecoder().decode(PhoneKit.self, from: JSONEncoder().encode(k)), k)
    }

    // MARK: Sync (LocalSyncTest)
    private let q = LocalTurn(mine: true, text: "why do tides happen")
    private let a = LocalTurn(mine: false, text: "The Moon pulls the sea.")

    func testACopyOfThePcChatHasNothingToSend() {
        let c = LocalSync.merge(nil, serverId: 7, title: "Tides", serverTurns: [q, a], now: 1000)
        XCTAssertEqual(c.serverId, 7); XCTAssertEqual(c.synced, 2); XCTAssertTrue(c.pending.isEmpty)
    }

    func testWhatWasWrittenOfflineIsKeptAndSentNextTime() {
        let copy = LocalSync.merge(nil, serverId: 7, title: "Tides", serverTurns: [q, a], now: 1000)
        var offline = copy
        offline.turns += [LocalTurn(mine: true, text: "and the sun?"), LocalTurn(mine: false, text: "A little too.")]
        XCTAssertEqual(offline.pending.map(\.text), ["and the sun?", "A little too."])
        let again = LocalSync.merge(offline, serverId: 7, title: "Tides", serverTurns: [q, a], now: 2000)
        XCTAssertEqual(again.id, offline.id)
        XCTAssertEqual(again.turns.count, 4); XCTAssertEqual(again.pending.count, 2)
    }

    func testARetriedSyncHasTheSameIdAndANewOneDoesNot() {
        let c = LocalChat(id: 5, title: "x", turns: [q, a])
        var renamed = c; renamed.title = "renamed"
        var synced = c; synced.synced = 2
        XCTAssertEqual(LocalSync.syncId(c), LocalSync.syncId(renamed))
        XCTAssertNotEqual(LocalSync.syncId(c), LocalSync.syncId(synced))
    }

    func testAnUnfinishedAnswerIsNotSent() {
        XCTAssertEqual(LocalChat(id: 5, title: "x", turns: [q, LocalTurn(mine: false, text: "…")]).pending.count, 1)
    }

    func testChatsWithSomethingToSendAreNeverDropped() {
        let old = LocalChat(id: 1, title: "old offline", turns: [q], updated: 1)
        let newer = (2...10).map { LocalChat(id: Int64($0), title: "c\($0)", turns: [q, a], serverId: Int64($0), synced: 2, updated: Int64($0) * 100) }
        let kept = LocalSync.keep([old] + newer, max: 3)
        XCTAssertTrue(kept.contains { $0.id == 1 })
        XCTAssertEqual(kept.count, 3)
        XCTAssertTrue(kept.contains { $0.id == 10 } && kept.contains { $0.id == 9 })
    }
}
