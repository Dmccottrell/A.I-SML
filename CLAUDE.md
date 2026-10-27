# Emvryx (A.I-SML): rules for anyone changing this project, people and AI alike

Emvryx is a small-language-model chat app with VryxCode (a coding agent), served from the owner's Windows PC (chat.emvryx.app), plus an Android app
in `android/`. The owner is not a programmer and reads on a phone: reply in short, plain words.

## Before every commit
- `python scripts/run_tests.py` and `python tools/lint.py` both pass. `python tools/guard_repo.py` is clean (CI runs all three on every pull request).
- New features go behind a feature flag in `app/flags.py`, default `"admins"`; add it to the order in `tests/test_flags.py` and, if it changes
  what existing tests see, switch it off in `tests/test_app_server.py` Base.
- A bug fix people would notice gets one plain line in `FIXES` in `app/flags.py` (product `"vryxcode"` or `None`): it goes out with the next
  release and shows under "Fixed" in What's new.
- Android (Kotlin) cannot be built here: wait for the `android` CI build before merging a change to `android/`.

## When a bug appears: the guardrails (the same ones VryxCode follows, coding/guardrails.py)
1. **Prove it first.** Reproduce the bug with a test that fails on the current code before touching the code. If the test passes on its first run,
   the bug is not what you thought: stop and look again, do not "fix" it anyway. A fix without a test is rejected by `tools/guard_repo.py`.
2. **The tests are the judge.** Never delete, weaken or skip an existing test to get green. A test that is truly wrong is retired in
   `tests/RETIRED.md` with the reason. A skip is only for the machine (no browser, no GPU): `skipIf` / `skipUnless`.
3. **Evidence, not belief.** "It works" means a command ran and passed: test output, exit code 0, a screenshot of the page. Never reason that
   code "should" work.
4. **Small, targeted fixes.** Change only what the failing test or the traceback points to. The second and later attempts at the same bug get
   smaller, not bigger.
5. **Stop going in circles.** If a change undoes an earlier one (add it, remove it, add it back), stop and choose. If three attempts have not
   made the failing test pass, stop, put the code back to the last passing state, and explain what is known instead of trying a fourth way.
6. **Done means the request is met.** Review against what was asked: CRITICAL (crash, security, lost data) and MAJOR (part of the request does
   not work) must be fixed; NITPICKs (naming, style) never start another round. "Nothing serious found" is a good review.
7. **Fresh eyes.** A review looks at the request, the diff and the test results, not at the story of how the code was written.
8. **Ask instead of guessing.** When the request is unclear, ask one clear question.
9. **Flakes are bugs too.** A test that fails sometimes has a race: fix the race (wait for the condition, retry the draw), never re-run until green.

## Standing rules from the owner
- Never paste, print or ask for keys, tokens or passwords; they live in `keys.env` on the PC. Hugging Face repos stay private.
- No spending, renting or paid services without the owner's approval.
- Never use Claude or ChatGPT outputs as training data.
- Never open router port 3389. No arbitrary command execution in Emvryx; VryxCode's real shell runs only in Docker or the cloud machine.
- Do not name the base model family to users.
- Commit and pull request trailers as the session instructions give them.
