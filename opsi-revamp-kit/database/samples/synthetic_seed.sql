-- SYNTHETIC demo data only (lab / E2E). Never run against production.
-- Creates tenant 'tenant-demo', user 'demo-user', a small service graph, one
-- Dynatrace-like problem, error signatures with evidence samples and a saved thread.
-- Run as a member of opsi_owner after migrations 0000-0005:
--   psql "$LAB_DATABASE_URL" -v ON_ERROR_STOP=1 -f database/samples/synthetic_seed.sql

BEGIN;
SELECT set_config('opsi.tenant_id', 'tenant-demo', true), set_config('opsi.user_id', 'demo-user', true);

INSERT INTO opsi_knowledge.entities (id, tenant_id, kind, natural_key, name, source_system, attributes, valid_from) VALUES
  ('00000000-0000-4000-8000-000000000001', 'tenant-demo', 'service', 'SERVICE-00000000000000A1', 'checkout-api', 'dynatrace', '{"tier":"1"}', '2026-01-01Z'),
  ('00000000-0000-4000-8000-000000000002', 'tenant-demo', 'service', 'SERVICE-00000000000000B2', 'payments', 'dynatrace', '{"tier":"1"}', '2026-01-01Z'),
  ('00000000-0000-4000-8000-000000000003', 'tenant-demo', 'host', 'synthetic-host-1', 'synthetic-host-1', 'dynatrace', '{}', '2026-01-01Z'),
  ('00000000-0000-4000-8000-000000000004', 'tenant-demo', 'table', 'opsi_pg.appdb.public.orders', 'orders', 'openmetadata', '{}', '2026-01-01Z'),
  ('00000000-0000-4000-8000-000000000005', 'tenant-demo', 'team', 'payments-team', 'Payments Team', 'openmetadata', '{}', '2026-01-01Z'),
  ('00000000-0000-4000-8000-000000000006', 'tenant-demo', 'incident', '-2222222222222222222_1729764060000V2', 'P-24102 Failure rate increase', 'dynatrace', '{}', '2026-10-24T10:01Z'),
  ('00000000-0000-4000-8000-000000000007', 'tenant-demo', 'runbook', 'kb://payments/declines', 'Payments decline spike runbook', 'manual', '{}', '2026-01-01Z')
ON CONFLICT DO NOTHING;

UPDATE opsi_knowledge.entities SET external_catalog_fqn = 'opsi_pg.appdb.public.orders'
 WHERE id = '00000000-0000-4000-8000-000000000004';

INSERT INTO opsi_knowledge.edges (tenant_id, src_id, dst_id, relation, valid_from, source_system, created_by, confidence) VALUES
  ('tenant-demo', '00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000002', 'calls', '2026-01-01Z', 'dynatrace', 'collector:seed', 1.0),
  ('tenant-demo', '00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000003', 'runs_on', '2026-01-01Z', 'dynatrace', 'collector:seed', 1.0),
  ('tenant-demo', '00000000-0000-4000-8000-000000000002', '00000000-0000-4000-8000-000000000004', 'writes_to', '2026-01-01Z', 'manual', 'demo-user', 0.9),
  ('tenant-demo', '00000000-0000-4000-8000-000000000002', '00000000-0000-4000-8000-000000000005', 'owned_by', '2026-01-01Z', 'openmetadata', 'collector:seed', 1.0),
  ('tenant-demo', '00000000-0000-4000-8000-000000000006', '00000000-0000-4000-8000-000000000002', 'affects', '2026-10-24T10:01Z', 'dynatrace', 'collector:seed', 1.0),
  ('tenant-demo', '00000000-0000-4000-8000-000000000002', '00000000-0000-4000-8000-000000000007', 'documented_by', '2026-01-01Z', 'manual', 'demo-user', 1.0)
ON CONFLICT DO NOTHING;

INSERT INTO opsi_ingest.problems (tenant_id, problem_id, display_id, title, status, severity_level, impact_level,
  start_time, end_time, root_cause_entity_id, affected_entity_ids, record_version, evidence_ref, last_observed_at) VALUES
  ('tenant-demo', '-2222222222222222222_1729764060000V2', 'P-24102', 'Failure rate increase', 'OPEN', 'ERROR', 'SERVICES',
   '2026-10-24T10:01Z', NULL, 'SERVICE-00000000000000B2', '["SERVICE-00000000000000B2"]', 'v1',
   'dynatrace-problem://-2222222222222222222_1729764060000V2', '2026-10-24T10:07Z')
ON CONFLICT DO NOTHING;

INSERT INTO opsi_ingest.error_signature_windows (tenant_id, source, window_start, window_end, service_id, fingerprint,
  severity, event_count, first_seen, last_seen, sample_message, sample_ref, run_id) VALUES
  ('tenant-demo', 'elastic', '2026-10-24T10:00Z', '2026-10-24T10:05Z', 'payments', 'a1b2c3d4e5f60718', 'ERROR', 42,
   '2026-10-24T10:00:05Z', '2026-10-24T10:04:58Z', 'Payment declined: upstream gateway timeout after <n> ms',
   'elastic://.ds-logs-payments-2026.10.24-000001/_doc/doc-1', '20261024T100700Z-seed0001')
ON CONFLICT DO NOTHING;

INSERT INTO opsi_ingest.evidence_samples (tenant_id, event_uid, source, window_start, service_id, fingerprint, severity,
  event_time, message_excerpt, source_ref, run_id) VALUES
  ('tenant-demo', 'seed-uid-1', 'elastic', '2026-10-24T10:00Z', 'payments', 'a1b2c3d4e5f60718', 'ERROR',
   '2026-10-24T10:00:05Z', 'Payment declined: upstream gateway timeout after 3000 ms',
   'elastic://.ds-logs-payments-2026.10.24-000001/_doc/doc-1', '20261024T100700Z-seed0001')
ON CONFLICT DO NOTHING;

INSERT INTO opsi_chat.threads (id, tenant_id, owner_id, title, linked_incident_id, last_message_at) VALUES
  ('00000000-0000-4000-9000-000000000001', 'tenant-demo', 'demo-user', 'Why is payments failing?',
   '-2222222222222222222_1729764060000V2', '2026-10-24T10:10Z')
ON CONFLICT DO NOTHING;

INSERT INTO opsi_chat.messages (tenant_id, thread_id, message_id, role, content_text, content_json, author_id) VALUES
  ('tenant-demo', '00000000-0000-4000-9000-000000000001', 'm-user-1', 'user', 'Why is payments failing?',
   '{"id":"m-user-1","role":"user","content":"Why is payments failing?"}', 'demo-user'),
  ('tenant-demo', '00000000-0000-4000-9000-000000000001', 'm-asst-1', 'assistant',
   'Payments shows 42 gateway timeouts between 10:00 and 10:05 UTC [c1], matching problem P-24102 [c2].',
   '{"id":"m-asst-1","role":"assistant","content":"Payments shows 42 gateway timeouts between 10:00 and 10:05 UTC [c1], matching problem P-24102 [c2]."}',
   'agent:opsi-investigator')
ON CONFLICT DO NOTHING;

INSERT INTO opsi_chat.evidence_refs (tenant_id, thread_id, message_id, citation_key, source_type, source_ref, title, event_time, snippet) VALUES
  ('tenant-demo', '00000000-0000-4000-9000-000000000001', 'm-asst-1', 'c1', 'error_signature',
   'elastic://.ds-logs-payments-2026.10.24-000001/_doc/doc-1', 'payments: gateway timeout (42x)', '2026-10-24T10:00:05Z',
   'Payment declined: upstream gateway timeout after 3000 ms'),
  ('tenant-demo', '00000000-0000-4000-9000-000000000001', 'm-asst-1', 'c2', 'dynatrace_problem',
   'dynatrace-problem://-2222222222222222222_1729764060000V2', 'P-24102 Failure rate increase', '2026-10-24T10:01Z', NULL)
ON CONFLICT DO NOTHING;

COMMIT;
