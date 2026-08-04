# Forge

Forge produces a reusable skill directory from trace evidence.

```bash
bao forge explore s_xxx --goal "extract order list"
bao forge generate --trace .bao/trace/s_xxx --name tt-orders
bao forge test .bao/skills/tt-orders
```

Generated layout:

```text
skills/{skill-name}
|-- SKILL.md
|-- scripts/
|   `-- capability.py
|-- tests/
|   `-- smoke.json
`-- evidence/
    `-- trace-summary.json
```

`capability.py` is trace-informed. It embeds the last captured state, recent action shape, and goal hints from the trace, then emits JavaScript for the live authenticated browser page context.

Supported generated modes:

```bash
python scripts/capability.py --mode auto
python scripts/capability.py --mode text --query "order"
python scripts/capability.py --mode tables
python scripts/capability.py --mode links --query "/api/"
python scripts/capability.py --mode inputs
```

Execute the emitted JavaScript through the runtime:

```bash
bao eval <session_id> "$(python scripts/capability.py --mode tables)"
```

Current v1 Forge does not yet perform full API-first endpoint inference. That remains a future enhancement. The generated wrapper is no longer an empty skeleton; it can extract text snippets, tables, links, and input metadata from the live page.
