# Emvryx for Android

The native Android app: Kotlin + Jetpack Compose (the plan is in [docs/NATIVE.md](../docs/NATIVE.md)). It is a client of your Emvryx server, the same one the website talks to, so the PC must be on.

**What works (milestone 1):**
- Sign in with a password (with the two-step code if it is on) or a key. The session is kept encrypted on the phone and shows as "The Emvryx app on Android" in the website's Devices list.
- "Emvryx is off right now" when the PC does not answer, and "Emvryx is resting" in Gaming mode, with Try again.
- Chat with streamed replies, Stop, the model picker, and the effort picker for models that have one.
- Chat history in the side drawer; new chat; sign out.
- **Bold**, `code` and code blocks in replies.

**Not yet:** pictures and files, editing or regenerating, Settings, usage, VryxCode, push notifications, share-to-Emvryx, fingerprint lock, passkey and email-code sign-in.

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
| `ui/*Screen.kt` | Sign-in, off, and chat screens |
| `src/test/` | Unit tests for the event parser, the reply formatting, and server addresses |
