# Emvryx for iPhone

Version 1: chat.emvryx.app inside a real iPhone app (SwiftUI + WKWebView). The setup steps on the Mac are in [docs/IOS.md](../docs/IOS.md).

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
xcodebuild test -project Emvryx.xcodeproj -scheme Emvryx -destination 'platform=iOS Simulator,name=iPhone 15' CODE_SIGNING_ALLOWED=NO
```
The tests that drive a signed-in chat (holding the voice button, picking a photo and seeing it attached) need an Emvryx server
and skip without one. A debug build can be pointed at a local one; App Store and TestFlight builds always use chat.emvryx.app:
```
python app_server.py --port 8765 --data /tmp/emvryx-ios-test          # demo mode, in its own folder (from the project folder)
python app_server.py --port 8765 --data /tmp/emvryx-ios-test --add-user iostest pro
python app_server.py --port 8765 --data /tmp/emvryx-ios-test --make-admin iostest --plan mega   # the voice button is for admins at first
xcrun simctl addmedia booted <a picture with words in it>             # demo mode only keeps pictures it can read
TEST_RUNNER_EMVRYX_TEST_SERVER=http://127.0.0.1:8765 TEST_RUNNER_EMVRYX_TEST_START=<the one-time /pair/ link it printed> xcodebuild test ...
```
Restart the server after `--make-admin`. The sign-in link is needed only on the first run; the app stays signed in after that.

## Not in version 1 yet
- Google sign-in: Google refuses sign-in inside apps' web views. Use email, an access key or a link for now. The fix (Apple's sign-in sheet) is version 2.
- Passkeys inside the app need Apple's paid account (an "associated domain"). Downloading files the AI made is also version 2.
