# Inline part of the Markdown converter: things inside one line of text (code, links, bold, italics, HTML escaping).
# Used by md/blocks.py for every heading, paragraph and list item. Reference solution for "markdown_html".
import re


def render_inline(text):
    """Convert one line of Markdown to HTML: `code`, [text](url), **bold**, *italic*. Raw < > & are escaped first.

    Example: "**hi** <b>" becomes "<strong>hi</strong> &lt;b&gt;".
    """
    # Escape HTML characters FIRST (& must go first or we would re-escape our own results). This stops user text
    # from being treated as real HTML tags. The tags we add afterwards are not touched.
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    codes = []

    def keep(m):
        """Replace a `code` span with a placeholder and remember its text, so bold/italic rules cannot change it."""
        codes.append(m.group(1))
        # \x00 is an invisible "null" character that cannot appear in normal text, so it makes a safe marker like \x000\x00.
        return f"\x00{len(codes) - 1}\x00"
    # Pattern: a backtick, any non-backtick characters (captured), a closing backtick.
    text = re.sub(r"`([^`]*)`", keep, text)
    # Links: [label](url). The label is anything but "]"; the url is anything but ")" or spaces. \1 / \2 paste the captured parts.
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', text)
    # Bold before italic, otherwise the two stars of ** would be mistaken for italics. The "?" makes .+ match as little as
    # possible, so two bold parts in one line stay separate.
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    # Put the saved code text back, wrapped in <code> tags (already escaped, and untouched by the rules above).
    return re.sub(r"\x00(\d+)\x00", lambda m: f"<code>{codes[int(m.group(1))]}</code>", text)
