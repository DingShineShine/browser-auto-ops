from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_component_scripts(scripts_dir: Path, workflow: dict[str, Any]) -> list[str]:
    scripts_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    if any(item.get("type") == "date_offset" for item in workflow.get("parameters") or [] if isinstance(item, dict)):
        (scripts_dir / "date-params.py").write_text(_date_params_script(workflow), encoding="utf-8")
        written.append("date-params.py")
    if _uses_combobox(workflow):
        (scripts_dir / "select-combobox.py").write_text(_select_combobox_script(), encoding="utf-8")
        written.append("select-combobox.py")
    if _uses_calendar(workflow):
        (scripts_dir / "select-calendar-day.py").write_text(_select_calendar_day_script(), encoding="utf-8")
        written.append("select-calendar-day.py")
    if _uses_react_input(workflow):
        (scripts_dir / "fill-react-input.py").write_text(_fill_react_input_script(), encoding="utf-8")
        written.append("fill-react-input.py")
    if _uses_polling(workflow):
        (scripts_dir / "poll-row-status.py").write_text(_poll_row_status_script(), encoding="utf-8")
        written.append("poll-row-status.py")
    if _uses_page_fetch(workflow):
        (scripts_dir / "download-via-page-fetch.py").write_text(_download_via_page_fetch_script(), encoding="utf-8")
        written.append("download-via-page-fetch.py")
    (scripts_dir / "download-artifact.py").write_text(_download_artifact_script(), encoding="utf-8")
    written.append("download-artifact.py")
    return written


def _uses_combobox(workflow: dict[str, Any]) -> bool:
    for locator in workflow.get("locators") or []:
        match = locator.get("match") if isinstance(locator, dict) and isinstance(locator.get("match"), dict) else {}
        if match.get("role") in {"combobox", "listbox"} or locator.get("action") == "select":
            return True
    return _steps_contain(workflow, "combobox", "listbox", "downshift")


def _uses_calendar(workflow: dict[str, Any]) -> bool:
    return any(item.get("type") == "date_offset" for item in workflow.get("parameters") or [] if isinstance(item, dict)) or _steps_contain(
        workflow,
        "calendar",
        "datepicker",
        "date picker",
    )


def _uses_react_input(workflow: dict[str, Any]) -> bool:
    if any(isinstance(item, dict) and item.get("action") == "input" for item in workflow.get("locators") or []):
        return True
    return _steps_contain(workflow, "value setter", "react", "input")


def _uses_polling(workflow: dict[str, Any]) -> bool:
    return _steps_contain(workflow, "poll", "status", "setinterval", "row status")


def _uses_page_fetch(workflow: dict[str, Any]) -> bool:
    return any(isinstance(item, dict) and item.get("type") == "api_call" for item in workflow.get("workflow_steps") or [])


def _steps_contain(workflow: dict[str, Any], *needles: str) -> bool:
    blob = json.dumps(workflow.get("workflow_steps") or [], ensure_ascii=False).lower()
    return any(needle in blob for needle in needles)


def _date_params_script(workflow: dict[str, Any]) -> str:
    params = [
        item
        for item in workflow.get("parameters") or []
        if isinstance(item, dict) and item.get("type") == "date_offset"
    ]
    literal = repr(json.dumps(params, ensure_ascii=False))
    return f'''import argparse
import json
from datetime import date, datetime, timedelta


DATE_PARAMS = json.loads({literal})


def _parse_today(value: str) -> date:
    if value:
        return datetime.strptime(value, "%Y-%m-%d").date()
    return date.today()


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve forge relative date parameters.")
    parser.add_argument("--today", default="", help="Override today as YYYY-MM-DD for tests or deterministic replay")
    args = parser.parse_args()
    today = _parse_today(args.today)
    rows = []
    for item in DATE_PARAMS:
        target = today - timedelta(days=int(item.get("offset_days") or 0))
        rows.append({{
            "name": item.get("name"),
            "token": item.get("value"),
            "iso": target.strftime("%Y-%m-%d"),
            "us": target.strftime("%m/%d/%Y"),
            "long_en": f"{{target.strftime('%B')}} {{target.day}}, {{target.year}}",
            "compact": target.strftime("%Y%m%d"),
        }})
    print(json.dumps({{"dates": rows}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
'''


def _download_artifact_script() -> str:
    return '''import argparse
import base64
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Save a base64 download artifact to disk.")
    parser.add_argument("--json-file", required=True)
    parser.add_argument("--output-dir", default=str(Path.home() / "Downloads"))
    parser.add_argument("--filename", default="")
    args = parser.parse_args()
    payload = json.loads(Path(args.json_file).read_text(encoding="utf-8"))
    body64 = payload.get("base64") or payload.get("response_body_base64")
    if not body64:
        raise SystemExit("payload does not contain base64 download content")
    filename = args.filename or payload.get("filename") or payload.get("suggested_filename") or "download.bin"
    output = Path(args.output_dir).expanduser().resolve() / filename
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(base64.b64decode(body64))
    print(json.dumps({"saved": str(output), "bytes": output.stat().st_size}, ensure_ascii=False))


if __name__ == "__main__":
    main()
'''


def _select_combobox_script() -> str:
    return '''import argparse
import json


JS = r"""
({label, option}) => {
  const textOf = (el) => (el.innerText || el.textContent || el.getAttribute('aria-label') || '').trim();
  const controls = [...document.querySelectorAll('[role="combobox"], input, button')];
  const control = controls.find((el) => textOf(el).includes(label) || (el.getAttribute('aria-label') || '').includes(label) || (el.placeholder || '').includes(label));
  if (!control) return {ok: false, reason: 'combobox not found'};
  control.click();
  const options = [...document.querySelectorAll('[role="option"], [role="menuitem"], li, button')];
  const target = options.find((el) => textOf(el).trim() === option || textOf(el).includes(option));
  if (!target) return {ok: false, reason: 'option not found'};
  target.click();
  return {ok: true, label, option};
}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Build JS for selecting a combobox/listbox option.")
    parser.add_argument("--label", required=True)
    parser.add_argument("--option", required=True)
    args = parser.parse_args()
    print(json.dumps({"script": JS, "args": {"label": args.label, "option": args.option}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
'''


def _select_calendar_day_script() -> str:
    return '''import argparse
import json


JS = r"""
({dayText}) => {
  const textOf = (el) => (el.innerText || el.textContent || el.getAttribute('aria-label') || '').trim();
  const candidates = [...document.querySelectorAll('button, [role="button"], [role="gridcell"]')];
  const target = candidates.find((el) => textOf(el) === dayText || textOf(el).includes(dayText));
  if (!target) return {ok: false, reason: 'calendar day not found', dayText};
  target.click();
  return {ok: true, dayText};
}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Build JS for selecting a visible calendar day.")
    parser.add_argument("--day-text", required=True)
    args = parser.parse_args()
    print(json.dumps({"script": JS, "args": {"dayText": args.day_text}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
'''


def _fill_react_input_script() -> str:
    return '''import argparse
import json


JS = r"""
({label, value}) => {
  const all = [...document.querySelectorAll('input, textarea')];
  const input = all.find((el) => (el.placeholder || '').includes(label) || (el.getAttribute('aria-label') || '').includes(label) || (el.name || '').includes(label));
  if (!input) return {ok: false, reason: 'input not found'};
  const proto = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
  setter ? setter.call(input, value) : input.value = value;
  input.dispatchEvent(new Event('input', {bubbles: true}));
  input.dispatchEvent(new Event('change', {bubbles: true}));
  return {ok: true, label, value};
}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Build JS for filling React-controlled inputs.")
    parser.add_argument("--label", required=True)
    parser.add_argument("--value", required=True)
    args = parser.parse_args()
    print(json.dumps({"script": JS, "args": {"label": args.label, "value": args.value}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
'''


def _poll_row_status_script() -> str:
    return '''import argparse
import json


JS = r"""
({rowText, statusText}) => {
  const rows = [...document.querySelectorAll('tr, [role="row"], li, [data-row]')];
  const row = rows.find((el) => (el.innerText || el.textContent || '').includes(rowText));
  if (!row) return {ok: false, reason: 'row not found'};
  const text = row.innerText || row.textContent || '';
  return {ok: text.includes(statusText), rowText, statusText, text};
}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Build JS for checking a generated row status.")
    parser.add_argument("--row-text", required=True)
    parser.add_argument("--status-text", required=True)
    args = parser.parse_args()
    print(json.dumps({"script": JS, "args": {"rowText": args.row_text, "statusText": args.status_text}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
'''


def _download_via_page_fetch_script() -> str:
    return '''import argparse
import json


JS = r"""
async ({url, method, body}) => {
  const response = await fetch(url, {
    method: method || 'GET',
    credentials: 'include',
    headers: body ? {'content-type': 'application/json'} : undefined,
    body: body || undefined,
  });
  const buffer = await response.arrayBuffer();
  const bytes = Array.from(new Uint8Array(buffer));
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return {
    ok: response.ok,
    status: response.status,
    contentType: response.headers.get('content-type'),
    base64: btoa(binary),
  };
}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Build JS for authenticated in-page fetch downloads.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--method", default="GET")
    parser.add_argument("--body", default="")
    args = parser.parse_args()
    print(json.dumps({"script": JS, "args": {"url": args.url, "method": args.method, "body": args.body}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
'''
