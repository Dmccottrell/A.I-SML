"""The app must answer within seconds of starting, even when Docker (checked for VryxCode's sandbox) is slow or stuck."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@unittest.skipIf(os.name == "nt", "the stand-in docker is a shell script")
class Startup(unittest.TestCase):
    def test_a_stuck_docker_does_not_keep_the_app_from_answering(self):
        d = tempfile.mkdtemp()
        fake = os.path.join(d, "docker")
        with open(fake, "w") as f:
            f.write("#!/bin/sh\nsleep 60\n")                                   # a Docker that never answers
        os.chmod(fake, 0o755)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        p = subprocess.Popen([sys.executable, os.path.join(HERE, "app_server.py"), "--port", str(port), "--data", tempfile.mkdtemp(), "--code-sandbox", "docker"],
                             cwd=HERE, env=dict(os.environ, PATH=d + os.pathsep + os.environ["PATH"]), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (p.terminate(), p.wait(10)))
        t0, status = time.time(), None
        while time.time() - t0 < 12 and status is None:
            try:
                status = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=2).status
            except OSError:
                time.sleep(0.3)
        self.assertEqual(status, 200)
        self.assertLess(time.time() - t0, 10)


if __name__ == "__main__":
    unittest.main()
