#  IRIS Source Code
#
#  Deterministic checks for the verified executive summary (iris-ng, 2026-10-09).
#
#  Pure functions over (claims, case record) -> flags. No Flask, no ORM: the
#  orchestrator builds the record (case_summary.build_case_record) and this
#  module never sees a database. Every rule is a function of the claim text,
#  its cited sources and the record, so a suite can drive each branch with a
#  dict. Severity lives in ONE table (SEVERITY) shared with the LLM verifier's
#  codes so the tests derive the vocabulary from the module, not a hand list.
#
#  Matching rule: a token extracted from a claim must appear in at least one
#  CITED source's normalised text (NFKC -> refang -> lower -> whitespace
#  collapsed), or -- for numbers -- in the record's allowed set (server
#  counts, evidence integrity). Only the cited sources count: a fact that is
#  true elsewhere in the case but not where the claim says it is, is a flag.

from __future__ import annotations

import ipaddress
import re
import unicodedata
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import date
from typing import Any

from dateutil import parser as dateparser

from app.iris_engine.utils.ioc_normalise import refang

CHECKS_VERSION = "checks-1"

SECTIONS = ("situation", "status", "impact", "evidence", "findings", "actions",
            "outstanding", "recommendations", "timeline", "lessons")
TIERS = ("confirmed", "suspected", "unverified", "third_party_reported")
REF_TYPES = ("note", "event", "task", "asset", "ioc", "evidence")
# ref type -> key of the record dict
RECORD_KEYS = {"note": "notes", "event": "events", "task": "tasks", "asset": "assets",
               "ioc": "iocs", "evidence": "evidence"}

# IRIS task statuses -> the three classes the checks reason about. Unknown
# names (a renamed status) fall back to open + a low flag.
TASK_STATUS_MAP = {
    "to do": "open", "in progress": "open",
    "on hold": "blocked",
    "done": "closed", "canceled": "closed", "cancelled": "closed",
}

# The single severity table for every flag code: deterministic (this module),
# verifier (summary_verifier.py) and pipeline (case_summary.py).
SEVERITY: dict[str, str] = {
    # deterministic
    "REF_MISSING": "high",
    "CONFIRMED_WITHOUT_REFS": "high",
    "NUMBER_NOT_IN_SOURCE": "high",
    "NUMBER_UNSOURCED": "high",
    "DATE_NOT_IN_SOURCE": "medium",
    "TIMELINE_DATE_MISMATCH": "high",
    "TIMELINE_NO_EVENT_REF": "high",
    "IP_NOT_IN_SOURCE": "high",
    "HOSTNAME_NOT_IN_SOURCE": "medium",
    "ACCOUNT_NOT_IN_SOURCE": "medium",
    "TASK_STATUS_MISMATCH": "high",
    "TASK_CANCELED_AS_ACTION": "medium",
    "TASK_ASSIGNEE_MISMATCH": "medium",
    "TASK_STATUS_UNKNOWN": "low",
    "EVIDENCE_MISMATCH": "high",
    "RELATIVE_TIME_PHRASE": "medium",
    "CLAIM_DROPPED": "low",
    "TIER_COERCED": "low",
    "REF_DROPPED": "low",
    "STATUS_MISSING": "low",
    # verifier, per claim
    "CLAIM_CONTRADICTED": "high",
    "CLAIM_UNSUPPORTED": "high",
    "CLAIM_PARTIALLY_SUPPORTED": "medium",
    "TIER_OVERSTATED": "high",          # medium when the claim is not 'confirmed' (the verifier passes severity=)
    "VERIFIER_NO_VERDICT": "medium",
    # verifier, whole document
    "DOC_CONTRADICTION": "high",
    "DOWNLOAD_AS_FILE": "medium",
    "IP_AS_ACTOR": "medium",
    "THIRD_PARTY_AS_CONFIRMED": "high",
    "IMPACT_NUMBER_UNSOURCED": "high",
    "STATUS_INCONSISTENT": "medium",
    # pipeline
    "VERIFIER_FAILED": "high",
    "VERIFIER_UNAVAILABLE": "high",
    "REVISE_FAILED": "medium",
}

DOCUMENT_PATTERN_CODES = ("DOWNLOAD_AS_FILE", "IP_AS_ACTOR", "THIRD_PARTY_AS_CONFIRMED",
                          "IMPACT_NUMBER_UNSOURCED", "RELATIVE_TIME_PHRASE", "STATUS_INCONSISTENT")


@dataclass
class Flag:
    code: str
    severity: str
    claim_id: str | None
    message: str
    source_refs: list = field(default_factory=list)
    detail: dict | None = None
    source: str = "checks"

    def to_dict(self) -> dict:
        return asdict(self)


def make_flag(code: str, claim_id: str | None, message: str, *, source_refs=None, detail=None,
              source: str = "checks", severity: str | None = None) -> Flag:
    return Flag(code=code, severity=severity or SEVERITY[code], claim_id=claim_id, message=message,
                source_refs=list(source_refs or []), detail=detail, source=source)


# ----- normalisation --------------------------------------------------------


_SCHEME_ANY_RE = re.compile(r"\b(hxxps?|fxp)(://)", re.IGNORECASE)
_SCHEMES = {"hxxp": "http", "hxxps": "https", "fxp": "ftp"}


def normalise(text: Any) -> str:
    """NFKC -> refang (hxxp, [.], (dot), [at] ...) -> lower -> whitespace collapsed.
    The product's refang() undoes a defanged scheme only at the start of a
    value; prose carries them mid-sentence, so they are undone here as well."""
    s = unicodedata.normalize("NFKC", str(text or ""))
    s = refang(s)
    s = _SCHEME_ANY_RE.sub(lambda m: _SCHEMES[m.group(1).lower()] + m.group(2), s)
    s = " ".join(s.split())
    return s.lower()


# ----- token extraction -----------------------------------------------------

_MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
# A trailing sentence period must not hide a token: "not followed by a word
# character or by '.digit'" rather than "not followed by a dot".
_IPV4_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d{1,3}){3})(?!\w|\.\d)")
_IPV6_CAND_RE = re.compile(r"(?<![\w:])([0-9a-f]{0,4}(?::[0-9a-f]{0,4}){2,7})(?![\w:])")
_HASH_RE = re.compile(r"\b([a-f0-9]{64}|[a-f0-9]{40}|[a-f0-9]{32})\b")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_DOMAIN_USER_RE = re.compile(r"(?<![\w\\])([a-z0-9_-]+\\[a-z0-9_-]+(?:\.[a-z0-9_-]+)*)")
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
# day-precision dates, in the order they are tried
_DATE_RES = (
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b"),
    re.compile(r"\b\d{1,2} " + _MONTHS + r" \d{4}\b"),
    re.compile(r"\b" + _MONTHS + r" \d{1,2},? \d{4}\b"),
)
# blanked before number extraction but not day-precision dates
_MONTH_YEAR_RE = re.compile(r"\b" + _MONTHS + r" \d{4}\b")
_NUMBER_RE = re.compile(r"(?<![\w.:/-])(\d[\d,]*(?:\.\d+)?)(?!\w|[.:/-]\d)")
_YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")
_FQDN_RE = re.compile(r"\b(?=[a-z0-9-]*[a-z])[a-z0-9-]{1,63}(?:\.[a-z0-9-]{1,63})*\.[a-z]{2,24}\b")
# Bare host names are taken from the ORIGINAL text (case carries the signal):
# an all-caps hyphenated name (WS-FIN-07, FS-CORP) or letters followed by up
# to four digits (DC01, srv12, PC0042). Hyphenated English ("third-party",
# "read-only") is neither.
_HOST_CAPS_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b")
_HOST_ALNUM_RE = re.compile(r"\b[A-Za-z]{2,}-?\d{1,4}\b")
_HOST_STOPLIST = {"sha1", "sha256", "sha512", "md5", "ipv4", "ipv6", "x64", "x86", "utf8", "utf16", "tls1",
                  "http2", "http3", "ps1", "e01", "ex01", "ad1", "win7", "win10", "win11", "mp4", "mp3", "oauth2",
                  "base64", "cve", "iso27001", "iso-27001", "nist", "sp800", "top10", "h1", "h2", "q1", "q2", "q3",
                  "q4", "fy25", "fy26", "fy27", "t1", "t2", "t3", "p1", "p2", "p3", "l1", "l2", "l3", "c2"}
_FILE_EXTS = ("e01", "ex01", "aff4", "dd", "raw", "img", "vmem", "vmdk", "mem", "dmp", "pcap", "pcapng", "evtx",
              "evt", "log", "csv", "json", "txt", "zip", "7z", "rar", "gz", "tgz", "bin", "exe", "dll", "sys",
              "ps1", "bat", "vbs", "js", "eml", "msg", "pst", "ost", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
              "pdf", "iso", "ad1", "ova", "ovf", "vhd", "vhdx", "lnk", "db", "sqlite", "xml", "html", "htm",
              "py", "sh", "jar", "apk", "dat", "tmp", "bak", "yml", "yaml", "ini", "cfg", "conf", "reg", "hiv")
_FILENAME_RE = re.compile(r"\b[\w.-]+\.(?:" + "|".join(_FILE_EXTS) + r")\b")
_SIZE_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s?(b|kb|mb|gb|tb|kib|mib|gib|tib)\b")
_CUSTODIAN_RE = re.compile(
    r"\b(?:collected|acquired|preserved|handled|registered|imaged|captured|exported) by "
    r"([a-z][a-z'.-]+(?: [a-z][a-z'.-]+)?)")
_CUSTODIAN_STOP = {"the", "a", "an", "our", "its", "their", "his", "her", "third", "external", "internal", "law",
                   "local", "remote", "forensic", "forensics", "it", "team", "staff", "vendor", "msp", "mssp",
                   "customer", "client", "analysts", "investigators", "responders", "engineers", "on", "at", "in",
                   "using", "via", "with", "from", "and"}
_RELATIVE_TIME_RE = re.compile(
    r"\b(?:in the (?:past|last) (?:few|several|couple of|\d+) (?:minutes?|hours?|days?|weeks?)"
    r"|(?:a few |several |\d+ )(?:minutes?|hours?|days?|weeks?) ago"
    r"|yesterday|today|tonight|this (?:morning|afternoon|evening)|earlier today|recently|just now|moments ago)\b")

_OPEN_WORDS_RE = re.compile(
    r"\b(?:still open|remains? open|in progress|ongoing|underway|pending|planned|not yet (?:started|complete|completed|done)"
    r"|has not (?:been )?(?:started|completed))\b")
_BLOCKED_WORDS_RE = re.compile(r"\b(?:blocked|on hold|waiting (?:on|for)|stalled|awaiting)\b")
_CLOSED_WORDS_RE = re.compile(r"\b(?:completed|has been completed|closed|done|finished|cancel+ed|was completed|were completed)\b")
_UNASSIGNED_RE = re.compile(r"\bunassigned\b|\bno (?:one|owner) (?:is )?assigned\b|\bwithout an? (?:owner|assignee)\b")
_ASSIGNED_RE = re.compile(r"\bassigned to\b|\bhas an? (?:owner|assignee)\b")

_UNITS = {"b": 1, "kb": 1000, "mb": 1000 ** 2, "gb": 1000 ** 3, "tb": 1000 ** 4,
          "kib": 1024, "mib": 1024 ** 2, "gib": 1024 ** 3, "tib": 1024 ** 4}


def _valid_ip(token: str) -> str | None:
    try:
        return ipaddress.ip_address(token).compressed
    except ValueError:
        return None


def extract_ips(norm: str) -> set[str]:
    out = set()
    for m in _IPV4_RE.finditer(norm):
        ip = _valid_ip(m.group(1))
        if ip:
            out.add(ip)
    for m in _IPV6_CAND_RE.finditer(norm):
        cand = m.group(1)
        if cand.count(":") >= 2 and any(ch.isalnum() for ch in cand):
            ip = _valid_ip(cand)
            if ip:
                out.add(ip)
    return out


def extract_hashes(norm: str) -> set[str]:
    return {m.group(1) for m in _HASH_RE.finditer(norm)}


def extract_emails(norm: str) -> set[str]:
    return set(_EMAIL_RE.findall(norm))


def extract_domain_users(norm: str) -> set[str]:
    return {m.group(1) for m in _DOMAIN_USER_RE.finditer(norm)}


def _parse_date(tok: str) -> date | None:
    try:
        return dateparser.parse(tok, dayfirst=False).date()
    except (ValueError, OverflowError, TypeError):
        return None


def extract_date_tokens(norm: str) -> list[str]:
    toks: list[str] = []
    for rx in _DATE_RES:
        toks.extend(rx.findall(norm))
    return toks


def extract_dates(norm: str) -> set[date]:
    out = set()
    for tok in extract_date_tokens(norm):
        d = _parse_date(tok)
        if d:
            out.add(d)
    return out


def _blank(norm: str, patterns) -> str:
    """Replace every match of each pattern with spaces so later extractors do
    not re-read the same characters (a date is not three numbers)."""
    for rx in patterns:
        norm = rx.sub(lambda m: " " * len(m.group(0)), norm)
    return norm


def extract_numbers(norm: str) -> set[str]:
    """Digit tokens with thousands separators removed, after dates, times,
    IPs, hashes and e-mail addresses are blanked out."""
    cleaned = _blank(norm, (*_DATE_RES, _MONTH_YEAR_RE, _TIME_RE, _IPV4_RE, _HASH_RE, _EMAIL_RE))
    out = set()
    for m in _NUMBER_RE.finditer(cleaned):
        tok = m.group(1).replace(",", "")
        if tok.endswith("."):
            tok = tok[:-1]
        if tok:
            out.add(tok)
    return out


def extract_hostnames(original: str, norm: str) -> set[str]:
    out = set()
    emails = extract_emails(norm)
    for tok in _FQDN_RE.findall(norm):
        if _valid_ip(tok) or any(tok in e for e in emails):
            continue
        if tok.rsplit(".", 1)[-1] in _FILE_EXTS:
            continue
        out.add(tok)
    for rx in (_HOST_CAPS_RE, _HOST_ALNUM_RE):
        for tok in rx.findall(original or ""):
            low = tok.lower()
            if low in _HOST_STOPLIST or _valid_ip(low):
                continue
            out.add(low)
    return out


def extract_sizes(norm: str) -> list[tuple[float, str]]:
    return [(float(v), u) for v, u in _SIZE_RE.findall(norm)]


def extract_filenames(norm: str) -> set[str]:
    return {m.group(0) for m in _FILENAME_RE.finditer(norm)}


def extract_custodians(norm: str) -> set[str]:
    out = set()
    for m in _CUSTODIAN_RE.finditer(norm):
        who = m.group(1).strip()
        if who.split(" ", 1)[0] in _CUSTODIAN_STOP:
            continue
        out.add(who)
    return out


def status_words(norm: str) -> set[str]:
    out = set()
    if _OPEN_WORDS_RE.search(norm):
        out.add("open")
    if _BLOCKED_WORDS_RE.search(norm):
        out.add("blocked")
    if _CLOSED_WORDS_RE.search(norm):
        out.add("closed")
    return out


# ----- record access --------------------------------------------------------


def _lookup(record: dict, ref: dict):
    bucket = record.get(RECORD_KEYS.get(ref.get("type"), ""), {}) or {}
    return bucket.get(ref.get("id"))


def _cited(claim: dict, record: dict) -> list[tuple[str, int, dict]]:
    """(type, id, source dict) for every ref that exists in the record."""
    out = []
    for ref in claim.get("source_refs") or []:
        src = _lookup(record, ref)
        if src is not None:
            out.append((ref.get("type"), ref.get("id"), src))
    return out


def _source_numbers(src: dict) -> set[str]:
    nums = src.get("_numbers")
    if nums is None:
        nums = extract_numbers(src.get("search", ""))
        for extra in src.get("numbers", ()):  # explicit numeric fields (ids, file_size, counts)
            nums.add(str(extra))
        src["_numbers"] = nums
    return nums


def _source_ips(src: dict) -> set[str]:
    ips = src.get("_ips")
    if ips is None:
        ips = extract_ips(src.get("search", ""))
        ip = src.get("ip")
        if ip:
            v = _valid_ip(normalise(ip))
            if v:
                ips.add(v)
        src["_ips"] = ips
    return ips


def _source_dates(src: dict) -> set[date]:
    dates = src.get("_dates")
    if dates is None:
        dates = extract_dates(src.get("search", ""))
        for d in src.get("dates", ()):
            if isinstance(d, date):
                dates.add(d)
        src["_dates"] = dates
    return dates


# ----- the checks -----------------------------------------------------------


def run_checks(claims: list[dict], record: dict) -> list[Flag]:
    flags: list[Flag] = []
    for claim in claims:
        flags.extend(check_claim(claim, record))
    return flags


def check_claim(claim: dict, record: dict) -> list[Flag]:
    flags: list[Flag] = []
    cid = claim.get("id")
    refs = list(claim.get("source_refs") or [])
    section = claim.get("section")
    tier = claim.get("tier")
    original = str(claim.get("text") or "")
    norm = normalise(original)

    # 1. every ref exists in this case
    for r in refs:
        if _lookup(record, r) is None:
            flags.append(make_flag("REF_MISSING", cid,
                                   f"Cited {r.get('type')} #{r.get('id')} does not exist in this case",
                                   source_refs=[r], detail={"ref": r}))
    cited = _cited(claim, record)
    existing_refs = [{"type": t, "id": i} for t, i, _ in cited]

    # 2. confirmed needs refs
    if tier == "confirmed" and not cited:
        flags.append(make_flag("CONFIRMED_WITHOUT_REFS", cid,
                               "Claim is marked confirmed but cites no case object",
                               detail={"refs_given": len(refs)}))

    # 3. relative-time phrases (the summary has no "now")
    m = _RELATIVE_TIME_RE.search(norm)
    if m:
        flags.append(make_flag("RELATIVE_TIME_PHRASE", cid,
                               f"Relative time phrase \"{m.group(0)}\" - state the date instead",
                               source_refs=existing_refs, detail={"phrase": m.group(0)}))

    search_blob = " ".join(src.get("search", "") for _, _, src in cited)

    # 4. numbers
    allowed = set(record.get("allowed_numbers", {}).get("*", ()))
    if section == "evidence":
        allowed |= set(record.get("allowed_numbers", {}).get("evidence", ()))
    src_numbers: set[str] = set()
    src_dates: set[date] = set()
    for _, _, src in cited:
        src_numbers |= _source_numbers(src)
        src_dates |= _source_dates(src)
    src_years = {str(d.year) for d in src_dates}
    for num in sorted(extract_numbers(norm)):
        if num in allowed or num in src_numbers:
            continue
        if _YEAR_RE.match(num) and num in src_years:
            continue
        if cited:
            flags.append(make_flag("NUMBER_NOT_IN_SOURCE", cid,
                                   f"The number {num} does not appear in the cited sources",
                                   source_refs=existing_refs, detail={"token": num}))
        else:
            flags.append(make_flag("NUMBER_UNSOURCED", cid,
                                   f"The number {num} is stated without a cited source",
                                   detail={"token": num}))

    # 5. dates (day precision) against every cited source's dates or literal text
    for tok in extract_date_tokens(norm):
        d = _parse_date(tok)
        if d is None:
            continue
        if d in src_dates or tok in search_blob:
            continue
        flags.append(make_flag("DATE_NOT_IN_SOURCE", cid, f"The date {tok} does not appear in the cited sources",
                               source_refs=existing_refs, detail={"token": tok}))

    # 6. timeline claims: an event ref and the exact minute
    if section == "timeline":
        event_refs = [(i, src) for t, i, src in cited if t == "event"]
        if not event_refs:
            flags.append(make_flag("TIMELINE_NO_EVENT_REF", cid, "Timeline entry cites no timeline event",
                                   source_refs=existing_refs))
        et = str(claim.get("event_time") or "").strip()
        if et and event_refs and et not in {src.get("event_time") for _, src in event_refs}:
            flags.append(make_flag("TIMELINE_DATE_MISMATCH", cid,
                                   f"Timeline entry says {et} but the cited event is at "
                                   + ", ".join(str(src.get("event_time")) for _, src in event_refs),
                                   source_refs=existing_refs,
                                   detail={"claimed": et, "events": [src.get("event_time") for _, src in event_refs]}))

    # 7. IPs
    src_ips: set[str] = set()
    for _, _, src in cited:
        src_ips |= _source_ips(src)
    for ip in sorted(extract_ips(norm)):
        if ip not in src_ips:
            flags.append(make_flag("IP_NOT_IN_SOURCE", cid, f"The address {ip} does not appear in the cited sources",
                                   source_refs=existing_refs, detail={"token": ip}))

    # 8. host names (FQDN or asset-style) - source text or a cited asset's name/domain
    asset_names = set()
    for t, _, src in cited:
        if t == "asset":
            for key in ("name", "domain"):
                v = src.get(key)
                if v:
                    asset_names.add(normalise(v))
    for host in sorted(extract_hostnames(original, norm)):
        if host in search_blob or host in asset_names:
            continue
        flags.append(make_flag("HOSTNAME_NOT_IN_SOURCE", cid,
                               f"The host name {host} does not appear in the cited sources",
                               source_refs=existing_refs, detail={"token": host}))

    # 9. accounts
    for acct in sorted(extract_emails(norm) | extract_domain_users(norm)):
        if acct in search_blob:
            continue
        flags.append(make_flag("ACCOUNT_NOT_IN_SOURCE", cid, f"The account {acct} does not appear in the cited sources",
                               source_refs=existing_refs, detail={"token": acct}))

    # 10. task status / assignees
    tasks = [(i, src) for t, i, src in cited if t == "task"]
    if tasks:
        classes: dict[int, str] = {}
        for i, src in tasks:
            cls = src.get("status_class")
            if cls not in ("open", "blocked", "closed"):
                flags.append(make_flag("TASK_STATUS_UNKNOWN", cid,
                                       f"Task #{i} has an unmapped status \"{src.get('status_name')}\"; treated as open",
                                       source_refs=[{"type": "task", "id": i}]))
                cls = "open"
            classes[i] = cls
        words = status_words(norm)
        task_refs = [{"type": "task", "id": i} for i, _ in tasks]
        if section == "actions":
            not_closed = [i for i, c in classes.items() if c != "closed"]
            if not_closed:
                flags.append(make_flag("TASK_STATUS_MISMATCH", cid,
                                       "Reported as an action taken, but task(s) "
                                       + ", ".join(f"#{i} ({_status_name(tasks, i)})" for i in not_closed)
                                       + " are not closed", source_refs=task_refs, detail={"tasks": not_closed}))
            canceled = [i for i, src in tasks if (src.get("status_name") or "").lower() in ("canceled", "cancelled")]
            if canceled:
                flags.append(make_flag("TASK_CANCELED_AS_ACTION", cid,
                                       "Reported as an action taken, but task(s) " + ", ".join(f"#{i}" for i in canceled)
                                       + " were canceled", source_refs=task_refs, detail={"tasks": canceled}))
        elif section == "outstanding":
            closed = [i for i, c in classes.items() if c == "closed"]
            if closed:
                flags.append(make_flag("TASK_STATUS_MISMATCH", cid,
                                       "Reported as outstanding, but task(s) " + ", ".join(f"#{i}" for i in closed)
                                       + " are closed", source_refs=task_refs, detail={"tasks": closed}))
        else:
            if "closed" in words and any(c != "closed" for c in classes.values()):
                flags.append(make_flag("TASK_STATUS_MISMATCH", cid,
                                       "Described as completed, but a cited task is not closed", source_refs=task_refs,
                                       detail={"words": sorted(words)}))
            if "open" in words and all(c == "closed" for c in classes.values()):
                flags.append(make_flag("TASK_STATUS_MISMATCH", cid,
                                       "Described as open or in progress, but every cited task is closed",
                                       source_refs=task_refs, detail={"words": sorted(words)}))
        if "blocked" in words and "blocked" not in classes.values():
            flags.append(make_flag("TASK_STATUS_MISMATCH", cid,
                                   "Described as blocked, but no cited task is on hold", source_refs=task_refs,
                                   detail={"words": sorted(words)}))
        if _UNASSIGNED_RE.search(norm) and all(src.get("has_assignee") for _, src in tasks):
            flags.append(make_flag("TASK_ASSIGNEE_MISMATCH", cid,
                                   "Described as unassigned, but every cited task has an assignee",
                                   source_refs=task_refs))
        if _ASSIGNED_RE.search(norm) and not any(src.get("has_assignee") for _, src in tasks):
            flags.append(make_flag("TASK_ASSIGNEE_MISMATCH", cid,
                                   "Described as assigned, but no cited task has an assignee",
                                   source_refs=task_refs))

    # 11. evidence claims vs the register
    ev = [(i, src) for t, i, src in cited if t == "evidence"]
    if ev:
        ev_refs = [{"type": "evidence", "id": i} for i, _ in ev]
        names = {normalise(src.get("filename")) for _, src in ev if src.get("filename")}
        hashes = {normalise(src.get("file_hash")) for _, src in ev if src.get("file_hash")}
        sizes = [src.get("file_size") for _, src in ev if src.get("file_size")]
        custodians = {normalise(src.get("created_by")) for _, src in ev if src.get("created_by")}
        for fn in sorted(extract_filenames(norm)):
            if fn not in names and fn not in search_blob:
                flags.append(make_flag("EVIDENCE_MISMATCH", cid, f"The file {fn} is not among the cited evidence items",
                                       source_refs=ev_refs, detail={"token": fn, "kind": "filename"}))
        for h in sorted(extract_hashes(norm)):
            if h not in hashes:
                flags.append(make_flag("EVIDENCE_MISMATCH", cid,
                                       f"The hash {h[:12]}... is not among the cited evidence items",
                                       source_refs=ev_refs, detail={"token": h, "kind": "hash"}))
        for value, unit in extract_sizes(norm):
            stated = value * _UNITS[unit]
            if not any(abs(stated - float(sz)) <= 0.05 * float(sz) for sz in sizes):
                flags.append(make_flag("EVIDENCE_MISMATCH", cid,
                                       f"The size {value:g} {unit.upper()} matches no cited evidence item (within 5 %)",
                                       source_refs=ev_refs, detail={"token": f"{value:g} {unit}", "kind": "size"}))
        for who in sorted(extract_custodians(norm)):
            if who in search_blob or any(who in c or c in who for c in custodians):
                continue
            flags.append(make_flag("EVIDENCE_MISMATCH", cid,
                                   f"\"{who}\" is not the recorded custodian of the cited evidence",
                                   source_refs=ev_refs, detail={"token": who, "kind": "custodian"}))
    return flags


def _status_name(tasks: list, i: int) -> str:
    for j, src in tasks:
        if j == i:
            return str(src.get("status_name") or src.get("status_class") or "?")
    return "?"


# ----- specialists: every id they emit must exist -----------------------------

_CITE_RE = re.compile(r"\[(note|event|task|asset|ioc|evidence):((?:\d+)(?:\s*,\s*\d+)*)\]", re.IGNORECASE)
_ID_KEYS = ("event_id", "asset_id", "note_id", "ioc_id", "task_id", "evidence_id")


def specialist_ids(parsed: Any) -> dict[str, set[int]]:
    """Every object id a specialist's parsed output names, by ref type:
    `[note:12,15]` tokens inside any string, plus the structured id fields
    (event_id, asset_id, evidence_ids ...)."""
    out: dict[str, set[int]] = {t: set() for t in REF_TYPES}

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in _ID_KEYS and isinstance(v, int) and not isinstance(v, bool):
                    out[k[:-3]].add(v)
                elif k == "evidence_ids" and isinstance(v, list):
                    out["evidence"].update(x for x in v if isinstance(x, int) and not isinstance(x, bool))
                else:
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, str):
            for m in _CITE_RE.finditer(node):
                for part in m.group(2).split(","):
                    part = part.strip()
                    if part.isdigit():
                        out[m.group(1).lower()].add(int(part))

    walk(parsed)
    return out


__all__ = ["CHECKS_VERSION", "SECTIONS", "TIERS", "REF_TYPES", "RECORD_KEYS", "TASK_STATUS_MAP", "SEVERITY",
           "DOCUMENT_PATTERN_CODES", "Flag", "make_flag", "normalise", "run_checks", "check_claim",
           "specialist_ids", "extract_numbers", "extract_ips", "extract_hostnames", "extract_dates",
           "extract_date_tokens", "extract_emails", "extract_domain_users", "extract_filenames",
           "extract_hashes", "extract_sizes", "extract_custodians", "status_words"]
