# Effect Settlement Trace Checkpoint v0.111

Date: 2026-06-13

## Purpose

This checkpoint extends settlement-record consistency beyond SP and energy.
Top-level HP, shield, and AV settlement records now have to match the concrete
transition state changes they summarize. This reduces another source of drift
between process records and replayable snapshot mutations.

## Changes

- Extended `_validate_resource_record_consistency()` to accept and validate:
  - `hp_records`
  - `shield_records`
  - `av_records`
- Added aggregate counters:
  - `settlement_checked_record_count`
  - `settlement_checked_record_valid_count`
- Added per-record counters:
  - `hp_record_count`
  - `hp_record_valid_count`
  - `shield_record_count`
  - `shield_record_valid_count`
  - `av_record_count`
  - `av_record_valid_count`
- HP record validation checks:
  - matching `unit.hp` resource state change exists;
  - unit id, old HP, and new HP match;
  - state-change delta matches settlement record delta.
- Shield record validation checks:
  - matching `unit.shield` resource state change exists;
  - unit id, old shield, and new shield match;
  - state-change delta matches settlement record delta.
- AV record validation checks:
  - matching `unit.remaining_av` AV state change exists;
  - unit id, old remaining AV, and new remaining AV match;
  - state-change delta matches settlement record delta;
  - state-change source id matches settlement record source id when present.

Status records are intentionally not included yet. Current status settlement
records still have known producer-side gaps, such as break aftermath status
records carrying default stack fields while the concrete status state change
contains the real stack and duration data. That should be fixed at the
record-production boundary before adding a strict status-record gate.

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
  --output /tmp/hsr_v111_effect_record_trace_c0_to_c8_exact.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --auto-probe-steps 1 \
  --output /tmp/hsr_v111_effect_record_trace_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/break_dot_minimal_case.yaml \
  --output /tmp/hsr_v111_effect_record_trace_break_dot.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/super_break_case.yaml \
  --output /tmp/hsr_v111_effect_record_trace_super_break.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_v111_effect_record_trace_seele_five_dummy.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/phase_lock_process_case.yaml \
  --output /tmp/hsr_v111_effect_record_trace_phase_lock.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/derived_damage_skip_process_case.yaml \
  --output /tmp/hsr_v111_effect_record_trace_derived_skip.json
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
- C0 to C8 checked settlement records: 92 / 92 valid.
- C0 to C8 resource records: 35 / 35 valid.
- C0 to C8 HP records: 9 / 9 valid.
- C0 to C8 shield records: 7 / 7 valid.
- C0 to C8 SP records: 4 / 4 valid.
- C0 to C8 energy records: 15 / 15 valid.
- C0 to C8 AV records: 57 / 57 valid.
- Auto probe replay ok: 1 / 1.
- Auto probe checked settlement records: 3 / 3 valid.
- Break/DoT minimal replay ok: 3 / 3.
- Break/DoT minimal checked settlement records: 10 / 10 valid.
- Super-break replay ok: 2 / 2.
- Super-break checked settlement records: 7 / 7 valid.
- Seele five-dummy replay ok: 4 / 4.
- Seele five-dummy checked settlement records: 16 / 16 valid.
- Phase-lock replay ok: 1 / 1.
- Derived-skip replay ok: 1 / 1.
- Damage and turn record mismatches in checked outputs: none.
- Tribbie follow-up final damage total:
  `4393.00559968331`.
- Seele skill final damage total in C0 to C8:
  `115919.63539530325`.

Negative smoke checks:

- Removed a concrete `unit.hp` state change while keeping the matching
  top-level HP settlement record.
  `_validate_resource_record_consistency()` returned
  `settlement_record_match = False` and reported
  `missing_matching_hp_state_change`.
- Corrupted one AV settlement record `source_id`.
  `_validate_resource_record_consistency()` returned
  `settlement_record_match = False` and reported
  `av_records[0].state_change.source.source_id`.

## Remaining Work

HP, shield, SP, energy, and AV top-level settlement records are now tied to
concrete transition state changes. The next useful target is status settlement
records: first fix their production so stack/duration/source fields are filled
from the actual committed status object, then add them to the same consistency
gate.
