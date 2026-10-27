#!/usr/bin/env python3
"""Find and repair MISP attributes the IOC sync overwrote.

Older versions of the MISP sync module could link a new IOC to an attribute
that belonged to a different IOC, then update that attribute in place: on a
MISP up to 2.5.32 the attribute search ignores the provenance filter the module
relied on and returned the event's first attribute. Each new IOC overwrote that
one attribute (its value and its comment) and added its own tags to it, so a
case's MISP event ends up holding a single attribute with the latest IOC's
value and every IOC's tags, while IRIS links all of those IOCs to it.

Run inside the app container (the scripts directory is mounted there):

  docker exec -w /iriswebapp -e PYTHONPATH=/iriswebapp iriswebapp_app \\
      python /iriswebapp/scripts/misp_sync_repair.py [--case ID ...] [--apply] [--sync-missing]

Without --apply it only reports, and changes nothing in IRIS or MISP.

With --apply, for each damaged attribute it soft-deletes the attribute in MISP
(restorable from the event's "Deleted" view; its accumulated tags go with it),
removes the IRIS link rows that pointed at it, and syncs each of those IOCs
again, so each one gets its own attribute with its own tags.

--sync-missing (with --apply) also syncs the IOCs of the same cases that have
no MISP attribute at all, or whose linked attribute no longer exists in MISP.

Damaged = one MISP attribute linked to IOCs with different types or values, or
an attribute whose value is no longer the value of the IOC linked to it.
Several IOCs that share one type and value legitimately share one attribute
(MISP keeps one attribute per type and value in an event); those are left alone.

Exit status: 0 = nothing damaged, or everything requested was repaired;
1 = an error (MISP unreachable, module not configured, a sync that failed).
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Any


def _key(ioc, misp_type: str) -> tuple[Any, str]:
    """An IOC's identity under the attribute's MISP type, its value as the sync sends it
    (`tcp/8070` and `8070` are the same port to MISP)."""
    from iris_misp_sync_module.IrisMISPSyncInterface import normalise_value

    return ioc.ioc_type_id, normalise_value(misp_type, ioc.ioc_value).lower()


def load_handler(log):
    """The sync handler built from the module's stored configuration."""
    from app.models.models import IrisModule
    from iris_misp_sync_module.IrisMISPSyncInterface import IrisMISPSyncHandler

    module = IrisModule.query.filter(IrisModule.module_name == "iris_misp_sync_module").first()
    if module is None:
        raise SystemExit("iris_misp_sync_module is not registered on this instance")
    config = {entry["param_name"]: entry.get("value") for entry in (module.module_config or [])
              if isinstance(entry, dict) and "param_name" in entry}
    handler = IrisMISPSyncHandler(mod_config=config, logger=log)
    if not handler._is_configured():
        raise SystemExit("the MISP sync module has no MISP URL / API key configured")
    if not module.is_active:
        log.warning("note: the MISP sync module is not active; repairing with its stored configuration anyway")
    return handler


def event_attributes(client, misp_event_id: int) -> dict[int, dict[str, Any]]:
    """Every live attribute of one MISP event, by id. `eventid` is honoured by
    every MISP version as long as no `searchall` is sent; deleted attributes
    are not returned."""
    response = client.search_attributes({
        "returnFormat": "json",
        "eventid": misp_event_id,
        "includeContext": False,
    })
    found = {}
    for attribute in response.get("response", {}).get("Attribute", []):
        if str(attribute.get("event_id")) == str(misp_event_id) and attribute.get("id") is not None:
            found[int(attribute["id"])] = attribute
    return found


def scan_event(client, event_link) -> dict[str, Any]:
    """Classify one case's links: damaged attribute groups and missing IOCs."""
    from app.models.models import Ioc, MispAttributeLink

    attributes = event_attributes(client, event_link.misp_event_id)
    links = MispAttributeLink.query.filter(MispAttributeLink.event_link_id == event_link.id).all()

    groups: dict[int, list] = {}
    for link in links:
        groups.setdefault(int(link.misp_attribute_id), []).append(link)

    damaged, stale = [], []
    for attribute_id, group in sorted(groups.items()):
        iocs = [Ioc.query.filter(Ioc.ioc_id == link.ioc_id).first() for link in group]
        iocs = [ioc for ioc in iocs if ioc is not None]
        attribute = attributes.get(attribute_id)
        if attribute is None:
            stale.extend(iocs)
            continue
        from iris_misp_sync_module.IrisMISPSyncInterface import normalise_value

        misp_type = attribute.get("type") or ""
        keys = {_key(ioc, misp_type) for ioc in iocs}
        value_moved = (len(keys) == 1
                       and next(iter(keys))[1] != normalise_value(misp_type, attribute.get("value")).lower())
        if len(keys) > 1 or value_moved:
            damaged.append({"attribute": attribute, "links": group, "iocs": iocs})

    linked_ids = {link.ioc_id for link in links}
    unlinked = Ioc.query.filter(Ioc.case_id == event_link.case_id).order_by(Ioc.ioc_id).all()
    missing = [ioc for ioc in unlinked if ioc.ioc_id not in linked_ids] + stale
    return {"damaged": damaged, "missing": missing, "attribute_count": len(attributes)}


def _sync(handler, ioc, log) -> bool:
    from app import db

    try:
        handler.sync_ioc(ioc)
        db.session.commit()
        return True
    except Exception as exc:  # noqa: BLE001 - reported per IOC, the run goes on
        db.session.rollback()
        log.error(f"    IOC #{ioc.ioc_id} ({ioc.ioc_value!r}) did not sync: {exc}")
        return False


def repair_event(handler, client, event_link, scan: dict[str, Any], sync_missing: bool, log) -> int:
    """Apply the repair for one event; returns the number of failures."""
    from app import db
    from app.models.models import MispAttributeLink

    failures = 0
    for item in scan["damaged"]:
        attribute_id = int(item["attribute"]["id"])
        try:
            client.delete_attribute(attribute_id)
        except Exception as exc:  # noqa: BLE001
            log.error(f"    attribute {attribute_id}: MISP refused the delete ({exc}); its links were left as they are")
            failures += 1
            continue
        MispAttributeLink.query.filter(MispAttributeLink.event_link_id == event_link.id,
                                       MispAttributeLink.misp_attribute_id == attribute_id).delete()
        db.session.commit()
        log.info(f"    attribute {attribute_id}: soft-deleted in MISP, {len(item['links'])} link(s) removed")
        for ioc in item["iocs"]:
            failures += 0 if _sync(handler, ioc, log) else 1

    if sync_missing:
        for ioc in scan["missing"]:
            MispAttributeLink.query.filter(MispAttributeLink.ioc_id == ioc.ioc_id).delete()
            db.session.commit()
            failures += 0 if _sync(handler, ioc, log) else 1
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--case", type=int, action="append", help="limit to this case id (repeatable)")
    parser.add_argument("--apply", action="store_true", help="repair (default: report only)")
    parser.add_argument("--sync-missing", action="store_true",
                        help="with --apply, also sync IOCs that have no MISP attribute")
    args = parser.parse_args(argv)

    log = logging.getLogger("misp_sync_repair")
    log.setLevel(logging.INFO)
    log.propagate = False
    for old in list(log.handlers):
        log.removeHandler(old)
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(stream)

    from app import app
    from app.models.models import MispEventLink

    with app.app_context():
        handler = load_handler(log)
        client = handler._build_client()
        query = MispEventLink.query.order_by(MispEventLink.case_id)
        if args.case:
            query = query.filter(MispEventLink.case_id.in_(args.case))
        event_links = query.all()

        totals = {"cases": 0, "damaged": 0, "iocs_on_damaged": 0, "missing": 0, "failures": 0}
        for event_link in event_links:
            try:
                scan = scan_event(client, event_link)
            except Exception as exc:  # noqa: BLE001
                log.error(f"case #{event_link.case_id} / MISP event {event_link.misp_event_id}: could not read the event ({exc})")
                totals["failures"] += 1
                continue
            totals["cases"] += 1
            if not scan["damaged"] and not scan["missing"]:
                continue
            log.info(f"case #{event_link.case_id} -> MISP event {event_link.misp_event_id} "
                     f"({scan['attribute_count']} live attribute(s))")
            for item in scan["damaged"]:
                attribute = item["attribute"]
                log.info(f"  DAMAGED attribute {attribute['id']} (now {attribute.get('type')} "
                         f"{attribute.get('value')!r}) is linked to {len(item['iocs'])} IOC(s):")
                for ioc in item["iocs"]:
                    log.info(f"    IOC #{ioc.ioc_id} {ioc.ioc_value!r}")
                totals["damaged"] += 1
                totals["iocs_on_damaged"] += len(item["iocs"])
            if scan["missing"]:
                log.info(f"  {len(scan['missing'])} IOC(s) with no MISP attribute: "
                         + ", ".join(f"#{ioc.ioc_id}" for ioc in scan["missing"]))
                totals["missing"] += len(scan["missing"])
            if args.apply:
                totals["failures"] += repair_event(handler, client, event_link, scan, args.sync_missing, log)

        log.info("")
        log.info(f"{totals['cases']} case(s) read; {totals['damaged']} damaged attribute(s) covering "
                 f"{totals['iocs_on_damaged']} IOC(s); {totals['missing']} IOC(s) without an attribute")
        if not args.apply and (totals["damaged"] or totals["missing"]):
            log.info("report only — re-run with --apply to repair the damaged attributes"
                     + (", and --sync-missing to also sync the IOCs without one" if totals["missing"] else ""))
        if args.apply:
            log.info(f"repair finished with {totals['failures']} failure(s)")
        return 1 if totals["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
