---
name: deal-eval
description: Score verdict quality on hand-labelled real deals and propose threshold changes. Use when tuning rules or before freezing the demo.
---
1. Load `tests/fixtures/labelled_deals.json`: each item has product, shop, price, was_price,
   expected label and a one-line why. If it doesn't exist, ask the user for 10 real deals.
2. Run `decide()` on each with recorded idealo data only (no live calls unless asked).
3. Print agreement, a confusion table, and every miss with its reasons and stats.
4. Propose at most two `Thresholds` changes, each with the misses it fixes and what it breaks.
   Don't apply them without the user's OK; when approved, add the fixed cases as tests.
