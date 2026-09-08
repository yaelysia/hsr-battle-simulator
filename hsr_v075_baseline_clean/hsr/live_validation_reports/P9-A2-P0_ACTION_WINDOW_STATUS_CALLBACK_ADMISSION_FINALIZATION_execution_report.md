# P9-A2-P0 Action-window Status Callback Admission Finalization — Execution Report

## 1. Scope, authority, and heads

- Fixed base: `master@bd1a4ac94ca394d2ea563d086eaf56e9ed45b285`.
- Pinned TBGD source: `14c1d18f91a8101d610e6c523447a7517de3fae1`.
- Production implementation commit remains `a73576c6d5d751f6c5d14713e5ed49883fc82b2f` (`Implement A2-P0 status callback admission finalizer`).
- Read-only validation workflow restore commit remains `6780464df87e7f98ec1b31793b2f808bd313f7f2`.
- Initial REVIEW STRICT-evidence return: PR comment `5578826676`.
- Latest REVIEW differential return for the remaining raw/source denominator gap: PR comment `5579864543`.
- Final validator-only remediation head before this report: `2a408fd2cd4960a20fb210a7caf73980197b3573`.
- Its committed-head validation run `34192741125`, job `101953963643`, concluded `success`.
- This report update creates a later governance-only head; its exact SHA and committed-head CI are recorded in the following PR WAIT/HANDOFF comment because a commit cannot contain its own SHA before it exists.

No production file changed after `a73576c6d5d751f6c5d14713e5ed49883fc82b2f`. The latest REVIEW remediation changes only the card-authorized validator and this execution report.

## 2. Exact production change

The only production file changed by this card is:

`hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py`

Production behavior remains the previously validated A2-P0 implementation:

1. after existing status callback/task lowering, initial status-event-family projection, and typed `TriggerAbility` linking, call `_finalize_action_window_status_callback_admission(...)`;
2. consume existing callback/task, event producer, effect, typed target, standalone graph/phase, and formal-source facts only;
3. re-adjudicate only the exact stale `status_callback_event_not_admitted:<event>` blocker when every source, producer, typed-target, graph and closure condition is satisfied;
4. preserve callback/task/source/link/topology identity and continue through existing blocker propagation, queue resolution, invocation-role assignment, task-graph materialization, CanonicalIR and RuleBook construction.

No second event registry, callback allowlist, character/ability/file special case, public IR schema change, TaskGraphIR/continuation change, runtime routing authority, RandomConfig caller, weighted-selection implementation or RNG ledger was added.

## 3. Production order and reused authorities

The verified production order is:

```text
raw character ability source
  -> per-file status callback/task lowering
  -> source/effect/task semantics
  -> status event family/runtime producer projection
  -> typed TriggerAbility link pass
  -> A2-P0 final admission projection
  -> status blocker propagation
  -> queue resolution
  -> invocation-role assignment
  -> task-graph materialization/catalog
  -> CanonicalIR / RuleBook
```

Existing authorities are reused, not replaced:

- raw/formal source: pinned TBGD character source graph and authoritative formal-source context;
- event producer: existing `STATUS_EVENT_RUNTIME_SOURCES` / `StatusEventFamilyIR.runtime_event_sources`;
- callback/task lowering identity: existing L0 lowering;
- formal child/template traversal: existing `_formal_ability_task_children(...)` backed by `control_by_location`, template references and formal source documents;
- typed target: existing `_link_status_trigger_ability_graphs(...)` output;
- queue roots: existing `_lower_queue_resolutions(...)`;
- invocation role: existing `_assign_character_ability_invocation_roles(...)`;
- formal task graphs: existing task-graph materializer helpers and catalog invariants;
- A1 admission: existing A1 authority/validator.

## 4. REVIEW remediation closure

### 4.1 Finding #1 — raw/source denominator now independent of production status-task lowering

Latest REVIEW comment `5579864543` correctly observed that the prior denominator began from already-lowered `StatusCallbackTaskIR`; therefore a lowering omission could be shared by both the denominator and finalizer audit.

The final validator now constructs the first denominator **before calling `_lower_ability_file(...)`**.

#### Raw/source occurrence authority

Direct first builds the pinned character source graph and obtains the authoritative formal-source context. It then enumerates action-window status callback/task occurrences directly from:

```text
formal_context.documents
+ formal_context.control_by_location
+ formal_context.references_by_node/template_by_id
+ existing _formal_ability_task_children(...)
+ existing STATUS_EVENT_RUNTIME_SOURCES
```

The raw occurrence key is:

```text
(callback_source_path,
 callback_json_path,
 event,
 task_source_path,
 task_json_path,
 raw_opcode)
```

No callback ID, task ID, character, ability, file name or expected count is used to select a passing row.

Run `34192741125` raw/source evidence:

- formal source files: `80`;
- action-window callback locations enumerated from raw/formal source: `238`;
- raw/source-backed action-window `TriggerAbility` occurrences: `1`;
- raw occurrence digest: `9c4b3ba1e834ce8027bb1ac5e5e5fdb69074bbc5d86cd86c95607a7d6cb3619c`;
- producer authority: `STATUS_EVENT_RUNTIME_SOURCES`;
- source expansion authority: `formal_context.documents + control_by_location/template references`.

#### Raw/source ↔ pre-finalizer lowering IR

Only after the raw ledger is complete does Direct run normal `_lower_ability_file(...)` over the same 80 formal source files.

It maps lowered `TriggerAbility` tasks back to source occurrence identity through existing callback/task source evidence:

- callback source path and `callback_json_path`;
- task source path and `json_path`;
- raw opcode;
- admission source path;
- event and runtime-source identity.

Run `34192741125`:

- raw occurrence count: `1`;
- matching pre-finalizer lowered occurrence count: `1`;
- `raw_to_pre_finalizer_ir_reconciliation = exact`.

Any raw occurrence missing from lowering, or any extra lowered occurrence not present in the raw ledger, fails Direct before finalizer validation. Therefore a `_lower_ability_file` / formal task-lowering omission can no longer be hidden by the finalizer audit sharing the same omission.

#### Pre-finalizer IR ↔ typed candidate ↔ finalizer audit

After raw↔lowered reconciliation, Direct performs the existing typed-target/effect/formal-graph filtering and then reconciles the resulting candidate set bidirectionally against production finalizer audit rows.

Run `34192741125`:

- independent denominator builder: `raw_formal_source_graph -> pre_finalizer_lowered_ir -> typed_candidate -> finalizer_audit`;
- typed action-window TriggerAbility denominator: `1`;
- promoted: `1`;
- typed/finalizer bidirectional reconciliation: `exact`.

The validation chain is therefore now:

```text
pinned raw/formal source occurrence ledger
  <-> pre-finalizer production lowering IR
  <-> typed target / formal graph candidate
  <-> production finalizer audit
  <-> final CanonicalIR / RuleBook
```

This closes the false-positive mode identified in REVIEW finding #1.

### 4.2 Finding #2 — queue/invocation-role context remains production-equivalent

REVIEW already marked this finding closed. The final run preserves that evidence.

Run `34192741125`:

- source-backed queue intents in focused source build: `213`;
- production-relevant `TurnInsertAbility` intents used for role resolution: `178`;
- queue resolutions: `178`;
- queue coverage: `150 executable`, `28 blocked`;
- executable queue-root standalone graphs: `43`;
- full queue-aware standalone phase role histogram:
  - `nested_only = 35`
  - `standalone_root = 43`
  - `unbound_definition = 983`
  - `non_gameplay_noop = 23`.

The dynamically promoted target is not a queue root. Its focused target closure remains `nested_only` under real queue-aware invocation-role assignment.

Focused final formal closure:

- target graph count: `1`;
- target phase count: `1`;
- ability formal slice count: `1`;
- status formal slice count: `1`;
- task-graph materializations: `2`.

### 4.3 Finding #3 — A1 admission behavior remains unchanged

REVIEW already marked this finding closed. The final run retains it.

These A1 authority paths remain byte-for-byte equal to fixed base:

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/action_contract.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/task_graph.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_formal_action_graph_admission_authority.py
```

Run `34192741125`:

- A1 Fast behavior digest: `7b47540c2cd8bea0dd218ae9898552f2f5d3bcae31ce76cd27a3f249144b8dc7`;
- signed TBGD source fingerprint: `349d9dd2ade62d32e17b25a49400c8043dfdf0cea73250aa0ee4bc23fcedb998`;
- every A1 Direct predicate passed.

The existing A1 Direct helper has a 165-second discovery guard, so `scanned_action_definitions` and its diagnostic digest are run-specific diagnostics, not fixed acceptance constants. In this run it scanned `31` definitions and emitted diagnostic digest `44c94fe263d7e75761e4d0747318dfa1418d0b8daa481c7daddc5cfce350cf28`.

## 5. Complete same-action-window-event transition ledger

Direct independently snapshots all formal `mainline_avatar_ability` callbacks whose event has one real action-window source, together with all owned callback tasks, before and after finalization/blocker propagation.

Run `34192741125`:

- action-window callbacks: `238`;
- owned callback tasks: `1008`.

Callback status histogram is unchanged:

```text
before: blocked=112, executable=126
after:  blocked=112, executable=126
```

No callback aggregate field changes occurred.

Task status histogram changes by exactly one row:

```text
before: blocked=458, executable=550
after:  blocked=457, executable=551
```

The stale `OnAfterAttack` blocker count changes from `111` to `110`; the empty task-reason count changes from `550` to `551`. All other independent condition/effect/queue/source/target blocker counts remain unchanged.

The only task transition is the same reconciled `TriggerAbility` candidate selected by the production finalizer:

- before: `blocked`, `status_callback_event_not_admitted:OnAfterAttack`;
- after: `executable`, no blocker;
- `promoted_by_finalizer = true`.

## 6. Production audit and final positive

The production finalizer audit contains eight `TriggerAbility` rows:

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

The dynamic representative in the current pinned source is the Silver Wolf `OnAfterAttack -> TriggerAbility` formal branch. This is report evidence only, never an allowlist.

For that row, final Direct proves:

- it exists in the independent raw/formal-source occurrence ledger;
- it maps exactly to a pre-finalizer lowering IR occurrence;
- pre-finalizer blocker is exactly `status_callback_event_not_admitted:OnAfterAttack`;
- event producer is uniquely `action.window.after_attack`;
- typed target is unique and resolves to the existing formal standalone graph;
- target is queue-aware `nested_only` and is not an executable queue root;
- final callback/task are executable;
- formal status root materializes as `task_graph:1547145a4dc70ef3ce732420f661012705efcaa561441dce019adb58a9e1b20d`;
- callback/task/source/link identity is stable.

The seven non-promoted audit rows remain blocked.

## 7. Fast validation

Command:

```bash
python hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p0_action_window_status_callback_admission_finalization.py --fast
```

Run `34192741125`: `FAST PASS`.

It emits all required negative reason classes and verifies:

- exact-stale positive promotion;
- independent blocker preservation;
- missing/ambiguous/bad typed target fail-closed behavior;
- wrong/synthetic source fail closed;
- missing/ambiguous/blocked producer fail closed;
- blocked sibling closure;
- formal-branch child closure;
- stable callback/task/source/link identity;
- S8B5B link pass alone does not promote a blocked parent;
- A1 Fast behavior regression;
- governance guards against forbidden runtime/task-graph/RandomConfig-RNG changes.

Resource evidence:

- elapsed command time: about `3.10 s`;
- peak RSS: `135128 KiB`.

## 8. Real L0 Direct validation

Command:

```bash
python hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p0_action_window_status_callback_admission_finalization.py --direct
```

Run `34192741125`: `DIRECT PASS`.

Key evidence:

- builder: `focused_formal_character_source_denominator`;
- independent chain: `raw_formal_source_graph -> pre_finalizer_lowered_ir -> typed_candidate -> finalizer_audit`;
- raw↔pre-finalizer reconciliation: `exact`;
- typed/finalizer reconciliation: `exact`;
- raw action-window callback locations: `238`;
- raw TriggerAbility occurrence count: `1`;
- typed denominator count: `1`;
- promoted count: `1`;
- complete same-action-window transition ledger: `238 callbacks / 1008 tasks`;
- queue-aware role resolution: `178` real `TurnInsertAbility` resolutions;
- focused formal closure: `1` target graph, `1` target phase, `1` ability slice, `1` status slice;
- installed task-graph materializations: `2`;
- internal focused build wall time before separate A1 Direct regression: `21.803 s`;
- total Direct elapsed: about `3:13.42`;
- peak RSS: `732596 KiB`.

## 9. CI, fixed-base, and token permissions

Validated validator head:

- head: `2a408fd2cd4960a20fb210a7caf73980197b3573`;
- run: `34192741125`;
- job: `101953963643`;
- result: `success`;
- successful steps: checkout pinned TBGD, source pin, Compile, Fast, Direct, fixed-base diff check.

Pinned submodule in the run:

`14c1d18f91a8101d610e6c523447a7517de3fae1`

Fixed-base command:

```bash
git diff --check bd1a4ac94ca394d2ea563d086eaf56e9ed45b285 HEAD
```

Result: PASS.

The job shows normal read-only `GITHUB_TOKEN` permissions:

```text
Contents: read
Metadata: read
Packages: read
```

No write permission is retained or requested by the final workflow.

## 10. Remediation audit trail

The production implementation was not changed during REVIEW remediation.

Relevant STRICT evidence history:

- REVIEW `5578826676` identified independent denominator, queue-context, and A1 behavior-evidence defects;
- queue-context and A1 defects were corrected and later explicitly accepted as closed by REVIEW;
- REVIEW `5579864543` identified the remaining false-positive risk: the denominator still began from pre-finalizer lowering IR;
- validator commit `2a408fd2cd4960a20fb210a7caf73980197b3573` adds the pre-lowering raw/formal-source occurrence ledger and raw↔lowered bidirectional reconciliation;
- run `34192741125` passes Compile/Fast/Direct/fixed-base with the new raw denominator active.

No remediation required production scope expansion, new dependency, new permission or public-contract change.

## 11. Scope proof

Current PR changed-file scope remains limited to the card-authorized five files:

```text
.github/workflows/p9-a2-p0-pr-validation.yml
hsr_v075_baseline_clean/hsr/live_validation_reports/P9-A2-P0_ACTION_WINDOW_STATUS_CALLBACK_ADMISSION_FINALIZATION_execution_report.md
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9-A2-P0_ACTION_WINDOW_STATUS_CALLBACK_ADMISSION_FINALIZATION.md
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p0_action_window_status_callback_admission_finalization.py
```

No `core/**`, `systems/**`, `rules/**`, `tbgd/task_graph_materializer.py`, `TaskGraphContinuation`, PR #11 runtime file, or PR #9 RandomConfig/weighted-selection/RNG implementation changed during this remediation. A1 authority files remain exact-equal to fixed base.

## 12. Remaining work / handoff boundary

A2-P0 closes only the merged-master L0 source-backed action-window status callback/task admission-finalization prerequisite.

After REVIEW independently accepts and merges PR #12:

1. preserve PR #11's existing implementation;
2. update PR #11 onto the newly merged master;
3. rerun PR #11's original Fast unchanged;
4. rerun PR #11's unchanged real `CombatExecutor.execute(ActionCommand)` Direct;
5. do not substitute this A2-P0 L0 Direct for PR #11 runtime Direct;
6. keep PR #9 RandomConfig/RNG deferred until the PR #11 chain is independently accepted/merged.
