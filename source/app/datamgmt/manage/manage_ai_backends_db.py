#  IRIS Source Code
#
#  Data access for the configured AI backends (iris-ng, 2026-10-09): the
#  `ai_backend` rows that replaced the two ServerSettings slots. Blueprints
#  and business code call these; nothing here imports business.
from __future__ import annotations

from sqlalchemy import func

from app import db
from app.models.models import AiBackend
from app.models.models import ServerSettings


def list_ai_backends() -> list[AiBackend]:
    """Every backend, in display order (position, then id)."""
    return AiBackend.query.order_by(AiBackend.position.asc(), AiBackend.id.asc()).all()


def get_ai_backend(backend_id) -> AiBackend | None:
    try:
        bid = int(backend_id)
    except (TypeError, ValueError):
        return None
    return db.session.get(AiBackend, bid)


def find_ai_backend_by_label(label: str, exclude_id: int | None = None) -> AiBackend | None:
    """The backend whose label equals `label` case-insensitively, if any."""
    q = AiBackend.query.filter(func.lower(AiBackend.label) == (label or '').strip().lower())
    if exclude_id is not None:
        q = q.filter(AiBackend.id != exclude_id)
    return q.first()


def next_ai_backend_position() -> int:
    current = db.session.query(func.max(AiBackend.position)).scalar()
    return (current + 1) if current is not None else 0


def features_pinned_to(settings: ServerSettings, backend_id: int) -> list[str]:
    """Feature keys whose override names `backend_id` (int or digit string)."""
    overrides = settings.ai_feature_overrides or {}
    pinned = []
    for feature, value in overrides.items():
        try:
            if value is not None and int(value) == int(backend_id):
                pinned.append(feature)
        except (TypeError, ValueError):
            continue
    return sorted(pinned)


def clear_feature_overrides_for(settings: ServerSettings, backend_id: int) -> list[str]:
    """Reset to null every feature override that names `backend_id`; returns the
    feature keys touched. Assigns a NEW dict so SQLAlchemy sees the JSONB change."""
    pinned = features_pinned_to(settings, backend_id)
    if pinned:
        overrides = dict(settings.ai_feature_overrides or {})
        for feature in pinned:
            overrides[feature] = None
        settings.ai_feature_overrides = overrides
    return pinned
