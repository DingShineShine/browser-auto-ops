# browser-auto-ops

`browser-auto-ops` is a clean-room browser automation engine for ADS/AdsPower,
local Chrome, and generic CDP endpoints.

It implements the v1 plan:

- Providers: `adspower-cdp`, `local-chrome`, `chrome-direct`, `cdp`
- BrowserAct-style `state` with indexed interactive elements
- Deterministic action executor with real browser events first, `hover`, and JS fallback
- Executor-level confirmation gate for dangerous operations
- Stagehand-style `observe`, `act`, and `extract`
- CDP network recording
- JSONL trace artifacts plus rolling `summary.json`
- BrowserAct Skill Forge-style `forge generate` with trace-informed extraction scripts

CLI command:

```bash
bao --help
```

## Install For Desktop Agents

This repository is private on the internal GitLab server. A BrowserAct-style
public `Skill URL` only works when the target agent can authenticate to GitLab.
If unauthenticated users open the GitLab tree URL, GitLab redirects to sign-in
or returns 401/404.

Recommended private install flow:

```bash
git clone ssh://git@git.shinebed.com.cn:2222/datagroup/browser-auto-ops.git
cd browser-auto-ops
uv tool install . --python 3.12 --force
bao --help
```

Then install the skill from the checked-out directory:

```text
.agents/skills/browser-auto-ops
```

If the agent supports authenticated GitLab tree URLs, use:

```text
https://git.shinebed.com.cn/datagroup/browser-auto-ops/-/tree/main/.agents/skills/browser-auto-ops
```

For a BrowserAct-like one-line install experience without authentication
issues, publish `.agents/skills/browser-auto-ops` to a public or internal
anonymous-readable skills repository.

Run API server:

```bash
uvicorn browser_auto_ops.server:app --reload
```
