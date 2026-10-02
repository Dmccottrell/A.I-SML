# Yuvra design concept (Oct 2026)

The first design for the Yuvra website, app and logo. It is a **concept**: nothing here is built into the app yet. The
requirements and behaviour are in [docs/APP_SPEC.md](../docs/APP_SPEC.md) and [docs/APP.md](../docs/APP.md).

## What is in this folder
| Path | What |
|---|---|
| `logo/*.svg` | Standalone logo files: the primary mark (dark and light) and the four model marks |
| `brand-tokens.json` | Colours (dark and light base, plus one palette per model) and fonts, ready to turn into CSS variables |
| `canvas/*.dc.html`, `canvas/canvas.json` | The design canvas sources: logo and brand board, model colours, website home (dark and light), desktop chat (dark and light), model picker, phone chat (dark and light) |

The `.dc.html` files are sources for a Claude Design canvas (they need its runtime, so they will not open as plain web pages).
To keep editing them, publish the folder to a Design canvas and open it there. The final website and app will be built
separately from these designs.

## The logo: a brain, getting bigger
- **Primary mark ("Brain-Y"):** a brain outline with a Y inside it; the amber node where the Y splits is the spark of thought.
  It says AI at a glance and still reads as the letter Y.
- **Family mark:** four brains that grow with the models: Flare (plain brain with a core), Equinox (adds the Y), Solstice (adds
  folds), Apogee (the largest, outline lit in ice blue).
- **Small sizes:** the folds and the Y drop away so the brain and the spark stay solid (favicon, app icon).
- Say it "YOOV-ruh". Domain and trademark checks are still to do (see docs/APP.md).

## Look and feel
- Dark by default and very dark (`#07080D`), with a light mode. One accent colour at a time.
- Fonts: Sora for headings, DM Sans for text.
- The chat's model chooser sits under the message box (next to + and Send), with the model's own brain icon beside its name and an
  Effort chip (Quick, Balanced, Deep). Auto is the first card in the model sheet. No "offline" labels, and no fixed "on this phone"
  or "on your PC" labels: any model can run at home or in the cloud, privately or publicly (see docs/APP.md, "Where models run").

## Model colours and transitions
Choosing a model re-colours the whole page and plays a short transition.

| Model | Colour | Feel | Transition |
|---|---|---|---|
| **Flare** | hot red-orange `#FF4B1F`, white-hot core | a sudden, intense burst, like a plasma discharge | a fast flash |
| **Equinox** | pure black and white | balance of light and dark | a black and white turn |
| **Solstice** | deep molten gold `#F2A60C` | the sun at its peak, warmer than plain yellow | a slow golden swell |
| **Apogee** | cold ice blue `#A8D1F5` with silver particles | the farthest point of an orbit: distant and quiet | a cold, drifting fade |

The original amber (`#F5A524`) stays as the brand colour for the website home and the logo.

## Names (as of this design)
Flare 3 (v3, beta), **Flare 3.5** (v3.5, in training), **Equinox 4** (v4), Solstice 5 (v5), Apogee 6 (v6). The cards show only the
name; the version appears as a small grey number in the model sheet.

## Website home sections
Hero, "Four models, one family", what it does (private by default, remembers you, looks things up with sources, skills),
"Built from the ground up" (what Yuvra is), "At home or in the cloud, private or public", try it, footer. Placeholders left in:
`[YEAR]` and the invite link.

## Usage and limits: sparks
Yuvra's own usage design, counted in tokens and shown as **sparks** (1 spark = 1,000 counted tokens). The phone's **Sparks** screen shows a brain that fills
like a tank (with the core as the spark), a seven-day strip for the week, and tokens by model. The owner-only **Sparks and limits** screen sets the tank
(capacity and hourly refill), the weekly ceiling, the Everyday and Long context windows, the counting multipliers and the model weights. The context
window caps one request; it is not an allowance. Full plan and worked examples: docs/APP_SPEC.md ("Usage and limits: sparks").

## Still open
- Final logo choice (the earlier network-Y and cradle ideas were dropped), plus app-icon and favicon exports as PNG/ICO.
- Equinox's spark is a black core in a white ring; a yin-yang symbol is not drawn yet.
- Whether the website's model cards should also re-colour the page on hover or click.
- Trademark, store and domain checks for "Yuvra".
