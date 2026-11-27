---
name: demo
description: Rehearse the pitch demo end to end and report timing and anything a judge would notice. Use before the pitch or after UI changes.
---
1. Run `make demo`; every line must be ✓. If not, stop and report the mismatch.
2. Start `make dev` in the background and wait for http://localhost:8000/healthz.
3. For each deal in `tests/fixtures/deals.json`, POST it to `/api/check`, time it, and check:
   the label matches `expect`, every reason has evidence, and nothing appears without a source.
4. If a browser tool is available, open the page, click each demo chip, take a screenshot at
   375 px wide and check: label readable, chart visible, source badge visible.
5. Report a table (deal, label, seconds, issues). Target: under 2 seconds per demo deal.
