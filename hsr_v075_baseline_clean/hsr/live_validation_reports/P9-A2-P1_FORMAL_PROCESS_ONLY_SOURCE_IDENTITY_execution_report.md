# P9-A2-P1 Formal process-only source identity — Execution Report

## 1. Scope, authority, and validation head

- Fixed base: `master@770a0649926932794585fcd30589c6776892bc3b`.
- Pinned TBGD source: `14c1d18f91a8101d610e6c523447a7517de3fae1`.
- Card: `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9-A2-P1_FORMAL_PROCESS_ONLY_SOURCE_IDENTITY.md`.
- Only production file changed: `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py`.
- Code/validator head validated before this report: `e98f531a227ab7ccc893f15e0ebe480fd573d5c9`.
- P1 exact-head CI run: `34320254691`, job `102365081456`, conclusion `success`.
- P0 regression CI run on the same head: `34320254696`, conclusion `success`.
- This report commit creates a later governance-only PR head. Its exact SHA and final committed-head CI are recorded in the PR WAIT/HANDOFF comment because a commit cannot contain its own SHA before it exists.

No PR #11 or PR #9 unmerged business implementation was read or reused. No A1 authority, task-graph materializer, runtime executor, RNG authority, public IR equality semantics, dependency, runner class, secret, or workflow write permission was changed.

## 2. Root cause and production closure

The original merged-master regression had two production manifestations inside the same lowering authority.

### 2.1 Formal task canonicalization

`_lower_ability_task_tree(...)` initially created a same-occurrence `AbilityTaskIR` and `EffectIR` from the same pre-canonical `IRSource`. `_lower_formal_ability_task_tree(...)` then removed stale formal-topology evidence from the task source while leaving its own effect on the pre-canonical source. Existing A1 process-only validation correctly rejected the pair with:

```text
process_only_task_effect_source_mismatch
```

The first production patch synchronizes only the formal parent task's own effect when all of these hold:

1. final task execution mode is already `process_only`;
2. the task has a non-empty `effect_id`;
3. canonicalization actually changed the parent source;
4. exactly one `EffectIR` has that exact `effect_id`;
5. that effect's old source is exactly the pre-canonical task source.

If any guard fails, the effect is left unchanged and the existing A1 exact-source check remains fail-closed. No child effect is selected by shape/opcode, and decoded-dynamic independent source authority is not overwritten.

### 2.2 Client-only camera post-conversion

Real same-owner action slicing exposed a second path in the same file. `_avatar_action_binding(...)` lowers through formal source context, then `_mark_client_only_trigger_ability_tasks(...)` can post-convert selected `TriggerAbility` tasks from runtime-effect semantics to `process_only` after formal lowering has already completed.

Because those tasks were not yet `process_only` inside `_lower_formal_ability_task_tree(...)`, the first guard correctly did not touch them. After the client-only conversion, however, A1 requires the resulting process-only task/effect pair to have exact source identity.

The second production patch therefore synchronizes only client-only effects when:

1. the effect is in the exact `client_only_effect_ids` set produced by the existing classification pass;
2. exactly one lowered task owns that exact `effect_id`;
3. that task's final execution mode is `process_only`;
4. the effect's old source exactly equals the reconstructed pre-canonical source for that task.

On any ambiguity or source disagreement the code performs no rewrite, preserving fail-closed behavior.

Across both production hunks, `lowering.py` has exactly `46` added lines and `0` deleted lines relative to the fixed base.

## 3. Governance and unchanged authorities

The P1 validator checks the complete fixed-base diff and rejects any changed path outside the card allowlist. On validated head `e98f531a227ab7ccc893f15e0ebe480fd573d5c9`, the changed paths before adding this report were:

```text
.github/workflows/p9-a2-p1-pr-validation.yml
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9-A2-P1_FORMAL_PROCESS_ONLY_SOURCE_IDENTITY.md
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p1_formal_process_only_source_identity.py
```

The validator requires the following A1/public authority paths to remain byte-for-byte equal to fixed base:

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/action_contract.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/ability_task_contract.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/task_graph.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/task_graph.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/ir_types.py
```

It also requires `_lower_ability_task_tree(...)` to remain AST-identical to fixed base, while the two intended source-identity authorities `_lower_formal_ability_task_tree(...)` and `_mark_client_only_trigger_ability_tasks(...)` must differ from fixed base.

The workflow uses GitHub-hosted `ubuntu-latest`, `permissions: contents: read`, `persist-credentials: false`, recursive submodule checkout, and an explicit PR-head SHA checkout with an expected/actual SHA assertion.

## 4. Fast validation

Run `34320254691` checked out exactly:

```text
e98f531a227ab7ccc893f15e0ebe480fd573d5c9
```

and pinned submodule:

```text
14c1d18f91a8101d610e6c523447a7517de3fae1
```

Compile passed for `tbgd/lowering.py` and the P1 validator.

Fast passed with all predicates true, including:

```text
exact_match_guard_present=true
source_mismatch_still_fail_closed=true
missing_effect_still_fail_closed=true
a1_fast_regression_pass=true
no_state_mutation_rng_or_event_execution=true
```

The existing A1 Fast suite also passed every predicate, including invalid process-only contract fail-closed behavior, active-cycle/deferred/unresolved-reference fail-closed behavior, external-legacy preservation, and no state mutation/RNG/graph execution.

P1 Fast wall time reported by the validator: `1.464814 s`.

## 5. Real pinned-TBGD Direct denominator

Direct used the pinned TBGD character source graph plus authoritative formal source context. Nested formal/template children are included through the production formal traversal and are fingerprinted by `formal_context.content_sha256_by_path`; the denominator is not restricted to only directly rooted source files.

A raw occurrence may legitimately project into more than one formal phase/action binding, so Direct keeps raw occurrence identity separately while using:

```text
task_id + effect_id + raw_occurrence_key
```

as the unique projected pair identity. No rows are removed or collapsed by opcode/shape.

Run `34320254691` produced:

```text
formal_process_only_task_effect_pair_count = 5073
baseline_mismatch_count = 5073
baseline_normalization_explained_mismatch_count = 5073
current_mismatch_count = 0
missing_process_only_effect_count = 0
independent_process_only_pair_count = 0
independent_process_only_effect_source_rewritten_count = 0
non_process_only_pair_count = 8120
non_process_only_effect_source_rewritten_count = 0
```

Source and identity evidence:

```text
source_fingerprint = 349d9dd2ade62d32e17b25a49400c8043dfdf0cea73250aa0ee4bc23fcedb998
pair_identity_digest = 892b39fb496fca3a2d7b83254ac76532373e1fe88a278ef499bc752077317268
topology_digest = bce19a11691522775ecf23f5e24c39dde3dfd3c025523b4d7e1e278505b96ad2
```

Thus every one of the 5073 baseline same-occurrence process-only mismatches is explained by the exact topology-source normalization under this card, and the current production denominator closes all 5073 without rewriting non-process-only or independent-source effects.

## 6. Same-owner A1 blocker delta

Direct dynamically selected an ordinary current-production representative through production action definition discovery, target query/accept, action admission and the existing `ActionContractSystem.evaluate(...)`. The representative is report evidence, not an allowlist:

```text
definition_id = action_def:avatar_skill:100101:1
action_id = avatar_skill:100101
action_level = 1
admission_id = action_admission:avatar:1001:avatar_skill:100101:level:1
submission_mode = external_turn
```

Baseline reachable blockers were:

```text
process_only_task_effect_source_mismatch
ability_task_graph_nested_identity_mismatch
task_graph_control_requires_domains:hit_random_sequence
task_graph_definition_not_admitted:effect:audit_only
effect_coverage_status:unsupported:FireProjectile
task_graph_definition_not_admitted:effect:unsupported
task_graph_control_requires_domains:damage_heal_shield
```

Current reachable blockers are exactly the same list with only:

```text
process_only_task_effect_source_mismatch
```

removed.

The action correctly remains fail-closed because unrelated future-domain blockers remain. Direct reports:

```text
same_owner_a1_process_only_mismatch_blocker_removed = true
other_reachable_blockers_preserved = true
future_domain_blockers_removed_count = 0
runtime_mutation_count = 0
```

The final `ActionContractSystem` blocked reason remains:

```text
ability_task_graph_nested_identity_mismatch,
task_graph_control_requires_domains:hit_random_sequence,
task_graph_definition_not_admitted:effect:audit_only,
effect_coverage_status:unsupported:FireProjectile,
task_graph_definition_not_admitted:effect:unsupported,
task_graph_control_requires_domains:damage_heal_shield
```

This is the expected Route-A result: P1 removes only its own source-identity blocker and does not make the action executable by consuming later-domain work.

## 7. Direct predicates and resource evidence

Every P1 Direct predicate passed, including:

```text
exact_base=true
pinned_tbgd=true
production_write_authority_is_lowering_only=true
formal_process_only_pair_denominator_nonempty=true
baseline_source_mismatch_reproduced=true
baseline_mismatch_uniquely_topology_normalization=true
current_source_mismatch_count_zero=true
same_owner_a1_mismatch_removed=true
other_reachable_blockers_preserved=true
process_only_contract_weakened_false=true
a1_authority_changed_false=true
task_graph_materializer_changed_false=true
runtime_changed_false=true
non_process_only_effect_source_rewritten_count_zero=true
independent_process_only_source_rewritten_count_zero=true
runtime_mutation_count_zero=true
runtime_rng_draw_count_zero=true
full_canonical_ir_build_count_zero=true
pr11_code_used_false=true
pr9_unmerged_code_used_false=true
```

Resource evidence from the successful P1 run:

```text
baseline probe wall_seconds = 19.301521
validator Direct wall_seconds = 41.694535
validator peak_rss_kib = 469740
/usr/bin/time elapsed = 42.41 s
/usr/bin/time maximum RSS = 491420 KiB
```

No full `CanonicalIR.build()` was used by Direct; the validation stays on the existing focused character production projection.

## 8. Fixed-base and CI evidence

Run `34320254691` executed and passed:

```text
python -m compileall -q \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p1_formal_process_only_source_identity.py

python hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p1_formal_process_only_source_identity.py --fast

python hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p1_formal_process_only_source_identity.py --direct

git diff --check 770a0649926932794585fcd30589c6776892bc3b HEAD
```

The P0 regression workflow `34320254696` also passed compile, Fast, Direct and fixed-base diff on the same code head.

The final report-only commit must receive its own exact-head P1/P0 CI before EXEC hands off to REVIEW. Until that final committed-head run is green, this report does not claim `ci_pass=true` for the final PR head.

## 9. Completion matrix at validated code head

```text
exact_base_is_770a0649926932794585fcd30589c6776892bc3b=true
production_write_authority_is_lowering_only=true
formal_process_only_pair_denominator_nonempty=true
formal_process_only_task_effect_source_mismatch_count=0
same_owner_a1_process_only_mismatch_blocker_removed=true
other_reachable_blockers_preserved=true
process_only_contract_weakened=false
a1_authority_changed=false
task_graph_materializer_changed=false
runtime_changed=false
pr11_code_used=false
pr9_unmerged_code_used=false
fast_pass=true
direct_pass=true
git_diff_check_pass=true
execution_report_complete=true
final_report_head_ci_pass=pending
```

After the report commit, EXEC records the exact final head and CI run IDs in the PR. Only after those runs pass may EXEC post `[HANDOFF:REVIEW]` and mark the PR ready. REVIEW remains responsible for independent acceptance, checklist/governance checkpointing, and merge.
