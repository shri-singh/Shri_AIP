# Dynatrace APIs and DQL

## Problems API v2 (classic token, scope `problems.read`)
```bash
DT=https://<env-id>.live.dynatrace.com
curl -s -H "Authorization: Api-Token $DYNATRACE_API_TOKEN" \
  "$DT/api/v2/problems?from=now-2h&pageSize=50" | jq '{totalCount, next: .nextPageKey, first: .problems[0] | {problemId, displayId, title, status, severityLevel}}'
curl -s -H "Authorization: Api-Token $DYNATRACE_API_TOKEN" "$DT/api/v2/problems?nextPageKey=<key>"   # ONLY nextPageKey on later pages
curl -s -H "Authorization: Api-Token $DYNATRACE_API_TOKEN" "$DT/api/v2/problems?problemSelector=status(%22OPEN%22)&pageSize=5"
```
Managed: base is `https://<host>/e/<env-id>`. Entities for the ontology: `/api/v2/entities?entitySelector=type(SERVICE)` (scope `entities.read`).

## Platform OAuth token (Grail)
```bash
TOKEN=$(curl -s -X POST https://sso.dynatrace.com/sso/oauth2/token \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode grant_type=client_credentials \
  --data-urlencode "client_id=$DYNATRACE_OAUTH_CLIENT_ID" \
  --data-urlencode "client_secret=$DYNATRACE_OAUTH_CLIENT_SECRET" \
  --data-urlencode 'scope=storage:logs:read storage:buckets:read' | jq -r .access_token)
# add --data-urlencode "resource=urn:dtaccount:<account-uuid>" if your setup requires it
```
Tokens expire in minutes (`expires_in`); the collector refreshes automatically.

## Grail query (execute / poll)
```bash
P=https://<env-id>.apps.dynatrace.com/platform/storage/query/v1
curl -s -X POST "$P/query:execute" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{
  "query": "fetch logs | filter loglevel == \"ERROR\" | summarize count()",
  "defaultTimeframeStart": "2026-10-24T10:00:00Z", "defaultTimeframeEnd": "2026-10-24T10:05:00Z",
  "timezone": "UTC", "locale": "en_US", "maxResultRecords": 1000, "requestTimeoutMilliseconds": 10000}' | tee /tmp/q.json | jq '{state, requestToken}'
curl -s "$P/query:poll?request-token=$(jq -r .requestToken /tmp/q.json)&request-timeout-milliseconds=10000" \
  -H "Authorization: Bearer $TOKEN" | jq '{state, records: .result.records, notes: .result.metadata.grail.notifications}'
```
States: NOT_STARTED, RUNNING, SUCCEEDED, RESULT_GONE (poll sooner), CANCELLED, FAILED. HTTP 200 = done, 202 = poll.

## DQL snippets
```
fetch logs | filter loglevel == "ERROR" | summarize count(), by:{dt.entity.service} | sort `count()` desc
fetch logs | filter in(loglevel, {"ERROR","WARN"}) and dt.entity.service == "SERVICE-0123456789ABCDEF"
fetch logs | filter matchesPhrase(content, "timeout") | fields timestamp, loglevel, content, dt.entity.service | limit 20
fetch logs | summarize count(), by:{bin(timestamp, 5m)}            // volume per 5-minute window
fetch dt.davis.problems | limit 5                                    // problems in Grail (storage:events:read)
```
The collector's `DYNATRACE_GRAIL_DQL` must not include `timeframe:`/`from:`/`to:` or `| limit`.
Field names (`loglevel`, `content`, `dt.entity.service`) can differ per log source - check with `fetch logs | limit 1`.
