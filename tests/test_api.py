"""End to end through the HTTP API on demo data (no network)."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.sources import DemoSource, IdealoMCPSource, SourceError

DEALS = json.loads((Path(__file__).parent / "fixtures" / "deals.json").read_text())
client = TestClient(main.app)


@pytest.mark.parametrize("d", DEALS, ids=[d["product"] for d in DEALS])
def test_demo_deals_get_expected_label(monkeypatch, d):
    monkeypatch.setattr(main, "source", DemoSource())
    body = {k: v for k, v in d.items() if k != "expect"}
    r = client.post("/api/check", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["label"] == d["expect"]


def test_unknown_product_is_not_enough_data(monkeypatch):
    monkeypatch.setattr(main, "source", DemoSource())
    r = client.post("/api/check", json={"product": "Totally Unknown Gadget", "price": 10})
    assert r.json()["label"] == "NOT_ENOUGH_DATA"


def test_invalid_price_is_rejected():
    assert client.post("/api/check", json={"product": "x y", "price": -1}).status_code == 422


class _FailingSource:
    name = "idealo"

    async def find(self, query: str):
        raise SourceError("idealo sign-in required: run make idealo-login")


def test_price_source_failure_is_a_clear_503_not_a_verdict(monkeypatch):
    monkeypatch.setattr(main, "source", _FailingSource())
    r = client.post("/api/check", json={"product": "Anything", "price": 10})
    assert r.status_code == 503 and "idealo" in r.json()["detail"]


def test_index_and_health():
    assert "Buy or Bye" in client.get("/").text
    assert client.get("/healthz").json()["ok"] == "true"


def test_photo_without_llm_config_asks_user_to_type(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    r = client.post("/api/extract/photo", files={"photo": ("t.jpg", b"\xff\xd8\xff", "image/jpeg")})
    assert r.status_code == 200 and "type the details" in r.json()["note"]


def test_non_image_upload_is_rejected():
    r = client.post("/api/extract/photo", files={"photo": ("t.txt", b"hello", "text/plain")})
    assert r.status_code == 415


def test_idealo_source_defaults_to_the_documented_tools():
    src = IdealoMCPSource()
    assert src.url == "https://mcp.idealo.com/mcp"
    assert src.tools == {
        "search": "search_products",
        "history": "get_product_price_history",
        "offers": "get_product_offers",
    }
