.PHONY: dev check demo data idealo-login live mcp
dev:
	uvicorn app.main:app --reload --port 8000
check:
	ruff check . && ruff format --check . && mypy && pytest -q
demo:
	python -m app.demo
data:
	python scripts/make_demo_data.py

idealo-login:  ## sign in to idealo once (opens a browser) and probe one product
	python -m app.idealo_auth "$(or $(Q),sony wh-1000xm5)"

live:  ## run the app on live idealo data
	PRICE_SOURCE=idealo uvicorn app.main:app --reload --port 8000

mcp:  ## run Buy or Bye as an MCP server over stdio (for Claude Desktop)
	PRICE_SOURCE=idealo python -m app.mcp_server
