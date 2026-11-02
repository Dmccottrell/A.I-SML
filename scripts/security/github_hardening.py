"""
github_hardening.py - sets up the GitHub side of the security design (docs/DEVSECOPS.md) with exact API calls, so nothing depends on clicking through menus from memory.

    python scripts/security/github_hardening.py plan                 print every request that would be sent (nothing is sent)
    python scripts/security/github_hardening.py apply                send them, one by one, and say what GitHub answered
    python scripts/security/github_hardening.py apply --only ruleset,environment
    python scripts/security/github_hardening.py plan --required-check "gate: result"

What it sets (each is its own step, so a step can be left out with --only):
    ruleset      a ruleset on main: only through a pull request, every commit on main signed (GitHub signs squash merges itself), the gate's one result check must pass,
                 no force-push, no deleting main. Repository admins can bypass only by way of a pull request.
    environment  an environment called `release`, usable only from main. The release secrets live in it (docs/DEVSECOPS.md, section 2), so a job on any other branch
                 or a pull request can never read them.
    scanning     GitHub's own secret scanning and push protection (blocks a push that contains a live key; free for public repositories)
    actions      the default token of every workflow is read-only, and workflows cannot approve pull requests
    variables    the repository variables the delivery workflow reads (SUPREME_CD is NOT set here: turning delivery on is the owner's decision, see "Switching over")

The token: set GITHUB_ADMIN_TOKEN to a fine-grained personal access token for this one repository with the permissions Administration (write), Environments (write)
and Variables (write). It is read from the environment, sent only to api.github.com, and never printed. Make the token on github.com > Settings > Developer settings.
Run `plan` first: it prints the exact JSON, and with no token set it still works.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

OWNER, REPO = "Dmccottrell", "A.I-SML"
API = "https://api.github.com"
ADMIN_ROLE_ID = 5                                       # GitHub's id for the repository role "admin" in a ruleset bypass list


def steps(required_check="gate: result", variables=None):
    """Every call, as (step name, method, path, body). The order matters: the environment before the branch policy that belongs to it."""
    repo = f"/repos/{OWNER}/{REPO}"
    out = [
        ("ruleset", "POST", f"{repo}/rulesets", {
            "name": "main is protected", "target": "branch", "enforcement": "active",
            "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
            "bypass_actors": [{"actor_id": ADMIN_ROLE_ID, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}],
            "rules": [
                {"type": "deletion"},
                {"type": "non_fast_forward"},
                {"type": "required_signatures"},
                {"type": "pull_request", "parameters": {"required_approving_review_count": 0, "dismiss_stale_reviews_on_push": True, "require_code_owner_review": False,
                                                        "require_last_push_approval": False, "required_review_thread_resolution": False,
                                                        "allowed_merge_methods": ["squash"]}},
                {"type": "required_status_checks", "parameters": {"strict_required_status_checks_policy": True, "required_status_checks": [{"context": required_check}]}},
            ]}),
        ("environment", "PUT", f"{repo}/environments/release", {"deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}}),
        ("environment", "POST", f"{repo}/environments/release/deployment-branch-policies", {"name": "main", "type": "branch"}),
        ("scanning", "PATCH", repo, {"security_and_analysis": {"secret_scanning": {"status": "enabled"}, "secret_scanning_push_protection": {"status": "enabled"}}}),
        ("actions", "PUT", f"{repo}/actions/permissions/workflow", {"default_workflow_permissions": "read", "can_approve_pull_request_reviews": False}),
    ]
    for name, value in (variables or {}).items():
        out.append(("variables", "POST", f"{repo}/actions/variables", {"name": name, "value": value}))
    return out


def send(method, path, body, token, opener=urllib.request.urlopen):
    """One call. Returns (status code, a short plain answer). The token goes only in the Authorization header."""
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(), method=method, headers={
        "Authorization": "Bearer " + token, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json", "User-Agent": "emvryx-hardening"})
    try:
        with opener(req, timeout=30) as r:
            return r.status, "ok"
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode()).get("message", "")
        except (ValueError, OSError):
            msg = ""
        return e.code, msg[:200] or "refused"
    except (urllib.error.URLError, OSError) as e:
        return 0, str(e)[:200]


def main(argv=None, environ=None, opener=urllib.request.urlopen, out=print):
    environ = os.environ if environ is None else environ
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("action", choices=("plan", "apply"))
    p.add_argument("--only", default="", help="comma separated: ruleset, environment, scanning, actions, variables")
    p.add_argument("--required-check", default="gate: result", help="the check name the ruleset requires (the gate's one result job)")
    p.add_argument("--variable", action="append", default=[], metavar="NAME=VALUE", help="a repository variable to create, for example ANDROID_CERT_SHA256=<fingerprint>")
    a = p.parse_args(argv)
    wanted = {x.strip() for x in a.only.split(",") if x.strip()}
    variables = dict(v.split("=", 1) for v in a.variable if "=" in v)
    chosen = [s for s in steps(a.required_check, variables) if not wanted or s[0] in wanted]
    if wanted - {s[0] for s in steps()} - {"variables"}:
        out("unknown step in --only")
        return 2
    token = environ.get("GITHUB_ADMIN_TOKEN", "")
    if a.action == "plan":
        for name, method, path, body in chosen:
            out(f"[{name}] {method} {API}{path}\n{json.dumps(body, indent=2)}\n")
        out("Nothing was sent." + ("" if token else " (GITHUB_ADMIN_TOKEN is not set; it is only needed for `apply`.)"))
        return 0
    if not token:
        out("Set the GITHUB_ADMIN_TOKEN environment variable first (a fine-grained token for this repository; see the top of this file).")
        return 2
    failed = 0
    for name, method, path, body in chosen:
        status, msg = send(method, path, body, token, opener)
        out(f"[{name}] {method} {path}: {status} {msg}")
        failed += 0 if 200 <= status < 300 else 1
    out("done" if not failed else f"{failed} call(s) were refused: read the lines above (a 422 on a ruleset usually means it already exists)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
