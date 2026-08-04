from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

import httpx
import typer

from browser_auto_ops.browsers import BrowserStore, provider_config_for_browser
from browser_auto_ops.config import ensure_data_dirs
from browser_auto_ops.forge import ForgeEngine
from browser_auto_ops.intelligence import ActService, ExtractService, ObserveService
from browser_auto_ops.safety import is_dangerous_text
from browser_auto_ops.schemas import ActionRequest, BrowserIdentity, BrowserSession, PageState, ProviderConfig
from browser_auto_ops.sessions import SessionManager, SessionStore

app = typer.Typer(help="browser-auto-ops CLI")
daemon_app = typer.Typer(help="Local daemon runtime")
browser_app = typer.Typer(help="Browser identity management")
chrome_direct_app = typer.Typer(help="Chrome direct utilities")
session_app = typer.Typer(help="Session lifecycle")
network_app = typer.Typer(help="Network inspection")
network_har_app = typer.Typer(help="Network HAR capture")
forge_app = typer.Typer(help="Skill Forge")
get_app = typer.Typer(help="Data extraction")
tab_app = typer.Typer(help="Tab commands")
cookies_app = typer.Typer(help="Cookie commands")
dialog_app = typer.Typer(help="Dialog commands")
downloads_app = typer.Typer(help="Download commands")
app.add_typer(daemon_app, name="daemon")
app.add_typer(browser_app, name="browser")
app.add_typer(chrome_direct_app, name="chrome-direct")
app.add_typer(session_app, name="session")
network_app.add_typer(network_har_app, name="har")
app.add_typer(network_app, name="network")
app.add_typer(forge_app, name="forge")
app.add_typer(get_app, name="get")
app.add_typer(tab_app, name="tab")
app.add_typer(cookies_app, name="cookies")
app.add_typer(dialog_app, name="dialog")
app.add_typer(downloads_app, name="downloads")

_ctx: dict[str, str | None] = {"session": None, "format": "text"}

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


@app.callback()
def main(
    session: Optional[str] = typer.Option(None, "--session", help="Named session for browser commands"),
    output_format: str = typer.Option("text", "--format", help="Output format: text or json"),
) -> None:
    _ctx["session"] = session
    _ctx["format"] = output_format


def run(coro):
    return asyncio.run(coro)


@daemon_app.command("start")
def daemon_start(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8765, "--port"),
    foreground: bool = typer.Option(False, "--foreground"),
) -> None:
    if foreground:
        import uvicorn

        uvicorn.run("browser_auto_ops.server:app", host=host, port=port)
        return
    root = ensure_data_dirs()
    pid_path = root / "daemon.json"
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "browser_auto_ops.server:app",
        "--host",
        host,
        "--port",
        str(port),
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    local_url = f"{'http'}://{host}:{port}"
    pid_path.write_text(json.dumps({"pid": process.pid, "url": local_url}, ensure_ascii=False, indent=2), encoding="utf-8")
    _echo({"ok": True, "pid": process.pid, "url": local_url}, force_json=True)


@daemon_app.command("status")
def daemon_status() -> None:
    health = _daemon_request("GET", "/health", required=False)
    _echo({"running": bool(health), "health": health}, force_json=True)


@daemon_app.command("stop")
def daemon_stop() -> None:
    path = ensure_data_dirs() / "daemon.json"
    if not path.exists():
        _echo({"ok": True, "stopped": False, "reason": "daemon pid file not found"}, force_json=True)
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    pid = int(data["pid"])
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.kill(pid, 15)
    finally:
        path.unlink(missing_ok=True)
    _echo({"ok": True, "stopped": True, "pid": pid}, force_json=True)


@chrome_direct_app.command("authorize")
def chrome_direct_authorize(
    url: str = typer.Option("chrome://inspect/#devices", "--url"),
    timeout_ms: int = typer.Option(60_000, "--timeout-ms"),
) -> None:
    if _daemon_available():
        config = ProviderConfig(provider="chrome-direct", confirm_direct=True, start_url=url, timeout_ms=timeout_ms)
        session_payload = _daemon_request("POST", "/sessions", config.model_dump(mode="json"))
        session = BrowserSession.model_validate(session_payload)
        _daemon_request("GET", f"/sessions/{session.session_id}/state")
        _daemon_request("GET", f"/sessions/{session.session_id}/state")
        _echo(
            {
                "ok": True,
                "session_id": session.session_id,
                "message": "chrome-direct authorization succeeded through daemon; repeated state calls reused the live runtime",
                "meta": session.meta,
            },
            force_json=True,
        )
        return

    async def _main() -> None:
        manager = SessionManager()
        session = await manager.start(
            ProviderConfig(
                provider="chrome-direct",
                confirm_direct=True,
                start_url=url,
                timeout_ms=timeout_ms,
            )
        )
        try:
            _echo(
                {
                    "ok": True,
                    "session_id": session.session_id,
                    "message": "chrome-direct authorization succeeded without daemon; run `bao daemon start` to avoid reconnect prompts",
                    "meta": session.meta,
                },
                force_json=True,
            )
        finally:
            await manager.sessions[session.session_id].connection.disconnect()

    run(_main())


@browser_app.command("create")
def browser_create(
    browser_type: str = typer.Option(..., "--type"),
    name: str = typer.Option(..., "--name"),
    desc: str = typer.Option("", "--desc"),
    ads_base_url: Optional[str] = typer.Option(None, "--ads-base-url"),
    ads_user_id: Optional[str] = typer.Option(None, "--ads-user-id"),
    api_key: Optional[str] = typer.Option(None, "--api-key"),
    chrome_path: Optional[Path] = typer.Option(None, "--chrome-path"),
    chrome_profile: Optional[str] = typer.Option(None, "--chrome-profile"),
    remote_debugging_port: Optional[int] = typer.Option(None, "--remote-debugging-port"),
    confirm_before_use: bool = typer.Option(False, "--confirm-before-use"),
) -> None:
    if browser_type not in {"chrome-direct", "ads"}:
        raise typer.BadParameter("public browser type must be chrome-direct or ads")
    if browser_type == "ads" and (not ads_base_url or not ads_user_id):
        raise typer.BadParameter("ads browser requires --ads-base-url and --ads-user-id")
    if browser_type == "chrome-direct" and _chrome_direct_exists(BrowserStore()):
        raise typer.BadParameter("only one chrome-direct browser identity is supported")
    provider = "chrome-direct" if browser_type == "chrome-direct" else "adspower-cdp"
    identity = BrowserIdentity(
        type=browser_type,  # type: ignore[arg-type]
        name=name,
        desc=desc,
        confirm_before_use=confirm_before_use or browser_type == "chrome-direct",
        provider_config=ProviderConfig(
            provider=provider,  # type: ignore[arg-type]
            ads_base_url=ads_base_url,
            ads_user_id=ads_user_id,
            api_key=api_key,
            chrome_path=chrome_path,
            chrome_profile=chrome_profile,
            remote_debugging_port=remote_debugging_port,
        ),
    )
    BrowserStore().save(identity)
    _echo(identity.model_dump(mode="json"))


@browser_app.command("list")
def browser_list() -> None:
    _echo([item.model_dump(mode="json") for item in BrowserStore().list()])


@browser_app.command("delete")
def browser_delete(browser_id_or_name: str) -> None:
    deleted = BrowserStore().delete(browser_id_or_name)
    if not deleted:
        raise typer.BadParameter(f"browser not found: {browser_id_or_name}")
    _echo(deleted.model_dump(mode="json"))


@browser_app.command("open")
def browser_open(
    browser_id_or_name: str,
    url: Optional[str] = typer.Argument(None),
    confirm: bool = typer.Option(False, "--confirm"),
) -> None:
    session_name = _session_name()
    browser = BrowserStore().get(browser_id_or_name)
    if not browser:
        raise typer.BadParameter(f"browser not found: {browser_id_or_name}")
    if _daemon_available():
        session = _daemon_request(
            "POST",
            f"/browsers/{browser_id_or_name}/open",
            {"url": url, "confirm": confirm, "session": session_name},
        )
        SessionStore().save(BrowserSession.model_validate(session))
        _echo(session, force_json=True)
        return

    async def _main() -> None:
        config = provider_config_for_browser(browser, start_url=url, confirm=confirm)
        manager = SessionManager()
        session = await manager.start(config)
        session.name = session_name
        session.browser_id = browser.browser_id
        SessionStore().save(session)
        _echo(session.model_dump(mode="json"))
        await manager.sessions[session.session_id].connection.disconnect()

    run(_main())


@session_app.command("start")
def session_start(
    provider: str = typer.Option(..., "--provider"),
    ads_base_url: Optional[str] = typer.Option(None, "--ads-base-url"),
    ads_user_id: Optional[str] = typer.Option(None, "--ads-user-id"),
    api_key: Optional[str] = typer.Option(None, "--api-key"),
    cdp_url: Optional[str] = typer.Option(None, "--cdp-url"),
    user_data_dir: Optional[Path] = typer.Option(None, "--user-data-dir"),
    headful: bool = typer.Option(False, "--headful"),
    chrome_path: Optional[Path] = typer.Option(None, "--chrome-path"),
    chrome_profile: Optional[str] = typer.Option(None, "--chrome-profile"),
    confirm_direct: bool = typer.Option(False, "--confirm-direct"),
    remote_debugging_port: Optional[int] = typer.Option(None, "--remote-debugging-port"),
    start_url: Optional[str] = typer.Option(None, "--start-url"),
    name: Optional[str] = typer.Option(None, "--name"),
) -> None:
    async def _main() -> None:
        config = ProviderConfig(
            provider=provider,  # type: ignore[arg-type]
            ads_base_url=ads_base_url,
            ads_user_id=ads_user_id,
            api_key=api_key,
            cdp_url=cdp_url,
            user_data_dir=user_data_dir,
            headful=headful,
            chrome_path=chrome_path,
            chrome_profile=chrome_profile,
            confirm_direct=confirm_direct,
            remote_debugging_port=remote_debugging_port,
            start_url=start_url,
        )
        manager = SessionManager()
        session = await manager.start(config)
        session.name = name
        SessionStore().save(session)
        _echo(session.model_dump(mode="json"))
        await manager.sessions[session.session_id].connection.disconnect()

    run(_main())


@session_app.command("list")
def session_list() -> None:
    _echo([item.model_dump(mode="json") for item in SessionStore().list()])


@session_app.command("stop")
@session_app.command("close")
def session_stop(session_id_or_name: Optional[str] = typer.Argument(None)) -> None:
    session_ref = session_id_or_name or _session_name()

    async def _main() -> None:
        store = SessionStore()
        session = store.get(session_ref)
        if not session:
            raise typer.BadParameter(f"session not found: {session_ref}")
        manager = SessionManager()
        stopped = await manager.stop_stored_only(session)
        store.delete(session.session_id)
        _echo(stopped.model_dump(mode="json"))

    run(_main())


@app.command()
def state(
    session_id: Optional[str] = typer.Argument(None),
    json_output: bool = typer.Option(False, "--json"),
    full: bool = typer.Option(False, "--full"),
) -> None:
    _ = full
    session_ref = _session_ref(session_id)
    if _daemon_available():
        payload = _daemon_request("GET", f"/sessions/{session_ref}/state")
        page_state = PageState.model_validate(payload)
        if json_output or _ctx["format"] == "json":
            _echo(page_state.model_dump(mode="json"), force_json=True)
        else:
            typer.echo(page_state.render_text())
        return

    async def _main() -> None:
        manager, attached_ref = await _attach(session_ref)
        try:
            page_state = await manager.state(attached_ref)
            _persist_attached(manager, attached_ref)
            if json_output or _ctx["format"] == "json":
                _echo(page_state.model_dump(mode="json"), force_json=True)
            else:
                typer.echo(page_state.render_text())
        finally:
            await manager.sessions[attached_ref].connection.disconnect()

    run(_main())


@app.command()
def navigate(first: str, second: Optional[str] = typer.Argument(None), confirm: bool = typer.Option(False, "--confirm")) -> None:
    session_ref, url = _session_and_value(first, second, value_name="url")
    _action(session_ref, ActionRequest(type="goto_url", url=url, require_confirm=confirm))


@app.command()
def back(session_id: Optional[str] = typer.Argument(None)) -> None:
    _action(_session_ref(session_id), ActionRequest(type="go_back"))


@app.command()
def forward(session_id: Optional[str] = typer.Argument(None)) -> None:
    _action(_session_ref(session_id), ActionRequest(type="go_forward"))


@app.command()
def reload(session_id: Optional[str] = typer.Argument(None)) -> None:
    _action(_session_ref(session_id), ActionRequest(type="reload"))


@app.command()
def click(first: str, second: Optional[int] = typer.Argument(None), confirm: bool = typer.Option(False, "--confirm")) -> None:
    session_ref, index = _session_and_int(first, second)
    _action(session_ref, ActionRequest(type="click", index=index, require_confirm=confirm))


@app.command()
def hover(first: str, second: Optional[int] = typer.Argument(None)) -> None:
    session_ref, index = _session_and_int(first, second)
    _action(session_ref, ActionRequest(type="hover", index=index))


@app.command("input")
def input_text(
    first: str,
    second: str,
    third: Optional[str] = typer.Argument(None),
    confirm: bool = typer.Option(False, "--confirm"),
) -> None:
    if third is None:
        session_ref = _session_name()
        index = int(first)
        text = second
    else:
        session_ref = first
        index = int(second)
        text = third
    _action(session_ref, ActionRequest(type="input_text", index=index, text=text, require_confirm=confirm))


@app.command()
def select(
    first: str,
    second: str,
    third: Optional[str] = typer.Argument(None),
    confirm: bool = typer.Option(False, "--confirm"),
) -> None:
    if third is None:
        session_ref = _session_name()
        index = int(first)
        option = second
    else:
        session_ref = first
        index = int(second)
        option = third
    _action(session_ref, ActionRequest(type="select_option", index=index, option=option, require_confirm=confirm))


@app.command()
def scroll(
    first: str = "down",
    second: Optional[str] = typer.Argument(None),
    amount: int = typer.Option(500, "--amount"),
) -> None:
    if second is None and first in {"up", "down", "left", "right"}:
        session_ref = _session_name()
        direction = first
    else:
        session_ref = first
        direction = second or "down"
    _action(session_ref, ActionRequest(type="scroll", direction=direction, amount=amount))  # type: ignore[arg-type]


@app.command()
def keys(first: str, second: Optional[str] = typer.Argument(None), confirm: bool = typer.Option(False, "--confirm")) -> None:
    session_ref, key = _session_and_value(first, second, value_name="key")
    _action(session_ref, ActionRequest(type="keypress", key=key, require_confirm=confirm))


@app.command()
def upload(
    first: str,
    second: str,
    third: Optional[Path] = typer.Argument(None),
    confirm: bool = typer.Option(False, "--confirm"),
) -> None:
    if third is None:
        session_ref = _session_name()
        index = int(first)
        file_path = Path(second)
    else:
        session_ref = first
        index = int(second)
        file_path = third
    _action(session_ref, ActionRequest(type="upload_file", index=index, file_path=file_path, require_confirm=confirm))


@app.command("eval")
def eval_js(first: str, second: Optional[str] = typer.Argument(None), confirm: bool = typer.Option(False, "--confirm")) -> None:
    session_ref, script = _session_and_value(first, second, value_name="script")
    _action(session_ref, ActionRequest(type="execute_js", script=script, require_confirm=confirm))


@app.command()
def screenshot(
    target: Optional[str] = typer.Argument(None),
    output: Optional[Path] = typer.Option(None, "--output"),
) -> None:
    async def _main() -> None:
        session_ref, path = _screenshot_args(target, output)
        manager, attached_ref = await _attach(session_ref)
        try:
            result = await manager.screenshot(attached_ref, path)
            typer.echo(str(result))
        finally:
            await manager.sessions[attached_ref].connection.disconnect()

    run(_main())


@app.command()
def wait(
    first: str = "stable",
    second: Optional[str] = typer.Argument(None),
    state: str = typer.Option("visible", "--state"),
    selector: Optional[str] = typer.Option(None, "--selector"),
    timeout_ms: int = typer.Option(5_000, "--timeout"),
) -> None:
    index_text = second
    if _ctx.get("session") and first in {"stable", "selector"}:
        session_ref = _session_name()
        condition = first
    else:
        session_ref = first
        condition = second or "stable"
        index_text = None
    if condition == "stable":
        _action(session_ref, ActionRequest(type="wait"))
        return
    if condition == "selector":
        _wait_selector(session_ref, selector=selector, index_text=index_text, state=state, timeout_ms=timeout_ms)
        return
    raise typer.BadParameter("supported wait conditions: stable, selector")


@app.command()
def observe(first: str, second: Optional[str] = typer.Argument(None)) -> None:
    session_ref, goal = _session_and_value(first, second, value_name="goal")

    async def _main() -> None:
        manager, attached_ref = await _attach(session_ref)
        try:
            page_state = await manager.state(attached_ref)
            _persist_attached(manager, attached_ref)
            candidates = ObserveService().observe(page_state, goal)
            _echo([item.model_dump(mode="json") for item in candidates], force_json=True)
        finally:
            await manager.sessions[attached_ref].connection.disconnect()

    run(_main())


@app.command()
def act(first: str, second: Optional[str] = typer.Argument(None), confirm: bool = typer.Option(False, "--confirm")) -> None:
    session_ref, goal = _session_and_value(first, second, value_name="goal")

    async def _main() -> None:
        manager, attached_ref = await _attach(session_ref)
        try:
            page_state = await manager.state(attached_ref)
            if is_dangerous_text(goal) and not confirm:
                _echo(
                    {
                        "blocked": True,
                        "reason": "goal requires explicit confirmation; rerun with --confirm",
                        "actions": [],
                        "results": [],
                    },
                    force_json=True,
                )
                return
            planner_result = ActService().plan_result(page_state, goal, allow_dangerous=confirm, require_confirm=confirm)
            actions = [ActionRequest(type=item.type, index=item.index, text=item.text, option=item.option, require_confirm=item.require_confirm) for item in planner_result.plan.actions][:3]
            results = []
            for request in actions:
                result, _ = await manager.action(attached_ref, request)
                results.append(result.model_dump(mode="json"))
                _persist_attached(manager, attached_ref)
            _echo(
                {
                    "planner": planner_result.model_dump(mode="json"),
                    "actions": [a.model_dump(mode="json") for a in actions],
                    "results": results,
                },
                force_json=True,
            )
        finally:
            await manager.sessions[attached_ref].connection.disconnect()

    run(_main())


@app.command()
def extract(first: str, second: Optional[str] = typer.Argument(None), schema: Optional[str] = typer.Option(None, "--schema")) -> None:
    session_ref, goal = _session_and_value(first, second, value_name="goal")

    async def _main() -> None:
        manager, attached_ref = await _attach(session_ref)
        managed = manager.sessions[attached_ref]
        try:
            schema_obj = json.loads(schema) if schema else None
            data = await ExtractService().extract(managed.connection.page, goal, schema_obj)
            managed.trace.event("extract", data)
            _persist_attached(manager, managed.session.session_id)
            _echo(data, force_json=True)
        finally:
            await managed.connection.disconnect()

    run(_main())


@get_app.command("title")
def get_title(session_id: Optional[str] = typer.Argument(None)) -> None:
    _read_page_value(_session_ref(session_id), "document.title")


@get_app.command("html")
def get_html(
    session_id: Optional[str] = typer.Argument(None),
    selector: Optional[str] = typer.Option(None, "--selector"),
) -> None:
    script = (
        "(selector) => document.querySelector(selector)?.outerHTML || ''"
        if selector
        else "document.documentElement.outerHTML"
    )
    _read_page_value(_session_ref(session_id), script, selector)


@get_app.command("text")
def get_text(first: str, second: Optional[int] = typer.Argument(None)) -> None:
    session_ref, index = _session_and_int(first, second)

    async def _main() -> None:
        manager, attached_ref = await _attach(session_ref)
        try:
            state_obj = await manager.state(attached_ref)
            element = next((item for item in state_obj.elements if item.index == index), None)
            if not element:
                raise typer.BadParameter(f"element index {index} not found")
            typer.echo(element.text or element.name or element.placeholder or element.value)
        finally:
            await manager.sessions[attached_ref].connection.disconnect()

    run(_main())


@get_app.command("value")
def get_value(first: str, second: Optional[int] = typer.Argument(None)) -> None:
    session_ref, index = _session_and_int(first, second)

    async def _main() -> None:
        manager, attached_ref = await _attach(session_ref)
        try:
            state_obj = await manager.state(attached_ref)
            element = next((item for item in state_obj.elements if item.index == index), None)
            if not element:
                raise typer.BadParameter(f"element index {index} not found")
            typer.echo(element.value)
        finally:
            await manager.sessions[attached_ref].connection.disconnect()

    run(_main())


@get_app.command("markdown")
def get_markdown(session_id: Optional[str] = typer.Argument(None)) -> None:
    script = """
    () => {
      const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
      const lines = [];
      for (const node of document.querySelectorAll('h1,h2,h3,h4,p,li,th,td,a,button,label')) {
        const text = clean(node.innerText || node.textContent);
        if (!text) continue;
        const tag = node.tagName.toLowerCase();
        if (tag === 'h1') lines.push('# ' + text);
        else if (tag === 'h2') lines.push('## ' + text);
        else if (tag === 'h3') lines.push('### ' + text);
        else if (tag === 'li') lines.push('- ' + text);
        else lines.push(text);
      }
      return lines.join('\\n');
    }
    """
    _read_page_value(_session_ref(session_id), script)


@network_app.command("requests")
def network_requests(
    session_id: Optional[str] = typer.Argument(None),
    type: Optional[str] = typer.Option(None, "--type"),
    filter: Optional[str] = typer.Option(None, "--filter"),
) -> None:
    session_ref = _session_ref(session_id)
    if _daemon_available():
        query = []
        if type:
            query.append(f"type={type}")
        if filter:
            query.append(f"filter={filter}")
        suffix = ("?" + "&".join(query)) if query else ""
        _echo(_daemon_request("GET", f"/sessions/{session_ref}/network/requests{suffix}"), force_json=True)
        return

    async def _main() -> None:
        manager, attached_ref = await _attach(session_ref)
        try:
            resource_types = type.split(",") if type else None
            items = manager.network_requests(attached_ref, filter_text=filter, resource_types=resource_types)
            _echo([item.model_dump(mode="json") for item in items], force_json=True)
        finally:
            await manager.sessions[attached_ref].connection.disconnect()

    run(_main())


@network_app.command("request")
def network_request(first: str, second: Optional[str] = typer.Argument(None)) -> None:
    session_ref, request_id = _session_and_value(first, second, value_name="request_id")
    if _daemon_available():
        _echo(_daemon_request("GET", f"/sessions/{session_ref}/network/requests/{request_id}"), force_json=True)
        return

    async def _main() -> None:
        manager, attached_ref = await _attach(session_ref)
        try:
            item = manager.network_request(attached_ref, request_id)
            _echo(item.model_dump(mode="json") if item else None, force_json=True)
        finally:
            await manager.sessions[attached_ref].connection.disconnect()

    run(_main())


@network_app.command("clear")
def network_clear(session_id: Optional[str] = typer.Argument(None)) -> None:
    session_ref = _session_ref(session_id)
    if _daemon_available():
        _echo(_daemon_request("POST", f"/sessions/{session_ref}/network/clear"), force_json=True)
        return

    async def _main() -> None:
        manager, attached_ref = await _attach(session_ref)
        try:
            cleared = manager.network_clear(attached_ref)
            _echo({"cleared": cleared}, force_json=True)
        finally:
            await manager.sessions[attached_ref].connection.disconnect()

    run(_main())


@network_har_app.command("start")
def network_har_start(session_id: Optional[str] = typer.Argument(None)) -> None:
    _ = _session_ref(session_id)
    _echo(
        {
            "supported": False,
            "reason": "HAR capture must be enabled when a browser context is created; this runtime records request/response evidence instead.",
        },
        force_json=True,
    )


@network_har_app.command("stop")
def network_har_stop(path: Optional[Path] = typer.Argument(None), session_id: Optional[str] = typer.Option(None, "--session-id")) -> None:
    _ = path
    _ = _session_ref(session_id)
    _echo({"supported": False, "reason": "HAR capture is not active in this runtime."}, force_json=True)


@tab_app.command("list")
def tab_list(session_id: Optional[str] = typer.Argument(None)) -> None:
    async def _main() -> None:
        manager, attached_ref = await _attach(_session_ref(session_id))
        try:
            managed = manager.sessions[attached_ref]
            tabs = []
            if hasattr(managed.connection.browser, "page_targets"):
                targets = await managed.connection.browser.page_targets()
                tabs = [
                    {
                        "tab_id": target.get("targetId"),
                        "url": target.get("url"),
                        "active": target.get("targetId") == managed.session.meta.get("target_id"),
                    }
                    for target in targets
                ]
            else:
                for index, page in enumerate(getattr(managed.connection.context, "pages", [])):
                    tabs.append({"tab_id": str(index), "url": getattr(page, "url", ""), "active": page is managed.connection.page})
            _echo(tabs, force_json=True)
        finally:
            await manager.sessions[attached_ref].connection.disconnect()

    run(_main())


@tab_app.command("switch")
def tab_switch(tab_id: str, session_id: Optional[str] = typer.Argument(None)) -> None:
    async def _main() -> None:
        manager, attached_ref = await _attach(_session_ref(session_id))
        try:
            managed = manager.sessions[attached_ref]
            browser = managed.connection.browser
            if hasattr(browser, "switch_to_target"):
                await browser.switch_to_target(tab_id)
                managed.connection.page = browser.page
            else:
                pages = list(getattr(managed.connection.context, "pages", []))
                managed.connection.page = pages[int(tab_id)]
                await managed.connection.page.bring_to_front()
            manager._sync_session_from_connection(managed)
            SessionStore().save(managed.session)
            _echo({"ok": True, "tab_id": tab_id}, force_json=True)
        finally:
            await manager.sessions[attached_ref].connection.disconnect()

    run(_main())


@tab_app.command("close")
def tab_close(tab_id: Optional[str] = typer.Argument(None), session_id: Optional[str] = typer.Option(None, "--session-id")) -> None:
    async def _main() -> None:
        manager, attached_ref = await _attach(_session_ref(session_id))
        try:
            managed = manager.sessions[attached_ref]
            if hasattr(managed.connection.browser, "client") and tab_id:
                await managed.connection.browser.client.send("Target.closeTarget", {"targetId": tab_id})
                _echo({"ok": True, "tab_id": tab_id}, force_json=True)
                return
            pages = list(getattr(managed.connection.context, "pages", []))
            page = pages[int(tab_id)] if tab_id is not None else managed.connection.page
            close = getattr(page, "close", None)
            if not callable(close):
                raise typer.BadParameter("tab close is not supported by this browser transport")
            await close()
            _echo({"ok": True, "tab_id": tab_id}, force_json=True)
        finally:
            await manager.sessions[attached_ref].connection.disconnect()

    run(_main())


@cookies_app.command("get")
def cookies_get(session_id: Optional[str] = typer.Argument(None), url: Optional[str] = typer.Option(None, "--url")) -> None:
    async def _main() -> None:
        manager, attached_ref = await _attach(_session_ref(session_id))
        try:
            context = manager.sessions[attached_ref].connection.context
            cookies = await _call_context_method(context, "cookies", [url] if url else [])
            _echo(cookies, force_json=True)
        finally:
            await manager.sessions[attached_ref].connection.disconnect()

    run(_main())


@cookies_app.command("export")
def cookies_export(path: Path, session_id: Optional[str] = typer.Option(None, "--session-id")) -> None:
    async def _main() -> None:
        manager, attached_ref = await _attach(_session_ref(session_id))
        try:
            context = manager.sessions[attached_ref].connection.context
            cookies = await _call_context_method(context, "cookies", [])
            path.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
            _echo({"ok": True, "path": str(path), "count": len(cookies)}, force_json=True)
        finally:
            await manager.sessions[attached_ref].connection.disconnect()

    run(_main())


@cookies_app.command("import")
def cookies_import(path: Path, session_id: Optional[str] = typer.Option(None, "--session-id")) -> None:
    async def _main() -> None:
        manager, attached_ref = await _attach(_session_ref(session_id))
        try:
            context = manager.sessions[attached_ref].connection.context
            cookies = json.loads(path.read_text(encoding="utf-8"))
            await _call_context_method(context, "add_cookies", cookies)
            _echo({"ok": True, "count": len(cookies)}, force_json=True)
        finally:
            await manager.sessions[attached_ref].connection.disconnect()

    run(_main())


@cookies_app.command("clear")
def cookies_clear(session_id: Optional[str] = typer.Argument(None)) -> None:
    async def _main() -> None:
        manager, attached_ref = await _attach(_session_ref(session_id))
        try:
            context = manager.sessions[attached_ref].connection.context
            await _call_context_method(context, "clear_cookies", [])
            _echo({"ok": True}, force_json=True)
        finally:
            await manager.sessions[attached_ref].connection.disconnect()

    run(_main())


@dialog_app.command("status")
def dialog_status() -> None:
    _echo({"active": False, "message": "dialog tracking is not persistent yet; use browser-visible prompts manually"}, force_json=True)


@dialog_app.command("accept")
def dialog_accept(text: Optional[str] = typer.Argument(None)) -> None:
    _ = text
    _echo({"supported": False, "reason": "dialog accept requires persistent dialog tracking and is not active yet"}, force_json=True)


@dialog_app.command("dismiss")
def dialog_dismiss() -> None:
    _echo({"supported": False, "reason": "dialog dismiss requires persistent dialog tracking and is not active yet"}, force_json=True)


@downloads_app.command("list")
def downloads_list(session_id: Optional[str] = typer.Argument(None)) -> None:
    session_ref = _session_ref(session_id)
    if not _daemon_available():
        raise typer.BadParameter("downloads require bao daemon; run `bao daemon start` first")
    _echo(_daemon_request("GET", f"/sessions/{session_ref}/downloads"), force_json=True)


@downloads_app.command("wait")
def downloads_wait(
    which: str = typer.Argument("latest"),
    session_id: Optional[str] = typer.Option(None, "--session-id"),
    timeout_ms: int = typer.Option(300_000, "--timeout"),
    output: Optional[Path] = typer.Option(None, "--output"),
) -> None:
    if which != "latest":
        raise typer.BadParameter("only `latest` is supported in this version")
    session_ref = _session_ref(session_id)
    if not _daemon_available():
        raise typer.BadParameter("downloads require bao daemon; run `bao daemon start` first")
    _echo(
        _daemon_request(
            "POST",
            f"/sessions/{session_ref}/downloads/wait",
            {"timeout_ms": timeout_ms, "output": str(output) if output else None},
        ),
        force_json=True,
    )


@downloads_app.command("save")
def downloads_save(
    which: str = typer.Argument("latest"),
    output: Optional[Path] = typer.Option(None, "--output"),
    session_id: Optional[str] = typer.Option(None, "--session-id"),
) -> None:
    downloads_wait(which=which, session_id=session_id, output=output)


@forge_app.command("explore")
def forge_explore(session_id: str, goal: str = typer.Option(..., "--goal")) -> None:
    async def _main() -> None:
        manager, attached_ref = await _attach(session_id)
        managed = manager.sessions[attached_ref]
        try:
            page_state = await manager.state(managed.session.session_id)
            managed.trace.event("forge.explore", {"goal": goal, "state": page_state})
            typer.echo(str(managed.trace.root))
        finally:
            await managed.connection.disconnect()

    run(_main())


@forge_app.command("generate")
def forge_generate(trace: Path = typer.Option(..., "--trace"), name: str = typer.Option(..., "--name"), goal: Optional[str] = typer.Option(None, "--goal")) -> None:
    root = ensure_data_dirs()
    path = ForgeEngine(root / "skills").generate(trace, name, goal)
    typer.echo(str(path))


@forge_app.command("test")
def forge_test(skill_dir: Path) -> None:
    ok = (skill_dir / "SKILL.md").exists() and (skill_dir / "scripts" / "capability.py").exists()
    _echo({"ok": ok, "skill_dir": str(skill_dir)}, force_json=True)


@app.command("get-skills")
def get_skills(name: str = typer.Argument("core"), skill_version: Optional[str] = typer.Option(None, "--skill-version")) -> None:
    _ = skill_version
    if name not in {"core", "enterprise", "main", "chrome-direct", "ads", "safety"}:
        raise typer.BadParameter("supported skill guides: core, enterprise, main, chrome-direct, ads, safety")
    typer.echo(_skill_text(name))


def _action(session_ref: str, request: ActionRequest) -> None:
    if _daemon_available():
        payload = _daemon_request(
            "POST",
            f"/sessions/{session_ref}/actions",
            request.model_dump(mode="json"),
        )
        _echo(payload, force_json=True)
        return

    async def _main() -> None:
        manager, attached_ref = await _attach(session_ref)
        try:
            result, after_state = await manager.action(attached_ref, request)
            _persist_attached(manager, attached_ref)
            payload: dict[str, Any] = {"result": result.model_dump(mode="json")}
            if after_state:
                payload["state"] = after_state.model_dump(mode="json")
            _echo(payload, force_json=True)
        finally:
            await manager.sessions[attached_ref].connection.disconnect()

    run(_main())


async def _attach(session_ref: str):
    store = SessionStore()
    session = store.get(session_ref)
    if not session:
        raise typer.BadParameter(f"session not found: {session_ref}")
    manager = SessionManager()
    managed = await manager.attach(session)
    return manager, managed.session.session_id


def _persist_attached(manager: SessionManager, session_id: str) -> None:
    managed = manager.sessions.get(session_id)
    if managed:
        SessionStore().save(managed.session)


def _echo(payload: Any, *, force_json: bool = False) -> None:
    if force_json or _ctx["format"] == "json" or not isinstance(payload, str):
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        typer.echo(payload)


def _daemon_url() -> str:
    return os.environ.get("BAO_DAEMON_URL", "http://127.0.0.1:8765").rstrip("/")


def _daemon_request(
    method: str,
    path: str,
    payload: Any | None = None,
    *,
    required: bool = True,
    timeout: float = 120.0,
) -> Any | None:
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.request(method, _daemon_url() + path, json=payload)
            response.raise_for_status()
            return response.json()
    except Exception as exc:
        if required:
            raise typer.BadParameter(f"daemon request failed: {exc}") from exc
        return None


def _daemon_available() -> bool:
    return _daemon_request("GET", "/health", required=False, timeout=1.0) is not None


def _session_name() -> str:
    session = _ctx.get("session")
    if not session:
        raise typer.BadParameter("this command requires --session <name> or a legacy session id argument")
    return session


def _session_ref(session_id: str | None) -> str:
    return session_id or _session_name()


def _session_and_int(first: str, second: int | None) -> tuple[str, int]:
    if second is None:
        return _session_name(), int(first)
    return first, int(second)


def _session_and_value(first: str, second: str | None, *, value_name: str) -> tuple[str, str]:
    if second is None:
        if _ctx.get("session"):
            return _session_name(), first
        raise typer.BadParameter(f"missing {value_name}; use --session <name> {first} or legacy SESSION_ID {value_name}")
    return first, second


def _screenshot_args(target: str | None, output: Path | None) -> tuple[str, Path | None]:
    if target is None:
        return _session_name(), output
    store = SessionStore()
    if store.get(target):
        return target, output
    if _ctx.get("session"):
        return _session_name(), Path(target)
    return target, output


def _read_page_value(session_ref: str, script: str, arg: Any = None) -> None:
    if _daemon_available() and arg is None:
        payload = _daemon_request(
            "POST",
            f"/sessions/{session_ref}/actions",
            ActionRequest(type="execute_js", script=script).model_dump(mode="json"),
        )
        data = (payload or {}).get("result", {}).get("data")
        if isinstance(data, (dict, list)):
            _echo(data, force_json=True)
        else:
            typer.echo("" if data is None else str(data))
        return

    async def _main() -> None:
        manager, attached_ref = await _attach(session_ref)
        try:
            managed = manager.sessions[attached_ref]
            data = await managed.connection.page.evaluate(script, arg)
            if isinstance(data, (dict, list)):
                _echo(data, force_json=True)
            else:
                typer.echo("" if data is None else str(data))
        finally:
            await manager.sessions[attached_ref].connection.disconnect()

    run(_main())


def _wait_selector(
    session_ref: str,
    *,
    selector: str | None,
    index_text: str | None,
    state: str,
    timeout_ms: int,
) -> None:
    async def _main() -> None:
        manager, attached_ref = await _attach(session_ref)
        try:
            managed = manager.sessions[attached_ref]
            resolved_selector = selector
            if not resolved_selector:
                if not index_text:
                    raise typer.BadParameter("wait selector requires an index or --selector")
                page_state = await manager.state(attached_ref)
                element = next((item for item in page_state.elements if item.index == int(index_text)), None)
                if not element:
                    raise typer.BadParameter(f"element index {index_text} not found")
                resolved_selector = f"xpath={element.locator.value}"
            wait_for_selector = getattr(managed.connection.page, "wait_for_selector", None)
            if callable(wait_for_selector):
                await wait_for_selector(resolved_selector, state=state, timeout=timeout_ms)
            else:
                await _poll_selector_with_eval(managed.connection.page, resolved_selector, state, timeout_ms)
            _echo({"ok": True, "selector": resolved_selector, "state": state}, force_json=True)
        finally:
            await manager.sessions[attached_ref].connection.disconnect()

    run(_main())


async def _poll_selector_with_eval(page, selector: str, state: str, timeout_ms: int) -> None:
    deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
    while asyncio.get_event_loop().time() < deadline:
        exists = await page.evaluate(
            """
            (selector) => {
              let node = null;
              if (selector.startsWith('xpath=')) {
                node = document.evaluate(selector.slice(6), document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
              } else {
                node = document.querySelector(selector);
              }
              if (!node) return {exists: false, visible: false};
              const rect = node.getBoundingClientRect();
              const style = getComputedStyle(node);
              return {
                exists: true,
                visible: style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0
              };
            }
            """,
            selector,
        )
        if state in {"attached", "visible"} and exists.get("exists") and (state == "attached" or exists.get("visible")):
            return
        if state in {"detached", "hidden"} and (not exists.get("exists") or (state == "hidden" and not exists.get("visible"))):
            return
        await asyncio.sleep(0.2)
    raise typer.BadParameter(f"timed out waiting for selector {selector} to be {state}")


async def _call_context_method(context, method_name: str, args: list[Any]):
    method = getattr(context, method_name, None)
    if not callable(method):
        raise typer.BadParameter(f"{method_name} is not supported by this browser transport")
    return await method(*args)


def _chrome_direct_exists(store: BrowserStore) -> bool:
    return any(browser.type == "chrome-direct" for browser in store.list())


def _skill_text(name: str) -> str:
    if name == "chrome-direct":
        return """# browser-auto-ops chrome-direct

Use `chrome-direct` only when the task needs the employee's live local Chrome cookies, extensions, SSO, or certificates.

First-time authorization:

```bash
bao daemon start
bao chrome-direct authorize
```

If Chrome shows a remote debugging permission dialog, wait for the user to click Allow. Do not send page actions until authorization succeeds.
Use daemon-backed sessions for normal work. Fallback reconnect mode can trigger Chrome's remote-debugging permission dialog repeatedly.

Open a session after explicit approval:

```bash
bao --session task-name browser open local https://example.com --confirm
bao --session task-name state
```
"""
    if name == "ads":
        return """# browser-auto-ops ads

Use `ads` for company-managed AdsPower/ADS profiles, preferably through the VPS-side browser-auto-ops sidecar.

Do not expose raw CDP ports publicly. The sidecar should start the AdsPower profile, read `data.ws.puppeteer`, and keep CDP access on the VPS host.
"""
    if name == "safety":
        return """# browser-auto-ops safety

Safety rules:

- Do not auto-submit payment, delete, publish, approval, or account-changing operations.
- Use `--confirm` only after explicit user approval.
- Prefer state/click/input/select over JS mutation.
- Read-only `eval` is acceptable for extraction.
- Mutation `eval`, form submission, API writes, and account changes require confirmation and trace evidence.
- Treat cookies, auth headers, passwords, verification codes, and AdsPower profile identifiers as sensitive.
"""
    variant = "enterprise" if name == "enterprise" else "core"
    return f"""# browser-auto-ops {variant}

Use `bao` as a BrowserAct-style enterprise browser CLI. Public browser types are only:

- `chrome-direct`: controls the employee's current local Chrome. Requires explicit confirmation before use.
- `ads`: controls an AdsPower/ADS profile, preferably through the VPS-side browser-auto-ops sidecar.

Core workflow:

```bash
bao daemon start
bao browser list
bao browser create --type chrome-direct --name local --desc "Employee current Chrome" --confirm-before-use
bao browser create --type ads --name amazon-us-01 --desc "VPS AdsPower profile" --ads-base-url http://HOST:PORT --ads-user-id PROFILE_ID
bao --session task-name browser open <browser_id_or_name> https://example.com --confirm
bao --session task-name state
bao --session task-name click 3
bao --session task-name input 1 "keyword"
bao --session task-name wait stable
bao --session task-name get title
bao --session task-name get markdown
bao --session task-name tab list
bao --session task-name cookies get
bao --session task-name wait selector 3 --state visible
bao --session task-name network requests --type xhr,fetch --filter /api/
bao --session task-name downloads wait latest --output D:\\exports
bao session close task-name
```

Important rules:

- Run `bao daemon start` before `chrome-direct` work. Without daemon, fallback reconnect mode may trigger Chrome's remote-debugging permission dialog repeatedly.
- Re-run `bao --session <name> state` after navigation or DOM changes; indexes are temporary.
- Use `chrome-direct` only when the task needs live local Chrome cookies, extensions, certificates, or SSO.
- Use `ads` for company-managed AdsPower browser profiles on the VPS.
- Do not expose raw CDP ports publicly.
- Do not auto-submit payment, delete, publish, approval, or account-changing operations. Use `--confirm` only after explicit user approval.
- Unsupported BrowserAct commands in this version: `stealth-extract`, `solve-captcha`, `remote-assist`, `network har`, browser profile import, and stealth browser creation.
"""
