# browser-auto-ops Runtime Reference

The installed CLI is the source of truth. Always start with:

```bash
bao get-skills core
```

## Public Browser Types

- `chrome-direct`: controls the employee's current local Chrome through CDP. Use only after explicit confirmation.
- `ads`: controls a company-managed ADS/AdsPower profile, preferably through the VPS-side browser-auto-ops sidecar.

Do not expose `local-chrome`, generic `cdp`, or `adspower-cdp` as employee-facing browser types. They are implementation details.

## Core Workflow

```bash
bao daemon start
bao browser list
bao browser create --type chrome-direct --name local --desc "Employee current Chrome" --confirm-before-use
bao browser create --type ads --name amazon-us-01 --desc "VPS AdsPower profile" --ads-base-url http://HOST:PORT --ads-user-id PROFILE_ID
bao chrome-direct authorize
bao --session task-name browser open <browser_id_or_name> https://example.com --confirm
bao --session task-name state
bao --session task-name click 3
bao --session task-name input 1 "keyword"
bao --session task-name wait stable
bao --session task-name get title
bao --session task-name get markdown
bao --session task-name tab list
bao --session task-name cookies get
bao --session task-name wait selector 3 --state visible
bao --session task-name network requests --type xhr,fetch --filter /api/
bao --session task-name downloads wait latest --output D:\exports
bao session close task-name
```

Indexes are temporary. Re-run `bao --session <name> state` after navigation or DOM changes.

## ADS/VPS Notes

AdsPower often returns a loopback `ws.puppeteer` URL. In production, run browser-auto-ops on the VPS or through an authenticated sidecar so the raw CDP endpoint is not exposed to employee desktops.

## Safety

- Do not expose CDP ports publicly.
- Do not auto-submit payment, delete, publish, approve, or account-changing operations.
- Use `--confirm` only after explicit user approval.
- Treat cookies, authorization headers, passwords, verification codes, and AdsPower profile identifiers as sensitive.

## Daemon Requirement

Use `bao daemon start` before `chrome-direct` work. Without the daemon, legacy reconnect mode may trigger Chrome's remote-debugging permission dialog on every command.

## Known Boundaries

- `dialog accept/dismiss` currently returns a clear unsupported response unless persistent dialog tracking is added.
- `network har start/stop` is registered but currently reports that HAR capture is not active; use request/response trace evidence for now.
- Raw CDP `chrome-direct` has a smaller capability surface than Playwright-backed `ads`.
