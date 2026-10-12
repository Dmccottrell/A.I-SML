# The Emvryx API: use Emvryx inside your own apps

Your own apps (household finance, charting practice, anything) can ask Emvryx a question and get an answer back. Each app has **its own key**, plan, instructions and speed limit, so you can switch one off or replace its key without touching the others. **Nothing an app asks is saved**, and by default nothing leaves your PC (no web search).

## Set it up (2 minutes)
1. Open Emvryx > account menu > **Admin** > **Apps**.
2. **Add an app**: a short name (`finance`), a display name, instructions for what it is for (see the examples below), a plan, and leave "May look things up" on **None** for anything about money or people.
3. Press **Make the app and its key**. The key (it starts with `emvx_`) is shown **once**: copy it into the app's secret settings. If you lose it, press **New key**.
4. Test it with the command the screen gives you.

## The one call
```
POST https://chat.emvryx.app/api/v1/ask
Authorization: Bearer emvx_...
Content-Type: application/json

{"question": "Can we afford a holiday this month?",
 "facts": ["Income this month: $4,800", "Spent so far: $3,950", "Planned bills still to come: $620"],
 "instructions": "Answer in two short sentences.",
 "model": "flare",            (optional: flare, equinox, solstice, apogee, or an id like flare-2.5; the app's default otherwise)
 "effort": "balanced",        (optional: auto, quick, balanced, deep)
 "stream": false}             (optional: true streams the answer as server-sent events)
```
Answer:
```
{"answer": "...", "model": "Flare 2.5", "model_id": "flare-2.5", "effort": "balanced", "complete": true,
 "usage": {"left_pct": 97, "messages_left": 190}}
```
- `facts` are the numbers and statements your app gives the model to use. **Your app's own code adds up the totals; the model only explains them in plain words.** The model is told to quote the numbers exactly and never to calculate. A model should never do the arithmetic.
- `instructions` apply to this one call, on top of the app's standing instructions set in Admin.
- Other calls: `GET /api/v1/models` (what this app may use) and the public `GET /api/status` (`{"up": true, "resting": false, ...}`), so your app can show "assistant offline" kindly before it asks.

## Errors (always `{"code", "message", "action"}`)
| Status | code | Meaning |
|---|---|---|
| 401 | `bad_key` | The key is wrong or was replaced |
| 403 | `app_off` | You switched this app off |
| 403 | `model_not_in_plan` | The app's plan does not include that model |
| 429 | `rate_limit` | Too many questions this minute (the app's limit, Admin > Apps); wait `retry_after` seconds |
| 429 | `tank_empty`, `week_limit` | The app used its plan's allowance; it refills (see Usage) |
| 503 | `gaming` | Gaming mode is on: Emvryx is resting while the PC is used for something else |
| 502 / 504 | `model_error`, `timeout` | The model failed or took too long |
If the PC is off or the tunnel is down there is no answer at all: treat a connection error the same way and show a friendly "assistant offline".

## Keep the key safe
- The key is a **secret**. It goes only in the app's **server side** (a Supabase edge function secret, a Vercel environment variable, a `.env` file that is not in git). **Never** in code that runs in a browser or phone app: anyone could read it. Browsers are refused by design.
- An app key opens only this API: it cannot sign in, open chats, or read anyone's data.
- Rotate it (Admin > Apps > New key) if it might have leaked. Keys start with `emvx_` so leaks are easy to spot in logs and repositories.
- The whole thing runs on your PC through your tunnel: the PC must be on, and Gaming mode pauses it.

## Examples
**Python (server side)**, with `examples/emvryx_client.py` (one file, no packages):
```python
from emvryx_client import Emvryx, EmvryxOffline
ai = Emvryx("https://chat.emvryx.app", os.environ["EMVRYX_KEY"])
try:
    print(ai.ask("Explain this month in two sentences.", facts=["Income: $4,800", "Spent: $3,950"])["answer"])
except EmvryxOffline as e:
    print("Assistant offline:", e)
```
**A Supabase edge function** (Deno; set the key with `supabase secrets set EMVRYX_KEY=emvx_...`):
```ts
Deno.serve(async (req) => {
  const { question, facts } = await req.json();        // check the caller is signed in to YOUR app first
  const r = await fetch("https://chat.emvryx.app/api/v1/ask", {
    method: "POST",
    headers: { "Authorization": `Bearer ${Deno.env.get("EMVRYX_KEY")}`, "Content-Type": "application/json" },
    body: JSON.stringify({ question, facts }),
  });
  const data = await r.json();
  return new Response(JSON.stringify(r.ok ? { answer: data.answer } : { offline: true, message: data.message }), { headers: { "Content-Type": "application/json" } });
});
```
**Instructions that work well**
- Household finance: "You are a calm budgeting helper inside a household finance app. Explain the figures you are given in plain words, one or two short paragraphs. Never calculate or guess a number; if a figure is missing, say what is needed. This is not financial advice."
- Charting practice: "You coach someone practising reading charts. Explain what a pattern means and ask one short quiz question. Never predict prices or give trading advice."

## Limits to say out loud
The PC must be on. Answers can be wrong, so anything important is checked. Nothing here is financial advice. Small models are weak at arithmetic: that is why your app adds the numbers up.
