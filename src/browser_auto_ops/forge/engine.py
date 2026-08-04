from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class ForgeEngine:
    def __init__(self, skills_root: Path) -> None:
        self.skills_root = skills_root
        self.skills_root.mkdir(parents=True, exist_ok=True)

    def generate(self, trace_dir: Path, name: str, goal: str | None = None) -> Path:
        skill_name = _slug(name)
        root = self.skills_root / skill_name
        scripts = root / "scripts"
        tests = root / "tests"
        evidence = root / "evidence"
        for path in (root, scripts, tests, evidence):
            path.mkdir(parents=True, exist_ok=True)

        summary = _load_trace_summary(trace_dir)
        resolved_goal = goal or summary.get("goal") or name
        (root / "SKILL.md").write_text(
            _skill_markdown(skill_name, resolved_goal),
            encoding="utf-8",
        )
        (scripts / "capability.py").write_text(_script_template(summary), encoding="utf-8")
        (tests / "smoke.json").write_text(
            json.dumps(
                {
                    "skill": skill_name,
                    "trace_dir": str(trace_dir),
                    "goal": resolved_goal,
                    "command": "python scripts/capability.py --mode text --query sample",
                    "expected": "prints JavaScript that returns JSON from the live browser page context",
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
        return root


def _slug(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower())
    return value.strip("-") or "generated-skill"


def _load_trace_summary(trace_dir: Path) -> dict[str, Any]:
    events_path = trace_dir / "events.jsonl"
    summary_path = trace_dir / "summary.json"
    file_summary = _read_json(summary_path) if summary_path.exists() else {}
    if not events_path.exists():
        return {"events": 0, **file_summary}

    count = 0
    types: dict[str, int] = {}
    goal: str | None = None
    last_state: dict[str, Any] | None = None
    actions: list[dict[str, Any]] = []
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
        if isinstance(payload, dict):
            if payload.get("goal"):
                goal = str(payload["goal"])
            if event_type == "state.capture":
                last_state = _compact_state(payload)
            elif event_type == "forge.explore" and isinstance(payload.get("state"), dict):
                last_state = _compact_state(payload["state"])
            elif event_type == "action.request":
                actions.append({"request": _compact_action(payload)})
            elif event_type == "action.result":
                if actions and "result" not in actions[-1]:
                    actions[-1]["result"] = _compact_action(payload)
                else:
                    actions.append({"result": _compact_action(payload)})

    return {
        **file_summary,
        "events": count,
        "event_types": types,
        "goal": goal,
        "last_state": last_state,
        "actions": actions[-20:],
    }


def _compact_state(state: dict[str, Any]) -> dict[str, Any]:
    elements = state.get("elements") or []
    return {
        "url": state.get("url"),
        "title": state.get("title"),
        "element_count": len(elements) if isinstance(elements, list) else 0,
        "elements": [_compact_element(item) for item in elements[:30] if isinstance(item, dict)],
    }


def _compact_element(element: dict[str, Any]) -> dict[str, Any]:
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
    }


def _compact_action(action: dict[str, Any]) -> dict[str, Any]:
    keep = {
        "type",
        "index",
        "text",
        "option",
        "url",
        "success",
        "message",
        "fallback_used",
        "require_confirm",
    }
    return {key: value for key, value in action.items() if key in keep}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _skill_markdown(skill_name: str, goal: str) -> str:
    return f"""---
name: {skill_name}
description: Generated by browser-auto-ops Forge. Goal: {goal}
---

# {skill_name}

This skill was generated from a browser-auto-ops trace.

## Usage

```bash
python scripts/capability.py --mode text --query "sample"
python scripts/capability.py --mode tables
python scripts/capability.py --mode links --query "order"
python scripts/capability.py --mode inputs
```

Then execute the emitted JavaScript in a live browser-auto-ops session:

```bash
bao eval <session_id> "$(python scripts/capability.py --mode tables)"
```

## Notes

- The Python wrapper only emits JavaScript.
- The JavaScript runs in the authenticated browser page context.
- Trace hints are embedded so an agent can see the source URL, title, recent elements, and recent action shape.
- Network/API replay should be validated against trace evidence before production use.
"""


def _script_template(summary: dict[str, Any]) -> str:
    hints = {
        "goal": summary.get("goal"),
        "last_state": summary.get("last_state"),
        "actions": summary.get("actions", []),
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
