# idealo MCP: what it returns and how Buy or Bye uses it

Source: github.com/idealo/mcp-server-guide (`docs/tools.md`). Endpoint `https://mcp.idealo.com/mcp`,
streamable HTTP, OAuth sign-in. Trial tier: 3 req/s, 6 burst, 500 calls/day per user.
The samples there are illustrative; verify against a live call before relying on edge cases.

| Tool | Parameters | Fields we use | Notes |
|---|---|---|---|
| `search_products` | `query`, `country` (DE) | `results[].productRef`, `name`, `url`, `itemType` | `productRef` is opaque and short-lived |
| `get_product_price_history` | `productRef`, `country` | `priceTrend.history[].dateTimeISO`, `.price` ("146,31 €", a string) | 30 days, daily; `priceTrend: null` when no history; verified live 2026-11-27 (also `statistics`, `dataSourceConfidence`) |
| `get_product_offers` | `productRef`, `country`, `offset` | `offers[].shop.name`, `.price` (item price), `.minShippingCost`, `.freshness` (last seen, UTC), `.relocatorUrl` | 5 per page; Trial caps at 10 per product; verified live 2026-11-27 |
| `get_product_details` | `productRef` (required), `country`, `type` (CLUSTER/PRODUCT/SINGLE_OFFER, from search `itemType`) | `name`, `url`, `productSpecification.groups[].attributes[]`, `productOverview[]` | verified live 2026-11-27, see below |

## `get_product_details`: verified schema (BOB-URL-001 M3)
Discovered with `list_tools` and one live call on 2026-11-27 (Philips XC2011/01, DE). Recorded in
`tests/fixtures/idealo/get_product_details_schema.json` (tool definition) and
`tests/fixtures/idealo/get_product_details_xc2011.json` (trimmed response).

- **Input:** `productRef` (string, required, opaque, from `search_products`), `country`
  (2 letters; unknown or omitted means DE), `type` (enum CLUSTER, PRODUCT, SINGLE_OFFER; omit
  unless the search `itemType` is CLUSTER or SINGLE_OFFER). Annotated read-only and idempotent.
- **Output (required):** `productRef`, `itemType`, `siteId`, `name`, `imageUrls`, `nextOffset`,
  `offers`. **Optional:** `nameDelta`, `url`, `badges`, `userReviews`, `prosCons`, `testReports`,
  `expertReview`, `productSpecification` (`groups[].{name, type, attributes[].{name, value}}`;
  the group with `type: IMPORTANT` holds e.g. `Produkttyp`), `productOverview` (list of strings),
  `productDetailsUrl`, `priceTrend` (`history[].{dateTime: epoch ms, price: integer cents}`).
- **Not in the response:** no brand field, no GTIN/EAN, no series or product family. For
  XC2011/01 the product type is "Stielstaubsauger"; "2000 Series" appears nowhere. Buy or Bye
  leaves those fields unknown rather than infer them.
- **What we use:** `name`, `url` (canonical ID), `productSpecification`, `productOverview`, and
  the `Produkttyp` attribute as product type. Offers, reviews and the trend come from the
  dedicated tools or are not used.
- **Canonical product ID:** the numeric ID in idealo's product URL
  (`/OffersOfProduct/203830913_-xc2011` gives `203830913`). Stable, unlike `productRef`.

## Usage limits (BOB-URL-001 decision D3)
`app/idealo_usage.py` counts every idealo tool call per UTC day in `~/.buyorbye/idealo_usage.json`
and refuses calls before they are made:
- `IDEALO_DAILY_LIMIT` (default and hard maximum 500, the Trial quota; higher values are capped).
- `IDEALO_PRICE_CHECK_RESERVE` (default 150): `get_product_details` is refused once fewer than this
  many calls are left today, so price checks keep working.
- Details are cached per canonical product ID (`IDEALO_DETAILS_TTL_S`, default 24 h, in memory);
  concurrent requests for the same product share one call. A failed or refused call returns a
  `ProductDetails` with `status: "unavailable"` and the reason; missing fields are listed, never
  filled in.

## How the data drives the verdict
- **Price history (30 days)** -> real saving vs typical price, recent low, pre-sale hike, whether
  the claimed "was" price ever happened. 30 days is also the window of § 11 PAngV.
- **Merchant offers** -> "cheaper at another shop right now".
- Each call per check: 1 search + 1 history + 1 offers page = 3 calls (about 160 checks/day on Trial).
- Identity resolution may add 1 `get_product_details` call per new product (cached).

## What the data does not have
- A shop's own crossed-out price: the shopper enters or photographs it, and confirms it.
- History beyond 30 days: windows in `app/verdict.py` shrink to the history really available,
  and reason texts say "30 days".

## Sign-in
`make idealo-login` opens the idealo login once and caches the token in
`~/.buyorbye/idealo_oauth.json` (secret: never commit or share). The app then reuses and refreshes it.

## Mapping code and tests
`app/sources.py`: `best_result`, `history_from_idealo`, `offers_from_idealo`, `parse_price`.
Tests: `tests/test_idealo_mapping.py`, built from the documented sample shapes.
