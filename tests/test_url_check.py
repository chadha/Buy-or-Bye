"""BOB-URL-001 M5: URL -> identity -> idealo market data -> unchanged verdict, with provenance.

Uses the live recordings in tests/fixtures/idealo/ (Philips XC2011/01, 27 Nov 2026). Every
price in the report says where it came from, when, from which seller and market, and whether
shipping is included. The verdict engine is called exactly as /api/check calls it.
"""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.models import Deal, ProductData
from app.sources import (
    SourceError,
    details_from_idealo,
    history_from_idealo,
    hits_from_idealo,
    offers_from_idealo,
)
from app.url_check import check_product_url
from app.verdict import decide

FIX = Path(__file__).parent / "fixtures" / "idealo"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


SEARCH, DETAILS = load("search_xc2011.json"), load("get_product_details_xc2011.json")
HISTORY, OFFERS = load("price_history_xc2011.json"), load("offers_xc2011.json")
PHILIPS = "https://www.home-appliances.philips/de/de/p/XC2011_01"
SHELL = "<html><title>VersuniB2CApp</title><app-root></app-root></html>"
TODAY = date(2026, 11, 28)
RETRIEVED = datetime(2026, 11, 27, 17, 0, tzinfo=UTC)


class FakeIdealo:
    name = "idealo"
    country = "DE"

    def __init__(self, offers=OFFERS, market_error=None):
        self.offers = offers
        self.market_error = market_error
        self.searches: list[str] = []
        self.market_calls: list[str] = []

    async def search(self, query, purpose="identity"):
        self.searches.append(query)
        return hits_from_idealo(SEARCH)

    async def product_details(self, product_ref, url, item_type=None):
        return details_from_idealo(DETAILS, RETRIEVED)

    async def market_data(self, product_ref, name, url):
        self.market_calls.append(product_ref)
        if self.market_error:
            raise self.market_error
        return ProductData(
            product_id=product_ref,
            name=name,
            url=url,
            source="idealo",
            history=history_from_idealo(HISTORY),
            offers=offers_from_idealo(self.offers),
            retrieved_at=RETRIEVED,
        )

    async def find(self, query):  # pragma: no cover - the URL flow must not search twice
        raise AssertionError("find() would run a second search")


def page(html):
    calls = {"n": 0}

    async def fetch(url):
        calls["n"] += 1
        return html

    return fetch, calls


# --- idealo mapping: explicit units, shipping, observation time -------------------------------


def test_history_tool_prices_are_strings_and_map_exactly():
    hist = history_from_idealo(HISTORY)
    assert len(hist) == 31
    assert (hist[0].day, hist[0].price) == (date(2026, 10, 28), Decimal("146.31"))
    assert min(p.price for p in hist) == Decimal("89.30")


@pytest.mark.parametrize(
    "raw,integer_cents,expected",
    [
        (999, False, Decimal("999.00")),  # a plain number is euros
        (999, True, Decimal("9.99")),  # get_product_details trend: integer cents, declared
        (14631, True, Decimal("146.31")),
        ("146,31 €", True, Decimal("146.31")),  # strings are always read as written
    ],
)
def test_integer_cents_are_explicit_never_guessed(raw, integer_cents, expected):
    point = {"dateTimeISO": "2026-11-01T22:59:59.999Z", "price": raw}
    hist = history_from_idealo({"priceTrend": {"history": [point]}}, integer_cents=integer_cents)
    assert hist[0].price == expected


def test_offers_carry_shipping_and_observation_time():
    offers = offers_from_idealo(OFFERS)
    by = {o.merchant: o for o in offers}
    philips = by["philips.de (Home-appliances)"]
    assert (philips.price, philips.shipping) == (Decimal("89.99"), Decimal("0.00"))
    assert by["proshop.de"].shipping == Decimal("4.99")
    assert philips.observed_at == datetime(2026, 11, 27, 16, 56, 47, 945000, tzinfo=UTC)


def test_offer_without_shipping_info_is_unknown_not_zero():
    raw = {"offers": [{"price": "10,00 €", "shop": {"name": "x.de"}}]}
    assert offers_from_idealo(raw)[0].shipping is None


# --- The URL check ----------------------------------------------------------------------------


async def test_philips_url_is_judged_with_same_shop_price_and_provenance():
    src = FakeIdealo()
    fetch, calls = page(SHELL)
    r = await check_product_url(PHILIPS, src, fetch=fetch, today=TODAY)
    assert r.status == "judged"
    assert calls["n"] == 1  # the page is read once for identity and prices
    assert len(src.searches) == 1 and len(src.market_calls) == 1  # M4 match reused
    d = r.deal
    assert (d.amount, d.currency, d.seller, d.source, d.market) == (
        Decimal("89.99"),
        "EUR",
        "philips.de (Home-appliances)",
        "idealo",
        "DE",
    )
    assert (d.shipping_cost, d.shipping_included) == (Decimal("0.00"), False)
    assert d.observed_at == datetime(2026, 11, 27, 16, 56, 47, 945000, tzinfo=UTC)
    assert d.source_url.startswith("https://www.idealo.de/relocator/")
    assert r.was is None
    m = r.market
    assert (m.canonical_id, m.market, m.currency, m.history_days) == ("203830913", "DE", "EUR", 31)
    assert m.history_window == "2026-10-28..2026-11-27"
    assert m.retrieved_at == RETRIEVED
    assert {o.seller for o in r.offers} >= {"kaufland.de", "proshop.de"}
    assert all(o.source == "idealo" and o.observed_at for o in r.offers)


async def test_verdict_is_exactly_what_the_engine_gives_for_the_same_numbers():
    src = FakeIdealo()
    fetch, _ = page(SHELL)
    r = await check_product_url(PHILIPS, src, fetch=fetch, today=TODAY)
    product = await FakeIdealo().market_data("p", "Philips XC2011/01", None)
    expected = decide(
        Deal(
            product="Philips XC2011/01", price=Decimal("89.99"), shop="philips.de (Home-appliances)"
        ),
        product,
        TODAY,
    )
    assert r.verdict.label == expected.label
    assert r.verdict.reasons == expected.reasons
    assert r.verdict.stats == expected.stats


async def test_page_price_and_was_price_win_and_shipping_is_unknown():
    html = (
        '<script type="application/ld+json">{"@type":"Product","name":"Philips XC2011/01",'
        '"brand":"Philips","mpn":"XC2011/01","category":"Staubsauger","offers":{'
        '"price":"99.99","priceCurrency":"EUR","priceSpecification":[{"priceType":'
        '"https://schema.org/StrikethroughPrice","price":"149.99"}]}}</script>'
    )
    fetch, calls = page(html)
    r = await check_product_url(PHILIPS, FakeIdealo(), fetch=fetch, today=TODAY)
    assert calls["n"] == 1
    assert (r.deal.amount, r.deal.source, r.deal.seller) == (
        Decimal("99.99"),
        "shop_page",
        "home-appliances.philips",
    )
    assert r.deal.shipping_included is None and r.deal.shipping_cost is None  # not stated
    assert r.deal.source_url == PHILIPS
    assert (r.was.amount, r.was.kind, r.was.source) == (
        Decimal("149.99"),
        "claimed_was_price",
        "shop_page",
    )
    assert r.verdict.deal.price == Decimal("99.99")
    assert r.verdict.deal.was_price == Decimal("149.99")


async def test_no_deal_price_means_no_verdict():
    offers = {"offers": [o for o in OFFERS["offers"] if "philips" not in o["shop"]["name"]]}
    fetch, _ = page(SHELL)
    r = await check_product_url(PHILIPS, FakeIdealo(offers=offers), fetch=fetch, today=TODAY)
    assert r.status == "not_enough_data" and r.verdict is None and r.deal is None
    assert any("no deal price" in x for x in r.reasons)
    assert r.market is not None  # market data is still shown, with provenance


async def test_unresolved_identity_with_a_price_gets_the_engines_not_enough_data():
    html = (
        '<script type="application/ld+json">{"@type":"Product","name":"Philips XC2011/03",'
        '"mpn":"XC2011/03","offers":{"price":"79.00","priceCurrency":"EUR"}}</script>'
    )
    fetch, _ = page(html)
    src = FakeIdealo()
    r = await check_product_url(PHILIPS, src, fetch=fetch, today=TODAY)
    assert r.resolution.status == "not_found"
    assert r.status == "not_enough_data"
    assert r.verdict is not None and r.verdict.label == "NOT_ENOUGH_DATA"  # label from decide()
    assert src.market_calls == []  # no market data for an unconfirmed product


async def test_market_data_failure_is_unavailable():
    fetch, _ = page(SHELL)
    src = FakeIdealo(market_error=SourceError("idealo daily limit reached"))
    r = await check_product_url(PHILIPS, src, fetch=fetch, today=TODAY)
    assert r.status == "unavailable" and r.verdict is None
    assert "daily limit" in r.reasons[0]


async def test_every_judged_number_has_provenance():
    fetch, _ = page(SHELL)
    r = await check_product_url(PHILIPS, FakeIdealo(), fetch=fetch, today=TODAY)
    body = r.model_dump(mode="json")
    assert body["deal"]["observed_at"] and body["deal"]["source_url"]
    assert body["market"]["retrieved_at"] and body["market"]["product_url"]
    for reason in body["verdict"]["reasons"]:
        for ev in reason["evidence"]:
            assert ev["source"] in ("idealo", "user")  # "user" = the deal, see report.deal


# --- API --------------------------------------------------------------------------------------


def test_check_endpoint(monkeypatch):
    from app import product_identity, url_check

    monkeypatch.setattr(main, "source", FakeIdealo())

    async def shell(url):
        return SHELL

    monkeypatch.setattr(product_identity, "fetch_page", shell)
    monkeypatch.setattr(url_check, "fetch_page", shell)
    r = TestClient(main.app).post("/api/v1/product-url/check", json={"url": PHILIPS})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema_version"] == "1" and body["status"] == "judged"
    assert body["deal"]["amount"] == 89.99 and isinstance(body["deal"]["amount"], float)
    assert body["verdict"]["label"] in ("BUY", "BYE", "WAIT")
    assert body["resolution"]["match"]["canonical_id"] == "203830913"


def test_check_endpoint_demo_mode_is_offline(monkeypatch):
    from app import product_identity, url_check
    from app.sources import DemoSource

    async def boom(url):
        raise AssertionError("demo mode must stay offline")

    monkeypatch.setattr(main, "source", DemoSource())
    monkeypatch.setattr(product_identity, "fetch_page", boom)
    monkeypatch.setattr(url_check, "fetch_page", boom)
    r = TestClient(main.app).post("/api/v1/product-url/check", json={"url": PHILIPS})
    assert r.status_code == 200 and r.json()["status"] == "unavailable"


def test_check_endpoint_invalid_url(monkeypatch):
    monkeypatch.setattr(main, "source", FakeIdealo())
    r = TestClient(main.app).post("/api/v1/product-url/check", json={"url": "https://10.0.0.1/x"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "not_public_host"


def test_old_check_endpoint_is_unchanged(monkeypatch):
    from app.sources import DemoSource

    monkeypatch.setattr(main, "source", DemoSource())
    r = TestClient(main.app).post(
        "/api/check", json={"product": "Nordwind ANC Headphones H7", "price": 209, "was_price": 279}
    )
    assert set(r.json()) == {"label", "headline", "reasons", "product", "deal", "stats"}
