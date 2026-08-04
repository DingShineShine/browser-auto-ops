from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import websocket

from browser_auto_ops.errors import ProviderError


class RawCdpClient:
    def __init__(self, ws_url: str, timeout_ms: int, *, auto_allow: bool = False) -> None:
        self.ws_url = ws_url
        self.timeout = max(1.0, timeout_ms / 1000)
        self.auto_allow = auto_allow
        self._ws: websocket.WebSocket | None = None
        self._next_id = 0
        self._lock = threading.Lock()
        self._helpers: list[subprocess.Popen[Any]] = []

    async def connect(self) -> None:
        await asyncio.to_thread(self._connect_sync)

    def _connect_sync(self) -> None:
        if self.auto_allow:
            self._helpers = _start_auto_allow_helpers(self.timeout)
        self._ws = websocket.create_connection(self.ws_url, timeout=self.timeout, suppress_origin=True)

    async def close(self) -> None:
        ws = self._ws
        self._ws = None
        if ws:
            await asyncio.to_thread(ws.close)

    async def send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(self._send_sync, method, params or {}, session_id)

    def _send_sync(
        self,
        method: str,
        params: dict[str, Any],
        session_id: str | None,
    ) -> dict[str, Any]:
        if not self._ws:
            raise ProviderError("raw CDP websocket is not connected")
        with self._lock:
            self._next_id += 1
            message_id = self._next_id
            message: dict[str, Any] = {"id": message_id, "method": method, "params": params}
            if session_id:
                message["sessionId"] = session_id
            self._ws.send(json.dumps(message))
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                raw = self._ws.recv()
                data = json.loads(raw)
                if data.get("id") != message_id:
                    continue
                if "error" in data:
                    error = data["error"]
                    raise ProviderError(f"CDP {method} failed: {error}")
                return data.get("result") or {}
        raise ProviderError(f"Timed out waiting for CDP response to {method}")


class RawCdpBrowser:
    def __init__(self, client: RawCdpClient, page: "RawCdpPage") -> None:
        self.client = client
        self.context = RawCdpContext(page)
        self.contexts = [self.context]

    @property
    def page(self) -> "RawCdpPage":
        return self.context.pages[0]

    async def close(self) -> None:
        await self.client.close()

    async def page_targets(self) -> list[dict[str, Any]]:
        targets = await self.client.send("Target.getTargets")
        return _page_targets(targets.get("targetInfos", []))

    async def adopt_new_or_related_page(
        self,
        before_target_ids: set[str],
        *,
        opener_target_id: str | None = None,
    ) -> bool:
        targets = await self.page_targets()
        candidates = [target for target in targets if str(target.get("targetId") or "") not in before_target_ids]
        if not candidates:
            await self.page._refresh_url()
            return False
        target = _best_page_target(candidates, opener_target_id=opener_target_id)
        await self.switch_to_target(str(target["targetId"]))
        return True

    async def switch_to_target(self, target_id: str) -> "RawCdpPage":
        if target_id == self.page.target_id:
            await self.page._refresh_url()
            return self.page
        targets = await self.page_targets()
        target = next((item for item in targets if item.get("targetId") == target_id), None)
        if not target:
            raise ProviderError(f"CDP target is no longer available: {target_id}")
        try:
            await self.client.send("Target.activateTarget", {"targetId": target_id})
        except Exception:
            pass
        try:
            await self.client.send("Target.detachFromTarget", {"sessionId": self.page.session_id})
        except Exception:
            pass
        attach = await self.client.send("Target.attachToTarget", {"targetId": target_id, "flatten": True})
        page = RawCdpPage(self.client, target_id, attach["sessionId"], target.get("url") or "")
        await self.client.send("Page.enable", session_id=page.session_id)
        await self.client.send("Runtime.enable", session_id=page.session_id)
        await page._refresh_url()
        self.context.pages[0] = page
        return page


class RawCdpContext:
    def __init__(self, page: "RawCdpPage") -> None:
        self.pages = [page]

    async def new_page(self) -> "RawCdpPage":
        return self.pages[0]


class RawCdpPage:
    def __init__(self, client: RawCdpClient, target_id: str, session_id: str, url: str = "") -> None:
        self.client = client
        self.target_id = target_id
        self.session_id = session_id
        self._url = url
        self.mouse = RawCdpMouse(self)
        self.keyboard = RawCdpKeyboard(self)
        self.frames = [RawCdpFrame(self)]

    @property
    def url(self) -> str:
        return self._url

    @property
    def viewport_size(self) -> dict[str, int]:
        return {"width": 0, "height": 0}

    def on(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def is_closed(self) -> bool:
        return False

    async def bring_to_front(self) -> None:
        await self.client.send("Target.activateTarget", {"targetId": self.target_id})

    async def title(self) -> str:
        value = await self.evaluate("document.title")
        await self._refresh_url()
        return str(value or "")

    async def evaluate(self, script: str, arg: Any = None) -> Any:
        return await self.frames[0].evaluate(script, arg)

    async def goto(self, url: str, wait_until: str = "domcontentloaded") -> None:
        await self.client.send("Page.enable", session_id=self.session_id)
        await self.client.send("Page.navigate", {"url": url}, session_id=self.session_id)
        self._url = url
        await self.wait_for_load_state(wait_until)
        await self._refresh_url()

    async def _refresh_url(self) -> None:
        try:
            self._url = str(await self.evaluate("location.href"))
        except Exception:
            pass

    async def wait_for_load_state(self, state: str = "domcontentloaded", timeout: int = 30_000) -> None:
        if state == "networkidle":
            await asyncio.sleep(0.3)
            return
        deadline = time.monotonic() + timeout / 1000
        while time.monotonic() < deadline:
            try:
                ready = await self.evaluate("document.readyState")
                if ready in {"interactive", "complete"}:
                    return
            except Exception:
                pass
            await asyncio.sleep(0.1)

    async def wait_for_timeout(self, ms: int) -> None:
        await asyncio.sleep(ms / 1000)

    async def screenshot(self, path: str, full_page: bool = True) -> None:
        _ = full_page
        await self.client.send("Page.enable", session_id=self.session_id)
        result = await self.client.send(
            "Page.captureScreenshot",
            {"format": "png", "fromSurface": True},
            session_id=self.session_id,
        )
        Path(path).write_bytes(base64.b64decode(result.get("data", "")))


class RawCdpFrame:
    def __init__(self, page: RawCdpPage) -> None:
        self.page = page

    @property
    def url(self) -> str:
        return self.page.url

    async def evaluate(self, script: str, arg: Any = None) -> Any:
        expression = _expression(script, arg)
        result = await self.page.client.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": True,
                "userGesture": True,
            },
            session_id=self.page.session_id,
        )
        if result.get("exceptionDetails"):
            raise ProviderError(f"Runtime.evaluate failed: {result['exceptionDetails']}")
        remote = result.get("result") or {}
        if "value" in remote:
            return remote["value"]
        return remote.get("description")

    def locator(self, selector: str) -> "RawCdpLocator":
        return RawCdpLocator(self, selector)


class RawCdpLocator:
    def __init__(self, frame: RawCdpFrame, selector: str) -> None:
        self.frame = frame
        self.selector = selector

    async def select_option(self, label: str) -> None:
        xpath = self.selector.removeprefix("xpath=")
        await self.frame.evaluate(
            """
            ({xpath, label}) => {
              const node = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
              if (!node) throw new Error('node not found');
              const match = Array.from(node.options || []).find(o => o.label === label || o.text === label || o.value === label);
              if (!match) throw new Error('option not found');
              node.value = match.value;
              node.dispatchEvent(new Event('input', {bubbles: true}));
              node.dispatchEvent(new Event('change', {bubbles: true}));
            }
            """,
            {"xpath": xpath, "label": label},
        )

    async def set_input_files(self, _path: str) -> None:
        raise ProviderError("raw CDP chrome-direct does not support file upload yet")


class RawCdpMouse:
    def __init__(self, page: RawCdpPage) -> None:
        self.page = page
        self.x = 0.0
        self.y = 0.0

    async def move(self, x: float, y: float) -> None:
        self.x = x
        self.y = y
        await self.page.client.send(
            "Input.dispatchMouseEvent",
            {"type": "mouseMoved", "x": x, "y": y, "button": "none"},
            session_id=self.page.session_id,
        )

    async def down(self) -> None:
        await self.page.client.send(
            "Input.dispatchMouseEvent",
            {"type": "mousePressed", "x": self.x, "y": self.y, "button": "left", "clickCount": 1},
            session_id=self.page.session_id,
        )

    async def up(self) -> None:
        await self.page.client.send(
            "Input.dispatchMouseEvent",
            {"type": "mouseReleased", "x": self.x, "y": self.y, "button": "left", "clickCount": 1},
            session_id=self.page.session_id,
        )

    async def click(self, x: float, y: float) -> None:
        await self.move(x, y)
        await self.down()
        await self.up()

    async def wheel(self, dx: float, dy: float) -> None:
        await self.page.client.send(
            "Input.dispatchMouseEvent",
            {"type": "mouseWheel", "x": self.x, "y": self.y, "deltaX": dx, "deltaY": dy},
            session_id=self.page.session_id,
        )


class RawCdpKeyboard:
    def __init__(self, page: RawCdpPage) -> None:
        self.page = page

    async def type(self, text: str) -> None:
        await self.page.client.send("Input.insertText", {"text": text}, session_id=self.page.session_id)

    async def press(self, key: str) -> None:
        normalized = key.lower()
        if normalized in {"control+a", "ctrl+a"}:
            await self._key("a", "KeyA", 65, modifiers=2)
            return
        if normalized == "backspace":
            await self._key("Backspace", "Backspace", 8)
            return
        if normalized == "enter":
            await self._key("Enter", "Enter", 13)
            return
        if len(key) == 1:
            await self.type(key)
            return
        await self._key(key, key, 0)

    async def _key(self, key: str, code: str, windows_code: int, modifiers: int = 0) -> None:
        base = {
            "key": key,
            "code": code,
            "windowsVirtualKeyCode": windows_code,
            "nativeVirtualKeyCode": windows_code,
            "modifiers": modifiers,
        }
        await self.page.client.send(
            "Input.dispatchKeyEvent",
            {"type": "keyDown", **base},
            session_id=self.page.session_id,
        )
        await self.page.client.send(
            "Input.dispatchKeyEvent",
            {"type": "keyUp", **base},
            session_id=self.page.session_id,
        )


async def connect_raw_cdp(
    ws_url: str,
    timeout_ms: int,
    *,
    target_id: str | None = None,
    create_new: bool = True,
) -> RawCdpBrowser:
    client = RawCdpClient(ws_url, timeout_ms, auto_allow=True)
    await client.connect()
    try:
        target = await _resolve_page_target(client, target_id=target_id, create_new=create_new)
        attach = await client.send("Target.attachToTarget", {"targetId": target["targetId"], "flatten": True})
        session_id = attach["sessionId"]
        page = RawCdpPage(client, target["targetId"], session_id, target.get("url") or "")
        await client.send("Page.enable", session_id=session_id)
        await client.send("Runtime.enable", session_id=session_id)
        return RawCdpBrowser(client, page)
    except Exception:
        await client.close()
        raise


async def _resolve_page_target(
    client: RawCdpClient,
    *,
    target_id: str | None = None,
    create_new: bool = True,
) -> dict[str, Any]:
    targets = await client.send("Target.getTargets")
    target_infos = targets.get("targetInfos", [])

    if target_id:
        for target in target_infos:
            if target.get("targetId") == target_id:
                return target
        raise ProviderError(f"CDP target is no longer available: {target_id}")

    if not create_new:
        for target in _page_targets(target_infos):
            return target
        raise ProviderError("No page target is available for raw CDP connection")

    created = await client.send("Target.createTarget", {"url": "about:blank"})
    created_target_id = created["targetId"]
    targets = await client.send("Target.getTargets")
    for target in targets.get("targetInfos", []):
        if target.get("targetId") == created_target_id:
            return target
    return {"targetId": created_target_id, "type": "page", "url": "about:blank"}


def _page_targets(target_infos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [target for target in target_infos if target.get("type") == "page"]


def _best_page_target(
    target_infos: list[dict[str, Any]],
    *,
    opener_target_id: str | None = None,
) -> dict[str, Any]:
    def score(item: tuple[int, dict[str, Any]]) -> tuple[int, int, int, int]:
        index, target = item
        url = str(target.get("url") or "")
        opener = str(target.get("openerId") or "")
        return (
            1 if opener_target_id and opener == opener_target_id else 0,
            1 if url and url not in {"about:blank", "chrome://newtab/"} else 0,
            1 if url.startswith(("http://", "https://", "file://")) else 0,
            index,
        )

    return max(enumerate(target_infos), key=score)[1]


def _expression(script: str, arg: Any = None) -> str:
    stripped = script.strip()
    if arg is not None:
        return f"({stripped})({json.dumps(arg, ensure_ascii=False)})"
    if stripped.startswith("async ") or stripped.startswith("()") or "=>" in stripped[:80]:
        return f"({stripped})()"
    return stripped


def _start_auto_allow_helpers(timeout: float) -> list[subprocess.Popen[Any]]:
    if os.name != "nt":
        return []
    helpers: list[subprocess.Popen[Any]] = []
    for command in _auto_allow_helper_commands(timeout):
        try:
            helpers.append(
                subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            )
        except Exception:
            continue
    return helpers


def _auto_allow_helper_commands(timeout: float) -> list[list[str]]:
    seconds = str(max(3.0, timeout))
    commands = [
        [
            sys.executable,
            "-m",
            "browser_auto_ops.cdp_auto_allow_helper",
            "--timeout-seconds",
            seconds,
        ]
    ]
    browser_act_python = _browser_act_python()
    if browser_act_python:
        commands.insert(
            0,
            [
                str(browser_act_python),
                "-m",
                "browser_act_cli.cdp_auto_allow_helper",
                "--timeout-seconds",
                seconds,
            ],
        )
    return commands


def _browser_act_python() -> Path | None:
    candidates: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "uv" / "tools" / "browser-act-cli" / "Scripts" / "python.exe")
    candidates.append(Path.home() / "AppData" / "Roaming" / "uv" / "tools" / "browser-act-cli" / "Scripts" / "python.exe")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None
