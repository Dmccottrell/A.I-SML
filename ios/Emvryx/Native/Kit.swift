import SwiftUI

// A small toolkit of reusable screen pieces (android/.../ui/Kit.kt): chips, the pills under the box, menus, sheets and a few shapes.

/// A button with just an icon (the top bar's menu and plus).
struct IconButton: View {
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

/// .chip: a small rounded button with a line round it (Copy, Regenerate).
struct Chip: View {
    let text: String
    var on = false
    let action: () -> Void
    @Environment(\.palette) private var p
    var body: some View {
        Button(action: action) {
            Text(text).font(Emvryx.body(14)).foregroundStyle(on ? p.accentText : Emvryx.muted).padding(.horizontal, 14).padding(.vertical, 6).frame(minHeight: 36)
                .overlay(Capsule().stroke(on ? p.accent : Emvryx.line, lineWidth: 1))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(text)
    }
}

/// A refusal or error: what happened and what to do (send.js errorCard).
struct FailureCard: View {
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

/// A small grey note under an answer (what it was given, how long it took, what it remembered).
struct Note: View {
    let text: String
    var body: some View { Text(text).font(Emvryx.body(13)).foregroundStyle(Emvryx.muted) }
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

/// Lays children out left to right and wraps them onto new lines (Android's FlowRow).
struct Flow: Layout {
    var spacing: CGFloat = 8
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        arrange(proposal.width ?? 300, subviews).size
    }
    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        for (i, f) in arrange(bounds.width, subviews).frames.enumerated() {
            subviews[i].place(at: CGPoint(x: bounds.minX + f.minX, y: bounds.minY + f.minY), proposal: ProposedViewSize(f.size))
        }
    }
    private func arrange(_ width: CGFloat, _ subviews: Subviews) -> (size: CGSize, frames: [CGRect]) {
        var x: CGFloat = 0, y: CGFloat = 0, row: CGFloat = 0, widest: CGFloat = 0
        var frames: [CGRect] = []
        for s in subviews {
            let size = s.sizeThatFits(.unspecified)
            if x > 0 && x + size.width > width { x = 0; y += row + spacing; row = 0 }
            frames.append(CGRect(origin: CGPoint(x: x, y: y), size: size))
            x += size.width + spacing; row = max(row, size.height); widest = max(widest, x - spacing)
        }
        return (CGSize(width: widest, height: y + row), frames)
    }
}

// MARK: - Menus and sheets

struct MenuHead: View {
    let text: String
    var body: some View {
        Text(text).font(Emvryx.body(12, semibold: true)).kerning(1.2).foregroundStyle(Emvryx.muted).padding(.horizontal, 6).padding(.vertical, 4)
    }
}

/// One choice in a menu: a line round it, in the accent colour when selected.
struct Opt<Content: View>: View {
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

struct PopMenu<Content: View>: View {
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

/// A sheet that slides up (Android's dialogs): a title, a body, and Close.
struct SheetCard<Content: View>: View {
    let title: String
    var close: String = "Close"
    let done: () -> Void
    @ViewBuilder let content: () -> Content
    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text(title).font(Emvryx.heading(20)).foregroundStyle(Emvryx.text)
                Spacer()
                Button(close, action: done).font(Emvryx.body(16, semibold: true)).foregroundStyle(Emvryx.muted)
            }
            .padding(.horizontal, 20).padding(.top, 20).padding(.bottom, 12)
            ScrollView {
                VStack(alignment: .leading, spacing: 10) { content() }.padding(.horizontal, 20).padding(.bottom, 24)
            }
        }
        .background(Emvryx.surface.ignoresSafeArea())
        .preferredColorScheme(.dark)
    }
}

/// A multi-line text input with a rounded box and a grey placeholder while it is empty.
struct NoteBox: View {
    @Binding var text: String
    let placeholder: String
    var minHeight: CGFloat = 48
    /// Opens the keyboard straight away (the edit sheet).
    var autofocus = false
    @FocusState private var focused: Bool
    var body: some View {
        TextField("", text: $text, prompt: Text(placeholder).foregroundColor(Emvryx.muted), axis: .vertical)
            .focused($focused)
            .task { if autofocus { try? await Task.sleep(nanoseconds: 500_000_000); focused = true } }
            .font(Emvryx.body(16)).foregroundStyle(Emvryx.text).tint(Emvryx.accent)
            .padding(12).frame(minHeight: minHeight, alignment: .topLeading)
            .background(Emvryx.bg, in: RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(Emvryx.line, lineWidth: 1))
            .accessibilityLabel(placeholder)
    }
}

/// A pill to pick one of a few (1 day, 7 days, 30 days).
struct Seg: View {
    let text: String
    let on: Bool
    let action: () -> Void
    @Environment(\.palette) private var p
    var body: some View {
        Button(action: action) {
            Text(text).font(Emvryx.body(14)).foregroundStyle(on ? p.onAccent : Emvryx.text).padding(.horizontal, 14).padding(.vertical, 8)
                .background(on ? p.accent : Emvryx.surface2, in: Capsule())
        }
        .buttonStyle(.plain)
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

/// The iPhone's own share sheet (for a file or a link).
struct ShareSheet: UIViewControllerRepresentable {
    let items: [Any]
    func makeUIViewController(context: Context) -> UIActivityViewController { UIActivityViewController(activityItems: items, applicationActivities: nil) }
    func updateUIViewController(_ vc: UIActivityViewController, context: Context) {}
}
