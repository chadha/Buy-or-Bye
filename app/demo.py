"""`make demo`: run the verdict on the demo deals and print a table."""

from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from pathlib import Path

from .models import Deal
from .sources import DemoSource
from .verdict import decide

DEALS = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "deals.json"


async def main() -> int:
    source, failures = DemoSource(), 0
    for d in json.loads(DEALS.read_text()):
        expect = d.pop("expect")
        deal = Deal(**d)
        product = await source.find(deal.product)
        today = product.history[-1].day + timedelta(days=1) if product else date.today()
        v = decide(deal, product, today)
        ok = v.label.value == expect
        failures += not ok
        print(f"{'✓' if ok else '✗'} {v.label.value:16} {deal.product:28} {v.headline}")
        for r in v.reasons:
            print(f"    [{r.polarity:7}] {r.text}")
    return failures


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
