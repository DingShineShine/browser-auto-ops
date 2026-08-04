from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from browser_auto_ops.config import ensure_data_dirs
from browser_auto_ops.errors import ProviderError
from browser_auto_ops.schemas import BrowserIdentity, ProviderConfig


class BrowserStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = ensure_data_dirs(root)
        self.path = self.root / "browsers.json"

    def list(self) -> list[BrowserIdentity]:
        return list(self._read().values())

    def get(self, browser_id_or_name: str) -> BrowserIdentity | None:
        browsers = self._read()
        if browser_id_or_name in browsers:
            return browsers[browser_id_or_name]
        for browser in browsers.values():
            if browser.name == browser_id_or_name:
                return browser
        return None

    def save(self, browser: BrowserIdentity) -> None:
        browsers = self._read()
        browser.updated_at = datetime.now(timezone.utc)
        browsers[browser.browser_id] = browser
        self._write(browsers)

    def delete(self, browser_id_or_name: str) -> BrowserIdentity | None:
        browsers = self._read()
        browser = self.get(browser_id_or_name)
        if not browser:
            return None
        browsers.pop(browser.browser_id, None)
        self._write(browsers)
        return browser

    def _read(self) -> dict[str, BrowserIdentity]:
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return {
            browser_id: BrowserIdentity.model_validate(payload)
            for browser_id, payload in raw.items()
        }

    def _write(self, browsers: dict[str, BrowserIdentity]) -> None:
        payload = {
            browser_id: browser.model_dump(mode="json")
            for browser_id, browser in browsers.items()
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def provider_config_for_browser(
    browser: BrowserIdentity,
    *,
    start_url: str | None = None,
    confirm: bool = False,
) -> ProviderConfig:
    config = browser.provider_config.model_copy(deep=True)
    config.start_url = start_url or config.start_url
    if browser.type == "chrome-direct":
        if browser.confirm_before_use and not confirm:
            raise ProviderError("browser requires explicit confirmation; rerun browser open with --confirm")
        config.provider = "chrome-direct"
        config.confirm_direct = confirm or config.confirm_direct
    elif browser.type == "ads":
        config.provider = "adspower-cdp"
    else:
        raise ProviderError(f"Unsupported public browser type: {browser.type}")
    return config
