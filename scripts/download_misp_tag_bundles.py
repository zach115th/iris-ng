#!/usr/bin/env python3
"""Download the FULL MISP taxonomies + galaxies snapshot into the iris-ng
resources bundle. One-shot — re-run when you want to refresh the snapshot.

Output:
  source/app/resources/misp_taxonomies/<namespace>.json   (machinetag.json from misp-taxonomies)
  source/app/resources/misp_galaxies/<type>.json          (clusters/<type>.json from misp-galaxy)

Discovers what to download via the GitHub contents API (no hard-coded list)
so new upstream taxonomies / galaxies land automatically on re-run. Stdlib
only — no `requests` dependency. Run from anywhere; paths resolve relative
to this script's location.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
BUNDLE_ROOT = REPO_ROOT / "source" / "app" / "resources"
TAX_DIR = BUNDLE_ROOT / "misp_taxonomies"
GAL_DIR = BUNDLE_ROOT / "misp_galaxies"


# Top-level GitHub contents endpoints used to discover what to download.
TAX_LIST_URL = "https://api.github.com/repos/MISP/misp-taxonomies/contents/"
GAL_LIST_URL = "https://api.github.com/repos/MISP/misp-galaxy/contents/clusters"

TAX_URL = "https://raw.githubusercontent.com/MISP/misp-taxonomies/main/{ns}/machinetag.json"
GAL_URL = "https://raw.githubusercontent.com/MISP/misp-galaxy/main/clusters/{type}.json"

# Galaxies we deliberately skip even on a "full" pull — Malpedia is huge
# (~5 MB / 3,683 entries of malware-sample metadata) and not relevant unless
# we add malware-sample tagging surfaces. Re-add by removing from this set.
SKIP_GALAXIES: set[str] = set()


def fetch(url: str, *, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "iris-ng-bundle-downloader/2.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def list_taxonomies() -> list[str]:
    """Return every taxonomy namespace present in misp-taxonomies main."""
    raw = fetch(TAX_LIST_URL)
    data = json.loads(raw)
    return sorted([entry["name"] for entry in data if entry.get("type") == "dir"])


def list_galaxies() -> list[str]:
    """Return every cluster filename (without .json) present in misp-galaxy/clusters."""
    raw = fetch(GAL_LIST_URL)
    data = json.loads(raw)
    out = []
    for entry in data:
        if entry.get("type") != "file":
            continue
        name = entry.get("name", "")
        if not name.endswith(".json"):
            continue
        out.append(name[:-5])
    return sorted(n for n in out if n not in SKIP_GALAXIES)


def fetch(url: str, *, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "iris-ng-bundle-downloader/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def download_one(url: str, dest: Path, label: str) -> bool:
    try:
        raw = fetch(url)
        # Validate it parses as JSON before writing — protects against partial /
        # HTML 404 pages slipping into the bundle.
        json.loads(raw)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError) as exc:
        print(f"    {label}: FAIL — {exc}", file=sys.stderr)
        return False

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    print(f"    {label}: ok ({dest.stat().st_size:,} bytes)")
    return True


def main() -> int:
    TAX_DIR.mkdir(parents=True, exist_ok=True)
    GAL_DIR.mkdir(parents=True, exist_ok=True)

    print("discovering upstream catalogs...")
    taxonomies = list_taxonomies()
    galaxies = list_galaxies()
    print(f"  upstream lists {len(taxonomies)} taxonomies, {len(galaxies)} galaxy clusters")

    print(f"taxonomies -> {TAX_DIR}")
    tax_ok = 0
    for ns in taxonomies:
        if download_one(TAX_URL.format(ns=ns), TAX_DIR / f"{ns}.json", ns):
            tax_ok += 1

    print(f"galaxies -> {GAL_DIR}")
    gal_ok = 0
    for typ in galaxies:
        if download_one(GAL_URL.format(type=typ), GAL_DIR / f"{typ}.json", typ):
            gal_ok += 1

    print()
    print(f"taxonomies: {tax_ok}/{len(taxonomies)}, galaxies: {gal_ok}/{len(galaxies)}")
    return 0 if tax_ok == len(taxonomies) and gal_ok == len(galaxies) else 1


if __name__ == "__main__":
    sys.exit(main())
