import SwiftUI

// The Android app's colours, fonts and logo (android/.../ui/theme/Theme.kt and ui/Logo.kt), dark look. Sizes are in points, which
// match Android's dp and sp one for one.

/// The fixed page colours and the fonts.
enum Emvryx {
    static let bg = Color(hex: 0x07080D)
    static let side = Color(hex: 0x0A0B11)
    static let surface = Color(hex: 0x0F1119)
    static let surface2 = Color(hex: 0x161926)
    static let line = Color(hex: 0x232739)
    static let text = Color(hex: 0xEEF0F6)
    static let muted = Color(hex: 0x9AA3BC)
    static let danger = Color(hex: 0xF87171)
    // The Emvryx amber (Palette.brand), for the screens that have no model yet.
    static let accent = Palette.brand.accent
    static let onAccent = Palette.brand.onAccent
    static let glow = Palette.brand.glow
    /// Sora, for headings and titles, as the PWA does.
    static func heading(_ size: CGFloat, bold: Bool = false) -> Font { .custom(bold ? "Sora-Regular_Bold" : "Sora-Regular_SemiBold", size: size) }
    /// DM Sans, for everything else.
    static func body(_ size: CGFloat, semibold: Bool = false) -> Font {
        .custom(semibold ? "DMSans-9ptRegular_SemiBold" : "DMSans-9ptRegular_Regular", size: size)
    }
}

extension Color {
    init(hex: Int, opacity: Double = 1) {
        self.init(.sRGB, red: Double((hex >> 16) & 255) / 255, green: Double((hex >> 8) & 255) / 255, blue: Double(hex & 255) / 255, opacity: opacity)
    }
}

/// A model's colours: buttons ([accent], with [onAccent] text on them), accent text, the logo's [sun] and [core], and the soft [glow].
struct Palette: Equatable {
    var accent: Color, onAccent: Color, accentText: Color, sun: Color, core: Color, glow: Color

    private init(_ a: Int, _ on: Int, _ t: Int, _ sun: Int, _ core: Int, _ glow: Int, _ glowAlpha: Int) {
        accent = Color(hex: a); onAccent = Color(hex: on); accentText = Color(hex: t); self.sun = Color(hex: sun); self.core = Color(hex: core)
        self.glow = Color(hex: glow, opacity: Double(glowAlpha) / 255)
    }

    // Theme.kt Palettes (dark): accent, onAccent, accentText, sun, core, glow.
    static let brand = Palette(0xF5A524, 0x1A1204, 0xF5A524, 0xF5A524, 0xFFD27A, 0xF5A524, 0x24)
    static let ember = Palette(0xC8431F, 0xFFFFFF, 0xF0734F, 0xC8431F, 0xFFB05A, 0xC8431F, 0x33)
    static let flare = Palette(0xFF4B1F, 0x1A0500, 0xFF6B3D, 0xFF4B1F, 0xFFF3E6, 0xFF4B1F, 0x33)
    static let equinox = Palette(0xEEF0F6, 0x07080D, 0xEEF0F6, 0xEEF0F6, 0x07080D, 0xEEF0F6, 0x14)
    static let solstice = Palette(0xF2A60C, 0x1F1400, 0xFFBE3B, 0xF2A60C, 0xFFE7A0, 0xF2A60C, 0x2E)
    static let apogee = Palette(0xA8D1F5, 0x06121F, 0xB5D8F8, 0xA8D1F5, 0xF4F9FF, 0xA8D1F5, 0x26)
    static let violet = Palette(0x8B5CF6, 0xFFFFFF, 0xA78BFA, 0x8B5CF6, 0xC4B5FD, 0x8B5CF6, 0x24)

    /// A model's palette by its name; no name is Emvryx's amber and an unknown name gets Flare's, as on the website. With the violet
    /// look (violet_theme) the buttons and glow are violet and a model keeps only its own logo colours (core.js applyTheme).
    static func forModel(_ name: String?, violet: Bool = false) -> Palette {
        let own: Palette
        switch name?.lowercased() {
        case nil, "": own = .brand
        case "ember": own = .ember
        case "equinox": own = .equinox
        case "solstice": own = .solstice
        case "apogee": own = .apogee
        default: own = .flare
        }
        guard violet else { return own }
        if name?.isEmpty ?? true { return .violet }
        var p = own
        p.accent = Palette.violet.accent; p.onAccent = Palette.violet.onAccent; p.accentText = Palette.violet.accentText; p.glow = Palette.violet.glow
        return p
    }
}

/// The Emvryx mark as ui/Logo.kt draws it (web/js/core.js logo()) on a 64 x 64 grid: an E whose middle arm runs into a ring that
/// changes with the model (Ember a coal, Flare a ring, Equinox ticks, Solstice rays, Apogee halos). [kind] nil: Emvryx's own amber mark.
struct Logo: View {
    var kind: String? = nil
    var violet = false

    var body: some View {
        Canvas { ctx, size in
            let k = kind.map { $0.lowercased() }.flatMap { ["ember", "flare", "equinox", "solstice", "apogee"].contains($0) ? $0 : "flare" } ?? "brand"
            let p = Palette.forModel(k == "brand" ? nil : k, violet: k == "brand" && violet)
            let u = min(size.width, size.height) / 64
            func o(_ x: CGFloat, _ y: CGFloat) -> CGPoint { CGPoint(x: x * u, y: y * u) }
            func disc(_ r: CGFloat, _ cx: CGFloat = 46) -> Path { Path(ellipseIn: CGRect(x: (cx - r) * u, y: (32 - r) * u, width: 2 * r * u, height: 2 * r * u)) }
            func line(_ a: CGPoint, _ b: CGPoint, _ c: Color, _ w: CGFloat = 6) {
                var path = Path(); path.move(to: a); path.addLine(to: b)
                ctx.stroke(path, with: .color(c), style: StrokeStyle(lineWidth: w * u, lineCap: .round))
            }
            func rays(_ r1: CGFloat, _ r2: CGFloat, _ n: Int, _ c: Color) {
                for i in 0..<n {
                    let a = Double(i) * 2 * .pi / Double(n)
                    line(o(46 + r1 * cos(a), 32 + r1 * sin(a)), o(46 + r2 * cos(a), 32 + r2 * sin(a)), c, 2)
                }
            }
            let main = k == "apogee" ? p.sun : Emvryx.text
            ctx.fill(disc(k == "ember" ? 9 : k == "apogee" ? 15 : 12), with: .color(p.sun.opacity(0.16)))
            line(o(17, 16), o(41, 16), main)
            line(o(17, 48), o(41, 48), main)
            line(o(17, 16), o(17, 48), main)
            line(o(17, 32), o(k == "ember" ? 36 : 37, 32), p.sun)
            switch k {
            case "brand":
                ctx.stroke(disc(5.5), with: .color(p.core), lineWidth: 3 * u)
                ctx.fill(disc(1.8), with: .color(p.sun))
            case "ember":
                ctx.fill(disc(3.4, 45), with: .color(p.sun))
            case "apogee":
                ctx.fill(disc(4.5), with: .color(p.core)); ctx.stroke(disc(4.5), with: .color(p.sun), lineWidth: 2.5 * u)
                ctx.stroke(disc(8.5), with: .color(p.sun.opacity(0.7)), lineWidth: 1.6 * u)
                ctx.stroke(disc(12), with: .color(p.sun.opacity(0.4)), lineWidth: 1.2 * u)
            default:
                ctx.fill(disc(5.5), with: .color(p.core)); ctx.stroke(disc(5.5), with: .color(p.sun), lineWidth: 3 * u)
                if k == "equinox" { rays(8.5, 11, 4, Emvryx.text) }
                if k == "solstice" { rays(8.5, 11.5, 8, p.sun) }
            }
        }
    }
}
