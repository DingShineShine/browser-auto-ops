# Providers

## `adspower-cdp`

Starts AdsPower and connects to `data.ws.puppeteer`.

If AdsPower returns `ws://127.0.0.1:port/...`, browser-auto-ops must run on the AdsPower host or use user-managed forwarding. v1 intentionally does not create SSH tunnels.

## `local-chrome`

Starts a new isolated Chrome profile:

```text
chrome.exe --remote-debugging-port=<port> --user-data-dir=<isolated-dir>
```

This is local because it uses the machine's Chrome binary, but it does not attach to the user's everyday Chrome profile. It is closest to a clean local automation browser.

## `chrome-direct`

BrowserAct-style local direct mode.

Goal:

```text
control a real local Chrome profile through a local CDP endpoint
```

Start:

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

## `cdp`

Connects to an existing endpoint:

```text
http://host:port
ws://host:port/devtools/browser/<id>
```

It does not own or stop external browsers.
