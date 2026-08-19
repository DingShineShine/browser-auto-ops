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

Runtime and Skill are split the same way as BrowserAct:

1. Install the CLI from the company GitLab Package Registry (private PyPI).
2. Load the thin skill at `.agents/skills/browser-auto-ops`.
3. Run `bao get-skills core` for the version-matched workflow.

```bash
uv tool install browser-auto-ops --python 3.12 --index-url https://git.shinebed.com.cn/api/v4/projects/datagroup%2Fbrowser-auto-ops/packages/pypi/simple
bao --help
bao get-skills core
```

The index URL uses the GitLab project path `datagroup/browser-auto-ops`. Numeric
Project ID is not required. If the registry is private, put a read token in
`%USERPROFILE%\.netrc`:

```text
machine git.shinebed.com.cn
login __token__
password <deploy-or-project-access-token>
```

Token scopes:

- Install / Agent machines: `read_package_registry`
- Publish: `write_package_registry`

Do not clone this repository onto employee desktops just to get `bao`.

Skill source for agents that accept a GitLab tree URL:

```text
https://git.shinebed.com.cn/datagroup/browser-auto-ops/-/tree/main/.agents/skills/browser-auto-ops
```

## Publish a wheel

Package Registry lives on the GitLab project: Deploy -> Package Registry.
Published artifacts are platform wheels only. Do not upload an sdist.

```powershell
$env:UV_PUBLISH_PASSWORD = "<project-access-token>"
powershell -File scripts/publish_gitlab.ps1
```

Or use the manual `publish` job in `.gitlab-ci.yml` on a Windows runner.
Build a Windows wheel (core modules compiled to `.pyd`, no sdist):

```powershell
uv venv --python 3.12 .venv-py312
uv pip install --python .venv-py312 cython setuptools ziglang hatchling
.\.venv-py312\Scripts\python.exe hatch_build.py
uv build --wheel
```

MSVC is used when `cl.exe` is on PATH. Otherwise the hook links with `ziglang`
(`x86_64-windows-gnu`). Do not upload an sdist.

Compiled implementation modules in the wheel:

- `snapshot.scanner`
- `actions.executor`
- `providers.chrome_direct`
- `providers.raw_cdp`
- `providers.adspower_cdp`
- `sessions.manager`

Cookies, ADS keys, downloads, and local `.bao/` state stay off the package.

## Local development

```bash
uv sync --extra dev
uv run pytest
```

`uv tool install .` builds a real wheel and needs the compiled `.pyd` files.
Use `python hatch_build.py` first, or install the GitLab/private-index package.

Run API server:

```bash
uvicorn browser_auto_ops.server:app --reload
```
