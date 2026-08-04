from __future__ import annotations

from urllib.parse import quote, urlparse

import httpx

from browser_auto_ops.errors import ProviderError
from browser_auto_ops.providers.base import BrowserConnection
from browser_auto_ops.providers.cdp import GenericCdpProvider
from browser_auto_ops.schemas import BrowserSession, ProviderConfig


class AdspowerCdpProvider:
    name = "adspower-cdp"

    def __init__(self) -> None:
        self._cdp = GenericCdpProvider()

    async def start(self, config: ProviderConfig) -> BrowserConnection:
        if not config.ads_base_url or not config.ads_user_id:
            raise ProviderError("adspower-cdp requires ads_base_url and ads_user_id")
        payload = await self._start_ads(config)
        ws = payload.get("data", {}).get("ws", {})
        cdp_url = ws.get("puppeteer")
        if not cdp_url:
            raise ProviderError("AdsPower start response did not include data.ws.puppeteer")
        parsed = urlparse(cdp_url)
        if parsed.hostname in {"127.0.0.1", "localhost"}:
            # This is still allowed, but the error on connect should be explicit.
            host_hint = (
                "AdsPower returned a loopback ws.puppeteer. browser-auto-ops must run on "
                "the ADS host, or you must configure cdp_mask / SSH tunnel / sidecar."
            )
        else:
            host_hint = ""
        try:
            connection = await self._cdp._connect(cdp_url, config.timeout_ms)
        except Exception as exc:
            message = f"Failed to connect AdsPower CDP {cdp_url}: {exc}"
            if host_hint:
                message += f" {host_hint}"
            raise ProviderError(message) from exc
        connection.meta.update(
            {
                "ads_base_url": config.ads_base_url,
                "ads_user_id": config.ads_user_id,
                "ads_start_response": payload,
            }
        )
        return connection

    async def connect(self, session: BrowserSession) -> BrowserConnection:
        if not session.cdp_url:
            raise ProviderError("Cannot reconnect adspower-cdp session without stored cdp_url")
        connection = await self._cdp._connect(session.cdp_url, session.provider_config.timeout_ms)
        connection.meta.update(session.meta)
        return connection

    async def stop(
        self,
        session: BrowserSession,
        connection: BrowserConnection | None = None,
    ) -> None:
        if connection:
            await connection.close()
        config = session.provider_config
        if config.ads_base_url and config.ads_user_id:
            await self._stop_ads(config)

    async def _start_ads(self, config: ProviderConfig) -> dict:
        base = config.ads_base_url.rstrip("/")
        user_id = quote(config.ads_user_id or "", safe="")
        params = {"user_id": config.ads_user_id}
        if config.api_key:
            params["api_key"] = config.api_key
        url = f"{base}/api/v1/browser/start"
        async with httpx.AsyncClient(timeout=config.timeout_ms / 1000) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        if payload.get("code") != 0:
            raise ProviderError(f"AdsPower start failed for {user_id}: {payload}")
        return payload

    async def _stop_ads(self, config: ProviderConfig) -> None:
        base = config.ads_base_url.rstrip("/")
        params = {"user_id": config.ads_user_id}
        if config.api_key:
            params["api_key"] = config.api_key
        url = f"{base}/api/v1/browser/stop"
        async with httpx.AsyncClient(timeout=config.timeout_ms / 1000) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()

