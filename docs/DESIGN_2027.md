# Design 2027 (switch `design_2027`, admins and the owner first)

One new look for the website, the installed app (PWA) and the Android app. It is a single switch in Admin > Previews, **Owner** to start with,
so nobody else sees it. Off, everything looks exactly as before. **This is not merged to main until the owner has reviewed it.**

Website files: `web/design2027.css` (the look), `web/js/design2027.js` (the few things CSS cannot do). Android: `ui/Design2027.kt` and small changes in
`ChatScreen.kt`, `CodeScreen.kt`, `theme/Theme.kt`, `AppViewModel.kt`.

| Brief | Website / PWA | Android |
|---|---|---|
| Floating frosted-glass input bar, 16 px off the bottom, blur 40, carbon at 70% | Yes: it floats over the chat and text blurs as it passes under | Detached 16 dp from the bottom, frosted carbon, lit top edge. **No real blur behind it** (Android cannot blur what is behind a view this way), and it does not float over the chat |
| Model and effort as tiny glowing tags (12 px) | Yes | Yes |
| Send button: no solid fill, a neon amethyst ring as the focal point. On the website it is one ring that also shows how full the chat's memory is, and it beats once per batch of words as they arrive | Yes | A glowing ring that pulses while the model writes (a steady pulse, not tied to each batch; the memory ring is still separate) |
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

## First review fixes (website and Android)

1. The user's message is a tactile matte carbon bubble (#16161D) with a lit top edge and a soft shadow, so it no longer melts into the glow.
2. The message bar is translucent carbon at 40% with a 40 px blur (the website also on touch phones, where the older look had switched the blur off).
   Android has the translucency and the lit edge but cannot blur what is behind the bar.
3. The top bar carries only the menu, a centred bold title and the icons. The usage pill moved to the sidebar, just above your name. The "Protect the owner
   account" banner (website) is a floating dark-glass card under the header with ghost buttons. (The Android app has no such banner.)
4. The buttons under a reply (Copy, Right, Regenerate) and the Edit button are not pills any more: muted #71717A text that lights up (#E4E4E7) when touched.


## VryxCode building screen (web)

The screen where VryxCode works now matches chat: your task is a solid carbon card (#16161D) with a lit top edge and shadow; the message bar floats as 40% dark glass with a 40px blur over the feed; "Allow this?" and questions are carbon cards with hollow ghost answers; tool rows are flat with hairlines. Tests: `tests/test_design_2027.py` (VryxCode home and building screen, plus the switch-off check).

Android: the same building screen (carbon task card, floating glass message bar with the glowing ring, carbon cards for steps, files and the end card, ghost answers on "Allow this?"). Wide editor layout (web): carbon panels, hairline lines, hollow mono tags for every small button, amethyst underline on the open tab, black code area.

### Calmer, more like Claude (VryxCode screen)

Steps and file changes are one quiet line of text (no box, no side bar); a change's code opens only when the line is tapped. The code font is only for names and code. "Allow this?" is a plain hairline card; only the main answer is amethyst. New text prints in VryxCode's colour (amethyst) and settles to its normal colour in about 1.8 seconds (web: `d27ink` animation; Android: `d27Ink`).
