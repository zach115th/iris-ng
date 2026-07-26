"""
/api/v2/correlation — IOC cross-case correlation endpoints.

All endpoints require authentication and respect per-user case ACL.
No CSRF needed on GET; POST endpoints require X-CSRFToken header per project rule.

Routes:
  GET  /api/v2/correlation/report
       Query params: min_shared (int, default 2), start_date (YYYY-MM-DD),
                     end_date (YYYY-MM-DD)
       Returns the full build_correlation_report() payload.

  GET  /api/v2/correlation/ioc-context
       Query params: ioc_value (str), ioc_type_id (int)
       Returns cross-case context for one IOC value (for the per-IOC modal panel).

  POST /api/v2/correlation/apply-campaign-tag
       Body: { "case_ids": [3, 7], "tag": "campaign:cluster-a3f...",
               "csrf_token": "..." }
       Applies the given tag to all listed cases the user can access.

  POST /api/v2/correlation/cluster-narrative
       Body: { "cluster": {...}, "case_meta": {...}, "csrf_token": "..." }
       Generates a campaign narrative + suggested name for one cluster (stateless,
       not cached server-side — JS caches by cluster_id within the page session).

  GET  /api/v2/correlation/clusters/<cluster_id>/stix
       Query params: min_shared (int, default 2), start_date (YYYY-MM-DD),
                     end_date (YYYY-MM-DD)  — same filter params as /report
       Downloads a self-contained STIX 2.1 bundle for the named cluster:
       identity + TLP:GREEN marking + campaign + N indicators + N relationships.
       If the analyst has already run "Analyze cluster" the cached AI narrative
       enriches the campaign object: suggested_name → campaign.name (machine
       slug moves to aliases), narrative prose → campaign.description.
       Returns 404 when the cluster_id is not found under the current filter params.
"""

import json
from datetime import datetime

from flask import Blueprint, Response, request
from flask_login import current_user

from app.blueprints.access_controls import ac_api_requires
from app.blueprints.rest.endpoints import response_api_success, response_api_error
from app.business.ioc_correlation import (
    build_correlation_report,
    get_ioc_cross_case_context,
)
from app import db
from app.datamgmt.case.case_db import get_case, save_case_tags, get_case_tags
from app.iris_engine.access_control.utils import ac_get_fast_user_cases_access
from app.models.models import Ioc
from app.iris_engine.ai.openai_client import AIClientError

correlation_blueprint = Blueprint(
    'correlation',
    __name__,
    url_prefix='/correlation',
)


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return None


@correlation_blueprint.route('/report', methods=['GET'])
@ac_api_requires()
def correlation_report():
    min_shared = request.args.get('min_shared', 2, type=int)
    if min_shared < 1:
        min_shared = 1

    start_date = _parse_date(request.args.get('start_date'))
    end_date = _parse_date(request.args.get('end_date'))

    report = build_correlation_report(
        user_id=current_user.id,
        min_shared=min_shared,
        start_date=start_date,
        end_date=end_date,
    )

    return response_api_success(report)


@correlation_blueprint.route('/ioc-context', methods=['GET'])
@ac_api_requires()
def ioc_context():
    ioc_value = request.args.get('ioc_value')
    ioc_type_id = request.args.get('ioc_type_id', type=int)

    if not ioc_value or ioc_type_id is None:
        return response_api_error("ioc_value and ioc_type_id are required", 400)

    ctx = get_ioc_cross_case_context(
        ioc_value=ioc_value,
        ioc_type_id=ioc_type_id,
        user_id=current_user.id,
    )

    return response_api_success(ctx)


@correlation_blueprint.route('/apply-campaign-tag', methods=['POST'])
@ac_api_requires()
def apply_campaign_tag():
    data = request.get_json(silent=True) or {}

    case_ids = data.get('case_ids')
    tag = data.get('tag', '').strip()
    shared_ioc_pairs = data.get('shared_ioc_pairs') or []  # [{ioc_value, ioc_type_id}, ...]

    if not case_ids or not isinstance(case_ids, list):
        return response_api_error("case_ids must be a non-empty list", 400)

    if not tag:
        return response_api_error("tag is required", 400)

    # Validate tag shape — must be campaign:cluster-<hex> or campaign:<slug>
    if not tag.startswith('campaign:'):
        return response_api_error("tag must start with 'campaign:'", 400)

    # Honour ACL — only apply to cases the user can see
    accessible = ac_get_fast_user_cases_access(current_user.id)
    if accessible:
        case_ids = [c for c in case_ids if c in accessible]

    applied = []
    skipped = []

    for case_id in case_ids:
        case = get_case(case_id)
        if not case:
            skipped.append(case_id)
            continue

        existing = get_case_tags(case_id)
        if tag not in existing:
            existing.append(tag)
            # save_case_tags expects a comma-separated string and the ORM case object
            save_case_tags(','.join(existing), case)
            applied.append(case_id)
        else:
            skipped.append(case_id)

    # Tag the shared IOCs across all accessible cases
    iocs_tagged = 0
    if shared_ioc_pairs:
        for pair in shared_ioc_pairs:
            ioc_value = pair.get('ioc_value', '')
            ioc_type_id = pair.get('ioc_type_id')
            if not ioc_value or not ioc_type_id:
                continue
            # Find all IOC rows matching this (value, type) across the accessible cluster cases
            ioc_rows = Ioc.query.filter(
                Ioc.ioc_value == ioc_value,
                Ioc.ioc_type_id == ioc_type_id,
                Ioc.case_id.in_(case_ids),
            ).all()
            for ioc in ioc_rows:
                existing_tags = [t.strip() for t in (ioc.ioc_tags or '').split(',') if t.strip()]
                if tag not in existing_tags:
                    existing_tags.append(tag)
                    ioc.ioc_tags = ','.join(existing_tags)
                    iocs_tagged += 1

        if iocs_tagged:
            db.session.commit()

    return response_api_success({
        "applied": applied,
        "already_tagged": skipped,
        "tag": tag,
        "iocs_tagged": iocs_tagged,
    })


@correlation_blueprint.route('/cluster-narrative', methods=['POST'])
@ac_api_requires()
def cluster_narrative():
    """Generate a campaign narrative + suggested name for one correlation cluster.

    Body JSON:
      {
        "cluster":   { cluster_id, case_ids, shared_ioc_count, shared_iocs,
                       suggested_campaign_tag },
        "case_meta": { "<case_id>": { name, client, open_date, close_date,
                                      classification, severity, case_tags } },
        "csrf_token": "..."
      }

    The caller should pass the cluster + case_meta exactly as received from
    /api/v2/correlation/report (optionally enriched with per-case classification
    and severity already populated by the report endpoint's case_meta dict).

    Returns: { suggested_name, narrative, confidence, prompt_id, cluster_id }
    """
    data = request.get_json(silent=True) or {}

    cluster = data.get('cluster')
    case_meta = data.get('case_meta')

    if not cluster or not isinstance(cluster, dict):
        return response_api_error("'cluster' dict is required", 400)
    if case_meta is None or not isinstance(case_meta, dict):
        return response_api_error("'case_meta' dict is required", 400)
    if not cluster.get('case_ids'):
        return response_api_error("cluster.case_ids must be non-empty", 400)

    force = str(data.get('force', '')).lower() in ('1', 'true', 'yes')

    from app.iris_engine.ai.cluster_narrative import generate_cluster_narrative
    try:
        result = generate_cluster_narrative(cluster=cluster, case_meta=case_meta, force=force)
    except AIClientError as exc:
        return response_api_error(str(exc), 503)
    except Exception as exc:
        from app import app as _app
        _app.logger.exception("cluster_narrative endpoint error")
        return response_api_error(f"Narrative generation failed: {exc}", 500)

    return response_api_success(result)


@correlation_blueprint.route('/clusters/<cluster_id>/stix', methods=['GET'])
@ac_api_requires()
def cluster_stix_export(cluster_id: str):
    """Export a single correlation cluster as a STIX 2.1 bundle (JSON download).

    Uses the same filter params as /report so the cluster is reproducible under
    the same date window and min_shared threshold.  Returns 404 when the cluster
    is not found under the current params (e.g. the threshold changed).
    """
    min_shared = request.args.get('min_shared', 2, type=int)
    if min_shared < 1:
        min_shared = 1

    start_date = _parse_date(request.args.get('start_date'))
    end_date = _parse_date(request.args.get('end_date'))

    report = build_correlation_report(
        user_id=current_user.id,
        min_shared=min_shared,
        start_date=start_date,
        end_date=end_date,
    )

    # Find the requested cluster
    cluster = next(
        (c for c in report.get('clusters', []) if c['cluster_id'] == cluster_id),
        None,
    )
    if cluster is None:
        return response_api_error(
            f"Cluster '{cluster_id}' not found under the current filter params. "
            "The cluster may no longer exist at the requested min_shared / date range.",
            404,
        )

    # Filter all_pairs to those that belong entirely within this cluster's cases
    cluster_case_set = set(cluster['case_ids'])
    pairs_for_cluster = [
        p for p in report.get('pairs', [])
        if cluster_case_set.issuperset(set(p['case_ids']))
    ]

    # Pull cached AI narrative (if the analyst already ran "Analyze cluster")
    narrative = None
    anchor_id = min(cluster['case_ids']) if cluster.get('case_ids') else None
    if anchor_id is not None:
        from app.models.models import CaseAiArtifact
        art = (
            CaseAiArtifact.query
            .filter_by(case_id=anchor_id, kind=f"cluster_narrative:{cluster_id}")
            .order_by(CaseAiArtifact.generated_at.desc())
            .first()
        )
        if art and art.content:
            try:
                narrative = json.loads(art.content)
            except (ValueError, TypeError):
                pass

    from app.iris_engine.stix_export import build_cluster_stix_bundle
    bundle = build_cluster_stix_bundle(
        cluster=cluster,
        pairs_for_cluster=pairs_for_cluster,
        case_meta=report.get('case_meta', {}),
        narrative=narrative,
    )

    bundle_json = json.dumps(bundle, indent=2, ensure_ascii=False)
    safe_id = ''.join(c for c in cluster_id if c.isalnum() or c in '-_')
    filename = f"iris-ng-cluster-{safe_id}-stix21.json"

    return Response(
        bundle_json,
        mimetype='application/json',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )
