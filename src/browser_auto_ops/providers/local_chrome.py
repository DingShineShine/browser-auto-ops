from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

import httpx

from browser_auto_ops.errors import ProviderError
from browser_auto_ops.providers.base import BrowserConnection, allocate_port, normalize_dir
from browser_auto_ops.providers.cdp import GenericCdpProvider
from browser_auto_ops.schemas import BrowserSession, ProviderConfig


class LocalChromeProvider:
    name = "local-chrome"

    def __init__(self) -> None:
        self._cdp = GenericCdpProvider()

    async def start(self, config: ProviderConfig) -> BrowserConnection:
        chrome = config.chrome_path or find_chrome_executable()
        if not chrome:
            raise ProviderError("Could not find Chrome executable; pass --chrome-path")
        user_data_dir = normalize_dir(config.user_data_dir or (Path.cwd() / ".bao" / "chrome-profile"))
        port = config.remote_debugging_port or allocate_port()
        endpoint = f"http://127.0.0.1:{port}"
        args = [
            str(chrome),
            f"--remote-debugging-port={port}",
            f"--user-data-dir={user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-popup-blocking",
        ]
        if not config.headful:
            args.append("--headless=new")
        if config.start_url:
            args.append(config.start_url)
        args.extend(config.extra_args)

        process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            await wait_for_cdp(endpoint, config.timeout_ms)
            connection = await self._cdp._connect(endpoint, config.timeout_ms)
            connection.process = process
            connection.owns_browser = True
            connection.meta.update({"user_data_dir": str(user_data_dir), "port": port})
            return connection
        except Exception:
            if process.poll() is None:
                process.terminate()
            raise

    async def connect(self, session: BrowserSession) -> BrowserConnection:
        if not session.cdp_url:
            raise ProviderError("Cannot reconnect local-chrome session without cdp_url")
        connection = await self._cdp._connect(session.cdp_url, session.provider_config.timeout_ms)
        connection.owns_browser = True
        return connection

    async def stop(
        self,
        session: BrowserSession,
        connection: BrowserConnection | None = None,
    ) -> None:
        if connection:
            await connection.close()
            return
        if session.process_pid:
            try:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(session.process_pid), "/T", "/F"],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    os.kill(session.process_pid, 15)
            except Exception:
                pass


async def wait_for_cdp(endpoint: str, timeout_ms: int) -> None:
    deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
    version_url = endpoint.rstrip("/") + "/json/version"
    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=2.0) as client:
        while asyncio.get_event_loop().time() < deadline:
            try:
                response = await client.get(version_url)
                if response.status_code == 200 and response.json().get("webSocketDebuggerUrl"):
                    return
            except Exception as exc:
                last_error = exc
            await asyncio.sleep(0.25)
    raise ProviderError(f"Timed out waiting for local Chrome CDP at {version_url}: {last_error}")


def find_chrome_executable() -> Path | None:
    candidates: list[Path] = []
    if os.name == "nt":
        for env_name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            root = os.environ.get(env_name)
            if root:
                candidates.append(Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe")
        candidates.append(Path("C:/Program Files/Google/Chrome/Application/chrome.exe"))
        candidates.append(Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"))
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            path = shutil_which(name)
            if path:
                candidates.append(Path(path))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def shutil_which(name: str) -> str | None:
    import shutil

    return shutil.which(name)

