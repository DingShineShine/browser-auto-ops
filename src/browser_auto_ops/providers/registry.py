from __future__ import annotations

from browser_auto_ops.errors import ProviderError
from browser_auto_ops.providers.adspower_cdp import AdspowerCdpProvider
from browser_auto_ops.providers.base import BrowserProvider
from browser_auto_ops.providers.cdp import GenericCdpProvider
from browser_auto_ops.providers.chrome_direct import ChromeDirectProvider
from browser_auto_ops.providers.local_chrome import LocalChromeProvider


def provider_for(name: str) -> BrowserProvider:
    providers: dict[str, BrowserProvider] = {
        "adspower-cdp": AdspowerCdpProvider(),
        "local-chrome": LocalChromeProvider(),
        "chrome-direct": ChromeDirectProvider(),
        "cdp": GenericCdpProvider(),
    }
    try:
        return providers[name]
    except KeyError as exc:
        raise ProviderError(f"Unsupported provider: {name}") from exc
