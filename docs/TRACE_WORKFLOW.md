# Trace And Workflow

Trace root:

```text
.bao/trace/{session_id}
|-- events.jsonl
|-- states/
|-- screenshots/
|-- network/
`-- summary.json
```

`events.jsonl` is the append-only event stream. Every event passes through redaction for cookies, authorization headers, tokens, passwords, API keys, CSRF values, and verification codes.

`summary.json` is updated whenever a trace event is written. It contains:

```json
{
  "session_id": "s_xxx",
  "events": 3,
  "event_types": {
    "provider.start": 1,
    "state.capture": 1,
    "action.result": 1
  },
  "last_event_type": "action.result",
  "updated_at": "2026-08-04T00:00:00Z",
  "paths": {
    "events": ".bao/trace/s_xxx/events.jsonl",
    "states": ".bao/trace/s_xxx/states",
    "screenshots": ".bao/trace/s_xxx/screenshots",
    "network": ".bao/trace/s_xxx/network"
  }
}
```

Workflow is intentionally minimal in v1. `act` can perform short one to three step plans. Longer workflow YAML/JSON orchestration is P6 future work.
