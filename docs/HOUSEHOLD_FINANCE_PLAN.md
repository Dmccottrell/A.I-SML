# Emvryx inside PennyOtter (household finance): the plan and what is built

PennyOtter is the household finance app (repository `Dmccottrell/household-finance`: Next.js 16, Supabase, Plaid, hosted on Vercel). It already has **Penny the otter coach** ("Ask the otter"): built-in answers for most questions, and an optional AI (Claude) for the rest, fed only a plain summary of the household's figures (`lib/coach-snapshot.ts`). That is exactly where Emvryx fits.

## First feature (built on a branch, Oct 12, 2026, not merged): the coach can answer through Emvryx
- **What it does:** for people the new feature preview **"Coach answers from Emvryx"** is on for, questions the built-in answers don't cover go to Emvryx (running on your PC) instead of Claude. The household figures stay on your own computer. If the PC is off or resting (Gaming mode), the coach falls back to Claude when it is set up, or says it can't reach the AI.
- **How the numbers stay right:** the app's own code adds everything up. The snapshot is turned into short plain sentences ("Safe to spend until the next payday: $873.50 ($109.18 a day)...") and sent as `facts`; Emvryx is told to quote them exactly and never calculate. Answers carry the note "AI answer from Emvryx, running on our own computer: double-check anything important."
- **What it touches:** `lib/emvryx-ai.ts` (new), `app/api/coach/ask/route.ts`, `lib/env.ts` (`EMVRYX_URL`, `EMVRYX_KEY`), `lib/feature-flags.ts` (the preview flag), `components/coach/coach-chat.tsx` (the label), README, `.env.example`, and 8 new tests. Typecheck, lint and all 128 tests pass. It is on the branch **`claude/emvryx-coach`**; nothing on `main` or on the live site changed.
- **Off by default, three locks:** the code does nothing until `EMVRYX_URL` and `EMVRYX_KEY` are set in Vercel, and then only for people the preview is published to (Settings > Admin > Feature previews), and then only for questions the built-in answers can't handle. It adds no database change.
- **Needs from Emvryx:** the `history` field on `POST /api/v1/ask` (added Oct 12, 2026), so the coach can keep a conversation going.

## How to switch it on (when you are ready)
1. **Emvryx:** Admin > Apps > Add an app: name `finance`, plan **Pro** or **Free** (Free has Flare and Equinox), "May look things up" **None**, instructions can stay empty (the app sends Penny's own). Copy the key.
2. **Reachability:** from a computer that is not on your home network, run the test command Admin shows (`curl ... https://chat.emvryx.app/api/v1/ask`). If Cloudflare blocks it (bot protection / Access rules), allow `/api/v1/*`.
3. **Vercel:** add `EMVRYX_URL=https://chat.emvryx.app` and `EMVRYX_KEY=emvx_...` as environment variables (Production), then redeploy. (Never `NEXT_PUBLIC_`.)
4. **Merge** the branch `claude/emvryx-coach` (after you have looked at it), then in PennyOtter go to Settings > Admin > Feature previews, publish **"Coach answers from Emvryx"** to yourself first (the previews work per user), and ask the otter a question it does not know ("is it a good time to book a trip?").
5. **Try it** with the PC on, then with Gaming mode on (it should fall back or say the AI can't be reached), and decide.
6. If you do not like it: unpublish the preview. Nothing else changes.

## Next jobs worth building (one at a time, each behind a preview)
1. **Plain-English monthly summary** (a card on the Dashboard or in the weekly digest): the app's totals as facts, Emvryx writes three sentences. Needs a place for the text and a cache so it is asked once a month.
2. **Explain an odd charge** ("Best Buy $649.99, usually never"): a button on a flagged charge in Spending.
3. **Suggest a category** for an uncategorised transaction: a hint the person confirms (never automatic), using `lib/merchant-names.ts` and the existing remembered corrections.
4. **"Can we afford this?"** stays the app's own calculation (`lib/coach.ts` `canIAfford`); Emvryx would only explain the result.
Rules for all of them: the app does the arithmetic; the person confirms anything that changes data; no automatic money movement of any kind (the app's own rule); nothing sent to the web.

## Limits to say out loud
The PC must be on for Emvryx answers. A small model can still misread the facts: the label says to double-check, and the built-in answers (exact, instant) are tried first. Nothing here is financial advice.
