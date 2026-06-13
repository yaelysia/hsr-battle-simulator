# Resource Settlement Trace Checkpoint v0.110

Date: 2026-06-13

## Purpose

This checkpoint starts validating top-level settlement records against the
canonical transition state changes. Replay validation already proves the final
snapshot projection, but settlement records such as `sp_records` and
`energy_records` live outside the transition object. Without a consistency
gate, those process records could drift away from the state changes they are
supposed to explain.

## Changes

- Added `_validate_resource_record_consistency()` in the settlement collector.
- `SettlementCollector.to_dict()` now:
  - serializes settlement records once;
  - validates SP and energy records against `transition.state_changes`;
  - adds `settlement_record_validation` to the settlement payload;
  - merges the same fields into `transition.replay_validation`;
  - requires `settlement_record_match` for `replay_validation.ok`.
- SP record validation checks:
  - matching `global.skill_points` resource state change exists;
  - old/new SP values match;
  - state-change delta equals `new_sp - old_sp`;
  - state-change `payload.requested_delta` equals settlement record `delta`;
  - source owner matches `source_id` when present.
- Energy record validation checks:
  - matching `unit.energy` resource state change exists;
  - old/new energy values match;
  - state-change delta equals `new_energy - old_energy`;
  - `energy_cost` records match `payload.energy_cost`;
  - `action_energy` records match `energy:{label}` and `payload.gain`;
  - `effect_energy` records match `effect:modify_energy`;
  - `new_energy <= max_energy`.

Important semantic detail: for positive energy/SP gains, settlement record
`delta` may be the requested amount while state-change `delta` is the actual
applied amount after caps. Validation therefore compares old/new values for
the applied result and only compares payload request fields when that request
is represented in the concrete state change.

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
  --output /tmp/hsr_v110_resource_record_trace_c0_to_c8_exact.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --auto-probe-steps 1 \
  --output /tmp/hsr_v110_resource_record_trace_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/break_dot_minimal_case.yaml \
  --output /tmp/hsr_v110_resource_record_trace_break_dot.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/super_break_case.yaml \
  --output /tmp/hsr_v110_resource_record_trace_super_break.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_v110_resource_record_trace_seele_five_dummy.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/phase_lock_process_case.yaml \
  --output /tmp/hsr_v110_resource_record_trace_phase_lock.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/derived_damage_skip_process_case.yaml \
  --output /tmp/hsr_v110_resource_record_trace_derived_skip.json
```

Results:

- Model pack validation: ok.
- Phase 3 verification: PASS, all 10 examples pass.
- Phase 4 verification: PASS, all 10 examples pass.
- C0 to C8 exact route: `metadata.route_assertions.ok = True`.
- C0 to C8 route trace count: 8.
- C0 to C8 log event count: 172.
- C0 to C8 replay ok: 10 / 10, including queued transitions.
- C0 to C8 unsupported replay paths: 0.
- C0 to C8 settlement resource records: 19 / 19 valid.
- C0 to C8 SP records: 4 / 4 valid.
- C0 to C8 energy records: 15 / 15 valid.
- C0 to C8 settlement record mismatches: 0.
- Auto probe replay ok: 1 / 1.
- Auto probe settlement resource records: 2 / 2 valid.
- Break/DoT minimal replay ok: 3 / 3.
- Break/DoT minimal settlement resource records: 1 / 1 valid.
- Super-break replay ok: 2 / 2.
- Super-break settlement resource records: 2 / 2 valid.
- Seele five-dummy replay ok: 4 / 4.
- Seele five-dummy settlement resource records: 4 / 4 valid.
- Phase-lock replay ok: 1 / 1.
- Derived-skip replay ok: 1 / 1.
- Damage and turn record mismatches in checked outputs: none.
- Tribbie follow-up final damage total:
  `4393.00559968331`.
- Seele skill final damage total in C0 to C8:
  `115919.63539530325`.

Negative smoke checks:

- Corrupted one SP settlement record `delta`.
  `_validate_resource_record_consistency()` returned
  `settlement_record_match = False` and reported
  `sp_records[0].state_change.payload.requested_delta`.
- Removed the matching `unit.energy` state change for one energy record.
  `_validate_resource_record_consistency()` returned
  `settlement_record_match = False` and reported
  `missing_matching_energy_state_change`.

## Remaining Work

SP and energy settlement records are now tied to concrete resource state
changes. The next useful target is to extend the same settlement-record
consistency layer to HP/shield/status/AV records, then gradually replace
one-off payload matching with typed settlement objects that can drive full
snapshot replay directly.
