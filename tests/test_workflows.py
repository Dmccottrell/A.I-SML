"""The CI/CD files are code that can be attacked, so they are tested like code. Every workflow and local action must keep these rules, and the gate must have the exact
shape the project relies on (order of jobs, which jobs may fail without blocking a merge). Nothing here needs a network."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import glob
import re
import unittest

try:
    import yaml
except ImportError:                                                     # the CI installs it; a machine without it skips these checks
    yaml = None

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
WORKFLOWS = sorted(glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml")))
ACTIONS = sorted(glob.glob(os.path.join(ROOT, ".github", "actions", "*", "action.yml")))
SAFE_IN_RUN = re.compile(r"^(matrix\.[\w.-]+|github\.(sha|repository|run_id|run_attempt|run_number|server_url)|runner\.\w+)$")
SHA_PIN = re.compile(r"^[\w.-]+/[\w.-]+(/[\w./-]+)?@[0-9a-f]{40}$")


def load(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def new_workflows():
    """The workflows written for the gate. The older ones (tests, android, windows-app, sandbox) stay until the owner switches over, and are retired then."""
    return [w for w in WORKFLOWS if os.path.basename(w).startswith(("supreme-", "monitor-", "alert-"))]


def steps_of(doc):
    """(where, step) for every step of a workflow (all jobs) or of a local composite action."""
    if "jobs" in doc:
        return [(f"job {j}", s) for j, job in doc["jobs"].items() for s in job.get("steps", [])]
    return [("action", s) for s in doc.get("runs", {}).get("steps", [])]


@unittest.skipUnless(yaml, "needs PyYAML")
class Rules(unittest.TestCase):
    def test_the_files_are_found(self):
        self.assertGreaterEqual(len(WORKFLOWS), 8)
        self.assertGreaterEqual(len(ACTIONS), 4)

    def test_every_new_workflow_and_action_pins_its_actions_to_a_full_commit(self):
        # the older workflows (tests, android, windows-app, sandbox) use version tags and are replaced by these; everything written for the gate is pinned
        for path in new_workflows() + ACTIONS:
            for where, step in steps_of(load(path)):
                uses = step.get("uses", "")
                if uses and not uses.startswith(("./", "docker://")):
                    self.assertRegex(uses, SHA_PIN, f"{os.path.basename(path)} {where}: {uses} is not pinned to a commit")

    def test_each_pin_names_its_version_in_a_comment(self):
        for path in new_workflows() + ACTIONS:
            with open(path, encoding="utf-8") as f:
                for n, line in enumerate(f.read().splitlines(), 1):
                    if re.search(r"uses:\s+[\w.-]+/[\w./-]+@[0-9a-f]{40}", line):
                        self.assertRegex(line, r"#\s*v\d", f"{os.path.basename(path)}:{n} has no version comment")

    def test_no_workflow_uses_pull_request_target_or_runs_code_from_a_pull_request_with_secrets(self):
        for path in WORKFLOWS:
            self.assertNotIn("pull_request_target", read(".github", "workflows", os.path.basename(path)), os.path.basename(path))

    def test_the_gate_and_the_alert_router_hold_no_secret_a_pull_request_could_steal(self):
        gate = read(".github", "workflows", "supreme-ci-gate.yml")
        self.assertNotIn("secrets.", re.sub(r"(?m)^\s*#.*$", "", gate))        # comments may talk about secrets; the code may not use them

    def test_nothing_untrusted_is_put_into_a_command(self):
        # a branch name, a pull request title or a message can contain anything: inside `run:` only fixed, safe values may be written with ${{ }}
        for path in new_workflows() + ACTIONS:
            for where, step in steps_of(load(path)):
                for expr in re.findall(r"\$\{\{\s*(.*?)\s*\}\}", step.get("run", "") or ""):
                    self.assertRegex(expr, SAFE_IN_RUN, f"{os.path.basename(path)} {where}: ${{{{ {expr} }}}} in a run: command")

    def test_every_job_and_the_gate_default_to_least_permission(self):
        for path in new_workflows():
            doc = load(path)
            self.assertIn("permissions", doc, f"{os.path.basename(path)} has no top-level permissions")
            self.assertEqual(doc["permissions"], {}, f"{os.path.basename(path)} must start from no permissions")
            for name, job in doc["jobs"].items():
                self.assertIn("permissions", job, f"{os.path.basename(path)} job {name} must say what it needs")
                for scope, level in job["permissions"].items():
                    if level == "write":
                        self.assertIn(scope, {"contents", "id-token", "attestations"}, f"{name}: unexpected write permission {scope}")

    def test_every_job_has_a_time_limit(self):
        for path in new_workflows():
            for name, job in load(path)["jobs"].items():
                self.assertIn("timeout-minutes", job, f"{os.path.basename(path)} job {name}")

    def test_no_checkout_leaves_the_token_on_disk(self):
        for path in new_workflows():
            for where, step in steps_of(load(path)):
                if str(step.get("uses", "")).startswith("actions/checkout@"):
                    self.assertIs(step.get("with", {}).get("persist-credentials"), False, f"{os.path.basename(path)} {where}")


@unittest.skipUnless(yaml, "needs PyYAML")
class Gate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gate = load(os.path.join(ROOT, ".github", "workflows", "supreme-ci-gate.yml"))
        cls.jobs = cls.gate["jobs"]

    def needs(self, job):
        n = self.jobs[job].get("needs", [])
        return {n} if isinstance(n, str) else set(n)

    def closure(self, job):
        seen, todo = set(), [job]
        while todo:
            for n in self.needs(todo.pop()):
                if n not in seen:
                    seen.add(n)
                    todo.append(n)
        return seen

    def test_it_runs_on_pull_requests_to_main(self):
        on = self.gate.get("on", self.gate.get(True))                    # YAML reads a bare `on` as the word true
        self.assertEqual(on["pull_request"]["branches"], ["main"])

    def test_the_jobs_the_project_relies_on_exist(self):
        for name in ("security-scan", "guard", "tests", "build-android", "windows-tests", "screens", "windows-app", "sandbox", "workers-cloudflare", "changes", "gate-result"):
            self.assertIn(name, self.jobs)

    def test_security_scan_then_guard_come_before_any_test_job(self):
        self.assertEqual(self.needs("guard"), {"security-scan"})                                # strictly one after the other
        for job in ("tests", "windows-tests"):
            self.assertTrue({"security-scan", "guard"} <= self.closure(job), job)

    def test_security_scan_is_trufflehog_and_fails_on_a_verified_secret(self):
        step = next(s for s in self.jobs["security-scan"]["steps"] if "trufflehog" in s.get("uses", ""))
        self.assertIn("--results=verified", step["with"]["extra_args"])
        for added_by_the_action in ("--fail", "--no-update"):                                   # the action adds these itself and TruffleHog refuses a repeated flag (seen on GitHub)
            self.assertNotIn(added_by_the_action, step["with"]["extra_args"])
        checkout = next(s for s in self.jobs["security-scan"]["steps"] if "checkout" in s.get("uses", ""))
        self.assertEqual(checkout["with"]["fetch-depth"], 0)                                    # every commit of the pull request is read

    def test_the_tests_run_in_two_shards_and_the_browser_suites_are_in_shard_two_only(self):
        job = self.jobs["tests"]
        self.assertEqual(job["strategy"]["matrix"]["shard"], [1, 2])
        runs = " ".join(s.get("run", "") for s in job["steps"])
        self.assertIn("--kind plain --shard ${{ matrix.shard }}/2", runs)
        browser = [s for s in job["steps"] if "--kind browser" in s.get("run", "")]
        self.assertEqual(len(browser), 1)
        self.assertEqual(browser[0]["if"], "matrix.shard == 2")
        for tool in ("tools/lint.py", "tools/lint_polyglot.py", "actionlint", "shellcheck", "cppcheck"):
            step = next(s for s in job["steps"] if tool in s.get("run", ""))
            self.assertEqual(step["if"], "matrix.shard == 1", tool)                              # the linters are shard 1's

    def test_the_optional_builds_run_only_when_their_folder_changed(self):
        for job, key in (("build-android", "android"), ("windows-app", "windows"), ("sandbox", "sandbox"), ("screens", "android")):
            self.assertIn("changes", self.needs(job), job)
            self.assertIn(f"needs.changes.outputs.{key} == 'true'", self.jobs[job]["if"], job)
        changes = next(s for s in self.jobs["changes"]["steps"] if "paths-filter" in s.get("uses", ""))
        filters = yaml.safe_load(changes["with"]["filters"])
        self.assertIn("android/**", filters["android"])
        self.assertIn("windows-app/**", filters["windows"])
        self.assertIn("docker/**", filters["sandbox"])

    def test_the_report_only_jobs_can_never_block_a_merge_and_the_others_can(self):
        for job in ("windows-tests", "screens", "windows-app", "sandbox", "workers-cloudflare"):
            self.assertIs(self.jobs[job]["continue-on-error"], True, job)
        for job in ("security-scan", "guard", "tests", "build-android", "changes"):
            self.assertNotIn("continue-on-error", self.jobs[job], job)

    def test_the_cloudflare_stand_in_exits_one(self):
        run = " ".join(s.get("run", "") for s in self.jobs["workers-cloudflare"]["steps"])
        self.assertIn("exit 1", run)

    def test_the_one_result_job_waits_for_every_blocking_job_and_always_runs(self):
        result = self.jobs["gate-result"]
        self.assertEqual(result["if"], "always()")
        self.assertTrue({"security-scan", "guard", "tests", "build-android"} <= self.needs("gate-result"))
        for report_only in ("windows-tests", "screens", "windows-app", "sandbox", "workers-cloudflare"):
            self.assertNotIn(report_only, self.needs("gate-result"))

    def test_unsigned_commits_only_report_until_the_owner_turns_enforcement_on(self):
        self.assertIn("SIGNED_COMMITS_ENFORCE", str(self.jobs["commit-signatures"]["continue-on-error"]))


@unittest.skipUnless(yaml, "needs PyYAML")
class Delivery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cd = load(os.path.join(ROOT, ".github", "workflows", "supreme-cd-release.yml"))
        cls.jobs = cls.cd["jobs"]

    def test_it_runs_on_pushes_to_main_and_is_off_until_the_owner_switches_it_on(self):
        on = self.cd.get("on", self.cd.get(True))
        self.assertEqual(on["push"]["branches"], ["main"])
        self.assertIn("SUPREME_CD == 'true'", self.jobs["plan"]["if"])
        for older, key in ((".github/workflows/android.yml", "if"), (".github/workflows/windows-app.yml", "if")):
            self.assertIn("vars.SUPREME_CD != 'true'", read(older))      # only one workflow writes the downloads

    def test_the_release_jobs_use_the_protected_environment_and_only_the_writes_they_need(self):
        for job in ("release-android", "release-windows"):
            self.assertEqual(self.jobs[job]["environment"], "release")
            self.assertEqual(self.jobs[job]["permissions"], {"contents": "write", "id-token": "write", "attestations": "write"})

    def test_the_android_release_refuses_a_key_that_is_not_the_pinned_one_and_signs_and_verifies(self):
        text = " ".join(s.get("run", "") for s in self.jobs["release-android"]["steps"])
        for needle in ("ANDROID_CERT_SHA256", "apksigner", "not by the pinned key", "cosign sign-blob", "cosign verify-blob", "sha256sum -c", "apk_sha256", "cert_sha256", "rm -f ~/.android/debug.keystore"):
            self.assertIn(needle, text.replace("\n", " "), needle)

    def test_both_downloads_are_replaced_in_place_so_the_link_never_goes_dark(self):
        for job, tag in (("release-android", "android-latest"), ("release-windows", "windows-latest")):
            text = " ".join(s.get("run", "") for s in self.jobs[job]["steps"])
            self.assertIn(f"gh release upload {tag}", text)
            self.assertIn("--clobber", text)
            self.assertNotIn("gh release delete", text)


@unittest.skipUnless(yaml, "needs PyYAML")
class Alerts(unittest.TestCase):
    def test_the_alert_router_reads_the_other_runs_and_sends_p1_p2_p3(self):
        router = load(os.path.join(ROOT, ".github", "workflows", "alert-router.yml"))
        on = router.get("on", router.get(True))
        self.assertEqual(on["workflow_run"]["types"], ["completed"])
        self.assertIn("supreme-ci-gate", on["workflow_run"]["workflows"])
        text = read(".github", "workflows", "alert-router.yml")
        for needle in ("priority=p1", "priority=p2", "priority=p3", "security-scan"):
            self.assertIn(needle, text)

    def test_the_notify_action_never_puts_untrusted_text_in_a_command(self):
        doc = load(os.path.join(ROOT, ".github", "actions", "notify", "action.yml"))
        run = doc["runs"]["steps"][0]["run"]
        self.assertNotIn("${{", run)                                           # everything arrives through env and is used as data
        self.assertIn("jq -n --arg", run)

    def test_uptime_asks_both_public_addresses_and_alerts_p1(self):
        text = read(".github", "workflows", "monitor-uptime.yml")
        self.assertIn("chat.emvryx.app/api/status", text)
        self.assertIn("https://emvryx.app/", text)
        self.assertIn("priority: p1", text)


if __name__ == "__main__":
    unittest.main()
