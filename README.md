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
