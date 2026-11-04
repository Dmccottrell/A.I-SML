# Emvryx for iPhone

Version 1: chat.emvryx.app inside a real iPhone app (SwiftUI + WKWebView). Version 2, stage 1 (feature flag `ios_native`, admins first):
the app's own sign-in and chat, like the Android app. The setup steps on the Mac are in [docs/IOS.md](../docs/IOS.md).

## The native screens (ios_native), stage 1
- **Sign-in** (`Native/SignInView.swift`, a port of `android/.../ui/SignInScreen.kt`): a password, an access key, or a code by email when the
  server offers it, and the two-step code. The session is the website's own cookie, kept in the iPhone's Keychain (this phone only, never in a
  backup) and shared with the website pages inside the app, so they open signed in.
- **Chat** (`Native/ChatView.swift`, `ui/ChatScreen.kt`, classic look): the top bar, your words in a bubble on the right, the reply written in as it
  comes (server-sent events, `Native/Sse.swift`, the same cases as Android's `SseParserTest`) with the model's logo and name, code blocks, Copy,
  Stop, the model and effort menus, the usage line, and the chat list (pinned, today, yesterday, last 7 days, older; search) with the account menu.
  Each model has its own colours and logo (`Theme.swift`, from `ui/theme/Theme.kt` and `ui/Logo.kt`), and the violet look when it is on.
- **Website pages inside the app**, signed in, with a bar back to the chat: VryxCode, Skills, Documents, Memory, Settings and Admin, as the
  Android app opens the ones it has no screen for.
- Switched off, the app is the website as in version 1 (after the app's own sign-in).
- **Next stages**: photos and files, voice, Regenerate, Continue, edit and ask again, branch, pin, delete, search inside chats, the memory ring;
  native VryxCode; then the iPhone's own: Face ID lock, Share to Emvryx, Siri Shortcuts, the on-phone model. Notifications need Apple's paid account.

## What it does
- Opens https://chat.emvryx.app full screen, inside the safe areas, with the dark `#07080D` behind the page, the status bar and the home bar.
- Swipe from the left edge to go back. **Pull to refresh does not work yet:** the website fixes its page in place (`overflow: hidden` on the
  body, it scrolls inside), so iOS switches the web view's own scrolling off, and with it the pull. Android and the website have no pull to refresh.
- The microphone and camera work for chat.emvryx.app only (the voice button); any other site gets no. Photo and file upload use iOS's own picker.
- The site's messages and questions (`alert`, `confirm`, `prompt`: "Skipped 1: ...", "Delete this chat?") show as iPhone alerts,
  as Android's web view shows its own dialogs.
- Links to other sites open in Safari. Pages the site itself sends you to (sign-in) stay in the app.
- When the site cannot be reached: the Android app's off screen ("Emvryx is off right now", or "No connection" when the phone itself is offline)
  with **Try again**. It also tries again by itself when the connection comes back.
- The user agent ends in `EmvryxiOS/1.0`, so the website can tell it runs in the app.
- Bundle id `app.emvryx.ios`, iOS 16.4 or newer.

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

Tests (link rules, microphone and camera rules, speech recognition hearing the microphone, the off screen and Try again, the user agent, the fonts):
```
xcodebuild test -project Emvryx.xcodeproj -scheme Emvryx -destination 'platform=iOS Simulator,name=iPhone 15' CODE_SIGN_IDENTITY=-
```
(`CODE_SIGN_IDENTITY=-` signs it for the simulator: an unsigned app cannot use the Keychain, so it would never stay signed in.)

The tests that drive a signed-in app need an Emvryx server and skip without one: the native chat (sign in with a key, send, the reply
written in, the model menu, the chat list, Settings inside the app) and, with ios_native off, the website's voice button and photo upload.
They switch ios_native on the test server themselves. A debug build can be pointed at a local server; App Store and TestFlight builds always
use chat.emvryx.app:
```
python app_server.py --port 8765 --data /tmp/emvryx-ios-test          # demo mode, in its own folder (from the project folder)
python app_server.py --port 8765 --data /tmp/emvryx-ios-test --add-user iostest pro
python app_server.py --port 8765 --data /tmp/emvryx-ios-test --make-admin iostest --plan mega   # the voice button is for admins at first
xcrun simctl addmedia booted <a picture with words in it>             # demo mode only keeps pictures it can read
TEST_RUNNER_EMVRYX_TEST_SERVER=http://127.0.0.1:8765 TEST_RUNNER_EMVRYX_TEST_KEY=<the key --add-user printed> xcodebuild test ...
```
Restart the server after `--make-admin`. Keep the key out of chats and files (`--rotate-key iostest` makes a new one).

## Not in version 1 yet
- Google sign-in: Google refuses sign-in inside apps' web views. Use email, an access key or a link for now. The fix (Apple's sign-in sheet) is version 2.
- Passkeys inside the app need Apple's paid account (an "associated domain"). Downloading files the AI made is also version 2.
