# Reference Matrix

This project does not copy large source blocks from referenced projects. Each row records the design reference, the lesson borrowed, and the clean-room implementation in this repo.

| Feature | Reference | Borrowed idea | Implementation |
|---|---|---|---|
| `adspower-cdp` provider | AdsPower Local API docs, existing TT Kotlin flow | Start profile, read `ws.puppeteer`, connect with CDP | `browser_auto_ops.providers.adspower_cdp.AdspowerCdpProvider` |
| `local-chrome` provider | Browser Use / Playwright local browser patterns | Launch isolated Chrome profile with remote debugging | `browser_auto_ops.providers.local_chrome.LocalChromeProvider` |
| `chrome-direct` provider | BrowserAct `chrome-direct` local mode and installed package docs/introspection | Use `DevToolsActivePort`, raw CDP, default-profile remote debugging flag, and auto-allow watcher | `browser_auto_ops.providers.chrome_direct.ChromeDirectProvider` / `providers.raw_cdp` |
| `cdp` provider | Playwright `connect_over_cdp`, Chrome DevTools Protocol | Treat CDP URL as the universal browser handle | `browser_auto_ops.providers.cdp.GenericCdpProvider` |
| Browser provider abstraction | Steel Browser, Skyvern browser engine | Separate browser lifecycle from automation logic | `browser_auto_ops.providers.base.BrowserProvider` |
| State/index | BrowserAct, Browser Use DOM service | Convert page into indexed interactive element list | `browser_auto_ops.snapshot.scanner.SnapshotEngine` |
| Interactive detector | Browser Use `DomService` | Use tag, role, ARIA, text, visibility, rect, scrollability | `DOM_SCANNER` in `snapshot/scanner.py` |
| Action execution | BrowserAct, Stagehand, Playwright | Real browser events first, JS fallback second | `browser_auto_ops.actions.executor.ActionExecutor` |
| `observe/act/extract` | Stagehand `observe`, `act`, `extract` | LLM/heuristic chooses target, executor stays deterministic | `browser_auto_ops.intelligence.services` |
| Action schema | Skyvern actions | Typed action records with status and confidence-friendly fields | `schemas.models.ActionRequest` / `ActionResult` |
| Network capture | BrowserAct network commands, CDP `Network.*` | Track XHR/fetch and response bodies | `browser_auto_ops.network.recorder.NetworkRecorder` |
| Trace | Skyvern workflow/debug trace | JSONL events plus states/screenshots/network evidence | `browser_auto_ops.trace.recorder.TraceRecorder` |
| Skill Forge | BrowserAct Skill Forge docs | Explore trace, generate `SKILL.md` and JS-emitting Python wrapper | `browser_auto_ops.forge.engine.ForgeEngine` |

Useful source links:

- Browser Use: https://github.com/browser-use/browser-use
- Stagehand: https://github.com/browserbase/stagehand
- Skyvern: https://github.com/skyvern-ai/skyvern
- Steel Browser: https://github.com/steel-dev/steel-browser
- Chrome DevTools Protocol: https://chromedevtools.github.io/devtools-protocol/
- BrowserAct docs: https://docs.browseract.com/agent-cli/
