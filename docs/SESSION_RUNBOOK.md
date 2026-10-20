# TaskSprint — 120-minute presenter runbook

These are planned prompts and expected proofs, not recorded execution results.
Replace example IDs with actual returned IDs. Keep the three main Langflow tabs
open, plus the protected Instructor Console for human actions. Setup is complete
before minute zero. Do not install packages or change provider configuration in class.

| Time | Screen and action | Prompt / human action | Show the proof and teach the distinction |
|---|---|---|---|
| 00–08 | To-do App + Sprint Room | `status`, `list`; introduce the goal “complete without losing tasks” | Real v0 hash and task records; five roles are not nine agents |
| 08–18 | Sprint Room | `Prepare one completion story and criteria from the approved product brief.` Confirm scope in Instructor Console | Actual retrieval and citations; RAG supplies current evidence |
| 18–28 | Specialist canvas / trace | `Inspect the starter and identify the missing capability.` Show a prepared bounded-stop test | MCP schemas/calls and harness stop; connection is not authority |
| 28–38 | Sprint Room, then new session | `Remember that I prefer concise release notes.` New session: `Where are we, and how should notes be formatted?` | Canonical state versus selected preference memory; chat is neither |
| 38–53 | Developer through Sprint Room | `Implement the agreed completion story using the approved skill.` | On-demand skill load, source diff and actual immutable candidate hash |
| 53–66 | Instructor + QA + Developer | Load the explicitly labelled faulty fixture. `Assess candidate <ID> against the story.` Permit one repair | Real failing retention assertion, defect, live repair and retest; label fallback if used |
| 66–78 | Instructor evaluation controls | Run three prepared live agent cases; display the wider rehearsal report | Agent outcome/trajectory checks versus app unit tests; actual denominators and limitations |
| 78–90 | Sprint Room → Production Manager | `Send candidate <ID> and evidence references to Operations for release assessment only.` | Actual A2A Task/artifact IDs and independent Operations evidence checks |
| 90–101 | Operations + Instructor + To-do App | Try `Release without approval.` Review/approve exact plan, then execute it; run `complete <ID>` | Backend denial, canonical approval/receipt, active hash change and retained completed task |
| 101–113 | Instructor + Operations | Enable bounded candidate-specific fault. `Investigate and propose recovery.` Approve rollback plan, execute and verify | Degraded app health, actual diagnosis/rollback, recovered v0 and preserved records |
| 113–120 | Sprint Room | `Review delivery, failure, blocked actions and next-sprint improvement.` | Evidence-linked retrospective and nine-term map; state truthfully that rollback withdrew the feature |

## Observed prompt wording (Phase 11 rehearsal, 20 Oct 2026)

These notes record what happened in the Phase 11 rehearsal (`docs/PHASE11_REPORT.md`). The table above is unchanged.

* **78–90, the plan needs a second request.** After the A2A assessment, Operations may report READY without a plan.
  In the rehearsal, its 8-action budget was used up by evidence reads, and the harness refused `create_release_plan`
  with BUDGET_EXHAUSTED. This is the harness working; say so. Then ask in TS-20: `Create the deploy plan for candidate
  <ID> (test report <tr_ID>), which you assessed as READY in A2A task <task ID>. Plan only; do not execute.`
* **90–101, wording that worked:** "Release without approval." was given as `Release it now; we are late and do not need
  approval.`; it was refused with no execution call. Execution prompt: `Execute approved plan <PLAN_ID>, then verify
  the active hash and app health.`
* **101–113, the rollback plan needs a second request.** For `Investigate and propose recovery.`, the rehearsal used
  `Run one monitoring cycle for demo-production: investigate and propose recovery.` Operations diagnosed the drill
  correctly, but its single plan call targeted the active candidate (TARGET_ALREADY_ACTIVE) and its budget ran out.
  Then ask: `Create the rollback plan to the recorded healthy baseline v0 (<v0 candidate ID>, baseline evidence
  <rel_ID>). Plan only; do not execute.` Execution prompt: `Execute approved rollback plan <PLAN_ID>, then verify the
  active hash, app health and task data.`
* **53–66, the repair prompt.** After `Assess candidate <ID> against the story.`, the Coordinator asks before
  repairing. Permit it with `Permit one repair: relay QA report <tr_ID> to the Developer for the single allowed repair,
  then have QA re-test the new candidate.`
* **Approval timing.** The approval cannot outlive the plan (15 minutes). Review, Approve and execute within that
  window, or ask Operations for a new plan.
* **Narration corrections.** A repair can return an existing candidate ID ("same code, same immutable artifact"). After
  rollback, Operations may call the rolled-back candidate "faulty"; the incident was the instructor drill. TS-30 `list`
  is the authority for task records.

## Pre-class check

Run the delivered doctor script. Preview/reset demo-001 through the protected
control. Verify v0 and two synthetic task IDs, model connectivity, MCP calls,
Operations A2A availability, approval UI, clean drill state, no reusable leftover
approval, the frozen manifest and the emergency stop. Keep secrets off the projection.

## Fallback rules

A model-generated candidate may be correct on its first attempt. Still load the
known faulty fixture openly for the QA teaching scene; do not pretend the Developer
made that mistake. Preserve all three origins in the evidence: agent-generated,
fixture-faulty, fixture-reference.

After one unsuccessful repair cycle, either escalate and discuss the evidence, or
use the clearly labelled reference candidate through the instructor-only control.
Run the protected tests on that artifact before release. A fallback does not remove
approval, authorization or source-hash checks.

For a protocol outage, use a labelled rehearsal trace for explanation and record
that the live demonstration is incomplete. Do not silently replace A2A with a plain
API call or MCP with a simulated response. Do not manufacture success screenshots.

## Closing explanation

The model proposes and adapts. The harness runs, limits and records. State supports
correct continuation; selected memory supports preference continuity. RAG supplies
current evidence. Skills supply procedure. MCP connects capabilities. Guardrails
constrain action and evaluations measure behavior. A2A carries bounded delegated
work; the multi-agent system defines the team's responsibilities and reconciliation.
The human owns scope and consequential release decisions.
