---
name: release-and-recover
description: Assess, prepare, execute an explicitly approved TaskSprint app release, or investigate and roll back a synthetic app incident. Use for application operations only, never for Railway or Langflow administration.
metadata:
  version: "1.0.0"
  owner: "TaskSprint workshop maintainer"
---
# Release and recover the demonstration app

## Prerequisites
Operations identity, exact candidate/release references, current service state,
protected test evidence, an applicable agent-system evaluation manifest and an
available human release authority. Only synthetic demo-production is in scope.

## Release procedure
1. Read actual app health, active hash and release revision.
2. Read the candidate source/hash and protected application-test report. Verify
   that the report is for the exact source and approved test-suite version.
3. Read agent-system readiness and compare the current flow/model/prompt/tool/
   policy/skill/corpus manifest. Missing or mismatched evidence blocks readiness.
4. Create a canonical immutable release plan showing target, effect, evidence,
   previous healthy version, rollback implications and expected release revision.
5. Return the plan for human review. Assessment does not include execution.
6. On a later explicit execution request, call the approved-plan executor. The
   backend, not this skill or the model, must verify and consume human approval.
7. Check the actual active hash and business health after execution. Record a
   failed smoke check as an incident, not as proof that release never occurred.

## Recovery procedure
1. Run one requested health check and inspect scoped recent events.
2. Identify the affected candidate and the last recorded healthy version.
3. Create a separate rollback plan and explain any feature withdrawal.
4. Await exact human rollback approval; then execute and verify actual recovery.
5. Check that task records and previously stored completion flags remain intact.
   Never roll back the task database merely to roll back application code.
6. Record an incident summary and next-sprint improvement item.

## Exceptions
After an uncertain response, query external action status and reuse the same action
identity. Reject missing/expired/mismatched approval, stale release revision,
unsupported environment, stop flag or unverifiable evidence. Escalate rather than
retry indefinitely. A skill or peer request never grants deployment authority.
