# P9-S8C1C Remaining Entry RandomConfig Source Closure — Execution Report

## Scope and immutable baseline

- Stage: `P9-S8C1C_REMAINING_ENTRY_RANDOM_CONFIG_SOURCE_CLOSURE`
- Fixed base: `f0701b69911d28451f560e3bed354ead355a2865`
- FIX1 production/validator/CI code-validation head: `4df688b7c76f26b3b0c6bf7b623a5fc303c1d2bb`
- Previous pre-review report head: `7865baf738294ff6ea2d74a5acd564ba7fe077ef`
- PR: `https://github.com/yaelysia/hsr-battle-simulator/pull/3`
- Branch: `exec/p9-s8c1c-random-config-source-closure`
- Execution card: `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9-S8C1C_REMAINING_ENTRY_RANDOM_CONFIG_SOURCE_CLOSURE.md`
- This report intentionally does **not** claim the commit SHA that contains this report update. The final PR head and final report-head CI are supplied separately in the ready-for-review handoff and PR execution comment.

## Independent-review FIX1 finding and remediation

The first independent review returned `return_for_fix` for one validator-completeness defect. Production code was not found to require redesign.

The defect was in Catalog validation: `_action_catalogs()` grouped `ActionDefinitionIR` by `action_id` and selected `min(level)`. Because production `definition_id` includes both action identity and level, distinct levels are distinct formal producer instances. The original source-key denominator `(source_path, json_path, family, content_sha256)` could therefore collapse multiple formal positions sharing one `RandomConfig` source, and a missing graph/selection for one level could escape detection.

FIX1 closes that gap without changing source authority, formal topology, `EntryKind`, or runtime behavior:

1. Action discovery is still dynamic and source-driven. The validator first discovers action IDs from the accepted source-graph relationships that reach `RandomConfig`; it does not hard-code business IDs.
2. After that pre-IR RandomConfig/source/reference narrowing, **all** `ActionDefinitionIR` values for every relevant action ID are retained. There is no `min(level)` selection.
3. The retained definitions are passed once through the existing production narrow lowering `_lower_action_ability_bindings(...)`, then through the existing task-graph materializer. This avoids a full canonical build and avoids repeatedly rebuilding unrelated card/target/action layers per level.
4. Every formal phase is mapped back through `phase.binding_id -> ActionAbilityBindingIR(action_id, level) -> ActionDefinitionIR.definition_id`, preserving the level-specific producer instance.
5. A separate `_FormalPositionKey` denominator records `producer_kind`, `producer_instance_id`, `entry_kind`, owner/callback identity, `formal_task_id`, exact source identity, and fingerprint. Expected positions are built from formal tasks **before** graph audit; actual positions are built independently from production graph nodes plus unique weighted selections. Catalog requires exact expected/actual equality.
6. Raw denominator/S8A/source-ledger closure remains a separate source-key audit. Formal-position multiplicity is not substituted for the raw source denominator and vice versa.
7. `all_formal_random_config_nodes_have_exactly_one_weighted_selection` is no longer a constant success value; it derives from formal-position expected/actual equality.
8. Fast now includes a minimal STRICT negative where two distinct action definition/level instances share one `RandomConfig` source and the actual formal-position set deliberately omits one instance. The audit must reject that case.

No production file was changed by FIX1. The two FIX1 validator commits were:

- `d6331744f8fd013467b55364fb5d043fbbb35830` — enumerate every relevant action definition/level, add formal-position denominator and STRICT shared-source/missing-level negative.
- `4df688b7c76f26b3b0c6bf7b623a5fc303c1d2bb` — retain the same complete level denominator while batching production narrow action lowering so Catalog remains within its resource budget.

The first implementation at `d633174...` passed compile/Fast/Direct and proved a real 57/57 formal-position closure for the dynamically selected Direct action levels, but Catalog hit its `180s` hard timeout because it repeatedly built a full action slice for every level. That was a validator performance defect only. The batched narrow projection at `4df688...` reduced Catalog to roughly 56 seconds outer wall while preserving complete formal-instance enumeration.

## Actual PR diff at FIX1 code-validation head

Against fixed base `f0701b69911d28451f560e3bed354ead355a2865`, code-validation head `4df688b7c76f26b3b0c6bf7b623a5fc303c1d2bb` contains only the planned/allowed PR paths:

- `.github/workflows/p9-s8c1c-pr-validation.yml` — PR-scoped STRICT validation workflow.
- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9-S8C1C_REMAINING_ENTRY_RANDOM_CONFIG_SOURCE_CLOSURE.md` — planning artifact; execution did not modify it.
- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/task_graph.py` — production entry-neutral RandomConfig weighted-selection invariant from the original execution.
- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py` — production entry-neutral RandomConfig attachment from the original execution.
- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_s8c1c_remaining_entry_random_config_source_closure.py` — S8C1C Fast/Direct/Catalog validator, including FIX1 multiplicity audit.
- `hsr_v075_baseline_clean/hsr/live_validation_reports/P9-S8C1C_REMAINING_ENTRY_RANDOM_CONFIG_SOURCE_CLOSURE_execution_report.md` — this report lineage.

The FIX1 delta from `7865baf...` through `4df688...` changed only the authorized S8C1C validator before this report update.

## Production result

The production result from the original S8C1C execution remains unchanged by FIX1:

- `TaskGraphIR` requires the weighted-selection parent-node set to equal the formal `RandomConfig` node set, for both current `EntryKind` values.
- The existing shared `_materialize_weighted_selection(...)` is attached for every formal `RandomConfig` node without an ability-only gate.
- Status and ability entries share the same signed `CharacterAbilityRawSnapshot`, S8A branch topology, numeric lowering and task-graph materializer.
- Non-`RandomConfig` nodes cannot carry weighted selections.
- No RNG evaluation, probability normalization, random branch execution, runtime producer/consumer, or third `EntryKind` was introduced.

## FIX1 Fast and focused validation evidence

Successful code-validation workflow:

- workflow: `P9 S8C1C PR Validation`
- run: `https://github.com/yaelysia/hsr-battle-simulator/actions/runs/33847811985`
- job: `100943551238`
- validated branch head: `4df688b7c76f26b3b0c6bf7b623a5fc303c1d2bb`
- PR merge checkout SHA: `13e0edb5cde50e73e2f385cb56613ee3b4859d16`
- result: `success`
- run interval: `2026-09-04T07:14:18Z` to `2026-09-04T07:19:02Z` (about `4m44s`, below the `<8min` job budget)

All commands below exited `0`; resource values are the outer `/usr/bin/time -v` measurements from the successful run.

| Check | Command | Exit | Wall | Peak RSS |
| --- | --- | ---: | ---: | ---: |
| scoped compile | `PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/task_graph.py hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_s8c1c_remaining_entry_random_config_source_closure.py` | 0 | 0.11 s | 18,684 KiB |
| S8C1A focused | `PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c1a_weighted_selection_ir` | 0 | 0.57 s | 38,892 KiB |
| S8C1B Fast regression | `PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c1b_action_entry_weighted_selection --fast` | 0 | 0.97 s | 88,032 KiB |
| S8C1C Fast + STRICT negatives | `PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c1c_remaining_entry_random_config_source_closure --fast` | 0 | 0.86 s | 88,328 KiB |
| base-to-HEAD diff check | `git diff --check f0701b69911d28451f560e3bed354ead355a2865 HEAD` | 0 | 0.00 s | 6,584 KiB |

S8C1C Fast emitted `cases=8`, `ok=true`. In addition to the original S8C1C fail-closed cases, FIX1 explicitly emitted:

```text
shared_source_multiple_action_levels_missing_position_fail_closed=true
```

That negative constructs two distinct formal action-definition positions sharing one source key, deliberately supplies only one actual position, and verifies that the formal-position denominator rejects the omission. It therefore tests the exact multiplicity defect identified by independent review rather than merely checking source-key presence.

## Direct real-source evidence after FIX1

Command:

```bash
PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c1c_remaining_entry_random_config_source_closure --direct
```

Result on code-validation head: exit `0`, `ok=true`; validator internal wall `49.324002 s`, outer wall `51.53 s`, peak RSS `593,636 KiB`.

Direct dynamically discovered its action source and enumerated every level for the selected relevant action. The emitted action-definition evidence contained ten distinct levels/definition IDs for that action. The independent formal-position denominator reported:

- expected formal positions: `57`
- actual graph+selection positions: `57`
- formal-position fingerprint: `1633da0ba54740368e7cefa7dc4cef0d8588b82b450be75d2b46d1e62647bbc5`
- enumerated action definitions: `10`
- random-bearing action definitions: `10`
- `full_canonical_ir_build_count=0`

The raw-source denominator remained independently reproducible at:

- source occurrences: `24`
- source fingerprint: `dba388b88cd4a3bf18be1728dce2bb10e64f7328153277fa551870e5a934ddc2`

Direct still dynamically found real `formal_bound` action, status and template producer classes; queue/standalone remained `zero_by_denominator`. A real status callback was checked against both `materialize_status_callback_task_graph(...)` and the combined character-runtime catalog, and a real non-RandomConfig node was verified to have no weighted selection. Direct did not build a full canonical IR or execute RNG.

## Catalog STRICT complete source and formal-position evidence after FIX1

Command:

```bash
PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c1c_remaining_entry_random_config_source_closure --catalog
```

Result on code-validation head: exit `0`, `ok=true`; validator internal wall `54.066472 s`, outer wall `56.38 s`, peak RSS `664,876 KiB`.

### Raw/S8A/source-ledger denominator

The existing source-key audit remains independent from formal multiplicity and remained unchanged:

- complete RandomConfig raw denominator: `24`
- denominator fingerprint: `dba388b88cd4a3bf18be1728dce2bb10e64f7328153277fa551870e5a934ddc2`
- `formal_bound`: `14`
- `no_formal_producer`: `10`
- formal-bound template source occurrences: `3`
- independent raw denominator == S8A RandomConfig nodes == production complete task-graph source ledger

Representative `no_formal_producer` evidence was again dynamically obtained from accepted shared-global template sources. These records have no accepted formal reference/materialization, retain their downstream `hit_random_sequence` owner, and do not receive synthetic entries or graphs.

### Independent formal-position denominator

Catalog first narrowed action candidates from accepted RandomConfig/source/reference relationships, then enumerated **all** `ActionDefinitionIR` rows for those relevant action IDs. On the current data this produced:

- enumerated relevant action definitions: `55`
- random-bearing action definitions: `55`
- distinct formal-position expected count: `117`
- distinct actual graph+unique-selection count: `117`
- formal-position fingerprint: `4299a3c7e231f0440faf19d31ef2cc5d21dee29d83b25edc3a6365669b2e180f`
- `full_canonical_ir_build_count=0`

The 55 definitions were dynamically distributed across the currently discovered relevant action IDs and all of their levels; no minimum-level representative was substituted. Each expected position includes the level-specific `definition_id`, formal entry owner/callback, formal task identity, exact RandomConfig source and source fingerprint. Each actual position independently comes from a production graph node carrying exactly one matching weighted selection. Exact set equality therefore verifies multiplicity, not merely unique source occurrence coverage.

Catalog emitted all required predicates true, including the new FIX1 predicate:

```text
formal_position_denominator_preserves_instance_multiplicity=true
```

and the previously required predicates:

```text
all_formal_random_config_nodes_have_exactly_one_weighted_selection=true
formal_bound_sources_close_to_every_formal_graph_position_and_selection=true
every_denominator_occurrence_is_exactly_formal_bound_or_no_formal_producer=true
no_formal_producer_sources_have_no_synthetic_entry_or_graph=true
status_single_entry_and_combined_catalog_are_identical=true
action_s8c1b_contract_is_preserved=true
random_config_raw_denominator_is_independently_reproducible=true
s8a_random_config_source_denominator_is_bidirectionally_complete=true
template_source_identity_and_formal_instance_identity_are_not_collapsed=true
full_canonical_ir_build_count=0
runtime_rng_behavior_changed=false
s8c_or_s5d2_claimed_complete=false
```

This directly closes the review scenario: if two formal action definitions/levels share the same source key and one graph/selection is missing, the source-key ledger may still contain that source, but expected/actual `_FormalPositionKey` equality now fails.

## CI and remediation history

Successful FIX1 code-validation run:

- S8C1C run: `33847811985`, job `100943551238`, result `success`, head `4df688b7c76f26b3b0c6bf7b623a5fc303c1d2bb`.
- Legacy S8C1B regression run on the same head: `33847811957`, job `100943550821`, result `success`, including its Direct regression and fixed-base diff check.
- Largest FIX1 S8C1C validator RSS: Catalog `664,876 KiB`, below `1.25 GiB`.
- S8C1C workflow wall: about `4m44s`, below `<8min`.

Remediation sequence:

1. `d6331744f8fd013467b55364fb5d043fbbb35830` introduced complete per-level enumeration and exact formal-position multiplicity auditing. Compile, S8C1A, S8C1B Fast, S8C1C Fast and Direct passed; Direct demonstrated `57/57` positions for all ten levels of its dynamically selected action. Catalog then hit the `180s` validator hard timeout because each definition repeated expensive full action-slice preparation.
2. `4df688b7c76f26b3b0c6bf7b623a5fc303c1d2bb` kept the exact same definition denominator and expected/actual position audit but batched all filtered action definitions through the existing production `_lower_action_ability_bindings(...)` narrow projection. Catalog then passed in `56.38s` outer wall with `117/117` formal positions across 55 relevant definitions.

No production source authority, S8A classification, S8B topology, runtime producer, or allowed write set was changed during FIX1.

## Deferred / explicitly not claimed

Still deferred by the execution card:

- runtime RNG evaluation / branch sampling / probability execution;
- parallel, projectile, and barrier execution semantics;
- P9-S8C1 aggregate and broader S8C runtime closure;
- P9-S5D2 transaction/replay follow-up;
- settlement, audit, and replay semantics.

This report does not mark the project checklist, does not perform independent acceptance, does not merge PR #3, and does not advance a later P9 stage.
