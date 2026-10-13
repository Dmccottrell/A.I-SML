"""web/editor.js (the VryxCode editor's colouring and indent rules), run with Node when it is installed."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import json
import shutil
import subprocess
import unittest

JS = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "web", "editor.js")


def run(expr):
    out = subprocess.run(["node", "-e", f"const E = require({json.dumps(os.path.abspath(JS))}); console.log(JSON.stringify({expr}));"], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("node"), "needs Node.js")
class EditorJs(unittest.TestCase):
    def test_languages_by_extension(self):
        self.assertEqual(run("[E.langOf('a/b/Main.PY'), E.langOf('x.tsx'), E.langOf('i.html'), E.langOf('README.md'), E.langOf('Makefile'), E.langOf('')]"), ["py", "js", "html", "md", "text", "text"])

    def test_python_is_coloured_and_html_in_code_is_escaped(self):
        html = run("E.highlight('def f(x):\\n    return \"a<b\"  # hi\\n', 'py')")
        self.assertIn('<span class="tk-k">def</span>', html)
        self.assertIn('<span class="tk-s">"a&lt;b"</span>', html)
        self.assertIn('<span class="tk-c"># hi</span>', html)
        self.assertNotIn("<b", html.replace("&lt;b", ""))                               # nothing from the file becomes real markup

    def test_other_languages(self):
        self.assertIn('<span class="tk-p">"a"</span>', run("E.highlight('{\"a\": 1, \"b\": true}', 'json')"))
        self.assertIn('<span class="tk-t">&lt;p</span>', run("E.highlight('<p class=\"x\">hi</p>', 'html')"))
        self.assertIn('<span class="tk-c">// c</span>', run("E.highlight('const a = `t`; // c', 'js')"))
        self.assertIn('<span class="tk-k"># Title</span>', run("E.highlight('# Title\\ntext', 'md')"))

    def test_unknown_languages_and_odd_text_never_throw_and_keep_every_character(self):
        self.assertEqual(run("E.highlight('a < b & c', 'text')"), "a &lt; b &amp; c\n")
        text = "x = 'unclosed\n\"\"\"never ends\n/* nor this"
        for lang in ("py", "js", "c", "css", "html", "md", "sql", "yaml", "json", "sh"):
            html = run(f"E.highlight({json.dumps(text)}, {json.dumps(lang)})")
            plain = html.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
            import re
            self.assertEqual(re.sub(r"</?span[^>]*>", "", plain), text + "\n", lang)

    def test_line_diff_marks_removed_added_and_unchanged_lines(self):
        d = run("E.diffLines('a\\nb\\nc', 'a\\nB\\nc\\nd')")
        self.assertEqual([(x["t"], x["s"]) for x in d], [("=", "a"), ("-", "b"), ("+", "B"), ("=", "c"), ("+", "d")])
        self.assertEqual([x["t"] for x in run("E.diffLines('same', 'same')")], ["="])
        self.assertEqual([x["t"] for x in run("E.diffLines('', 'x')")], ["-", "+"])                  # an empty selection: the one empty line goes, the new text comes

    def test_enter_keeps_the_indent_and_adds_one_after_an_opening_line(self):
        self.assertEqual(run("E.indentAfter('def f():\\n    if x:')"), "        ")
        self.assertEqual(run("E.indentAfter('    a = 1')"), "    ")
        self.assertEqual(run("E.indentAfter('items = [')"), "    ")
        self.assertEqual(run("E.indentAfter('')"), "")


if __name__ == "__main__":
    unittest.main()
