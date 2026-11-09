import SwiftUI

// VryxCode's newer parts, drawn (android/.../ui/CodeScreen.kt): the task list box, the review feed (quiet lines, file chips, "Changed N files"), Restore, how a message
// ended (waiting, out of steps, the review verdict), the memory and rules sheets, and the strip of pictures and documents. The logic is in CodeParity.swift.

private let violet = Color(hex: 0x8B5CF6)

/// The plan as a box (flag vryxcode_taskbox): a ticked circle when done, a filled one on the step being worked on, an empty one still to come.
struct PlanBox: View {
    let steps: [PlanStep]
    @State private var open = true
    var body: some View {
        let done = steps.filter { $0.state == "done" }.count
        VStack(alignment: .leading, spacing: 8) {
            Button { open.toggle() } label: {
                HStack {
                    Text("Plan").font(Emvryx.body(15, semibold: true)).foregroundStyle(Emvryx.text)
                    Text("\(done) of \(steps.count) done").font(Emvryx.body(13)).foregroundStyle(Emvryx.muted)
                    Spacer()
                    Image(systemName: open ? "chevron.up" : "chevron.down").font(.system(size: 12)).foregroundStyle(Emvryx.muted)
                }
            }
            .buttonStyle(.plain).accessibilityLabel("Plan, \(done) of \(steps.count) done")
            if open {
                ForEach(Array(steps.enumerated()), id: \.offset) { _, s in
                    HStack(alignment: .top, spacing: 8) {
                        Image(systemName: s.state == "done" ? "checkmark.circle.fill" : s.state == "now" ? "circle.inset.filled" : "circle")
                            .font(.system(size: 15)).foregroundStyle(s.state == "todo" ? Emvryx.muted : violet)
                        Text(s.text).font(Emvryx.body(14)).foregroundStyle(s.state == "done" ? Emvryx.muted : Emvryx.text)
                            .strikethrough(s.state == "done").multilineTextAlignment(.leading)
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityLabel((s.state == "done" ? "Done: " : s.state == "now" ? "Now: " : "To do: ") + s.text)
                }
            }
        }
        .padding(12).frame(maxWidth: .infinity, alignment: .leading)
        .background(Emvryx.surface, in: RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Emvryx.line, lineWidth: 1))
        .accessibilityIdentifier("planbox")
    }
}

/// A quiet grey line: "Read app/page.tsx", "Thought 4s"; a red mark and the reason when the step went wrong.
struct QuietRow: View {
    let line: QuietLine
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(line.text).font(Emvryx.body(14)).foregroundStyle(line.bad ? Emvryx.danger : Emvryx.muted).lineLimit(1)
            if line.bad && !line.why.isEmpty { Text(line.why).font(Emvryx.body(12)).foregroundStyle(Emvryx.danger).lineLimit(2) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }
}

/// Quiet lines folded into one ("Read 3 files, ran 2 commands"); a tap opens them.
struct GroupRow: View {
    let lines: [QuietLine]
    @State private var open = false
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Button { open.toggle() } label: {
                HStack(spacing: 6) {
                    Text(groupTitle(lines)).font(Emvryx.body(14)).foregroundStyle(lines.contains { $0.bad } ? Emvryx.danger : Emvryx.muted)
                    Image(systemName: open ? "chevron.up" : "chevron.down").font(.system(size: 10)).foregroundStyle(Emvryx.muted)
                    Spacer(minLength: 0)
                }
            }
            .buttonStyle(.plain).accessibilityLabel(groupTitle(lines))
            if open { ForEach(Array(lines.enumerated()), id: \.offset) { _, l in QuietRow(line: l).padding(.leading, 10) } }
        }
    }
}

/// A changed file: its name with the lines added and taken away; a tap shows the change.
struct FileChip: View {
    let path: String, add: Int, del: Int, diff: [DiffLine], bad: Bool, why: String
    @State private var open = false
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Button { open.toggle() } label: {
                HStack(spacing: 8) {
                    Image(systemName: "doc.text").font(.system(size: 13)).foregroundStyle(Emvryx.muted)
                    Text(path).font(Emvryx.body(14, semibold: true)).foregroundStyle(bad ? Emvryx.danger : Emvryx.text).lineLimit(1)
                    Spacer(minLength: 4)
                    if add > 0 { Text("+\(add)").font(Emvryx.body(13, semibold: true)).foregroundStyle(Color(hex: 0x34D399)) }
                    if del > 0 { Text("−\(del)").font(Emvryx.body(13, semibold: true)).foregroundStyle(Emvryx.danger) }
                }
            }
            .buttonStyle(.plain).accessibilityLabel("Changed " + path)
            if bad && !why.isEmpty { Text(why).font(Emvryx.body(12)).foregroundStyle(Emvryx.danger).lineLimit(2) }
            if open && !diff.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(Array(diff.prefix(120).enumerated()), id: \.offset) { _, l in
                            Text(l.text.isEmpty ? " " : l.text).font(.system(size: 12, design: .monospaced))
                                .foregroundStyle(l.kind == "+" ? Color(hex: 0x34D399) : l.kind == "-" ? Emvryx.danger : Emvryx.muted)
                        }
                    }
                    .padding(8)
                }
                .background(Emvryx.bg, in: RoundedRectangle(cornerRadius: 8))
            }
        }
        .padding(10).frame(maxWidth: .infinity, alignment: .leading)
        .background(Emvryx.surface, in: RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Emvryx.line, lineWidth: 1))
    }
}

/// The end of a finished message: "Changed 3 files +20 −4" and each file.
struct DoneRow: View {
    let files: [(path: String, add: Int, del: Int)]
    var body: some View {
        let add = files.reduce(0) { $0 + $1.add }, del = files.reduce(0) { $0 + $1.del }
        VStack(alignment: .leading, spacing: 4) {
            Text("Changed \(files.count) file" + (files.count == 1 ? "" : "s") + "  +\(add) −\(del)").font(Emvryx.body(14, semibold: true)).foregroundStyle(Emvryx.text)
            ForEach(Array(files.enumerated()), id: \.offset) { _, f in
                HStack {
                    Text(f.path).font(Emvryx.body(13)).foregroundStyle(Emvryx.muted).lineLimit(1)
                    Spacer(minLength: 4)
                    Text("+\(f.add) −\(f.del)").font(Emvryx.body(12)).foregroundStyle(Emvryx.muted)
                }
            }
        }
        .padding(12).frame(maxWidth: .infinity, alignment: .leading)
        .background(Emvryx.surface, in: RoundedRectangle(cornerRadius: 12))
        .accessibilityIdentifier("changedfiles")
    }
}

/// Restore on one of your messages (flag vryxcode_restore): the files go back to just before it, after a yes. Off while the agent works.
struct RestorePill: View {
    @ObservedObject var code: CodeStore
    let turn: Int
    @State private var ask = false
    var body: some View {
        Button("Restore") { ask = true }
            .font(Emvryx.body(13)).foregroundStyle(Emvryx.muted).padding(.horizontal, 12).frame(minHeight: 30)
            .overlay(Capsule().stroke(Emvryx.line, lineWidth: 1))
            .disabled(code.working).opacity(code.working ? 0.4 : 1)
            .accessibilityLabel("Restore to before this message")
            .alert("Put the files back?", isPresented: $ask) {
                Button("Restore", role: .destructive) { code.restore(turn: turn) }
                Button("Cancel", role: .cancel) {}
            } message: { Text("The project's files go back to just before this message. Later changes are undone.") }
    }
}

/// How a message ended, said plainly: waiting for your answer (with replies one tap sends), out of steps, and the review's verdict (flags vryxcode_autocontinue, vryxcode_guardrails).
struct EndNotes: View {
    @ObservedObject var code: CodeStore
    let e: CodeEvent
    let all: [CodeEvent]
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if code.parity.contains("vryxcode_autocontinue"), let s = endState(e) {
                switch s {
                case .waiting where !justAnswered(e, all):
                    Text("Not finished yet: it is waiting for your answer.").font(Emvryx.body(14, semibold: true)).foregroundStyle(Color(hex: 0xFBBF24))
                    Flow(spacing: 8) { ForEach(waitingReplies(e.str("summary")), id: \.self) { r in Chip(text: r) { code.send(r) } } }
                case let .outOfSteps(rounds):
                    Text("It used all its steps" + (rounds > 0 ? " after \(rounds) rounds" : "") + " before the task was finished.").font(Emvryx.body(14, semibold: true)).foregroundStyle(Color(hex: 0xFBBF24))
                    Chip(text: "Carry on") { code.send("Carry on from where you stopped.") }
                default: EmptyView()
                }
            }
            if code.parity.contains("vryxcode_guardrails"), let v = verdictOf(e) {
                Text(v.approved ? "Review: approved" : "Review: \(v.blocking) to fix" + (v.nits > 0 ? ", \(v.nits) small points" : ""))
                    .font(Emvryx.body(14, semibold: true)).foregroundStyle(v.approved ? Color(hex: 0x34D399) : Emvryx.danger)
                    .accessibilityIdentifier("verdict")
                if !v.approved && !v.fix.isEmpty { Chip(text: "Fix these (test first)") { code.send(v.fix) } }
            }
        }
    }
}

/// What VryxCode remembers (/memory): each note can be forgotten.
struct CodeMemorySheet: View {
    @ObservedObject var code: CodeStore
    var body: some View {
        SheetCard(title: "What VryxCode remembers", done: { code.memory = nil }) {
            let notes = code.memory ?? []
            if notes.isEmpty { Text("Nothing yet. It writes down what it learns about your projects.").font(Emvryx.body(15)).foregroundStyle(Emvryx.muted) }
            ForEach(Array(notes.enumerated()), id: \.offset) { i, n in
                HStack(alignment: .top, spacing: 10) {
                    Text(n).font(Emvryx.body(15)).foregroundStyle(Emvryx.text).frame(maxWidth: .infinity, alignment: .leading)
                    Button("Forget") { code.forget(i) }.font(Emvryx.body(14)).foregroundStyle(Emvryx.muted).accessibilityLabel("Forget " + n)
                }
                .padding(12).background(Emvryx.bg, in: RoundedRectangle(cornerRadius: 12))
            }
        }
        .accessibilityIdentifier("memorysheet")
    }
}

/// What it may do without asking and what it must never do, for this project (/permissions).
struct RulesSheet: View {
    @ObservedObject var code: CodeStore
    @State private var rule = ""
    var body: some View {
        SheetCard(title: "Permissions for " + code.project, done: { code.rules = nil }) {
            group("ALLOWED WITHOUT ASKING", code.rules?.allow ?? [])
            group("NEVER ALLOWED", code.rules?.deny ?? [])
            NoteBox(text: $rule, placeholder: "A command or file pattern, like npm test")
            HStack(spacing: 8) {
                Chip(text: "Allow it") { code.addRule("allow", rule); rule = "" }
                Chip(text: "Never allow it") { code.addRule("deny", rule); rule = "" }
            }
        }
        .accessibilityIdentifier("rulessheet")
    }
    @ViewBuilder private func group(_ title: String, _ rules: [String]) -> some View {
        Text(title).font(Emvryx.body(11, semibold: true)).kerning(1.1).foregroundStyle(Emvryx.muted.opacity(0.8)).padding(.top, 6)
        if rules.isEmpty { Text("None").font(Emvryx.body(14)).foregroundStyle(Emvryx.muted) }
        ForEach(rules, id: \.self) { r in
            HStack {
                Text(r).font(.system(size: 14, design: .monospaced)).foregroundStyle(Emvryx.text).frame(maxWidth: .infinity, alignment: .leading)
                Button("Remove") { code.removeRule(r) }.font(Emvryx.body(14)).foregroundStyle(Emvryx.muted).accessibilityLabel("Remove " + r)
            }
            .padding(12).background(Emvryx.bg, in: RoundedRectangle(cornerRadius: 12))
        }
    }
}

/// The pictures and documents waiting to go with the next message.
struct AttachStrip: View {
    @ObservedObject var code: CodeStore
    var body: some View {
        if !code.pictures.isEmpty || !code.docs.isEmpty {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(Array(code.pictures.enumerated()), id: \.offset) { i, src in
                        ZStack(alignment: .topTrailing) {
                            Group {
                                if let d = Data(base64Encoded: String(src.drop(while: { $0 != "," }).dropFirst())), let img = UIImage(data: d) {
                                    Image(uiImage: img).resizable().scaledToFill()
                                } else { Emvryx.surface2 }
                            }
                            .frame(width: 56, height: 56).clipShape(RoundedRectangle(cornerRadius: 10))
                            Button { code.removePicture(i) } label: { Image(systemName: "xmark.circle.fill").foregroundStyle(Emvryx.text, Emvryx.surface2) }
                                .accessibilityLabel("Remove picture")
                        }
                    }
                    ForEach(Array(code.docs.enumerated()), id: \.offset) { i, d in
                        HStack(spacing: 6) {
                            Image(systemName: "doc").foregroundStyle(Emvryx.muted)
                            Text(d.name).font(Emvryx.body(13)).foregroundStyle(Emvryx.text).lineLimit(1)
                            Button { code.removeDoc(i) } label: { Image(systemName: "xmark").font(.system(size: 11)).foregroundStyle(Emvryx.muted) }
                                .accessibilityLabel("Remove " + d.name)
                        }
                        .padding(.horizontal, 10).frame(height: 40).overlay(Capsule().stroke(Emvryx.line, lineWidth: 1))
                    }
                }
            }
            .accessibilityIdentifier("attachstrip")
        }
    }
}

/// The /commands that match what is typed: one tap fills the box.
struct SlashList: View {
    let matches: [(name: String, about: String)]
    let pick: (String) -> Void
    var body: some View {
        if !matches.isEmpty {
            VStack(alignment: .leading, spacing: 0) {
                ForEach(matches.prefix(6), id: \.name) { m in
                    Button { pick(m.name) } label: {
                        HStack {
                            Text(m.name).font(Emvryx.body(15, semibold: true)).foregroundStyle(Emvryx.text)
                            Text(m.about).font(Emvryx.body(13)).foregroundStyle(Emvryx.muted).lineLimit(1)
                            Spacer(minLength: 0)
                        }
                        .padding(.horizontal, 14).frame(minHeight: 40)
                    }
                    .buttonStyle(.plain).accessibilityLabel("Command " + m.name)
                }
            }
            .background(Emvryx.surface, in: RoundedRectangle(cornerRadius: 14))
            .overlay(RoundedRectangle(cornerRadius: 14).stroke(Emvryx.line, lineWidth: 1))
            .padding(.horizontal, 16)
        }
    }
}
