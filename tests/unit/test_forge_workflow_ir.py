from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path

from browser_auto_ops.forge import ForgeEngine
from browser_auto_ops.forge.auth import auth_gate_failure
from browser_auto_ops.forge.component_scripts import write_component_scripts
from browser_auto_ops.forge.locators import locator_for_element
from browser_auto_ops.forge.ir import action_from_step
from browser_auto_ops.forge.replay import action_candidates_for_replay_step, workflow_actions, workflow_replay_steps
from browser_auto_ops.forge.tester import evaluate_skill
from browser_auto_ops.schemas import ActionResult, PageState
from browser_auto_ops.server import _artifact_valid, _collect_runtime_artifact, _semantic_step_success, _write_replay_repair_suggestion
from browser_auto_ops.sessions.payload import compact_action_payload

IR_V2_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "forge" / "ir_v2_events.jsonl"


def test_workflow_ir_preserves_wait_js_download_and_fallback(tmp_path: Path) -> None:
    trace = tmp_path / "trace"
    trace.mkdir()
    (trace / "events.jsonl").write_text(IR_V2_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    skill = ForgeEngine(tmp_path / "skills").generate(trace, "report", "download report", install=False)
    workflow = json.loads((skill / "evidence" / "workflow.json").read_text(encoding="utf-8"))
    step_types = [item["type"] for item in workflow["workflow_steps"]]

    assert workflow["schema_version"] == 2
    assert "wait_condition" in step_types
    assert "assertion" in step_types
    assert "api_call" in step_types
    assert "fallback" in step_types
    assert any(item.get("type") == "artifact" for item in workflow["validators"])
    assert workflow["artifacts"][0]["from_step"]
    assert "download-via-page-fetch.py" in workflow["component_scripts"]
    replay_types = [item["type"] for item in workflow_actions(workflow)]
    assert "wait" in replay_types
    assert "execute_js" in replay_types
    assert "click" in replay_types
    replay_steps = workflow_replay_steps(workflow)
    assert any(item["type"] == "wait_condition" for item in replay_steps)
    assert all(item.get("type") != "fallback" for item in replay_steps)


def test_generation_report_counts_workflow_steps_not_only_locators(tmp_path: Path) -> None:
    trace = tmp_path / "trace"
    trace.mkdir()
    (trace / "events.jsonl").write_text(IR_V2_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    skill = ForgeEngine(tmp_path / "skills").generate(trace, "report", "download report", install=False)
    report = json.loads((skill / "evidence" / "generation-report.json").read_text(encoding="utf-8"))

    assert report["actions"]["included"] == report["replay_plan"]["executable_steps"]
    assert report["replay_plan"]["api_calls"] == 1
    assert report["replay_plan"]["wait_conditions"] == 1
    assert report["locator_table"]["strict_locators"] == 1
    assert any(item["reason"] == "preserved_as_workflow_step" for item in report["preserved_as_workflow_step"])
    assert all(item["reason"] != "noise_action" for item in report["dropped_actions"])


def test_locator_ranking_records_actionability_and_shortest_unique_prefix() -> None:
    target = {"kind": "label", "tag": "label", "text": "Product Report", "visible": True, "enabled": True, "clickable": True}
    elements = [
        {"kind": "label", "tag": "label", "text": "Wayfair Sponsored Products Product Report", "clickable": True},
        target,
    ]

    row = locator_for_element(target, elements=elements, action="click")

    assert row["actionability"] == {"visible": True, "enabled": True, "not_occluded": True, "stable": True}
    assert row["locator_rank"]["unique"] is True
    assert row["match"]["text"] == "Product Report"
    assert row["match"]["text_mode"] == "exact"


def test_replay_prefers_recorded_request_before_strict_locator() -> None:
    step = {
        "type": "browser_action",
        "request": {
            "type": "click",
            "match": {
                "role": "label",
                "name": "Wayfair Sponsored Products (WSP)",
                "name_mode": "contains",
            },
        },
        "locator": {
            "action": "click",
            "match": {
                "kind": "label",
                "role": "label",
                "text": "Wayfair Sponsored Products (WSP)",
                "text_mode": "exact",
            },
        },
    }

    action = action_from_step(step, {})

    assert action == step["request"]


def test_replay_action_candidates_include_strict_and_relaxed_fallbacks() -> None:
    step = {
        "type": "browser_action",
        "request": {"type": "click", "match": {"role": "button", "name": "Generate Report"}},
        "locator": {
            "action": "click",
            "match": {"kind": "button", "role": "button", "text": "Generate Report", "text_mode": "exact"},
        },
    }

    candidates = action_candidates_for_replay_step(step, {})
    strategies = [item["strategy"] for item in candidates]

    assert strategies[0] == "recorded_request"
    assert "strict_locator" in strategies
    assert any(item["action"]["match"].get("kind") is None for item in candidates if item["strategy"] != "recorded_request")


def test_replay_steps_skip_any_step_marked_replay_false() -> None:
    workflow = {
        "workflow_steps": [
            {
                "id": "api_create_report",
                "type": "api_call",
                "request": {"method": "POST", "url": "/proxy"},
                "replay": True,
            },
            {
                "id": "diagnostic_create_report",
                "type": "api_call",
                "script": "fetch('/proxy')",
                "replay": False,
            },
        ]
    }

    steps = workflow_replay_steps(workflow)

    assert [step["id"] for step in steps] == ["api_create_report"]


def test_parameter_candidates_detect_dates_filenames_and_runtime_ids(tmp_path: Path) -> None:
    trace = tmp_path / "trace"
    trace.mkdir()
    report_id = "4f96d397-d6de-41f4-ae1c-4fb1626736b1"
    events = "\n".join(
        [
            '{"type":"action.request","payload":{"type":"execute_js","script":"document.body.innerText"}}',
            f'{{"type":"action.result","payload":{{"type":"execute_js","success":true,"data":"{{\\"latestId\\":\\"{report_id}\\",\\"filename\\":\\"report.csv\\"}}"}}}}',
            f'{{"type":"action.request","payload":{{"type":"execute_js","script":"fetch(\\"/reports/{report_id}/download\\")"}}}}',
            '{"type":"action.result","payload":{"type":"execute_js","success":true,"data":{"base64":"Zm9v","filename":"report.csv"}}}',
        ]
    )
    (trace / "events.jsonl").write_text(events, encoding="utf-8")

    skill = ForgeEngine(tmp_path / "skills").generate(
        trace,
        "report",
        "download report for 2026-08-22 as report.csv",
        install=False,
    )
    workflow = json.loads((skill / "evidence" / "workflow.json").read_text(encoding="utf-8"))
    skill_text = (skill / "SKILL.md").read_text(encoding="utf-8")
    candidate_values = {item["value"] for item in workflow["parameter_candidates"]}
    steps = workflow["workflow_steps"]

    assert "2026-08-22" in candidate_values
    assert "report.csv" in candidate_values
    assert report_id in candidate_values
    assert steps[0]["outputs"]["report_id"] == "$.latestId"
    assert "{outputs." in steps[1]["script"]
    assert steps[1]["uses"]["report_id"].endswith(".report_id}")
    assert "poll generated row status" in skill_text
    assert "download artifact from authenticated page API" in skill_text
    assert "Artifact Contract" in skill_text


def test_parameter_templates_and_artifact_contract_without_base64(tmp_path: Path) -> None:
    trace = tmp_path / "trace"
    trace.mkdir()
    report_id = "4f96d397-d6de-41f4-ae1c-4fb1626736b1"
    events = "\n".join(
        [
            '{"type":"action.request","payload":{"type":"execute_js","script":"const day = \\"August 21, 2026\\"; return day"}}',
            '{"type":"action.result","payload":{"type":"execute_js","success":true,"data":"August 21, 2026"}}',
            '{"type":"action.request","payload":{"type":"execute_js","script":"const day = \\"August 22, 2026\\"; return day"}}',
            '{"type":"action.result","payload":{"type":"execute_js","success":true,"data":"August 22, 2026"}}',
            '{"type":"action.request","payload":{"type":"execute_js","script":"const value = \\"wayfair_adv_reports_2026-08-22\\"; document.querySelector(\\"input\\").value = value"}}',
            '{"type":"action.result","payload":{"type":"execute_js","success":true,"data":"{\\"reportName\\":\\"wayfair_adv_reports_2026-08-22\\"}"}}',
            '{"type":"action.request","payload":{"type":"execute_js","script":"document.body.innerText"}}',
            f'{{"type":"action.result","payload":{{"type":"execute_js","success":true,"data":"{{\\"latestId\\":\\"{report_id}\\",\\"downloadReady\\":true}}"}}}}',
        ]
    )
    (trace / "events.jsonl").write_text(events, encoding="utf-8")

    skill = ForgeEngine(tmp_path / "skills").generate(
        trace,
        "wayfair",
        "Download WSP Product Report for T-3 to T-2 as CSV wayfair_adv_reports_{T-2}",
        install=False,
    )
    workflow = json.loads((skill / "evidence" / "workflow.json").read_text(encoding="utf-8"))
    skill_text = (skill / "SKILL.md").read_text(encoding="utf-8")

    assert 'description: "Generated by browser-auto-ops Forge. Goal:' in skill_text
    assert workflow["parameters"][-1]["name"] == "report_name"
    assert workflow["parameters"][-1]["template"] == "wayfair_adv_reports_{end_date.iso}"
    executable_text = json.dumps(
        [
            {"script": item.get("script"), "request": item.get("request"), "intent": item.get("intent")}
            for item in workflow["workflow_steps"]
            if isinstance(item, dict)
        ],
        ensure_ascii=False,
    )
    assert "August 21, 2026" not in executable_text
    assert "August 22, 2026" not in executable_text
    assert "wayfair_adv_reports_2026-08-22" not in executable_text
    assert any(item["type"] == "artifact" for item in workflow["workflow_steps"])
    assert workflow["artifacts"][0]["filename_template"] == "{report_name}.csv"
    assert workflow["artifacts"][0]["validators"][-1] == {"type": "extension", "value": ".csv"}
    candidates = workflow["parameter_candidates"]
    assert any(item["value"] == report_id and item["binding_scope"] == "runtime_output" for item in candidates)
    assert not any(item["value"] == report_id and item["requires_confirmation"] for item in candidates)
    assert "`--report_name`" in skill_text
    assert "download artifact to output directory" in skill_text


def test_component_generator_writes_atomic_helpers_from_patterns(tmp_path: Path) -> None:
    written = write_component_scripts(
        tmp_path,
        {
            "parameters": [{"type": "date_offset", "name": "start", "value": "T-3", "offset_days": 3, "source": "goal"}],
            "locators": [
                {"action": "select", "match": {"role": "combobox", "text": "Group By"}},
                {"action": "input", "match": {"role": "textbox", "placeholder": "Report Name"}},
            ],
            "workflow_steps": [
                {"type": "wait_condition", "description": "poll generated row status"},
                {"type": "api_call", "script": "fetch('/download')"},
            ],
        },
    )

    assert {
        "date-params.py",
        "select-combobox.py",
        "select-calendar-day.py",
        "fill-react-input.py",
        "poll-row-status.py",
        "download-via-page-fetch.py",
        "download-artifact.py",
    }.issubset(set(written))


def test_artifact_contract_saves_and_validates_csv(tmp_path: Path) -> None:
    step = {"id": "download_report"}
    result = SimpleNamespace(data={"base64": "RGF0ZQoyMDI2LTA4LTIyCg==", "filename": "report.csv"})
    context = {
        "params": {"output_dir": str(tmp_path), "start_date": {"iso": "2026-08-22"}, "end_date": {"iso": "2026-08-22"}},
        "outputs": {},
        "artifacts": [],
        "workflow": {
            "artifacts": [
                {
                    "name": "report",
                    "from_step": "download_report",
                    "filename_template": "export.csv",
                    "output_dir": "{output_dir}",
                    "validators": [
                        {"type": "exists"},
                        {"type": "non_empty"},
                        {"type": "extension", "value": ".csv"},
                        {"type": "csv_header_contains", "value": "Date"},
                    ],
                }
            ]
        },
    }

    artifact = _collect_runtime_artifact(step, result, context)

    assert artifact is not None
    assert Path(artifact["path"]).name == "export.csv"
    assert Path(artifact["path"]).read_text(encoding="utf-8").startswith("Date")
    assert all(item["ok"] for item in artifact["validators"])
    assert context["artifacts"] == [artifact]


def test_artifact_valid_requires_all_validators() -> None:
    assert _artifact_valid({"validators": [{"ok": True}, {"ok": True}]}) is True
    assert _artifact_valid({"validators": [{"ok": True}, {"ok": False, "reason": "bad extension"}]}) is False


def test_eval_helper_semantic_failure_is_not_treated_as_success(tmp_path: Path) -> None:
    trace = tmp_path / "trace"
    trace.mkdir()
    events = "\n".join(
        [
            '{"type":"action.request","payload":{"type":"execute_js","script":"document.querySelector(\\"button\\").click()"}}',
            '{"type":"action.result","payload":{"type":"execute_js","success":true,"data":"{\\"error\\":true,\\"message\\":\\"button not found\\"}"}}',
        ]
    )
    (trace / "events.jsonl").write_text(events, encoding="utf-8")

    skill = ForgeEngine(tmp_path / "skills").generate(trace, "broken-helper", "click missing button", install=False)
    workflow = json.loads((skill / "evidence" / "workflow.json").read_text(encoding="utf-8"))
    report = json.loads((skill / "evidence" / "generation-report.json").read_text(encoding="utf-8"))

    assert workflow["workflow_steps"][0]["type"] == "fallback"
    assert report["dropped_actions"][0]["reason"] == "failed_action"


def test_runtime_semantic_failure_rejects_error_payload() -> None:
    step = {
        "type": "eval_helper",
        "success_predicate": {"json_path": "$.ok", "equals": True},
        "failure_predicate": {"json_path": "$.error", "equals": True},
    }
    result = ActionResult(type="execute_js", success=True, data='{"error":true,"message":"not found"}')

    ok, reason = _semantic_step_success(step, result)

    assert ok is False
    assert reason == "failure_predicate matched"


def test_wayfair_report_proxy_network_generates_api_first_workflow(tmp_path: Path) -> None:
    trace = tmp_path / "trace"
    network = trace / "network"
    network.mkdir(parents=True)
    post_data = {
        "path": "/partner/v1/reports",
        "method": "POST",
        "body": {
            "name": "wayfair_adv_reports_2026-08-22",
            "reportType": "SKU_REPORT",
            "campaignType": "WSP",
            "timeDimension": "DAY",
            "fileType": "CSV",
            "filters": {"startDate": "2026-08-21 00:00:00", "endDate": "2026-08-22 00:00:00"},
            "attributionWindow": 14,
        },
    }
    (network / "snapshot.json").write_text(
        json.dumps(
            [
                {
                    "url": "https://partners.wayfair.com/a/media_hub/report/proxy",
                    "method": "POST",
                    "resource_type": "fetch",
                    "status": 200,
                    "post_data": json.dumps(post_data),
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    skill = ForgeEngine(tmp_path / "skills").generate(
        trace,
        "wayfair-api-first",
        "Download Wayfair WSP Product Report for T-3 to T-2 as CSV wayfair_adv_reports_{T-2}",
        install=False,
    )
    workflow = json.loads((skill / "evidence" / "workflow.json").read_text(encoding="utf-8"))
    report = json.loads((skill / "evidence" / "generation-report.json").read_text(encoding="utf-8"))

    assert workflow["capability_discovery"]["strategy"] == "api_first"
    assert [step["id"] for step in workflow["workflow_steps"][:3]] == [
        "api_create_report",
        "api_poll_report_status",
        "api_download_report",
    ]
    assert workflow["workflow_steps"][0]["request"]["body_template"]["body"]["name"] == "wayfair_adv_reports_{end_date.iso}"
    assert workflow["workflow_steps"][2]["artifact"]["filename_template"] == "wayfair_adv_reports_{end_date.iso}.csv"
    assert "startsWith('complete')" in workflow["workflow_steps"][1]["script"]
    assert "const completed = matches.find" in workflow["workflow_steps"][1]["script"]
    assert workflow["auth_precheck"]["required_for"] == ["api_call"]
    assert workflow["auth_precheck"]["login_required_when"]["title_contains"] == ["sign in", "login"]
    assert workflow["auth_precheck"]["on_missing_auth_branch"] == "fail_fast"
    assert "This skill has no captured login branch" in (skill / "SKILL.md").read_text(encoding="utf-8")
    assert report["capability_discovery"]["selected"]["id"] == "wayfair_report_proxy_api"


def test_auth_gate_fail_fast_for_login_page_without_auth_branch() -> None:
    workflow = {
        "auth_precheck": {
            "required_for": ["api_call"],
            "login_required_when": {"title_contains": ["sign in", "login"], "url_contains": ["/auth/", "login"]},
            "on_missing_auth_branch": "fail_fast",
        },
        "workflow_steps": [{"id": "api_create_report", "type": "api_call"}],
    }

    failure = auth_gate_failure(workflow, {"url": "https://partners.wayfair.com/auth/login", "title": "Sign In"})

    assert failure is not None
    assert failure["reason"] == "login_required"
    assert "Authentication is required before API replay" in failure["message"]


def test_auth_gate_allows_captured_auth_branch_on_login_page() -> None:
    workflow = {
        "auth": {"steps": ["input Email with runtime credential"]},
        "auth_precheck": {
            "required_for": ["api_call"],
            "login_required_when": {"title_contains": ["sign in", "login"], "url_contains": ["/auth/", "login"]},
            "on_missing_auth_branch": "fail_fast",
        },
    }

    assert auth_gate_failure(workflow, {"url": "https://partners.wayfair.com/auth/login", "title": "Login"}) is None


def test_auth_gate_allows_non_login_page() -> None:
    workflow = {
        "auth_precheck": {
            "required_for": ["api_call"],
            "login_required_when": {"title_contains": ["sign in", "login"], "url_contains": ["/auth/", "login"]},
            "on_missing_auth_branch": "fail_fast",
        },
    }

    assert auth_gate_failure(workflow, {"url": "https://partners.wayfair.com/a/media_hub", "title": "Reports"}) is None


def test_forge_tester_reports_login_required_for_api_skill(tmp_path: Path) -> None:
    skill = tmp_path / "api-skill"
    evidence = skill / "evidence"
    evidence.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        """# api-skill

## 复跑流程

1. call report API

## 成功标准

- recorded step checkpoints succeeded

## 查找元素

locator
""",
        encoding="utf-8",
    )
    (evidence / "workflow.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "workflow_steps": [{"id": "api_create_report", "type": "api_call", "replay": True}],
                "validators": [{"type": "step_success", "step_id": "api_create_report"}],
                "auth_precheck": {
                    "required_for": ["api_call"],
                    "login_required_when": {"title_contains": ["sign in", "login"], "url_contains": ["/auth/", "login"]},
                    "on_missing_auth_branch": "fail_fast",
                },
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_skill(skill, live={"url": "https://partners.wayfair.com/auth/login", "title": "Sign In"})

    assert result["ok"] is False
    check = next(item for item in result["checks"] if item["name"] == "live_auth_precheck")
    assert check["reason"] == "login_required"


def test_structured_api_call_builds_page_fetch_action() -> None:
    action = action_from_step(
        {
            "type": "api_call",
            "request": {
                "method": "POST",
                "url": "/proxy",
                "headers": {"Content-Type": "application/json"},
                "body_template": {"name": "{report_name}"},
            },
        },
        {},
    )

    assert action is not None
    assert action["type"] == "execute_js"
    assert "fetch(\"/proxy\"" in action["script"]
    assert "{report_name}" in action["script"]


def test_compact_action_payload_scrubs_base64_data() -> None:
    result = ActionResult(
        type="execute_js",
        success=True,
        data=json.dumps({"ok": True, "base64": "a" * 120, "filename": "report.csv"}),
    )

    payload = compact_action_payload(result)

    assert "<base64:120 chars>" in payload["result"]["data"]
    assert "a" * 80 not in payload["result"]["data"]


def test_repair_suggestion_is_written_as_evidence(tmp_path: Path) -> None:
    skill = tmp_path / "skill"
    state = PageState(session_id="s_test", url="https://example.test/reports", title="Reports")

    path = _write_replay_repair_suggestion(
        skill,
        3,
        {"type": "click", "match": {"role": "button", "text": "Generate"}},
        SimpleNamespace(message="element not found"),
        state,
    )
    payload = json.loads(Path(path).read_text(encoding="utf-8"))

    assert payload["step"] == 3
    assert payload["message"] == "element not found"
    assert payload["current_title"] == "Reports"
    assert (skill / "evidence" / "repair-suggestion.json").exists()
