---
paths:
  - "app/verdict.py"
  - "tests/test_verdict.py"
---
# Verdict engine rules
- Keep `app/verdict.py` pure: no imports of httpx, os, datetime.now/date.today, or app.sources.
- Every new `Reason` needs at least one `Evidence` whose value comes from the data or the user.
- Thresholds live in `Thresholds`; never hard-code a percentage inside `decide`.
- New rule: failing test first in `tests/test_verdict.py`, then the rule, then `make demo` still
  gives the expected labels.
