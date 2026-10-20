"""Protected application test service (Architecture A6, A8) — NOT BUILT; Phase 03.

The append-only ``test_runs`` table exists (migration 1). Only trusted testing
code will write it; QA prose never does. State transitions out of IN_QA already
require a matching trusted test run, so they are unreachable until Phase 03.
"""
