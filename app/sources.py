"""Where price data comes from. The rest of the app only sees the PriceSource protocol.

* DemoSource: synthetic products in `app/demo_data.json`, clearly labelled "demo" in the UI.
* IdealoMCPSource: the idealo MCP server (mcp.idealo.com), mapped from idealo's published
  tool reference. See docs/idealo-mcp.md.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from importlib import resources
from typing import TYPE_CHECKING, Any, Literal, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, model_validator

from .models import Money, Offer, PricePoint, ProductData, cents, to_decimal

if TYPE_CHECKING:
    from .idealo_usage import Purpose, UsageTracker

log = logging.getLogger("buy_or_bye.sources")


class SourceError(RuntimeError):
    """The data source failed or is not configured. The API reports it; it never guesses."""


class PriceSource(Protocol):
    name: str

    async def find(self, query: str) -> ProductData | None: ...


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 1}


class DemoSource:
    name = "demo"

    def __init__(self, data: list[dict[str, Any]] | None = None) -> None:
        if data is None:
            raw = resources.files("app").joinpath("demo_data.json").read_text()
            data = json.loads(raw)["products"]
        self._products = [ProductData(**p) for p in data]

    async def find(self, query: str) -> ProductData | None:
        q = _tokens(query)
        if not q:
            return None
        best, best_score = None, 0.0
        for p in self._products:
            score = len(q & _tokens(p.name)) / len(_tokens(p.name))
            if score > best_score:
                best, best_score = p, score
        return best if best_score >= 0.6 else None


def parse_price(text: Any) -> Decimal | None:
    """idealo formats prices as strings: "1.059,00 €" (DE/AT/FR/IT/ES) or "£999.99" (GB).
    Returns exact cents (Decimal); numbers are read through to_decimal, never as binary floats."""
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        try:
            return cents(to_decimal(text))
        except ValueError:
            return None
    if not isinstance(text, str):
        return None
    raw = re.sub(r"[^0-9,.]", "", text)
    if not raw:
        return None
    # The last separator followed by exactly two digits is the decimal point;
    # the other separator groups thousands ("1.059,00 €" in DE, "£1,299.00" in GB).
    m = re.search(r"[.,](\d{2})$", raw)
    if m:
        whole = re.sub(r"[.,]", "", raw[: m.start()])
        raw = f"{whole}.{m.group(1)}"
    else:
        raw = re.sub(r"[.,]", "", raw)
    try:
        return cents(Decimal(raw))
    except InvalidOperation:
        return None


def _match_score(query: str, name: str) -> float:
    q = _tokens(query)
    return len(q & _tokens(name)) / len(q) if q else 0.0


class IdealoMCPSource:
    """Adapter for the idealo MCP server (https://mcp.idealo.com/mcp, streamable HTTP + OAuth).

    Tool names and fields follow github.com/idealo/mcp-server-guide (docs/tools.md):
    search_products -> productRef; get_product_price_history -> priceTrend.history (30 days,
    daily); get_product_offers -> offers (5 per page). Mapping lives in the `*_from_*` helpers,
    which are pure and tested against the documented response shapes.
    """

    name = "idealo"

    def __init__(
        self,
        url: str | None = None,
        country: str | None = None,
        usage: UsageTracker | None = None,
        details_cache: DetailsCache | None = None,
    ) -> None:
        self.url = url or os.environ.get("IDEALO_MCP_URL") or "https://mcp.idealo.com/mcp"
        self.country = (country or os.environ.get("IDEALO_COUNTRY") or "DE").upper()
        self.tools = {
            "search": os.environ.get("IDEALO_TOOL_SEARCH") or "search_products",
            "history": os.environ.get("IDEALO_TOOL_HISTORY") or "get_product_price_history",
            "offers": os.environ.get("IDEALO_TOOL_OFFERS") or "get_product_offers",
            "details": os.environ.get("IDEALO_TOOL_DETAILS") or "get_product_details",
        }
        self.min_match = float(os.environ.get("IDEALO_MIN_MATCH", "0.6"))
        if usage is None:
            from .idealo_usage import UsageTracker

            usage = UsageTracker()
        self.usage = usage
        self.details_cache = details_cache or DetailsCache(
            ttl_s=float(os.environ.get("IDEALO_DETAILS_TTL_S", str(24 * 3600)))
        )

    async def _call_many(
        self, calls: list[tuple[str, dict[str, Any]]], purpose: Purpose = "price_check"
    ) -> list[Any]:
        try:
            from mcp import ClientSession
            from mcp.client import streamable_http as transport

            from .idealo_auth import open_transport
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise SourceError("install the idealo extra: pip install -e '.[idealo]'") from exc
        # Daily budget (D3): refused here, before any connection, all calls or none.
        await self.usage.acquire([tool for tool, _ in calls], purpose)
        out: list[Any] = []
        try:
            async with open_transport(transport, self.url) as streams:
                session = ClientSession(streams[0], streams[1])
                async with session:
                    await session.initialize()
                    for tool, args in calls:
                        result = await session.call_tool(tool, args)
                        out.append(_unwrap(tool, result))
        except Exception as exc:  # noqa: BLE001 - every idealo failure is reported the same way
            # The SDK wraps errors in ExceptionGroups (anyio task groups); surface the tool's
            # own SourceError if there is one, otherwise one clear, actionable message.
            inner = _first_source_error(exc)
            if inner is not None:
                raise inner from exc
            raise SourceError(
                "idealo is not answering. The sign-in may have expired: "
                "run `make idealo-login` and try again."
            ) from exc
        return out

    async def _call(self, tool: str, args: dict[str, Any]) -> Any:
        return (await self._call_many([(tool, args)]))[0]

    async def find(self, query: str) -> ProductData | None:
        found = await self._call(self.tools["search"], {"query": query, "country": self.country})
        hit = best_result(found, query, self.min_match)
        if hit is None:
            return None
        return await self.market_data(
            str(hit["productRef"]), str(hit.get("name") or query), hit.get("url")
        )

    async def market_data(self, product_ref: str, name: str, url: str | None) -> ProductData:
        """30-day history and current offers for an already identified product (2 calls).
        The URL flow passes its resolved match here, so it never searches twice."""
        args = {"productRef": product_ref, "country": self.country}
        hist, offers = await self._call_many(
            [(self.tools["history"], args), (self.tools["offers"], {**args, "offset": 0})]
        )
        return ProductData(
            product_id=product_ref,
            name=name,
            url=url,
            history=history_from_idealo(hist),
            offers=offers_from_idealo(offers),
            source="idealo",
            retrieved_at=datetime.now(UTC),
        )

    async def search(self, query: str, purpose: Purpose = "identity") -> list[SearchHit]:
        """search_products as typed hits (identity resolution, BOB-URL-001 M4)."""
        raw = (
            await self._call_many(
                [(self.tools["search"], {"query": query, "country": self.country})], purpose
            )
        )[0]
        return hits_from_idealo(raw)

    def details_args(self, product_ref: str, item_type: str | None = None) -> dict[str, Any]:
        """Arguments exactly as the recorded tool schema defines them (docs/idealo-mcp.md)."""
        args: dict[str, Any] = {"productRef": product_ref, "country": self.country}
        if item_type in ("CLUSTER", "SINGLE_OFFER"):  # the schema says: omit for PRODUCT
            args["type"] = item_type
        return args

    async def product_details(
        self, product_ref: str, url: str | None, item_type: str | None = None
    ) -> ProductDetails:
        """get_product_details for one search hit, cached by canonical idealo product ID.

        Never raises: a failure or a refused call (daily budget) gives status "unavailable"
        with the reason. Only call it when identity resolution needs it (see
        product_identity.details_needed).
        """
        cid = canonical_product_id(url)
        key = cid or f"ref:{product_ref}"
        async with self.details_cache.lock(key):
            cached = self.details_cache.get(key)
            if cached is not None:
                return cached
            try:
                raw = (
                    await self._call_many(
                        [(self.tools["details"], self.details_args(product_ref, item_type))],
                        purpose="identity",
                    )
                )[0]
            except SourceError as exc:
                return ProductDetails(
                    status="unavailable",
                    canonical_id=cid,
                    product_ref=product_ref,
                    error=str(exc),
                    missing=list(IDENTITY_FIELDS),
                )
            details = details_from_idealo(raw, datetime.now(UTC))
            details.canonical_id = details.canonical_id or cid
            details.product_ref = details.product_ref or product_ref
            if details.status != "unavailable":
                self.details_cache.put(key, details)
            return details


# --- get_product_details (schema verified live, see docs/idealo-mcp.md) -----------------------

IDENTITY_FIELDS = ("name", "url", "product_type")
_PRODUCT_TYPE_KEYS = {"produkttyp"}  # the attribute name seen in DE data; others not verified
_MAX_TEXT = 200
_MAX_OVERVIEW = 30
_MAX_SPECS = 100
_IDEALO_ID = re.compile(r"/OffersOfProduct/(\d+)")
_IDEALO_HOST = re.compile(r"(www\.)?idealo\.[a-z.]+")


class SpecAttribute(BaseModel):
    group: str | None = None
    name: str
    value: str


class ProductDetails(BaseModel):
    """What get_product_details says about one product. Fields idealo does not return (brand,
    GTIN, series) do not exist here, so they can never be filled in by guesswork."""

    status: Literal["complete", "partial", "unavailable"]
    source: Literal["idealo"] = "idealo"
    canonical_id: str | None = None
    product_ref: str | None = None
    name: str | None = None
    url: str | None = None
    product_type: str | None = None
    specifications: list[SpecAttribute] = Field(default_factory=list)
    overview: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    error: str | None = None
    retrieved_at: datetime | None = None


def canonical_product_id(url: str | None) -> str | None:
    """The stable numeric idealo product ID from an idealo product URL, else None."""
    if not url:
        return None
    parts = urlsplit(url)
    if not _IDEALO_HOST.fullmatch((parts.hostname or "").lower()):
        return None
    m = _IDEALO_ID.search(parts.path)
    return m.group(1) if m else None


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()
    return text[:_MAX_TEXT] or None


def _spec_attributes(raw: dict[str, Any]) -> list[SpecAttribute]:
    specs: list[SpecAttribute] = []
    groups = (raw.get("productSpecification") or {}).get("groups") or []
    for group in groups if isinstance(groups, list) else []:
        if not isinstance(group, dict):
            continue
        for attr in group.get("attributes") or []:
            if not isinstance(attr, dict) or len(specs) >= _MAX_SPECS:
                continue
            name, value = _text(attr.get("name")), _text(attr.get("value"))
            if name and value:
                specs.append(SpecAttribute(group=_text(group.get("name")), name=name, value=value))
    return specs


def details_from_idealo(raw: Any, retrieved_at: datetime) -> ProductDetails:
    if not isinstance(raw, dict) or not _text(raw.get("name")):
        return ProductDetails(
            status="unavailable",
            error="idealo returned no usable product details",
            missing=list(IDENTITY_FIELDS),
            retrieved_at=retrieved_at,
        )
    specs = _spec_attributes(raw)
    product_type = next((a.value for a in specs if a.name.lower() in _PRODUCT_TYPE_KEYS), None)
    overview = [t for t in (_text(o) for o in raw.get("productOverview") or []) if t]
    url = _text(raw.get("url")) or _text(raw.get("productDetailsUrl"))
    details = ProductDetails(
        status="complete",
        canonical_id=canonical_product_id(url),
        product_ref=_text(raw.get("productRef")),
        name=_text(raw.get("name")),
        url=url,
        product_type=product_type,
        specifications=specs,
        overview=overview[:_MAX_OVERVIEW],
        retrieved_at=retrieved_at,
    )
    details.missing = [f for f in IDENTITY_FIELDS if getattr(details, f) is None]
    if details.missing:
        details.status = "partial"
    return details


_CURRENCY_SYMBOLS = {"€": "EUR", "£": "GBP"}
_MAX_HITS = 20


class SearchHit(BaseModel):
    """One search_products result. `currency` is only what idealo's price string shows."""

    product_ref: str
    name: str
    url: str | None = None
    item_type: str | None = None
    price: Money | None = None
    currency: str | None = None
    canonical_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _read(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        out["name"] = _text(out.get("name")) or ""
        price = out.get("price")
        if isinstance(price, str):
            out["currency"] = out.get("currency") or next(
                (code for sym, code in _CURRENCY_SYMBOLS.items() if sym in price), None
            )
            out["price"] = parse_price(price)
        out["canonical_id"] = out.get("canonical_id") or canonical_product_id(out.get("url"))
        return out


def hits_from_idealo(raw: Any) -> list[SearchHit]:
    """search_products results -> SearchHit (results without a productRef or name dropped)."""
    results = raw.get("results") if isinstance(raw, dict) else None
    hits: list[SearchHit] = []
    for r in results if isinstance(results, list) else []:
        if not isinstance(r, dict) or not r.get("productRef") or not _text(r.get("name")):
            continue
        hits.append(
            SearchHit.model_validate(
                {
                    "product_ref": str(r["productRef"]),
                    "name": r.get("name"),
                    "url": _text(r.get("url")),
                    "item_type": _text(r.get("itemType")),
                    "price": r.get("price") if isinstance(r.get("price"), str) else None,
                }
            )
        )
        if len(hits) >= _MAX_HITS:
            break
    return hits


class DetailsCache:
    """In-memory details cache by canonical product ID, with a per-key lock so concurrent
    requests for the same product share one idealo call."""

    def __init__(self, ttl_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl_s = ttl_s
        self._clock = clock
        self._items: dict[str, tuple[float, ProductDetails]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def lock(self, key: str) -> asyncio.Lock:
        return self._locks.setdefault(key, asyncio.Lock())

    def get(self, key: str) -> ProductDetails | None:
        item = self._items.get(key)
        if item is None or self._clock() >= item[0]:
            self._items.pop(key, None)
            return None
        return item[1].model_copy(deep=True)

    def put(self, key: str, details: ProductDetails) -> None:
        self._items[key] = (self._clock() + self.ttl_s, details.model_copy(deep=True))


def _first_source_error(exc: BaseException) -> SourceError | None:
    if isinstance(exc, SourceError):
        return exc
    for sub in getattr(exc, "exceptions", ()) or ():
        found = _first_source_error(sub)
        if found is not None:
            return found
    return None


def _field(result: Any, *names: str) -> Any:
    # MCP SDK 1.x uses camelCase result fields, 2.x snake_case.
    for n in names:
        value = getattr(result, n, None)
        if value is not None:
            return value
    return None


def _unwrap(tool: str, result: Any) -> Any:
    if _field(result, "is_error", "isError"):
        texts = [c.text for c in getattr(result, "content", []) if getattr(c, "text", None)]
        raise SourceError(f"idealo tool {tool} returned an error: {' '.join(texts)[:200]}")
    structured = _field(result, "structured_content", "structuredContent")
    if structured is not None:
        return structured
    texts = [c.text for c in getattr(result, "content", []) if getattr(c, "text", None)]
    try:
        return json.loads(texts[0]) if texts else None
    except ValueError as exc:
        raise SourceError(f"idealo tool {tool} returned non-JSON content") from exc


def best_result(found: Any, query: str, min_match: float = 0.6) -> dict[str, Any] | None:
    """Pick the search result that matches the shopper's product name; None if nothing does."""
    results = (found or {}).get("results") or []
    scored = [
        (_match_score(query, str(r.get("name", ""))), i, r)
        for i, r in enumerate(results)
        if r.get("productRef") and r.get("itemType", "PRODUCT") in ("PRODUCT", "CLUSTER")
    ]
    if not scored:
        return None
    score, _, best = max(scored, key=lambda x: (x[0], -x[1]))
    return best if score >= min_match else None


def history_from_idealo(raw: Any, integer_cents: bool = False) -> list[PricePoint]:
    """priceTrend.history -> one PricePoint per day (lowest price of that day), oldest first.

    get_product_price_history gives price strings ("146,31 €"); the trend inside
    get_product_details gives integers in cents (14631). The caller states which one it
    passes (`integer_cents`): the unit is never guessed from the size of the number.
    """
    trend = (raw or {}).get("priceTrend") or {}
    by_day: dict[date, Decimal] = {}
    for h in trend.get("history") or []:
        value = h.get("price")
        if integer_cents and isinstance(value, int) and not isinstance(value, bool):
            price: Decimal | None = cents(Decimal(value) / 100)
        else:
            price = parse_price(value)
        iso = h.get("dateTimeISO")
        if price is None:
            continue
        if iso:
            day = date.fromisoformat(str(iso)[:10])
        elif isinstance(h.get("dateTime"), (int, float)):
            from datetime import UTC, datetime

            day = datetime.fromtimestamp(h["dateTime"] / 1000, tz=UTC).date()
        else:
            continue
        by_day[day] = min(price, by_day.get(day, price))
    return [PricePoint(day=d, price=p) for d, p in sorted(by_day.items())]


def offers_from_idealo(raw: Any) -> list[Offer]:
    """offers[] -> Offer: item price (as the shop tags it), shipping cost when idealo states
    it (`minShippingCost`; otherwise unknown, never 0) and idealo's observation time
    (`freshness`)."""
    out: list[Offer] = []
    for o in (raw or {}).get("offers") or []:
        price = parse_price(o.get("price"))
        shop = o.get("shop") or {}
        name = shop.get("name") or shop.get("merchantName")
        if price is None or not name:
            continue
        ship = o.get("minShippingCost")
        out.append(
            Offer(
                merchant=str(name),
                price=price,
                url=o.get("relocatorUrl"),
                shipping=parse_price(ship) if isinstance(ship, str) else None,
                observed_at=_utc(o.get("freshness")),
            )
        )
    return out


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None


def make_source() -> PriceSource:
    return IdealoMCPSource() if os.environ.get("PRICE_SOURCE") == "idealo" else DemoSource()


def history_from_pairs(pairs: list[tuple[str, Decimal | float]]) -> list[PricePoint]:
    return [PricePoint.model_validate({"day": date.fromisoformat(d), "price": p}) for d, p in pairs]


def offers_from_pairs(pairs: list[tuple[str, Decimal | float]]) -> list[Offer]:
    return [Offer.model_validate({"merchant": m, "price": p}) for m, p in pairs]
