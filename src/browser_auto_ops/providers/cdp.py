from __future__ import annotations

from urllib.parse import urlparse

import httpx
from playwright.async_api import async_playwright

from browser_auto_ops.errors import ProviderError
from browser_auto_ops.providers.base import BrowserConnection, first_page
from browser_auto_ops.schemas import BrowserSession, ProviderConfig


class GenericCdpProvider:
    name = "cdp"

    async def start(self, config: ProviderConfig) -> BrowserConnection:
        if not config.cdp_url:
            raise ProviderError("cdp provider requires cdp_url")
        cdp_url = await self._validate_or_resolve(config.cdp_url, config.timeout_ms)
        return await self._connect(cdp_url, config.timeout_ms)

    async def connect(self, session: BrowserSession) -> BrowserConnection:
        cdp_url = session.cdp_url or session.provider_config.cdp_url
        if not cdp_url:
            raise ProviderError(f"session {session.session_id} has no cdp_url")
        return await self._connect(cdp_url, session.provider_config.timeout_ms)

    async def stop(
        self,
        session: BrowserSession,
        connection: BrowserConnection | None = None,
    ) -> None:
        if connection:
            await connection.close()

    async def _connect(self, cdp_url: str, timeout_ms: int) -> BrowserConnection:
        try:
            playwright = await async_playwright().start()
            # AdsPower/Chrome already own download settings. Playwright's default
            # connect_over_cdp calls Browser.setDownloadBehavior and turns Wayfair's
            # client-side blob CSV into a UUID file with no extension.
            browser = await playwright.chromium.connect_over_cdp(
                cdp_url,
                timeout=timeout_ms,
                no_defaults=True,
            )
            context, page = await first_page(browser)
            return BrowserConnection(
                playwright=playwright,
                browser=browser,
                context=context,
                page=page,
                cdp_url=cdp_url,
                owns_browser=False,
            )
        except Exception as exc:
            raise ProviderError(f"Failed to connect CDP endpoint {cdp_url}: {exc}") from exc

    async def _validate_or_resolve(self, cdp_url: str, timeout_ms: int) -> str:
        parsed = urlparse(cdp_url)
        if parsed.scheme in {"ws", "wss"}:
            return cdp_url
        if parsed.scheme not in {"http", "https"}:
            raise ProviderError("cdp_url must start with http://, https://, ws://, or wss://")
        version_url = cdp_url.rstrip("/") + "/json/version"
        try:
            async with httpx.AsyncClient(timeout=timeout_ms / 1000) as client:
                response = await client.get(version_url)
                response.raise_for_status()
                payload = response.json()
                if not payload.get("webSocketDebuggerUrl"):
                    raise ProviderError(f"{version_url} did not return webSocketDebuggerUrl")
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"CDP health check failed for {version_url}: {exc}") from exc
        return cdp_url

