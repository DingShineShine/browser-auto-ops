# Implementation Checklist

## P0 Project

- [x] Python package skeleton
- [x] CLI entrypoint `bao`
- [x] FastAPI app
- [x] Pydantic schemas

## P1 Providers

- [x] `adspower-cdp`
- [x] `local-chrome`
- [x] `cdp`
- [ ] ADS real profile smoke test

## P2 State

- [x] DOM scanner
- [x] state text renderer
- [x] indexed elements
- [ ] AX tree enrichment
- [ ] DOMSnapshot enrichment

## P3 Actions

- [x] click/input/select/scroll/keys/upload/eval/screenshot/wait/navigation
- [x] hover
- [x] JS fallback
- [x] executor-level confirmation gate for dangerous operations
- [ ] advanced iframe coordinate mapping

## P4 Network

- [x] request/response recorder
- [x] response body best effort
- [ ] HAR export

## P5 Intelligence

- [x] observe
- [x] act
- [x] extract
- [x] dangerous-goal block and confirmed planning path
- [ ] LLM provider integration

## P6 Forge

- [x] explore trace marker
- [x] generate skill
- [x] test generated skill layout
- [x] trace-informed `capability.py` for text/tables/links/inputs extraction
- [ ] API-first endpoint inference
- [ ] operation safe-mode replay

## P7 Trace

- [x] `events.jsonl`
- [x] `states/`
- [x] `screenshots/`
- [x] `network/`
- [x] rolling `summary.json`
