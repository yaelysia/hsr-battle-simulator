# Modifier Ledger Structure Checkpoint v0.120

Date: 2026-06-15

## Purpose

This checkpoint introduces a normalized `ModifierLedger` boundary under
`DamageSettlement`. Existing direct-damage `formula_ledger` payloads are still
preserved on `DamageRecord`, but `DamageSettlement` now derives a structured
ledger with explicit modifier terms by bucket, source, scope, condition, and
applied reason.

## Changes

- Added `MODIFIER_LEDGER_ENCODING = hsr.settlement.modifier_ledger.v1`.
- Added `ModifierTerm` with normalized fields:
  - `bucket`
  - `source_type`
  - `source_id`
  - `key`
  - `scope`
  - `condition`
  - `value`
  - `stacks`
  - `applied_value`
  - `applied`
  - `applied_reason`
  - `skipped_reason`
  - `raw_path`
  - `raw`
- Added `ModifierLedger` for one direct damage record.
- `ModifierLedger.from_formula_ledger()` converts the current audit-only
  `formula_ledger.buckets.*.terms[]` shape into normalized terms.
- `DamageSettlement.to_dict()` now emits `modifier_ledgers`.
- `DamageSettlement.summary` now includes:
  - `modifier_ledger_count`
  - `modifier_term_count`
  - `skipped_modifier_term_count`
- Exported `ModifierLedger`, `ModifierTerm`, and `MODIFIER_LEDGER_ENCODING`
  from `hsr_engine.settlement`.

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
  --output /tmp/hsr_v120_modifier_ledger_c0_to_c8_exact.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/break_dot_minimal_case.yaml \
  --output /tmp/hsr_v120_modifier_ledger_break_dot.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/super_break_case.yaml \
  --output /tmp/hsr_v120_modifier_ledger_super_break.json
```

Results:

- Model pack validation: ok.
- Phase 3 verification: PASS, all 10 examples pass.
- Phase 4 verification: PASS, all 10 examples pass.
- C0 to C8 exact route: `metadata.route_assertions.ok = True`.
- C0 to C8 route trace count: 8.
- C0 to C8 queued transition count: 2.
- C0 to C8 log event count: 172.
- Checked settlement records: 148 / 148 valid.
- Direct damage records in C0 to C8: 14.
- Modifier ledgers in C0 to C8: 14.
- Normalized modifier terms in C0 to C8: 40.
- Skipped modifier terms in C0 to C8: 0.
- Covered buckets in C0 to C8:
  `dmg_bonus`, `res`, `universal_reduction`.
- Covered scopes in C0 to C8:
  `actor`, `target`.
- Every direct damage record with a non-empty `formula_ledger` has one
  corresponding `ModifierLedger`.
- Tribbie follow-up final damage total:
  `4393.00559968331`.
- Seele skill final damage total in C0 to C8:
  `115919.63539530325`.
- Break/DoT and super-break example outputs include `modifier_ledger_count`
  in `DamageSettlement.summary`.

Structural smoke check:

- `ModifierLedger` and `ModifierTerm` can be imported from
  `hsr_engine.settlement`.
- `DamageSettlement(damage_records=[DamageRecord(formula_ledger=...)])`
  serializes a normalized `modifier_ledgers[0].terms[0]` entry with bucket,
  source, scope, applied value, and raw path.

## Remaining Work

This checkpoint normalizes the current direct-damage audit ledger after damage
calculation. The next step is to move ledger construction closer to the formula
path so skipped or condition-failed modifiers are recorded at the point where
the engine decides not to apply them. Break, DoT, and super-break formulas also
need equivalent native ledgers.
