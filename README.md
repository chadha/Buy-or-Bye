# Buy or Bye



https://github.com/user-attachments/assets/f665af60-bb86-4c2e-82c1-a497af08e85c



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

Live data: set `PRICE_SOURCE=idealo` and `IDEALO_MCP_URL` (see `.env.example` and
`docs/idealo-mcp.md`). The idealo field mapping in `app/sources.py` is intentionally not
implemented until real responses are recorded.

Relation to the plan: this slice uses `app/` instead of the `api/` / `domain/` /
`orchestration/` layout in `AGENTS.md`, and has no LangGraph or PostgreSQL yet. Moving it
into that layout is follow-up work (M1-M2 in `IMPLEMENTATION_PLAN.md`).
