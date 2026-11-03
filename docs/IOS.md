# The iPhone app: set up your Mac and start

You have a Mac, so the iPhone app can be built. This page is everything to do on the Mac, in order, in plain words. Nothing here costs money. The one paid step (Apple's $99 a year) comes much later and only when you say yes.

## What you need
- The Mac (any recent one; if the App Store says Xcode needs a newer macOS, update macOS first: Apple menu > System Settings > General > Software Update).
- Your iPhone and its charging cable.
- An Apple ID (the one you use for the App Store is fine). The free kind is enough for now.
- About 40 GB free space and an evening for the downloads.

## Part 1: install the tools (once)
1. **Xcode**: open the App Store on the Mac, search "Xcode", press Get. It is free and big, so let it finish. Then open Xcode once, press Agree, and let it install its extra parts. Close it.
2. **Terminal**: press Cmd+Space, type Terminal, press Enter. Everything below is typed there.
3. **Apple's command line tools**: type `xcode-select --install` and press Enter. If it says they are already installed, good.
4. **Homebrew** (installs the other tools): go to https://brew.sh, copy the one line shown there, paste it in Terminal, press Enter, follow what it says (it asks for your Mac password; that is normal and stays on your Mac).
5. **The other tools**: type `brew install git gh xcodegen` and press Enter.
6. **Claude Code on the Mac**: follow the install steps at https://claude.com/claude-code and sign in with your Claude account.

## Part 2: get the project
1. In Terminal: `git clone https://github.com/Dmccottrell/A.I-SML.git`
2. Then: `cd A.I-SML`
3. Sign in to GitHub so it can save work: `gh auth login`, choose GitHub.com, HTTPS, and "Login with a web browser". Do the sign-in in the browser it opens. **Never paste a password or token into a chat or a file.**
4. Make a place for the iPhone work: `git checkout -b ios-app`

## Part 3: start Claude Code there
1. Still in the A.I-SML folder, type `claude` and press Enter. It reads the project's rules (`CLAUDE.md`) by itself.
2. Paste this as your first message:

> I want to build the Emvryx iPhone app on this Mac. Read CLAUDE.md, docs/NATIVE.md, docs/ANDROID_EXTRAS.md (the iPhone part) and docs/IOS.md. Start with the first version: a SwiftUI app in a new `ios/` folder, made with XcodeGen (`ios/project.yml`), that opens https://chat.emvryx.app in a WKWebView full screen, with: pull to refresh, a native "No connection" page with a Retry button, links to other sites opening in Safari, the microphone and camera allowed for chat.emvryx.app only (the voice button), photo and file upload working, the dark colour #07080D behind the page and the status bar, safe areas respected, and a user agent ending in "EmvryxiOS/1.0". Bundle id `app.emvryx.ios`, iOS 16.4 or newer. Build it with xcodebuild for the simulator and run it there, take a screenshot, and show me. Work on the `ios-app` branch. Keep the project's rules: tests and lint pass before every commit, plain short words to me, never ask for or print keys or passwords, no spending. Tell me each step you need me to do on the iPhone.

3. Claude Code will ask permission before it runs things. Say yes to the build and simulator steps you understand; ask it to explain any you do not.

## Part 4: see it on your own iPhone (free)
1. On the iPhone: Settings > Privacy & Security > Developer Mode > turn on, and restart when it asks.
2. Plug the iPhone into the Mac. Tap Trust on the phone if it asks.
3. In Xcode: Xcode menu > Settings > Accounts > the + button > add your Apple ID.
4. Open the project (Claude Code will tell you the file: `ios/Emvryx.xcodeproj`). Click the project name at the top left, then Signing & Capabilities, and under Team choose your name (Personal Team).
5. At the top, pick your iPhone instead of a simulator and press the Play button.
6. The first time, the iPhone says "Untrusted developer": Settings > General > VPN & Device Management > your Apple ID > Trust.
7. **A free Apple ID app stops working after 7 days.** Press Play again to refresh it. This limit goes away with the paid account.

## Part 5: the paid step, later, only if you say yes
Apple Developer Program, **$99 a year**. It gives TestFlight (friends and testers install from a link) and the App Store. Nothing is bought until you decide; Claude does not sign you up or pay.

## The plan, in order
1. **Version 1 (this page):** the website inside a real app, so Emvryx is on your home screen with its own icon.
2. **Version 2:** native pieces one at a time, the same ones the Android app has (sign-in with the keychain, notifications when a VryxCode session ends, share into Emvryx, Siri Shortcut "ask Emvryx", the phone model running offline with the iPhone's graphics chip).
3. **Version 3:** TestFlight, then the App Store (needs the paid account).
4. A GitHub Mac build (`.github/workflows/ios.yml`, free for this public project) will check on every pull request that the app still compiles.

## What iPhone does not allow (so we do not promise it)
Being the phone's main assistant (only Siri Shortcuts), running on its own in the background, and installing an app from outside TestFlight or the App Store.

## If something goes wrong
- "Xcode needs a newer macOS": update macOS, then install Xcode again.
- "No such module" or the project will not open: tell Claude Code the exact words on the screen; it can run `xcodegen generate` again.
- The iPhone does not appear in Xcode: unplug, unlock the iPhone, plug in again, tap Trust.
- The app opens but shows a blank page: check the iPhone has internet, then pull down to refresh.
