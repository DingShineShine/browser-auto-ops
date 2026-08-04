from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

import typer

from browser_auto_ops.config import ensure_data_dirs
from browser_auto_ops.forge import ForgeEngine
from browser_auto_ops.intelligence import ActService, ExtractService, ObserveService
from browser_auto_ops.safety import is_dangerous_text
from browser_auto_ops.schemas import ActionRequest, ProviderConfig
from browser_auto_ops.sessions import SessionManager, SessionStore

app = typer.Typer(help="browser-auto-ops CLI")
session_app = typer.Typer(help="Session lifecycle")
network_app = typer.Typer(help="Network inspection")
forge_app = typer.Typer(help="Skill Forge")
app.add_typer(session_app, name="session")
app.add_typer(network_app, name="network")
app.add_typer(forge_app, name="forge")

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def run(coro):
    return asyncio.run(coro)


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
        SessionStore().save(session)
        typer.echo(json.dumps(session.model_dump(mode="json"), ensure_ascii=False, indent=2))
        await manager.sessions[session.session_id].connection.disconnect()

    run(_main())


@session_app.command("list")
def session_list() -> None:
    sessions = [item.model_dump(mode="json") for item in SessionStore().list()]
    typer.echo(json.dumps(sessions, ensure_ascii=False, indent=2))


@session_app.command("stop")
def session_stop(session_id: str) -> None:
    async def _main() -> None:
        store = SessionStore()
        session = store.get(session_id)
        if not session:
            raise typer.BadParameter(f"session not found: {session_id}")
        manager = SessionManager()
        stopped = await manager.stop_stored_only(session)
        store.delete(session_id)
        typer.echo(json.dumps(stopped.model_dump(mode="json"), ensure_ascii=False, indent=2))

    run(_main())


@app.command()
def state(session_id: str, json_output: bool = typer.Option(False, "--json")) -> None:
    async def _main() -> None:
        manager, _ = await _attach(session_id)
        try:
            page_state = await manager.state(session_id)
            _persist_attached(manager, session_id)
            if json_output:
                typer.echo(json.dumps(page_state.model_dump(mode="json"), ensure_ascii=False, indent=2))
            else:
                typer.echo(page_state.render_text())
        finally:
            await manager.sessions[session_id].connection.disconnect()

    run(_main())


@app.command()
def navigate(session_id: str, url: str, confirm: bool = typer.Option(False, "--confirm")) -> None:
    _action(session_id, ActionRequest(type="goto_url", url=url, require_confirm=confirm))


@app.command()
def click(session_id: str, index: int, confirm: bool = typer.Option(False, "--confirm")) -> None:
    _action(session_id, ActionRequest(type="click", index=index, require_confirm=confirm))


@app.command()
def hover(session_id: str, index: int) -> None:
    _action(session_id, ActionRequest(type="hover", index=index))


@app.command("input")
def input_text(session_id: str, index: int, text: str, confirm: bool = typer.Option(False, "--confirm")) -> None:
    _action(session_id, ActionRequest(type="input_text", index=index, text=text, require_confirm=confirm))


@app.command()
def select(session_id: str, index: int, option: str, confirm: bool = typer.Option(False, "--confirm")) -> None:
    _action(session_id, ActionRequest(type="select_option", index=index, option=option, require_confirm=confirm))


@app.command()
def scroll(session_id: str, direction: str = "down", amount: int = typer.Option(500, "--amount")) -> None:
    _action(session_id, ActionRequest(type="scroll", direction=direction, amount=amount))  # type: ignore[arg-type]


@app.command()
def keys(session_id: str, key: str, confirm: bool = typer.Option(False, "--confirm")) -> None:
    _action(session_id, ActionRequest(type="keypress", key=key, require_confirm=confirm))


@app.command()
def upload(session_id: str, index: int, file_path: Path, confirm: bool = typer.Option(False, "--confirm")) -> None:
    _action(session_id, ActionRequest(type="upload_file", index=index, file_path=file_path, require_confirm=confirm))


@app.command("eval")
def eval_js(session_id: str, script: str, confirm: bool = typer.Option(False, "--confirm")) -> None:
    _action(session_id, ActionRequest(type="execute_js", script=script, require_confirm=confirm))


@app.command()
def screenshot(session_id: str, output: Optional[Path] = typer.Option(None, "--output")) -> None:
    async def _main() -> None:
        manager, _ = await _attach(session_id)
        try:
            path = await manager.screenshot(session_id, output)
            typer.echo(str(path))
        finally:
            await manager.sessions[session_id].connection.disconnect()

    run(_main())


@app.command()
def wait(session_id: str, condition: str = "stable") -> None:
    if condition != "stable":
        raise typer.BadParameter("v1 only supports stable")
    _action(session_id, ActionRequest(type="wait"))


@app.command()
def observe(session_id: str, goal: str) -> None:
    async def _main() -> None:
        manager, _ = await _attach(session_id)
        try:
            page_state = await manager.state(session_id)
            _persist_attached(manager, session_id)
            candidates = ObserveService().observe(page_state, goal)
            typer.echo(json.dumps([item.model_dump(mode="json") for item in candidates], ensure_ascii=False, indent=2))
        finally:
            await manager.sessions[session_id].connection.disconnect()

    run(_main())


@app.command()
def act(session_id: str, goal: str, confirm: bool = typer.Option(False, "--confirm")) -> None:
    async def _main() -> None:
        manager, _ = await _attach(session_id)
        try:
            page_state = await manager.state(session_id)
            if is_dangerous_text(goal) and not confirm:
                typer.echo(
                    json.dumps(
                        {
                            "blocked": True,
                            "reason": "goal requires explicit confirmation; rerun with --confirm",
                            "actions": [],
                            "results": [],
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return
            actions = ActService().plan(page_state, goal, allow_dangerous=confirm, require_confirm=confirm)[:3]
            results = []
            for request in actions:
                result, _ = await manager.action(session_id, request)
                results.append(result.model_dump(mode="json"))
                _persist_attached(manager, session_id)
            typer.echo(json.dumps({"actions": [a.model_dump(mode="json") for a in actions], "results": results}, ensure_ascii=False, indent=2))
        finally:
            await manager.sessions[session_id].connection.disconnect()

    run(_main())


@app.command()
def extract(session_id: str, goal: str, schema: Optional[str] = typer.Option(None, "--schema")) -> None:
    async def _main() -> None:
        manager, managed = await _attach(session_id)
        try:
            schema_obj = json.loads(schema) if schema else None
            data = await ExtractService().extract(managed.connection.page, goal, schema_obj)
            managed.trace.event("extract", data)
            _persist_attached(manager, session_id)
            typer.echo(json.dumps(data, ensure_ascii=False, indent=2))
        finally:
            await managed.connection.disconnect()

    run(_main())


@network_app.command("requests")
def network_requests(
    session_id: str,
    type: Optional[str] = typer.Option(None, "--type"),
    filter: Optional[str] = typer.Option(None, "--filter"),
) -> None:
    async def _main() -> None:
        manager, _ = await _attach(session_id)
        try:
            resource_types = type.split(",") if type else None
            items = manager.network_requests(session_id, filter_text=filter, resource_types=resource_types)
            typer.echo(json.dumps([item.model_dump(mode="json") for item in items], ensure_ascii=False, indent=2))
        finally:
            await manager.sessions[session_id].connection.disconnect()

    run(_main())


@network_app.command("request")
def network_request(session_id: str, request_id: str) -> None:
    async def _main() -> None:
        manager, _ = await _attach(session_id)
        try:
            item = manager.network_request(session_id, request_id)
            typer.echo(json.dumps(item.model_dump(mode="json") if item else None, ensure_ascii=False, indent=2))
        finally:
            await manager.sessions[session_id].connection.disconnect()

    run(_main())


@forge_app.command("explore")
def forge_explore(session_id: str, goal: str = typer.Option(..., "--goal")) -> None:
    async def _main() -> None:
        manager, managed = await _attach(session_id)
        try:
            page_state = await manager.state(session_id)
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
    typer.echo(json.dumps({"ok": ok, "skill_dir": str(skill_dir)}, ensure_ascii=False, indent=2))


def _action(session_id: str, request: ActionRequest) -> None:
    async def _main() -> None:
        manager, _ = await _attach(session_id)
        try:
            result, after_state = await manager.action(session_id, request)
            _persist_attached(manager, session_id)
            payload = {"result": result.model_dump(mode="json")}
            if after_state:
                payload["state"] = after_state.model_dump(mode="json")
            typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        finally:
            await manager.sessions[session_id].connection.disconnect()

    run(_main())


async def _attach(session_id: str):
    store = SessionStore()
    session = store.get(session_id)
    if not session:
        raise typer.BadParameter(f"session not found: {session_id}")
    manager = SessionManager()
    managed = await manager.attach(session)
    return manager, managed


def _persist_attached(manager: SessionManager, session_id: str) -> None:
    managed = manager.sessions.get(session_id)
    if managed:
        SessionStore().save(managed.session)
