"""Promote-time IOC extraction for working-timeline events.

Called from the working-timeline `promote` endpoint — NEVER at import
time. Mirrors the asset-resolver design: tool-ingested events stay
inert until an analyst signs off, at which point we extract IOCs from
the event's text + raw payload and lazily create any that don't yet
exist in the case, linking each to the freshly-promoted cases_event.

Thin wrapper over the existing AI extractor (`iris_engine.ai.ioc_extractor`).
The extractor already does sigma-RAG-grounded suggestion + per-type regex
sanity + dedup. We add:

    * A higher confidence floor (0.7 vs the extractor's 0.5) — there is no
      analyst-review step here, so we want fewer false positives.
    * Drop noise_flag-tagged candidates (CDN, public DNS, parked, etc.) —
      these are surfaced in the notes flow as a warning, but auto-promote
      should not pull them into the IOC inventory.
    * Find-or-create on (case_id, type_id, value) — same dedup key the
      rest of IRIS-NG uses.
    * Returns the same shape the asset_resolver returns so the promote
      endpoint can wire both reports into the same response envelope.
"""
from __future__ import annotations

from typing import Any

from app import app
from app import db
from app.iris_engine.ai.ioc_extractor import IocExtractorError
from app.iris_engine.ai.ioc_extractor import extract_iocs
from app.models.cases import CaseWorkingEvent
from app.models.models import Ioc

# Tighter than the 0.5 floor used in the notes-extractor flow because
# auto-promote bypasses analyst review. Keep this conservative.
PROMOTE_MIN_CONFIDENCE = 0.7


def _build_extraction_text(working: CaseWorkingEvent) -> str:
    """Concatenate the event's surfaced text into one prompt-friendly blob.

    The Hayabusa parser already pre-formats the Sigma `Details:` and
    `Extra:` blocks into the description (Markdown), and the title carries
    the headline. event_raw['head'] (when present) holds the original
    detail string the parser parsed — included verbatim so the model sees
    the same Cmdline / User / IP fields the analyst sees.
    """
    parts: list[str] = []
    if working.event_title:
        parts.append(working.event_title)
    if working.event_description:
        parts.append(working.event_description)
    raw = working.event_raw or {}
    head = raw.get('head')
    if isinstance(head, str) and head.strip():
        parts.append(head.strip())
    extra = raw.get('extra')
    if isinstance(extra, str) and extra.strip():
        parts.append(extra.strip())
    if working.event_source_host:
        parts.append(f'Host: {working.event_source_host}')
    return '\n\n'.join(parts).strip()


def _find_existing(case_id: int, type_id: int, value: str) -> Ioc | None:
    """IRIS-NG dedup key is case-sensitive on ioc_value (matches case_iocs_db_exists)."""
    return Ioc.query.filter(
        Ioc.case_id == case_id,
        Ioc.ioc_type_id == type_id,
        Ioc.ioc_value == value,
    ).first()


def _ensure_ioc(
    *,
    case_id: int,
    value: str,
    type_id: int,
    tlp_id: int | None,
    description: str | None,
    tags: str | None,
    user_id: int,
) -> tuple[Ioc, bool]:
    """Find-or-create. Returns ``(ioc, created)``."""
    existing = _find_existing(case_id, type_id, value)
    if existing is not None:
        return existing, False

    ioc = Ioc()
    ioc.ioc_value = value
    ioc.ioc_type_id = type_id
    ioc.ioc_tlp_id = tlp_id
    ioc.ioc_description = description or ''
    ioc.ioc_tags = tags or ''
    ioc.user_id = user_id
    ioc.case_id = case_id
    db.session.add(ioc)
    db.session.flush()  # populate ioc_id for the FK link below
    return ioc, True


def ensure_iocs_for_working_event(
    working: CaseWorkingEvent,
    *,
    user_id: int,
    min_confidence: float = PROMOTE_MIN_CONFIDENCE,
) -> dict[str, Any]:
    """Run the AI IOC extractor against this working event and materialize hits.

    Returns:
        ``{
            'ioc_ids':    [int, …],
            'created':    [{'id', 'value', 'type', 'confidence'}, …],
            'reused':     [{'id', 'value', 'type', 'confidence'}, …],
            'skipped':    [{'value', 'type', 'reason'}, …],
            'error':      str | None,  # set if AI extractor failed; promote still proceeds.
        }``

    Errors from the AI extractor (backend down, model timeout, JSON parse
    failure) are caught and reported via the `error` field — promote
    must not fail just because the model is unhappy.
    """
    text = _build_extraction_text(working)
    if not text:
        return {'ioc_ids': [], 'created': [], 'reused': [], 'skipped': [], 'error': None}

    try:
        result = extract_iocs(text, case_id=working.case_id)
    except IocExtractorError as exc:
        app.logger.warning(
            f"IocResolver: AI extraction failed for working event #{working.id} ({exc})"
        )
        return {'ioc_ids': [], 'created': [], 'reused': [], 'skipped': [], 'error': str(exc)}

    candidates = result.get('iocs') or []
    default_tlp = result.get('default_tlp') or {}
    default_tlp_id = default_tlp.get('id') if isinstance(default_tlp, dict) else None

    ioc_ids: list[int] = []
    created: list[dict[str, Any]] = []
    reused: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for c in candidates:
        confidence = float(c.get('confidence') or 0.0)
        value = c.get('value')
        type_id = c.get('type_id')
        type_name = c.get('type')
        if not value or type_id is None:
            continue

        if confidence < min_confidence:
            skipped.append({
                'value': value,
                'type': type_name,
                'reason': f'confidence {confidence:.2f} below {min_confidence:.2f}',
            })
            continue

        noise = c.get('noise_flag')
        if noise:
            skipped.append({
                'value': value,
                'type': type_name,
                'reason': f'noise: {noise}',
            })
            continue

        description = (
            f'Extracted on promote of {working.source} working event '
            f'({working.external_id or working.id})'
        )
        if c.get('reason'):
            description += f' — {c["reason"]}'

        tlp_id = c.get('tlp_id') or default_tlp_id

        ioc, was_created = _ensure_ioc(
            case_id=working.case_id,
            value=value,
            type_id=int(type_id),
            tlp_id=tlp_id,
            description=description,
            tags=c.get('tags') or '',
            user_id=user_id,
        )
        ioc_ids.append(ioc.ioc_id)
        info = {
            'id': ioc.ioc_id,
            'value': ioc.ioc_value,
            'type': type_name,
            'confidence': confidence,
        }
        (created if was_created else reused).append(info)

    return {
        'ioc_ids': ioc_ids,
        'created': created,
        'reused': reused,
        'skipped': skipped,
        'error': None,
    }
