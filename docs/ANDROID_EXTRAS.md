# Android extras (the phone's own features)

All of these are switches in **Admin > Previews**, on for admins first (default `"admins"`). The phone remembers the switches
(`local/NativeExtras.kt` `NativeFlags`), so they also work when the app is opened from outside or is closed.

| Switch | What it does | Where to find it |
|---|---|---|
| `android_text_menu` | Select words in any app, tap **Ask Emvryx** next to Copy: a new chat opens with them in the box (in the phone's own chats when the PC is off). | The text selection menu (sometimes under ⋮). |
| `android_quick_launch` | Long-press the icon: **New chat, Talk, VryxCode, Chats on this phone**. A home-screen widget with the same buttons. | Long-press the icon; long-press the home screen > Widgets > Emvryx. |
| `android_assistant` | **Emvryx as the phone's assistant, like Gemini or Bixby.** Hold the power or home button: a bar opens over any app. Ask by voice or typing, **Ask about this screen**, or give a command (below). Answers are read out when you asked by voice. | Settings > Apps > Default apps > **Digital assistant app** > Emvryx. For Ask about this screen also turn on **Use screenshot** there. |
| `android_reply_inline` | **Reply** in the "answer ready" notification, like a text message; the answer comes back in the same notification. | Any chat-answer notification. |
| `android_camera_scan` | **Take a photo** and **Scan a document** (Google's scanner finds, straightens and crops the page) in the + menu, and 📷 🧾 in the phone's own chats. | The + by the message box. |
| `android_background_sync` | Chats and VryxCode drafts written with the PC off go to it by themselves, even with the app closed (about every 15 minutes, only with a connection). Needs `android_offline_model` too. | Nothing to tap. |
| `android_offline_talk` | **Talk** in the phone's own chats: speak, the model on the phone answers out loud. No PC. | Chats on this phone > 🗣 Talk. |
| `android_auto_offline` | **Offline ready by itself.** A phone with the room fetches the small phone model and asks Google for its offline speech pack. Only on Wi-Fi, only a model the phone has the memory and free space for (2 GB kept spare), the smallest that fits unless one was picked in Settings. Asked once first; admins are not asked. Stop, Remove and "No thanks" stop it for good. The picture model is never fetched on its own. Needs `android_offline_model`. | A banner the first time; Settings > Answers with the PC off. |

## Voice commands (the assistant bar)

Plain rules, no model (`local/VoiceCommands.kt`): if it is not clearly a command, it goes to Emvryx as a question, so nothing surprising happens.

- "open WhatsApp" / "open the camera" / "take a photo"
- "set a timer for 10 minutes", "timer 1 hour 30 minutes"
- "set an alarm for 7:30 am", "wake me up at 6"
- "turn on the flashlight" / "torch off"
- "navigate to the airport", "directions to Tesco"
- "search for cheap flights", "play lo-fi on YouTube"
- "call 07700 900123" (puts the number in the dialler; you tap Call, it never calls by itself)
- "Wi-Fi", "Bluetooth", "battery", "sound", "display" (opens that settings page: Android does not let apps switch these by themselves)

Anything else ("what's the weather like in Paris", "write a reply to this") is a question for Emvryx: the PC answers in a chat of its own with the
model you last used; with the PC off the model on the phone answers. **Open Emvryx** opens that chat.

## How it is built (for whoever changes it)

- `assist/Assistant.kt`: `EmvryxVoiceService` + `EmvryxSessionService` + `AssistBar` (the bar, plain Android views).
- `assist/EmvryxRecognition.kt`: Android makes the assistant the phone's speech-typing service too. This one only passes the work on to the
  phone's own (Google's), so the keyboard microphone keeps working. `assist/Voice.kt` always asks the phone's own one directly.
- `assist/Asker.kt`: a question from outside the app (the bar, a notification reply), PC first, phone model when the PC is off.
- `assist/PhoneActions.kt`: carries a command out with the phone's own apps.
- `assist/Background.kt`: `SyncWorker` (WorkManager, every 15 minutes) and `ReplyReceiver` / `ReplyWorker`.
- `ui/CameraScan.kt`: the camera and the scanner.
- Tests: `VoiceCommandsTest`, `AssistantPartsTest`, `NativeExtrasTest` (on the computer) and `NativeExtrasDeviceTest` (on the CI phone).

## Offline

- Works with no signal: phone commands (open an app, timer, alarm, torch), reading answers out loud (if the phone's voice is installed), and
  questions answered by the model on the phone (needs it downloaded and `android_offline_model` on).
- Voice to words uses the phone's own speech typing. With no internet the bar asks for the offline speech first, and if the online one fails on the
  connection it tries the offline one once. That needs the offline speech pack (Settings > Google > Voice > Offline speech); without it the bar says so.
- Needs internet: navigate, search, YouTube (those apps), Ask about this screen (the picture goes to the PC).

## Limits

- The bar cannot read other apps' screens unless **Use screenshot** is on in the assistant settings. The picture goes to the PC to be looked at
  (with the PC off it says so: the phone's picture model is only in the phone's own chats).
- Samsung phones: the side key opens Bixby by default. Settings > Advanced features > Side key > Press and hold > **Digital assistant**.
- "Hey Emvryx" (a wake word, hands-free) is **not** done: it needs the microphone on all the time and Android only lets the phone's maker's
  assistant do that well. Holding the button is the way in.
- The scanner needs Google Play services (almost every Android phone has it).
- Auto offline downloads while the app is open (the download carries on where it stopped the next time it opens); there is no download
  notification yet. Google's speech pack can be asked for on Android 13 and later; older phones get the Settings page instead.
- Background sync runs when Android allows it (battery saver can delay it).

## Not done: a faster model on the phone's graphics chip (GPU)

Looked into, not switched on. The phone model runs on the processor. Speeding it up with the GPU needs llama.cpp built with Vulkan (needs
`vulkan.hpp` and the `glslc` shader compiler in the build) or OpenCL (Qualcomm phones only, needs its headers). It can only be proven on a real
phone, and on many phones the Vulkan path is slower or crashes. Next step when wanted: a separate test build with Vulkan, timed on the owner's
phone against the current one.

## Tomorrow: iOS (iPhone)

1. **Now, free:** the website already works as an app on iPhone: Safari > Share > **Add to Home Screen** (the PWA: offline page, notifications
   on iOS 16.4+).
2. **A real iPhone app** needs a Mac to build (or a cloud Mac in CI: GitHub's macOS runners are free for public repos, paid minutes for private)
   and an **Apple Developer account, $99 a year** (needs the owner's OK before anything is paid). Then TestFlight to put it on your phone.
3. **What carries over:** the server and all the features. The Android app is Kotlin; for iPhone the choices are Swift (a new app, like the
   Windows app wraps the website) or a small Swift app that wraps the website first, then native parts one by one.
4. **What iPhone does not allow:** being the phone's assistant (Siri only; Emvryx can add Siri Shortcuts: "Hey Siri, ask Emvryx"), an app
   running on its own in the background, or a downloaded app outside the App Store/TestFlight.
5. **The phone model on iPhone:** llama.cpp runs well on iPhones (Metal, the iPhone GPU), so the offline model may be faster there than on Android.
