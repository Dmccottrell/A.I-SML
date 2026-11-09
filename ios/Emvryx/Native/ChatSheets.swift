import SwiftUI

// The sheets of the chat screen: Regenerate, Report, Edit, Share a link, Save as, Memory, Usage, Archived chats
// (android/.../ui/ChatExtras.kt and ChatMore.kt, where they are dialogs).

struct RegenSheet: View {
    @ObservedObject var vm: AppModel
    let done: () -> Void
    var body: some View {
        SheetCard(title: "Regenerate", done: done) {
            let options = (vm.state?.regenOptions ?? []).isEmpty ? [RegenOption(id: "again", label: "Try again", blurb: "Same question, a fresh answer")]
                                                                  : vm.state!.regenOptions
            ForEach(options) { o in
                Opt(selected: false, action: { vm.regenerate(o.id); done() }) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(o.label).font(Emvryx.body(16, semibold: true)).foregroundStyle(Emvryx.text)
                        if !o.blurb.isBlank { Text(o.blurb).font(Emvryx.body(14)).foregroundStyle(Emvryx.muted) }
                    }
                    Spacer(minLength: 0)
                }
                .accessibilityLabel(o.label)
            }
        }
    }
}

struct ReportSheet: View {
    @ObservedObject var vm: AppModel
    let bubble: Bubble
    let done: () -> Void
    @State private var kind = "wrong_fact"
    @State private var note = ""
    private static let kinds = [("wrong_fact", "Wrong fact"), ("ignored", "Ignored my question"), ("too_long", "Too long"),
                                ("too_short", "Too short or vague"), ("cut_off", "Cut off"), ("unsafe", "Not appropriate"), ("other", "Something else")]
    var body: some View {
        SheetCard(title: "What went wrong?", close: "Cancel", done: done) {
            ForEach(Self.kinds, id: \.0) { id, label in
                Opt(selected: kind == id, action: { kind = id }) { Text(label).font(Emvryx.body(15)).foregroundStyle(Emvryx.text); Spacer(minLength: 0) }
            }
            NoteBox(text: $note, placeholder: "Anything else? (optional)")
            Text("Your question and this answer go to the owner so the next version gets it right.").font(Emvryx.body(13)).foregroundStyle(Emvryx.muted)
            PwaButton(text: "Send") { vm.report(bubble, kind: kind, note: note); done() }
        }
    }
}

struct EditSheet: View {
    @ObservedObject var vm: AppModel
    let bubble: Bubble
    let done: () -> Void
    @State private var text = ""
    var body: some View {
        let later = vm.bubbles.last?.id != bubble.id
        SheetCard(title: "Edit your message", close: "Cancel", done: done) {
            NoteBox(text: $text, placeholder: "Your message", minHeight: 100, autofocus: true)
            if later { Text("This replaces the answers after it with a new one.").font(Emvryx.body(13)).foregroundStyle(Emvryx.muted) }
            PwaButton(text: "Save and ask again", enabled: !text.isBlank) { vm.edit(bubble, text); done() }
        }
        .onAppear { text = bubble.text }
    }
}

struct ShareLinkSheet: View {
    @ObservedObject var vm: AppModel
    let done: () -> Void
    @State private var days = 7
    @State private var copied = false
    var body: some View {
        SheetCard(title: "Share a link", done: { vm.closeShares(); done() }) {
            if let s = vm.shares {
                if !s.on {
                    Text("Sharing links is switched off on this Emvryx. The owner can turn it on in Settings > Owner > Overview.")
                        .font(Emvryx.body(15)).foregroundStyle(Emvryx.muted)
                } else {
                    Text("Anyone who has the link can read a copy of this chat as it is now: only the words, not pictures, files or later messages. You can cancel the link any time.")
                        .font(Emvryx.body(14)).foregroundStyle(Emvryx.muted)
                    HStack(spacing: 8) { Seg(text: "1 day", on: days == 1) { days = 1 }; Seg(text: "7 days", on: days == 7) { days = 7 }; Seg(text: "30 days", on: days == 30) { days = 30 } }
                    PwaButton(text: "Make a link") { vm.makeShare(days: days); copied = false }
                    if let url = vm.shareUrl {
                        Text(url).font(Emvryx.body(14)).foregroundStyle(Emvryx.text).textSelection(.enabled)
                        HStack(spacing: 8) {
                            Chip(text: copied ? "Copied" : "Copy link") { UIPasteboard.general.string = url; copied = true }
                            if let u = URL(string: url) { ShareLink(item: u) { Text("Share…").font(Emvryx.body(14)).foregroundStyle(Emvryx.muted).padding(.horizontal, 14).frame(height: 36).overlay(Capsule().stroke(Emvryx.line, lineWidth: 1)) } }
                        }
                    }
                }
                if !s.shares.isEmpty { Text("Your links").font(Emvryx.body(16, semibold: true)).foregroundStyle(Emvryx.text).padding(.top, 6) }
                ForEach(s.shares) { r in
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(r.title).font(Emvryx.body(15, semibold: true)).foregroundStyle(Emvryx.text).lineLimit(1)
                            Text("Works until " + Date(timeIntervalSince1970: r.expires).formatted(.dateTime.day().month(.abbreviated).year()))
                                .font(Emvryx.body(13)).foregroundStyle(Emvryx.muted)
                        }
                        Spacer(minLength: 0)
                        Chip(text: "Cancel link") { vm.revokeShare(r) }
                    }
                }
            } else {
                ProgressView().tint(Emvryx.muted).frame(maxWidth: .infinity)
            }
        }
        .onAppear { vm.loadShares() }
    }
}

/// Save as (documents.js saveAs): PDF, Word or Markdown made on the server and handed to the iPhone's share sheet; or just copy the text.
struct SaveAsSheet: View {
    @ObservedObject var vm: AppModel
    let text: String
    let done: () -> Void
    let onFile: (URL) -> Void
    @State private var working = false
    var body: some View {
        SheetCard(title: "Save as", done: done) {
            Text("Worksheets keep the answer key and teacher notes on their own pages, so you can print page 1 for the class.")
                .font(Emvryx.body(14)).foregroundStyle(Emvryx.muted)
            PwaButton(text: "PDF", busy: working) { make("pdf") }
            PwaButton(text: "Word", enabled: !working) { make("docx") }
            PwaButton(text: "Markdown", ghost: true, enabled: !working) { make("md") }
            PwaButton(text: "Copy text", ghost: true) { UIPasteboard.general.string = text; done() }
        }
    }
    private func make(_ format: String) {
        working = true
        Task {
            if let url = await vm.saveAs(format, text: text) { done(); onFile(url) }
            working = false
        }
    }
}

/// The memory ring's details (the context window), with "Compact now".
struct MemorySheet: View {
    @ObservedObject var vm: AppModel
    let done: () -> Void
    var body: some View {
        SheetCard(title: "Memory", done: done) {
            if let c = vm.ctx {
                let left = max(0, c.compactAt - c.used)
                Capsule().fill(Emvryx.line).frame(height: 8).overlay(alignment: .leading) {
                    GeometryReader { g in Capsule().fill(vm.palette.accent).frame(width: g.size.width * min(max(c.pct / 100, 0), 1)) }
                }
                .frame(height: 8)
                kv("\(Int(c.pct.rounded()))% used", "\(kTok(c.used)) of \(kTok(c.window)) tokens", bold: true)
                kv("Free", kTok(max(0, c.window - c.used)))
                if c.compactAt > 0 { kv("Summarizes older messages at", kTok(c.compactAt) + (left > 0 ? " (\(kTok(left)) to go)" : " (next step)")) }
                Text("When it gets there, the older messages are summarized so the chat can keep going. Compact now does it straight away.")
                    .font(Emvryx.body(13)).foregroundStyle(Emvryx.muted)
                if vm.chatId != nil && !vm.isPrivate { PwaButton(text: "Compact now", enabled: !vm.streaming) { vm.compact(); done() } }
            }
        }
    }
    private func kv(_ k: String, _ v: String, bold: Bool = false) -> some View {
        HStack(alignment: .top) {
            Text(k).font(Emvryx.body(14, semibold: bold)).foregroundStyle(Emvryx.text)
            Spacer(minLength: 12)
            Text(v).font(Emvryx.body(14)).foregroundStyle(Emvryx.muted).multilineTextAlignment(.trailing)
        }
    }
    /// 12k, 1.5k, 800: a token count short.
    private func kTok(_ n: Int64) -> String {
        n >= 1000 ? (n % 1000 == 0 || n >= 10_000 ? "\(n / 1000)k" : String(format: "%.1fk", Double(n) / 1000)) : "\(n)"
    }
}

/// The usage sheet (chat.js openUsage): the token tank, when it is full again, this week's allowance, and messages left per model.
struct UsageSheet: View {
    let usage: Usage
    let done: () -> Void
    var body: some View {
        SheetCard(title: "Usage", done: done) {
            if usage.exempt {
                Text("No usage limit on this account.").font(Emvryx.body(16)).foregroundStyle(Emvryx.text)
            } else {
                row("Right now", "\(Usage.percent(usage.tankPct / 100)) · about \(usage.tankMessagesLeft) messages")
                if usage.tankFullAt > 0 { row("Full again", Date(timeIntervalSince1970: usage.tankFullAt).formatted(.relative(presentation: .named))) }
                row("This week", "\(Usage.percent(usage.weekPctLeft / 100)) · about \(usage.weekMessagesLeft) messages")
                if usage.weekResetsAt > 0 { row("Week resets", Date(timeIntervalSince1970: usage.weekResetsAt).formatted(.relative(presentation: .named))) }
                if !usage.models.isEmpty {
                    Text("MESSAGES LEFT BY MODEL").font(Emvryx.body(12, semibold: true)).kerning(1.2).foregroundStyle(Emvryx.muted).padding(.top, 8)
                    ForEach(usage.models.indices, id: \.self) { i in row(usage.models[i].model.capitalized, "\(usage.models[i].messagesLeft)") }
                }
            }
        }
    }
    private func row(_ k: String, _ v: String) -> some View {
        HStack(alignment: .top) {
            Text(k).font(Emvryx.body(15)).foregroundStyle(Emvryx.text)
            Spacer(minLength: 12)
            Text(v).font(Emvryx.body(15)).foregroundStyle(Emvryx.muted).multilineTextAlignment(.trailing)
        }
    }
}

/// Archived chats: out of the list, but kept, searchable and still remembered. Tap one to open it; Put back returns it to the list.
struct ArchivedSheet: View {
    @ObservedObject var vm: AppModel
    let done: () -> Void
    var body: some View {
        SheetCard(title: "Archived chats", done: { vm.closeArchived(); done() }) {
            if let rows = vm.archivedChats {
                if rows.isEmpty { Text("No archived chats.").font(Emvryx.body(15)).foregroundStyle(Emvryx.muted) }
                ForEach(rows) { c in
                    HStack {
                        Button { vm.openChat(c.id); vm.closeArchived(); done() } label: {
                            Text(c.title).font(Emvryx.body(16)).foregroundStyle(Emvryx.text).lineLimit(1).frame(maxWidth: .infinity, alignment: .leading)
                        }
                        Chip(text: "Put back") { vm.archive(c, false) }
                    }
                }
            } else {
                ProgressView().tint(Emvryx.muted).frame(maxWidth: .infinity)
            }
        }
        .task { await vm.loadArchived() }
    }
}
