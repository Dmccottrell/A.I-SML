import SwiftUI

/// The chat list that slides in from the left (android/.../ui/ChatScreen.kt Sidebar): new chat, search, the chats grouped by day, the
/// links (VryxCode, Skills, Documents, Private chat) and the account menu at the bottom.
struct Sidebar: View {
    @ObservedObject var vm: AppModel
    let done: () -> Void
    let onSheet: (ChatSheet) -> Void
    @State private var query = ""
    @State private var account = false
    @State private var deleting: ChatSummary?
    @ObservedObject private var lock = AppLock.shared

    var body: some View {
        let p = vm.palette
        let shown = vm.chats.filter { query.isBlank || $0.title.localizedCaseInsensitiveContains(query.trimmingCharacters(in: .whitespaces)) }
        let inside = (vm.hits ?? []).filter { h in !shown.contains { $0.id == h.id } }
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
                    .onChange(of: query) { vm.search($0) }
            }
            .padding(.horizontal, 10).frame(minHeight: 40)
            .background(Emvryx.surface, in: RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(Emvryx.line, lineWidth: 1))
            .padding(.horizontal, 14).padding(.vertical, 6)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 2) {
                    ForEach(groups(shown), id: \.0) { label, rows in
                        header(label)
                        ForEach(rows) { c in row(c, p) }
                    }
                    if !query.isBlank && !inside.isEmpty {
                        header("IN MESSAGES")
                        ForEach(inside) { h in
                            Button { vm.openChat(h.id); done() } label: {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(h.title).font(Emvryx.body(16)).foregroundStyle(Emvryx.text).lineLimit(1)
                                    if !h.snippet.isBlank { Text(h.snippet).font(Emvryx.body(13)).foregroundStyle(Emvryx.muted).lineLimit(2) }
                                }
                                .padding(.horizontal, 12).padding(.vertical, 8).frame(maxWidth: .infinity, alignment: .leading).contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    if shown.isEmpty && inside.isEmpty {
                        Text(query.isBlank ? "No chats yet." : "No chats match.").font(Emvryx.body(15)).foregroundStyle(Emvryx.muted)
                            .padding(.horizontal, 6).padding(.vertical, 14)
                    }
                }
                .padding(.horizontal, 14)
            }
            Rectangle().fill(Emvryx.line).frame(height: 1)
            SideLink(icon: "lock", text: "Private chat", note: "Never saved") { vm.newChat(isPrivate: true); done() }
            SideLink(icon: "chevron.left.forwardslash.chevron.right", text: "VryxCode") { vm.screen = .code; done() }
            SideLink(icon: "sparkles", text: "Skills") { vm.screen = .skills; done() }
            SideLink(icon: "doc", text: "Documents") { vm.screen = .files; done() }
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
                if vm.usage != nil { SideLink(icon: "chart.bar", text: "Usage") { onSheet(.usage); done() } }
                SideLink(icon: "brain", text: "Memory") { vm.screen = .memory; done() }
                SideLink(icon: "archivebox", text: "Archived chats") { onSheet(.archived); done() }
                SideLink(icon: "gearshape", text: "Settings") { vm.screen = .settings; done() }
                if vm.isAdmin { SideLink(icon: "shield", text: "Admin") { vm.open("/#admin", "Admin"); done() } }
                SideLink(icon: "lock.shield", text: "App lock", note: lock.enabled ? "On" : "Off") { lock.toggle() }
                SideLink(icon: "rectangle.portrait.and.arrow.right", text: "Sign out") { vm.signOut(); done() }
            }
        }
        .frame(maxWidth: 312, maxHeight: .infinity, alignment: .top)
        .frame(width: min(312, UIScreen.main.bounds.width * 0.86))
        .background(Emvryx.side.ignoresSafeArea())
        .overlay(alignment: .trailing) { Rectangle().fill(Emvryx.line).frame(width: 1).ignoresSafeArea() }
        .alert("Delete this chat?", isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }), presenting: deleting) { c in
            Button("Delete", role: .destructive) { vm.delete(c) }
            Button("Cancel", role: .cancel) {}
        } message: { c in Text("\"\(c.title)\" and its messages are deleted. This can't be undone.") }
    }

    private func header(_ label: String) -> some View {
        Text(label).font(Emvryx.body(11, semibold: true)).kerning(1.1).foregroundStyle(Emvryx.muted.opacity(0.8))
            .padding(.leading, 6).padding(.top, 14).padding(.bottom, 2)
    }

    /// One chat in the list; hold it to pin, archive or delete it. The current chat has a soft fill and an accent edge on the left.
    private func row(_ c: ChatSummary, _ p: Palette) -> some View {
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
        .contextMenu {
            Button(c.pinned ? "Unpin" : "Pin") { vm.pin(c) }
            Button("Archive (still remembered)") { vm.archive(c) }
            Button("Delete", role: .destructive) { deleting = c }
        }
        .accessibilityLabel(c.title)
        .accessibilityIdentifier("chatrow")
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

struct SideLink: View {
    let icon: String
    let text: String
    var note = ""
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: icon).font(.system(size: 16)).foregroundStyle(Emvryx.muted).frame(width: 22)
                Text(text).font(Emvryx.body(16)).foregroundStyle(Emvryx.text)
                if !note.isEmpty { Text(note).font(Emvryx.body(13)).foregroundStyle(Emvryx.muted) }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 20).frame(minHeight: 44).contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(text)
    }
}
