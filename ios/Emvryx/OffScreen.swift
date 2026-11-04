import SwiftUI

// The Android app's off screen (android/.../ui/OffScreen.kt) drawn the same way: the same logo, glow, fonts, sizes, colours and spacing.
// Sizes are in points, which match Android's dp and sp one for one.

/// The colours from android/.../ui/theme/Theme.kt (dark, the Emvryx amber "brand" palette used before a model is known).
enum Emvryx {
    static let bg = Color(hex: 0x07080D)
    static let text = Color(hex: 0xEEF0F6)
    static let muted = Color(hex: 0x9AA3BC)
    static let accent = Color(hex: 0xF5A524)
    static let onAccent = Color(hex: 0x1A1204)
    static let sun = Color(hex: 0xF5A524)
    static let core = Color(hex: 0xFFD27A)
    static let glow = Color(hex: 0xF5A524, opacity: 0x24 / 255.0)
    static func heading(_ size: CGFloat) -> Font { .custom("Sora-Regular_SemiBold", size: size) }
    static func body(_ size: CGFloat, semibold: Bool = false) -> Font {
        .custom(semibold ? "DMSans-9ptRegular_SemiBold" : "DMSans-9ptRegular_Regular", size: size)
    }
}

extension Color {
    init(hex: Int, opacity: Double = 1) {
        self.init(.sRGB, red: Double((hex >> 16) & 255) / 255, green: Double((hex >> 8) & 255) / 255, blue: Double(hex & 255) / 255, opacity: opacity)
    }
}

/// Shown when the site cannot be reached. [phoneOnline] false: the phone itself has no internet. Otherwise Android's words for the
/// server not answering. [retry] loads again (the app also retries by itself when the connection returns).
struct OffScreen: View {
    let phoneOnline: Bool
    let retry: () -> Void

    var body: some View {
        ZStack {
            Emvryx.bg.ignoresSafeArea()
            AccentWash(glow: Emvryx.glow, height: 420).ignoresSafeArea()
            VStack(spacing: 14) {
                Logo().frame(width: 64, height: 64)
                Text(phoneOnline ? "Emvryx is off right now" : "No connection")
                    .font(Emvryx.heading(26))
                    .foregroundStyle(Emvryx.text)
                    .multilineTextAlignment(.center)
                Text(phoneOnline
                     ? "It runs on a home PC, and that PC is switched off, asleep, or offline. Your chats are safe and will be here when it is back."
                     : "Your phone is offline. Check Wi-Fi or mobile data, then try again.")
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
struct PwaButton: View {
    let text: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(text)
                .font(Emvryx.body(16, semibold: true))
                .foregroundStyle(Emvryx.onAccent)
                .padding(.horizontal, 18)
                .frame(maxWidth: .infinity, minHeight: 48)
                .background(Emvryx.accent, in: RoundedRectangle(cornerRadius: 12))
        }
        .buttonStyle(.plain)
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

/// Android's Logo() with no model (Emvryx's own amber mark), drawn on the same 64 x 64 grid as web/js/core.js `logo()`.
struct Logo: View {
    var body: some View {
        Canvas { ctx, size in
            let u = min(size.width, size.height) / 64
            func o(_ x: CGFloat, _ y: CGFloat) -> CGPoint { CGPoint(x: x * u, y: y * u) }
            func circle(_ r: CGFloat) -> Path { Path(ellipseIn: CGRect(x: (46 - r) * u, y: (32 - r) * u, width: 2 * r * u, height: 2 * r * u)) }
            func line(_ a: CGPoint, _ b: CGPoint, _ c: Color) {
                var p = Path(); p.move(to: a); p.addLine(to: b)
                ctx.stroke(p, with: .color(c), style: StrokeStyle(lineWidth: 6 * u, lineCap: .round))
            }
            ctx.fill(circle(12), with: .color(Emvryx.sun.opacity(0.16)))      // the faint glow behind the ring
            line(o(17, 16), o(41, 16), Emvryx.text)                            // the E: top, bottom, upright
            line(o(17, 48), o(41, 48), Emvryx.text)
            line(o(17, 16), o(17, 48), Emvryx.text)
            line(o(17, 32), o(37, 32), Emvryx.sun)                             // its middle arm, into the ring
            ctx.stroke(circle(5.5), with: .color(Emvryx.core), lineWidth: 3 * u)
            ctx.fill(circle(1.8), with: .color(Emvryx.sun))
        }
    }
}
