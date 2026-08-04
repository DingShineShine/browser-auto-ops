# browser-auto-ops v1 Project Plan

## Goal

Implement a clean-room BrowserAct-style enterprise browser automation engine with two employee-facing browser types:

- `chrome-direct`: BrowserAct-style local direct mode for a real local Chrome profile, gated by explicit confirmation.
- `ads`: company-managed ADS/AdsPower profiles, preferably controlled from a VPS-side browser-auto-ops sidecar.

The product shape is:

```text
Browser identity
  -> named session
  -> provider connection
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
- Public browser types: `chrome-direct`, `ads`
- Internal provider helpers: `adspower-cdp`, `cdp`, and local development helpers
- Docs: this `docs/` set
- Tests: unit tests plus local/ADS smoke-test hooks

## Local Browser Semantics

`ads` and `chrome-direct` are intentionally different:

- `chrome-direct` is BrowserAct-style direct local control. It can access the user's real Chrome profile state, so it requires `--confirm-direct` / `confirm_direct=true`. It discovers `DevToolsActivePort` and uses raw CDP instead of assuming `/json/version` works.
- `ads` controls an AdsPower profile. In production, browser-auto-ops should run on the VPS/ADS host or through a sidecar so `ws.puppeteer` is not exposed publicly.

## Out Of Scope For v1

- `adspower-selenium`
- Generic Selenium Grid support
- Automatic SSH tunneling for AdsPower loopback CDP URLs
- General captcha solving
