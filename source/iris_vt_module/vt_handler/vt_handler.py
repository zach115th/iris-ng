#!/usr/bin/env python3
#
#  IRIS VT Module - VirusTotal API v3 handler
#  (iris-ng in-tree fork of iris-vt-module; behaviour mirrors the v2-API
#  module - same hooks, same insights, same attribute tab - with the API
#  swapped to v3 and the template context mapped for compatibility.)
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
import traceback

import iris_interface.IrisInterfaceStatus as InterfaceStatus
from app.datamgmt.manage.manage_attribute_db import add_tab_attribute_field

from iris_vt_module.vt_handler.vt3_client import VT3Client, VT3Error, \
    map_file_report, map_domain_report, map_ip_report
from iris_vt_module.vt_handler.vt_helper import detection_ratio, \
    gen_domain_report_from_template, gen_ip_report_from_template, gen_hash_report_from_template


class VtHandler(object):
    def __init__(self, mod_config, server_config, logger):
        self.mod_config = mod_config
        self.server_config = server_config
        self.log = logger
        self.vt = self.get_vt_instance()

    def get_vt_instance(self):
        """API v3 client. No public/private split - v3 quota rides the key."""
        api_key = self.mod_config.get('vt_api_key')
        proxies = {}

        if self.server_config.get('http_proxy'):
            proxies['http'] = self.server_config.get('http_proxy')

        if self.server_config.get('https_proxy'):
            proxies['https'] = self.server_config.get('https_proxy')

        return VT3Client(api_key, proxies=proxies)

    def tag_if_malicious_or_suspicious(self, context, ioc):
        """Tag an IOC if the detection ratio is above the configured
        thresholds; below both, previously-set vt: tags are removed
        (same contract as the v2-API module)."""
        avg_detected_ratio = detection_ratio(context)

        if avg_detected_ratio is None:
            return

        if ioc.ioc_tags is None:
            ioc.ioc_tags = ""

        if float(self.mod_config.get('vt_tag_malicious_threshold')) <= float(avg_detected_ratio):
            if 'vt:malicious' not in ioc.ioc_tags.split(','):
                ioc.ioc_tags = f"{ioc.ioc_tags},vt:malicious"

        elif float(self.mod_config.get('vt_tag_suspicious_threshold')) <= float(avg_detected_ratio):
            if 'vt:suspicious' not in ioc.ioc_tags.split(','):
                ioc.ioc_tags = f"{ioc.ioc_tags},vt:suspicious"

        else:
            if 'vt:suspicious' in ioc.ioc_tags.split(','):
                ioc.ioc_tags = ioc.ioc_tags.replace('vt:suspicious', '').replace(',,', ',')
            if 'vt:malicious' in ioc.ioc_tags.split(','):
                ioc.ioc_tags = ioc.ioc_tags.replace('vt:malicious', '').replace(',,', ',')

    def _store_report(self, ioc, rendered_report):
        try:
            add_tab_attribute_field(ioc, tab_name='VT Report', field_name="HTML report", field_type="html",
                                    field_value=rendered_report)
        except Exception:
            self.log.error(traceback.format_exc())
            return InterfaceStatus.I2Error(traceback.format_exc())
        return InterfaceStatus.I2Success()

    def handle_vt_domain(self, ioc):
        """Handles an IOC of type domain and adds VT insights."""
        self.log.info(f'Getting domain report for {ioc.ioc_value}')
        try:
            raw = self.vt.domain_report(ioc.ioc_value)

            need_subdomains = (self.mod_config.get('vt_domain_add_subdomain_as_desc') is True
                               or self.mod_config.get('vt_report_as_attribute') is True)
            subdomains = []
            if need_subdomains:
                try:
                    rel = self.vt.relationship(f"/domains/{ioc.ioc_value}", "subdomains")
                    subdomains = [row.get('id') for row in rel.get('data', []) if row.get('id')]
                except VT3Error as e:
                    # optional context - a missing relationship must not fail enrichment
                    self.log.warning(f'Could not fetch subdomains: {e.message}')

            resolutions = []
            if self.mod_config.get('vt_report_as_attribute') is True:
                try:
                    rel = self.vt.relationship(f"/domains/{ioc.ioc_value}", "resolutions")
                    resolutions = rel.get('data', [])
                except VT3Error as e:
                    self.log.warning(f'Could not fetch resolutions: {e.message}')

        except VT3Error as e:
            self.log.error(f'VT API error for {ioc.ioc_value} :: {e}')
            return InterfaceStatus.I2Error(str(e))

        report = map_domain_report(raw, ioc.ioc_value, subdomains=subdomains, resolutions=resolutions)
        results = report.get('results')

        self.tag_if_malicious_or_suspicious(context=results, ioc=ioc)

        if self.mod_config.get('vt_domain_add_whois_as_desc') is True:
            if ioc.ioc_description is None:
                ioc.ioc_description = ""
            if "WHOIS" not in ioc.ioc_description:
                if results.get('whois'):
                    self.log.info('Adding WHOIS information to IOC description')
                    ioc.ioc_description = f"{ioc.ioc_description}\n\nWHOIS\n{results.get('whois')}"
                else:
                    self.log.info('No WHOIS in VT report')
            else:
                self.log.info('Skipped adding WHOIS. Information already present')
        else:
            self.log.info('Skipped adding WHOIS. Option disabled')

        if self.mod_config.get('vt_domain_add_subdomain_as_desc') is True:
            if ioc.ioc_description is None:
                ioc.ioc_description = ""
            if "Subdomains" not in ioc.ioc_description:
                if subdomains:
                    subd_data = "".join(f"- {subd}\n" for subd in subdomains)
                    self.log.info('Adding subdomains information to IOC description')
                    ioc.ioc_description = f"{ioc.ioc_description}\n\nSubdomains\n{subd_data}"
                else:
                    self.log.info('No subdomains in VT report')
            else:
                self.log.info('Skipped adding subdomains information. Information already present')
        else:
            self.log.info('Skipped adding subdomain information. Option disabled')

        if self.mod_config.get('vt_report_as_attribute') is True:
            self.log.info('Adding new attribute VT Domain Report to IOC')
            status = gen_domain_report_from_template(html_template=self.mod_config.get('vt_domain_report_template'),
                                                     vt_report=report)
            if not status.is_success():
                return status
            return self._store_report(ioc, status.get_data())

        self.log.info('Skipped adding attribute report. Option disabled')
        return InterfaceStatus.I2Success()

    def handle_vt_ip(self, ioc):
        """Handles an IOC of type IP and adds VT insights."""
        self.log.info(f'Getting IP report for {ioc.ioc_value}')
        try:
            raw = self.vt.ip_report(ioc.ioc_value)

            resolutions = []
            if self.mod_config.get('vt_report_as_attribute') is True:
                try:
                    rel = self.vt.relationship(f"/ip_addresses/{ioc.ioc_value}", "resolutions")
                    resolutions = rel.get('data', [])
                except VT3Error as e:
                    self.log.warning(f'Could not fetch resolutions: {e.message}')

        except VT3Error as e:
            self.log.error(f'VT API error for {ioc.ioc_value} :: {e}')
            return InterfaceStatus.I2Error(str(e))

        report = map_ip_report(raw, ioc.ioc_value, resolutions=resolutions)
        results = report.get('results')

        self.tag_if_malicious_or_suspicious(context=results, ioc=ioc)

        if self.mod_config.get('vt_ip_assign_asn_as_tag') is True:
            self.log.info('Assigning new ASN tag to IOC.')
            asn = results.get('asn')
            if asn is None:
                self.log.info('ASN was null - skipping')
            else:
                if ioc.ioc_tags is None:
                    ioc.ioc_tags = ""
                if f'ASN:{asn}' not in ioc.ioc_tags.split(','):
                    ioc.ioc_tags = f"{ioc.ioc_tags},ASN:{asn}"
                else:
                    self.log.info('ASN already tagged for this IOC. Skipping')

        if self.mod_config.get('vt_report_as_attribute') is True:
            self.log.info('Adding new attribute VT IP Report to IOC')
            status = gen_ip_report_from_template(html_template=self.mod_config.get('vt_ip_report_template'),
                                                 vt_report=report)
            if not status.is_success():
                return status
            return self._store_report(ioc, status.get_data())

        self.log.info('Skipped adding attribute report. Option disabled')
        return InterfaceStatus.I2Success("Successfully processed IP")

    def handle_vt_hash(self, ioc):
        """Handles an IOC of type hash and adds VT insights."""
        self.log.info(f'Getting hash report for {ioc.ioc_value}')
        try:
            raw = self.vt.file_report(ioc.ioc_value)
        except VT3Error as e:
            self.log.error(f'VT API error for {ioc.ioc_value} :: {e}')
            return InterfaceStatus.I2Error(str(e))

        report = map_file_report(raw, ioc.ioc_value)
        results = report.get('results')

        self.tag_if_malicious_or_suspicious(context=results, ioc=ioc)

        if self.mod_config.get('vt_report_as_attribute') is True:
            self.log.info('Generating report from template')
            status = gen_hash_report_from_template(html_template=self.mod_config.get('vt_hash_report_template'),
                                                   vt_report=report)
            if not status.is_success():
                return status
            self.log.info('Adding new attribute VT hash Report to IOC')
            return self._store_report(ioc, status.get_data())

        self.log.info('Skipped adding attribute report. Option disabled')
        return InterfaceStatus.I2Success("Successfully processed hash")
