# Synthetic fixtures (no real data)

Every file here is **hand-written synthetic data** shaped like the vendor
responses the adapters were written against (verified docs, October 2026). They
contain no customer data, hostnames, tokens or PII except deliberately fake
"secrets" used to prove redaction works. Test code assembles such values at runtime
(e.g. `"AKIA" + "..."`) so secret scanners do not flag the repository.

| File | Shape of |
|---|---|
| `elastic_hits_page1.json`, `elastic_hits_page2.json` | `_search` responses with `pit_id` + `hits.hits[].sort` |
| `dynatrace_problems_page1.json`, `..._page2.json` | `GET /api/v2/problems` pages with `nextPageKey` |
| `grail_execute_202.json`, `grail_poll_running.json`, `grail_poll_succeeded.json` | Storage Query API execute/poll |

## Replacing with real captures (recommended before production)

1. Capture a response in a **non-production** tenant, e.g.
   `python -m opsi_ingest collect --source dynatrace_problems --dry-run` with
   `--log-level DEBUG` is NOT enough (we never log payloads) - use `curl` and save to a file.
2. Redact it: `python tools/redact_file.py in.json > out.json` and review by hand.
3. Add a contract test asserting the fields the adapter and normalizer depend on.
4. Never commit unredacted captures. CI runs `scripts/secret_scan.sh`.
