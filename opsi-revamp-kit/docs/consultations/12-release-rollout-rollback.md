# 12 - Release strategy, rollout and rollback

## The question
"How do we go live without risking the production Opsi?"

## Short answer
Strangler pattern: new capabilities sit beside the old app behind flags and new routes; data changes are additive;
every step has a tested rollback; rollout goes lab -> staging -> pilot users -> everyone.

## Stages
| Stage | Who | Gate to next |
|---|---|---|
| Lab | engineers | `make smoke` green on the EC2 lab; phase exit criteria |
| Staging | engineers + 2-3 SREs | acceptance journey passes; security checklist (consultation 10); restore drill done |
| Pilot | 5-20 named users (flag by group) | 2 weeks: no P1/P2 issues, feedback >= agreed threshold, budgets/costs within plan |
| GA | all | change approval; on-call runbook acknowledged |

## Flags
- Backend: `OPSI_REVAMP_ENABLED` (mount routers), per-feature flags (`OPSI_VOICE_ENABLED`, `OPSI_VECTOR_ENABLED`).
- Frontend: `revampChat` flag (by user group) controls the provider and entry points.
- Collectors: timers per source (enable one at a time).

## Change windows
Migrations, NGINX includes and runtime start each get their own change with rollback steps (commit-plan.md). Avoid
bundling a DB migration with a UI release.

## Blue/green on EC2 (optional)
Run the revamp API on a second port/instance, switch the NGINX upstream for `/api/v2/` and `/api/copilotkit/` only;
rollback = switch back. The legacy app's routes are untouched.

## Rollback drills
Practise once in staging: turn flags off, stop runtime/timers, remove NGINX include, (optionally) run down migrations on a
restored copy. Time it; record in the evidence log.

## Verify
Pilot metrics: error rates, latency, cost per run, feedback; incident count related to the revamp = 0 before GA.
