#!/usr/bin/env python3
#
#  IRIS MISP Sync Module Source Code
#

module_name = "IrisMISPSync"
module_description = "Synchronize IRIS cases and IOCs to MISP events and attributes"
interface_version = "1.2.0"
module_version = "0.1.0"
pipeline_support = False
pipeline_info = {}

module_configuration = [
    {
        "param_name": "misp_sync_url",
        "param_human_name": "MISP URL",
        "param_description": "Base URL of the target MISP instance",
        "default": "https://misp.example.com",
        "mandatory": True,
        "type": "string",
        "section": "Connection"
    },
    {
        "param_name": "misp_sync_api_key",
        "param_human_name": "MISP API key",
        "param_description": "API key used for MISP event and attribute synchronization",
        "default": "",
        "mandatory": True,
        "type": "string",
        "section": "Connection"
    },
    {
        "param_name": "misp_sync_verify_tls",
        "param_human_name": "Verify TLS",
        "param_description": "Validate the MISP TLS certificate during API calls",
        "default": True,
        "mandatory": True,
        "type": "bool",
        "section": "Connection"
    },
    {
        "param_name": "misp_sync_http_proxy",
        "param_human_name": "HTTP Proxy",
        "param_description": "Optional HTTP proxy used for MISP API requests",
        "default": None,
        "mandatory": False,
        "type": "string",
        "section": "Connection"
    },
    {
        "param_name": "misp_sync_https_proxy",
        "param_human_name": "HTTPS Proxy",
        "param_description": "Optional HTTPS proxy used for MISP API requests",
        "default": None,
        "mandatory": False,
        "type": "string",
        "section": "Connection"
    },
    {
        "param_name": "misp_sync_org_id",
        "param_human_name": "Organisation ID",
        "param_description": "MISP organisation ID used for newly created events",
        "default": 31,
        "mandatory": True,
        "type": "int",
        "section": "Event defaults"
    },
    {
        "param_name": "misp_sync_distribution",
        "param_human_name": "Event distribution",
        "param_description": "Default MISP event distribution value",
        "default": 4,
        "mandatory": True,
        "type": "int",
        "section": "Event defaults"
    },
    {
        "param_name": "misp_sync_sharing_group_id",
        "param_human_name": "Sharing group ID",
        "param_description": "Optional MISP sharing group ID applied to newly created events",
        "default": 1,
        "mandatory": False,
        "type": "int",
        "section": "Event defaults"
    },
    {
        "param_name": "misp_sync_threat_level_id",
        "param_human_name": "Threat level ID",
        "param_description": "Default MISP threat level ID for newly created events",
        "default": 2,
        "mandatory": True,
        "type": "int",
        "section": "Event defaults"
    },
    {
        "param_name": "misp_sync_analysis",
        "param_human_name": "Analysis state",
        "param_description": "Default MISP analysis state for newly created events",
        "default": 1,
        "mandatory": True,
        "type": "int",
        "section": "Event defaults"
    },
    {
        "param_name": "misp_sync_attribute_to_ids",
        "param_human_name": "Mark attributes for IDS",
        "param_description": "Sets the MISP to_ids flag on synchronized attributes",
        "default": True,
        "mandatory": True,
        "type": "bool",
        "section": "Attribute defaults"
    },
    {
        "param_name": "misp_sync_tlp_distribution_policy",
        "param_human_name": "TLP distribution policy",
        "param_description": "JSON mapping of IRIS TLP names to MISP attribute distribution values",
        "default": "{\n"
                   "  \"clear\": 5,\n"
                   "  \"green\": 5,\n"
                   "  \"white\": 5,\n"
                   "  \"amber\": 0,\n"
                   "  \"amber+strict\": 0,\n"
                   "  \"red\": 0\n"
                   "}",
        "mandatory": True,
        "type": "textfield_json",
        "section": "Attribute defaults"
    },
    {
        "param_name": "misp_sync_tag_sync_enabled",
        "param_human_name": "Sync IRIS tags",
        "param_description": "Push IRIS case and IOC tags to MISP",
        "default": True,
        "mandatory": True,
        "type": "bool",
        "section": "Behavior"
    },
    {
        "param_name": "misp_sync_case_create_enabled",
        "param_human_name": "Trigger on case create",
        "param_description": "Create a MISP event when a new IRIS case is created",
        "default": True,
        "mandatory": True,
        "type": "bool",
        "section": "Triggers"
    },
    {
        "param_name": "misp_sync_case_update_enabled",
        "param_human_name": "Trigger on case update",
        "param_description": "Refresh MISP event metadata when an IRIS case is updated",
        "default": True,
        "mandatory": True,
        "type": "bool",
        "section": "Triggers"
    },
    {
        "param_name": "misp_sync_ioc_create_enabled",
        "param_human_name": "Trigger on IOC create",
        "param_description": "Create a MISP attribute when a new IRIS IOC is added",
        "default": True,
        "mandatory": True,
        "type": "bool",
        "section": "Triggers"
    },
    {
        "param_name": "misp_sync_ioc_update_enabled",
        "param_human_name": "Trigger on IOC update",
        "param_description": "Update the linked MISP attribute when an IRIS IOC changes",
        "default": True,
        "mandatory": True,
        "type": "bool",
        "section": "Triggers"
    },
    {
        "param_name": "misp_sync_ai_enabled",
        "param_human_name": "Enable AI type fallback",
        "param_description": "Use an OpenAI-compatible LLM to resolve IRIS IOC types that have no direct MISP attribute-type mapping (account, file-path, ip-any)",
        "default": False,
        "mandatory": False,
        "type": "bool",
        "section": "AI fallback"
    },
    {
        "param_name": "misp_sync_ai_url",
        "param_human_name": "AI backend URL",
        "param_description": "OpenAI-compatible base URL (e.g. http://<your-lm-studio-host>:1234/v1 for local LM Studio)",
        "default": "",
        "mandatory": False,
        "type": "string",
        "section": "AI fallback"
    },
    {
        "param_name": "misp_sync_ai_api_key",
        "param_human_name": "AI backend API key",
        "param_description": "Bearer token for the AI backend",
        "default": "",
        "mandatory": False,
        "type": "string",
        "section": "AI fallback"
    },
    {
        "param_name": "misp_sync_ai_model",
        "param_human_name": "AI model",
        "param_description": "Model name passed to the OpenAI-compatible chat-completions endpoint",
        "default": "openai/gpt-oss-20b",
        "mandatory": False,
        "type": "string",
        "section": "AI fallback"
    },
    {
        "param_name": "misp_sync_ai_confidence_threshold",
        "param_human_name": "AI confidence threshold",
        "param_description": "Minimum AI confidence (0.0-1.0) required to accept the suggested MISP type. Below this, sync is skipped and the suggestion is logged for analyst review.",
        "default": 0.70,
        "mandatory": False,
        "type": "float",
        "section": "AI fallback"
    }
]
