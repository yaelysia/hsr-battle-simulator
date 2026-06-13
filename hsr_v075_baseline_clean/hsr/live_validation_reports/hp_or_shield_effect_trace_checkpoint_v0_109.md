# HP Or Shield Effect Trace Checkpoint v0.109

Date: 2026-06-13

## Purpose

This checkpoint tightens `unit.hp_or_shield` damage audit records so they can be
traced back to concrete `unit.hp` and `unit.shield` state changes. Previous
direct damage records stored formula damage as `damage_applied`, while
`hp_loss` stayed at `0.0`; this made the audit fact weaker than the snapshot
mutation it was supposed to explain.

## Changes

- `_apply_hp_damage_to_bars()` now returns cumulative `hp_loss`.
- `apply_damage_result()` now writes settlement effect fields into the damage
  result:
  - `shield_absorbed`
  - `hp_loss`
  - `damage_applied`
  - `applied_damage`
  - `overkill`
  - `is_overkill`
- Direct `DamageRecord` creation now uses those actual effect fields.
- Removed the old attempted damage-record backfill from `apply_damage_result()`;
  it ran before the current damage record was created and could only affect a
  previous record.
- `_validate_damage_state_changes()` now validates that direct, DoT, and
  super-break `unit.hp_or_shield` audit records are backed by concrete
  HP/shield state changes:
  - `damage_applied == hp_loss + shield_absorbed`;
  - direct `hp_loss` must match prior `damage:hp_damage` /
    `damage:hp_bar_depleted` `unit.hp` state changes;
  - direct `shield_absorbed` must match prior `damage:shield_absorb`
    `unit.shield` state changes;
  - DoT HP/shield changes must match `dot:{kind}:hp_loss` /
    `dot:{kind}:shield_absorb` and the source status id;
  - super-break HP/shield changes must match `super_break:hp_loss` /
    `super_break:shield_absorb`;
  - matched concrete state changes are consumed so repeated packets cannot all
    claim the same HP/shield mutation.

`final_damage` remains the formula/display damage. `damage_applied` now means
the portion that actually changed HP or shield. Phase locks and overkill are
therefore visible as `final_damage > damage_applied`.

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
  --output /tmp/hsr_v109_hp_or_shield_trace_c0_to_c8_exact.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --auto-probe-steps 1 \
  --output /tmp/hsr_v109_hp_or_shield_trace_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/break_dot_minimal_case.yaml \
  --output /tmp/hsr_v109_hp_or_shield_trace_break_dot.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/super_break_case.yaml \
  --output /tmp/hsr_v109_hp_or_shield_trace_super_break.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_v109_hp_or_shield_trace_seele_five_dummy.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/phase_lock_process_case.yaml \
  --output /tmp/hsr_v109_hp_or_shield_trace_phase_lock.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/derived_damage_skip_process_case.yaml \
  --output /tmp/hsr_v109_hp_or_shield_trace_derived_skip.json
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
- C0 to C8 direct damage changes: 14 / 14 valid.
- C0 to C8 turn changes: 14 / 14 valid.
- C0 to C8 damage/break/turn mismatches: 0.
- Auto probe replay ok: 1 / 1.
- Seele five-dummy replay ok: 4 / 4.
- Seele five-dummy direct damage changes: 4 / 4 valid.
- Break/DoT minimal replay ok: 3 / 3.
- Break/DoT minimal direct damage changes: 1 / 1 valid.
- Break/DoT minimal DoT changes: 2 / 2 valid.
- Break/DoT minimal super-break changes: 1 / 1 valid.
- Super-break replay ok: 2 / 2.
- Super-break direct damage changes: 2 / 2 valid.
- Super-break super-break changes: 2 / 2 valid.
- Phase-lock replay ok: 1 / 1.
- Phase-lock first hit: `final_damage = 60.0`,
  `damage_applied = 50.0`, `hp_loss = 50.0`, `overkill = 10.0`.
- Derived-skip replay ok: 1 / 1.
- Derived-skip primary hit: `final_damage = 100.0`,
  `damage_applied = 50.0`, `hp_loss = 50.0`, `overkill = 50.0`.
- Tribbie follow-up final damage total:
  `4393.00559968331`.
- Seele skill final damage total in C0 to C8:
  `115919.63539530325`.

Negative smoke checks:

- Corrupted one direct-damage `hp_loss` in C0 to C8.
  `validate_transition_replay()` returned `damage_record_match = False`,
  `ok = False`, and reported `payload.damage_applied_components`.
- Removed one concrete direct-damage `unit.hp` state change while keeping the
  damage audit record.
  `validate_transition_replay()` returned `damage_record_match = False`,
  `ok = False`, and reported `missing_matching_hp_loss_state_change`.

## Remaining Work

`unit.hp_or_shield` is still audit-only from the reducer projection
perspective, but it is now a strict traceable settlement fact: each damage audit
must point to the concrete HP/shield mutation that made the snapshot change.
The next useful step is to continue moving settlement facts from one-off
payload conventions toward explicit typed records for resource/status/AV
effects, so the reducer can eventually produce full snapshots from structured
settlement objects rather than ad hoc state-change paths.
