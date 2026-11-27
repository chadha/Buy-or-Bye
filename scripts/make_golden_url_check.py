"""Snapshot the full URL check for Philips XC2011/01 (BOB-URL-001 M6 golden fixture).

Runs check_product_url on the live recordings in tests/fixtures/idealo/ (27 Nov 2026) with a
fixed judging day and writes the whole report as JSON. tests/test_golden_url_check.py compares
every later run against it. Regenerate only for an intended, explained change and review the
diff: it covers identity, statuses, provenance, offers and the verdict in one file.

    python scripts/make_golden_url_check.py > tests/fixtures/golden_url_check_xc2011.json
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.url_check import check_product_url  # noqa: E402
from tests.test_url_check import PHILIPS, SHELL, TODAY, FakeIdealo  # noqa: E402

# The only value that depends on when the test runs: our own page download time.
VOLATILE = (("resolution", "identification", "page", "retrieved_at"),)


def snapshot() -> dict[str, Any]:
    async def shell(url: str) -> str:
        return SHELL

    report = asyncio.run(check_product_url(PHILIPS, FakeIdealo(), fetch=shell, today=TODAY))
    data = report.model_dump(mode="json")
    for path in VOLATILE:
        node = data
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = "<volatile>"
    return data


if __name__ == "__main__":
    json.dump(snapshot(), sys.stdout, ensure_ascii=False, indent=1, sort_keys=True)
    sys.stdout.write("\n")
