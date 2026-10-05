# Emvryx design concept (Oct 2026)

The first design for the Emvryx website, app and logo. It is a **concept**: nothing here is built into the app yet. The
requirements and behaviour are in [docs/APP_SPEC.md](../docs/APP_SPEC.md) and [docs/APP.md](../docs/APP.md).

## What is in this folder
| Path | What |
|---|---|
| `logo/*.svg` | Standalone logo files: the primary mark (dark and light) and the five model marks |
| `brand-tokens.json` | Colours (dark and light base, plus one palette per model) and fonts, ready to turn into CSS variables |
| `canvas/*.dc.html`, `canvas/canvas.json` | The design canvas sources: logo and brand board, model colours, website home (dark and light), desktop chat (dark and light), model picker, phone chat (dark and light) |

The `.dc.html` files are sources for a Claude Design canvas (they need its runtime, so they will not open as plain web pages).
To keep editing them, publish the folder to a Design canvas and open it there. The final website and app will be built
separately from these designs.

## The logo: an E with a spark (Oct 2026)
- **Primary mark:** an E whose middle arm runs into a glowing ring: the model's core, the spark. It starts the name, reads at tiny
  sizes, and is amber (`#F5A524`) on the dark background. (Replaced the earlier brain-and-X.)
- **Family mark:** the same E for all five models, each in its own colour, with a ring that grows: Ember (a small coal), Flare (a ring
  with a pale core), Equinox (ring with four ticks, white), Solstice (ring with eight rays, amber), Apogee (ring with two halos, ice blue).
- **Small sizes:** favicon and app icon use a bolder E and a solid dot (`web/icon.svg`, `logo/emvryx-icon-small.svg`).
- **Files:** `python design/logo/make_logos.py` rewrites every file in `logo/` and `web/icon.svg`. The concepts that led here are in `logo/concepts/`.
- The usage meter is an E that fills like a tank.

## Look and feel
- Dark by default and very dark (`#07080D`), with a light mode. One accent colour at a time.
- Fonts: Sora for headings, DM Sans for text.
- The chat's model chooser sits under the message box (next to + and Send), with the model's own icon beside its name and an
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
Flare 3 (v3, beta, trained from scratch), **Flare 2** (Qwen-based, in training), **Equinox 2**, Solstice 2, Apogee 2 (the 2.x series). The cards show only the
name; the version appears as a small grey number in the model sheet.

## Website: five pages, not one long page
The site is split so no page is cluttered. Each page has the same top menu (Models, Plans, How usage works, About) and footer, and links to the others.

| Page | File | What is on it |
|---|---|---|
| **Home** | `Main.dc.html` | Hero with a chat preview, the five models in one row, three highlights (private, remembers you, shows its sources), a short plans teaser, try it |
| **Models** | `SiteModels.dc.html` | The five models in detail (colour, job, which plans have it, which effort levels it offers) and the effort explained (Quick, Balanced, Deep) |
| **Plans** | `SitePlans.dc.html` | Free, Pro and Mega side by side in plain language (messages a week, in one sitting, models, document length), "always free on your own device", "plans are planned, prices to be announced" |
| **How usage works** | `SiteUsage.dc.html` | Right now (the brain tank), this week (resets Monday 4 AM), what a message costs by model, effort and usage, tips, and a short "for the curious" about tokens |
| **About** | `SiteAbout.dc.html` | Built from the ground up (stats, a "How it measures up" comparison table (Emvryx models side by side), and what makes it different), at home or in the cloud, private or public, what to keep in mind |

**Comparison table rule:** one column per model (Earlier v2, Flare 3, Flare 2 highlighted as the one in training, Equinox 2, Solstice 2, Apogee 2), a few rows only (HellaSwag, the Emvryx 20-question test sheet, long-document recall). A dash means not measured yet. **Benchmark strip rule (same idea):** only measured scores are drawn as solid bars (v2 28.4%, Flare 3 31.7% at step 15,000, both HellaSwag on the full 10,042-question test); forecasts (Flare 3.5, Equinox 4) are drawn dashed and labelled as forecasts, and are replaced when the model finishes training. No score of another company's model is shown. `HomeLight.dc.html` is the Home page in light mode. The canvas itself is also split into three pages: **Brand**, **Website** and **App screens**. Placeholders left in: `[YEAR]` and the invite link; prices are "to be announced".

## Usage and limits
Plain language first: **messages left**, not tokens. The phone's **Usage** screen shows a brain that fills like a tank ("Right now: about 250 messages"), "Left this week"
(a big percentage, about how many messages, the reset time, "comfortable pace"), messages left by model, a tip for making usage last, and a collapsed "See the numbers (tokens)" section.
**Every number follows the account's plan** (Free, Pro, Mega), so the same screen shows different amounts on each. The owner-only **Usage limits** screen has a tab per plan and sets the
tank (capacity and hourly refill), the weekly ceiling, the Everyday and Long context windows, the models the plan can use, the counting multipliers and the model weights. The context window
caps one request; it is not an allowance. Full plan and worked examples: docs/APP_SPEC.md ("Usage and limits").

## Still open
- Final logo choice (the earlier network-Y and cradle ideas were dropped), plus app-icon and favicon exports as PNG/ICO.
- Equinox's spark is a black core in a white ring; a yin-yang symbol is not drawn yet.
- Whether the website's model cards should also re-colour the page on hover or click.
- Trademark, store and domain checks for "Emvryx".

## New logo concepts (Oct 2026)
`logo/concepts/`: three simpler marks to replace the brain-and-X, all on the amber `#F5A524` brand colour.
`a-bars-e.svg` (an E of three bars with a spark), `b-spark-x.svg` (a crossed X with a glowing core; recommended: it
reads at 24 px and echoes the X in Emvryx), `c-ember.svg` (a flame with a core). Not yet used by the site or app.
`d-e-ring.svg` (the bars E with B's glowing ring at the end of the amber arm: A + B joined) and `h-rise-e.svg` (the same, with the arms tilted upward like a rising spark) combine the two favourites.
