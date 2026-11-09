import AVFoundation
import Speech

/// Hold to talk (the website's chat_voice): the iPhone's own speech recognition turns what you say into text in the message box.
/// The first time, iOS asks for the microphone and for speech recognition (the descriptions are in project.yml).
@MainActor
final class SpeechInput: ObservableObject {
    @Published private(set) var listening = false
    /// Why it could not listen (no permission, no microphone), to show once.
    @Published var problem: String?

    private let recognizer = SFSpeechRecognizer(locale: Locale.current) ?? SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private let engine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?

    /// Starts listening; every update of the words calls [onText] with [base] (what was already typed) followed by what was heard.
    func start(base: String, onText: @escaping (String) -> Void) {
        guard !listening else { return }
        Task {
            if let why = await Self.permission() { problem = why; return }
            guard let recognizer, recognizer.isAvailable else { problem = "Speech recognition is not available right now."; return }
            #if targetEnvironment(simulator)
            // The simulator has no microphone to open: asking for it aborts the app (an audio RPC timeout). A real iPhone listens as below.
            problem = "Voice needs the microphone of a real iPhone. It cannot listen in the simulator."
            return
            #else
            do {
                let session = AVAudioSession.sharedInstance()
                try session.setCategory(.record, mode: .measurement, options: .duckOthers)
                try session.setActive(true, options: .notifyOthersOnDeactivation)
                let request = SFSpeechAudioBufferRecognitionRequest()
                request.shouldReportPartialResults = true
                self.request = request
                let input = engine.inputNode
                input.removeTap(onBus: 0)
                input.installTap(onBus: 0, bufferSize: 1024, format: input.outputFormat(forBus: 0)) { buffer, _ in request.append(buffer) }
                engine.prepare()
                try engine.start()
                listening = true
                let prefix = base.isEmpty || base.hasSuffix(" ") ? base : base + " "
                task = recognizer.recognitionTask(with: request) { [weak self] result, error in
                    Task { @MainActor in
                        if let r = result { onText(prefix + r.bestTranscription.formattedString) }
                        if error != nil || result?.isFinal == true { self?.stop() }
                    }
                }
            } catch {
                problem = "The microphone could not be used."
                stop()
            }
            #endif
        }
    }

    /// Stops listening (the words so far stay in the box).
    func stop() {
        if engine.isRunning { engine.stop(); engine.inputNode.removeTap(onBus: 0) }
        request?.endAudio()
        task?.finish()
        request = nil
        task = nil
        listening = false
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    /// Asks for the microphone and for speech recognition; nil when both are allowed, otherwise what to tell the person.
    private static func permission() async -> String? {
        let speech = await withCheckedContinuation { c in SFSpeechRecognizer.requestAuthorization { c.resume(returning: $0) } }
        guard speech == .authorized else { return "Allow Speech Recognition for Emvryx in Settings to talk instead of typing." }
        let mic = await withCheckedContinuation { c in AVAudioSession.sharedInstance().requestRecordPermission { c.resume(returning: $0) } }
        return mic ? nil : "Allow the Microphone for Emvryx in Settings to talk instead of typing."
    }
}

/// Read aloud: the answer spoken by the iPhone itself (the website's "Read aloud" button), without code blocks and marks.
@MainActor
final class Speaker: NSObject, ObservableObject, AVSpeechSynthesizerDelegate {
    static let shared = Speaker()
    @Published private(set) var speaking: Int?                // the local id of the answer being read
    private let synth = AVSpeechSynthesizer()

    override init() { super.init(); synth.delegate = self }

    func toggle(_ id: Int, text: String) {
        if synth.isSpeaking { synth.stopSpeaking(at: .immediate); if speaking == id { speaking = nil; return } }
        let u = AVSpeechUtterance(string: Self.plain(text))
        u.voice = AVSpeechSynthesisVoice(language: Locale.current.identifier.replacingOccurrences(of: "_", with: "-"))
        speaking = id
        synth.speak(u)
    }

    /// The text without ``` code blocks, headings, bold marks, quotes and the target of links.
    static func plain(_ text: String) -> String {
        text.replacingOccurrences(of: "```[\\s\\S]*?```", with: " (code) ", options: .regularExpression)
            .replacingOccurrences(of: "\\[([^\\]]+)\\]\\([^)]+\\)", with: "$1", options: .regularExpression)
            .replacingOccurrences(of: "[#*_`>|]", with: "", options: .regularExpression)
    }

    nonisolated func speechSynthesizer(_ s: AVSpeechSynthesizer, didFinish u: AVSpeechUtterance) { Task { @MainActor in self.speaking = nil } }
    nonisolated func speechSynthesizer(_ s: AVSpeechSynthesizer, didCancel u: AVSpeechUtterance) { Task { @MainActor in if !self.synth.isSpeaking { self.speaking = nil } } }
}
