# Shop pages: pre-filling prices from a pasted link

Code: `app/shop_page.py`. Tests: `tests/test_shop_page.py` (no network).

## What happens when a shopper pastes a link (live mode only)
1. **Shop page.** One GET of that page plus its `robots.txt`. The price, the strikethrough
   ("was") price and the product name are read from schema.org JSON-LD (`Product` → `offers`,
   `priceSpecification` with `priceType` StrikethroughPrice/ListPrice) or price meta tags
   (`product:price:amount`, `og:price:amount`, `itemprop="price"`). EUR only.
2. **idealo fallback.** If the page has no readable price, idealo is searched for the product
   and the current offer **from the same shop** is used (`merchant_matches`). Another shop's
   price is never put in the deal price field.
3. **Typing.** Otherwise the shopper types the prices.

Every value is a pre-fill: the shopper confirms or edits it before `/api/check` judges the
deal against idealo price history. Demo mode (`PRICE_SOURCE=demo`) never fetches links.

## Terms, allowed use and limits (AGENTS.md: new data source record)
| Item | Rule |
|---|---|
| Allowed use | Read one public product page the shopper explicitly pasted, on their request. No crawling, no follow-up links, no stored copies. |
| robots.txt | Fetched first; a disallowed page is not read. 4xx/3xx = no robots.txt; 5xx or network error = not read. User-agent token `BuyOrBye`. |
| Access | No logins, cookies, CAPTCHAs, paywalls or JavaScript rendering. Shops whose prices load only via JavaScript (e.g. home-appliances.philips) fall back to idealo or typing. |
| Data fields | Product name, price, strikethrough price, currency. Free page text is ignored (untrusted, ambiguous). |
| Rate | One page + one robots.txt per paste, no retries. idealo fallback costs 3 idealo calls. |
| Freshness | Read at paste time; nothing is cached. |
| Network safety | http/https on ports 80/443 only, no credentials in URLs, every host and redirect hop must resolve to public addresses, max 3 redirects, 8 s timeout, 2 MB page and 512 KB robots.txt limits. |
| Failure behaviour | Never raises to the UI; the note tells the shopper to type the prices. |

## Known limits
- DNS is checked before connecting, and httpx resolves again when it connects. A host that
  changes its DNS answer between the two lookups is not fully covered. Pin the resolved
  address in the HTTP transport before exposing this beyond a local or demo deployment.
- Shop terms of service still apply per shop. Review a shop's terms before relying on it in
  a public release.
