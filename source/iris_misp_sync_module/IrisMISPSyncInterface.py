#!/usr/bin/env python3
#
#  IRIS MISP Sync Module Source Code
#

from __future__ import annotations

import datetime
import json
from typing import Any

import iris_interface.IrisInterfaceStatus as InterfaceStatus
from iris_interface.IrisModuleInterface import IrisModuleInterface, IrisModuleTypes

import iris_misp_sync_module.IrisMISPSyncConfig as interface_conf
from app import db
from app.misp_ioc_taxonomy import resolve_ioc_type_taxonomy
from app.models.cases import Cases
from app.models.models import Ioc
from app.models.models import MispAttributeLink
from app.models.models import MispEventLink
from iris_misp_sync_module.ai_type_resolver import AITypeResolver
from iris_misp_sync_module.ai_type_resolver import AITypeResolverError
from iris_misp_sync_module.misp_sync_client import MispSyncClient
from iris_misp_sync_module.misp_sync_client import MispSyncClientError


class IrisMISPSyncHandler:
    """Implements the Phase 1 case and IOC synchronization behavior."""

    def __init__(self, mod_config: dict[str, Any], logger):
        self.log = logger
        self.config = mod_config
        self._type_defaults: dict[str, str] | None = None

    def _is_configured(self) -> bool:
        return bool(self.config.get("misp_sync_url") and self.config.get("misp_sync_api_key"))

    def _build_client(self) -> MispSyncClient:
        if not self._is_configured():
            raise MispSyncClientError("MISP sync is not configured yet")

        proxies = {}
        if self.config.get("misp_sync_http_proxy"):
            proxies["http"] = self.config.get("misp_sync_http_proxy")
        if self.config.get("misp_sync_https_proxy"):
            proxies["https"] = self.config.get("misp_sync_https_proxy")

        return MispSyncClient(
            base_url=self.config.get("misp_sync_url"),
            api_key=self.config.get("misp_sync_api_key"),
            verify_tls=bool(self.config.get("misp_sync_verify_tls", True)),
            proxies=proxies or None
        )

    @staticmethod
    def _clean_payload(payload: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in payload.items() if value not in (None, "", [], {})}

    def _parse_tlp_policy(self) -> dict[str, int]:
        raw_policy = self.config.get("misp_sync_tlp_distribution_policy") or "{}"
        if isinstance(raw_policy, dict):
            return {str(key).lower(): int(value) for key, value in raw_policy.items()}

        try:
            data = json.loads(raw_policy)
        except json.JSONDecodeError as exc:
            raise MispSyncClientError("The TLP distribution policy is not valid JSON") from exc

        return {str(key).lower(): int(value) for key, value in data.items()}

    def _default_attribute_distribution(self, ioc: Ioc, event_link: MispEventLink) -> int:
        tlp_name = ""
        if getattr(ioc, "tlp", None) and getattr(ioc.tlp, "tlp_name", None):
            tlp_name = ioc.tlp.tlp_name.lower()

        policy = self._parse_tlp_policy()
        if tlp_name in policy:
            return policy[tlp_name]

        return event_link.misp_distribution or int(self.config.get("misp_sync_distribution", 4))

    def _get_type_defaults(self, client: MispSyncClient) -> dict[str, str]:
        if self._type_defaults is not None:
            return self._type_defaults

        response = client.describe_types()
        sane_defaults = response.get("result", {}).get("sane_defaults", {})
        self._type_defaults = {
            type_name: details.get("default_category")
            for type_name, details in sane_defaults.items()
            if details.get("default_category")
        }
        return self._type_defaults

    def _event_payload(self, case: Cases) -> dict[str, Any]:
        org_id = self.config.get("misp_sync_org_id")
        payload = {
            "info": case.name or f"IRIS case #{case.case_id}",
            "date": case.open_date.isoformat() if case.open_date else datetime.date.today().isoformat(),
            "distribution": self.config.get("misp_sync_distribution"),
            "sharing_group_id": self.config.get("misp_sync_sharing_group_id"),
            "threat_level_id": self.config.get("misp_sync_threat_level_id"),
            "analysis": self.config.get("misp_sync_analysis"),
            "org_id": str(org_id) if org_id is not None else None,
            "orgc_id": str(org_id) if org_id is not None else None,
            "published": False
        }
        return self._clean_payload(payload)

    @staticmethod
    def _case_tag_names(case: Cases) -> list[str]:
        return [tag.tag_title for tag in getattr(case, "tags", []) if getattr(tag, "tag_title", None)]

    @staticmethod
    def _ioc_tag_names(ioc: Ioc) -> list[str]:
        if not ioc.ioc_tags:
            return []
        return [tag.strip() for tag in ioc.ioc_tags.split(",") if tag.strip()]

    @staticmethod
    def _iter_tag_records(payload: Any):
        if isinstance(payload, dict):
            if "Tag" in payload and isinstance(payload["Tag"], dict):
                yield payload["Tag"]
            elif "id" in payload and "name" in payload:
                yield payload

            for value in payload.values():
                yield from IrisMISPSyncHandler._iter_tag_records(value)

        elif isinstance(payload, list):
            for item in payload:
                yield from IrisMISPSyncHandler._iter_tag_records(item)

    def _ensure_tag(self, client: MispSyncClient, tag_name: str) -> int | None:
        search_response = client.search_tags(tag_name)
        for tag in self._iter_tag_records(search_response):
            if tag.get("name") == tag_name and tag.get("id") is not None:
                return int(tag["id"])

        try:
            create_response = client.create_tag({
                "name": tag_name,
                "colour": "#5182b6",
                "exportable": True,
                "hide_tag": False,
                "org_id": "0",
                "user_id": "0"
            })
            for tag in self._iter_tag_records(create_response):
                if tag.get("name") == tag_name and tag.get("id") is not None:
                    return int(tag["id"])
        except MispSyncClientError:
            # The tag may already exist or the instance may restrict creation;
            # fall through to a second lookup before giving up.
            self.log.info(f"Unable to create tag {tag_name}, retrying search")

        search_response = client.search_tags(tag_name)
        for tag in self._iter_tag_records(search_response):
            if tag.get("name") == tag_name and tag.get("id") is not None:
                return int(tag["id"])

        self.log.warning(f"Unable to resolve MISP tag id for {tag_name}")
        return None

    @staticmethod
    def _extract_event_record(payload: dict[str, Any]) -> dict[str, Any]:
        if isinstance(payload.get("Event"), dict):
            return payload["Event"]
        if isinstance(payload.get("response"), dict) and isinstance(payload["response"].get("Event"), dict):
            return payload["response"]["Event"]
        return payload

    @staticmethod
    def _extract_attribute_record(payload: dict[str, Any]) -> dict[str, Any]:
        if isinstance(payload.get("Attribute"), dict):
            return payload["Attribute"]
        if isinstance(payload.get("response"), dict):
            response = payload["response"]
            if isinstance(response.get("Attribute"), list) and response["Attribute"]:
                return response["Attribute"][0]
            if isinstance(response.get("Attribute"), dict):
                return response["Attribute"]
        return payload

    def _sync_event_tags(self, client: MispSyncClient, case: Cases, event_link: MispEventLink):
        if not self.config.get("misp_sync_tag_sync_enabled", True):
            return

        for tag_name in self._case_tag_names(case):
            tag_id = self._ensure_tag(client, tag_name)
            if tag_id is not None:
                try:
                    client.add_event_tag(event_link.misp_event_id, tag_id, local=False)
                except MispSyncClientError:
                    self.log.info(f"Skipping duplicate or rejected event tag {tag_name}")

    def _sync_attribute_tags(self, client: MispSyncClient, ioc: Ioc, attr_id: int):
        if not self.config.get("misp_sync_tag_sync_enabled", True):
            return

        tag_names = self._ioc_tag_names(ioc)
        if getattr(ioc, "tlp", None) and getattr(ioc.tlp, "tlp_name", None):
            tag_names.append(f"tlp:{ioc.tlp.tlp_name.lower()}")

        for tag_name in tag_names:
            tag_id = self._ensure_tag(client, tag_name)
            if tag_id is not None:
                try:
                    client.add_attribute_tag(attr_id, tag_id, local=False)
                except MispSyncClientError:
                    self.log.info(f"Skipping duplicate or rejected attribute tag {tag_name}")

    def _get_or_create_event_link(self, client: MispSyncClient, case: Cases) -> MispEventLink:
        event_link = MispEventLink.query.filter(MispEventLink.case_id == case.case_id).first()
        if event_link:
            return event_link

        event_response = client.create_event(self._event_payload(case))
        event_data = self._extract_event_record(event_response)
        if not event_data.get("id"):
            raise MispSyncClientError(f"Unable to read MISP event id from response: {event_response}")

        event_link = MispEventLink()
        event_link.case_id = case.case_id
        event_link.misp_event_id = int(event_data["id"])
        event_link.misp_event_uuid = event_data.get("uuid")
        event_link.misp_org_id = int(self.config.get("misp_sync_org_id")) if self.config.get("misp_sync_org_id") is not None else None
        event_link.misp_distribution = int(self.config.get("misp_sync_distribution")) if self.config.get("misp_sync_distribution") is not None else None
        event_link.misp_sharing_group_id = int(self.config.get("misp_sync_sharing_group_id")) if self.config.get("misp_sync_sharing_group_id") is not None else None
        event_link.last_synced_at = datetime.datetime.utcnow()
        db.session.add(event_link)
        db.session.commit()

        self._sync_event_tags(client, case, event_link)
        event_link.last_synced_at = datetime.datetime.utcnow()
        db.session.commit()
        return event_link

    def sync_case_create(self, case: Cases):
        client = self._build_client()
        self._get_or_create_event_link(client, case)

    def sync_case_update(self, case: Cases):
        client = self._build_client()
        event_link = MispEventLink.query.filter(MispEventLink.case_id == case.case_id).first()
        if event_link is None:
            event_link = self._get_or_create_event_link(client, case)
        else:
            client.update_event(event_link.misp_event_id, self._event_payload(case))

        self._sync_event_tags(client, case, event_link)
        event_link.last_synced_at = datetime.datetime.utcnow()
        db.session.commit()

    @staticmethod
    def _build_ioc_comment(ioc: Ioc) -> str:
        comment_parts = [
            f"dfir_ioc_id={ioc.ioc_id}",
            f"dfir_ioc_uuid={ioc.ioc_uuid}",
            f"dfir_case_id={ioc.case_id}"
        ]

        if ioc.tlp and ioc.tlp.tlp_name:
            comment_parts.append(f"tlp={ioc.tlp.tlp_name.lower()}")
        if ioc.ioc_description:
            comment_parts.append(f"desc={ioc.ioc_description}")
        if ioc.ioc_tags:
            comment_parts.append(f"tags={ioc.ioc_tags}")

        return " | ".join(comment_parts)

    def _build_ai_resolver(self) -> AITypeResolver | None:
        if not bool(self.config.get("misp_sync_ai_enabled", False)):
            return None

        url = (self.config.get("misp_sync_ai_url") or "").strip()
        model = (self.config.get("misp_sync_ai_model") or "").strip()
        if not url or not model:
            return None

        try:
            return AITypeResolver(
                base_url=url,
                api_key=self.config.get("misp_sync_ai_api_key") or "",
                model=model
            )
        except AITypeResolverError as exc:
            self.log.warning(f"AI fallback disabled: {exc}")
            return None

    def _ai_confidence_threshold(self) -> float:
        try:
            value = float(self.config.get("misp_sync_ai_confidence_threshold", 0.70))
        except (TypeError, ValueError):
            value = 0.70
        return max(0.0, min(1.0, value))

    def _try_ai_fallback(self, ioc: Ioc, defaults: dict[str, str]) -> str | None:
        raw_type = getattr(ioc.ioc_type, "type_name", None)
        if not raw_type or not AITypeResolver.supports(raw_type):
            return None

        resolver = self._build_ai_resolver()
        if resolver is None:
            return None

        tlp_name = getattr(getattr(ioc, "tlp", None), "tlp_name", "") or ""

        try:
            suggestion = resolver.resolve(
                raw_type=raw_type,
                value=ioc.ioc_value or "",
                description=ioc.ioc_description or "",
                tags=ioc.ioc_tags or "",
                tlp=tlp_name
            )
        except AITypeResolverError as exc:
            self.log.warning(
                f"AI fallback for IOC #{ioc.ioc_id} ({raw_type}={ioc.ioc_value!r}) failed: {exc}"
            )
            return None

        threshold = self._ai_confidence_threshold()
        confidence = suggestion["confidence"]
        mapped = suggestion["mapped_type"]

        if confidence < threshold:
            self.log.warning(
                f"AI fallback for IOC #{ioc.ioc_id} ({raw_type}={ioc.ioc_value!r}) "
                f"suggested {mapped!r} at confidence {confidence:.2f} < threshold {threshold:.2f}; "
                f"skipping sync. Reason: {suggestion.get('reason') or 'n/a'}"
            )
            return None

        if mapped not in defaults:
            self.log.warning(
                f"AI fallback for IOC #{ioc.ioc_id} ({raw_type}={ioc.ioc_value!r}) "
                f"suggested {mapped!r} but that type is not present in MISP describeTypes; skipping sync"
            )
            return None

        self.log.info(
            f"AI fallback for IOC #{ioc.ioc_id} ({raw_type}={ioc.ioc_value!r}) "
            f"resolved to MISP type {mapped!r} at confidence {confidence:.2f} "
            f"(model={suggestion['model']}, reason={suggestion.get('reason') or 'n/a'})"
        )
        return mapped

    def _resolve_misp_type(self, client: MispSyncClient, ioc: Ioc) -> str:
        defaults = self._get_type_defaults(client)
        misp_type = resolve_ioc_type_taxonomy(
            getattr(ioc.ioc_type, "type_name", None),
            getattr(ioc.ioc_type, "type_taxonomy", None)
        )

        if not misp_type:
            misp_type = self._try_ai_fallback(ioc, defaults)

        if not misp_type:
            raise MispSyncClientError(
                f"IOC #{ioc.ioc_id} type {ioc.ioc_type.type_name} does not have a direct "
                f"MISP attribute-type mapping (AI fallback unavailable, disabled, or below threshold)"
            )
        if misp_type not in defaults:
            raise MispSyncClientError(
                f"IOC #{ioc.ioc_id} resolved to MISP type {misp_type}, but that type is not present in describeTypes"
            )
        return misp_type

    def _attribute_payload(self, ioc: Ioc, event_link: MispEventLink, misp_type: str, category: str) -> dict[str, Any]:
        distribution = self._default_attribute_distribution(ioc, event_link)
        sharing_group_id = None
        if distribution == 4:
            sharing_group_id = event_link.misp_sharing_group_id
            if sharing_group_id is None:
                raise MispSyncClientError(
                    "Attribute distribution 4 requires a MISP sharing group id in the synced event link"
                )

        payload = {
            "type": misp_type,
            "category": category,
            "value": ioc.ioc_value,
            "to_ids": bool(self.config.get("misp_sync_attribute_to_ids", True)),
            "comment": self._build_ioc_comment(ioc),
            "distribution": distribution,
            "sharing_group_id": sharing_group_id
        }
        return self._clean_payload(payload)

    def _category_for_ioc(self, client: MispSyncClient, misp_type: str) -> str:
        defaults = self._get_type_defaults(client)
        category = defaults.get(misp_type)
        if not category:
            raise MispSyncClientError(
                f"Unable to resolve a default MISP category for IOC type {misp_type}"
            )
        return category

    def _lookup_existing_attribute(self, client: MispSyncClient, ioc: Ioc, event_link: MispEventLink) -> dict[str, Any] | None:
        search_response = client.search_attributes({
            "returnFormat": "json",
            "eventid": event_link.misp_event_id,
            "searchall": f"dfir_ioc_uuid={ioc.ioc_uuid}",
            "includeContext": False
        })
        attributes = search_response.get("response", {}).get("Attribute", [])
        if attributes:
            return attributes[0]
        return None

    def sync_ioc(self, ioc: Ioc):
        if not ioc.case_id:
            self.log.info(f"Skipping IOC #{ioc.ioc_id} because it is not attached to a case")
            return

        case = ioc.case if getattr(ioc, "case", None) else Cases.query.filter(Cases.case_id == ioc.case_id).first()
        if case is None:
            raise MispSyncClientError(f"Unable to resolve case #{ioc.case_id} for IOC #{ioc.ioc_id}")

        client = self._build_client()
        event_link = self._get_or_create_event_link(client, case)
        misp_type = self._resolve_misp_type(client, ioc)
        category = self._category_for_ioc(client, misp_type)
        payload = self._attribute_payload(ioc, event_link, misp_type, category)

        attr_link = MispAttributeLink.query.filter(MispAttributeLink.ioc_id == ioc.ioc_id).first()
        if attr_link is None:
            existing_attribute = self._lookup_existing_attribute(client, ioc, event_link)
            if existing_attribute:
                attr_link = MispAttributeLink()
                attr_link.event_link_id = event_link.id
                attr_link.ioc_id = ioc.ioc_id
                attr_link.misp_attribute_id = int(existing_attribute["id"])
                attr_link.misp_attribute_uuid = existing_attribute.get("uuid")
                attr_link.last_synced_at = datetime.datetime.utcnow()
                db.session.add(attr_link)
                db.session.commit()

        if attr_link is None:
            response = client.add_attribute(event_link.misp_event_id, payload)
            attr_data = self._extract_attribute_record(response)
            if not attr_data.get("id"):
                raise MispSyncClientError(f"Unable to read MISP attribute id from response: {response}")

            attr_link = MispAttributeLink()
            attr_link.event_link_id = event_link.id
            attr_link.ioc_id = ioc.ioc_id
            attr_link.misp_attribute_id = int(attr_data["id"])
            attr_link.misp_attribute_uuid = attr_data.get("uuid")
            attr_link.last_synced_at = datetime.datetime.utcnow()
            db.session.add(attr_link)
        else:
            response = client.update_attribute(attr_link.misp_attribute_id, payload)
            attr_data = self._extract_attribute_record(response)
            attr_link.misp_attribute_uuid = attr_data.get("uuid", attr_link.misp_attribute_uuid)
            attr_link.last_synced_at = datetime.datetime.utcnow()

        ioc.ioc_misp = attr_link.misp_attribute_uuid or str(attr_link.misp_attribute_id)
        event_link.last_synced_at = datetime.datetime.utcnow()
        db.session.commit()
        self._sync_attribute_tags(client, ioc, attr_link.misp_attribute_id)


class IrisMISPSyncInterface(IrisModuleInterface):
    """Provide the interface between IRIS and the native MISP sync module."""

    name = "IrisMISPSyncInterface"
    module_id = -1
    _module_name = interface_conf.module_name
    _module_description = interface_conf.module_description
    _interface_version = interface_conf.interface_version
    _module_version = interface_conf.module_version
    _pipeline_support = interface_conf.pipeline_support
    _pipeline_info = interface_conf.pipeline_info
    _module_configuration = interface_conf.module_configuration
    _module_type = IrisModuleTypes.module_processor

    def register_hooks(self, module_id: int):
        self.module_id = module_id
        hook_map = [
            ("misp_sync_case_create_enabled", "on_postload_case_create"),
            ("misp_sync_case_update_enabled", "on_postload_case_update"),
            ("misp_sync_ioc_create_enabled", "on_postload_ioc_create"),
            ("misp_sync_ioc_update_enabled", "on_postload_ioc_update")
        ]

        for config_key, hook_name in hook_map:
            if self.module_dict_conf.get(config_key):
                status = self.register_to_hook(module_id, iris_hook_name=hook_name)
                if status.is_failure():
                    self.log.error(status.get_message())
                    self.log.error(status.get_data())
            else:
                self.deregister_from_hook(module_id=self.module_id, iris_hook_name=hook_name)

    def hooks_handler(self, hook_name: str, hook_ui_name: str, data: Any):
        self.log.info(f"Received {hook_name}")

        # Fork-safety: IRIS dispatches each hook payload to a celery prefork
        # ForkPoolWorker. The child inherits the parent's SQLAlchemy
        # session + the live psycopg2 connection it was holding — Postgres
        # connections are NOT fork-safe and the first query in the child
        # crashes with `(psycopg2.DatabaseError) error with status
        # PGRES_TUPLES_OK and no message from the libpq`. Discarding the
        # scoped session at task entry forces each child to take a fresh
        # connection from the pool. This is the documented SQLAlchemy +
        # multiprocessing fix; see
        # https://docs.sqlalchemy.org/en/20/core/pooling.html#using-connection-pools-with-multiprocessing-or-os-fork
        # Without this, Accept-all flows that fire N parallel `+ add`
        # POSTs lose IOCs because every-other prefork child crashes
        # before reaching MISP.
        try:
            from app import db
            db.session.remove()
        except Exception as exc:
            # Don't let a session-cleanup failure mask the real hook work
            # below — log and continue. If the session was already clean
            # this is a no-op.
            self.log.warning(f"db.session.remove() at hook entry raised: {exc}")

        handler = IrisMISPSyncHandler(mod_config=self.module_dict_conf, logger=self.log)
        failures = []

        if hook_name in ["on_postload_case_create", "on_postload_case_update"]:
            for case in data:
                try:
                    if hook_name == "on_postload_case_create":
                        handler.sync_case_create(case)
                    else:
                        handler.sync_case_update(case)
                except Exception as exc:
                    self.log.exception(exc)
                    failures.append(str(exc))

        elif hook_name in ["on_postload_ioc_create", "on_postload_ioc_update"]:
            for ioc in data:
                try:
                    handler.sync_ioc(ioc)
                except Exception as exc:
                    self.log.exception(exc)
                    failures.append(str(exc))
        else:
            msg = f"Received unsupported hook {hook_name}"
            self.log.critical(msg)
            return InterfaceStatus.I2Error(message=msg, data=data, logs=list(self.message_queue))

        if failures:
            return InterfaceStatus.I2Error(
                message=f"Encountered error processing hook {hook_name}",
                data=data,
                logs=list(self.message_queue)
            )

        return InterfaceStatus.I2Success(data=data, logs=list(self.message_queue))
