"""BOB-URL-001 M3: idealo get_product_details with usage guardrails (decision D3).

The tool schema and the XC2011/01 response were recorded live (tests/fixtures/idealo/). No
test touches the network.
"""

import asyncio
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app.idealo_usage import QuotaExceeded, UsagePolicy, UsageTracker
from app.product_identity import FieldValue, ProductIdentity, details_needed
from app.sources import (
    DetailsCache,
    IdealoMCPSource,
    SourceError,
    canonical_product_id,
    details_from_idealo,
)

FIX = Path(__file__).parent / "fixtures" / "idealo"
DETAILS = json.loads((FIX / "get_product_details_xc2011.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((FIX / "get_product_details_schema.json").read_text(encoding="utf-8"))
URL = DETAILS["url"]  # as recorded: .../OffersOfProduct/203830913_-xc2011-01-philips.html
NOW = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)


def tracker(tmp_path, limit=500, reserve=150, day=date(2026, 11, 27)):
    clock = {"day": day}
    t = UsageTracker(
        tmp_path / "usage.json",
        UsagePolicy(daily_limit=limit, price_check_reserve=reserve),
        today=lambda: clock["day"],
    )
    return t, clock


# --- Usage policy ---------------------------------------------------------------------------------


def test_default_policy_is_the_trial_quota():
    p = UsagePolicy.from_env({})
    assert (p.daily_limit, p.price_check_reserve) == (500, 150)


@pytest.mark.parametrize(
    "env,limit,reserve",
    [
        ({"IDEALO_DAILY_LIMIT": "100"}, 100, 100),  # reserve capped at the limit
        ({"IDEALO_DAILY_LIMIT": "100", "IDEALO_PRICE_CHECK_RESERVE": "20"}, 100, 20),
        ({"IDEALO_DAILY_LIMIT": "900"}, 500, 150),  # never above the hard maximum
        ({"IDEALO_DAILY_LIMIT": "-5"}, 0, 0),
        ({"IDEALO_DAILY_LIMIT": "lots"}, 500, 150),  # invalid: default
        ({"IDEALO_PRICE_CHECK_RESERVE": "x"}, 500, 150),
    ],
)
def test_policy_from_env_is_clamped(env, limit, reserve):
    p = UsagePolicy.from_env(env)
    assert (p.daily_limit, p.price_check_reserve) == (limit, reserve)


# --- Usage tracker --------------------------------------------------------------------------------


def test_default_tracker_uses_the_configured_file(tmp_path, monkeypatch):
    # Regression: a default IdealoMCPSource() in tests once wrote to the real ~/.buyorbye file.
    monkeypatch.setenv("IDEALO_USAGE_FILE", str(tmp_path / "elsewhere.json"))
    assert UsageTracker().path == tmp_path / "elsewhere.json"
    assert IdealoMCPSource().usage.path == tmp_path / "elsewhere.json"


async def test_calls_are_counted_and_persisted(tmp_path):
    t, _ = tracker(tmp_path)
    await t.acquire(["search_products", "get_product_offers"])
    t2, _ = tracker(tmp_path)  # a new process reads the same file
    snap = t2.snapshot()
    assert snap["total"] == 2
    assert snap["by_tool"] == {"search_products": 1, "get_product_offers": 1}
    assert snap["remaining"] == 498


async def test_new_utc_day_resets_the_count(tmp_path):
    t, clock = tracker(tmp_path)
    await t.acquire(["search_products"] * 3)
    clock["day"] = date(2026, 11, 28)
    assert t.snapshot()["total"] == 0
    await t.acquire(["search_products"])
    assert t.snapshot() == {**t.snapshot(), "day": "2026-11-28", "total": 1}


async def test_hard_limit_refuses_before_the_call_and_counts_nothing(tmp_path):
    t, _ = tracker(tmp_path, limit=3, reserve=0)
    await t.acquire(["a", "b", "c"])
    with pytest.raises(QuotaExceeded) as err:
        await t.acquire(["d"])
    assert isinstance(err.value, SourceError)
    assert "3" in str(err.value)
    assert t.snapshot()["total"] == 3


async def test_multi_call_check_is_all_or_nothing(tmp_path):
    t, _ = tracker(tmp_path, limit=5, reserve=0)
    await t.acquire(["a", "b", "c"])
    with pytest.raises(QuotaExceeded):
        await t.acquire(["search_products", "get_product_price_history", "get_product_offers"])
    assert t.snapshot()["total"] == 3


async def test_identity_calls_leave_the_reserve_for_price_checks(tmp_path):
    t, _ = tracker(tmp_path, limit=10, reserve=4)
    await t.acquire(["x"] * 6)
    with pytest.raises(QuotaExceeded, match="reserved"):
        await t.acquire(["get_product_details"], purpose="identity")
    await t.acquire(["search_products"] * 4)  # price checks may use the reserve
    with pytest.raises(QuotaExceeded):
        await t.acquire(["search_products"])


async def test_concurrent_acquires_never_exceed_the_limit(tmp_path):
    t, _ = tracker(tmp_path, limit=10, reserve=0)

    async def one():
        try:
            await t.acquire(["search_products"])
            return True
        except QuotaExceeded:
            return False

    results = await asyncio.gather(*(one() for _ in range(50)))
    assert sum(results) == 10
    assert t.snapshot()["total"] == 10


async def test_corrupt_usage_file_starts_fresh(tmp_path):
    (tmp_path / "usage.json").write_text("{not json", encoding="utf-8")
    t, _ = tracker(tmp_path)
    await t.acquire(["search_products"])
    assert t.snapshot()["total"] == 1


# --- Recorded schema: we never send parameters idealo does not define -------------------------


def test_details_arguments_match_the_recorded_schema():
    props = SCHEMA["inputSchema"]["properties"]
    for item_type in (None, "PRODUCT", "CLUSTER", "SINGLE_OFFER"):
        args = IdealoMCPSource(country="DE").details_args("pr.v1.x", item_type)
        assert set(args) <= set(props)
        assert set(SCHEMA["inputSchema"]["required"]) <= set(args)
        if "type" in args:
            assert args["type"] in props["type"]["enum"]
    assert "type" not in IdealoMCPSource().details_args("pr.v1.x", "PRODUCT")
    assert IdealoMCPSource().details_args("pr.v1.x", "CLUSTER")["type"] == "CLUSTER"


def test_mapped_fields_exist_in_the_recorded_output_schema():
    for field in ("name", "url", "productSpecification", "productOverview"):
        assert field in SCHEMA["outputSchemaProperties"]


# --- Mapping a details response ---------------------------------------------------------------


@pytest.mark.parametrize(
    "url,cid",
    [
        (URL, "203830913"),
        (
            "https://www.idealo.de/preisvergleich/OffersOfProduct/207671677_-wh-1000xm5-sony.html",
            "207671677",
        ),
        ("https://www.idealo.at/preisvergleich/OffersOfProduct/1234567", "1234567"),
        ("https://www.idealo.de/preisvergleich/ProductCategory/3932.html", None),
        ("https://evil.example/OffersOfProduct/203830913_-x", None),  # only idealo hosts
        (None, None),
    ],
)
def test_canonical_product_id(url, cid):
    assert canonical_product_id(url) == cid


def test_recorded_xc2011_details_map_to_complete_identity_fields():
    d = details_from_idealo(DETAILS, NOW)
    assert d.status == "complete" and d.missing == [] and d.error is None
    assert (d.canonical_id, d.name, d.url) == ("203830913", "Philips XC2011/01", URL)
    assert d.product_type == "Stielstaubsauger"
    assert d.source == "idealo" and d.retrieved_at == NOW
    assert any(a.name == "Betriebszeit" and a.value == "40 Min." for a in d.specifications)
    assert "\xa0" not in json.dumps(d.model_dump(mode="json"), ensure_ascii=False)
    assert "Betriebszeit 40 Min." in d.overview
    # idealo gives no brand, GTIN or series: the model has no place to invent them.
    assert not {"brand", "gtin", "family", "series"} & set(type(d).model_fields)


def test_missing_specification_gives_a_partial_result():
    raw = {k: v for k, v in DETAILS.items() if k != "productSpecification"}
    d = details_from_idealo(raw, NOW)
    assert d.status == "partial"
    assert d.missing == ["product_type"]
    assert d.name == "Philips XC2011/01"


@pytest.mark.parametrize("raw", [None, [], "text", {"unexpected": 1}])
def test_unusable_response_is_unavailable(raw):
    d = details_from_idealo(raw, NOW)
    assert d.status == "unavailable"
    assert d.error
    assert d.name is None


def test_values_are_bounded():
    raw = {**DETAILS, "name": "x" * 1000, "productOverview": ["y" * 1000] * 100}
    d = details_from_idealo(raw, NOW)
    assert len(d.name) <= 200
    assert len(d.overview) <= 30 and all(len(o) <= 200 for o in d.overview)


# --- Adapter: cache, single flight, failures, quota -------------------------------------------


class Recorder:
    def __init__(self, response=None, error=None):
        self.calls: list[tuple[str, dict]] = []
        self.response = response if response is not None else DETAILS
        self.error = error

    async def __call__(self, calls, purpose="price_check"):
        assert purpose == "identity"
        await asyncio.sleep(0)
        self.calls.extend(calls)
        if self.error:
            raise self.error
        return [self.response for _ in calls]


def source_with(monkeypatch, recorder, tmp_path, cache=None):
    t, _ = tracker(tmp_path)
    src = IdealoMCPSource(usage=t, details_cache=cache or DetailsCache(ttl_s=3600))
    monkeypatch.setattr(src, "_call_many", recorder)
    return src


async def test_details_are_cached_by_canonical_id(monkeypatch, tmp_path):
    rec = Recorder()
    src = source_with(monkeypatch, rec, tmp_path)
    first = await src.product_details("pr.v1.a", URL)
    again = await src.product_details("pr.v1.b-new-ref", URL)  # productRef changes; ID does not
    assert first.status == again.status == "complete"
    assert len(rec.calls) == 1
    assert rec.calls[0] == ("get_product_details", {"productRef": "pr.v1.a", "country": "DE"})


async def test_concurrent_requests_share_one_call(monkeypatch, tmp_path):
    rec = Recorder()
    src = source_with(monkeypatch, rec, tmp_path)
    results = await asyncio.gather(*(src.product_details("pr.v1.a", URL) for _ in range(5)))
    assert len(rec.calls) == 1
    assert {r.canonical_id for r in results} == {"203830913"}


async def test_cache_expires(monkeypatch, tmp_path):
    clock = {"t": 1000.0}
    rec = Recorder()
    src = source_with(monkeypatch, rec, tmp_path, DetailsCache(ttl_s=60, clock=lambda: clock["t"]))
    await src.product_details("pr.v1.a", URL)
    clock["t"] += 61
    await src.product_details("pr.v1.a", URL)
    assert len(rec.calls) == 2


async def test_failure_returns_structured_unavailable_and_is_not_cached(monkeypatch, tmp_path):
    rec = Recorder(error=SourceError("idealo is not answering"))
    src = source_with(monkeypatch, rec, tmp_path)
    d = await src.product_details("pr.v1.a", URL)
    assert (d.status, d.canonical_id, d.name) == ("unavailable", "203830913", None)
    assert "not answering" in (d.error or "")
    await src.product_details("pr.v1.a", URL)
    assert len(rec.calls) == 2  # retried, because failures are not cached


async def test_quota_refusal_never_opens_a_connection(monkeypatch, tmp_path):
    pytest.importorskip("mcp")  # the budget check runs after the SDK import
    from app import idealo_auth

    def boom(*a, **k):
        raise AssertionError("no idealo connection may be opened")

    monkeypatch.setattr(idealo_auth, "open_transport", boom)
    t, _ = tracker(tmp_path, limit=10, reserve=10)  # whole budget reserved for price checks
    src = IdealoMCPSource(usage=t, details_cache=DetailsCache(ttl_s=3600))
    d = await src.product_details("pr.v1.a", URL)
    assert d.status == "unavailable" and "reserved" in (d.error or "")
    assert t.snapshot()["total"] == 0


async def test_price_check_calls_are_counted(monkeypatch, tmp_path):
    pytest.importorskip("mcp")  # the budget check runs after the SDK import
    from contextlib import asynccontextmanager

    from app import idealo_auth

    @asynccontextmanager
    async def failing(transport, url):
        raise RuntimeError("offline test")
        yield  # pragma: no cover

    monkeypatch.setattr(idealo_auth, "open_transport", failing)
    t, _ = tracker(tmp_path)
    src = IdealoMCPSource(usage=t)
    with pytest.raises(SourceError):
        await src.find("sony wh-1000xm5")
    assert t.snapshot()["by_tool"] == {"search_products": 1}  # attempts count, conservatively


# --- When details are needed ------------------------------------------------------------------


def test_details_only_when_identity_lacks_a_category():
    assert details_needed(ProductIdentity()) is True
    known = ProductIdentity(category=FieldValue(value="Staubsauger", source="json_ld"))
    assert details_needed(known) is False


def test_snapshot_reports_policy(tmp_path):
    t, _ = tracker(tmp_path, limit=100, reserve=30)
    snap = t.snapshot()
    assert (snap["limit"], snap["price_check_reserve"], snap["remaining"]) == (100, 30, 100)
    assert snap["day"] == "2026-11-27"
