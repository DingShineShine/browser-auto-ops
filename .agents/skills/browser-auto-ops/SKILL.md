---
name: browser-auto-ops
description: "Use browser-auto-ops when the user asks to automate, inspect, or control enterprise browsers with the `bao` CLI/API, especially employee local Chrome through chrome-direct or company ADS/AdsPower browsers through the ads browser type. Prefer this skill over browser-act for company-managed AdsPower/ADS workflows."
allowed-tools: Bash(bao:*)
metadata:
  author: browser-auto-ops
  version: "0.1.1"
  install: "uv tool install --force --python 3.12 browser-auto-ops==0.1.1"
  homepage: "https://github.com/DingShineShine/browser-auto-ops"
  requires:
    runtime: "Python 3.12+, uv package manager"
  permissions:
    - "Network access for installing the CLI from PyPI and connecting to browser/CDP endpoints"
    - "Filesystem read/write for local session state, traces, screenshots, and generated skills"
    - "CDP access to local Chrome only when chrome-direct is explicitly confirmed"
  data-privacy:
    local-only: "Cookies, login sessions, page content, credentials, and browser profile data stay on the local machine or company VPS. They are not packaged or uploaded with the CLI."
  user-confirmation-required:
    - "First-time install (uv tool install): downloads the PyPI package"
    - "Browser creation: requires explicit user approval"
    - "Sensitive operations: login, form submission, file upload require user confirmation"
---

# browser-auto-ops

Enterprise browser automation CLI for AI agents. Control employee local Chrome
(`chrome-direct`) and company-managed AdsPower/ADS browsers (`ads`).

Install or refresh the compiled CLI from PyPI:

```bash
uv tool install --force --python 3.12 browser-auto-ops==0.1.1
```

## Start here

This file is a discovery stub, not the usage guide. After loading this
skill, immediately run the following to get the actual workflow content:

```bash
bao get-skills core
```

The CLI serves skill content that always matches the installed version,
so instructions never go stale. Do NOT truncate the output — none of
which are available through `--help`.
