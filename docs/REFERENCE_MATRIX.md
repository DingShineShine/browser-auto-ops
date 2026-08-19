# Reference Matrix

This project does not copy large source blocks from referenced projects. Each row records the design reference, the lesson borrowed, and the clean-room implementation in this repo.

| Feature | Reference | Borrowed idea | Implementation |
|---|---|---|---|
| `adspower-cdp` provider | AdsPower Local API docs, existing TT Kotlin flow | Start profile, read `ws.puppeteer`, connect with CDP | `browser_auto_ops.providers.adspower_cdp.AdspowerCdpProvider` |
| `local-chrome` provider | Browser Use / Playwright local browser patterns | Launch isolated Chrome profile with remote debugging | `browser_auto_ops.providers.local_chrome.LocalChromeProvider` |
| `chrome-direct` provider | BrowserAct `chrome-direct` local mode and installed package docs/introspection | Use `DevToolsActivePort`, raw CDP, default-profile remote debugging flag, and auto-allow watcher | `browser_auto_ops.providers.chrome_direct.ChromeDirectProvider` / `providers.raw_cdp` |
| `cdp` provider | Playwright `connect_over_cdp`, Chrome DevTools Protocol | Treat CDP URL as the universal browser handle | `browser_auto_ops.providers.cdp.GenericCdpProvider` |
| Browser provider abstraction | Steel Browser, Skyvern browser engine | Separate browser lifecycle from automation logic | `browser_auto_ops.providers.base.BrowserProvider` |
| Browser identity UX | BrowserAct browser/session model | Agents choose a named browser identity before opening a named session | `browser_auto_ops.schemas.BrowserIdentity` / `browser_auto_ops.browsers.BrowserStore` |
| State/index | BrowserAct, Browser Use DOM service | Convert page into indexed interactive element list | `browser_auto_ops.snapshot.scanner.SnapshotEngine` |
| Snapshot refs | Playwright MCP, BrowserAct element handles | Human-readable `@eN` handle for the current snapshot; same-page rescans can preserve refs when xpath is still unique | `StateElement.ref`, `snapshot.scanner.SnapshotEngine.capture(previous=...)`, `snapshot.resolve` |
| Interactive detector | Browser Use `DomService` | Use tag, role, ARIA, text, visibility, rect, scrollability | `DOM_SCANNER` in `snapshot/scanner.py` |
| Action execution | BrowserAct, Stagehand, Playwright | Real browser events first, JS fallback second | `browser_auto_ops.actions.executor.ActionExecutor` |
| Strict action targeting | Playwright strict locators | Match by ref or role/name; fail on 0 or multiple matches instead of guessing | `schemas.ElementMatch`, `snapshot.resolve.resolve_element`, CLI `--role/--name` |
| Compact action response | BrowserAct/agent-browser token discipline | Default action response returns result + checkpoint, not a full after-state dump | `sessions.payload.compact_action_payload`, `/sessions/{id}/actions?include_state=1`, CLI `--full` |
| Batch actions | agent-browser batch command | Reduce Windows CLI startup tax with a thin ordered action array | `bao batch`, `/sessions/{id}/batch` |
| `observe/act/extract` | Stagehand `observe`, `act`, `extract` | LLM/heuristic chooses target, executor stays deterministic | `browser_auto_ops.intelligence.services` |
| Action schema | Skyvern actions | Typed action records with status and confidence-friendly fields | `schemas.models.ActionRequest` / `ActionResult` |
| Network capture | BrowserAct network commands, CDP `Network.*` | Track XHR/fetch and response bodies | `browser_auto_ops.network.recorder.NetworkRecorder` |
| Network archive and HAR export | BrowserAct network evidence, HAR 1.2 | Preserve same-session xhr/fetch across page switches and export the archive when needed | `SessionManager.network_archive`, `network.har.to_har`, `bao network export` |
| Trace | Skyvern workflow/debug trace | JSONL events plus states/screenshots/network evidence | `browser_auto_ops.trace.recorder.TraceRecorder` |
| Skill Forge | BrowserAct Skill Forge docs | Describe → Explore → Generate → Self-test; API-first when network evidence exists; business literals become parameters | `browser_auto_ops.forge.engine.ForgeEngine` writes replay `SKILL.md`, semantic locators, optional API scripts, and `.agents/skills` install |
| Forge live test/replay | Playwright locator replay, BrowserAct skill validation | Static checks by default; session mode validates criteria/locators; replay executes locator steps and stops on first failure | `forge.tester.evaluate_skill`, `forge.replay.workflow_actions`, `bao forge test --session --replay` |
| Daemon data root | BrowserAct named browser/session runtime | CLI and daemon must share one store so `browser create` is visible to `browser open` | `bao daemon start` sets `BAO_HOME`; `/health` returns `data_root` |
| Explore signals | BrowserAct `get title` / `state` / `network requests` | Independent observation commands; action results expose url/title checkpoint | `bao get-skills explore`; `browser open` returns `{session,url,title}`; `_verification_payload` compacted as `checkpoint` |
| Semantic locators | Playwright locators, Stagehand observe | Role + accessible name; container scope when names collide; indexes are ephemeral | `browser_auto_ops.forge.locators` |
| Trace artifacts | Skyvern run artifacts | One session keeps steps and network on the same trace | `GET /sessions/{ref}/trace`; `forge generate --session` |

Public API note:

- Employee-facing browser types are `chrome-direct` and `ads`.
- `local-chrome`, generic `cdp`, and `adspower-cdp` are retained as internal implementation details unless explicitly needed for development diagnostics.

Useful source links:

- Browser Use: https://github.com/browser-use/browser-use
- Stagehand: https://github.com/browserbase/stagehand
- Skyvern: https://github.com/skyvern-ai/skyvern
- Steel Browser: https://github.com/steel-dev/steel-browser
- Chrome DevTools Protocol: https://chromedevtools.github.io/devtools-protocol/
- BrowserAct docs: https://docs.browseract.com/agent-cli/
