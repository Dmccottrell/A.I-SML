# Connected apps (free, read-only)

**Menu > Settings > Connected apps > See all apps.** Connect an app once, then ask in any chat: "what is on my calendar tomorrow?", "search my Notion for the trip plan", "what tasks do I have today?". Everything is **read-only**: Emvryx never sends, posts, edits or deletes in any of them.

## How it works
- You paste what the service gives you (a token, a private link, or an app password). It is checked with one harmless request, then kept **encrypted** on the server (`secret_box.py`, file mode 600). It is never shown again, never given to the model, and deleted the moment you disconnect.
- A chat only looks in an app when the question is clearly about it: the app is named ("in Notion", "my Slack") or a topic word comes with "my" ("my calendar", "my tasks", "my email"). Ordinary questions ("what is a calendar year") never touch your apps.
- The few matching items (at most 6, about 1,100 letters) go to the model as notes; the reply shows "Looked in your Calendar."
- **Private chats never use connected apps.** Settings > Connected apps has a switch to turn them off for chats.
- Each app keeps a short log of what was read ("read for 'trip plan'"), shown in its box. Results are cached for a minute.
- A link you type (calendar, news feeds) is only fetched if it is a public https address: never a private-network address, and redirects are checked the same way. Jira only accepts `*.atlassian.net`. Home Assistant (an address on your own network) can only be connected by the owner.

## The apps (21)
| Group | App | What you paste | Where to get it |
|---|---|---|---|
| Everyday | Calendar (Google, Apple, Outlook) | private iCal link | Google Calendar > Settings > your calendar > Integrate > *Secret address in iCal format* |
| Everyday | Email (Gmail, Outlook, iCloud, Yahoo) | email + **app password** | Account security > 2-Step > App passwords. Opened read-only; it cannot delete or send |
| Everyday | News feeds (RSS/Atom) | up to 5 feed links | the site's RSS link |
| Everyday | Todoist | API token | Settings > Integrations > Developer |
| Everyday | Raindrop.io | test token | Settings > Integrations > For Developers |
| Everyday | Readwise | access token | readwise.io/access_token |
| Everyday | Home Assistant (owner only) | address + long-lived token | Profile > Security |
| Work | Notion | integration secret | notion.so/my-integrations, then share pages with it |
| Work | Slack | user token (`xoxp`, can search) or bot token (`xoxb`, reads channels it joined) | api.slack.com/apps |
| Work | Linear | personal API key | Settings > Account > Security & access |
| Work | Asana | personal access token | Settings > Apps |
| Work | ClickUp | API token | Settings > Apps |
| Work | Trello | API key + token | trello.com/power-ups/admin |
| Work | Jira | site + email + API token | id.atlassian.com > Security > API tokens |
| Work | Dropbox | access token | dropbox.com/developers/apps (these expire after a few hours) |
| Builders | GitHub | token or sign-in | see the GitHub box (VryxCode can also push) |
| Builders | GitLab | token with `read_api` | Preferences > Access tokens |
| Builders | Hugging Face | read token | huggingface.co/settings/tokens |
| Builders | Vercel | token | vercel.com/account/tokens |
| Builders | Netlify | personal access token | app.netlify.com/user/applications |
| Builders | Cloudflare | token with *Zone: Read* | dash.cloudflare.com/profile/api-tokens |
| Builders | Supabase | access token | supabase.com/dashboard/account/tokens |

Google Drive stays "Coming soon": Google only allows it through its own sign-in screen, which needs a Google client id that only the owner can create.

## What is tested, and what is not
`tests/test_app_links.py` runs every app against stand-ins shaped like each service's documented replies (including repeating calendar events, time zones, RSS and Atom, IMAP read-only, Jira host checks, the private-address guard, encryption at rest, caching, and that a private chat or the off switch means no lookup). **None of it has been run against the live services**: if one changed its API, that app says so plainly ("answered with an error") and the others keep working. Tell me which one and I will fix it.

Email text and web pages can contain instructions ("ignore the rules"). They only reach the model as quoted notes, and the chat model has no tools that change anything, so the worst case is a wrong answer.
