#  IRIS-NG Source Code
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 3 of the License, or (at your option) any later version.
"""Triage verdict for a master-timeline event.

The verdict replaces the pair of "Add to summary" / "Display in graph"
checkboxes with a single analyst decision, and drives both of them plus the
card colour.

It needs its own column rather than being derived from the two booleans:
`to_be_determined` and `true_positive` carry the *same* boolean state (both on),
so the flags cannot distinguish them. The flags remain the mechanism -- every
consumer already filters on `event_in_summary` / `event_in_graph` -- but the
verdict is what the analyst sets, and it is the single source of truth for the
colour.

Keep this module as the ONLY place the mapping lives. Every write path
(modal save, working-timeline promote, CSV import, alert escalation) should go
through `apply_verdict()` so a verdict can never disagree with the flags or the
colour it implies.
"""
from __future__ import annotations

VERDICT_TBD = 'to_be_determined'
VERDICT_TRUE_POSITIVE = 'true_positive'
VERDICT_FALSE_POSITIVE = 'false_positive'

DEFAULT_VERDICT = VERDICT_TBD

# label / colour / in_summary / in_graph, in the order they appear in the picker.
# Colours reuse the existing palette: violet is the iris-ng accent already used
# by the timeline rail dots, green/red are the Atlantis success/danger values
# the rest of the UI uses. The trailing 99 is the alpha the colour swatches
# already carried, kept so cards render consistently with pre-verdict events.
VERDICTS: dict[str, dict] = {
    VERDICT_TBD: {
        'label': 'To be determined',
        'color': '#8B5CF699',
        'in_summary': True,
        'in_graph': True,
    },
    VERDICT_TRUE_POSITIVE: {
        'label': 'True positive',
        'color': '#31CE3699',
        'in_summary': True,
        'in_graph': True,
    },
    VERDICT_FALSE_POSITIVE: {
        'label': 'False positive',
        'color': '#F2596199',
        'in_summary': False,
        'in_graph': False,
    },
}

VALID_VERDICTS = tuple(VERDICTS)


def normalise(verdict) -> str:
    """Coerce anything unrecognised -- None, '', a stale value -- to the default.

    Deliberately forgiving: this is reached from API clients and n8n workflows
    that predate the field, and refusing an event because its verdict is absent
    would be a breaking change to a compatible API.
    """
    if isinstance(verdict, str) and verdict in VERDICTS:
        return verdict
    return DEFAULT_VERDICT


def apply_verdict(event, verdict=None):
    """Set `event_verdict` and the three values it determines.

    Pass `verdict=None` to re-apply whatever the event already carries, which is
    how a create path picks up the default.
    """
    resolved = normalise(verdict if verdict is not None else getattr(event, 'event_verdict', None))
    spec = VERDICTS[resolved]
    event.event_verdict = resolved
    event.event_in_summary = spec['in_summary']
    event.event_in_graph = spec['in_graph']
    event.event_color = spec['color']
    return event


def verdict_from_flags(in_summary, in_graph) -> str:
    """Best-effort verdict for a row that predates the column.

    Only an explicit both-off maps to false positive -- that is the one state an
    analyst could previously express to mean "keep this out of the summary and
    the graph". Everything else, including the mixed states and the NULLs left
    by events created before either flag was used, becomes to-be-determined,
    which is the neutral reading and leaves the flags where they already are.
    """
    if in_summary is False and in_graph is False:
        return VERDICT_FALSE_POSITIVE
    return VERDICT_TBD


def choices() -> list[tuple[str, str]]:
    """(value, label) pairs for a SelectField / <option> loop."""
    return [(key, spec['label']) for key, spec in VERDICTS.items()]
