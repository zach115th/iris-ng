"""
STIX 2.1 bundle builder for iris-ng IOC correlation clusters.

Produces a self-contained bundle containing:
  identity           — iris-ng as the producing system
  marking-definition — TLP:GREEN (all correlatable IOCs are green/clear)
  campaign           — the correlation cluster (1 per export)
  indicator(s)       — one per shared IOC value, with STIX-pattern mapping
  relationship(s)    — indicator --indicates--> campaign

Hand-rolled JSON — no stix2 library required, which avoids a pip dependency
and an image rebuild.  UUIDs are deterministic (UUID v5, STIX 2.1 namespace)
so the same logical entity always produces the same STIX id across calls.

TLP note: the correlation engine already filters to TLP:GREEN/CLEAR only.
We mark all exported indicators and relationships TLP:GREEN.

Usage:
    from app.iris_engine.stix_export import build_cluster_stix_bundle
    bundle = build_cluster_stix_bundle(cluster, pairs_for_cluster, case_meta)
    # bundle is a plain dict — json.dumps(bundle) for the wire format
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

# ---------------------------------------------------------------------------
# STIX 2.1 constants
# ---------------------------------------------------------------------------

# UUID namespace for deterministic STIX ids (OASIS STIX 2.1 spec, Appendix B)
_STIX_NS = uuid.UUID("00abedb4-aa42-466c-9c01-fed23315a9b7")

# TLP:GREEN well-known STIX 2.1 marking-definition ID (OASIS STIX 2.0/2.1 Annex F)
# Widely recognised by MISP, OpenCTI, and other STIX-consuming tools.
_TLP_GREEN_ID = "marking-definition--34098fce-860f-48ae-8e50-ebd3cc5e41da"


def _sid(type_name: str, key: str) -> str:
    """Return a deterministic STIX id: '<type>--<uuid5(STIX_NS, key)>'."""
    return f"{type_name}--{uuid.uuid5(_STIX_NS, key)}"


def _ts(dt: datetime) -> str:
    """Format a datetime as STIX 2.1 timestamp (UTC, millisecond precision)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


# ---------------------------------------------------------------------------
# Constant STIX objects included in every export
# ---------------------------------------------------------------------------

_IRIS_NG_IDENTITY_ID = _sid("identity", "iris-ng:system")

_IDENTITY_OBJECT: dict[str, Any] = {
    "type": "identity",
    "spec_version": "2.1",
    "id": _IRIS_NG_IDENTITY_ID,
    "created": "2026-01-01T00:00:00.000Z",
    "modified": "2026-01-01T00:00:00.000Z",
    "name": "IRIS-NG",
    "identity_class": "system",
    "description": (
        "IRIS-NG — DFIR case management platform "
        "(fork of DFIR-IRIS v2.5.0-beta.1)"
    ),
}

_TLP_GREEN_OBJECT: dict[str, Any] = {
    "type": "marking-definition",
    "spec_version": "2.1",
    "id": _TLP_GREEN_ID,
    "created": "2017-01-20T00:00:00.000Z",
    "definition_type": "tlp",
    "name": "TLP:GREEN",
    "definition": {"tlp": "green"},
}


# ---------------------------------------------------------------------------
# IOC type → STIX 2.1 pattern
# ---------------------------------------------------------------------------

def _hash_prop(hash_type: str) -> str:
    """Map an iris-ng hash slug to the STIX file:hashes property name."""
    return {
        "md5": "MD5",
        "sha1": "SHA-1",
        "sha256": "SHA-256",
        "sha512": "SHA-512",
        "sha224": "SHA-224",
        "ssdeep": "ssdeep",
        "imphash": "IMPHASH",
        "tlsh": "TLSH",
    }.get(hash_type.lower(), hash_type.upper())


def _esc(value: str) -> str:
    """Escape a string for safe embedding inside a STIX pattern single-quoted literal."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _ioc_pattern(ioc_type: str, ioc_value: str) -> tuple[str, str]:
    """
    Map an iris-ng IOC (type slug, value) to a STIX 2.1 pattern string.

    Returns:
        (pattern, note) where note is an empty string for standard patterns
        or a short human-readable warning when a custom fallback was used.
    """
    v = _esc(ioc_value)
    t = ioc_type.lower()

    # --- IP addresses ---
    if t in ("ip-dst", "ip-src", "ip-any"):
        obj = "ipv6-addr" if ":" in ioc_value else "ipv4-addr"
        return f"[{obj}:value = '{v}']", ""

    # IP|port composite — take the IP part only
    if t in ("ip-dst|port", "ip-src|port"):
        ip_part = ioc_value.split("|")[0] if "|" in ioc_value else ioc_value
        obj = "ipv6-addr" if ":" in ip_part else "ipv4-addr"
        return f"[{obj}:value = '{_esc(ip_part)}']", ""

    # --- Domain / hostname ---
    if t in ("domain", "hostname"):
        return f"[domain-name:value = '{v}']", ""

    # domain|ip composite — take domain
    if t == "domain|ip":
        d = ioc_value.split("|")[0] if "|" in ioc_value else ioc_value
        return f"[domain-name:value = '{_esc(d)}']", ""

    # --- URL / URI ---
    if t in ("url", "uri"):
        return f"[url:value = '{v}']", ""

    # --- File hashes ---
    if t in ("md5", "sha1", "sha256", "sha512", "sha224", "ssdeep", "imphash", "tlsh"):
        return f"[file:hashes.'{_hash_prop(t)}' = '{v}']", ""

    # --- Filename ---
    if t == "filename":
        return f"[file:name = '{v}']", ""

    # filename|hash composites (e.g. filename|md5)
    if t.startswith("filename|"):
        hash_type = t.split("|", 1)[1]
        if "|" in ioc_value:
            fname, hval = ioc_value.split("|", 1)
            prop = _hash_prop(hash_type)
            return (
                f"[file:name = '{_esc(fname)}'"
                f" AND file:hashes.'{prop}' = '{_esc(hval)}']",
                "",
            )
        return f"[file:name = '{v}']", ""

    # --- Email ---
    if t in ("email-src", "email-dst", "email"):
        return f"[email-addr:value = '{v}']", ""

    if t == "email-subject":
        return f"[email-message:subject = '{v}']", ""

    # --- Windows registry ---
    if t == "regkey":
        return f"[windows-registry-key:key = '{v}']", ""

    if t.startswith("regkey|"):
        if "|" in ioc_value:
            key, rval = ioc_value.split("|", 1)
            return (
                f"[windows-registry-key:key = '{_esc(key)}'"
                f" AND windows-registry-key:values[0].data = '{_esc(rval)}']",
                "",
            )
        return f"[windows-registry-key:key = '{v}']", ""

    # --- Mutex ---
    if t == "mutex":
        return f"[mutex:name = '{v}']", ""

    # --- User-Agent ---
    if t == "user-agent":
        return (
            "[network-traffic:extensions.'http-request-ext'"
            f".request_header.'User-Agent' = '{v}']",
            "",
        )

    # --- AS number ---
    if t == "as":
        try:
            num = int(ioc_value.lstrip("AS").strip())
            return f"[autonomous-system:number = {num}]", ""
        except ValueError:
            pass

    # --- Port ---
    if t == "port":
        try:
            return f"[network-traffic:dst_port = {int(ioc_value)}]", ""
        except ValueError:
            pass

    # Fallback: custom STIX 2.1 SCO (x- prefix = custom object, valid per spec)
    note = f"No standard STIX 2.1 SCO pattern for type '{ioc_type}' — custom x-iris-ng-indicator used"
    return (
        f"[x-iris-ng-indicator:ioc_type = '{ioc_type}'"
        f" AND x-iris-ng-indicator:value = '{v}']",
        note,
    )


# ---------------------------------------------------------------------------
# Bundle builder
# ---------------------------------------------------------------------------

def _earliest_open_date(case_ids: list[int], case_meta: dict) -> datetime:
    """
    Return the earliest case open_date from case_meta as a UTC datetime.
    Falls back to utcnow when no open_date is available.
    """
    dates = []
    for cid in case_ids:
        # case_meta keys may be int or str depending on JSON serialization path
        meta = case_meta.get(cid) or case_meta.get(str(cid))
        if not meta:
            continue
        raw = meta.get("open_date")
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(str(raw))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dates.append(dt)
        except (ValueError, TypeError):
            pass
    return min(dates) if dates else datetime.now(timezone.utc)


def build_cluster_stix_bundle(
    cluster: dict,
    pairs_for_cluster: list[dict],
    case_meta: dict,
    now_utc: Optional[datetime] = None,
    narrative: Optional[dict] = None,
) -> dict:
    """
    Build a STIX 2.1 bundle for one correlation cluster.

    Args:
        cluster:
            Cluster dict from build_correlation_report() — must contain
            cluster_id, case_ids, shared_ioc_count, suggested_campaign_tag.
            Optional: ioc_confidence (float 0-1, added by decay scorer).
        pairs_for_cluster:
            Full pair dicts from build_correlation_report()["pairs"] already
            filtered to this cluster's cases.  Each pair must have at least:
            ioc_value, ioc_type_name, case_ids.
        case_meta:
            Dict of {case_id: {name, client, open_date, ...}} as returned by
            build_correlation_report().
        now_utc:
            Timestamp to stamp created/modified fields.  Uses utcnow if None.
        narrative:
            Optional cached AI narrative dict from CaseAiArtifact.  When
            present, ``suggested_name`` becomes the campaign name (machine
            slug moves to ``aliases``) and ``narrative`` text becomes the
            campaign description.  Silently ignored if None or malformed.

    Returns:
        A plain Python dict representing a valid STIX 2.1 bundle.
        Serialise with json.dumps(bundle, indent=2, ensure_ascii=False).
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    now_str = _ts(now_utc)
    cluster_id = cluster["cluster_id"]
    case_ids = cluster["case_ids"]
    campaign_tag = cluster.get("suggested_campaign_tag", f"campaign:cluster-{cluster_id}")

    # earliest open_date → valid_from for all indicators
    valid_from_str = _ts(_earliest_open_date(case_ids, case_meta))

    campaign_id = _sid("campaign", f"iris-ng:cluster:{cluster_id}")
    bundle_id = _sid("bundle", f"iris-ng:bundle:cluster:{cluster_id}")

    # --- campaign ---
    base_description = (
        f"IOC correlation cluster detected by IRIS-NG. "
        f"{len(case_ids)} correlated case(s), "
        f"{len(pairs_for_cluster)} shared IOC(s)."
    )

    campaign_name = campaign_tag
    campaign_aliases: list[str] = []
    campaign_description = base_description

    # Enrich from cached AI narrative when available
    if narrative and isinstance(narrative, dict):
        ai_name = (narrative.get("suggested_name") or "").strip()
        ai_prose = (narrative.get("narrative") or "").strip()
        if ai_name and ai_name != campaign_tag:
            campaign_name = ai_name
            campaign_aliases = [campaign_tag]
        if ai_prose:
            campaign_description = f"{base_description}\n\n{ai_prose}"

    campaign_obj: dict[str, Any] = {
        "type": "campaign",
        "spec_version": "2.1",
        "id": campaign_id,
        "created": now_str,
        "modified": now_str,
        "created_by_ref": _IRIS_NG_IDENTITY_ID,
        "name": campaign_name,
        "description": campaign_description,
        "object_marking_refs": [_TLP_GREEN_ID],
    }
    if campaign_aliases:
        campaign_obj["aliases"] = campaign_aliases

    # ioc_confidence (float 0-1) → STIX confidence (int 0-100)
    raw_conf = cluster.get("ioc_confidence")
    if raw_conf is not None:
        try:
            campaign_obj["confidence"] = max(0, min(100, int(round(float(raw_conf) * 100))))
        except (TypeError, ValueError):
            pass

    # --- indicators + relationships ---
    indicators: list[dict] = []
    relationships: list[dict] = []

    for pair in pairs_for_cluster:
        ioc_value = pair["ioc_value"]
        ioc_type_name = pair.get("ioc_type_name", "unknown")
        case_count = pair.get("case_count", len(pair.get("case_ids", [])))

        pattern, pattern_note = _ioc_pattern(ioc_type_name, ioc_value)
        indicator_id = _sid("indicator", f"iris-ng:ioc:{ioc_type_name}:{ioc_value}")

        description = (
            f"Shared {ioc_type_name} indicator observed in "
            f"{case_count} correlated case(s)."
        )
        if pattern_note:
            description += f" Note: {pattern_note}"

        indicator_obj: dict[str, Any] = {
            "type": "indicator",
            "spec_version": "2.1",
            "id": indicator_id,
            "created": now_str,
            "modified": now_str,
            "created_by_ref": _IRIS_NG_IDENTITY_ID,
            "name": ioc_value,
            "description": description,
            "indicator_types": ["malicious-activity"],
            "pattern": pattern,
            "pattern_type": "stix",
            "valid_from": valid_from_str,
            "labels": [ioc_type_name],
            "object_marking_refs": [_TLP_GREEN_ID],
        }
        indicators.append(indicator_obj)

        rel_id = _sid("relationship", f"iris-ng:indicates:{indicator_id}:{campaign_id}")
        relationships.append({
            "type": "relationship",
            "spec_version": "2.1",
            "id": rel_id,
            "created": now_str,
            "modified": now_str,
            "created_by_ref": _IRIS_NG_IDENTITY_ID,
            "relationship_type": "indicates",
            "source_ref": indicator_id,
            "target_ref": campaign_id,
            "object_marking_refs": [_TLP_GREEN_ID],
        })

    return {
        "type": "bundle",
        "id": bundle_id,
        "spec_version": "2.1",
        "objects": (
            [_IDENTITY_OBJECT, _TLP_GREEN_OBJECT, campaign_obj]
            + indicators
            + relationships
        ),
    }
