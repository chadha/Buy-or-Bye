"""The verdict engine. Pure functions only: no network, no LLM, no clock (today is passed in).

Every label is decided here, from idealo price history plus the deal's own numbers.
Every reason carries the numbers it used, so the UI and a judge can check them.
All money and ratios are Decimal (BOB-URL-001 D1): no float arithmetic on prices.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from .models import (
    Deal,
    Evidence,
    Label,
    Offer,
    PricePoint,
    ProductData,
    Reason,
    Verdict,
    cents,
)

RATIO_PLACES = Decimal("0.0001")


@dataclass(frozen=True)
class Thresholds:
    min_points_30d: int = 10  # fewer daily prices than this in 30 days -> not enough data
    buy_min_saving: Decimal = Decimal("0.10")  # >= 10% below the typical (median) 30-day price
    near_low_tolerance: Decimal = Decimal("0.03")  # within 3% of the 90-day low = "at the low"
    above_low_tolerance: Decimal = Decimal("0.03")  # > 3% above the 30-day low: cheaper recently
    cheaper_elsewhere: Decimal = Decimal("0.05")  # another shop >= 5% cheaper right now
    fake_ratio: Decimal = Decimal("3.0")  # claimed discount >= 3x the real one ...
    fake_min_claim: Decimal = Decimal("0.20")  # ... and the claim is at least 20%
    claim_saving_floor: Decimal = Decimal("0.01")  # real saving counted as >= 1% in that ratio
    hike_ratio: Decimal = Decimal("1.10")  # pre-sale max >= 10% above the earlier typical price
    hike_max_saving: Decimal = Decimal("0.05")  # after a hike, < 5% real saving is a BYE
    was_never_needed_margin: Decimal = Decimal("1.05")  # "was" > 5% above the 90-day max


DEFAULT = Thresholds()


@dataclass(frozen=True)
class Stats:
    low_30: Decimal
    median_30: Decimal
    low_90: Decimal
    max_90: Decimal
    baseline_before_sale: Decimal | None  # typical price 22..60 days ago
    peak_last_21: Decimal | None  # highest daily low in the last 21 days
    points_30: int
    window_30: str
    window_90: str
    long_days: int = 90  # days the long window really covers (idealo history is 30 days)
    baseline_days: str = "22–60"


def _window(points: list[PricePoint], today: date, start_days: int, end_days: int) -> list[Decimal]:
    start, end = today - timedelta(days=start_days), today - timedelta(days=end_days)
    return [p.price for p in points if start <= p.day <= end]


def compute_stats(history: list[PricePoint], today: date) -> Stats | None:
    last_30 = _window(history, today, 30, 1)
    last_90 = _window(history, today, 90, 1)
    if not last_30 or not last_90:
        return None
    before = _window(history, today, 60, 22)
    recent = _window(history, today, 21, 1)

    def fmt(a: int, b: int) -> str:
        return (
            f"{(today - timedelta(days=a)).isoformat()}..{(today - timedelta(days=b)).isoformat()}"
        )

    first = min(p.day for p in history)
    long_days = max(1, min(90, (today - first).days))
    return Stats(
        long_days=long_days,
        baseline_days=f"22–{min(60, long_days)}",
        low_30=min(last_30),
        median_30=median(last_30),
        low_90=min(last_90),
        max_90=max(last_90),
        baseline_before_sale=median(before) if len(before) >= 7 else None,
        peak_last_21=max(recent) if recent else None,
        points_30=len(last_30),
        window_30=fmt(30, 1),
        window_90=fmt(long_days, 1),
    )


def _pct(x: Decimal) -> str:
    # Whole percent, half up like money (an exact 37.5% shows as 38%).
    return f"{(x * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)}%"


def _eur(x: Decimal) -> str:
    return f"€{cents(x):,.2f}"


def _cheapest_other(offers: list[Offer], shop: str | None) -> Offer | None:
    others = [o for o in offers if o.in_stock and (not shop or o.merchant.lower() != shop.lower())]
    return min(others, key=lambda o: o.price, default=None)


def decide(
    deal: Deal, product: ProductData | None, today: date, t: Thresholds = DEFAULT
) -> Verdict:
    if product is None:
        return Verdict(
            label=Label.NOT_ENOUGH_DATA,
            deal=deal,
            reasons=[],
            headline="We couldn't find this product on idealo, so no verdict. We don't guess.",
        )
    src = product.source
    s = compute_stats(product.history, today)
    if s is None or s.points_30 < t.min_points_30d:
        return Verdict(
            label=Label.NOT_ENOUGH_DATA,
            deal=deal,
            product=product,
            reasons=[],
            headline="Too little recent price history to judge this deal fairly.",
        )

    price = deal.price
    # A price pushed up before the sale also lifts the 30-day median, which would make the
    # "saving" look bigger. When that happens, compare against the price before the hike.
    hike = (
        s.baseline_before_sale is not None
        and s.peak_last_21 is not None
        and s.peak_last_21 >= s.baseline_before_sale * t.hike_ratio
    )
    ref = s.median_30
    if hike and s.baseline_before_sale is not None:
        ref = min(ref, s.baseline_before_sale)
    ref_label = (
        "the typical price before the pre-sale increase"
        if ref != s.median_30
        else "the typical price of the last 30 days"
    )
    real_saving = (ref - price) / ref
    vs_low30 = (price - s.low_30) / s.low_30  # > 0: it was cheaper recently
    reasons: list[Reason] = []
    ev_typ = (
        Evidence(
            metric=f"median daily lowest price, {s.baseline_days} days ago",
            value=cents(ref),
            source=src,
        )
        if ref != s.median_30
        else Evidence(
            metric="median daily lowest price, 30 days",
            value=cents(s.median_30),
            window=s.window_30,
            source=src,
        )
    )
    ev_low30 = Evidence(
        metric="lowest price, 30 days", value=cents(s.low_30), window=s.window_30, source=src
    )
    ev_low90 = Evidence(
        metric=f"lowest price, {s.long_days} days",
        value=cents(s.low_90),
        window=s.window_90,
        source=src,
    )
    ev_price = Evidence(metric="deal price", value=price, source="user")

    # 1. Real saving against the typical recent price
    if real_saving > 0:
        reasons.append(
            Reason(
                code="real_saving",
                polarity="for" if real_saving >= t.buy_min_saving else "neutral",
                text=f"Real saving: {_pct(real_saving)} below {ref_label} ({_eur(ref)}).",
                evidence=[ev_price, ev_typ],
            )
        )
    else:
        reasons.append(
            Reason(
                code="no_saving",
                polarity="against",
                text=f"No real saving: {ref_label} was {_eur(ref)}, and this deal "
                f"is {_eur(price)}.",
                evidence=[ev_price, ev_typ],
            )
        )

    # 2. Cheaper in the last 30 days
    above_recent_low = vs_low30 > t.above_low_tolerance
    if above_recent_low:
        reasons.append(
            Reason(
                code="cheaper_recently",
                polarity="against",
                text=f"It was cheaper recently: {_eur(s.low_30)} within the last "
                f"30 days, {_pct(vs_low30)} less than this deal.",
                evidence=[ev_price, ev_low30],
            )
        )
    at_90_low = price <= s.low_90 * (1 + t.near_low_tolerance)
    if at_90_low:
        reasons.append(
            Reason(
                code="at_90_day_low",
                polarity="for",
                text=f"At or near the lowest price of the last {s.long_days} days "
                f"({_eur(s.low_90)}).",
                evidence=[ev_price, ev_low90],
            )
        )
    elif not above_recent_low:
        reasons.append(
            Reason(
                code="lower_within_90_days",
                polarity="neutral",
                text=f"It has been cheaper: {_eur(s.low_90)} within the last {s.long_days} days.",
                evidence=[ev_price, ev_low90],
            )
        )

    # 3. The claimed discount vs the real one
    fake = False
    if deal.was_price and deal.was_price > price:
        claimed = (deal.was_price - price) / deal.was_price
        ev_was = Evidence(metric="claimed 'was' price", value=deal.was_price, source="user")
        ev_max = Evidence(
            metric=f"highest daily lowest price, {s.long_days} days",
            value=cents(s.max_90),
            window=s.window_90,
            source=src,
        )
        if claimed >= t.fake_min_claim and claimed >= t.fake_ratio * max(
            real_saving, t.claim_saving_floor
        ):
            fake = True
            reasons.append(
                Reason(
                    code="inflated_claim",
                    polarity="against",
                    text=f"Claimed −{_pct(claimed)}, but the real saving is "
                    f"{_pct(max(real_saving, Decimal(0)))} against {ref_label}.",
                    evidence=[ev_was, ev_price, ev_typ],
                )
            )
        if deal.was_price > s.max_90 * t.was_never_needed_margin:
            reasons.append(
                Reason(
                    code="was_price_never_needed",
                    polarity="against",
                    text=f"Nobody needed to pay {_eur(deal.was_price)}: the "
                    f"lowest idealo price never went above {_eur(s.max_90)} "
                    f"in {s.long_days} days.",
                    evidence=[ev_was, ev_max],
                )
            )

    # 4. Price pushed up before the sale
    if hike and s.baseline_before_sale is not None and s.peak_last_21 is not None:
        reasons.append(
            Reason(
                code="pre_sale_hike",
                polarity="against",
                text=f"The price was pushed up before the sale: from about "
                f"{_eur(s.baseline_before_sale)} to {_eur(s.peak_last_21)} "
                f"in the last three weeks.",
                evidence=[
                    Evidence(
                        metric=f"typical price {s.baseline_days} days ago",
                        value=cents(s.baseline_before_sale),
                        source=src,
                    ),
                    Evidence(
                        metric="highest daily lowest price, 21 days",
                        value=cents(s.peak_last_21),
                        source=src,
                    ),
                ],
            )
        )

    # 5. Cheaper at another shop right now
    other = _cheapest_other(product.offers, deal.shop)
    cheaper_now = other is not None and other.price <= price * (1 - t.cheaper_elsewhere)
    if cheaper_now and other is not None:
        reasons.append(
            Reason(
                code="cheaper_elsewhere",
                polarity="against",
                text=f"Cheaper right now at {other.merchant}: {_eur(other.price)}.",
                evidence=[
                    Evidence(
                        metric=f"current offer at {other.merchant}", value=other.price, source=src
                    )
                ],
            )
        )

    # Decide. Order matters: any clear red flag wins over a nice-looking saving.
    if (
        fake
        or cheaper_now
        or (hike and real_saving < t.hike_max_saving)
        or real_saving <= 0
        or (above_recent_low and not at_90_low)
    ):
        label = Label.BYE
        headline = "Bye: this isn't the deal it claims to be."
    elif real_saving >= t.buy_min_saving and at_90_low:
        label = Label.BUY
        headline = f"Buy: a real {_pct(real_saving)} saving, at the {s.long_days}-day low."
    else:
        label = Label.WAIT
        headline = "Wait: a fair price, but not a special one. Set a price alert."

    return Verdict(
        label=label,
        headline=headline,
        reasons=reasons,
        product=product,
        deal=deal,
        stats={
            "median_30": cents(s.median_30),
            "low_30": cents(s.low_30),
            "low_90": cents(s.low_90),
            "max_90": cents(s.max_90),
            "reference_price": cents(ref),
            "real_saving": real_saving.quantize(RATIO_PLACES, rounding=ROUND_HALF_UP),
        },
    )
