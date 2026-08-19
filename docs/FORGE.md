# Forge

Forge turns one recorded session into a replayable skill: goal, semantic locators, success criteria, optional API scripts, and a git-installable copy.

```bash
bao daemon start
bao daemon status
bao get-skills forge
bao forge generate --session <name> --name <skill-name> --goal "the user goal"
bao forge test .bao/skills/<skill-name> --session <name>
bao forge test .bao/skills/<skill-name> --session <name> --replay
```

`--session` and `--trace` are mutually exclusive. Prefer `--session` so generate reads the same `events.jsonl` that recorded click/input/wait. `bao forge explore <session> --goal "..."` only appends a goal onto that existing trace; it must not open a second recorder.

Generated layout:

```text
.bao/skills/{skill-name}          runtime copy + evidence
.agents/skills/{skill-name}       git-facing copy (secrets stripped)
|-- SKILL.md
|-- scripts/
|   |-- extract.py                optional page reader, not the replay path
|   |-- capability.py             legacy alias of extract.py
|   `-- api-<operation>.py        only when network evidence exists
|-- tests/
|   `-- smoke.json
`-- evidence/
    |-- trace-summary.json
    |-- workflow.json
    `-- generation-report.json
```

`bao forge generate` writes `evidence/generation-report.json` and returns the same report in the CLI/server response. The report summarizes included actions, dropped failed/noise actions, extracted parameters, auth branch status, API hints, and the installed `.agents/skills` path.

`bao forge test` checks replay steps, locator table, success criteria, and rejects ephemeral `click <index>` selectors. Without `--session` it stays static-only. With `--session`, live URL/title criteria and only locators marked `live_current` are checked against the current page. Login fields, calendar popovers, and modal-only buttons are not default current-page checks.

`--replay` requires `--session`. It executes recorded locators step-by-step through the same action resolver, stops on the first failure, and never rewrites or self-repairs the skill. If the workflow has an auth branch, replay skips login steps when the current title/url already look logged in and only runs auth steps when the current page looks like a login page.

Observation commands used while exploring live in `bao get-skills explore`.
