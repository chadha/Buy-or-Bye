# Buy or Bye --- Implementation Plan

**Execution model:** small GitHub issues, implemented through SuperPlane
Factory, verified by CI, reviewed by a human.\
**Runtime:** separate from SuperPlane; select hosting before production
deployment.\
**Primary outcome:** a read-only, evidence-backed shopping
recommendation workflow.

## 1. Delivery strategy

Build a modular monolith and one end-to-end vertical slice. Do not build
six autonomous agents, a vector database, a payment layer, or a
microservice fleet before proving the first workflow.

Each issue must include: - user/problem context; - scope and
non-goals; - acceptance criteria; - test plan; - security/privacy
impact; - dependencies; - rollback/disable behavior.

## 2. Milestones

### M0 --- Repository and delivery foundation

Tasks: - inspect existing repository and preserve working code; -
establish Python and `uv` baseline; - create shared `AGENTS.md` and
`CLAUDE.md`; - establish branch protection and PR template; - add CI for
lint, format, type check and tests; - add Docker Compose for local
PostgreSQL; - connect GitHub repository to SuperPlane; - configure
coding-agent integrations with least privilege; - configure Backlog →
Implement → Verify → Done (or workspace-equivalent) workflow.

Acceptance: - clean clone can install and run checks; - CI is green; -
SuperPlane can ingest a small issue and create a reviewable PR; - human
review remains required; - no production environment or deployment is
connected by default.

### M1 --- Domain and API skeleton

Tasks: - create Pydantic domain schemas; - use Decimal for money; -
create database migrations and repository interfaces; - implement health
endpoints; - implement session create/read with ownership checks; - add
request IDs and idempotency behavior.

Acceptance: - schema tests and API contract tests pass; - cross-user
session access is denied; - no secrets appear in logs.

### M2 --- First LangGraph vertical slice

Tasks: - define serializable `ShoppingState`; - implement
`validate_intent`; - implement `plan_research`; - implement fake product
search adapter; - implement `normalize_candidates`; - compile graph with
in-memory checkpointer for local tests only; - expose
`POST /v1/shopping-sessions`.

Acceptance: - a test request produces normalized candidates; - graph
transitions are deterministic; - invalid or ambiguous requests request
clarification or return validation errors; - all external calls are
mocked.

### M3 --- Price and product assessment

Tasks: - implement approved provider adapter interface; - implement
price normalization with Decimal; - represent shipping, tax, currency,
market and timestamp explicitly; - implement product-fit assessment
against explicit criteria; - add duplicate detection and conflict
representation.

Acceptance: - arithmetic and currency tests pass; - unknown fields
remain unknown; - stale prices are labeled; - provider timeout yields
safe partial results.

### M4 --- Evidence and decision policy

Tasks: - define evidence schema and source-quality metadata; - implement
Trust & Evidence checks; - implement prompt-injection isolation tests; -
implement deterministic, versioned score and decision policy; -
implement BUY / BYE / INVESTIGATE report; - disclose affiliate/sponsored
status where applicable.

Acceptance: - every material factual claim has source provenance or is
labeled unverified; - decision tests cover all boundaries; - LLM cannot
override policy; - insufficient evidence results in INVESTIGATE or a
clear failure.

### M5 --- Durable workflow and observability

Tasks: - add PostgreSQL-backed LangGraph checkpointer; - add thread
ownership and safe resume; - add LangGraph interrupt for user
clarification/review; - add OpenTelemetry tracing and structured
redacted logs; - add provider timeouts, bounded retries, rate limits and
circuit breakers; - add retention policy and checkpoint cleanup design.

Acceptance: - workflow resumes after process restart in integration
test; - retries are idempotent; - trace links
request/session/graph/policy versions without sensitive payloads; -
retention and deletion behavior documented.

### M6 --- Evaluation and product experience

Tasks: - create 100+ scenario golden dataset; - implement component and
end-to-end evaluation; - build decision board UI/API response; - collect
optional user feedback; - run human review and calibrate
thresholds/weights; - measure cost and latency.

Acceptance: - `EVALUATION.md` initial gates are measured; - no critical
safety failures; - decision report explains evidence, uncertainty and
risks; - no purchase capability exists.

### M7 --- Staging and production readiness

Tasks: - choose runtime host and EU region; - define network, secrets,
database, backup, monitoring and deployment; - build immutable container
image; - run dependency/image/secret scans; - test backup restore and
rollback; - conduct threat model and privacy review; - configure staged
release with human approval.

Acceptance: - staging is isolated from production; - production release
has explicit approval; - runbook, incident response, SLOs and ownership
exist; - no unapproved external side effects.

## 3. First 10 GitHub issues

1.  `chore: establish Python project, uv lockfile and CI`
2.  `docs: add shared agent instructions and architecture baseline`
3.  `feat(domain): add typed shopping intent and product schemas`
4.  `feat(api): add health endpoints and session API skeleton`
5.  `feat(orchestration): add serializable LangGraph state and graph shell`
6.  `feat(tools): add fake product search adapter and provider interface`
7.  `feat(orchestration): implement intent validation and clarification path`
8.  `feat(domain): normalize product candidates and price observations`
9.  `feat(decision): implement evidence-aware BUY/BYE/INVESTIGATE policy`
10. `test(eval): add first 25 golden shopping scenarios and safety cases`

Keep each issue small enough for a single focused PR. Split if the
implementation touches multiple unrelated bounded contexts.

## 4. SuperPlane setup

1.  Create/choose the SuperPlane workspace.
2.  Connect the Buy or Bye GitHub repository with only required
    repository permissions.
3.  Confirm issues can be imported into the backlog.
4.  Configure the selected coding agent/model source(s) and secrets
    through SuperPlane's secret/integration settings.
5.  Configure the factory line to implement tasks on branches and open
    PRs.
6.  Configure Verify to run the repository's CI checks.
7.  Configure failed-check feedback with bounded repair attempts.
8.  Require human PR review and merge approval.
9.  Keep production deployment disconnected until M7 and explicitly
    approved.

SuperPlane's exact component names, configuration fields and available
integrations may change. Follow the current workspace UI and official
documentation; do not invent an undocumented workflow YAML.

## 5. Claude Code + Codex collaboration

-   `AGENTS.md` is the canonical shared instruction file.
-   `CLAUDE.md` contains Claude-specific additions and points
    contributors to `AGENTS.md`.
-   Claude Code and Codex should work on separate issues/branches, not
    simultaneously edit the same working tree.
-   Use GitHub issues as task contracts and PRs as review boundaries.
-   Assign one human/agent owner for changes to shared schemas, graph
    state, decision policy and migrations.
-   Require each assistant to report changed files, tests executed,
    assumptions and remaining risks.
-   Do not let either assistant approve its own PR or deploy.

Suggested division: - Claude Code: implementation slice or refactoring
 task. - Codex: independent review, test gap analysis, threat review or
 separate issue. - Human: architecture decisions, merge approval,
 provider approval and release authorization.

## 6. Local developer commands

These are the intended commands; adapt to actual scripts once the
repository exists.

``` bash
# Install
uv sync --all-groups

# Start local dependencies
docker compose up -d postgres

# Quality checks
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q

# Run API (once app entry point exists)
uv run uvicorn app.main:app --reload

# Stop local dependencies
docker compose down
```

Do not claim a command works until it has been verified in the
repository.

## 7. Release and change controls

-   Feature branches only; protect the default branch.
-   CI required before merge.
-   Human review required before merge.
-   Human approval required before staging/production deployment.
-   Database migrations require forward and rollback notes.
-   Scoring changes require evaluation comparison and policy version
    bump.
-   Provider changes require terms, rate limits, data fields and
    freshness review.
-   Model changes require regression and cost/latency evaluation.
-   Any transaction feature requires a new architecture/security review
    and explicit product approval.

## 8. Risks and dependencies

  -----------------------------------------------------------------------
  Risk                                Mitigation
  ----------------------------------- -----------------------------------
  Product data unavailable or         Start with mock adapters; verify
  restricted                          provider rights before integration

  Prices stale or incomplete          Timestamp observations and expose
                                      unknowns

  LLM hallucinations                  Typed outputs, evidence gates and
                                      deterministic policy

  Prompt injection                    Untrusted-content isolation and
                                      adversarial tests

  Scope creep into checkout           Keep transaction tools absent from
                                      MVP

  SuperPlane confused with runtime    Separate factory control plane from
                                      app hosting

  Two coding agents conflict          Separate issues/branches and assign
                                      file ownership

  Cost/latency grows                  Budgets, traces, caching and
                                      measured limits

  User preferences create privacy     Minimize, consent, retention and
  risk                                deletion
  -----------------------------------------------------------------------

## Feature work: BOB-URL-001 (URL-to-Product Intelligence)

In progress on the demo slice in `app/`. Decisions (Decimal money, additive versioned APIs,
guarded idealo `get_product_details`), stages M1–M6 and acceptance criteria are in
[`docs/bob-url-001.md`](docs/bob-url-001.md). Those stage names are scoped to the feature and
are separate from the milestones above.

## 9. Immediate next action

Start with M0 only. Inspect the existing Buy or Bye repository and
current code before scaffolding. Create the first issue, connect
SuperPlane to GitHub, and validate one small
issue-to-PR-to-CI-to-human-review loop. Do not deploy.
