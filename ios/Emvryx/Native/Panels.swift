import SwiftUI

// The app's own Memory, Documents, Skills and Settings screens (android/.../ui/NativeScreens.kt), instead of the website's panels in a web view:
// they open at once, follow the app's look, and say what went wrong with Try again. They make the same calls as the website.

/// The frame of every one of the app's own screens: a bar with Back and the title, then the content.
struct PanelScreen<Content: View>: View {
    let title: String
    let back: () -> Void
    @ViewBuilder let content: () -> Content

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Button(action: back) {
                    Label("Chat", systemImage: "chevron.left").font(Emvryx.body(16, semibold: true)).foregroundStyle(Emvryx.text)
                }
                .accessibilityLabel("Back to chat")
                Spacer()
            }
            .overlay(Text(title).font(Emvryx.body(17, semibold: true)).foregroundStyle(Emvryx.text))
            .padding(.horizontal, 16).frame(height: 56)
            Rectangle().fill(Emvryx.line).frame(height: 1)
            content()
        }
        .background(Emvryx.bg.ignoresSafeArea())
    }
}

/// Loads something once (and again on Try again): a spinner, then the content, or what went wrong. Never a blank page.
struct Loaded<T, Content: View>: View {
    @ObservedObject var vm: AppModel
    let load: () async throws -> T
    @ViewBuilder let content: (T, @escaping () -> Void) -> Content
    @State private var value: T?
    @State private var error: String?
    @State private var attempt = 0

    var body: some View {
        Group {
            if let v = value { content(v) { attempt += 1 } }
            else if let e = error { Problem(message: e) { attempt += 1 } }
            else { ProgressView().tint(vm.palette.accent).frame(maxWidth: .infinity, maxHeight: .infinity) }
        }
        .task(id: attempt) {
            error = nil
            do { value = try await load() } catch { if let a = error as? ApiError, a.signedOut { vm.handle(error) } else { self.error = vm.describe(error) } }
        }
    }
}

/// What went wrong, and Try again.
struct Problem: View {
    let message: String
    let retry: () -> Void
    var body: some View {
        VStack(spacing: 14) {
            Logo().frame(width: 48, height: 48)
            Text(message).font(Emvryx.body(16)).foregroundStyle(Emvryx.muted).multilineTextAlignment(.center)
            PwaButton(text: "Try again", action: retry)
        }
        .padding(28).frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

/// A small grey all-capitals heading that starts a group.
private struct Section: View {
    let text: String
    var body: some View {
        Text(text.uppercased()).font(Emvryx.body(11, semibold: true)).kerning(1.1).foregroundStyle(Emvryx.muted.opacity(0.8))
            .padding(.leading, 4).padding(.top, 18).padding(.bottom, 6).frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// A rounded box that holds a group of related controls.
private struct Card<Content: View>: View {
    @ViewBuilder let content: () -> Content
    var body: some View {
        VStack(alignment: .leading, spacing: 8) { content() }
            .padding(14).frame(maxWidth: .infinity, alignment: .leading)
            .background(Emvryx.surface, in: RoundedRectangle(cornerRadius: 14))
    }
}

// MARK: - Memory

struct MemoryPanel: View {
    @ObservedObject var vm: AppModel
    @State private var list: MemoryList?
    @State private var text = ""
    @State private var note: String?
    @State private var clearing = false

    var body: some View {
        PanelScreen(title: "Memory", back: vm.backToChat) {
            Loaded(vm: vm, load: { try await vm.api.memory() }) { first, _ in
                let m = list ?? first
                ScrollView {
                    VStack(alignment: .leading, spacing: 8) {
                        Text(m.on ? "Facts you tell Emvryx are kept here and given to whichever model you talk to. Private chats never save or read them."
                                  : "Memory is off (Settings > Remember things about me): nothing new is kept.")
                            .font(Emvryx.body(14)).foregroundStyle(Emvryx.muted).padding(.top, 14)
                        Field(label: "Add a fact", text: $text, placeholder: "I live in Leeds and have two cats").padding(.top, 4)
                        PwaButton(text: "Remember this", enabled: !text.isBlank) {
                            let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
                            Task {
                                do { var l = try await vm.api.memoryAdd(t); l.on = m.on; list = l; text = ""; note = nil } catch { note = vm.describe(error) }
                            }
                        }
                        if let n = note { Text(n).font(Emvryx.body(14)).foregroundStyle(Emvryx.muted) }
                        Section(text: m.facts.isEmpty ? "Nothing remembered yet" : "\(m.facts.count) remembered")
                        ForEach(m.facts) { f in
                            HStack(spacing: 0) {
                                Text(f.text).font(Emvryx.body(15)).foregroundStyle(Emvryx.text).padding(.vertical, 12).padding(.leading, 14)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                Button("Delete") {
                                    Task {
                                        try? await vm.api.memoryDelete(f.id)
                                        var l = m; l.facts.removeAll { $0.id == f.id }; list = l
                                    }
                                }
                                .font(Emvryx.body(15)).foregroundStyle(Emvryx.muted).padding(.horizontal, 14).frame(minHeight: 44)
                                .accessibilityLabel("Delete " + f.text)
                            }
                            .background(Emvryx.surface, in: RoundedRectangle(cornerRadius: 12))
                        }
                        if !m.facts.isEmpty {
                            PwaButton(text: "Forget everything", ghost: true) { clearing = true }.padding(.top, 10)
                        }
                    }
                    .padding(.horizontal, 16).padding(.bottom, 24)
                }
                .scrollDismissesKeyboard(.interactively)
                .alert("Forget everything?", isPresented: $clearing) {
                    Button("Forget", role: .destructive) {
                        Task { try? await vm.api.memoryClear(); var l = m; l.facts = []; list = l }
                    }
                    Button("Cancel", role: .cancel) {}
                } message: { Text("Emvryx forgets every fact above. Your chats are not deleted.") }
            }
        }
    }
}

// MARK: - Documents

struct FilesPanel: View {
    @ObservedObject var vm: AppModel
    @State private var list: DocList?
    @State private var asking: DocList.DocRow?

    var body: some View {
        PanelScreen(title: "Documents", back: vm.backToChat) {
            Loaded(vm: vm, load: { try await vm.api.documents() }) { first, _ in
                let d = list ?? first
                ScrollView {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Files and pictures you added to chats. Add new ones with the + by the message box" + (d.maxMb > 0 ? " (up to \(d.maxMb) MB each)." : "."))
                            .font(Emvryx.body(14)).foregroundStyle(Emvryx.muted).padding(.top, 14)
                        if d.documents.isEmpty { Text("No documents yet.").font(Emvryx.body(16)).foregroundStyle(Emvryx.muted).padding(.top, 18) }
                        ForEach(d.documents) { f in
                            HStack(spacing: 10) {
                                Image(systemName: f.isPicture ? "photo" : "doc").font(.system(size: 16)).foregroundStyle(Emvryx.muted).padding(.leading, 14)
                                VStack(alignment: .leading, spacing: 0) {
                                    Text(f.name).font(Emvryx.body(15)).foregroundStyle(Emvryx.text).lineLimit(1)
                                    Text([f.kind.uppercased(), f.size].filter { !$0.isEmpty }.joined(separator: " · ")).font(Emvryx.body(13)).foregroundStyle(Emvryx.muted)
                                }
                                .padding(.vertical, 10)
                                Spacer(minLength: 0)
                                Button("Delete") { asking = f }.font(Emvryx.body(15)).foregroundStyle(Emvryx.muted).padding(.horizontal, 14).frame(minHeight: 44)
                                    .accessibilityLabel("Delete " + f.name)
                            }
                            .background(Emvryx.surface, in: RoundedRectangle(cornerRadius: 12))
                        }
                    }
                    .padding(.horizontal, 16).padding(.bottom, 24)
                }
                .alert("Delete this file?", isPresented: Binding(get: { asking != nil }, set: { if !$0 { asking = nil } }), presenting: asking) { f in
                    Button("Delete", role: .destructive) {
                        Task { try? await vm.api.deleteDocument(f.id); var l = d; l.documents.removeAll { $0.id == f.id }; list = l }
                    }
                    Button("Cancel", role: .cancel) {}
                } message: { f in Text(f.name) }
            }
        }
    }
}

// MARK: - Skills

struct SkillsPanel: View {
    @ObservedObject var vm: AppModel
    var body: some View {
        PanelScreen(title: "Skills", back: vm.backToChat) {
            Loaded(vm: vm, load: { try await vm.api.skills() }) { skills, _ in
                ScrollView {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Start a chat where every answer is shaped for one job.").font(Emvryx.body(14)).foregroundStyle(Emvryx.muted).padding(.top, 14)
                        ForEach(skills) { s in
                            Button { vm.newChat(skill: s.id, skillName: s.name); vm.backToChat() } label: {
                                VStack(alignment: .leading, spacing: 4) {
                                    HStack {
                                        Image(systemName: "sparkles").font(.system(size: 18)).foregroundStyle(vm.palette.accentText)
                                        VStack(alignment: .leading, spacing: 0) {
                                            Text(s.name).font(Emvryx.body(16, semibold: true)).foregroundStyle(Emvryx.text)
                                            if !s.forWho.isEmpty { Text(s.forWho).font(Emvryx.body(13)).foregroundStyle(Emvryx.muted) }
                                        }
                                        Spacer(minLength: 0)
                                        Text("Start").font(Emvryx.body(16, semibold: true)).foregroundStyle(vm.palette.accentText)
                                    }
                                    if !s.does.isEmpty { Text(s.does).font(Emvryx.body(14)).foregroundStyle(Emvryx.text).multilineTextAlignment(.leading) }
                                    if !s.tryThis.isEmpty { Text("Try: " + s.tryThis).font(Emvryx.body(13)).foregroundStyle(Emvryx.muted).multilineTextAlignment(.leading) }
                                }
                                .padding(14).frame(maxWidth: .infinity, alignment: .leading)
                                .background(Emvryx.surface, in: RoundedRectangle(cornerRadius: 14))
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel("Start " + s.name)
                        }
                    }
                    .padding(.horizontal, 16).padding(.bottom, 24)
                }
            }
        }
    }
}

// MARK: - Settings

struct SettingsPanel: View {
    @ObservedObject var vm: AppModel
    @State private var now: SettingsData?
    @State private var note: String?
    @State private var how: String?

    var body: some View {
        PanelScreen(title: "Settings", back: vm.backToChat) {
            Loaded(vm: vm, load: { try await vm.api.settings() }) { first, _ in
                let s = now ?? first
                let instructions = how ?? s.customInstructions
                ScrollView {
                    VStack(alignment: .leading, spacing: 8) {
                        if let n = note { Text(n).font(Emvryx.body(14)).foregroundStyle(Emvryx.muted).padding(.top, 10) }
                        Section(text: "Answers")
                        Card {
                            Text("Where answers come from").font(Emvryx.body(15, semibold: true)).foregroundStyle(Emvryx.text)
                            Text("Auto looks things up in Wikipedia first and searches the web for recent things. Private chats never search the web.")
                                .font(Emvryx.body(13)).foregroundStyle(Emvryx.muted)
                            Choice(options: [("auto", "Auto"), ("off", "Wikipedia only"), ("always", "Always search the web"), ("none", "Model only")], value: s.webSearch) { save("web_search", $0) }
                        }
                        Card { Toggle("Live facts", "Sums, dates, prices, rates, scores and news come from code and free public services, not from the model’s memory.", s.liveData) { save("live_data", $0) } }
                        Card {
                            Text("Pause before the answer").font(Emvryx.body(15, semibold: true)).foregroundStyle(Emvryx.text)
                            Choice(options: [("off", "None"), ("short", "Short"), ("natural", "Natural")], value: s.thinkingPause) { save("thinking_pause", $0) }
                        }
                        Card {
                            Text("How long a chat can be").font(Emvryx.body(15, semibold: true)).foregroundStyle(Emvryx.text)
                            Choice(options: [("everyday", "Everyday (about 8K)"), ("long", "Long (if allowed)")], value: s.windowMode) { save("window_mode", $0) }
                        }
                        Card { Toggle("Show word counts", "The tokens each answer used, under it.", s.showTokens) { save("show_tokens", $0) } }
                        Section(text: "Make it yours")
                        Card {
                            Field(label: "How you like answers", text: Binding(get: { instructions }, set: { how = String($0.prefix(400)) }), placeholder: "Keep answers short. I am a nurse.")
                            HStack(spacing: 8) {
                                PwaButton(text: "Save", enabled: instructions != s.customInstructions) { save("custom_instructions", instructions); how = nil }.frame(maxWidth: 120)
                                Text("\(instructions.count)/400").font(Emvryx.body(13)).foregroundStyle(Emvryx.muted)
                            }
                        }
                        Card {
                            Toggle("Remember things about me", "Facts you tell it are kept and given to whichever model you talk to. Passwords and card numbers are never kept.", s.memory) { save("memory", $0) }
                            Chip(text: "What it remembers") { vm.screen = .memory }
                        }
                        Card { Toggle("Use my connected apps in chats", "When a question is clearly about one (“what is on my calendar”), the few matching items are read. Read-only.", s.connectedApps) { save("connected_apps", $0) } }
                        if vm.phone.allowed {
                            Section(text: "This phone")
                            Card { PhoneCard(phone: vm.phone, vm: vm) }
                        }
                        Section(text: "More")
                        Card {
                            Text("Connected apps, data controls, notifications and everything else are in the full Settings.").font(Emvryx.body(13)).foregroundStyle(Emvryx.muted)
                            Chip(text: "More settings") { vm.open("/#settings", "Settings") }
                        }
                    }
                    .padding(.horizontal, 16).padding(.bottom, 24)
                }
                .scrollDismissesKeyboard(.interactively)
            }
        }
    }

    /// Every change is saved at once on the server, and the reply replaces what is on screen.
    private func save(_ key: String, _ value: Any) {
        Task {
            do { now = try await vm.api.saveSettings([key: value]); note = nil } catch { note = vm.describe(error) }
        }
    }
}

/// A row of pills where exactly one is selected.
private struct Choice: View {
    let options: [(String, String)]
    let value: String
    let pick: (String) -> Void
    var body: some View {
        Flow(spacing: 8) {
            ForEach(options, id: \.0) { id, label in Seg(text: label, on: id == value) { pick(id) } }
        }
    }
}

/// An on/off switch row with a title and a small description; [flip] gets the new value.
private struct Toggle: View {
    let title: String
    let desc: String
    let on: Bool
    let flip: (Bool) -> Void
    @Environment(\.palette) private var p
    init(_ title: String, _ desc: String, _ on: Bool, flip: @escaping (Bool) -> Void) { self.title = title; self.desc = desc; self.on = on; self.flip = flip }
    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(Emvryx.body(15, semibold: true)).foregroundStyle(Emvryx.text)
                Text(desc).font(Emvryx.body(13)).foregroundStyle(Emvryx.muted)
            }
            Spacer(minLength: 10)
            SwiftUI.Toggle("", isOn: Binding(get: { on }, set: flip)).labelsHidden().tint(p.accent).accessibilityLabel(title)
        }
    }
}
