"""BOB-URL-001 M5: one product URL -> identity -> idealo market data -> verdict, with provenance.

Flow (the page is fetched once; idealo is searched once):
1. Validate the URL and read the page's structured data (M1). The same HTML gives the
   shop's own price and claimed "was" price, if the page states them.
2. Resolve the identity to one idealo product (M4). Only a "matched" identity is judged;
   anything less never gets market data or a BUY/BYE/WAIT.
3. Fetch 30-day history and current offers for that product (2 idealo calls).
4. Deal price: the shop page's price, else idealo's current offer from the same shop. No
   price, no verdict. The "was" price comes only from the shop page.
5. `verdict.decide` judges exactly as /api/check does. It stays the only authority for the
   label (an unresolved product with a price gets its NOT_ENOUGH_DATA from decide()).

Every price in the report is a PriceObservation (source, URL, time, seller, market,
currency, shipping); idealo statistics carry a market-data provenance block.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from .identity_resolution import IdentitySource, Resolution, resolve_identity
from .models import Deal, Offer, PriceObservation, ProductData, Verdict
from .product_identity import UrlIdentityReport, identify_product_url
from .shop_page import PagePrices, fetch_page, merchant_matches, prices_from_html
from .sources import SourceError
from .verdict import decide

Fetcher = Callable[[str], Awaitable[str]]


class CheckSource(IdentitySource, Protocol):
    async def market_data(self, product_ref: str, name: str, url: str | None) -> ProductData: ...


class MarketProvenance(BaseModel):
    source: Literal["idealo"] = "idealo"
    canonical_id: str | None
    product_url: str | None
    market: str
    currency: str | None
    retrieved_at: datetime | None  # UTC
    history_days: int
    history_window: str | None
    offers: int


class UrlCheckReport(BaseModel):
    schema_version: Literal["1"] = "1"
    status: Literal["judged", "not_enough_data", "unavailable"]
    verdict: Verdict | None = None
    reasons: list[str] = Field(default_factory=list)
    deal: PriceObservation | None = None
    was: PriceObservation | None = None
    offers: list[PriceObservation] = Field(default_factory=list)
    market: MarketProvenance | None = None
    resolution: Resolution
    warnings: list[str] = Field(default_factory=list)


def _fetch_once(fetch: Fetcher) -> tuple[Fetcher, dict[str, str]]:
    """Wrap a fetcher so identity and prices share one page download."""
    seen: dict[str, str] = {}

    async def once(url: str) -> str:
        if url not in seen:
            seen[url] = await fetch(url)
        return seen[url]

    return once, seen


def _offer_observation(o: Offer, market: str, currency: str | None) -> PriceObservation:
    return PriceObservation(
        kind="offer",
        amount=o.price,
        currency=currency or "EUR",
        seller=o.merchant,
        market=market,
        source="idealo",
        source_url=o.url,
        observed_at=o.observed_at,
        shipping_cost=o.shipping,
        shipping_included=False,  # idealo offer prices are item prices; shipping is separate
    )


def _deal_from_page(
    page: PagePrices, report: UrlIdentityReport, market: str | None
) -> tuple[PriceObservation | None, PriceObservation | None]:
    if page.price is None:
        return None, None
    deal = PriceObservation(
        kind="deal_price",
        amount=page.price,
        currency="EUR",  # prices_from_html accepts EUR prices only
        seller=report.input.shop,
        market=market,
        source="shop_page",
        source_url=report.input.url,
        observed_at=report.page.retrieved_at,
    )  # shipping: not stated by the page, so left unknown
    was = (
        deal.model_copy(update={"kind": "claimed_was_price", "amount": page.was_price})
        if page.was_price is not None and page.was_price > page.price
        else None
    )
    return deal, was


async def check_product_url(
    raw_url: str,
    source: CheckSource,
    *,
    fetch: Fetcher | None = None,
    today: date | None = None,
) -> UrlCheckReport:
    """Raises UrlValidationError for unusable input; everything else ends in a report."""
    once, seen = _fetch_once(fetch or fetch_page)
    report = await identify_product_url(raw_url, fetch=once)
    page = prices_from_html(seen[report.input.url]) if report.input.url in seen else PagePrices()
    resolution = await resolve_identity(report, source)
    market_code = source.country.upper()
    deal_obs, was_obs = _deal_from_page(page, report, market_code)
    judge_day = today or date.today()

    if resolution.status != "matched" or resolution.match is None:
        reasons = [f"product identity is {resolution.status}: no market comparison"]
        reasons += resolution.reasons
        verdict = None
        if deal_obs is not None:  # the engine itself says NOT_ENOUGH_DATA for no product
            named = report.identity.name or report.identity.model
            deal = Deal(
                product=named.value if named else report.input.shop,
                price=deal_obs.amount,
                was_price=was_obs.amount if was_obs else None,
                shop=report.input.shop,
            )
            verdict = decide(deal, None, judge_day)
        return UrlCheckReport(
            status="not_enough_data",
            verdict=verdict,
            reasons=reasons,
            deal=deal_obs,
            was=was_obs,
            resolution=resolution,
            warnings=resolution.warnings,
        )

    match = resolution.match
    try:
        product = await source.market_data(match.product_ref, match.name, match.url)
    except SourceError as exc:
        return UrlCheckReport(
            status="unavailable",
            reasons=[str(exc)],
            deal=deal_obs,
            was=was_obs,
            resolution=resolution,
            warnings=resolution.warnings,
        )

    currency = resolution.identity.currency.value if resolution.identity.currency else None
    offers = [_offer_observation(o, market_code, currency) for o in product.offers]
    same_shop = next(
        (
            o
            for o in product.offers
            if o.in_stock and merchant_matches(o.merchant, report.input.host)
        ),
        None,
    )
    history = product.history
    market = MarketProvenance(
        canonical_id=match.canonical_id,
        product_url=match.url,
        market=market_code,
        currency=currency,
        retrieved_at=product.retrieved_at,
        history_days=len(history),
        history_window=f"{history[0].day}..{history[-1].day}" if history else None,
        offers=len(product.offers),
    )
    if deal_obs is None and same_shop is not None:
        deal_obs = _offer_observation(same_shop, market_code, currency).model_copy(
            update={"kind": "deal_price"}
        )
    if deal_obs is None:
        return UrlCheckReport(
            status="not_enough_data",
            reasons=[
                "no deal price: the shop page states none and idealo lists no offer from this shop"
            ],
            offers=offers,
            market=market,
            resolution=resolution,
            warnings=resolution.warnings,
        )

    deal = Deal(
        product=match.name,
        price=deal_obs.amount,
        was_price=was_obs.amount if was_obs else None,
        shop=same_shop.merchant if same_shop else report.input.shop,
    )
    verdict = decide(deal, product, judge_day)
    return UrlCheckReport(
        status="judged",
        verdict=verdict,
        deal=deal_obs,
        was=was_obs,
        offers=offers,
        market=market,
        resolution=resolution,
        warnings=resolution.warnings,
    )
