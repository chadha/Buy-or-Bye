# Buy or Bye: product positioning

## Product promise

**Don't analyze the deal. Just ask Buy or Bye.**

Buy or Bye is a purchase-decision assistant. It does the investigation and interpretation so the shopper can make a confident decision without becoming their own price analyst.

The customer should not need to:
- Research price history or calculate discount percentages.
- Compare retailer offers manually.
- Interpret charts, price fluctuations, or conflicting claims.
- Work out whether the advertised saving is meaningful.

The customer supplies a product or offer. Buy or Bye gathers and evaluates the available evidence, then returns a clear recommendation with a short explanation.

## Experience

1. **Give Buy or Bye the product:** paste a product/deal URL, enter product details, or provide a photo or screenshot where supported.
2. **Buy or Bye investigates:** identify the product and offer, retrieve available price and retailer evidence, evaluate savings, alternatives, suitability, risks, and evidence quality according to the supported checks.
3. **Get a decision:** show an actionable verdict, the key reasons, relevant risks, and uncertainty. The customer should not have to repeat the analysis.

## Decision principles

- **Action first:** lead with the recommended next step, not a dashboard of metrics.
- **Evidence underneath:** make the recommendation explainable with traceable sources, timestamps, and the numbers that materially affected it.
- **Honest uncertainty:** missing, stale, conflicting, or insufficient evidence must reduce confidence or produce an insufficient-evidence outcome. Never invent certainty.
- **Human remains in control:** Buy or Bye recommends; the customer decides. The MVP does not purchase, pay, or perform retailer-side transactions.
- **Low effort:** ask the customer to confirm or correct extracted details only when needed. Do not make manual research a prerequisite.

## Position relative to price-comparison tools

Price history and offer comparison are useful inputs, not the customer-facing product promise.

Tools such as idealo can expose price history and comparison data. Buy or Bye's intended value is to interpret the available evidence and translate it into a clear purchase action. Do not claim that price history, discount checking, or deal comparison alone is unique to Buy or Bye.

This is a product-positioning distinction, not a claim that every competitor lacks decision or recommendation features. Validate differentiation through customer research and competitive testing.

## Customer-facing language

Primary line: **Don't analyze the deal. Just ask Buy or Bye.**

Supporting line: **Share a link or a photo. We'll check the evidence and tell you whether to BUY, WAIT, or BYE, and why.**

Use an insufficient-evidence outcome when the available data cannot support a responsible recommendation. Do not force a verdict.

## Product design implications

- Put the verdict and one-sentence rationale at the top of the result.
- Show only the few evidence points needed to justify the recommendation; make deeper details available on demand.
- Keep source provenance and timestamps accessible.
- Distinguish observed facts, calculated metrics, and model-generated explanations.
- Never let an LLM fabricate evidence or override deterministic decision rules.
- Optimize the flow for a shopper who wants an answer, not a research workspace.

## Success signal

A shopper can submit a product with minimal effort, understand the recommendation and its main reason quickly, and decide what to do next without manually analyzing price charts or retailer comparisons.
