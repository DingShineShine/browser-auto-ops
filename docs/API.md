# API

## CLI

```bash
bao session start --provider adspower-cdp --ads-base-url http://host:50325 --ads-user-id profile-id
bao session start --provider local-chrome --user-data-dir E:\tmp\bao-profile --headful
bao session start --provider cdp --cdp-url http://127.0.0.1:9222
bao session list
bao session stop s_xxx

bao navigate s_xxx https://example.com
bao state s_xxx
bao click s_xxx 3
bao hover s_xxx 3
bao input s_xxx 1 "keyword"
bao select s_xxx 5 "United States"
bao scroll s_xxx down --amount 1000
bao keys s_xxx Enter
bao upload s_xxx 7 D:\file.xlsx
bao eval s_xxx "document.title"
bao screenshot s_xxx --output page.png
bao wait s_xxx stable

bao observe s_xxx "find the search box"
bao act s_xxx "search bluetooth speaker"
bao extract s_xxx "extract the current table"

bao network requests s_xxx --type xhr,fetch --filter /api/
bao network request s_xxx r_xxx

bao forge explore s_xxx --goal "extract order list"
bao forge generate --trace .bao/trace/s_xxx --name tt-orders
bao forge test .bao/skills/tt-orders
```

Dangerous operations require explicit confirmation:

```bash
bao click s_xxx 8 --confirm
bao act s_xxx "delete order" --confirm
bao eval s_xxx "fetch('/api/delete')" --confirm
```

## HTTP

- `POST /sessions`
- `GET /sessions/{id}`
- `DELETE /sessions/{id}`
- `GET /sessions/{id}/state`
- `POST /sessions/{id}/actions`
- `POST /sessions/{id}/observe`
- `POST /sessions/{id}/act`
- `POST /sessions/{id}/extract`
- `GET /sessions/{id}/network/requests`
- `GET /sessions/{id}/network/requests/{request_id}`
- `POST /forge/jobs`

Confirmed action request:

```json
{
  "type": "click",
  "index": 8,
  "require_confirm": true
}
```

Confirmed act request:

```json
{
  "goal": "delete order",
  "confirm": true
}
```
