#!/usr/bin/env python3
#
#  IRIS VT Module - VirusTotal API v3 client
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
from datetime import datetime, timezone
from urllib.parse import quote

import requests


class VT3Error(Exception):
    """Raised on any VT API v3 failure - carries the HTTP status and the
    API's own error message so callers can log something actionable."""
    def __init__(self, status, message):
        self.status = status
        self.message = message
        super().__init__(f"VT API v3 error {status}: {message}")


class VT3Client:
    """Minimal VirusTotal API v3 client over requests.

    v3 has no public/private client split - quota is enforced server-side
    by the key, so the old `vt_key_is_premium` distinction is gone.
    """

    BASE = "https://www.virustotal.com/api/v3"

    def __init__(self, api_key, proxies=None, timeout=30):
        self.api_key = api_key
        self.proxies = proxies or {}
        self.timeout = timeout

    def _get(self, path, params=None):
        r = requests.get(self.BASE + path,
                         headers={"x-apikey": self.api_key,
                                  "Accept": "application/json"},
                         params=params,
                         proxies=self.proxies,
                         timeout=self.timeout)
        if r.status_code == 200:
            return r.json()
        try:
            message = r.json().get("error", {}).get("message", "")
        except Exception:
            message = (r.text or "")[:200]
        raise VT3Error(r.status_code, message)

    def file_report(self, file_hash):
        return self._get(f"/files/{quote(file_hash, safe='')}")

    def domain_report(self, domain):
        return self._get(f"/domains/{quote(domain, safe='')}")

    def ip_report(self, ip):
        return self._get(f"/ip_addresses/{quote(ip, safe='')}")

    def relationship(self, object_path, rel, limit=40):
        """e.g. relationship('/domains/example.com', 'subdomains')"""
        return self._get(f"{object_path}/{rel}", params={"limit": limit})


def fmt_epoch(epoch):
    """VT v3 timestamps are unix epochs; render as the UTC string the v2
    API used, so stored reports and templates keep the same shape."""
    if not epoch:
        return None
    try:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError, OverflowError):
        return None


def _stats_counts(attrs):
    """positives/total from last_analysis_stats. `positives` counts
    malicious engines (what the VT UI shows); `total` counts engines that
    returned a verdict - type-unsupported engines never had a say."""
    stats = attrs.get("last_analysis_stats") or {}
    positives = stats.get("malicious", 0) or 0
    suspicious = stats.get("suspicious", 0) or 0
    total = sum((v or 0) for k, v in stats.items() if k != "type-unsupported")
    return stats, positives, suspicious, total


def map_file_report(v3, queried_value):
    """v3 file object -> v2-compatible template context (plus new fields)."""
    attrs = (v3.get("data") or {}).get("attributes") or {}
    stats, positives, suspicious, total = _stats_counts(attrs)
    sha256 = attrs.get("sha256") or queried_value
    scans = {}
    for engine, res in (attrs.get("last_analysis_results") or {}).items():
        scans[engine] = {
            "detected": res.get("category") in ("malicious", "suspicious"),
            "result": res.get("result"),
            "update": res.get("engine_update"),
            "version": res.get("engine_version"),
        }
    threat = (attrs.get("popular_threat_classification") or {})
    return {"results": {
        "response_code": 1,
        "positives": positives,
        "suspicious": suspicious,
        "total": total,
        "stats": stats,
        "scan_date": fmt_epoch(attrs.get("last_analysis_date")),
        "permalink": f"https://www.virustotal.com/gui/file/{sha256}",
        "md5": attrs.get("md5"),
        "sha1": attrs.get("sha1"),
        "sha256": attrs.get("sha256"),
        "names": (attrs.get("names") or [])[:10],
        "threat_label": threat.get("suggested_threat_label"),
        "scans": scans,
    }}


def map_domain_report(v3, queried_value, subdomains=None, resolutions=None):
    attrs = (v3.get("data") or {}).get("attributes") or {}
    stats, positives, suspicious, total = _stats_counts(attrs)
    res_list = []
    for row in (resolutions or []):
        rattrs = (row.get("attributes") or {})
        res_list.append({"ip_address": rattrs.get("ip_address"),
                         "last_resolved": fmt_epoch(rattrs.get("date"))})
    return {"results": {
        "response_code": 1,
        "positives": positives,
        "suspicious": suspicious,
        "total": total,
        "stats": stats,
        "scan_date": fmt_epoch(attrs.get("last_analysis_date")),
        "permalink": f"https://www.virustotal.com/gui/domain/{queried_value}",
        "whois": attrs.get("whois"),
        "registrar": attrs.get("registrar"),
        "categories": attrs.get("categories") or {},
        "subdomains": subdomains or [],
        "resolutions": res_list,
    }}


def map_ip_report(v3, queried_value, resolutions=None):
    attrs = (v3.get("data") or {}).get("attributes") or {}
    stats, positives, suspicious, total = _stats_counts(attrs)
    res_list = []
    for row in (resolutions or []):
        rattrs = (row.get("attributes") or {})
        res_list.append({"hostname": rattrs.get("host_name"),
                         "last_resolved": fmt_epoch(rattrs.get("date"))})
    return {"results": {
        "response_code": 1,
        "positives": positives,
        "suspicious": suspicious,
        "total": total,
        "stats": stats,
        "scan_date": fmt_epoch(attrs.get("last_analysis_date")),
        "permalink": f"https://www.virustotal.com/gui/ip-address/{queried_value}",
        "asn": attrs.get("asn"),
        "as_owner": attrs.get("as_owner"),
        "country": attrs.get("country"),
        "resolutions": res_list,
    }}
