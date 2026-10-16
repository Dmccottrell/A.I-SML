import os
import tempfile
import unittest

from shortener.codes import decode, encode
from shortener.service import Shortener


class Codes(unittest.TestCase):
    def test_codes(self):
        self.assertEqual([encode(0), encode(61), encode(62), encode(3843)], ["0", "Z", "10", "ZZ"])
        for n in (0, 1, 61, 62, 10001, 987654321):
            self.assertEqual(decode(encode(n)), n)
        with self.assertRaises(ValueError):
            encode(-1)
        with self.assertRaises(ValueError):
            decode("ab!")


class Service(unittest.TestCase):
    def test_shorten_and_resolve(self):
        s = Shortener()
        code = s.shorten("https://example.com/a")
        self.assertEqual(code, encode(10001))
        self.assertEqual(s.shorten("https://example.com/a"), code)
        self.assertNotEqual(s.shorten("http://example.com/b"), code)
        self.assertEqual(s.resolve(code), "https://example.com/a")
        s.resolve(code)
        self.assertEqual(s.stats(code), {"url": "https://example.com/a", "clicks": 2})
        self.assertIsNone(s.resolve("nope"))
        self.assertIsNone(s.stats("nope"))

    def test_bad_input_and_alias(self):
        s = Shortener()
        for bad in ("example.com", "ftp://x", "https://", ""):
            with self.assertRaises(ValueError):
                s.shorten(bad)
        self.assertEqual(s.shorten("https://x.io", alias="my-link"), "my-link")
        with self.assertRaises(ValueError):
            s.shorten("https://y.io", alias="my-link")
        for bad in ("ab", "has space", "x" * 31, "bad!"):
            with self.assertRaises(ValueError):
                s.shorten("https://y.io", alias=bad)

    def test_top_and_persistence(self):
        path = os.path.join(tempfile.mkdtemp(), "links.db")
        s = Shortener(path)
        a, b, c = s.shorten("https://a.io"), s.shorten("https://b.io"), s.shorten("https://c.io", alias="ccc")
        for code, n in ((a, 1), (b, 3), (c, 1)):
            for _ in range(n):
                s.resolve(code)
        self.assertEqual(s.top(2), [(b, 3), (min(a, c), 1)])
        self.assertEqual(Shortener(path).stats(b)["clicks"], 3)


if __name__ == "__main__":
    unittest.main()
