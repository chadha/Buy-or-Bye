# ADR 0001: The verdict is decided by code, not by the LLM

**Status:** accepted · 2026-11-25

## Context
The product's value is a call a shopper can trust and check. LLM judgements vary between runs and
can't be tested against fixed cases; they can also be steered by text in an ad or a photo.

## Decision
`app/verdict.py` decides the label from price history and the shopper's confirmed numbers,
with thresholds in one `Thresholds` dataclass. The LLM is used only to read photos into fields
that the shopper confirms before any verdict.

## Consequences
- (+) Every label is reproducible and unit-tested; the demo can't drift between rehearsal and pitch.
- (+) Text in an ad saying "this is a great deal" has no effect on the verdict.
- (−) The rules need tuning on real deals (`/deal-eval`) instead of relying on model judgement.
