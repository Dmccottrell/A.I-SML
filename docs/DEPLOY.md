# Deploying Emvryx: Vercel, Supabase and where the app runs

Short version: **the website goes on Vercel (free). The chat app does not go on Vercel; it runs on a computer or server you
control. You do not need Supabase yet.** (Written Oct 2026. Prices and plan rules change: check each site's current page.)

## What runs where
| Piece | What it is | Where it goes | Why |
|---|---|---|---|
| **Website** (`site/`: Home, Models, Plans, How usage works, About) | Plain static HTML pages made by `tools/build_site.py` from the designs | **Vercel** | Static pages are exactly what Vercel is for; free to start; every merge to `main` redeploys |
| **Chat app** (`app_server.py` + `web/`) | A Python server that keeps chats in files (SQLite), counts usage and starts `llama-server` for the model | **Your PC** now; a **rented server** later | It is a long-running process that needs disk, memory and (for big models) a GPU. Vercel runs short, stateless functions with no GPU and no permanent disk, so it can't hold this |
| **Models** (`.gguf` files) | The trained models | Next to the app server | Too big and too slow for Vercel |
| **Accounts, payments, cross-device sync** | Not built yet | **Supabase** (later) | See "Do we need Supabase?" |

## Do we need Supabase?
**Not now.** The app already stores its own data (chats, usage, plans, keys) in files on the server, which is right for a small
private test group where you hand out links with `--add-user`.

Add Supabase when you go **public**, for things the app server should not do itself:
- **Sign-in** (email or Google) instead of hand-made keys: Supabase Auth.
- **Plans and payments**: a database table of who has Free / Pro / Mega, and a Stripe link.
- **Usage and chats in one place** so they survive moving the app server, and sync between phone and PC: Postgres.
- **Connected apps** (Google, Slack, GitHub...): safely storing each person's access tokens, encrypted.

Even then, the models keep running on your own server; Supabase only holds the data. When that day comes the work is: make a
Supabase project, move `UsageStore` and `ChatStore` from SQLite to Postgres, and put Supabase sign-in in front of the page.

## A. Put the website on Vercel (about 10 minutes, free)
You already have a Vercel account (it has three other projects). The site is already built and committed in `site/`, so Vercel
needs **no build step**.

1. On GitHub, make sure `main` has the latest (it does after the merge).
2. Go to **vercel.com/new**. If asked, **install the Vercel GitHub app** and give it access to the repository
   `Dmccottrell/A.I-SML` (only that one is enough).
3. **Import** `A.I-SML`.
4. On the settings screen:
   - **Project Name:** `emvryx`
   - **Framework Preset:** `Other`
   - **Root Directory:** click *Edit* and choose **`site`**
   - **Build Command, Install Command, Output Directory:** leave **empty** (do not override)
5. Click **Deploy**. In about a minute you get `https://emvryx-<something>.vercel.app`. Open it: the five pages and the dark/light
   button should work.
6. **Production Branch** is `main` by default: every merge to `main` redeploys. Every pull request gets its own preview link.
7. **A domain (later):** Project > Settings > Domains > add `emvryx.ai` (or whichever you buy; check it is free first, see
   `docs/APP.md`). Vercel shows the DNS records to add at your registrar.

If the designs change: `python tools/build_site.py`, commit `site/`, merge to `main`. Vercel does the rest.

Plan note: Vercel's free **Hobby** plan is for personal, non-commercial use. The moment you charge for Pro or Mega, move the site
to Vercel's paid plan (or another host). Check their current terms.

## B. Run the chat app (not on Vercel)
**Today, on your PC** (this is what you already do):
```powershell
cd C:\Users\Darry\Projects\a.i-sml
git pull origin main
python app_server.py --llama-bin "$HOME\Downloads\llama-b11192-bin-win-cpu-x64\llama-server.exe"
python app_server.py --add-user sam pro          # a tester's private link
```

**Let testers reach it from the internet, free: a Cloudflare tunnel.** The app stays on your PC and only listens on this
computer; the tunnel gives it a public link.
1. Install `cloudflared` (Cloudflare's tunnel program) and run: `cloudflared tunnel --url http://localhost:8000`
2. It prints a `https://....trycloudflare.com` address. Add the tester's key: `https://....trycloudflare.com/?key=<their key>`.
3. That address changes each time you restart it (fine for testing). A fixed address needs a (free) Cloudflare account and a domain.
4. Never post keys publicly. The PC must be on while they chat. Don't run it while a GPU training run needs the machine.

**A fixed address, `chat.emvryx.app` (set up Oct 2026).** A named Cloudflare tunnel (`emvryx-chat`, installed on the PC as the `cloudflared` Windows service) sends `chat.emvryx.app` to the chat app on this PC; the website's buttons point at it.
- In Cloudflare (Zero Trust, Networks, Tunnels, `emvryx-chat`, Published application routes): subdomain `chat`, domain `emvryx.app`, type **HTTP**, URL **`127.0.0.1:PORT`** (the port the app runs on). Use `127.0.0.1`, not `localhost`: on Windows `localhost` can resolve to the newer address type while the app listens on the older one, and the tunnel then shows **502 Bad gateway**.
- Check the app answers on this PC (`curl.exe -s -o NUL -w "%{http_code}" http://127.0.0.1:PORT/` prints 200), and `Get-Service cloudflared` says Running.
- Only one copy of the app may run per port: on Windows an old copy can keep answering (a picker that shows old models means an old copy; use a new `--port`).
- Give people their own key (`python app_server.py --add-user NAME mega`), never the owner key, and replace any key that has been seen (`--rotate-key NAME`, then restart the app). The PC must be on, awake and running the app. Cloudflare Access (a login before the page loads) is a free extra layer worth adding.

**Start by itself at boot (Windows).** The tunnel is already a Windows service. To make the app start on its own too, restart if it stops, and keep the PC awake while plugged in, run this once in PowerShell **as Administrator** (use your own paths; the `-Llama` one should be the llama-server with GPU support):
```powershell
cd C:\Users\Darry\Projects\a.i-sml
powershell -ExecutionPolicy Bypass -File windows\install_autostart.ps1 -Llama "C:\path\to\llama-server.exe"   # replace the path with your real llama-server.exe; add -Port 8001 -CodeSandbox if that is how you run it
Start-ScheduledTask -TaskName "Emvryx App"
```
It writes `.emvryx\start_emvryx.cmd` (log: `.emvryx\server.log`), registers the task "Emvryx App", turns off sleep/hibernate on mains power and sets the tunnel service to start and restart automatically. Undo with `-Remove`. Limits: the app starts when you **sign in**, so after a restart the PC waits at the sign-in screen (turning on automatic sign-in fixes that but lets anyone who restarts the PC use it: only do it if the PC is somewhere safe and use BitLocker/a screen lock). Stop the old copy before starting a new one (one app per port). Not tested on a real Windows PC yet: if a step fails, send me the message.

**Search keys and weather (optional, all free tiers; limits change, check them).** Without any key, "lookup" uses Wikipedia only, so live questions (news, scores, weather) get "I don't know". Set a key once (a normal PowerShell window, then restart the whole app so it reads it): `setx TAVILY_API_KEY "..."` (Tavily, built for AI apps), `setx BRAVE_API_KEY "..."` (Brave Search), or `setx GEMINI_API_KEY "..."` (Google Gemini with Google Search; your question goes to Google and free-tier content may be used to improve its products, so it is the last choice). The app uses the first key found in that order. Never paste a key into chat. Claude's and ChatGPT's APIs are paid (no free tier), so they are not included. **The simplest way that always works:** put the keys in a small text file the app reads when it starts, `.emvryx\keys.env` (one `NAME=value` per line, for example `TAVILY_API_KEY=your-key`; the names are TAVILY_API_KEY, BRAVE_API_KEY, GEMINI_API_KEY, RAWG_API_KEY, TMDB_API_KEY, USDA_API_KEY, FRED_API_KEY, WOLFRAM_APPID, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and the mail settings EMVRYX_SMTP_HOST, EMVRYX_SMTP_PORT, EMVRYX_SMTP_USER, EMVRYX_SMTP_PASS and EMVRYX_MAIL_FROM). It never goes to GitHub (`.emvryx` is ignored), the app prints only the key names it loaded, and a key set with `setx` still wins. A scheduled task does not always see a key set with `setx` until you sign out and back in, which is why this file exists. **Weather** needs no key: Open-Meteo gives a real forecast ("weather in Paris", or set a default place with `--weather-place "Austin, Texas"` / the installer's `-WeatherPlace`). Open-Meteo's free service is for **non-commercial** use: if Emvryx ever charges, switch to their commercial plan or another weather source. Only the place name is sent to them. The Tavily, Brave and Gemini sources have not been run against the live services yet; the first real question will show.

**Later, a rented server** (when the PC being on stops being OK): a small cloud server (a few dollars a month) runs
`app_server.py` plus `llama-server` for small models (Ember, Flare); bigger models (Equinox and up) need a GPU server, which is the
main cost. The website's "Open Emvryx" button then points at that address.

## C. Connected apps
Two different things are called "connected apps":

**1. Apps connected to your Claude account (what helps you build this).** In this session you have GitHub, Vercel, Supabase,
Gmail and Indeed connected.
- **GitHub:** I make pull requests and merge to `main` for you.
- **Vercel:** I can read your projects, deployments and logs, and (only when you say so) create the `emvryx` project from the repo,
  add a domain, or redeploy. Buying a domain always needs your explicit approval.
- **Supabase:** not needed yet. It is there for when you go public.
- Give Vercel access to the repo first (step A2): the connector can only use what your account can already see.

**2. "Connected apps" inside Emvryx (for the people who use it).** A new screen, Menu > Connected apps, lists the apps Emvryx
will be able to work with (Google Calendar, Gmail, Google Drive, Notion, Slack, GitHub, Vercel, Supabase). **Nothing is
connected yet**: the list and the rules are built (`app/connected_apps.py`), and every app says "Coming soon". The rules: off until the
person connects it with their own sign-in; read-only first; anything that sends, posts, edits or deletes needs a tap on Confirm
every time; Emvryx only sees what an app returns for the question asked; disconnecting deletes the access at once; on-device models
never send an app's data anywhere. Real connections need sign-in with each service, so they come with accounts (Supabase).

## When you are short of credits
- The site on Vercel (steps A1 to A6) needs nothing from me: it is clicks on vercel.com.
- Running the app and adding testers (section B) needs nothing from me either.
- Ask me for the things that need code: a domain hook-up, Supabase sign-in, real connected apps, a rented-server setup.


## Install it on a phone (the app is a PWA)

Open your `https://chat.emvryx.app` address in the phone's browser, then: **Android (Chrome):** menu (three dots) > *Install app* (or *Add to Home screen*). **iPhone (Safari):** Share > *Add to Home Screen*. It then opens full screen with the Emvryx icon, like an app. It needs https (the Cloudflare address has it); over plain `http://` on your home network the browser will only offer a shortcut, not an install. The page shell is cached so it opens instantly, but chatting needs the server (and your PC, if that is where the model runs) to be on: the API is never cached. If the icon does not update after a change, remove the app and add it again.


## Going public later: the checklist (decided Oct 2026: stay on keys for now)

Today Emvryx is for you and the people you give a key to. Opening it to anyone is a different job, because strangers can then use your computer's time, your money (cloud models) and, through VryxCode, run code and reach connected accounts. When we get there, in this order:

**1. Sign-in that is not a pasted key.** Accounts with email or Google sign-in (or Cloudflare Access in front of the tunnel as a first step), a session that can be revoked, and "remember this device" that is not the key itself. Today a key is stored in plain text in `.emvryx/users.json` (file mode 600) and is its own login: fine for a few people, not for the public. Hash anything stored, add expiry.

**2. Sign-in protections.** Rate-limit login attempts and sign-ups per address (the app has no per-address limit yet), lock out repeated failures, require a verified email, and add a way to ban an account. Use Cloudflare's rate-limiting and bot rules too.

**3. Browser protections (not built).** `Secure` on the cookie (it has HttpOnly and SameSite=Strict already), a Content-Security-Policy and HSTS, an Origin check on every POST (CSRF), and no secrets in URLs (the `?key=` link would go).

**4. VryxCode must not run on the shared machine for strangers.** The sandbox protects against a small model's mistakes, not a hostile user (see `coding/harness.py`). For the public: run each coding session in a throwaway container (Docker with gVisor or a micro-VM) with no network, hard CPU, memory, disk and time limits, a per-person quota, and a separate machine from the models. Until then, keep VryxCode to people you trust (a tier that is off by default).

**5. Connected accounts.** Replace the pasted GitHub token with GitHub's own sign-in (OAuth), encrypt tokens at rest with a server key, show a clear log, and keep pull and push confirmed every time.

**6. Capacity and cost.** The PC cannot serve strangers: use a cloud GPU with the plan limits and the owner's pause switch (both already built), per-person daily caps, a spending alarm, and a queue so a busy moment degrades politely.

**7. Data and rules.** A short privacy policy and terms (chats are saved on the server; private chats are never saved; delete-everything exists), backups, an abuse and takedown contact, a check of the Emvryx name for trademarks (not done), and the model licence credits in `NOTICE` (done) plus the "outside model" labels (done).

**8. Before the doors open.** A security review of the code (`/security-review`), a dependency audit, a test with a few outside testers on the free tier first, and monitoring of errors and unusual usage.

Start with 1, 2 and 3: they are small. 4 and 6 are the big ones and decide when it is safe to go public.


## Backups on a schedule

Windows (Task Scheduler, daily at 3 AM): Action "Start a program": `python` with arguments `tools/backup_data.py --data .emvryx --out D:\emvryx-backups --keep 14`, start in the project folder. Linux: `0 3 * * * cd /path/to/A.I-SML && python tools/backup_data.py --data .emvryx --out /backups/emvryx --keep 14`. Keep `secret.key` somewhere else (it is not in the zip): without it a restore asks people to connect GitHub again, which is fine. Test a restore once: `python tools/backup_data.py --restore <zip> --to <empty folder>`. See [SECURITY.md](SECURITY.md).

## Updating from your phone (Admin > PC > Software update)
Signed in as the **owner**, open Admin > PC > Software update and press **Check for updates**: it lists what is new on GitHub's `main`. **Update and restart** then pulls it (`git pull --ff-only`, so it only moves forward) and restarts the app by itself through a one-off Windows task (`EmvryxRestart`, deleted when it has run), which stops and starts the "Emvryx App" task. The page reloads when Emvryx is back (about 10 to 20 seconds).
It refuses, and says why, when: files on the PC were edited by hand, the PC is on another branch or has commits of its own, GitHub cannot be reached, or the newest change is not the one you were shown. It asks again if a reply or coding session is running. If `requirements.txt` changed it tells you to run `pip install -r requirements.txt` on the PC (it never installs anything itself). Each update is written to the security log. Needs `git` on the PC; the automatic restart needs the "Emvryx App" task from the install step above. Admins who are not the owner do not see it.
