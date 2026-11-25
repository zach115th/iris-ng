"""Stored text for the vis views (iris-ng 2026-11-20; network titles as text 2026-11-25).

vis-timeline 8 (the visual timeline) puts a string it is given as an item's `content` or `title`, or a group's
`content`, into the page as HTML (after its own xss filter). Every such string built from stored text goes through
vis_text(): escaped, with its line breaks kept.

vis-network 10 (the case Graph tab, the alert Relationships graph) shows a string `title` as text - it sets the
tooltip's innerText, where vis 4.21 set its innerHTML - so a network title goes through vis_plain(): the stored text
as typed, its line breaks as "\n" (an escaped title would show its entities). A network `label` is drawn on the
canvas as text and goes through neither.

Pure module (no Flask / ORM imports): datamgmt and the blueprints share it.
"""
from html import escape


def _lines(value):
    return str(value).replace('\r\n', '\n').replace('\r', '\n')


def vis_text(value):
    """`value` as HTML that shows exactly its text, line breaks kept; None stays None (no tooltip)."""
    if value is None:
        return None
    return escape(_lines(value), quote=True).replace('\n', '<br>')


def vis_plain(value):
    """`value` as the text a vis-network tooltip shows, line breaks as "\n"; None stays None (no tooltip)."""
    if value is None:
        return None
    return _lines(value)
