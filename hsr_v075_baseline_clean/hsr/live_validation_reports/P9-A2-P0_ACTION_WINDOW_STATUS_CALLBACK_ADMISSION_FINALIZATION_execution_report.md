# P9-A2-P0 Action-window Status Callback Admission Finalization — Execution Report

## 1. Scope and heads

- Base: `master@bd1a4ac94ca394d2ea563d086eaf56e9ed45b285`.
- Production implementation commit: `a73576c6d5d751f6c5d14713e5ed49883fc82b2f` (`Implement A2-P0 status callback admission finalizer`).
- Validated committed code/workflow head before this report: `6780464df87e7f98ec1b31793b2f808bd313f7f2` (`Restore PR12 read-only final validation workflow`).
- Final PR governance head: the commit containing this report. Its exact 40-character SHA is recorded in the PR EXEC handoff / CI-wait comment because a Git commit cannot literally contain its own SHA before that commit exists.
- PR remains independent of unmerged PR #11 implementation and of PR #9 RandomConfig/RNG work.

## 2. Exact production diff

The only production file changed by this card is:

`hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py`

Production changes are limited to:

1. In `TBGDLowering.build()`, after the existing initial `_lower_status_event_families(status_callbacks, status_callback_tasks)` projection and after typed `TriggerAbility` links/facts are available, call `_finalize_action_window_status_callback_admission(...)` with the existing callbacks, tasks, event families, effects, standalone graphs, phases, and `formal_status_root_paths`.
2. Store the returned audit as `_action_window_status_callback_finalization_audit` and recompute the existing `StatusEventFamilyIR` projection from the finalized callback/task state before the existing status-event blocker projection continues.
3. Add `_finalize_action_window_status_callback_admission(...)` as the single post-link L0 admission finalizer. It consumes existing source/typed facts only and changes only `coverage_status` / blocker fields and callback aggregate admission fields for rows that satisfy the exact stale-event criteria.
4. The finalizer verifies unique callback/task/effect/graph/phase identities, exact source mode and formal source path, a unique executable `action.window.*` producer, the exact stale `status_callback_event_not_admitted:<event>` blocker, executable `TriggerAbility` effect semantics, exactly one typed linked phase-or-standalone target, formal target consistency, callback root-ledger membership, formal-branch provenance for non-root owned tasks, and fail-closed sibling closure.

No second event registry, callback allowlist, role/ability/file-name special case, synthetic producer, public IR schema, TaskGraphIR contract, continuation contract, or runtime routing authority was added.

Validation-only file:

`hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p0_action_window_status_callback_admission_finalization.py`

Governance-only files in the PR are this execution card/report and `.github/workflows/p9-a2-p0-pr-validation.yml`.

## 3. Real build call position and authorities

Observed production order on the merged-master lineage used by PR #12:

```text
raw character ability source
  -> per-file status callback/task lowering
  -> existing callback/task source + effect/task semantics
  -> existing status event family/runtime producer projection
  -> existing typed TriggerAbility link facts
  -> _finalize_action_window_status_callback_admission   # A2-P0
  -> recomputed existing StatusEventFamilyIR projection
  -> existing formal status task-graph materialization/catalog
  -> CanonicalIR
  -> RuleBook
```

Authorities consumed, not replaced:

- event/runtime producer authority: existing `StatusEventFamilyIR.runtime_event_sources`;
- source identity: existing mainline character ability lowering and formal source paths;
- nested target identity: existing `linked_ability_phase_id` / `linked_standalone_graph_id`;
- formal graph/root resolution: existing standalone graph/phase catalog and task-graph materializer;
- callback aggregate fields: existing `StatusCallbackIR` semantics.

The finalizer does not execute callbacks and does not implement PR #11 action-window runtime transport.

## 4. Independent source denominator

Committed-head Direct run rebuilt the focused formal character-source denominator from the pinned TBGD submodule (`14c1d18f91a8101d610e6c523447a7517de3fae1`) and production lowering. The validator does not hard-code a character, callback ID, task ID, source file, or denominator count as a pass gate.

Focused build evidence:

- `snapshot_source_count = 80`
- `formal_source_path_count = 80`
- `selected_formal_ability_file_count = 80`
- `status_callback_count = 2470`
- `status_callback_task_count = 9392`
- `standalone_graph_count = 1084`
- `task_graph_materialization_count = 2396`

The dynamic action-window producer-backed `mainline_avatar_ability` `TriggerAbility` denominator contained `1` real candidate in this source snapshot.

## 5. Before/after audit histograms

The production audit covered eight `TriggerAbility` audit rows. Decision histogram:

```text
action_window_producer_missing: 7
promoted: 1
```

Before-task blocker histogram:

```text
status_callback_event_not_admitted:OnAfterAttack: 1
status_callback_event_not_admitted:OnAfterBeingHit: 1
status_callback_event_not_admitted:OnDefenderPrepareAttackData: 1
status_callback_event_not_admitted:OnEnterBattle: 2
status_callback_event_not_admitted:OnListenBreak: 1
status_callback_task_opcode_not_admitted:TriggerAbility: 2
```

After-task coverage histogram:

```text
blocked: 7
executable: 1
```

Callback aggregate transition summary:

- no audited callback identity/source/event/root ledger changed;
- the one promoted task belonged to a callback whose aggregate callback coverage/admission was already executable with no callback blocker, so that callback remained executable before/after;
- the seven non-promoted rows caused no callback aggregate transition;
- therefore callback aggregate admission was not used as a blanket promotion path, and all callback-level transitions in this audit were unchanged.

## 6. Promoted row ledger

The dynamically selected real positive row in the current source snapshot was:

- source: `Config/ConfigAbility/Avatar/Advanced/Avatar_Advanced_Silwolf_00_Ability.json`
- callback: `status_callback:Config/ConfigAbility/Avatar/Advanced/Avatar_Advanced_Silwolf_00_Ability.json:MAvatar_Advanced_Silwolf_00_Passive:2:OnAfterAttack`
- task: `status_callback_task:status_callback:Config/ConfigAbility/Avatar/Advanced/Avatar_Advanced_Silwolf_00_Ability.json:MAvatar_Advanced_Silwolf_00_Passive:2:OnAfterAttack:$.AbilityList[7].Modifiers.MAvatar_Advanced_Silwolf_00_Passive._CallbackList[1].CallbackConfig[1].formal_branch[0].child[0]:TriggerAbility`
- event: `OnAfterAttack`
- old reason: `status_callback_event_not_admitted:OnAfterAttack`
- new task status: `executable`
- action-window producer: `action.window.after_attack`
- typed target: `standalone_ability_graph:Config_ConfigAbility_Avatar_Advanced_Avatar_Advanced_Silwolf_00_Ability_json:Avatar_Advanced_Silwolf_00_PassiveSkill_RandomBug`
- formal graph: same standalone graph identity above
- resolved formal status root graph: `task_graph:1547145a4dc70ef3ce732420f661012705efcaa561441dce019adb58a9e1b20d`
- target phases were verified by Direct to have the existing `nested_only` invocation role.

This row is report evidence only; its role/character/file identity is not a production or validator allowlist.

## 7. Non-promoted rows

Seven audited `TriggerAbility` rows remained blocked because no unique real `action.window.*` producer existed for their event family in the current runtime-source mapping. The finalizer did not remove their original independent blockers or promote them through callback aggregation.

Fast negative coverage additionally exercised and reported the following fail-closed reasons:

```text
action_window_producer_ambiguous
action_window_producer_missing
callback_closure_blocked
event_family_blocked
source_mode_not_admitted
task_not_exact_stale_blocker
typed_target_ambiguous
typed_target_graph_missing
typed_target_missing
```

## 8. Fast validation

Command:

```bash
python hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p0_action_window_status_callback_admission_finalization.py --fast
```

Committed-head CI result: `FAST PASS`.

Current final-code CI resource evidence:

- elapsed wall clock: about `1.68 s` in run `34180077591`;
- peak RSS: `118596 KiB`;
- all required negative reason classes above were emitted.

Fast also retains governance guards against runtime / task-graph / RandomConfig-RNG scope expansion and checks stable identity plus the S8B5B rule that the typed-link pass alone does not promote a blocked parent.

## 9. Real L0 Direct validation

Command:

```bash
python hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p0_action_window_status_callback_admission_finalization.py --direct
```

Committed-head CI result: `DIRECT PASS`.

Evidence from run `34180077591`:

- builder: `focused_formal_character_source_denominator`;
- denominator count: `1`;
- promoted count: `1`;
- internal source-build wall time: `23.942 s`;
- measured command elapsed: about `25.63 s`;
- peak RSS: `636092 KiB`;
- formal source coverage: `80 / 80` selected formal source files;
- final CanonicalIR/RuleBook contains executable callback/task state, unique typed nested target, existing nested-only invocation role, and a materialized formal status root.

## 10. CI and fixed-base check

Committed-head validation run:

- run id: `34180077591`
- URL: `https://github.com/yaelysia/hsr-battle-simulator/actions/runs/34180077591`
- conclusion: `success`
- successful steps: checkout pinned TBGD, source pin, compile, Fast, Direct, fixed-base diff check.

The run log shows the restored final workflow token permissions as:

```text
Contents: read
Metadata: read
Packages: read
```

Thus the one-off Actions write permission used during implementation is no longer present in the final validation workflow.

Fixed-base command:

```bash
git diff --check bd1a4ac94ca394d2ea563d086eaf56e9ed45b285 HEAD
```

Result: PASS.

## 11. Write-permission cleanup history

- The first one-off writeback attempt validated Fast/Direct but GitHub rejected a push that also modified the workflow because the Actions token lacked the separate `workflows` permission. That runner-local commit never reached the branch.
- A production-only retry (`34179929026`) again passed Fast/Direct and pushed only `lowering.py` plus the validator as `a73576c6d5d751f6c5d14713e5ed49883fc82b2f`.
- Commit `6780464df87e7f98ec1b31793b2f808bd313f7f2` then restored `.github/workflows/p9-a2-p0-pr-validation.yml` to the normal read-only PR validator.
- The subsequent committed-head run `34180077591` passed with read-only token permissions.

No new write permission is retained or requested by this report/finalization step.

## 12. Scope proof

PR changed-file scope before adding this report was exactly:

```text
.github/workflows/p9-a2-p0-pr-validation.yml
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9-A2-P0_ACTION_WINDOW_STATUS_CALLBACK_ADMISSION_FINALIZATION.md
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p0_action_window_status_callback_admission_finalization.py
```

This report adds only the card-authorized report path. No `core/**`, `systems/**`, `rules/**`, `task_graph_materializer.py`, `systems/task_graph.py`, `TaskGraphContinuation`, PR #11 runtime file, RandomConfig weighted-selection caller, or RNG ledger implementation was modified.

## 13. Remaining work / handoff boundary

A2-P0 closes only the merged-master L0 source-backed action-window status callback/task admission finalization prerequisite.

After REVIEW independently accepts and merges PR #12, PR #11 must preserve its existing implementation, update onto the newly merged master, and rerun its original Fast plus the unchanged real `CombatExecutor.execute(ActionCommand)` Direct. This report and A2-P0 L0 Direct are not substitutes for PR #11 runtime Direct. PR #9 RandomConfig/RNG remains deferred until the PR #11 chain is accepted/merged.
