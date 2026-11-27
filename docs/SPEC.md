# Buy or Bye: spec

**Idea:** [Name] and [Name]. **Team:** [Name], [Name], [you].
**Challenge:** idealo, AI Agents Berlin, Friday 27 Nov 2026 (Black Friday).

## Problem
On Black Friday, many "−70%" claims are measured against prices nobody recently paid.
A shopper looking at one deal can't check that in the moment.

## User and moment
One shopper, one deal, on a phone or laptop: in a shop, in an ad, or on a product page.

## Flow
1. **Input:** paste the product link or take a photo of a price tag or ad. There are no
   manual price fields.
2. **Identify (live mode, a link):** the link is validated, the page's structured data
   read once, and the product resolved to one idealo product (exact model and variant).
   "What we found" lists each fact with its source and status: *verified* (two sources
   agree), *one source*, or *sources disagree*. Facts no source states (e.g. the product
   series) are shown as not stated, never guessed.
3. **Price:** the shop page's own price, else idealo's current offer from the same shop, with
   the seller, shipping (or "not stated") and when idealo last saw it; such a price is marked
   as not live. No price found → no verdict; the app asks for a photo instead.
4. **Verdict:** BUY, BYE, WAIT or "not enough data", a price-history chart and one line per
   reason, each with the numbers it used and where they came from. Only a matched product is
   judged. Demo mode and photos use the offline path (`/api/extract/*` + `/api/check`).

API: `POST /api/v1/product-url/identify`, `/resolve`, `/check` (BOB-URL-001, details in
`docs/bob-url-001.md`); `/api/extract/*` and `/api/check` are unchanged.

## Checks (`app/verdict.py`, thresholds in `Thresholds`)
| Check | Data | Signal |
|---|---|---|
| Real saving | deal price vs reference price: median daily lowest price of the last 30 days, or the pre-hike typical price when a hike is detected | ≥ 10% supports BUY |
| Near 90-day low | deal price vs lowest price of the last 90 days | within 3% supports BUY |
| Cheaper recently | deal price vs lowest price of the last 30 days | > 3% above → BYE |
| Inflated claim | claimed discount vs real saving | ≥ 3× and ≥ 20% claimed → BYE |
| "Was" price never needed | claimed "was" vs highest daily lowest price in 90 days | > 5% above → reason |
| Pre-sale hike | peak of the last 21 days vs typical price 22–60 days ago | ≥ +10% → reference switches to the pre-hike price |
| Cheaper elsewhere now | current offers from other shops | ≥ 5% cheaper → BYE |
| Not enough data | product not found, or < 10 daily prices in 30 days | no verdict |

**Decision order:** any red flag → BYE. Otherwise BUY needs a ≥ 10% real saving *and* the 90-day
low. Everything else → WAIT.

## Out of scope (Friday)
Accounts, price alerts that buy, browser extension, native app, crawling or scraping shop
pages. Reading the one page a shopper pastes (structured data only, robots.txt honoured) is
in scope: see `docs/shop-pages.md`.

## Verification
`make check` passes; `make demo` shows ✓ for all five demo deals; with `PRICE_SOURCE=idealo`,
one real product returns a verdict whose numbers match idealo's own price chart;
`tests/test_golden_url_check.py` pins the full report for the Philips XC2011/01 link.
