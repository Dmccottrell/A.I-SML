# Package marker for the small Markdown-to-HTML converter (reference solution for the "markdown_html" exercise).
# It re-exports convert() so users can write `from md import convert`. The noqa note tells the linter the import is
# intentionally "unused" here (it exists only to be re-exported).
from md.blocks import convert  # noqa: F401
