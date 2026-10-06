# Emvryx security: what is built, how it works, what is left

This file is the single place for how Emvryx keeps people and their data safe. It grows as each part is built (the "Going public" checklist in [DEPLOY.md](DEPLOY.md) is the plan; this is the result). Plain rule of thumb: **today it is built for you and people you invite; the public-facing parts are being added in order, and the capacity and cost part (6) is on hold.**

## 1. Signing in (built: `auth.py`, `mailer.py`)

- **Keys are not stored.** A key is made once, shown once, and only its SHA-256 is kept in `users.json` (file mode 600). A stolen file cannot sign anyone in. An older file that kept the keys is converted the first time the server starts, and the old keys keep working.
- **The cookie is a session, not the key.** After a key, a pairing link or an email code, the browser gets `emvryx_session`: a random 256-bit token (HttpOnly, SameSite=Strict, Secure when the proxy says https). The server keeps only its hash, a coarse "where" (the first two parts of the address), and a device label like "Chrome on Android". A session lasts 90 days from last use (`session_days`).
- **Devices:** Settings > "Where you are signed in" lists every device and signs any of them out, or all the others. Rotating a key signs that person out everywhere. Turning a person off (ban) does too.
- **Pairing links** replace `?key=` links: `python app_server.py --pair owner` (or Settings > Owner > "make a sign-in link") makes `/pair/<token>`: valid 15 minutes, works once, becomes a session. The server prints one when it starts. `/?key=` still works (it turns into a session and drops the key from the address) but pairing links are the way now.
- **Email codes** (off until a mail server is set): 6 digits, 10 minutes, 5 tries, one live code per address, stored hashed. Set `EMVRYX_SMTP_HOST`, `EMVRYX_SMTP_USER`, `EMVRYX_SMTP_PASS` (and optionally `EMVRYX_SMTP_PORT`, `EMVRYX_MAIL_FROM`) before starting; the password is never written to a file. The same answer is given whether or not an address has an account, so nobody can probe who does. Owner: set a person's email when you add them. **Open signups** (anyone with a working email gets a free account) are off; to allow them, put `{"open_signups": true}` in `.emvryx/security.json`.
- Not built: sign-in with Google. It needs a Google client id and secret, which only you can create; the session code above is what it would plug into.

## 2. Guessing, lockouts, bans, the audit log (built)

- **Rate limits:** 8 wrong tries (key, pairing link or code) from one address in 10 minutes locks that address out of every key-based sign-in for the rest of the window (HTTP 429 with Retry-After), even for the right key. Asking for email codes is limited to 5 per 10 minutes per address and 3 per address of email. The address is the real caller's: behind the Cloudflare tunnel it is read from `CF-Connecting-IP`, but only when the request came from this computer (a trusted proxy), never from an outside caller.
- **Bans:** the owner can turn a person off (Settings > Owner > People): their devices are signed out at once and key, link and code sign-in are refused. The owner cannot be turned off.
- **Audit log:** the last 5,000 security events (sign-ins, failures, pairing, sign-outs, bans, key rotations, email codes) with the person, a coarse address and a short note, never a key, code or token. Owner only: Settings > People and the security log, or `GET /api/admin/audit`.

## Settings you can change (`.emvryx/security.json`, all optional)

`session_days` (90), `pair_minutes` (15), `login_fail_limit` (8), `login_fail_window` (600 seconds), `email_start_limit` (5), `email_start_window` (600), `open_signups` (false), `trusted_proxies` (`["127.0.0.1", "::1"]`; set `[]` if the app is reached directly and not through a proxy).

## Still to build (in order)

Browser protections (3), VryxCode in containers (4), encrypted connected-account tokens and GitHub sign-in (5), policies and data tools (7), a security review, dependency audit and monitoring (8). Capacity and cost (6) is on hold by decision.
