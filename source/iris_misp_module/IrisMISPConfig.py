#!/usr/bin/env python3
#
#  IRIS MISP Module Source Code
#  contact@dfir-iris.org
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

module_name = "IrisMISP"
module_description = "Provides an interface between MISP and IRIS"
interface_version = "1.2.0"
module_version = "1.4.0"
pipeline_support = False
pipeline_info = {}

# iris-ng: the upstream default for all four report templates was the raw
# MISP search result dumped as indented JSON - on a hub indicator that is
# tens of MB stored per enrichment run, which dominated IOC page loads.
# The in-tree default is a lean highlights-plus-link report instead. All
# third-party strings are |e-escaped: these templates render WITHOUT
# autoescape and MISP event titles are other people's data.
# Context per configured server: {url, name, result: [{Event: {...}}]}.
LEAN_MISP_TEMPLATE = """<div class="row">
  <div class="col-12">
    <h3>MISP highlights</h3>
    {% for srv in results %}
      {% set evs = srv.result if srv.result else [] %}
      <div style="margin-bottom:6px;">
        <b>{{ srv.name | e }}</b> &mdash; {{ evs | length }} matching event{{ '' if evs|length == 1 else 's' }}
        &middot; <a href="{{ srv.url | e }}" rel="noopener" target="_blank">Open MISP</a>
      </div>
      {% if evs %}
      {# newest first: MISP returns search results in id order, not date
         order. Normalise the two result shapes, sort dated events by the
         YYYY-MM-DD string (lexicographic == chronological), and append
         undated ones at the end rather than crashing the render on them. #}
      {% set norm = [] %}
      {% for ev in evs %}{% if norm.append(ev.Event if ev.Event is defined else ev) %}{% endif %}{% endfor %}
      {% set ordered = (norm | selectattr('date', 'defined') | sort(attribute='date', reverse=true) | list)
                       + (norm | rejectattr('date', 'defined') | list) %}
      <ul>
        {% for e_ in ordered[:10] %}
          <li>{{ e_.date | e }} &mdash;
              <a href="{{ srv.url | e }}/events/view/{{ e_.id | e }}" rel="noopener" target="_blank">{{ e_.info | e }}</a></li>
        {% endfor %}
      </ul>
      {% if evs | length > 10 %}
      <p class="text-muted">&hellip; and {{ evs|length - 10 }} more &mdash; use the MISP link above.</p>
      {% endif %}
      {% endif %}
    {% endfor %}
    <p class="text-muted">Details live in MISP; nothing bulky is stored here.</p>
  </div>
</div>"""

module_configuration = [
    {
        "param_name": "misp_config",
        "param_human_name": "MISP configuration",
        "param_description": "Configure one or several MISP instances",
        "default": "{\n"
        "   \"name\": \"Public_MISP\",\n"
        "   \"type\":\"public\",\n"
        "   \"url\":[\"https://URL\"],\n"
        "   \"key\":[\"APIKEY\"],\n"
        "   \"ssl\":[false]\n"
        "}",
        "mandatory": True,
        "type": "textfield_json"
    },
    {
        "param_name": "misp_http_proxy",
        "param_human_name": "MISP HTTP Proxy",
        "param_description": "HTTP Proxy parameter",
        "default": None,
        "mandatory": False,
        "type": "string"
    },
    {
        "param_name": "misp_https_proxy",
        "param_human_name": "MISP HTTPS Proxy",
        "param_description": "HTTPS Proxy parameter",
        "default": None,
        "mandatory": False,
        "type": "string"
    },
    {
        "param_name": "misp_report_as_attribute",
        "param_human_name": "Add MISP report as new IOC attribute",
        "param_description": "Creates a new attribute on the IOC, base on the MISP report. Attributes are based "
                             "on the templates of this configuration",
        "default": True,
        "mandatory": True,
        "type": "bool",
        "section": "Insights"
    },
    {
        "param_name": "misp_domain_report_template",
        "param_human_name": "Domain report template",
        "param_description": "Domain report template used to add a new custom attribute to the target IOC",
        "default": LEAN_MISP_TEMPLATE,
        "mandatory": False,
        "type": "textfield_html",
        "section": "Templates"
    },
    {
        "param_name": "misp_ip_report_template",
        "param_human_name": "IP report template",
        "param_description": "IP report template used to add a new custom attribute to the target IOC",
        "default": LEAN_MISP_TEMPLATE,
        "mandatory": False,
        "type": "textfield_html",
        "section": "Templates"
    },
    {
        "param_name": "misp_hash_report_template",
        "param_human_name": "Hash report template",
        "param_description": "Hash report template used to add a new custom attribute to the target IOC",
        "default": LEAN_MISP_TEMPLATE,
        "mandatory": False,
        "type": "textfield_html",
        "section": "Templates"
    },
    {
        "param_name": "misp_ja3_report_template",
        "param_human_name": "JA3 report template",
        "param_description": "JA3 report template used to add a new custom attribute to the target IOC",
        "default": LEAN_MISP_TEMPLATE,
        "mandatory": False,
        "type": "textfield_html",
        "section": "Templates"
    },
    {
        "param_name": "misp_manual_hook_enabled",
        "param_human_name": "Manual triggers on IOCs",
        "param_description": "Set to True to offers possibility to manually triggers the module via the UI",
        "default": True,
        "mandatory": True,
        "type": "bool",
        "section": "Triggers"
    },
    {
        "param_name": "misp_on_create_hook_enabled",
        "param_human_name": "Triggers automatically on IOC create",
        "param_description": "Set to True to automatically add a MISP insight each time an IOC is created",
        "default": False,
        "mandatory": True,
        "type": "bool",
        "section": "Triggers"
    },
    {
        "param_name": "misp_on_update_hook_enabled",
        "param_human_name": "Triggers automatically on IOC update",
        "param_description": "Set to True to automatically add a MISP insight each time an IOC is updated",
        "default": False,
        "mandatory": True,
        "type": "bool",
        "section": "Triggers"
    }
]
