import PhotosUI
import SwiftUI
import UniformTypeIdentifiers

// The VryxCode screens (android/.../ui/CodeScreen.kt): the home with the sessions and the starters, and a session's live feed.

struct CodeView_: View {
    @ObservedObject var vm: AppModel
    @StateObject private var code: CodeStore

    init(vm: AppModel) {
        self.vm = vm
        _code = StateObject(wrappedValue: CodeStore(api: vm.api, onSignedOut: { vm.handle(ApiError.server(http: 401, code: "bad_key", message: "", action: "")) }))
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Button { if code.sid != nil { code.close() } else { vm.backToChat() } } label: {
                    Label(code.sid != nil ? "Sessions" : "Chat", systemImage: "chevron.left").font(Emvryx.body(16, semibold: true)).foregroundStyle(Emvryx.text)
                }
                .accessibilityLabel(code.sid != nil ? "Back to sessions" : "Back to chat")
                Spacer()
            }
            .overlay(Text(code.sid != nil ? (code.title.isEmpty ? "Session" : code.title) : "VryxCode").font(Emvryx.body(17, semibold: true)).foregroundStyle(Emvryx.text)
                        .lineLimit(1).padding(.horizontal, 100))
            .padding(.horizontal, 16).frame(height: 56)
            Rectangle().fill(Emvryx.line).frame(height: 1)
            if !code.loaded {
                ProgressView().tint(vm.palette.accent).frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let i = code.info, !i.allowed {
                VStack(spacing: 14) {
                    Logo().frame(width: 48, height: 48)
                    Text(i.whyNot.isEmpty ? "VryxCode is not available for this account." : i.whyNot).font(Emvryx.body(16)).foregroundStyle(Emvryx.muted).multilineTextAlignment(.center)
                }
                .padding(28).frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if code.info == nil {
                Problem(message: code.error ?? "VryxCode could not be reached.") { Task { await code.load() } }
            } else if code.sid != nil {
                SessionFeed(vm: vm, code: code)
            } else {
                CodeHome(vm: vm, code: code)
            }
        }
        .background(Emvryx.bg.ignoresSafeArea())
        .environment(\.palette, vm.palette)
        .task { code.setParity(vm.flag); await code.load(); await code.loadCommands() }
        .onDisappear { code.stopPolling() }
        .sheet(isPresented: Binding(get: { code.memory != nil }, set: { if !$0 { code.memory = nil } })) { CodeMemorySheet(code: code).environment(\.palette, vm.palette) }
        .sheet(isPresented: Binding(get: { code.rules != nil }, set: { if !$0 { code.rules = nil } })) { RulesSheet(code: code).environment(\.palette, vm.palette) }
    }
}

// MARK: - Home

private struct CodeHome: View {
    @ObservedObject var vm: AppModel
    @ObservedObject var code: CodeStore
    @State private var idea = ""
    @State private var showArchived = false

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    Text("Describe one task. VryxCode reads, edits, runs the tests and tries again in its own project folder, and asks before it changes anything.")
                        .font(Emvryx.body(14)).foregroundStyle(Emvryx.muted).padding(.top, 14)
                    if let e = code.error { FailureCard(failure: Failure(message: e)) { code.error = nil } }
                    if !code.templates.isEmpty {
                        Text("START FROM").font(Emvryx.body(11, semibold: true)).kerning(1.1).foregroundStyle(Emvryx.muted.opacity(0.8)).padding(.top, 8)
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: 8) {
                                ForEach(code.templates) { t in
                                    Button { code.template = t.id; idea = t.idea } label: {
                                        VStack(alignment: .leading, spacing: 2) {
                                            Text(t.icon + " " + t.name).font(Emvryx.body(15, semibold: true)).foregroundStyle(Emvryx.text)
                                            Text(t.desc).font(Emvryx.body(12)).foregroundStyle(Emvryx.muted).lineLimit(2).multilineTextAlignment(.leading)
                                        }
                                        .padding(12).frame(width: 190, alignment: .leading)
                                        .background(Emvryx.surface, in: RoundedRectangle(cornerRadius: 14))
                                        .overlay(RoundedRectangle(cornerRadius: 14).stroke(code.template == t.id ? vm.palette.accent : Emvryx.line, lineWidth: 1))
                                    }
                                    .buttonStyle(.plain).accessibilityLabel("Starter " + t.name)
                                }
                            }
                        }
                    }
                    HStack {
                        Text(code.sessions.isEmpty ? "NO SESSIONS YET" : "SESSIONS").font(Emvryx.body(11, semibold: true)).kerning(1.1).foregroundStyle(Emvryx.muted.opacity(0.8))
                        Spacer()
                        if code.info?.environments.isEmpty == false || true {
                            Button(showArchived ? "Hide archived" : "Archived") { showArchived.toggle(); if showArchived { Task { await code.loadArchived() } } }
                                .font(Emvryx.body(13)).foregroundStyle(Emvryx.muted)
                        }
                    }
                    .padding(.top, 8)
                    if code.parity.contains("vryxcode_review") && !showArchived {
                        ForEach(sessionGroups(code.sessions, seen: code.reviewed), id: \.title) { g in
                            Text(g.title).font(Emvryx.body(11, semibold: true)).kerning(1.1).foregroundStyle(Emvryx.muted.opacity(0.8)).padding(.top, 6)
                                .accessibilityIdentifier("group " + g.title)
                            ForEach(g.sessions) { s in row(s) }
                        }
                    } else {
                        ForEach(showArchived ? code.archived : code.sessions) { s in row(s) }
                    }
                }
                .padding(.horizontal, 16).padding(.bottom, 16)
            }
            CodeComposer(vm: vm, code: code, text: $idea, placeholder: "Describe a task…")
        }
    }

    private func row(_ s: CodeSessionRow) -> some View {
        Button { code.open(s) } label: {
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text(s.title.isEmpty ? "Session" : s.title).font(Emvryx.body(16, semibold: true)).foregroundStyle(Emvryx.text).lineLimit(1)
                    Spacer(minLength: 8)
                    StatePill(state: s.state)
                }
                Text([s.project, s.age].filter { !$0.isEmpty }.joined(separator: " · ") + (s.files > 0 ? " · \(s.files) files" : "")
                     + (s.added + s.removed > 0 ? " · +\(s.added) −\(s.removed)" : "")).font(Emvryx.body(13)).foregroundStyle(Emvryx.muted)
                if !s.snippet.isEmpty { Text(s.snippet).font(Emvryx.body(14)).foregroundStyle(Emvryx.muted).lineLimit(2).multilineTextAlignment(.leading) }
            }
            .padding(14).frame(maxWidth: .infinity, alignment: .leading)
            .background(Emvryx.surface, in: RoundedRectangle(cornerRadius: 14))
        }
        .buttonStyle(.plain)
        .contextMenu {
            Button(s.archived ? "Put back" : "Archive") { code.archive(s, !s.archived) }
            Button("Delete", role: .destructive) { code.deleteSession(s) }
        }
        .accessibilityLabel("Session " + s.title)
        .accessibilityIdentifier("codesession")
    }
}

private struct StatePill: View {
    let state: String
    var body: some View {
        let (text, color): (String, Color) = {
            switch state {
            case "working", "starting": return ("Working", Color(hex: 0x34D399))
            case "asking": return ("Asking", Color(hex: 0xFBBF24))
            case "queued": return ("Queued", Emvryx.muted)
            case "done": return ("Done", Emvryx.muted)
            case "error", "failed": return ("Stopped", Emvryx.danger)
            default: return (state.prefix(1).uppercased() + state.dropFirst(), Emvryx.muted)
            }
        }()
        return Text(text).font(Emvryx.body(12, semibold: true)).foregroundStyle(color).padding(.horizontal, 10).padding(.vertical, 3)
            .overlay(Capsule().stroke(color.opacity(0.6), lineWidth: 1))
    }
}

// MARK: - A session

private struct SessionFeed: View {
    @ObservedObject var vm: AppModel
    @ObservedObject var code: CodeStore
    @State private var text = ""

    var body: some View {
        VStack(spacing: 0) {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 10) {
                        if code.parity.contains("vryxcode_taskbox") {
                            let steps = planSteps(code.events, working: code.working)
                            if !steps.isEmpty { PlanBox(steps: steps) }
                        }
                        if code.parity.contains("vryxcode_lines") || code.parity.contains("vryxcode_review") {
                            let items = reviewItems(code.events)
                            ForEach(code.parity.contains("vryxcode_lines") ? foldQuiet(items) : items) { item in ReviewRow(item: item, code: code) }
                        } else {
                            ForEach(code.events) { e in EventRow(e: e, all: code.events, code: code) }
                        }
                        if let q = code.pending {
                            if q.str("tool") == "ask_user" || q.kind == "choose" || q.raw["options"] != nil { ChoiceCard(code: code, q: q) } else { AskCard(code: code, q: q) }
                        } else if code.working {
                            WorkingLine(stopping: code.stopping)
                        }
                        if let e = code.error { FailureCard(failure: Failure(message: e)) { code.error = nil } }
                        Color.clear.frame(height: 1).id("end")
                    }
                    .padding(.horizontal, 16).padding(.vertical, 14)
                }
                .scrollDismissesKeyboard(.interactively)
                .onChange(of: code.events.count) { _ in proxy.scrollTo("end", anchor: .bottom) }
                .onChange(of: code.pending?.str("id")) { _ in proxy.scrollTo("end", anchor: .bottom) }
            }
            if !code.offer.isEmpty && !code.working && text.isEmpty {
                Chip(text: code.offer) { code.send(code.offer) }.padding(.horizontal, 16).padding(.top, 6).accessibilityIdentifier("suggestion")
            }
            CodeComposer(vm: vm, code: code, text: $text, placeholder: code.working ? "Tell it something while it works…" : "Message VryxCode…")
        }
    }
}

/// One item of the review feed: a quiet line, a folded group, a file chip, the "Changed N files" summary, or an ordinary event.
private struct ReviewRow: View {
    let item: ReviewItem
    @ObservedObject var code: CodeStore
    var body: some View {
        switch item {
        case let .quiet(q): QuietRow(line: q)
        case let .group(g): GroupRow(lines: g)
        case let .file(path, add, del, diff, bad, why): FileChip(path: path, add: add, del: del, diff: diff, bad: bad, why: why)
        case let .done(files): DoneRow(files: files)
        case let .event(e): EventRow(e: e, all: code.events, code: code)
        }
    }
}

/// For tests: one event drawn as in a session's feed.
enum CodeEventPreview {
    static func row(_ e: CodeEvent, _ all: [CodeEvent]) -> some View { EventRow(e: e, all: all, code: nil) }
}

/// One event of a session drawn as a row; each kind looks different and unknown kinds draw nothing.
private struct EventRow: View {
    let e: CodeEvent
    let all: [CodeEvent]
    var code: CodeStore?
    @State private var open = false
    @Environment(\.palette) private var p
    private let violet = Color(hex: 0x8B5CF6)

    var body: some View {
        switch e.kind {
        case "start", "user":
            if !e.bool("auto") {
                HStack {
                    Spacer(minLength: 0)
                    Text((e.bool("plan") ? "[Plan] " : "") + (e.str("task").isEmpty ? e.str("text") : e.str("task")) + (e.bool("steer") ? "  (while it worked)" : ""))
                        .font(Emvryx.body(16)).foregroundStyle(Emvryx.text).padding(.horizontal, 16).padding(.vertical, 12)
                        .background(Emvryx.surface2, in: Corners(topLeading: 18, topTrailing: 18, bottomTrailing: 4, bottomLeading: 18))
                        .frame(maxWidth: (UIScreen.main.bounds.width - 32) * 0.85, alignment: .trailing)
                }
                if let code, code.parity.contains("vryxcode_restore"), e.int("turn") > 0 {
                    HStack { Spacer(); RestorePill(code: code, turn: e.int("turn")) }
                }
            }
        case "step":
            let preview = e.str("preview")
            let took = [e.num("secs").map { "\(Int($0.rounded()))s" }, e.int("words") > 0 ? NumberFormatter.localizedString(from: NSNumber(value: e.int("words")), number: .decimal) + " tokens" : nil]
                .compactMap { $0 }.joined(separator: " · ")
            Button { open.toggle() } label: {
                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 6) {
                        Text("●").font(.system(size: 10)).foregroundStyle(Color(hex: 0x34D399))
                        Text(e.str("tool")).font(Emvryx.body(15, semibold: true)).foregroundStyle(Emvryx.text)
                        if !e.str("label").isEmpty { Text(e.str("label")).font(Emvryx.body(14)).foregroundStyle(Emvryx.muted).lineLimit(1) }
                        Spacer(minLength: 0)
                        if !took.isEmpty { Text(took).font(Emvryx.body(13)).foregroundStyle(Emvryx.muted) }
                    }
                    if open && !preview.isEmpty { mono(String(preview.prefix(1500))) }
                }
                .padding(12).frame(maxWidth: .infinity, alignment: .leading)
                .background(Emvryx.surface, in: RoundedRectangle(cornerRadius: 14))
                .overlay(RoundedRectangle(cornerRadius: 14).stroke(Emvryx.line, lineWidth: 1))
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Step " + e.str("tool"))
        case "result":
            Text("→ " + String(e.str("text").prefix(600))).font(.system(size: 13, design: .monospaced)).foregroundStyle(Emvryx.muted).lineLimit(8)
        case "retry": Note(text: "↻ " + e.str("why"))
        case "note", "language": Text(e.str("text")).font(Emvryx.body(14)).foregroundStyle(Emvryx.muted)
        case "queued": Text("Queued: it starts when the session before it finishes.").font(Emvryx.body(14)).foregroundStyle(Emvryx.muted)
        case "compacted": Note(text: "Summarized earlier steps to make room.")
        case "model": Note(text: "Now using \(e.str("model")).")
        case "rewind": Text("↶ Rewound the files to before: " + e.str("label")).font(Emvryx.body(14)).foregroundStyle(Emvryx.muted)
        case "ask", "choose":
            if all.contains(where: { $0.kind == "answer" && $0.str("id") == e.str("id") }) {
                Note(text: e.kind == "choose" ? "Asked: " + e.str("question") : "Asked to use " + e.str("tool"))
            }
        case "answer":
            if !e.str("choice").isEmpty { Text("You chose: " + e.str("choice")).font(Emvryx.body(14)).foregroundStyle(violet) }
        case "end":
            let finished = e.bool("finished")
            VStack(alignment: .leading, spacing: 8) {
                ForEach(Array(Markdown.blocks(e.str("summary").isEmpty ? (finished ? "Done." : "Stopped.") : e.str("summary")).enumerated()), id: \.offset) { _, b in
                    switch b {
                    case let .prose(t): Text(t).font(Emvryx.body(15)).foregroundStyle(Emvryx.text).tint(p.accentText)
                    case let .code(c): mono(c)
                    }
                }
                ForEach(e.strings("next"), id: \.self) { Text("→ " + $0).font(Emvryx.body(14)).foregroundStyle(Emvryx.muted) }
                if let code { EndNotes(code: code, e: e, all: all) }
            }
            .padding(14).frame(maxWidth: .infinity, alignment: .leading)
            .background(finished ? violet.opacity(0.14) : Emvryx.surface, in: RoundedRectangle(cornerRadius: 14))
            .overlay(RoundedRectangle(cornerRadius: 14).stroke(finished ? violet : Emvryx.line, lineWidth: 1))
            .textSelection(.enabled)
        default: EmptyView()
        }
    }

    private func mono(_ t: String) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            Text(t).font(.system(size: 13, design: .monospaced)).foregroundStyle(Emvryx.muted).padding(10)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Emvryx.bg, in: RoundedRectangle(cornerRadius: 10))
    }
}

/// The working line under the newest step: the Emvryx logo and what it is doing, with the seconds ticking on their own.
private struct WorkingLine: View {
    let stopping: Bool
    @State private var start = Date()
    var body: some View {
        TimelineView(.periodic(from: start, by: 1)) { ctx in
            HStack(spacing: 10) {
                Logo().frame(width: 22, height: 22)
                Text(stopping ? "Stopping…" : "Working…").font(Emvryx.body(14)).foregroundStyle(Emvryx.muted)
                Text("\(max(0, Int(ctx.date.timeIntervalSince(start))))s").font(Emvryx.body(13)).foregroundStyle(Emvryx.muted)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(stopping ? "Stopping" : "Working")
    }
}

/// A permission question: Yes / Yes and don't ask again / No.
private struct AskCard: View {
    @ObservedObject var code: CodeStore
    let q: CodeEvent
    @Environment(\.palette) private var p
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Allow this?").font(Emvryx.body(17, semibold: true)).foregroundStyle(Emvryx.text)
            ScrollView(.horizontal, showsIndicators: false) {
                Text(String(q.str("preview").prefix(2500))).font(.system(size: 13, design: .monospaced)).foregroundStyle(Emvryx.muted).padding(10)
            }
            .background(Emvryx.bg, in: RoundedRectangle(cornerRadius: 10))
            Flow(spacing: 8) {
                Button { code.answer(allow: true) } label: {
                    Text("Yes").font(Emvryx.body(16, semibold: true)).foregroundStyle(p.onAccent).padding(.horizontal, 22).frame(minHeight: 44).background(p.accent, in: RoundedRectangle(cornerRadius: 12))
                }
                .buttonStyle(.plain).accessibilityLabel("Yes")
                Chip(text: "Yes, and don't ask again for this") { code.answer(allow: true, always: true) }
                Chip(text: "No") { code.answer(allow: false) }
            }
        }
        .padding(14).frame(maxWidth: .infinity, alignment: .leading)
        .background(Emvryx.surface, in: RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Color(hex: 0x8B5CF6), lineWidth: 1))
    }
}

/// The full agent's multiple-choice question: one tap answers, or write your own.
private struct ChoiceCard: View {
    @ObservedObject var code: CodeStore
    let q: CodeEvent
    @State private var own = ""
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(q.str("question")).font(Emvryx.body(17, semibold: true)).foregroundStyle(Emvryx.text)
            ForEach(q.strings("options"), id: \.self) { o in
                Button { code.choose(o) } label: {
                    Text(o).font(Emvryx.body(15)).foregroundStyle(Emvryx.text).padding(.horizontal, 16).padding(.vertical, 12).frame(maxWidth: .infinity, alignment: .leading)
                        .overlay(Capsule().stroke(Emvryx.line, lineWidth: 1))
                }
                .buttonStyle(.plain)
            }
            HStack(spacing: 8) {
                NoteBox(text: $own, placeholder: "Or write your own answer")
                PwaButton(text: "Send", enabled: !own.isBlank) { code.choose(own); own = "" }.frame(width: 90)
            }
        }
        .padding(14).frame(maxWidth: .infinity, alignment: .leading)
        .background(Emvryx.surface, in: RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Color(hex: 0x8B5CF6), lineWidth: 1))
    }
}

// MARK: - The message box

/// The box at the bottom: the text, the pick buttons (mode, model or effort, where it runs), Stop or Send, and the usage line.
private struct CodeComposer: View {
    @ObservedObject var vm: AppModel
    @ObservedObject var code: CodeStore
    @Binding var text: String
    let placeholder: String
    @State private var photos = false
    @State private var files = false
    @State private var camera = false
    @State private var photoItems: [PhotosPickerItem] = []

    var body: some View {
        let p = vm.palette
        VStack(spacing: 6) {
            SlashList(matches: code.slashMatches(text)) { text = $0 + " " }
            VStack(alignment: .leading, spacing: 10) {
                AttachStrip(code: code)
                TextField("", text: $text, prompt: Text(placeholder).foregroundColor(Emvryx.muted), axis: .vertical)
                    .font(Emvryx.body(16)).foregroundStyle(Emvryx.text).tint(p.accent).lineLimit(1...6)
                    .accessibilityLabel("Message VryxCode")
                HStack(spacing: 6) {
                    if code.extras {
                        Menu {
                            Button { photos = true } label: { Label("Photos or screenshots", systemImage: "photo") }
                            if UIImagePickerController.isSourceTypeAvailable(.camera) { Button { camera = true } label: { Label("Take a photo", systemImage: "camera") } }
                            Button { files = true } label: { Label("A document (PDF, Word, text)", systemImage: "doc") }
                        } label: {
                            Image(systemName: "plus").font(.system(size: 15, weight: .semibold)).foregroundStyle(Emvryx.muted)
                                .frame(width: 32, height: 32).overlay(Circle().stroke(Emvryx.line, lineWidth: 1))
                        }
                        .accessibilityLabel("Attach to VryxCode")
                    }
                    pick("Mode", code.mode == "auto" ? "Auto" : code.mode == "plan" ? "Plan" : "Ask") {
                        Button("Ask before editing") { code.mode = "ask" }
                        Button("Edit without asking") { code.mode = "auto" }
                        Button("Plan first") { code.mode = "plan" }
                    }
                    if let e = code.info?.effort, !e.levels.isEmpty {
                        pick("Effort", e.levels.first { $0.id == code.effort }?.name ?? "Effort") {
                            ForEach(e.levels) { l in Button(l.name + (l.note.isEmpty ? "" : " · " + l.note)) { code.effort = l.id } }
                        }
                    } else if let models = code.info?.models, !models.isEmpty {
                        pick("Model", models.first { $0.id == code.model }?.label ?? "Model") {
                            ForEach(models.filter(\.ready)) { m in Button(m.label.isEmpty ? m.name : m.label) { code.model = m.id } }
                        }
                    }
                    if code.sid == nil, let envs = code.info?.environments, envs.count > 1 {
                        pick("Where it runs", envs.first { $0.id == code.env }?.name ?? "Place") {
                            ForEach(envs.filter(\.available)) { e in Button(e.name) { code.env = e.id } }
                        }
                    }
                    Spacer(minLength: 0)
                    Button {
                        if code.working && !(code.full && !text.isBlank) { code.stop() } else { code.send(text); text = "" }
                    } label: {
                        ZStack {
                            if code.working && !(code.full && !text.isBlank) { RoundedRectangle(cornerRadius: 2).fill(Emvryx.text).frame(width: 12, height: 12) }
                            else { Image(systemName: "arrow.up").font(.system(size: 18, weight: .bold)).foregroundStyle(p.onAccent) }
                        }
                        .frame(width: 44, height: 44)
                        .background(code.working && !(code.full && !text.isBlank) ? Emvryx.surface2 : p.accent, in: RoundedRectangle(cornerRadius: 12))
                    }
                    .buttonStyle(.plain)
                    .disabled(!code.working && text.isBlank && code.pictures.isEmpty)
                    .opacity(!code.working && text.isBlank && code.pictures.isEmpty ? 0.45 : 1)
                    .accessibilityLabel(code.working && !(code.full && !text.isBlank) ? "Stop" : "Send")
                }
            }
            .padding(.leading, 16).padding(.trailing, 10).padding(.top, 12).padding(.bottom, 10)
            .background(Emvryx.surface, in: RoundedRectangle(cornerRadius: 20))
            .overlay(RoundedRectangle(cornerRadius: 20).stroke(Emvryx.line, lineWidth: 1))
            .padding(.horizontal, 16).padding(.top, 8)
            .photosPicker(isPresented: $photos, selection: $photoItems, maxSelectionCount: 3, matching: .images)
            .onChange(of: photoItems) { items in loadPhotos(items) }
            .fileImporter(isPresented: $files, allowedContentTypes: [.item], allowsMultipleSelection: true) { result in
                if case let .success(urls) = result { for f in urls.compactMap(Picked.file) { add(f) } }
            }
            .fullScreenCover(isPresented: $camera) {
                CameraPicker { image in
                    camera = false
                    if let d = image?.jpegData(compressionQuality: 1), let f = Picked.picture(d, name: "photo.jpg") { add(f) }
                }
                .ignoresSafeArea()
            }
            if let u = code.usageLabel { Text(u).font(Emvryx.body(13)).foregroundStyle(Emvryx.muted).padding(.bottom, 8) }
        }
    }

    /// A picked file goes with the next message: pictures as pictures, anything else as a document.
    private func add(_ f: (name: String, data: Data)) {
        if ["jpg", "jpeg", "png", "webp", "gif"].contains((f.name as NSString).pathExtension.lowercased()) { code.addPicture(name: f.name, data: f.data) }
        else { code.addDoc(name: f.name, data: f.data) }
    }

    private func loadPhotos(_ items: [PhotosPickerItem]) {
        guard !items.isEmpty else { return }
        Task {
            for (i, item) in items.enumerated() {
                if let data = try? await item.loadTransferable(type: Data.self), let f = Picked.picture(data, name: "photo-\(i + 1)") { code.addPicture(name: f.name, data: f.data) }
            }
            photoItems = []
        }
    }

    private func pick<M: View>(_ label: String, _ value: String, @ViewBuilder _ items: () -> M) -> some View {
        Menu { items() } label: {
            HStack(spacing: 4) {
                Text(value).font(Emvryx.body(13)).foregroundStyle(Emvryx.muted).lineLimit(1)
                Image(systemName: "arrowtriangle.down.fill").font(.system(size: 7)).foregroundStyle(Emvryx.muted)
            }
            .padding(.horizontal, 10).frame(height: 32).overlay(Capsule().stroke(Emvryx.line, lineWidth: 1))
        }
        .accessibilityLabel(label)
    }
}
