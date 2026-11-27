# Buy or Bye --- Architecture Decision Baseline

**Status:** Proposed baseline for MVP\
**Product:** Evidence-led Agentic Commerce decision assistant\
**Orchestration:** LangGraph\
**API:** FastAPI\
**Engineering factory:** SuperPlane + GitHub + CI\
**Runtime hosting:** Not selected; SuperPlane is not assumed to host the
application runtime.

## 1. Product scope

### Problem

Consumers face too many product choices, inconsistent specifications,
opaque discounts, mixed-quality reviews, and uncertainty about whether a
product is good value for their needs.

### MVP outcome

Given a shopping request, Buy or Bye: 1. extracts budget, market, use
case, must-have criteria and preferences; 2. retrieves candidates from
approved sources; 3. normalizes product and price facts; 4. compares
candidate suitability and total known cost; 5. checks evidence
provenance, freshness and conflicts; 6. applies a deterministic,
versioned decision policy; 7. presents BUY / BYE / INVESTIGATE with
evidence, risks and uncertainty.

### Explicit non-goals

No checkout, payment, retailer login, order placement, automatic
negotiation, browser automation that bypasses provider rules, purchase
of restricted goods, or autonomous post-purchase actions. No promise of
guaranteed lowest price. No claim that reviews prove product quality.

## 2. System context

``` mermaid
flowchart TD
    U[Consumer] --> UI[Web / Mobile UI]
    UI --> API[FastAPI API]
    API --> AUTH[Identity and authorization]
    API --> G[LangGraph workflow]
    G --> PLAN[Shopping Planner]
    G --> RET[Product Research]
    G --> PRICE[Price Intelligence]
    G --> ANALYST[Product Analyst]
    G --> TRUST[Trust and Evidence]
    G --> DECIDE[Decision Advisor]
    RET --> ADAPTERS[Approved provider adapters]
    PRICE --> ADAPTERS
    ANALYST --> DB[(PostgreSQL)]
    TRUST --> DB
    G --> CP[(LangGraph checkpointer)]
    API --> DB
    G --> OBS[Tracing, metrics, audit]
    ADAPTERS --> EXT[Retailer / catalog / search APIs]
    DECIDE --> API
    API --> UI
```

## 3. Deployment topology

``` mermaid
flowchart LR
    subgraph Factory["Engineering control plane"]
      SP[SuperPlane Factory]
      GH[GitHub]
      CI[CI checks]
      PR[Pull request + human review]
      SP --> GH --> CI --> PR
    end
    subgraph Runtime["Application runtime - provider TBD"]
      EDGE[HTTPS ingress]
      APP[FastAPI + LangGraph workers]
      PG[(Managed PostgreSQL)]
      CACHE[(Optional Redis)]
      TELE[Telemetry backend]
      EDGE --> APP
      APP --> PG
      APP --> CACHE
      APP --> TELE
    end
    PR -->|approved merge triggers controlled release pipeline| EDGE
```

SuperPlane coordinates software delivery: issue intake, coding-agent
execution, checks, feedback and review. The application runtime is a
separate concern. Select a runtime provider, region, networking, secret
store, database offering, backup policy and deployment method before
production.

## 4. Recommended MVP technology

  -----------------------------------------------------------------------
  Concern                 Baseline                Notes
  ----------------------- ----------------------- -----------------------
  Language                Python 3.12+            Confirm repository
                                                  baseline

  Package manager         uv                      Lock dependencies

  API                     FastAPI                 Versioned REST
                                                  endpoints

  Validation              Pydantic v2             Typed boundaries

  Orchestration           LangGraph StateGraph    Explicit nodes and
                                                  edges

  Database                PostgreSQL              System of record

  Checkpointing           LangGraph Postgres      Durable state in
                          checkpointer            production

  Cache                   Redis, optional         Never source of truth

  Search                  Approved APIs/adapters  Provider compliance
                                                  required

  Observability           OpenTelemetry + chosen  Avoid vendor lock-in
                          trace backend            

  Tests                   pytest                  Unit, integration,
                                                  contract, adversarial

  CI                      GitHub Actions or       SuperPlane consumes
                          existing CI             verification results

  Packaging               Docker                  Immutable image

  Runtime                 TBD                     Not implied by
                                                  SuperPlane Cloud
  -----------------------------------------------------------------------

Do not add Qdrant or a vector database until an evaluated
semantic-retrieval requirement exists. Product attributes and price
facts should be queryable as structured data first.

## 5. Domain model

Core entities: - `ShoppingSession`: user-owned workflow and status. -
`ShoppingIntent`: category, query, budget, currency, market, use cases,
must-haves, preferences. - `Product`: normalized product identity and
category. - `ProductCandidate`: candidate product as observed from a
provider. - `PriceObservation`: amount, currency, seller, shipping/tax
inclusion, market, source and observed time. - `ProductAttribute`:
normalized attribute with value, unit, source and confidence/status. -
`Evidence`: claim, source URL, source type, retrieved time, status and
excerpt/reference. - `ProductAssessment`: fit against explicit criteria,
unknowns and risks. - `Recommendation`: decision, score (optional),
evidence coverage, reasons, risks, confidence, policy version. -
`AuditEvent`: actor, action, resource, timestamp, policy and correlation
IDs.

Use UUID/ULID identifiers internally. Use `Decimal` for money. Store raw
provider IDs in separate fields. All times are UTC.

## 6. Workflow design

``` mermaid
flowchart TD
    A[Request] --> B[Validate and parse intent]
    B --> C{Critical details missing?}
    C -->|Yes| D[Ask user to clarify]
    D --> B
    C -->|No| E[Retrieve candidates]
    E --> F[Normalize and deduplicate]
    F --> G[Price analysis]
    F --> H[Product fit analysis]
    G --> I[Evidence verification]
    H --> I
    I --> J{Evidence policy satisfied?}
    J -->|No| K[Investigate / mark unknown]
    K --> L[Decision policy]
    J -->|Yes| L
    L --> M[Decision report]
    M --> N[Human review / feedback]
```

### Nodes and ownership

  -------------------------------------------------------------------------
  Node                      Responsibility          Side effects
  ------------------------- ----------------------- -----------------------
  `validate_intent`         Validate schema and     None
                            required fields         

  `plan_research`           Select                  None
                            category-specific       
                            search plan             

  `retrieve_products`       Call approved read-only External reads
                            adapters                

  `normalize_candidates`   Normalize, deduplicate, DB upsert
                            validate                

  `analyze_prices`          Calculate known total   DB upsert
                            cost                    

  `assess_product_fit`      Map evidence to user    DB upsert
                            criteria                

  `verify_evidence`         Check provenance,       DB upsert
                            freshness, conflicts    

  `apply_decision_policy`   Deterministic scoring   DB write
                            and outcome             

  `present_report`          Produce customer-facing None
                            report                  

  `collect_feedback`        Store optional user     DB write
                            feedback                
  -------------------------------------------------------------------------

Parallel price and fit analysis is allowed after normalized candidate
retrieval. Provider calls must have concurrency and rate limits.

## 7. Agent design

Agents are bounded reasoning modules, not autonomous administrators.
They receive typed input, use allowlisted read-only tools, return typed
output, and cannot grant themselves permissions.

1.  **Shopping Planner:** creates a structured plan and asks for
    clarification when budget, market or core requirements are missing.
2.  **Product Researcher:** searches authorized catalogs and returns
    candidates with source provenance.
3.  **Price Intelligence:** normalizes price, shipping, fees, currency,
    seller, market and observation time. Price history is optional and
    must be sourced.
4.  **Product Analyst:** evaluates fit against the customer's explicit
    requirements; unknown attributes remain unknown.
5.  **Trust & Evidence:** assesses source quality, freshness,
    contradictions and prompt-injection indicators.
6.  **Decision Advisor:** calls deterministic scoring/policy code and
    explains the returned result. It cannot override the policy result.

## 8. Decision policy

Initial weights are product hypotheses, not facts from the source book.
Keep them in versioned configuration and validate with user research and
expert-labeled test cases.

  Dimension                          Initial weight
  -------------------------------- ----------------
  Product suitability                           35%
  Price and value                               25%
  Quality evidence                              20%
  Explicit customer requirements                15%
  Seller/service reliability                     5%

Score only dimensions with sufficient evidence, or use an explicit
missing-data strategy. Do not silently renormalize without recording the
method. Calculate evidence coverage separately.

Decision outcomes: - `BUY`: no hard constraint violated, minimum
evidence gate passed, value policy satisfied. - `BYE`: hard requirement
violated or a clearly superior alternative is supported by evidence. -
`INVESTIGATE`: insufficient evidence, material conflict, stale price,
unknown must-have attribute, or ambiguous request.

The decision report must include policy version, score method, evidence
coverage, source list, risks and reasons. The system must not claim a
guaranteed best price.

## 9. Persistence and memory

-   PostgreSQL stores users, sessions, normalized product facts,
    observations, evidence, recommendations, audit events and workflow
    metadata.
-   LangGraph checkpointer stores thread-scoped execution state. Use
    durable PostgreSQL-backed checkpointing in production.
-   Long-term user preferences require explicit product design, consent,
    retention and deletion behavior. Do not conflate checkpointer state
    with user profile memory.
-   Keep graph state compact. Store references/IDs rather than full web
    pages or unbounded transcripts.
-   Enforce user/tenant ownership before any state read, update or
    resume.
-   Define retention and deletion jobs before launch.

## 10. API surface (proposed)

-   `POST /v1/shopping-sessions` --- create a session and start
    research.
-   `GET /v1/shopping-sessions/{session_id}` --- retrieve status/report
    after ownership check.
-   `POST /v1/shopping-sessions/{session_id}/clarifications` --- provide
    missing intent details.
-   `POST /v1/shopping-sessions/{session_id}/feedback` --- submit
    optional feedback.
-   `GET /health/live` --- process liveness.
-   `GET /health/ready` --- dependency readiness.

Use request IDs and idempotency keys for create/resume operations. Do
not expose internal graph state or provider secrets.

## 11. Failure handling and resilience

-   Provider timeouts and bounded retries with jitter for retryable
    failures.
-   Circuit breakers and per-provider rate limits.
-   Partial-result behavior must clearly identify missing providers and
    evidence gaps.
-   Do not retry non-idempotent writes without idempotency keys.
-   Persist workflow status and failure reason; allow safe resume.
-   Fail closed when policy checks cannot run.
-   Set per-session time, token, tool-call, result-count and cost
    budgets.
-   Use structured errors and redacted logs.

## 12. Observability

Every run has `request_id`, `session_id`, `thread_id`,
`user/tenant reference`, graph version, policy version and
model/provider metadata. Do not put direct identifiers or sensitive data
into trace attributes unnecessarily.

Metrics: - workflow success/failure and stage latency; - provider
availability, latency, rate-limit and error counts; - products retrieved
and valid candidate ratio; - source freshness and evidence coverage; -
recommendation distribution and human override rate; - tokens, model
cost and cost per completed session; - retry count, checkpoint/resume
failures and timeout rate.

Logs must be structured and redacted. Audit events are append-only from
the application perspective.

## 13. Security architecture

-   OIDC/session-based authentication at API boundary.
-   Authorization on every session and preference query.
-   Secrets in a managed secret store; never in repository or graph
    state.
-   Egress allowlist for provider adapters; SSRF protection and URL
    validation.
-   Treat retrieved content as hostile data. It cannot change system
    instructions or call tools.
-   No shell/browser/payment capability for business agents.
-   Dependency scanning, image scanning, secret scanning and
    least-privilege CI tokens.
-   Encrypt in transit and at rest.
-   Document incident response, backup/restore and credential rotation.

## 14. SuperPlane integration

Use SuperPlane as the engineering workflow control plane: 1. Connect a
GitHub repository with least-privilege permissions. 2. Import or create
small, well-defined GitHub issues. 3. Configure coding-agent provider(s)
and scoped GitHub credentials. 4. Use Backlog → Implement → Verify →
Done stages or their workspace equivalents. 5. Run CI checks on each PR.
6. Send failed check details back for bounded agent repair attempts. 7.
Require human review and merge approval. 8. Keep deployment approval
separate from PR verification.

Do not assume SuperPlane runs the FastAPI/LangGraph production service.
Runtime deployment needs its own target and pipeline.

## 15. Architecture decisions to validate

-   Runtime hosting provider and EU region.
-   Identity provider and account model.
-   First product categories and permitted data sources.
-   Data provider terms, price freshness and attribution.
-   Whether Redis is needed.
-   Whether a vector database is justified by retrieval evaluations.
-   Data retention and user preference consent.
-   Model provider, fallback and cost limits.
-   Product scoring thresholds from a labeled evaluation set.
