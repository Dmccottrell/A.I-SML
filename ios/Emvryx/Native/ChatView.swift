import SwiftUI

/// The native chat (android/.../ui/ChatScreen.kt, classic look): the top bar, the messages, the message box with the model and effort
/// pickers, the usage line, and the chat list that slides in from the left.
struct ChatView: View {
    @ObservedObject var vm: AppModel
    @State private var drawer = false
    @State private var menu: PickMenu?

    enum PickMenu { case model, effort }

    var body: some View {
        let p = vm.palette
        ZStack(alignment: .leading) {
            Emvryx.bg.ignoresSafeArea()
            VStack(spacing: 0) {
                TopBar(vm: vm) { withAnimation(.easeOut(duration: 0.25)) { drawer = true } }
                ZStack(alignment: .bottom) {
                    if vm.bubbles.isEmpty { EmptyChat(vm: vm) } else { ThreadView(vm: vm) }
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
                Composer(vm: vm, open: menu) { which in menu = menu == which ? nil : which }
                UsageLine(usage: vm.usage, palette: p)
            }
            if drawer {
                Color.black.opacity(0.45).ignoresSafeArea()
                    .onTapGesture { withAnimation(.easeOut(duration: 0.25)) { drawer = false } }
                    .transition(.opacity)
                Sidebar(vm: vm) { withAnimation(.easeOut(duration: 0.25)) { drawer = false } }
                    .transition(.move(edge: .leading))
            }
        }
        .preferredColorScheme(.dark)
        .environment(\.palette, p)
    }
}

// MARK: - Top bar

private struct TopBar: View {
    @ObservedObject var vm: AppModel
    let onMenu: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 0) {
                IconButton(system: "line.3.horizontal", label: "Chats", action: onMenu)
                Text(vm.title).font(Emvryx.body(17, semibold: true)).foregroundStyle(Emvryx.text).lineLimit(1)
                    .frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 8)
                IconButton(system: "plus", label: "New chat") { vm.newChat() }.disabled(vm.streaming)
            }
            .padding(.horizontal, 12).frame(height: 60)
            Rectangle().fill(Emvryx.line).frame(height: 1)
        }
    }
}

private struct IconButton: View {
    let system: String
    let label: String
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            Image(systemName: system).font(.system(size: 20, weight: .regular)).foregroundStyle(Emvryx.text).frame(width: 48, height: 48)
        }
        .accessibilityLabel(label)
    }
}

// MARK: - Messages

private struct EmptyChat: View {
    @ObservedObject var vm: AppModel
    var body: some View {
        ScrollView {
            VStack(spacing: 0) {
                Spacer(minLength: 80)
                Logo(kind: vm.currentModel?.name ?? "flare", violet: vm.flag("violet_theme")).frame(width: 64, height: 64)
                Text("How can I help?").font(Emvryx.heading(32)).kerning(-0.6).foregroundStyle(Emvryx.text)
                    .multilineTextAlignment(.center).padding(.top, 12).padding(.bottom, 6)
                Text("Ask anything. Pick a model and how much it should think under the box.")
                    .font(Emvryx.body(16)).foregroundStyle(Emvryx.muted).multilineTextAlignment(.center)
                if let f = vm.failure { FailureCard(failure: f) { vm.failure = nil }.padding(.top, 16) }
                Spacer(minLength: 24)
            }
            .padding(.horizontal, 24).frame(maxWidth: .infinity)
        }
    }
}

private struct ThreadView: View {
    @ObservedObject var vm: AppModel
    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 18) {
                    ForEach(vm.bubbles) { b in
                        if b.mine { UserMessage(bubble: b) } else { AiMessage(vm: vm, bubble: b) }
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

/// .msg.user .bubble: your words in a filled bubble on the right, at most 80% wide.
private struct UserMessage: View {
    let bubble: Bubble
    var body: some View {
        HStack {
            Spacer(minLength: 0)
            Text(bubble.text).font(Emvryx.body(16)).lineSpacing(24 - 16 * 1.302).foregroundStyle(Emvryx.text)
                .textSelection(.enabled)
                .padding(.horizontal, 16).padding(.vertical, 12)
                .background(Emvryx.surface2, in: Corners(topLeading: 18, topTrailing: 18, bottomTrailing: 4, bottomLeading: 18))
                .frame(maxWidth: (UIScreen.main.bounds.width - 32) * 0.8, alignment: .trailing)
        }
    }
}

/// .msg.ai: the model's logo and name over a bordered card; the reply is written into it as it comes.
private struct AiMessage: View {
    @ObservedObject var vm: AppModel
    let bubble: Bubble
    @State private var copied = false

    var body: some View {
        let who = vm.models.first { $0.id == bubble.model }
        let shape = Corners(topLeading: 18, topTrailing: 18, bottomTrailing: 18, bottomLeading: 4)
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Logo(kind: who?.name ?? "flare").frame(width: 16, height: 16)
                Text((who?.fullName ?? "Emvryx") + (bubble.cut && !bubble.streaming ? " · stopped" : ""))
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
            if !bubble.streaming && !bubble.text.isEmpty {
                Chip(text: copied ? "Copied" : "Copy") { UIPasteboard.general.string = bubble.text; copied = true }
            }
        }
        .frame(maxWidth: (UIScreen.main.bounds.width - 32) * 0.94, alignment: .leading)
    }
}

/// The thinking word, fading in and out while nothing is written yet.
private struct ThinkingWord: View {
    let word: String
    @State private var dim = false
    var body: some View {
        Text(word).font(Emvryx.body(16)).foregroundStyle(Emvryx.muted).opacity(dim ? 0.45 : 1)
            .onAppear { withAnimation(.easeInOut(duration: 0.9).repeatForever(autoreverses: true)) { dim = true } }
            .accessibilityLabel("Thinking")
    }
}

/// .chip: a small rounded button with a line round it (Copy).
private struct Chip: View {
    let text: String
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            Text(text).font(Emvryx.body(14)).foregroundStyle(Emvryx.muted).padding(.horizontal, 14).padding(.vertical, 6).frame(minHeight: 36)
                .overlay(Capsule().stroke(Emvryx.line, lineWidth: 1))
        }
        .buttonStyle(.plain)
    }
}

/// A refusal or error: what happened and what to do (send.js errorCard).
private struct FailureCard: View {
    let failure: Failure
    let dismiss: () -> Void
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(failure.message).font(Emvryx.body(16, semibold: true)).foregroundStyle(Emvryx.text)
            if !failure.action.isEmpty { Text(failure.action).font(Emvryx.body(15)).foregroundStyle(Emvryx.muted) }
            Button("OK", action: dismiss).font(Emvryx.body(15, semibold: true)).foregroundStyle(Emvryx.danger)
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading)
        .background(Emvryx.surface, in: RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Emvryx.danger.opacity(0.6), lineWidth: 1))
        .accessibilityElement(children: .combine)
    }
}

// MARK: - The message box

private struct Composer: View {
    @ObservedObject var vm: AppModel
    let open: ChatView.PickMenu?
    let onMenu: (ChatView.PickMenu) -> Void
    @FocusState private var focused: Bool

    var body: some View {
        let p = vm.palette
        let canSend = vm.streaming || !vm.draft.isBlank
        VStack(alignment: .leading, spacing: 10) {
            TextField("", text: $vm.draft, prompt: Text("Message Emvryx…").foregroundColor(Emvryx.muted), axis: .vertical)
                .font(Emvryx.body(16)).foregroundStyle(Emvryx.text).tint(p.accent)
                .lineLimit(1...6).focused($focused)
                .accessibilityLabel("Message")
            HStack(spacing: 6) {
                Pill(open: open == .model, filled: true, label: "Choose model") { onMenu(.model) } content: {
                    Logo(kind: vm.currentModel?.name ?? "flare").frame(width: 20, height: 20)
                    Text(vm.currentModel?.fullName ?? "Model").font(Emvryx.body(12, semibold: true)).foregroundStyle(Emvryx.text).lineLimit(1)
                }
                Pill(open: open == .effort, filled: false, label: "Choose effort") { onMenu(.effort) } content: {
                    Text(vm.state?.efforts.first { $0.id == vm.effort }?.name ?? "Balanced").font(Emvryx.body(14)).foregroundStyle(Emvryx.muted).lineLimit(1)
                }
                Spacer(minLength: 0)
                SendButton(stop: vm.streaming, enabled: canSend, palette: p) {
                    if vm.streaming { vm.stop() } else { vm.send(vm.draft) }
                }
            }
        }
        .padding(.leading, 16).padding(.trailing, 10).padding(.top, 12).padding(.bottom, 10)
        .background(Emvryx.surface, in: RoundedRectangle(cornerRadius: 20))
        .overlay(RoundedRectangle(cornerRadius: 20).stroke(Emvryx.line, lineWidth: 1))
        .padding(.horizontal, 16).padding(.top, 8)
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

/// .usage: a thin bar in the model's colour and "Usage: 99.5% · about 397 messages left" (red when a fifth or less is left).
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
        .frame(maxWidth: .infinity).padding(.top, 10).padding(.bottom, 8)
    }
}

// MARK: - Model and effort menus

private struct PopMenu<Content: View>: View {
    @ViewBuilder let content: () -> Content
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 6) { content() }.padding(12)
        }
        .frame(maxHeight: 560).fixedSize(horizontal: false, vertical: true)
        .background(Emvryx.surface, in: RoundedRectangle(cornerRadius: 20))
        .overlay(RoundedRectangle(cornerRadius: 20).stroke(Emvryx.line, lineWidth: 1))
        .padding(.horizontal, 16).padding(.bottom, 10)
    }
}

private struct MenuHead: View {
    let text: String
    var body: some View {
        Text(text).font(Emvryx.body(12, semibold: true)).kerning(1.2).foregroundStyle(Emvryx.muted).padding(.horizontal, 6).padding(.vertical, 4)
    }
}

private struct Opt<Content: View>: View {
    let selected: Bool
    var enabled = true
    let action: () -> Void
    @ViewBuilder let content: () -> Content
    @Environment(\.palette) private var p
    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) { content() }
                .padding(.horizontal, 14).padding(.vertical, 10).frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                .overlay(RoundedRectangle(cornerRadius: 14).stroke(selected ? p.accent : Emvryx.line, lineWidth: 1))
                .contentShape(RoundedRectangle(cornerRadius: 14))
        }
        .buttonStyle(.plain).disabled(!enabled).opacity(enabled ? 1 : 0.5)
    }
}

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

// MARK: - The chat list

private struct Sidebar: View {
    @ObservedObject var vm: AppModel
    let done: () -> Void
    @State private var query = ""
    @State private var account = false

    var body: some View {
        let p = vm.palette
        let shown = vm.chats.filter { query.isBlank || $0.title.localizedCaseInsensitiveContains(query.trimmingCharacters(in: .whitespaces)) }
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 10) {
                Logo(violet: vm.flag("violet_theme")).frame(width: 32, height: 32)
                Text("Emvryx").font(Emvryx.heading(20)).kerning(-0.4).foregroundStyle(Emvryx.text)
            }
            .padding(.leading, 20).padding(.top, 12).padding(.bottom, 4)
            Button { vm.newChat(); done() } label: {
                Label("New chat", systemImage: "plus").font(Emvryx.body(16, semibold: true)).foregroundStyle(p.onAccent)
                    .frame(maxWidth: .infinity, minHeight: 46).background(p.accent, in: RoundedRectangle(cornerRadius: 14))
            }
            .buttonStyle(.plain).padding(.horizontal, 14).padding(.top, 12).padding(.bottom, 6)
            HStack(spacing: 8) {
                Image(systemName: "magnifyingglass").font(.system(size: 15)).foregroundStyle(Emvryx.muted)
                TextField("", text: $query, prompt: Text("Search chats").foregroundColor(Emvryx.muted))
                    .font(Emvryx.body(15)).foregroundStyle(Emvryx.text).tint(p.accent)
            }
            .padding(.horizontal, 10).frame(minHeight: 40)
            .background(Emvryx.surface, in: RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(Emvryx.line, lineWidth: 1))
            .padding(.horizontal, 14).padding(.vertical, 6)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 2) {
                    ForEach(groups(shown), id: \.0) { label, rows in
                        Text(label).font(Emvryx.body(11, semibold: true)).kerning(1.1).foregroundStyle(Emvryx.muted.opacity(0.8))
                            .padding(.leading, 6).padding(.top, 14).padding(.bottom, 2)
                        ForEach(rows) { c in
                            Button { vm.openChat(c.id); done() } label: {
                                HStack(spacing: 8) {
                                    if c.pinned { Image(systemName: "pin.fill").font(.system(size: 11)).foregroundStyle(Emvryx.muted) }
                                    Text(c.title).font(Emvryx.body(16)).foregroundStyle(Emvryx.text).lineLimit(1)
                                    Spacer(minLength: 0)
                                }
                                .padding(.horizontal, 12).frame(minHeight: 40)
                                .background(c.id == vm.chatId ? Emvryx.surface2 : .clear, in: RoundedRectangle(cornerRadius: 12))
                                .overlay(alignment: .leading) {
                                    if c.id == vm.chatId { RoundedRectangle(cornerRadius: 2).fill(p.accent).frame(width: 3, height: 20) }
                                }
                                .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    if shown.isEmpty {
                        Text(query.isBlank ? "No chats yet." : "No chats match.").font(Emvryx.body(15)).foregroundStyle(Emvryx.muted)
                            .padding(.horizontal, 6).padding(.vertical, 14)
                    }
                }
                .padding(.horizontal, 14)
            }
            Rectangle().fill(Emvryx.line).frame(height: 1)
            SideLink(icon: "chevron.left.forwardslash.chevron.right", text: "VryxCode") { vm.open("/#code", "VryxCode"); done() }
            SideLink(icon: "sparkles", text: "Skills") { vm.open("/", "Skills", run: "openSkills()"); done() }
            SideLink(icon: "doc", text: "Documents") { vm.open("/", "Documents", run: "openDocs()"); done() }
            Rectangle().fill(Emvryx.line).frame(height: 1)
            Button { account.toggle() } label: {
                HStack(spacing: 10) {
                    Text(String((vm.state?.user ?? "").prefix(1)).uppercased()).font(Emvryx.body(16, semibold: true)).foregroundStyle(p.onAccent)
                        .frame(width: 34, height: 34).background(p.accent, in: Circle())
                    VStack(alignment: .leading, spacing: 0) {
                        Text(vm.state?.user ?? "").font(Emvryx.body(16, semibold: true)).foregroundStyle(Emvryx.text)
                        if let s = vm.state { Text(s.planName).font(Emvryx.body(14)).foregroundStyle(Emvryx.muted) }
                    }
                    Spacer(minLength: 0)
                    Image(systemName: account ? "chevron.down" : "chevron.up").font(.system(size: 13)).foregroundStyle(Emvryx.muted)
                }
                .padding(.horizontal, 16).padding(.vertical, 12).contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Account")
            if account {
                SideLink(icon: "brain", text: "Memory") { vm.open("/", "Memory", run: "openMemory()"); done() }
                SideLink(icon: "gearshape", text: "Settings") { vm.open("/#settings", "Settings"); done() }
                if vm.isAdmin { SideLink(icon: "shield", text: "Admin") { vm.open("/#admin", "Admin"); done() } }
                SideLink(icon: "rectangle.portrait.and.arrow.right", text: "Sign out") { vm.signOut(); done() }
            }
        }
        .frame(maxWidth: 312, maxHeight: .infinity, alignment: .top)
        .frame(width: min(312, UIScreen.main.bounds.width * 0.86))
        .background(Emvryx.side.ignoresSafeArea())
        .overlay(alignment: .trailing) { Rectangle().fill(Emvryx.line).frame(width: 1).ignoresSafeArea() }
    }

    /// PINNED, TODAY, YESTERDAY, LAST 7 DAYS, OLDER, as the website groups the chat list.
    private func groups(_ rows: [ChatSummary]) -> [(String, [ChatSummary])] {
        let cal = Calendar.current
        let now = Date()
        var out: [(String, [ChatSummary])] = []
        func add(_ label: String, _ list: [ChatSummary]) { if !list.isEmpty { out.append((label, list)) } }
        let pinned = rows.filter(\.pinned)
        let rest = rows.filter { !$0.pinned }.sorted { $0.updated > $1.updated }
        let day = { (c: ChatSummary) in Date(timeIntervalSince1970: c.updated) }
        add("PINNED", pinned)
        add("TODAY", rest.filter { cal.isDateInToday(day($0)) })
        add("YESTERDAY", rest.filter { cal.isDateInYesterday(day($0)) })
        add("LAST 7 DAYS", rest.filter { !cal.isDateInToday(day($0)) && !cal.isDateInYesterday(day($0)) && now.timeIntervalSince(day($0)) < 7 * 86400 })
        add("OLDER", rest.filter { now.timeIntervalSince(day($0)) >= 7 * 86400 && !cal.isDateInYesterday(day($0)) })
        return out
    }
}

private struct SideLink: View {
    let icon: String
    let text: String
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: icon).font(.system(size: 16)).foregroundStyle(Emvryx.muted).frame(width: 22)
                Text(text).font(Emvryx.body(16)).foregroundStyle(Emvryx.text)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 20).frame(minHeight: 44).contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

/// A rectangle with its own radius at each corner (the bubbles' "tail" corner is smaller), for iOS 16.
struct Corners: Shape {
    var topLeading: CGFloat, topTrailing: CGFloat, bottomTrailing: CGFloat, bottomLeading: CGFloat
    func path(in r: CGRect) -> Path {
        var p = Path()
        p.move(to: CGPoint(x: r.minX + topLeading, y: r.minY))
        p.addLine(to: CGPoint(x: r.maxX - topTrailing, y: r.minY))
        p.addArc(center: CGPoint(x: r.maxX - topTrailing, y: r.minY + topTrailing), radius: topTrailing, startAngle: .degrees(-90), endAngle: .degrees(0), clockwise: false)
        p.addLine(to: CGPoint(x: r.maxX, y: r.maxY - bottomTrailing))
        p.addArc(center: CGPoint(x: r.maxX - bottomTrailing, y: r.maxY - bottomTrailing), radius: bottomTrailing, startAngle: .degrees(0), endAngle: .degrees(90), clockwise: false)
        p.addLine(to: CGPoint(x: r.minX + bottomLeading, y: r.maxY))
        p.addArc(center: CGPoint(x: r.minX + bottomLeading, y: r.maxY - bottomLeading), radius: bottomLeading, startAngle: .degrees(90), endAngle: .degrees(180), clockwise: false)
        p.addLine(to: CGPoint(x: r.minX, y: r.minY + topLeading))
        p.addArc(center: CGPoint(x: r.minX + topLeading, y: r.minY + topLeading), radius: topLeading, startAngle: .degrees(180), endAngle: .degrees(270), clockwise: false)
        p.closeSubpath()
        return p
    }
}

// MARK: - The current model's colours, for the pieces below the chat screen

private struct PaletteKey: EnvironmentKey { static let defaultValue = Palette.brand }
extension EnvironmentValues {
    var palette: Palette {
        get { self[PaletteKey.self] }
        set { self[PaletteKey.self] = newValue }
    }
}
