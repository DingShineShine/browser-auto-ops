# browser-auto-ops

`browser-auto-ops` is a clean-room enterprise browser automation engine for
employee local Chrome and company-managed ADS/AdsPower browsers.

It implements the v1 plan:

- Public browser types: `chrome-direct`, `ads`
- BrowserAct-style `state` with indexed interactive elements
- Deterministic action executor with real browser events first, `hover`, and JS fallback
- Executor-level confirmation gate for dangerous operations
- Stagehand-style `observe`, `act`, and `extract`
- CDP network recording
- JSONL trace artifacts plus rolling `summary.json`
- BrowserAct Skill Forge-style `forge generate` with trace-informed extraction scripts

CLI command:

```bash
bao get-skills core
```

Core employee workflow:

```bash
bao daemon start
bao browser create --type chrome-direct --name local --desc "Employee current Chrome" --confirm-before-use
bao browser create --type ads --name amazon-us-01 --desc "VPS AdsPower profile" --ads-base-url http://HOST:PORT --ads-user-id PROFILE_ID
bao chrome-direct authorize
bao --session report browser open amazon-us-01 https://example.com
bao --session report state
bao --session report click 3
bao --session report tab list
bao --session report cookies get
bao --session report downloads wait latest --output D:\exports
bao session close report
```

## Install For Desktop Agents

During development, GitHub `main` is the install source. The thin skill stays
stable; workflow text is served by the installed CLI.

```bash
uv tool upgrade browser-auto-ops --python 3.12 || uv tool install git+https://github.com/DingShineShine/browser-auto-ops.git --python 3.12
bao --help
bao get-skills core
```

Skill source:

```text
https://github.com/DingShineShine/browser-auto-ops/tree/main/.agents/skills/browser-auto-ops
```

After you push `main`, other agents refresh with `uv tool upgrade`. They do not
need to reinstall the skill file or clone the company GitLab repo.

Cookies, ADS keys, downloads, and local `.bao/` state stay off the package.

## Later: compiled wheels and a package index

Default installs are pure Python so `uv tool install git+...` works without
MSVC or zig. Optional compile extras and `hatch_build.py` remain for a later
stable release (PyPI or a private index). Do not use them as the development
install path.

## Local development

```bash
uv sync --extra dev
uv run pytest
```

Run API server:

```bash
uvicorn browser_auto_ops.server:app --reload
```
