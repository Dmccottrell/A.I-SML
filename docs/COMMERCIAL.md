# The Emvryx commercial

Two cuts of one idea: **"Small models. Real help."** A 15 second silent animation, and a 30 second animation **with a voice, captions and music**, both built. The 30 second script below is the one the voiced version follows.

## The 15 second animated version (built)
- The page: `site/commercial.html` (1080 x 1920, the shape of Reels, Shorts and TikTok). Open it in a browser: it plays by itself, has a Replay button and a scrubber. `?t=8.9` shows one moment, `?clean` hides the buttons. It is not linked from the site and is marked noindex until the owner decides to publish it.
- The video: `python tools/render_commercial.py` asks the page for each of the 450 frames (30 a second) in a real browser and lets ffmpeg make `site/emvryx-ad-15s.mp4`. `--music` adds a soft pad that ffmpeg makes from sine tones itself (nothing copied from any recording, so no music rights). `--stills` writes six pictures to look at.
- Colours and shapes are the app's own (the E mark, the violet glow, the carbon cards). The wording only claims what the app does: private chat that is never saved, the phone app working with no internet, the four models, research and code.
- On the website only: a video page cannot be inside the Android app.

| Time | What you see | Words on screen |
|---|---|---|
| 0.0 to 2.9 | the E mark draws itself, the dot pops | Meet Emvryx / A small AI that does big things |
| 2.6 to 6.4 | a question is typed, the answer arrives word by word | Ask anything. |
| 6.2 to 9.9 | VryxCode writes a file, checks the page, runs the tests | Build anything. |
| 9.7 to 12.5 | four cards pop in | Made for you. Private chat. On your phone. Pick your model. Research and code. |
| 12.3 to 15.0 | the mark, the name, the button | Emvryx. Small models. Real help. emvryx.app |

## The 30 second version with the voice (built)
- The page: `site/commercial30.html` (unlisted, noindex). The list of spoken lines at the top of its script (`VOICE`) is the single source: the captions, the voice and the timing all come from it. "Sound" in the page's bar reads the lines with the browser's own voice (only a preview).
- The video: `python tools/render_commercial.py --cut 30` makes `site/emvryx-ad-30s.mp4` (900 frames at 30 a second, about 10 minutes). The voice is made on this computer by **Piper** (free, open source, nothing leaves the computer except the one-time voice download) and placed at each line's time; the soft original pad sits underneath and dips while the voice speaks.
- Credit (the voice's licence asks for it when the ad is published): **Voice: Alba, CSTR, University of Edinburgh, CC BY 4.0**. Alba is a British English voice. The other free voices are not used on purpose: Ryan is non-commercial only, and Lessac's licence is unclear.
- The voice is a computer voice: clear and even, not an actor. For a more human read, record the same lines yourself (the table below) and put your recording over the video in a free editor.
- If the voice says a word wrongly, change its spelling in the `VOICE` list (the brand name is spelt "Em-vrix" for the voice, "Emvryx" in the captions) and render again.
- Scenes: the mark draws itself in the dark; Meet Emvryx on a phone; a question and a plain answer; VryxCode builds and checks; a padlock closes and the phone answers with no internet; the four models; the sign-off.

## The 48 second feature advert (built): the real app, shown off
- Made of pictures of the **real** Emvryx screens, not drawings: `python tools/capture_app_screens.py` starts the server the way the tests do (a stand-in model, no one's data), opens the real web app in a phone-sized browser with the 2027 look, puts example messages on the screen and saves `site/ad-screens/*.png`. The page `site/commercial-features.html` (unlisted, noindex) plays them inside a phone.
- The video: `python tools/render_commercial.py --cut 48` makes `site/emvryx-ad-48s.mp4` (1,440 frames, about 20 minutes) with the same free voice (Alba, credit below) and the soft pad ducked under it.
- What it shows, in order: Ask anything (tables and code), Pick your model (Flare, Equinox, Solstice, Apogee, and how hard it thinks), Research (a report with numbered sources), Private chat (never saved), VryxCode building a bill splitter and checking it in a browser with a live preview, Dark or light, Everywhere (Android app, Windows app, any browser, offline on your phone). Only things the app does: the iPhone app is not advertised because it does not exist yet (`tests/test_commercial.py` checks this).
- The example messages are written for the picture (a sky question, an electric cars report, a bill splitter): they show what the screens look like, not real answers from a model.
- To change it: edit the `VOICE` and `FEATURES` lists at the top of the page's script (words, timing, pictures), run the capture again if a screen changed, then render.

## The 30 second script (for a voiced ad)
Tone: calm, warm, a little proud. Not shouting. Music: soft and rising, one gentle beat on each scene change. Voice: one person, natural, close to the microphone.

| Time | Picture | Voiceover | On screen |
|---|---|---|---|
| 0 to 4 | Black. The E mark draws itself and glows. | "Some AI wants to know everything about you." | (none) |
| 4 to 8 | The mark finishes, the dot pops. A phone appears. | "Emvryx just wants to help." | Meet Emvryx |
| 8 to 13 | A real person's hands, a kitchen table, a phone. Over their shoulder: a question typed, an answer arriving word by word. | "Ask it anything. It answers in plain words." | Ask anything. |
| 13 to 18 | Laptop, late evening. VryxCode writes a file, checks the page, runs the tests. A tick appears. | "Tell it what to build. It builds it, and checks its own work." | Build anything. |
| 18 to 23 | A phone on a train, aeroplane mode on. The chat still answers. A padlock closes on the words Private chat. | "Chat in private, and never saved. Even on your phone, even with no internet." | Private chat. On your phone. |
| 23 to 27 | Four model names slide in one by one: Flare, Equinox, Solstice, Apogee. | "Pick the model that fits the moment." | Pick your model. |
| 27 to 30 | The mark, the name, the button. | "Emvryx. Small models. Real help." | Emvryx / emvryx.app |

Read-aloud length: about 62 words, which fits 30 seconds at a calm pace.

**The 15 second voiced cut** (to go with the animation): "Meet Emvryx. Ask it anything. Tell it what to build. Chat in private, even with no internet. Emvryx. Small models. Real help."

## Captions and posts (short)
- "Meet Emvryx. A small AI that does big things. emvryx.app"
- "Ask anything. Build anything. Private chat, never saved. #AI #Emvryx"
- "It works on your phone, even with no internet."

## What still needs a person or money
Recording a human voice, filming real people, buying stock footage or paid music, and paying for ad space. None of it is done or bought. Free routes: record the voice on a phone, or add your own sound in a free editor such as CapCut on top of `emvryx-ad-15s.mp4`.

## Checks before it goes public
Say only what the app really does (the tests in `tests/test_commercial.py` keep the page to that list); do not name the base model family (house rule); look at it on a phone; decide where it is published (it is unlisted now).
