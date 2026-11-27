"""End-to-end golden test for the URL check (BOB-URL-001 M6).

The whole report for the Philips XC2011/01 link, built from live idealo recordings, must stay
exactly as snapshotted in tests/fixtures/golden_url_check_xc2011.json (see
scripts/make_golden_url_check.py). Spot checks below make the key facts readable in review.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from make_golden_url_check import snapshot  # noqa: E402

GOLDEN = json.loads(
    (ROOT / "tests" / "fixtures" / "golden_url_check_xc2011.json").read_text(encoding="utf-8")
)


def test_url_check_matches_the_golden_report():
    assert snapshot() == GOLDEN


def test_golden_report_key_facts():
    r = GOLDEN
    assert r["status"] == "judged" and r["verdict"]["label"] == "BUY"
    ident = r["resolution"]["identity"]
    assert (ident["model"]["value"], ident["model"]["status"]) == ("XC2011/01", "verified")
    assert (ident["brand"]["value"], ident["brand"]["status"]) == ("Philips", "verified")
    assert ident["family"] is None and "family" in r["resolution"]["unknown"]
    assert (r["deal"]["amount"], r["deal"]["seller"], r["deal"]["source"]) == (
        89.99,
        "philips.de (Home-appliances)",
        "idealo",
    )
    assert r["deal"]["observed_at"] and r["deal"]["shipping_included"] is False
    assert r["market"]["history_days"] == 31 and r["market"]["canonical_id"] == "203830913"
