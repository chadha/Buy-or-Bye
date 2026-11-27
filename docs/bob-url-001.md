# BOB-URL-001: URL-to-Product Intelligence

Status: M1–M5 done (27 Nov 2026); next M6. Priority: P0. Owner: product (chadha); implementation: Claude Code.

A shopper pastes a product URL. Buy or Bye validates it, extracts what the page and URL say
about the product, identifies the exact product on idealo, compares market prices and price
history, verifies the evidence and returns an explainable verdict.

**Invariants (every stage):**
- Never invent prices, product attributes, historical observations or retailer offers.
  Unknown stays unknown; every value carries its source.
- `app/verdict.py` stays the only authority for BUY, BYE, WAIT and NOT_ENOUGH_DATA, and stays
  deterministic.
- Existing endpoints and their request/response behaviour do not change.
- No deployment. No push without the product owner's approval.

Stage names are scoped to this feature ("BOB-URL-001 M1"); they are not the whole-system
milestones M0–M7 in `IMPLEMENTATION_PLAN.md`.

## Decisions (27 Nov 2026, product owner)

### D1: money as `Decimal` (approved)
- Use `Decimal` for monetary values across domain models and calculations; no float
  arithmetic on money.
- Keep existing API compatibility where possible: JSON keeps numeric values (no strings).
- Regression tests freeze the current verdict outputs before the migration.
- JSON serialisation is tested explicitly.

Implemented in M2: `Money` (`app/models.py`) is `Decimal` quantised to cents, half up; floats
are read through their shortest repr ("79.99"), never their binary value; NaN, infinity and
booleans are refused. In JSON it is still a plain number (`279.0`), so clients see the same
shapes. Ratios and stats use `Number` (Decimal, numeric in JSON). Percentages in reason texts
round half up, like money. The golden set (505 cases, `tests/fixtures/golden_verdicts.json`,
frozen from the float code) matches exactly except two documented float defects, both proven
by tests and neither changing a label: a half-cent median (Kestrel €1,093.955 now €1,093.96,
not €1,093.95) and an exact 37.5% claimed discount (now "−38%", not "−37%").

### D2: API contracts (conditionally approved)
- `/api/extract/*` and `/api/check` keep their current request and response behaviour.
- New fields are optional. URL intelligence gets new, versioned endpoints under `/api/v1/`.
- Backward-compatibility tests pin the existing response shapes.

### D3: idealo `get_product_details` (approved with usage guardrails)
- Discover and record the real tool schema (`list_tools`) before using it; no invented
  parameters or fields.
- Call it only when needed to resolve product identity.
- Cache results by canonical idealo product ID; no duplicate calls for the same product.
- Track idealo calls per day; hard cap, configurable, default 500/day (idealo Trial limit),
  with a reserved share kept for price checks.
- On failure return a structured partial result. Never fabricate missing information.

## Stages

Each stage: failing tests first, implementation, `make check` + `make demo`, local commit.

| Stage | Scope | Acceptance |
|---|---|---|
| **M1** URL validation and product extraction | Validate and canonicalise the URL (scheme, host, port, credentials, length, tracking parameters, fragment). Extract a `ProductIdentity` (name, brand, model, GTIN, MPN, category, currency, market) from schema.org JSON-LD, meta tags and the URL, each field with its source and status `unverified`. New `POST /api/v1/product-url/identify`. | XC2011_01 URL → model `XC2011/01` from the URL path, market `DE`; brand/family/currency stay unknown when the page has no structured data (it loads them with JavaScript). Invalid URLs → structured 422. Demo mode stays offline. Old endpoints unchanged. |
| **M2** Decimal migration (D1) | Freeze current verdict outputs as golden tests; move `Deal`, `PricePoint`, `Offer`, `Stats`, `Evidence` and verdict arithmetic to `Decimal`; JSON stays numeric. | All golden verdicts identical; JSON round-trip tests; no float money in `app/`. |
| **M3** idealo product details (D3) | Record the real `get_product_details` schema; adapter in `sources.py`; per-product cache; daily usage tracker with configurable hard cap and reserve; structured partial results. | Schema recorded in `docs/idealo-mcp.md`; second lookup of a product makes no call; cap enforced in tests; failure → partial result, no invented fields. |
| **M4** Identity resolution and verification | Match the URL identity to an idealo product by GTIN, then brand + model (+ variant). Confidence and reasons. Fix shop matching for idealo merchant names like `philips.de (Home-appliances)`. Fields confirmed by idealo become `verified`, disagreements `contradicted`. | XC2011_01 URL → Philips XC2011/01 (brand and family from idealo, verified), same-shop offer €89.99 when idealo lists it; wrong-variant matches rejected. |
| **M5** Market comparison and evidence | Same-shop price, other offers, 30-day history into the existing verdict. Every observation carries source URL, retrieval time (UTC), seller and market. `POST /api/v1/product-url/check` returns the full report. | Verdict unchanged for identical numbers; every number in the report has provenance. |
| **M6** UI, golden fixtures, docs | "What we found" shows identity, sources and statuses; golden URL fixtures (recorded, minimal) for the XC2011/01 path; SPEC and demo docs. | Browser check on 375 px; `make demo` green; docs updated. |

## M3 findings (verified live, 27 Nov 2026)
- `get_product_details` input: `productRef` (required), `country`, `type`. Output has name,
  URL, specifications, overview, offers, reviews and a price trend, but **no brand, GTIN/EAN or
  series field**. Full record in `docs/idealo-mcp.md` and `tests/fixtures/idealo/`.
- For XC2011/01 idealo gives product type "Stielstaubsauger" (stick vacuum). "2000 Series"
  appears in no idealo field, and the Philips page exposes no structured data, so the family
  stays **unknown** unless another approved source provides it. It is not inferred.
- Canonical product ID: the numeric ID in idealo's product URL (203830913), stable, unlike
  `productRef`.
- Every idealo call now goes through the daily budget (`app/idealo_usage.py`): a price check
  costs 3 calls, a details lookup 1 (cached per product for 24 h).

## M4 results (verified live, 27 Nov 2026)
`POST /api/v1/product-url/resolve` on the XC2011_01 URL: matched, confidence high, idealo
product 203830913 "Philips XC2011/01".

| Field | Value | Source | Status |
|---|---|---|---|
| model | XC2011/01 | URL path | verified by idealo's product name |
| brand | Philips | idealo product name | verified by the shop's own domain (.philips) |
| market | DE | URL path | verified by the idealo DE marketplace |
| category | Stielstaubsauger | idealo details | unverified (one source) |
| currency | EUR | idealo price ("89,30 €") | unverified (one source) |
| name | Philips XC2011/01 | idealo | unverified |
| family, GTIN, MPN | unknown | no approved source states them | — |

Rules: "verified" needs two independent sources; one source is "unverified"; disagreement is
"contradicted". Exact model + variant gives high confidence; model without variant medium;
name only low ("uncertain", never a firm identity); another variant or model, a different
page brand, or a single-shop listing is rejected; equally good different products are
"ambiguous". A market mismatch makes the result "uncertain". Product details are fetched only
when the category is unknown.

Shop matching now understands idealo merchant names such as `philips.de (Home-appliances)`, so
the link pre-fill finds the same-shop offer (€89.99 live).

## M5 results (verified live, 27 Nov 2026)
`POST /api/v1/product-url/check` on the XC2011_01 URL: judged **BUY** ("a real 31% saving, at
the 30-day low"). Deal price €89.99 from idealo's current offer by `philips.de
(Home-appliances)` (the Philips page states no price), shipping €0.00 stated separately;
history 31 days (2026-10-28..2026-11-27), 4 offers. Cost: 4 idealo calls (search, details,
history, offers): the M4 match is reused, nothing is searched twice, the page is read once.

- Every price is a `PriceObservation`: kind, amount, currency, seller, market, source
  (`shop_page` or `idealo`), source URL, observed time, shipping cost and whether it is
  included (`None` = not stated, never assumed). idealo statistics carry a `MarketProvenance`
  block (product ID and URL, market, currency, retrieval time, history window, offer count).
- Deal price: the shop page's own price first, else idealo's offer from the same shop; no
  price, no verdict. The "was" price only ever comes from the shop page.
- Only a "matched" identity gets market data and a label. An unresolved product with a price
  gets NOT_ENOUGH_DATA from `verdict.decide` itself.
- `verdict.decide` is called exactly as `/api/check` calls it (tested for identical results).
- idealo units are explicit: history strings are read as written, details trends are integer
  cents only when the caller says so. The old "integer above 1000 is cents" guess is gone.
- idealo's offer `freshness` is passed through as `observed_at`, separate from our
  `retrieved_at`. It is a real "last seen" time (36 and 60 minutes old in two live samples),
  so the UI must not present these prices as live.

## Example (test expectation, not a hard-coded rule)

`https://www.home-appliances.philips/de/de/p/XC2011_01` should end as Philips XC2011/01,
2000 Series cordless vacuum cleaner, EUR. Live findings on 27 Nov 2026: the page is a
JavaScript shell (no structured data), robots.txt allows it; idealo knows "Philips XC2011/01"
(31 days of history, 4 offers, including `philips.de (Home-appliances)` at €89.99). So in
M1 only the model and market come from the URL; brand, family and currency arrive in M3/M4
from idealo, marked with idealo as their source.

## Risks
- Shops that render prices only with JavaScript give no page data; identity then depends on
  the URL and idealo.
- URL slugs are weak evidence: a model number read from a slug is `unverified` until M4.
- idealo Trial quota (500 calls/day) bounds checks per day; M3 adds tracking and a cap.
- DNS rebinding gap in page fetching (see `docs/shop-pages.md`) must be closed before any
  public deployment.
