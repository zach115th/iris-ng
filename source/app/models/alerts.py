#  IRIS Source Code
#  Copyright (C) 2024 - DFIR-IRIS
#  contact@dfir-iris.org
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

from datetime import datetime

import uuid
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy import BigInteger
from sqlalchemy import Boolean
from sqlalchemy import CheckConstraint
from sqlalchemy import String
from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import Text
from sqlalchemy import text
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app import db
from app.models.models import alert_assets_association
from app.models.models import alert_iocs_association


class AlertCaseAssociation(db.Model):
    __tablename__ = 'alert_case_association'

    alert_id = Column(ForeignKey('alerts.alert_id'), primary_key=True, nullable=False)
    case_id = Column(ForeignKey('cases.case_id'), primary_key=True, nullable=False, index=True)


class Alert(db.Model):
    __tablename__ = 'alerts'

    alert_id = Column(BigInteger, primary_key=True)
    alert_uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False,
                        server_default=text('gen_random_uuid()'), unique=True)
    alert_title = Column(Text, nullable=False)
    alert_description = Column(Text)
    alert_source = Column(Text)
    alert_source_ref = Column(Text)
    alert_source_link = Column(Text)
    alert_source_content = Column(JSON)
    alert_severity_id = Column(ForeignKey('severities.severity_id'), nullable=False)
    alert_status_id = Column(ForeignKey('alert_status.status_id'), nullable=False)
    alert_context = Column(JSON)
    alert_source_event_time = Column(DateTime, nullable=False, server_default=text("now()"))
    alert_creation_time = Column(DateTime, nullable=False, server_default=text("now()"))
    alert_note = Column(Text)
    alert_tags = Column(Text)
    alert_owner_id = Column(ForeignKey('user.id'))
    modification_history = Column(JSON)
    alert_customer_id = Column(ForeignKey('client.client_id'), nullable=False)
    alert_classification_id = Column(ForeignKey('case_classification.id'))
    alert_resolution_status_id = Column(ForeignKey('alert_resolution_status.resolution_status_id'), nullable=True)

    owner = relationship('User', foreign_keys=[alert_owner_id])
    severity = relationship('Severity')
    status = relationship('AlertStatus')
    customer = relationship('Client')
    classification = relationship('CaseClassification')
    resolution_status = relationship('AlertResolutionStatus')

    cases = relationship('Cases', secondary="alert_case_association", back_populates='alerts')
    comments = relationship('Comments', back_populates='alert', cascade='all, delete-orphan')

    assets = relationship('CaseAssets', secondary=alert_assets_association, back_populates='alerts')
    iocs = relationship('Ioc', secondary=alert_iocs_association, back_populates='alerts')


class Severity(db.Model):
    __tablename__ = 'severities'

    severity_id = Column(Integer, primary_key=True)
    severity_name = Column(Text, nullable=False, unique=True)
    severity_description = Column(Text)


class AlertStatus(db.Model):
    __tablename__ = 'alert_status'

    status_id = Column(Integer, primary_key=True)
    status_name = Column(Text, nullable=False, unique=True)
    status_description = Column(Text)


class AlertResolutionStatus(db.Model):
    __tablename__ = 'alert_resolution_status'

    resolution_status_id = Column(Integer, primary_key=True)
    resolution_status_name = Column(Text, nullable=False, unique=True)
    resolution_status_description = Column(Text)


class SimilarAlertsCache(db.Model):
    __tablename__ = 'similar_alerts_cache'

    id = Column(BigInteger, primary_key=True)
    customer_id = Column(BigInteger, ForeignKey('client.client_id'), nullable=False)
    asset_name = Column(Text, nullable=True)
    ioc_value = Column(Text, nullable=True)
    alert_id = Column(BigInteger, ForeignKey('alerts.alert_id'), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=text("now()"))

    asset_type_id = Column(Integer, ForeignKey('assets_type.asset_id'), nullable=True)
    ioc_type_id = Column(Integer, ForeignKey('ioc_type.type_id'), nullable=True)

    alert = relationship('Alert')
    customer = relationship('Client')
    asset_type = relationship('AssetsType')
    ioc_type = relationship('IocType')

    def __init__(self, customer_id, alert_id, asset_name=None, ioc_value=None, asset_type_id=None, ioc_type_id=None,
                 created_at=None):
        self.customer_id = customer_id
        self.asset_name = asset_name
        self.ioc_value = ioc_value
        self.alert_id = alert_id
        self.asset_type_id = asset_type_id
        self.ioc_type_id = ioc_type_id
        self.created_at = created_at if created_at else datetime.utcnow()


class AlertSimilarity(db.Model):
    __tablename__ = 'alert_similarity'

    id = Column(BigInteger, primary_key=True)
    alert_id = Column(BigInteger, ForeignKey('alerts.alert_id'), nullable=False)
    similar_alert_id = Column(BigInteger, ForeignKey('alerts.alert_id'), nullable=False)
    similarity_type = Column(String(255), nullable=True)
    matching_asset_id = Column(BigInteger, ForeignKey('case_assets.asset_id'), nullable=True)
    matching_ioc_id = Column(BigInteger, ForeignKey('ioc.ioc_id'), nullable=True)

    alert = relationship("Alert", foreign_keys=[alert_id])
    similar_alert = relationship("Alert", foreign_keys=[similar_alert_id])
    matching_asset = relationship("CaseAssets")
    matching_ioc = relationship("Ioc")


class MailRule(db.Model):
    """iris-ng v2 (Phase 1): one ordered rule turning ingested email into an
    alert (or dropping it). Evaluated ascending by priority; the first ENABLED
    rule whose conditions all match wins. A rule flagged is_fallback matches
    any message and is evaluated after every non-fallback rule regardless of
    its priority value, so ordinary rules cannot be shadowed by it.

    conditions is a JSON list of {"field": "subject"|"from"|"to"|"body",
    "regex": "<python regex>"} - AND-ed; an empty list matches everything
    (useful only on the fallback rule). Regexes are compiled with a 4 KB input
    truncation at match time (admin-supplied, but bounded anyway).

    CHECK constraints live here on __table_args__, not only in the migration:
    IRIS runs db.create_all() from the ORM before alembic, so a fresh install
    creates this table from the model and the migration's guarded create is
    skipped (fork rule).
    """
    __tablename__ = 'mail_rule'

    id = Column(BigInteger, primary_key=True)
    rule_uuid = Column(UUID(as_uuid=True), default=uuid.uuid4,
                       server_default=text('gen_random_uuid()'), nullable=False, unique=True)
    name = Column(Text, nullable=False)
    enabled = Column(Boolean, nullable=False, server_default=text('true'))
    priority = Column(Integer, nullable=False, server_default=text('100'))
    conditions = Column(JSON, nullable=False, server_default=text("'[]'::json"))
    action = Column(String(32), nullable=False, server_default=text("'create_alert'"))
    is_fallback = Column(Boolean, nullable=False, server_default=text('false'))

    # Alert defaults applied when action = create_alert (the AI triage may
    # refine severity/classification when enabled; these are the floor).
    customer_id = Column(BigInteger, ForeignKey('client.client_id'), nullable=False)
    severity_id = Column(Integer, ForeignKey('severities.severity_id'), nullable=True)
    classification_id = Column(Integer, ForeignKey('case_classification.id'), nullable=True)
    alert_source = Column(Text, nullable=False, server_default=text("'Mail'"))
    # Safe substitution only ({subject}, {from}, {to}) - never str.format.
    title_template = Column(Text, nullable=True)

    created_by = Column(BigInteger, ForeignKey('user.id'), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text('now()'))
    updated_at = Column(DateTime, nullable=False, server_default=text('now()'))

    customer = relationship('Client')
    severity = relationship('Severity')
    classification = relationship('CaseClassification')
    creator = relationship('User')

    __table_args__ = (
        CheckConstraint("action IN ('create_alert', 'ignore')",
                        name='ck_mail_rule_action'),
    )


class MailIngestLog(db.Model):
    """iris-ng v2 (Phase 1): one row per email the poller processed, whatever
    the outcome - the audit trail behind the Recent Ingest Activity panel and
    the dedup barrier. Dedup is two-layer: the RFC Message-ID (unique below;
    Postgres permits multiple NULLs, so messages without one fall through) and
    a code-side (imap_uid, folder) check for that case.

    Errors are RECORDED here, never raised past the per-message loop - one
    poison message must not stop the mailbox.
    """
    __tablename__ = 'mail_ingest_log'

    id = Column(BigInteger, primary_key=True)
    message_id = Column(Text, nullable=True)
    imap_uid = Column(Text, nullable=True)
    folder = Column(Text, nullable=True)
    from_addr = Column(Text, nullable=True)
    subject = Column(Text, nullable=True)
    received_at = Column(DateTime, nullable=True)
    processed_at = Column(DateTime, nullable=False, server_default=text('now()'))
    # SET NULL on both: deleting a rule or an alert must never break the audit log.
    rule_id = Column(BigInteger, ForeignKey('mail_rule.id', ondelete='SET NULL'), nullable=True)
    outcome = Column(String(32), nullable=False)
    alert_id = Column(BigInteger, ForeignKey('alerts.alert_id', ondelete='SET NULL'), nullable=True)
    error = Column(Text, nullable=True)
    # Audit copy of what the AI mail triage returned (or its error), for the
    # log panel - deliberately NOT a cached artifact (emails are one-shot).
    ai_triage = Column(JSON, nullable=True)

    rule = relationship('MailRule')
    alert = relationship('Alert')

    __table_args__ = (
        UniqueConstraint('message_id', name='uq_mail_ingest_message_id'),
        CheckConstraint(
            "outcome IN ('alert_created', 'ignored', 'no_match', 'duplicate', 'error')",
            name='ck_mail_ingest_outcome'),
        Index('idx_mail_ingest_processed_at', 'processed_at'),
    )


class AlertClusteringRule(db.Model):
    """iris-ng v2 (Phase 2): one rule grouping incoming alerts into Alert
    Clusters. Evaluated ascending by priority at ingest time (synchronously,
    inside create_alert_from_payload's post-create pipeline); the first ENABLED
    rule whose match_conditions accept the alert claims it — an alert belongs
    to at most one cluster in v1 (UNIQUE(alert_id) on the member table).

    match_conditions is a JSON condition tree evaluated in PYTHON over an
    alert_view dict (business/condition_eval.py) — alert_context is plain
    ``json``, not ``jsonb``, so SQL-side evaluation is not available. Leaves
    are {"field", "operator", "value"}; groups are {"and"|"or": [...]} and
    {"not": node}; an empty tree matches every alert of any customer, so
    pair it with tight correlation_keys.

    correlation_keys is a JSON list of dotted paths into the same alert_view
    (e.g. ["alert_source", "alert_context.hostname"]). Their resolved values —
    plus rule id and customer id, ALWAYS, for tenant isolation by
    construction — are hashed into the cluster fingerprint.

    CHECK constraints live here on __table_args__, not only in the migration:
    IRIS runs db.create_all() from the ORM before alembic (fork rule).
    """
    __tablename__ = 'alert_clustering_rule'

    id = Column(BigInteger, primary_key=True)
    rule_uuid = Column(UUID(as_uuid=True), default=uuid.uuid4,
                       server_default=text('gen_random_uuid()'), nullable=False, unique=True)
    name = Column(Text, nullable=False)
    enabled = Column(Boolean, nullable=False, server_default=text('true'))
    priority = Column(Integer, nullable=False, server_default=text('100'))
    match_conditions = Column(JSON, nullable=False, server_default=text("'{}'::json"))
    correlation_keys = Column(JSON, nullable=False, server_default=text("'[]'::json"))
    # Stacking window: a new matching alert more than window_minutes after the
    # open cluster's last_alert_at closes it and opens a fresh one.
    window_minutes = Column(Integer, nullable=False, server_default=text('1440'))
    # Safe {path} substitution against the alert_view — never str.format.
    title_template = Column(Text, nullable=True)

    created_by = Column(BigInteger, ForeignKey('user.id'), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text('now()'))
    updated_at = Column(DateTime, nullable=False, server_default=text('now()'))

    creator = relationship('User')

    __table_args__ = (
        CheckConstraint('window_minutes > 0',
                        name='ck_alert_clustering_rule_window'),
    )


class AlertCluster(db.Model):
    """iris-ng v2 (Phase 2): a group of alerts stacked by a clustering rule.
    Named Alert Cluster throughout — the computed IOC "correlation clusters"
    on the dashboard are a different feature and keep their name.

    correlation_fingerprint = sha256(rule_id | customer_id | sorted resolved
    key=value pairs)[:32]. The PARTIAL unique index (fingerprint WHERE
    status='open') is the concurrency contract: at most one OPEN cluster per
    fingerprint, so two racing ingests both trying to create it get one
    IntegrityError, and the loser re-SELECTs and joins. Closed clusters with
    the same fingerprint accumulate freely (history).

    NOTE for the create_all path: the partial index IS declared below via
    Index(..., unique=True, postgresql_where=...), so a fresh install gets it
    from the ORM — same reason the CHECKs are here.
    """
    __tablename__ = 'alert_cluster'

    id = Column(BigInteger, primary_key=True)
    cluster_uuid = Column(UUID(as_uuid=True), default=uuid.uuid4,
                          server_default=text('gen_random_uuid()'), nullable=False, unique=True)
    # SET NULL: deleting a rule must never destroy the clusters it built.
    rule_id = Column(BigInteger, ForeignKey('alert_clustering_rule.id', ondelete='SET NULL'),
                     nullable=True)
    customer_id = Column(BigInteger, ForeignKey('client.client_id'), nullable=False)
    correlation_fingerprint = Column(String(64), nullable=False)
    # Resolved {path: value} pairs at cluster-open time, for display.
    correlation_values = Column(JSON, nullable=True)
    title = Column(Text, nullable=False)
    status = Column(String(16), nullable=False, server_default=text("'open'"))
    # Ingest times (alert_creation_time), not source event times — the
    # stacking window is about arrival bursts, and event times arrive out of
    # order (documented in business/alert_clustering.py).
    first_alert_at = Column(DateTime, nullable=False, server_default=text('now()'))
    last_alert_at = Column(DateTime, nullable=False, server_default=text('now()'))
    closed_at = Column(DateTime, nullable=True)
    closed_by = Column(BigInteger, ForeignKey('user.id'), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text('now()'))

    # v3 parity (2026-09-01): the cluster's DISPLAYED severity is DERIVED as
    # the highest member-alert severity (rank by NAME — severity_id order is
    # not intensity order on this schema); a non-NULL override pins it until
    # cleared. NULL = derived, always truthful.
    severity_override_id = Column(ForeignKey('severities.severity_id'), nullable=True)
    owner_id = Column(BigInteger, ForeignKey('user.id'), nullable=True)
    # Analyst-owned summary document (v3 Summary tab, autosave). The AI
    # triage narrative stays a separate artifact — clear ownership.
    summary = Column(Text, nullable=True)
    # Provenance of a full-cluster escalate/merge. SET NULL: deleting the
    # case must never destroy the cluster history.
    escalated_case_id = Column(BigInteger,
                               ForeignKey('cases.case_id', ondelete='SET NULL'),
                               nullable=True)

    rule = relationship('AlertClusteringRule')
    customer = relationship('Client')
    closer = relationship('User', foreign_keys=[closed_by])
    owner = relationship('User', foreign_keys=[owner_id])
    severity_override = relationship('Severity')

    # v3 status vocabulary (2026-09-01): open/investigating/dismissed/
    # escalated are the analyst-facing states; 'closed' is kept for
    # window-expiry auto-closes and legacy rows. The ACTIVE set — clusters
    # that accept new members, and the unique-index predicate — is
    # ('open','investigating'), so marking a cluster Investigating cannot
    # cause a parallel duplicate on the next matching alert.
    __table_args__ = (
        CheckConstraint("status IN ('open', 'investigating', 'dismissed', "
                        "'escalated', 'closed')",
                        name='ck_alert_cluster_status'),
        Index('uq_alert_cluster_open_fingerprint', 'correlation_fingerprint',
              unique=True,
              postgresql_where=text("status IN ('open', 'investigating')")),
        Index('idx_alert_cluster_customer', 'customer_id'),
    )


class AlertClusterMember(db.Model):
    """iris-ng v2 (Phase 2): (cluster, alert) membership. UNIQUE(alert_id)
    enforces the v1 rule that an alert belongs to at most one cluster —
    first-match by rule priority claims it. CASCADE both ways: deleting an
    alert or a cluster removes the membership row, never blocks the delete.
    """
    __tablename__ = 'alert_cluster_member'

    cluster_id = Column(BigInteger,
                        ForeignKey('alert_cluster.id', ondelete='CASCADE'),
                        primary_key=True, nullable=False)
    alert_id = Column(BigInteger,
                      ForeignKey('alerts.alert_id', ondelete='CASCADE'),
                      primary_key=True, nullable=False, index=True)
    added_at = Column(DateTime, nullable=False, server_default=text('now()'))

    cluster = relationship('AlertCluster')
    alert = relationship('Alert')

    __table_args__ = (
        UniqueConstraint('alert_id', name='uq_alert_cluster_member_alert'),
    )


class AlertClusterComment(db.Model):
    """iris-ng v2 (v3 parity, 2026-09-01): analyst comments on an alert
    cluster — the v3 Activity tab is a comment feed. DEDICATED table on
    purpose: widening the upstream Comments model with a cluster FK would
    change what CommentSchema dumps to every existing API client (never
    widen a public schema for a private UI need). CASCADE: deleting the
    cluster deletes its feed.
    """
    __tablename__ = 'alert_cluster_comment'

    id = Column(BigInteger, primary_key=True)
    cluster_id = Column(BigInteger,
                        ForeignKey('alert_cluster.id', ondelete='CASCADE'),
                        nullable=False, index=True)
    user_id = Column(BigInteger, ForeignKey('user.id'), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=text('now()'))

    cluster = relationship('AlertCluster')
    user = relationship('User')


class InvestigationFlow(db.Model):
    """iris-ng v2 (Phase 3): a checklist auto-attached to alerts and/or
    clusters whose triggering alert matches the flow's condition tree
    (business/condition_eval.py — the same grammar clustering rules use).

    target: 'alert' attaches to every matching alert; 'cluster' attaches to
    a cluster when the alert that CREATES it matches; 'both' does both. ALL
    matching flows attach (checklists are not exclusive); priority only
    orders display.

    Live-edit caveat (documented in the admin UI): steps belong to the FLOW,
    so editing a deployed flow changes every attached checklist. Step STATES
    survive edits (keyed by step id); deleting a step deletes its states.

    CHECK constraints live on __table_args__ (create_all-before-alembic
    fork rule).
    """
    __tablename__ = 'investigation_flow'

    id = Column(BigInteger, primary_key=True)
    flow_uuid = Column(UUID(as_uuid=True), default=uuid.uuid4,
                       server_default=text('gen_random_uuid()'), nullable=False, unique=True)
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    enabled = Column(Boolean, nullable=False, server_default=text('true'))
    priority = Column(Integer, nullable=False, server_default=text('100'))
    target = Column(String(16), nullable=False, server_default=text("'alert'"))
    match_conditions = Column(JSON, nullable=False, server_default=text("'{}'::json"))

    created_by = Column(BigInteger, ForeignKey('user.id'), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text('now()'))
    updated_at = Column(DateTime, nullable=False, server_default=text('now()'))

    creator = relationship('User')
    steps = relationship('FlowStep', order_by='FlowStep.step_order',
                         cascade='all, delete-orphan', back_populates='flow')

    __table_args__ = (
        CheckConstraint("target IN ('alert', 'cluster', 'both')",
                        name='ck_investigation_flow_target'),
    )


class FlowStep(db.Model):
    """iris-ng v2 (Phase 3): one ordered step of a flow. is_required is
    ADVISORY in v1 — an amber "N required steps incomplete" banner, nothing
    blocks (a block-flag is an explicit v2 candidate)."""
    __tablename__ = 'investigation_flow_step'

    id = Column(BigInteger, primary_key=True)
    flow_id = Column(BigInteger,
                     ForeignKey('investigation_flow.id', ondelete='CASCADE'),
                     nullable=False, index=True)
    step_order = Column(Integer, nullable=False)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    is_required = Column(Boolean, nullable=False, server_default=text('false'))

    flow = relationship('InvestigationFlow', back_populates='steps')

    __table_args__ = (
        UniqueConstraint('flow_id', 'step_order', name='uq_flow_step_order'),
    )


class FlowAttachment(db.Model):
    """iris-ng v2 (Phase 3): a flow instance on exactly one anchor (alert XOR
    cluster — enforced by CHECK). UNIQUE(flow, anchor) makes attachment
    idempotent: re-deploys and repeat evaluations are natural no-ops
    (Postgres UNIQUE ignores NULL columns, so the two per-anchor uniques
    coexist). Ingest writes ONLY this row — step states are lazily created
    on first read (FlowStepState), keeping the ingest hot path minimal.
    """
    __tablename__ = 'flow_attachment'

    id = Column(BigInteger, primary_key=True)
    flow_id = Column(BigInteger,
                     ForeignKey('investigation_flow.id', ondelete='CASCADE'),
                     nullable=False, index=True)
    alert_id = Column(BigInteger,
                      ForeignKey('alerts.alert_id', ondelete='CASCADE'),
                      nullable=True, index=True)
    cluster_id = Column(BigInteger,
                        ForeignKey('alert_cluster.id', ondelete='CASCADE'),
                        nullable=True, index=True)
    attached_at = Column(DateTime, nullable=False, server_default=text('now()'))

    flow = relationship('InvestigationFlow')
    alert = relationship('Alert')
    cluster = relationship('AlertCluster')

    __table_args__ = (
        CheckConstraint('(alert_id IS NULL) != (cluster_id IS NULL)',
                        name='ck_flow_attachment_one_anchor'),
        UniqueConstraint('flow_id', 'alert_id', name='uq_flow_attachment_alert'),
        UniqueConstraint('flow_id', 'cluster_id', name='uq_flow_attachment_cluster'),
    )


class FlowStepState(db.Model):
    """iris-ng v2 (Phase 3): per-attachment progress on one step. Rows are
    created lazily on first read of the attachment's checklist — pending by
    default; done/skipped carry who + when + an optional analyst note."""
    __tablename__ = 'flow_step_state'

    id = Column(BigInteger, primary_key=True)
    attachment_id = Column(BigInteger,
                           ForeignKey('flow_attachment.id', ondelete='CASCADE'),
                           nullable=False, index=True)
    step_id = Column(BigInteger,
                     ForeignKey('investigation_flow_step.id', ondelete='CASCADE'),
                     nullable=False, index=True)
    state = Column(String(16), nullable=False, server_default=text("'pending'"))
    done_by = Column(BigInteger, ForeignKey('user.id'), nullable=True)
    done_at = Column(DateTime, nullable=True)
    note = Column(Text, nullable=True)

    step = relationship('FlowStep')
    attachment = relationship('FlowAttachment')
    done_by_user = relationship('User')

    __table_args__ = (
        CheckConstraint("state IN ('pending', 'done', 'skipped')",
                        name='ck_flow_step_state'),
        UniqueConstraint('attachment_id', 'step_id', name='uq_flow_step_state'),
    )
