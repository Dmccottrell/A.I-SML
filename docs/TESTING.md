# Testing Emvryx with real people: the checklist

For the owner and the first testers. Plain words. Report anything odd with **Settings > About > Send feedback** (switch `send_feedback`; admins first).

## Before you invite anyone (the owner, 10 minutes)
- [ ] The PC is on, `chat.emvryx.app` opens on your phone over mobile data (not Wi-Fi at home).
- [ ] Settings > Data controls: a backup was made today; Admin > Backups shows a recent one.
- [ ] Admin > Previews: only the switches you want testers to see are on for "Admins" or "Everyone". Make each tester an admin only if they should see the new things.
- [ ] Make each tester their own account (Admin > People), never share yours.
- [ ] Check Admin > Crashes is empty, or that the entries are known.

## What each tester tries (15 minutes each, in any order)
**Chat**
- [ ] Sign in, ask three ordinary questions, one long answer, one about today's news or weather.
- [ ] Stop an answer half way; regenerate one; edit your own message.
- [ ] Attach a picture or a document and ask about it.
- [ ] Start a Private chat: it must not appear in the list afterwards.
- [ ] Turn on dark and light mode; make the text bigger in the phone's settings; nothing should be cut off.

**VryxCode**
- [ ] Ask for a small program ("a bill splitter with tip"). Allow the steps. Open Preview.
- [ ] Say something while it works; press Stop; archive, restore and delete a session.
- [ ] Download what it built (website zip, or the app for Android/Windows if offered).

**Offline (Android)**
- [ ] Download the phone model on Wi-Fi, then turn on Airplane mode and chat.
- [ ] Turn Airplane mode off: chats written offline appear on the PC and website.
- [ ] Close the app while the model is downloading: the download carries on.

**The phone itself**
- [ ] Install the new app over the old one: chats and sign-in are still there.
- [ ] Battery saver on: chat still works; background sync may be delayed (that is fine).
- [ ] A low-memory phone: the app must not crash when the phone model loads. If it does, send feedback with the phone's name.

**Safety**
- [ ] Someone who is not a tester cannot open `chat.emvryx.app` without an account.
- [ ] Sign out; the back button must not show your chats.
- [ ] Delete a test account from Settings: its chats are gone.

## What to write in a report
What you did, what you expected, what happened, and the phone/computer and app (website, Android, Windows). A screenshot helps.

## The owner reads reports in
Settings > Answer reports (also shows app feedback): mark each one handled when fixed. Anything that crashes goes to Admin > Crashes.

## Ready to widen? (all must be true)
- [ ] A week of testers with no crash that loses chats or files.
- [ ] Every "bug" report is handled or consciously left.
- [ ] A backup restore was tried once (`python tools/backup_data.py --restore ...`).
- [ ] The privacy and terms pages say what the app does today (read them once).

## Tools for the owner (free, on the PC)
- **Restore drill** (once before inviting testers, then monthly): `python tools/restore_drill.py --out backups` unpacks the newest backup into a throw-away folder,
  checks every database and says how old the backup is. It never touches the live data.
- **Load test** (to learn how many people the PC can serve): set `EMVRYX_KEY` to a *test* account's key, then
  `python tools/load_test.py --url https://chat.emvryx.app --users 3 --rounds 2 --scenario pages`, and again with `--scenario chat` (that one uses the model).
  Raise `--users` slowly. It prints typical and slow waits and how many requests failed.

## What Claude checked in the first pass (and what is left for a person)
Done and kept as automatic tests:
- Every API address in the code answers "not signed in" without a sign-in (only the three public sign-in addresses are open), and a normal person
  cannot reach any admin address (`tests/test_route_access.py`; new routes are found by themselves).
- File addresses cannot be tricked into serving the server's own source files.
- The page carries the protective headers (no framing, strict script policy, no referrer). One real bug was found and fixed: the page blocked its own
  microphone, so voice typing could not start in Chrome (`tests/test_voice_permission.py`).
- Text contrast in the new design: the only misses were the muted grey of the small buttons under replies (4.2:1); it is now #7C7C86 (4.7:1 on black).
- Backups: restoring is tested, and the drill above checks a real backup.

Still for a person (not something code can judge): a screen-reader walk through sign-in, chat and VryxCode; checking on a real phone with the largest
text size; an outside penetration test before many strangers sign up (that one costs money).
