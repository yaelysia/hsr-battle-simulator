# P9-A2-P2 Process-only TriggerAbility admission identity — Execution Report

## 1. Scope and authority

- Fixed base: `master@f6ea5d2e2d067cb8cecb82bb28faf14beb2a29b4`.
- Pinned TBGD: `14c1d18f91a8101d610e6c523447a7517de3fae1`.
- Execution card: `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9-A2-P2_PROCESS_ONLY_TRIGGER_ABILITY_ADMISSION_IDENTITY.md`.
- Production implementation commit: `3ad34fae11f3b63f6a6e31659f94b289246e646c`.
- Validator/workflow head validated before this report commit: `a2249c1cb58d17cedce9e49c86bd4e917a246082`.
- Only production file changed: `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/action_contract.py`.

This card closes only the A1 admission-projection mismatch where a canonical, accepted process-only `TriggerAbility` leaf was being reinterpreted as a nested gameplay edge from opcode alone. It does not implement S8C, S11, insert-window authorization, A2 runtime transport, PR #9 RNG/caller work, or PR #11 unmerged business code.

The report commit necessarily creates a later PR head, so its own SHA and final exact-head CI cannot be embedded in this file before that commit exists. Those values are recorded in the subsequent PR `[WAIT:CI]` / `[HANDOFF:REVIEW]` comment.

## 2. Production change

`_formal_action_task_graph_projection(...)` now distinguishes the already-accepted process-only identity before deciding whether the node participates in nested gameplay traversal:

```python
process_only = is_process_only_ability_task(task)
nested_node = node.node_kind == "ability_call" or (
    task.opcode == "TriggerAbility" and not process_only
)
```

The nested identity gate additionally rejects `process_only` if a canonical node is nevertheless shaped as `ability_call`. Therefore:

- valid process-only `TriggerAbility` + materialized `leaf` no longer enters nested reference/graph traversal;
- process-only `ability_call` remains fail-closed with `ability_task_graph_nested_identity_mismatch`;
- non-process-only `TriggerAbility` materialized as `leaf` remains fail-closed;
- non-TriggerAbility materialized as `ability_call` remains fail-closed;
- real gameplay `TriggerAbility -> ability_call -> exact ability reference -> exact linked nested_only graph` checks are unchanged.

No materializer, lowering, runtime executor, process-only contract, public IR, target/admission, resource, event/status, mutation, RNG, settlement, replay, dependency, secret, or runner authority was changed.

## 3. Governance

On validated head `a2249c1cb58d17cedce9e49c86bd4e917a246082`, the fixed-base changed paths were exactly:

```text
.github/workflows/p9-a2-p2-pr-validation.yml
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9-A2-P2_PROCESS_ONLY_TRIGGER_ABILITY_ADMISSION_IDENTITY.md
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/action_contract.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p2_process_only_trigger_ability_admission_identity.py
```

After this report is committed, the only additional allowed path is:

```text
hsr_v075_baseline_clean/hsr/live_validation_reports/P9-A2-P2_PROCESS_ONLY_TRIGGER_ABILITY_ADMISSION_IDENTITY_execution_report.md
```

The focused validator compares all card-declared read-only authorities byte-for-byte to the fixed base and requires the sole production path to be `systems/action_contract.py`.

## 4. Fast validation

Exact-head hosted run `34568743472`, job `103166126947`, checked out exactly:

```text
expected_head=a2249c1cb58d17cedce9e49c86bd4e917a246082
actual_head=a2249c1cb58d17cedce9e49c86bd4e917a246082
TBGD=14c1d18f91a8101d610e6c523447a7517de3fae1
```

Scoped compile passed. P2 Fast returned `ok=true` with all predicates true:

```text
process_only_trigger_leaf_admitted
invalid_process_only_contract_fail_closed
gameplay_nested_identity_fail_closed
nested_reference_link_fail_closed
reachable_future_blocker_preserved
projection_deterministic
a1_fast_regression
no_runtime_execution_condition_or_rng
```

The matrix directly exercised production `_formal_action_task_graph_projection(...)` using existing A1 fixture helpers. It covered valid process-only leaf admission, process-only source/effect failure, missing effect, process-only `ability_call`, gameplay `TriggerAbility` leaf, ordinary-task `ability_call`, valid gameplay nested traversal with downstream blocker, missing/unresolved/ambiguous nested references, linked phase/standalone mismatch, reachable unsupported gameplay, deterministic projection, and the existing A1 Fast regression.

P2 Fast resource evidence:

```text
validator wall = 0.034702 s
/usr/bin/time elapsed = 1.56 s
maximum RSS = 96228 KiB
```

The independent existing A1 Fast regression in the same exact-head run also passed all 11 predicates, including active-cycle, deferred-node, unresolved gameplay reference, external-legacy, invalid process-only, reachable nested blocker, determinism, and no runtime execution/state mutation/RNG. `/usr/bin/time` elapsed was `1.43 s`, maximum RSS `94300 KiB`.

## 5. STRICT real-source Direct

The P2 Direct used pinned TBGD plus current production lowering, action definition discovery, formal graph materialization, public target query/accept, ActionAdmission and `ActionContractSystem.evaluate(...)`. The representative was discovered dynamically; it is evidence, not an allowlist:

```text
definition_id = action_def:avatar_skill:100101:1
action_id = avatar_skill:100101
action_level = 1
admission_id = action_admission:avatar:1001:avatar_skill:100101:level:1
submission_mode = external_turn
source_fingerprint = 349d9dd2ade62d32e17b25a49400c8043dfdf0cea73250aa0ee4bc23fcedb998
eligible_external_turn_candidates = 1
scanned_action_definitions = 1
```

The fixed-base probe dynamically found exactly one matching mismatch candidate/occurrence. Its exact reachable task was:

```text
ability_task:ability_phase:avatar_skill:100101:1:0:Avatar_Mar_7th_00_Skill01_Phase01:OnStart:OnStart[0]:TriggerAbility
```

and Direct proved all required root-cause facts:

```text
opcode = TriggerAbility
execution_mode = process_only
node_kind = leaf
materialization_status = materialized
runtime_support_blocked_reason = ""
source_path = Config/ConfigAbility/Avatar/Avatar_Mar_7th_00_Ability.json
json_path = $.AbilityList[0].OnStart[0]
```

Fixed-base reachable blockers were:

```text
ability_task_graph_nested_identity_mismatch
task_graph_control_requires_domains:hit_random_sequence
task_graph_definition_not_admitted:effect:audit_only
effect_coverage_status:unsupported:FireProjectile
task_graph_definition_not_admitted:effect:unsupported
task_graph_control_requires_domains:damage_heal_shield
```

Current reachable blockers were exactly the same list with only `ability_task_graph_nested_identity_mismatch` removed:

```text
task_graph_control_requires_domains:hit_random_sequence
task_graph_definition_not_admitted:effect:audit_only
effect_coverage_status:unsupported:FireProjectile
task_graph_definition_not_admitted:effect:unsupported
task_graph_control_requires_domains:damage_heal_shield
```

The Direct comparison also proved:

- only the `nested_node_identity` provenance row for that process-only leaf was removed;
- root graph IDs, reachable task IDs and excluded bound task IDs were unchanged;
- all non-P2 blocker provenance was unchanged and retained in order;
- `ActionContractSystem.evaluate(...)` remained `ok=false` because the future-domain blockers above still fail closed;
- current mismatch candidate/occurrence count became zero;
- full `TBGDLowering.build()` count remained zero;
- runtime mutation count, RNG draw count, graph execution count and condition-evaluation count remained zero.

P2 Direct resource evidence:

```text
baseline probe wall = 14.904417 s
current validator wall = 31.236775 s
/usr/bin/time elapsed = 32.69 s
maximum RSS = 412988 KiB
```

All are within the card budget.

## 6. Hosted CI evidence

Primary exact-head gate:

```text
run 34568743472 — P9 A2 P2 PR validation — success
job 103166126947 — success
head a2249c1cb58d17cedce9e49c86bd4e917a246082
```

It passed exact-head assertion, pinned submodule assertion, scoped compile, P2 Fast, A1 Fast regression, P2 Direct and `git diff --check f6ea5d2e2d067cb8cecb82bb28faf14beb2a29b4 HEAD`.

Supplementary compatibility regression:

```text
run 34568743466 — P9 S8C1B PR Validation — success
job 103166127658 — success
```

That pre-existing workflow checks out GitHub's PR merge ref (`00c4d49d71c20ae88638e9a2d97b626912f7083d`, merge of `a2249c1...` into the same base), not the exact PR head, so it is not counted as the P2 final-head gate. It nevertheless passed scoped compile, S8C1A/S8C1B Fast+Direct, A1 Fast+Direct and base diff-check. Its A1 Direct remained fail-closed and completed in `2:48.21` with maximum RSS `573576 KiB`.

No local repository validation result is claimed: the earlier available container could not resolve `github.com` (`Could not resolve host: github.com`), and no replacement dependency environment was created. The committed hosted validation above is the executed evidence.

## 7. Remaining scope and next stage

P2 completion does not close the remaining S8C/S11/future-domain blockers and does not automatically resume PR #11. PR #11 remains paused. After independent REVIEW accepts and squash-merges this predecessor, PLAN must recompute same-owner outer-action blocker attribution from the new merged master. Only when that predecessor chain is empty may PR #11 resume its original Fast plus real `CombatExecutor.execute(ActionCommand)` Direct.

PR #9 remains paused until PR #11 is independently accepted and merged.
