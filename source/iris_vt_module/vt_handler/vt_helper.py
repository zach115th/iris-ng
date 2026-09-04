#!/usr/bin/env python3
#
#  IRIS VT Module - template rendering helpers (API v3)
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
import logging
import traceback

from jinja2 import Template

import iris_interface.IrisInterfaceStatus as IrisInterfaceStatus

log = logging.getLogger(__name__)


def detection_ratio(results):
    """Detection percentage from the mapped context (0-100, or None when
    VT returned no verdicts). One formula for hashes, domains and IPs -
    v2's separate detected-URLs averaging is gone with the v2 API."""
    total = results.get("total")
    if not total:
        return None
    return round(float(results.get("positives", 0)) / float(total), 2) * 100


def _render(html_template, context):
    """Render a report template with the mapped context. The context dict
    is passed whole, so templates read both `results.x` and any top-level
    convenience keys a mapper adds."""
    try:
        rendered = Template(html_template).render(context)
    except Exception:
        log.error(traceback.format_exc())
        return IrisInterfaceStatus.I2Error(traceback.format_exc())
    return IrisInterfaceStatus.I2Success(data=rendered)


def gen_hash_report_from_template(html_template, vt_report) -> IrisInterfaceStatus:
    return _render(html_template, vt_report)


def gen_domain_report_from_template(html_template, vt_report) -> IrisInterfaceStatus:
    return _render(html_template, vt_report)


def gen_ip_report_from_template(html_template, vt_report) -> IrisInterfaceStatus:
    return _render(html_template, vt_report)
