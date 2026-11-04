import PhotosUI
import SwiftUI
import UniformTypeIdentifiers

/// The native chat (android/.../ui/ChatScreen.kt, classic look): the top bar, the messages, the message box with the model and effort
/// pickers, the usage line, and the chat list that slides in from the left.
struct ChatView: View {
    @ObservedObject var vm: AppModel
    @State private var drawer = false
    @State private var menu: PickMenu?
    @State private var sheet: ChatSheet?

    enum PickMenu { case model, effort }

    var body: some View {
        let p = vm.palette
        ZStack(alignment: .leading) {
            Emvryx.bg.ignoresSafeArea()
            VStack(spacing: 0) {
                TopBar(vm: vm, onMenu: { withAnimation(.easeOut(duration: 0.25)) { drawer = true } }, onSheet: { sheet = $0 })
                if let t = vm.toast { ToastLine(text: t) { vm.toast = nil } }
                ZStack(alignment: .bottom) {
                    if vm.bubbles.isEmpty { EmptyChat(vm: vm) } else { ThreadView(vm: vm) { sheet = $0 } }
                    if let m = menu {
                        Color.black.opacity(0.001).onTapGesture { menu = nil }
                        PopMenu {
                            switch m {
                            case .model: ModelMenu(vm: vm) { menu = nil }
                            case .effort: EffortMenu(vm: vm) { menu = nil }
                            }
                        }
                    }
                }
                Composer(vm: vm, open: menu, onMenu: { which in menu = menu == which ? nil : which }, onSheet: { sheet = $0 })
                UsageLine(usage: vm.usage, palette: p).onTapGesture { if vm.usage != nil { sheet = .usage } }
            }
            if drawer {
                Color.black.opacity(0.45).ignoresSafeArea()
                    .onTapGesture { withAnimation(.easeOut(duration: 0.25)) { drawer = false } }
                    .transition(.opacity)
                Sidebar(vm: vm, done: { withAnimation(.easeOut(duration: 0.25)) { drawer = false } }, onSheet: { sheet = $0 })
                    .transition(.move(edge: .leading))
            }
        }
        .preferredColorScheme(.dark)
        .environment(\.palette, p)
        .sheet(item: $sheet) { s in sheetView(s).environment(\.palette, p).presentationDetents(detents(s)) }
    }

    private func detents(_ s: ChatSheet) -> Set<PresentationDetent> {
        switch s { case .edit, .report, .share, .archived, .memory: return [.large]; default: return [.medium, .large] }
    }

    @ViewBuilder private func sheetView(_ s: ChatSheet) -> some View {
        let close = { sheet = nil }
        switch s {
        case .regen: RegenSheet(vm: vm, done: close)
        case let .report(b): ReportSheet(vm: vm, bubble: b, done: close)
        case let .edit(b): EditSheet(vm: vm, bubble: b, done: close)
        case .share: ShareLinkSheet(vm: vm, done: close)
        case let .saveAs(text): SaveAsSheet(vm: vm, text: text, done: close) { url in DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) { sheet = .file(url) } }
        case .memory: MemorySheet(vm: vm, done: close)
        case .usage: if let u = vm.usage { UsageSheet(usage: u, done: close) }
        case .archived: ArchivedSheet(vm: vm, done: close)
        case let .file(url): ShareSheet(items: [url])
        }
    }
}

// MARK: - Top bar

private struct TopBar: View {
    @ObservedObject var vm: AppModel
    let onMenu: () -> Void
    let onSheet: (ChatSheet) -> Void
    @State private var deleting = false

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 0) {
                IconButton(system: "line.3.horizontal", label: "Chats", action: onMenu)
                Text(vm.title).font(Emvryx.body(17, semibold: true)).foregroundStyle(Emvryx.text).lineLimit(1)
                    .frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 8)
                if vm.chatId != nil && !vm.bubbles.isEmpty {
                    Menu {
                        if !vm.isPrivate { Button("Share a link…") { onSheet(.share) } }
                        Button("Save as PDF or Word…") { onSheet(.saveAs(chatAsText)) }
                        if !vm.isPrivate { Button("Archive (still remembered)") { vm.archiveThis() } }
                        if !vm.isPrivate { Button("Delete this chat", role: .destructive) { deleting = true } }
                    } label: {
                        Text("⋯").font(.system(size: 22)).foregroundStyle(Emvryx.text).frame(width: 48, height: 48)
                    }
                    .accessibilityLabel("More for this chat")
                }
                IconButton(system: "plus", label: "New chat") { vm.newChat() }.disabled(vm.streaming)
            }
            .padding(.horizontal, 12).frame(height: 60)
            Rectangle().fill(Emvryx.line).frame(height: 1)
        }
        .alert("Delete this chat?", isPresented: $deleting) {
            Button("Delete", role: .destructive) { vm.deleteThis() }
            Button("Cancel", role: .cancel) {}
        } message: { Text("\"\(vm.title)\" and its messages are deleted. This can't be undone.") }
    }

    /// The whole chat as Markdown, for Save as.
    private var chatAsText: String {
        "# \(vm.title)\n\n" + vm.bubbles.filter { !$0.text.isBlank }.map { b in
            (b.mine ? "**You:** " : "**\(vm.models.first { $0.id == b.model }?.fullName ?? "Emvryx"):** ") + b.text
        }.joined(separator: "\n\n")
    }
}

/// A short message under the top bar (Skipped files, summarized, saved ...). Tap it to hide it.
private struct ToastLine: View {
    let text: String
    let hide: () -> Void
    var body: some View {
        Button(action: hide) {
            Text(text).font(Emvryx.body(14)).foregroundStyle(Emvryx.text).multilineTextAlignment(.leading)
                .padding(.horizontal, 16).padding(.vertical, 10).frame(maxWidth: .infinity, alignment: .leading).background(Emvryx.surface2)
        }
        .buttonStyle(.plain)
        .task(id: text) { try? await Task.sleep(nanoseconds: 6_000_000_000); hide() }
        .accessibilityLabel(text)
    }
}

// MARK: - The message box

private struct Composer: View {
    @ObservedObject var vm: AppModel
    let open: ChatView.PickMenu?
    let onMenu: (ChatView.PickMenu) -> Void
    let onSheet: (ChatSheet) -> Void
    @StateObject private var speech = SpeechInput()
    @FocusState private var focused: Bool
    @State private var photos = false
    @State private var photoItems: [PhotosPickerItem] = []
    @State private var files = false
    @State private var camera = false
    @State private var heard = false

    var body: some View {
        let p = vm.palette
        let canSend = vm.streaming || ((!vm.draft.isBlank || !vm.attached.isEmpty) && !vm.uploading)
        let research = vm.research && vm.canResearch
        VStack(alignment: .leading, spacing: 10) {
            DocRow(vm: vm, docs: vm.attached, onRemove: vm.unattach)
            if vm.uploading { Text("Adding…").font(Emvryx.body(13)).foregroundStyle(Emvryx.muted) }
            TextField("", text: $vm.draft, prompt: Text(research ? "What should Emvryx research?" : "Message Emvryx…").foregroundColor(Emvryx.muted), axis: .vertical)
                .font(Emvryx.body(16)).foregroundStyle(Emvryx.text).tint(p.accent)
                .lineLimit(1...6).focused($focused)
                .accessibilityLabel("Message")
            HStack(spacing: 6) {
                attachMenu(p)
                Pill(open: open == .model, filled: true, label: "Choose model") { onMenu(.model) } content: {
                    Logo(kind: vm.currentModel?.name ?? "flare").frame(width: 20, height: 20)
                    Text(vm.currentModel?.fullName ?? "Model").font(Emvryx.body(12, semibold: true)).foregroundStyle(Emvryx.text).lineLimit(1)
                }
                Pill(open: open == .effort, filled: false, label: "Choose effort") { onMenu(.effort) } content: {
                    Text(vm.state?.efforts.first { $0.id == vm.effort }?.name ?? "Balanced").font(Emvryx.body(14)).foregroundStyle(Emvryx.muted).lineLimit(1)
                }
                Spacer(minLength: 0)
                if vm.flag("chat_voice") { micButton(p) }
                if let c = vm.ctx, vm.flag("context_meter") { MemoryRing(ctx: c, palette: p) { onSheet(.memory) } }
                SendButton(stop: vm.streaming, enabled: canSend, palette: p) {
                    if vm.streaming { vm.stop() } else { speech.stop(); vm.send(vm.draft) }
                }
            }
        }
        .padding(.leading, 16).padding(.trailing, 10).padding(.top, 12).padding(.bottom, 10)
        .background(Emvryx.surface, in: RoundedRectangle(cornerRadius: 20))
        .overlay(RoundedRectangle(cornerRadius: 20).stroke(research ? p.accent : Emvryx.line, lineWidth: 1))
        .padding(.horizontal, 16).padding(.top, 8)
        .photosPicker(isPresented: $photos, selection: $photoItems, maxSelectionCount: 10, matching: .images)
        .onChange(of: photoItems) { items in loadPhotos(items) }
        .fileImporter(isPresented: $files, allowedContentTypes: [.item], allowsMultipleSelection: true) { result in
            if case let .success(urls) = result { vm.attach(urls.compactMap(Picked.file)) }
        }
        .fullScreenCover(isPresented: $camera) {
            CameraPicker { image in
                camera = false
                if let d = image?.jpegData(compressionQuality: 1), let f = Picked.picture(d, name: "photo.jpg") { vm.attach([f]) }
            }
            .ignoresSafeArea()
        }
        .alert("Voice", isPresented: Binding(get: { speech.problem != nil }, set: { if !$0 { speech.problem = nil } })) {
            Button("OK", role: .cancel) {}
        } message: { Text(speech.problem ?? "") }
    }

    /// + : a picture from your photos, a photo with the camera, or a file; and Deep Research on or off.
    private func attachMenu(_ p: Palette) -> some View {
        Menu {
            Button { photos = true } label: { Label("Photos or screenshots", systemImage: "photo") }
            if UIImagePickerController.isSourceTypeAvailable(.camera) { Button { camera = true } label: { Label("Take a photo", systemImage: "camera") } }
            Button { files = true } label: { Label("Choose a file", systemImage: "doc") }
            if vm.canResearch { Button { vm.research.toggle() } label: { Label(vm.research ? "Deep Research: on" : "Deep Research: off", systemImage: "magnifyingglass") } }
        } label: {
            Image(systemName: "plus").font(.system(size: 16, weight: .medium)).foregroundStyle(Emvryx.muted).frame(width: 36, height: 36)
                .overlay(Circle().stroke(Emvryx.line, lineWidth: 1))
        }
        .accessibilityLabel("Add a picture or file")
    }

    /// Hold to talk: the iPhone's speech recognition writes into the box while the button is held.
    private func micButton(_ p: Palette) -> some View {
        Image(systemName: speech.listening ? "mic.fill" : "mic").font(.system(size: 16)).foregroundStyle(speech.listening ? p.onAccent : Emvryx.muted)
            .frame(width: 36, height: 36)
            .background(speech.listening ? p.accent : .clear, in: Circle())
            .overlay(Circle().stroke(speech.listening ? p.accent : Emvryx.line, lineWidth: 1))
            .gesture(DragGesture(minimumDistance: 0)
                .onChanged { _ in
                    guard !heard else { return }
                    heard = true
                    speech.start(base: vm.draft) { vm.draft = $0 }
                }
                .onEnded { _ in heard = false; speech.stop() })
            .accessibilityLabel("Hold to talk")
            .accessibilityAddTraits(.isButton)
    }

    private func loadPhotos(_ items: [PhotosPickerItem]) {
        guard !items.isEmpty else { return }
        Task {
            var picked: [(name: String, data: Data)] = []
            for (i, item) in items.enumerated() {
                if let data = try? await item.loadTransferable(type: Data.self), let f = Picked.picture(data, name: "photo-\(i + 1)") { picked.append(f) }
            }
            photoItems = []
            vm.attach(picked)
        }
    }
}

/// The memory ring (feature flag context_meter): how full the model's memory is; red when it is close to being summarized.
private struct MemoryRing: View {
    let ctx: Ctx
    let palette: Palette
    let action: () -> Void
    var body: some View {
        let frac = min(max(ctx.pct / 100, 0), 1)
        let color = ctx.compactAt > 0 && Double(ctx.used) >= Double(ctx.compactAt) * 0.9 ? Emvryx.danger : palette.accent
        Button(action: action) {
            ZStack {
                Circle().stroke(Emvryx.surface2, lineWidth: 3).frame(width: 28, height: 28)
                Circle().trim(from: 0, to: frac).stroke(color, style: StrokeStyle(lineWidth: 3, lineCap: .round)).rotationEffect(.degrees(-90)).frame(width: 28, height: 28)
                Text("\(Int(ctx.pct.rounded()))%").font(Emvryx.body(9)).foregroundStyle(Emvryx.muted)
            }
            .frame(width: 36, height: 36)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Memory")
    }
}

/// .pill: the model (filled) and effort (plain) buttons under the box.
private struct Pill<Content: View>: View {
    let open: Bool
    let filled: Bool
    let label: String
    let action: () -> Void
    @ViewBuilder let content: () -> Content
    @Environment(\.palette) private var p

    var body: some View {
        Button(action: action) {
            HStack(spacing: 4) {
                content()
                Image(systemName: "arrowtriangle.down.fill").font(.system(size: 7)).foregroundStyle(Emvryx.muted).frame(width: 16)
            }
            .padding(.leading, 8).padding(.trailing, 2).frame(height: 36)
            .background(filled ? Emvryx.surface2 : .clear, in: Capsule())
            .overlay(Capsule().stroke(open ? p.accent : Emvryx.line, lineWidth: 1))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }
}

/// .send: a rounded square in the model's colour with an up arrow; while a reply is written it is .send.stop, a square to stop it.
private struct SendButton: View {
    let stop: Bool
    let enabled: Bool
    let palette: Palette
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            ZStack {
                if stop {
                    RoundedRectangle(cornerRadius: 2).fill(Emvryx.text).frame(width: 12, height: 12)
                } else {
                    Image(systemName: "arrow.up").font(.system(size: 18, weight: .bold)).foregroundStyle(palette.onAccent)
                }
            }
            .frame(width: 44, height: 44)
            .background(stop ? Emvryx.surface2 : palette.accent, in: RoundedRectangle(cornerRadius: 12))
            .overlay { if stop { RoundedRectangle(cornerRadius: 12).stroke(Emvryx.line, lineWidth: 1) } }
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
        .opacity(enabled ? 1 : 0.45)
        .accessibilityLabel(stop ? "Stop" : "Send")
    }
}

/// .usage: a thin bar in the model's colour and "Usage: 99.5% · about 397 messages left" (red when a fifth or less is left). Tap it for the details.
private struct UsageLine: View {
    let usage: Usage?
    let palette: Palette
    var body: some View {
        VStack(spacing: 6) {
            if let u = usage {
                let low = !u.exempt && u.fraction <= 0.2
                Capsule().fill(Emvryx.surface2).frame(width: 220, height: 5)
                    .overlay(alignment: .leading) { Capsule().fill(low ? Emvryx.danger : palette.accent).frame(width: 220 * min(max(u.fraction, 0), 1)) }
                Text(u.label).font(Emvryx.body(13)).foregroundStyle(low ? Emvryx.danger : Emvryx.muted)
            }
        }
        .frame(maxWidth: .infinity).padding(.top, 10).padding(.bottom, 8).contentShape(Rectangle())
    }
}

// MARK: - Model and effort menus

private struct ModelMenu: View {
    @ObservedObject var vm: AppModel
    let close: () -> Void
    var body: some View {
        MenuHead(text: "SELECT MODEL")
        ForEach(vm.models) { m in
            Opt(selected: m.id == vm.model, enabled: m.ready, action: { vm.pickModel(m.id); close() }) {
                Logo(kind: m.name).frame(width: 30, height: 30)
                VStack(alignment: .leading, spacing: 2) {
                    Text(m.fullName).font(Emvryx.body(16, semibold: true)).foregroundStyle(Emvryx.text)
                    if !m.tagline.isBlank { Text(m.tagline).font(Emvryx.body(14)).foregroundStyle(Emvryx.muted) }
                }
                Spacer(minLength: 0)
            }
            .accessibilityLabel(m.fullName)
        }
    }
}

private struct EffortMenu: View {
    @ObservedObject var vm: AppModel
    let close: () -> Void
    var body: some View {
        MenuHead(text: "HOW MUCH SHOULD IT THINK?")
        ForEach(vm.state?.efforts ?? []) { e in
            let allowed = vm.effortAllowed(e.id)
            Opt(selected: e.id == vm.effort, enabled: allowed, action: { vm.effort = e.id; close() }) {
                VStack(alignment: .leading, spacing: 2) {
                    (Text(e.name).font(Emvryx.body(16, semibold: true)).foregroundColor(Emvryx.text)
                        + Text(e.use.isEmpty ? "" : " · " + e.use).font(Emvryx.body(14)).foregroundColor(Emvryx.muted))
                    Text(allowed ? e.blurb : "Needs Flare or a bigger model.").font(Emvryx.body(14)).foregroundStyle(Emvryx.muted)
                }
                Spacer(minLength: 0)
                if e.id == vm.effort { Text("✓").font(Emvryx.body(16)).foregroundStyle(Emvryx.text) }
            }
            .accessibilityLabel(e.name)
        }
        Text("Thinking longer is slower and uses more of your usage.").font(Emvryx.body(12)).foregroundStyle(Emvryx.muted)
            .padding(.horizontal, 6).padding(.vertical, 4)
    }
}
