import SwiftUI

/// What the chat screen can slide up (Android's dialogs).
enum ChatSheet: Identifiable {
    case regen, report(Bubble), edit(Bubble), share, saveAs(String), memory, usage, archived
    case file(URL)

    var id: String {
        switch self {
        case .regen: return "regen"
        case let .report(b): return "report\(b.id)"
        case let .edit(b): return "edit\(b.id)"
        case .share: return "share"
        case .saveAs: return "saveAs"
        case .memory: return "memory"
        case .usage: return "usage"
        case .archived: return "archived"
        case let .file(u): return "file" + u.absoluteString
        }
    }
}

// MARK: - The empty chat and the thread

struct EmptyChat: View {
    @ObservedObject var vm: AppModel
    var body: some View {
        ScrollView {
            VStack(spacing: 0) {
                Spacer(minLength: 80)
                Logo(kind: vm.currentModel?.name ?? "flare", violet: vm.flag("violet_theme")).frame(width: 64, height: 64)
                Text("How can I help?").font(Emvryx.heading(32)).kerning(-0.6).foregroundStyle(Emvryx.text)
                    .multilineTextAlignment(.center).padding(.top, 12).padding(.bottom, 6)
                Text(vm.isPrivate ? "Private chat: not saved, never searched on the web, and it uses no memory. Gone when you leave it."
                                  : "Ask anything. Pick a model and how much it should think under the box.")
                    .font(Emvryx.body(16)).foregroundStyle(Emvryx.muted).multilineTextAlignment(.center)
                if let f = vm.failure { FailureCard(failure: f) { vm.failure = nil }.padding(.top, 16) }
                Spacer(minLength: 24)
            }
            .padding(.horizontal, 24).frame(maxWidth: .infinity)
        }
    }
}

struct ThreadView: View {
    @ObservedObject var vm: AppModel
    let onSheet: (ChatSheet) -> Void
    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 18) {
                    ForEach(vm.bubbles) { b in
                        if b.mine { UserMessage(vm: vm, bubble: b, onSheet: onSheet) }
                        else { AiMessage(vm: vm, bubble: b, isLast: b.id == vm.bubbles.last?.id, onSheet: onSheet) }
                    }
                    if let f = vm.failure { FailureCard(failure: f) { vm.failure = nil } }
                    Color.clear.frame(height: 1).id("end")
                }
                .padding(.horizontal, 16).padding(.vertical, 16)
            }
            .scrollDismissesKeyboard(.interactively)
            .onChange(of: vm.bubbles) { _ in proxy.scrollTo("end", anchor: .bottom) }
            .onAppear { proxy.scrollTo("end", anchor: .bottom) }
        }
    }
}

// MARK: - Your messages

/// .msg.user .bubble: your words in a filled bubble on the right, with the pictures and files that went with them. Hold it to copy or edit.
struct UserMessage: View {
    @ObservedObject var vm: AppModel
    let bubble: Bubble
    let onSheet: (ChatSheet) -> Void

    private var hasWords: Bool { !bubble.text.isBlank && bubble.text != "(sent a picture)" && bubble.text != "(sent a file)" }

    var body: some View {
        HStack {
            Spacer(minLength: 0)
            VStack(alignment: .trailing, spacing: 6) {
                DocRow(vm: vm, docs: bubble.docs)
                if hasWords {
                    Text(bubble.text).font(Emvryx.body(16)).lineSpacing(24 - 16 * 1.302).foregroundStyle(Emvryx.text)
                        .padding(.horizontal, 16).padding(.vertical, 12)
                        .background(Emvryx.surface2, in: Corners(topLeading: 18, topTrailing: 18, bottomTrailing: 4, bottomLeading: 18))
                        .contextMenu {
                            Button("Copy") { UIPasteboard.general.string = bubble.text }
                            if bubble.serverId > 0 && !vm.streaming { Button("Edit and ask again") { onSheet(.edit(bubble)) } }
                        }
                }
            }
            .frame(maxWidth: (UIScreen.main.bounds.width - 32) * 0.8, alignment: .trailing)
        }
    }
}

// MARK: - The model's answers

/// .msg.ai: the model's logo and name over a bordered card; the reply is written into it as it comes, then Copy, Regenerate and the rest.
struct AiMessage: View {
    @ObservedObject var vm: AppModel
    let bubble: Bubble
    let isLast: Bool
    let onSheet: (ChatSheet) -> Void
    @ObservedObject private var speaker = Speaker.shared
    @State private var copied = false

    var body: some View {
        let who = vm.models.first { $0.id == bubble.model }
        let shape = Corners(topLeading: 18, topTrailing: 18, bottomTrailing: 18, bottomLeading: 4)
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Logo(kind: who?.name ?? "flare").frame(width: 16, height: 16)
                Text((who?.fullName ?? "Emvryx") + (bubble.cut && !bubble.streaming ? " · stopped" : "") + (bubble.autoNote.map { " · " + $0 } ?? ""))
                    .font(Emvryx.body(14)).foregroundStyle(Emvryx.muted)
            }
            VStack(alignment: .leading, spacing: 10) {
                if bubble.streaming && bubble.text.isEmpty {
                    ThinkingWord(word: vm.working ?? vm.thinkingWord)
                } else {
                    ForEach(Array(Markdown.blocks(bubble.text + (bubble.streaming ? " ▍" : "")).enumerated()), id: \.offset) { _, block in
                        switch block {
                        case let .prose(text):
                            Text(text).font(Emvryx.body(16)).lineSpacing(24 - 16 * 1.302).foregroundStyle(Emvryx.text).tint(vm.palette.accentText)
                        case let .code(code):
                            ScrollView(.horizontal, showsIndicators: false) {
                                Text(code).font(.system(size: 14, design: .monospaced)).foregroundStyle(Emvryx.text).padding(12)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(Emvryx.bg, in: RoundedRectangle(cornerRadius: 12))
                            .overlay(RoundedRectangle(cornerRadius: 12).stroke(Emvryx.line, lineWidth: 1))
                        }
                    }
                    .textSelection(.enabled)
                    if bubble.cut { Text("Stopped.").font(Emvryx.body(13)).foregroundStyle(Emvryx.muted) }
                }
            }
            .padding(.horizontal, 18).padding(.vertical, 14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Emvryx.surface, in: shape)
            .overlay(shape.stroke(Emvryx.line, lineWidth: 1))
            if !bubble.streaming && !bubble.text.isEmpty { actions }
            if let m = bubble.memory { Note(text: m) }
        }
        .frame(maxWidth: (UIScreen.main.bounds.width - 32) * 0.94, alignment: .leading)
    }

    private var actions: some View {
        let saved = (vm.chatId ?? -1) >= 0 && bubble.serverId > 0
        let stronger = isLast && !vm.streaming ? vm.strongerModel(than: bubble.model) : nil
        return Flow(spacing: 8) {
            Chip(text: copied ? "Copied" : "Copy") { UIPasteboard.general.string = bubble.text; copied = true }
            if saved { Chip(text: bubble.liked ?? "👍 Right", on: bubble.liked != nil) { if bubble.liked == nil { vm.like(bubble) } } }
            if isLast && !vm.streaming && bubble.cut { Chip(text: "Continue →") { vm.continueReply() } }
            if isLast && !vm.streaming { Chip(text: "Regenerate ▾") { onSheet(.regen) } }
            if vm.flag("chat_voice") {
                Chip(text: speaker.speaking == bubble.id ? "■ Stop" : "🔊 Read aloud") { speaker.toggle(bubble.id, text: bubble.text) }
            }
            Menu {
                Button("Save as…") { onSheet(.saveAs(bubble.text)) }
                if let m = stronger { Button("Ask \(m.name) (a stronger model)") { vm.askStronger(m) } }
                if bubble.serverId > 0 && !vm.streaming && vm.chatId != nil { Button("Branch: new chat from here") { vm.branch(bubble) } }
                if saved { Button(bubble.fb.isEmpty ? "Report a problem…" : "Reported (thanks)") { if bubble.fb.isEmpty { onSheet(.report(bubble)) } } }
            } label: {
                Text("⋯").font(Emvryx.body(14)).foregroundStyle(Emvryx.muted).padding(.horizontal, 14).padding(.vertical, 6).frame(minHeight: 36)
                    .overlay(Capsule().stroke(Emvryx.line, lineWidth: 1))
            }
            .accessibilityLabel("More")
        }
    }
}

/// The thinking word, fading in and out while nothing is written yet.
struct ThinkingWord: View {
    let word: String
    @State private var dim = false
    var body: some View {
        Text(word).font(Emvryx.body(16)).foregroundStyle(Emvryx.muted).opacity(dim ? 0.45 : 1)
            .onAppear { withAnimation(.easeInOut(duration: 0.9).repeatForever(autoreverses: true)) { dim = true } }
            .accessibilityLabel("Thinking")
    }
}
