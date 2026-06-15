# Combat Core Direct Damage Checkpoint v0.121

Date: 2026-06-15

## Purpose

This checkpoint starts the parallel clean-core refactor. Direct damage
calculation and direct HP/shield application now go through
`hsr_engine.combat_core` instead of being implemented inline in
`hsr_simulator_prototype_v7_7.py`.

The old CLI, route cases, settlement JSON keys, and numeric baselines remain
compatible.

## Changes

- Added `hsr_engine/combat_core/` as the new combat-core boundary.
- Added `contracts.py` with:
  - `ActionInput`
  - `ActionTransaction`
  - `RuleDataView`
  - `StateView`
  - `StateMutator`
- Added `executor.py` with `CombatExecutor`.
- Added `damage.py` with:
  - `DamageResolver`
  - `DamageApplier`
  - `DamageApplication`
- `BattleSimulator.resolve_damage_packet()` is now a compatibility wrapper
  around `DamageResolver.resolve_packet()`.
- `BattleSimulator.apply_damage_result()` now delegates direct shield/HP
  application to `DamageApplier.apply_direct_damage_result()`.
- Break, DoT, and super-break remain on the legacy path for this stage.
- `DamageRecord` now stores a native `modifier_ledger` alongside legacy
  `formula_ledger`.
- `DamageSettlement` prefers native `modifier_ledger` and only falls back to
  deriving a ledger from legacy `formula_ledger`.
- Added `examples/modifier_ledger_skipped_terms_case.yaml` to prove skipped
  modifier terms are traceable.

## Validation

Commands:

```bash
python3 -m compileall -q simulator_v7_7
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py --model-pack model_pack_v3_0 --validate-model-pack
cd simulator_v7_7 && python3 test_phase3_verify.py
cd simulator_v7_7 && python3 test_phase4_verify.py
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode exact \
  --output /tmp/hsr_core_v121_combat_core_c0_to_c8_exact.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/modifier_ledger_skipped_terms_case.yaml \
  --output /tmp/hsr_core_v121_modifier_ledger_skipped_terms_final.json
```

Results:

- Model pack validation: ok.
- Phase 3 verification: PASS, all 11 examples pass.
- Phase 4 verification: PASS, all 11 examples pass.
- C0 to C8 exact route: `metadata.route_assertions.ok = True`.
- C0 to C8 route trace count: 8.
- C0 to C8 queued transition count: 2.
- C0 to C8 combined settlement trace count: 10.
- C0 to C8 log event count: 172.
- Checked settlement records: 148 / 148 valid.
- Direct damage records in C0 to C8: 14.
- Native modifier ledgers in C0 to C8: 14.
- Normalized modifier terms in C0 to C8: 40.
- Ledger-to-damage-record index mismatches: none.
- Tribbie follow-up final damage total:
  `4393.00559968331`.
- Seele skill final damage total in C0 to C8:
  `115919.63539530325`.
- Skipped-terms example:
  - route assertions ok.
  - `modifier_ledger_count = 1`.
  - `modifier_term_count = 1`.
  - `skipped_modifier_term_count = 1`.
  - skipped term:
    `actor.status mixed_damage_bonus dmg_bonus.fire condition_not_matched`.

Structural checks:

- The migrated direct damage path no longer calls
  `collect_damage_formula_ledger()`; that method remains only as legacy
  compatibility/reference code.
- `DamageSettlement.modifier_ledgers` is one-to-one with direct damage records
  for the C0 to C8 route.

## Remaining Work

This is the first clean-core vertical slice, not the finished engine. The next
stage should move target resolution and the whole action lifecycle into
`CombatExecutor`, then migrate break, DoT, super-break, resources, status, AV,
and queue mutations onto explicit core transaction interfaces.
