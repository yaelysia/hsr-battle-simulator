# HSR Simulator Prototype v2.0

Route-validation battle simulator for HSR combat modeling.

This remains a **route validator**, not an automatic solver. It executes specified routes, resolves state transitions, and writes a replayable JSON event log.

## Main entry

```bash
python hsr_simulator_prototype_v2_0.py <case.yaml> --output <result.json>
```

## Validation

```bash
python tests/run_validations_v2_0.py
```

The validation report is written to `VALIDATION_v2_0.md`.

## HP model semantics

Use explicit HP semantics for units with multiple bars:

```yaml
hp_model:
  type: phase_hp        # normal_hp | segmented_hp | phase_hp
  bars:
    - hp: 18016543
      on_depleted:
        - type: immediate_action
          actor: lance_of_fury
          action: phase_transition_action
          targets: [lance_of_fury]
    - hp: 18016543
  carry_over_damage: false
```

Semantics:

- `normal_hp`: one ordinary HP pool.
- `segmented_hp`: segmented HP inside one phase; overflow damage carries by default.
- `phase_hp`: each HP bar is a phase boundary; overflow damage does not carry by default.

For Knight 3 Lance of Fury, use `phase_hp` with `carry_over_damage: false`.

## Changes after v1.3

- v1.4: explicit `hp_model.bars` are now honored. The simulator uses each next bar's own HP value and applies inline `bars[].on_depleted` effects.
- v1.5: context-specific modifiers now apply to the packet scaling stat, not only to Crit Rate / Crit DMG.
- v1.6: context-specific percentage modifiers preserve split base/pct/flat stat semantics.


## Changes through v2.0

- v1.7: phase HP boundaries lock later packets from the same action; condition RHS references and nested global flags are resolved correctly.
- v1.8: immediate actions defer target selection across wave transitions; single-target YAML strings are normalized.
- v1.9: kill energy is applied before after_defeat_enemy trigger conditions.
- v2.0: deferred queued actions with no valid targets are skipped before costs or action energy resolve.


## v7.0 architecture note

v7.0 introduces a schema boundary before battle resolution.  External model-pack YAML, generated route YAML, and hand-written validation cases are first processed by `hsr_engine.schema_normalizer.canonicalize_case()`, using scalar/list rules from `hsr_engine.core_rules`.  The battle engine then consumes a canonical internal representation.  See `ENGINE_ARCHITECTURE_v7_0.md`.

## v7.2 canonical model-pack input

The simulator can now load a normalized model pack directory directly:

```bash
python3 hsr_simulator_prototype_v7_2.py --model-pack /path/to/hsr_model_pack_v3_0 --validate-model-pack
python3 hsr_simulator_prototype_v7_2.py --model-pack /path/to/hsr_model_pack_v3_0 --case-id arbitration_4_3_knight_3_opening --output output.json
python3 hsr_simulator_prototype_v7_2.py /path/to/hsr_model_pack_v3_0 --output output.json
```

The model-pack boundary is documented in `MODEL_PACK_INTEGRATION_v7_2.md`.
