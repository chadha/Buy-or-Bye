"""BOB-URL-001 M2: money is Decimal inside the app and a plain JSON number at the API edge."""

import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import main
from app.extract import Extracted, parse_text, to_number
from app.models import Deal, Evidence, Offer, PricePoint, ProductData, Verdict
from app.shop_page import PagePrices, prices_from_html
from app.sources import DemoSource, history_from_idealo, offers_from_idealo, parse_price
from app.verdict import Thresholds, compute_stats, decide

TODAY = date(2026, 11, 27)


# --- The Money type ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        (79.99, Decimal("79.99")),  # float input is read through its shortest repr, not binary
        ("79.99", Decimal("79.99")),
        (279, Decimal("279.00")),
        (0.1 + 0.2, Decimal("0.30")),  # quantised to cents
        ("19.995", Decimal("20.00")),  # half up, as prices are rounded in shops
        ("19.994", Decimal("19.99")),
    ],
)
def test_money_input_becomes_exact_cents(raw, expected):
    d = Deal(product="Kettle", price=raw)
    assert isinstance(d.price, Decimal)
    assert d.price == expected
    assert d.price.as_tuple().exponent == -2


@pytest.mark.parametrize("bad", ["NaN", "inf", float("nan"), float("inf"), True, "abc", "", None])
def test_money_rejects_non_numbers(bad):
    with pytest.raises(ValidationError):
        Deal(product="Kettle", price=bad)


def test_money_bounds_still_apply():
    with pytest.raises(ValidationError):
        Deal(product="Kettle", price="0")
    with pytest.raises(ValidationError):
        Deal(product="Kettle", price="100000")


def test_json_keeps_prices_as_numbers():
    d = Deal(product="Kettle", price="1049.00", was_price="1199.5")
    body = json.loads(d.model_dump_json())
    assert body["price"] == 1049.0 and isinstance(body["price"], float)
    assert body["was_price"] == 1199.5
    # Round trip: JSON number back into exact cents.
    assert Deal.model_validate_json(d.model_dump_json()) == d


def test_python_dump_keeps_decimal():
    assert Deal(product="Kettle", price="9.90").model_dump()["price"] == Decimal("9.90")


def test_every_money_field_is_decimal():
    values = [
        PricePoint(day=TODAY, price=1.5).price,
        Offer(merchant="A", price=2.25).price,
        Deal(product="Kettle", price=3).price,
        Extracted(price=4.1, was_price=5).price,
        Extracted(price=4.1, was_price=5).was_price,
        PagePrices(price=6, was_price=7.7).price,
        PagePrices(price=6, was_price=7.7).was_price,
        Evidence(metric="m", value=Decimal("1.5"), source="idealo").value,
    ]
    assert all(isinstance(v, Decimal) for v in values), values


def test_text_evidence_stays_text():
    assert Evidence(metric="m", value="2026-10-28", source="idealo").value == "2026-10-28"


# --- Parsers return Decimal ----------------------------------------------------------------------


def test_parsers_return_decimal():
    assert parse_price("1.059,00 €") == Decimal("1059.00")
    assert parse_price("£1,299.99") == Decimal("1299.99")
    assert parse_price(89.99) == Decimal("89.99")
    assert to_number("79,99") == Decimal("79.99")
    assert to_number("1.299") == Decimal("1299")
    x = parse_text("Kettle 42,50 € statt 60 €")
    assert (x.price, x.was_price) == (Decimal("42.50"), Decimal("60.00"))
    page = prices_from_html(
        '<script type="application/ld+json">{"@type":"Product","name":"K",'
        '"offers":{"price":"199.99","priceCurrency":"EUR"}}</script>'
    )
    assert page.price == Decimal("199.99")


def test_idealo_mapping_returns_decimal():
    hist = history_from_idealo(
        {
            "priceTrend": {
                "history": [
                    {"dateTimeISO": "2026-11-01T00:00:00Z", "price": "1.059,00 €"},
                    {"dateTimeISO": "2026-11-02T00:00:00Z", "price": 105900},
                ]
            }
        },
        integer_cents=True,  # M5: the unit is declared by the caller, never guessed
    )
    assert [p.price for p in hist] == [Decimal("1059.00"), Decimal("1059.00")]
    offers = offers_from_idealo({"offers": [{"price": "89,99 €", "shop": {"name": "philips.de"}}]})
    assert offers[0].price == Decimal("89.99")


# --- Verdict arithmetic is Decimal end to end -----------------------------------------------------


def _product(prices: list[str]) -> ProductData:
    hist = [
        PricePoint(day=TODAY - timedelta(days=len(prices) - i), price=p)
        for i, p in enumerate(prices)
    ]
    return ProductData(product_id="p", name="Kettle", history=hist, offers=[], source="demo")


def test_thresholds_are_decimal():
    t = Thresholds()
    for name in (
        "buy_min_saving",
        "near_low_tolerance",
        "above_low_tolerance",
        "cheaper_elsewhere",
        "fake_ratio",
        "fake_min_claim",
        "hike_ratio",
    ):
        assert isinstance(getattr(t, name), Decimal), name


def test_stats_and_evidence_are_decimal():
    product = _product(["100.10"] * 15 + ["100.11"] * 15)
    s = compute_stats(product.history, TODAY)
    assert s is not None and isinstance(s.median_30, Decimal)
    v = decide(Deal(product="Kettle", price="90.00", was_price="120.00"), product, TODAY)
    assert all(isinstance(x, Decimal) for x in v.stats.values() if x is not None)
    assert all(
        isinstance(e.value, Decimal)
        for r in v.reasons
        for e in r.evidence
        if not isinstance(e.value, str)
    )


def test_cent_exact_median_no_binary_drift():
    # Median of 100.10 and 100.11 is exactly 100.105 -> 100.11 (half up), never 100.10 from
    # binary 100.10499999...
    product = _product(["100.10"] * 15 + ["100.11"] * 15)
    v = decide(Deal(product="Kettle", price="99.00"), product, TODAY)
    assert v.stats["median_30"] == Decimal("100.11")


def test_verdict_json_is_numeric():
    product = _product(["100.00"] * 30)
    v = decide(Deal(product="Kettle", price="80.00", was_price="100.00"), product, TODAY)
    body = json.loads(v.model_dump_json())
    assert isinstance(body["stats"]["median_30"], float)
    assert isinstance(body["stats"]["real_saving"], float)
    assert isinstance(body["deal"]["price"], float)
    assert isinstance(body["product"]["history"][0]["price"], float)
    assert Verdict.model_validate_json(v.model_dump_json()).stats == v.stats


# --- API compatibility: same JSON shapes, numbers stay numbers -----------------------------------


def test_api_check_returns_numbers(monkeypatch):
    monkeypatch.setattr(main, "source", DemoSource())
    r = TestClient(main.app).post(
        "/api/check", json={"product": "Nordwind ANC Headphones H7", "price": 209, "was_price": 279}
    )
    body = r.json()
    assert r.status_code == 200
    assert body["deal"]["price"] == 209.0 and isinstance(body["deal"]["price"], float)
    assert isinstance(body["stats"]["median_30"], float)


def test_api_extract_returns_numbers(monkeypatch):
    monkeypatch.setattr(main, "source", DemoSource())
    r = TestClient(main.app).post("/api/extract/text", json={"text": "Kettle 42,50 € statt 60 €"})
    assert r.json()["price"] == 42.5 and r.json()["was_price"] == 60.0
