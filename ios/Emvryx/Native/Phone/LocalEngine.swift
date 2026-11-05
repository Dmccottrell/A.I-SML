import Foundation

/// How a reply on the phone ended.
enum LocalEnd: Equatable { case done, tooLong, failed }

struct LocalEngineError: Error, Equatable { var message: String }

/// The part that actually reads and writes words with the model file (llama.cpp on a real build). Everything around it (the download, the
/// prompt, the chats, the sync) does not depend on it, so it is tested with a stand-in and the engine can be swapped.
protocol LocalEngine: AnyObject {
    /// Whether this build of the app has an engine inside (the llama.cpp library has to be built in: ios/scripts/get-llama.sh).
    var canRun: Bool { get }
    func load(path: String, context: Int) throws
    /// How many tokens (small pieces of text) the model makes of [text]; used to leave out the oldest turns when a chat does not fit.
    func count(_ text: String) -> Int
    /// Writes the answer to [prompt]; calls [piece] with each piece of bytes and stops when it returns false.
    func generate(prompt: String, maxTokens: Int, sampling: [String: Double], piece: ([UInt8]) -> Bool) -> LocalEnd
    func stop()
    func close()
}

/// Used when the llama.cpp library is not built into this app.
final class NoEngine: LocalEngine {
    var canRun: Bool { false }
    func load(path: String, context: Int) throws { throw LocalEngineError(message: "This build of the app has no model engine inside.") }
    func count(_ text: String) -> Int { text.count / 3 }
    func generate(prompt: String, maxTokens: Int, sampling: [String: Double], piece: ([UInt8]) -> Bool) -> LocalEnd { .failed }
    func stop() {}
    func close() {}
}

/// A stand-in engine for tests: writes back what it was asked, a few letters at a time, so everything around it can be checked without a model.
final class ScriptedEngine: LocalEngine {
    var canRun: Bool { true }
    private(set) var loaded: String?
    private(set) var prompts: [String] = []
    private var stopping = false
    var reply: (String) -> String = { prompt in
        let turn = prompt.components(separatedBy: "<|im_start|>user\n").last?.components(separatedBy: "<|im_end|>").first ?? "?"
        let q = turn.components(separatedBy: "\n\n").first ?? turn                     // the question, without the instructions that follow it
        return "Phone answer to: " + q.trimmingCharacters(in: .whitespacesAndNewlines) + "<|im_end|>"
    }
    var delayPerPiece: UInt32 = 0
    func load(path: String, context: Int) throws { loaded = path }
    func count(_ text: String) -> Int { text.count / 3 }
    func generate(prompt: String, maxTokens: Int, sampling: [String: Double], piece: ([UInt8]) -> Bool) -> LocalEnd {
        stopping = false
        prompts.append(prompt)
        for chunk in reply(prompt).utf8.chunked(4) {
            if stopping { return .done }
            if delayPerPiece > 0 { usleep(delayPerPiece) }
            if !piece(Array(chunk)) { return .done }
        }
        return .done
    }
    func stop() { stopping = true }
    func close() { loaded = nil }
}

private extension String.UTF8View {
    func chunked(_ n: Int) -> [[UInt8]] {
        var out: [[UInt8]] = [], cur: [UInt8] = []
        for b in self { cur.append(b); if cur.count == n { out.append(cur); cur = [] } }
        if !cur.isEmpty { out.append(cur) }
        return out
    }
}
