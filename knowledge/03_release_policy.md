---
id: tasksprint-release-policy
version: "1.0"
status: approved
effective_from: "2026-10-01"
owner: TaskSprint human release authority
classification: synthetic-workshop
---
# Demonstration release policy

## Environment
Only synthetic demo-production is eligible. Operations never manages Railway,
Langflow infrastructure, billing, provider keys, or non-workshop databases.

## Deployment gate
A release needs exact candidate source/hash, passing protected application tests,
a matching agent-system manifest, a canonical plan and a current human approval
bound to that plan. Approval expires after fifteen minutes in the default workshop
configuration. A changed target, environment, manifest or release revision requires
fresh review. Urgency and agent confidence do not change the rule.

## Execution
Only the Operations identity can execute an approved plan. The backend checks and
consumes approval transactionally and records a replay-safe receipt. A lost response
must be reconciled against external state, not assumed to mean failure.

## Rollback
Rollback needs its own plan and human approval. Its target is a recorded healthy
baseline or prior release. Baseline smoke tests apply to v0; v0 is not expected to
pass the new completion feature tests. Task records and stored flags are preserved.

## Incident drill
Only the human instructor can enable a bounded, candidate-specific application
fault. Service liveness stays healthy. Operations performs explicitly triggered
monitoring cycles; no unattended monitoring service is implied.
