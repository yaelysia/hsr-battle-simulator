# v8 Workflow Design Checkpoint v0_201

## Scope

This checkpoint freezes the v8 working order before implementing more combat
mechanics. It is intentionally a design checkpoint, not a mechanics checkpoint.

The goal is to prevent v8 from repeating the v7 pattern of mixing runtime
logic, source-specific hacks, and incomplete snapshots.

## Added

- `simulator_v8_clean_core/ARCHITECTURE.md`
  - Clean-core invariants.
  - Module boundaries.
  - Action lifecycle.
  - Rule-source constraints.
  - Acceptance gates.

- `simulator_v8_clean_core/MECHANIC_WORKFLOW.md`
  - Required path for every new mechanic:
    TBGD source -> Canonical IR -> RuleBook -> system handler -> Mutation ->
    Settlement -> Snapshot replay.
  - Definition of Done.
  - Explicit forbidden patterns.

- `simulator_v8_clean_core/WORK_PLAN.md`
  - Staged plan from `v0_201` to `v0_210`.
  - Scenario, target/resource/timeline, direct damage, formulas, status,
    toughness, break, triggers, queue, DoT, super-break, heal, shield, enemy,
    wave, summon, and C0-C8 reconstruction order.

## Validation

Commands:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_200 --output-dir validation_outputs_v0_200
```

Expected:

- compileall passes.
- v0_200 validation remains `ok=true`.
- Static checks remain clean.
- Snapshot replay remains clean.

## Remaining Risk

The documents freeze the workflow, but they do not yet enforce every rule
automatically. Static checks should be expanded in later checkpoints as each
runtime boundary becomes concrete.

