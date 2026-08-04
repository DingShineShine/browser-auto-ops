# API

## CLI

```bash
bao daemon start
bao daemon status
bao daemon stop

bao browser list
bao browser create --type chrome-direct --name local --desc "Employee current Chrome" --confirm-before-use
bao browser create --type ads --name amazon-us-01 --desc "VPS AdsPower profile" --ads-base-url http://host:50325 --ads-user-id profile-id
bao chrome-direct authorize
bao --session work browser open amazon-us-01 https://example.com
bao session list
bao session close work

bao --session work navigate https://example.com
bao --session work state
bao --session work click 3
bao --session work hover 3
bao --session work input 1 "keyword"
bao --session work select 5 "United States"
bao --session work scroll down --amount 1000
bao --session work keys Enter
bao --session work upload 7 D:\file.xlsx
bao --session work eval "document.title"
bao --session work screenshot page.png
bao --session work wait stable
bao --session work get title
bao --session work get html
bao --session work get markdown
bao --session work tab list
bao --session work tab switch 0
bao --session work cookies get
bao --session work cookies export cookies.json
bao --session work dialog status
bao --session work wait selector 3 --state visible

bao --session work observe "find the search box"
bao --session work act "search bluetooth speaker"
bao --session work extract "extract the current table"

bao --session work network requests --type xhr,fetch --filter /api/
bao --session work network request r_xxx
bao --session work network clear
bao --session work network har start
bao --session work network har stop trace.har
bao --session work downloads list
bao --session work downloads wait latest --timeout 300000 --output D:\exports

bao forge explore s_xxx --goal "extract order list"
bao forge generate --trace .bao/trace/s_xxx --name tt-orders
bao forge test .bao/skills/tt-orders
```

Dangerous operations require explicit confirmation:

```bash
bao --session work click 8 --confirm
bao --session work act "delete order" --confirm
bao --session work eval "fetch('/api/delete')" --confirm
```

## HTTP

- `GET /browsers`
- `POST /browsers`
- `DELETE /browsers/{id_or_name}`
- `POST /browsers/{id_or_name}/open`
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
- `GET /sessions/{id}/downloads`
- `POST /sessions/{id}/downloads/wait`
- `POST /forge/jobs`

Confirmed action request:

```json
{
  "type": "click",
  "index": 8,
  "require_confirm": true
}
```

Action response shape:

```json
{
  "result": {
    "type": "click",
    "success": true,
    "message": "clicked with mouse",
    "fallback_used": false,
    "verification": {
      "before": {
        "url": "https://www.baidu.com/",
        "title": "百度一下，你就知道",
        "target_id": "old-target",
        "page_ids": ["old-target"]
      },
      "after": {
        "url": "https://top.baidu.com/board?platform=pc",
        "title": "百度热搜",
        "target_id": "new-target",
        "page_ids": ["old-target", "new-target"]
      },
      "url_changed": true,
      "title_changed": true,
      "target_changed": true,
      "page_count_changed": true
    }
  },
  "state": {}
}
```

LLM callers should use `verification.after` and the returned `state` as the
post-action truth. `success=true` alone only means the low-level operation did
not error.

Confirmed act request:

```json
{
  "goal": "delete order",
  "confirm": true
}
```
