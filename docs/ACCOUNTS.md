# Accounts, sign-in and Settings

How people get in to Emvryx, how to protect the owner account, and where each setting lives. For the security reasoning see [SECURITY.md](SECURITY.md) section 1b.

## The sign-in screen

| Way in | When it shows | Notes |
|---|---|---|
| Name (or email) + password | always | The normal way. |
| Email me a code | when the server can send mail | Only for a **verified** email. 6 digits, 10 minutes. |
| Access key or link | always | The key the owner gave you. Fine for programs, and the way the first owner sign-in works. |
| Pairing link (`/pair/...`) | when the owner makes one | One use, 15 minutes. Skips the two-step code on purpose (see below). |
| Create account | when the owner opens sign-ups | Name, email, password (plus an invite code in invite mode). |

When two-step sign-in is on, the password / key / email code is only the first step: a second screen asks for the 6-digit code (or a recovery code).

## Set up the owner account (do this once)

1. Sign in the way you do now.
2. A bar at the top says *Protect the owner account*. Tap **Do it now** (or Settings > Security).
3. **Set a password.** Not your name or email; a few words in a row is good ("correct horse battery" style).
4. **Set up two-step sign-in.** Scan the QR code from another device, or tap *Open my authenticator app* on your phone (Google Authenticator, Microsoft Authenticator, Authy, 1Password...). If it does not open, choose *enter a setup key* in the app and type the key shown. Type the 6-digit code it shows. **Save the 8 recovery codes** (Copy or Download) before pressing Done.
5. Settings > Account > **add your email**. If mail is set up on the server, verify it too.
6. Settings > Owner > **Overview** shows what is still missing on the "safe to share" checklist.

If you lose your phone and your recovery codes, on the computer that runs Emvryx:

```
python app_server.py --reset-mfa owner
```

then restart the app. (`python app_server.py --set-password owner` sets a new password at a hidden prompt.)

## Who can sign up (Settings > Owner > Sign-ups and invites)

- **Closed** (the default): nobody can make an account; you add people.
- **Invite only**: make a code (pick the plan it gives and how many people may use it); it works for 14 days. Send it privately. The sign-up screen then asks for it.
- **Open**: anyone can make a free account. Only choose this when you want strangers using your GPU.

## Invite codes and the website

The home page (emvryx.app) has a **Try Emvryx** box: a person types their invite code, taps *Create my account*, and lands on Create account in the app with the code already filled in (the code is taken out of the address bar straight away). You can also copy a ready-made **invite link** from Settings > Owner > Sign-ups and invites right after you make a code, and send that instead. It needs the sign-up rule set to **Invite only** (Closed turns every code off).

## Where each setting is

| Page | What is on it |
|---|---|
| General | theme, text size, pause before the answer |
| Chat and lookups | where facts come from (auto / Wikipedia only / always web / model only), live facts, which sources are on, chat length |
| Memory | remember things about me, see/edit memory, saved notes |
| Data controls | documents, download my data, delete all chats, privacy and terms |
| Connected apps | GitHub for VryxCode |
| Security | password, two-step sign-in, recovery codes, signed-in devices, recent security activity |
| Account | name, email (+ verify), plan and usage, sign out, delete account (not for the owner) |
| About | what Emvryx is, contact |
| Owner: Overview | safe-to-share checklist, people and plans, last-hour numbers, pause everyone, live sources |
| Owner: People | everyone, sign-in links, reset two-step, turn off / on, add a person |
| Owner: Sign-ups and invites | the sign-up rule, make and cancel invite codes |
| Owner: Security log | the latest 100 sign-ins, failures and changes |

Settings are kept per person in `.emvryx/settings.json`, so they survive a restart. The search box at the top finds a setting by its name or what it does.

## Not built yet

- Custom instructions ("always answer in short sentences"): the models were taught to answer from notes, so this needs a test before it goes in.
- Passkeys, and sign-in with Google.
- Email verification and email codes need mail set up on the server (see [DEPLOY.md](DEPLOY.md)).
