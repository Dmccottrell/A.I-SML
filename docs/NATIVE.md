# Native apps (Android first, then iPhone): what is needed

Decision (Oct 2026): both apps are built natively, like the big AI apps: **Kotlin + Jetpack Compose** on Android, **Swift + SwiftUI** on iPhone. Capacitor was the cheaper road (see [ANDROID.md](ANDROID.md)); this is the polished one. Nothing here has to be built today.

## Where it is built matters
| Place | Android | iPhone |
|---|---|---|
| **This cloud session (Claude Code on the web)** | Can write Kotlin and test its plain-logic parts (Java and Gradle are here). **Cannot build the app**: Google's Android SDK download is blocked. A GitHub Actions build can compile it and I read the log. **Cannot run it** | Can write Swift. **Cannot build or run** (needs macOS). A GitHub macOS build can compile it |
| **Your Windows PC** (Claude Code on the PC) | **Everything**: Android Studio + SDK, emulator, builds, install straight to your phone over USB or Wi-Fi, logs, screenshots of the running app. Fast edit-run-fix loop | Cannot build (needs a Mac) |
| **The owner's Mac** | Not needed | **Everything** for iOS: Xcode, simulator, TestFlight upload |

**So yes: working on your own machine would help a lot**, mainly because the loop "change, run on a real device or emulator, look at it, fix" is minutes locally and many slow round trips from the cloud (push, wait for the GitHub build, install the `.apk` by hand, send me screenshots). The cloud is fine for the API document, the plain-logic modules, tests, the build pipeline and reviews. The screens, animations and "does it feel right" are where being local pays off.

## What to set up (when it is time)
**Android (on your Windows PC, about an hour):**
1. Android Studio (free) and its SDK + one emulator image (Pixel, Android 14), about 10 GB of disk.
2. Developer options and USB debugging on your phone (or Wireless debugging), so builds install straight to it.
3. Claude Code running in the repo folder on the PC, so it can run `gradlew`, start the emulator, install, read `adb logcat` and take screenshots.
4. For the Play Store later: a Google Play Console account (US$25 once) and a signing key kept off GitHub.

**iPhone (needs a Mac):**
1. The owner's Mac with Xcode (free) and Claude Code running in the repo folder there, so builds, the simulator and TestFlight uploads can be done and checked directly (a GitHub macOS build is only a backup).
2. Apple Developer Program, US$99 a year (installs beyond a few days, TestFlight testers, the App Store).
3. An iPhone for testing; the simulator covers most screens.

**Both:** the same `docs/NATIVE_API.md` contract (to write first, in the cloud: sign-in, chats, streaming replies, models, usage, VryxCode sessions, push registration) so the two apps and the server cannot drift apart.

## Server changes the native apps need (small, do in the cloud)
- A **versioned, documented API** (`/api/v1/...`) for what the apps call, with the streaming format written down.
- **Device registration and push**: the server stores a device token per signed-in device and sends one message when a VryxCode session or queued build ends (Firebase Cloud Messaging for Android, Apple's service for iPhone).
- **App-friendly sign-in**: a long-lived device session and the passkey and pairing flows working outside a browser.
- **Connected-to indicator** (your PC or on this phone) and the "Emvryx is off" state as data, not just a page.

## Status
Planned, not started. Start later, in this order: write `NATIVE_API.md` and the server pieces (cloud), then set up Android Studio and Claude Code on the Windows PC, then the Mac for iPhone. Having the Mac means both apps can be built, run and checked locally.

## Order of work
1. (cloud) `NATIVE_API.md` and the server pieces above, with tests.
2. (PC) Android skeleton, installs on your phone; sign-in; "Emvryx is off".
3. (PC) Chat with streaming, model and effort pickers, history. **First milestone: talk to your PC's models from a real app.**
4. (PC) Settings, usage, VryxCode, push, share, fingerprint lock.
5. (Mac, the owner's) iPhone app from the same API document, screen for screen.
6. Later: on-phone model (llama.cpp) for both.

## Decisions still open
Lowest Android version (suggest 10), package name (`app.emvryx.android`), Play Store listing or `.apk` only, violet or amber, ~~and whether you have or want a Mac~~ (decided: the owner has a Mac, so the iPhone app can be built and tested locally).
