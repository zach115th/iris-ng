import requests
import json
from urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

headers = {
    "Authorization": "Bearer <redacted-api-key>",
    "Content-Type": "application/json"
}

payload = {
    "cid": 40,
    "event_date": "2026-07-10T14:30:00",
    "event_tz": "+00:00",
    "event_title": "Test Event",
    "event_category_id": 18,
    "event_content": "Test content",
    "event_source": "Test",
    "event_assets": [],
    "event_iocs": []
}

resp = requests.post(
    "https://localhost/case/timeline/events/add",
    json=payload,
    headers=headers,
    verify=False
)

print(f"Status: {resp.status_code}")
result = resp.json()
print(f"Result: {json.dumps(result, indent=2)}")
