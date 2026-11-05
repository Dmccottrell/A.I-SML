import SwiftUI

// The phone model's screens (android/.../ui/LocalChatScreen.kt and the "This phone" card of Settings).

/// Settings > This phone: download the model from the PC, see how far it is, remove it, open the chats written here.
struct PhoneCard: View {
    @ObservedObject var phone: PhoneModel
    @ObservedObject var vm: AppModel

    private var chosen: PhoneChoice? { phone.choices.first { $0.id == (phone.kit?.id ?? phone.wanted ?? phone.choices.first?.id) } ?? phone.choices.first }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("The model on this phone").font(Emvryx.body(15, semibold: true)).foregroundStyle(Emvryx.text)
            Text("Your small Flare model is downloaded from your PC once, over Wi-Fi is best. Then chats still get answers when the PC is off or there is no signal. They are written on the phone and join your chats when the PC is back. Phone answers do not search the web.")
                .font(Emvryx.body(13)).foregroundStyle(Emvryx.muted)
            if phone.choices.count > 1, phone.status != .ready {
                Flow(spacing: 8) {
                    ForEach(phone.choices) { c in Seg(text: c.fullName + " · " + c.sizeText, on: c.id == chosen?.id) { phone.pick(c.id) } }
                }
            }
            switch phone.status {
            case .none:
                PwaButton(text: "Download " + (chosen?.fullName ?? "the model") + (chosen.map { " (" + $0.sizeText + ")" } ?? "")) { phone.download() }
                if !phone.canRun {
                    Text("This build of the app has no model engine inside, so the download is switched off (ios/README.md: the model on the phone).").font(Emvryx.body(13)).foregroundStyle(Emvryx.muted)
                }
            case let .downloading(done, total):
                ProgressView(value: Double(done), total: Double(max(total, 1))).tint(vm.palette.accent)
                Text("\(ByteCountFormatter.string(fromByteCount: done, countStyle: .file)) of \(ByteCountFormatter.string(fromByteCount: total, countStyle: .file)). Keep the app open: it carries on where it stopped.")
                    .font(Emvryx.body(13)).foregroundStyle(Emvryx.muted)
                PwaButton(text: "Cancel", ghost: true) { phone.cancel() }
            case .checking:
                HStack(spacing: 8) { ProgressView().tint(Emvryx.muted); Text("Checking the download…").font(Emvryx.body(14)).foregroundStyle(Emvryx.muted) }
            case .ready:
                Text("✓ " + (phone.kit?.fullName ?? "The model") + " is on this phone.").font(Emvryx.body(14, semibold: true)).foregroundStyle(Emvryx.text)
                if let n = phone.newer {
                    Text("A newer model (\(n.fullName)) is on the PC.").font(Emvryx.body(13)).foregroundStyle(Emvryx.muted)
                    PwaButton(text: "Download " + n.fullName) { phone.remove(); phone.download() }
                }
                PwaButton(text: "Open the chats on this phone") { vm.screen = .local }
                PwaButton(text: "Remove the model from this phone", ghost: true) { phone.remove() }
            case let .failed(message):
                Text(message).font(Emvryx.body(14)).foregroundStyle(Emvryx.danger)
                PwaButton(text: "Try again") { phone.download() }
            }
        }
        .task { await phone.loadChoices() }
    }
}

/// "On this phone": the chats written here with the model on the phone. Works with the PC off.
struct LocalChatView: View {
    @ObservedObject var vm: AppModel
    @ObservedObject var phone: PhoneModel
    @State private var text = ""
    @State private var shown = ""
    @State private var problem: String?
    @State private var working = false

    private var open: LocalChat? { phone.openChat.flatMap { id in phone.chats.first { $0.id == id } } }

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Button { if open != nil { phone.openChat = nil } else { vm.start() } } label: {
                    Label(open != nil ? "Chats" : "Back", systemImage: "chevron.left").font(Emvryx.body(16, semibold: true)).foregroundStyle(Emvryx.text)
                }
                .accessibilityLabel(open != nil ? "Back to the phone's chats" : "Back to the PC")
                Spacer()
                if open == nil { Button { phone.openChat = phone.newChat().id } label: { Image(systemName: "plus").foregroundStyle(Emvryx.text).frame(width: 44, height: 44) }.accessibilityLabel("New chat on this phone") }
            }
            .overlay(Text(open?.title ?? "On this phone").font(Emvryx.body(17, semibold: true)).foregroundStyle(Emvryx.text).lineLimit(1).padding(.horizontal, 90))
            .padding(.horizontal, 16).frame(height: 56)
            Rectangle().fill(Emvryx.line).frame(height: 1)
            if !phone.ready {
                VStack(spacing: 14) {
                    Logo().frame(width: 48, height: 48)
                    Text("The model is not on this phone yet. Download it in Settings while the PC is on.").font(Emvryx.body(16)).foregroundStyle(Emvryx.muted).multilineTextAlignment(.center)
                }.padding(28).frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let chat = open {
                thread(chat)
                composer(chat)
            } else {
                list
            }
        }
        .background(Emvryx.bg.ignoresSafeArea())
        .task(id: phone.ask) { await askIfWaiting() }
        .onAppear { if let d = phone.draft { text = d; phone.draft = nil } }
    }

    // MARK: The list

    private var list: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 8) {
                Text("Chats written here stay on the phone until the PC is back; then they join your chats.").font(Emvryx.body(14)).foregroundStyle(Emvryx.muted).padding(.top, 14)
                PwaButton(text: "New chat on this phone") { phone.openChat = phone.newChat().id }
                if phone.chats.isEmpty { Text("No chats on this phone yet.").font(Emvryx.body(15)).foregroundStyle(Emvryx.muted).padding(.top, 10) }
                ForEach(phone.chats.sorted { $0.updated > $1.updated }) { c in
                    Button { phone.openChat = c.id } label: {
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(c.title).font(Emvryx.body(16, semibold: true)).foregroundStyle(Emvryx.text).lineLimit(1)
                                Text(c.turns.last?.text ?? "").font(Emvryx.body(13)).foregroundStyle(Emvryx.muted).lineLimit(1)
                            }
                            Spacer(minLength: 8)
                            if !c.pending.isEmpty { Text("waiting to send").font(Emvryx.body(12)).foregroundStyle(Emvryx.muted) }
                        }
                        .padding(14).frame(maxWidth: .infinity, alignment: .leading).background(Emvryx.surface, in: RoundedRectangle(cornerRadius: 14))
                    }
                    .buttonStyle(.plain)
                    .contextMenu { Button("Delete", role: .destructive) { phone.deleteChat(c.id) } }
                    .accessibilityLabel("Phone chat " + c.title)
                    .accessibilityIdentifier("phonechat")
                }
            }
            .padding(.horizontal, 16).padding(.bottom, 20)
        }
    }

    // MARK: A chat

    private func thread(_ chat: LocalChat) -> some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 18) {
                    ForEach(Array(chat.turns.enumerated()), id: \.offset) { i, t in
                        if t.mine {
                            HStack { Spacer(minLength: 0)
                                Text(t.text).font(Emvryx.body(16)).foregroundStyle(Emvryx.text).padding(.horizontal, 16).padding(.vertical, 12)
                                    .background(Emvryx.surface2, in: Corners(topLeading: 18, topTrailing: 18, bottomTrailing: 4, bottomLeading: 18))
                                    .frame(maxWidth: (UIScreen.main.bounds.width - 32) * 0.8, alignment: .trailing)
                            }
                        } else {
                            let last = i == chat.turns.count - 1
                            let body = last && working ? (shown.isEmpty ? "" : shown) : t.text
                            VStack(alignment: .leading, spacing: 6) {
                                HStack(spacing: 6) { Logo().frame(width: 16, height: 16); Text((phone.kit?.fullName ?? "Emvryx") + " · on this phone").font(Emvryx.body(14)).foregroundStyle(Emvryx.muted) }
                                VStack(alignment: .leading, spacing: 10) {
                                    if body.isEmpty { ThinkingWord(word: "Thinking") }
                                    else {
                                        ForEach(Array(Markdown.blocks(body + (last && working ? " ▍" : "")).enumerated()), id: \.offset) { _, b in
                                            switch b {
                                            case let .prose(p): Text(p).font(Emvryx.body(16)).foregroundStyle(Emvryx.text)
                                            case let .code(c): ScrollView(.horizontal, showsIndicators: false) { Text(c).font(.system(size: 14, design: .monospaced)).foregroundStyle(Emvryx.text).padding(12) }
                                                .background(Emvryx.bg, in: RoundedRectangle(cornerRadius: 12))
                                            }
                                        }
                                        .textSelection(.enabled)
                                    }
                                }
                                .padding(.horizontal, 18).padding(.vertical, 14).frame(maxWidth: .infinity, alignment: .leading)
                                .background(Emvryx.surface, in: Corners(topLeading: 18, topTrailing: 18, bottomTrailing: 18, bottomLeading: 4))
                                .overlay(Corners(topLeading: 18, topTrailing: 18, bottomTrailing: 18, bottomLeading: 4).stroke(Emvryx.line, lineWidth: 1))
                            }
                            .frame(maxWidth: (UIScreen.main.bounds.width - 32) * 0.94, alignment: .leading)
                        }
                    }
                    if let p = problem { FailureCard(failure: Failure(message: p)) { problem = nil } }
                    Color.clear.frame(height: 1).id("end")
                }
                .padding(.horizontal, 16).padding(.vertical, 16)
            }
            .scrollDismissesKeyboard(.interactively)
            .onChange(of: shown) { _ in proxy.scrollTo("end", anchor: .bottom) }
            .onChange(of: chat.turns.count) { _ in proxy.scrollTo("end", anchor: .bottom) }
        }
    }

    private func composer(_ chat: LocalChat) -> some View {
        let p = vm.palette
        return HStack(alignment: .bottom, spacing: 8) {
            TextField("", text: $text, prompt: Text("Message the model on this phone…").foregroundColor(Emvryx.muted), axis: .vertical)
                .font(Emvryx.body(16)).foregroundStyle(Emvryx.text).tint(p.accent).lineLimit(1...6).accessibilityLabel("Message the phone")
            Button { working ? phone.stop() : send(chat) } label: {
                ZStack {
                    if working { RoundedRectangle(cornerRadius: 2).fill(Emvryx.text).frame(width: 12, height: 12) }
                    else { Image(systemName: "arrow.up").font(.system(size: 18, weight: .bold)).foregroundStyle(p.onAccent) }
                }
                .frame(width: 44, height: 44).background(working ? Emvryx.surface2 : p.accent, in: RoundedRectangle(cornerRadius: 12))
            }
            .buttonStyle(.plain).disabled(!working && text.isBlank).opacity(!working && text.isBlank ? 0.45 : 1)
            .accessibilityLabel(working ? "Stop" : "Send to the phone")
        }
        .padding(.leading, 16).padding(.trailing, 10).padding(.vertical, 10)
        .background(Emvryx.surface, in: RoundedRectangle(cornerRadius: 20)).overlay(RoundedRectangle(cornerRadius: 20).stroke(Emvryx.line, lineWidth: 1))
        .padding(.horizontal, 16).padding(.vertical, 8)
    }

    private func send(_ chat: LocalChat) {
        let q = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty, !working else { return }
        text = ""
        ask(q, in: chat.id)
    }

    /// A question carried over from the chat when the PC dropped: answered here at once.
    private func askIfWaiting() async {
        guard phone.ready, let q = phone.ask, let id = phone.openChat else { return }
        phone.ask = nil
        ask(q, in: id)
    }

    private func ask(_ question: String, in id: Int64) {
        working = true; shown = ""; problem = nil
        Task {
            problem = await phone.answer(chatId: id, question: question) { shown = $0 }
            working = false
        }
    }
}
