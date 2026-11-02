# The Emvryx commercial

Two cuts of one idea: **"Small models. Real help."** A 30 second script for a voiced ad, and a 15 second animated version that is already built.

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

## The 30 second script (for a voiced ad)
Tone: calm, warm, a little proud. Not shouting. Music: soft and rising, one gentle beat on each scene change. Voice: one person, natural, close to the microphone.

| Time | Picture | Voiceover | On screen |
|---|---|---|---|
| 0 to 4 | Black. The E mark draws itself and glows. | "Some AI wants to know everything about you." | (none) |
| 4 to 8 | The mark finishes, the dot pops. A phone appears. | "Emvryx just wants to help." | Meet Emvryx |
| 8 to 13 | A real person's hands, a kitchen table, a phone. Over their shoulder: a question typed, an answer arriving word by word. | "Ask it anything. It answers in plain words." | Ask anything. |
| 13 to 18 | Laptop, late evening. VryxCode writes a file, checks the page, runs the tests. A tick appears. | "Tell it what to build. It builds it, and checks its own work." | Build anything. |
| 18 to 23 | A phone on a train, aeroplane mode on. The chat still answers. A padlock closes on "Private chat". | "Chat in private, and never saved. Even on your phone, even with no internet." | Private chat. On your phone. |
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
