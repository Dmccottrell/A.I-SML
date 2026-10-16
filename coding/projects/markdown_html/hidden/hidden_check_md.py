import os
import subprocess
import sys
import tempfile
import unittest

from md import convert
from md.inline import render_inline

HERE = os.path.dirname(os.path.abspath(__file__))


class Inline(unittest.TestCase):
    def test_escape_and_marks(self):
        self.assertEqual(render_inline("a < b & c > d"), "a &lt; b &amp; c &gt; d")
        self.assertEqual(render_inline("**bold** and *it*"), "<strong>bold</strong> and <em>it</em>")
        self.assertEqual(render_inline("see [docs](http://x.io/a)"), 'see <a href="http://x.io/a">docs</a>')

    def test_code_is_left_alone(self):
        self.assertEqual(render_inline("run `a*b*c` now"), "run <code>a*b*c</code> now")
        self.assertEqual(render_inline("`<b>`"), "<code>&lt;b&gt;</code>")


class Blocks(unittest.TestCase):
    def test_example(self):
        self.assertEqual(convert("# Hi\n\nSome *text*\nhere\n\n- a\n- b"),
                         "<h1>Hi</h1>\n<p>Some <em>text</em> here</p>\n<ul><li>a</li><li>b</li></ul>")

    def test_headings_levels_and_no_blank_lines(self):
        self.assertEqual(convert("### Three\ntext\n###### Six"), "<h3>Three</h3>\n<p>text</p>\n<h6>Six</h6>")
        self.assertEqual(convert("#No space"), "<p>#No space</p>")

    def test_list_inline_and_empty(self):
        self.assertEqual(convert("- **x**\n- `y`"), "<ul><li><strong>x</strong></li><li><code>y</code></li></ul>")
        self.assertEqual(convert(""), "")
        self.assertEqual(convert("\n\n"), "")

    def test_paragraphs(self):
        self.assertEqual(convert("one\n\n\ntwo  \nthree"), "<p>one</p>\n<p>two three</p>")

    def test_cli(self):
        d = tempfile.mkdtemp()
        src, dst = os.path.join(d, "in.md"), os.path.join(d, "out.html")
        with open(src, "w", encoding="utf-8") as f:
            f.write("## T\n\nhello **you**\n")
        r = subprocess.run([sys.executable, "-m", "md", src, dst], cwd=HERE, capture_output=True, text=True, timeout=30,
                           env={**os.environ, "PYTHONPATH": HERE})
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(dst, encoding="utf-8") as f:
            self.assertEqual(f.read().strip(), "<h2>T</h2>\n<p>hello <strong>you</strong></p>")


if __name__ == "__main__":
    unittest.main()
