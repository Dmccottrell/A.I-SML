# Emvryx for iPhone

Version 1: chat.emvryx.app inside a real iPhone app (SwiftUI + WKWebView). The setup steps on the Mac are in [docs/IOS.md](../docs/IOS.md).

## What it does
- Opens https://chat.emvryx.app full screen, inside the safe areas, with the dark `#07080D` behind the page, the status bar and the home bar.
- Pull down to reload. Swipe from the left edge to go back.
- The microphone and camera work for chat.emvryx.app only (the voice button); any other site gets no. Photo and file upload use iOS's own picker.
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

Tests (link rules, microphone and camera rules, the off screen, the user agent, the fonts):
```
xcodebuild test -project Emvryx.xcodeproj -scheme Emvryx -destination 'platform=iOS Simulator,name=iPhone 15' CODE_SIGNING_ALLOWED=NO
```

## Not in version 1 yet
- Google sign-in: Google refuses sign-in inside apps' web views. Use email, an access key or a link for now. The fix (Apple's sign-in sheet) is version 2.
- Passkeys inside the app need Apple's paid account (an "associated domain"). Downloading files the AI made is also version 2.
