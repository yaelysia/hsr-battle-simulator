# Clean Combat Core Checkpoint v0.123

## Scope

This checkpoint starts the clean-core rewrite after the v0.122 runtime boundary
migration. It does not claim the legacy runtime is fully removed yet; it creates
the first explicit clean-core fact layers and verifies that existing replay
behavior remains unchanged.

## Structural Changes

- Added `StateStore` and `StateMutator` as the canonical state mutation boundary.
  `BattleSimulator.commit_state_change()` now delegates to the clean mutator.
- Added `RuleBook` and `RuleEvaluator` as the explicit rule-query boundary.
  Current callbacks still bridge to existing rule helpers while the pure IR
  implementation is built out.
- Replaced the large `effects.py` if/elif dispatcher with an `EffectRegistry`
  facade. The legacy dispatcher is isolated in `_legacy_effects.py`.
- Added a clean executable handler for `set_unit_flag`; remaining handlers are
  reported as `legacy_fallback`.
- Added Canonical IR coverage scanning and clean-core static checks to
  `runtime_audit.clean_core_coverage`.
- `ActionTransaction` now carries state store, state mutator, rule evaluator,
  and effect registry references as first-class execution context.

## Validation

Commands run:

```bash
python3 -m compileall -q simulator_v7_7
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py --model-pack model_pack_v3_0 --validate-model-pack
cd simulator_v7_7 && python3 test_phase3_verify.py
cd simulator_v7_7 && python3 test_phase4_verify.py
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py --model-pack model_pack_v3_0 --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only --route-mode exact --output validation_outputs_v0_123/c0_to_c8_clean_core_v0_123.json
```

C0-C8 exact replay:

- `metadata.route_assertions.ok = True`
- route trace: 8
- queued transitions: 2
- combined transitions: 10
- log events: 172
- settlement checked records: 148 / 148 valid
- Tribbie total damage: `4393.00559968331`
- Seele skill total damage: `115919.63539530325`

Clean-core coverage in `validation_outputs_v0_123/c0_to_c8_clean_core_v0_123.json`:

- runtime effect dispatch: `6 executable`, `21 legacy_fallback`
- Canonical IR effects: `2 executable`, `24 legacy_fallback`
- rule queries: `6 legacy_callback`
- clean static checks: `ok = True`

## Remaining Work

- Replace legacy fallback handlers in `_legacy_effects.py` with clean
  `EffectRegistry` handlers by effect family.
- Replace `RuleEvaluator` legacy callbacks with pure Canonical IR evaluators.
- Move action/queue/timeline runtimes off `SimulatorRuntimeAdapter`.
- Extend coverage matrix from current compiled case IR toward full TBGD lowering
  coverage.
