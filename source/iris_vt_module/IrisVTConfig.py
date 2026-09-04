#!/usr/bin/env python3
#
#  IRIS VT Module - VirusTotal API v3 (iris-ng in-tree fork of iris-vt-module)
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

module_name = "IrisVT"
module_description = "Provides an interface between VirusTotal (API v3) and IRIS"
interface_version = "1.2.0"
module_version = "2.0.0"
pipeline_support = False
pipeline_info = {}

# Lean v3 default templates: highlights plus a permalink, per the iris-ng
# enrichment philosophy - the analyst follows the link for the full analysis
# and nothing bulky is stored on the IOC. Admin-set template values in an
# existing install are PRESERVED by reconcile_module_configurations(); these
# defaults apply to fresh installs only.
#
# Template context (v2-compatible keys kept so older custom templates still
# render): results.positives (malicious engine count), results.suspicious,
# results.total (engines that returned a verdict), results.stats (the raw
# last_analysis_stats dict), results.permalink, results.scan_date (UTC),
# results.threat_label (v3 popular_threat_classification, hashes only),
# results.md5/sha1/sha256/names (hashes), results.scans (per-engine table,
# v2 shape), results.whois/subdomains/resolutions (domains),
# results.asn/as_owner/country/resolutions (IPs).

_HASH_TEMPLATE = """<div class="row">
  <div class="col-12">
    <h3>Basic information</h3>
    <dl class="row">
      {% if results.total %}
      <dt class="col-sm-3">Detection</dt>
      <dd class="col-sm-9">{{ results.positives }} / {{ results.total }}</dd>
      {% endif %}
      {% if results.threat_label %}
      <dt class="col-sm-3">Threat label</dt>
      <dd class="col-sm-9">{{ results.threat_label | e }}</dd>
      {% endif %}
      {% if results.permalink %}
      <dt class="col-sm-3">Permalink</dt>
      <dd class="col-sm-9"><a href="{{ results.permalink | e }}" rel="noopener" target="_blank">{{ results.permalink | e }}</a></dd>
      {% endif %}
      {% if results.scan_date %}
      <dt class="col-sm-3">Scan date</dt>
      <dd class="col-sm-9">{{ results.scan_date | e }}</dd>
      {% endif %}
    </dl>
    <p class="text-muted">Full analysis via the permalink; nothing bulky is stored here.</p>
  </div>
</div>"""

_DOMAIN_TEMPLATE = """<div class="row">
  <div class="col-12">
    <h3>Basic information</h3>
    <dl class="row">
      {% if results.total %}
      <dt class="col-sm-3">Detection</dt>
      <dd class="col-sm-9">{{ results.positives }} / {{ results.total }}</dd>
      {% endif %}
      {% if results.registrar %}
      <dt class="col-sm-3">Registrar</dt>
      <dd class="col-sm-9">{{ results.registrar | e }}</dd>
      {% endif %}
      {% if results.permalink %}
      <dt class="col-sm-3">Permalink</dt>
      <dd class="col-sm-9"><a href="{{ results.permalink | e }}" rel="noopener" target="_blank">{{ results.permalink | e }}</a></dd>
      {% endif %}
      {% if results.scan_date %}
      <dt class="col-sm-3">Scan date</dt>
      <dd class="col-sm-9">{{ results.scan_date | e }}</dd>
      {% endif %}
    </dl>
    <p class="text-muted">Full analysis via the permalink; nothing bulky is stored here.</p>
  </div>
</div>"""

_IP_TEMPLATE = """<div class="row">
  <div class="col-12">
    <h3>Basic information</h3>
    <dl class="row">
      {% if results.total %}
      <dt class="col-sm-3">Detection</dt>
      <dd class="col-sm-9">{{ results.positives }} / {{ results.total }}</dd>
      {% endif %}
      {% if results.as_owner %}
      <dt class="col-sm-3">AS owner</dt>
      <dd class="col-sm-9">{{ results.as_owner | e }}{% if results.asn %} (ASN {{ results.asn | e }}){% endif %}</dd>
      {% endif %}
      {% if results.country %}
      <dt class="col-sm-3">Country</dt>
      <dd class="col-sm-9">{{ results.country | e }}</dd>
      {% endif %}
      {% if results.permalink %}
      <dt class="col-sm-3">Permalink</dt>
      <dd class="col-sm-9"><a href="{{ results.permalink | e }}" rel="noopener" target="_blank">{{ results.permalink | e }}</a></dd>
      {% endif %}
      {% if results.scan_date %}
      <dt class="col-sm-3">Scan date</dt>
      <dd class="col-sm-9">{{ results.scan_date | e }}</dd>
      {% endif %}
    </dl>
    <p class="text-muted">Full analysis via the permalink; nothing bulky is stored here.</p>
  </div>
</div>"""

module_configuration = [
    {
        "param_name": "vt_api_key",
        "param_human_name": "VT API Key",
        "param_description": "API key to use to communicate with VT (API v3)",
        "default": None,
        "mandatory": True,
        "type": "sensitive_string"
    },
    {
        "param_name": "vt_manual_hook_enabled",
        "param_human_name": "Manual triggers on IOCs",
        "param_description": "Set to True to offers possibility to manually triggers the module via the UI",
        "default": True,
        "mandatory": True,
        "type": "bool",
        "section": "Triggers"
    },
    {
        "param_name": "vt_on_update_hook_enabled",
        "param_human_name": "Triggers automatically on IOC update",
        "param_description": "Set to True to automatically add a VT insight each time an IOC is updated",
        "default": False,
        "mandatory": True,
        "type": "bool",
        "section": "Triggers"
    },
    {
        "param_name": "vt_on_create_hook_enabled",
        "param_human_name": "Triggers automatically on IOC create",
        "param_description": "Set to True to automatically add a VT insight each time an IOC is created",
        "default": False,
        "mandatory": True,
        "type": "bool",
        "section": "Triggers"
    },
    {
        "param_name": "vt_ip_assign_asn_as_tag",
        "param_human_name": "Assign ASN tag to IP",
        "param_description": "Assign a new tag to IOC IPs with the ASN fetched from VT",
        "default": True,
        "mandatory": True,
        "type": "bool",
        "section": "Insights"
    },
    {
        "param_name": "vt_tag_malicious_threshold",
        "param_human_name": "IOC tag malicious threshold",
        "param_description": "Tag the IOC has malicious if the percentage of detection is above the specified threshold",
        "default": "10",
        "mandatory": True,
        "type": "float",
        "section": "Insights"
    },
    {
        "param_name": "vt_tag_suspicious_threshold",
        "param_human_name": "IOC tag suspicious threshold",
        "param_description": "Tag the IOC has suspicious if the percentage of detection is above the specified "
                             "threshold",
        "default": "5",
        "mandatory": True,
        "type": "float",
        "section": "Insights"
    },
    {
        "param_name": "vt_domain_add_whois_as_desc",
        "param_human_name": "Add WHOIS to domain IOC description",
        "param_description": "Appends the WHOIS record from VT to the description of domain IOCs",
        "default": False,
        "mandatory": True,
        "type": "bool",
        "section": "Insights"
    },
    {
        "param_name": "vt_domain_add_subdomain_as_desc",
        "param_human_name": "Add subdomains to domain IOC description",
        "param_description": "Appends known subdomains from VT to the description of domain IOCs "
                             "(one extra API call per enrichment)",
        "default": False,
        "mandatory": True,
        "type": "bool",
        "section": "Insights"
    },
    {
        "param_name": "vt_report_as_attribute",
        "param_human_name": "Add VT report as new IOC attribute",
        "param_description": "Creates a new attribute on the IOC, base on the VT report. Attributes are based "
                             "on the templates of this configuration",
        "default": True,
        "mandatory": True,
        "type": "bool",
        "section": "Insights"
    },
    {
        "param_name": "vt_domain_report_template",
        "param_human_name": "Domain report template",
        "param_description": "Domain reports template used to add a new custom attribute to the target IOC. "
                             "Context: results.positives/total/stats/permalink/scan_date/whois/registrar/"
                             "categories/subdomains/resolutions",
        "default": _DOMAIN_TEMPLATE,
        "mandatory": False,
        "type": "textfield_html",
        "section": "Templates"
    },
    {
        "param_name": "vt_ip_report_template",
        "param_human_name": "IP report template",
        "param_description": "IP report template used to add a new custom attribute to the target IOC. "
                             "Context: results.positives/total/stats/permalink/scan_date/asn/as_owner/"
                             "country/resolutions",
        "default": _IP_TEMPLATE,
        "mandatory": False,
        "type": "textfield_html",
        "section": "Templates"
    },
    {
        "param_name": "vt_hash_report_template",
        "param_human_name": "Hash report template",
        "param_description": "Hash report template used to add a new custom attribute to the target IOC. "
                             "Context: results.positives/total/stats/permalink/scan_date/threat_label/"
                             "md5/sha1/sha256/names/scans",
        "default": _HASH_TEMPLATE,
        "mandatory": False,
        "type": "textfield_html",
        "section": "Templates"
    }
]
