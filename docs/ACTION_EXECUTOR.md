# Action Executor

Execution order:

```text
index -> StateElement -> safety confirmation gate
  -> locator/rect
  -> scroll/focus if needed
  -> real browser event via Playwright mouse/keyboard/locator
  -> JS fallback only if needed
  -> wait stable
  -> reconcile active page/target
  -> refresh state from the reconciled page
```

Supported v1 actions:

- `click`
- `input_text`
- `select_option`
- `hover`
- `scroll`
- `keypress`
- `upload_file`
- `goto_url`
- `go_back`
- `go_forward`
- `reload`
- `wait`
- `execute_js`
- `screenshot`

`hover` uses Playwright mouse movement first. If a normal coordinate hover is not possible, it falls back to dispatching `mouseover`, `mouseenter`, and `mousemove` in the page context.

Dangerous actions are blocked unless explicitly confirmed. The executor checks the action payload plus the indexed element label/text/attributes for operation words such as delete, pay, submit, publish, confirm, transfer, refund, and Chinese equivalents.

Confirmation options:

```bash
bao click s_xxx 3 --confirm
bao input s_xxx 1 "value" --confirm
bao select s_xxx 5 "United States" --confirm
bao eval s_xxx "fetch('/api/delete')" --confirm
bao navigate s_xxx https://example.test/delete --confirm
```

HTTP callers set:

```json
{
  "type": "click",
  "index": 3,
  "require_confirm": true
}
```

The project should not become JS-only automation. Real browser events are the default because many modern apps listen for pointer, keyboard, and composition events.

## Verification Metadata

Every action result may include `verification`:

```json
{
  "before": {
    "url": "https://www.baidu.com/",
    "title": "百度一下，你就知道",
    "target_id": "old",
    "page_ids": ["old"]
  },
  "after": {
    "url": "https://top.baidu.com/board?platform=pc&sa=pcindex_entry",
    "title": "百度热搜",
    "target_id": "new",
    "page_ids": ["old", "new"]
  },
  "url_changed": true,
  "title_changed": true,
  "target_changed": true,
  "page_count_changed": true
}
```

The calling LLM should treat `success=true` as "the low-level event was sent",
then use `verification` plus the returned `state` to decide whether the task
goal actually progressed.

For raw CDP `chrome-direct`, the session manager compares CDP targets before and
after an action. If a click opens a new related page target, it switches the
session page to that target, updates `session.meta.target_id`, and persists it
for the next CLI call.
