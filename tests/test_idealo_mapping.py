"""Mapping of idealo MCP responses, using the shapes published in
github.com/idealo/mcp-server-guide docs/tools.md (illustrative samples, not live recordings)."""

from datetime import date, timedelta

from app.mcp_server import judge
from app.sources import best_result, history_from_idealo, offers_from_idealo, parse_price

SEARCH = {
    "query": "macbook",
    "results": [
        {
            "productRef": "pr.v1.k1.a==",
            "itemType": "PRODUCT",
            "name": 'Apple MacBook Air 13" M2',
            "price": "999,00 €",
            "url": "https://www.idealo.de/preisvergleich/OffersOfProduct/1.html",
        },
        {
            "productRef": "pr.v1.k1.b==",
            "itemType": "PRODUCT",
            "name": "Apple MacBook Pro 14 M3",
            "price": "1.799,00 €",
        },
    ],
}

HISTORY = {
    "priceTrend": {
        "history": [
            {
                "dateTime": 1701388800000,
                "price": "1.059,00 €",
                "dateTimeISO": "2023-11-30T12:00:00.000Z",
                "priceChangePercent": None,
            },
            {
                "dateTime": 1706745600000,
                "price": "999,00 €",
                "dateTimeISO": "2024-02-01T12:00:00.000Z",
                "priceChangePercent": -2.92,
            },
        ],
        "statistics": {"minPrice": "950,00 €", "maxPrice": "1.099,00 €"},
        "samplingGranularity": "daily",
        "periodDays": 30,
    }
}

OFFERS = {
    "nextOffset": 5,
    "offers": [
        {
            "price": "999,00 €",
            "relocatorUrl": "https://www.techstore.de/macbook-air",
            "shop": {"name": "TechStore", "merchantName": "TechStore GmbH"},
        },
        {"price": "n/a", "shop": {"name": "Broken"}},
    ],
}


def test_parse_price_formats() -> None:
    assert parse_price("1.059,00 €") == 1059.0
    assert parse_price("999,00 €") == 999.0
    assert parse_price("£999.99") == 999.99
    assert parse_price("£1,299.00") == 1299.0
    assert parse_price("") is None
    assert parse_price(None) is None


def test_best_result_matches_the_shoppers_product() -> None:
    hit = best_result(SEARCH, "MacBook Air M2")
    assert hit is not None and hit["productRef"] == "pr.v1.k1.a=="


def test_best_result_refuses_a_weak_match() -> None:
    assert best_result(SEARCH, "Sony WH-1000XM5 headphones") is None
    assert best_result({"results": []}, "anything") is None


def test_history_mapping() -> None:
    pts = history_from_idealo(HISTORY)
    assert [(p.day, p.price) for p in pts] == [
        (date(2023, 11, 30), 1059.0),
        (date(2024, 2, 1), 999.0),
    ]
    assert history_from_idealo({"priceTrend": None}) == []


def test_offers_mapping_skips_unparseable_rows() -> None:
    offers = offers_from_idealo(OFFERS)
    assert [(o.merchant, o.price) for o in offers] == [("TechStore", 999.0)]
    assert offers[0].url == "https://www.techstore.de/macbook-air"


def _series(today: date, prices: list[float]) -> dict:
    start = today - timedelta(days=len(prices))
    return {
        "priceTrend": {
            "history": [
                {
                    "dateTimeISO": f"{(start + timedelta(days=i)).isoformat()}T12:00:00.000Z",
                    "price": f"{p:.2f}".replace(".", ",") + " €",
                }
                for i, p in enumerate(prices)
            ]
        }
    }


def test_judge_flags_a_pre_sale_hike_on_30_days_of_idealo_data() -> None:
    today = date(2026, 11, 27)
    prices = [84.0] * 9 + [123.0] * 21  # flat, then pushed up three weeks before the sale
    out = judge(
        "Air Fryer XL", 79.99, 249.99, "Shop D", _series(today, prices), {"offers": []}, today=today
    )
    assert out["label"] == "BYE"
    codes = " ".join(r["text"] for r in out["reasons"])
    assert "pushed up before the sale" in codes
    assert "30 days" in codes and "90 days" not in codes
    assert out["decided_by"].startswith("Buy or Bye rules engine")


def test_judge_needs_enough_history() -> None:
    today = date(2026, 11, 27)
    out = judge("Xbox", 10.0, None, None, _series(today, [12.0] * 5), {}, today=today)
    assert out["label"] == "NOT_ENOUGH_DATA"


class _Text:
    def __init__(self, text: str) -> None:
        self.text = text


class _ResultV2:  # MCP SDK 2.x field names
    def __init__(self, structured=None, is_error=False, text=None):
        self.structured_content = structured
        self.is_error = is_error
        self.content = [_Text(text)] if text else []


class _ResultV1:  # MCP SDK 1.x field names
    def __init__(self, structured=None, is_error=False):
        self.structuredContent = structured
        self.isError = is_error
        self.content = []


def test_unwrap_reads_both_sdk_result_shapes() -> None:
    import pytest

    from app.sources import SourceError, _unwrap

    assert _unwrap("t", _ResultV2(structured={"a": 1})) == {"a": 1}
    assert _unwrap("t", _ResultV1(structured={"b": 2})) == {"b": 2}
    assert _unwrap("t", _ResultV2(text='{"c": 3}')) == {"c": 3}
    with pytest.raises(SourceError):
        _unwrap("t", _ResultV2(is_error=True, text="rate limited"))
    with pytest.raises(SourceError):
        _unwrap("t", _ResultV1(is_error=True))
