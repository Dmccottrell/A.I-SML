// The engine that runs the model file on the phone, with llama.cpp (https://github.com/ggml-org/llama.cpp, MIT licence), pinned to the
// version in ios/scripts/get-llama.sh. It is only compiled when that library has been built into the project (`import llama` exists):
// without it the app still builds and says so (NoEngine). Written against the calls of that version (include/llama.h, and the project's own
// examples/llama.swiftui/llama.cpp.swift).
#if canImport(llama)
import Foundation
import llama

final class LlamaEngine: LocalEngine {
    private var model: OpaquePointer?
    private var context: OpaquePointer?
    private var vocab: OpaquePointer?
    private let lock = NSLock()
    private var stopping = false

    var canRun: Bool { true }

    deinit { close() }

    func load(path: String, context contextSize: Int) throws {
        close()
        llama_backend_init()
        var modelParams = llama_model_default_params()
        #if targetEnvironment(simulator)
        modelParams.n_gpu_layers = 0                                   // the simulator has no usable Metal GPU for this
        #endif
        guard let m = llama_model_load_from_file(path, modelParams) else { throw LocalEngineError(message: "The model could not be loaded.") }
        var contextParams = llama_context_default_params()
        contextParams.n_ctx = UInt32(contextSize)
        contextParams.n_batch = 512
        let threads = Int32(max(1, min(8, ProcessInfo.processInfo.processorCount - 2)))
        contextParams.n_threads = threads
        contextParams.n_threads_batch = threads
        guard let c = llama_init_from_model(m, contextParams) else {
            llama_model_free(m)
            throw LocalEngineError(message: "The model could not be loaded: the phone may not have enough free memory. Close other apps and try again.")
        }
        model = m
        context = c
        vocab = llama_model_get_vocab(m)
    }

    func close() {
        if let c = context { llama_free(c) }
        if let m = model { llama_model_free(m) }
        context = nil; model = nil; vocab = nil
    }

    func stop() { lock.lock(); stopping = true; lock.unlock() }
    private var shouldStop: Bool { lock.lock(); defer { lock.unlock() }; return stopping }

    /// The prompt as tokens. Special markers like <|im_start|> in the text become the model's own marker tokens (parse_special).
    private func tokenize(_ text: String, addSpecial: Bool) -> [llama_token] {
        guard let vocab else { return [] }
        let bytes = Array(text.utf8)
        var tokens = [llama_token](repeating: 0, count: bytes.count + 8)
        var n = bytes.withUnsafeBufferPointer { b in
            b.baseAddress!.withMemoryRebound(to: CChar.self, capacity: bytes.count) { p in
                llama_tokenize(vocab, p, Int32(bytes.count), &tokens, Int32(tokens.count), addSpecial, true)
            }
        }
        if n < 0 {                                                    // the buffer was too small: -n says how many are needed
            tokens = [llama_token](repeating: 0, count: Int(-n))
            n = bytes.withUnsafeBufferPointer { b in
                b.baseAddress!.withMemoryRebound(to: CChar.self, capacity: bytes.count) { p in
                    llama_tokenize(vocab, p, Int32(bytes.count), &tokens, Int32(tokens.count), addSpecial, true)
                }
            }
        }
        return n > 0 ? Array(tokens.prefix(Int(n))) : []
    }

    func count(_ text: String) -> Int { tokenize(text, addSpecial: false).count }

    /// The bytes of one token, special markers included (so the stop markers can be seen in the text).
    private func pieceBytes(_ token: llama_token) -> [UInt8] {
        guard let vocab else { return [] }
        var buf = [CChar](repeating: 0, count: 32)
        var n = llama_token_to_piece(vocab, token, &buf, Int32(buf.count), 0, true)
        if n < 0 {
            buf = [CChar](repeating: 0, count: Int(-n))
            n = llama_token_to_piece(vocab, token, &buf, Int32(buf.count), 0, true)
        }
        return n > 0 ? buf.prefix(Int(n)).map { UInt8(bitPattern: $0) } : []
    }

    func generate(prompt: String, maxTokens: Int, sampling: [String: Double], piece: ([UInt8]) -> Bool) -> LocalEnd {
        guard let context, let vocab else { return .failed }
        lock.lock(); stopping = false; lock.unlock()
        let tokens = tokenize(prompt, addSpecial: true)
        let window = Int(llama_n_ctx(context))
        if tokens.isEmpty { return .failed }
        if tokens.count >= window { return .tooLong }
        llama_memory_clear(llama_get_memory(context), true)

        // The way the model picks its words: the PC's settings (temperature, top_k ...) as sent in the kit.
        let chain = llama_sampler_chain_init(llama_sampler_chain_default_params())
        defer { llama_sampler_free(chain) }
        if let rp = sampling["repeat_penalty"], rp != 1 || (sampling["presence_penalty"] ?? 0) != 0 {
            llama_sampler_chain_add(chain, llama_sampler_init_penalties(llama_vocab_n_tokens(vocab), 64, Float(rp), 0, Float(sampling["presence_penalty"] ?? 0)))
        }
        if let k = sampling["top_k"], k > 0 { llama_sampler_chain_add(chain, llama_sampler_init_top_k(Int32(k))) }
        if let p = sampling["top_p"], p > 0, p < 1 { llama_sampler_chain_add(chain, llama_sampler_init_top_p(Float(p), 1)) }
        if let p = sampling["min_p"], p > 0 { llama_sampler_chain_add(chain, llama_sampler_init_min_p(Float(p), 1)) }
        llama_sampler_chain_add(chain, llama_sampler_init_temp(Float(sampling["temperature"] ?? 0.7)))
        llama_sampler_chain_add(chain, llama_sampler_init_dist(UInt32.random(in: 0...UInt32.max)))

        // Read the prompt, a batch at a time.
        var batch = llama_batch_init(512, 0, 1)
        defer { llama_batch_free(batch) }
        var position = 0
        while position < tokens.count {
            let n = min(512, tokens.count - position)
            batch.n_tokens = Int32(n)
            for i in 0..<n {
                batch.token[i] = tokens[position + i]
                batch.pos[i] = Int32(position + i)
                batch.n_seq_id[i] = 1
                batch.seq_id[i]![0] = 0
                batch.logits[i] = (position + i == tokens.count - 1) ? 1 : 0       // only the last one needs an answer
            }
            if llama_decode(context, batch) != 0 { return .failed }
            position += n
        }

        // Write the answer, one token at a time.
        var written = 0
        var current = Int32(tokens.count)
        while written < maxTokens {
            if shouldStop { return .done }
            let token = llama_sampler_sample(chain, context, -1)
            if llama_vocab_is_eog(vocab, token) { return .done }
            if !piece(pieceBytes(token)) { return .done }
            written += 1
            if Int(current) + 1 >= window { return .done }
            batch.n_tokens = 1
            batch.token[0] = token
            batch.pos[0] = current
            batch.n_seq_id[0] = 1
            batch.seq_id[0]![0] = 0
            batch.logits[0] = 1
            if llama_decode(context, batch) != 0 { return .failed }
            current += 1
        }
        return .done
    }
}
#endif
