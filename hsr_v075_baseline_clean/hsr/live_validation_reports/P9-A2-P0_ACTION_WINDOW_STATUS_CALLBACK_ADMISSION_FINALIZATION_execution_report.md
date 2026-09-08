# P9-A2-P0 Action-window Status Callback Admission Finalization — Execution Report

## 1. Scope, authority, and heads

- Fixed base: `master@bd1a4ac94ca394d2ea563d086eaf56e9ed45b285`.
- Pinned TBGD source: `14c1d18f91a8101d610e6c523447a7517de3fae1`.
- Production implementation commit remains `a73576c6d5d751f6c5d14713e5ed49883fc82b2f` (`Implement A2-P0 status callback admission finalizer`).
- Read-only validation workflow restore commit remains `6780464df87e7f98ec1b31793b2f808bd313f7f2`.
- REVIEW returned the first execution report for STRICT evidence remediation in PR comment `5578826676`.
- Final validator-only remediation head: `fd300413dd4c0e330c711b6542c74d81bda1b91b`; committed-head run `34188668989` succeeded.
- First report-containing head: `29a66b81d07f6fb91007602b60fd48f09d30fd60`; committed-head run `34189199612` also succeeded.
- This accuracy correction creates one later governance-only head. Its exact SHA and committed-head CI are recorded in the subsequent PR WAIT/HANDOFF comment because a Git commit cannot contain its own SHA before it exists.

No production file changed after `a73576c6d5d751f6c5d14713e5ed49883fc82b2f`. All remediation after REVIEW comment `5578826676` was confined to the card-authorized validator and execution report.

## 2. Exact production diff

The only production file changed by this card is:

`hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py`

Production changes are limited to:

1. In `TBGDLowering.build()`, after existing status callback/task lowering, initial `StatusEventFamilyIR` projection, and typed `TriggerAbility` linking, call `_finalize_action_window_status_callback_admission(...)` using existing callbacks, tasks, event families, effects, standalone graphs/phases, and formal source paths.
2. Store the returned audit and recompute the existing status event family projection before the pre-existing blocker propagation / queue / invocation-role / task-graph materialization sequence continues.
3. The finalizer only re-adjudicates the exact stale `status_callback_event_not_admitted:<event>` blocker when source mode, real action-window producer, typed target, formal graph identity, callback root ledger, formal-branch closure, and all independent blockers prove the row is admissible.
4. Stable callback/task/source/link/topology identity is preserved. No event registry, callback allowlist, character/ability/file special case, public IR schema, TaskGraphIR/continuation change, runtime routing authority, RandomConfig caller, weighted-selection implementation, or RNG ledger was added.

## 3. Production order and existing authorities

Observed production order used by the validator is:

```text
raw character ability source
  -> per-file status callback/task lowering
  -> existing source/effect/task semantics
  -> existing status event family/runtime producer projection
  -> existing typed TriggerAbility link pass
  -> A2-P0 final admission projection
  -> recomputed status event family / callback blocker propagation
  -> existing queue intent blocking
  -> existing queue resolution authority
  -> existing invocation-role authority
  -> existing task-graph materialization/catalog
  -> CanonicalIR / RuleBook
```

Existing authorities are consumed, not replaced:

- event/runtime producer: existing `StatusEventFamilyIR.runtime_event_sources`;
- callback/task identity: current mainline character ability lowering and source graph;
- typed target: existing `linked_ability_phase_id` / `linked_standalone_graph_id`;
- queue roots: existing `_lower_queue_resolutions(...)`;
- invocation role: existing `_assign_character_ability_invocation_roles(...)`;
- formal task graphs: existing task-graph materializer helpers and catalog invariants;
- A1 admission: existing `systems/action_contract.py`, `rules/task_graph.py`, `tbgd/task_graph_materializer.py`, and `validate_p9_formal_action_graph_admission_authority.py`.

## 4. REVIEW remediation summary

REVIEW comment `5578826676` identified three ordinary STRICT-evidence defects. The final validator closes them as follows.

### 4.1 Independent source denominator and bidirectional reconciliation

Before invoking the production finalizer, Direct independently builds the candidate set from pinned TBGD + current character source graph + raw lowered callback/task/effect facts + current event-family producer facts + typed TriggerAbility target facts.

The independent candidate key is `(source_path, callback_id, task_id, event)`. For every candidate, Direct records and reconciles source path/mode, callback/task IDs, event, pre-finalizer coverage/blockers, unique real `action.window.*` source, typed linked target, and independently resolved formal graph identity.

Production finalizer audit rows with action-window producer facts must have exactly the same key set. Missing/extra rows, duplicate identities, or any field mismatch fail Direct. Runs `34188668989` and `34189199612` both reported `bidirectional_reconciliation = exact`.

Dynamic current-source result in both runs:

- `snapshot_source_count = 80`
- `formal_source_path_count = 80`
- `selected_formal_ability_file_count = 80`
- `status_callback_count = 2470`
- `status_callback_task_count = 9392`
- `standalone_graph_count = 1084`
- independent action-window TriggerAbility denominator count = `1`
- promoted count = `1`

No role, character, callback ID, task ID, file name, or count is hard-coded as a pass condition.

### 4.2 Production-equivalent queue / invocation-role context

The focused Direct no longer supplies an empty queue context. It first applies existing callback-derived queue blocking, then uses existing queue resolver and invocation-role authority.

Both successful committed-head runs show:

- total source-backed queue intents in focused source build: `213`;
- production-relevant `TurnInsertAbility` denominator: `178`;
- queue resolutions: `178`;
- coverage: `150 executable`, `28 blocked`;
- executable queue-root standalone graphs: `43`;
- full queue-aware standalone phase role histogram:
  - `nested_only = 35`
  - `standalone_root = 43`
  - `unbound_definition = 983`
  - `non_gameplay_noop = 23`

Every blocked queue resolution has an explicit reason. Existing blocked/deferred/unsupported queue facts are not erased.

The dynamically promoted status target is not an executable queue-root graph. Its focused typed-target closure contains exactly one phase, which remains `nested_only` under the real queue-aware invocation-role projection.

The final focused RuleBook uses existing production task-graph helpers to build a source-closed formal slice consisting of the dynamic action-window candidate callback plus its queue-aware typed-target ability closure. This keeps CanonicalIR formal ability/status graph denominators internally complete.

Focused formal slice evidence:

- formal target graph count: `1`;
- formal target phase count: `1`;
- ability formal slice count: `1`;
- status formal slice count: `1`;
- installed task-graph materializations: `2`;
- focused queue-aware role histogram: `nested_only = 1`.

### 4.3 A1 admission regression

Fast and Direct reuse the existing A1 validator rather than inventing a parallel authority.

The following A1 authority paths are byte-for-byte equal to fixed base `bd1a4ac94ca394d2ea563d086eaf56e9ed45b285`:

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/action_contract.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/task_graph.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_formal_action_graph_admission_authority.py
```

Stable A1 acceptance evidence across both committed-head runs:

- A1 Fast behavior digest: `7b47540c2cd8bea0dd218ae9898552f2f5d3bcae31ce76cd27a3f249144b8dc7`;
- signed TBGD source fingerprint: `349d9dd2ade62d32e17b25a49400c8043dfdf0cea73250aa0ee4bc23fcedb998`;
- every A1 Direct predicate passed, including real signed source, graph-root/nested-link discovery, reachable blocker preservation, public target query/accept, action-contract evaluation after target acceptance, no forged authorization/fingerprint, target context revalidation, and zero full CanonicalIR builds in the A1 Direct helper.

The existing A1 Direct validator intentionally has `_DIRECT_DISCOVERY_GUARD_SECONDS = 165.0` and stops scanning additional action definitions once that discovery budget is exceeded. Therefore `scanned_action_definitions` and the A1 Direct diagnostic digest are run-specific diagnostics, not stable pass gates:

- run `34188668989`: scanned `31`, diagnostic digest `44c94fe263d7e75761e4d0747318dfa1418d0b8daa481c7daddc5cfce350cf28`;
- run `34189199612`: scanned `40`, diagnostic digest `22e7b7896661d3c226b940f7f51e8aac5a720e529040483e680c3f26783df2af`.

This variation occurred with identical source fingerprint, exact-equal A1 authority files, and the same complete predicate set passing. The report does not treat the scan count or Direct diagnostic digest as a fixed regression baseline.

## 5. Complete same-action-window-event transition ledger

Direct independently snapshots every formal `mainline_avatar_ability` callback whose event has a unique real action-window runtime source, plus all owned callback tasks, before finalization and after normal post-finalizer blocker propagation.

Both successful runs report:

- action-window callbacks: `238`;
- owned callback tasks: `1008`.

Callback status histogram is unchanged:

```text
before: blocked=112, executable=126
after:  blocked=112, executable=126
```

There are no callback aggregate field changes.

Task status histogram changes by exactly one row:

```text
before: blocked=458, executable=550
after:  blocked=457, executable=551
```

The stale `OnAfterAttack` reason changes from `111` rows to `110`; empty reason changes from `550` to `551`. All other independent condition/effect/queue/source/target blocker counts remain unchanged.

The only task transition is the same dynamically reconciled TriggerAbility candidate selected by the production finalizer:

- before: `blocked`, `status_callback_event_not_admitted:OnAfterAttack`;
- after: `executable`, no blocker;
- `promoted_by_finalizer = true`.

Any blocked task becoming executable without a production finalizer `promoted` audit row fails Direct. Any promoted row whose old reason is not the exact stale event blocker fails Direct.

## 6. Production audit and promoted row evidence

The production finalizer audit currently contains eight TriggerAbility rows:

```text
action_window_producer_missing: 7
promoted: 1
```

Before-task reason histogram:

```text
status_callback_event_not_admitted:OnAfterAttack: 1
status_callback_event_not_admitted:OnAfterBeingHit: 1
status_callback_event_not_admitted:OnDefenderPrepareAttackData: 1
status_callback_event_not_admitted:OnEnterBattle: 2
status_callback_event_not_admitted:OnListenBreak: 1
status_callback_task_opcode_not_admitted:TriggerAbility: 2
```

After-task status histogram:

```text
blocked: 7
executable: 1
```

The dynamic positive representative in the current source snapshot is the Silver Wolf `OnAfterAttack -> TriggerAbility` formal branch. This identity is report evidence only, never an allowlist.

For that dynamic row both successful runs prove:

- pre-finalizer blocker is exactly `status_callback_event_not_admitted:OnAfterAttack`;
- event producer is uniquely `action.window.after_attack`;
- callback/task are executable after finalization;
- typed target is unique and resolves to the existing standalone formal graph;
- target is `nested_only` under real queue context and is not a queue root;
- formal status root materializes as `task_graph:1547145a4dc70ef3ce732420f661012705efcaa561441dce019adb58a9e1b20d`;
- stable callback/task/source/link identity does not change.

The other seven audited TriggerAbility rows remain blocked.

## 7. Fast validation

Command:

```bash
python hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p0_action_window_status_callback_admission_finalization.py --fast
```

Successful committed-head results:

- run `34188668989`: `FAST PASS`, about `2.66 s`, peak RSS `135144 KiB`;
- report-head run `34189199612`: `FAST PASS`, about `2.48 s`, peak RSS `134976 KiB`.

Fast emits all required negative reason classes and verifies positive exact-stale promotion, independent blocker preservation, typed target failures, synthetic/wrong source failures, producer failures, blocked sibling closure, formal-branch closure, stable identity, S8B5B link-pass-only non-promotion, A1 behavior regression, and governance guards.

## 8. Real L0 Direct validation

Command:

```bash
python hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p0_action_window_status_callback_admission_finalization.py --direct
```

Both committed-head runs returned `DIRECT PASS`.

Stable Direct evidence:

- builder: `focused_formal_character_source_denominator`;
- independent denominator builder: `pre_finalizer_source_backed_ir`;
- bidirectional reconciliation: `exact`;
- denominator count: `1`;
- promoted count: `1`;
- same-action-window transition ledger: `238 callbacks / 1008 tasks`;
- queue-aware role resolution: `178` real `TurnInsertAbility` resolutions;
- focused formal closure: `1` target graph, `1` target phase, `1` ability slice, `1` status slice;
- installed materializations: `2`.

Resource observations:

- run `34188668989`: focused build `21.664 s`, total Direct about `3:12.03`, peak RSS `733968 KiB`;
- report-head run `34189199612`: focused build `19.249 s`, total Direct about `3:08.90`, peak RSS `733944 KiB`.

The higher total Direct time includes the separate existing A1 real-source behavior regression. No validation criterion was removed to reduce runtime.

## 9. CI, fixed-base check, and token permissions

Validator head:

- head `fd300413dd4c0e330c711b6542c74d81bda1b91b`;
- run `34188668989`, job `101942040773`;
- Compile/Fast/Direct/fixed-base all successful.

First report-containing head:

- head `29a66b81d07f6fb91007602b60fd48f09d30fd60`;
- run `34189199612`, job `101943586164`;
- Compile/Fast/Direct/fixed-base all successful.

Fixed-base command:

```bash
git diff --check bd1a4ac94ca394d2ea563d086eaf56e9ed45b285 HEAD
```

Result: PASS on both runs.

Both jobs show normal read-only `GITHUB_TOKEN` permissions:

```text
Contents: read
Metadata: read
Packages: read
```

No write permission is retained or requested by the final workflow.

## 10. Remediation CI audit trail

After REVIEW comment `5578826676`, intermediate validator-only heads intentionally failed while strengthening STRICT evidence. These failures did not change production behavior and were repaired under EXEC:

- run `34185605704`: focused Direct widened ability/materializer context incorrectly;
- run `34186604858`: transition ledger incorrectly required formal descendants to share callback root source path;
- run `34187325178`: unrelated nested-only ability entries were still included in focused formal materializer denominator;
- run `34187867529`: status-only formal slice was attached to CanonicalIR still claiming all formal ability entries;
- validator head `fd300413dd4c0e330c711b6542c74d81bda1b91b`, run `34188668989`: all gates passed;
- report head `29a66b81d07f6fb91007602b60fd48f09d30fd60`, run `34189199612`: all gates passed again.

These are validation-harness/report corrections only. They required no production scope expansion, dependency, permission, or public-contract change.

## 11. Scope proof

Current PR changed-file scope is limited to the card-authorized five files:

```text
.github/workflows/p9-a2-p0-pr-validation.yml
hsr_v075_baseline_clean/hsr/live_validation_reports/P9-A2-P0_ACTION_WINDOW_STATUS_CALLBACK_ADMISSION_FINALIZATION_execution_report.md
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9-A2-P0_ACTION_WINDOW_STATUS_CALLBACK_ADMISSION_FINALIZATION.md
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p0_action_window_status_callback_admission_finalization.py
```

No `core/**`, `systems/**`, `rules/**`, `tbgd/task_graph_materializer.py`, `TaskGraphContinuation`, PR #11 runtime file, or PR #9 RandomConfig/weighted-selection/RNG implementation changed. A1 authority files are exact-equal to fixed base.

## 12. Remaining work / handoff boundary

A2-P0 closes only the merged-master L0 source-backed action-window status callback/task admission-finalization prerequisite.

After REVIEW independently accepts and merges PR #12:

1. preserve PR #11's existing implementation;
2. update PR #11 onto the newly merged master;
3. rerun PR #11's original Fast unchanged;
4. rerun PR #11's unchanged real `CombatExecutor.execute(ActionCommand)` Direct;
5. do not substitute this A2-P0 L0 Direct for PR #11 runtime Direct;
6. keep PR #9 RandomConfig/RNG deferred until the PR #11 chain is independently accepted/merged.
