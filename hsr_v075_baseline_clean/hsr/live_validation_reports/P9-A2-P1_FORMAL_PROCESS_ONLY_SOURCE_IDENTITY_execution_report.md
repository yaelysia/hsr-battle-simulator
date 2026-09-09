# P9-A2-P1 Formal process-only source identity — Execution Report

## 1. Scope, authority, and validated code head

- Fixed base: `master@770a0649926932794585fcd30589c6776892bc3b`.
- Pinned TBGD source: `14c1d18f91a8101d610e6c523447a7517de3fae1`.
- Card: `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9-A2-P1_FORMAL_PROCESS_ONLY_SOURCE_IDENTITY.md`.
- Only production file changed: `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py`.
- Latest code/validator head validated before this report update: `cfc6b17c8ede0a923f3e301ab58903916a8d46fb`.
- P1 exact-head CI run: `34329570230`, job `102394727550`, conclusion `success`.
- P0 regression CI run on the same head: `34329570074`, job `102394727332`, conclusion `success`.
- S8C1A workflow `34329570104` was path-filter skipped and is not counted as a pass.
- REVIEW return requiring executable STRICT Fast evidence: PR comment `5597805187`.

This report update creates a later report-only PR head. Its exact SHA and final committed-head CI are recorded in the subsequent PR WAIT/HANDOFF comment because a commit cannot contain its own SHA before it exists.

No PR #11 or PR #9 unmerged business implementation was read or reused. No A1 authority, task-graph materializer, runtime executor, RNG authority, public IR equality semantics, dependency, runner class, secret, or workflow write permission was changed by the REVIEW remediation.

## 2. Root cause and production closure

The merged-master regression had two manifestations inside the same allowed lowering authority.

### 2.1 Formal task canonicalization

`_lower_ability_task_tree(...)` initially creates a same-occurrence `AbilityTaskIR` and `EffectIR` from the same pre-canonical `IRSource`. `_lower_formal_ability_task_tree(...)` then removes stale formal-topology evidence from the task source. Before P1, the task's own effect retained the pre-canonical source, so the existing A1 process-only consumer correctly rejected the pair with:

```text
process_only_task_effect_source_mismatch
```

The first production hunk synchronizes only the formal parent task's own effect when all of these hold:

1. final task execution mode is already `process_only`;
2. the task has a non-empty `effect_id`;
3. canonicalization actually changed the parent source;
4. exactly one `EffectIR` has that exact `effect_id`;
5. that effect's old source is exactly the pre-canonical task source.

If any guard fails, the effect is left unchanged and the existing A1 exact-source check remains fail-closed. No child effect is selected by shape/opcode, and decoded-dynamic independent source authority is not overwritten.

### 2.2 Client-only camera post-conversion

Real same-owner action slicing exposed a second path in the same file. `_avatar_action_binding(...)` lowers through formal source context, then `_mark_client_only_trigger_ability_tasks(...)` can post-convert selected `TriggerAbility` tasks from runtime-effect semantics to `process_only` after formal lowering has completed.

Because those tasks are not yet `process_only` inside `_lower_formal_ability_task_tree(...)`, the first guard correctly does not touch them. After the client-only conversion, however, A1 requires the resulting process-only task/effect pair to have exact source identity.

The second production hunk synchronizes only client-only effects when:

1. the effect is in the exact `client_only_effect_ids` set produced by the existing classification pass;
2. exactly one lowered task owns that exact `effect_id`;
3. that task's final execution mode is `process_only`;
4. the effect's old source exactly equals the reconstructed pre-canonical source for that task.

On ambiguity or source disagreement the code performs no rewrite, preserving fail-closed behavior.

Across both production hunks, `lowering.py` has exactly `46` added lines and `0` deleted lines relative to the fixed base.

## 3. Governance and unchanged authorities

The dedicated P1 validator checks the complete fixed-base diff and rejects any changed path outside the card allowlist. On validated head `cfc6b17c8ede0a923f3e301ab58903916a8d46fb`, the changed paths were exactly:

```text
.github/workflows/p9-a2-p1-pr-validation.yml
hsr_v075_baseline_clean/hsr/live_validation_reports/P9-A2-P1_FORMAL_PROCESS_ONLY_SOURCE_IDENTITY_execution_report.md
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

## 4. REVIEW Fast-evidence remediation

REVIEW comment `5597805187` correctly rejected the prior Fast evidence because it proved the exact source patch text/AST and the downstream consumer fail-closed behavior, but did not actually execute the card §6 lowering behavior matrix.

The remediation changes only the dedicated validator. Production, Direct denominator logic, A1, runtime and task-graph materialization remain unchanged.

### 4.1 Initial executable matrix and fixture correction

Validator head `1af6ecd26317981a0664194afed1e806a90956cf` added the executable Fast matrix. P1 run `34324861792` compiled successfully but failed in Fast before Direct because the JSON-path conflict fixture used an out-of-range list index. Production `_value_at_rooted_json_path(...)` correctly failed closed with:

```text
IndexError: $.AbilityList[0].OnStart[1]
```

The validator helper had expected a later `ValueError`, so the failure was a fixture/API exception-shape assumption, not a production semantic failure. P0 run `34324861797` remained fully green on that head.

Commit `cfc6b17c8ede0a923f3e301ab58903916a8d46fb` changed only that fixture path from the out-of-range path to the existing-but-wrong object path:

```text
$.AbilityList[0]
```

This reaches the production formal-source identity check and fails closed with the intended error:

```text
formal ability task payload does not match its source
```

No production, Direct, denominator or governance assertion was relaxed.

### 4.2 Actual Fast behavior matrix on cfc6b17

Run `34329570230` checked out exactly:

```text
cfc6b17c8ede0a923f3e301ab58903916a8d46fb
```

with pinned submodule:

```text
14c1d18f91a8101d610e6c523447a7517de3fae1
```

Compile passed for `tbgd/lowering.py` and the dedicated P1 validator.

Fast then executed real production lowering/helpers with minimal IR/source-backed fixtures while guarding against task-graph execution, condition evaluation and RNG. All returned predicates were true:

```text
formal_process_only_source_sync_executed=true
formal_non_process_only_effect_source_preserved=true
distinct_raw_occurrences_not_merged=true
source_path_conflict_fail_closed=true
json_path_conflict_fail_closed=true
fingerprint_conflict_fail_closed=true
formal_ambiguity_no_rewrite=true
formal_source_disagreement_no_rewrite=true
client_only_source_sync_executed=true
client_only_non_candidate_no_rewrite=true
client_only_ambiguity_no_rewrite=true
client_only_source_disagreement_no_rewrite=true
task_identity_preserved=true
effect_identity_preserved=true
consumer_valid_pair_admitted=true
consumer_source_mismatch_fail_closed=true
consumer_missing_effect_fail_closed=true
a1_fast_regression_pass=true
runtime_execution_condition_rng_guards_not_hit=true
```

The formal process-only positive case proved:

```text
initial_source_equal=true
canonical_source_equal=true
task_identity_preserved=true
effect_identity_preserved=true
```

The non-process-only formal case proved:

```text
effect_source_preserved=true
task_identity_preserved=true
effect_identity_preserved=true
```

The formal fail-closed matrix observed these actual production errors/results:

```text
source_path = formal ability task source document is missing
json_path = formal ability task payload does not match its source
fingerprint = formal ability task source fingerprint is missing
ambiguity_no_rewrite = true
source_disagreement_no_rewrite = true
```

The client-only post-conversion matrix used two same-opcode/same-shape but distinct raw occurrences and proved:

```text
positive_pair_count = 2
distinct raw occurrence sources remain separate
source synchronization executed for each own pair
task_identity_preserved = true
effect_identity_preserved = true
non_candidate_no_rewrite = true
ambiguity_no_rewrite = true
source_disagreement_no_rewrite = true
```

The original A1 process-only consumer minimum cases also still pass:

```text
valid = ""
mismatch = process_only_task_effect_source_mismatch
missing = process_only_task_effect_missing
```

Every existing A1 Fast predicate remained true, including invalid process-only contract fail-closed behavior, active-cycle/deferred/unresolved-reference fail-closed behavior, external-legacy preservation and no state mutation/RNG/graph execution.

P1 Fast validator wall time: `1.396769 s`; `/usr/bin/time` elapsed: `2.69 s`; maximum RSS: `134136 KiB`.

This closes the exact STRICT Fast evidence gap identified by REVIEW.

## 5. Real pinned-TBGD Direct denominator

Direct used the pinned TBGD character source graph plus authoritative formal source context. Nested formal/template children are included through the production formal traversal and are fingerprinted by `formal_context.content_sha256_by_path`; the denominator is not restricted to only directly rooted source files.

A raw occurrence may legitimately project into more than one formal phase/action binding, so Direct keeps raw occurrence identity separately while using:

```text
task_id + effect_id + raw_occurrence_key
```

as the unique projected pair identity. No rows are removed or collapsed by opcode/shape.

Run `34329570230` produced:

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

Every P1 Direct predicate passed on `cfc6b17c8ede0a923f3e301ab58903916a8d46fb`, including:

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

Resource evidence from run `34329570230`:

```text
baseline probe wall_seconds = 18.559178
validator Direct wall_seconds = 39.871317
validator peak_rss_kib = 471392
/usr/bin/time elapsed = 40.59 s
/usr/bin/time maximum RSS = 492076 KiB
```

No full `CanonicalIR.build()` was used by Direct; validation stays on the existing focused character production projection.

## 8. Fixed-base and CI evidence at validated code head

Run `34329570230` executed and passed:

```text
python -m compileall -q \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p1_formal_process_only_source_identity.py

python hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p1_formal_process_only_source_identity.py --fast

python hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p1_formal_process_only_source_identity.py --direct

git diff --check 770a0649926932794585fcd30589c6776892bc3b HEAD
```

The P0 regression workflow `34329570074` also passed compile, Fast, Direct and fixed-base diff on the same head.

The report-only commit produced by this update must receive its own exact-head P1/P0 CI before EXEC hands off to REVIEW. Until that final committed-head run is green, this report does not claim `ci_pass=true` for the final PR head.

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
strict_fast_behavior_matrix_pass=true
direct_pass=true
p0_regression_pass=true
git_diff_check_pass=true
execution_report_updated_for_review_return_5597805187=true
final_report_head_ci_pass=pending
```

After this report commit, EXEC records the exact final head and CI run IDs in the PR. Only after those runs pass may EXEC post a new `[HANDOFF:REVIEW]` and mark the PR ready. REVIEW remains responsible for independent acceptance, checklist/governance checkpointing and merge.
