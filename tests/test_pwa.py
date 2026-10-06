"""The installable-app (PWA) pieces: manifest, icons, service worker are served without a key and agree with each other."""
import json

from tests.test_app_server import Base, Client


class Pwa(Base):
    def get(self, path):
        return Client(self.port).call("GET", path, raw=True)

    def test_manifest_icons_are_all_served_as_the_right_type(self):
        st, hdr, body = self.get("/manifest.webmanifest")
        self.assertEqual(st, 200)
        m = json.loads(body)
        self.assertEqual(m["display"], "standalone")
        sizes = {(i["sizes"], i["purpose"]) for i in m["icons"]}
        self.assertIn(("192x192", "any"), sizes)
        self.assertIn(("512x512", "any"), sizes)
        self.assertIn(("512x512", "maskable"), sizes)
        for icon in m["icons"]:
            st, hdr, data = self.get(icon["src"])
            self.assertEqual(st, 200, icon["src"])
            self.assertEqual(hdr["Content-Type"], icon["type"])
            if icon["type"] == "image/png":
                self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")

    def test_the_page_points_at_the_phone_icon_and_the_worker_is_served(self):
        st, hdr, page = self.get("/")
        self.assertIn(b'rel="apple-touch-icon"', page)
        self.assertEqual(self.get("/apple-touch-icon.png")[0], 200)
        st, hdr, sw = self.get("/sw.js")
        self.assertEqual(st, 200)
        self.assertIn(b"/api/", sw)                                 # it must leave the API alone
