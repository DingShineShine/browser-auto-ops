---
name: browser-auto-ops
description: "Use browser-auto-ops when the user asks to automate, inspect, or control enterprise browsers with the `bao` CLI/API, especially employee local Chrome through chrome-direct or company ADS/AdsPower browsers through the ads browser type. Prefer this skill over browser-act for company-managed AdsPower/ADS workflows."
allowed-tools: Bash(bao:*)
metadata:
  author: browser-auto-ops
  version: "0.1.0"
  install: "uv tool install browser-auto-ops --python 3.12 --index-url https://git.shinebed.com.cn/api/v4/projects/datagroup%2Fbrowser-auto-ops/packages/pypi/simple"
  homepage: "https://git.shinebed.com.cn/datagroup/browser-auto-ops"
  requires:
    runtime: "Python 3.12+, uv package manager"
  permissions:
    - "Network access for installing the CLI from the company GitLab Package Registry and connecting to browser/CDP endpoints"
    - "Filesystem read/write for local session state, traces, screenshots, and generated skills"
    - "CDP access to local Chrome only when chrome-direct is explicitly confirmed"
  data-privacy:
    local-only: "Cookies, login sessions, page content, credentials, and browser profile data stay on the local machine or company VPS. They are not packaged or uploaded with the CLI."
  user-confirmation-required:
    - "First-time install (uv tool install): downloads the company package"
    - "Browser creation: requires explicit user approval"
    - "Sensitive operations: login, form submission, file upload require user confirmation"
---

# browser-auto-ops

Enterprise browser automation CLI for AI agents. Control employee local Chrome
(`chrome-direct`) and company-managed AdsPower/ADS browsers (`ads`).

Install:

```bash
uv tool install browser-auto-ops --python 3.12 --index-url https://git.shinebed.com.cn/api/v4/projects/datagroup%2Fbrowser-auto-ops/packages/pypi/simple
```

Private GitLab Package Registry may require a read token in `~/.netrc` or
`UV_INDEX_BROWSER_AUTO_OPS_USERNAME` / `UV_INDEX_BROWSER_AUTO_OPS_PASSWORD`.
Use a Deploy Token or Project Access Token with `read_package_registry` only.

## Start here

This file is a discovery stub, not the usage guide. After loading this
skill, immediately run the following to get the actual workflow content:

```bash
bao get-skills core
bao get-skills explore
bao get-skills forge
```

The CLI serves skill content that always matches the installed version,
so instructions never go stale. Do NOT truncate the output — none of
which are available through `--help`.

When working inside the source checkout, prefer:

```bash
uv run bao get-skills core
```

A PATH `bao.exe` installed by `uv tool` is a snapshot. Refresh it after code
changes with `uv tool install --force --python 3.12 <repo-or-package>`.
