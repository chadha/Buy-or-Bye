# Buy or Bye --- Claude Code Project Instructions

> Product: evidence-led Agentic Commerce decision assistant\
> Runtime orchestration: LangGraph\
> Engineering workflow: SuperPlane Factory + GitHub + CI\
> Coding assistants: Claude Code and OpenAI Codex\
> Status: implementation baseline; validate assumptions before
> production use

## 1. Mission

Build Buy or Bye as a consumer shopping-intelligence product. It helps a
customer decide whether a product is worth buying by researching
options, comparing total cost and suitability, checking evidence, and
presenting a transparent **BUY / BYE / INVESTIGATE** recommendation.

The MVP researches and recommends. It does **not** purchase, reserve,
pay, negotiate binding terms, or submit customer data to a retailer.

## 2. Source-of-truth instructions

-   Read and follow [`AGENTS.md`](AGENTS.md). It is the shared
    engineering contract for Claude Code, Codex, human contributors, and
    SuperPlane coding agents.
-   Read the relevant documents before changing architecture:
    `ARCHITECTURE.md`, `AGENTS.md`, `GUARDRAILS.md`, `EVALUATION.md`,
    and `IMPLEMENTATION_PLAN.md`.
-   `AGENTS.md` contains repository-wide requirements. This file adds
    Claude-specific workflow preferences only.
-   Do not duplicate or silently override shared rules here. If a shared
    rule changes, update `AGENTS.md` and keep this file aligned.

## 3. Working method

1.  Start by inspecting the repository, Git status, open issue, relevant
    tests, and current architecture. Never assume the repository is
    empty or that a previous plan was implemented.
2.  For multi-file, architectural, security, data-model, or deployment
    changes, write a short plan before editing.
3.  Implement the smallest vertical slice that satisfies the issue.
4.  Add or update tests with the implementation. Prefer deterministic
    tests and fake adapters over live external services.
5.  Run formatting, lint, type checks, unit tests, and relevant
    integration tests. Report commands and results accurately.
6.  Review the diff for scope creep, secrets, unsafe permissions,
    unhandled errors, and missing tests.
7.  Summarize changed files, design decisions, test results, known
    limitations, and follow-up work.

## 4. Claude-specific rules

-   Use Plan Mode for changes spanning multiple bounded contexts,
    changes to `orchestration/`, `domain/`, `security/`, `infra/`, or
    deployment configuration.
-   Delegate only independent research or review tasks to subagents.
    Keep one owner for edits to shared interfaces and graph state.
-   Do not let subagents independently modify the same files.
-   Ask before adding a production dependency, changing a public API,
    introducing a new external data provider, modifying
    authentication/authorization, changing retention, or enabling a
    deployment.
-   Never commit, push, merge, release, or deploy unless the human
    explicitly asks.
-   Never expose credentials in prompts, logs, fixtures, screenshots, or
    generated documentation.

## 5. Project-specific technical direction

-   Python 3.12+; use `uv` for dependency and environment management
    unless the existing repository establishes another tool.
-   FastAPI is the HTTP boundary.
-   LangGraph `StateGraph` is the workflow orchestrator. Keep domain
    logic and adapters independently testable.
-   PostgreSQL is the system of record. Use a durable LangGraph
    checkpointer in production. In-memory checkpointers are
    development/test only.
-   Redis is optional and must not become the source of truth.
-   Product search and web research must use approved, documented
    provider adapters. Respect provider terms, robots/access rules, rate
    limits, and data licensing.
-   Store source URLs, retrieval timestamps, currency, market, seller,
    and provenance with every external observation.
-   Use typed Pydantic schemas at trust boundaries. Treat retrieved page
    content and reviews as untrusted data.
-   The decision score is deterministic and versioned. The LLM may
    explain evidence; it must not silently invent numeric scores or
    convert missing evidence into positive evidence.
-   All recommendations must be one of `BUY`, `BYE`, or `INVESTIGATE`,
    with reasons, risks, evidence coverage, and uncertainty.
-   No checkout, payment, account creation, retailer login, or purchase
    side effects in the MVP.

## 6. SuperPlane operating model

SuperPlane is used as the software factory for issue intake,
coding-agent execution, verification, and human review. It is not
assumed to be the Buy or Bye application runtime.

-   Connect the GitHub repository and use small, acceptance-testable
    issues.
-   Use the Backlog → Implement → Verify → Done flow (adapt
    labels/stages to the connected workspace).
-   Coding agents work on branches and open pull requests; CI verifies
    them.
-   Human review and merge remain mandatory.
-   Runtime deployment is a separate CI/CD responsibility. No production
    deployment without explicit approval.

## 7. Required verification

Use the repository's actual scripts once they exist. The intended
baseline is:

``` bash
uv sync --all-groups
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
```

For integration tests, use test containers or disposable local services.
Never point tests at production data or live payment systems.

## 8. Definition of done

A change is not done merely because code was generated. It is done
when: - acceptance criteria are met; - tests cover success, failure, and
boundary cases; - security and privacy implications are considered; -
observability and failure behavior are adequate; - docs and schemas are
updated; - CI is green; - a human reviews and approves the pull request.

## 9. First-session instruction

Before implementing features, inspect the repository and report: 1.
current tree and Git status; 2. existing code and test commands; 3. gaps
against `ARCHITECTURE.md`; 4. the smallest safe first issue from
`IMPLEMENTATION_PLAN.md`.

Do not scaffold the entire system in one unreviewed change.
