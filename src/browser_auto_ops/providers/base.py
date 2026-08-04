from __future__ import annotations

import asyncio
import socket
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from playwright.async_api import Browser, BrowserContext, Page, Playwright

from browser_auto_ops.schemas import BrowserSession, ProviderConfig


@dataclass
class BrowserConnection:
    playwright: Playwright | None
    browser: Browser | Any
    context: BrowserContext | Any
    page: Page | Any
    cdp_url: str
    process: subprocess.Popen[Any] | None = None
    owns_browser: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    async def close(self) -> None:
        if self.owns_browser:
            await self.browser.close()
        elif self.playwright is None and hasattr(self.browser, "close"):
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                await asyncio.to_thread(self.process.wait, 5)
            except Exception:
                self.process.kill()

    async def disconnect(self) -> None:
        """Disconnect automation transport without closing an externally managed browser."""
        if self.playwright is None and hasattr(self.browser, "close"):
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()


class BrowserProvider(Protocol):
    name: str

    async def start(self, config: ProviderConfig) -> BrowserConnection:
        ...

    async def connect(self, session: BrowserSession) -> BrowserConnection:
        ...

    async def stop(
        self,
        session: BrowserSession,
        connection: BrowserConnection | None = None,
    ) -> None:
        ...


def allocate_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def first_page(browser: Browser) -> tuple[BrowserContext, Page]:
    context = browser.contexts[0] if browser.contexts else await browser.new_context()
    page = context.pages[0] if context.pages else await context.new_page()
    return context, page


def normalize_dir(path: Path) -> Path:
    path = path.expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path
