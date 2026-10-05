"""Tests for prepare_web_data.prefer_long: short web pages are thinned out for long-context versions, deterministically."""
import unittest

import config
import prepare_web_data as P


def docs():
    for i in range(2000):
        yield ("short page %d " % i) * 20 if i % 2 == 0 else ("long page %d " % i) * 600


class PreferLong(unittest.TestCase):
    def test_every_long_page_is_kept_and_about_40_percent_of_short_ones(self):
        out = list(P.prefer_long(docs)())
        long_kept = sum(1 for t in out if len(t) >= P.LONG_MIN_CHARS)
        short_kept = len(out) - long_kept
        self.assertEqual(long_kept, 1000)
        self.assertTrue(300 <= short_kept <= 500, short_kept)

    def test_same_documents_in_the_same_order_every_time(self):
        self.assertEqual(list(P.prefer_long(docs)()), list(P.prefer_long(docs)()))

    def test_only_long_context_versions_and_web_sources_are_thinned(self):
        v35 = {n: loader for n, loader, _ in P.sources_for(config.VERSIONS["v3.5"])}
        v3 = {n: loader for n, loader, _ in P.sources_for(config.VERSIONS["v3"])}
        self.assertIsNot(v35["fineweb_100bt"], P.LOADERS["fineweb_100bt"])
        self.assertIs(v35["wikipedia"], P.LOADERS["wikipedia"])
        self.assertIs(v35["math"], P.LOADERS["math"])
        self.assertIs(v3["fineweb"], P.LOADERS["fineweb"])           # v3 (2,048) is unchanged


if __name__ == "__main__":
    unittest.main()
