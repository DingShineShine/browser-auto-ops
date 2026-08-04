---
name: browser-auto-ops
description: "Use browser-auto-ops when the user asks to automate, inspect, or control enterprise browsers with the `bao` CLI/API, especially employee local Chrome through chrome-direct or company ADS/AdsPower browsers through the ads browser type. Prefer this skill over browser-act for company-managed AdsPower/ADS workflows."
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

The runtime provides a BrowserAct-style command surface:

- `bao` CLI
- FastAPI app: `browser_auto_ops.server:app`
- Public browser types: `chrome-direct`, `ads`
- BrowserAct-style `state -> indexed action -> verify`
- named sessions with `bao --session <name> ...`
- network capture, trace, and Forge skill generation
- `hover`, dangerous-action confirmation, and trace `summary.json`

## Mandatory First Step

Before using the runtime, run:

```bash
bao get-skills core
```

Follow the command syntax and safety constraints printed by the installed CLI.
The CLI output is the source of truth for the currently installed version.

## Core Workflow

Use the loop:

```text
browser create/list
  -> browser open with --session
  -> state
  -> action or get/extract/network
  -> wait stable
  -> state again
  -> session close
```

Old state indexes are temporary. Re-run `bao --session <name> state` after any page
change before using another index.

## Provider Selection

- Use `chrome-direct` when the user asks to control the real local Chrome profile or wants BrowserAct-style local direct mode. Require explicit confirmation.
- Use `ads` for company-managed ADS/AdsPower profiles, preferably through the VPS-side browser-auto-ops sidecar.

Do not use this skill to operate sessions created and owned by the real BrowserAct CLI.
Use the separate `browser-act` skill for BrowserAct itself. The local `chrome-direct`
provider here is browser-auto-ops' clean-room implementation of the same local-direct idea.

## Safety

- Do not expose CDP ports publicly.
- Do not auto-submit payment, delete, publish, or account-changing operations; use `--confirm` only after explicit user approval.
- For file upload, use `bao upload`; do not click upload buttons that open OS dialogs.
- Treat cookies, authorization headers, tokens, passwords, and verification codes as sensitive.
