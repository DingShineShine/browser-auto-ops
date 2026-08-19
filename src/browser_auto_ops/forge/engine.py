from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from browser_auto_ops.forge.api_scripts import compact_network, write_api_scripts
from browser_auto_ops.forge.component_scripts import write_component_scripts
from browser_auto_ops.forge.install import install_skill
from browser_auto_ops.forge.workflow import build_workflow, generation_report, render_skill


class ForgeEngine:
    def __init__(self, skills_root: Path) -> None:
        self.skills_root = skills_root
        self.skills_root.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        trace_dir: Path,
        name: str,
        goal: str | None = None,
        *,
        install: bool = True,
        agents_root: Path | None = None,
        network: list[dict[str, Any]] | None = None,
        session_name: str | None = None,
        browser_type: str | None = None,
    ) -> Path:
        skill_name = _slug(name)
        root = self.skills_root / skill_name
        scripts = root / "scripts"
        tests = root / "tests"
        evidence = root / "evidence"
        for path in (root, scripts, tests, evidence):
            path.mkdir(parents=True, exist_ok=True)
        for leftover in scripts.glob("api-*.py"):
            leftover.unlink()

        summary = load_trace_summary(trace_dir)
        if network:
            summary["network"] = compact_network(network)
        if session_name:
            summary["session_name"] = session_name
        if browser_type:
            summary["browser_type"] = browser_type
        resolved_goal = goal or summary.get("goal") or name
        api_scripts = write_api_scripts(scripts, summary)
        summary["api_scripts"] = api_scripts
        workflow = build_workflow(summary, skill_name, resolved_goal)
        component_scripts = write_component_scripts(scripts, workflow)
        workflow["component_scripts"] = component_scripts
        (root / "SKILL.md").write_text(render_skill(workflow), encoding="utf-8")
        extract_script = _script_template(summary)
        (scripts / "extract.py").write_text(extract_script, encoding="utf-8")
        (scripts / "capability.py").write_text(extract_script, encoding="utf-8")
        (tests / "smoke.json").write_text(
            json.dumps(
                {
                    "skill": skill_name,
                    "trace_dir": str(trace_dir),
                    "goal": resolved_goal,
                    "command": "bao forge test " + str(root),
                    "expected": "static replay checks pass; indexes are not used as locators",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (evidence / "trace-summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (evidence / "workflow.json").write_text(
            json.dumps(workflow, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        agents_path: Path | None = None
        if install:
            agents_path = install_skill(root, agents_root or Path.cwd() / ".agents" / "skills")
        report = generation_report(
            summary,
            workflow,
            api_scripts=api_scripts,
            agents_path=str(agents_path) if agents_path else None,
        )
        (evidence / "generation-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return root


def load_trace_summary(trace_dir: Path) -> dict[str, Any]:
    return _load_trace_summary(trace_dir)


def _slug(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower())
    return value.strip("-") or "generated-skill"


def _load_trace_summary(trace_dir: Path) -> dict[str, Any]:
    events_path = trace_dir / "events.jsonl"
    summary_path = trace_dir / "summary.json"
    file_summary = _read_json(summary_path) if summary_path.exists() else {}
    network_path = trace_dir / "network" / "snapshot.json"
    network = _read_json_list(network_path)
    if not events_path.exists():
        return {"events": 0, "actions": [], "network": compact_network(network), **file_summary}

    count = 0
    types: dict[str, int] = {}
    goal: str | None = None
    last_state: dict[str, Any] | None = None
    last_elements: list[dict[str, Any]] = []
    last_by_index: dict[Any, dict[str, Any]] = {}
    actions: list[dict[str, Any]] = []
    pending: dict[str, Any] | None = None
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        count += 1
        try:
            event = json.loads(line)
        except Exception:
            continue
        event_type = event.get("type", "unknown")
        types[event_type] = types.get(event_type, 0) + 1
        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if payload.get("goal"):
            goal = str(payload["goal"])
        if event_type == "state.capture":
            last_state = _compact_state(payload)
            last_elements = [_compact_element(item) for item in (payload.get("elements") or []) if isinstance(item, dict)]
            last_by_index = {item.get("index"): item for item in last_elements if item.get("index") is not None}
            if pending is not None and pending.get("after_url") is None:
                pending["after_url"] = last_state.get("url")
                pending["after_title"] = last_state.get("title")
        elif event_type == "forge.explore" and isinstance(payload.get("state"), dict):
            last_state = _compact_state(payload["state"])
            if payload.get("goal"):
                goal = str(payload["goal"])
        elif event_type == "action.request":
            request = _compact_action(payload)
            element = last_by_index.get(request.get("index"))
            pending = {
                "request": request,
                "element": element,
                "elements": list(last_elements),
                "before_url": last_state.get("url") if last_state else None,
                "before_title": last_state.get("title") if last_state else None,
            }
            actions.append(pending)
        elif event_type == "action.result":
            result = _compact_action(payload)
            if pending is not None and "result" not in pending:
                pending["result"] = result
                pending["checkpoint"] = _checkpoint_from_result(result, pending)
            else:
                actions.append({"result": result})
                pending = actions[-1]
        elif event_type in {"network.request", "network.response"}:
            network.append(payload)

    if last_state is None:
        last_state = {}
    return {
        **file_summary,
        "events": count,
        "event_types": types,
        "goal": goal,
        "last_state": last_state,
        "last_url_query_keys": list(parse_qs(urlparse(str(last_state.get("url") or "")).query)),
        "actions": actions,
        "network": compact_network(network),
    }


def _compact_state(state: dict[str, Any]) -> dict[str, Any]:
    elements = state.get("elements") or []
    compacted = [_compact_element(item) for item in elements if isinstance(item, dict)]
    return {
        "url": state.get("url"),
        "title": state.get("title"),
        "element_count": len(elements) if isinstance(elements, list) else 0,
        "elements": compacted[:30],
    }


def _compact_element(element: dict[str, Any]) -> dict[str, Any]:
    attributes = element.get("attributes")
    return {
        "index": element.get("index"),
        "kind": element.get("kind"),
        "tag": element.get("tag"),
        "role": element.get("role"),
        "name": element.get("name"),
        "text": element.get("text"),
        "placeholder": element.get("placeholder"),
        "clickable": element.get("clickable"),
        "fillable": element.get("fillable"),
        "selectable": element.get("selectable"),
        "modal": element.get("modal"),
        "value": element.get("value"),
        "attributes": attributes if isinstance(attributes, dict) else {},
    }


def _compact_action(action: dict[str, Any]) -> dict[str, Any]:
    keep = {
        "type",
        "index",
        "ref",
        "match",
        "text",
        "option",
        "url",
        "success",
        "message",
        "fallback_used",
        "require_confirm",
        "verification",
    }
    return {key: value for key, value in action.items() if key in keep}


def _checkpoint_from_result(result: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    verification = result.get("verification")
    if isinstance(verification, dict) and isinstance(verification.get("after"), dict):
        after = verification["after"]
        return {
            "url": after.get("url"),
            "title": after.get("title"),
            "url_changed": bool(verification.get("url_changed")),
            "title_changed": bool(verification.get("title_changed")),
        }
    return {
        "url": action.get("after_url"),
        "title": action.get("after_title"),
        "url_changed": bool(action.get("before_url") and action.get("after_url") and action.get("before_url") != action.get("after_url")),
        "title_changed": bool(action.get("before_title") and action.get("after_title") and action.get("before_title") != action.get("after_title")),
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict) and isinstance(data.get("requests"), list):
        return [item for item in data["requests"] if isinstance(item, dict)]
    return []


def _script_template(summary: dict[str, Any]) -> str:
    hints = {
        "goal": summary.get("goal"),
        "last_state": summary.get("last_state"),
        "actions": [
            {
                "request": item.get("request"),
                "result": item.get("result"),
                "checkpoint": item.get("checkpoint"),
            }
            for item in summary.get("actions", [])
            if isinstance(item, dict)
        ],
    }
    hints_json_literal = repr(json.dumps(hints, ensure_ascii=False))
    return f'''import argparse
import json
import sys


TRACE_HINTS = json.loads({hints_json_literal})


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", newline="\\n")
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["auto", "text", "tables", "links", "inputs"], default="auto")
    parser.add_argument("--query", default="")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    payload = json.dumps(
        {{
            "query": args.query,
            "mode": args.mode,
            "limit": args.limit,
            "trace_hints": TRACE_HINTS,
        }},
        ensure_ascii=False,
    )
    js = """
(async function() {{
  const input = __PAYLOAD__;
  const limit = Number(input.limit || 50);
  const query = String(input.query || "").toLowerCase();
  const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
  const textOf = (node) => clean(node.innerText || node.textContent || "");
  const matches = (value) => !query || clean(value).toLowerCase().includes(query);

  const collectText = () => {{
    const selectors = "h1,h2,h3,h4,p,li,td,th,label,button,a,[role='button'],[aria-label]";
    const snippets = Array.from(document.querySelectorAll(selectors))
      .map((node) => textOf(node) || clean(node.getAttribute("aria-label")))
      .filter(Boolean)
      .filter(matches)
      .slice(0, limit);
    const bodyText = clean(document.body ? document.body.innerText : "");
    return {{
      snippets,
      body_preview: matches(bodyText) ? bodyText.slice(0, 8000) : ""
    }};
  }};

  const collectTables = () => Array.from(document.querySelectorAll("table"))
    .slice(0, limit)
    .map((table) => {{
      const rows = Array.from(table.querySelectorAll("tr")).slice(0, 200).map((row) =>
        Array.from(row.querySelectorAll("th,td")).slice(0, 30).map((cell) => textOf(cell))
      ).filter((row) => row.length);
      return rows;
    }})
    .filter((rows) => rows.length);

  const collectLinks = () => Array.from(document.querySelectorAll("a[href]"))
    .map((link) => ({{
      text: textOf(link),
      href: link.href
    }}))
    .filter((link) => matches(link.text) || matches(link.href))
    .slice(0, limit);

  const collectInputs = () => Array.from(document.querySelectorAll("input,textarea,select,[contenteditable='true']"))
    .map((node) => ({{
      tag: node.tagName.toLowerCase(),
      type: node.getAttribute("type") || "",
      name: node.getAttribute("name") || "",
      id: node.id || "",
      placeholder: node.getAttribute("placeholder") || "",
      aria_label: node.getAttribute("aria-label") || "",
      value: "value" in node ? node.value : textOf(node),
      options: node.tagName === "SELECT" ? Array.from(node.options).map((option) => ({{
        text: option.text,
        value: option.value,
        selected: option.selected
      }})) : []
    }}))
    .filter((item) => matches(Object.values(item).flat().join(" ")))
    .slice(0, limit);

  let mode = input.mode || "auto";
  if (mode === "auto") {{
    mode = document.querySelector("table") ? "tables" : "text";
  }}

  const result = {{
    ok: true,
    mode,
    query: input.query,
    title: document.title,
    url: location.href,
    trace_hints: input.trace_hints,
    data: {{}}
  }};
  if (mode === "text") result.data = collectText();
  if (mode === "tables") result.data.tables = collectTables();
  if (mode === "links") result.data.links = collectLinks();
  if (mode === "inputs") result.data.inputs = collectInputs();
  return JSON.stringify(result);
}})()
"""
    print(js.replace("__PAYLOAD__", payload).strip())


if __name__ == "__main__":
    main()
'''
