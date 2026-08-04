# browser-auto-ops v1 Project Plan

## Goal

Implement a clean-room browser automation engine with ADS/AdsPower, local Chrome, BrowserAct-style direct Chrome, and generic CDP providers:

- `adspower-cdp`: start an AdsPower profile and connect to `data.ws.puppeteer`.
- `local-chrome`: launch an isolated local Chrome profile and connect over CDP.
- `chrome-direct`: BrowserAct-style local direct mode for a real local Chrome profile, gated by explicit confirmation.
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
- Providers: `adspower-cdp`, `local-chrome`, `chrome-direct`, `cdp`
- Docs: this `docs/` set
- Tests: unit tests plus local/ADS smoke-test hooks

## Local Browser Semantics

`local-chrome` and `chrome-direct` are intentionally different:

- `local-chrome` is safe isolated automation. It starts a separate profile and does not touch the user's everyday Chrome state.
- `chrome-direct` is BrowserAct-style direct local control. It can access the user's real Chrome profile state, so it requires `--confirm-direct` / `confirm_direct=true`. It discovers `DevToolsActivePort` and uses raw CDP instead of assuming `/json/version` works.

## Out Of Scope For v1

- `adspower-selenium`
- Generic Selenium Grid support
- Automatic SSH tunneling for AdsPower loopback CDP URLs
- General captcha solving
