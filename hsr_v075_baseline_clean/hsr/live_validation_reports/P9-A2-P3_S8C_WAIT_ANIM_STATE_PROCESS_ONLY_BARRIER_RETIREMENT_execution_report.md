# P9-A2-P3 / S8C WaitAnimState process-only barrier retirement — execution report

## Status

- Stage: `P9-A2-P3`
- Result: implementation and card-specific validation passed on business/evidence head `650e67a0d5ca7ed538752c1ae0f350a3c48b7d2b`.
- Fixed base: `eedebb406b85ab2611e8345b3fe7a75e9a7c53a0`.
- Pinned TBGD: `14c1d18f91a8101d610e6c523447a7517de3fae1`.
- Production write authority remained limited to `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py`.
- This report is documentation-only. REVIEW must use the final PR head after this report commit and its final-head CI, not substitute the pre-report head.

## Delivered change

The production materializer now retires the erroneous `hit_random_sequence` ownership only for source-proven `WaitAnimState` occurrences that satisfy the existing process-only presentation shape contract. The admitted node is a materialized leaf owned only by `task_graph_execution`.

The v2 canonical invariant is preserved: each admitted WaitAnimState keeps exactly one formal `effect` reference matching `task.effect_id`; the referenced EffectIR must be same-source, opcode-matching, `coverage_status=audit_only`, and carry an admitted process-only source contract. This audit identity remains deferred evidence and is not promoted into executable/gameplay effect behavior.

The source-disposition retirement removes only the admitted WaitAnimState control-node `hit_random_sequence` obligation. Non-WaitAnim S8C siblings, FireProjectile, and S11 settlement ownership remain unchanged/fail-closed.

Focused tests and the Direct validator cover valid retirement plus source-contract/effect-identity failures, gameplay field/branch/termination negatives, non-WaitAnim sibling isolation, S11 isolation, canonical source/JSON round-trip, and zero/multiple/wrong effect-reference rejection.

## Validator incident and fix

An external Linux Direct run on `55275a9d1f1506987cf0adcce7f42007668d3544` initially failed with `AssertionError: s8c_sibling_source_authority_changed` after compileall and `20 passed` focused tests.

The failure was isolated to the validator: `_s8c_sibling_signature()` returned `list[tuple]` in the current process, while the baseline probe crossed a JSON subprocess boundary and returned the same values as `list[list]`. The semantic source authority was unchanged, but Python container-type comparison produced a false mismatch. Commit `650e67a0d5ca7ed538752c1ae0f350a3c48b7d2b` makes the signature JSON-native/stable (`list[list]`) without changing production code or relaxing the sibling comparison.

## Card-specific validation on `650e67a0d5ca7ed538752c1ae0f350a3c48b7d2b`

The scheduler ran the required commands in an isolated Linux checkout using the existing environment and pinned TBGD checkout `/home/zhangjinhao/code/hsr/turnbasedgamedata-main` at `14c1d18f91a8101d610e6c523447a7517de3fae1`:

- `python -m compileall ...` — exit `0`.
- focused pytest `test_p9_a2_p3_wait_anim_state_process_only_barrier_retirement.py` — `20 passed in 1.34s`.
- `validate_p9_a2_p3_wait_anim_state_process_only_barrier_retirement.py` — exit `0`; output `mode=direct`, `ok=true`, all predicates `true`; wall time `40.750721s`.

The Direct result proves the required real-source delta and preserved boundaries:

- baseline `hit_random_sequence` provenance: `WaitAnimState x2 + FireProjectile x1`;
- current provenance: `WaitAnimState x0 + FireProjectile x1`;
- top-level `task_graph_control_requires_domains:hit_random_sequence` remains because FireProjectile remains unresolved;
- `effect_coverage_status:unsupported:FireProjectile`, `task_graph_definition_not_admitted:effect:unsupported`, `task_graph_definition_not_admitted:effect:audit_only`, and `task_graph_control_requires_domains:damage_heal_shield` remain preserved;
- admitted WaitAnimState nodes are process-only materialized leaves with exactly one canonical audit-only effect reference;
- zero/multiple/wrong effect-reference mutations fail formal CanonicalIR closure;
- action admission remains fail-closed and does not execute task-graph runtime, condition evaluation, RNG, mutation, settlement, or replay behavior for this retirement;
- non-WaitAnim S8C sibling source authority is unchanged;
- read-only lowering/runtime/schema/action-contract authorities are unchanged.

## GitHub Actions on `650e67a0d5ca7ed538752c1ae0f350a3c48b7d2b`

- Run `34678638865` — `P9 S8C1B PR Validation`: success. Compile, upstream S8C1A, weighted Fast/Direct, formal-action Fast/Direct, and fixed-base diff check all succeeded.
- Run `34678638877` — `P9 S8C1C PR Validation`: success. Compile, S8C1A/S8C1B regressions, remaining-entry Fast, real-source Direct, full RandomConfig catalog validation, and fixed-base diff check all succeeded.
- Run `34678638900` — `P9-S8C1A PR1 fast validation`: skipped by its path/condition gate; not counted as success evidence.

## Scope and residual blockers

No runtime/schema/lowering/action-contract authority was changed. No FireProjectile count/default was inferred. No non-WaitAnim presentation/barrier family was globally admitted. `DamagePerformFinish` and `SkillPerformFinish` remain under the later `damage_heal_shield`/S11 predecessor. FireProjectile remains the surviving `hit_random_sequence` source on the representative action. PR11 remains paused until the predecessor chain is re-attributed from merged master.

The next role is REVIEW after the report-only final head receives its applicable final-head CI.