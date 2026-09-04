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

"""Org-wide Customer Asset registry — datamgmt primitives (iris-ng v2,
Phase 4). Lives in datamgmt (not business) on purpose: the create_asset()
funnel and the alert escalation/merge loops are datamgmt code, and datamgmt
must never import business (three-layer rule). business/customer_assets.py
holds curation + the celery task and imports from here.

``sync_asset`` is the single upsert every touchpoint calls. Two properties
are load-bearing:

  1. **It runs on its own engine-level connection** (``db.engine.begin()``),
     NEVER the caller's ORM session. Several touchpoints (working-timeline
     promote, case import) call it mid-transaction — a ``db.session.commit()``
     here would commit the caller's half-done work, and a failure would
     poison the caller's session (the PendingRollbackError shape). Engine
     isolation makes both impossible. Workers run NullPool, so this opens a
     fresh connection there; the web process checks one out of QueuePool.
  2. **It never raises.** Registry sync is derived bookkeeping; a defect in
     it must never break asset creation, alert ingest, escalation or
     promote. Failures are logged and swallowed, and ``scan_registry``
     recovers anything missed.

Sync semantics: insert-or-touch (identity = customer + lower(trim(name)) +
type; display casing is first-seen; last_seen advances). Compromise status
is RAISED to compromised only from NULL/to_be_determined/unknown — analyst
curation (criticality/environment/owner/notes, and any explicit compromise
verdict) is never overwritten by sync.
"""

import logging
from datetime import datetime

from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app import db
from app.models.models import CompromiseStatus
from app.models.models import CustomerAsset

log = logging.getLogger(__name__)

_RAISEABLE = (CompromiseStatus.to_be_determined.value,
              CompromiseStatus.unknown.value)

CRITICALITY_VALUES = ('low', 'medium', 'high', 'critical')
# Analyst-curated fields sync must never touch (REST edits go through
# update_curation below, which writes change rows).
CURATED_FIELDS = ('criticality', 'environment', 'owner', 'notes',
                  'compromise_status', 'compromise_since')


def _norm(name: str) -> str:
    return (name or '').strip().lower()


def _sync_on_conn(conn, customer_id: int, asset_name: str, asset_type_id: int,
                  compromise_status_id: int = None) -> None:
    """Core upsert on an already-open connection. Raises on failure —
    wrap it (sync_asset / sync_alert_assets swallow + log)."""
    norm = _norm(asset_name)
    if not norm or not asset_type_id or not customer_id:
        return
    now = datetime.utcnow()
    table = CustomerAsset.__table__
    stmt = (pg_insert(table)
            .values(customer_id=customer_id,
                    asset_name=asset_name.strip(),
                    asset_name_norm=norm,
                    asset_type_id=asset_type_id,
                    first_seen=now, last_seen=now)
            .on_conflict_do_update(
                constraint='uq_customer_asset_identity',
                set_={'last_seen': now})
            .returning(table.c.id, table.c.compromise_status))
    row = conn.execute(stmt).first()
    if (row is not None
            and compromise_status_id == CompromiseStatus.compromised.value
            and (row.compromise_status is None
                 or row.compromise_status in _RAISEABLE)):
        res = conn.execute(sa_text(
            'UPDATE customer_asset SET compromise_status = :c, '
            'compromise_since = COALESCE(compromise_since, :now) '
            'WHERE id = :id AND (compromise_status IS NULL '
            'OR compromise_status IN (0, 3))'),
            {'c': CompromiseStatus.compromised.value,
             'now': now, 'id': row.id})
        if res.rowcount:
            conn.execute(sa_text(
                'INSERT INTO customer_asset_change '
                '(customer_asset_id, field, old_value, new_value, '
                'changed_by, changed_at) VALUES '
                "(:id, 'compromise_status', :old, 'compromised', "
                'NULL, :now)'),
                {'id': row.id, 'now': now,
                 'old': (CompromiseStatus(row.compromise_status).name
                         if row.compromise_status is not None else None)})


def sync_asset(customer_id: int, asset_name: str, asset_type_id: int,
               compromise_status_id: int = None) -> None:
    """Upsert one sighting into the registry. Never raises (see module
    docstring). No-op on empty name/type/customer."""
    try:
        with db.engine.begin() as conn:
            _sync_on_conn(conn, customer_id, asset_name, asset_type_id,
                          compromise_status_id)
    except Exception:
        log.exception('customer-asset sync failed (customer=%s, name=%r) — '
                      'registry unaffected callers; scan recovers it',
                      customer_id, asset_name)


def sync_case_asset(case_asset) -> None:
    """Sync a CaseAssets row via its case's customer. Never raises."""
    try:
        if case_asset is None or not case_asset.case_id:
            return
        row = db.session.execute(sa_text(
            'SELECT client_id FROM cases WHERE case_id = :cid'),
            {'cid': case_asset.case_id}).first()
        if row is None:
            return
        sync_asset(row.client_id, case_asset.asset_name,
                   case_asset.asset_type_id,
                   compromise_status_id=case_asset.asset_compromise_status_id)
    except Exception:
        log.exception('customer-asset sync (case asset) failed')


def sync_alert_assets(alert) -> None:
    """Sync every asset attached to an alert (case_id is NULL on those rows —
    the customer comes from the alert). ONE engine transaction for the whole
    batch — sync_asset costs ~5ms/call (commit fsync), and this runs on the
    ingest hot path, so N assets must not pay N fsyncs. Never raises."""
    try:
        assets = list(alert.assets or [])
        if not assets:
            return
        with db.engine.begin() as conn:
            for asset in assets:
                _sync_on_conn(conn, alert.alert_customer_id, asset.asset_name,
                              asset.asset_type_id,
                              compromise_status_id=asset.asset_compromise_status_id)
    except Exception:
        log.exception('customer-asset sync (alert assets) failed')


# ---------------------------------------------------------------- sightings

def sightings_counts(asset_ids: list) -> dict:
    """Live counts per registry row: distinct case and alert sightings.
    Two grouped queries for the current page — never denormalized."""
    if not asset_ids:
        return {}
    out = {aid: {'cases': 0, 'alerts': 0} for aid in asset_ids}
    case_rows = db.session.execute(sa_text(
        'SELECT cu.id, count(DISTINCT ca.case_id) FROM customer_asset cu '
        'JOIN case_assets ca ON lower(trim(ca.asset_name)) = cu.asset_name_norm '
        ' AND ca.asset_type_id = cu.asset_type_id '
        'JOIN cases cs ON cs.case_id = ca.case_id '
        ' AND cs.client_id = cu.customer_id '
        'WHERE cu.id = ANY(:ids) GROUP BY cu.id'), {'ids': asset_ids}).all()
    for rid, n in case_rows:
        out[rid]['cases'] = n
    alert_rows = db.session.execute(sa_text(
        'SELECT cu.id, count(DISTINCT aaa.alert_id) FROM customer_asset cu '
        'JOIN case_assets ca ON lower(trim(ca.asset_name)) = cu.asset_name_norm '
        ' AND ca.asset_type_id = cu.asset_type_id '
        'JOIN alert_assets_association aaa ON aaa.asset_id = ca.asset_id '
        'JOIN alerts a ON a.alert_id = aaa.alert_id '
        ' AND a.alert_customer_id = cu.customer_id '
        'WHERE cu.id = ANY(:ids) GROUP BY cu.id'), {'ids': asset_ids}).all()
    for rid, n in alert_rows:
        out[rid]['alerts'] = n
    return out


def latest_observation(asset: CustomerAsset) -> dict:
    """IP / domain / tags / description from the MOST RECENT matching
    case_assets sighting. Live-derived, never stored: case_assets already
    carries these fields, so the registry displays them without duplicating
    them into curated columns (same philosophy as sightings). Covers both
    case-linked rows and alert-only rows (case_id NULL, reached through
    alert_assets_association)."""
    row = db.session.execute(sa_text(
        'SELECT ca.asset_ip, ca.asset_domain, ca.asset_tags, ca.asset_description '
        'FROM case_assets ca '
        'LEFT JOIN cases cs ON cs.case_id = ca.case_id '
        'WHERE lower(trim(ca.asset_name)) = :norm AND ca.asset_type_id = :tid '
        ' AND (cs.client_id = :cust OR (ca.case_id IS NULL AND EXISTS ('
        '   SELECT 1 FROM alert_assets_association aaa '
        '   JOIN alerts a ON a.alert_id = aaa.alert_id '
        '   WHERE aaa.asset_id = ca.asset_id'
        '    AND a.alert_customer_id = :cust))) '
        'ORDER BY coalesce(ca.date_update, ca.date_added) DESC NULLS LAST '
        'LIMIT 1'),
        {'norm': asset.asset_name_norm, 'tid': asset.asset_type_id,
         'cust': asset.customer_id}).first()
    if row is None:
        return {'ip': None, 'domain': None, 'tags': None, 'description': None}
    return {'ip': row[0], 'domain': row[1], 'tags': row[2], 'description': row[3]}


def timeline_events_for(asset: CustomerAsset, user_id: int,
                        limit: int = 50) -> list:
    """Master-timeline events linked to any matching case asset, newest
    first. Feeds the detail panel's Timeline tab (live-derived, like
    sightings) and is ACL-FILTERED to the viewer's cases exactly like
    sighting_details — event titles are case data."""
    from app.iris_engine.access_control.utils import ac_get_fast_user_cases_access
    accessible = ac_get_fast_user_cases_access(user_id) or []
    if not accessible:
        return []
    rows = db.session.execute(sa_text(
        'SELECT DISTINCT ce.event_id, ce.event_title, ce.event_date, '
        ' cs.case_id, cs.name '
        'FROM case_events_assets cea '
        'JOIN cases_events ce ON ce.event_id = cea.event_id '
        'JOIN case_assets ca ON ca.asset_id = cea.asset_id '
        'JOIN cases cs ON cs.case_id = ca.case_id '
        ' AND cs.client_id = :cust '
        'WHERE lower(trim(ca.asset_name)) = :norm '
        ' AND ca.asset_type_id = :tid '
        ' AND cs.case_id = ANY(:acl) '
        'ORDER BY ce.event_date DESC LIMIT :lim'),
        {'norm': asset.asset_name_norm, 'tid': asset.asset_type_id,
         'cust': asset.customer_id, 'lim': limit,
         'acl': list(accessible)}).all()
    return [{
        'event_id': r[0], 'title': r[1],
        'event_date': r[2].isoformat() + 'Z' if r[2] else None,
        'case_id': r[3], 'case_name': r[4],
    } for r in rows]


def timeline_event_count(asset: CustomerAsset) -> int:
    """Distinct master-timeline events linked to any matching case asset."""
    n = db.session.execute(sa_text(
        'SELECT count(DISTINCT cea.event_id) FROM case_events_assets cea '
        'JOIN case_assets ca ON ca.asset_id = cea.asset_id '
        'JOIN cases cs ON cs.case_id = ca.case_id '
        ' AND cs.client_id = :cust '
        'WHERE lower(trim(ca.asset_name)) = :norm '
        ' AND ca.asset_type_id = :tid'),
        {'norm': asset.asset_name_norm, 'tid': asset.asset_type_id,
         'cust': asset.customer_id}).scalar()
    return int(n or 0)


def sighting_details(asset: CustomerAsset, user_id: int) -> dict:
    """Case + alert sightings for one registry row, ACL-FILTERED to the
    viewer: cases through the per-case effective-access list, alerts are
    already customer-scoped by the caller's client-access check."""
    from app.iris_engine.access_control.utils import ac_get_fast_user_cases_access
    accessible = ac_get_fast_user_cases_access(user_id) or []

    case_rows = db.session.execute(sa_text(
        'SELECT DISTINCT cs.case_id, cs.name, cs.open_date, cs.close_date, '
        ' ca.asset_compromise_status_id '
        'FROM case_assets ca '
        'JOIN cases cs ON cs.case_id = ca.case_id AND cs.client_id = :cust '
        'WHERE lower(trim(ca.asset_name)) = :norm AND ca.asset_type_id = :tid '
        'ORDER BY cs.case_id DESC'),
        {'cust': asset.customer_id, 'norm': asset.asset_name_norm,
         'tid': asset.asset_type_id}).all()
    accessible_set = set(accessible)
    cases = [{'case_id': r.case_id, 'name': r.name,
              'open_date': r.open_date.isoformat() if r.open_date else None,
              'closed': r.close_date is not None,
              'compromise_status': r.asset_compromise_status_id}
             for r in case_rows if r.case_id in accessible_set]

    alert_rows = db.session.execute(sa_text(
        'SELECT DISTINCT a.alert_id, a.alert_title, a.alert_creation_time '
        'FROM case_assets ca '
        'JOIN alert_assets_association aaa ON aaa.asset_id = ca.asset_id '
        'JOIN alerts a ON a.alert_id = aaa.alert_id '
        ' AND a.alert_customer_id = :cust '
        'WHERE lower(trim(ca.asset_name)) = :norm AND ca.asset_type_id = :tid '
        'ORDER BY a.alert_id DESC LIMIT 100'),
        {'cust': asset.customer_id, 'norm': asset.asset_name_norm,
         'tid': asset.asset_type_id}).all()
    alerts = [{'alert_id': r.alert_id, 'title': r.alert_title,
               'creation_time': (r.alert_creation_time.isoformat() + 'Z'
                                 if r.alert_creation_time else None)}
              for r in alert_rows]

    return {'cases': cases, 'cases_hidden_by_acl': len(case_rows) - len(cases),
            'alerts': alerts}


# --------------------------------------------------------------------- scan

_SCAN_CASE_ASSETS_SQL = """
INSERT INTO customer_asset
    (customer_id, asset_name, asset_name_norm, asset_type_id, first_seen, last_seen)
SELECT sub.client_id,
       (array_agg(sub.asset_name ORDER BY sub.date_added ASC NULLS LAST))[1],
       sub.norm, sub.asset_type_id,
       COALESCE(min(sub.date_added), now()),
       COALESCE(max(COALESCE(sub.date_update, sub.date_added)), now())
FROM (
    SELECT cs.client_id, ca.asset_name, lower(trim(ca.asset_name)) AS norm,
           ca.asset_type_id, ca.date_added, ca.date_update
    FROM case_assets ca
    JOIN cases cs ON cs.case_id = ca.case_id
    WHERE ca.asset_name IS NOT NULL AND trim(ca.asset_name) <> ''
      AND ca.asset_type_id IS NOT NULL
) sub
GROUP BY sub.client_id, sub.norm, sub.asset_type_id
ON CONFLICT ON CONSTRAINT uq_customer_asset_identity
DO UPDATE SET last_seen = GREATEST(customer_asset.last_seen, EXCLUDED.last_seen)
"""

_SCAN_ALERT_ASSETS_SQL = """
INSERT INTO customer_asset
    (customer_id, asset_name, asset_name_norm, asset_type_id, first_seen, last_seen)
SELECT sub.customer_id,
       (array_agg(sub.asset_name ORDER BY sub.seen_at ASC NULLS LAST))[1],
       sub.norm, sub.asset_type_id,
       COALESCE(min(sub.seen_at), now()), COALESCE(max(sub.seen_at), now())
FROM (
    SELECT a.alert_customer_id AS customer_id, ca.asset_name,
           lower(trim(ca.asset_name)) AS norm, ca.asset_type_id,
           a.alert_creation_time AS seen_at
    FROM case_assets ca
    JOIN alert_assets_association aaa ON aaa.asset_id = ca.asset_id
    JOIN alerts a ON a.alert_id = aaa.alert_id
    WHERE ca.asset_name IS NOT NULL AND trim(ca.asset_name) <> ''
      AND ca.asset_type_id IS NOT NULL
) sub
GROUP BY sub.customer_id, sub.norm, sub.asset_type_id
ON CONFLICT ON CONSTRAINT uq_customer_asset_identity
DO UPDATE SET last_seen = GREATEST(customer_asset.last_seen, EXCLUDED.last_seen)
"""

_SCAN_COMPROMISE_SQL = """
UPDATE customer_asset cu
SET compromise_status = 1,
    compromise_since = COALESCE(cu.compromise_since, now())
FROM (
    SELECT DISTINCT cs.client_id, lower(trim(ca.asset_name)) AS norm,
           ca.asset_type_id
    FROM case_assets ca
    JOIN cases cs ON cs.case_id = ca.case_id
    WHERE ca.asset_compromise_status_id = 1
      AND ca.asset_name IS NOT NULL AND trim(ca.asset_name) <> ''
      AND ca.asset_type_id IS NOT NULL
) comp
WHERE cu.customer_id = comp.client_id
  AND cu.asset_name_norm = comp.norm
  AND cu.asset_type_id = comp.asset_type_id
  AND (cu.compromise_status IS NULL OR cu.compromise_status IN (0, 3))
"""


def scan_registry() -> dict:
    """Set-based backfill over every case asset and alert asset — no
    per-row Python loop, so no yield_per/commit interaction at all. The
    compromise pass raises to compromised only from unassessed (same rule
    as live sync); the count is reported, per-row change entries are
    deliberately not written for bulk scans (audit noise)."""
    with db.engine.begin() as conn:
        n_case = conn.execute(sa_text(_SCAN_CASE_ASSETS_SQL)).rowcount
        n_alert = conn.execute(sa_text(_SCAN_ALERT_ASSETS_SQL)).rowcount
        n_comp = conn.execute(sa_text(_SCAN_COMPROMISE_SQL)).rowcount
    return {'case_asset_rows': n_case, 'alert_asset_rows': n_alert,
            'compromise_raised': n_comp}
