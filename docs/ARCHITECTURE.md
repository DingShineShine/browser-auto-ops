# Architecture

```text
CLI / FastAPI
  -> SessionManager
    -> BrowserProvider
      -> AdspowerCdpProvider
      -> LocalChromeProvider
      -> ChromeDirectProvider
      -> GenericCdpProvider
    -> SnapshotEngine
    -> ActionExecutor
    -> ObserveService / ActService / ExtractService
    -> NetworkRecorder
    -> TraceRecorder
    -> ForgeEngine
```

## Provider Interface

```python
class BrowserProvider(Protocol):
    async def start(self, config: ProviderConfig) -> BrowserConnection: ...
    async def connect(self, session: BrowserSession) -> BrowserConnection: ...
    async def stop(self, session: BrowserSession, connection: BrowserConnection | None = None) -> None: ...
```

## Runtime Model

- `BrowserSession`: serializable metadata, also stored by CLI in `.bao/sessions.json`.
- `BrowserConnection`: live Playwright browser/page/context handle.
- `ManagedSession`: runtime tuple of metadata, connection, trace, network recorder, and last state.

CLI commands reconnect to stored CDP URLs per invocation. FastAPI keeps live sessions in memory.
