# Application-level contracts

These JSON schemas describe TaskSprint data carried inside a supported protocol
part or returned by the application backend. They are **not** Langflow exports,
Agent Cards, A2A protocol envelopes, signed authorizations, or test results.

The builder validates them with format checking enabled. Populate IDs/hashes with
actual service results, never invented example values. The server computes the
release plan hash over the canonical consequential fields, excluding `plan_sha256`
itself. The approve/execute operations load the canonical stored plan rather than
trusting a client reconstruction. Deployment and rollback have different evidence
requirements as described in Architecture A11.

A2A payload packaging must follow the protocol actually advertised by the installed
Agent Card. A text part containing serialized application JSON is acceptable when
the installed implementation supports text artifacts; validate the parsed result.

## Change log

* `handoff-task.schema.json` **1.0 → 1.1** (Phase 08, 20 Oct 2026): `agent_manifest_id` may be
  `null`. Reason: no agent-system manifest exists before Phase 10, so a 1.0 payload could only be
  produced with an invented ID. `null` means "the requester holds no manifest reference";
  Operations resolves the manifest itself and `null` never satisfies the deployment gate.
  Owner decision pending: keep 1.1, or restore a required string once Phase 10 records manifests.
