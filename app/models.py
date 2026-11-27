"""Domain types. Money is `Decimal` in exact cents inside the app (BOB-URL-001 decision D1)
and a plain JSON number at the API edge, so existing clients see the same JSON. Dates are ISO.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, Field, PlainSerializer

CENT = Decimal("0.01")


def to_decimal(value: Any) -> Any:
    """Read numbers exactly: a float goes through its shortest repr ("79.99"), never its binary
    expansion. Booleans and non-finite values are refused; other types reach pydantic as-is."""
    if isinstance(value, bool):
        raise ValueError("a price must be a number, not a boolean")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("a price must be a finite number")
        return Decimal(repr(value))
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        try:
            out = Decimal(value.strip())
        except InvalidOperation as exc:
            raise ValueError("not a number") from exc
        if not out.is_finite():
            raise ValueError("a price must be a finite number")
        return out
    return value


def cents(value: Decimal) -> Decimal:
    """Round to whole cents, half up (as shops round prices)."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _json_number(value: Decimal) -> float:
    # JSON has no decimal type: emit a number, as the API always did. Cent amounts below
    # 100 000 round-trip exactly through the shortest float repr. No arithmetic happens here.
    return float(value)


_AS_JSON_NUMBER = PlainSerializer(_json_number, return_type=float, when_used="json")
# A monetary amount in exact cents.
Money = Annotated[Decimal, BeforeValidator(to_decimal), AfterValidator(cents), _AS_JSON_NUMBER]
# A non-money decimal (ratios, statistics), also numeric in JSON.
Number = Annotated[Decimal, BeforeValidator(to_decimal), _AS_JSON_NUMBER]


class Label(StrEnum):
    BUY = "BUY"
    BYE = "BYE"
    WAIT = "WAIT"
    NOT_ENOUGH_DATA = "NOT_ENOUGH_DATA"


class PricePoint(BaseModel):
    day: date
    price: Money  # lowest offer price on idealo that day


class Offer(BaseModel):
    merchant: str
    price: Money  # the item price as the shop lists it, without shipping
    in_stock: bool = True
    url: str | None = None
    shipping: Money | None = None  # lowest shipping cost; None = unknown (never assumed 0)
    observed_at: datetime | None = None  # when the price source last saw this offer (UTC)


class ProductData(BaseModel):
    product_id: str
    name: str
    url: str | None = None
    history: list[PricePoint]  # daily lowest price, oldest first
    offers: list[Offer]  # current offers
    source: Literal["idealo", "demo"]
    retrieved_at: datetime | None = None  # when Buy or Bye fetched this data (UTC)


class PriceObservation(BaseModel):
    """One price with its provenance (CLAUDE.md: source, time, currency, market, seller)."""

    kind: Literal["deal_price", "claimed_was_price", "offer"]
    amount: Money
    currency: str
    seller: str | None = None
    market: str | None = None
    source: Literal["shop_page", "idealo"]
    source_url: str | None = None
    observed_at: datetime | None = None  # UTC
    shipping_cost: Money | None = None  # None = not stated by the source
    shipping_included: bool | None = None  # None = unknown


class Deal(BaseModel):
    """What the shopper is looking at. Numbers here come from the user (typed or confirmed)."""

    product: str = Field(min_length=2, max_length=200)
    price: Money = Field(gt=0, lt=100_000)
    was_price: Money | None = Field(default=None, gt=0, lt=100_000)
    shop: str | None = Field(default=None, max_length=100)


class Evidence(BaseModel):
    """The exact numbers a reason relies on, so a judge can check them against the chart."""

    metric: str
    value: Number | str
    window: str | None = None  # e.g. "2026-10-25..2026-11-23"
    source: Literal["idealo", "demo", "user"]


class Reason(BaseModel):
    code: str
    text: str
    polarity: Literal["for", "against", "neutral"]
    evidence: list[Evidence]


class Verdict(BaseModel):
    label: Label
    headline: str
    reasons: list[Reason]
    product: ProductData | None = None
    deal: Deal
    stats: dict[str, Number | None] = Field(default_factory=dict)
