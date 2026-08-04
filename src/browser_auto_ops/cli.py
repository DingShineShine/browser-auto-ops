from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Optional

import typer

from browser_auto_ops.browsers import BrowserStore, provider_config_for_browser
from browser_auto_ops.config import ensure_data_dirs
from browser_auto_ops.forge import ForgeEngine
from browser_auto_ops.intelligence import ActService, ExtractService, ObserveService
from browser_auto_ops.safety import is_dangerous_text
from browser_auto_ops.schemas import ActionRequest, BrowserIdentity, ProviderConfig
from browser_auto_ops.sessions import SessionManager, SessionStore

app = typer.Typer(help="browser-auto-ops CLI")
browser_app = typer.Typer(help="Browser identity management")
session_app = typer.Typer(help="Session lifecycle")
network_app = typer.Typer(help="Network inspection")
forge_app = typer.Typer(help="Skill Forge")
get_app = typer.Typer(help="Data extraction")
app.add_typer(browser_app, name="browser")
app.add_typer(session_app, name="session")
app.add_typer(network_app, name="network")
app.add_typer(forge_app, name="forge")
app.add_typer(get_app, name="get")

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
def state(session_id: Optional[str] = typer.Argument(None), json_output: bool = typer.Option(False, "--json")) -> None:
    async def _main() -> None:
        manager, session_ref = await _attach(_session_ref(session_id))
        try:
            page_state = await manager.state(session_ref)
            _persist_attached(manager, session_ref)
            if json_output or _ctx["format"] == "json":
                _echo(page_state.model_dump(mode="json"), force_json=True)
            else:
                typer.echo(page_state.render_text())
        finally:
            await manager.sessions[session_ref].connection.disconnect()

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
def wait(first: str = "stable", second: Optional[str] = typer.Argument(None)) -> None:
    if second is None and first == "stable":
        session_ref = _session_name()
        condition = first
    else:
        session_ref = first
        condition = second or "stable"
    if condition != "stable":
        raise typer.BadParameter("v1 only supports stable")
    _action(session_ref, ActionRequest(type="wait"))


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
            actions = ActService().plan(page_state, goal, allow_dangerous=confirm, require_confirm=confirm)[:3]
            results = []
            for request in actions:
                result, _ = await manager.action(attached_ref, request)
                results.append(result.model_dump(mode="json"))
                _persist_attached(manager, attached_ref)
            _echo({"actions": [a.model_dump(mode="json") for a in actions], "results": results}, force_json=True)
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
    async def _main() -> None:
        manager, attached_ref = await _attach(_session_ref(session_id))
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
    async def _main() -> None:
        manager, attached_ref = await _attach(_session_ref(session_id))
        try:
            cleared = manager.network_clear(attached_ref)
            _echo({"cleared": cleared}, force_json=True)
        finally:
            await manager.sessions[attached_ref].connection.disconnect()

    run(_main())


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
    if name not in {"core", "enterprise", "main"}:
        raise typer.BadParameter("supported skill guides: core, enterprise, main")
    typer.echo(_skill_text(name))


def _action(session_ref: str, request: ActionRequest) -> None:
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


def _chrome_direct_exists(store: BrowserStore) -> bool:
    return any(browser.type == "chrome-direct" for browser in store.list())


def _skill_text(name: str) -> str:
    variant = "enterprise" if name == "enterprise" else "core"
    return f"""# browser-auto-ops {variant}

Use `bao` as a BrowserAct-style enterprise browser CLI. Public browser types are only:

- `chrome-direct`: controls the employee's current local Chrome. Requires explicit confirmation before use.
- `ads`: controls an AdsPower/ADS profile, preferably through the VPS-side browser-auto-ops sidecar.

Core workflow:

```bash
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
bao --session task-name network requests --type xhr,fetch --filter /api/
bao session close task-name
```

Important rules:

- Re-run `bao --session <name> state` after navigation or DOM changes; indexes are temporary.
- Use `chrome-direct` only when the task needs live local Chrome cookies, extensions, certificates, or SSO.
- Use `ads` for company-managed AdsPower browser profiles on the VPS.
- Do not expose raw CDP ports publicly.
- Do not auto-submit payment, delete, publish, approval, or account-changing operations. Use `--confirm` only after explicit user approval.
- Unsupported BrowserAct commands in this version: `stealth-extract`, `solve-captcha`, `remote-assist`, `network har`, browser profile import, and stealth browser creation.
"""
