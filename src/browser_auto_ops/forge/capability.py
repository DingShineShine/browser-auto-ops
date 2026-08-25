from __future__ import annotations

import copy
import json
import re
from typing import Any


_PROXY_URL = "/a/media_hub/report/proxy"
_REPORTS_PATH = "/partner/v1/reports"
_ERROR_JSON_PATH = "$.error"
_JSON_HEADERS = {
    "Content-Type": "application/json",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json",
}


def discover_capabilities(summary: dict[str, Any], goal: str, parameters: list[dict[str, Any]]) -> dict[str, Any]:
    """Discover stable replay capabilities before falling back to DOM replay."""

    goal_text = goal.strip()
    candidates: list[dict[str, Any]] = []
    wayfair = _discover_wayfair_report_proxy(summary, parameters)
    if wayfair:
        candidates.append(wayfair)
    selected = _select_candidate(candidates)
    return {
        "attempted": ["api", "dom_helper", "ui_replay"],
        "candidates": candidates,
        "selected": selected,
        "strategy": selected.get("strategy") if selected else "ui_replay",
        "reason": selected.get("reason") if selected else "no transparent API capability found",
        "goal": goal_text,
    }


def apply_capability_plan(steps: list[dict[str, Any]], plan: dict[str, Any]) -> list[dict[str, Any]]:
    selected = plan.get("selected") if isinstance(plan.get("selected"), dict) else None
    capability_steps = selected.get("workflow_steps") if isinstance(selected, dict) else None
    if not capability_steps:
        return steps
    auth_steps = [step for step in steps if isinstance(step, dict) and step.get("branch") == "auth"]
    diagnostic_steps: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict) or step.get("branch") == "auth":
            continue
        row = copy.deepcopy(step)
        row["replay"] = False
        row["purpose"] = "diagnostic"
        row["superseded_by"] = selected.get("id")
        diagnostic_steps.append(row)
    return auth_steps + [copy.deepcopy(step) for step in capability_steps if isinstance(step, dict)] + diagnostic_steps


def _discover_wayfair_report_proxy(summary: dict[str, Any], parameters: list[dict[str, Any]]) -> dict[str, Any] | None:
    observed = _observed_wayfair_create_request(summary)
    if not observed:
        return None
    body = _wayfair_create_body(observed, parameters)
    report_name = str(body.get("name") or "{report_name}")
    filename_template = "{report_name}.csv" if _has_parameter(parameters, "report_name") else f"{report_name}.csv"
    steps = [
        _wayfair_create_step(body),
        _wayfair_poll_step(report_name),
        _wayfair_download_step(filename_template),
    ]
    return {
        "id": "wayfair_report_proxy_api",
        "kind": "api_capability",
        "strategy": "api_first",
        "stability_score": 0.92 if observed else 0.78,
        "reason": "Wayfair report proxy exposes create/list/download operations through authenticated page fetch",
        "input_parameters": _parameter_names(parameters),
        "output_fields": ["report_id", "status", "filename"],
        "validators": [
            {"type": "http_status", "expected": 200},
            {"type": "json_path", "path": "$.ok", "equals": True},
            {"type": "artifact", "assertions": ["exists", "non_empty"]},
        ],
        "evidence": {
            "observed_proxy_request": bool(observed),
            "proxy_url": _PROXY_URL,
            "operation": _REPORTS_PATH,
        },
        "workflow_steps": steps,
    }


def _observed_wayfair_create_request(summary: dict[str, Any]) -> dict[str, Any] | None:
    proxy_requests = _wayfair_proxy_requests(summary)
    for post_data in proxy_requests:
        if _is_create_report_request(post_data):
            body = post_data.get("body")
            return body if isinstance(body, dict) else None
    return None


def _wayfair_proxy_requests(summary: dict[str, Any]) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for item in summary.get("network") or []:
        if not isinstance(item, dict):
            continue
        if _PROXY_URL not in str(item.get("url") or item.get("path") or ""):
            continue
        post_data = _parse_json(item.get("post_data"))
        if isinstance(post_data, dict):
            requests.append(post_data)
    return requests


def _is_create_report_request(post_data: dict[str, Any]) -> bool:
    return str(post_data.get("path") or "") == _REPORTS_PATH and str(post_data.get("method") or "").upper() == "POST"


def _wayfair_create_body(observed: dict[str, Any] | None, parameters: list[dict[str, Any]]) -> dict[str, Any]:
    body = copy.deepcopy(observed) if observed else {}
    body.setdefault("reportType", "SKU_REPORT")
    body.setdefault("campaignType", "WSP")
    body.setdefault("timeDimension", "DAY")
    body.setdefault("fileType", "CSV")
    body.setdefault("attributionWindow", 14)
    body["name"] = _report_name_template(str(body.get("name") or "wayfair_report"), parameters)
    filters = body.get("filters") if isinstance(body.get("filters"), dict) else {}
    if _has_parameter(parameters, "start_date"):
        filters["startDate"] = "{start_date.iso} 00:00:00"
    else:
        filters.setdefault("startDate", "")
    if _has_parameter(parameters, "end_date"):
        filters["endDate"] = "{end_date.iso} 00:00:00"
    else:
        filters.setdefault("endDate", "")
    body["filters"] = filters
    return body


def _wayfair_create_step(body: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "api_create_report",
        "type": "api_call",
        "purpose": "business_action",
        "intent": "create Wayfair WSP Product Report through report proxy API",
        "description": "create report with authenticated page API instead of replaying report form widgets",
        "request": {
            "execution_context": "page_fetch",
            "method": "POST",
            "url": _PROXY_URL,
            "headers": _JSON_HEADERS,
            "body_template": {
                "path": _REPORTS_PATH,
                "method": "POST",
                "body": body,
            },
        },
        "success_predicate": {"json_path": "$.ok", "equals": True},
        "failure_predicate": {"json_path": _ERROR_JSON_PATH, "equals": True},
        "replay": True,
    }


def _wayfair_poll_step(report_name: str) -> dict[str, Any]:
    script = r"""
(async function() {
  try {
    const wanted = "__REPORT_NAME__";
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    for (let attempt = 1; attempt <= 120; attempt++) {
      const res = await fetch('/a/media_hub/report/proxy', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
          'Accept': 'application/json'
        },
        credentials: 'include',
        body: JSON.stringify({path: '/partner/v1/reports', method: 'GET'})
      });
      const reports = await res.json();
      const matches = (Array.isArray(reports) ? reports : [])
        .filter((row) => row && row.name === wanted)
        .sort((a, b) => String(b.dateCreatedUTC || '').localeCompare(String(a.dateCreatedUTC || '')));
      const completed = matches.find((row) => String(row.status || '').toLowerCase().startsWith('complete')) || null;
      const latest = completed || matches[0] || null;
      const status = String(latest && latest.status || '').toLowerCase();
      if (completed) {
        return JSON.stringify({
          ok: true,
          status: completed.status,
          report_id: completed.id,
          filename: completed.name ? completed.name + '.csv' : '',
          latest: completed
        });
      }
      if (latest && /failed|error/i.test(String(latest.status || latest.message || ''))) {
        return JSON.stringify({ok: false, report_id: latest.id, status: latest.status, message: latest.message || 'report failed'});
      }
      await sleep(5000);
    }
    return JSON.stringify({ok: false, message: 'report did not complete before timeout'});
  } catch (e) {
    return JSON.stringify({error: true, message: e.message});
  }
})()
""".strip().replace("__REPORT_NAME__", report_name)
    return {
        "id": "api_poll_report_status",
        "type": "api_call",
        "purpose": "business_action",
        "intent": "poll generated Wayfair report status and capture report id",
        "description": "poll report list API until the requested report is complete",
        "script": script,
        "outputs": {
            "report_id": "$.report_id",
            "filename": "$.filename",
            "status": "$.status",
        },
        "success_predicate": {"json_path": "$.ok", "equals": True},
        "failure_predicate": {"json_path": _ERROR_JSON_PATH, "equals": True},
        "replay": True,
    }


def _wayfair_download_step(filename_template: str) -> dict[str, Any]:
    return {
        "id": "api_download_report",
        "type": "api_call",
        "purpose": "artifact",
        "intent": "download Wayfair report CSV through report proxy API",
        "description": "download report bytes via authenticated page API and save as artifact",
        "uses": {
            "report_id": "{outputs.api_poll_report_status.report_id}",
            "filename": "{outputs.api_poll_report_status.filename}",
        },
        "request": {
            "execution_context": "page_fetch",
            "method": "POST",
            "url": _PROXY_URL,
            "headers": _JSON_HEADERS,
            "response_mode": "base64",
            "body_template": {
                "path": "/partner/v1/reports/{outputs.api_poll_report_status.report_id}/download",
                "method": "GET",
            },
        },
        "artifact": {
            "name": "wayfair_report_csv",
            "source": "page_fetch",
            "filename_template": filename_template,
            "output_dir": "{output_dir}",
            "validators": [{"type": "exists"}, {"type": "non_empty"}, {"type": "extension", "value": ".csv"}],
        },
        "success_predicate": {"json_path": "$.ok", "equals": True},
        "failure_predicate": {"json_path": _ERROR_JSON_PATH, "equals": True},
        "replay": True,
    }


def _select_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None
    return max(candidates, key=lambda item: float(item.get("stability_score") or 0))


def _parameter_names(parameters: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("name")) for item in parameters if isinstance(item, dict) and item.get("name")]


def _has_parameter(parameters: list[dict[str, Any]], name: str) -> bool:
    return any(isinstance(item, dict) and item.get("name") == name for item in parameters)


def _report_name_template(value: str, parameters: list[dict[str, Any]]) -> str:
    if _has_parameter(parameters, "report_name"):
        return "{report_name}"
    if _has_parameter(parameters, "end_date"):
        return re.sub(r"\d{4}-\d{2}-\d{2}", "{end_date.iso}", value, count=1)
    return value


def _parse_json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return json.loads(value)
    except Exception:
        return None
