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
bao browser create --type chrome-direct --name local --desc "Employee current Chrome" --confirm-before-use
bao browser create --type ads --name amazon-us-01 --desc "VPS AdsPower profile" --ads-base-url http://HOST:PORT --ads-user-id PROFILE_ID
bao --session report browser open amazon-us-01 https://example.com
bao --session report state
bao --session report click 3
bao session close report
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
