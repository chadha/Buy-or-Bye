---
name: idealo-connect
description: Connect the real idealo MCP - map its tools, record fixtures, implement the adapter with tests. Use on hackathon day once IDEALO_MCP_URL is known.
---
1. Use the `data-scout` subagent to map the idealo MCP tools and record one trimmed response
   per tool into `tests/fixtures/idealo/` and `docs/idealo-mcp.md`.
2. Write a failing test in `tests/test_idealo.py` that loads those recorded responses and
   expects a `ProductData` with history (oldest first, daily lowest price) and current offers.
3. Implement `IdealoMCPSource._to_product` (and `find` if the search needs two calls) in
   `app/sources.py` until the test passes. Put the `IDEALO_TOOL_*` names in `.env.example`.
4. Run `PRICE_SOURCE=idealo make dev` and check one real product end to end.
5. Report which SPEC checks the real data supports and which it doesn't.
