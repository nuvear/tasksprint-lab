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
