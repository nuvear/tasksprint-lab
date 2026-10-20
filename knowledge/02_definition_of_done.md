---
id: tasksprint-definition-of-done
version: "1.0"
status: approved
effective_from: "2026-10-01"
owner: TaskSprint human Product Owner
classification: synthetic-workshop
---
# Definition of Done

## Increment evidence
The implementation is inspectable, identified by immutable source hash, and linked
to the agreed story and retrieved requirements. A protected test suite checks the
candidate's actual behavior on isolated task records. All required application
checks must pass; infrastructure failures are not a pass.

## Agent-system evidence
The workshop agent system has a separately recorded evaluation manifest and
repeated task/trajectory results. Required evidence retrieval, scoped tools,
missing-approval denial, failure escalation and bounded stopping are checked.
Passing application unit tests alone does not establish these properties.

## Acceptance versus release
Human review accepts the increment. Production release is a separate decision
against an exact plan. The team cannot approve its own release, rewrite test results,
or treat a conversational “looks good” as authorization.

## Recovery
The previous healthy application artifact and a tested rollback path are identified.
Application rollback preserves task data. The final state must be described honestly,
including any feature withdrawn by rollback.
