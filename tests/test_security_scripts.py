"""The two setup scripts in scripts/security: the GitHub hardening calls (planned, sent with the token only in the header, never printed) and the pinning of the update
signing key on the PC (the downloaded key must carry GitHub's published id; the result must make a real update check pass)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import io
import json
import shutil
import subprocess
import tempfile
import unittest
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "scripts", "security"))
import github_hardening as H
import pin_update_keys as P
import update_verify

TOKEN = "github_pat_" + "Q" * 40


class Hardening(unittest.TestCase):
    def collect(self, argv, environ=None, opener=None):
        lines = []
        rc = H.main(argv, environ={"GITHUB_ADMIN_TOKEN": TOKEN} if environ is None else environ, opener=opener or (lambda *a, **k: None), out=lines.append)
        return rc, "\n".join(lines)

    def test_plan_prints_every_call_and_sends_nothing(self):
        def boom(*a, **k):
            raise AssertionError("plan must not send anything")
        rc, text = self.collect(["plan"], opener=boom)
        self.assertEqual(rc, 0)
        for needle in ("POST https://api.github.com/repos/Dmccottrell/A.I-SML/rulesets", "required_signatures", "gate: result", "refs/heads/main", "environments/release",
                       "deployment-branch-policies", "secret_scanning_push_protection", "default_workflow_permissions", "Nothing was sent"):
            self.assertIn(needle, text)
        self.assertNotIn(TOKEN, text)

    def test_the_ruleset_is_the_one_the_design_needs(self):
        body = next(b for n, m, p, b in H.steps() if n == "ruleset")
        kinds = {r["type"] for r in body["rules"]}
        self.assertTrue({"deletion", "non_fast_forward", "required_signatures", "pull_request", "required_status_checks"} <= kinds)
        pr = next(r for r in body["rules"] if r["type"] == "pull_request")["parameters"]
        self.assertEqual(pr["allowed_merge_methods"], ["squash"])                      # a squash merge is signed by GitHub itself
        self.assertEqual(body["bypass_actors"][0]["bypass_mode"], "pull_request")      # even an admin goes through a pull request
        self.assertEqual(body["conditions"]["ref_name"]["include"], ["refs/heads/main"])

    def test_the_release_environment_only_accepts_main(self):
        calls = [(m, p, b) for n, m, p, b in H.steps() if n == "environment"]
        self.assertEqual(calls[0][2]["deployment_branch_policy"], {"protected_branches": False, "custom_branch_policies": True})
        self.assertEqual(calls[1][2], {"name": "main", "type": "branch"})

    def test_apply_sends_with_the_token_only_in_the_header_and_never_prints_it(self):
        sent = []

        class Reply:
            status = 201

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        rc, text = self.collect(["apply", "--only", "scanning,actions"], opener=lambda req, timeout=0: sent.append(req) or Reply())
        self.assertEqual(rc, 0)
        self.assertEqual(len(sent), 2)
        for req in sent:
            self.assertEqual(req.get_header("Authorization"), "Bearer " + TOKEN)
            self.assertNotIn(TOKEN, req.full_url)
            self.assertNotIn(TOKEN.encode(), req.data)
            self.assertTrue(req.full_url.startswith("https://api.github.com/"))
        self.assertNotIn(TOKEN, text)

    def test_a_refusal_is_reported_in_plain_words_and_fails_the_run(self):
        def refuse(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, 422, "x", {}, io.BytesIO(b'{"message": "Validation Failed: name already exists"}'))
        rc, text = self.collect(["apply", "--only", "ruleset"], opener=refuse)
        self.assertEqual(rc, 1)
        self.assertIn("422 Validation Failed: name already exists", text)
        self.assertNotIn(TOKEN, text)

    def test_apply_without_a_token_does_nothing(self):
        rc, text = self.collect(["apply"], environ={})
        self.assertEqual(rc, 2)
        self.assertIn("GITHUB_ADMIN_TOKEN", text)

    def test_variables_are_created_when_given(self):
        rc, text = self.collect(["plan", "--only", "variables", "--variable", "ANDROID_CERT_SHA256=" + "ab" * 32])
        self.assertIn("actions/variables", text)
        self.assertIn("ANDROID_CERT_SHA256", text)


HAVE_GPG = shutil.which("gpg") is not None and shutil.which("git") is not None


@unittest.skipUnless(HAVE_GPG, "needs git and gpg")
class Pin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pk")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        home = os.path.join(self.tmp, "k")
        os.makedirs(home, mode=0o700)
        subprocess.run(["gpg", "--homedir", home, "--batch", "--passphrase", "", "--quick-generate-key", "gh <gh@example.test>", "ed25519", "sign", "never"], check=True, capture_output=True)
        self.home = home
        colon = subprocess.run(["gpg", "--homedir", home, "--list-keys", "--with-colons"], capture_output=True, text=True).stdout
        self.fpr = next(l.split(":")[9] for l in colon.splitlines() if l.startswith("fpr:")).upper()
        self.public = subprocess.run(["gpg", "--homedir", home, "--armor", "--export", self.fpr], capture_output=True, text=True).stdout
        self.data = os.path.join(self.tmp, ".emvryx")
        os.makedirs(self.data)
        self.lines = []

    def run_pin(self, key_id, *argv, key=None):
        old = P.WEB_FLOW_KEY_ID
        P.WEB_FLOW_KEY_ID = key_id
        self.addCleanup(setattr, P, "WEB_FLOW_KEY_ID", old)
        return P.main(["--data", self.data, *argv], download=lambda url: key or self.public, out=self.lines.append, root=self.tmp)

    def test_a_key_with_the_published_id_is_pinned_with_its_full_fingerprint(self):
        rc = self.run_pin(self.fpr[-16:], "--mode", "enforce")
        self.assertEqual(rc, 0, self.lines)
        with open(os.path.join(self.data, "update_trust.json")) as f:
            trust = json.load(f)
        self.assertEqual((trust["mode"], trust["fingerprints"], trust["remote"]), ("enforce", [self.fpr], P.REMOTE))
        self.assertTrue(os.path.isdir(trust["gnupghome"]))

    def test_a_download_whose_key_id_is_not_the_published_one_is_refused_and_nothing_is_written(self):
        rc = self.run_pin("4AEE18F83AFDEB23")                                      # the real id: this test key does not have it
        self.assertEqual(rc, 1)
        self.assertIn("Nothing was pinned", " ".join(self.lines))
        self.assertFalse(os.path.exists(os.path.join(self.data, "update_trust.json")))

    def test_garbage_instead_of_a_key_is_refused(self):
        self.assertEqual(self.run_pin("4AEE18F83AFDEB23", key="<html>not a key</html>"), 1)

    def test_your_own_key_needs_the_full_fingerprint_you_checked(self):
        path = os.path.join(self.tmp, "mine.asc")
        with open(path, "w") as f:
            f.write(self.public)
        self.assertEqual(P.main(["--data", self.data, "--key-file", path], out=self.lines.append, root=self.tmp), 2)
        self.assertEqual(P.main(["--data", self.data, "--key-file", path, "--accept-fingerprint", "0" * 40], out=self.lines.append, root=self.tmp), 2)
        self.assertEqual(P.main(["--data", self.data, "--key-file", path, "--accept-fingerprint", self.fpr], out=self.lines.append, root=self.tmp), 0)

    def test_what_it_writes_is_exactly_what_the_update_check_reads(self):
        self.run_pin(self.fpr[-16:])
        os.environ["EMVRYX_UPDATE_TRUST"] = os.path.join(self.data, "update_trust.json")
        self.addCleanup(os.environ.pop, "EMVRYX_UPDATE_TRUST", None)
        trust = update_verify.load_trust(self.tmp)
        self.assertEqual((trust["mode"], trust["fingerprints"]), ("warn", [self.fpr]))
        self.assertEqual(trust["gnupghome"], os.path.join(self.data, "update_gpg"))


if __name__ == "__main__":
    unittest.main()
