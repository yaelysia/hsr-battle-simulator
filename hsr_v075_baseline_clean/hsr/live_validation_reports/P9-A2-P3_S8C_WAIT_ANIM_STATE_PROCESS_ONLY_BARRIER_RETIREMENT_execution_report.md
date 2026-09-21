# P9-A2-P3 / S8C WaitAnimState process-only barrier retirement — execution report

## Status

- Stage: `P9-A2-P3`.
- Card-specific implementation and exact-head validation passed on `62bf4b15561e48c80fb308d13951c226bac34be5`.
- Fixed base: `eedebb406b85ab2611e8345b3fe7a75e9a7c53a0`.
- Pinned TBGD: `14c1d18f91a8101d610e6c523447a7517de3fae1`.
- Production write authority remained limited to `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py`.
- Read-only lowering/runtime/schema/action-contract authorities remained unchanged.
- This report update is documentation-only. REVIEW must use the final PR head after this report commit and its applicable final-head CI.

## Delivered behavior

The materializer retires the erroneous `hit_random_sequence` ownership only for source-proven `WaitAnimState` occurrences satisfying the existing process-only presentation shape contract. Each admitted node is a materialized process-only leaf owned only by `task_graph_execution`.

The canonical reference invariant is preserved: each admitted WaitAnimState keeps exactly one formal `effect` reference matching `AbilityTaskIR.effect_id`. The referenced `EffectIR` remains same-source, opcode-matching, `coverage_status=audit_only`, and carries the admitted process-only source contract. This reference is audit identity/evidence only; it is not promoted into executable gameplay behavior.

The representative real action changes only from `WaitAnimState x2 + FireProjectile x1` to `WaitAnimState x0 + FireProjectile x1`. FireProjectile therefore remains the surviving `hit_random_sequence` source. S11 ownership and non-WaitAnim S8C siblings remain fail-closed and unchanged.

## Exact-head Fast validation on `62bf4b15561e48c80fb308d13951c226bac34be5`

External fixed-head validation reported:

- focused pytest `test_p9_a2_p3_wait_anim_state_process_only_barrier_retirement.py`: `25 passed, 1 warning in 1.15s`;
- three-file `compileall`: exit `0`;
- fixed-base `git diff --check`: exit `0`.

The pytest warning is the Windows pytest cache write warning from the relay environment; the focused test suite itself passed.

## Exact-head Direct validation

Linux Direct against pinned TBGD returned exit `0`, `mode=direct`, `ok=true`, with every business predicate true.

### Representative action and authority boundary

The Direct result proves:

- baseline `hit_random_sequence` provenance: `WaitAnimState x2 + FireProjectile x1`;
- current provenance: `WaitAnimState x0 + FireProjectile x1`;
- the top-level `task_graph_control_requires_domains:hit_random_sequence` blocker remains by design because FireProjectile remains unresolved;
- `effect_coverage_status:unsupported:FireProjectile` remains preserved;
- `task_graph_definition_not_admitted:effect:unsupported` remains preserved;
- `task_graph_definition_not_admitted:effect:audit_only` remains preserved;
- `task_graph_control_requires_domains:damage_heal_shield` remains preserved;
- the outer action remains fail-closed and state is unchanged;
- non-WaitAnim S8C sibling source authority is unchanged;
- read-only authorities are unchanged.

### Formal WaitAnimState denominator

The real formal denominator completed with:

- total WaitAnimState occurrences: `22330`;
- admitted: `22166`;
- blocked: `164`;
- WaitAnim-bearing formal entries: `7169`;
- distinct blocked reasons: `36`;
- denominator identity closed exactly: `22330 = 22166 + 164`;
- admitted denominator is non-empty;
- the two representative WaitAnimState task identities are present in the formal denominator.

The blocked set remains fail-closed. It includes `15` `source_contract:wait_anim_state_source_incomplete` occurrences and the remaining blocked occurrences retain their exact production `task_graph_ability_reference_not_lowered:<control-node>` reasons; no blocked occurrence is counted as admitted and no blocked reason is swallowed.

A real admitted fingerprint-closure sample was reported from:

- source path: `Config/ConfigAbility/Avatar/Avatar_DanHeng_00_Ability.json`;
- JSON path: `$.AbilityList[0].OnStart[4]`;
- task id: `ability_task:ability_phase:avatar_skill:100201:1:0:Avatar_DanHeng_00_Skill01_Phase01:OnStart:OnStart[4]:WaitAnimState`;
- production source-file SHA256: `3e73a9ec96610b42725970e09699c38a3426f2bceccc77c0d9949ef9757109e7`;
- formal source fingerprint scope: `source_file`;
- control, graph node, and audit reference all carry that same source-file SHA256;
- the raw task/effect evidence SHA field is empty as expected at that canonical layer;
- disposition: admitted with no reason.

The validator streams complete per-occurrence evidence to `/tmp` JSONL and returns aggregate counts, blocked-reason counts and samples rather than retaining all graph/row objects in memory.

### Zero gameplay leakage

All explicit runtime/formal channels remained zero:

- task-graph execute calls: `0`;
- condition-evaluation calls: `0`;
- RNG draw calls: `0`;
- mutations: `0`;
- events: `0`;
- RNG events: `0`;
- settlement records: `0`;
- replay mutations: `0`;
- replay runtime channel defined: `false`;
- pending-event delta: `0`;
- event-index delta: `0`;
- RNG-state event delta: `0`;
- settlement-state delta: `0`;
- replay-state delta: `0`.

Canonical zero/multiple/wrong effect-reference negatives also remain fail-closed.

## Resource validation and validator repair history

The final Direct resource result is inside the card budget:

- wall time: `230.643899s` (`< 480s`);
- final peak RSS: `772308 KiB` (`< 3 GiB`);
- parent peak RSS: `460024 KiB`;
- baseline worker peak RSS: `471580 KiB`;
- denominator worker peak RSS: `772308 KiB`.

Earlier validator-only implementations first repeated full materialization work per Wait-bearing slice, then retained the complete formal canonical plus thousands of materialized graphs/rows at once. Those approaches either exceeded the bounded runtime or peaked near `6.2 GiB`. The accepted validator path preserves the same real denominator and production materialization semantics while streaming formal slices and evidence so the exact counts remain `22330 / 22166 / 164 / 7169` and the resource gates pass. No production/read-only authority was widened to obtain this improvement.

## Scope and residual blockers

No FireProjectile count/default was inferred or admitted. No non-WaitAnim presentation/barrier family was globally admitted. `DamagePerformFinish` and `SkillPerformFinish` remain under the later `damage_heal_shield` / S11 predecessor. FireProjectile remains the surviving `hit_random_sequence` source on the representative action. PR11 remains paused until the predecessor chain is re-attributed from merged master.

The remaining EXEC work after this report commit is only applicable final-head CI, then Ready + `[HANDOFF:REVIEW]` if those gates pass.
