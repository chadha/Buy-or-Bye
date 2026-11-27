"""Freeze verdict outputs as a golden regression set (BOB-URL-001 M2, Decimal migration).

Generated ONCE from the float implementation (commit e3fda17) before money moved to Decimal;
tests/test_golden_verdicts.py checks that every case still gives exactly the same label,
headline, reasons, evidence and stats. Do not regenerate to make a failing test pass: a diff
means behaviour changed and must be explained.

Cases: the five demo deals, plus a sweep of deal and "was" prices around each demo product's
own 30-day typical price (borderline thresholds included), with and without the shop, on the
full 120-day history and on a 30-day history (the window idealo provides).

    python scripts/make_golden_verdicts.py > tests/fixtures/golden_verdicts.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.models import Deal, ProductData  # noqa: E402
from app.verdict import decide  # noqa: E402

PRICE_STEPS = ["0.70", "0.80", "0.88", "0.90", "0.92", "0.95", "0.97", "1.00", "1.03", "1.20"]
WAS_STEPS = [None, "1.10", "1.30", "2.50"]
SHORT_PRICE_STEPS = ["0.85", "0.90", "0.97", "1.00", "1.10"]
SHORT_WAS_STEPS = [None, "1.60"]


def cases() -> list[dict[str, Any]]:
    data = json.loads((ROOT / "app" / "demo_data.json").read_text(encoding="utf-8"))["products"]
    deals = json.loads((ROOT / "tests" / "fixtures" / "deals.json").read_text(encoding="utf-8"))
    out: list[dict[str, Any]] = []
    for d in deals:
        out.append(
            {
                "id": f"demo:{d['product']}",
                "product": d["product"],
                "history_days": None,
                "deal": {k: v for k, v in d.items() if k != "expect"},
            }
        )
    for p in data:
        last30 = [h["price"] for h in p["history"][-30:]]
        base = median(last30)
        shops = [None, p["offers"][0]["merchant"]] if p["offers"] else [None]
        for days, steps, was_steps in (
            (None, PRICE_STEPS, WAS_STEPS),
            (31, SHORT_PRICE_STEPS, SHORT_WAS_STEPS),
        ):
            for step in steps:
                price = round(base * float(step), 2)
                for was in was_steps:
                    for shop in shops:
                        deal = {
                            "product": p["name"],
                            "price": price,
                            "was_price": round(price * float(was), 2) if was else None,
                            "shop": shop,
                        }
                        out.append(
                            {
                                "id": f"{p['name']}|days={days}|p={step}|was={was}|shop={shop}",
                                "product": p["name"],
                                "history_days": days,
                                "deal": deal,
                            }
                        )
    return out


def run(case: dict[str, Any]) -> dict[str, Any]:
    from datetime import timedelta

    data = json.loads((ROOT / "app" / "demo_data.json").read_text(encoding="utf-8"))["products"]
    raw = next(p for p in data if p["name"] == case["product"])
    if case["history_days"]:
        raw = {**raw, "history": raw["history"][-case["history_days"] :]}
    product = ProductData(**raw)
    today = product.history[-1].day + timedelta(days=1)
    v = decide(Deal(**case["deal"]), product, today)
    dumped = v.model_dump(mode="json")
    return {k: dumped[k] for k in ("label", "headline", "reasons", "stats", "deal")}


def main() -> None:
    out = [{**c, "expected": run(c)} for c in cases()]
    json.dump(out, sys.stdout, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
