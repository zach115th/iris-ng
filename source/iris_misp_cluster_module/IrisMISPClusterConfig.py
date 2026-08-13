#!/usr/bin/env python3
#
#  IRIS MISP Cluster Module Source Code
#

module_name = "IrisMISPCluster"
module_description = (
    "Publish a cross-case IOC correlation cluster to MISP as a single campaign "
    "event, carrying the cluster's shared IOCs, their tags, and the analyst "
    "notes linked to them"
)
interface_version = "1.2.0"
module_version = "0.1.0"
pipeline_support = False
pipeline_info = {}

module_configuration = [
    {
        "param_name": "misp_cluster_url",
        "param_human_name": "MISP URL",
        "param_description": "Base URL of the MISP instance (e.g. https://misp.example.com)",
        "default": "https://misp.example.com",
        "mandatory": True,
        "type": "string",
        "section": "Connection"
    },
    {
        "param_name": "misp_cluster_api_key",
        "param_human_name": "MISP API key",
        "param_description": "MISP automation key used to authenticate the push",
        "default": "",
        "mandatory": True,
        "type": "string",
        "section": "Connection"
    },
    {
        "param_name": "misp_cluster_verify_tls",
        "param_human_name": "Verify TLS",
        "param_description": (
            "Verify the MISP TLS certificate. Uncheck for a self-signed or "
            "private-CA certificate, otherwise every push fails with "
            "SSLCertVerificationError"
        ),
        "default": True,
        "mandatory": True,
        "type": "bool",
        "section": "Connection"
    },
    {
        "param_name": "misp_cluster_http_proxy",
        "param_human_name": "HTTP proxy",
        "param_description": "Optional HTTP proxy URL",
        "default": None,
        "mandatory": False,
        "type": "string",
        "section": "Connection"
    },
    {
        "param_name": "misp_cluster_https_proxy",
        "param_human_name": "HTTPS proxy",
        "param_description": "Optional HTTPS proxy URL",
        "default": None,
        "mandatory": False,
        "type": "string",
        "section": "Connection"
    },
    {
        "param_name": "misp_cluster_org_id",
        "param_human_name": "Organisation ID",
        "param_description": "MISP organisation ID that owns the created campaign events",
        "default": 1,
        "mandatory": True,
        "type": "int",
        "section": "Event defaults"
    },
    {
        "param_name": "misp_cluster_distribution",
        "param_human_name": "Event distribution",
        "param_description": (
            "MISP distribution level for the campaign event: 0 = your org only, "
            "1 = this community, 2 = connected communities, 3 = all communities, "
            "4 = sharing group"
        ),
        "default": 0,
        "mandatory": True,
        "type": "int",
        "section": "Event defaults"
    },
    {
        "param_name": "misp_cluster_sharing_group_id",
        "param_human_name": "Sharing group ID",
        "param_description": "Sharing group used when distribution is 4",
        "default": 1,
        "mandatory": False,
        "type": "int",
        "section": "Event defaults"
    },
    {
        "param_name": "misp_cluster_threat_level_id",
        "param_human_name": "Threat level",
        "param_description": "1 = High, 2 = Medium, 3 = Low, 4 = Undefined",
        "default": 2,
        "mandatory": True,
        "type": "int",
        "section": "Event defaults"
    },
    {
        "param_name": "misp_cluster_analysis",
        "param_human_name": "Analysis state",
        "param_description": "0 = Initial, 1 = Ongoing, 2 = Complete",
        "default": 1,
        "mandatory": True,
        "type": "int",
        "section": "Event defaults"
    },
    {
        "param_name": "misp_cluster_attribute_to_ids",
        "param_human_name": "Set to_ids on attributes",
        "param_description": "Mark pushed indicators as actionable for detection (to_ids)",
        "default": True,
        "mandatory": True,
        "type": "bool",
        "section": "Event defaults"
    },
    {
        "param_name": "misp_cluster_galaxy_enabled",
        "param_human_name": "Apply campaign galaxy tag",
        "param_description": (
            "Tag the event with misp-galaxy:campaign=\"<name>\" using the "
            "AI-suggested (or analyst-corrected) campaign name"
        ),
        "default": True,
        "mandatory": False,
        "type": "bool",
        "section": "Content"
    },
    {
        "param_name": "misp_cluster_tag_sync_enabled",
        "param_human_name": "Push IOC tags",
        "param_description": "Copy each IOC's iris-ng tags onto the corresponding MISP attribute",
        "default": True,
        "mandatory": False,
        "type": "bool",
        "section": "Content"
    },
    {
        "param_name": "misp_cluster_notes_enabled",
        "param_human_name": "Push linked analyst notes",
        "param_description": (
            "Attach notes linked to the pushed IOCs via the ioc_note_link "
            "provenance table. Only deliberately-linked notes are sent — case "
            "notes at large are never pushed"
        ),
        "default": True,
        "mandatory": False,
        "type": "bool",
        "section": "Content"
    },
    {
        "param_name": "misp_cluster_redact_enabled",
        "param_human_name": "Redact entity names",
        "param_description": (
            "Replace client and organisation names with [redacted] in the "
            "narrative and in pushed notes before they reach MISP. IOC values "
            "are never redacted — a lookalike domain containing the victim's "
            "name is the intelligence"
        ),
        "default": True,
        "mandatory": False,
        "type": "bool",
        "section": "Redaction"
    },
    {
        "param_name": "misp_cluster_redact_terms",
        "param_human_name": "Additional terms to redact",
        "param_description": (
            "Comma-separated extra terms to redact, for names the client record "
            "does not cover — divisions, subsidiaries, internal project names, "
            "executive titles (e.g. Applied Sciences, WayneTech, Wayne Foundation)"
        ),
        "default": "",
        "mandatory": False,
        "type": "string",
        "section": "Redaction"
    },
    {
        "param_name": "misp_cluster_note_max_chars",
        "param_human_name": "Max characters per note",
        "param_description": "Notes longer than this are truncated before being pushed",
        "default": 4000,
        "mandatory": False,
        "type": "int",
        "section": "Content"
    },
    {
        "param_name": "misp_cluster_tlp_tag",
        "param_human_name": "TLP tag for the event",
        "param_description": (
            "TLP tag applied to the campaign event. Correlation only surfaces "
            "TLP:GREEN and TLP:CLEAR indicators, so tlp:green is the correct default"
        ),
        "default": "tlp:green",
        "mandatory": False,
        "type": "string",
        "section": "Content"
    },
]
