# Decision trees

## Which auth mode for the API modules?
```
Does Opsi already authenticate API requests (session cookie or bearer)?
├─ yes -> can I call its "current user" logic from a FastAPI dependency?
│        ├─ yes -> OPSI_AUTH_MODE=existing (write the adapter, consultation 07)
│        └─ no  -> does the SPA have an OIDC access token for an API audience?
│                 ├─ yes -> OPSI_AUTH_MODE=oidc
│                 └─ no  -> register an API audience in the IdP first (blocker)
└─ no  -> OPSI_AUTH_MODE=oidc (plus SPA login flow) - plan with the IAM team
```

## Forward cookie or bearer through the runtime?
```
SPA keeps an access token in memory/JS?  -> bearer via provider headers (default allowlist)
Session is an HttpOnly cookie?            -> add "cookie" to RUNTIME_FORWARD_HEADERS and RUNTIME_REQUIRE_AUTH_HEADERS,
                                             existing adapter reads the cookie, keep runtime on loopback
Proxy (oauth2-proxy) authenticates?       -> proxy injects a signed JWT header; forward it; validate in FastAPI
```

## A collector window failed - what now?
```
Error says 401/403/404/400?  -> permanent: fix credentials/scope/URL/query, next run retries automatically
Error transient (5xx/429/network)? -> wait one run; if it persists check egress/proxy/vendor status
WindowTooLarge at minimum split? -> narrow the source filter or raise the cap
Data irrecoverable (retention expired)? -> skip-window with actor + reason + approval
```

## Where should a new piece of data live?
```
Raw event or log line?                    -> S3 bronze (never PostgreSQL)
Aggregated signal per window/service?     -> opsi_ingest curated table
Catalog fact (owner, schema, domain, tag)? -> OpenMetadata (read via API; xref in catalog_xrefs)
Operational relation (calls, affects ...)? -> opsi_knowledge.edges with provenance
Chat/user artefact?                        -> opsi_chat (RLS)
Long text for semantic search (runbook)?   -> opsi_knowledge.documents (pgvector, optional)
Secret?                                    -> Secrets Manager -> rendered env file (never DB/Git)
```

## Which OpenMetadata deployment?
```
Just exploring APIs/UI for a week?     -> dev compose + lab override (isolated host)
Need a demo with release images fast?  -> quickstart compose + an override like the lab one
Shared by a team / real metadata?      -> release images + dedicated RDS (PG>=15) + managed OpenSearch 3.x (template)
On Kubernetes already?                  -> official Helm charts
```

## Should the model get a new tool?
```
Is it read-only and bounded (time window, row cap)?  -> new search route (ADR-0008)
Does it change what the user sees?                    -> UI action (frontend tool), validated (ADR-0013)
Does it change a record anywhere?                     -> approval-gated action + executor with the user's authority
Would it need free-form SQL/DSL/code?                 -> no; design a named template instead
```

## Something leaked (secret/PII seen where it shouldn't be)?
```
In logs/traces?  -> rotate the secret, add a redaction rule + test, purge/expire the telemetry per backend policy
In curated PG?   -> delete rows, fix normaliser/redactor, re-index affected windows
In bronze S3?    -> follow data-handling policy (versioned delete), fix redactor, re-collect if needed
Cross-tenant?    -> platform incident response (runbook): contain (flags off), preserve evidence, notify security
```
