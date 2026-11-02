# Design 2027 (switch `design_2027`, owner only until reviewed)

One new look for the website, the installed app (PWA) and the Android app. It is a single switch in Admin > Previews, **Owner** to start with,
so nobody else sees it. Off, everything looks exactly as before. **This is not merged to main until the owner has reviewed it.**

Website files: `web/design2027.css` (the look), `web/js/design2027.js` (the few things CSS cannot do). Android: `ui/Design2027.kt` and small changes in
`ChatScreen.kt`, `CodeScreen.kt`, `theme/Theme.kt`, `AppViewModel.kt`.

| Brief | Website / PWA | Android |
|---|---|---|
| Floating frosted-glass input bar, 16 px off the bottom, blur 40, carbon at 70% | Yes: it floats over the chat and text blurs as it passes under | Detached 16 dp from the bottom, frosted carbon, lit top edge. **No real blur behind it** (Android cannot blur what is behind a view this way), and it does not float over the chat |
| Model and effort as tiny glowing tags (12 px) | Yes | Yes |
| Send button: no solid fill, glowing amethyst ring that pulses while the model writes (and the memory ring glows too) | Yes | Yes |
| Dense VryxCode list, hairline borders | Yes | Yes (organizer rows) |
| Monospace for metrics, dates, usage, token numbers | Yes (Geist Mono, JetBrains Mono, then the system's) | Yes (the system's monospace; the two named fonts are not bundled) |
| Ghost buttons (New session, Build it, New chat) | Yes | Yes |
| Pure OLED black | Yes (dark mode) | Yes (dark mode) |
| Slow ambient glow behind the top, violet at rest, amber while working (teal in VryxCode on the website) | Yes | Yes (violet and amber) |
| Tactile cards: matte carbon, 1 px lit top border, 2% grain | Yes | Carbon and lit border; no grain |
| Usage as a pill near the top, steady digits | Yes | Yes |
| Sidebar in two bento blocks (chat tools, developer tools) | Yes | Yes |
| Words fade in over 50 ms as they arrive | Yes (only the newest characters fade) | **Not done** |
| Speed line under replies (tokens a second, model, first word) | Yes | Yes. Measured on the device while the reply streams; tokens are estimated from the length (about 4 letters each). VryxCode sessions do not stream tokens, so it is under chat replies only |
| Quiet code theme (black blocks, hairline border, soft cyan, pale gold, amethyst) | Yes (VryxCode code; chat code blocks black with a hairline) | Black blocks with a hairline border; no colour theme for the words |
| Card grows into the next page | Yes where the browser has View Transitions (Chrome, Edge, Safari 18) | **Not done** |
| Shimmering skeleton instead of a spinner | Yes (opening a session) | Yes (a session that is starting) |

Respects "reduce motion" on the website. Light mode keeps the normal colours (the look is dark-first).
