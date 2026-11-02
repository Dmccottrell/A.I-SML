# Hidden checks for the "url_shortener" coding exercise. The agent never sees this file; it is run afterwards to decide
# whether the agent's shortener/ package works (base-62 codes, shortening, aliases, click counts, saved data).
import os
import tempfile
import unittest

from shortener.codes import decode, encode
from shortener.service import Shortener


class Codes(unittest.TestCase):
    """Checks for the base-62 encode/decode functions."""

    def test_codes(self):
        """Proves known values (0, 61, 62, 3843), that decode reverses encode, and that bad input raises ValueError."""
        # 61 is the last single digit "Z"; 62 rolls over to "10"; 3843 = 62*62 - 1 is "ZZ".
        self.assertEqual([encode(0), encode(61), encode(62), encode(3843)], ["0", "Z", "10", "ZZ"])
        for n in (0, 1, 61, 62, 10001, 987654321):
            self.assertEqual(decode(encode(n)), n)
        with self.assertRaises(ValueError):
            encode(-1)
        with self.assertRaises(ValueError):
            decode("ab!")


class Service(unittest.TestCase):
    """Checks for the Shortener class."""

    def test_shorten_and_resolve(self):
        """Proves the first code is encode(10001), the same url gives the same code, a new url a new code, and clicks are counted."""
        s = Shortener()
        code = s.shorten("https://example.com/a")
        self.assertEqual(code, encode(10001))
        self.assertEqual(s.shorten("https://example.com/a"), code)
        self.assertNotEqual(s.shorten("http://example.com/b"), code)
        self.assertEqual(s.resolve(code), "https://example.com/a")
        # A second resolve makes 2 clicks in total; stats itself must not add a click.
        s.resolve(code)
        self.assertEqual(s.stats(code), {"url": "https://example.com/a", "clicks": 2})
        self.assertIsNone(s.resolve("nope"))
        self.assertIsNone(s.stats("nope"))

    def test_bad_input_and_alias(self):
        """Proves urls without http(s):// are refused, a custom alias works once, and bad aliases (too short/long, spaces, symbols) are refused."""
        s = Shortener()
        for bad in ("example.com", "ftp://x", "https://", ""):
            with self.assertRaises(ValueError):
                s.shorten(bad)
        self.assertEqual(s.shorten("https://x.io", alias="my-link"), "my-link")
        # The alias is already used by another url.
        with self.assertRaises(ValueError):
            s.shorten("https://y.io", alias="my-link")
        for bad in ("ab", "has space", "x" * 31, "bad!"):
            with self.assertRaises(ValueError):
                s.shorten("https://y.io", alias=bad)

    def test_top_and_persistence(self):
        """Proves top(n) orders by clicks (ties by code) and that click counts survive reopening the database file."""
        path = os.path.join(tempfile.mkdtemp(), "links.db")
        s = Shortener(path)
        a, b, c = s.shorten("https://a.io"), s.shorten("https://b.io"), s.shorten("https://c.io", alias="ccc")
        # Click a once, b three times, c once.
        for code, n in ((a, 1), (b, 3), (c, 1)):
            for _ in range(n):
                s.resolve(code)
        # b wins; a and c tie at 1 click, so the one that sorts first by code comes second.
        self.assertEqual(s.top(2), [(b, 3), (min(a, c), 1)])
        # A brand-new Shortener on the same file still sees the 3 clicks.
        self.assertEqual(Shortener(path).stats(b)["clicks"], 3)


if __name__ == "__main__":
    unittest.main()
