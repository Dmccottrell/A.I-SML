"""tools/comments_only.py: the check that explaining code with comments never changes what the code does."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import importlib.util
import unittest

_spec = importlib.util.spec_from_file_location("comments_only", os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "tools", "comments_only.py"))
co = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(co)


class Python(unittest.TestCase):
    def test_comments_docstrings_and_spacing_do_not_count(self):
        a = 'def f(x):\n    return x + 1\n'
        b = 'def f(x):\n    """Adds one."""\n    # the plus is the whole point\n\n    return x   +   1  # done\n'
        self.assertEqual(co.python_shape(a), co.python_shape(b))

    def test_a_real_change_is_seen(self):
        self.assertNotEqual(co.python_shape('def f(x):\n    return x + 1\n'), co.python_shape('def f(x):\n    return x + 2\n'))
        self.assertNotEqual(co.python_shape('x = "a"\n'), co.python_shape('x = "b"\n'))      # a string that is not a docstring is code


class CLike(unittest.TestCase):
    def test_comments_do_not_count_but_strings_do(self):
        a = 'val u = "http://x"\nfun f() = 1\n'
        b = '/** Doc */\nval u = "http://x" // the address\n/* block */\nfun   f() =  1\n'
        self.assertEqual(co.c_like_shape(a), co.c_like_shape(b))
        self.assertNotEqual(co.c_like_shape('val u = "http://x"'), co.c_like_shape('val u = "http://y"'))
        self.assertNotEqual(co.c_like_shape('fun f() = 1'), co.c_like_shape('fun f() = 2'))

    def test_a_javascript_regex_with_a_quote_in_it_does_not_hide_the_code(self):
        # /[`'"]/g looks like the start of a string to a naive reader; a comment added after it must still be "comments only"
        a = "const r = /[`'\"]/g;\nlet x = 1;\n"
        b = "const r = /[`'\"]/g; // strips quotes\n// next line sets x\nlet x = 1;\n"
        self.assertEqual(co.c_like_shape(a, regex=True), co.c_like_shape(b, regex=True))
        self.assertNotEqual(co.c_like_shape(a, regex=True), co.c_like_shape(a.replace("= 1", "= 2"), regex=True))

    def test_a_double_slash_inside_a_raw_string_is_not_a_comment(self):
        self.assertNotEqual(co.c_like_shape('val s = """a // b"""'), co.c_like_shape('val s = """a """'))


class OtherKinds(unittest.TestCase):
    def test_html_xml_and_hash_files(self):
        self.assertEqual(co.shape("a.html", "<p>hi</p><script>var a = 1;</script>"), co.shape("a.html", "<!-- note -->\n<p>hi</p>\n<script>\n// say\nvar a = 1;\n</script>"))
        self.assertNotEqual(co.shape("a.html", "<script>var a = 1;</script>"), co.shape("a.html", "<script>var a = 2;</script>"))
        self.assertEqual(co.shape("a.xml", "<a><b/></a>"), co.shape("a.xml", "<!-- why -->\n<a>\n  <b/>\n</a>"))
        self.assertEqual(co.shape("a.yml", "on: push\njobs: x"), co.shape("a.yml", "# what\non: push\n\n  # more\njobs: x"))
        self.assertNotEqual(co.shape("a.yml", "on: push"), co.shape("a.yml", "on: pull"))
        self.assertEqual(co.shape("a.css", "a { color: red; }"), co.shape("a.css", "/* links */ a { color: red; }"))


if __name__ == "__main__":
    unittest.main()
