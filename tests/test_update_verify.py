"""The PC's software update proves the newest commit is the project's own before it installs it (app/update_verify.py): the pinned https address, the certificate
check left on, and a valid GPG signature from a pinned key, all decided by a trust file that lives only on the PC. These tests use real git repositories and real
GPG keys (a key GitHub would use, a stranger's key, no signature at all)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import json
import shutil
import subprocess
import tempfile
import unittest

import update_verify
import browser_check
import updater
from tests.test_app_server import Base
from tests.test_browser_check import find_browser
from tests.test_code_sessions import wait_for

REMOTE = "https://github.com/Dmccottrell/A.I-SML.git"
def gpg_can_sign():
    """True when git and gpg are here AND this computer's gpg can make a signing key in a fresh folder (on the Windows test machine Git's gpg stops with an error
    on that, so these tests, which sign real commits, are skipped there: they need the machine's gpg, they do not test it)."""
    if not (shutil.which("gpg") and shutil.which("git")):
        return False
    home = tempfile.mkdtemp()
    try:
        return subprocess.run(["gpg", "--homedir", home, "--batch", "--passphrase", "", "--quick-generate-key", "probe <probe@example.test>", "ed25519", "sign", "never"],
                              capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        shutil.rmtree(home, ignore_errors=True)


HAVE_GPG = gpg_can_sign()


def run(cwd, *args, env=None):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True, env=dict(os.environ, **(env or {})))


@unittest.skipUnless(HAVE_GPG, "needs git and gpg")
class Verify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="uv")                          # short path: gpg sockets have a length limit
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.origin, self.work, self.other = (os.path.join(self.tmp, n) for n in ("o.git", "w", "x"))
        run(self.tmp, "git", "init", "--bare", "-b", "main", self.origin)
        run(self.tmp, "git", "clone", self.origin, self.work)
        self.g(self.work, "checkout", "-b", "main")
        self.write(self.work, "a.txt", "one\n")
        self.g(self.work, "add", "."), self.g(self.work, "commit", "-m", "first"), self.g(self.work, "push", "-u", "origin", "main")
        run(self.tmp, "git", "clone", self.origin, self.other)
        # the work copy fetches from the local origin but says its address is the project's https one, as on the real PC
        self.g(self.work, "remote", "set-url", "origin", REMOTE)
        self.g(self.work, "config", f"url.{self.origin}.insteadOf", REMOTE)
        self.github, self.stranger = self.new_key("github"), self.new_key("stranger")
        self.pinned = os.path.join(self.tmp, "pinned")                      # the keyring the PC checks against: only GitHub's key
        os.makedirs(self.pinned, mode=0o700)
        public = run(self.tmp, "gpg", "--homedir", self.github[0], "--armor", "--export", self.github[1]).stdout
        subprocess.run(["gpg", "--homedir", self.pinned, "--batch", "--import"], input=public, text=True, check=True, capture_output=True)
        self.trust_file = os.path.join(self.tmp, "update_trust.json")
        os.environ["EMVRYX_UPDATE_TRUST"] = self.trust_file
        self.addCleanup(os.environ.pop, "EMVRYX_UPDATE_TRUST", None)
        os.environ.pop("GIT_SSL_NO_VERIFY", None)

    def g(self, cwd, *args):
        run(cwd, "git", "-c", "user.email=t@t", "-c", "user.name=t", *args)

    def write(self, root, name, text):
        with open(os.path.join(root, name), "w") as f:
            f.write(text)

    def new_key(self, name):
        home = os.path.join(self.tmp, "k-" + name)
        os.makedirs(home, mode=0o700)
        run(self.tmp, "gpg", "--homedir", home, "--batch", "--passphrase", "", "--quick-generate-key", f"{name} <{name}@example.test>", "ed25519", "sign", "never")
        colon = run(self.tmp, "gpg", "--homedir", home, "--list-keys", "--with-colons").stdout
        fpr = next(l.split(":")[9] for l in colon.splitlines() if l.startswith("fpr:"))
        return home, fpr

    def push_change(self, signer=None, text="two\n"):
        """A new commit on origin's main, signed by `signer` (a key from new_key) or not signed at all; returns its full id."""
        self.write(self.other, "a.txt", text)
        self.g(self.other, "add", ".")
        if signer:
            home, fpr = signer
            run(self.other, "git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", f"user.signingkey={fpr}", "-c", "gpg.format=openpgp", "-c", "gpg.program=gpg", "commit", "-S", "-m", "a change",
                env={"GNUPGHOME": home})
        else:
            self.g(self.other, "commit", "-m", "a change")
        self.g(self.other, "push", "origin", "main")
        return run(self.other, "git", "rev-parse", "HEAD").stdout.strip()

    def trust(self, mode="enforce", fingerprints=None, remote=REMOTE):
        with open(self.trust_file, "w") as f:
            json.dump({"mode": mode, "remote": remote, "gnupghome": self.pinned, "fingerprints": [self.github[1]] if fingerprints is None else fingerprints}, f)

    def real_pc_runner(self, args, **kw):
        """The test copy fetches from a local folder (through `url.<folder>.insteadOf`), but a real PC connects to the https address: for the one question about the
        address git connects to, answer as such a PC would; every other command really runs."""
        if args[:3] == ["git", "ls-remote", "--get-url"]:
            return subprocess.CompletedProcess(args, 0, stdout=REMOTE + "\n", stderr="")
        return subprocess.run(args, **kw)

    def updater(self, real_pc=True):
        u = updater.Updater(self.work, restart=lambda: None, runner=self.real_pc_runner if real_pc else subprocess.run)
        u.can_restart = lambda: False
        return u

    # ---- the check
    def test_without_a_trust_file_nothing_changes(self):
        self.push_change(signer=None)
        c = self.updater().check()
        self.assertEqual((c["can_update"], c["verification"]["mode"], c["verification"]["ok"]), (True, "off", None))

    def test_a_commit_signed_by_the_pinned_key_is_installed_exactly_as_checked(self):
        self.trust()
        full = self.push_change(signer=self.github)
        u = self.updater()
        c = u.check()
        self.assertTrue(c["can_update"], c["reason"])
        self.assertEqual((c["verification"]["ok"], c["verification"]["signer"]), (True, self.github[1].upper()))
        self.assertIn("signed by pinned key", " ".join(c["verification"]["checks"]))
        r = u.apply(c["latest"])
        self.assertTrue(r["updated"])
        self.assertEqual(run(self.work, "git", "rev-parse", "HEAD").stdout.strip(), full)       # on the commit that was verified, not on whatever came later

    def test_an_unsigned_commit_is_refused_in_enforce_mode_and_nothing_changes(self):
        self.trust()
        self.push_change(signer=None)
        u = self.updater()
        c = u.check()
        self.assertFalse(c["can_update"])
        self.assertIn("no valid signature", c["reason"])
        with self.assertRaises(updater.UpdateError):
            u.apply(c["latest"])
        with open(os.path.join(self.work, "a.txt")) as f:
            self.assertEqual(f.read(), "one\n")

    def test_a_commit_signed_by_a_stranger_is_refused(self):
        self.trust()
        self.push_change(signer=self.stranger)
        c = self.updater().check()
        self.assertFalse(c["can_update"])
        self.assertFalse(c["verification"]["ok"])

    def test_a_good_signature_from_a_key_that_is_not_in_the_list_is_refused(self):
        self.trust(fingerprints=["0" * 40])                                  # the keyring has the key, but the trust file does not allow it
        self.push_change(signer=self.github)
        c = self.updater().check()
        self.assertFalse(c["can_update"])
        self.assertIn("not pinned", c["reason"])

    def test_warn_mode_shows_the_problem_but_still_allows_the_update(self):
        self.trust(mode="warn")
        self.push_change(signer=None)
        u = self.updater()
        c = u.check()
        self.assertEqual((c["can_update"], c["verification"]["ok"], c["verification"]["mode"]), (True, False, "warn"))
        self.assertTrue(u.apply(c["latest"])["updated"])

    # ---- the connection
    def test_a_different_origin_is_refused_even_when_the_signature_is_good(self):
        self.trust()
        self.push_change(signer=self.github)
        self.g(self.work, "remote", "set-url", "origin", "https://github.com/someone-else/A.I-SML.git")
        self.g(self.work, "config", f"url.{self.origin}.insteadOf", "https://github.com/someone-else/A.I-SML.git")
        c = self.updater().check()
        self.assertFalse(c["can_update"])
        self.assertIn("not the pinned", c["reason"])

    def test_a_url_rewrite_that_redirects_git_elsewhere_is_refused(self):
        self.trust()
        self.push_change(signer=self.github)
        c = self.updater(real_pc=False).check()                              # here git really is redirected (to the local folder): the written address looks right, the real one does not
        self.assertFalse(c["can_update"])
        self.assertIn("redirected", c["reason"])

    def test_switching_off_the_certificate_check_is_refused(self):
        self.trust()
        self.push_change(signer=self.github)
        self.g(self.work, "config", "http.sslVerify", "false")
        c = self.updater().check()
        self.assertFalse(c["can_update"])
        self.assertIn("certificate check is switched off", c["reason"])
        self.g(self.work, "config", "--unset", "http.sslVerify")
        os.environ["GIT_SSL_NO_VERIFY"] = "1"
        self.addCleanup(os.environ.pop, "GIT_SSL_NO_VERIFY", None)
        self.assertFalse(self.updater().check()["can_update"])

    def test_a_damaged_trust_file_makes_updates_stricter_never_looser(self):
        with open(self.trust_file, "w") as f:
            f.write("{ this is not json")
        self.push_change(signer=self.github)
        c = self.updater().check()
        self.assertFalse(c["can_update"])
        self.assertEqual(c["verification"]["mode"], "enforce")

    def test_an_http_pin_is_never_accepted(self):
        self.trust(remote="http://github.com/Dmccottrell/A.I-SML.git")
        self.push_change(signer=self.github)
        self.assertFalse(self.updater().check()["can_update"])


class Parts(unittest.TestCase):
    def test_signer_status_lines_are_read_strictly(self):
        good = "[GNUPG:] GOODSIG AAAA name\n[GNUPG:] VALIDSIG " + "A" * 40 + " 2026-01-01 1 0 4 0 22 8 00 " + "B" * 40
        self.assertEqual(update_verify.signer_from_status(good), (True, ["A" * 40, "B" * 40]))
        for bad in ("[GNUPG:] ERRSIG AAAA 22 8 00 1 9", "[GNUPG:] BADSIG AAAA name", "[GNUPG:] EXPKEYSIG AAAA name", "[GNUPG:] REVKEYSIG AAAA name", "", "gpg: some words"):
            self.assertEqual(update_verify.signer_from_status(bad)[0], False, bad)
        self.assertFalse(update_verify.signer_from_status("[GNUPG:] GOODSIG AAAA name")[0])             # a good signature with no full fingerprint is not enough

    def test_addresses_compare_equal_in_one_form_only(self):
        n = update_verify.normalize_remote
        self.assertEqual(n("https://GitHub.com/Dmccottrell/A.I-SML.git/"), n("https://github.com/dmccottrell/a.i-sml"))
        self.assertNotEqual(n("https://github.com/dmccottrell/a.i-sml"), n("https://github.com/other/a.i-sml"))


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class Screen(Base):
    """Admin > PC > Software update shows the result of the check, and never hides a failure."""
    def card(self, verification, can_update=True):
        from playwright.sync_api import sync_playwright
        p = sync_playwright().start()
        self.addCleanup(p.stop)
        b = p.chromium.launch(executable_path=find_browser())
        self.addCleanup(b.close)
        page = b.new_context(extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{self.port}/")
        wait_for(lambda: page.evaluate("typeof S !== 'undefined' && !!S.state && typeof updateCard === 'function'"))
        reply = {"can_update": can_update, "reason": "" if can_update else "The newest change could not be proven to be the project's own (x), so it will not be installed.", "behind": 1,
                 "current": "aaaaaaaaaaaa", "latest": "bbbbbbbbbbbb", "incoming": [{"sha": "b", "subject": "a change"}], "busy": False, "restart": True, "verification": verification}
        page.evaluate("(r) => { api = async () => ({ok: true, json: async () => r}); const c = updateCard(); c.id = 'testcard'; document.body.append(c); }", reply)
        page.evaluate("[...document.querySelectorAll('#testcard button')].find((b) => b.textContent === 'Check for updates').click()")
        page.wait_for_selector("#testcard .adm-acts + div, #testcard div > p")
        page.wait_for_timeout(300)
        self.assertEqual(errors, [])
        return page

    def test_a_proven_update_says_so(self):
        page = self.card({"mode": "enforce", "ok": True, "signer": "A" * 40, "reason": "", "checks": ["origin is the pinned https address", "signed by pinned key AAAAAAAAAAAAAAAA"]})
        text = page.inner_text("#testcard .update-proof")
        self.assertIn("Proven to be the project", text)
        self.assertIn("signed by pinned key", text)

    def test_a_failed_check_is_shown_in_red_with_its_reason_even_in_warn_mode(self):
        page = self.card({"mode": "warn", "ok": False, "signer": "", "reason": "the newest change has no valid signature from a pinned key", "checks": []})
        text = page.inner_text("#testcard .update-proof")
        self.assertIn("Not proven (warn mode)", text)
        self.assertIn("no valid signature", text)

    def test_with_nothing_pinned_the_card_is_as_before(self):
        page = self.card({"mode": "off", "ok": None, "signer": "", "reason": "", "checks": []})
        self.assertEqual(page.evaluate("document.querySelectorAll('#testcard .update-proof').length"), 0)
        self.assertIn("Update and restart", page.inner_text("#testcard"))

    def test_a_refused_update_still_shows_why(self):
        page = self.card({"mode": "enforce", "ok": False, "signer": "", "reason": "no signing key is pinned", "checks": []}, can_update=False)
        self.assertIn("will not be installed", page.inner_text("#testcard"))
        self.assertIn("Not proven (enforce mode)", page.inner_text("#testcard .update-proof"))


if __name__ == "__main__":
    unittest.main()
