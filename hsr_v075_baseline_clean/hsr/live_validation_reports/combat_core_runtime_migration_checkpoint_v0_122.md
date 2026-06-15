# Combat Core Runtime Migration Checkpoint v0.122

## Scope

This checkpoint migrates the battle runtime entrypoints out of
`hsr_simulator_prototype_v7_7.py` and into `hsr_engine/combat_core/`.
The TBGD/model-pack compiler layer is intentionally unchanged.

Moved runtime boundaries:

- `resolve_route_step` -> `combat_core.runtime.CombatRuntime`
- `resolve_action` -> `combat_core.actions.ActionRuntime`
- `apply_effect` -> `combat_core.effects.EffectRuntime`
- `drain_queues` -> `combat_core.queues.QueueRuntime`
- break / super-break / DoT / hp-loss public damage entrypoints now enter through `combat_core.damage`

`BattleSimulator` keeps compatibility wrappers for CLI, compiled cases, and
existing JSON output shape.

## Structural Results

- `BattleSimulator.resolve_route_step`, `resolve_action`, `apply_effect`, and `drain_queues` are 2-line wrappers.
- `CombatExecutor` owns the runtime facade and delegates action/effect/queue/route execution through `CombatRuntime`.
- `ActionTransaction` now carries action input, resolved targets, events, phase locks, transition-linked state/rng/process events, and a legacy context view.
- `ActionRuntime` attaches `_transaction` to the legacy context while helpers are still being converted to explicit core contracts.
- `DamageSettlement` remains the unified damage-family output for direct, break, DoT, and super-break records.

## Validation

Commands run:

```bash
python3 -m compileall -q simulator_v7_7
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py --model-pack model_pack_v3_0 --validate-model-pack
cd simulator_v7_7 && python3 test_phase3_verify.py
cd simulator_v7_7 && python3 test_phase4_verify.py
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py --model-pack model_pack_v3_0 --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only --route-mode exact --output validation_outputs_v0_122/c0_to_c8_runtime_migration_v0_122.json
```

C0-C8 exact replay:

- `metadata.route_assertions.ok = True`
- route trace: 8
- queued transitions: 2
- combined transitions: 10
- log events: 172
- settlement checked records: 148 / 148 valid
- direct damage records: 14
- native modifier ledgers: 14
- modifier terms: 40
- Tribbie total damage: `4393.00559968331`
- Seele skill total damage: `115919.63539530325`
- all action transitions include before/after snapshots, target resolution, state changes, rng events, and process events

## Remaining Risk

This is a large boundary migration, not the final clean-room core. Several moved
runtime methods still call legacy simulator helpers through `SimulatorRuntimeAdapter`
to preserve behavior while the monolithic helper surface is reduced. The next
cleanup should replace those delegated helpers with explicit `StateView`,
`StateMutator`, and `RuleDataView` contracts module by module.
