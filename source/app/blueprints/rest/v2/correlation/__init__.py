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
from app.blueprints.responses import response
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
    discard_edit = str(data.get('discard_edit', '')).lower() in ('1', 'true', 'yes')

    # Manual-edit guard: regeneration inserts a new artifact row and reads take
    # the latest, so re-running over an edited narrative silently orphans the
    # analyst's corrections. Server-side so API clients are covered too.
    if not discard_edit:
        from app.iris_engine.ai.cluster_narrative import get_latest_cluster_narrative
        anchor = min(cluster['case_ids'])
        existing = get_latest_cluster_narrative(anchor, str(cluster.get('cluster_id') or ''))
        if existing is not None and existing.is_edited:
            # Real 409 Conflict. NB: response_api_error()'s second positional is
            # `data`, not a status code, and it always emits 400 — the existing
            # `response_api_error(str(exc), 503)` calls in this file are
            # therefore 400s carrying data:503. Build the body via response()
            # so the client can branch on the status.
            return response(409, data={
                'message': (
                    'This narrative has been manually edited. Re-running will '
                    'discard those edits — retry with discard_edit=true to '
                    'confirm, or revert the edit first.'
                ),
                'data': {
                    'reason': 'manual_edit_present',
                    'edited_at': existing.edited_at.isoformat() if existing.edited_at else None,
                    'edited_by': existing.edited_by.name if existing.edited_by else None,
                }
            })

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


def _anchor_from_body(data: dict):
    """Resolve (anchor_case_id, cluster_id) from an edit request body.

    The anchor is min(case_ids) — the same convention generate_cluster_narrative
    uses to pick which case row the artifact hangs off.
    """
    cluster_id = str(data.get('cluster_id') or '').strip()
    case_ids = data.get('case_ids')
    if not cluster_id:
        return None, None, "'cluster_id' is required"
    if not isinstance(case_ids, list) or not case_ids:
        return None, None, "'case_ids' must be a non-empty list"
    try:
        anchor = min(int(c) for c in case_ids)
    except (TypeError, ValueError):
        return None, None, "'case_ids' must be integers"
    return anchor, cluster_id, None


@correlation_blueprint.route('/cluster-narrative/edit', methods=['PUT'])
@ac_api_requires()
def cluster_narrative_edit():
    """Save an analyst correction over a generated cluster narrative.

    Body: {cluster_id, case_ids: [...], suggested_name, narrative, csrf_token}

    The corrected title and prose supersede the model output everywhere the
    narrative is read, including the STIX bundle export.
    """
    data = request.get_json(silent=True) or {}
    anchor, cluster_id, err = _anchor_from_body(data)
    if err:
        return response_api_error(err)

    from app.iris_engine.ai.cluster_narrative import (
        ClusterNarrativeEditError,
        save_cluster_narrative_edit,
        _artifact_to_result,
    )
    try:
        art = save_cluster_narrative_edit(
            anchor,
            cluster_id,
            data.get('suggested_name', ''),
            data.get('narrative', ''),
            current_user.id,
        )
    except ClusterNarrativeEditError as exc:
        return response_api_error(str(exc))

    return response_api_success(_artifact_to_result(art, cached=True))


@correlation_blueprint.route('/cluster-narrative/edit', methods=['DELETE'])
@ac_api_requires()
def cluster_narrative_revert():
    """Discard the analyst correction, restoring the original AI narrative."""
    data = request.get_json(silent=True) or {}
    anchor, cluster_id, err = _anchor_from_body(data)
    if err:
        return response_api_error(err)

    from app.iris_engine.ai.cluster_narrative import (
        ClusterNarrativeEditError,
        revert_cluster_narrative_edit,
        _artifact_to_result,
    )
    try:
        art = revert_cluster_narrative_edit(anchor, cluster_id)
    except ClusterNarrativeEditError as exc:
        return response_api_error(str(exc))

    return response_api_success(_artifact_to_result(art, cached=True))


def _misp_cluster_module_config() -> dict:
    """Flatten the IrisMISPCluster module's stored config into {param: value}.

    Same shape the hook path gets via `self.module_dict_conf`; this module is
    button-driven so we read it directly.
    """
    from app.models.models import IrisModule
    mod = IrisModule.query.filter(
        IrisModule.module_name == 'iris_misp_cluster_module'
    ).first()
    if mod is None:
        return {}
    return {
        p.get('param_name'): p.get('value', p.get('default'))
        for p in (mod.module_config or [])
        if isinstance(p, dict) and p.get('param_name')
    }


def _build_ioc_records(pairs_for_cluster: list[dict]) -> tuple[list[dict], int]:
    """Assemble {value, misp_type, tags, notes} for each shared IOC.

    Takes the FULL typed pair list for the cluster, not `cluster['shared_iocs']`
    — that field is a display list of bare values capped at 20 and carries no
    `ioc_type_id`. Using it would silently truncate the push on any cluster
    with more than 20 shared indicators. The STIX exporter has the same
    requirement and resolves it the same way.

    Only the cluster's shared IOCs are included, and only notes an analyst
    deliberately linked through `ioc_note_link` — case notes at large are never
    published.

    TLP FILTERING IS DONE HERE, EXPLICITLY. It used to be inherited from the
    correlation query, which restricted to green/clear; that restriction was
    removed from the display path (an analyst may see any TLP in a case they can
    already open) and moved here, where it governs what actually leaves the
    instance. This function and the STIX exporter are the two outbound paths.

    The rule is MOST RESTRICTIVE WINS, matching what the Correlation tab badges
    and the STIX exporter use. If an indicator is TLP:RED in any one of its
    cases it is not published at all, even where another case labels the same
    value green.

    That is deliberately the conservative reading. The alternative — publish the
    value because some case cleared it, and carry only that case's content — is
    more nuanced but wrong in the case that matters: an indicator marked red in
    the case where it was discovered may be restricted precisely because the
    *value* is sensitive, and another analyst labelling it green elsewhere does
    not undo that. It also has to agree with the UI: the analyst sees a RED
    badge on that row, and a push that published it anyway would contradict what
    they were shown.

    An indicator with no TLP set in any case is likewise not published.

    Returns ``(records, withheld_count)``; the caller surfaces the count so a
    partial push never looks like a complete one.
    """
    from app.models.models import IocNoteLink, IocType
    from app.business.ioc_correlation import is_shareable_tlp

    records: list[dict] = []
    seen: set[tuple] = set()
    withheld = 0

    for pair in pairs_for_cluster or []:
        value = (pair.get('ioc_value') or '').strip()
        type_id = pair.get('ioc_type_id')
        if not value or type_id is None:
            continue
        key = (value, type_id)
        if key in seen:
            continue
        seen.add(key)

        # MISP attribute type comes from Goal #2's IocType.type_taxonomy, which
        # is backfilled from the bundled MISP catalog at startup.
        ioc_type = IocType.query.filter(IocType.type_id == type_id).first()
        misp_type = (getattr(ioc_type, 'type_taxonomy', None) or '').strip()
        if not misp_type:
            # No clean MISP mapping — skip rather than push a bogus type.
            continue

        rows = Ioc.query.filter(
            Ioc.ioc_value == value,
            Ioc.ioc_type_id == type_id
        ).all()

        # Most restrictive wins across every appearance. NULL counts as not
        # shareable: `ioc_tlp_id` has no column default, so an API client or n8n
        # workflow that omits it writes NULL, and an unlabelled indicator has
        # not been cleared for sharing by anyone.
        #
        # `all()` rather than `any()` is the whole point — one red appearance
        # withholds the indicator.
        if not rows or not all(is_shareable_tlp(r.ioc_tlp_id) for r in rows):
            withheld += 1
            continue

        tags: set[str] = set()
        # The analyst's own comment on the indicator. Each case holds its own
        # Ioc row for the same value, and those descriptions legitimately
        # differ ("sending infrastructure" in one case, "beacon C2" in
        # another) — collect every distinct one rather than picking a winner.
        descriptions: list[str] = []
        notes: list[dict] = []
        note_ids: set[int] = set()
        for ioc in rows:
            desc = (ioc.ioc_description or '').strip()
            if desc and desc not in descriptions:
                descriptions.append(desc)
            for t in (ioc.ioc_tags or '').replace('|', ',').split(','):
                t = t.strip()
                if t:
                    tags.add(t)
            links = IocNoteLink.query.filter(IocNoteLink.ioc_id == ioc.ioc_id).all()
            for link in links:
                note = link.note
                if note is None or note.note_id in note_ids:
                    continue
                note_ids.add(note.note_id)
                notes.append({
                    'title': note.note_title or '',
                    'content': note.note_content or '',
                })

        records.append({
            'value': value,
            'misp_type': misp_type,
            'tags': sorted(tags),
            'descriptions': descriptions,
            'notes': notes,
        })

    return records, withheld


@correlation_blueprint.route('/clusters/<cluster_id>/misp-push', methods=['POST'])
@ac_api_requires()
def cluster_misp_push(cluster_id: str):
    """Publish a correlation cluster to MISP as a single campaign event.

    One-directional (iris-ng -> MISP). Pushes the cluster's shared IOCs as
    attributes, their tags, and the analyst notes linked to those IOCs via
    `ioc_note_link`. The cached AI narrative (or the analyst's correction of it)
    supplies the event title and description.

    Body / query: same filter params as /report — `min_shared`, `start_date`,
    `end_date` — so the cluster is reproducible. `force=true` re-publishes a
    cluster that was already pushed, creating a NEW MISP event.
    """
    from app.models.models import CaseAiArtifact, MispClusterLink

    data = request.get_json(silent=True) or {}
    force = str(data.get('force', '')).lower() in ('1', 'true', 'yes')

    min_shared = int(data.get('min_shared') or request.args.get('min_shared', 2))
    if min_shared < 1:
        min_shared = 1
    start_date = _parse_date(data.get('start_date') or request.args.get('start_date'))
    end_date = _parse_date(data.get('end_date') or request.args.get('end_date'))

    report = build_correlation_report(
        user_id=current_user.id,
        min_shared=min_shared,
        start_date=start_date,
        end_date=end_date,
    )
    cluster = next(
        (c for c in report.get('clusters', []) if c.get('cluster_id') == cluster_id),
        None
    )
    if cluster is None:
        return response_api_error(
            f"Cluster {cluster_id} not found under the current filter parameters"
        )

    # Already published? Refuse unless the analyst explicitly re-publishes —
    # a second click would otherwise create a duplicate MISP event.
    existing = MispClusterLink.query.filter(
        MispClusterLink.cluster_id == cluster_id
    ).first()
    if existing is not None and not force:
        cfg_url = (_misp_cluster_module_config().get('misp_cluster_url') or '').rstrip('/')
        return response(409, data={
            'message': (
                f'This cluster was already published to MISP as event '
                f'#{existing.misp_event_id}. Re-publishing creates a NEW event — '
                f'retry with force=true to confirm.'
            ),
            'data': {
                'reason': 'already_published',
                'misp_event_id': existing.misp_event_id,
                'misp_event_url': f'{cfg_url}/events/view/{existing.misp_event_id}' if cfg_url else None,
                'pushed_at': existing.pushed_at.isoformat() if existing.pushed_at else None,
                'pushed_by': existing.pushed_by.name if existing.pushed_by else None,
            }
        })

    # Narrative: display_content so an analyst correction is what gets published.
    narrative = None
    anchor_id = min(cluster['case_ids']) if cluster.get('case_ids') else None
    if anchor_id is not None:
        art = (
            CaseAiArtifact.query
            .filter_by(case_id=anchor_id, kind=f"cluster_narrative:{cluster_id}")
            .order_by(CaseAiArtifact.generated_at.desc())
            .first()
        )
        if art and art.display_content:
            try:
                narrative = json.loads(art.display_content)
            except (ValueError, TypeError):
                narrative = None

    # Full typed pair list for this cluster — same derivation the STIX export
    # uses, so neither surface is limited by the 20-value display cap.
    cluster_case_set = set(cluster['case_ids'])
    pairs_for_cluster = [
        p for p in report.get('pairs', [])
        if cluster_case_set.issuperset(set(p['case_ids']))
    ]

    ioc_records, tlp_withheld = _build_ioc_records(pairs_for_cluster)
    if not ioc_records:
        # Distinguish the two reasons, because the fix differs: a TLP hold is
        # the analyst's own labelling and is corrected in IRIS-NG, whereas a
        # missing taxonomy mapping is a catalog gap.
        if tlp_withheld:
            return response_api_error(
                f'No publishable indicators in this cluster — {tlp_withheld} '
                'indicator(s) are held back because their TLP does not permit '
                'redistribution (only TLP:GREEN and TLP:CLEAR are published; an '
                'indicator with no TLP set is treated as not shareable)'
            )
        return response_api_error(
            'No publishable indicators in this cluster — every shared IOC type '
            'lacks a MISP attribute-type mapping (IocType.type_taxonomy)'
        )

    # Entity names to redact from free text before it leaves for MISP. Built
    # fresh on every push, so customers and cases created later are covered
    # automatically — nothing here is a fixed list.
    #
    #   - EVERY client name in the instance, not just this cluster's. A note in
    #     one case routinely references another customer, and the cost of
    #     including them all is one cheap query.
    #   - The case names of the cluster's cases. Customer names are not the only
    #     identifiers: divisions, subsidiaries and project names live in case
    #     titles ("… Applied Sciences Credential Harvest", "… WayneTech
    #     Prototype Schematics") and leaked from note prose until this was added.
    #
    # The module expands each into significant tokens, filtering generic IR and
    # sector vocabulary, then appends the admin-configured extras. IOC values
    # are protected from redaction inside the module — a lookalike domain built
    # from the victim's name IS the indicator.
    from app.models.cases import Cases
    from app.models.models import Client

    redact_terms: list[str] = [c.name for c in Client.query.all() if c.name]
    for case in Cases.query.filter(Cases.case_id.in_(cluster['case_ids'])).all():
        if case.name:
            redact_terms.append(case.name)

    from iris_misp_cluster_module.IrisMISPClusterInterface import (
        IrisMISPClusterError,
        IrisMISPClusterHandler,
    )
    from app import app as _app

    handler = IrisMISPClusterHandler(
        mod_config=_misp_cluster_module_config(),
        logger=_app.logger,
    )
    try:
        result = handler.push_cluster(
            cluster=cluster,
            narrative=narrative,
            ioc_records=ioc_records,
            campaign_tag=cluster.get('suggested_campaign_tag'),
            redact_terms=redact_terms,
        )
    except IrisMISPClusterError as exc:
        return response_api_error(str(exc))
    except Exception as exc:
        _app.logger.exception('cluster_misp_push failed')
        return response_api_error(f'MISP push failed: {exc}')

    if existing is not None:
        existing.misp_event_id = result['misp_event_id']
        existing.misp_event_uuid = result.get('misp_event_uuid')
        existing.case_ids = ','.join(str(c) for c in cluster.get('case_ids') or [])
        existing.pushed_at = datetime.utcnow()
        existing.pushed_by_id = current_user.id
    else:
        db.session.add(MispClusterLink(
            cluster_id=cluster_id,
            misp_event_id=result['misp_event_id'],
            misp_event_uuid=result.get('misp_event_uuid'),
            case_ids=','.join(str(c) for c in cluster.get('case_ids') or []),
            pushed_by_id=current_user.id,
        ))
    db.session.commit()

    # Report what was held back. A push that silently drops indicators reads as
    # a complete one, and the analyst has no way to tell the MISP event is a
    # subset of the cluster they were looking at.
    if tlp_withheld:
        result = dict(result)
        result['tlp_withheld_count'] = tlp_withheld
        result['tlp_withheld_note'] = (
            f'{tlp_withheld} indicator(s) were not published because their TLP '
            'does not permit redistribution. Only TLP:GREEN and TLP:CLEAR are '
            'sent; an indicator with no TLP set is treated as not shareable.'
        )

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

    # TLP gate — this is an outbound path. A STIX bundle is built to hand to a
    # third party, so only indicators whose TLP permits redistribution go in.
    # The correlation query itself no longer filters by TLP (an analyst may see
    # any TLP in a case they can already open), which is exactly why this has to
    # be explicit here. `tlp_shareable` is computed from the most restrictive TLP
    # across the indicator's appearances, and is false when any appearance has no
    # TLP set at all.
    tlp_withheld = sum(1 for p in pairs_for_cluster if not p.get('tlp_shareable'))
    pairs_for_cluster = [p for p in pairs_for_cluster if p.get('tlp_shareable')]

    if not pairs_for_cluster:
        return response_api_error(
            f'Nothing to export — all {tlp_withheld} shared indicator(s) in this '
            'cluster are held back because their TLP does not permit '
            'redistribution. Only TLP:GREEN and TLP:CLEAR are exported; an '
            'indicator with no TLP set is treated as not shareable.',
            404,
        )

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
        # display_content, not content — an analyst correction is authoritative
        # and must reach partners instead of superseded model text.
        if art and art.display_content:
            try:
                narrative = json.loads(art.display_content)
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

    headers = {'Content-Disposition': f'attachment; filename="{filename}"'}
    if tlp_withheld:
        # The download is a file, so there is no response body to carry a
        # warning — a header is the only channel that survives. Without it a
        # partial bundle is indistinguishable from a complete one.
        headers['X-IRIS-TLP-Withheld'] = str(tlp_withheld)
        _app.logger.info(
            'STIX export for cluster %s withheld %d indicator(s) on TLP grounds',
            cluster_id, tlp_withheld,
        )

    return Response(
        bundle_json,
        mimetype='application/json',
        headers=headers,
    )
