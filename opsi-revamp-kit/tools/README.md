# Tools

## `kb/ask.py` - ask the kit anything, offline
Pure-Python BM25 search over every doc/config/script in the kit, returning ranked passages with `file:line`.
```bash
python3 tools/kb/ask.py "how do I rotate the dynatrace oauth secret"
python3 tools/kb/ask.py --top 10 "RUN_ERROR llm_unavailable"
python3 tools/kb/ask.py --list-topics | grep -i openmetadata
python3 tools/kb/ask.py --llm "why does the runtime return 401"     # optional: answer via corporate Portkey -> Bedrock
```
`--llm` sends only the retrieved kit passages + your question (env `PORTKEY_API_KEY`, `PORTKEY_BASE_URL`,
`PORTKEY_PROVIDER`/`PORTKEY_CONFIG`, `LLM_MODEL`). Use only if the gateway is approved for this purpose.
Synonyms understood: om=openmetadata, dt=dynatrace, es=elasticsearch, pg=postgresql, ck=copilotkit, rls, sso.

## `redact_file.py` - prepare fixtures
`python3 tools/redact_file.py capture.json > services/ingestion/fixtures/new.json` - same rules as the collectors;
review by hand afterwards (hostnames/ids/names are not removed automatically).
