"""Buy or Bye as an MCP server: any AI assistant can ask "is this discount real?".

The assistant only talks. The label comes from app/verdict.py, computed from idealo's own
price history and merchant offers. Run over stdio for Claude Desktop:

    python -m app.mcp_server

Tools
- check_deal: searches idealo itself (needs `make idealo-login` once), then judges.
- judge_deal: the assistant passes the raw idealo responses it already fetched with the idealo
  connector (get_product_price_history, get_product_offers); this server judges them.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .models import Deal, ProductData, Verdict
from .sources import SourceError, history_from_idealo, make_source, offers_from_idealo
from .verdict import decide


def _deal(product: str, deal_price: float, was_price: float | None, shop: str | None) -> Deal:
    # Tool arguments arrive as JSON numbers; Deal validation turns them into exact Decimal cents.
    return Deal.model_validate(
        {"product": product, "price": deal_price, "was_price": was_price, "shop": shop}
    )


def _summary(v: Verdict) -> dict[str, Any]:
    return {
        "label": v.label.value,
        "headline": v.headline,
        "reasons": [
            {
                "polarity": r.polarity,
                "text": r.text,
                "evidence": [e.model_dump(mode="json", exclude_none=True) for e in r.evidence],
            }
            for r in v.reasons
        ],
        "product": v.product.name if v.product else None,
        "idealo_url": v.product.url if v.product else None,
        "decided_by": "Buy or Bye rules engine (deterministic code), not the language model",
        "data_source": v.product.source if v.product else None,
    }


def judge(
    product: str,
    deal_price: float,
    was_price: float | None,
    shop: str | None,
    price_history: Any,
    offers: Any,
    today: date | None = None,
) -> dict[str, Any]:
    deal = _deal(product, deal_price, was_price, shop)
    data = ProductData(
        product_id=product,
        name=product,
        history=history_from_idealo(price_history),
        offers=offers_from_idealo(offers),
        source="idealo",
    )
    return _summary(decide(deal, data, today or date.today()))


def build_server() -> Any:
    from mcp.server.mcpserver import MCPServer

    server = MCPServer(
        name="buy-or-bye",
        instructions=(
            "Use these tools whenever a user asks whether a discount, sale price or "
            "'was' price is real. Report the label and reasons exactly as returned; never "
            "change the label or invent numbers. Remind the user that they buy on the shop's "
            "site themselves."
        ),
    )

    @server.tool(
        description=(
            "Check a discount against idealo price history and current offers. "
            "Returns BUY, BYE, WAIT or NOT_ENOUGH_DATA with evidence."
        )
    )
    async def check_deal(
        product: str, deal_price: float, was_price: float | None = None, shop: str | None = None
    ) -> dict[str, Any]:
        src = make_source()
        try:
            found = await src.find(product)
        except SourceError as exc:
            return {"label": "ERROR", "headline": str(exc)}
        deal = _deal(product, deal_price, was_price, shop)
        last = found.history[-1].day if found and found.history else None
        from .main import _today_for

        return _summary(decide(deal, found, _today_for(last, src.name)))

    @server.tool(
        description=(
            "Judge a discount from idealo data you already fetched. Pass the JSON returned by "
            "idealo get_product_price_history as price_history and by get_product_offers as "
            "offers, unchanged. Returns BUY, BYE, WAIT or NOT_ENOUGH_DATA with evidence."
        )
    )
    def judge_deal(
        product: str,
        deal_price: float,
        price_history: dict[str, Any],
        offers: dict[str, Any] | None = None,
        was_price: float | None = None,
        shop: str | None = None,
    ) -> dict[str, Any]:
        return judge(product, deal_price, was_price, shop, price_history, offers or {})

    return server


if __name__ == "__main__":
    build_server().run("stdio")
