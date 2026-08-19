import pytest

from browser_auto_ops.providers.cdp import GenericCdpProvider


class _FakePage:
    pass


class _FakeContext:
    pages = [_FakePage()]


class _FakeBrowser:
    contexts = [_FakeContext()]


class _FakeChromium:
    def __init__(self, captured: dict) -> None:
        self._captured = captured

    async def connect_over_cdp(self, endpoint_url: str, **kwargs):
        self._captured["url"] = endpoint_url
        self._captured["kwargs"] = kwargs
        return _FakeBrowser()


class _FakePlaywright:
    def __init__(self, captured: dict) -> None:
        self.chromium = _FakeChromium(captured)

    async def stop(self) -> None:
        return None


class _FakeAsyncPlaywright:
    def __init__(self, captured: dict) -> None:
        self._captured = captured

    async def start(self) -> _FakePlaywright:
        return _FakePlaywright(self._captured)


@pytest.mark.asyncio
async def test_cdp_connect_preserves_browser_download_defaults(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(
        "browser_auto_ops.providers.cdp.async_playwright",
        lambda: _FakeAsyncPlaywright(captured),
    )

    connection = await GenericCdpProvider()._connect("http://127.0.0.1:9222", 5000)

    assert captured["url"] == "http://127.0.0.1:9222"
    assert captured["kwargs"]["timeout"] == 5000
    assert captured["kwargs"]["no_defaults"] is True
    assert connection.owns_browser is False
    assert connection.cdp_url == "http://127.0.0.1:9222"
