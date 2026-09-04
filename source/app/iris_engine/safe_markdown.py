"""Markdown rendering that is safe to inject into the DOM.

`mistletoe.markdown()` implements CommonMark, which passes raw HTML through
verbatim -- `<img src=x onerror=...>` in a note survives rendering and executes
in the analyst's browser. Any surface that renders analyst-supplied markdown and
injects the result as HTML must use `render_markdown_safe()` instead.

Why a renderer subclass rather than a sanitiser library: `docx_generator 0.8.0`
hard-pins `mistletoe==0.7.2` as part of the deliberately frozen .docx reporter
stack, so mistletoe cannot be upgraded to a version with `process_html_tokens`,
and adding a sanitiser dependency would mean rebuilding the app image. Escaping
at render time needs neither, and keeps tables/lists/code intact.
"""

import html

from mistletoe import Document
from mistletoe.html_renderer import HTMLRenderer

# Schemes that execute script when placed in an href. Compared after all
# whitespace is stripped, because browsers tolerate `java\tscript:`.
_DANGEROUS_SCHEMES = ('javascript:', 'data:', 'vbscript:')


def _is_dangerous_target(target: str) -> bool:
    return ''.join((target or '').split()).lower().startswith(_DANGEROUS_SCHEMES)


class SafeHTMLRenderer(HTMLRenderer):
    """HTMLRenderer that escapes raw HTML instead of emitting it verbatim.

    Markdown formatting -- tables, lists, emphasis, code, safe links -- renders
    exactly as before. Only raw HTML and script-bearing URLs are neutralised.
    """

    def render_html_block(self, token):
        return html.escape(token.content)

    def render_html_span(self, token):
        return html.escape(token.content)

    def render_link(self, token):
        if _is_dangerous_target(token.target):
            # Keep the link text, drop the URL entirely.
            return self.render_inner(token)
        return super().render_link(token)

    def render_auto_link(self, token):
        if _is_dangerous_target(token.target):
            return html.escape(token.target)
        return super().render_auto_link(token)


def render_markdown_safe(text: str) -> str:
    """Render markdown to HTML with raw HTML escaped and unsafe URLs stripped.

    The result is safe to inject into the DOM without further escaping.
    """
    if not text:
        return ''

    with SafeHTMLRenderer() as renderer:
        return renderer.render(Document(text))
