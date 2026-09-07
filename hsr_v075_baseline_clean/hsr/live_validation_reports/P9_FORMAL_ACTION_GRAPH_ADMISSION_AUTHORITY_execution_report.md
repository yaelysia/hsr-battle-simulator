# P9 Formal Action Graph Admission Authority — Execution Report

Execution handoff result: `ready_for_review`.

## 1. Identity

- Stage: `P9_FORMAL_ACTION_GRAPH_ADMISSION_AUTHORITY` (A1 prerequisite only)
- PR: `#10`
- Branch: `plan/p9-formal-action-graph-admission-authority`
- Planning/base authority: `master@b01e813bd194b5e5bc7bcd6ba65d8ba0ee0e44ce`
- Execution card: `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9_FORMAL_ACTION_GRAPH_ADMISSION_AUTHORITY.md`
- Code-validation head: `bb057de0fa1abc9ecab668836d2482d1fcee7ee3`
- Code-validation hosted CI: `https://github.com/yaelysia/hsr-battle-simulator/actions/runs/34117081776`
- Code-validation job: `101726310045`
- Repository-pinned TBGD submodule: `14c1d18f91a8101d610e6c523447a7517de3fae1`
- Report-containing final PR head and its final hosted CI are intentionally recorded in the PR `[HANDOFF:REVIEW]` comment because this report cannot self-reference its own commit.

## 2. Authorized write set

The execution diff is confined to the planner-owned card plus the card-authorized execution paths.

Execution-authorized paths:

1. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/action_contract.py` — the **only production file** changed by A1.
2. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_formal_action_graph_admission_authority.py`
3. `hsr_v075_baseline_clean/hsr/live_validation_reports/P9_FORMAL_ACTION_GRAPH_ADMISSION_AUTHORITY_execution_report.md`
4. `.github/workflows/p9-s8c1b-pr-validation.yml` — reuse of the existing workflow only; accepted S8C1A/S8C1B regression gates and PR-base diff check are retained.

Planner-owned path already present before EXEC implementation:

- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9_FORMAL_ACTION_GRAPH_ADMISSION_AUTHORITY.md`

No `AbilityTaskSystem`, `TaskGraphExecutor`, task-graph IR/materializer, RuleBook storage, event/status transport, RNG, `CombatExecutor`, or PR #9 production file was modified.

## 3. Authority and implementation result

A1 changes only action-admission projection in `ActionContractSystem`.

The resulting authority chain is:

`ActionAdmissionIR / accepted target-selection context -> ActionContractSystem -> exact formal action_root graph(s) -> statically reachable graph-node support + exact TriggerAbility nested graph links -> existing ability_task_runtime_blocked_reason(...)`

Key properties of the implementation:

- Formal roots are derived from existing `AbilityPhaseIR.invocation_role == "action_root"` facts used by the current formal ability runtime.
- `nested_only` phases are not flat roots. They enter admission only through an exact reachable `TriggerAbility` link to the exact existing nested phase/callback graph.
- `standalone_root` and `unbound_definition` do not become ordinary action-submission roots merely because they are bound to the same action/source definition.
- `external_legacy` retains the existing flat legacy gate with `topology_authority="external_legacy"`.
- Reachable formal tasks reuse `ability_task_runtime_blocked_reason(..., topology_authority="task_graph")`; A1 does not introduce a second opcode/effect/value support table.
- Reachable deferred task-graph nodes remain fail-closed with stable node status reason/provenance.
- Reachable non-process-only unresolved gameplay references remain fail-closed.
- Process-only tasks retain the current formal runtime distinction: their existing process-only contract is checked, while an audit-only unresolved graph reference is not by itself promoted into a gameplay blocker.
- Missing/mismatched graph/task/phase/callback/owner/nested-link identities fail closed.
- Admission does not evaluate runtime conditions, select branches, consume RNG, mutate state, or execute the graph.
- A1 does not add a second task-graph topology walker. `TaskGraphIR` already enforces that every graph node belongs to the canonical root-reachable, acyclic, single-parent graph. Admission scans that canonical graph node set for static support and only recursively resolves exact nested formal graphs.
- Deterministic metadata records root graph IDs, root entries, reachable task IDs, excluded bound task IDs, and blocker provenance. This metadata is evidence only and is not a gameplay input.

## 4. Focused Fast validation

Command:

```bash
env PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_formal_action_graph_admission_authority --fast
```

Code-validation run `34117081776`: **success**. The validator reports `cases=10`, `ok=true` and proves all required bounded cases:

1. unrelated bound `nested_only` task with a flat blocker is excluded from ordinary formal action admission;
2. reachable `TriggerAbility -> nested_only` graph is included and a blocker inside it remains fail-closed;
3. reachable deferred node blocks with stable provenance;
4. reachable non-process-only unresolved gameplay reference blocks;
5. process-only unresolved audit-only reference is not by itself a gameplay blocker when the existing process-only contract is valid;
6. invalid process-only task contract still blocks;
7. `external_legacy` keeps the existing flat gate;
8. missing/malformed graph identity fails closed;
9. projection/metadata are deterministic across repeated runs;
10. admission performs no state mutation, RNG selection, graph execution, or runtime branch evaluation.

The workflow keeps a hard `30s` Fast timeout. Code-validation remained within this gate.

## 5. Real TBGD Direct validation

Command:

```bash
env PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_formal_action_graph_admission_authority --direct
```

Code-validation run `34117081776`: **success**. The workflow keeps the existing hard `180s` Direct timeout; the validator independently enforces `<= 180s` and `<= 1 GiB`. The green code-validation head passed both limits. Full `TBGDLowering.build()` is instrumented fail-closed and the measured full-CanonicalIR build count is `0`.

The Direct denominator is dynamically discovered from current merged-master production lowering/materialization and the repository-pinned TBGD submodule. It does not import PR #9 or hard-code the representative as the only denominator. The bounded scan selected a reproducible strict flat-vs-graph representative from the current production denominator.

### Representative identity

- Action: `avatar_skill:100103`
- Level: `1`
- Definition: `action_def:avatar_skill:100103:1`
- Owner entity: `avatar:1001`
- Public submission mode used by the representative: `insert_window`
- Allowed/current window: `ultimate`
- Formal action-root phase: `ability_phase:avatar_skill:100103:1:0:Avatar_Mar_7th_00_Skill03_Phase01`
- Nested-only phase reachable from the formal graph: `ability_phase:avatar_skill:100103:1:1:Avatar_Mar_7th_00_Skill03_Phase02`
- Unrelated bound nested-only phase excluded from the action-root closure: `ability_phase:avatar_skill:100103:1:2:Avatar_Mar_7th_00_Skill03_EnterReady`
- Root graph: `task_graph:20dbeb7ef7e53fa28d4bb9283c986192533be95e2b08a16d6a674e9e0720cdf0`

The validator emits the exact root-node IDs, full reachable-task list, excluded-task list, phase invocation roles and blocker provenance in its Direct JSON output for reproduction from run `34117081776`.

### Before-vs-after projection delta

The old flat formal bound-task set is strictly broader than the action-root graph closure. In particular, the unrelated `Avatar_Mar_7th_00_Skill03_EnterReady` bound phase contributes flat-only tasks that are not reachable from the formal action root.

A reproducible unique old flat-only blocker is the excluded `HeadLookAt` task under `Avatar_Mar_7th_00_Skill03_EnterReady`:

- opcode/family: `HeadLookAt`
- old flat blocker: `effect_coverage_status:unsupported:HeadLookAt`
- Direct marks this reason as unique to the excluded set for the representative.

After A1, that excluded task is absent from `formal_action_reachable_task_ids` and from `formal_action_blocker_provenance`; its unique flat-only blocker does not leak into `ActionContractSystem.evaluate(...)`.

### Reachable blockers remain fail-closed

The same representative also contains blockers inside its actual formal graph closure, so Direct verifies the opposite side of the authority change at the same time. Reachable examples include:

- `effect_coverage_status:unsupported:AlignTargetToTeamCenter`
- `task_graph_definition_not_admitted:effect:unsupported`
- `process_only_task_effect_source_mismatch`

These reachable blockers remain present in the projection/provenance and keep the action contract fail-closed. A1 therefore removes only out-of-closure false blockers; it does not weaken blockers belonging to an actually reachable possible formal execution path.

### Public target/admission path

The representative is not admitted with a forged selection fingerprint or an internal shortcut. Direct performs:

1. `ActionTargetSelectionSystem.query(...)`;
2. `ActionTargetSelectionSystem.accept(...)`;
3. target-selection context revalidation against the unchanged state/command;
4. `ActionContractSystem.evaluate(...)` with the accepted context fingerprint;
5. comparison of ActionContract metadata against the independently derived production projection.

The selected representative uses the real automatic target-selection path against the validation enemy. Direct verifies that ActionContract root IDs, reachable IDs, excluded IDs and blocker provenance exactly equal the production projection.

### External legacy denominator

The bounded real scan did not encounter an `external_legacy` representative in the scanned current denominator. Direct records that fact and treats the real regression as applicable only when present; Fast independently proves the existing `external_legacy` flat gate is preserved.

## 6. Accepted upstream regressions and CI

The reused `.github/workflows/p9-s8c1b-pr-validation.yml` retains the accepted upstream gates. Code-validation run `34117081776`, job `101726310045`, completed **success** for every step:

- checkout with the pinned TBGD submodule: success;
- scoped compile: success;
- S8C1A upstream weighted-selection IR validation: success;
- S8C1B weighted-selection Fast: success;
- S8C1B weighted-selection Direct: success;
- A1 focused Fast: success;
- A1 focused Direct: success;
- `git diff --check` against PR base: success.

The workflow uses the normal GitHub-hosted Ubuntu runner only. No paid/self-hosted runner or new dependency was introduced.

The retained PR-base diff check is:

```bash
git diff --check b01e813bd194b5e5bc7bcd6ba65d8ba0ee0e44ce HEAD
```

and it passed on the code-validation head.

## 7. Validator remediation trace

The final production authority did not need scope expansion during this continuation. The remaining failures were validator/reporting defects and were repaired without lowering any gate.

- At head `040ddeeac4836f1ff5f2d6b7a2446a36a337dda9`, the real Direct produced the required semantic evidence inside the unchanged resource budgets, but the summary put a deliberately negative evidence field (`forged_selection_fingerprint_or_authorization=false`) inside `all(predicates.values())`, making the aggregate result false. The field was converted to the positive predicate `no_forged_selection_fingerprint_or_authorization=true`.
- At head `7e696196a5be1fb36cc804761e366a4b42d3b8bd`, all semantic predicates were true and Direct again remained inside the unchanged `180s / 1GiB` gates, but numeric evidence `full_canonical_ir_build_count=0` was still included in `all(...)`; Python correctly treats integer zero as false. The final validator instruments attempted full builds, records the numeric count independently, and gates on the positive boolean `full_canonical_ir_build_count_is_zero`. Any future full-build attempt increments the counter and fails closed.
- Head `bb057de0fa1abc9ecab668836d2482d1fcee7ee3` then passed compile, all retained upstream regressions, focused Fast, focused Direct and PR-base diff check on the hosted runner.

No remediation changed the production write set, Direct/Fast timeouts, memory limit, target/admission requirements, authority chain, dependency set, or deferred boundary.

## 8. Deferred / remaining scope

A1 does **not** claim or implement A2. The following remains deferred exactly as the execution card requires:

- action-window status callback -> nested formal ability continuation/hook transport and routing;
- status-hook composition or any `StatusCallbackSystem` RandomConfig/RNG implementation;
- PR #9 weighted-selection caller / RandomConfig caller-RNG-ledger implementation;
- any task-graph executor/IR/materializer change;
- broader P9/S8C aggregate acceptance or unrelated mechanic families.

PR #9 remains paused until A1 and the separately planned A2 prerequisite are accepted and merged. Only after both prerequisites merge should PR #9 be reconciled to the new master and resume its original real `CombatExecutor.execute(ActionCommand)` Direct.

## 9. Handoff

- EXEC result: `ready_for_review`
- Remaining implementation work in A1: none known.
- Next role: `REVIEW`
- REVIEW should independently reproduce the strict flat-vs-action-root-closure representative, the preserved reachable blocker evidence, the target query/accept -> ActionContract path, the zero full-build condition, the final-head hosted CI and the authorized diff boundary before acceptance.
