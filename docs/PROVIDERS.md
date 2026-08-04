# Browser Types And Providers

Employee-facing browser types are `chrome-direct` and `ads`. Lower-level provider names remain implementation details.

## `ads`

Starts an AdsPower/ADS profile and connects to `data.ws.puppeteer`.

```bash
bao browser create --type ads --name amazon-us-01 --desc "VPS AdsPower profile" --ads-base-url http://HOST:PORT --ads-user-id PROFILE_ID
bao --session work browser open amazon-us-01 https://example.com
```

If AdsPower returns `ws://127.0.0.1:port/...`, browser-auto-ops should run on the AdsPower/VPS host or through an authenticated sidecar. Do not expose raw CDP ports publicly.

Internal provider: `adspower-cdp`.

## `chrome-direct`

BrowserAct-style local direct mode.

Goal:

```text
control a real local Chrome profile through a local CDP endpoint
```

Create and open:

```bash
bao browser create --type chrome-direct --name local --desc "Employee current Chrome" --confirm-before-use
bao --session local-task browser open local https://example.com --confirm
```

Legacy direct start still exists for development diagnostics:

```bash
bao session start \
  --provider chrome-direct \
  --confirm-direct \
  --remote-debugging-port 9222 \
  --start-url https://www.baidu.com
```

Or attach to a Chrome that is already running with remote debugging:

```bash
bao session start \
  --provider chrome-direct \
  --cdp-url http://127.0.0.1:9222 \
  --confirm-direct
```

Behavior:

- Requires explicit `--confirm-direct` / `confirm_direct=true`.
- Reads the default Chrome profile's `DevToolsActivePort` and connects to the real `ws://127.0.0.1:<port>/devtools/browser/<id>` endpoint.
- Does not rely on `/json/version` for default-profile direct mode; Chrome may return 404 there while the WebSocket endpoint is valid.
- Uses raw CDP transport for `chrome-direct` because Playwright `connect_over_cdp` can hang on default-profile Chrome permission flows.
- Starts a remote-debugging auto-allow watcher during CDP connection. If BrowserAct is installed, its helper is used as a compatibility watcher; browser-auto-ops also ships a clean-room pywinauto fallback helper.
- If `DevToolsActivePort` is missing, it sets `devtools.remote_debugging.user-enabled=true` in Chrome `Local State`, launches Chrome, and waits for `DevToolsActivePort`.
- It does not close the user's Chrome on stop; it only disconnects automation.
- If Chrome is already running without remote debugging, Chrome may ignore the new debug-port launch. In that case close all Chrome windows and start again, or manually launch Chrome with a debug port.

Manual direct launch example:

```powershell
chrome.exe --remote-debugging-port=9222 --user-data-dir="$env:LOCALAPPDATA\Google\Chrome\User Data"
```

## Internal Helpers

- `adspower-cdp`: provider behind the public `ads` browser type.
- `cdp`: generic endpoint connector used internally and for development diagnostics.
- `local-chrome`: local isolated Chrome helper retained for diagnostics, not employee-facing.
