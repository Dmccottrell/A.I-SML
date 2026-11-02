"""A sweep of every API address found in the route files: without a sign-in only the few public ones answer, a normal person cannot reach any admin address, and
file addresses cannot be tricked into serving the server's own source. New routes are picked up by themselves, so a route added without a sign-in check fails here."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import glob
import http.client
import re
import unittest

from tests.test_app_server import Base

HERE = os.path.dirname(os.path.abspath(__file__))
# The addresses that are meant to be open to someone who is not signed in (the sign-in page needs them).
PUBLIC = {"/api/auth-options", "/api/status", "/api/login/email/start"}


def api_paths():
    """Every /api address named in the route files, with each (group) of a pattern replaced by 1, so it can be called."""
    found = set()
    for f in glob.glob(os.path.join(HERE, os.pardir, "app", "routes_*.py")):
        with open(f, encoding="utf-8") as fh:
            src = fh.read()
        found.update(m.group(1) for m in re.finditer(r'path == "(/api[^"]*)"', src))
        for m in re.finditer(r'fullmatch\(r"(/api[^"]*)"', src):
            found.add(re.sub(r"\([^)]*\)", "1", m.group(1)).replace("\\", "").replace("?", ""))
    return sorted(found)


class Access(Base):
    def test_the_sweep_finds_the_routes(self):
        self.assertGreater(len(api_paths()), 100)                         # the regex still finds the routes (if the code is rewritten, update it)

    def test_without_a_sign_in_only_the_public_addresses_answer(self):
        open_ones = []
        for p in api_paths():
            for method in ("GET", "POST"):
                st, _ = self.owner.call(method, p, {} if method == "POST" else None, bearer=False)
                if st not in (401, 403, 404, 405) and p not in PUBLIC:
                    open_ones.append((method, p, st))
        self.assertEqual(open_ones, [], "these answered without a sign-in: add the check, or (only if meant to be public) add them to PUBLIC")

    def test_a_normal_person_cannot_reach_the_admin_addresses(self):
        reached = []
        for p in api_paths():
            if not (p.startswith("/api/admin") or "/admin/" in p):
                continue
            for method in ("GET", "POST"):
                st, _ = self.sam.call(method, p, {} if method == "POST" else None)
                if st not in (401, 403, 404, 405):
                    reached.append((method, p, st))
        self.assertEqual(reached, [])

    def test_file_addresses_do_not_serve_the_servers_own_files(self):
        for probe in ("/js/..%2f..%2fapp%2fauth.py", "/../app/auth.py", "/js/../../app/auth.py", "/%2e%2e/%2e%2e/app/auth.py", "/js/auth.js%00.py", "/web/../CLAUDE.md"):
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            c.request("GET", probe)
            r = c.getresponse()
            body = r.read().decode("utf-8", "replace")
            c.close()
            self.assertNotIn("def ", body[:2000], probe)                   # no Python source
            self.assertNotIn("Emvryx (A.I-SML): rules", body, probe)       # no project notes
            self.assertNotEqual(r.status, 500, probe)


if __name__ == "__main__":
    unittest.main()
