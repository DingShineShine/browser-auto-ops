# browser-auto-ops Runtime Reference

Runtime path:

```text
E:\code\work\browser-auto-ops
```

Run commands from that directory:

```bash
cd E:\code\work\browser-auto-ops
uv run bao --help
```

Install as global tool if needed:

```bash
uv tool install E:\code\work\browser-auto-ops --force
```

Run API server:

```bash
uv run uvicorn browser_auto_ops.server:app --host 127.0.0.1 --port 8765
```

## Providers

### adspower-cdp

```bash
bao session start --provider adspower-cdp --ads-base-url http://HOST:PORT --ads-user-id PROFILE_ID
```

This calls AdsPower `/api/v1/browser/start`, reads `data.ws.puppeteer`, and
connects with Playwright CDP.

If the returned URL is `ws://127.0.0.1:...`, browser-auto-ops must run on the
AdsPower host, or the user must configure `cdp_mask`, SSH forwarding, or a
sidecar. v1 does not create tunnels automatically.

### local-chrome

```bash
bao session start --provider local-chrome --user-data-dir E:\tmp\bao-profile --headful
```

This starts an isolated local Chrome profile with remote debugging and connects
over CDP. It does not attach to the user's default Chrome.

### chrome-direct

```bash
bao session start --provider chrome-direct --confirm-direct --remote-debugging-port 9222
bao session start --provider chrome-direct --cdp-url http://127.0.0.1:9222 --confirm-direct
```

This is the BrowserAct-style local direct path. It controls a real local Chrome
profile through a local CDP endpoint. It requires explicit confirmation because
it can access the user's cookies, extensions, certificates, and open-session
state.

Implementation notes:

- Reads `DevToolsActivePort` from the default Chrome user-data directory.
- Connects to the direct `ws://127.0.0.1:<port>/devtools/browser/<id>` endpoint.
- Does not rely on `/json/version` for default-profile direct mode.
- Uses raw CDP transport and a remote-debugging auto-allow watcher.

If Chrome is already running without a usable `DevToolsActivePort`, the provider
sets the Chrome `Local State` remote-debugging flag and launches Chrome. If that
still fails, close all Chrome windows and retry, or manually start Chrome with:

```powershell
chrome.exe --remote-debugging-port=9222 --user-data-dir="$env:LOCALAPPDATA\Google\Chrome\User Data"
```

### cdp

```bash
bao session start --provider cdp --cdp-url http://127.0.0.1:9222
bao session start --provider cdp --cdp-url ws://host:port/devtools/browser/id
```

This connects to an external browser endpoint and does not own that browser
lifecycle.

## State And Actions

```bash
bao state SESSION_ID
bao click SESSION_ID 3
bao hover SESSION_ID 3
bao input SESSION_ID 1 "keyword"
bao select SESSION_ID 5 "United States"
bao scroll SESSION_ID down --amount 1000
bao keys SESSION_ID Enter
bao upload SESSION_ID 7 D:\file.xlsx
bao eval SESSION_ID "document.title"
bao screenshot SESSION_ID --output page.png
bao wait SESSION_ID stable
```

`state` returns BrowserAct-style indexed elements:

```text
[1] input "Search products"
[2] button "Search"
[3] link "Orders"
```

Indexes are invalid after navigation or significant DOM changes.

Action responses include verification metadata so the calling LLM can decide
whether the action chain really progressed:

```json
{
  "result": {
    "success": true,
    "message": "clicked with mouse",
    "verification": {
      "before": {"url": "https://www.baidu.com/", "target_id": "old"},
      "after": {"url": "https://top.baidu.com/board?platform=pc", "target_id": "new"},
      "url_changed": true,
      "target_changed": true,
      "page_count_changed": true
    }
  },
  "state": {}
}
```

For `chrome-direct`, action reconciliation watches for new CDP page targets and
updates the stored session `target_id`. This lets follow-up commands operate on
the page that actually opened after a click, including links that open a new
tab.

## Confirmation

Dangerous actions are blocked unless explicitly confirmed. Use `--confirm` for
CLI calls or `require_confirm=true` / `confirm=true` for HTTP calls.

```bash
bao click SESSION_ID 8 --confirm
bao act SESSION_ID "delete order" --confirm
bao eval SESSION_ID "fetch('/api/delete')" --confirm
```

## Intelligence

```bash
bao observe SESSION_ID "find the search box"
bao act SESSION_ID "search bluetooth speaker"
bao extract SESSION_ID "extract the current table"
```

v1 is deterministic plus semi-intelligent. It uses heuristics for now; future
work may add an OpenAI-compatible LLM client.

## Network

```bash
bao network requests SESSION_ID --type xhr,fetch --filter /api/
bao network request SESSION_ID REQUEST_ID
```

Network capture uses Playwright page events in v1.

## Forge

```bash
bao forge explore SESSION_ID --goal "extract order list"
bao forge generate --trace .bao/trace/SESSION_ID --name tt-orders
bao forge test .bao/skills/tt-orders
```

Generated Python wrappers emit JavaScript only. Execute emitted JS with:

```bash
bao eval SESSION_ID "$(python scripts/capability.py --mode tables)"
```

Generated modes:

```bash
python scripts/capability.py --mode auto
python scripts/capability.py --mode text --query "order"
python scripts/capability.py --mode tables
python scripts/capability.py --mode links
python scripts/capability.py --mode inputs
```

## Runtime Docs

Detailed implementation docs are in:

```text
E:\code\work\browser-auto-ops\docs
```
