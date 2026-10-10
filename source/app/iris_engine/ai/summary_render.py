#  IRIS Source Code
#
#  Renderer for the verified executive summary (iris-ng, 2026-10-09).
#
#  The writer emits structured, sourced CLAIMS; this module turns them into
#  the ten-section leadership markdown the Executive Case Summary card,
#  the SitRep draft, the room summary, the webhook payload and the reports
#  have always received. Pure: no Flask, no ORM, no clock -- every number
#  and every fixed line comes from `meta`, which the orchestrator computes
#  server-side (counts, activity, task flags, the assets table, evidence
#  integrity). A model never writes a count into the briefing.
#
#  Claims carry no markers in the markdown: both markdown renderers in the
#  product escape HTML, so an inline marker would print. The claim <-> text
#  mapping is served beside the text (GET .../summary/verification).

from __future__ import annotations

from typing import Any

from app.iris_engine.ai.summary_checks import SECTIONS

STATUS_LINES = {
    "critical": "🔴 Critical — Active Threat",
    "high": "🟠 High — Contained but Ongoing",
    "medium": "🟡 Medium — Under Investigation",
    "low": "🟢 Low — Resolved / Monitoring",
}

TIER_SUFFIX = {
    "unverified": " *(unverified)*",
    "third_party_reported": " *(third-party reported)*",
}

EMPTY_LINES = {
    "impact": "Impact assessment is ongoing — no confirmed business impact at this time.",
    "assets": "No assets recorded for this case.",
    "evidence": "No evidence has been registered for this case yet.",
    "findings": "No findings have been established yet.",
    "actions": "No completed response actions are recorded.",
    "outstanding": "No outstanding actions are recorded.",
    "recommendations": "No leadership decisions are required at this time.",
    "timeline": "No timeline events have been recorded yet.",
    "lessons": "No lessons have been recorded for this case.",
    "situation": "The case record does not yet support a situation overview.",
    "status": "The operational state of the case has not been established.",
}

SPARSE_FIELDS = ("assets", "iocs", "timeline_events", "tasks", "notes")
SPARSE_THRESHOLD = 3
TIMELINE_MAX = 8
INACTIVITY_HOURS = 48
FOOTER = ("*This summary was automatically generated from case data and should be reviewed "
          "by the lead analyst before distribution.*")
STREAM_LABELS = {"audit_log": "audit log"}


def is_sparse(counts: dict[str, Any]) -> bool:
    """Fewer than three of assets / iocs / timeline_events / tasks / notes are
    non-zero. `evidence` is deliberately not one of them: a pile of evidence
    with nothing analysed is still too early to brief on."""
    populated = sum(1 for k in SPARSE_FIELDS if (counts or {}).get(k))
    return populated < SPARSE_THRESHOLD


def sparse_fields(counts: dict[str, Any]) -> list[str]:
    return [k for k in SPARSE_FIELDS if (counts or {}).get(k)]


def render_sparse(counts: dict[str, Any]) -> str:
    populated = sparse_fields(counts)
    listed = ", ".join(populated) if populated else "none"
    return ("> This case is too early in triage to produce a meaningful executive summary. "
            f"The following fields are currently populated: {listed}. "
            "Please re-run this summary once the case has been further developed.")


def _plural(n: int, singular: str, plural: str | None = None) -> str:
    return singular if n == 1 else (plural or singular + "s")


def claim_line(claim: dict[str, Any]) -> str:
    text = str(claim.get("text") or "").strip()
    return text + TIER_SUFFIX.get(claim.get("tier"), "")


def _by_section(claims: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {s: [] for s in SECTIONS}
    for c in claims:
        sec = c.get("section")
        if sec in out:
            out[sec].append(c)
    return out


def _paragraph(items: list[dict[str, Any]], empty: str) -> str:
    if not items:
        return empty
    return " ".join(claim_line(c) for c in items)


def _bullets(items: list[dict[str, Any]], empty: str) -> str:
    if not items:
        return empty
    return "\n".join("- " + claim_line(c) for c in items)


def status_flag_lines(meta: dict[str, Any]) -> list[str]:
    """The server-derived lines under Current Status: unassigned tasks,
    overdue tasks, the 48-hour inactivity warning (from `activity`, which
    spans every object type, never from timeline dates)."""
    lines: list[str] = []
    task_flags = meta.get("task_flags") or {}
    unassigned = list(task_flags.get("unassigned") or [])
    overdue = list(task_flags.get("overdue") or [])
    if unassigned:
        lines.append(f"⚠️ {len(unassigned)} open {_plural(len(unassigned), 'task')} "
                     f"{_plural(len(unassigned), 'has', 'have')} no assignee: "
                     + "; ".join(unassigned[:3]) + (" …" if len(unassigned) > 3 else "") + ".")
    if overdue:
        lines.append(f"⚠️ {len(overdue)} {_plural(len(overdue), 'task')} "
                     f"{_plural(len(overdue), 'has', 'have')} been open for more than "
                     f"{int(task_flags.get('overdue_days') or 14)} days without closing: "
                     + "; ".join(overdue[:3]) + (" …" if len(overdue) > 3 else "") + ".")
    activity = meta.get("activity") or {}
    hours = activity.get("hours_since_last_activity")
    if hours is None or hours > INACTIVITY_HOURS:
        line = (f"⚠️ No case activity detected in the last {INACTIVITY_HOURS} hours — "
                "escalation may be warranted.")
        per_type = activity.get("per_type_last_activity") or {}
        freshest = None
        for stream, v in per_type.items():
            if not isinstance(v, dict) or v.get("hours_ago") is None:
                continue
            if freshest is None or v["hours_ago"] < freshest[1]:
                freshest = (stream, v["hours_ago"])
        if freshest is not None:
            label = STREAM_LABELS.get(freshest[0], freshest[0])
            line += f" The most recent change was to the {label} ~{int(round(freshest[1]))} hours ago."
        lines.append(line)
    return lines


def assets_table(rows: list[dict[str, Any]]) -> str:
    """| Asset | Type | Status | from the case record. `rows` carry name,
    type, status (Confirmed compromised / Not compromised / Under
    investigation), already derived server-side from the compromise status."""
    if not rows:
        return EMPTY_LINES["assets"]
    out = ["| Asset | Type | Status |", "|---|---|---|"]
    for r in rows:
        cells = [str(r.get("name") or "").replace("|", "/"),
                 str(r.get("type") or "").replace("|", "/"),
                 str(r.get("status") or "Under investigation").replace("|", "/")]
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def evidence_counts_sentence(integrity: dict[str, Any]) -> str:
    total = int(integrity.get("items_total") or 0)
    hashed = int(integrity.get("items_with_hash") or 0)
    return (f"{total} {_plural(total, 'item')} {_plural(total, 'has', 'have')} been preserved; "
            f"{hashed} of the {total} {_plural(hashed, 'carries', 'carry')} a recorded hash.")


def integrity_notes(integrity: dict[str, Any]) -> list[str]:
    """Preservation gaps in business terms, from the server counts only."""
    total = int(integrity.get("items_total") or 0)
    notes: list[str] = []
    missing = int(integrity.get("items_missing_hash") or 0)
    if missing:
        notes.append(f"{missing} of {total} preserved {_plural(total, 'item')} "
                     f"{_plural(missing, 'has', 'have')} no recorded hash, which weakens "
                     f"{'its' if missing == 1 else 'their'} evidentiary value.")
    unlinked = int(integrity.get("items_without_asset_link") or 0)
    if unlinked:
        notes.append(f"{unlinked} of {total} {_plural(total, 'item')} "
                     f"{_plural(unlinked, 'is', 'are')} not linked to the system "
                     f"{'it' if unlinked == 1 else 'they'} came from.")
    nowindow = int(integrity.get("items_without_coverage_window") or 0)
    if nowindow:
        notes.append(f"{nowindow} of {total} {_plural(total, 'item')} "
                     f"{_plural(nowindow, 'has', 'have')} no recorded coverage window.")
    return notes


def _timeline_block(items: list[dict[str, Any]]) -> str:
    if not items:
        return EMPTY_LINES["timeline"]
    ordered = sorted(items, key=lambda c: str(c.get("event_time") or ""))[:TIMELINE_MAX]
    return "\n\n".join(f"{str(c.get('event_time') or '').strip()} — {claim_line(c)}" for c in ordered)


def render_claims_markdown(case: dict[str, Any], claims: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    """The full briefing. `case`: name, classification (e.g. TLP:AMBER),
    generated_on (YYYY-MM-DD), is_closed. `meta`: status, counts, activity,
    task_flags {unassigned, overdue, overdue_days}, assets [{name,type,status}],
    evidence_integrity."""
    by = _by_section(claims)
    counts = meta.get("counts") or {}
    integrity = meta.get("evidence_integrity") or {}
    status_key = str(meta.get("status") or "medium").lower()
    status_line = STATUS_LINES.get(status_key, STATUS_LINES["medium"])

    parts: list[str] = [
        "---",
        f"# Incident Summary — {case.get('name') or ''}",
        f"**Classification:** {case.get('classification') or 'TLP:AMBER'}",
        f"**Report Generated:** {case.get('generated_on') or ''}",
        "**Prepared By:** Automated Threat Intelligence System",
        "",
        "---",
        "",
        "## Situation Overview",
        _paragraph(by["situation"], EMPTY_LINES["situation"]),
        "",
        "## Current Status",
        f"**{status_line}**",
        "",
        _paragraph(by["status"], EMPTY_LINES["status"]),
    ]
    flag_lines = status_flag_lines(meta)
    if flag_lines:
        parts.append("")
        parts.append("\n\n".join(flag_lines))
    parts += [
        "",
        "## Business Impact",
        _bullets(by["impact"], EMPTY_LINES["impact"]),
        "",
        "## Affected Assets",
        assets_table(list(meta.get("assets") or [])),
        "",
        "## Evidence Preservation",
    ]
    if not counts.get("evidence"):
        parts.append(EMPTY_LINES["evidence"])
    else:
        ev_para = evidence_counts_sentence(integrity)
        if by["evidence"]:
            ev_para += " " + " ".join(claim_line(c) for c in by["evidence"])
        parts.append(ev_para)
        notes = integrity_notes(integrity)
        if notes:
            parts.append("")
            parts.append("\n".join("- " + n for n in notes))
    parts += [
        "",
        "## Key Findings",
        _bullets(by["findings"], EMPTY_LINES["findings"]),
        "",
        "## Actions Taken",
        _bullets(by["actions"], EMPTY_LINES["actions"]),
        "",
        "## Outstanding Actions",
        _bullets(by["outstanding"], EMPTY_LINES["outstanding"]),
        "",
        "## Recommendations for Leadership",
        _bullets(by["recommendations"], EMPTY_LINES["recommendations"]),
        "",
        "## Timeline of Key Events",
        _timeline_block(by["timeline"]),
    ]
    if case.get("is_closed"):
        parts += [
            "",
            "## Lessons Learned",
            _paragraph(by["lessons"], EMPTY_LINES["lessons"]),
        ]
    parts += ["", "---", FOOTER]
    return "\n".join(parts) + "\n"


__all__ = ["STATUS_LINES", "TIER_SUFFIX", "EMPTY_LINES", "SPARSE_FIELDS", "SPARSE_THRESHOLD", "TIMELINE_MAX",
           "INACTIVITY_HOURS", "FOOTER", "is_sparse", "sparse_fields", "render_sparse", "claim_line",
           "status_flag_lines", "assets_table", "evidence_counts_sentence", "integrity_notes",
           "render_claims_markdown"]
