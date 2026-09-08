# P9-A2-P0 Action-window Status Callback Admission Finalization — Execution Report

## 1. Scope, authority, and heads

- Fixed base: `master@bd1a4ac94ca394d2ea563d086eaf56e9ed45b285`.
- Pinned TBGD source: `14c1d18f91a8101d610e6c523447a7517de3fae1`.
- Production implementation commit remains `a73576c6d5d751f6c5d14713e5ed49883fc82b2f` (`Implement A2-P0 status callback admission finalizer`).
- Read-only validation workflow restore commit remains `6780464df87e7f98ec1b31793b2f808bd313f7f2`.
- REVIEW returned the first execution report for STRICT evidence remediation in PR comment `5578826676`.
- The final validator-only remediation head before this report is `fd300413dd4c0e330c711b6542c74d81bda1b91b`.
- Its committed-head validation run is `34188668989`, conclusion `success`.
- This report update creates a later governance-only head. The exact final report-containing head and its own committed-head CI are recorded in the subsequent PR WAIT/HANDOFF comment because a Git commit cannot contain its own SHA before it exists.

No production file changed after `a73576c6d5d751f6c5d14713e5ed49883fc82b2f`. All remediation after REVIEW comment `5578826676` was confined to the card-authorized validator and this execution report.

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

The independent candidate key is `(source_path, callback_id, task_id, event)`. For every candidate, Direct records and reconciles:

- source path / source mode;
- callback and task IDs;
- event;
- pre-finalizer callback coverage/blocker;
- pre-finalizer task coverage/blocker;
- unique real `action.window.*` runtime source;
- typed linked phase/standalone target;
- independently resolved formal graph identity.

Production finalizer audit rows with action-window producer facts must have exactly the same key set. Missing or extra rows, duplicate identities, or any field mismatch fail Direct. The final run reported `bidirectional_reconciliation = exact`.

Dynamic current-source result in run `34188668989`:

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

The focused Direct no longer supplies an empty queue context. It first applies the existing callback-derived queue blocking, then uses the existing queue resolver and invocation-role authority.

Run `34188668989` evidence:

- total source-backed queue intents in the focused source build: `213`;
- production-relevant `TurnInsertAbility` queue intent denominator used for role resolution: `178`;
- queue resolutions: `178`;
- queue resolution coverage: `150 executable`, `28 blocked`;
- executable queue-root standalone graphs: `43`;
- full queue-aware standalone phase role histogram:
  - `nested_only = 35`
  - `standalone_root = 43`
  - `unbound_definition = 983`
  - `non_gameplay_noop = 23`

Every blocked queue resolution has an explicit reason. Existing blocked/deferred/unsupported queue facts are not erased.

The dynamically promoted status target is not one of the executable queue-root graphs. Its focused target closure contains exactly one phase and that phase remains `nested_only` under the real queue-aware invocation-role projection.

For the final focused RuleBook, the validator uses existing production task-graph helpers to build a source-closed formal slice consisting of the dynamic action-window candidate callback plus its queue-aware typed-target ability closure. This keeps CanonicalIR formal ability/status graph denominators internally complete instead of omitting queue authority or claiming unrelated formal entries were materialized.

Final focused formal slice evidence:

- formal target graph count: `1`;
- formal target phase count: `1`;
- ability formal slice count: `1`;
- status formal slice count: `1`;
- installed task-graph materializations: `2`;
- focused queue-aware invocation-role histogram: `nested_only = 1`.

### 4.3 A1 admission regression

Fast and Direct both reuse the existing A1 validator rather than inventing a parallel authority.

The following A1 authority paths are byte-for-byte equal to fixed base `bd1a4ac94ca394d2ea563d086eaf56e9ed45b285`:

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/action_contract.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/task_graph.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_formal_action_graph_admission_authority.py
```

Run `34188668989`:

- A1 Fast behavior digest: `7b47540c2cd8bea0dd218ae9898552f2f5d3bcae31ce76cd27a3f249144b8dc7`;
- A1 Direct behavior digest: `44c94fe263d7e75761e4d0747318dfa1418d0b8daa481c7daddc5cfce350cf28`;
- A1 Direct scanned `31` real action definitions from signed TBGD source;
- all A1 Fast/Direct predicates passed, including graph-root/nested-link discovery, reachable blocker preservation, public target query/accept, action-contract evaluation after target acceptance, no forged authorization/fingerprint, and zero full CanonicalIR builds inside the A1 Direct helper.

## 5. Complete same-action-window-event transition ledger

Direct independently snapshots every formal `mainline_avatar_ability` callback whose event has a unique real action-window runtime source, plus all owned callback tasks, before finalization and after the normal post-finalizer blocker propagation.

Run `34188668989` denominator:

- action-window callbacks: `238`;
- owned callback tasks: `1008`.

Callback status histogram was unchanged:

```text
before: blocked=112, executable=126
after:  blocked=112, executable=126
```

There were no callback aggregate field changes.

Task status histogram changed by exactly one row:

```text
before: blocked=458, executable=550
after:  blocked=457, executable=551
```

The stale `OnAfterAttack` task reason changed from `111` rows to `110`; empty task reason changed from `550` to `551`. All other independent condition/effect/queue/source/target blocker reason counts remained unchanged.

The only task transition was the same dynamically reconciled TriggerAbility candidate selected by the production finalizer:

- before: `blocked`, `status_callback_event_not_admitted:OnAfterAttack`;
- after: `executable`, no blocker;
- `promoted_by_finalizer = true`.

Any blocked task becoming executable without a corresponding production finalizer `promoted` audit row fails Direct. Any promoted row whose old reason is not the exact stale event blocker fails Direct.

## 6. Production audit and promoted row evidence

The production finalizer audit currently contains eight TriggerAbility audit rows:

```text
action_window_producer_missing: 7
promoted: 1
```

Before-task reason histogram for those audit rows:

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

The dynamic positive representative in the current source snapshot is the Silver Wolf `OnAfterAttack -> TriggerAbility` formal branch. This identity is report evidence only and is not used as a validator or production allowlist.

For that dynamic row, run `34188668989` proves:

- pre-finalizer task blocker is exactly `status_callback_event_not_admitted:OnAfterAttack`;
- event producer is uniquely `action.window.after_attack`;
- callback/task are executable after finalization;
- typed target is unique;
- typed target resolves to the existing standalone formal graph;
- target is `nested_only` under real queue context and is not a queue root;
- formal status root materializes as `task_graph:1547145a4dc70ef3ce732420f661012705efcaa561441dce019adb58a9e1b20d`;
- no callback/task/source/link stable identity changes.

The other seven audited TriggerAbility rows remain blocked.

## 7. Fast validation

Command:

```bash
python hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p0_action_window_status_callback_admission_finalization.py --fast
```

Run `34188668989`: `FAST PASS`.

Negative reason classes emitted:

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

Fast also verifies:

- positive exact-stale promotion;
- independent task blocker preservation;
- typed target missing/ambiguous/missing-graph fail closed;
- synthetic/wrong source mode fail closed;
- blocked/missing/ambiguous producer fail closed;
- blocked sibling closure;
- formal-branch child closure semantics;
- stable callback/task/source/link identity;
- S8B5B link pass alone does not promote the parent;
- A1 behavior regression;
- governance guards against forbidden runtime/task-graph/RandomConfig-RNG scope expansion.

Resource evidence from run `34188668989`:

- elapsed command time: about `2.66 s`;
- peak RSS: `135144 KiB`.

## 8. Real L0 Direct validation

Command:

```bash
python hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p0_action_window_status_callback_admission_finalization.py --direct
```

Run `34188668989`: `DIRECT PASS`.

Key evidence:

- builder: `focused_formal_character_source_denominator`;
- independent denominator builder: `pre_finalizer_source_backed_ir`;
- bidirectional reconciliation: `exact`;
- denominator count: `1`;
- promoted count: `1`;
- complete same-action-window-event transition ledger: `238 callbacks / 1008 tasks`;
- queue-aware role resolution: `178` real `TurnInsertAbility` resolutions;
- focused formal closure: `1` target graph, `1` target phase, `1` ability slice, `1` status slice;
- installed materializations: `2`;
- internal focused build wall time before the separate A1 Direct regression: `21.664 s`;
- total measured Direct command elapsed: about `3:12.03`;
- peak RSS: `733968 KiB`.

The higher total Direct time includes the independent A1 real-source behavior regression; no validation criterion was removed to reduce runtime.

## 9. CI, fixed-base check, and token permissions

Validated pre-report head:

`fd300413dd4c0e330c711b6542c74d81bda1b91b`

Committed-head workflow run:

- run id: `34188668989`;
- job id: `101942040773`;
- conclusion: `success`;
- successful steps: checkout pinned TBGD, source pin, compile, Fast, Direct, fixed-base diff check.

Fixed-base command:

```bash
git diff --check bd1a4ac94ca394d2ea563d086eaf56e9ed45b285 HEAD
```

Result: PASS.

The successful final-code job shows normal read-only `GITHUB_TOKEN` permissions:

```text
Contents: read
Metadata: read
Packages: read
```

No write permission is retained or requested by the final workflow.

## 10. Remediation CI audit trail

After REVIEW comment `5578826676`, several intermediate validator-only heads intentionally failed while strengthening the STRICT evidence. These failures did not change production behavior and were repaired under EXEC rather than re-planned:

- run `34185605704`: focused Direct widened ability/materializer context incorrectly;
- run `34186604858`: transition ledger incorrectly required formal descendants to share callback root source path;
- run `34187325178`: unrelated nested-only ability entries were still included in the focused formal materializer denominator;
- run `34187867529`: status-only formal slice was attached to a CanonicalIR still claiming all formal ability entries;
- final validator head `fd300413dd4c0e330c711b6542c74d81bda1b91b`, run `34188668989`: all Compile/Fast/Direct/fixed-base gates passed.

These are ordinary validation harness corrections. They did not require production scope expansion, new dependency, new permission, or public-contract change.

## 11. Scope proof

Current PR changed-file scope is limited to the card-authorized five files:

```text
.github/workflows/p9-a2-p0-pr-validation.yml
hsr_v075_baseline_clean/hsr/live_validation_reports/P9-A2-P0_ACTION_WINDOW_STATUS_CALLBACK_ADMISSION_FINALIZATION_execution_report.md
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9-A2-P0_ACTION_WINDOW_STATUS_CALLBACK_ADMISSION_FINALIZATION.md
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p0_action_window_status_callback_admission_finalization.py
```

No `core/**`, `systems/**`, `rules/**`, `tbgd/task_graph_materializer.py`, `TaskGraphContinuation`, PR #11 runtime file, or PR #9 RandomConfig/weighted-selection/RNG implementation changed in this PR. The A1 authority files are exact-equal to the fixed base.

## 12. Remaining work / handoff boundary

A2-P0 closes only the merged-master L0 source-backed action-window status callback/task admission-finalization prerequisite.

After REVIEW independently accepts and merges PR #12:

1. preserve PR #11's existing implementation;
2. update PR #11 onto the newly merged master;
3. rerun PR #11's original Fast unchanged;
4. rerun PR #11's unchanged real `CombatExecutor.execute(ActionCommand)` Direct;
5. do not substitute this A2-P0 L0 Direct for PR #11 runtime Direct;
6. keep PR #9 RandomConfig/RNG deferred until the PR #11 chain is independently accepted/merged.
