# browser-auto-ops

`browser-auto-ops` is a clean-room browser automation engine for ADS/AdsPower,
local Chrome, and generic CDP endpoints.

It implements the v1 plan:

- Providers: `adspower-cdp`, `local-chrome`, `chrome-direct`, `cdp`
- BrowserAct-style `state` with indexed interactive elements
- Deterministic action executor with real browser events first, `hover`, and JS fallback
- Executor-level confirmation gate for dangerous operations
- Stagehand-style `observe`, `act`, and `extract`
- CDP network recording
- JSONL trace artifacts plus rolling `summary.json`
- BrowserAct Skill Forge-style `forge generate` with trace-informed extraction scripts

CLI command:

```bash
bao --help
```

Run API server:

```bash
uvicorn browser_auto_ops.server:app --reload
```
