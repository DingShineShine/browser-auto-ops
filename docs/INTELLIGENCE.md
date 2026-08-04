# Intelligence

v1 is deterministic plus semi-intelligent:

- `observe(goal)` ranks state elements as action candidates.
- `act(goal)` plans one to three deterministic `ActionRequest`s.
- `extract(goal, schema)` extracts tables, lists, and text from the live page.

`act` uses the same safety policy as direct actions. Dangerous goals are blocked unless the caller explicitly confirms them:

```bash
bao act s_xxx "delete order"
bao act s_xxx "delete order" --confirm
```

HTTP callers pass:

```json
{
  "goal": "delete order",
  "confirm": true
}
```

When confirmed, planned `ActionRequest`s include `require_confirm=true`, so the executor-level safety gate and the planner stay aligned.

Future work:

- OpenAI-compatible LLM client
- action cache
- self-heal based on failed locators
- richer task loop and multi-step workflow runner
