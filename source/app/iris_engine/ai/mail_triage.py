#  IRIS Source Code
#  Copyright (C) 2026 - iris-ng
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 3 of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#  Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

"""AI mail triage (iris-ng v2, Phase 1).

Runs synchronously inside the mail poller's celery task, BEFORE the alert is
created, so ingested email arrives pre-enriched: suggested severity +
classification (validated against the live catalogs by NAME — lookup ids vary
per deployment), a one-line triage summary, and extracted IOCs.

The IOC half deliberately REUSES ioc_extractor.extract_iocs() — its per-type
regex validation, live IocType resolution, TLP defaulting, noise flagging and
Sigma-RAG grounding — rather than re-prompting for indicators. Because no
analyst reviews these before the alert exists, the promote-time bar applies
(same rationale as working_timeline/ioc_resolver.py): confidence >= 0.7 and
noise-flagged candidates dropped.

Everything here is advisory: the caller treats any raised error as "use the
rule defaults" (fail-soft), and per the never-cache-failures rule nothing is
persisted here — the poller stores the returned dict (or the error string) in
MailIngestLog.ai_triage for audit only.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app import app
from app.iris_engine.ai.openai_client import build_default_client
from app.models.alerts import Severity
from app.models.models import CaseClassification

MAIL_TRIAGE_PROMPT_ID = "MailTriageSystemPrompt-v1"
PROMPT_PATH = Path(__file__).parent.parent.parent / "resources" / "ai_prompts" / "mail_triage.md"

# Suggestions below this keep only the summary; severity/classification fall
# back to the mail rule's defaults (stated in the prompt).
MIN_CONFIDENCE = 0.5

# Promote-time bar for unreviewed IOCs (mirrors working_timeline/ioc_resolver).
IOC_MIN_CONFIDENCE = 0.7

_BODY_CAP = 8000

log = app.logger


class MailTriageError(Exception):
    """Raised when triage cannot proceed; the poller falls back to rule defaults."""


def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _extract_json_block(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9]*\n?", "", stripped)
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    return stripped.strip()


def _severity_index() -> dict[str, int]:
    return {row.severity_name.lower(): row.severity_id for row in Severity.query.all()}


def _classification_index() -> dict[str, int]:
    return {row.name.lower(): row.id
            for row in CaseClassification.query.all() if row.name}


def _extract_mail_iocs(subject: str, body: str) -> list[dict[str, Any]]:
    """Validated IOCs in alert_iocs payload shape. Fail-soft: an extractor
    error must not kill the severity/summary half of triage."""
    try:
        from app.iris_engine.ai.ioc_extractor import extract_iocs
        result = extract_iocs(f"{subject}\n\n{body}", case_id=None)
    except Exception as e:
        log.warning(f"mail triage: IOC extraction failed, continuing without IOCs: {e}")
        return []

    iocs = []
    for item in result.get('iocs') or []:
        if item.get('noise_flag'):
            continue
        if (item.get('confidence') or 0) < IOC_MIN_CONFIDENCE:
            continue
        tags = item.get('tags') or ''
        iocs.append({
            'ioc_value': item['value'],
            'ioc_type_id': item['type_id'],
            'ioc_tlp_id': item.get('tlp_id'),
            'ioc_description': item.get('reason') or 'Extracted from ingested email',
            'ioc_tags': (tags + ',' if tags else '') + 'mail-ingest',
        })
    return iocs


def triage_email(subject: str, body: str, from_addr: str) -> dict[str, Any]:
    """Returns the enrichment dict build_alert_payload() consumes — and which
    the poller stores verbatim in MailIngestLog.ai_triage:

        {'severity_id': int|None, 'classification_id': int|None,
         'summary': str|None, 'confidence': float|None,
         'iocs': [alert_iocs-shaped dicts],
         'model': str, 'prompt_id': str}
    """
    client = build_default_client(timeout=90.0, default_max_tokens=1200,
                                  feature='mail_triage')
    if client is None:
        raise MailTriageError("AI backend is not configured")

    sev_index = _severity_index()
    cls_index = _classification_index()

    # Catalogs snapshotted at request time — admin-added entries are picked up
    # automatically (established rule from the evidence-type suggester).
    user_message = (
        f"## Severity catalog\n{json.dumps(sorted(sev_index))}\n\n"
        f"## Classification catalog\n{json.dumps(sorted(cls_index))}\n\n"
        f"## Email\nFrom: {from_addr}\nSubject: {subject}\n\n"
        f"{(body or '')[:_BODY_CAP]}"
    )

    envelope = client.chat([
        {"role": "system", "content": load_system_prompt()},
        {"role": "user", "content": user_message},
    ])
    raw = client.extract_content(envelope)
    try:
        parsed = json.loads(_extract_json_block(raw))
    except (json.JSONDecodeError, TypeError) as e:
        raise MailTriageError(f"AI backend returned non-JSON content ({e})")
    if not isinstance(parsed, dict):
        raise MailTriageError("AI backend returned a non-object payload")

    confidence = parsed.get('confidence')
    confidence = float(confidence) if isinstance(confidence, (int, float)) else None

    severity_id = None
    classification_id = None
    if confidence is not None and confidence >= MIN_CONFIDENCE:
        sev_name = parsed.get('severity')
        if isinstance(sev_name, str):
            severity_id = sev_index.get(sev_name.strip().lower())
        cls_name = parsed.get('classification')
        if isinstance(cls_name, str):
            classification_id = cls_index.get(cls_name.strip().lower())

    summary = parsed.get('summary')
    summary = summary.strip()[:300] if isinstance(summary, str) and summary.strip() else None

    return {
        'severity_id': severity_id,
        'classification_id': classification_id,
        'summary': summary,
        'confidence': confidence,
        'iocs': _extract_mail_iocs(subject, body),
        'model': client.model,
        'prompt_id': MAIL_TRIAGE_PROMPT_ID,
    }
