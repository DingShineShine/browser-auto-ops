from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from browser_auto_ops.errors import ProviderError
from browser_auto_ops.providers.base import BrowserConnection
from browser_auto_ops.providers.cdp import GenericCdpProvider
from browser_auto_ops.providers.local_chrome import find_chrome_executable
from browser_auto_ops.providers.raw_cdp import connect_raw_cdp
from browser_auto_ops.schemas import BrowserSession, ProviderConfig


@dataclass(frozen=True)
class DevToolsActivePort:
    port: int
    ws_path: str

    @property
    def ws_url(self) -> str:
        return f"ws://127.0.0.1:{self.port}{self.ws_path}"


class ChromeDirectProvider:
    name = "chrome-direct"

    def __init__(self) -> None:
        self._cdp = GenericCdpProvider()

    async def start(self, config: ProviderConfig) -> BrowserConnection:
        if not config.confirm_direct:
            raise ProviderError(
                "chrome-direct controls a real local Chrome profile. "
                "Pass --confirm-direct or set confirm_direct=true after explicit user approval."
            )

        user_data_dir = _default_user_data_dir(config)
        if config.cdp_url:
            connection = await self._connect_explicit(config, user_data_dir)
        else:
            connection = await self._connect_default_profile(config, user_data_dir)

        if config.start_url:
            await connection.page.goto(config.start_url, wait_until="domcontentloaded")
        return connection

    async def connect(self, session: BrowserSession) -> BrowserConnection:
        cdp_url = session.cdp_url or session.provider_config.cdp_url
        if not cdp_url:
            raise ProviderError("Cannot reconnect chrome-direct session without cdp_url")
        if cdp_url.startswith(("ws://", "wss://")):
            target_id = _meta_str(session.meta, "target_id")
            return await _connect_raw(
                cdp_url,
                session.provider_config.timeout_ms,
                {"mode": "chrome-direct", "transport": "raw-cdp"},
                target_id=target_id,
                create_new=target_id is None,
            )
        connection = await self._cdp._connect(cdp_url, session.provider_config.timeout_ms)
        connection.owns_browser = False
        connection.meta.update({"mode": "chrome-direct", "transport": "playwright-cdp"})
        return connection

    async def stop(
        self,
        session: BrowserSession,
        connection: BrowserConnection | None = None,
    ) -> None:
        if connection:
            await connection.disconnect()

    async def _connect_explicit(self, config: ProviderConfig, user_data_dir: Path) -> BrowserConnection:
        cdp_url = config.cdp_url or ""
        if cdp_url.startswith(("ws://", "wss://")):
            return await _connect_raw(cdp_url, config.timeout_ms, {"mode": "chrome-direct", "transport": "raw-cdp"})

        parsed = urlparse(cdp_url)
        if parsed.scheme in {"http", "https"}:
            port = parsed.port
            active = _read_devtools_active_port(user_data_dir)
            if active and (port is None or active.port == port) and _port_is_open("127.0.0.1", active.port):
                return await _connect_raw(
                    active.ws_url,
                    config.timeout_ms,
                    {"mode": "chrome-direct", "transport": "raw-cdp", "discovery": "DevToolsActivePort"},
                )
            try:
                connection = await self._cdp.start(config)
                connection.meta.update({"mode": "chrome-direct", "transport": "playwright-cdp"})
                return connection
            except ProviderError as exc:
                raise ProviderError(
                    f"chrome-direct could not connect explicit endpoint {cdp_url}. "
                    "For default Chrome, prefer DevToolsActivePort/ws discovery. "
                    f"Original error: {exc}"
                ) from exc

        raise ProviderError("chrome-direct cdp_url must start with http://, https://, ws://, or wss://")

    async def _connect_default_profile(self, config: ProviderConfig, user_data_dir: Path) -> BrowserConnection:
        if not user_data_dir.exists():
            raise ProviderError(f"Chrome user data directory does not exist: {user_data_dir}")

        active = _read_live_devtools_active_port(user_data_dir)
        if active:
            return await _connect_raw(
                active.ws_url,
                config.timeout_ms,
                {
                    "mode": "chrome-direct",
                    "transport": "raw-cdp",
                    "discovery": "DevToolsActivePort",
                    "user_data_dir": str(user_data_dir),
                    "port": active.port,
                },
            )

        _set_local_state_remote_debugging_enabled(user_data_dir)
        launch_error = await _open_chrome_for_direct(config, user_data_dir)
        if launch_error:
            raise ProviderError(_direct_error(user_data_dir, launch_error)) from launch_error

        active = await _wait_for_live_devtools_active_port(user_data_dir, config.timeout_ms)
        if not active:
            raise ProviderError(
                _direct_error(
                    user_data_dir,
                    ProviderError("DevToolsActivePort did not appear after launching Chrome"),
                )
            )
        return await _connect_raw(
            active.ws_url,
            config.timeout_ms,
            {
                "mode": "chrome-direct",
                "transport": "raw-cdp",
                "discovery": "DevToolsActivePort-after-launch",
                "user_data_dir": str(user_data_dir),
                "port": active.port,
            },
        )


async def _connect_raw(
    ws_url: str,
    timeout_ms: int,
    meta: dict[str, object],
    *,
    target_id: str | None = None,
    create_new: bool = True,
) -> BrowserConnection:
    browser = await connect_raw_cdp(ws_url, timeout_ms, target_id=target_id, create_new=create_new)
    context = browser.contexts[0]
    page = context.pages[0]
    connection_meta = {**meta, "target_id": page.target_id}
    return BrowserConnection(
        playwright=None,
        browser=browser,
        context=context,
        page=page,
        cdp_url=ws_url,
        owns_browser=False,
        meta=connection_meta,
    )


async def _open_chrome_for_direct(config: ProviderConfig, user_data_dir: Path) -> Exception | None:
    chrome = config.chrome_path or find_chrome_executable()
    if not chrome:
        return ProviderError("Could not find Chrome executable; pass --chrome-path")

    args = [
        str(chrome),
        f"--user-data-dir={user_data_dir}",
        f"--remote-debugging-port={config.remote_debugging_port or 0}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    profile = config.chrome_profile or "Default"
    if profile:
        args.append(f"--profile-directory={profile}")
    args.append(config.start_url or "chrome://inspect/#devices")
    args.extend(config.extra_args)
    try:
        subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return None
    except Exception as exc:
        return exc


def _read_live_devtools_active_port(user_data_dir: Path) -> DevToolsActivePort | None:
    active = _read_devtools_active_port(user_data_dir)
    if active and _port_is_open("127.0.0.1", active.port):
        return active
    return None


async def _wait_for_live_devtools_active_port(user_data_dir: Path, timeout_ms: int) -> DevToolsActivePort | None:
    deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
    while asyncio.get_event_loop().time() < deadline:
        active = _read_live_devtools_active_port(user_data_dir)
        if active:
            return active
        await asyncio.sleep(0.2)
    return None


def _read_devtools_active_port(user_data_dir: Path) -> DevToolsActivePort | None:
    path = user_data_dir / "DevToolsActivePort"
    if not path.exists():
        return None
    try:
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(lines) < 2:
            return None
        port = int(lines[0])
        ws_path = lines[1]
        if not ws_path.startswith("/"):
            return None
        return DevToolsActivePort(port=port, ws_path=ws_path)
    except Exception:
        return None


def _set_local_state_remote_debugging_enabled(user_data_dir: Path) -> None:
    path = user_data_dir / "Local State"
    if not path.exists():
        raise ProviderError(f"Chrome Local State file does not exist: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        devtools = data.setdefault("devtools", {})
        remote_debugging = devtools.setdefault("remote_debugging", {})
        if remote_debugging.get("user-enabled") is True:
            return
        remote_debugging["user-enabled"] = True
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        temp.replace(path)
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError(f"Could not enable Chrome remote debugging in Local State: {exc}") from exc


def _port_is_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _default_user_data_dir(config: ProviderConfig) -> Path:
    if config.user_data_dir:
        return config.user_data_dir.expanduser().resolve()
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "Google" / "Chrome" / "User Data"
    if os.name == "posix":
        home = Path.home()
        candidates = [
            home / ".config" / "google-chrome",
            home / ".config" / "chromium",
            home / "Library" / "Application Support" / "Google" / "Chrome",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
    return Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data"


def _meta_str(meta: dict[str, object], key: str) -> str | None:
    value = meta.get(key)
    return value if isinstance(value, str) and value else None


def _direct_error(user_data_dir: Path, cause: Exception) -> str:
    return (
        "chrome-direct could not enable or discover default Chrome remote debugging.\n"
        f"User data dir: {user_data_dir}\n"
        f"Cause: {cause}\n"
        "BrowserAct-compatible notes: default-profile direct mode should read DevToolsActivePort, not rely on /json/version. "
        "If DevToolsActivePort is missing, Chrome may need its remote debugging permission enabled from chrome://inspect/#devices "
        "or a restart after Local State is updated."
    )
