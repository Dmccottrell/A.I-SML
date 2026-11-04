import SwiftUI

// The Android app's off screen (android/.../ui/OffScreen.kt) drawn the same way: the same logo, glow, fonts, sizes, colours and spacing.
// Sizes are in points, which match Android's dp and sp one for one. The colours, fonts and logo are in Theme.swift.

/// Shown when the site cannot be reached. [phoneOnline] false: the phone itself has no internet. Otherwise Android's words for the
/// server not answering. [retry] loads again (the app also retries by itself when the connection returns).
struct OffScreen: View {
    let phoneOnline: Bool
    /// The PC is busy in Gaming mode (GET /api/status "resting").
    var resting = false
    let retry: () -> Void

    var body: some View {
        ZStack {
            Emvryx.bg.ignoresSafeArea()
            AccentWash(glow: Emvryx.glow, height: 420).ignoresSafeArea()
            VStack(spacing: 14) {
                Logo().frame(width: 64, height: 64)
                Text(!phoneOnline ? "No connection" : resting ? "Emvryx is resting" : "Emvryx is off right now")
                    .font(Emvryx.heading(26))
                    .foregroundStyle(Emvryx.text)
                    .multilineTextAlignment(.center)
                Text(!phoneOnline ? "Your phone is offline. Check Wi-Fi or mobile data, then try again."
                     : resting ? "The PC is being used for something else. Please try again in a little while."
                     : "It runs on a home PC, and that PC is switched off, asleep, or offline. Your chats are safe and will be here when it is back.")
                    .font(Emvryx.body(16))
                    .lineSpacing(24 - 16 * 1.302)       // Android's bodyLarge: 16 sp text on 24 sp lines (DM Sans draws 1.302 x its size)
                    .foregroundStyle(Emvryx.muted)
                    .multilineTextAlignment(.center)
                PwaButton(text: "Try again", action: retry).padding(.top, 6)
                Text(Site.host)
                    .font(Emvryx.body(14))
                    .foregroundStyle(Emvryx.muted)
                    .padding(8)
            }
            .frame(maxWidth: 420)
            .padding(28)
        }
    }
}

/// The website's .btn and Android's PwaButton: accent fill, 12 pt corners, at least 48 pt tall, 18 pt side padding, 16 pt semibold label.
/// [ghost] is .btn.ghost (a line round a clear button); [enabled] false fades it to 45% and ignores taps; [busy] shows a spinner instead.
struct PwaButton: View {
    let text: String
    var ghost = false
    var palette: Palette = .brand
    var enabled = true
    var busy = false
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            ZStack {
                if busy { ProgressView().tint(ghost ? Emvryx.text : palette.onAccent) } else { Text(text).font(Emvryx.body(16, semibold: true)) }
            }
            .foregroundStyle(ghost ? Emvryx.text : palette.onAccent)
            .padding(.horizontal, 18)
            .frame(maxWidth: .infinity, minHeight: 48)
            .background(ghost ? Color.clear : palette.accent, in: RoundedRectangle(cornerRadius: 12))
            .overlay { if ghost { RoundedRectangle(cornerRadius: 12).stroke(Emvryx.line, lineWidth: 1) } }
            .contentShape(RoundedRectangle(cornerRadius: 12))
        }
        .buttonStyle(.plain)
        .disabled(!enabled || busy)
        .opacity(enabled ? 1 : 0.45)
        .accessibilityLabel(text)
    }
}

/// Android's Modifier.accentWash: a glow fading to clear, centred 78% across and 15% of [height] above the top, radius 1.4 x [height],
/// drawn no taller than 1.6 x [height].
struct AccentWash: View {
    let glow: Color
    let height: CGFloat

    var body: some View {
        Canvas { ctx, size in
            let rect = CGRect(x: 0, y: 0, width: size.width, height: min(size.height, height * 1.6))
            ctx.fill(Path(rect), with: .radialGradient(Gradient(colors: [glow, glow.opacity(0)]),
                                                       center: CGPoint(x: size.width * 0.78, y: -height * 0.15),
                                                       startRadius: 0, endRadius: height * 1.4))
        }
    }
}
