#!/usr/bin/env python3
"""Set the IrisMISP module's four report templates to the lean
highlights-plus-link shape.

The IrisMISP module (upstream wheel) defaults to dumping the raw MISP
search result as indented JSON into the IOC attribute - on a hub
indicator that is tens of MB stored per enrichment run. This applies a
trimmed template instead: per configured MISP server, the match count,
the 10 newest events as dated links into MISP, and an overflow line.
All third-party strings are |e-escaped (module templates render without
autoescape, and MISP event titles are other people's data).

Idempotent; run it again after a config reset. The module reads its
config per call, so no restart is needed.

Usage (inside the app container):
  docker exec -w /iriswebapp -e PYTHONPATH=/iriswebapp <app_container> \
      python /iriswebapp/scripts/apply_lean_misp_templates.py
"""
import json
import sys

from app import app, db
from app.models.models import IrisModule
from sqlalchemy.orm.attributes import flag_modified

from iris_misp_module.IrisMISPConfig import LEAN_MISP_TEMPLATE

TEMPLATE_PARAMS = (
    'misp_domain_report_template',
    'misp_ip_report_template',
    'misp_hash_report_template',
    'misp_ja3_report_template',
)


def main():
    with app.app_context():
        mod = IrisModule.query.filter(IrisModule.module_name == 'iris_misp_module').first()
        if not mod:
            print('iris_misp_module is not registered on this instance - nothing to do')
            return 0
        conf = mod.module_config if isinstance(mod.module_config, list) else json.loads(mod.module_config)
        hit = 0
        for p in conf:
            if p.get('param_name') in TEMPLATE_PARAMS:
                p['value'] = LEAN_MISP_TEMPLATE
                hit += 1
        if hit != len(TEMPLATE_PARAMS):
            print(f'expected {len(TEMPLATE_PARAMS)} template params, found {hit} - aborting without change')
            return 1
        mod.module_config = conf
        flag_modified(mod, 'module_config')
        db.session.commit()
        print(f'{hit} MISP template slots set to the lean template '
              '(takes effect on the next enrichment run, no restart needed)')
        return 0


if __name__ == '__main__':
    sys.exit(main())
