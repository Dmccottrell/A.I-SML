# DevSecOps: the gate, signed delivery, the update check and the alerts

What this is: the full delivery and security design for Emvryx, with the exact files, commands and settings. Everything marked **in the repository** is already
written and tested here; everything marked **you do** needs your accounts, your ID or your approval. Nothing here costs money unless a section says **PAID**.

```
pull request ──> security-scan ──> guard ──> tests (shard 1: linters + half, shard 2: half + browser suites) ─┐
                 changes ────────────────────> build-android (only if android/ changed)                      ├─> "gate: result" (the one required check)
                 report only: windows-tests, screens, windows-app, sandbox, workers-cloudflare, commit-signatures
merge to main ──> (GitHub signs the squash commit) ──> supreme-cd-release: build, sign, publish android-latest + windows-latest
                  Vercel: builds the website only if site/ changed (site/ignore-build.sh)
the PC           ──> Admin > Software update: pulls only a commit that passes app/update_verify.py
alerts           ──> P1 phone (ntfy), P2 Slack, P3 run summary / Better Stack logs
```

| What | File |
|---|---|
| The gate | `.github/workflows/supreme-ci-gate.yml` |
| Signed delivery | `.github/workflows/supreme-cd-release.yml` |
| Alerts and uptime | `.github/workflows/alert-router.yml`, `.github/workflows/monitor-uptime.yml`, `.github/actions/notify/` |
| Shared steps | `.github/actions/{python-env,android-ndk,build-windows}/` |
| Keeping pins fresh | `.github/dependabot.yml` |
| Website build rule | `site/ignore-build.sh`, `site/vercel.json` |
| Update check on the PC | `app/update_verify.py`, `app/updater.py`, `scripts/security/pin_update_keys.py` |
| GitHub settings as code | `scripts/security/github_hardening.py` |
| Error reports | `app/observability.py` |
| Tests of all of it | `tests/test_workflows.py`, `test_update_verify.py`, `test_vercel_ignore.py`, `test_observability.py`, `test_security_scripts.py`, `test_ci_tools.py` |

## 1. The CI gate

`supreme-ci-gate.yml` runs on every pull request to `main`. Order, as the file enforces it (`tests/test_workflows.py` fails if it changes):

1. **security-scan**: TruffleHog (open source) reads every commit of the pull request and asks each service whether a key it found still works. `--results=verified` (the action adds `--fail` itself):
   only a live key stops the run, so test fixtures cause no noise. The checkout has full history (`fetch-depth: 0`).
2. **guard** (runs only after security-scan passed): `tools/guard_repo.py`, the repository's own rules (tests are the judge, no skipping, a fix has its proof, no secrets).
3. **tests**, two shards side by side, only after both of the above:
   - **shard 1**: Python lint (`tools/lint.py`), JavaScript / JSON / YAML / XML / CSS / shell / HTML checks (`tools/lint_polyglot.py`), workflow lint (actionlint), shell lint
     (shellcheck), C++ lint (cppcheck), then half of the tests that need no browser;
   - **shard 2**: the other half of those, then every browser suite (they drive a real Chromium, which only this shard installs).
   `scripts/run_tests.py --kind plain|browser --shard I/N` does the split; `tests/test_ci_tools.py` proves every test file runs exactly once.
4. **build-android**, **windows-app**, **sandbox**, **screens**: only when their folders changed (`dorny/paths-filter`: `android/**`, `windows-app/**`, `docker/**` and the two sandbox files).
5. **gate: result**: passes only when everything that had to run passed (a job skipped because its folder did not change counts as passed). **Make this the one required check.**

Report-only, `continue-on-error: true`, they can never block a merge: `windows-tests`, `screens`, `windows-app`, `sandbox`, and `workers-cloudflare`, which exits 1 on purpose to
stand in for Cloudflare's own "Workers Builds" check that always fails here.

Three linters (actionlint, shellcheck, cppcheck) are also `continue-on-error` for now, because they have never run on this code and an unknown finding should not block anyone
on day one. After one clean run, delete that line from each; from then on they block.

Rules every new workflow keeps (tested): every action pinned to a full 40-character commit (version in a comment), no `pull_request_target`, permissions start at none and each job
asks only for what it needs, every job has a time limit, checkouts leave no token on disk, no outside text (branch name, pull request title) is ever written into a command, and the
gate itself uses **no secret at all** (a pull request can edit the workflow, so it must hold nothing worth stealing). Dependabot opens one grouped weekly pull request to refresh the pins.

### Switching over (do this in order; nothing breaks if you stop after any step)
1. Merge this change. The gate now runs beside the older workflows (`tests`, `android`, `windows-app`, `sandbox`), which still publish exactly as before.
2. After three pull requests with a green **gate: result**, protect `main`:
   `python scripts/security/github_hardening.py plan` (read it), then `GITHUB_ADMIN_TOKEN=... python scripts/security/github_hardening.py apply --only ruleset,scanning,actions`.
3. Delivery (section 3): set the secrets and variables, run **supreme-cd-release** by hand once, check it, then set `SUPREME_CD` to `true`.
4. Retire the older workflows: delete `tests.yml`, `sandbox.yml`, and the `build`/`screens`/`release` jobs of `android.yml` and `windows-app.yml` (or the files), and remove the older
   required checks from the ruleset.

## 2. Cryptographic protection

### 2.1 Signed commits (what stops someone injecting code under your name)
The rule on `main` (the ruleset above) is: **only through a pull request, every commit on `main` signed, squash merges only, no force-push**. Squash merges are signed by GitHub itself
(the `web-flow` key), so every commit that lands on `main` is signed and "Verified", whoever wrote the pull request. The commits inside a pull request should also be signed by their author.

Set up your own signing on the PC (SSH signing, no GPG needed; run in Git Bash or PowerShell):
```bash
ssh-keygen -t ed25519 -f ~/.ssh/emvryx_signing -C "emvryx commit signing" -N ""
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/emvryx_signing.pub
git config --global commit.gpgsign true
git config --global tag.gpgsign true
mkdir -p ~/.config/git && echo "$(git config user.email) $(cat ~/.ssh/emvryx_signing.pub)" >> ~/.config/git/allowed_signers
git config --global gpg.ssh.allowedSignersFile ~/.config/git/allowed_signers
```
Tell GitHub the public key (so it shows "Verified"). Use a token with the "SSH signing keys" write permission:
```bash
curl -fsS -X POST https://api.github.com/user/ssh_signing_keys \
  -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github+json" \
  -d "$(jq -n --arg k "$(cat ~/.ssh/emvryx_signing.pub)" '{title: "emvryx signing", key: $k}')"
```
Then on github.com: Settings > SSH and GPG keys > turn on **Flag unsigned commits as unverified** (vigilante mode), so an unsigned commit that claims to be you is labelled.

Check one more thing before you turn enforcement on: commits made by Claude's cloud sessions carry an SSH signature (the session's own key). They show "Verified" only if that
public key is registered on GitHub. Look at any pull request: if its commits say **Unverified**, they are signed but GitHub cannot check by whom, and the ruleset would not stop
them (it applies to `main`, which only receives squash merges). The job **gate: commit-signatures** reports this on every pull request and is report-only until you set the repository
variable `SIGNED_COMMITS_ENFORCE` to `true`.

### 2.2 Secrets: GitHub Actions against Vercel (who can read what)

| Where | Name | Holds | Who can read it | Rule |
|---|---|---|---|---|
| GitHub **environment** `release` (only the branch `main`) | `ANDROID_DEBUG_KEYSTORE` | the Android signing key (base64) | only `release-android` on `main` | an environment secret is invisible to every job that is not in that environment, and the environment refuses any branch but `main` |
| same | `WINDOWS_PFX_BASE64`, `WINDOWS_PFX_PASSWORD` | an Authenticode certificate (**PAID**, not set today) | only `release-windows` on `main` | |
| GitHub repository secrets | `NTFY_TOPIC_P1`, `NTFY_TOKEN`, `SLACK_WEBHOOK_P2`, `BETTERSTACK_SOURCE_TOKEN` | alert channels | only `alert-router` and `monitor-uptime`, which run from `main` or on a schedule | never given to a workflow a pull request can edit |
| GitHub repository **variables** (not secret) | `SUPREME_CD`, `ANDROID_CERT_SHA256`, `SIGNED_COMMITS_ENFORCE`, `MSIX_IDENTITY_NAME`, `MSIX_PUBLISHER`, `MSIX_PUBLISHER_DISPLAY`, `BETTERSTACK_INGEST_HOST` | settings and fingerprints | everyone with read access | a fingerprint is meant to be public |
| the PC, `.emvryx/keys.env` | search keys, mail password, `EMVRYX_SENTRY_DSN` | the server's own keys | the PC only | **never** in GitHub, never in Vercel |
| Vercel | none | the website is static and needs no key | | see below |

Set the release secrets (GitHub CLI, free; on the PC):
```bash
gh api -X PUT repos/Dmccottrell/A.I-SML/environments/release --input - <<< '{"deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true}}'
gh api -X POST repos/Dmccottrell/A.I-SML/environments/release/deployment-branch-policies -f name=main -f type=branch
base64 -w0 ~/.android/debug.keystore | gh secret set ANDROID_DEBUG_KEYSTORE --env release --repo Dmccottrell/A.I-SML
FP=$(keytool -list -v -keystore ~/.android/debug.keystore -alias androiddebugkey -storepass android | sed -n 's/^ *SHA256: //p' | tr -d ':' | tr 'A-F' 'a-f')
gh variable set ANDROID_CERT_SHA256 --body "$FP" --repo Dmccottrell/A.I-SML
gh secret delete ANDROID_DEBUG_KEYSTORE --repo Dmccottrell/A.I-SML          # the old repository-wide copy, now that the environment has it
```
(`github_hardening.py` does the two `environments` calls for you.) The keystore is the same file the app has always been signed with, so phones keep accepting updates;
the job refuses to publish an app signed by any other key (`ANDROID_CERT_SHA256` is the pin).

**Production database keys and Vercel previews.** Today there is no database key on Vercel at all: the chat database is SQLite on your PC, and the website is static. That is the
strongest rule, and it stays: *a key that is not there cannot leak*. If a hosted database (Supabase, see docs/DEPLOY.md) is ever added, these are the parameters, exactly:
- two separate database **projects**, one for production and one for everything else, with different keys (a preview must never be able to reach production data);
- the production key is created with `type: sensitive` (it can never be read back, not even by you) and `target: ["production"]` only; preview and development get the other project's key:
```bash
# the value comes from a file so it never appears in your shell history or process list
jq -n --arg v "$(cat prod_db_key.txt)" '{key:"DATABASE_KEY", value:$v, type:"sensitive", target:["production"]}' | \
  curl -fsS -X POST "https://api.vercel.com/v10/projects/$VERCEL_PROJECT_ID/env" -H "Authorization: Bearer $VERCEL_TOKEN" -H "Content-Type: application/json" --data @-
jq -n --arg v "$(cat preview_db_key.txt)" '{key:"DATABASE_KEY", value:$v, type:"sensitive", target:["preview"]}' | \
  curl -fsS -X POST "https://api.vercel.com/v10/projects/$VERCEL_PROJECT_ID/env" -H "Authorization: Bearer $VERCEL_TOKEN" -H "Content-Type: application/json" --data @-
```
- prove it, any time (prints `true` when no production-looking key is visible to previews):
```bash
curl -fsS "https://api.vercel.com/v9/projects/$VERCEL_PROJECT_ID/env" -H "Authorization: Bearer $VERCEL_TOKEN" | \
  jq '[.envs[] | select(.target | index("preview")) | select(.target | index("production"))] | length == 0'
```
- Vercel > Project > Settings > Deployment Protection: leave **Vercel Authentication** on for previews, so a preview link is not public; and never add a production value to the `development` target.
- The same discipline on GitHub: a production secret is an *environment* secret in `release`, so a pull request, a fork or any branch other than `main` cannot read it.

## 3. Delivery and the manual update

### 3.1 Signed downloads: `supreme-cd-release.yml`
Runs on every push to `main` (and by hand), **only when the repository variable `SUPREME_CD` is `true`** (until then the older release jobs publish exactly as before, and when it is on they
stand down, so one workflow only ever writes the downloads). For Android and Windows, each changed folder at a time:
1. builds (`assemblePhone` for Android; the exe, the installer and the Store package for Windows);
2. **Android only**: the key comes out of the encrypted environment secret into a file only that job can read, the app is built, the key is deleted again, and `apksigner` (Google's own
   tool) reads the signing certificate back out of the finished file; its SHA-256 fingerprint must equal `ANDROID_CERT_SHA256` or nothing is published;
3. writes `<file>.sha256` and `version.json` with the commit, the time, the file's SHA-256, the key's fingerprint and the run's address. The apps already read `sha` and `built` from it, so
   the "a new version is ready" notice keeps working (`app_updates`);
4. signs the file and `version.json` with **Sigstore, keyless**: GitHub gives the job an identity token that says "this workflow, in this repository, on `main`"; no signing key exists to steal.
   It also stores a GitHub build-provenance attestation;
5. replaces the `android-latest` / `windows-latest` release **in place** (upload with `--clobber`, then move the tag), so the download link never goes dark if a step fails;
6. downloads what the public link now serves and checks the checksum and the signature the way a stranger would.

Check any download yourself (needs the free `cosign` program):
```bash
curl -fsSLO https://github.com/Dmccottrell/A.I-SML/releases/download/android-latest/emvryx.apk
curl -fsSLO https://github.com/Dmccottrell/A.I-SML/releases/download/android-latest/emvryx.apk.sigstore.json
cosign verify-blob --bundle emvryx.apk.sigstore.json \
  --certificate-identity https://github.com/Dmccottrell/A.I-SML/.github/workflows/supreme-cd-release.yml@refs/heads/main \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com emvryx.apk
```
The Windows installer is **not** Authenticode-signed (that needs a paid certificate): Windows still says "Windows protected your PC" the first time. The Sigstore signature is the proof today;
the Store route (docs/MICROSOFT_STORE.md) is the free way to remove the warning. If you buy a certificate later, set `WINDOWS_PFX_BASE64` and `WINDOWS_PFX_PASSWORD` in the `release` environment and the step signs and verifies the installer.

### 3.2 The website: Vercel's Ignored Build Step
`site/vercel.json` says `"ignoreCommand": "bash ignore-build.sh"`. The project's Root Directory is `site` (docs/DEPLOY.md), and the script works from there or from the repository root. It compares
the commit about to build with the last commit Vercel built on that branch (`VERCEL_GIT_PREVIOUS_SHA`) and looks only inside `site/`:

| It prints | Exit | Vercel does |
|---|---|---|
| nothing in site/ changed | 0 | skips the build (nothing new goes live, no build minutes) |
| site/ changed, or any doubt (no earlier commit, a commit missing from the shallow clone, not a git checkout) | 1 | builds |

If you prefer to set it in the dashboard instead: Project > Settings > Git > Ignored Build Step > Run my Bash script > `bash ignore-build.sh`.
`tests/test_vercel_ignore.py` runs the script against real git repositories for every case above.

### 3.3 The PC's manual update: how a man-in-the-middle is stopped
Delivery to the chat server is pull-based and manual on purpose: nothing arrives unless you press **Admin > PC > Software update > Update and restart**. When you do, `app/updater.py`
runs `git fetch` and then `app/update_verify.py` checks, with a trust file that lives only on the PC (`.emvryx/update_trust.json`, outside the repository, never changed by an update):

1. **the address is pinned**: the repository's `origin` is exactly `https://github.com/Dmccottrell/A.I-SML.git`, **and** the address git really connects to (after any `insteadOf` rewriting
   in a config file) is the same one, so nobody can quietly redirect the fetch to their own copy;
2. **the certificate check is on**: `GIT_SSL_NO_VERIFY` is unset and `http.sslVerify` is not `false`; the connection is https to GitHub's certificate, so a network attacker cannot read or change it;
3. **the newest commit has a valid signature**, read by git's own `verify-commit --raw` against a keyring that holds *only* the pinned key (`.emvryx/update_gpg`);
4. **the signer is on the list**: the signing key's full 40-character fingerprint must be one of the pinned ones (the short id is not enough);
5. **the update moves to exactly the commit that was checked** (`git merge --ff-only <that commit>`), not to whatever a second `git pull` would fetch a moment later;
6. it still only moves forward, never over hand-edited files, only to the change you were shown, and only the owner can press the button (all as before).

Pin the key once, on the PC (needs gpg, which Git for Windows includes):
```powershell
python scripts\security\pin_update_keys.py                 # GitHub's signing key, mode "warn": the Admin screen shows the result but updates still work
python scripts\security\pin_update_keys.py --mode enforce  # after one good update: a commit that fails the check is refused and nothing changes
```
It downloads GitHub's key over https, refuses it unless its fingerprint ends in GitHub's published key id `4AEE18F83AFDEB23`, and writes the full fingerprint it found. A damaged trust
file makes updates stricter (enforce, no keys), never looser.

What this does **not** protect against, plainly: a signature proves who signed, not that the change is good. If someone with permission to merge into `main` is tricked or hacked, GitHub will
sign their merge too. That is what the ruleset (a protected `main`, a required gate), two-step sign-in on your GitHub account, and a fine-grained token with the fewest permissions are for.
The Admin screen shows the check's result next to the list of changes; a failed check is never hidden.

## 4. Monitoring and incident response

### 4.1 Where things go
- **Sentry (free Developer plan): errors from the chat server**, off unless you opt in. `app/observability.py` removes everything private on the PC *before* sending: the error's message,
  variable values, source lines, breadcrumbs, request data (the address is cut to its path), IP, computer name, and anything key-shaped; what is left is the kind of error and the file and line.
  Performance traces and profiles are off. The privacy page says so. Set up: create a Sentry project (platform Python), then on the PC:
  `pip install sentry-sdk`, add `EMVRYX_SENTRY_DSN=<the project's DSN>` to `.emvryx/keys.env`, restart; the start-up line says `Error reports: on` (never the address).
  Then in Sentry: Settings > Integrations > Slack > install; Alerts > Create Alert > Issues > *When a new issue is created* > *send a notification via Slack to the P2 channel*. That is the P2 route for new errors.
- **Vercel Log Drains: not enabled, on purpose.** Drains need a paid Vercel plan (**PAID**), and the website is static (build logs only). If you move to a paid plan: Vercel dashboard > Team Settings >
  Drains > Add Drain, source "Project logs", destination "HTTP" at Better Stack's intake with its source token as a bearer header. Until then, a failed website deployment shows in the pull request's checks and,
  with the Vercel app for Slack, in the P2 channel.
- **Centralised logs: Better Stack Telemetry (free tier) is wired, Datadog is not** (Datadog is paid). The P3 route posts one JSON line per low-priority event to Better Stack's HTTP intake
  (`https://$BETTERSTACK_INGEST_HOST`, `Authorization: Bearer $BETTERSTACK_SOURCE_TOKEN`), see `.github/actions/notify/action.yml`. Create a source in Better Stack (Telemetry > Sources > Connect source > HTTP),
  then set the secret and the variable:
  ```bash
  gh secret set BETTERSTACK_SOURCE_TOKEN --repo Dmccottrell/A.I-SML
  gh variable set BETTERSTACK_INGEST_HOST --body "<the ingest host Better Stack shows for that source>" --repo Dmccottrell/A.I-SML
  ```
- **Production uptime**: `monitor-uptime.yml` asks `https://chat.emvryx.app/api/status` (must answer `{"up": true}`) and `https://emvryx.app/` (must answer 200) every five minutes, three tries each;
  still down means a P1 alert (at most twice an hour) and a red run.

### 4.2 The alert channels (all free)
```bash
# P1: ntfy. The topic name is the password: make a long random one, subscribe to it in the free ntfy phone app, and set Priority "urgent" to override silent mode
TOPIC=$(python -c "import secrets; print(secrets.token_urlsafe(24))"); echo "$TOPIC"          # subscribe to this name in the ntfy app
printf '%s' "$TOPIC" | gh secret set NTFY_TOPIC_P1 --repo Dmccottrell/A.I-SML
# P2: Slack. Create an incoming webhook (api.slack.com/apps > Create New App > Incoming Webhooks > Add to channel #emvryx-alerts) and store its address:
gh secret set SLACK_WEBHOOK_P2 --repo Dmccottrell/A.I-SML
```
Test them (sends one real alert each): `gh workflow run monitor-uptime.yml` only alerts when something is down; to test the channels directly, run the ntfy line by hand:
`curl -H "Priority: 5" -H "Title: test" -d "test" https://ntfy.sh/$TOPIC`.

### 4.3 The priority matrix

| Priority | What | Detected by | Goes to | Within | You do |
|---|---|---|---|---|---|
| **P1 critical** | a live secret found in a pull request | `security-scan` (TruffleHog, verified keys only) -> `alert-router` | ntfy, priority 5 (rings the phone) | about 3 minutes of the push | revoke the key now (before anything else), rotate it, then remove it from history |
| **P1 critical** | production down: the chat server or the website does not answer 3 times in a row | `monitor-uptime` every 5 minutes | ntfy, priority 5, at most twice an hour | 5 to 10 minutes | check the PC is on and `cloudflared` is running (docs/DEPLOY.md); the website: Vercel dashboard |
| **P2 standard** | a build of `main` failed (tests, android, windows-app, sandbox, supreme-cd-release on a push to main) | `alert-router` | Slack `#emvryx-alerts` | about 3 minutes | open the run, fix forward or revert; the downloads are untouched (delivery replaces them only after a good build) |
| **P2 standard** | a new error in the chat server (first time seen) | Sentry alert rule | Slack `#emvryx-alerts` | seconds | Admin > Crashes has the same error with its context |
| **P3 low** | a pull request or preview branch failed | `alert-router` | the run summary; Better Stack logs when set up | when you look | nothing urgent |
| **P3 low** | the report-only checks (windows-tests, screens, windows-app, sandbox, Cloudflare) are red | the Actions tab | nothing sent | | read when convenient |

Incident steps, in order: **1** stop the bleeding (revoke or switch off the thing: a key, `SUPREME_CD` = `false`, `gh workflow disable`); **2** find what changed (`git log`, the run); **3** fix forward through a pull request,
or `git revert` the change and merge the revert; **4** write one line in What's new if people noticed; **5** if a secret was exposed, rotate it *first* and rewrite history only after.

## What was verified here, and what only a real run can prove
Verified in this repository by tests that run on every pull request: every workflow and local action parses, pins every action to a commit, holds the permission rules, has the exact job order and
the exact set of report-only jobs; the test split runs every file exactly once; the multi-language lint passes on the current code and catches a broken file of each kind; the Vercel script gives the right answer
for every case with real git repositories; the update check works with real git and real GPG keys (signed by the pinned key, unsigned, a stranger's key, a good key not on the list, a different origin, a redirected
address, the certificate check off, a damaged trust file); the error scrubber leaves nothing private in a realistic event; the setup scripts send exactly the planned calls with the token only in a header.

Only GitHub, Vercel, Sentry and your phone can prove: that TruffleHog, cosign, the attestation action, actionlint, shellcheck and cppcheck run cleanly on this code (the first run of each is the proof; three of them are
report-only until then), that the emulator job still passes, that `ntfy` and Slack deliver, and that Vercel honours the ignore command in your project. The first pull request after this merges is that proof; read its checks.
Costs: nothing above is paid. **PAID, not set up, need your approval:** an Authenticode certificate, Vercel Pro (log drains), Datadog, Sentry above its free limits.
