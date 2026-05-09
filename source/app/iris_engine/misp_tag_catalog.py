#  IRIS Source Code
#
#  In-process catalog of MISP taxonomy + galaxy tags, sourced from the
#  bundled snapshot in source/app/resources/misp_{taxonomies,galaxies}/.
#  Powers the /api/v2/misp-tags autocomplete endpoint and the soft-mapping
#  table's "MISP tag" picker.
#
#  Refresh the snapshot with: python scripts/download_misp_tag_bundles.py
#
#  Why both kinds in one catalog: analysts pick a taxonomy or a galaxy from
#  the same tag-input typeahead and don't care about the structural
#  difference — they care about "what's the right tag for this thing?".
#  Per docs/22-misp-galaxies.md §4a the autocomplete records carry a `kind`
#  discriminator so the UI can render a small chip (`taxonomy` vs `galaxy`).

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Iterator


# Bundled snapshot lives next to the existing misp.attribute_types.json and
# misp.classification.taxonomy.json — same `source/app/resources/` parent.
_RESOURCES_ROOT = Path(__file__).resolve().parent.parent / "resources"
_TAX_DIR = _RESOURCES_ROOT / "misp_taxonomies"
_GAL_DIR = _RESOURCES_ROOT / "misp_galaxies"


# Shared catalog cache. Built lazily on first call to `search()` so import
# time stays fast and we don't crash app boot if a bundle file is malformed.
_CATALOG: list[dict[str, Any]] | None = None
_LOCK = threading.Lock()


def _flatten_taxonomy(tax: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield one record per machine-tag the taxonomy can produce.

    MISP taxonomies have two shapes per predicate:
    - bare predicate (no `values` block) -> `<ns>:<pred>` (e.g. `tlp:red`)
    - predicate with `entry[]` values    -> `<ns>:<pred>="<value>"`
    """
    ns = (tax.get("namespace") or "").strip()
    if not ns:
        return

    predicates_by_value: dict[str, dict[str, Any]] = {}
    for p in tax.get("predicates") or []:
        v = p.get("value")
        if v:
            predicates_by_value[v] = p

    entries_by_predicate: dict[str, list[dict[str, Any]]] = {}
    for block in tax.get("values") or []:
        pred = block.get("predicate")
        if pred:
            entries_by_predicate[pred] = block.get("entry") or []

    for pred_value, pred_meta in predicates_by_value.items():
        pred_expanded = pred_meta.get("expanded") or pred_value
        pred_desc = pred_meta.get("description") or ""
        entries = entries_by_predicate.get(pred_value)
        if entries:
            for entry in entries:
                ev = entry.get("value")
                if not ev:
                    continue
                yield {
                    "tag": f'{ns}:{pred_value}="{ev}"',
                    "namespace": ns,
                    "kind": "taxonomy",
                    "expanded": entry.get("expanded") or ev,
                    "description": entry.get("description") or pred_desc,
                    "synonyms": [],
                }
        else:
            yield {
                "tag": f"{ns}:{pred_value}",
                "namespace": ns,
                "kind": "taxonomy",
                "expanded": pred_expanded,
                "description": pred_desc,
                "synonyms": [],
            }


def _flatten_galaxy(galaxy: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield one record per cluster value in a galaxy.

    All bundled galaxies use the `misp-galaxy` namespace. If we ever bundle
    a galaxy that uses a different namespace (some MITRE / Tidal clusters),
    extend this to honor the upstream `namespace` field on the galaxy file
    instead of hard-coding `misp-galaxy`.
    """
    typ = (galaxy.get("type") or "").strip()
    if not typ:
        return

    ns = "misp-galaxy"
    for v in galaxy.get("values") or []:
        val = v.get("value")
        if not val:
            continue
        meta = v.get("meta") or {}
        synonyms = list(meta.get("synonyms") or [])
        yield {
            "tag": f'{ns}:{typ}="{val}"',
            "namespace": ns,
            "galaxy_type": typ,
            "kind": "galaxy",
            "expanded": val,
            "description": v.get("description") or "",
            "synonyms": synonyms,
            "uuid": v.get("uuid"),
            "country": meta.get("country"),
        }


def _build_catalog() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    if _TAX_DIR.is_dir():
        for path in sorted(_TAX_DIR.glob("*.json")):
            try:
                tax = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            out.extend(_flatten_taxonomy(tax))

    if _GAL_DIR.is_dir():
        for path in sorted(_GAL_DIR.glob("*.json")):
            try:
                gal = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            out.extend(_flatten_galaxy(gal))

    return out


def _ensure_catalog() -> list[dict[str, Any]]:
    global _CATALOG
    if _CATALOG is not None:
        return _CATALOG
    with _LOCK:
        if _CATALOG is None:
            _CATALOG = _build_catalog()
    return _CATALOG


def reload_catalog() -> int:
    """Reset and rebuild the catalog. Returns the new count.

    Useful after running scripts/download_misp_tag_bundles.py without
    restarting the app.
    """
    global _CATALOG
    with _LOCK:
        _CATALOG = _build_catalog()
        return len(_CATALOG)


def catalog_size() -> int:
    return len(_ensure_catalog())


def _score(record: dict[str, Any], q_lower: str) -> tuple[int, str]:
    """Return (rank, secondary_sort_key). Lower rank == better match.

    Ranks:
        0 — tag starts with q
        1 — tag contains q
        2 — expanded starts with q
        3 — expanded contains q
        4 — synonym matches (galaxies only)
    """
    tag_l = record["tag"].lower()
    exp_l = record["expanded"].lower()
    if tag_l.startswith(q_lower):
        return (0, tag_l)
    if q_lower in tag_l:
        return (1, tag_l)
    if exp_l.startswith(q_lower):
        return (2, exp_l)
    if q_lower in exp_l:
        return (3, exp_l)
    for syn in record.get("synonyms") or []:
        if q_lower in syn.lower():
            return (4, syn.lower())
    return (99, tag_l)


def search(
    query: str,
    *,
    limit: int = 20,
    kinds: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Return up to `limit` catalog records matching `query`.

    Args:
        query: free-text. Empty/whitespace returns the first `limit` records
            (alphabetical-ish — useful for "show all tags from this namespace").
        limit: max records returned.
        kinds: optional tuple of {"taxonomy", "galaxy"} to filter on.

    Each returned record carries `tag`, `namespace`, `kind`, `expanded`,
    `description`, `synonyms`, plus `galaxy_type`/`uuid`/`country` for
    galaxy records. The result also includes a `matched_synonym` field
    when the rank-4 path fired, so the UI can show the user "matched on
    synonym 'Fancy Bear' -> APT28".
    """
    cat = _ensure_catalog()
    q = (query or "").strip().lower()

    if kinds:
        candidates = [r for r in cat if r["kind"] in kinds]
    else:
        candidates = cat

    if not q:
        # No query: return the first `limit` records as a sane "browse" fallback.
        return [_strip_for_response(r) for r in candidates[:limit]]

    scored: list[tuple[tuple[int, str], dict[str, Any]]] = []
    for record in candidates:
        rank, key = _score(record, q)
        if rank < 99:
            scored.append(((rank, key), record))

    scored.sort(key=lambda item: item[0])
    return [_attach_match_hint(r, q) for _, r in scored[:limit]]


def _attach_match_hint(record: dict[str, Any], q_lower: str) -> dict[str, Any]:
    out = _strip_for_response(record)
    if record.get("synonyms"):
        for syn in record["synonyms"]:
            if q_lower in syn.lower():
                out["matched_synonym"] = syn
                break
    return out


def _strip_for_response(record: dict[str, Any]) -> dict[str, Any]:
    """Trim internal fields. Currently a no-op — kept for forward compat."""
    return dict(record)
