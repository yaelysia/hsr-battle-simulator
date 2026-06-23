# v8 Queue Interrupt / Extra Turn Checkpoint v0_247

## Scope

This checkpoint extends the queue family baseline from generic insert ability/action into a source-audited window model.

Implemented:

- Added `QueueWindowIR` to Canonical IR and RuleBook.
- Lowered queue window families from TBGD queue intent evidence:
  - `ultimate`
  - `counter`
  - `insert_ability`
  - `insert_action`
  - `assistant`
  - `immediate`
- Added `QueueTargetResolver` and stable `QueueTargetResolution` for queue enqueue/drain.
- Updated queue entries and queue drain plans to carry window family, window policy, and target resolution.
- Updated queue drain ordering to use `priority_value -> window_family_order -> enqueue_order -> entry_id`.
- Added manual ultimate queue request entry point in `CombatScheduler.enqueue_manual_ultimate()`.
- Extended source audit so queue mutations require window/target provenance, with a separate manual ultimate route-input provenance path.
- Added `validate_v0_247`.

## Current Results

`QueueWindowIR` lowering:

- total windows: 1218
- executable windows: 164
- executable `insert_ability`: 156
- executable `counter`: 6
- executable `ultimate`: 2

Manual ultimate:

- admitted manual ultimate request creates a queue entry.
- energy-not-ready request is blocked and does not mutate state.
- queue mutation passes settlement traceability, replay, and source audit.

Queue drain:

- existing standalone ability queue drain remains valid.
- existing queue action drain path from v0_246 does not regress.

## Blocked / Not Faked

- `extra_turn`: no admitted mainline queue source was classified as `extra_turn` in current TBGD lowering.
- `follow_up`: no admitted mainline queue source was classified as `follow_up` in current TBGD lowering.
- `interrupt`: no admitted mainline queue source was classified as `interrupt` in current TBGD lowering.
- `assistant`: classified but blocked because assistant actor / ability / target semantics are not admitted.
- `insert_action`: still blocked in current TBGD samples because fixed `SkillIndex` action resolution is not admitted for a runtime actor in the available path.

These remain non-mutating with explicit blockers. No synthetic extra-turn, follow-up, counter, assistant, or action mapping was introduced.

## Verification

Run from `hsr_v075_baseline_clean/hsr`:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_242 --output-dir /tmp/hsr_v8_regression_v0_242
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_245 --output-dir /tmp/hsr_v8_regression_v0_245
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_246 --output-dir /tmp/hsr_v8_regression_v0_246
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_247 --output-dir /tmp/hsr_v8_v0_247
git diff --check
```

Results:

- compileall: pass
- v0_225: `ok=True`
- v0_242: `ok=True`
- v0_245: `ok=True`
- v0_246: `ok=True`
- v0_247: `ok=True`
- `git diff --check`: pass

## Progress

Queue board status:

- `queue_enqueue`: trusted for current scope.
- `queue_priority`: trusted for current scope.
- `queue_resolution`: trusted for current scope where admitted.
- `queue_window_ir`: trusted for current scope.
- `manual_ultimate_enqueue`: trusted for current scope.
- `counter_window`: trusted for current scope as a queue window classification, not a damage family.
- `extra_turn_window`: blocked until an admitted mainline extra-turn source exists in Canonical IR.
- `full inserted action / ultimate / follow-up / counter execution`: still depends on admitted downstream action/ability resolution and source-specific window policy.

