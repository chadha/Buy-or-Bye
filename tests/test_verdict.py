"""The verdict engine: one test per rule, built from small hand-made histories."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.models import Deal, Label, Offer, PricePoint, ProductData
from app.verdict import compute_stats, decide

TODAY = date(2026, 11, 27)


def history(fn, days: int = 120) -> list[PricePoint]:
    """fn(days_ago) -> price; days_ago = 1 is yesterday."""
    return [PricePoint(day=TODAY - timedelta(days=a), price=fn(a)) for a in range(days, 0, -1)]


def product(fn, offers=(), days: int = 120) -> ProductData:
    return ProductData(
        product_id="p1",
        name="Test Product",
        history=history(fn, days),
        offers=[Offer(merchant=m, price=p) for m, p in offers],
        source="demo",
    )


def deal(price: float, was: float | None = None, shop: str | None = "Shop A") -> Deal:
    return Deal(product="Test Product", price=price, was_price=was, shop=shop)


def codes(v) -> set[str]:
    return {r.code for r in v.reasons}


def test_real_drop_at_90_day_low_is_buy():
    v = decide(deal(85), product(lambda a: 100), TODAY)
    assert v.label is Label.BUY
    assert {"real_saving", "at_90_day_low"} <= codes(v)


def test_inflated_claim_is_bye():
    v = decide(deal(97, was=299), product(lambda a: 100), TODAY)
    assert v.label is Label.BYE
    assert {"inflated_claim", "was_price_never_needed"} <= codes(v)


def test_pre_sale_hike_is_detected_and_not_counted_as_saving():
    # 100 for months, pushed to 130 in the last 3 weeks, "deal" at 98.
    v = decide(deal(98, was=199), product(lambda a: 130 if a <= 21 else 100), TODAY)
    assert v.label is Label.BYE
    assert "pre_sale_hike" in codes(v)
    assert v.stats["reference_price"] == 100  # compared against the pre-hike price
    assert v.stats["real_saving"] == pytest.approx(0.02)


def test_cheaper_at_another_shop_is_bye():
    v = decide(deal(85), product(lambda a: 100, offers=[("Shop A", 85), ("Shop B", 79)]), TODAY)
    assert v.label is Label.BYE
    assert "cheaper_elsewhere" in codes(v)


def test_own_shop_is_not_counted_as_elsewhere():
    v = decide(deal(85, shop="Shop B"), product(lambda a: 100, offers=[("shop b", 79)]), TODAY)
    assert "cheaper_elsewhere" not in codes(v)


def test_more_expensive_than_recently_is_bye():
    v = decide(deal(100), product(lambda a: 90 if a == 5 else 100), TODAY)
    assert v.label is Label.BYE
    assert {"cheaper_recently", "no_saving"} <= codes(v)


def test_small_saving_is_wait():
    v = decide(deal(96), product(lambda a: 90 if 50 <= a <= 60 else 100), TODAY)
    assert v.label is Label.WAIT
    assert "lower_within_90_days" in codes(v)


@pytest.mark.parametrize("days", [0, 5])
def test_too_little_history_is_not_enough_data(days):
    p = (
        product(lambda a: 100, days=days)
        if days
        else ProductData(product_id="p", name="x", history=[], offers=[], source="demo")
    )
    v = decide(deal(80), p, TODAY)
    assert v.label is Label.NOT_ENOUGH_DATA
    assert v.reasons == []


def test_unknown_product_is_not_enough_data_never_a_guess():
    v = decide(deal(80), None, TODAY)
    assert v.label is Label.NOT_ENOUGH_DATA
    assert "don't guess" in v.headline


def test_every_reason_carries_evidence_with_a_source():
    v = decide(
        deal(97, was=299),
        product(lambda a: 130 if a <= 21 else 100, offers=[("Shop B", 80)]),
        TODAY,
    )
    assert v.reasons
    for r in v.reasons:
        assert r.evidence, r.code
        assert all(e.source in {"demo", "idealo", "user"} for e in r.evidence)


def test_evidence_numbers_come_from_the_data_or_the_user():
    p = product(lambda a: 100 + (a % 7))
    d = deal(95, was=150)
    v = decide(d, p, TODAY)
    allowed = (
        {pt.price for pt in p.history}
        | {d.price, d.was_price}
        | {round(x, 2) for x in v.stats.values() if x is not None}
    )
    for r in v.reasons:
        for e in r.evidence:
            if isinstance(e.value, float):
                assert e.value in allowed, (r.code, e.metric, e.value)


def test_stats_windows_exclude_today():
    s = compute_stats(history(lambda a: 100.0), TODAY)
    assert s is not None
    assert s.window_30.endswith((TODAY - timedelta(days=1)).isoformat())
