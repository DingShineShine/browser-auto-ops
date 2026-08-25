# BrowserAct Skill Forge vs browser-auto-ops Forge: Wayfair WSP Product Report

## Scope

This comparison uses the same Wayfair Partner Home advertising task:

- Generate Wayfair Sponsored Products Product Report
- Date range: `T-3` to `T-2`
- Group by `Day`
- File format: CSV
- Report name: `wayfair_adv_reports_{T-2}`
- Save the CSV artifact to Desktop

## Artifacts Compared

BrowserAct Skill Forge output:

- `output/wayfair-wsp-product-report-browseract-forge/wayfair-wsp-product-report/SKILL.md`
- `output/wayfair-wsp-product-report-browseract-forge/wayfair-wsp-product-report/scripts/scan-report-config.py`
- `output/wayfair-wsp-product-report-browseract-forge/wayfair-wsp-product-report/scripts/create-product-report.py`
- `output/wayfair-wsp-product-report-browseract-forge/wayfair-wsp-product-report/scripts/find-report.py`
- `output/wayfair-wsp-product-report-browseract-forge/wayfair-wsp-product-report/scripts/download-report.py`

Installed BrowserAct-generated skill:

- `C:/Users/Administrator/.codex/skills/wayfair-wsp-product-report-browseract-forge/SKILL.md`

browser-auto-ops Forge output:

- `.agents/skills/wayfair-ads-product-report/SKILL.md`
- `.bao/skills/wayfair-ads-product-report/evidence/workflow.json`
- `.bao/skills/wayfair-ads-product-report/evidence/generation-report.json`
- `.bao/skills/wayfair-ads-product-report/evidence/repair-suggestion.json`

## Execution Results

BrowserAct Skill Forge path:

- Installed `browser-act-skill-forge` from the official BrowserAct skills repository.
- Explored Wayfair with BrowserAct `chrome` mode.
- Captured the actual Generate Report request through HAR.
- Identified an API-first path through Wayfair's frontend proxy endpoint:
  - `POST /a/media_hub/report/proxy`
  - create report: `path = /partner/v1/reports`, `method = POST`
  - list reports: `path = /partner/v1/reports`, `method = GET`
  - download CSV: `path = /partner/v1/reports/{id}/download`, `method = GET`
- Generated and verified a reusable skill package with Python JS-wrapper scripts.
- End-to-end verification created report id `bac6c118-4419-4f93-a9a5-644fc5e9e20e`.
- Downloaded CSV to `C:/Users/Administrator/Desktop/wayfair_adv_reports_2026-08-23_forge_verify.csv`.
- Download result: `text/csv;charset=utf-8`, `32675` bytes.

browser-auto-ops Forge path:

- Generated a machine-readable `workflow.json`.
- Produced a replay plan with 35 steps:
  - 34 executable steps
  - 9 browser actions
  - 9 eval helpers
  - 2 API calls
  - 7 wait conditions
  - 1 artifact step
- Generated parameters for `start_date`, `end_date`, and `report_name`.
- Generated artifact contract for `{output_dir}/{report_name}.csv`.
- Replay failed at the Day dropdown step:
  - step id: `s17_click_day`
  - failed locator: role option `Day` inside dialog `None Day Week Month`
  - root contributing issue: a prior Product Report helper returned `{"error": true}` but the step was treated as action success because the JS itself executed.

## Core Difference

BrowserAct Skill Forge optimizes for capability extraction.

It asks: "What stable capability can reproduce the business operation?" In this case it discovered that the visual form is only a frontend for a transparent internal report proxy. The generated skill therefore uses the internal report API directly from the logged-in browser context.

browser-auto-ops Forge optimizes for trace replay.

It asks: "Can we replay the actions that happened during the recorded session?" The generated workflow preserves browser actions, eval helpers, waits, parameter candidates, evidence, and artifact contracts. This gives a richer replay/evidence model, but it stayed closer to the fragile UI interaction path.

## Capability Model

BrowserAct Skill Forge output is component-based:

- `scan-report-config.py`: discover enums and date rules.
- `create-product-report.py`: create the report through the internal proxy.
- `find-report.py`: poll report history by report name.
- `download-report.py`: download the CSV by report id.

Each component is a small Python wrapper that emits browser-side JS. The browser session still supplies authentication and cookies.

browser-auto-ops Forge output is workflow-based:

- A single `workflow.json` represents the recorded journey.
- Steps include navigation, clicks, waits, eval helpers, polling, and artifact handling.
- Parameters and artifact contracts are represented as first-class workflow metadata.

## Stability

BrowserAct Skill Forge is more stable for this task because it bypasses the fragile UI controls:

- No WSP radio click is needed.
- No Product Report label matching is needed.
- No Downshift menu selection is needed.
- No calendar picker is needed.
- No Generate Report button locator is needed.

The only required browser state is a logged-in Wayfair session. The task becomes a small set of report proxy calls.

browser-auto-ops Forge is less stable on this task because it replayed UI-level evidence:

- The Product Report helper can fail internally but still be marked as executed.
- The Day dropdown depends on transient dialog content and timing.
- The calendar requires robust month navigation.
- Wait steps add runtime variance.
- The replay has more steps and more state-dependent failure points.

## Product Strengths

BrowserAct Skill Forge strengths:

- Strong API-first exploration discipline.
- Produces compact reusable scripts.
- Explicitly separates exploration from reuse.
- Avoids over-replaying UI when backend contracts are transparent.
- Generated skill is easier for another agent to understand and run manually.

browser-auto-ops Forge strengths:

- Produces a structured `workflow.json`, not just a written playbook.
- Has explicit replay semantics and step metadata.
- Has locator table and repair-suggestion evidence.
- Has parameter candidate extraction and relative date binding.
- Has artifact contract and validation as part of the workflow.
- Can be used as a product runtime entrypoint through `bao forge run`.

## Product Gaps

BrowserAct Skill Forge gaps observed:

- The output is not a machine workflow with a standard runtime schema.
- Artifact saving is instructional; it is not a first-class artifact contract.
- There is no locator/evidence table comparable to `workflow.json`.
- Large CSV downloads returned as base64 through eval may hit stdout or truncation limits.
- The generated skill is agent-readable, but not a typed replay plan.

browser-auto-ops Forge gaps observed:

- It needs stronger API-first capability discovery before committing to UI replay.
- Eval helper results need semantic success validation, not only "script executed".
- UI replay should collapse fragile widget flows into capability-level helpers.
- Generation should better distinguish business actions from incidental UI mechanics.
- Repair suggestions identify failing steps, but they do not yet recommend switching abstraction level from UI replay to API capability.

## Product Direction

The most important product lesson is not to copy BrowserAct's output format directly. The better direction is to combine both systems:

1. Add an API-first exploration phase before replay-plan generation.
2. Let Forge choose the highest stable abstraction:
   - API capability when request shape is transparent.
   - DOM helper when the page JS must handle tokens or widget complexity.
   - Browser action replay only when no stable API or helper exists.
3. Keep our `workflow.json` as the durable runtime format.
4. Represent API components as workflow steps with explicit inputs, outputs, validators, and artifact contracts.
5. Preserve the `SKILL.md` as human documentation, but keep `workflow.json` as the source of truth for execution.

For this Wayfair task, the ideal browser-auto-ops Forge output should be:

- `params.start_date = T-3`
- `params.end_date = T-2`
- `params.report_name = wayfair_adv_reports_{end_date.iso}`
- Step 1: ensure logged-in reports page.
- Step 2: read report config and validate WSP/SKU_REPORT/DAY/CSV support.
- Step 3: create report with `/partner/v1/reports`.
- Step 4: poll `/partner/v1/reports` until status is `COMPLETED`.
- Step 5: download `/partner/v1/reports/{id}/download`.
- Step 6: save and validate `{output_dir}/{report_name}.csv`.

This would keep the BrowserAct API-first stability while preserving browser-auto-ops' stronger workflow, parameter, artifact, and validation model.
