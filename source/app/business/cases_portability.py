#  IRIS-NG additive — case import/export round-trip helpers.
#
#  Exports a case to a portable JSON document and re-imports it as a brand-new
#  case on the same (or a different) instance. Lookup IDs (severity, classification,
#  IOC type, asset type, etc.) vary per deployment, so the export carries their
#  *names*; the import resolves them locally by name and falls back to sensible
#  defaults when a name is unknown, accumulating warnings rather than failing.
#
#  Scope (v1):
#   - Case info, notes (with directories), IOCs, assets, tasks, evidence
#     metadata (no file bytes), timeline events, and the asset/IOC cross-links
#     each of those carry.
#   - Skips: working timeline events, comments, AI artifact cache, IOC↔note
#     provenance, task links, evidence↔asset links, modification history.
#
#  See docs/19-ux-ai-design.md for the design background.

import datetime
import logging as log

from flask_login import current_user

from app import db
from app.business.errors import BusinessProcessingError
from app.business.cases import cases_create
from app.datamgmt.case.case_db import save_case_tags
from app.datamgmt.case.case_notes_db import add_note
from app.datamgmt.manage.manage_attribute_db import get_default_custom_attributes
from app.iris_engine.utils.tracker import track_activity
from app.models.alerts import Severity
from app.models.cases import Cases, CasesEvent
from app.models.models import (
    AnalysisStatus, AssetsType, CaseAssets, CaseClassification, CaseEventCategory,
    CaseEventsAssets, CaseEventsIoc, CaseReceivedFile, CaseTasks, Client,
    CompromiseStatus, EventCategory, EvidenceTypes, Ioc, IocAssetLink,
    IocType, NoteDirectory, Notes, TaskStatus, Tlp
)


SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def _iso(dt):
    if dt is None:
        return None
    if isinstance(dt, datetime.datetime):
        return dt.isoformat()
    if isinstance(dt, datetime.date):
        return dt.isoformat()
    return str(dt)


def _name_or_none(obj, attr):
    """Return getattr(obj, attr) if obj is not None else None. Safe for refs."""
    return getattr(obj, attr, None) if obj is not None else None


def _build_directory_path(directory, cache):
    if directory is None:
        return None
    if directory.id in cache:
        return cache[directory.id]
    parts = []
    cur = directory
    seen = set()
    while cur is not None and cur.id not in seen:
        seen.add(cur.id)
        parts.append(cur.name or '')
        cur = cur.parent
    path = '/'.join(reversed(parts))
    cache[directory.id] = path
    return path


def export_case_for_portability(case_id: int) -> dict:
    """Serialize a case to a JSON-safe dict suitable for re-importing."""

    case = Cases.query.filter(Cases.case_id == case_id).first()
    if case is None:
        raise BusinessProcessingError(f'Case {case_id} not found')

    # Tag list
    tags = [t.tag_title for t in (case.tags or [])]

    case_block = {
        'name': case.name,
        'description': case.description or '',
        'soc_id': case.soc_id,
        'customer_name': _name_or_none(case.client, 'name'),
        'classification_name': _name_or_none(case.classification, 'name'),
        'severity_name': _name_or_none(case.severity, 'severity_name'),
        'state_name': _name_or_none(case.state, 'state_name'),
        'status_id': case.status_id,
        'open_date': _iso(case.open_date),
        'close_date': _iso(case.close_date),
        'initial_date': _iso(case.initial_date),
        'closing_note': case.closing_note,
        'tags': tags,
        'custom_attributes': case.custom_attributes,
    }

    # Notes (with directory paths)
    dir_cache = {}
    notes_block = []
    for note in Notes.query.filter(Notes.note_case_id == case_id).all():
        notes_block.append({
            'title': note.note_title,
            'content': note.note_content or '',
            'directory_path': _build_directory_path(note.directory, dir_cache),
            'creation_date': _iso(note.note_creationdate),
            'custom_attributes': note.custom_attributes,
        })

    # IOCs — exported with values used later as the unique key for linking
    iocs_block = []
    for ioc in Ioc.query.filter(Ioc.case_id == case_id).all():
        iocs_block.append({
            'value': ioc.ioc_value,
            'type_name': _name_or_none(ioc.ioc_type, 'type_name'),
            'tlp_name': _name_or_none(ioc.tlp, 'tlp_name'),
            'description': ioc.ioc_description,
            'tags': ioc.ioc_tags,
            'misp': ioc.ioc_misp,
            'custom_attributes': ioc.custom_attributes,
        })

    # Assets — and the IOC values linked to each
    assets_block = []
    for asset in CaseAssets.query.filter(CaseAssets.case_id == case_id).all():
        linked_ioc_values = [
            link.ioc.ioc_value for link in (asset.iocs or [])
            if link.ioc is not None
        ]
        compromise_name = None
        if asset.asset_compromise_status_id is not None:
            try:
                compromise_name = CompromiseStatus(asset.asset_compromise_status_id).name
            except ValueError:
                compromise_name = None
        assets_block.append({
            'name': asset.asset_name,
            'description': asset.asset_description,
            'type_name': _name_or_none(asset.asset_type, 'asset_name'),
            'analysis_status_name': _name_or_none(asset.analysis_status, 'name'),
            'compromise_status': compromise_name,
            'ip': asset.asset_ip,
            'domain': asset.asset_domain,
            'info': asset.asset_info,
            'tags': asset.asset_tags,
            'linked_ioc_values': linked_ioc_values,
            'custom_attributes': asset.custom_attributes,
        })

    # Tasks
    tasks_block = []
    for task in CaseTasks.query.filter(CaseTasks.task_case_id == case_id).all():
        tasks_block.append({
            'title': task.task_title,
            'description': task.task_description,
            'status_name': _name_or_none(task.status, 'status_name'),
            'tags': task.task_tags,
            'open_date': _iso(task.task_open_date),
            'close_date': _iso(task.task_close_date),
            'last_update': _iso(task.task_last_update),
            'custom_attributes': task.custom_attributes,
        })

    # Evidence — metadata only, no file bytes
    evidences_block = []
    for ev in CaseReceivedFile.query.filter(CaseReceivedFile.case_id == case_id).all():
        evidences_block.append({
            'filename': ev.filename,
            'file_hash': ev.file_hash,
            'file_size': ev.file_size,
            'description': ev.file_description,
            'type_name': _name_or_none(ev.type, 'name'),
            'date_added': _iso(ev.date_added),
            'acquisition_date': _iso(ev.acquisition_date),
            'start_date': _iso(ev.start_date),
            'end_date': _iso(ev.end_date),
            'custom_attributes': ev.custom_attributes,
        })

    # Timeline events
    timeline_block = []
    events = CasesEvent.query.filter(CasesEvent.case_id == case_id) \
        .order_by(CasesEvent.event_date).all()
    for ev in events:
        # Category via the case_events_category join
        cat_row = CaseEventCategory.query.filter(
            CaseEventCategory.event_id == ev.event_id
        ).first()
        category_name = None
        if cat_row is not None:
            cat = EventCategory.query.filter(EventCategory.id == cat_row.category_id).first()
            category_name = cat.name if cat is not None else None

        # Linked assets / iocs (by their natural keys, not IDs)
        linked_asset_names = [
            row.asset.asset_name for row in
            CaseEventsAssets.query.filter(CaseEventsAssets.event_id == ev.event_id).all()
            if row.asset is not None
        ]
        linked_ioc_values = [
            row.ioc.ioc_value for row in
            CaseEventsIoc.query.filter(CaseEventsIoc.event_id == ev.event_id).all()
            if row.ioc is not None
        ]

        timeline_block.append({
            'title': ev.event_title,
            'date': _iso(ev.event_date),
            'tz': ev.event_tz,
            'date_wtz': _iso(ev.event_date_wtz),
            'content': ev.event_content,
            'raw': ev.event_raw,
            'source': ev.event_source,
            'tags': ev.event_tags,
            'color': ev.event_color,
            'is_flagged': bool(ev.event_is_flagged),
            'in_summary': bool(ev.event_in_summary),
            'in_graph': bool(ev.event_in_graph),
            'category_name': category_name,
            'linked_asset_names': linked_asset_names,
            'linked_ioc_values': linked_ioc_values,
            'custom_attributes': ev.custom_attributes,
        })

    return {
        'schema_version': SCHEMA_VERSION,
        'exported_at': datetime.datetime.utcnow().isoformat(),
        'exported_by': getattr(current_user, 'user', None) if current_user else None,
        'source': {
            'case_id': case.case_id,
            'case_uuid': str(case.case_uuid) if case.case_uuid else None,
        },
        'case': case_block,
        'notes': notes_block,
        'iocs': iocs_block,
        'assets': assets_block,
        'tasks': tasks_block,
        'evidences': evidences_block,
        'timeline': timeline_block,
    }


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def _resolve_first_accessible_customer():
    """Best-effort: any customer the current user can see. Falls back to the
    primary customer (id 1) which exists in stock IRIS-NG."""
    cust = Client.query.order_by(Client.client_id).first()
    return cust


def _resolve_customer(name, warnings):
    if name:
        c = Client.query.filter(Client.name == name).first()
        if c is not None:
            return c
        warnings.append(f"Customer '{name}' not found — falling back to first available customer")
    c = _resolve_first_accessible_customer()
    if c is None:
        raise BusinessProcessingError('No customers exist on this instance — cannot import case')
    return c


def _resolve_classification(name, warnings):
    if not name:
        return None
    c = CaseClassification.query.filter(CaseClassification.name == name).first()
    if c is None:
        warnings.append(f"Classification '{name}' not found — leaving unset")
    return c


def _resolve_severity(name, warnings):
    if name:
        sev = Severity.query.filter(Severity.severity_name == name).first()
        if sev is not None:
            return sev.severity_id
        warnings.append(f"Severity '{name}' not found — defaulting to Medium")
    med = Severity.query.filter(Severity.severity_name == 'Medium').first()
    return med.severity_id if med is not None else 4


def _resolve_ioc_type(name, warnings, cache):
    if name in cache:
        return cache[name]
    if name:
        t = IocType.query.filter(IocType.type_name == name).first()
        if t is not None:
            cache[name] = t.type_id
            return t.type_id
        warnings.append(f"IOC type '{name}' not found — falling back to 'other'")
    other = IocType.query.filter(IocType.type_name == 'other').first()
    fallback = other.type_id if other is not None else None
    cache[name] = fallback
    return fallback


def _resolve_tlp(name, warnings, cache):
    if name in cache:
        return cache[name]
    if name:
        t = Tlp.query.filter(Tlp.tlp_name == name).first()
        if t is not None:
            cache[name] = t.tlp_id
            return t.tlp_id
        warnings.append(f"TLP '{name}' not found — defaulting to amber")
    amber = Tlp.query.filter(Tlp.tlp_name == 'amber').first()
    fallback = amber.tlp_id if amber is not None else 2
    cache[name] = fallback
    return fallback


def _resolve_asset_type(name, warnings, cache):
    if name in cache:
        return cache[name]
    if name:
        t = AssetsType.query.filter(AssetsType.asset_name == name).first()
        if t is not None:
            cache[name] = t.asset_id
            return t.asset_id
        warnings.append(f"Asset type '{name}' not found — falling back to 'Other'")
    other = AssetsType.query.filter(AssetsType.asset_name == 'Other').first()
    fallback = other.asset_id if other is not None else None
    cache[name] = fallback
    return fallback


def _resolve_analysis_status(name, warnings, cache):
    if name in cache:
        return cache[name]
    if name:
        a = AnalysisStatus.query.filter(AnalysisStatus.name == name).first()
        if a is not None:
            cache[name] = a.id
            return a.id
        warnings.append(f"Analysis status '{name}' not found — defaulting to 'Unspecified'")
    unsp = AnalysisStatus.query.filter(AnalysisStatus.name == 'Unspecified').first()
    fallback = unsp.id if unsp is not None else None
    cache[name] = fallback
    return fallback


def _resolve_task_status(name, warnings, cache):
    if name in cache:
        return cache[name]
    if name:
        s = TaskStatus.query.filter(TaskStatus.status_name == name).first()
        if s is not None:
            cache[name] = s.id
            return s.id
        warnings.append(f"Task status '{name}' not found — defaulting to 'To do'")
    todo = TaskStatus.query.filter(TaskStatus.status_name == 'To do').first()
    fallback = todo.id if todo is not None else None
    cache[name] = fallback
    return fallback


def _resolve_evidence_type(name, warnings, cache):
    if name in cache:
        return cache[name]
    if not name:
        cache[name] = None
        return None
    t = EvidenceTypes.query.filter(EvidenceTypes.name == name).first()
    if t is None:
        warnings.append(f"Evidence type '{name}' not found — leaving unset")
        cache[name] = None
        return None
    cache[name] = t.id
    return t.id


def _resolve_event_category(name, warnings, cache):
    if name in cache:
        return cache[name]
    if not name:
        cache[name] = None
        return None
    c = EventCategory.query.filter(EventCategory.name == name).first()
    if c is None:
        warnings.append(f"Event category '{name}' not found — leaving unset")
        cache[name] = None
        return None
    cache[name] = c.id
    return c.id


def _compromise_id_from_name(name):
    if not name:
        return CompromiseStatus.unknown.value
    try:
        return CompromiseStatus[name].value
    except KeyError:
        return CompromiseStatus.unknown.value


def _get_or_create_directory(case_id, path, cache):
    if not path:
        return None
    if path in cache:
        return cache[path]
    parent = None
    parts = [p for p in path.split('/') if p]
    for part in parts:
        existing = NoteDirectory.query.filter(
            NoteDirectory.case_id == case_id,
            NoteDirectory.name == part,
            NoteDirectory.parent_id == (parent.id if parent else None)
        ).first()
        if existing is None:
            existing = NoteDirectory(name=part, case_id=case_id,
                                     parent_id=parent.id if parent else None)
            db.session.add(existing)
            db.session.flush()
        parent = existing
    cache[path] = parent
    return parent


def import_case_from_portability_dict(payload: dict) -> dict:
    """Create a brand new case from an export payload. Returns the new case id
    and a list of human-readable warnings."""

    if not isinstance(payload, dict):
        raise BusinessProcessingError('Import payload must be a JSON object')

    sv = payload.get('schema_version')
    if sv not in (None, SCHEMA_VERSION):
        raise BusinessProcessingError(f'Unsupported export schema_version: {sv}')

    case_block = payload.get('case') or {}
    if not case_block.get('name'):
        raise BusinessProcessingError("Export payload is missing 'case.name'")

    warnings = []

    # Resolve refs needed for the parent case
    customer = _resolve_customer(case_block.get('customer_name'), warnings)
    classification = _resolve_classification(case_block.get('classification_name'), warnings)
    severity_id = _resolve_severity(case_block.get('severity_name'), warnings)

    # Strip "#<id> - " prefix if exporter included it; cases_create re-prefixes.
    raw_name = case_block.get('name') or 'Imported case'
    short_name = raw_name
    if raw_name.startswith('#'):
        try:
            short_name = raw_name.split(' - ', 1)[1]
        except IndexError:
            short_name = raw_name

    create_payload = {
        'case_name': f'{short_name} (imported)',
        'case_soc_id': case_block.get('soc_id') or '',
        'case_description': case_block.get('description') or '',
        'case_customer': customer.client_id,
        'case_tags': ','.join(case_block.get('tags') or []),
        'classification_id': classification.id if classification else None,
        'custom_attributes': case_block.get('custom_attributes'),
    }

    try:
        case = cases_create(create_payload)
    except BusinessProcessingError:
        raise
    except Exception as e:
        log.exception('Case import: case creation failed')
        raise BusinessProcessingError(f'Failed to create imported case: {e}')

    # cases_create defaults severity to 4; override with the exporter's value
    case.severity_id = severity_id
    db.session.commit()

    # Re-apply tags via the same helper the case-update path uses so the tag
    # rows are normalised, the rest of the system already trusts that path.
    save_case_tags(create_payload['case_tags'], case)

    case_id = case.case_id
    counts = {
        'notes': 0, 'directories': 0, 'iocs': 0, 'assets': 0, 'tasks': 0,
        'evidences': 0, 'timeline_events': 0, 'asset_ioc_links': 0,
        'event_asset_links': 0, 'event_ioc_links': 0,
    }

    # Lookup caches per import
    ioc_type_cache = {}
    tlp_cache = {}
    asset_type_cache = {}
    analysis_status_cache = {}
    task_status_cache = {}
    evidence_type_cache = {}
    event_category_cache = {}
    directory_cache = {}

    user_id = current_user.id

    # --- Notes -------------------------------------------------------------
    for note in payload.get('notes') or []:
        title = (note.get('title') or 'Untitled')[:155]
        content = note.get('content') or ''
        directory = _get_or_create_directory(case_id, note.get('directory_path'), directory_cache)
        directory_id = directory.id if directory else None
        now = datetime.datetime.utcnow()
        try:
            add_note(title, now, user_id, case_id, directory_id, content)
            counts['notes'] += 1
        except Exception as e:
            warnings.append(f"Failed to import note '{title}': {e}")
    counts['directories'] = len(directory_cache)

    # --- IOCs -------------------------------------------------------------
    ioc_value_to_id = {}
    for ioc in payload.get('iocs') or []:
        value = ioc.get('value')
        if not value:
            continue
        type_id = _resolve_ioc_type(ioc.get('type_name'), warnings, ioc_type_cache)
        tlp_id = _resolve_tlp(ioc.get('tlp_name'), warnings, tlp_cache)
        new_ioc = Ioc(
            ioc_value=value,
            ioc_type_id=type_id,
            ioc_tlp_id=tlp_id,
            ioc_description=ioc.get('description'),
            ioc_tags=ioc.get('tags'),
            ioc_misp=ioc.get('misp'),
            user_id=user_id,
            case_id=case_id,
            custom_attributes=ioc.get('custom_attributes') or get_default_custom_attributes('ioc'),
        )
        db.session.add(new_ioc)
        db.session.flush()
        ioc_value_to_id[value] = new_ioc.ioc_id
        counts['iocs'] += 1

    # --- Assets -----------------------------------------------------------
    asset_name_to_id = {}
    for asset in payload.get('assets') or []:
        name = asset.get('name')
        if not name:
            continue
        new_asset = CaseAssets(
            asset_name=name,
            asset_description=asset.get('description'),
            asset_type_id=_resolve_asset_type(asset.get('type_name'), warnings, asset_type_cache),
            analysis_status_id=_resolve_analysis_status(asset.get('analysis_status_name'),
                                                       warnings, analysis_status_cache),
            asset_compromise_status_id=_compromise_id_from_name(asset.get('compromise_status')),
            asset_ip=asset.get('ip'),
            asset_domain=asset.get('domain'),
            asset_info=asset.get('info'),
            asset_tags=asset.get('tags'),
            date_added=datetime.datetime.utcnow(),
            user_id=user_id,
            case_id=case_id,
            custom_attributes=asset.get('custom_attributes') or get_default_custom_attributes('asset'),
        )
        db.session.add(new_asset)
        db.session.flush()
        asset_name_to_id[name] = new_asset.asset_id
        counts['assets'] += 1

        # Cross-link this asset to any imported IOCs by value
        for ioc_value in asset.get('linked_ioc_values') or []:
            ioc_id = ioc_value_to_id.get(ioc_value)
            if ioc_id is None:
                continue
            db.session.add(IocAssetLink(ioc_id=ioc_id, asset_id=new_asset.asset_id))
            counts['asset_ioc_links'] += 1

    # --- Tasks ------------------------------------------------------------
    for task in payload.get('tasks') or []:
        title = task.get('title') or 'Untitled task'
        new_task = CaseTasks(
            task_title=title,
            task_description=task.get('description'),
            task_status_id=_resolve_task_status(task.get('status_name'), warnings, task_status_cache),
            task_tags=task.get('tags'),
            task_open_date=datetime.datetime.utcnow(),
            task_last_update=datetime.datetime.utcnow(),
            task_userid_open=user_id,
            task_userid_update=user_id,
            task_case_id=case_id,
            custom_attributes=task.get('custom_attributes') or get_default_custom_attributes('task'),
        )
        db.session.add(new_task)
        counts['tasks'] += 1

    # --- Evidence ---------------------------------------------------------
    for ev in payload.get('evidences') or []:
        new_ev = CaseReceivedFile(
            filename=ev.get('filename') or 'unnamed',
            file_hash=ev.get('file_hash'),
            file_size=ev.get('file_size'),
            file_description=ev.get('description'),
            type_id=_resolve_evidence_type(ev.get('type_name'), warnings, evidence_type_cache),
            date_added=datetime.datetime.utcnow(),
            case_id=case_id,
            user_id=user_id,
            custom_attributes=ev.get('custom_attributes') or get_default_custom_attributes('evidence'),
        )
        db.session.add(new_ev)
        counts['evidences'] += 1

    # --- Timeline events --------------------------------------------------
    for ev in payload.get('timeline') or []:
        title = ev.get('title') or 'Untitled event'
        # Parse event date — fall back to now if missing/unparseable
        event_date = datetime.datetime.utcnow()
        if ev.get('date'):
            try:
                event_date = datetime.datetime.fromisoformat(ev['date'].replace('Z', '+00:00'))
                if event_date.tzinfo is not None:
                    event_date = event_date.replace(tzinfo=None)
            except (ValueError, AttributeError):
                warnings.append(f"Event '{title}' has unparseable date '{ev.get('date')}' — using now")

        event_date_wtz = event_date
        if ev.get('date_wtz'):
            try:
                event_date_wtz = datetime.datetime.fromisoformat(ev['date_wtz'].replace('Z', '+00:00'))
                if event_date_wtz.tzinfo is not None:
                    event_date_wtz = event_date_wtz.replace(tzinfo=None)
            except (ValueError, AttributeError):
                pass

        new_event = CasesEvent(
            event_title=title,
            event_content=ev.get('content'),
            event_raw=ev.get('raw'),
            event_source=ev.get('source'),
            event_date=event_date,
            event_date_wtz=event_date_wtz,
            event_tz=ev.get('tz') or '+00:00',
            event_added=datetime.datetime.utcnow(),
            event_color=ev.get('color'),
            event_tags=ev.get('tags'),
            event_is_flagged=bool(ev.get('is_flagged')),
            event_in_summary=bool(ev.get('in_summary')),
            event_in_graph=bool(ev.get('in_graph')),
            user_id=user_id,
            case_id=case_id,
            custom_attributes=ev.get('custom_attributes') or get_default_custom_attributes('event'),
        )
        db.session.add(new_event)
        db.session.flush()
        counts['timeline_events'] += 1

        # Category
        cat_id = _resolve_event_category(ev.get('category_name'), warnings, event_category_cache)
        if cat_id is not None:
            db.session.add(CaseEventCategory(event_id=new_event.event_id, category_id=cat_id))

        # Linked assets
        for asset_name in ev.get('linked_asset_names') or []:
            asset_id = asset_name_to_id.get(asset_name)
            if asset_id is None:
                continue
            db.session.add(CaseEventsAssets(
                event_id=new_event.event_id, asset_id=asset_id, case_id=case_id
            ))
            counts['event_asset_links'] += 1

        # Linked IOCs
        for ioc_value in ev.get('linked_ioc_values') or []:
            ioc_id = ioc_value_to_id.get(ioc_value)
            if ioc_id is None:
                continue
            db.session.add(CaseEventsIoc(
                event_id=new_event.event_id, ioc_id=ioc_id, case_id=case_id
            ))
            counts['event_ioc_links'] += 1

    db.session.commit()

    track_activity(
        f'imported case "{case.name}" from JSON ({counts["notes"]} notes, '
        f'{counts["iocs"]} iocs, {counts["assets"]} assets, '
        f'{counts["tasks"]} tasks, {counts["evidences"]} evidences, '
        f'{counts["timeline_events"]} timeline events)',
        caseid=case_id, ctx_less=False,
    )

    return {
        'case_id': case_id,
        'case_name': case.name,
        'counts': counts,
        'warnings': warnings,
    }
