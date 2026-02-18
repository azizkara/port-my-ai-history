"""Convert Markdown text to HTML with Pygments syntax highlighting."""

from __future__ import annotations

try:
    import markdown
    from markdown.extensions.codehilite import CodeHiliteExtension
    from markdown.extensions.fenced_code import FencedCodeExtension

    HAS_MARKDOWN = True
except ImportError:
    HAS_MARKDOWN = False


def md_to_html(text: str) -> str:
    """Convert markdown text to HTML with syntax-highlighted code blocks."""
    if not HAS_MARKDOWN:
        # Fallback: basic escaping and <pre> wrapping for code
        import html

        text = html.escape(text)
        text = text.replace("\n", "<br>\n")
        return text

    extensions = [
        FencedCodeExtension(),
        CodeHiliteExtension(css_class="highlight", linenums=False, guess_lang=False),
        "markdown.extensions.tables",
        "markdown.extensions.nl2br",
    ]
    return markdown.markdown(text, extensions=extensions)
