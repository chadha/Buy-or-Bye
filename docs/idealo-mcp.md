# idealo MCP: what it returns and how Buy or Bye uses it

Source: github.com/idealo/mcp-server-guide (`docs/tools.md`). Endpoint `https://mcp.idealo.com/mcp`,
streamable HTTP, OAuth sign-in. Trial tier: 3 req/s, 6 burst, 500 calls/day per user.
The samples there are illustrative; verify against a live call before relying on edge cases.

| Tool | Parameters | Fields we use | Notes |
|---|---|---|---|
| `search_products` | `query`, `country` (DE) | `results[].productRef`, `name`, `url`, `itemType` | `productRef` is opaque and short-lived |
| `get_product_price_history` | `productRef`, `country` | `priceTrend.history[].dateTimeISO`, `.price` ("1.059,00 €") | 30 days, daily; `priceTrend: null` when no history |
| `get_product_offers` | `productRef`, `country`, `offset` | `offers[].shop.name`, `.price`, `.relocatorUrl` | 5 per page; Trial caps at 10 per product |
| `get_product_details` | `productRef` | (not used yet) test reports, pros/cons, 30-day trend | candidate for a later "quality" signal |

## How the data drives the verdict
- **Price history (30 days)** -> real saving vs typical price, recent low, pre-sale hike, whether
  the claimed "was" price ever happened. 30 days is also the window of § 11 PAngV.
- **Merchant offers** -> "cheaper at another shop right now".
- Each call per check: 1 search + 1 history + 1 offers page = 3 calls (about 160 checks/day on Trial).

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
