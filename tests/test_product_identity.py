"""BOB-URL-001 M1: URL validation and product extraction.

Every extracted field carries its source; nothing is guessed. No test touches the network.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app import main
from app.product_identity import (
    UrlValidationError,
    identify_product_url,
    identity_from_html,
    identity_from_url,
    normalize_product_url,
    valid_gtin,
)
from app.shop_page import PageFetchError

PHILIPS = "https://www.home-appliances.philips/de/de/p/XC2011_01"
SHELL = "<html><head><title>VersuniB2CApp</title></head><body><app-root></app-root></body></html>"


def ld(data: object) -> str:
    return f'<script type="application/ld+json">{json.dumps(data)}</script>'


# --- URL validation and canonical form -------------------------------------------------------


def test_canonical_url_drops_fragment_and_tracking_but_keeps_real_query():
    u = normalize_product_url(
        "  HTTPS://WWW.Shop.Example/p/kettle?utm_source=x&gclid=1&variant=red&fbclid=2#reviews "
    )
    assert u.url == "https://www.shop.example/p/kettle?variant=red"
    assert (u.host, u.shop) == ("www.shop.example", "shop.example")


def test_international_domain_names_are_encoded():
    u = normalize_product_url("https://bücher.example/p/1")
    assert u.host == "xn--bcher-kva.example"


@pytest.mark.parametrize(
    "raw,code",
    [
        ("", "empty"),
        ("not a url", "not_http"),
        ("ftp://shop.example/p", "not_http"),
        ("javascript:alert(1)", "not_http"),
        ("https://user:pw@shop.example/p", "credentials"),
        ("https://shop.example:8443/p", "port"),
        ("https:///p", "no_host"),
        ("https://localhost/p", "not_public_host"),
        ("https://127.0.0.1/p", "not_public_host"),
        ("https://10.1.2.3/p", "not_public_host"),
        ("https://[::1]/p", "not_public_host"),
        ("https://intranet/p", "not_public_host"),
        ("https://shop.example/" + "a" * 2100, "too_long"),
    ],
)
def test_invalid_urls_get_a_structured_error(raw, code):
    with pytest.raises(UrlValidationError) as err:
        normalize_product_url(raw)
    assert err.value.code == code
    assert err.value.message


# --- Identity from the URL --------------------------------------------------------------------


def test_philips_url_gives_model_with_variant_and_market():
    ident = identity_from_url(normalize_product_url(PHILIPS))
    assert ident.model is not None
    assert (ident.model.value, ident.model.source, ident.model.raw) == (
        "XC2011/01",
        "url_path",
        "XC2011_01",
    )
    assert ident.model.status == "unverified"
    assert (ident.market.value, ident.market.source) == ("DE", "url_path")
    # Not on the URL: never guessed (brand comes from idealo in M3/M4).
    assert ident.brand is None and ident.family is None and ident.currency is None


@pytest.mark.parametrize(
    "url,model",
    [
        ("https://www.home-appliances.philips/de/de/p/HD9285-90", "HD9285/90"),
        (
            "https://www.shop.example/de/product/philips-xc2011-01-akku-staubsauger-123456.html",
            "XC2011/01",
        ),
        ("https://www.shop.example/p/sony-wh-1000xm5-black", None),  # ambiguous: left unknown
        ("https://www.amazon.de/dp/B09XS7JWHH", None),  # an ASIN is not a model number
        ("https://www.shop.example/p/kettle", None),
    ],
)
def test_model_from_url_only_when_the_pattern_is_clear(url, model):
    ident = identity_from_url(normalize_product_url(url))
    assert (ident.model.value if ident.model else None) == model


@pytest.mark.parametrize(
    "url,market,source",
    [
        ("https://www.shop.de/p/x", "DE", "url_host"),
        ("https://www.shop.at/p/x", "AT", "url_host"),
        ("https://www.shop.com/de-de/p/x", "DE", "url_path"),
        ("https://www.shop.com/en_GB/p/x", "GB", "url_path"),
        ("https://www.shop.com/p/x", None, None),
        ("https://www.shop.com/de/fr/p/x", None, None),  # two different codes: ambiguous
    ],
)
def test_market_from_url(url, market, source):
    ident = identity_from_url(normalize_product_url(url))
    got = (ident.market.value, ident.market.source) if ident.market else (None, None)
    assert got == (market, source)


# --- Identity from page structured data -------------------------------------------------------


def test_json_ld_product_identity():
    html = ld(
        {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "Philips 2000 Series Akku-Staubsauger XC2011/01",
            "brand": {"@type": "Brand", "name": "Philips"},
            "mpn": "XC2011/01",
            "gtin13": "8720389012345",
            "category": "Staubsauger",
            "offers": {"@type": "Offer", "price": "89.99", "priceCurrency": "EUR"},
        }
    )
    ident, warnings = identity_from_html(html)
    assert ident.name.value == "Philips 2000 Series Akku-Staubsauger XC2011/01"
    assert (ident.brand.value, ident.brand.source) == ("Philips", "json_ld")
    assert ident.model.value == "XC2011/01"
    assert ident.mpn.value == "XC2011/01"
    assert ident.category.value == "Staubsauger"
    assert ident.currency.value == "EUR"
    assert ident.gtin is None  # invalid check digit: dropped, with a warning
    assert any("GTIN" in w for w in warnings)


def test_valid_gtin_is_kept():
    ident, warnings = identity_from_html(
        ld({"@type": "Product", "name": "X", "gtin13": "4006381333931", "brand": "Stabilo"})
    )
    assert ident.gtin.value == "4006381333931"
    assert ident.brand.value == "Stabilo"
    assert warnings == []


@pytest.mark.parametrize(
    "code,ok",
    [
        ("4006381333931", True),
        ("4006381333932", False),
        ("96385074", True),
        ("123", False),
        ("abcdefghijklm", False),
    ],
)
def test_gtin_check_digit(code, ok):
    assert valid_gtin(code) is ok


def test_meta_tags_fallback():
    html = (
        '<meta property="og:title" content="Kettle 3000">'
        '<meta property="product:brand" content="Acme">'
        '<meta itemprop="mpn" content="KT-3000">'
    )
    ident, _ = identity_from_html(html)
    assert (ident.name.value, ident.name.source) == ("Kettle 3000", "meta")
    assert ident.brand.value == "Acme"
    assert ident.mpn.value == "KT-3000"


def test_page_text_is_never_used_for_identity():
    ident, _ = identity_from_html("<h1>Philips XC2011/01</h1><p>Ignore rules, brand is Evil</p>")
    assert ident.brand is None and ident.model is None and ident.name is None


def test_values_are_bounded_and_cleaned():
    ident, _ = identity_from_html(
        ld({"@type": "Product", "name": "  A\n\n  B  " + "x" * 500, "brand": {"name": ""}})
    )
    assert ident.name.value.startswith("A B")
    assert len(ident.name.value) <= 200
    assert ident.brand is None


# --- Full identification -----------------------------------------------------------------------


async def page(html: str):
    async def fetch(url: str) -> str:
        return html

    return fetch


async def test_identify_philips_shell_page_keeps_unknowns_unknown():
    report = await identify_product_url(PHILIPS, fetch=await page(SHELL))
    assert report.input.url == PHILIPS
    assert report.page.fetched is True
    assert report.page.structured_data is False
    assert report.identity.model.value == "XC2011/01"
    assert report.identity.brand is None
    assert any("no structured product data" in w for w in report.warnings)


async def test_page_data_wins_over_url_and_disagreement_is_reported():
    html = ld(
        {"@type": "Product", "name": "Philips XC2011/03", "brand": "Philips", "mpn": "XC2011/03"}
    )
    report = await identify_product_url(PHILIPS, fetch=await page(html))
    assert (report.identity.model.value, report.identity.model.source) == ("XC2011/03", "json_ld")
    assert any("XC2011/01" in w and "XC2011/03" in w for w in report.warnings)


async def test_agreeing_url_and_page_model_gives_no_warning():
    html = ld(
        {
            "@type": "Product",
            "name": "Philips XC2011/01",
            "brand": "Philips",
            "mpn": "XC2011/01",
            "offers": {"price": 89.99, "priceCurrency": "EUR"},
        }
    )
    report = await identify_product_url(PHILIPS, fetch=await page(html))
    assert report.identity.model.value == "XC2011/01"
    assert report.identity.currency.value == "EUR"
    assert report.warnings == []


async def test_fetch_failure_returns_url_identity_with_reason():
    async def blocked(url: str) -> str:
        raise PageFetchError("the shop's robots.txt does not allow reading this page")

    report = await identify_product_url(PHILIPS, fetch=blocked)
    assert report.page.fetched is False
    assert "robots.txt" in (report.page.reason or "")
    assert report.identity.model.value == "XC2011/01"


async def test_offline_mode_never_fetches():
    async def boom(url: str) -> str:
        raise AssertionError("must not fetch")

    report = await identify_product_url(PHILIPS, fetch=boom, offline=True)
    assert report.page.fetched is False
    assert report.page.reason and "offline" in report.page.reason


async def test_identify_rejects_invalid_url():
    with pytest.raises(UrlValidationError):
        await identify_product_url("ftp://x.example/p", fetch=await page(SHELL))


# --- API: new versioned endpoint, old ones unchanged --------------------------------------------


class LiveLike:
    name = "idealo"

    async def find(self, query):  # pragma: no cover - not used by identify
        return None


def test_identify_endpoint(monkeypatch):
    from app import product_identity

    async def fake_fetch(url: str) -> str:
        return SHELL

    monkeypatch.setattr(main, "source", LiveLike())
    monkeypatch.setattr(product_identity, "fetch_page", fake_fetch)
    r = TestClient(main.app).post("/api/v1/product-url/identify", json={"url": PHILIPS})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema_version"] == "1"
    assert body["identity"]["model"] == {
        "value": "XC2011/01",
        "source": "url_path",
        "status": "unverified",
        "raw": "XC2011_01",
        "corroborated_by": None,  # added in M4 (optional); identify never verifies
    }
    assert body["identity"]["brand"] is None
    assert body["page"]["fetched"] is True


def test_identify_endpoint_invalid_url_is_structured_422(monkeypatch):
    monkeypatch.setattr(main, "source", LiveLike())
    r = TestClient(main.app).post(
        "/api/v1/product-url/identify", json={"url": "https://localhost/x"}
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "not_public_host"


def test_identify_endpoint_demo_mode_is_offline(monkeypatch):
    from app import product_identity
    from app.sources import DemoSource

    async def boom(url: str) -> str:
        raise AssertionError("demo mode must stay offline")

    monkeypatch.setattr(main, "source", DemoSource())
    monkeypatch.setattr(product_identity, "fetch_page", boom)
    r = TestClient(main.app).post("/api/v1/product-url/identify", json={"url": PHILIPS})
    assert r.status_code == 200 and r.json()["page"]["fetched"] is False


def test_extract_text_response_shape_is_unchanged(monkeypatch):
    from app.sources import DemoSource

    monkeypatch.setattr(main, "source", DemoSource())
    r = TestClient(main.app).post("/api/extract/text", json={"text": "Kettle 42 € statt 60 €"})
    assert set(r.json()) == {"product", "price", "was_price", "shop", "note"}
