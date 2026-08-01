#  IRIS Source Code
#
#  Thin urllib-based client for Pinecone Inference + Data plane. No new pip
#  deps — same pattern as `iris_misp_sync_module/ai_type_resolver.py`.
#
#  Two endpoints used:
#  - POST https://api.pinecone.io/embed              (Pinecone-hosted embeddings)
#  - POST https://<index-host>/query                 (semantic search)
#  - GET  https://<index-host>/vectors/fetch         (fetch-by-id)
#
#  The index hosts come straight from `Config.PINECONE_*_HOST`. The embedding
#  model defaults to `llama-text-embed-v2` (the model used to populate the
#  user's existing indexes — must match for queries to score correctly).
#
#  Graceful degradation: every helper returns None / empty list when Pinecone
#  isn't configured (PINECONE_API_KEY empty) or when a network/HTTP error
#  occurs. Callers can treat "no Pinecone" as "no RAG context" without
#  branching on configuration state.

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from app import app
from flask import current_app


PINECONE_INFERENCE_URL = "https://api.pinecone.io/embed"
PINECONE_INFERENCE_API_VERSION = "2025-10"
PINECONE_DATA_API_VERSION = "2026-04"

DEFAULT_TIMEOUT_SECONDS = 15.0


class PineconeClientError(Exception):
    """Raised on transport / HTTP errors from Pinecone calls."""


def _read_settings_row() -> dict[str, Any]:
    """Pull Pinecone config from the ServerSettings row.

    Returns a dict with `enabled` (bool|None) and the 5 string fields stripped
    to '' when missing/null. Any failure (no row yet, pre-migration boot)
    returns a permissive empty shape so callers fall back to env vars.
    """
    try:
        from app.models.models import ServerSettings
        row = ServerSettings.query.first()
    except Exception:
        return {"enabled": None, "api_key": "", "embed_model": "", "sigma_host": "", "attack_host": "", "atomic_host": ""}

    if row is None:
        return {"enabled": None, "api_key": "", "embed_model": "", "sigma_host": "", "attack_host": "", "atomic_host": ""}

    return {
        "enabled": getattr(row, "pinecone_enabled", None),
        "api_key": (getattr(row, "pinecone_api_key", None) or "").strip(),
        "embed_model": (getattr(row, "pinecone_embed_model", None) or "").strip(),
        "sigma_host": (getattr(row, "pinecone_sigma_host", None) or "").strip(),
        "attack_host": (getattr(row, "pinecone_attack_host", None) or "").strip(),
        "atomic_host": (getattr(row, "pinecone_atomic_host", None) or "").strip(),
    }


def _config() -> dict[str, str]:
    """Read the Pinecone settings — DB row takes precedence, env vars fall back.

    Mirrors the resolution order used by `openai_client.build_default_client`:
      1. ServerSettings table (admin-editable via /manage/settings)
      2. app.config (env vars at startup — bootstrap fallback)

    `enabled` is propagated through so `is_configured()` can short-circuit when
    the admin has explicitly turned RAG off.
    """
    db_row = _read_settings_row()
    cfg = current_app.config if current_app else app.config

    api_key = db_row["api_key"] or (cfg.get("PINECONE_API_KEY") or "").strip()
    embed_model = db_row["embed_model"] or (cfg.get("PINECONE_EMBED_MODEL") or "llama-text-embed-v2").strip()
    sigma_host = db_row["sigma_host"] or (cfg.get("PINECONE_SIGMA_HOST") or "").strip()
    attack_host = db_row["attack_host"] or (cfg.get("PINECONE_ATTACK_HOST") or "").strip()
    atomic_host = db_row["atomic_host"] or (cfg.get("PINECONE_ATOMIC_HOST") or "").strip()

    # When the row is silent (None / pre-migration), infer enabled from
    # presence of key + a host so env-only deployments keep working unchanged.
    enabled = db_row["enabled"]
    if enabled is None:
        enabled = bool(api_key and (sigma_host or attack_host or atomic_host))

    return {
        "enabled": enabled,
        "api_key": api_key,
        "embed_model": embed_model,
        "sigma_host": sigma_host,
        "attack_host": attack_host,
        "atomic_host": atomic_host,
    }


def is_configured() -> bool:
    """Cheap check used by callers to decide whether to attempt RAG.

    Returns True only when the admin toggle is on AND the API key plus at
    least one index host are set. Per-feature helpers (e.g. sigma_grounding)
    additionally check their specific host.
    """
    cfg = _config()
    if not cfg["enabled"]:
        return False
    return bool(cfg["api_key"]) and bool(cfg["sigma_host"] or cfg["attack_host"] or cfg["atomic_host"])


def _post_json(url: str, headers: dict[str, str], body: dict[str, Any], timeout: float) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        raise PineconeClientError(f"HTTP {e.code} from {url}: {body_text}") from e
    except urllib.error.URLError as e:
        raise PineconeClientError(f"URLError calling {url}: {e}") from e
    except (TimeoutError, json.JSONDecodeError) as e:
        raise PineconeClientError(f"{type(e).__name__} calling {url}: {e}") from e


def _get_json(url: str, headers: dict[str, str], timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        raise PineconeClientError(f"HTTP {e.code} from {url}: {body_text}") from e
    except urllib.error.URLError as e:
        raise PineconeClientError(f"URLError calling {url}: {e}") from e


def embed_query(text: str, *, model: str | None = None, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> list[float] | None:
    """Embed a single text snippet via Pinecone's hosted inference API.

    Matches the n8n `Pinecone Retrieval Gateway` workflow: model defaults to
    `llama-text-embed-v2`, `input_type=query`, `truncate=END`. Returns the
    raw vector or None on any error (caller can decide to fall back).
    """
    cfg = _config()
    if not cfg["api_key"]:
        return None
    text = (text or "").strip()
    if not text:
        return None
    body = {
        "model": model or cfg["embed_model"],
        "parameters": {"input_type": "query", "truncate": "END"},
        "inputs": [{"text": text}],
    }
    headers = {
        "Api-Key": cfg["api_key"],
        "X-Pinecone-Api-Version": PINECONE_INFERENCE_API_VERSION,
        "Content-Type": "application/json",
    }
    try:
        resp = _post_json(PINECONE_INFERENCE_URL, headers, body, timeout)
    except PineconeClientError as exc:
        app.logger.warning(f"Pinecone embed failed: {exc}")
        return None
    try:
        values = resp["data"][0]["values"]
    except (KeyError, IndexError, TypeError) as exc:
        app.logger.warning(f"Pinecone embed: malformed response: {exc}")
        return None
    if not isinstance(values, list) or not values:
        return None
    return values


def query_index(
    *,
    host: str,
    vector: list[float],
    top_k: int = 5,
    namespace: str = "",
    metadata_filter: dict[str, Any] | None = None,
    include_metadata: bool = True,
    include_values: bool = False,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    """Run a semantic search on a single Pinecone index.

    Returns the list of `matches` (id / score / metadata / optional values).
    Returns [] on any error so callers can treat "no RAG context" as a
    benign empty input.
    """
    cfg = _config()
    if not cfg["api_key"] or not host:
        return []
    body: dict[str, Any] = {
        "topK": int(top_k),
        "vector": vector,
        "includeMetadata": bool(include_metadata),
        "includeValues": bool(include_values),
    }
    if namespace:
        body["namespace"] = namespace
    if metadata_filter:
        body["filter"] = metadata_filter
    headers = {
        "Api-Key": cfg["api_key"],
        "X-Pinecone-Api-Version": PINECONE_DATA_API_VERSION,
        "Content-Type": "application/json",
    }
    url = f"https://{host}/query"
    try:
        resp = _post_json(url, headers, body, timeout)
    except PineconeClientError as exc:
        app.logger.warning(f"Pinecone query failed ({host}): {exc}")
        return []
    matches = resp.get("matches")
    return matches if isinstance(matches, list) else []


def fetch_by_id(
    *,
    host: str,
    ids: list[str],
    namespace: str = "",
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, dict[str, Any]]:
    """Fetch one or more vectors by id. Returns {id: {metadata, values?}, ...}."""
    cfg = _config()
    if not cfg["api_key"] or not host or not ids:
        return {}
    parts = [f"ids={urllib.request.quote(id_)}" for id_ in ids if id_]
    if namespace:
        parts.append(f"namespace={urllib.request.quote(namespace)}")
    url = f"https://{host}/vectors/fetch?{'&'.join(parts)}"
    headers = {
        "Api-Key": cfg["api_key"],
        "X-Pinecone-Api-Version": PINECONE_DATA_API_VERSION,
    }
    try:
        resp = _get_json(url, headers, timeout)
    except PineconeClientError as exc:
        app.logger.warning(f"Pinecone fetch failed ({host}): {exc}")
        return {}
    vectors = resp.get("vectors")
    return vectors if isinstance(vectors, dict) else {}


def search_text(
    *,
    host: str,
    text: str,
    top_k: int = 5,
    namespace: str = "",
    metadata_filter: dict[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    """Convenience: embed + query in one call. Most callers want this.

    Returns matches (id / score / metadata) or [] on any failure.
    """
    if not text or not text.strip():
        return []
    vector = embed_query(text, timeout=timeout)
    if vector is None:
        return []
    return query_index(
        host=host,
        vector=vector,
        top_k=top_k,
        namespace=namespace,
        metadata_filter=metadata_filter,
        timeout=timeout,
    )
