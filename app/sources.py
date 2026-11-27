"""Where price data comes from. The rest of the app only sees the PriceSource protocol.

* DemoSource: synthetic products in `app/demo_data.json`, clearly labelled "demo" in the UI.
* IdealoMCPSource: the idealo MCP server. Tool names and field mapping are configured from
  `docs/idealo-mcp.md` once the `data-scout` subagent has probed the real server.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date
from importlib import resources
from typing import Any, Protocol

from .models import Offer, PricePoint, ProductData


class SourceError(RuntimeError):
    """The data source failed or is not configured. The API reports it; it never guesses."""


class PriceSource(Protocol):
    name: str

    async def find(self, query: str) -> ProductData | None: ...


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 1}


class DemoSource:
    name = "demo"

    def __init__(self, data: list[dict[str, Any]] | None = None) -> None:
        if data is None:
            raw = resources.files("app").joinpath("demo_data.json").read_text()
            data = json.loads(raw)["products"]
        self._products = [ProductData(**p) for p in data]

    async def find(self, query: str) -> ProductData | None:
        q = _tokens(query)
        if not q:
            return None
        best, best_score = None, 0.0
        for p in self._products:
            score = len(q & _tokens(p.name)) / len(_tokens(p.name))
            if score > best_score:
                best, best_score = p, score
        return best if best_score >= 0.6 else None


class IdealoMCPSource:
    """Adapter for the idealo MCP server (streamable HTTP).

    Map tool names with env vars once known: IDEALO_TOOL_SEARCH, IDEALO_TOOL_HISTORY,
    IDEALO_TOOL_OFFERS. `_to_product` is the single place that converts idealo's response
    shape into ProductData; fill it from docs/idealo-mcp.md, with a recorded fixture test.
    """

    name = "idealo"

    def __init__(self, url: str | None = None) -> None:
        self.url = url or os.environ.get("IDEALO_MCP_URL", "")
        self.tools = {
            k: os.environ.get(f"IDEALO_TOOL_{k.upper()}", "")
            for k in ("search", "history", "offers")
        }

    async def _call(self, tool: str, args: dict[str, Any]) -> Any:
        try:
            from mcp import ClientSession
            from mcp.client import streamable_http as transport
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise SourceError("install the idealo extra: pip install -e '.[idealo]'") from exc
        # The SDK renamed the client between versions; accept either name.
        client = getattr(transport, "streamable_http_client", None) or getattr(
            transport, "streamablehttp_client", None
        )
        if client is None:  # pragma: no cover
            raise SourceError("unsupported mcp SDK version")
        async with client(self.url) as streams:
            session = ClientSession(streams[0], streams[1])
            async with session:
                await session.initialize()
                result = await session.call_tool(tool, args)
        if getattr(result, "isError", False):
            raise SourceError(f"idealo tool {tool} returned an error")
        structured = getattr(result, "structuredContent", None)
        if structured is not None:
            return structured
        texts = [c.text for c in getattr(result, "content", []) if getattr(c, "text", None)]
        try:
            return json.loads(texts[0]) if texts else None
        except ValueError as exc:
            raise SourceError(f"idealo tool {tool} returned non-JSON content") from exc

    async def find(self, query: str) -> ProductData | None:
        if not self.url or not all(self.tools.values()):
            raise SourceError(
                "idealo MCP not configured: set IDEALO_MCP_URL and IDEALO_TOOL_* "
                "(see docs/idealo-mcp.md)"
            )
        found = await self._call(self.tools["search"], {"query": query})
        return self._to_product(found) if found else None

    @staticmethod
    def _to_product(raw: Any) -> ProductData:
        # Filled in on the day from the real response shape (docs/idealo-mcp.md).
        raise SourceError(
            "idealo response mapping not implemented yet: run the data-scout "
            "subagent, then implement IdealoMCPSource._to_product with a test"
        )


def make_source() -> PriceSource:
    return IdealoMCPSource() if os.environ.get("PRICE_SOURCE") == "idealo" else DemoSource()


def history_from_pairs(pairs: list[tuple[str, float]]) -> list[PricePoint]:
    return [PricePoint(day=date.fromisoformat(d), price=p) for d, p in pairs]


def offers_from_pairs(pairs: list[tuple[str, float]]) -> list[Offer]:
    return [Offer(merchant=m, price=p) for m, p in pairs]
