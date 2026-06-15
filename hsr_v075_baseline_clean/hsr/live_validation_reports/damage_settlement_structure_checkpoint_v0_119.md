# Damage Settlement Structure Checkpoint v0.119

Date: 2026-06-15

## Purpose

This checkpoint introduces `DamageSettlement` as the structured sub-settlement
for all damage-family records inside one action settlement. Direct damage,
break, toughness, DoT, and super-break records are no longer only parallel
top-level lists: `ActionSettlement` now owns a `damage_settlement` object and
derives the legacy top-level damage-family keys from it for compatibility.

## Changes

- Added `DAMAGE_SETTLEMENT_ENCODING = hsr.settlement.damage.v1`.
- Added `DamageSettlement` with:
  - `damage_records`
  - `break_records`
  - `toughness_records`
  - `dot_records`
  - `super_break_records`
  - `summary`
- `DamageSettlement.summary` reports record counts and aggregate
  `damage_applied`, `hp_loss`, and `shield_absorbed`.
- `ActionSettlement` now accepts an optional `damage_settlement`.
- `ActionSettlement.to_dict()` emits the new `damage_settlement` key and keeps
  the existing top-level `damage_records`, `break_records`,
  `toughness_records`, `dot_records`, and `super_break_records` keys derived
  from that sub-settlement.
- `SettlementCollector.to_dict()` now constructs a `DamageSettlement` and
  passes it into `ActionSettlement`.
- Exported `DamageSettlement` and `DAMAGE_SETTLEMENT_ENCODING` from
  `hsr_engine.settlement`.

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
  --output /tmp/hsr_v119_damage_settlement_structure_c0_to_c8_exact.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/break_dot_minimal_case.yaml \
  --output /tmp/hsr_v119_damage_settlement_break_dot.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/super_break_case.yaml \
  --output /tmp/hsr_v119_damage_settlement_super_break.json
```

Results:

- Model pack validation: ok.
- Phase 3 verification: PASS, all 10 examples pass.
- Phase 4 verification: PASS, all 10 examples pass.
- C0 to C8 exact route: `metadata.route_assertions.ok = True`.
- C0 to C8 route trace count: 8.
- C0 to C8 queued transition count: 2.
- C0 to C8 log event count: 172.
- Settlement encodings in route and queued transitions:
  `hsr.settlement.action.v1`.
- Damage settlement encodings in route and queued transitions:
  `hsr.settlement.damage.v1`.
- `damage_settlement` legacy-derived keys matched top-level legacy keys for all
  checked settlements.
- Checked settlement records: 148 / 148 valid.
- C0 to C8 total damage from legacy records:
  `126348.68931498655`.
- C0 to C8 total damage from `DamageSettlement.summary`:
  `126348.68931498656`.
- Tribbie follow-up final damage total:
  `4393.00559968331`.
- Seele skill final damage total in C0 to C8:
  `115919.63539530325`.
- Break/DoT and super-break example outputs include non-empty
  `DamageSettlement.summary` entries for break, toughness, DoT, and
  super-break records.

Structural smoke check:

- `DamageSettlement` can be imported from `hsr_engine.settlement`.
- `DamageSettlement(damage_records=[...], break_records=[...])` serializes
  typed records and computes aggregate summary totals.

## Remaining Work

The damage-family records now have a sub-settlement boundary, but the modifier
ledger is still embedded inside each `DamageRecord.formula_ledger`. The next
structural step should introduce a normalized `ModifierLedger` object and make
damage settlement expose applied and skipped modifier terms by source, bucket,
condition, scope, and reason.
