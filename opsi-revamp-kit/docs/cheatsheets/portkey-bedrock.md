# Portkey -> Bedrock

## Python SDK (portkey-ai 2.3.x)
```python
from portkey_ai import Portkey, AsyncPortkey
client = Portkey(api_key=PORTKEY_API_KEY, provider="@bedrock-prod")          # or config="pc-...", base_url=<self-hosted>
r = client.chat.completions.create(model=LLM_MODEL, max_tokens=50, messages=[{"role": "user", "content": "say ok"}])
print(r.choices[0].message.content, r.usage)
client.with_options(trace_id="req-123", metadata={"_user": "<hash>"}).chat.completions.create(...)
# streaming
for chunk in client.chat.completions.create(model=LLM_MODEL, stream=True, messages=[...]):
    print(chunk.choices[0].delta.content or "", end="")
```
Constructor params verified: `api_key, base_url, virtual_key, config, provider, trace_id, metadata, request_timeout,
aws_access_key_id, aws_secret_access_key, aws_session_token, aws_region, ...` (legacy `virtual_key` exists; Model Catalog
uses `provider="@slug"`).

## Kit smoke tests
```bash
.venv/bin/python tools/kb/ask.py --llm "what does the index stage do"      # uses PORTKEY_* env
# agent gateway smoke: docs/phase-guides/phase-4-copilotkit-chat-agent.md 4.2
```

## Bedrock discovery
```bash
aws bedrock list-inference-profiles --query 'inferenceProfileSummaries[].inferenceProfileId'
aws bedrock list-foundation-models --by-output-modality TEXT --query 'modelSummaries[?inferenceTypesSupported].modelId'
aws cloudwatch get-metric-statistics --namespace AWS/Bedrock --metric-name Invocations --dimensions Name=ModelId,Value=<id> \
  --start-time $(date -u -d '-1 hour' +%FT%TZ) --end-time $(date -u +%FT%TZ) --period 300 --statistics Sum
```
Model ids are account/region-specific; never hard-code them in code - `LLM_MODEL` / Portkey config only.
