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

"""AI Alert-Cluster triage (iris-ng v2, Phase 2).

Generates a triage narrative for one Alert Cluster: what the grouped alerts
most likely represent, why it matters, and concrete next steps. First
consumer of the generic ``AiArtifact`` anchor cache
(anchor_type='alert_cluster', kind='cluster_triage').

Load-bearing rules honoured here:

  - Every COUNT the narrative can cite is computed server-side and passed in
    a ``stats`` block the prompt declares authoritative — the model never
    counts (case-summary evidence-specialist rule).
  - A failed or unparseable AI call is NEVER persisted: parse failure raises
    and the endpoint returns a transient error (feedback rule
    never-cache-failed-ai-calls). Stricter than cluster_narrative's
    raw-text fallback, deliberately.
  - input_hash covers model + prompt + payload; the payload derives purely
    from cluster/alert rows, so no wall-clock value ever lands in the hash
    (cache-key rule).
  - Manual override rides AiOverrideMixin; regeneration over an edit is
    guarded with HTTP 409 at the ENDPOINT layer (rest/v2/alert_clusters).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from collections import Counter
from datetime import datetime
from typing import Any

from app import db
from app.iris_engine.ai.openai_client import AIClientError
from app.iris_engine.ai.openai_client import OpenAIClient
from app.iris_engine.ai.openai_client import build_default_client
from app.models.alerts import Alert
from app.models.alerts import AlertCluster
from app.models.alerts import AlertClusterMember
from app.models.models import AiArtifact

log = logging.getLogger(__name__)

PROMPT_ID = 'AlertClusterTriageSystemPrompt-v1'
FEATURE_KEY = 'alert_cluster_triage'
KIND = 'cluster_triage'
ANCHOR_TYPE = 'alert_cluster'

_PROMPT_PATH = os.path.join(
    os.path.dirname(__file__), '..', '..', 'resources', 'ai_prompts',
    'alert_cluster_triage.md')

# Newest alerts included verbatim; stats cover the full membership.
_ALERT_DETAIL_CAP = 25


class ClusterTriageError(Exception):
    """Raised when triage cannot run or the model output is unusable —
    never persisted, the endpoint renders it as a transient error."""


class ClusterTriageEditError(Exception):
    """Raised when a manual edit cannot be saved or reverted."""


def _load_system_prompt() -> str:
    with open(_PROMPT_PATH, encoding='utf-8') as fh:
        return fh.read()


def build_cluster_payload(cluster: AlertCluster) -> dict[str, Any]:
    """Assemble the prompt payload. All counts are computed HERE from the
    rows — the prompt declares the stats block authoritative over the alert
    sample. Derived purely from stored rows: nothing wall-clock-dependent
    lands in the (hashed) payload."""
    member_rows = (db.session.query(Alert)
                   .join(AlertClusterMember,
                         AlertClusterMember.alert_id == Alert.alert_id)
                   .filter(AlertClusterMember.cluster_id == cluster.id)
                   .order_by(Alert.alert_creation_time.desc(),
                             Alert.alert_id.desc())
                   .all())

    titles = Counter(a.alert_title for a in member_rows if a.alert_title)
    sources = Counter(a.alert_source for a in member_rows if a.alert_source)
    severities = Counter(a.severity.severity_name for a in member_rows
                         if a.severity is not None)
    assets = Counter()
    iocs = Counter()
    for a in member_rows:
        for asset in (a.assets or []):
            if asset.asset_name:
                assets[asset.asset_name] += 1
        for ioc in (a.iocs or []):
            if ioc.ioc_value:
                iocs[ioc.ioc_value] += 1

    detail = []
    for a in member_rows[:_ALERT_DETAIL_CAP]:
        detail.append({
            'alert_id': a.alert_id,
            'title': a.alert_title,
            'severity': a.severity.severity_name if a.severity else None,
            'source': a.alert_source,
            'source_event_time': (a.alert_source_event_time.isoformat()
                                  if a.alert_source_event_time else None),
            'tags': a.alert_tags or '',
            'description': (a.alert_description or '')[:1000],
        })

    return {
        'cluster': {
            'cluster_id': cluster.id,
            'title': cluster.title,
            'rule_name': cluster.rule.name if cluster.rule else None,
            'correlation_values': cluster.correlation_values or {},
            'customer': cluster.customer.name if cluster.customer else None,
            'status': cluster.status,
            'first_alert_at': (cluster.first_alert_at.isoformat()
                               if cluster.first_alert_at else None),
            'last_alert_at': (cluster.last_alert_at.isoformat()
                              if cluster.last_alert_at else None),
        },
        'stats': {
            'alert_count': len(member_rows),
            'alerts_in_detail_list': min(len(member_rows), _ALERT_DETAIL_CAP),
            'distinct_titles': [{'title': t, 'count': c}
                                for t, c in titles.most_common(15)],
            'distinct_sources': [{'source': s, 'count': c}
                                 for s, c in sources.most_common(10)],
            'severity_distribution': dict(severities),
            'distinct_assets': [{'asset': n, 'count': c}
                                for n, c in assets.most_common(20)],
            'distinct_iocs': [{'ioc': v, 'count': c}
                              for v, c in iocs.most_common(20)],
        },
        'alerts': detail,
    }


def _compute_input_hash(payload: dict, system_prompt: str, model: str) -> str:
    canon = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    h = hashlib.md5()
    h.update(model.encode('utf-8'))
    h.update(b'\x00')
    h.update(system_prompt.encode('utf-8'))
    h.update(b'\x00')
    h.update(canon.encode('utf-8'))
    return h.hexdigest()


def get_latest_triage(cluster_id: int) -> AiArtifact | None:
    """Newest stored triage for a cluster regardless of input hash — what
    the analyst is currently looking at (edit/revert/409 guard target)."""
    return (AiArtifact.query
            .filter(AiArtifact.anchor_type == ANCHOR_TYPE,
                    AiArtifact.anchor_id == cluster_id,
                    AiArtifact.kind == KIND)
            .order_by(AiArtifact.generated_at.desc())
            .first())


def _find_cache_hit(cluster_id: int, input_hash: str) -> AiArtifact | None:
    return (AiArtifact.query
            .filter(AiArtifact.anchor_type == ANCHOR_TYPE,
                    AiArtifact.anchor_id == cluster_id,
                    AiArtifact.kind == KIND,
                    AiArtifact.input_hash == input_hash)
            .order_by(AiArtifact.generated_at.desc())
            .first())


def artifact_to_result(art: AiArtifact, *, cached: bool) -> dict[str, Any]:
    """Serialize an artifact row. Reads display_content so an analyst
    correction supersedes model text for every consumer; the untouched model
    output rides along as ai_* fields when edited."""
    try:
        obj = json.loads(art.display_content)
    except (TypeError, ValueError):
        obj = {'suggested_name': 'Cluster triage', 'narrative': art.display_content,
               'confidence': 'low'}
    obj['prompt_id'] = art.prompt_id
    obj['model'] = art.model
    obj['cluster_id'] = art.anchor_id
    obj['cached'] = cached
    obj['generated_at'] = art.generated_at.isoformat() if art.generated_at else None
    obj['artifact_id'] = art.id
    obj['is_edited'] = art.is_edited
    obj['edited_at'] = art.edited_at.isoformat() if art.edited_at else None
    obj['edited_by'] = art.edited_by.name if art.edited_by else None
    if art.is_edited:
        try:
            ai_obj = json.loads(art.content)
        except (TypeError, ValueError):
            ai_obj = {'narrative': art.content, 'suggested_name': 'Cluster triage'}
        obj['ai_narrative'] = ai_obj.get('narrative', '')
        obj['ai_suggested_name'] = ai_obj.get('suggested_name', '')
    return obj


def _parse_response(raw: str) -> dict[str, Any]:
    """Extract and validate the JSON object. RAISES on failure — an
    unparseable response must never be persisted as an artifact."""
    cleaned = re.sub(r'```(?:json)?\s*', '', raw or '').strip().rstrip('`').strip()
    match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if not match:
        raise ClusterTriageError('AI backend returned no JSON object')
    try:
        obj = json.loads(match.group())
    except json.JSONDecodeError as exc:
        raise ClusterTriageError(f'AI backend returned invalid JSON: {exc}')

    narrative = str(obj.get('narrative', '')).strip()
    if not narrative:
        raise ClusterTriageError('AI backend returned an empty narrative')
    return {
        'suggested_name': (str(obj.get('suggested_name', '')).strip()
                           or 'Cluster triage')[:80],
        'narrative': narrative,
        'confidence': (obj.get('confidence')
                       if obj.get('confidence') in ('high', 'medium', 'low')
                       else 'low'),
    }


def generate_cluster_triage(cluster_id: int, *, force: bool = False) -> dict[str, Any]:
    """Generate (or return cached) the triage narrative for one cluster.

    The 409 manual-edit guard is NOT here — it lives in the endpoint so the
    async queue, scripts and API clients all pass through it before this
    runs with force=True.
    """
    cluster = db.session.get(AlertCluster, cluster_id)
    if cluster is None:
        raise ClusterTriageError(f'Alert cluster #{cluster_id} not found')

    client: OpenAIClient | None = build_default_client(
        feature=FEATURE_KEY, timeout=120.0, default_max_tokens=1500)
    if client is None:
        raise ClusterTriageError(
            'AI backend is not configured. Enable it in Manage → Settings → AI.')

    system_prompt = _load_system_prompt()
    payload = build_cluster_payload(cluster)
    input_hash = _compute_input_hash(payload, system_prompt, client.model)

    if not force:
        cached = _find_cache_hit(cluster_id, input_hash)
        if cached is not None:
            log.info('cluster_triage: cache hit (cluster=%s, artifact=%s)',
                     cluster_id, cached.id)
            return artifact_to_result(cached, cached=True)

    messages = [
        {'role': 'system',
         'content': system_prompt + '\n\n' + json.dumps(payload, indent=2, default=str)},
        {'role': 'user',
         'content': 'Triage the cluster above. Output ONLY the JSON object — '
                    'no prose, no markdown fences.'},
    ]

    try:
        resp = client.chat(messages, max_tokens=1500)
        raw = OpenAIClient.extract_content(resp)
    except AIClientError as exc:
        # Transport/auth/timeout: raise, never persist (project rule).
        log.error('cluster_triage: AI call failed — %s', exc)
        raise ClusterTriageError(str(exc))

    result = _parse_response(raw)

    art = AiArtifact(
        anchor_type=ANCHOR_TYPE,
        anchor_id=cluster_id,
        kind=KIND,
        prompt_id=PROMPT_ID,
        model=client.model,
        input_hash=input_hash,
        content=json.dumps(result, ensure_ascii=False),
        confidence=None,
    )
    db.session.add(art)
    db.session.commit()
    log.info('cluster_triage: persisted (cluster=%s, artifact=%s)', cluster_id, art.id)

    return artifact_to_result(art, cached=False)


def save_triage_edit(cluster_id: int, suggested_name: str, narrative: str,
                     user_id: int) -> AiArtifact:
    """Store an analyst correction. `content` keeps the model original;
    confidence carries over from the original (it grades the underlying
    data, not the wording — same policy as cluster_narrative)."""
    art = get_latest_triage(cluster_id)
    if art is None:
        raise ClusterTriageEditError(
            f'Cluster #{cluster_id} has no generated triage to edit')

    name = (suggested_name or '').strip()
    body = (narrative or '').strip()
    if not body:
        raise ClusterTriageEditError('Narrative cannot be empty')
    if not name:
        raise ClusterTriageEditError('Name cannot be empty')

    try:
        original = json.loads(art.content)
    except (TypeError, ValueError):
        original = {}

    art.edited_content = json.dumps({
        'suggested_name': name[:80],
        'narrative': body,
        'confidence': original.get('confidence', 'low'),
    }, ensure_ascii=False)
    art.edited_by_id = user_id
    art.edited_at = datetime.utcnow()
    db.session.commit()
    log.info('cluster_triage: cluster %s edited by user %s (artifact=%s)',
             cluster_id, user_id, art.id)
    return art


def revert_triage_edit(cluster_id: int) -> AiArtifact:
    """Drop the analyst override, restoring the original model output."""
    art = get_latest_triage(cluster_id)
    if art is None:
        raise ClusterTriageEditError(f'Cluster #{cluster_id} has no stored triage')
    if art.is_edited:
        art.edited_content = None
        art.edited_by_id = None
        art.edited_at = None
        db.session.commit()
        log.info('cluster_triage: cluster %s edit reverted (artifact=%s)',
                 cluster_id, art.id)
    return art
