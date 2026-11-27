# Buy or Bye --- Engineering Harness

This folder contains the initial engineering contract for a
production-oriented, read-only Agentic Commerce MVP.

## Files

- `CLAUDE.md` --- Claude Code project instructions.
- `AGENTS.md` --- shared instructions for Codex, Claude Code,
  SuperPlane agents and humans.
- `ARCHITECTURE.md` --- system boundaries, workflow, data model and
  deployment topology.
- `GUARDRAILS.md` --- security, privacy, tool permissions and human
  approvals.
- `EVALUATION.md` --- metrics, golden dataset, adversarial tests and
  release gates.
- `IMPLEMENTATION_PLAN.md` --- staged roadmap, first issues and
  SuperPlane setup.
- `README.md` --- package index.

## Install in repository

Copy these files into the root of the Buy or Bye Git repository. Keep
`AGENTS.md` at repository root. Keep `CLAUDE.md` at repository root.

Claude Code reads `CLAUDE.md`; Codex reads `AGENTS.md`. Both are
instructed to follow the same shared contract.

## Important architecture distinction

SuperPlane is the engineering software factory coordinating backlog
work, coding agents, CI and human review. It is not assumed to host the
Buy or Bye FastAPI/LangGraph runtime. Select and configure the
application runtime separately.

## First action

Inspect the actual repository and Git status. Start with M0 in
`IMPLEMENTATION_PLAN.md`. Do not scaffold or deploy the entire product
in one step.

## Hackathon demo app (runnable today)

A first vertical slice of Buy or Bye lives in `app/`: a mobile-first web app that checks
one discount claim against price history and returns **BUY / BYE / WAIT / NOT ENOUGH DATA**,
with the evidence behind every reason. The label is decided by code (`app/verdict.py`), never
by an LLM. Rules for this slice: `docs/DEMO_APP.md`. Spec: `docs/SPEC.md`.

```bash
pip install -e ".[dev]"
make dev      # http://localhost:8000, fictional demo data (labelled in the UI)
make check    # ruff + mypy + pytest
make demo     # the five demo deals with their expected labels
```

### Live idealo data
```bash
pip install -e ".[dev,idealo]"
make idealo-login Q="sony wh-1000xm5"   # browser sign-in once, then probes one product
make live                              # the web app on live idealo data
```
Mapping and limits: `docs/idealo-mcp.md`. In live mode a pasted product link goes through
`POST /api/v1/product-url/check` (identity, idealo match, provenance, verdict): see
`docs/bob-url-001.md`. idealo calls are capped per day (`IDEALO_DAILY_LIMIT`, max 500).

### Buy or Bye inside Claude (conversational commerce)
Run Buy or Bye as an MCP server so Claude can answer "is this discount real?" in a chat.
The label still comes from `app/verdict.py`; Claude only explains it.
Add to Claude Desktop's `claude_desktop_config.json` (use the Python where you installed the repo):
```json
{
  "mcpServers": {
    "buy-or-bye": {
      "command": "/full/path/to/python",
      "args": ["-m", "app.mcp_server"],
      "env": { "PRICE_SOURCE": "idealo" }
    }
  }
}
```
Tools: `check_deal` (fetches idealo itself; run `make idealo-login` first) and `judge_deal`
(Claude passes the responses it already got from the idealo connector).

Relation to the plan: this slice uses `app/` instead of the `api/` / `domain/` /
`orchestration/` layout in `AGENTS.md`, and has no LangGraph or PostgreSQL yet. Moving it
into that layout is follow-up work (M1-M2 in `IMPLEMENTATION_PLAN.md`).
