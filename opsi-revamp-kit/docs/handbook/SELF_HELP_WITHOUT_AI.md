# Working it out yourself (no assistant available)

A method for questions the docs don't answer, using only the box, the kit and vendor docs.

## 1. Search the kit first
```bash
python3 tools/kb/ask.py "words from your question"          # ranked passages with file:line
grep -rn -i "keyword" docs/ apps/ services/ database/ infrastructure/ | head -50
```

## 2. Read the installed code - it is the ground truth for APIs
```bash
# Python: where is a class/function defined, what are its parameters?
.venv/bin/python -c "import inspect, ag_ui.core as m; print(inspect.signature(m.RunAgentInput))"
.venv/bin/python -c "import portkey_ai, inspect; print(inspect.signature(portkey_ai.AsyncPortkey.__init__))"
.venv/bin/python -m pydoc ag_ui.encoder.EventEncoder
.venv/bin/pip show -f elasticsearch | head -20          # version + files
# JavaScript/TypeScript: read the .d.ts files
grep -rn "interface CopilotKitProviderProps" node_modules/@copilotkit/react-core/dist/ | head
grep -n "export {" node_modules/@copilotkit/runtime/dist/v2/index.d.mts | tr ',' '\n' | grep -i handler
node -e "import('@copilotkit/runtime/v2').then(m => console.log(Object.keys(m).sort().join('\n')))"
npm ls @ag-ui/client                                    # duplicate versions?
```

## 3. Reproduce small
- Collector issue: `collect --dry-run` for one window; `--log-level DEBUG` (payloads are never logged).
- Agent issue: `curl -N` the agent endpoint directly (consultation 01) and read the events one by one.
- RLS issue: `psql` as a non-superuser with `set_config` (FAQ "Database").
- Frontend issue: DevTools -> Network -> EventStream tab of the `/run` request.

## 4. Read vendor docs for the **exact version**
| Vendor | Where | Version pinning tip |
|---|---|---|
| CopilotKit | https://docs.copilotkit.ai/reference/v2 ; package `.d.ts` | docs track latest; trust your installed `.d.ts` |
| AG-UI | https://docs.ag-ui.com (concepts/events) | match `ag-ui-protocol` major |
| OpenMetadata | https://docs.open-metadata.org/v2.0.x/... (version in URL) ; `<OM>/swagger.html` on your server | use the versioned path |
| Dynatrace | https://docs.dynatrace.com (API references), your tenant's API explorer (Settings -> Integration -> Dynatrace API) | tenant-specific features |
| Elastic | https://www.elastic.co/docs/reference (choose your version) | client major = cluster major |
| Portkey | https://portkey.ai/docs | SDK source in site-packages |
| AWS | `aws <service> help`, https://docs.aws.amazon.com | `aws --version` |

Write down what you verified in `docs/verified-facts.md` (date, version, source).

## 5. Decide with the kit's principles
When two options both "work", prefer the one that: keeps identity server-side, keeps raw data out of PostgreSQL,
keeps tools read-only and typed, is reversible, is testable without vendor access, and is documented in an ADR.

## 6. Ask a corporate-approved assistant (if any) with context
Use [PROMPT_LIBRARY.md](PROMPT_LIBRARY.md) prompts; paste only non-sensitive excerpts; `tools/kb/ask.py --llm` sends only
kit passages + your question through Portkey.
