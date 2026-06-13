# Damage Ledger Replay Checkpoint v0.105

Date: 2026-06-13

## Purpose

This checkpoint tightens the link between direct damage settlement records and
the canonical transition state changes. Formula ledgers were already built by
the damage resolver and present in damage logs, but `DamageRecord` did not keep
that ledger. That made the canonical settlement weaker than the runtime log for
auditing damage calculations.

## Changes

- Added `packet_id` to `DamageRecord`.
- Added `formula_ledger` to `DamageRecord`.
- Direct action damage settlement now passes `packet_id` into the damage record.
- The existing `formula_ledger` argument passed by the runtime is now preserved
  because it is a real `DamageRecord` field.
- `transition_reducer.validate_transition_replay()` now validates direct damage
  audit state changes:
  - `unit.hp_or_shield` direct damage changes have a dict payload;
  - payload target matches `state_change.subject_id`;
  - payload `damage_type` matches `state_change.reason`;
  - payload actor/action match `state_change.source`;
  - `state_change.delta == -payload.damage_applied`;
  - payload `final_damage` is numeric;
  - payload has a non-empty `formula_ledger`;
  - formula ledger actor/target/action/packet ids match the damage record;
  - formula ledger final/base damage matches the damage record when present.
- `replay_validation` now reports:
  - `direct_damage_change_count`
  - `direct_damage_change_valid_count`
  - `direct_damage_formula_ledger_count`
  - `damage_record_match`
  - `damage_record_mismatch_count`
  - `damage_record_mismatches`

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
  --output /tmp/hsr_v105_damage_ledger_c0_to_c8_exact.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --auto-probe-steps 1 \
  --output /tmp/hsr_v105_damage_ledger_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_v105_damage_ledger_seele_five_dummy.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/phase_lock_process_case.yaml \
  --output /tmp/hsr_v105_damage_ledger_phase_lock.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/derived_damage_skip_process_case.yaml \
  --output /tmp/hsr_v105_damage_ledger_derived_skip.json
```

Results:

- Model pack validation: ok.
- Phase 3 verification: PASS, all 10 examples pass.
- Phase 4 verification: PASS, all 10 examples pass.
- C0 to C8 exact route: `metadata.route_assertions.ok = True`.
- C0 to C8 route trace count: 8.
- C0 to C8 log event count: 172.
- C0 to C8 replay ok: 10 / 10.
- C0 to C8 process events: 56, unsupported 0, mismatches 0.
- C0 to C8 target decisions: 38 / 38 valid.
- C0 to C8 direct damage changes: 14 / 14 valid.
- C0 to C8 direct damage formula ledgers: 14.
- C0 to C8 settlement damage records: 14, all 14 have formula ledgers.
- Auto probe assertions: ok, 1 / 1 actions executed.
- Seele five-dummy replay direct/full/process/damage match: 4 / 4.
- Seele five-dummy direct damage changes: 4 / 4 valid.
- Seele five-dummy settlement damage records: 4, all 4 have formula ledgers.
- Phase-lock process case direct damage changes: 1 / 1 valid.
- Derived-damage skip process case direct damage changes: 1 / 1 valid.
- Unsupported process event types in checked outputs: none.
- Damage record mismatches in checked outputs: none.
- Tribbie follow-up total: `4393.00559968331`.
- Seele skill total in C0 to C8: `115919.63539530325`.

Negative smoke check:

- Manually removed the derived-damage skip case direct damage
  `state_change.payload.formula_ledger`.
- `validate_transition_replay()` returned `damage_record_match = False`,
  `ok = False`, and reported `missing_formula_ledger_dict`.

## Remaining Work

Direct damage records now carry formula ledgers and are replay-validated against
their audit state changes. DoT and super-break records still use separate
record types with weaker replay validation, and the formula ledger schema itself
is still only structurally checked at a shallow level.
