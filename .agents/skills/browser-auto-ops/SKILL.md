---
name: browser-auto-ops
description: "Use browser-auto-ops when the user asks to automate, inspect, or control ADS/AdsPower browsers, local Chrome, or generic CDP browser endpoints with the `bao` CLI/API; when they mention browser-auto-ops, bao, adspower-cdp, local-chrome, CDP state/index actions, observe/act/extract, network capture, trace, or Forge skill generation. Prefer this skill over browser-act when the browser source is AdsPower/ADS or an arbitrary CDP endpoint."
allowed-tools: Bash(bao:*)
metadata:
  author: browser-auto-ops
  version: "0.1.0"
  install: "uv tool install git+ssh://git@git.shinebed.com.cn:2222/datagroup/browser-auto-ops.git --python 3.12"
  requires:
    runtime: "Python 3.12+, uv package manager"
  permissions:
    - "Network access for installing the CLI and connecting to browser/CDP endpoints"
    - "Filesystem read/write for local session state, traces, screenshots, and generated skills"
    - "CDP access to local Chrome only when chrome-direct is explicitly confirmed"
---

# browser-auto-ops

Use this skill as the routing and operating guide for the local
`browser-auto-ops` runtime at:

```text
E:\code\work\browser-auto-ops
```

The runtime provides:

- `bao` CLI
- FastAPI app: `browser_auto_ops.server:app`
- Providers: `adspower-cdp`, `local-chrome`, `chrome-direct`, `cdp`
- BrowserAct-style `state -> indexed action -> verify`
- Stagehand-style `observe / act / extract`
- network capture, trace, and Forge skill generation
- `hover`, dangerous-action confirmation, and trace `summary.json`

## Mandatory First Step

Before using the runtime, read:

```text
references/runtime.md
```

It contains the current command syntax, provider rules, safety constraints, and
troubleshooting notes.

## Core Workflow

Use the loop:

```text
session start
  -> state
  -> action or observe/act/extract
  -> wait stable
  -> state again
  -> stop when done
```

Old state indexes are temporary. Re-run `bao state <session_id>` after any page
change before using another index.

## Provider Selection

- Use `adspower-cdp` for AdsPower/ADS profiles when `ws.puppeteer` is reachable from this machine.
- Use `local-chrome` for isolated local development, test pages, or automation that should not touch the user's everyday Chrome profile.
- Use `chrome-direct` when the user asks to control the real local Chrome profile or wants BrowserAct-style local direct mode. Require explicit confirmation.
- Use `cdp` for an already-running CDP endpoint, including manually forwarded remote Chrome.

Do not use this skill to operate sessions created and owned by the real BrowserAct CLI.
Use the separate `browser-act` skill for BrowserAct itself. The local `chrome-direct`
provider here is browser-auto-ops' clean-room implementation of the same local-direct idea.

## Safety

- Do not expose CDP ports publicly.
- Do not auto-submit payment, delete, publish, or account-changing operations; use `--confirm` only after explicit user approval.
- For file upload, use `bao upload`; do not click upload buttons that open OS dialogs.
- Treat cookies, authorization headers, tokens, passwords, and verification codes as sensitive.
