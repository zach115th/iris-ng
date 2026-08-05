#!/usr/bin/env python3
#
#  IRIS MISP Cluster Module Source Code
#
#  Publishes a cross-case IOC correlation cluster to MISP as ONE campaign
#  event. One-directional (iris-ng -> MISP) by design: nothing is read back,
#  so a MISP-side edit is never overwritten by iris-ng and vice versa.
#
#  Trigger is an explicit "Push to MISP" button on the Correlation tab, NOT a
#  hook. Applying a campaign tag is local bookkeeping an analyst may do while
#  still triaging; making that publish to a shared MISP would be a surprising
#  and hard-to-undo side effect. This module therefore registers NO hooks and
#  is invoked directly by the correlation REST endpoint.

import re
from typing import Any

from iris_interface.IrisModuleInterface import IrisModuleInterface
from iris_interface.IrisModuleInterface import IrisModuleTypes
import iris_interface.IrisInterfaceStatus as InterfaceStatus

import iris_misp_cluster_module.IrisMISPClusterConfig as interface_conf

# NB: the MISP REST client is shared with IrisMISPSync rather than duplicated.
# It carries non-obvious fixes — notably search_tags() using POST /tags/index,
# because GET /tags/search/<term> silently returns [] for any name containing a
# colon, which is every taxonomy tag. Forking it would fork that bug back in.
# If this module is ever packaged and shipped independently, vendor the client
# rather than re-implementing it.
from iris_misp_sync_module.misp_sync_client import MispSyncClient
from iris_misp_sync_module.misp_sync_client import MispSyncClientError


class IrisMISPClusterError(Exception):
    """Raised when a cluster cannot be published to MISP."""


class IrisMISPClusterHandler:
    """Builds and pushes the campaign event for one correlation cluster."""

    def __init__(self, mod_config: dict[str, Any], logger):
        self.mod_config = mod_config or {}
        self.log = logger

    # ----- configuration -------------------------------------------------

    def is_configured(self) -> bool:
        url = (self.mod_config.get("misp_cluster_url") or "").strip()
        key = (self.mod_config.get("misp_cluster_api_key") or "").strip()
        return bool(url) and bool(key) and url != "https://misp.example.com"

    def build_client(self) -> MispSyncClient:
        proxies = {}
        if self.mod_config.get("misp_cluster_http_proxy"):
            proxies["http"] = self.mod_config["misp_cluster_http_proxy"]
        if self.mod_config.get("misp_cluster_https_proxy"):
            proxies["https"] = self.mod_config["misp_cluster_https_proxy"]

        return MispSyncClient(
            base_url=self.mod_config.get("misp_cluster_url", ""),
            api_key=self.mod_config.get("misp_cluster_api_key", ""),
            verify_tls=bool(self.mod_config.get("misp_cluster_verify_tls", True)),
            proxies=proxies or None,
        )

    # ----- tag helpers ---------------------------------------------------

    @staticmethod
    def _iter_tag_records(payload: Any):
        """MISP's tag responses vary in shape between versions and endpoints."""
        if isinstance(payload, dict):
            for key in ("Tag", "response", "tags", "data"):
                inner = payload.get(key)
                if isinstance(inner, list):
                    yield from (t for t in inner if isinstance(t, dict))
                elif isinstance(inner, dict):
                    yield inner
        elif isinstance(payload, list):
            for entry in payload:
                if isinstance(entry, dict):
                    yield entry.get("Tag", entry)

    def _ensure_tag(self, client: MispSyncClient, tag_name: str) -> int | None:
        """Resolve a tag name to its MISP id, creating the tag if absent."""
        name = (tag_name or "").strip()
        if not name:
            return None

        try:
            found = client.search_tags(name)
        except MispSyncClientError as exc:
            self.log.warning(f"MISP tag search failed for '{name}': {exc}")
            found = None

        for record in self._iter_tag_records(found):
            if str(record.get("name", "")).lower() == name.lower():
                try:
                    return int(record["id"])
                except (KeyError, TypeError, ValueError):
                    continue

        try:
            created = client.create_tag({"name": name})
        except MispSyncClientError as exc:
            self.log.warning(f"MISP tag create failed for '{name}': {exc}")
            return None

        for record in self._iter_tag_records(created):
            try:
                return int(record["id"])
            except (KeyError, TypeError, ValueError):
                continue

        # MISP rejects duplicates; re-search covers the create-race.
        try:
            for record in self._iter_tag_records(client.search_tags(name)):
                if str(record.get("name", "")).lower() == name.lower():
                    return int(record["id"])
        except (MispSyncClientError, KeyError, TypeError, ValueError):
            pass

        return None

    def _tag_event(self, client: MispSyncClient, event_id: int, tag_name: str):
        tag_id = self._ensure_tag(client, tag_name)
        if tag_id is None:
            self.log.warning(f"Could not resolve MISP tag '{tag_name}' — event left untagged for it")
            return
        try:
            client.add_event_tag(event_id, tag_id)
        except MispSyncClientError as exc:
            self.log.warning(f"Failed to tag event {event_id} with '{tag_name}': {exc}")

    def _tag_attribute(self, client: MispSyncClient, attribute_id: int, tag_name: str):
        tag_id = self._ensure_tag(client, tag_name)
        if tag_id is None:
            return
        try:
            client.add_attribute_tag(attribute_id, tag_id)
        except MispSyncClientError as exc:
            self.log.warning(f"Failed to tag attribute {attribute_id} with '{tag_name}': {exc}")

    # ----- payload builders ----------------------------------------------

    def _event_payload(self, cluster: dict, narrative: dict | None) -> dict[str, Any]:
        cluster_id = cluster.get("cluster_id", "")
        case_ids = cluster.get("case_ids") or []
        shared = cluster.get("shared_iocs") or []

        name = ""
        if narrative:
            name = (narrative.get("suggested_name") or "").strip()
        title = name or f"iris-ng correlation cluster {cluster_id}"

        payload = {
            "info": title,
            "distribution": int(self.mod_config.get("misp_cluster_distribution", 0)),
            "threat_level_id": int(self.mod_config.get("misp_cluster_threat_level_id", 2)),
            "analysis": int(self.mod_config.get("misp_cluster_analysis", 1)),
            "org_id": int(self.mod_config.get("misp_cluster_org_id", 1)),
        }
        if payload["distribution"] == 4:
            payload["sharing_group_id"] = int(
                self.mod_config.get("misp_cluster_sharing_group_id", 1)
            )
        return payload

    # ----- entity-name redaction -----------------------------------------
    #
    # The v2 cluster-narrative prompt forbids the MODEL from writing entity
    # names, which is what makes the narrative safe to share. Analyst notes were
    # never prompt-constrained — they routinely name the client, its divisions,
    # dollar amounts and job titles — so publishing them verbatim would leak
    # exactly what the prompt was protecting. Everything that is free text gets
    # redacted here before it leaves.
    #
    # IOC VALUES ARE NEVER REDACTED. A lookalike domain built from the victim's
    # name IS the indicator; masking it would destroy the intelligence. Pushed
    # IOC values are therefore protected inside note text too, so a note quoting
    # `wayne-sso-verify.example` keeps it intact while a sentence naming the
    # organisation does not.

    REDACTION_PLACEHOLDER = "[redacted]"

    # Vocabulary that must NOT become a redaction term when tokenising client
    # and case names. Two groups:
    #   - incident/attack words: redacting them would strip the very thing the
    #     note is describing without protecting anyone.
    #   - SECTOR words: the v2 narrative prompt deliberately describes victims
    #     by sector role ("a water utility"), so sector language is the context
    #     worth keeping, not an identifier.
    _GENERIC_NAME_TOKENS = frozenset({
        # attack / incident vocabulary
        "spear", "phishing", "spearphishing", "campaign", "malware", "ransomware",
        "beacon", "backdoor", "trojan", "worm", "dropper", "loader", "implant",
        "exfiltration", "exfil", "compromise", "breach", "incident", "intrusion",
        "insider", "fraud", "wire", "credential", "credentials", "harvest",
        "theft", "dump", "lateral", "movement", "privilege", "escalation",
        "persistence", "command", "control", "recon", "reconnaissance",
        "delivery", "exploitation", "objectives", "staging", "pivot", "pivoting",
        "attempt", "suspected", "possible", "unknown", "investigation", "case",
        "alert", "report", "summary", "analysis", "review", "response", "triage",
        "business", "email", "mail", "mailbox", "account", "user", "admin",
        "administrator", "cobalt", "strike", "mimikatz", "psexec", "powershell",
        # infrastructure vocabulary
        "vlan", "network", "server", "workstation", "host", "endpoint", "domain",
        "subnet", "firewall", "proxy", "gateway", "cloud", "system", "systems",
        # sector vocabulary — keep, this is legitimate shared context
        "manufacturing", "energy", "water", "wastewater", "healthcare", "health",
        "financial", "finance", "banking", "government", "education", "retail",
        "telecom", "telecommunications", "utility", "utilities", "transport",
        "transportation", "defense", "defence", "chemical", "agriculture",
        "maritime", "nuclear", "emergency", "communications",
    })

    @classmethod
    def _redaction_terms(cls, terms: list[str] | None, extra_config: str | None) -> list[str]:
        """Normalise + expand the term list, longest first.

        `terms` carries client names AND case names supplied by the caller.
        Each contributes its full string plus its significant tokens, so a
        client recorded as "Wayne Enterprises" also catches "WayneTech", and a
        case titled "… Applied Sciences Credential Harvest" catches "Applied"
        and "Sciences" while leaving "Credential" and "Harvest" alone.

        Tokens under 4 characters and anything in the generic IR/sector
        vocabulary are dropped — otherwise ordinary incident prose would be
        shredded without protecting anybody.
        """
        collected: set[str] = set()
        for source in (terms or []):
            name = (source or "").strip()
            if len(name) < 3:
                continue
            collected.add(name)
            for token in re.split(r"[\s\-_/,()]+", name):
                token = token.strip(".:;#")
                if len(token) >= 4 and token.lower() not in cls._GENERIC_NAME_TOKENS:
                    # Skip pure numbers / case-number fragments.
                    if not token.isdigit():
                        collected.add(token)

        # Admin-supplied extras are explicit intent — never stoplist-filtered.
        for raw in (extra_config or "").split(","):
            token = raw.strip()
            if len(token) >= 3:
                collected.add(token)

        # Longest first so "Wayne Enterprises" is consumed before bare "Wayne".
        return sorted(collected, key=len, reverse=True)

    def _redact(self, text: str, terms: list[str], protected: list[str]) -> str:
        """Mask protected indicator values, redact entity terms, restore."""
        if not text or not terms:
            return text

        # Substring (not word-bounded) matching, because compound forms like
        # "WayneTech" have no boundary after the org token.
        working = text
        vault: dict[str, str] = {}
        for idx, value in enumerate(sorted(protected or [], key=len, reverse=True)):
            v = (value or "").strip()
            if not v:
                continue
            token = f"\x00IOC{idx}\x00"
            pattern = re.compile(re.escape(v), re.IGNORECASE)
            if pattern.search(working):
                working = pattern.sub(token, working)
                vault[token] = v

        for term in terms:
            # Trailing \w* so compound forms redact whole: "WayneTech" becomes
            # "[redacted]", not "[redacted]Tech". Erring toward over-redaction
            # is the correct bias for outbound sharing.
            working = re.compile(re.escape(term) + r"\w*", re.IGNORECASE).sub(
                self.REDACTION_PLACEHOLDER, working
            )

        for token, value in vault.items():
            working = working.replace(token, value)
        return working

    # Words that begin a sentence or are common in IR prose — never treated as
    # candidate entity names, or every note would be flagged.
    _PROPER_NOUN_STOPLIST = frozenset({
        "the", "this", "that", "these", "those", "initial", "summary", "targeted",
        "cobalt", "strike", "beacon", "insider", "business", "email", "compromise",
        "credential", "harvest", "attacker", "analyst", "case", "note", "usd",
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
        "january", "february", "march", "april", "may", "june", "july", "august",
        "september", "october", "november", "december", "windows", "linux", "macos",
        "active", "directory", "office", "outlook", "sharepoint", "vpn", "sso",
        "cfo", "ceo", "cto", "ciso", "it", "hr", "soc", "mfa", "dns", "http", "https",
    })

    @classmethod
    def _candidate_entity_names(cls, text: str) -> set[str]:
        """Proper-noun-ish phrases surviving redaction, for an advisory warning.

        Redaction only knows the client records plus the admin's extra-terms
        list, so a division, subsidiary or project name that appears purely in
        prose slips through. Rather than fail silently, flag what looks like an
        unredacted name so the analyst can add it to the config. Heuristic and
        advisory only — it never blocks or alters a push.
        """
        if not text:
            return set()
        found: set[str] = set()
        # Two or more consecutive Capitalised words ("Applied Sciences").
        # [ \t]+ not \s+ — a newline is a phrase boundary, otherwise a heading
        # and the next sentence's first word merge into a false candidate.
        for m in re.finditer(r"\b([A-Z][a-z]{2,}(?:[ \t]+[A-Z][a-z]{2,})+)\b", text):
            phrase = m.group(1)
            if all(w.lower() in cls._PROPER_NOUN_STOPLIST for w in phrase.split()):
                continue
            found.add(phrase)
        # Internal-capital tokens ("WayneTech", "AcmeCorp").
        for m in re.finditer(r"\b([A-Z][a-z]+[A-Z][A-Za-z]+)\b", text):
            if m.group(1).lower() not in cls._PROPER_NOUN_STOPLIST:
                found.add(m.group(1))
        return found

    # Hex-hash types whose length is fixed. Checked before the API call so a
    # malformed value reports as a readable reason instead of surfacing as an
    # opaque MISP 403/400 in the failures list. Deliberately narrow — only
    # shapes we are certain about, so legitimate values are never blocked.
    _HEX_HASH_LEN = {"md5": 32, "sha1": 40, "sha256": 64, "sha512": 128}

    @classmethod
    def _shape_problem(cls, misp_type: str, value: str) -> str | None:
        """Return a human-readable reason when a value cannot be that type."""
        expected = cls._HEX_HASH_LEN.get((misp_type or "").strip().lower())
        if expected is None:
            return None
        v = (value or "").strip()
        if len(v) != expected:
            return f"not a valid {misp_type}: {len(v)} characters, expected {expected}"
        if not all(c in "0123456789abcdefABCDEF" for c in v):
            return f"not a valid {misp_type}: contains non-hexadecimal characters"
        return None

    DEFAULT_ATTRIBUTE_COMMENT = "Shared indicator from an iris-ng cross-case correlation cluster"

    def _build_attribute_comment(self, descriptions: list[str], scrub) -> str:
        """MISP attribute comment from the analyst's own IOC descriptions.

        `Ioc.ioc_description` IS the analyst's comment on that indicator — the
        text iris-ng shows as "Analyst note on this IOC" — so it belongs in
        MISP's comment field. The same value carries a different description in
        each case it appears in ("sending infrastructure" vs "beacon C2"), and
        all of them are useful, so every distinct one is published.

        Falls back to a provenance line only when no analyst wrote anything.
        Redacted like all other free text — descriptions routinely name the
        client and its divisions.
        """
        cap = int(self.mod_config.get("misp_cluster_note_max_chars", 4000))
        cleaned = []
        for desc in descriptions or []:
            text = scrub((desc or "").strip())
            if text and text not in cleaned:
                cleaned.append(text)

        if not cleaned:
            return self.DEFAULT_ATTRIBUTE_COMMENT

        joined = "\n".join(cleaned)
        if len(joined) > cap:
            joined = joined[:cap] + " [truncated by iris-ng]"
        return joined

    def _attribute_payload(self, ioc_value: str, misp_type: str,
                           comment: str | None = None) -> dict[str, Any]:
        return {
            "value": ioc_value,
            "type": misp_type,
            "to_ids": bool(self.mod_config.get("misp_cluster_attribute_to_ids", True)),
            "distribution": 5,  # inherit from the event
            "comment": comment or self.DEFAULT_ATTRIBUTE_COMMENT,
        }

    def _note_distribution(self) -> str:
        """Sharing level for analyst notes, derived from the event's setting.

        MISP analyst data accepts distribution 0-3 only — 5 ("inherit event")
        is rejected — so notes cannot simply follow the event and the value has
        to be resolved here. Sharing groups (4) have no analyst-data equivalent
        either, so that falls back to org-only rather than silently widening.
        """
        try:
            event_distribution = int(self.mod_config.get("misp_cluster_distribution", 0))
        except (TypeError, ValueError):
            event_distribution = 0
        return str(event_distribution) if event_distribution in (0, 1, 2, 3) else "0"

    def _attach_notes(self, client: MispSyncClient, attribute_uuid: str,
                      notes: list[dict], scrub) -> tuple[int, list[str]]:
        """Attach each linked analyst note to the indicator as a MISP Note.

        Analyst notes rather than the attribute `comment` field: they are
        first-class objects with an author, timestamp and their own sharing
        level, several can hang off one indicator (so a note citing three IOCs
        appears on all three), and the comment column stays a short provenance
        line instead of a wall of prose.
        """
        cap = int(self.mod_config.get("misp_cluster_note_max_chars", 4000))
        distribution = self._note_distribution()
        attached, failures = 0, []
        seen: set[str] = set()

        for note in notes or []:
            body = (note.get("content") or "").strip()
            if not body:
                continue
            title = scrub((note.get("title") or "Analyst note").strip())
            text = f"**{title}**\n\n{scrub(body)}"
            if len(text) > cap:
                text = text[:cap] + "\n\n*[truncated by iris-ng]*"
            if text in seen:
                continue
            seen.add(text)
            try:
                client.add_analyst_note({
                    "object_type": "Attribute",
                    "object_uuid": attribute_uuid,
                    "note": text,
                    "language": "en",
                    "distribution": distribution,
                })
                attached += 1
            except MispSyncClientError as exc:
                failures.append(f"note '{title}': {exc}")
        return attached, failures

    def push_cluster(
        self,
        cluster: dict,
        narrative: dict | None,
        ioc_records: list[dict],
        campaign_tag: str | None = None,
        redact_terms: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create the campaign event and populate it.

        `ioc_records` is a list of
            {value, misp_type, tags: [str], notes: [{title, content}]}
        built by the caller from the already TLP-filtered cluster data — this
        module does no correlation querying of its own.

        Returns a summary dict for the UI.
        """
        if not self.is_configured():
            raise IrisMISPClusterError(
                "IrisMISPCluster is not configured — set the MISP URL and API key "
                "in /manage/modules"
            )

        client = self.build_client()
        cluster_id = cluster.get("cluster_id", "")

        # Redaction context. `protected` is every indicator value we are about
        # to publish — those must survive inside note prose untouched.
        redact_on = bool(self.mod_config.get("misp_cluster_redact_enabled", True))
        terms = self._redaction_terms(
            redact_terms, self.mod_config.get("misp_cluster_redact_terms")
        ) if redact_on else []
        protected = [r.get("value", "") for r in ioc_records]
        redactions = 0
        possible_unredacted: set[str] = set()

        def scrub(text: str) -> str:
            nonlocal redactions
            if not terms or not text:
                return text
            out = self._redact(text, terms, protected)
            if out != text:
                redactions += 1
            possible_unredacted.update(self._candidate_entity_names(out))
            return out

        # The event title and the campaign galaxy tag both derive from
        # suggested_name, so scrub it once and use the result for both.
        safe_narrative = dict(narrative) if narrative else None
        if safe_narrative:
            safe_narrative["suggested_name"] = scrub(
                (safe_narrative.get("suggested_name") or "").strip()
            )

        try:
            created = client.create_event(self._event_payload(cluster, safe_narrative))
        except MispSyncClientError as exc:
            raise IrisMISPClusterError(f"Could not create the MISP event: {exc}") from exc

        event = created.get("Event", created) if isinstance(created, dict) else {}
        try:
            event_id = int(event["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise IrisMISPClusterError(
                f"MISP did not return an event id for cluster {cluster_id}"
            ) from exc
        event_uuid = event.get("uuid")

        # --- event-level tags
        tlp_tag = (self.mod_config.get("misp_cluster_tlp_tag") or "").strip()
        if tlp_tag:
            self._tag_event(client, event_id, tlp_tag)
        if campaign_tag:
            self._tag_event(client, event_id, campaign_tag)
        if self.mod_config.get("misp_cluster_galaxy_enabled", True) and safe_narrative:
            name = (safe_narrative.get("suggested_name") or "").strip()
            if name:
                # Value form on the wire, per the MISP galaxy convention.
                self._tag_event(client, event_id, f'misp-galaxy:campaign="{name}"')

        # The campaign analysis goes into a MISP Event Report — a first-class
        # Markdown document — rather than a `type=comment` attribute. Reports
        # render properly and keep the attribute list to actual indicators.
        event_reports_created = 0
        if narrative and (narrative.get("narrative") or "").strip():
            # Scrubbed as defence in depth: the v2 prompt keeps entity names out
            # of MODEL output, but an analyst-edited narrative has no such
            # guarantee.
            body = scrub(narrative["narrative"].strip())
            confidence = str(narrative.get("confidence") or "").strip()
            report_name = (
                safe_narrative.get("suggested_name") if safe_narrative else ""
            ) or f"iris-ng correlation cluster {cluster_id}"

            content = f"## Campaign analysis\n\n{body}\n"
            if confidence:
                content += f"\n---\n\n*Assessed confidence: {confidence}.*\n"
            content += (
                f"\n*Generated by iris-ng from cross-case IOC correlation cluster "
                f"`{cluster_id}` spanning {len(cluster.get('case_ids') or [])} cases. "
                f"Organisation names are redacted.*\n"
            )

            try:
                client.add_event_report(event_id, {
                    "name": report_name,
                    "content": content,
                    "distribution": 5,  # inherit from the event
                })
                event_reports_created += 1
            except MispSyncClientError as exc:
                self.log.warning(
                    f"Could not add the campaign analysis report to event {event_id}: {exc}"
                )

        # --- indicators
        attributes_created = 0
        notes_attached = 0
        tags_applied = 0
        failures: list[str] = []

        push_tags = bool(self.mod_config.get("misp_cluster_tag_sync_enabled", True))
        push_notes = bool(self.mod_config.get("misp_cluster_notes_enabled", True))

        for rec in ioc_records:
            value = (rec.get("value") or "").strip()
            misp_type = (rec.get("misp_type") or "").strip()
            if not value or not misp_type:
                continue

            problem = self._shape_problem(misp_type, value)
            if problem is not None:
                self.log.warning(f"Skipping {value}: {problem}")
                failures.append(f"{value}: {problem}")
                continue

            try:
                attr_resp = client.add_attribute(
                    event_id,
                    self._attribute_payload(
                        value, misp_type,
                        self._build_attribute_comment(rec.get("descriptions"), scrub),
                    ),
                )
            except MispSyncClientError as exc:
                failures.append(f"{value}: {exc}")
                continue

            attributes_created += 1
            attr = attr_resp.get("Attribute", attr_resp) if isinstance(attr_resp, dict) else {}
            try:
                attr_id = int(attr["id"])
            except (KeyError, TypeError, ValueError):
                attr_id = None

            if attr_id is not None and push_tags:
                for tag in rec.get("tags") or []:
                    self._tag_attribute(client, attr_id, tag)
                    tags_applied += 1

            # Linked analyst notes attach to this indicator as MISP Notes,
            # keyed on the attribute UUID (not its numeric id).
            attr_uuid = attr.get("uuid")
            if push_notes and rec.get("notes"):
                if attr_uuid:
                    added, note_failures = self._attach_notes(
                        client, attr_uuid, rec["notes"], scrub
                    )
                    notes_attached += added
                    failures.extend(note_failures)
                else:
                    failures.append(f"{value}: MISP returned no attribute UUID, notes not attached")

        if possible_unredacted:
            self.log.warning(
                f"Cluster {cluster_id} -> MISP event {event_id}: possible unredacted "
                f"entity names published: {sorted(possible_unredacted)}. Add them to "
                f"the module's 'Additional terms to redact' setting and re-push."
            )

        self.log.info(
            f"Cluster {cluster_id} pushed to MISP event {event_id}: "
            f"{attributes_created} attributes, {notes_attached} notes, "
            f"{tags_applied} attribute tags, {len(failures)} failures"
        )

        return {
            "cluster_id": cluster_id,
            "misp_event_id": event_id,
            "misp_event_uuid": event_uuid,
            "misp_event_url": f"{self.mod_config.get('misp_cluster_url', '').rstrip('/')}/events/view/{event_id}",
            "attributes_created": attributes_created,
            "notes_attached": notes_attached,
            "event_reports_created": event_reports_created,
            "attribute_tags_applied": tags_applied,
            "redactions_applied": redactions,
            "possible_unredacted_names": sorted(possible_unredacted),
            "redaction_enabled": redact_on,
            "failures": failures,
        }


class IrisMISPClusterInterface(IrisModuleInterface):
    """Interface between IRIS and the MISP cluster publisher.

    Registers NO hooks — the push is button-driven from the Correlation tab.
    The class exists so the module appears in /manage/modules with a
    configuration UI, the same way IrisMISPSync does.
    """

    name = "IrisMISPClusterInterface"
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
        # Intentionally empty: publishing is an explicit analyst action.
        self.module_id = module_id

    def hooks_handler(self, hook_name: str, hook_ui_name: str, data: Any):
        # No hooks are registered, so this should never fire.
        self.log.warning(f"IrisMISPCluster received unexpected hook {hook_name}")
        return InterfaceStatus.I2Success(data=data)
