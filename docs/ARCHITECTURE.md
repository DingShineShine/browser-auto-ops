# Architecture

```text
CLI / FastAPI
  -> BrowserStore
    -> public browser types: chrome-direct, ads
  -> SessionManager
    -> BrowserProvider
      -> AdspowerCdpProvider
      -> ChromeDirectProvider
      -> GenericCdpProvider (internal helper)
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

- `BrowserIdentity`: employee-facing browser identity with `name`, `desc`, `type`, and provider config.
- `BrowserSession`: serializable metadata, also stored by CLI in `.bao/sessions.json`.
- `BrowserConnection`: live Playwright browser/page/context handle.
- `ManagedSession`: runtime tuple of metadata, connection, trace, network recorder, and last state.

CLI commands reconnect to stored CDP URLs per invocation. FastAPI keeps live sessions in memory.

Public browser types are intentionally narrower than internal providers:

- `chrome-direct` controls the employee's current local Chrome through the clean-room raw CDP path.
- `ads` starts or attaches to an AdsPower profile, ideally from a VPS-side browser-auto-ops sidecar so raw CDP is not exposed to employee desktops.

`local-chrome`, generic `cdp`, and `adspower-cdp` are implementation details and should not be presented as employee-facing browser choices.
