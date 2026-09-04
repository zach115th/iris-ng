#  IRIS Source Code
#  Copyright (C) 2021 - Airbus CyberSecurity (SAS)
#  ir@cyberactionlab.net
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
import datetime
# IMPORTS ------------------------------------------------
import enum
import uuid

from sqlalchemy import BigInteger, UniqueConstraint, Table, CheckConstraint
from sqlalchemy import Index
from sqlalchemy import Boolean
from sqlalchemy import Column
from sqlalchemy import Date
from sqlalchemy import DateTime
from sqlalchemy import Float
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import LargeBinary
from sqlalchemy import Sequence
from sqlalchemy import String
from sqlalchemy import TIMESTAMP
from sqlalchemy import Text
from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSON, JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import declared_attr
from sqlalchemy.orm import relationship
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func

from app import app
from app import db

Base = declarative_base()
metadata = Base.metadata


class CaseStatus(enum.Enum):
    unknown = 0x0
    false_positive = 0x1
    true_positive_with_impact = 0x2
    not_applicable = 0x3
    true_positive_without_impact = 0x4
    legitimate = 0x5


class ReviewStatusList:
    no_review_required = "No review required"
    not_reviewed = "Not reviewed"
    pending_review = "Pending review"
    review_in_progress = "Review in progress"
    reviewed = "Reviewed"


class CompromiseStatus(enum.Enum):
    to_be_determined = 0x0
    compromised = 0x1
    not_compromised = 0x2
    unknown = 0x3

    @classmethod
    def has_value(cls, value):
        return value in cls._value2member_map_


def create_safe(session, model, **kwargs):
    instance = session.query(model).filter_by(**kwargs).first()
    if instance:
        return False
    else:
        instance = model(**kwargs)
        session.add(instance)
        session.commit()
        return True


def create_safe_limited(session, model, keywords_list, **kwargs):
    kwdup = kwargs.keys()
    for kw in list(kwdup):
        if kw not in keywords_list:
            kwargs.pop(kw)

    instance = session.query(model).filter_by(**kwargs).first()
    if instance:
        return False
    else:
        instance = model(**kwargs)
        session.add(instance)
        session.commit()
        return True


def get_by_value_or_create(session, model, fieldname, **kwargs):
    select_value = {fieldname: kwargs.get(fieldname)}
    instance = session.query(model).filter_by(**select_value).first()
    if instance:
        return instance
    else:
        instance = model(**kwargs)
        session.add(instance)
        session.commit()
        return instance


def get_or_create(session, model, **kwargs):
    instance = session.query(model).filter_by(**kwargs).first()
    if instance:
        return instance
    else:
        instance = model(**kwargs)
        session.add(instance)
        session.commit()
        return instance


class Client(db.Model):
    __tablename__ = 'client'

    client_id = Column(BigInteger, primary_key=True)
    client_uuid = Column(UUID(as_uuid=True), server_default=text("gen_random_uuid()"), nullable=False)
    name = Column(Text, unique=True)
    description = Column(Text)
    sla = Column(Text)
    creation_date = Column(DateTime, server_default=func.now(), nullable=True)
    created_by = Column(ForeignKey('user.id'), nullable=True)
    last_update_date = Column(DateTime, server_default=func.now(), nullable=True)

    # iris-next: comma-separated DHS CIIP sector slugs (e.g. "financial-services,it").
    # New cases for this customer inherit these as case tags when the create
    # payload doesn't already include a sector tag. See app/business/cases.py.
    dhs_sectors = Column(Text, nullable=True)

    custom_attributes = Column(JSON)


class AssetsType(db.Model):
    __tablename__ = 'assets_type'

    asset_id = Column(Integer, primary_key=True)
    asset_name = Column(String(155))
    asset_description = Column(String(255))
    asset_icon_not_compromised = Column(String(255))
    asset_icon_compromised = Column(String(255))


alert_assets_association = Table(
    'alert_assets_association',
    db.Model.metadata,
    Column('alert_id', ForeignKey('alerts.alert_id'), primary_key=True),
    Column('asset_id', ForeignKey('case_assets.asset_id'), primary_key=True)
)

alert_iocs_association = Table(
    'alert_iocs_association',
    db.Model.metadata,
    Column('alert_id', ForeignKey('alerts.alert_id'), primary_key=True),
    Column('ioc_id', ForeignKey('ioc.ioc_id'), primary_key=True)
)


class CaseAssets(db.Model):
    __tablename__ = 'case_assets'

    asset_id = Column(BigInteger, primary_key=True)
    asset_uuid = Column(UUID(as_uuid=True), server_default=text("gen_random_uuid()"), nullable=False)
    asset_name = Column(Text)
    asset_description = Column(Text)
    asset_domain = Column(Text)
    asset_ip = Column(Text)
    asset_info = Column(Text)
    asset_compromise_status_id = Column(Integer, nullable=True)
    asset_type_id = Column(ForeignKey('assets_type.asset_id'))
    asset_tags = Column(Text)
    case_id = Column(ForeignKey('cases.case_id'))
    date_added = Column(DateTime)
    date_update = Column(DateTime)
    user_id = Column(ForeignKey('user.id'))
    analysis_status_id = Column(ForeignKey('analysis_status.id'))
    custom_attributes = Column(JSON)
    asset_enrichment = Column(JSONB)
    modification_history = Column(JSON)

    case = relationship('Cases')
    user = relationship('User')
    asset_type = relationship('AssetsType')
    analysis_status = relationship('AnalysisStatus')

    alerts = relationship('Alert', secondary=alert_assets_association, back_populates='assets')
    iocs = relationship('IocAssetLink', back_populates='asset')
    evidences = relationship('EvidenceAssetLink', back_populates='asset', cascade='all, delete-orphan')


class AnalysisStatus(db.Model):
    __tablename__ = 'analysis_status'

    id = Column(Integer, primary_key=True)
    name = Column(Text)


class CaseClassification(db.Model):
    __tablename__ = 'case_classification'

    id = Column(Integer, primary_key=True)
    name = Column(Text)
    name_expanded = Column(Text)
    description = Column(Text)
    creation_date = Column(DateTime, server_default=func.now(), nullable=True)
    created_by_id = Column(ForeignKey('user.id'), nullable=True)

    created_by = relationship('User')


class SectorCatalog(db.Model):
    """iris-ng: admin-editable sector catalog (Case Objects > Sectors).

    Replaces the hardcoded sector picker options + the recognition dicts in
    business/cases.py and business/dashboard_metrics.py. `slug` is the stable
    key — Client.dhs_sectors stores bare slugs, so it must never change once
    customers reference it. `tag` is the full MISP machine-tag the picker
    emits (e.g. dhs-ciip-sectors:DHS-critical-sectors="water" or
    threatmatch:sector="Education"). `enabled` gates the PICKERS only —
    recognition (soft-enforcement + metrics) derives from ALL rows so
    disabling a sector never orphans historical tags; deleting a row in a
    namespace the legacy constants don't cover does.
    """
    __tablename__ = 'sector_catalog'

    id = Column(Integer, primary_key=True)
    slug = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    tag = Column(Text, nullable=False)
    enabled = Column(Boolean, nullable=False, server_default=text('true'))
    creation_date = Column(DateTime, server_default=func.now(), nullable=True)

    __table_args__ = (
        UniqueConstraint('slug', name='uq_sector_catalog_slug'),
    )


class EvidenceTypes(db.Model):
    __tablename__ = 'evidence_type'

    id = Column(Integer, primary_key=True)
    name = Column(Text)
    description = Column(Text)
    creation_date = Column(DateTime, server_default=func.now(), nullable=True)
    created_by_id = Column(ForeignKey('user.id'), nullable=True)

    created_by = relationship('User')


class CaseTemplate(db.Model):
    __tablename__ = 'case_template'

    # Metadata
    id = Column(Integer, primary_key=True)
    created_by_user_id = Column(Integer, db.ForeignKey('user.id'))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    # Data
    name = Column(String, nullable=False)
    display_name = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    author = Column(String, nullable=True)
    title_prefix = Column(String, nullable=True)
    summary = Column(String, nullable=True)
    tags = Column(JSON, nullable=True)
    tasks = Column(JSON, nullable=True)
    note_directories = Column(JSON, nullable=True)
    classification = Column(String, nullable=True)

    created_by_user = relationship('User')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def update_from_dict(self, data: dict):
        for field, value in data.items():
            setattr(self, field, value)


class Contact(db.Model):
    __tablename__ = 'contact'

    id = Column(BigInteger, primary_key=True)
    contact_uuid = Column(UUID(as_uuid=True), server_default=text("gen_random_uuid()"), nullable=False)
    contact_name = Column(Text)
    contact_email = Column(Text)
    contact_role = Column(Text)
    contact_note = Column(Text)
    contact_work_phone = Column(Text)
    contact_mobile_phone = Column(Text)
    custom_attributes = Column(JSON)
    client_id = Column(ForeignKey('client.client_id'))

    client = relationship('Client')


class CaseEventsAssets(db.Model):
    __tablename__ = 'case_events_assets'

    id = Column(BigInteger, primary_key=True)
    event_id = Column(ForeignKey('cases_events.event_id'))
    asset_id = Column(ForeignKey('case_assets.asset_id'))
    case_id = Column(ForeignKey('cases.case_id'))

    event = relationship('CasesEvent')
    asset = relationship('CaseAssets')
    case = relationship('Cases')


class CaseEventsIoc(db.Model):
    __tablename__ = 'case_events_ioc'

    id = Column(BigInteger, primary_key=True)
    event_id = Column(ForeignKey('cases_events.event_id'))
    ioc_id = Column(ForeignKey('ioc.ioc_id'))
    case_id = Column(ForeignKey('cases.case_id'))

    event = relationship('CasesEvent')
    ioc = relationship('Ioc')
    case = relationship('Cases')


class ObjectState(db.Model):
    __tablename__ = 'object_state'

    object_id = Column(BigInteger, primary_key=True)
    object_case_id = Column(ForeignKey('cases.case_id'))
    object_updated_by_id = db.Column(db.Integer(), db.ForeignKey('user.id'))
    object_name = Column(Text)
    object_state = Column(BigInteger)
    object_last_update = Column(TIMESTAMP)

    case = relationship('Cases')
    updated_by = relationship('User')


class EventCategory(db.Model):
    __tablename__ = 'event_category'

    id = Column(Integer, primary_key=True)
    name = Column(Text)


class CaseEventCategory(db.Model):
    __tablename__ = 'case_events_category'

    id = Column(Integer, primary_key=True)
    event_id = Column(ForeignKey('cases_events.event_id'), unique=True)
    category_id = Column(ForeignKey('event_category.id'))

    event = relationship('CasesEvent', cascade="delete")
    category = relationship('EventCategory')


class CaseGraphAssets(db.Model):
    __tablename__ = 'case_graph_assets'

    id = Column(Integer, primary_key=True)
    case_id = Column(ForeignKey('cases.case_id'))
    asset_id = Column(Integer)
    asset_type_id = Column(ForeignKey('assets_type.asset_id'))

    case = relationship('Cases')
    asset_type = relationship('AssetsType')


class CaseGraphLinks(db.Model):
    __tablename__ = 'case_graph_links'

    id = Column(Integer, primary_key=True)
    case_id = Column(ForeignKey('cases.case_id'))
    source_id = Column(ForeignKey('case_graph_assets.id'))
    dest_id = Column(ForeignKey('case_graph_assets.id'))

    case = relationship('Cases')


class Languages(db.Model):
    __tablename__ = 'languages'

    id = db.Column(db.Integer(), primary_key=True)
    name = db.Column(db.String(), unique=True)
    code = db.Column(db.String(), unique=True)


class ReportType(db.Model):
    __tablename__ = 'report_type'

    id = db.Column(db.Integer(), primary_key=True)
    name = db.Column(db.Text(), unique=True)


class CaseTemplateReport(db.Model):
    __tablename__ = 'case_template_report'

    id = db.Column(db.Integer(), primary_key=True)
    name = db.Column(db.String())
    description = db.Column(db.String())
    internal_reference = db.Column(db.String(), unique=True)
    naming_format = db.Column(db.String())
    created_by_user_id = db.Column(db.Integer(), db.ForeignKey('user.id'))
    date_created = db.Column(DateTime)
    language_id = db.Column(db.Integer(), db.ForeignKey('languages.id'))
    report_type_id = db.Column(db.Integer(), db.ForeignKey('report_type.id'))

    report_type = relationship('ReportType')
    language = relationship('Languages')
    created_by_user = relationship('User')


class Tlp(db.Model):
    __tablename__ = 'tlp'

    tlp_id = Column(Integer, primary_key=True)
    tlp_name = Column(Text)
    tlp_bscolor = Column(Text)


class Ioc(db.Model):
    __tablename__ = 'ioc'

    ioc_id = Column(BigInteger, primary_key=True)
    ioc_uuid = Column(UUID(as_uuid=True), server_default=text("gen_random_uuid()"), nullable=False)
    ioc_value = Column(Text)
    ioc_type_id = Column(ForeignKey('ioc_type.type_id'))
    ioc_description = Column(Text)
    ioc_tags = Column(String(512))
    user_id = Column(ForeignKey('user.id'))
    ioc_misp = Column(Text)
    ioc_tlp_id = Column(ForeignKey('tlp.tlp_id'))
    custom_attributes = Column(JSON)
    ioc_enrichment = Column(JSONB)
    modification_history = Column(JSON)

    case_id = Column(ForeignKey('cases.case_id'), nullable=True)

    user = relationship('User')
    tlp = relationship('Tlp')
    ioc_type = relationship('IocType')
    case = relationship('Cases')
    assets = relationship('IocAssetLink', back_populates='ioc', cascade="delete")
    events = relationship('CaseEventsIoc', back_populates='ioc', cascade="delete")
    comments = relationship('IocComments', back_populates='ioc', cascade="all, delete")
    alerts = relationship('Alert', secondary=alert_iocs_association, back_populates='iocs')
    misp_attribute_link = relationship('MispAttributeLink', back_populates='ioc', uselist=False,
                                       cascade="all, delete-orphan")


class CustomAttribute(db.Model):
    __tablename__ = 'custom_attribute'

    attribute_id = Column(Integer, primary_key=True)
    attribute_display_name = Column(Text)
    attribute_description = Column(Text)
    attribute_for = Column(Text)
    attribute_content = Column(JSON)


class DataStorePath(db.Model):
    __tablename__ = 'data_store_path'

    path_id = Column(BigInteger, primary_key=True)
    path_uuid = Column(UUID(as_uuid=True), default=uuid.uuid4)
    path_name = Column(Text, nullable=False)
    path_parent_id = Column(BigInteger)
    path_is_root = Column(Boolean)
    path_case_id = Column(ForeignKey('cases.case_id'), nullable=False)

    case = relationship('Cases')


class DataStoreFile(db.Model):
    __tablename__ = 'data_store_file'

    file_id = Column(BigInteger, primary_key=True)
    file_uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, server_default=text("gen_random_uuid()"), nullable=False)
    file_original_name = Column(Text, nullable=False)
    file_local_name = Column(Text, nullable=False)
    file_description = Column(Text)
    file_date_added = Column(DateTime)
    file_tags = Column(Text)
    file_size = Column(BigInteger)
    file_is_ioc = Column(Boolean)
    file_is_evidence = Column(Boolean)
    file_password = Column(Text)
    file_parent_id = Column(ForeignKey('data_store_path.path_id'), nullable=False)
    file_sha256 = Column(Text)
    added_by_user_id = Column(ForeignKey('user.id'), nullable=False)
    modification_history = Column(JSON)
    file_case_id = Column(ForeignKey('cases.case_id'), nullable=False)

    case = relationship('Cases')
    user = relationship('User')
    data_parent = relationship('DataStorePath')


class IocType(db.Model):
    __tablename__ = 'ioc_type'

    type_id = Column(Integer, primary_key=True)
    type_name = Column(Text)
    type_description = Column(Text)
    type_taxonomy = Column(Text)
    type_validation_regex = Column(Text)
    type_validation_expect = Column(Text)


class MispEventLink(db.Model):
    __tablename__ = 'misp_event_link'

    id = Column(BigInteger, primary_key=True)
    case_id = Column(ForeignKey('cases.case_id'), nullable=False, unique=True)
    misp_event_id = Column(BigInteger, nullable=False, unique=True)
    misp_event_uuid = Column(Text, nullable=True, unique=True)
    misp_org_id = Column(Integer, nullable=True)
    misp_distribution = Column(Integer, nullable=True)
    misp_sharing_group_id = Column(Integer, nullable=True)
    date_created = Column(DateTime, server_default=func.now(), nullable=False)
    last_synced_at = Column(DateTime, nullable=True)

    case = relationship('Cases')
    attributes = relationship('MispAttributeLink', back_populates='event_link',
                              cascade="all, delete-orphan")


class MispAttributeLink(db.Model):
    __tablename__ = 'misp_attribute_link'

    id = Column(BigInteger, primary_key=True)
    event_link_id = Column(ForeignKey('misp_event_link.id'), nullable=False)
    # One IRIS IOC has at most one MISP attribute — this direction IS unique.
    ioc_id = Column(ForeignKey('ioc.ioc_id'), nullable=False, unique=True)
    # The reverse direction is NOT unique, and used to be (dropped in
    # d1a7c93f5e64). MISP deduplicates attributes within an event by
    # (type, value, category), so it hands the SAME attribute id to two
    # different IRIS IOCs whenever they share a value+type in one case — or
    # when an IOC is deleted and recreated, since that mints a new ioc_id and
    # a new ioc_uuid while MISP still holds the original attribute. Marking
    # these unique encoded an invariant MISP does not honour, and the insert
    # died on a UniqueViolation instead of syncing.
    misp_attribute_id = Column(BigInteger, nullable=False, index=True)
    misp_attribute_uuid = Column(Text, nullable=True, index=True)
    date_created = Column(DateTime, server_default=func.now(), nullable=False)
    last_synced_at = Column(DateTime, nullable=True)

    event_link = relationship('MispEventLink', back_populates='attributes')
    ioc = relationship('Ioc', back_populates='misp_attribute_link')


class AiOverrideMixin:
    """Analyst manual override of AI output (iris-ng; extracted to a mixin in
    v2 Phase 2 — refactor only, no schema change to case_ai_artifact).

    `content` always keeps the ORIGINAL model output so "View AI original" /
    "Revert to AI" stay available; `edited_content` is the analyst's corrected
    text and, when non-NULL, is what every read surface displays
    (``display_content``). Regeneration is guarded at the endpoint layer —
    a new generation inserts a NEW row, so an unguarded regen would silently
    orphan the edit (HTTP 409 unless discard_edit=true, built via response(),
    never response_api_error).
    """

    @declared_attr
    def edited_content(cls):
        return Column(Text, nullable=True)

    @declared_attr
    def edited_by_id(cls):
        return Column(ForeignKey('user.id'), nullable=True)

    @declared_attr
    def edited_at(cls):
        return Column(DateTime, nullable=True)

    @declared_attr
    def edited_by(cls):
        return relationship('User', foreign_keys=[cls.edited_by_id])

    @property
    def display_content(self) -> str:
        """Text that should be shown to analysts — the edit when present."""
        return self.edited_content if self.edited_content else self.content

    @property
    def is_edited(self) -> bool:
        return self.edited_content is not None


class CaseAiArtifact(AiOverrideMixin, db.Model):
    """Cached AI output keyed by (case_id, kind, input_hash).

    `kind` discriminates feature (e.g. 'case_summary'). `input_hash` is the
    MD5 of the canonical input payload used to generate `content`; identical
    inputs short-circuit to the cached row instead of re-calling the model.
    Manual-override columns + display_content/is_edited come from
    AiOverrideMixin (same columns as before the v2 refactor).
    """
    __tablename__ = 'case_ai_artifact'

    id = Column(BigInteger, primary_key=True)
    case_id = Column(ForeignKey('cases.case_id', ondelete='CASCADE'), nullable=False, index=True)
    kind = Column(String(64), nullable=False)
    prompt_id = Column(String(128), nullable=False)
    model = Column(String(128), nullable=False)
    input_hash = Column(String(64), nullable=False, index=True)
    content = Column(Text, nullable=False)
    confidence = Column(Float, nullable=True)
    generated_at = Column(DateTime, server_default=func.now(), nullable=False)

    case = relationship('Cases')


class CustomerAsset(db.Model):
    """iris-ng v2 (Phase 4): org-wide asset registry — one row per asset a
    customer is known to have, aggregated across every case and alert.

    Identity is UNIQUE(customer_id, asset_name_norm, asset_type_id) with
    asset_name_norm = lower(trim(name)) and **no domain stripping** — 'host'
    and 'host.corp.local' are different assets (this is the rule that lived
    as dead code in CaseAssetsSchema.is_unique_for_customer, now enforced).
    Display casing (asset_name) is first-seen.

    Sync (business/customer_assets.py) only ever advances last_seen and
    RAISES compromise status from NULL/to_be_determined/unknown — it never
    overwrites analyst-set curation fields (criticality/environment/owner/
    notes/compromise downgrades). created_by NULL = the system sync created
    the row.

    Sightings are computed LIVE from case_assets/alert links — deliberately
    not denormalized here.
    """
    __tablename__ = 'customer_asset'

    id = Column(BigInteger, primary_key=True)
    customer_id = Column(BigInteger, ForeignKey('client.client_id', ondelete='CASCADE'),
                         nullable=False, index=True)
    asset_name = Column(Text, nullable=False)
    asset_name_norm = Column(Text, nullable=False)
    asset_type_id = Column(Integer, ForeignKey('assets_type.asset_id'), nullable=False)
    criticality = Column(String(16), nullable=True)
    environment = Column(Text, nullable=True)
    owner = Column(Text, nullable=True)
    # Reuses the CompromiseStatus enum values (0 tbd / 1 compromised /
    # 2 not_compromised / 3 unknown); NULL = never assessed.
    compromise_status = Column(Integer, nullable=True)
    compromise_since = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    first_seen = Column(DateTime, nullable=False, server_default=text('now()'))
    last_seen = Column(DateTime, nullable=False, server_default=text('now()'))
    created_by = Column(BigInteger, ForeignKey('user.id'), nullable=True)

    customer = relationship('Client')
    asset_type = relationship('AssetsType')
    creator = relationship('User')

    __table_args__ = (
        UniqueConstraint('customer_id', 'asset_name_norm', 'asset_type_id',
                         name='uq_customer_asset_identity'),
        CheckConstraint("criticality IN ('low', 'medium', 'high', 'critical')",
                        name='ck_customer_asset_criticality'),
    )


class CustomerAssetChange(db.Model):
    """iris-ng v2 (Phase 4): dedicated audit rows for registry changes —
    chosen over a JSON modification_history blob because org-level audit
    needs cross-asset queries ("what changed criticality this month").
    changed_by NULL = the system sync (e.g. a compromise-status raise)."""
    __tablename__ = 'customer_asset_change'

    id = Column(BigInteger, primary_key=True)
    customer_asset_id = Column(BigInteger,
                               ForeignKey('customer_asset.id', ondelete='CASCADE'),
                               nullable=False, index=True)
    field = Column(String(64), nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    changed_by = Column(BigInteger, ForeignKey('user.id'), nullable=True)
    changed_at = Column(DateTime, nullable=False, server_default=text('now()'))

    changed_by_user = relationship('User')


class AiArtifact(AiOverrideMixin, db.Model):
    """iris-ng v2 (Phase 2): generic AI cache for NON-case anchors — the same
    (kind, input_hash, content, override) contract as CaseAiArtifact, keyed by
    (anchor_type, anchor_id) instead of a case. Retires the anchor-case hacks
    (cluster narratives cached on min(case_ids)).

    anchor_id carries NO foreign key on purpose (polymorphic across anchor
    tables); orphaned rows are harmless cache and read paths always take the
    newest row for their anchor. CHECK on anchor_type lives here on
    __table_args__ (create_all-before-alembic fork rule); extending it for a
    new anchor type is a deliberate migration.

    NEVER persist a failed AI call as an artifact (project rule): raise, let
    the endpoint return a transient error — only parsed, expected-shape
    output is cached.
    """
    __tablename__ = 'ai_artifact'

    id = Column(BigInteger, primary_key=True)
    anchor_type = Column(String(32), nullable=False)
    anchor_id = Column(BigInteger, nullable=False)
    kind = Column(String(64), nullable=False)
    prompt_id = Column(String(128), nullable=False)
    model = Column(String(128), nullable=False)
    input_hash = Column(String(64), nullable=False)
    content = Column(Text, nullable=False)
    confidence = Column(Float, nullable=True)
    generated_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("anchor_type IN ('alert_cluster', 'war_room')",
                        name='ck_ai_artifact_anchor_type'),
        Index('idx_ai_artifact_anchor', 'anchor_type', 'anchor_id', 'kind'),
    )


class MispClusterLink(db.Model):
    """Record of a correlation cluster published to MISP as a campaign event.

    One row per cluster. `cluster_id` is the MD5[:8] of the cluster's sorted
    case ids, so it is stable for a given set of cases — a UNIQUE constraint on
    it is what stops a second "Push to MISP" click from creating a duplicate
    event. Re-publishing is possible but must be explicit.

    UNIQUE lives on __table_args__ (not only in the migration) because IRIS runs
    db.create_all() from the ORM models BEFORE alembic; a constraint declared
    only in the migration would be skipped on a fresh install.
    """
    __tablename__ = 'misp_cluster_link'
    __table_args__ = (
        UniqueConstraint('cluster_id', name='uq_misp_cluster_link_cluster_id'),
    )

    id = Column(BigInteger, primary_key=True)
    cluster_id = Column(String(64), nullable=False, index=True)
    misp_event_id = Column(Integer, nullable=False)
    misp_event_uuid = Column(String(80), nullable=True)
    case_ids = Column(Text, nullable=True)          # comma-separated, as pushed
    pushed_at = Column(DateTime, server_default=func.now(), nullable=False)
    pushed_by_id = Column(ForeignKey('user.id', ondelete='SET NULL'), nullable=True)

    pushed_by = relationship('User', foreign_keys=[pushed_by_id])


class AiJob(db.Model):
    """Async AI job — one row per enqueued AI request (docs/19 §5b.3).

    The synchronous AI endpoints (case summary, chat, …) block a gunicorn
    worker for the full model latency (120-180s on gpt-oss-20b for a large
    case), which doesn't scale past a single analyst and brushes the worker
    timeout. This table backs the async pattern: the POST enqueues a celery
    task on the dedicated `ai_queue` (worker_concurrency=1 → bounds GPU load),
    returns 202 + task_id, and the client polls GET /api/v2/ai/jobs/<task_id>.

    Two result shapes are supported:
      - artifact-returning features (summary) set `artifact_id`; the client
        fetches the cached CaseAiArtifact.
      - dict-returning features (chat — not persisted as an artifact) set
        `result_json`; the client reads the payload straight off the job.
    """
    __tablename__ = 'ai_job'

    id = Column(BigInteger, primary_key=True)
    task_id = Column(String(36), unique=True, nullable=False, index=True)  # celery uuid
    case_id = Column(ForeignKey('cases.case_id', ondelete='CASCADE'), nullable=True, index=True)
    user_id = Column(ForeignKey('user.id'), nullable=False)
    feature = Column(String(64), nullable=False)        # 'case_summary' | 'chat' | …
    params = Column(Text, nullable=True)                # JSON-encoded call args (force, question, history, variant)
    priority = Column(Integer, nullable=False, default=5)  # 1=high … 9=low (celery priority)
    state = Column(String(16), nullable=False, default='queued', index=True)  # queued|running|done|error|cancelled
    submitted_at = Column(DateTime, server_default=func.now(), nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    artifact_id = Column(ForeignKey('case_ai_artifact.id', ondelete='SET NULL'), nullable=True)
    result_json = Column(Text, nullable=True)           # for features that return a dict, not an artifact
    error_message = Column(Text, nullable=True)

    artifact = relationship('CaseAiArtifact')


class IocAssetLink(db.Model):
    __tablename__ = 'ioc_asset_link'

    ioc_asset_link_id = Column(Integer, primary_key=True)
    ioc_id = Column(ForeignKey('ioc.ioc_id'), nullable=False)
    asset_id = Column(ForeignKey('case_assets.asset_id'), nullable=False)

    ioc = relationship('Ioc', back_populates='assets')
    asset = relationship('CaseAssets', back_populates='iocs')


class EvidenceAssetLink(db.Model):
    """Many-to-many link between case evidence (CaseReceivedFile) and case assets.

    Mirrors the IocAssetLink pattern. Stored once per (asset, evidence) pair —
    UNIQUE prevents accidental dupes when set_evidence_links() races, and the
    cascade='all, delete-orphan' on `CaseAssets.evidences` keeps the table tidy
    when an asset is deleted. Evidence-side back_populates does the same on
    file deletion.
    """
    __tablename__ = 'evidence_asset_link'
    __table_args__ = (
        UniqueConstraint('asset_id', 'evidence_id', name='uq_evidence_asset_link_pair'),
    )

    id = Column(BigInteger, primary_key=True)
    asset_id = Column(ForeignKey('case_assets.asset_id', ondelete='CASCADE'), nullable=False, index=True)
    evidence_id = Column(ForeignKey('case_received_file.id', ondelete='CASCADE'), nullable=False, index=True)

    asset = relationship('CaseAssets', back_populates='evidences')
    evidence = relationship('CaseReceivedFile', back_populates='assets')


class CaseTaskLink(db.Model):
    """Jira-style directed task relationship within a single case.

    Two link types in v1:

        blocks       <->  is blocked by      (rendered as inverse of `blocks`)
        depends_on   <->  is depended on by  (rendered as inverse of `depends_on`)

    Each pair is stored once in the canonical "forward" direction
    (`from_task_id` -> `to_task_id`); inverse views (`is blocked by`,
    `is depended on by`) are computed at read time from the same row.
    Adding a third link type later (e.g. `relates_to`, `duplicates`)
    is a one-line change to the CHECK constraint plus a UI label add.

    Constraints (DB-enforced):
      - `UNIQUE(from_task_id, to_task_id, link_type)` — no duplicate links.
      - `CHECK(from_task_id <> to_task_id)` — no self-link.
      - `CHECK(link_type IN ('blocks', 'depends_on'))` — known types only.

    Cycle prevention is intentionally NOT enforced in DB or model — an
    analyst may legitimately want to flag a circular dependency to make
    it visible to reviewers. The UI surfaces a soft warning if a new
    link would close a cycle, but doesn't reject it.
    """
    __tablename__ = 'case_task_link'

    id = Column(BigInteger, primary_key=True)
    from_task_id = Column(ForeignKey('case_tasks.id', ondelete='CASCADE'), nullable=False, index=True)
    to_task_id = Column(ForeignKey('case_tasks.id', ondelete='CASCADE'), nullable=False, index=True)
    link_type = Column(String(32), nullable=False)
    case_id = Column(ForeignKey('cases.case_id', ondelete='CASCADE'), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    created_by = Column(ForeignKey('user.id', ondelete='SET NULL'), nullable=True)

    from_task = relationship('CaseTasks', foreign_keys=[from_task_id])
    to_task = relationship('CaseTasks', foreign_keys=[to_task_id])

    # CHECK constraints live here (not just in the Alembic migration)
    # because IRIS runs `db.create_all()` from the ORM models BEFORE
    # alembic migrations run; if the table is auto-created without these
    # checks, the matching `op.create_table` in the migration is skipped
    # by `_has_table` and the constraints never land. Defining them on
    # the model is the source-of-truth path; the migration's identical
    # CHECKs are a belt-and-braces no-op for fresh installs.
    __table_args__ = (
        UniqueConstraint('from_task_id', 'to_task_id', 'link_type', name='uq_case_task_link_triple'),
        CheckConstraint('from_task_id <> to_task_id', name='ck_case_task_link_no_self'),
        CheckConstraint("link_type IN ('blocks', 'depends_on')", name='ck_case_task_link_type'),
    )


class CaseTimeEntry(db.Model):
    """iris-next: analyst time tracking, logged in 15-minute increments.

    Captures only what cannot be derived from the case itself —
    (case, analyst, minutes, date, optional note/task). The two
    management-reporting dimensions that would otherwise be analyst
    overhead — **sector** and **incident type** — are NOT stored here;
    they are joined at report time through the case
    (`Client.dhs_sectors` / case tag, and `Cases.classification_id`).
    This keeps logging to ~2 clicks and means historical reports
    self-correct when a case is reclassified or its sector fixed.

    The four breakdowns management asked for:
      - by case     -> case_id
      - by person   -> user_id
      - by sector   -> case -> client.dhs_sectors (report-time join)
      - by incident -> case -> classification_id  (report-time join)

    `task_id` is optional — logging from a task gives free per-task
    rollups; case-level logging leaves it NULL.

    Edit/delete policy is enforced in the business layer, not here:
    an analyst may freely edit/delete their own entries while the case
    is OPEN (`cases.close_date IS NULL`); entries lock when the case
    closes and unlock again if it is reopened (reopen nulls close_date).

    Constraints (DB-enforced):
      - `CHECK(minutes > 0 AND minutes % 15 = 0)` — 15-min increments only.

    CHECK lives on `__table_args__` (not just the migration) because IRIS
    runs `db.create_all()` from the ORM models BEFORE alembic; a constraint
    defined only in the migration would be skipped by `_has_table` and never
    land. Same rule as CaseTaskLink above.
    """
    __tablename__ = 'case_time_entry'

    id = Column(BigInteger, primary_key=True)
    case_id = Column(ForeignKey('cases.case_id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = Column(ForeignKey('user.id', ondelete='SET NULL'), nullable=True, index=True)
    task_id = Column(ForeignKey('case_tasks.id', ondelete='SET NULL'), nullable=True, index=True)
    minutes = Column(Integer, nullable=False)
    activity_date = Column(Date, nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), nullable=False)

    case = relationship('Cases', foreign_keys=[case_id])
    user = relationship('User', foreign_keys=[user_id])
    task = relationship('CaseTasks', foreign_keys=[task_id])

    __table_args__ = (
        CheckConstraint('minutes > 0 AND minutes % 15 = 0', name='ck_case_time_entry_increment'),
    )


class IocNoteLink(db.Model):
    """Provenance link from an Ioc row to one or more source Notes.

    Many-to-many: a single IOC can be cited by several notes, and a note
    can yield multiple IOCs. Populated automatically when the AI IOC
    extractor's `+ add` flow promotes a suggestion to a real IOC; the
    link records *which note* the analyst was editing at the time of
    the extraction. Used for analyst back-reference ("where did this
    IOC come from?"), LLM grounding (chat-bar can cite the source note),
    and the pinned dual-timeline / mind-map features.
    """
    __tablename__ = 'ioc_note_link'

    id = Column(BigInteger, primary_key=True)
    ioc_id = Column(ForeignKey('ioc.ioc_id', ondelete='CASCADE'), nullable=False, index=True)
    note_id = Column(ForeignKey('notes.note_id', ondelete='CASCADE'), nullable=False, index=True)
    case_id = Column(ForeignKey('cases.case_id', ondelete='CASCADE'), nullable=False, index=True)
    source = Column(String(32), nullable=False, server_default='ai_extractor')
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    ioc = relationship('Ioc')
    note = relationship('Notes')

    __table_args__ = (
        UniqueConstraint('ioc_id', 'note_id', name='uq_ioc_note_link_pair'),
    )


class OsType(db.Model):
    __tablename__ = 'os_type'

    type_id = Column(Integer, primary_key=True)
    type_name = Column(String(155))


class CasesAssetsExt(db.Model):
    __tablename__ = 'cases_assets_ext'

    asset_id = Column(Integer, primary_key=True)
    type_id = Column(ForeignKey('assets_type.asset_id'))
    case_id = Column(ForeignKey('cases.case_id'))
    asset_content = Column(Text)

    type = relationship('AssetsType')
    case = relationship('Cases')


class Notes(db.Model):
    __tablename__ = 'notes'

    note_id = Column(BigInteger, primary_key=True)
    note_uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, server_default=text("gen_random_uuid()"), nullable=False)
    note_title = Column(String(155))
    note_content = Column(Text)
    note_user = Column(ForeignKey('user.id'))
    note_creationdate = Column(DateTime)
    note_lastupdate = Column(DateTime)
    note_case_id = Column(ForeignKey('cases.case_id'))
    custom_attributes = Column(JSON)
    directory_id = Column(ForeignKey('note_directory.id'), nullable=True)
    modification_history = Column(JSON)

    user = relationship('User')
    case = relationship('Cases')
    directory = relationship('NoteDirectory', backref='notes')
    versions = relationship('NoteRevisions', back_populates='note', cascade="all, delete-orphan")


class NoteRevisions(db.Model):
    __tablename__ = 'note_revisions'

    revision_id = Column(BigInteger, primary_key=True)
    note_id = Column(BigInteger, ForeignKey('notes.note_id'), nullable=False)
    revision_number = Column(Integer, nullable=False)
    note_title = Column(String(155))
    note_content = Column(Text)
    note_user = Column(ForeignKey('user.id'))
    revision_timestamp = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship('User')
    note = relationship('Notes', back_populates='versions')


class NoteDirectory(db.Model):
    __tablename__ = 'note_directory'

    id = Column(BigInteger, primary_key=True)
    name = Column(Text, nullable=False)
    parent_id = Column(ForeignKey('note_directory.id'), nullable=True)
    case_id = Column(ForeignKey('cases.case_id'), nullable=False)

    parent = relationship('NoteDirectory', remote_side=[id], backref='subdirectories')
    case = relationship('Cases', backref='note_directories')


class NotesGroup(db.Model):
    __tablename__ = 'notes_group'

    group_id = Column(BigInteger, primary_key=True)
    group_uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, server_default=text("gen_random_uuid()"),
                        nullable=False)
    group_title = Column(String(155))
    group_user = Column(ForeignKey('user.id'))
    group_creationdate = Column(DateTime)
    group_lastupdate = Column(DateTime)
    group_case_id = Column(ForeignKey('cases.case_id'))

    user = relationship('User')
    case = relationship('Cases')


class NotesGroupLink(db.Model):
    __tablename__ = 'notes_group_link'

    link_id = Column(BigInteger, primary_key=True)
    group_id = Column(ForeignKey('notes_group.group_id'))
    note_id = Column(ForeignKey('notes.note_id'))
    case_id = Column(ForeignKey('cases.case_id'))

    note = relationship('Notes')
    note_group = relationship('NotesGroup')
    case = relationship('Cases')


class CaseKanban(db.Model):
    __tablename__ = 'case_kanban'

    case_id = Column(ForeignKey('cases.case_id'), primary_key=True)
    kanban_data = Column(Text)

    case = relationship('Cases')


class CaseReceivedFile(db.Model):
    __tablename__ = 'case_received_file'

    id = Column(BigInteger, primary_key=True)
    file_uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, server_default=text("gen_random_uuid()"), nullable=False)
    filename = Column(Text)
    date_added = Column(DateTime)
    acquisition_date = Column(DateTime)
    file_hash = Column(Text)
    file_description = Column(Text)
    file_size = Column(BigInteger)
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    case_id = Column(ForeignKey('cases.case_id'))
    user_id = Column(ForeignKey('user.id'))
    type_id = Column(ForeignKey('evidence_type.id'))
    # iris-next: physical-custody metadata. `user_id` records the IRIS account
    # that registered the evidence; `created_by` is the free-text custodian /
    # collector (may be an IRIS username or an external party). barcode +
    # physical_location track the physical chain-of-custody item.
    created_by = Column(Text)
    barcode = Column(Text)
    physical_location = Column(Text)
    # iris-next: the physical drive this evidence item lives on (Inventory tab).
    # Nullable — items not on a managed drive (or after the drive is wiped) have
    # drive_id = NULL. ondelete=SET NULL so deleting a drive doesn't cascade-kill
    # evidence rows (case history must survive).
    drive_id = Column(ForeignKey('evidence_drive.id', ondelete='SET NULL'), nullable=True)
    custom_attributes = Column(JSON)
    chain_of_custody = Column(JSON)
    modification_history = Column(JSON)

    case = relationship('Cases')
    user = relationship('User')
    type = relationship('EvidenceTypes')
    drive = relationship('EvidenceDrive', back_populates='evidences')
    assets = relationship('EvidenceAssetLink', back_populates='evidence', cascade='all, delete-orphan')


class EvidenceDrive(db.Model):
    """iris-next: a physical drive (the barcoded item) that holds digital
    evidence. One drive maps to one *current* case but is reusable across its
    lifecycle (assigned → in use → wiped → available → reassigned). Distinct
    from CaseReceivedFile, which is a logical evidence item *on* the drive.

    The Inventory tab on the dashboard scans/keys `barcode` to resolve the drive,
    its physical_location, current case, and the evidence items on it.
    """
    __tablename__ = 'evidence_drive'
    __table_args__ = (
        # Barcode is the scan key — must be unique. Defined here (not only in the
        # migration) because iris-ng runs db.create_all() before alembic; a
        # constraint living only in the migration would be skipped on fresh boot.
        UniqueConstraint('barcode', name='uq_evidence_drive_barcode'),
    )

    id = Column(BigInteger, primary_key=True)
    drive_uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, server_default=text("gen_random_uuid()"), nullable=False)
    barcode = Column(Text, nullable=False)
    label = Column(Text)
    serial_number = Column(Text)
    physical_location = Column(Text)
    # available | in_use | wiped | retired
    status = Column(Text, nullable=False, server_default=text("'available'"))
    capacity = Column(Text)
    notes = Column(Text)
    created_by = Column(Text)
    case_id = Column(ForeignKey('cases.case_id', ondelete='SET NULL'), nullable=True)
    date_added = Column(DateTime, server_default=text("now()"))
    date_assigned = Column(DateTime)
    date_wiped = Column(DateTime)

    case = relationship('Cases')
    evidences = relationship('CaseReceivedFile', back_populates='drive')


class TaskStatus(db.Model):
    __tablename__ = 'task_status'

    id = Column(Integer, primary_key=True)
    status_name = Column(Text)
    status_description = Column(Text)
    status_bscolor = Column(Text)


class CaseTasks(db.Model):
    __tablename__ = 'case_tasks'

    id = Column(BigInteger, primary_key=True)
    task_uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, server_default=text("gen_random_uuid()"), nullable=False)
    task_title = Column(Text)
    task_description = Column(Text)
    task_tags = Column(Text)
    task_open_date = Column(DateTime)
    task_close_date = Column(DateTime)
    task_last_update = Column(DateTime)
    task_userid_open = Column(ForeignKey('user.id'))
    task_userid_close = Column(ForeignKey('user.id'))
    task_userid_update = Column(ForeignKey('user.id'))
    task_status_id = Column(ForeignKey('task_status.id'))
    task_case_id = Column(ForeignKey('cases.case_id'))
    custom_attributes = Column(JSON)
    modification_history = Column(JSON)

    case = relationship('Cases')
    user_open = relationship('User', foreign_keys=[task_userid_open])
    user_close = relationship('User', foreign_keys=[task_userid_close])
    user_update = relationship('User', foreign_keys=[task_userid_update])
    status = relationship('TaskStatus', foreign_keys=[task_status_id])


class Tags(db.Model):
    __tablename__ = 'tags'

    id = Column(BigInteger, primary_key=True, nullable=False)
    tag_title = Column(Text, unique=True)
    tag_creation_date = Column(DateTime)
    tag_namespace = Column(Text)

    cases = relationship('Cases', secondary="case_tags", back_populates='tags', viewonly=True)

    def __init__(self, tag_title, namespace=None):
        self.id = None
        self.tag_title = tag_title
        self.tag_creation_date = datetime.datetime.now()
        self.tag_namespace = namespace

    def save(self):
        existing_tag = self.get_by_title(self.tag_title)
        if existing_tag is not None:
            return existing_tag
        else:
            db.session.add(self)
            db.session.commit()
            return self

    @classmethod
    def get_by_title(cls, tag_title):
        return cls.query.filter_by(tag_title=tag_title).first()


class TaskAssignee(db.Model):
    __tablename__ = "task_assignee"

    id = Column(BigInteger, primary_key=True, nullable=False)
    user_id = Column(BigInteger, ForeignKey('user.id'), nullable=False)
    task_id = Column(BigInteger, ForeignKey('case_tasks.id'), nullable=False)

    user = relationship('User')
    task = relationship('CaseTasks')

    UniqueConstraint('user_id', 'task_id')


class GlobalTasks(db.Model):
    __tablename__ = 'global_tasks'

    id = Column(BigInteger, primary_key=True)
    task_uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, server_default=text("gen_random_uuid()"), nullable=False)
    task_title = Column(Text)
    task_description = Column(Text)
    task_tags = Column(Text)
    task_open_date = Column(DateTime)
    task_close_date = Column(DateTime)
    task_last_update = Column(DateTime)
    task_userid_open = Column(ForeignKey('user.id'))
    task_userid_close = Column(ForeignKey('user.id'))
    task_userid_update = Column(ForeignKey('user.id'))
    task_assignee_id = Column(ForeignKey('user.id'), nullable=True)
    task_status_id = Column(ForeignKey('task_status.id'))

    user_open = relationship('User', foreign_keys=[task_userid_open])
    user_close = relationship('User', foreign_keys=[task_userid_close])
    user_update = relationship('User', foreign_keys=[task_userid_update])
    user_assigned = relationship('User', foreign_keys=[task_assignee_id])
    status = relationship('TaskStatus', foreign_keys=[task_status_id])


class UserActivity(db.Model):
    __tablename__ = "user_activity"

    id = Column(BigInteger, primary_key=True)
    user_id = Column(ForeignKey('user.id'), nullable=True)
    case_id = Column(ForeignKey('cases.case_id'), nullable=True)
    activity_date = Column(DateTime)
    activity_desc = Column(Text)
    user_input = Column(Boolean, default=False)
    is_from_api = Column(Boolean, default=False)
    display_in_ui = Column(Boolean, default=True)

    user = relationship('User')
    case = relationship('Cases')


class CaseNotificationAck(db.Model):
    """Per-(user, case) read watermark for the case-updates bell.

    One row per analyst per case, holding the timestamp of the most recent
    UserActivity row that analyst has acknowledged for that case. Absent row =
    never acknowledged, so the whole retained activity history counts as unread.

    The watermark is deliberately per-case and durable across logins: switching
    context to another case shows that case's own unread set, and logging out
    does not clear anything.
    """
    __tablename__ = "case_notification_ack"

    id = Column(BigInteger, primary_key=True)
    user_id = Column(ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    case_id = Column(ForeignKey('cases.case_id', ondelete='CASCADE'), nullable=False, index=True)
    last_ack_at = Column(DateTime, nullable=False)

    user = relationship('User')
    case = relationship('Cases')

    # UNIQUE lives on the model, not only in the migration: db.create_all() runs
    # from the ORM before alembic, so a constraint declared only in the migration
    # is skipped by alembic's _has_table guard and never lands.
    __table_args__ = (
        UniqueConstraint('user_id', 'case_id', name='uq_case_notification_ack_user_case'),
    )


class Notification(db.Model):
    """Addressed-to-me notification (iris-ng v2, Phase 5).

    Distinct scope from the per-case bell (CaseNotificationAck + user_activity):
    that one answers "what changed in the case I am looking at"; this one
    answers "what is addressed to ME across the whole instance" - mentions,
    assignments, escalations. Event types come from the catalog in
    business/notifications.py; rows are only created for recipients whose
    resolved preference has the in-app channel on.
    """
    __tablename__ = 'notification'

    id = Column(BigInteger, primary_key=True)
    user_id = Column(ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    event_type = Column(String(64), nullable=False)
    title = Column(Text, nullable=False)
    body = Column(Text, nullable=True)
    # Loose anchor, no FK: the referenced object may be deleted later and the
    # notification must survive as history (same trade-off as AiArtifact).
    object_type = Column(String(32), nullable=True)
    object_id = Column(BigInteger, nullable=True)
    case_id = Column(BigInteger, nullable=True)
    url = Column(Text, nullable=True)
    is_read = Column(Boolean, default=False, nullable=False, server_default=text('false'))
    created_at = Column(DateTime, server_default=text('now()'), nullable=False)

    user = relationship('User')

    __table_args__ = (
        Index('idx_notification_user_read_created', 'user_id', 'is_read', 'created_at'),
    )


class UserNotificationPreference(db.Model):
    """Per-user, per-event channel override (iris-ng v2, Phase 5).

    Absent row or NULL channel = inherit the org default
    (ServerSettings.notification_defaults, falling back to code defaults).
    A dedicated table rather than a JSONB blob on user: auto-creates on
    upgrade, queryable per event, and does not touch the user table.
    """
    __tablename__ = 'user_notification_preference'

    id = Column(BigInteger, primary_key=True)
    user_id = Column(ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    event_type = Column(String(64), nullable=False)
    in_app = Column(Boolean, nullable=True)
    email = Column(Boolean, nullable=True)

    __table_args__ = (
        UniqueConstraint('user_id', 'event_type',
                         name='uq_user_notification_pref_user_event'),
    )


class UserFollow(db.Model):
    """A user following a case or alert (iris-ng v2, Phase 5).

    Feeds the home-page following feed. No FK on object_id (case and alert
    ids live in different tables); rows for deleted objects are skipped at
    read time.
    """
    __tablename__ = 'user_follow'

    id = Column(BigInteger, primary_key=True)
    user_id = Column(ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    object_type = Column(String(16), nullable=False)
    object_id = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, server_default=text('now()'), nullable=False)

    __table_args__ = (
        UniqueConstraint('user_id', 'object_type', 'object_id',
                         name='uq_user_follow_user_object'),
        CheckConstraint("object_type IN ('case', 'alert')",
                        name='ck_user_follow_object_type'),
    )


class WarRoom(db.Model):
    """iris-ng v2 (Phase 6): a war room — the first real persisted multi-case
    container. Attaches cases, holds members with roles, chat messages and
    versioned SitReps.

    Promotion provenance: a room promoted from a computed correlation cluster
    records the cluster hash (source_cluster_id) and the campaign tag it
    carried. Rooms are NEVER auto-created from computed clusters (user rule);
    the correlation ENGINE stays untouched — only the workspace migrates here.
    """
    __tablename__ = 'war_room'

    id = Column(BigInteger, primary_key=True)
    room_uuid = Column(UUID(as_uuid=True), default=uuid.uuid4,
                       server_default=text("gen_random_uuid()"), nullable=False)
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    # Analyst-owned room summary; seeded from the analyst-edited cluster
    # narrative (display_content) on promote, editable afterwards.
    summary = Column(Text, nullable=True)
    # v3 four-state model: open (fresh) / active (ongoing response) /
    # standby (dormant, still writable) / closed (read-only; frees a
    # promoted cluster). archived_at records when the room was closed.
    status = Column(String(16), nullable=False, default='open',
                    server_default=text("'open'"))
    # v3 header severity chip; NULL = unset, renders nothing.
    severity = Column(String(16), nullable=True)
    source_cluster_id = Column(String(64), nullable=True)
    campaign_tag = Column(Text, nullable=True)
    created_by = Column(ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime, server_default=text('now()'), nullable=False)
    archived_at = Column(DateTime, nullable=True)

    creator = relationship('User', foreign_keys=[created_by])

    __table_args__ = (
        CheckConstraint("status IN ('open', 'active', 'standby', 'closed')",
                        name='ck_war_room_status'),
        CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')",
                        name='ck_war_room_severity'),
    )


class WarRoomMember(db.Model):
    """Room membership with role. Role hierarchy lead > responder > observer
    (CaseAnalystLink precedent, plus the observer tier). Membership does NOT
    grant case access — the room stream is filtered per-viewer by case ACL
    (v1 decision, flagged for revisit)."""
    __tablename__ = 'war_room_member'

    id = Column(BigInteger, primary_key=True)
    room_id = Column(ForeignKey('war_room.id', ondelete='CASCADE'),
                     nullable=False, index=True)
    user_id = Column(ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    role = Column(String(16), nullable=False)
    added_at = Column(DateTime, server_default=text('now()'), nullable=False)
    added_by = Column(ForeignKey('user.id', ondelete='SET NULL'), nullable=True)

    user = relationship('User', foreign_keys=[user_id])

    __table_args__ = (
        UniqueConstraint('room_id', 'user_id',
                         name='uq_war_room_member_room_user'),
        CheckConstraint("role IN ('lead', 'responder', 'observer')",
                        name='ck_war_room_member_role'),
    )


class WarRoomCaseLink(db.Model):
    """Cases attached to a room. Composite PK; CASCADE both sides — a deleted
    case silently leaves the room, a deleted room drops its links."""
    __tablename__ = 'war_room_case_link'

    room_id = Column(ForeignKey('war_room.id', ondelete='CASCADE'),
                     primary_key=True)
    case_id = Column(ForeignKey('cases.case_id', ondelete='CASCADE'),
                     primary_key=True)
    added_at = Column(DateTime, server_default=text('now()'), nullable=False)
    added_by = Column(ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    note = Column(Text, nullable=True)

    case = relationship('Cases')


class WarRoomTeam(db.Model):
    """Per-room @-mention group (v3 Teams tab). The name is what people
    type after @ — mentioning a team notifies every member. Grouping only:
    team membership never grants anything (the room ACL admits)."""
    __tablename__ = 'war_room_team'

    id = Column(BigInteger, primary_key=True)
    room_id = Column(ForeignKey('war_room.id', ondelete='CASCADE'),
                     nullable=False, index=True)
    name = Column(String(64), nullable=False)
    description = Column(Text, nullable=True)
    color = Column(String(16), nullable=True)
    created_by = Column(ForeignKey('user.id', ondelete='SET NULL'),
                        nullable=True)
    created_at = Column(DateTime, server_default=text('now()'), nullable=False)

    creator = relationship('User')
    members = relationship('WarRoomTeamMember', back_populates='team',
                           cascade='all, delete-orphan')

    __table_args__ = (
        UniqueConstraint('room_id', 'name', name='uq_war_room_team_name'),
    )


class WarRoomTeamMember(db.Model):
    __tablename__ = 'war_room_team_member'

    team_id = Column(ForeignKey('war_room_team.id', ondelete='CASCADE'),
                     primary_key=True)
    user_id = Column(ForeignKey('user.id', ondelete='CASCADE'),
                     primary_key=True)
    added_at = Column(DateTime, server_default=text('now()'), nullable=False)

    team = relationship('WarRoomTeam', back_populates='members')
    user = relationship('User')


class WarRoomMessage(db.Model):
    """Room chat. user_id SET NULL so history survives user deletion.
    Keyset pagination on (room_id, id).

    Chat machinery (v3 stream completion): `topic` groups messages
    (# Main = 'main'); `kind` distinguishes plain messages from /note and
    /decision entries (the Notes/Pins + Decisions rail counters); `pinned`
    highlights any message; `parent_id` is full reply-to threading — a
    reply anchors to its ROOT message (replies to a reply re-anchor to the
    same root, one level), and a root with `thread_title` is a named
    /thread."""
    __tablename__ = 'war_room_message'

    id = Column(BigInteger, primary_key=True)
    room_id = Column(ForeignKey('war_room.id', ondelete='CASCADE'),
                     nullable=False)
    user_id = Column(ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    content = Column(Text, nullable=False)
    topic = Column(String(64), nullable=False, default='main',
                   server_default=text("'main'"))
    kind = Column(String(16), nullable=False, default='message',
                  server_default=text("'message'"))
    parent_id = Column(ForeignKey('war_room_message.id', ondelete='CASCADE'),
                       nullable=True)
    thread_title = Column(Text, nullable=True)
    pinned = Column(Boolean, nullable=False, default=False,
                    server_default=text('false'))
    created_at = Column(DateTime, server_default=text('now()'), nullable=False)

    user = relationship('User')

    __table_args__ = (
        Index('idx_war_room_message_room_id_id', 'room_id', 'id'),
        CheckConstraint("kind IN ('message', 'note', 'decision')",
                        name='ck_war_room_message_kind'),
    )


class WarRoomTask(db.Model):
    """ROOM-LEVEL task (maintainer decision: /task creates a war-room task,
    not a case task — coordination items belong to the room; case tasks
    stay on the case pages and are only aggregated read-only).

    v3 shape: description, five statuses, due date, tags, one-level
    subtasks via parent_task_id."""
    __tablename__ = 'war_room_task'

    id = Column(BigInteger, primary_key=True)
    room_id = Column(ForeignKey('war_room.id', ondelete='CASCADE'),
                     nullable=False, index=True)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    assignee_id = Column(ForeignKey('user.id', ondelete='SET NULL'),
                         nullable=True)
    status = Column(String(16), nullable=False, default='no_status',
                    server_default=text("'no_status'"))
    due_date = Column(DateTime, nullable=True)
    tags = Column(Text, nullable=True)
    parent_task_id = Column(ForeignKey('war_room_task.id',
                                       ondelete='CASCADE'), nullable=True)
    created_by = Column(ForeignKey('user.id', ondelete='SET NULL'),
                        nullable=True)
    created_at = Column(DateTime, server_default=text('now()'), nullable=False)
    done_at = Column(DateTime, nullable=True)
    done_by = Column(ForeignKey('user.id', ondelete='SET NULL'), nullable=True)

    assignee = relationship('User', foreign_keys=[assignee_id])
    creator = relationship('User', foreign_keys=[created_by])

    __table_args__ = (
        CheckConstraint("status IN ('no_status', 'todo', 'in_progress', "
                        "'on_hold', 'done', 'cancelled')",
                        name='ck_war_room_task_status'),
    )


class SitRep(db.Model):
    """Versioned situation report on a war room. Own table, NOT Notes reuse —
    Notes.case_id is non-nullable and a SitRep belongs to a room, not a case.
    draft -> published; edits after publish write a revision row first
    (NoteRevisions pattern)."""
    __tablename__ = 'sitrep'

    id = Column(BigInteger, primary_key=True)
    room_id = Column(ForeignKey('war_room.id', ondelete='CASCADE'),
                     nullable=False, index=True)
    title = Column(Text, nullable=False)
    content = Column(Text, nullable=True)
    status = Column(String(16), nullable=False, default='draft',
                    server_default=text("'draft'"))
    created_by = Column(ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime, server_default=text('now()'), nullable=False)
    updated_at = Column(DateTime, nullable=True)
    published_at = Column(DateTime, nullable=True)
    published_by = Column(ForeignKey('user.id', ondelete='SET NULL'), nullable=True)

    creator = relationship('User', foreign_keys=[created_by])
    publisher = relationship('User', foreign_keys=[published_by])
    revisions = relationship('SitRepRevision', back_populates='sitrep',
                             cascade='all, delete-orphan')

    __table_args__ = (
        CheckConstraint("status IN ('draft', 'published')",
                        name='ck_sitrep_status'),
    )


class SitRepRevision(db.Model):
    """Snapshot of a SitRep before an edit (NoteRevisions pattern verbatim)."""
    __tablename__ = 'sitrep_revision'

    id = Column(BigInteger, primary_key=True)
    sitrep_id = Column(ForeignKey('sitrep.id', ondelete='CASCADE'),
                       nullable=False, index=True)
    revision_number = Column(Integer, nullable=False)
    title = Column(Text)
    content = Column(Text)
    user_id = Column(ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    revision_timestamp = Column(DateTime, server_default=text('now()'),
                                nullable=False)

    user = relationship('User')
    sitrep = relationship('SitRep', back_populates='revisions')


class WarRoomPoll(db.Model):
    """Stream poll (v3 composer poll builder). Effective closed-ness is
    `closed OR closes_at < now` — computed at read time, no clock job."""
    __tablename__ = 'war_room_poll'

    id = Column(BigInteger, primary_key=True)
    room_id = Column(ForeignKey('war_room.id', ondelete='CASCADE'),
                     nullable=False, index=True)
    question = Column(Text, nullable=False)
    multiple = Column(Boolean, nullable=False, default=False,
                      server_default=text('false'))
    anonymous = Column(Boolean, nullable=False, default=False,
                       server_default=text('false'))
    closes_at = Column(DateTime, nullable=True)
    closed = Column(Boolean, nullable=False, default=False,
                    server_default=text('false'))
    created_by = Column(ForeignKey('user.id', ondelete='SET NULL'),
                        nullable=True)
    created_at = Column(DateTime, server_default=text('now()'), nullable=False)

    creator = relationship('User', foreign_keys=[created_by])
    options = relationship('WarRoomPollOption', back_populates='poll',
                           cascade='all, delete-orphan',
                           order_by='WarRoomPollOption.position')


class WarRoomPollOption(db.Model):
    __tablename__ = 'war_room_poll_option'

    id = Column(BigInteger, primary_key=True)
    poll_id = Column(ForeignKey('war_room_poll.id', ondelete='CASCADE'),
                     nullable=False, index=True)
    text = Column(Text, nullable=False)
    position = Column(Integer, nullable=False)

    poll = relationship('WarRoomPoll', back_populates='options')


class WarRoomPollVote(db.Model):
    """One row per (option, voter). Single-choice polls enforce one vote per
    poll in the business layer; the UNIQUE stops double-votes per option."""
    __tablename__ = 'war_room_poll_vote'

    id = Column(BigInteger, primary_key=True)
    poll_id = Column(ForeignKey('war_room_poll.id', ondelete='CASCADE'),
                     nullable=False, index=True)
    option_id = Column(ForeignKey('war_room_poll_option.id',
                                  ondelete='CASCADE'), nullable=False)
    user_id = Column(ForeignKey('user.id', ondelete='CASCADE'),
                     nullable=False)
    created_at = Column(DateTime, server_default=text('now()'), nullable=False)

    user = relationship('User')

    __table_args__ = (
        UniqueConstraint('option_id', 'user_id',
                         name='uq_war_room_poll_vote_option_user'),
    )


class WarRoomTimeline(db.Model):
    """Room-owned timeline (Timelines tab). Room events are coordination
    annotations; the case timelines stay the forensic source of truth and
    are only READ by the room (invariant)."""
    __tablename__ = 'war_room_timeline'

    id = Column(BigInteger, primary_key=True)
    room_id = Column(ForeignKey('war_room.id', ondelete='CASCADE'),
                     nullable=False, index=True)
    name = Column(Text, nullable=False)
    color = Column(String(16), nullable=True)
    created_by = Column(ForeignKey('user.id', ondelete='SET NULL'),
                        nullable=True)
    created_at = Column(DateTime, server_default=text('now()'), nullable=False)

    creator = relationship('User')
    events = relationship('WarRoomTimelineEvent', back_populates='timeline',
                          cascade='all, delete-orphan')


class WarRoomTimelineEvent(db.Model):
    __tablename__ = 'war_room_timeline_event'

    id = Column(BigInteger, primary_key=True)
    timeline_id = Column(ForeignKey('war_room_timeline.id',
                                    ondelete='CASCADE'),
                         nullable=False, index=True)
    event_date = Column(DateTime, nullable=False)
    title = Column(Text, nullable=False)
    content = Column(Text, nullable=True)
    category = Column(String(64), nullable=True)
    color = Column(String(16), nullable=True)
    tags = Column(Text, nullable=True)
    created_by = Column(ForeignKey('user.id', ondelete='SET NULL'),
                        nullable=True)
    created_at = Column(DateTime, server_default=text('now()'), nullable=False)
    updated_at = Column(DateTime, nullable=True)

    creator = relationship('User')
    timeline = relationship('WarRoomTimeline', back_populates='events')


class WarRoomNoteFolder(db.Model):
    """One-level folder for room notes (v3 Notes rail). Deleting a folder
    moves its notes to the root (SET NULL) — folders never own content."""
    __tablename__ = 'war_room_note_folder'

    id = Column(BigInteger, primary_key=True)
    room_id = Column(ForeignKey('war_room.id', ondelete='CASCADE'),
                     nullable=False, index=True)
    name = Column(Text, nullable=False)
    created_by = Column(ForeignKey('user.id', ondelete='SET NULL'),
                        nullable=True)
    created_at = Column(DateTime, server_default=text('now()'), nullable=False)

    creator = relationship('User')


class WarRoomNote(db.Model):
    """Room-owned read-write note (Notes tab). Case notes stay the forensic
    source of truth and are only READ by the room (invariant)."""
    __tablename__ = 'war_room_note'

    id = Column(BigInteger, primary_key=True)
    room_id = Column(ForeignKey('war_room.id', ondelete='CASCADE'),
                     nullable=False, index=True)
    folder_id = Column(ForeignKey('war_room_note_folder.id',
                                  ondelete='SET NULL'), nullable=True)
    title = Column(Text, nullable=False)
    content = Column(Text, nullable=True)
    created_by = Column(ForeignKey('user.id', ondelete='SET NULL'),
                        nullable=True)
    created_at = Column(DateTime, server_default=text('now()'), nullable=False)
    updated_at = Column(DateTime, nullable=True)
    updated_by = Column(ForeignKey('user.id', ondelete='SET NULL'),
                        nullable=True)

    creator = relationship('User', foreign_keys=[created_by])
    editor = relationship('User', foreign_keys=[updated_by])
    folder = relationship('WarRoomNoteFolder')


class WarRoomMispLink(db.Model):
    """Record of a war room published to MISP as a campaign event — the room's
    durable id supersedes MispClusterLink's comma-separated case_ids hack.
    UNIQUE(room_id): a second push returns 409; force republishes into a NEW
    MISP event and updates this row (same contract as MispClusterLink)."""
    __tablename__ = 'war_room_misp_link'

    id = Column(BigInteger, primary_key=True)
    room_id = Column(ForeignKey('war_room.id', ondelete='CASCADE'),
                     nullable=False)
    misp_event_id = Column(Integer, nullable=False)
    misp_event_uuid = Column(String(80), nullable=True)
    pushed_at = Column(DateTime, server_default=func.now(), nullable=False)
    pushed_by_id = Column(ForeignKey('user.id', ondelete='SET NULL'), nullable=True)

    pushed_by = relationship('User', foreign_keys=[pushed_by_id])

    __table_args__ = (
        UniqueConstraint('room_id', name='uq_war_room_misp_link_room'),
    )


class ServerSettings(db.Model):
    __table_name__ = "server_settings"

    id = Column(Integer, primary_key=True)
    https_proxy = Column(Text)
    http_proxy = Column(Text)
    prevent_post_mod_repush = Column(Boolean)
    prevent_post_objects_repush = Column(Boolean, default=False)
    has_updates_available = Column(Boolean)
    enable_updates_check = Column(Boolean)
    password_policy_min_length = Column(Integer)
    password_policy_upper_case = Column(Boolean)
    password_policy_lower_case = Column(Boolean)
    password_policy_digit = Column(Boolean)
    password_policy_special_chars = Column(Text)
    enforce_mfa = Column(Boolean)

    # AI backend (used by the Tier-1 AI features in source/app/iris_engine/ai/).
    # When ai_backend_enabled is False, the AI surfaces gracefully refuse with
    # "AI backend is not configured" instead of erroring. URL/key/model populate
    # from env (.env) on first install via post_init; admins can override here.
    ai_backend_enabled = Column(Boolean, default=False, nullable=False, server_default=text('false'))
    # Slot-1 (the default / "primary" backend).
    ai_backend_url = Column(Text, nullable=True)
    ai_backend_api_key = Column(Text, nullable=True)
    ai_backend_model = Column(Text, nullable=True)
    ai_backend_label = Column(Text, nullable=True)
    # Slot-2 ("alternate" backend) — admins can keep two configs side-by-side
    # (e.g. LM Studio + a hosted OpenAI-compatible endpoint) and switch the active one via
    # ai_backend_active_slot without retyping the URL/key/model fields.
    ai_backend_alt_url = Column(Text, nullable=True)
    ai_backend_alt_api_key = Column(Text, nullable=True)
    ai_backend_alt_model = Column(Text, nullable=True)
    ai_backend_alt_label = Column(Text, nullable=True)
    # 'primary' or 'alt'. Read by build_default_client() to pick which slot
    # gets used. Defaults to 'primary' so existing rows keep behaviour.
    ai_backend_active_slot = Column(String(16), nullable=False, server_default=text("'primary'"))
    ai_backend_confidence_threshold = Column(Float, nullable=True)
    # Per-feature slot overrides. JSONB dict: {"feature_key": "primary"|"alt"}.
    # Missing key / null value = use the global ai_backend_active_slot default.
    # Written/read by openai_client.build_default_client(feature=...).
    ai_feature_overrides = Column(JSONB, nullable=True)

    # Pinecone vector DB (used by sigma_grounding + ATT&CK / Atomic RAG layers).
    # When pinecone_enabled is False, callers fall back to model-only suggestions
    # with no degradation in core behaviour. Hosts/key seed from PINECONE_*
    # environment variables on first install; UI values take precedence afterwards.
    pinecone_enabled = Column(Boolean, default=False, nullable=False, server_default=text('false'))
    pinecone_api_key = Column(Text, nullable=True)
    pinecone_embed_model = Column(Text, nullable=True)
    pinecone_sigma_host = Column(Text, nullable=True)
    pinecone_attack_host = Column(Text, nullable=True)
    pinecone_atomic_host = Column(Text, nullable=True)

    # iris-next: time-tracking "you logged 0 time on cases you touched" nudge.
    # OFF by default — management asked for it but it must not add overhead
    # unless an admin opts in. Queried per page-load; no restart to flip.
    time_tracking_nudge_enabled = Column(Boolean, default=False, nullable=False, server_default=text('false'))

    # iris-next: physical evidence-drive retention policy. NULL = no policy.
    # Drives with status='in_use' and date_assigned older than (retention_months × 30)
    # days receive an 'overdue' flag on the Inventory tab to prompt wipe-and-rotate.
    retention_months = Column(Integer, nullable=True)

    # iris-next: capacity planning settings for the Inventory tab order-more indicator.
    # NULL = use UI defaults (window=3 months, target=2 months).
    capacity_planning_window_months = Column(Integer, nullable=True)
    capacity_planning_target_months = Column(Integer, nullable=True)

    # iris-ng v2 (Phase 1): mail ingest (IMAP mailbox -> mail rules -> alerts)
    # and outbound SMTP (the notification email channel consumes it in Phase 5).
    # The two password columns are WRITE-ONLY through the API:
    # ServerSettingsSchema marks them load_only and dumps mail_*_password_set
    # booleans instead, and the settings update route treats empty/masked values
    # as "keep stored" — the settings GET must never return a stored secret
    # (deliberate deviation from how ai_backend_api_key round-trips).
    # The mail poller reads them from this ORM row directly, never from the
    # dumped settings dict. Enum-ish columns are validated in the schema
    # (house style — ai_backend_active_slot has no CHECK either).
    mail_ingest_enabled = Column(Boolean, default=False, nullable=False, server_default=text('false'))
    mail_imap_host = Column(Text, nullable=True)
    mail_imap_port = Column(Integer, nullable=True)
    mail_imap_ssl = Column(Boolean, nullable=False, server_default=text('true'))
    mail_imap_username = Column(Text, nullable=True)
    mail_imap_password = Column(Text, nullable=True)
    mail_imap_folder = Column(Text, nullable=False, server_default=text("'INBOX'"))
    # NULL = polling disabled even when mail_ingest_enabled is on.
    mail_poll_interval_minutes = Column(Integer, nullable=True)
    mail_smtp_host = Column(Text, nullable=True)
    mail_smtp_port = Column(Integer, nullable=True)
    # 'tls' (implicit TLS), 'starttls', or 'none'.
    mail_smtp_security = Column(String(16), nullable=False, server_default=text("'tls'"))
    mail_smtp_username = Column(Text, nullable=True)
    mail_smtp_password = Column(Text, nullable=True)
    mail_smtp_from_addr = Column(Text, nullable=True)
    # Run ingested mail through the AI triage (IOC extraction + severity /
    # classification suggestion) before the alert is created. Fail-soft: any
    # AI error falls back to the matching rule's defaults, never blocks ingest.
    mail_ai_triage_enabled = Column(Boolean, default=False, nullable=False, server_default=text('false'))
    # Master switch for the outbound notification email channel (Phase 5).
    email_notifications_enabled = Column(Boolean, default=False, nullable=False, server_default=text('false'))
    # Org-wide notification defaults (Phase 5). JSONB dict keyed by event type:
    # {"mention": {"in_app": true, "email": false}, ...}. NULL / missing keys
    # fall back to the code defaults (in-app on, email off). Per-user overrides
    # live in user_notification_preference.
    notification_defaults = Column(JSONB, nullable=True)


class Comments(db.Model):
    __tablename__ = "comments"

    comment_id = Column(BigInteger, primary_key=True)
    comment_uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, server_default=text("gen_random_uuid()"),
                          nullable=False)
    comment_text = Column(Text)
    comment_date = Column(DateTime)
    comment_update_date = Column(DateTime)
    comment_user_id = Column(ForeignKey('user.id'))
    comment_case_id = Column(ForeignKey('cases.case_id'))
    comment_alert_id = Column(ForeignKey('alerts.alert_id'))

    user = relationship('User')
    case = relationship('Cases')
    alert = relationship('Alert')


class EventComments(db.Model):
    __tablename__ = "event_comments"

    id = Column(BigInteger, primary_key=True)
    comment_id = Column(ForeignKey('comments.comment_id'))
    comment_event_id = Column(ForeignKey('cases_events.event_id'))

    event = relationship('CasesEvent')
    comment = relationship('Comments')


class TaskComments(db.Model):
    __tablename__ = "task_comments"

    id = Column(BigInteger, primary_key=True)
    comment_id = Column(ForeignKey('comments.comment_id'))
    comment_task_id = Column(ForeignKey('case_tasks.id'))

    task = relationship('CaseTasks')
    comment = relationship('Comments')


class IocComments(db.Model):
    __tablename__ = "ioc_comments"

    id = Column(BigInteger, primary_key=True)
    comment_id = Column(ForeignKey('comments.comment_id'))
    comment_ioc_id = Column(ForeignKey('ioc.ioc_id'))

    ioc = relationship('Ioc')
    comment = relationship('Comments')


class AssetComments(db.Model):
    __tablename__ = "asset_comments"

    id = Column(BigInteger, primary_key=True)
    comment_id = Column(ForeignKey('comments.comment_id'))
    comment_asset_id = Column(ForeignKey('case_assets.asset_id'))

    asset = relationship('CaseAssets')
    comment = relationship('Comments')


class EvidencesComments(db.Model):
    __tablename__ = "evidence_comments"

    id = Column(BigInteger, primary_key=True)
    comment_id = Column(ForeignKey('comments.comment_id'))
    comment_evidence_id = Column(ForeignKey('case_received_file.id'))

    evidence = relationship('CaseReceivedFile')
    comment = relationship('Comments')


class NotesComments(db.Model):
    __tablename__ = "note_comments"

    id = Column(BigInteger, primary_key=True)
    comment_id = Column(ForeignKey('comments.comment_id'))
    comment_note_id = Column(ForeignKey('notes.note_id'))

    note = relationship('Notes')
    comment = relationship('Comments')


class IrisModule(db.Model):
    __tablename__ = "iris_module"

    id = Column(Integer, primary_key=True)
    added_by_id = Column(ForeignKey('user.id'), nullable=False)
    module_human_name = Column(Text)
    module_name = Column(Text)
    module_description = Column(Text)
    module_version = Column(Text)
    interface_version = Column(Text)
    date_added = Column(DateTime)
    is_active = Column(Boolean)
    has_pipeline = Column(Boolean)
    pipeline_args = Column(JSON)
    module_config = Column(JSON)
    module_type = Column(Text)

    user = relationship('User')


class IrisHook(db.Model):
    __tablename__ = "iris_hooks"

    id = Column(Integer, primary_key=True)
    hook_name = Column(Text)
    hook_description = Column(Text)


class IrisModuleHook(db.Model):
    __tablename__ = "iris_module_hooks"

    id = Column(BigInteger, primary_key=True)
    module_id = Column(ForeignKey('iris_module.id'), nullable=False)
    hook_id = Column(ForeignKey('iris_hooks.id'), nullable=False)
    is_manual_hook = Column(Boolean)
    manual_hook_ui_name = Column(Text)
    retry_on_fail = Column(Boolean)
    max_retry = Column(Integer)
    run_asynchronously = Column(Boolean)
    wait_till_return = Column(Boolean)

    module = relationship('IrisModule')
    hook = relationship('IrisHook')


class IrisReport(db.Model):
    __tablename__ = 'iris_reports'

    report_id = Column(db.Integer, Sequence("iris_reports_id_seq"), primary_key=True)
    case_id = Column(ForeignKey('cases.case_id'), nullable=False)
    report_title = Column(String(155))
    report_date = Column(DateTime)
    report_content = Column('report_content', JSON)
    user_id = Column(ForeignKey('user.id'))

    user = relationship('User')
    case = relationship('Cases')

    def __init__(self, case_id, report_title, report_date, report_content, user_id):
        self.case_id = case_id
        self.report_title = report_title
        self.report_date = report_date
        self.report_content = report_content
        self.user_id = user_id

    def save(self):
        # Create an engine and a session because this method
        # will be called from Celery thread and might cause
        # error if it uses the session context of the app
        engine = create_engine(app.config['SQLALCHEMY_DATABASE_URI'])
        Session = sessionmaker(bind=engine)
        session = Session()

        # inject self into db session
        session.add(self)

        # commit change and save the object
        session.commit()

        # Close session
        session.close()

        # Dispose engine
        engine.dispose()

        return self


class SavedFilter(db.Model):
    __tablename__ = 'saved_filters'

    filter_id = Column(BigInteger, primary_key=True)
    created_by = Column(ForeignKey('user.id'), nullable=False)
    filter_name = Column(Text, nullable=False)
    filter_description = Column(Text)
    filter_data = Column(JSON, nullable=False)
    filter_is_private = Column(Boolean, nullable=False)
    filter_type = Column(Text, nullable=False)

    user = relationship('User', foreign_keys=[created_by])


class ReviewStatus(db.Model):
    __tablename__ = 'review_status'

    id = Column(Integer, primary_key=True)
    status_name = Column(Text, nullable=False)


class CeleryTaskMeta(db.Model):
    __bind_key__ = 'iris_tasks'
    __tablename__ = 'celery_taskmeta'

    id = Column(BigInteger, Sequence('task_id_sequence'), primary_key=True)
    task_id = Column(String(155))
    status = Column(String(50))
    result = Column(LargeBinary)
    date_done = Column(DateTime)
    traceback = Column(Text)
    name = Column(String(155))
    args = Column(LargeBinary)
    kwargs = Column(LargeBinary)
    worker = Column(String(155))
    retries = Column(Integer)
    queue = Column(String(155))

    def __repr__(self):
        return str(self.id) + ' - ' + str(self.user)


def create_safe_attr(session, attribute_display_name, attribute_description, attribute_for, attribute_content):
    cat = CustomAttribute.query.filter(
        CustomAttribute.attribute_display_name == attribute_display_name,
        CustomAttribute.attribute_description == attribute_description,
        CustomAttribute.attribute_for == attribute_for
    ).first()

    if cat:
        return False
    else:
        instance = CustomAttribute()
        instance.attribute_display_name = attribute_display_name
        instance.attribute_description = attribute_description
        instance.attribute_for = attribute_for
        instance.attribute_content = attribute_content
        session.add(instance)
        session.commit()
        return True


class RuntimeSecret(db.Model):
    """Server-generated secrets that must be identical across every process.

    Exists so a deployment that never edited IRIS_SECRET_KEY does not run on the
    well-known placeholder shipped in .env.model / values.yaml / the EKS
    manifests. That value is public, and SECRET_KEY signs the session cookie, so
    anyone could forge a session for any user.

    Deliberately NOT a column on server_settings: that model is serialised by
    ServerSettingsSchema and round-tripped through the admin settings form, so a
    secret there could be exposed in an API response or overwritten by a save.

    Stored in the database rather than generated per process because the app runs
    as several containers (app / worker / ai_worker) and can scale to multiple
    replicas under the Helm chart. A per-process key would mean a session signed
    by one replica is rejected by the next, logging users out at random.

    UNIQUE on `name` lives on __table_args__ (not only in the migration) because
    IRIS runs db.create_all() from the ORM models BEFORE alembic; a constraint
    declared only in the migration would be skipped on a fresh install. It is
    also what makes first-boot generation race-safe: replicas start together, the
    first INSERT wins, and the losers re-read the winner's value.
    """
    __tablename__ = 'runtime_secret'
    __table_args__ = (
        UniqueConstraint('name', name='uq_runtime_secret_name'),
    )

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    value = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=text('now()'))


class AnnouncementBanner(db.Model):
    """iris-ng v2: top-of-app announcement banners (v3 parity, Settings >
    Banners). Published to every AUTHENTICATED user while active — maintenance
    notices, outages, announcements. Message is plain text, escaped at render;
    level drives the strip colour through a validated map on the client (a
    free-form value must never reach a style attribute).

    CHECK lives on __table_args__ (not only the migration) because IRIS runs
    db.create_all() before alembic — a constraint declared only in the
    migration is skipped on a fresh install.
    """
    __tablename__ = 'announcement_banner'
    __table_args__ = (
        CheckConstraint("level IN ('info', 'warning', 'danger')",
                        name='ck_announcement_banner_level'),
    )

    id = Column(Integer, primary_key=True)
    message = Column(Text, nullable=False)
    level = Column(Text, nullable=False, default='info', server_default='info')
    is_active = Column(Boolean, nullable=False, default=True, server_default=text('true'))
    created_at = Column(DateTime, server_default=text('now()'))
    created_by = Column(ForeignKey('user.id'), nullable=True)
