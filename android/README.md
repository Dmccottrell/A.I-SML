# Emvryx for Android

The native Android app: Kotlin + Jetpack Compose (the plan is in [docs/NATIVE.md](../docs/NATIVE.md)). It is a client of your Emvryx server, the same one the website talks to, so the PC must be on.

**What works:**
- Sign in with a password (with the two-step code if it is on) or a key. The session is kept encrypted on the phone and shows as "The Emvryx app on Android" in the website's Devices list.
- "Emvryx is off right now" when the PC does not answer, and "Emvryx is resting" in Gaming mode, with Try again.
- Chat with streamed replies, Stop, the model picker, and the effort picker for models that have one.
- **Pictures and files** (the + by the message box): pictures, screenshots and documents go with the message; a picture alone is sent as it is. Pictures show in the thread.
- **Regenerate options** (Try again, Shorter, Simpler, More detail …), **Continue** an answer that stopped at its length limit, **Report** an answer, **New chat from here**.
- Hold your message to **copy it or edit it and ask again**. Hold a chat in the list to **pin or delete** it. **Search** finds words inside chats too.
- The **memory ring** with *Compact now* (when the owner's "Memory meter" switch is on for you).
- **Share to Emvryx** from any app: text goes in the box, pictures and PDFs are attached to a new chat.
- **VryxCode**: the sessions list, a session's live work feed, the message box with Effort (or the model), Ask / Auto / Plan and where it runs, "Allow this?"
  and multiple-choice questions, typing to it while it works (with the "works like Claude Code" switch), screenshots, the /commands
  (/plan, /ask, /auto, /new, /memory, /permissions, /fixci, and the project's own), and new projects.
- **Everything else from the website opens inside the app, already signed in:** Settings, Admin (owners and admins), and the full website for skills,
  teacher mode, connected apps, your files, sharing, the VryxCode editor, preview and file browser. Links to other sites open in the phone's browser.

- **The rest of the website's chat:** the chat's ⋯ menu (Share a link, Save as PDF / Word / Markdown, Archive, Delete), Archived chats,
  Private chat (never saved), Move to a folder (the list groups pinned chats, folders, days and skills as the website does), 👍 Right,
  the answer's ⋯ (Save as, Ask a stronger model, Branch, Report), what an answer looked up, Memory updated notes, the owner's timing line,
  the thinking words with their clock, the error card, following a reply that kept going while the app was away, Jump to the newest.
- **Usage and memory:** tap the usage line for the tank, when it is full again, this week and messages left by model; the memory
  (context window) ring shows from the first message (an estimate until a reply measures it) with used, free and when it summarizes.
- **Light or dark** (the moon in the top bar), **Your day** from connected apps, **email-code sign-in** when the server sends mail,
  and a **fingerprint lock** (the switch by your name in the menu; it asks again after a minute away).

**Not yet:** push notifications (needs a Firebase project), passkeys (needs the server's domain set up for the app), the on-phone model.

**Built on GitHub:** every pull request that changes `android/` is compiled and its tests run (`.github/workflows/android.yml`); the debug `.apk`
is under the run's *Artifacts* (emvryx-android-debug), so it can be installed without Android Studio.

## Build and run (Windows)
Android Studio supplies the SDK and Java. Open this `android/` folder in Android Studio and press Run. Or from a terminal:
```
cd android
set JAVA_HOME=C:\Program Files\Android\Android Studio\jbr
gradlew.bat testDebugUnitTest assembleDebug
adb install -r app\build\outputs\apk\debug\app-debug.apk
```
The debug app is called `app.emvryx.android.debug`, so it installs next to a release build.

## Trying it against your PC
- **Emulator:** the debug build starts at `http://10.0.2.2:8000`, which is the PC's own `python app_server.py`.
- **Your phone on the same Wi-Fi:** run the server with `--host 0.0.0.0`, then on the sign-in screen tap *Server* and enter `http://<your PC's address>:8000`.
- **Anywhere:** `https://chat.emvryx.app` (the default for release builds). Release builds only use https.

## Where things are
| File | What it does |
|---|---|
| `data/ApiClient.kt` | Every server call, plus the streamed reply (`POST /api/chats/{id}/send`) |
| `data/Sse.kt` | Turns the server-sent events into thinking / loading / piece / done / error |
| `data/SessionStore.kt` | The server address and the `emvryx_session` cookie, kept in encrypted storage |
| `ui/AppViewModel.kt` | Which screen is showing, sign-in, chats and sending |
| `ui/*Screen.kt` | Sign-in, off, chat, VryxCode (`CodeScreen.kt`) and the in-app website pages (`WebScreen.kt`) |
| `ui/ChatExtras.kt` | Pictures and files, the memory ring, Regenerate options, Report and Edit |
| `ui/CodeViewModel.kt`, `data/Code.kt` | VryxCode: sessions, the polled work feed, questions, messages while it works |
| `src/test/` | Unit tests for the event parser, the reply formatting, and server addresses |
