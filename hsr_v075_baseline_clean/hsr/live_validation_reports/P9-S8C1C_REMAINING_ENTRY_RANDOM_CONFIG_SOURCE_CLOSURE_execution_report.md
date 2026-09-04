# P9-S8C1C Remaining Entry RandomConfig Source Closure — Execution Report

## Scope and immutable baseline

- Stage: `P9-S8C1C_REMAINING_ENTRY_RANDOM_CONFIG_SOURCE_CLOSURE`
- Fixed base: `f0701b69911d28451f560e3bed354ead355a2865`
- Production/code/validator/CI validation head: `8b62679a5e06169b705c8456d1cf4f693d7ba454`
- PR: `https://github.com/yaelysia/hsr-battle-simulator/pull/3`
- Branch: `exec/p9-s8c1c-random-config-source-closure`
- Execution card: `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9-S8C1C_REMAINING_ENTRY_RANDOM_CONFIG_SOURCE_CLOSURE.md`
- This report intentionally does **not** claim a commit SHA containing itself. The final PR head is supplied separately in the ready-for-review handoff.

## Actual PR diff at the code-validation head

Against the fixed base, `git compare f0701b69911d28451f560e3bed354ead355a2865..8b62679a5e06169b705c8456d1cf4f693d7ba454` contained:

- `.github/workflows/p9-s8c1c-pr-validation.yml` — added; S8C1C PR-scoped validation workflow.
- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9-S8C1C_REMAINING_ENTRY_RANDOM_CONFIG_SOURCE_CLOSURE.md` — pre-existing planning artifact for this PR; execution did not modify it.
- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/task_graph.py` — modified; `TaskGraphIR` now requires the weighted-selection node set to equal the formal `RandomConfig` node set, independent of `EntryKind`.
- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py` — modified; existing `_materialize_weighted_selection(...)` is attached for every formal `RandomConfig` control node instead of only `ability_phase_callback`.
- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_s8c1c_remaining_entry_random_config_source_closure.py` — added; `--fast`, `--direct`, and `--catalog` validation.

This report is the only additional execution artifact committed after that validation head.

## Production result

The shared weighted-selection authority remains the existing `_materialize_weighted_selection(...)`. No alternate status/template weighted model was introduced.

`TaskGraphIR` now fails closed unless:

- every formal node with `source_family == "RandomConfig"` has exactly one `TaskGraphWeightedSelectionIR`;
- no non-`RandomConfig` node has a weighted selection;
- each selection remains closed to the parent graph node/source occurrence/source bytes and to the existing branch/Odds/numeric-definition identities.

The materializer no longer uses `entry_kind == "ability_phase_callback"` as an attachment prerequisite. The accepted S8C1B action path therefore continues through the same producer and selection model, while `status_callback` formal entries are admitted through the same path.

No runtime RNG, probability normalization, random choice execution, replay behavior, or new `EntryKind` was added.

## Fast and focused validation evidence

Final code-validation CI run: `https://github.com/yaelysia/hsr-battle-simulator/actions/runs/33838064409`

All commands below exited `0` on the final code-validation run. `/usr/bin/time -v` values are the outer process measurements recorded by CI.

| Check | Command | Exit | Wall | Peak RSS |
| --- | --- | ---: | ---: | ---: |
| scoped compile | `PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/task_graph.py hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_s8c1c_remaining_entry_random_config_source_closure.py` | 0 | 0.13 s | 18,648 KiB |
| S8C1A focused | `PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c1a_weighted_selection_ir` | 0 | 0.65 s | 38,552 KiB |
| S8C1B Fast regression | `PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c1b_action_entry_weighted_selection --fast` | 0 | 1.45 s | 88,052 KiB |
| S8C1C Fast + negative cases | `PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c1c_remaining_entry_random_config_source_closure --fast` | 0 | 0.74 s | 88,136 KiB |
| base-to-HEAD whitespace check | `git diff --check f0701b69911d28451f560e3bed354ead355a2865 HEAD` | 0 | 0.00 s | 6,612 KiB |

The S8C1C Fast JSON reported 7 focused cases and `ok=true`. It covered the new fail-closed requirements: status RandomConfig without a selection, OddsList/branch denominator mismatch, forged parent-source identity, reachable source mislabeled `no_formal_producer`, and a no-producer source given a synthetic materialization. It also confirmed the ability fixture remains weighted and runtime behavior was not changed. The S8C1A focused check additionally retained its forged-source-identity fail-closed evidence.

## Direct real-source evidence

Command:

```bash
PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c1c_remaining_entry_random_config_source_closure --direct
```

Result: exit `0`, `ok=true`; validator internal wall `40.538846 s`, outer CI wall `42.38 s`, peak RSS `630,888 KiB`.

Direct dynamically rebuilt the current signed `RandomConfig` denominator and obtained:

- denominator count: `24`
- denominator fingerprint: `dba388b88cd4a3bf18be1728dce2bb10e64f7328153277fa551870e5a934ddc2`
- representative Direct materialization positions observed: `10`
- remaining denominator positions not sampled as formal Direct positions: `14`
- `full_canonical_ir_build_count=0`

Producer classes were discovered from the current source/producer topology rather than hard-coded business identities:

- ability action: `formal_bound`
- status callback: `formal_bound`
- reachable template: `formal_bound`
- queue/standalone: `zero_by_denominator`

Representative action evidence dynamically selected a real `ability_phase_callback` under `Config/ConfigAbility/Avatar/Advanced/Avatar_Advanced_Silwolf_00_Ability.json`, at `$.AbilityList[8].OnStart[0].FailedTaskList[0].FailedTaskList[0].FailedTaskList[0]`, with three source-backed choices. The validator reconstructed each `OddsList[i]` child occurrence and numeric definition from the signed source bytes and matched branch ordinal, branch id, choice id, selection id, and parent source occurrence. The same action graph also passed the single-entry-vs-catalog S8C1B regression check.

Representative status evidence dynamically selected a real `status_callback` in `Config/ConfigAbility/Avatar/Avatar_Anaxa_00_Ability.json`, event `OnEnterBattle`, whose formal RandomConfig source is `$.GlobalTemplates[0].TaskList[8]` with seven choices. `materialize_status_callback_task_graph(...)` and the same callback inside `materialize_character_runtime_task_graph_catalog(...)` produced structurally identical graph/selection output.

The same status slice supplied a real document-global template case. The accepted template source identity (`document_global`, `$.GlobalTemplates[0].TaskList[8]`) remained distinct from its formal status task/node position while preserving the same signed source occurrence and production source-record linkage.

A real non-RandomConfig status node (`RemoveModifier`) was also observed with no weighted selection.

Direct did not instantiate `BattleState`, sample RNG, normalize odds, or choose a branch.

## Catalog STRICT denominator evidence

Command:

```bash
PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c1c_remaining_entry_random_config_source_closure --catalog
```

Result: exit `0`, `ok=true`; validator internal wall `49.795859 s`, outer CI wall `51.65 s`, peak RSS `721,056 KiB`.

The Catalog mode independently rebuilt the RandomConfig-only raw denominator from the complete character `CharacterAbilityRawSnapshot` plus accepted S8A shared-template sources, before any full canonical build. It then compared exact `(source_path, json_path, family, content_sha256)` occurrence identities bidirectionally with the accepted S8A control-flow catalog and the production TaskGraph source ledger.

Final complete denominator evidence:

- denominator count: `24`
- denominator fingerprint: `dba388b88cd4a3bf18be1728dce2bb10e64f7328153277fa551870e5a934ddc2`
- `formal_bound`: `14`
- `no_formal_producer`: `10`
- formal-bound template-source occurrences: `3`
- `full_canonical_ir_build_count=0`

Classification rule used for evidence, not as a whitelist: an occurrence is `formal_bound` only when the current production formal producer topology yields one or more real ability/status formal graph positions that reverse-link through a production source record and each position has exactly one weighted selection. The complement is `no_formal_producer` only after the production source record has no `formal_materialization_ids`, accepted ability/status reachability is empty, no synthetic entry/graph position exists, and the retained downstream owner/template-reference closure remains explicit.

For every formal-bound occurrence, Catalog checked every discovered formal graph position and selection, including source-record -> materialization -> graph node -> unique selection and the reverse direction. Every branch preserved the original `TaskList[i]`/`OddsList[i]` ordinal and a distinct Odds child source occurrence/numeric definition even when numeric values could repeat.

For `no_formal_producer`, representative sources were dynamically found in the accepted shared-global `Config/ConfigGlobalTaskListTemplate/GlobalTaskListTemplate_GridFight.json`. The sampled records had `accepted_reference_count=0`, empty formal materialization linkage, `template_scope=shared_global`, and retained downstream `owner_domains=["hit_random_sequence"]`. They were not labeled executable and no synthetic template entry or graph was created.

All acceptance predicates emitted by Catalog were true, including:

- current entry denominator remains ability/status only;
- every formal RandomConfig node has exactly one weighted selection;
- non-RandomConfig nodes have none;
- ability and status share the one weighted materialization authority;
- status single-entry and combined catalog agree;
- S8C1B action behavior is preserved;
- raw denominator is independently reproducible and S8A/source-ledger identities are bidirectionally closed;
- every denominator occurrence is exactly `formal_bound` or `no_formal_producer`;
- formal-bound sources close to every formal graph position/selection;
- no-producer sources have no synthetic entry/graph;
- template source identity is not collapsed into formal instance identity;
- branch/Odds/source/numeric identities are one-to-one;
- `full_canonical_ir_build_count=0`;
- `runtime_rng_behavior_changed=false`;
- `s8c_or_s5d2_claimed_complete=false`.

## CI evidence and remediation history

Successful code-validation run:

- workflow: `P9 S8C1C PR Validation`
- run: `https://github.com/yaelysia/hsr-battle-simulator/actions/runs/33838064409`
- job: `100914537539`
- branch head under validation: `8b62679a5e06169b705c8456d1cf4f693d7ba454`
- PR merge checkout SHA: `a33161fefd640808225691a580bc5e103ac404d3`
- result: `success`
- run wall from `2026-09-04T04:46:48Z` to `2026-09-04T04:51:33Z`: approximately `4m45s`, below the `<8min` job budget.
- largest Python validator RSS: Catalog `721,056 KiB`, below `1.25 GiB`.

The legacy S8C1B PR workflow also completed successfully on the same branch head (`run 33838064421`), including its own Direct regression.

An earlier S8C1C CI attempt (`run 33837627142`) passed compile, S8C1A, S8C1B Fast, and S8C1C Fast, then exposed an ordinary validator-only tuple-unpacking mismatch in `_lower_standalone_ability_graphs(...)`. That interface-adaptation error was fixed within the authorized validator path in commit `8b62679a5e06169b705c8456d1cf4f693d7ba454`; no production scope or source authority changed. The succeeding run above is the evidence used for this report.

## Deferred / explicitly not claimed

Still deferred by this card:

- runtime RNG evaluation / branch sampling / probability execution;
- parallel, projectile, and barrier execution semantics;
- P9-S8C1 aggregate and broader S8C runtime closure;
- P9-S5D2 or any target-random/bounce aggregate work;
- settlement, audit, and replay semantics.

This report does not mark the project checklist, does not perform final independent acceptance, does not merge the PR, and does not advance a later P9 stage.
