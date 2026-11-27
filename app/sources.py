"""Where price data comes from. The rest of the app only sees the PriceSource protocol.

* DemoSource: synthetic products in `app/demo_data.json`, clearly labelled "demo" in the UI.
* IdealoMCPSource: the idealo MCP server (mcp.idealo.com), mapped from idealo's published
  tool reference. See docs/idealo-mcp.md.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date
from importlib import resources
from typing import Any, Protocol

from .models import Offer, PricePoint, ProductData


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


def parse_price(text: Any) -> float | None:
    """idealo formats prices as strings: "1.059,00 €" (DE/AT/FR/IT/ES) or "£999.99" (GB)."""
    if isinstance(text, (int, float)):
        return float(text)
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
        return round(float(raw), 2)
    except ValueError:
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

    def __init__(self, url: str | None = None, country: str | None = None) -> None:
        self.url = url or os.environ.get("IDEALO_MCP_URL") or "https://mcp.idealo.com/mcp"
        self.country = (country or os.environ.get("IDEALO_COUNTRY") or "DE").upper()
        self.tools = {
            "search": os.environ.get("IDEALO_TOOL_SEARCH") or "search_products",
            "history": os.environ.get("IDEALO_TOOL_HISTORY") or "get_product_price_history",
            "offers": os.environ.get("IDEALO_TOOL_OFFERS") or "get_product_offers",
        }
        self.min_match = float(os.environ.get("IDEALO_MIN_MATCH", "0.6"))

    async def _call_many(self, calls: list[tuple[str, dict[str, Any]]]) -> list[Any]:
        try:
            from mcp import ClientSession
            from mcp.client import streamable_http as transport

            from .idealo_auth import open_transport
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise SourceError("install the idealo extra: pip install -e '.[idealo]'") from exc
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
        ref = hit["productRef"]
        args = {"productRef": ref, "country": self.country}
        hist, offers = await self._call_many(
            [(self.tools["history"], args), (self.tools["offers"], {**args, "offset": 0})]
        )
        return ProductData(
            product_id=str(ref),
            name=str(hit.get("name") or query),
            url=hit.get("url"),
            history=history_from_idealo(hist),
            offers=offers_from_idealo(offers),
            source="idealo",
        )


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


def history_from_idealo(raw: Any) -> list[PricePoint]:
    """priceTrend.history -> one PricePoint per day (lowest price of that day), oldest first."""
    trend = (raw or {}).get("priceTrend") or {}
    by_day: dict[date, float] = {}
    for h in trend.get("history") or []:
        price = parse_price(h.get("price"))
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
        # get_product_details reports cents as integers; the history tool reports strings.
        if isinstance(h.get("price"), int) and h["price"] > 1000 and price > 1000:
            price = round(price / 100, 2)
        by_day[day] = min(price, by_day.get(day, price))
    return [PricePoint(day=d, price=p) for d, p in sorted(by_day.items())]


def offers_from_idealo(raw: Any) -> list[Offer]:
    """offers[] -> Offer(merchant, item price). Shipping is excluded to match the shop's tag."""
    out: list[Offer] = []
    for o in (raw or {}).get("offers") or []:
        price = parse_price(o.get("price"))
        shop = o.get("shop") or {}
        name = shop.get("name") or shop.get("merchantName")
        if price is None or not name:
            continue
        out.append(Offer(merchant=str(name), price=price, url=o.get("relocatorUrl")))
    return out


def make_source() -> PriceSource:
    return IdealoMCPSource() if os.environ.get("PRICE_SOURCE") == "idealo" else DemoSource()


def history_from_pairs(pairs: list[tuple[str, float]]) -> list[PricePoint]:
    return [PricePoint(day=date.fromisoformat(d), price=p) for d, p in pairs]


def offers_from_pairs(pairs: list[tuple[str, float]]) -> list[Offer]:
    return [Offer(merchant=m, price=p) for m, p in pairs]
