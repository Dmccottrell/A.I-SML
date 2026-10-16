import sys

from md.blocks import convert

if len(sys.argv) != 3:
    sys.exit("usage: python -m md input.md output.html")
with open(sys.argv[1], encoding="utf-8") as f:
    html = convert(f.read())
with open(sys.argv[2], "w", encoding="utf-8") as f:
    f.write(html)
