"""Prices for a pasted shop link: the page's structured product data first, idealo second.

Rules (see docs/shop-pages.md):
* One GET for the page the shopper pasted, plus its robots.txt. No crawling, no logins,
  no JavaScript, no retries. A page robots.txt disallows is not fetched.
* Only public http(s) hosts on the default ports; every redirect hop is re-checked, so a
  link cannot point the server at a private network or a cloud metadata address.
* Only schema.org JSON-LD and price meta tags are read. Prices in free page text are ignored:
  they are ambiguous (shipping, accessories, ads) and the page is untrusted content.
* idealo is used only for the SAME shop's current offer. Another shop's price is never put
  into the deal price field.
* The page shows what was read and where it came from ("What we found"). No price, no verdict.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import socket
import urllib.robotparser
from collections.abc import Awaitable, Callable, Iterator
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import BaseModel

from .extract import Extracted, parse_text
from .sources import PriceSource, SourceError, parse_price

log = logging.getLogger("buy_or_bye.shop_page")

USER_AGENT = "BuyOrBye/0.1 (deal checker; reads one product page when a shopper pastes it)"
ROBOTS_TOKEN = "BuyOrBye"
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_ROBOTS_BYTES = 512 * 1024
MAX_REDIRECTS = 3
TIMEOUT = httpx.Timeout(8.0, connect=4.0)

Resolver = Callable[[str], list[str]]
Fetcher = Callable[[str], Awaitable[str]]


class PageFetchError(RuntimeError):
    """The page was not fetched (unsafe URL, robots.txt, HTTP error, wrong type or size)."""


class PagePrices(BaseModel):
    name: str | None = None
    price: float | None = None
    was_price: float | None = None


# --- URL safety --------------------------------------------------------------------------------


def _system_resolve(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise PageFetchError(f"cannot resolve {host}") from exc
    return [str(info[4][0]) for info in infos]


def check_public_url(url: str, resolve: Resolver = _system_resolve) -> None:
    """Raise PageFetchError unless url is http(s) on a default port and resolves only to
    public addresses. Note: httpx resolves again when connecting, so a host that changes its
    DNS answer between the two lookups is not fully covered (documented in docs/shop-pages.md).
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise PageFetchError("only http and https links are read")
    if parts.username or parts.password:
        raise PageFetchError("links with a user name or password are not read")
    try:
        port = parts.port
    except ValueError as exc:
        raise PageFetchError("invalid port") from exc
    if port not in (None, 80, 443):
        raise PageFetchError("only the default web ports are read")
    host = parts.hostname
    if not host:
        raise PageFetchError("link has no host")
    addresses = resolve(host)
    if not addresses:
        raise PageFetchError(f"cannot resolve {host}")
    for raw in addresses:
        ip = ipaddress.ip_address(raw.split("%")[0])
        mapped = getattr(ip, "ipv4_mapped", None)
        if not (mapped or ip).is_global:
            raise PageFetchError(f"{host} is not a public address")


# --- Fetching ----------------------------------------------------------------------------------


async def _read_limited(resp: httpx.Response, limit: int, what: str) -> bytes:
    body = bytearray()
    async for chunk in resp.aiter_bytes():
        body.extend(chunk)
        if len(body) > limit:
            raise PageFetchError(f"{what} is too large")
    return bytes(body)


async def _robots_allows(client: httpx.AsyncClient, url: str) -> bool:
    parts = urlsplit(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    try:
        async with client.stream("GET", robots_url) as resp:
            if 400 <= resp.status_code < 500 or 300 <= resp.status_code < 400:
                return True  # no robots.txt here (redirects are not followed for it)
            if resp.status_code != 200:
                raise PageFetchError(f"robots.txt unavailable ({resp.status_code})")
            text = (await _read_limited(resp, MAX_ROBOTS_BYTES, "robots.txt")).decode(
                "utf-8", "replace"
            )
    except httpx.HTTPError as exc:
        raise PageFetchError("robots.txt unavailable") from exc
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(text.splitlines())
    return parser.can_fetch(ROBOTS_TOKEN, url)


async def fetch_page(
    url: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    resolve: Resolver = _system_resolve,
) -> str:
    """GET one public HTML page, honouring robots.txt, with re-checked redirects and limits."""
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    async with httpx.AsyncClient(
        transport=transport, timeout=TIMEOUT, follow_redirects=False, headers=headers
    ) as client:
        robots_checked: dict[str, bool] = {}
        for _hop in range(MAX_REDIRECTS + 1):
            await asyncio.to_thread(check_public_url, url, resolve)
            origin = urlsplit(url).netloc
            if origin not in robots_checked:
                robots_checked[origin] = await _robots_allows(client, url)
            if not robots_checked[origin]:
                raise PageFetchError("the shop's robots.txt does not allow reading this page")
            try:
                async with client.stream("GET", url) as resp:
                    if resp.is_redirect and resp.headers.get("location"):
                        url = urljoin(url, resp.headers["location"])
                        continue
                    if resp.status_code != 200:
                        raise PageFetchError(f"the shop page returned {resp.status_code}")
                    ctype = resp.headers.get("content-type", "").lower()
                    if "html" not in ctype:
                        raise PageFetchError("the link is not an HTML page")
                    body = await _read_limited(resp, MAX_PAGE_BYTES, "the page")
                    return body.decode(resp.encoding or "utf-8", "replace")
            except httpx.HTTPError as exc:
                raise PageFetchError("the shop page could not be loaded") from exc
        raise PageFetchError("too many redirects")


# --- Parsing (pure) ----------------------------------------------------------------------------

_LD_RE = re.compile(
    r"<script[^>]*type\s*=\s*[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.S | re.I
)
_META_RE = re.compile(r"<meta\b[^>]*>", re.I)
_ATTR_RE = re.compile(r"([a-zA-Z:-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)')")


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        out: float | None = float(value)
    elif isinstance(value, str):
        s = value.strip()
        out = float(s) if re.fullmatch(r"\d+(\.\d+)?", s) else parse_price(s)
    else:
        return None
    return round(out, 2) if out is not None and 0 < out < 100_000 else None


def _types(node: dict[str, Any]) -> list[str]:
    t = node.get("@type", [])
    return [
        str(x).rsplit("/", 1)[-1].rsplit(":", 1)[-1] for x in (t if isinstance(t, list) else [t])
    ]


def _nodes(data: Any) -> Iterator[dict[str, Any]]:
    if isinstance(data, list):
        for item in data:
            yield from _nodes(item)
    elif isinstance(data, dict):
        yield data
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in data:
                yield from _nodes(data[key])


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value] if value is not None else []


def _is_eur(*nodes: Any) -> bool:
    for n in nodes:
        if isinstance(n, dict) and n.get("priceCurrency"):
            return str(n["priceCurrency"]).strip().upper() == "EUR"
    return False


def _strikethrough(spec: dict[str, Any]) -> bool:
    kind = str(spec.get("priceType", "")).lower()
    return any(k in kind for k in ("strikethrough", "listprice", "srp", "msrp"))


def _offer_prices(offer: dict[str, Any]) -> tuple[float | None, float | None]:
    specs = [s for s in _as_list(offer.get("priceSpecification")) if isinstance(s, dict)]
    if not _is_eur(offer, *specs):
        return None, None
    price = _num(offer.get("price")) or _num(offer.get("lowPrice"))
    if price is None:
        price = next(
            (p for s in specs if not _strikethrough(s) and (p := _num(s.get("price")))), None
        )
    was = max((p for s in specs if _strikethrough(s) and (p := _num(s.get("price")))), default=None)
    return price, was


def _from_json_ld(html: str) -> PagePrices:
    best = PagePrices()
    for m in _LD_RE.finditer(html):
        try:
            data = json.loads(m.group(1).strip())
        except ValueError:
            continue
        for node in _nodes(data):
            if "Product" not in _types(node):
                continue
            name = node.get("name") if isinstance(node.get("name"), str) else None
            for offer in _as_list(node.get("offers")):
                if not isinstance(offer, dict):
                    continue
                price, was = _offer_prices(offer)
                if price is not None and (best.price is None or price < best.price):
                    best = PagePrices(name=name or best.name, price=price, was_price=was)
            if best.name is None and name:
                best.name = name
    return best


def _from_meta(html: str) -> PagePrices:
    meta: dict[str, str] = {}
    for tag in _META_RE.findall(html):
        attrs = {k.lower(): (a if a else b) for k, a, b in _ATTR_RE.findall(tag)}
        key = attrs.get("property") or attrs.get("name") or attrs.get("itemprop")
        if key and "content" in attrs:
            meta.setdefault(key.lower(), attrs["content"])
    price, currency = None, ""
    for amount_key, currency_key in (
        ("product:price:amount", "product:price:currency"),
        ("og:price:amount", "og:price:currency"),
        ("price", "pricecurrency"),
    ):
        if amount_key in meta:
            price, currency = _num(meta[amount_key]), meta.get(currency_key, "")
            break
    name = meta.get("og:title")
    if currency.strip().upper() != "EUR":
        price = None
    return PagePrices(name=name, price=price)


def prices_from_html(html: str) -> PagePrices:
    """Product name, price and strikethrough price from structured data only."""
    page = _from_json_ld(html)
    if page.price is None:
        meta = _from_meta(html)
        page = PagePrices(name=page.name or meta.name, price=meta.price)
    if page.price is not None and page.was_price is not None and page.was_price <= page.price:
        page.was_price = None
    if page.name:
        page.name = re.sub(r"\s+", " ", page.name).strip()[:120] or None
    return page


# --- Link -> fields ----------------------------------------------------------------------------


def _alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def merchant_matches(merchant: str, host: str) -> bool:
    """Is an idealo merchant ("MediaMarkt" or "mediamarkt.de") the shop at host?"""
    m = merchant.strip().lower().removeprefix("www.")
    h = host.strip().lower().removeprefix("www.")
    if "." in m:
        return h == m or h.endswith("." + m)
    labels = h.split(".")[:-1]
    return bool(_alnum(m)) and any(_alnum(label) == _alnum(m) for label in labels)


async def prices_for_link(
    url: str, source: PriceSource | None, fetch: Fetcher | None = None
) -> Extracted:
    """Pre-fill the deal fields for a pasted link. Never raises; falls back to typing."""
    base = parse_text(url)
    shop = base.shop or "this shop"
    page = PagePrices()
    try:
        page = prices_from_html(await (fetch or fetch_page)(url))
    except PageFetchError as exc:
        log.info("shop page not read for %s: %s", shop, exc)
    except Exception:  # noqa: BLE001 - a pre-fill must never break the form
        log.exception("shop page parsing failed for %s", shop)

    product = page.name or base.product
    if page.price is not None:
        return Extracted(
            product=product,
            price=page.price,
            was_price=page.was_price,
            shop=base.shop,
            note="Prices read from the shop page's product data"
            + ("." if page.was_price else "; the page shows no claimed 'was' price."),
        )

    if source is not None and product and base.shop:
        try:
            found = await source.find(product)
        except SourceError as exc:
            log.info("idealo lookup failed for %s: %s", shop, exc)
            found = None
        except Exception:  # noqa: BLE001 - a pre-fill must never break the form
            log.exception("idealo lookup crashed for %s", shop)
            found = None
        offer = next(
            (
                o
                for o in (found.offers if found else [])
                if o.in_stock and merchant_matches(o.merchant, base.shop)
            ),
            None,
        )
        if found and offer:
            return Extracted(
                product=found.name,
                price=offer.price,
                shop=base.shop,
                note=f"Price from idealo's current offer for {base.shop} (the shop page had "
                "no readable price data).",
            )

    return Extracted(
        product=product,
        shop=base.shop,
        note=f"We couldn't read prices for {shop}: its page has no readable price data and "
        "idealo lists no offer from this shop.",
    )
