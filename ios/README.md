# Emvryx for iPhone

Version 1: chat.emvryx.app inside a real iPhone app (SwiftUI + WKWebView). Version 2, stage 1 (feature flag `ios_native`, admins first):
the app's own sign-in and chat, like the Android app. The setup steps on the Mac are in [docs/IOS.md](../docs/IOS.md).

## The native screens (ios_native)
Behind the server switch `ios_native` (admins first; Admin > Previews). Switched off, the app is the website as in version 1 after its own sign-in.

**Stage 1: sign-in and chat** (`Native/SignInView.swift`, `ChatView.swift`; ports of `SignInScreen.kt`, `ChatScreen.kt`, classic look)
- Sign-in with a password, an access key, a code by email (when the server offers it) and the two-step code. The session is the website's own
  cookie, kept in the Keychain (this phone only, never in a backup) and shared with the website pages inside the app.
- Bubbles, the reply written in as it streams (`Sse.swift`, the same cases as Android's `SseParserTest`), code blocks, Stop, the model and effort
  menus, the usage line; each model's own colours and logo (`Theme.swift`) and the violet look.

**Stage 2: everything the website chat has** (`Messages.swift`, `ChatSheets.swift`, `Sidebar.swift`, `Attach.swift`, `Voice.swift`)
- Regenerate (with its options), Continue, edit and ask again, Copy, "Right answer", Report, Branch, Ask a stronger model, Read aloud,
  Save as PDF / Word / Markdown (made on the server, handed to the share sheet), share a link, the memory ring with Compact now, the usage sheet.
- Chats: pin, archive and Put back, delete (asks first), search inside messages, Private chat, grouped by day.
- Pictures and files from Photos, the camera or Files (pictures are shrunk and saved as JPEG; HEIC is not read by the models), thumbnails in the
  box and the thread, and the server's reasons when a file is skipped.
- Voice: hold the mic to talk (the iPhone's speech recognition); the first time iOS asks for the microphone and speech recognition.

**Stage 3: the app's own Memory, Documents, Skills and Settings** (`Panels.swift`, port of `NativeScreens.kt`); "More settings", Admin and
Connected apps open the website's pages inside the app, signed in.

**Stage 4: VryxCode** (`Code.swift`, `CodeStore.swift`, `CodeViews.swift`): the home with the starters and the sessions (archive, delete,
archived), a session's live feed (your task, the agent's steps, results, notes, the end card), permission and multiple-choice questions,
steering it while it works, Stop, Ask / Auto / Plan, the effort or model picker, where it runs, and a new project named from the idea.

**Stage 5: the iPhone's own**
- **App lock**: Face ID (or the passcode) when the app opens and when you come back to it; the app is not drawn at all while locked.
- **Share to Emvryx**: text or a link shared from another app opens Emvryx with the words in the box of a new chat (a share extension and
  `emvryx://ask?text=…`; a link only fills the box, it never sends).
- **Siri Shortcut "Ask Emvryx"** (App Intents): asks for the question, opens the app and sends it in a new chat.

### What is not done, and what is not proven
- **Not built**: the model running on the phone (it needs a third-party library and a download of about 2 GB, so it waits for a yes);
  notifications (Apple's paid account); Google sign-in (Google refuses it inside web views) and passkeys (the paid account);
  light mode and the "modern" / Design 2027 looks (the app is the classic dark look, with the violet look); from Android's VryxCode: restore,
  the plan box, review lines, Preview, servers, GitHub, Publish, fix CI, slash commands, rules, memory, pictures and documents to the agent.
- **Seen working in the simulator**: sign-in, sending and streaming, every chat action above, photo upload, Memory / Documents / Skills / Settings,
  VryxCode's home, sessions and feed against the demo server, the lock with Face ID, and a link from outside.
- **Only unit-tested, never seen with a real agent**: VryxCode's steps, permission questions, choices, steering and Stop (the demo server has no
  model; a scripted server drives them in `CodeStoreTests`).
- **Not tried at all**: a real iPhone; hearing words through the microphone (the simulator has none: it says so instead of crashing); the share
  sheet's Emvryx item and Siri's own phrase (the link and the intent are tested, the system's menus are not); email-code and two-step sign-in.

## Same look as Android and the website
- **Icon**: the website's mark (`web/icon.svg`) on `#07080D`, the logo grid at 70% of the icon and centred, the same proportions as the website's
  iPhone icon (`web/apple-touch-icon.png`) and `web/icon-maskable-512.png`. It is drawn at 1024 px rather than stretched from 512 px.
- **Off screen**: `Emvryx/OffScreen.swift` copies `android/.../ui/OffScreen.kt` exactly: the same logo drawing, amber glow, Sora and DM Sans fonts
  (the font files and their licences come from `android/`), sizes, colours, 12 pt button corners and spacing. Points on iPhone equal dp and sp on Android.
- Everything else is the website itself, so it already matches.

## Build and run
```
cd ios
xcodegen generate
open Emvryx.xcodeproj
```
`Emvryx.xcodeproj` is made from `project.yml` and is not saved in git, so run `xcodegen generate` after every pull. Choosing your Team in
Signing & Capabilities has to be done again after that.

Tests (about 50 in `EmvryxTests` and `EmvryxUITests`):
```
xcodebuild test -project Emvryx.xcodeproj -scheme Emvryx -destination 'platform=iOS Simulator,name=iPhone 15' CODE_SIGN_IDENTITY=-
```
(`CODE_SIGN_IDENTITY=-` signs it for the simulator: an unsigned app cannot use the Keychain, so it would never stay signed in.)

The tests that drive a signed-in app need an Emvryx server and skip without one. They sign in with the key, start from a clean test account (no
chats, files, memory or VryxCode sessions) and switch ios_native on the test server themselves. `OutsideUITests` also needs the harness
(`TEST_RUNNER_EMVRYX_TEST_OUTSIDE=1`, then `xcrun simctl openurl booted "emvryx://ask?text=Hello%20from%20a%20link"` for the link, and
`xcrun simctl spawn booted notifyutil -p com.apple.BiometricKit_Sim.pearl.match` sent every few seconds for Face ID, after
`notifyutil -s com.apple.BiometricKit.enrollmentChanged 1 && notifyutil -p com.apple.BiometricKit.enrollmentChanged`). A debug build can be pointed at a local server; App Store and TestFlight builds always
use chat.emvryx.app:
```
python app_server.py --port 8765 --data /tmp/emvryx-ios-test          # demo mode, in its own folder (from the project folder)
python app_server.py --port 8765 --data /tmp/emvryx-ios-test --add-user iostest pro
python app_server.py --port 8765 --data /tmp/emvryx-ios-test --make-admin iostest --plan mega   # the voice button is for admins at first
xcrun simctl addmedia booted <a picture with words in it>             # demo mode only keeps pictures it can read
TEST_RUNNER_EMVRYX_TEST_SERVER=http://127.0.0.1:8765 TEST_RUNNER_EMVRYX_TEST_KEY=<the key --add-user printed> xcodebuild test ...
```
Restart the server after `--make-admin`. Keep the key out of chats and files (`--rotate-key iostest` makes a new one).

## Still missing
Google sign-in (Google refuses it inside apps' web views), passkeys (Apple's paid account, an "associated domain") and downloading files the AI
made. See "What is not done" above.
