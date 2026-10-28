"""private_files.py: the data folder is private on Windows too (icacls), and the tests' privacy check works on both systems."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import tempfile
import types
import unittest
from unittest import mock

import private_files


class Windows(unittest.TestCase):
    def test_the_folder_is_locked_to_this_user_the_system_and_admins(self):
        calls = []
        run = lambda argv, **kw: calls.append(argv) or types.SimpleNamespace(returncode=0, stdout="")     # noqa: E731
        with mock.patch.object(private_files.os, "name", "nt"), mock.patch.dict(os.environ, {"USERNAME": "darryl", "USERDOMAIN": "PC"}):
            self.assertTrue(private_files.lock_folder("D:\\Emvryx\\data", runner=run))
        argv = calls[0]
        self.assertEqual(argv[:4], ["icacls", "D:\\Emvryx\\data", "/inheritance:r", "/grant:r"])       # inherited "Users can read" is removed
        self.assertIn("PC\\darryl:(OI)(CI)F", argv)
        self.assertIn("*S-1-5-18:(OI)(CI)F", argv)                                                      # the system
        self.assertIn("*S-1-5-32-544:(OI)(CI)F", argv)                                                  # administrators
        self.assertFalse(any("S-1-1-0" in a or "Users" in a for a in argv[4:]))

    def test_never_stops_the_app(self):
        def boom(*a, **k):
            raise OSError("no icacls")
        with mock.patch.object(private_files.os, "name", "nt"), mock.patch.dict(os.environ, {"USERNAME": "darryl"}):
            self.assertFalse(private_files.lock_folder("D:\\x", runner=boom))
        self.assertFalse(private_files.lock_folder("/x"))                                               # not Windows: nothing to do

    def test_reading_the_access_list(self):
        mine = "D:\\data\\users.json PC\\darryl:(F)\n NT AUTHORITY\\SYSTEM:(F)\n BUILTIN\\Administrators:(F)\n\nSuccessfully processed 1 files"
        shared = mine.replace("BUILTIN\\Administrators:(F)", "BUILTIN\\Users:(RX)")
        with mock.patch.object(private_files.os, "name", "nt"):
            self.assertTrue(private_files.is_private("x", runner=lambda *a, **k: types.SimpleNamespace(stdout=mine)))
            self.assertFalse(private_files.is_private("x", runner=lambda *a, **k: types.SimpleNamespace(stdout=shared)))
            self.assertFalse(private_files.is_private("x", runner=lambda *a, **k: types.SimpleNamespace(stdout="")))


@unittest.skipIf(os.name == "nt", "the file mode is a Linux and macOS check")
class Posix(unittest.TestCase):
    def test_mode(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a")
            open(p, "w").close()
            os.chmod(p, 0o644)
            self.assertFalse(private_files.is_private(p))
            os.chmod(p, 0o600)
            self.assertTrue(private_files.is_private(p))
            self.assertTrue(private_files.is_private(p, mode=0o600))
            self.assertFalse(private_files.is_private(p, mode=0o400))


if __name__ == "__main__":
    unittest.main()
