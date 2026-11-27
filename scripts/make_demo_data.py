"""Generate the synthetic demo products in app/demo_data.json (deterministic).

These are FICTIONAL products with invented prices, for offline development and rehearsal only.
The UI labels them "demo data". Real verdicts come from the idealo MCP (PRICE_SOURCE=idealo).
"""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

LAST_DAY = date(2026, 11, 26)  # demo "today" is the day after: Black Friday 2026
OUT = Path(__file__).resolve().parents[1] / "app" / "demo_data.json"


def series(days: int, base: float, noise: float, seed: int, overrides=None) -> list[dict]:
    rnd = random.Random(seed)
    out = []
    for i in range(days):
        day = LAST_DAY - timedelta(days=days - 1 - i)
        ago = (LAST_DAY - day).days + 1  # 1 = yesterday relative to demo today
        price = base * (1 + rnd.uniform(-noise, noise))
        if overrides:
            price = overrides(ago, price)
        out.append({"day": day.isoformat(), "price": round(price, 2)})
    return out


def product(pid, name, history, offers):
    return {
        "product_id": pid,
        "name": name,
        "history": history,
        "source": "demo",
        "offers": [{"merchant": m, "price": p, "in_stock": True} for m, p in offers],
    }


products = [
    # BUY: steady ~€249, today €209 at a real 90-day low
    product(
        "demo-headphones-h7",
        "Nordwind ANC Headphones H7",
        series(120, 249, 0.03, 1),
        [("Shop A", 209.0), ("Shop B", 219.0), ("Shop C", 229.0)],
    ),
    # BYE: ~€84 for months, pushed to ~€119 in the last 3 weeks, "−68%" from an invented €249.99
    product(
        "demo-airfryer-xl",
        "Polar Air Fryer XL 6L",
        series(120, 84, 0.02, 2, lambda ago, p: 119 * (1 + (p / 84 - 1)) if ago <= 21 else p),
        [("Shop D", 79.99), ("Shop E", 82.5)],
    ),
    # BYE: decent discount, but another shop is €30 cheaper right now
    product(
        "demo-monitor-27q",
        "Lumen 4K Monitor 27Q",
        series(120, 329, 0.02, 3),
        [("MegaShop", 299.0), ("Shop F", 269.0)],
    ),
    # WAIT: 4–5% below typical; it was €999 two months ago
    product(
        "demo-laptop-14pro",
        "Kestrel Laptop 14 Pro",
        series(120, 1099, 0.015, 4, lambda ago, p: 999.0 if 55 <= ago <= 62 else p),
        [("Shop G", 1049.0), ("Shop H", 1069.0)],
    ),
    # NOT ENOUGH DATA: only a few days of history
    product("demo-watch-s3", "Vela Smartwatch S3", series(6, 199, 0.02, 5), [("Shop I", 179.0)]),
]

DEALS = [
    {
        "product": "Nordwind ANC Headphones H7",
        "price": 209.0,
        "was_price": 279.0,
        "shop": "Shop A",
        "expect": "BUY",
    },
    {
        "product": "Polar Air Fryer XL 6L",
        "price": 79.99,
        "was_price": 249.99,
        "shop": "Shop D",
        "expect": "BYE",
    },
    {
        "product": "Lumen 4K Monitor 27Q",
        "price": 299.0,
        "was_price": 399.0,
        "shop": "MegaShop",
        "expect": "BYE",
    },
    {
        "product": "Kestrel Laptop 14 Pro",
        "price": 1049.0,
        "was_price": 1199.0,
        "shop": "Shop G",
        "expect": "WAIT",
    },
    {
        "product": "Vela Smartwatch S3",
        "price": 179.0,
        "was_price": 249.0,
        "shop": "Shop I",
        "expect": "NOT_ENOUGH_DATA",
    },
]

if __name__ == "__main__":
    OUT.write_text(
        json.dumps(
            {"note": "Synthetic demo data. Fictional products and prices.", "products": products},
            indent=1,
        )
        + "\n"
    )
    deals = OUT.parents[1] / "tests" / "fixtures" / "deals.json"
    deals.parent.mkdir(parents=True, exist_ok=True)
    deals.write_text(json.dumps(DEALS, indent=2) + "\n")
    print(f"wrote {OUT} and {deals}")
