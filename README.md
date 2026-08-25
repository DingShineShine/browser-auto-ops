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

`bao daemon start` is safe to run at the start of every task. It reuses an
already-running daemon for this repository, or replaces a confirmed old bao
daemon whose `data_root` points at another `.bao` directory.

## Install For Desktop Agents

Other agents install the compiled wheel from PyPI. This is the same artifact
they will get after a stable release, so they should not read `.py` sources
from `site-packages`.

```bash
uv tool install --force --python 3.12 browser-auto-ops==0.1.5
bao --help
bao get-skills core
```

Skill source:

```text
https://github.com/DingShineShine/browser-auto-ops/tree/main/.agents/skills/browser-auto-ops
```

Pushing GitHub does not update other machines. After you publish a new PyPI
version, update this pinned install command and have agents run it again.

Cookies, ADS keys, downloads, and local `.bao/` state stay off the package.

## Publish a new version

PyPI rejects reusing a version. Each update for others needs a new number.

1. Change code or `bao get-skills` text in `src/browser_auto_ops/cli.py`.
2. Bump `[project].version` in `pyproject.toml` (`0.1.4` -> `0.1.5`).
3. Create a pypi.org API token once. Do not paste it into chat.
4. Publish the compiled Windows wheel only:

```powershell
$env:UV_PUBLISH_TOKEN = "<pypi-api-token>"
powershell -File scripts/publish_pypi.ps1
```

The script compiles core modules to `.pyd`, builds a platform wheel, and
refuses to upload an sdist or a `py3-none-any` source wheel.

Optional: `git tag v0.1.5` and push the tag.

## Local development

You keep working from the source checkout. Editable installs skip Cython.

```bash
uv sync --extra dev
uv run pytest
```

Run API server:

```bash
uvicorn browser_auto_ops.server:app --reload
```
