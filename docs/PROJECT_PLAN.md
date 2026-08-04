# browser-auto-ops v1 Project Plan

## Goal

Implement a clean-room browser automation engine for three v1 providers:

- `adspower-cdp`: start an AdsPower profile and connect to `data.ws.puppeteer`.
- `local-chrome`: launch an isolated local Chrome profile and connect over CDP.
- `cdp`: connect to any existing CDP endpoint.

The product shape is:

```text
Provider connection
  -> BrowserAct/Browser Use style state/index
  -> deterministic action executor
  -> Stagehand style observe/act/extract
  -> CDP network recording
  -> Skyvern style trace/action records
  -> BrowserAct Skill Forge style skill generation
```

## Deliverables

- Python package: `browser_auto_ops`
- CLI: `bao`
- API server: `browser_auto_ops.server:app`
- Providers: `adspower-cdp`, `local-chrome`, `cdp`
- Docs: this `docs/` set
- Tests: unit tests plus local/ADS smoke-test hooks

## Out Of Scope For v1

- `adspower-selenium`
- Generic Selenium Grid support
- BrowserAct-style direct takeover of a user's default Chrome
- Automatic SSH tunneling for AdsPower loopback CDP URLs
- General captcha solving

