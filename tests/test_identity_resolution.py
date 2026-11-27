"""BOB-URL-001 M4: resolve a URL identity to one idealo product and verify its fields.

Search and details responses are the live recordings in tests/fixtures/idealo/. A field is
"verified" only when two independent sources agree; idealo alone leaves it "unverified";
disagreement is "contradicted". Nothing is inferred beyond what a source states.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.identity_resolution import resolve_identity
from app.product_identity import FieldValue, ProductIdentity, identify_product_url
from app.shop_page import merchant_matches, prices_for_link
from app.sources import (
    ProductDetails,
    SearchHit,
    SourceError,
    details_from_idealo,
    hits_from_idealo,
)

FIX = Path(__file__).parent / "fixtures" / "idealo"
SEARCH = json.loads((FIX / "search_xc2011.json").read_text(encoding="utf-8"))
DETAILS = json.loads((FIX / "get_product_details_xc2011.json").read_text(encoding="utf-8"))
PHILIPS = "https://www.home-appliances.philips/de/de/p/XC2011_01"
IDEALO = "https://www.idealo.de/preisvergleich/OffersOfProduct"
SHELL = "<html><title>VersuniB2CApp</title><app-root></app-root></html>"


async def shell(url: str) -> str:
    return SHELL


class FakeIdealo:
    name = "idealo"

    def __init__(self, hits=None, details=None, search_error=None, country="DE"):
        self.country = country
        self.hits = hits if hits is not None else hits_from_idealo(SEARCH)
        self.details = details
        self.search_error = search_error
        self.searches: list[tuple[str, str]] = []
        self.detail_calls: list[str] = []

    async def search(self, query, purpose="identity"):
        self.searches.append((query, purpose))
        if self.search_error:
            raise self.search_error
        return self.hits

    async def product_details(self, product_ref, url, item_type=None):
        self.detail_calls.append(product_ref)
        if self.details is not None:
            return self.details
        from datetime import UTC, datetime

        return details_from_idealo(DETAILS, datetime(2026, 11, 27, tzinfo=UTC))

    async def find(self, query):  # pragma: no cover - not used here
        return None


async def resolve(url=PHILIPS, html=SHELL, source=None):
    async def fetch(u):
        return html

    report = await identify_product_url(url, fetch=fetch)
    return await resolve_identity(report, source or FakeIdealo())


def hit(name, ref="r", url=None, item_type="PRODUCT", price="89,30 €"):
    return SearchHit.model_validate(
        {
            "product_ref": ref,
            "name": name,
            "url": url or f"{IDEALO}/{abs(hash(name)) % 10**9}_-x.html",
            "item_type": item_type,
            "price": price,
        }
    )


# --- Shop matching: idealo merchant names ---------------------------------------------------------


@pytest.mark.parametrize(
    "merchant,host,ok",
    [
        ("philips.de (Home-appliances)", "www.home-appliances.philips", True),
        ("philips.de (Home-appliances)", "home-appliances.philips", True),
        ("philips.de (Personal-care)", "www.home-appliances.philips", False),  # other Philips shop
        ("philips.de", "www.home-appliances.philips", True),  # brand TLD owned by the merchant
        ("mediamarkt.de", "www.mediamarkt.de", True),
        ("MediaMarkt", "www.mediamarkt.de", True),
        ("amazon.de", "www.amazon.com", False),  # same name, other market: not the same shop
        ("kaufland.de", "www.home-appliances.philips", False),
        ("philips.de (Home-appliances)", "www.mediamarkt.de", False),
    ],
)
def test_merchant_matches_idealo_names(merchant, host, ok):
    assert merchant_matches(merchant, host) is ok


async def test_link_prefill_now_finds_the_same_shop_offer():
    from app.models import Offer, ProductData

    class Src:
        name = "idealo"

        async def find(self, q):
            return ProductData(
                product_id="203830913",
                name="Philips XC2011/01",
                history=[],
                offers=[
                    Offer(merchant="philips.de (Home-appliances)", price="89.99"),
                    Offer(merchant="kaufland.de", price="95.00"),
                ],
                source="idealo",
            )

    x = await prices_for_link(PHILIPS, Src(), fetch=shell)
    assert (x.product, x.price, x.shop) == (
        "Philips XC2011/01",
        Decimal("89.99"),
        "home-appliances.philips",
    )
    assert "idealo" in x.note


# --- Search hits from the recorded response -------------------------------------------------------


def test_hits_from_recorded_search():
    hits = hits_from_idealo(SEARCH)
    assert [h.name for h in hits][:1] == ["Philips XC2011/01"]
    first = hits[0]
    assert (first.canonical_id, first.item_type, first.price, first.currency) == (
        "203830913",
        "PRODUCT",
        Decimal("89.30"),
        "EUR",
    )
    assert hits[1].canonical_id is None  # a SINGLE_OFFER relocator link has no product ID


@pytest.mark.parametrize("raw", [None, {}, {"results": "x"}, {"results": [{"name": "no ref"}]}])
def test_hits_from_unusable_search(raw):
    assert hits_from_idealo(raw) == []


# --- Matching ---------------------------------------------------------------------------------


async def test_philips_url_resolves_to_one_idealo_product_with_high_confidence():
    src = FakeIdealo()
    r = await resolve(source=src)
    assert r.status == "matched" and r.confidence == "high"
    assert (r.match.canonical_id, r.match.name) == ("203830913", "Philips XC2011/01")
    assert src.searches == [("XC2011/01", "identity")]
    rejected = {c.name: c.reason for c in r.rejected}
    assert (
        "single shop listing"
        in rejected["Ersatzbürste für Philips 3000 Series Akku-Staubsauger, schwarz"]
    )
    assert "model" in rejected["Philips XD1111/10"]


async def test_fields_are_verified_only_when_two_sources_agree():
    r = await resolve()
    ident = r.identity
    # Model: URL slug and idealo product name agree -> verified.
    assert (ident.model.value, ident.model.status, ident.model.corroborated_by) == (
        "XC2011/01",
        "verified",
        "idealo",
    )
    # Brand: stated by idealo's product name, and the shop's own domain (.philips) agrees.
    assert (
        ident.brand.value,
        ident.brand.source,
        ident.brand.status,
        ident.brand.corroborated_by,
    ) == ("Philips", "idealo", "verified", "url_host")
    # Market: URL path DE and the idealo DE marketplace agree.
    assert (ident.market.status, ident.market.corroborated_by) == ("verified", "idealo")
    # Currency: observed in idealo's price ("89,30 €"), one source only.
    assert (ident.currency.value, ident.currency.source, ident.currency.status) == (
        "EUR",
        "idealo",
        "unverified",
    )
    # Category: idealo details product type, one source only.
    assert (ident.category.value, ident.category.source, ident.category.status) == (
        "Stielstaubsauger",
        "idealo",
        "unverified",
    )
    # Family: no approved source states it -> stays unknown, and the report says so.
    assert ident.family is None
    assert "family" in r.unknown


async def test_details_are_fetched_only_when_needed():
    src = FakeIdealo()
    await resolve(source=src)
    assert len(src.detail_calls) == 1  # category was unknown
    src2 = FakeIdealo()
    html = (
        '<script type="application/ld+json">{"@type":"Product","name":"Philips XC2011/01",'
        '"brand":"Philips","mpn":"XC2011/01","category":"Staubsauger"}</script>'
    )
    r = await resolve(html=html, source=src2)
    assert src2.detail_calls == []  # category already known from the page
    assert r.identity.category.value == "Staubsauger"


async def test_wrong_variant_is_rejected_not_matched():
    src = FakeIdealo(
        hits=[
            hit(
                "Philips XC2011/03",
                url="https://www.idealo.de/preisvergleich/OffersOfProduct/111_-x.html",
            )
        ]
    )
    r = await resolve(source=src)
    assert r.status == "not_found" and r.match is None
    assert "variant" in r.rejected[0].reason


async def test_model_without_variant_is_medium_confidence():
    src = FakeIdealo(
        hits=[
            hit(
                "Philips XC2011",
                url="https://www.idealo.de/preisvergleich/OffersOfProduct/222_-x.html",
            )
        ]
    )
    r = await resolve(source=src)
    assert (r.status, r.confidence) == ("matched", "medium")
    assert r.identity.model.status == "unverified"  # idealo does not state the variant
    assert any("variant" in reason for reason in r.reasons)


async def test_two_different_exact_products_are_ambiguous():
    src = FakeIdealo(
        hits=[
            hit(
                "Philips XC2011/01",
                ref="a",
                url="https://www.idealo.de/preisvergleich/OffersOfProduct/1_-a.html",
            ),
            hit(
                "Philips XC2011/01 blau",
                ref="b",
                url="https://www.idealo.de/preisvergleich/OffersOfProduct/2_-b.html",
            ),
        ]
    )
    r = await resolve(source=src)
    assert r.status == "ambiguous" and r.match is None
    assert src.detail_calls == []


async def test_page_brand_must_agree():
    html = (
        '<script type="application/ld+json">{"@type":"Product","name":"X","brand":"Bosch",'
        '"mpn":"XC2011/01"}</script>'
    )
    r = await resolve(html=html)
    assert r.status == "not_found"
    assert any("brand" in c.reason for c in r.rejected)


async def test_market_mismatch_is_contradicted_and_uncertain():
    r = await resolve(url="https://www.home-appliances.philips/at/at/p/XC2011_01")
    assert r.status == "uncertain"
    assert r.identity.market.status == "contradicted"
    assert any("market" in w for w in r.warnings)


async def test_page_currency_disagreeing_with_idealo_is_contradicted():
    html = (
        '<script type="application/ld+json">{"@type":"Product","name":"Philips XC2011/01",'
        '"mpn":"XC2011/01","category":"x","offers":{"price":"79","priceCurrency":"GBP"}}'
        "</script>"
    )
    r = await resolve(html=html)
    assert r.identity.currency.status == "contradicted"


async def test_name_only_match_is_low_confidence_and_uncertain():
    html = (
        '<script type="application/ld+json">{"@type":"Product",'
        '"name":"Nordwind ANC Headphones H7","category":"Kopfhörer"}</script>'
    )
    src = FakeIdealo(
        hits=[
            hit(
                "Nordwind ANC Headphones H7",
                url="https://www.idealo.de/preisvergleich/OffersOfProduct/333_-n.html",
            )
        ]
    )
    r = await resolve(
        url="https://www.shop.example/p/nordwind-anc-headphones", html=html, source=src
    )
    assert (r.status, r.confidence) == ("uncertain", "low")
    assert src.searches[0][0] == "Nordwind ANC Headphones H7"


async def test_nothing_to_search_for():
    src = FakeIdealo()
    r = await resolve(url="https://www.shop.example/p/kettle", source=src)
    assert r.status == "not_found" and src.searches == []
    assert r.reasons


async def test_search_failure_is_unavailable_with_reason():
    src = FakeIdealo(
        search_error=SourceError(
            "product details skipped: the last 150 idealo calls today are reserved for "
            "price checks."
        )
    )
    r = await resolve(source=src)
    assert r.status == "unavailable" and r.match is None
    assert "reserved" in r.reasons[0]
    assert r.identity.model.status == "unverified"  # nothing verified without idealo


async def test_details_failure_keeps_the_match_with_a_partial_identity():
    src = FakeIdealo(details=ProductDetails(status="unavailable", error="idealo is not answering"))
    r = await resolve(source=src)
    assert r.status == "matched"
    assert r.identity.category is None and "category" in r.unknown
    assert any("not answering" in w for w in r.warnings)


async def test_untrusted_hit_names_are_bounded():
    src = FakeIdealo(
        hits=[
            hit(
                "Philips XC2011/01 " + "x" * 500,
                url="https://www.idealo.de/preisvergleich/OffersOfProduct/9_-x.html",
            )
        ]
    )
    r = await resolve(source=src)
    assert len(r.match.name) <= 200


# --- API --------------------------------------------------------------------------------------


def test_resolve_endpoint(monkeypatch):
    from app import product_identity

    monkeypatch.setattr(main, "source", FakeIdealo())
    monkeypatch.setattr(product_identity, "fetch_page", shell)
    r = TestClient(main.app).post("/api/v1/product-url/resolve", json={"url": PHILIPS})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema_version"] == "1"
    assert body["status"] == "matched" and body["confidence"] == "high"
    assert body["match"]["canonical_id"] == "203830913"
    assert body["identity"]["brand"]["value"] == "Philips"
    assert body["identification"]["input"]["url"] == PHILIPS


def test_resolve_endpoint_demo_mode_is_offline(monkeypatch):
    from app import product_identity
    from app.sources import DemoSource

    async def boom(url):
        raise AssertionError("demo mode must stay offline")

    monkeypatch.setattr(main, "source", DemoSource())
    monkeypatch.setattr(product_identity, "fetch_page", boom)
    r = TestClient(main.app).post("/api/v1/product-url/resolve", json={"url": PHILIPS})
    assert r.status_code == 200 and r.json()["status"] == "unavailable"


def test_resolve_endpoint_invalid_url(monkeypatch):
    monkeypatch.setattr(main, "source", FakeIdealo())
    r = TestClient(main.app).post("/api/v1/product-url/resolve", json={"url": "file:///etc/passwd"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "not_http"


def test_identify_endpoint_still_answers_the_same_fields(monkeypatch):
    from app import product_identity

    monkeypatch.setattr(main, "source", FakeIdealo())
    monkeypatch.setattr(product_identity, "fetch_page", shell)
    body = TestClient(main.app).post("/api/v1/product-url/identify", json={"url": PHILIPS}).json()
    assert body["identity"]["model"]["status"] == "unverified"  # identify never verifies


def test_fieldvalue_corroboration_is_optional():
    assert FieldValue(value="x", source="meta").corroborated_by is None
    assert ProductIdentity().model_dump()["brand"] is None
