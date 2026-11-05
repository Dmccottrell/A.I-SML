import SwiftUI
import XCTest
@testable import Emvryx

/// The dark and light looks: the same colours as android/.../ui/theme/Theme.kt, one set for each.
final class ThemeTests: XCTestCase {
    private func rgb(_ ui: UIColor, _ style: UIUserInterfaceStyle) -> Int {
        var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0
        ui.resolvedColor(with: UITraitCollection(userInterfaceStyle: style)).getRed(&r, green: &g, blue: &b, alpha: nil)
        return (Int((r * 255).rounded()) << 16) | (Int((g * 255).rounded()) << 8) | Int((b * 255).rounded())
    }

    func testAColourPairSwitchesWithTheLook() {
        let c = UIColor.pair(dark: 0x07080D, light: 0xF7F8FC)
        XCTAssertEqual(rgb(c, .dark), 0x07080D)
        XCTAssertEqual(rgb(c, .light), 0xF7F8FC)
        var a: CGFloat = 0
        UIColor.pair(dark: 0, light: 0, darkAlpha: 0.5, lightAlpha: 0.25).resolvedColor(with: UITraitCollection(userInterfaceStyle: .light)).getRed(nil, green: nil, blue: nil, alpha: &a)
        XCTAssertEqual(a, 0.25, accuracy: 0.01)
    }

    func testThePageColoursAreTheAndroidOnes() {
        let want: [String: (Int, Int)] = ["bg": (0x07080D, 0xF7F8FC), "side": (0x0A0B11, 0xEEF0F7), "surface": (0x0F1119, 0xFFFFFF), "surface2": (0x161926, 0xEEF0F7),
                                          "line": (0x232739, 0xD8DCEA), "text": (0xEEF0F6, 0x0D0F1A), "muted": (0x9AA3BC, 0x4A526B), "danger": (0xF87171, 0xD93A3A)]
        XCTAssertEqual(Set(Emvryx.values.keys), Set(want.keys))
        for (k, v) in want { XCTAssertEqual(Emvryx.values[k]?.dark, v.0, k); XCTAssertEqual(Emvryx.values[k]?.light, v.1, k) }
    }

    func testEachModelHasItsOwnLightColours() {
        // Theme.kt Palettes, dark and light (accent, onAccent, accentText, sun, core, glow rgb, glow alpha).
        func m(_ a: Int, _ on: Int, _ t: Int, _ sun: Int, _ core: Int, _ g: Int, _ ga: Int) -> Palette.Mode { .init(accent: a, onAccent: on, accentText: t, sun: sun, core: core, glow: g, glowAlpha: ga) }
        XCTAssertEqual(Palette.brand.dark, m(0xF5A524, 0x1A1204, 0xF5A524, 0xF5A524, 0xFFD27A, 0xF5A524, 0x24))
        XCTAssertEqual(Palette.brand.light, m(0xF5A524, 0x1A1204, 0x8F5600, 0xE08A00, 0xFFD27A, 0xF5A524, 0x1F))
        XCTAssertEqual(Palette.ember.light, m(0xB7391E, 0xFFFFFF, 0x8F2A14, 0xA8321A, 0xFF9A3C, 0xB7391E, 0x24))
        XCTAssertEqual(Palette.flare.dark, m(0xFF4B1F, 0x1A0500, 0xFF6B3D, 0xFF4B1F, 0xFFF3E6, 0xFF4B1F, 0x33))
        XCTAssertEqual(Palette.flare.light, m(0xFF4B1F, 0x1A0500, 0xB83208, 0xE5340A, 0xFFF3E6, 0xFF4B1F, 0x1F))
        XCTAssertEqual(Palette.equinox.dark, m(0xEEF0F6, 0x07080D, 0xEEF0F6, 0xEEF0F6, 0x07080D, 0xEEF0F6, 0x14))
        XCTAssertEqual(Palette.equinox.light, m(0x0D0F1A, 0xFFFFFF, 0x0D0F1A, 0x0D0F1A, 0xFFFFFF, 0x0D0F1A, 0x12))
        XCTAssertEqual(Palette.solstice.light, m(0xF2A60C, 0x1F1400, 0x8A5A00, 0xD18A00, 0xFFE7A0, 0xF2A60C, 0x21))
        XCTAssertEqual(Palette.apogee.light, m(0xA8D1F5, 0x06121F, 0x2A5F96, 0x4F8FC9, 0xF4F9FF, 0x78AADC, 0x26))
        XCTAssertEqual(Palette.violet.dark, m(0x8B5CF6, 0xFFFFFF, 0xA78BFA, 0x8B5CF6, 0xC4B5FD, 0x8B5CF6, 0x24))
        XCTAssertEqual(Palette.violet.light, m(0x7C3AED, 0xFFFFFF, 0x6D28D9, 0x7C3AED, 0x8B5CF6, 0x7C3AED, 0x1F))
    }

    func testTheVioletLookKeepsAModelsOwnLogoColours() {
        let p = Palette.forModel("flare", violet: true)
        XCTAssertEqual(p.dark.accent, Palette.violet.dark.accent)
        XCTAssertEqual(p.light.accentText, Palette.violet.light.accentText)
        XCTAssertEqual(p.dark.sun, Palette.flare.dark.sun)
        XCTAssertEqual(Palette.forModel(nil, violet: true), Palette.violet)
        XCTAssertEqual(Palette.forModel("unknown"), Palette.flare)
    }
}
