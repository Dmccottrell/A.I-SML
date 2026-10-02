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

## Website: five pages, not one long page
The site is split so no page is cluttered. Each page has the same top menu (Models, Plans, How usage works, About) and footer, and links to the others.

| Page | File | What is on it |
|---|---|---|
| **Home** | `Main.dc.html` | Hero with a chat preview, the four models in one row, three highlights (private, remembers you, shows its sources), a short plans teaser, try it |
| **Models** | `SiteModels.dc.html` | The four models in detail (colour, job, which plans have it, which effort levels it offers) and the effort explained (Quick, Balanced, Deep) |
| **Plans** | `SitePlans.dc.html` | Free, Pro and Mega side by side in plain language (messages a week, in one sitting, models, document length), "always free on your own device", "plans are planned, prices to be announced" |
| **How usage works** | `SiteUsage.dc.html` | Right now (the brain tank), this week (resets Monday 4 AM), what a message costs by model, effort and usage, tips, and a short "for the curious" about tokens |
| **About** | `SiteAbout.dc.html` | Built from the ground up (stats and what makes it different), at home or in the cloud, private or public, what to keep in mind |

`HomeLight.dc.html` is the Home page in light mode. The canvas itself is also split into three pages: **Brand**, **Website** and **App screens**. Placeholders left in: `[YEAR]` and the invite link; prices are "to be announced".

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
- Trademark, store and domain checks for "Yuvra".
