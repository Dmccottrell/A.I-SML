#if canImport(llama)
import XCTest
@testable import Emvryx

/// The real engine with a real model file: only when the llama.cpp library is built in (ios/scripts/get-llama.sh) and a model file is given
/// (TEST_RUNNER_EMVRYX_TEST_GGUF=/path/to/model.gguf, for example your own Flare file). Any small ChatML model will do.
final class LlamaEngineTests: XCTestCase {
    private func model() throws -> String {
        let path = ProcessInfo.processInfo.environment["EMVRYX_TEST_GGUF"] ?? ""
        try XCTSkipIf(path.isEmpty || !FileManager.default.fileExists(atPath: path), "needs a model file (EMVRYX_TEST_GGUF)")
        return path
    }

    func testTheRealEngineLoadsAModelAndWritesAnAnswer() throws {
        let engine = LlamaEngine()
        XCTAssertTrue(engine.canRun)
        try engine.load(path: try model(), context: 1024)
        defer { engine.close() }
        XCTAssertGreaterThan(engine.count("Hello there, how are you today?"), 2)
        var joiner = Utf8Joiner()
        let end = engine.generate(prompt: "<|im_start|>user\nSay hello.<|im_end|>\n<|im_start|>assistant\n", maxTokens: 24, sampling: ["temperature": 0.7, "top_k": 20]) { joiner.add($0); return true }
        XCTAssertEqual(end, .done)
        XCTAssertFalse(joiner.text.isEmpty, "the model wrote nothing")
    }

    func testStopEndsAnAnswerEarly() throws {
        let engine = LlamaEngine()
        try engine.load(path: try model(), context: 1024)
        defer { engine.close() }
        var pieces = 0
        _ = engine.generate(prompt: "<|im_start|>user\nCount to one hundred.<|im_end|>\n<|im_start|>assistant\n", maxTokens: 200, sampling: ["temperature": 0.7]) { _ in
            pieces += 1
            if pieces == 3 { engine.stop() }
            return true
        }
        XCTAssertLessThan(pieces, 20)
    }

    func testAPromptLongerThanTheWindowIsRefused() throws {
        let engine = LlamaEngine()
        try engine.load(path: try model(), context: 256)
        defer { engine.close() }
        XCTAssertEqual(engine.generate(prompt: String(repeating: "word ", count: 2000), maxTokens: 8, sampling: [:]) { _ in true }, .tooLong)
    }

    func testAModelThatIsNotThereGivesAReasonNotACrash() {
        XCTAssertThrowsError(try LlamaEngine().load(path: "/no/such/model.gguf", context: 512))
    }
}
#endif
