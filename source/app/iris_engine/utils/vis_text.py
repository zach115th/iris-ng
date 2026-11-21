"""Stored text for the vis.js 4.21 views (iris-ng 2026-11-20).

vis.js 4.21 puts a string it is given as a network node's or edge's `title`, a timeline item's `content` or
`title`, or a timeline group's `content` into the page as HTML. Every such string built from stored text goes
through vis_text(): escaped, with its line breaks kept. A network `label` is drawn on the canvas as plain text and
never goes through it (it would show the entities).

Pure module (no Flask / ORM imports): datamgmt and the blueprints share it.
"""
from html import escape


def vis_text(value):
    """`value` as HTML that shows exactly its text, line breaks kept; None stays None (no tooltip)."""
    if value is None:
        return None
    text = str(value).replace('\r\n', '\n').replace('\r', '\n')
    return escape(text, quote=True).replace('\n', '<br>')
