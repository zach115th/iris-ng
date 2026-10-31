"""Lookup-table rows for the (i) help icons (iris-ng, 2026-10-30).

A glossary term with "values": "<source>" describes a field whose values live in
one of these tables; the popover and the glossary page show the description of
the chosen value as this server stores it. IOC, asset and evidence types, case
classifications and case states are edited under Manage; the others keep their
seeded text (post_init.upgrade_seed_descriptions).
"""
from app.models.alerts import AlertResolutionStatus
from app.models.alerts import AlertStatus
from app.models.alerts import Severity
from app.models.cases import CaseState
from app.models.models import AssetsType
from app.models.models import CaseClassification
from app.models.models import EvidenceTypes
from app.models.models import IocType
from app.models.models import TaskStatus

# source -> (model, id column, name column, description column, label column or None,
#            order: 'id' (the seeded lifecycle order) or 'name')
VALUE_TABLES = {
    'severity': (Severity, 'severity_id', 'severity_name', 'severity_description', None, 'rank'),
    'alert_status': (AlertStatus, 'status_id', 'status_name', 'status_description', None, 'id'),
    'alert_resolution': (AlertResolutionStatus, 'resolution_status_id', 'resolution_status_name',
                         'resolution_status_description', None, 'id'),
    'case_state': (CaseState, 'state_id', 'state_name', 'state_description', None, 'id'),
    'case_classification': (CaseClassification, 'id', 'name', 'description', 'name_expanded', 'name'),
    'ioc_type': (IocType, 'type_id', 'type_name', 'type_description', None, 'name'),
    'asset_type': (AssetsType, 'asset_id', 'asset_name', 'asset_description', None, 'name'),
    'evidence_type': (EvidenceTypes, 'id', 'name', 'description', None, 'name'),
    'task_status': (TaskStatus, 'id', 'status_name', 'status_description', None, 'id'),
}

# Severity ids do not follow intensity (Medium is 1 on a seeded install).
SEVERITY_RANK = ('Unspecified', 'Informational', 'Low', 'Medium', 'High', 'Critical')


def lookup_values(source):
    """[{id, name, label, description}] in the table's natural order; None for an
    unknown source."""
    spec = VALUE_TABLES.get(source)
    if spec is None:
        return None
    model, id_col, name_col, desc_col, label_col, order = spec
    columns = [getattr(model, id_col), getattr(model, name_col), getattr(model, desc_col)]
    if label_col:
        columns.append(getattr(model, label_col))
    rows = model.query.with_entities(*columns).order_by(
        getattr(model, name_col if order == 'name' else id_col)).all()
    if order == 'rank':
        rows.sort(key=lambda r: (SEVERITY_RANK.index(r[1]) if r[1] in SEVERITY_RANK else len(SEVERITY_RANK),
                                 r[1] or ''))
    out = []
    for row in rows:
        name = row[1] or ''
        out.append({
            'id': row[0],
            'name': name,
            'label': (row[3] if label_col else None) or name,
            'description': (row[2] or '').strip(),
        })
    return out
