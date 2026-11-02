# Hidden checks for the "markdown_html" coding exercise. The agent never sees this file; it is run afterwards to decide
# whether the agent's md/ package really converts Markdown to HTML (inline rules, block rules, and the command line).
import os
import subprocess
import sys
import tempfile
import unittest

from md import convert
from md.inline import render_inline

# The folder this check file lives in; the command-line test runs from here so `python -m md` finds the md package.
HERE = os.path.dirname(os.path.abspath(__file__))


class Inline(unittest.TestCase):
    """Checks for render_inline (formatting inside one line)."""

    def test_escape_and_marks(self):
        """Proves < > & are escaped, **bold** and *italic* become tags, and [text](url) becomes a link."""
        self.assertEqual(render_inline("a < b & c > d"), "a &lt; b &amp; c &gt; d")
        self.assertEqual(render_inline("**bold** and *it*"), "<strong>bold</strong> and <em>it</em>")
        self.assertEqual(render_inline("see [docs](http://x.io/a)"), 'see <a href="http://x.io/a">docs</a>')

    def test_code_is_left_alone(self):
        """Proves text inside `backticks` is not formatted (the stars stay) but is still escaped."""
        self.assertEqual(render_inline("run `a*b*c` now"), "run <code>a*b*c</code> now")
        self.assertEqual(render_inline("`<b>`"), "<code>&lt;b&gt;</code>")


class Blocks(unittest.TestCase):
    """Checks for convert (headings, paragraphs, lists)."""

    def test_example(self):
        """Proves a mixed document: heading, a two-line paragraph joined into one, then a bullet list."""
        self.assertEqual(convert("# Hi\n\nSome *text*\nhere\n\n- a\n- b"),
                         "<h1>Hi</h1>\n<p>Some <em>text</em> here</p>\n<ul><li>a</li><li>b</li></ul>")

    def test_headings_levels_and_no_blank_lines(self):
        """Proves heading levels 3 and 6 work without blank lines between blocks, and "#" with no space is plain text."""
        self.assertEqual(convert("### Three\ntext\n###### Six"), "<h3>Three</h3>\n<p>text</p>\n<h6>Six</h6>")
        self.assertEqual(convert("#No space"), "<p>#No space</p>")

    def test_list_inline_and_empty(self):
        """Proves list items get inline formatting, and empty or blank-only input gives an empty string."""
        self.assertEqual(convert("- **x**\n- `y`"), "<ul><li><strong>x</strong></li><li><code>y</code></li></ul>")
        self.assertEqual(convert(""), "")
        self.assertEqual(convert("\n\n"), "")

    def test_paragraphs(self):
        """Proves several blank lines count as one break, and trailing spaces and line breaks inside a paragraph become single spaces."""
        self.assertEqual(convert("one\n\n\ntwo  \nthree"), "<p>one</p>\n<p>two three</p>")

    def test_cli(self):
        """Proves `python -m md in.md out.html` exits with 0 and writes the converted HTML to the output file."""
        d = tempfile.mkdtemp()
        src, dst = os.path.join(d, "in.md"), os.path.join(d, "out.html")
        with open(src, "w", encoding="utf-8") as f:
            f.write("## T\n\nhello **you**\n")
        # Run the converter as a separate program; PYTHONPATH tells it where the md package is, timeout stops a hang.
        r = subprocess.run([sys.executable, "-m", "md", src, dst], cwd=HERE, capture_output=True, text=True, timeout=30,
                           env={**os.environ, "PYTHONPATH": HERE})
        # The second argument is the message shown if this fails (the program's error output).
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(dst, encoding="utf-8") as f:
            self.assertEqual(f.read().strip(), "<h2>T</h2>\n<p>hello <strong>you</strong></p>")


if __name__ == "__main__":
    unittest.main()
