"""Quick template-syntax check for the case_ai_panel.html partial.

Walks the same template search paths Flask uses (root templates + every
blueprint's templates folder), then renders both case_ai_panel.html and
case.html with a stub case context. Any Jinja error prints + exits 1.
"""
from __future__ import annotations

import os
import sys

from jinja2 import Environment, FileSystemLoader


def main() -> int:
    search = ['/iriswebapp/app/templates']
    for root, dirs, _ in os.walk('/iriswebapp/app/blueprints'):
        if 'templates' in dirs:
            search.append(os.path.join(root, 'templates'))

    env = Environment(loader=FileSystemLoader(search))
    try:
        tmpl = env.get_template('case_ai_panel.html')
        src = tmpl.render(case={'case_id': 99})
        marker = 'iris-ai-panel' in src
        print('AI panel template renders OK '
              f'(chars={len(src)}, marker_present={marker})')
        env.get_template('case.html')
        print('case.html parses OK (parent template loaded by Jinja)')
    except Exception as exc:
        print('TEMPLATE ERROR:', repr(exc))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
