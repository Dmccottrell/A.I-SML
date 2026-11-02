# Command-line entry point: running `python -m md input.md output.html` reads a Markdown file and writes the HTML.
# Python runs this file when the package is started with -m; it is not imported by other code.
import sys

from md.blocks import convert

# sys.argv is the list of words typed on the command line: [program, input, output]. Anything else shows usage help and exits.
if len(sys.argv) != 3:
    sys.exit("usage: python -m md input.md output.html")
# Read the whole input file, convert it, and write the result (utf-8 so non-English letters survive).
with open(sys.argv[1], encoding="utf-8") as f:
    html = convert(f.read())
with open(sys.argv[2], "w", encoding="utf-8") as f:
    f.write(html)
