# Deploying Emvryx: Vercel, Supabase and where the app runs

Short version: **the website goes on Vercel (free). The chat app does not go on Vercel; it runs on a computer or server you
control. You do not need Supabase yet.** (Written Oct 2026. Prices and plan rules change: check each site's current page.)

## What runs where
| Piece | What it is | Where it goes | Why |
|---|---|---|---|
| **Website** (`site/`: Home, Models, Plans, How usage works, About) | Plain static HTML pages made by `build_site.py` from the designs | **Vercel** | Static pages are exactly what Vercel is for; free to start; every merge to `main` redeploys |
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

If the designs change: `python build_site.py`, commit `site/`, merge to `main`. Vercel does the rest.

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
connected yet**: the list and the rules are built (`connected_apps.py`), and every app says "Coming soon". The rules: off until the
person connects it with their own sign-in; read-only first; anything that sends, posts, edits or deletes needs a tap on Confirm
every time; Emvryx only sees what an app returns for the question asked; disconnecting deletes the access at once; on-device models
never send an app's data anywhere. Real connections need sign-in with each service, so they come with accounts (Supabase).

## When you are short of credits
- The site on Vercel (steps A1 to A6) needs nothing from me: it is clicks on vercel.com.
- Running the app and adding testers (section B) needs nothing from me either.
- Ask me for the things that need code: a domain hook-up, Supabase sign-in, real connected apps, a rented-server setup.
