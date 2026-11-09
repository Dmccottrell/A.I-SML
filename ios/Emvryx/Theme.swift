import SwiftUI

// The Android app's colours, fonts and logo (android/.../ui/theme/Theme.kt and ui/Logo.kt), dark look. Sizes are in points, which
// match Android's dp and sp one for one.

/// A colour with a dark and a light version: it changes by itself when the app's look changes (the moon button). [lightAlpha] / [darkAlpha]
/// are the opacity of each.
extension Color {
    static func pair(dark: Int, light: Int, darkAlpha: Double = 1, lightAlpha: Double = 1) -> Color {
        Color(uiColor: .pair(dark: dark, light: light, darkAlpha: darkAlpha, lightAlpha: lightAlpha))
    }
    init(hex: Int, opacity: Double = 1) {
        self.init(.sRGB, red: Double((hex >> 16) & 255) / 255, green: Double((hex >> 8) & 255) / 255, blue: Double(hex & 255) / 255, opacity: opacity)
    }
}

extension UIColor {
    /// A UIKit colour that is [dark] in the dark look and [light] in the light look.
    static func pair(dark: Int, light: Int, darkAlpha: Double = 1, lightAlpha: Double = 1) -> UIColor {
        UIColor { trait in trait.userInterfaceStyle == .light ? UIColor(hex: light, alpha: lightAlpha) : UIColor(hex: dark, alpha: darkAlpha) }
    }
    convenience init(hex: Int, alpha: Double = 1) {
        self.init(red: CGFloat((hex >> 16) & 255) / 255, green: CGFloat((hex >> 8) & 255) / 255, blue: CGFloat(hex & 255) / 255, alpha: alpha)
    }
}

/// The fixed page colours (dark, and light as Android's Theme.kt has it) and the fonts.
enum Emvryx {
    /// The page colours as (dark, light) values: Theme.kt Emvryx.bg, side, surface ... (the tests check them against Android's).
    static let values: [String: (dark: Int, light: Int)] = [
        "bg": (0x07080D, 0xF7F8FC), "side": (0x0A0B11, 0xEEF0F7), "surface": (0x0F1119, 0xFFFFFF), "surface2": (0x161926, 0xEEF0F7),
        "line": (0x232739, 0xD8DCEA), "text": (0xEEF0F6, 0x0D0F1A), "muted": (0x9AA3BC, 0x4A526B), "danger": (0xF87171, 0xD93A3A),
    ]
    private static func pair(_ name: String) -> Color { Color.pair(dark: values[name]!.dark, light: values[name]!.light) }
    static let bg = pair("bg")
    static let side = pair("side")
    static let surface = pair("surface")
    static let surface2 = pair("surface2")
    static let line = pair("line")
    static let text = pair("text")
    static let muted = pair("muted")
    static let danger = pair("danger")
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

/// A model's colours: buttons ([accent], with [onAccent] text on them), accent text, the logo's [sun] and [core], and the soft [glow]. Each has a
/// dark and a light version.
struct Palette: Equatable {
    var accent: Color, onAccent: Color, accentText: Color, sun: Color, core: Color, glow: Color
    /// The same colours as plain values, for the tests (and for anything that needs the numbers).
    let dark: Mode, light: Mode

    /// One mode's six colours: accent, onAccent, accentText, sun, core, then the glow's colour and opacity (0 to 255).
    struct Mode: Equatable {
        var accent: Int, onAccent: Int, accentText: Int, sun: Int, core: Int, glow: Int, glowAlpha: Int
    }

    init(dark d: Mode, light l: Mode) {
        dark = d; light = l
        accent = .pair(dark: d.accent, light: l.accent); onAccent = .pair(dark: d.onAccent, light: l.onAccent)
        accentText = .pair(dark: d.accentText, light: l.accentText); sun = .pair(dark: d.sun, light: l.sun); core = .pair(dark: d.core, light: l.core)
        glow = .pair(dark: d.glow, light: l.glow, darkAlpha: Double(d.glowAlpha) / 255, lightAlpha: Double(l.glowAlpha) / 255)
    }

    // Theme.kt Palettes: the dark ones, then the light ones (brandL, emberL ...).
    static let brand = Palette(dark: Mode(accent: 0xF5A524, onAccent: 0x1A1204, accentText: 0xF5A524, sun: 0xF5A524, core: 0xFFD27A, glow: 0xF5A524, glowAlpha: 0x24),
                               light: Mode(accent: 0xF5A524, onAccent: 0x1A1204, accentText: 0x8F5600, sun: 0xE08A00, core: 0xFFD27A, glow: 0xF5A524, glowAlpha: 0x1F))
    static let ember = Palette(dark: Mode(accent: 0xC8431F, onAccent: 0xFFFFFF, accentText: 0xF0734F, sun: 0xC8431F, core: 0xFFB05A, glow: 0xC8431F, glowAlpha: 0x33),
                               light: Mode(accent: 0xB7391E, onAccent: 0xFFFFFF, accentText: 0x8F2A14, sun: 0xA8321A, core: 0xFF9A3C, glow: 0xB7391E, glowAlpha: 0x24))
    static let flare = Palette(dark: Mode(accent: 0xFF4B1F, onAccent: 0x1A0500, accentText: 0xFF6B3D, sun: 0xFF4B1F, core: 0xFFF3E6, glow: 0xFF4B1F, glowAlpha: 0x33),
                               light: Mode(accent: 0xFF4B1F, onAccent: 0x1A0500, accentText: 0xB83208, sun: 0xE5340A, core: 0xFFF3E6, glow: 0xFF4B1F, glowAlpha: 0x1F))
    static let equinox = Palette(dark: Mode(accent: 0xEEF0F6, onAccent: 0x07080D, accentText: 0xEEF0F6, sun: 0xEEF0F6, core: 0x07080D, glow: 0xEEF0F6, glowAlpha: 0x14),
                                 light: Mode(accent: 0x0D0F1A, onAccent: 0xFFFFFF, accentText: 0x0D0F1A, sun: 0x0D0F1A, core: 0xFFFFFF, glow: 0x0D0F1A, glowAlpha: 0x12))
    static let solstice = Palette(dark: Mode(accent: 0xF2A60C, onAccent: 0x1F1400, accentText: 0xFFBE3B, sun: 0xF2A60C, core: 0xFFE7A0, glow: 0xF2A60C, glowAlpha: 0x2E),
                                  light: Mode(accent: 0xF2A60C, onAccent: 0x1F1400, accentText: 0x8A5A00, sun: 0xD18A00, core: 0xFFE7A0, glow: 0xF2A60C, glowAlpha: 0x21))
    static let apogee = Palette(dark: Mode(accent: 0xA8D1F5, onAccent: 0x06121F, accentText: 0xB5D8F8, sun: 0xA8D1F5, core: 0xF4F9FF, glow: 0xA8D1F5, glowAlpha: 0x26),
                                light: Mode(accent: 0xA8D1F5, onAccent: 0x06121F, accentText: 0x2A5F96, sun: 0x4F8FC9, core: 0xF4F9FF, glow: 0x78AADC, glowAlpha: 0x26))
    static let violet = Palette(dark: Mode(accent: 0x8B5CF6, onAccent: 0xFFFFFF, accentText: 0xA78BFA, sun: 0x8B5CF6, core: 0xC4B5FD, glow: 0x8B5CF6, glowAlpha: 0x24),
                                light: Mode(accent: 0x7C3AED, onAccent: 0xFFFFFF, accentText: 0x6D28D9, sun: 0x7C3AED, core: 0x8B5CF6, glow: 0x7C3AED, glowAlpha: 0x1F))

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
        p = Palette(dark: Palette.Mode(accent: Palette.violet.dark.accent, onAccent: Palette.violet.dark.onAccent, accentText: Palette.violet.dark.accentText, sun: own.dark.sun, core: own.dark.core, glow: Palette.violet.dark.glow, glowAlpha: Palette.violet.dark.glowAlpha),
                    light: Palette.Mode(accent: Palette.violet.light.accent, onAccent: Palette.violet.light.onAccent, accentText: Palette.violet.light.accentText, sun: own.light.sun, core: own.light.core, glow: Palette.violet.light.glow, glowAlpha: Palette.violet.light.glowAlpha))
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
