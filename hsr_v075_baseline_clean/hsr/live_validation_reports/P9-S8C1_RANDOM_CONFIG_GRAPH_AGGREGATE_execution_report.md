# P9-S8C1 RandomConfig Graph Aggregate — Execution Report

## Scope and immutable baseline

- Stage: `P9-S8C1`
- Fixed base: `539b2e1b9a7dfb99a319bcda0249ec276b6847df`
- Planning head included by this execution: `1625f78d6d0008496474c0e814c94cd5ea8d4a5a`
- Code-validation head: `3002dae92b9e29e51a660186afe1b851d1dcaa2a`
- PR: `https://github.com/yaelysia/hsr-battle-simulator/pull/4`
- Branch: `exec/p9-s8c1-random-config-aggregate-audit`
- Execution card: `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9-S8C1_RANDOM_CONFIG_GRAPH_AGGREGATE_AUDIT.md`
- Validator: `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_s8c1_random_config_graph_aggregate.py`
- CI: `.github/workflows/p9-s8c1-pr-validation.yml`

This execution did not modify production `rules/`, `tbgd/`, `core/`, `systems/`, RNG, settlement, replay, scenario, or UI code. The execution delta after the planning head is limited to the aggregate validator, this report, and the PR-scoped workflow authorized by the card.

This report intentionally does not claim the commit SHA that contains itself. The final report-containing PR head and its CI are supplied by the structured `[HANDOFF:REVIEW]` comment after the report-head workflow completes.

## Aggregate validator authority and construction

The validator does not import or invoke any earlier P9 validator as an authority. It independently reconstructs and compares three evidence sets from the current pinned TBGD source:

1. **Raw denominator** — direct typed `RandomConfig` occurrences from the current `CharacterAbilityRawSnapshot` plus accepted shared-global template source, preserving source path, JSON path, family, and content SHA-256.
2. **Expected formal positions** — independently derived from current admitted formal producers/tasks before graph materialization. Action producers preserve every concrete action definition/level instance; status callbacks preserve their concrete callback/task identity; currently admitted queue/standalone producers would be included if present.
3. **Actual formal positions** — independently derived only after one combined call to the public production entry `materialize_character_runtime_task_graph_catalog(...)`, from graph nodes and their unique `TaskGraphWeightedSelectionIR` values.

The real Direct/Catalog path never calls `_materialize_weighted_selection(...)` directly. That private helper is used only by the tiny Fast fixture to exercise auditor fail-closed mechanics. `TBGDLowering.build` is patched to fail if a full CanonicalIR build is attempted; both real modes report `full_canonical_ir_build_count=0`.

For each actual formal `RandomConfig` graph node the validator reverses the source bytes, recomputes `OddsList[i]` source occurrence, numeric expression/definition identity, branch identity, choice identity, and exact ordinal mapping. It also rejects orphan/duplicate selections and selections on non-`RandomConfig` nodes.

## Fast / STRICT negative evidence

Command:

```bash
PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c1_random_config_graph_aggregate --fast
```

Result on code-validation head `3002dae92b9e29e51a660186afe1b851d1dcaa2a`: exit `0`, `ok=true`, `cases=7`.

All required mechanical negatives fail closed:

- missing formal producer instance;
- source-key collapse of two producer instances;
- overlap between `formal_bound` and `no_formal_producer`;
- orphan weighted selection;
- duplicate weighted selection identity;
- parent/source fingerprint tamper;
- `OddsList[i]` ordinal/source-path tamper.

CI outer measurement: wall `1.58 s`, peak RSS `88,120 KiB`. Validator internal measurement: wall `0.002662 s`, peak RSS `88,120 KiB`.

## Direct real-source evidence

Command:

```bash
PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c1_random_config_graph_aggregate --direct
```

Result: exit `0`, `ok=true`.

Direct dynamically discovered current producer classes and selected the minimum real action slice needed for representative evidence; no business ID, action ID, status ID, source filename, prior count, or prior fingerprint is hard-coded into selection logic.

Observed current Direct evidence:

- raw denominator count: `24`
- raw denominator fingerprint: `dba388b88cd4a3bf18be1728dce2bb10e64f7328153277fa551870e5a934ddc2`
- representative-slice formal source occurrences: `10`
- representative-slice remainder not materialized by Direct: `14`
- enumerated relevant action definitions/levels in Direct slice: `10`
- expected formal positions: `57`
- actual formal positions: `57`
- formal-position fingerprint: `d7923d82a3ec2431cd998fb28b31bb30e87f20c29ed0e35b9224f56caeb21464`
- dynamically present producer classes: `action_definition`, `status_callback`
- single-entry ability observation equals the same position in the combined public catalog
- single-entry status observation equals the same position in the combined public catalog
- a real non-`RandomConfig` formal node carries no weighted selection
- `full_canonical_ir_build_count=0`
- runtime RNG executed: `false`
- mutation/event/settlement/replay executed: `false`

CI outer measurement: wall `45.00 s`, peak RSS `616,372 KiB`. Validator internal measurement: wall `42.342953 s`, peak RSS `616,372 KiB`.

The Direct `10/14` source split is only the intentionally narrowed representative slice and is not the aggregate producer classification. Aggregate classification is established only by Catalog below.

## Catalog complete aggregate evidence

Command:

```bash
PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c1_random_config_graph_aggregate --catalog
```

Result: exit `0`, `ok=true`.

### Raw / S8A / source-ledger closure

The complete current direct `RandomConfig` denominator was rebuilt from the pinned source rather than copied from prior reports:

- direct raw denominator: `24`
- stable fingerprint: `dba388b88cd4a3bf18be1728dce2bb10e64f7328153277fa551870e5a934ddc2`
- raw denominator == S8A direct `RandomConfig` source set == complete production task-graph source ledger: exact bidirectional equality
- `formal_bound`: `14`
- `no_formal_producer`: `10`
- union of the two classifications equals the denominator; intersection is empty

Each `no_formal_producer` row is checked against the production source disposition rather than inferred merely from graph absence. Current representative rows retain exact source path/JSON path/content SHA-256, source-record identity, accepted ancestor-template/reference evidence, and one deferred owner; the observed deferred owner is `hit_random_sequence`. No such source receives a synthetic graph or formal materialization.

### Formal producer / position multiplicity closure

Catalog dynamically discovered all current relevant action IDs and then retained every concrete definition/level instance. No `min(level)`, first-only selection, or source-key dedupe is used.

Current complete evidence:

- enumerated relevant action definition/level instances: `55`
- expected formal positions: `117`
- actual combined-catalog graph+unique-selection positions: `117`
- exact expected/actual equality: `true`
- formal-position fingerprint: `c66736e795a75b197e55e1768cd8f5f5e92c4a56c58ea237adc1ae610089877e`
- dynamically present producer classes: `action_definition`, `status_callback`
- currently absent producer classes are not synthesized

Every actual formal `RandomConfig` node has exactly one matching weighted selection, and each choice closes one-to-one through ordinal -> graph branch -> exact `OddsList[i]` source occurrence -> numeric expression/definition -> choice identity. Distinct ordinals retain distinct source occurrences and choice identities even when values or expressions could otherwise coincide.

Catalog predicates all passed, including:

```text
raw_s8a_source_ledger_exact_equal=true
expected_actual_formal_positions_exact_equal=true
formal_task_source_and_actual_graph_source_exact_equal=true
all_formal_random_config_nodes_have_exactly_one_selection=true
weighted_choice_ordinal_branch_numeric_source_contract_closed=true
non_random_config_nodes_have_no_weighted_selection=true
combined_public_character_runtime_catalog_used=true
producer_classes_dynamically_sampled=true
single_entry_matches_combined_catalog=true
every_denominator_occurrence_is_exactly_formal_bound_or_no_formal_producer=true
producer_expected_sources_are_formal_bound=true
no_formal_producer_has_no_synthetic_graph=true
no_formal_producer_has_unique_deferred_owner=true
full_canonical_ir_build_count=0
runtime_rng_executed=false
mutation_event_settlement_replay_executed=false
```

CI outer measurement: wall `49.53 s`, peak RSS `798,688 KiB`. Validator internal measurement: wall `46.732288 s`, peak RSS `798,688 KiB`, below the card's `1.25 GiB` validator ceiling.

## CI evidence

Successful code-validation workflow:

- workflow: `P9 S8C1 PR Validation`
- run: `https://github.com/yaelysia/hsr-battle-simulator/actions/runs/33857295167`
- job: `100973440495`
- validated branch head: `3002dae92b9e29e51a660186afe1b851d1dcaa2a`
- PR merge checkout SHA used by GitHub Actions: `0b8ed9909e9a812406a855b1308c7bf6851171ce`
- result: `success`
- run interval: `2026-09-04T09:13:53Z` through `2026-09-04T09:18:19Z`, approximately `4m26s`, below the `<8min` job budget
- GitHub token in the final validation workflow: `contents: read`

Successful steps and outer `/usr/bin/time -v` measurements:

| Check | Exit | Wall | Peak RSS |
| --- | ---: | ---: | ---: |
| scoped compile | 0 | 0.39 s | 17,716 KiB |
| Fast aggregate negatives | 0 | 1.58 s | 88,120 KiB |
| Direct real-source aggregate | 0 | 45.00 s | 616,372 KiB |
| Catalog complete aggregate | 0 | 49.53 s | 798,688 KiB |
| `git diff --check 539b2e1b... HEAD` | 0 | 0.07 s | 6,188 KiB |

The first execution CI attempt (`33856561147`) passed compile/Fast but Direct stopped before production catalog materialization because the new validator used `graph_id` instead of the actual `StandaloneAbilityGraphIR.standalone_ability_graph_id` field while deduplicating the combined narrow view. This was a validator-only defect. It was mechanically corrected within the authorized validator path, and the temporary remediation workflow was immediately restored to the final read-only STRICT workflow before code-validation run `33857295167`. No production mismatch or production modification resulted from the remediation.

## Actual scope / changed files

Execution-created paths are exactly the three paths authorized by the card:

- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_s8c1_random_config_graph_aggregate.py`
- `hsr_v075_baseline_clean/hsr/live_validation_reports/P9-S8C1_RANDOM_CONFIG_GRAPH_AGGREGATE_execution_report.md`
- `.github/workflows/p9-s8c1-pr-validation.yml`

The PR also contains its pre-existing planning artifact at `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9-S8C1_RANDOM_CONFIG_GRAPH_AGGREGATE_AUDIT.md`; execution did not modify that card.

No checklist, governance ledger, P9 index, handoff document, or production source was changed.

## Deferred / explicitly not claimed

This aggregate audit establishes the static graph contract only. It does **not** implement or claim completion of:

- gameplay RNG request/consumption, probability normalization, choice selection, selected-child execution, or RNG replay;
- projectile hit sequence, target iteration, barrier, or parallel merge runtime semantics;
- mutation/event/settlement/audit/replay transaction behavior;
- S5D2 replay/transaction closure;
- broader S8C runtime aggregate or any later P9 business stage.

Those remain outside P9-S8C1 and require later planning/acceptance under their own stage authority.
