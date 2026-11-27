"""Domain types. Prices are euros as floats rounded to cents at the edges; dates are ISO dates."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Label(StrEnum):
    BUY = "BUY"
    BYE = "BYE"
    WAIT = "WAIT"
    NOT_ENOUGH_DATA = "NOT_ENOUGH_DATA"


class PricePoint(BaseModel):
    day: date
    price: float  # lowest offer price on idealo that day


class Offer(BaseModel):
    merchant: str
    price: float  # total incl. shipping where known
    in_stock: bool = True
    url: str | None = None


class ProductData(BaseModel):
    product_id: str
    name: str
    url: str | None = None
    history: list[PricePoint]  # daily lowest price, oldest first
    offers: list[Offer]  # current offers
    source: Literal["idealo", "demo"]


class Deal(BaseModel):
    """What the shopper is looking at. Numbers here come from the user (typed or confirmed)."""

    product: str = Field(min_length=2, max_length=200)
    price: float = Field(gt=0, lt=100_000)
    was_price: float | None = Field(default=None, gt=0, lt=100_000)
    shop: str | None = Field(default=None, max_length=100)


class Evidence(BaseModel):
    """The exact numbers a reason relies on, so a judge can check them against the chart."""

    metric: str
    value: float | str
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
    stats: dict[str, float | None] = Field(default_factory=dict)
