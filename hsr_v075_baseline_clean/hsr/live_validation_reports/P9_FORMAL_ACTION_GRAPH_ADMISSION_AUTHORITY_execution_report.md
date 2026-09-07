# P9 Formal Action Graph Admission Authority — Execution Report

Execution handoff result: `ready_for_review`.

## 1. Identity

- Stage: `P9_FORMAL_ACTION_GRAPH_ADMISSION_AUTHORITY` (A1 prerequisite only)
- PR: `#10`
- Branch: `plan/p9-formal-action-graph-admission-authority`
- Planning/base authority: `master@b01e813bd194b5e5bc7bcd6ba65d8ba0ee0e44ce`
- Execution card: `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9_FORMAL_ACTION_GRAPH_ADMISSION_AUTHORITY.md`
- REVIEW return-for-fix handoff: PR comment `5570308533`
- Remediation code-validation head: `8f4aa5df14abc7cc5a9385a86330a987228ddb0b`
- Remediation code-validation hosted CI: `https://github.com/yaelysia/hsr-battle-simulator/actions/runs/34121219910`
- Remediation code-validation job: `101739442339`
- Repository-pinned TBGD submodule: `14c1d18f91a8101d610e6c523447a7517de3fae1`
- Report-containing final PR head and its final hosted CI are intentionally recorded in the PR `[HANDOFF:REVIEW]` comment because this report cannot self-reference its own commit.

## 2. Authorized write set

The execution diff remains confined to the planner-owned card plus the card-authorized execution paths.

Execution-authorized paths:

1. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/action_contract.py` — the **only production file** changed by A1.
2. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_formal_action_graph_admission_authority.py`
3. `hsr_v075_baseline_clean/hsr/live_validation_reports/P9_FORMAL_ACTION_GRAPH_ADMISSION_AUTHORITY_execution_report.md`
4. `.github/workflows/p9-s8c1b-pr-validation.yml` — reuse of the existing workflow only; accepted S8C1A/S8C1B regression gates and PR-base diff check are retained.

Planner-owned path already present before EXEC implementation:

- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9_FORMAL_ACTION_GRAPH_ADMISSION_AUTHORITY.md`

No `AbilityTaskSystem`, `TaskGraphExecutor`, task-graph IR/materializer, RuleBook storage, event/status transport, RNG, `CombatExecutor`, or PR #9 production file was modified. The REVIEW remediation did not expand this write set.

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
- **Intra-graph topology remains solely authoritative in `TaskGraphIR`**: admission scans the canonical node set and does not re-walk runtime branches inside a graph.
- **Cross-graph nested-call cycle detection is path-sensitive**: one-time static support collection may globally de-duplicate graph bodies, but every resolved nested-graph call edge is recorded and then checked by a separate three-state DFS recursion stack from each formal action root. Re-entry into a currently active nested graph emits `task_graph_active_cycle:<graph_id>` with `source="nested_graph_cycle"` and fails closed.
- This DFS is limited to the resolved nested-graph call relation. It is not a second interpreter and does not evaluate branch/condition/count/target/RNG semantics.
- Deterministic metadata records root graph IDs, root entries, reachable task IDs, excluded bound task IDs, and blocker provenance. This metadata is evidence only and is not a gameplay input.

## 4. REVIEW return-for-fix remediation

REVIEW comment `5570308533` identified a real correctness defect in the first A1 implementation: the breadth-first support scan used one global `visited_graph_ids` set. For the reachable nested topology

`A -> {B, C}, B -> C, C -> B`

a graph body could already be globally visited through one sibling route before the other route reached the same graph. That global support-scan de-duplication could therefore suppress a path-sensitive active-cycle finding even though runtime graph execution is guarded by an active graph stack.

The remediation keeps the global set only for its valid purpose — scanning each graph body once for static support — and separately records the resolved nested graph edges. After support collection, a DFS with states `unvisited / visiting / done` walks that edge relation from each formal root. Any edge to a `visiting` graph is a fail-closed cross-graph active cycle.

No timeout, memory budget, target/admission gate, source authority, production write authority, dependency, or deferred boundary was relaxed.

## 5. Focused Fast validation

Command:

```bash
env PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_formal_action_graph_admission_authority --fast
```

Remediation code-validation run `34121219910`: **success**. The focused validator now reports `cases=11`, `ok=true` and covers:

1. unrelated bound `nested_only` task with a flat blocker is excluded from ordinary formal action admission;
2. reachable `TriggerAbility -> nested_only` graph is included and a blocker inside it remains fail-closed;
3. **explicit cross-graph topology `A -> {B,C}, B -> C, C -> B` fails closed with `task_graph_active_cycle:*` and `source="nested_graph_cycle"` provenance;**
4. reachable deferred node blocks with stable provenance;
5. reachable non-process-only unresolved gameplay reference blocks;
6. process-only unresolved audit-only reference is not by itself a gameplay blocker when the existing process-only contract is valid;
7. invalid process-only task contract still blocks;
8. `external_legacy` keeps the existing flat gate;
9. missing/malformed graph identity fails closed;
10. projection/metadata are deterministic across repeated runs;
11. admission performs no state mutation, RNG selection, graph execution, or runtime branch evaluation.

The cycle regression uses independently constructed fixture topology and independently expected cycle/provenance properties; it does not call the production projection helper to derive its expected answer. Because canonical node ordering may enter either side of the B/C strongly connected pair first, the assertion accepts either valid deterministic back edge while still requiring an actual `task_graph_active_cycle:*` result tied to one of the B<->C cycle edges and `nested_graph_cycle` provenance.

The workflow retains the hard `30s` Fast timeout. The green remediation run passed this unchanged gate.

## 6. Real TBGD Direct validation

Command:

```bash
env PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_formal_action_graph_admission_authority --direct
```

Remediation code-validation run `34121219910`: **success**. The workflow retains the hard `180s` Direct timeout; the validator independently enforces `<= 180s` and `<= 1 GiB`. A successful exit therefore proves the current remediation head remained inside both unchanged limits and all Direct semantic predicates were true. Full `TBGDLowering.build()` remains instrumented fail-closed and the Direct gate requires the measured full-CanonicalIR build count to be exactly `0`.

The Direct denominator is dynamically discovered from current merged-master production lowering/materialization and the repository-pinned TBGD submodule. It does not import PR #9 or hard-code the representative as the only denominator.

The established real-source representative remains:

- Action: `avatar_skill:100103`
- Level: `1`
- Definition: `action_def:avatar_skill:100103:1`
- Owner entity: `avatar:1001`
- Public submission mode: `insert_window`
- Allowed/current window: `ultimate`
- Formal action-root phase: `ability_phase:avatar_skill:100103:1:0:Avatar_Mar_7th_00_Skill03_Phase01`
- Nested-only phase reachable from the formal graph: `ability_phase:avatar_skill:100103:1:1:Avatar_Mar_7th_00_Skill03_Phase02`
- Unrelated bound nested-only phase excluded from the action-root closure: `ability_phase:avatar_skill:100103:1:2:Avatar_Mar_7th_00_Skill03_EnterReady`
- Root graph: `task_graph:20dbeb7ef7e53fa28d4bb9283c986192533be95e2b08a16d6a674e9e0720cdf0`

The old flat formal bound-task set is strictly broader than the action-root graph closure. A reproducible unique old flat-only blocker is the excluded `HeadLookAt` task under `Avatar_Mar_7th_00_Skill03_EnterReady` with `effect_coverage_status:unsupported:HeadLookAt`; after A1 it is absent from reachable-task/provenance output and does not leak into `ActionContractSystem.evaluate(...)`.

Reachable graph blockers remain fail-closed. The representative still exercises real public target selection through `ActionTargetSelectionSystem.query(...)`, `accept(...)`, context revalidation, and `ActionContractSystem.evaluate(...)`; no selection fingerprint or authorization is forged. The bounded real scan records external-legacy presence when encountered, while Fast independently proves the existing external-legacy flat gate.

## 7. Upstream regressions and hosted CI

For remediation code-validation head `8f4aa5df14abc7cc5a9385a86330a987228ddb0b`, hosted run `34121219910`, job `101739442339`, every workflow step completed **success**:

- checkout with the pinned TBGD submodule;
- scoped compile;
- S8C1A upstream weighted-selection IR validation;
- S8C1B weighted-selection Fast;
- S8C1B weighted-selection Direct;
- A1 focused Fast, including the new cross-graph active-cycle regression;
- A1 focused real-TBGD Direct;
- `git diff --check` against PR base.

The retained PR-base diff check remains:

```bash
git diff --check b01e813bd194b5e5bc7bcd6ba65d8ba0ee0e44ce HEAD
```

No paid/self-hosted runner or new dependency was introduced.

## 8. Validation/remediation trace

Historical failed heads are evidence only and are not used as current results:

- `040ddeeac4836f1ff5f2d6b7a2446a36a337dda9`: semantic evidence was inside the unchanged resource gates, but a deliberately negative evidence field (`forged_selection_fingerprint_or_authorization=false`) was incorrectly included directly in `all(predicates.values())`; fixed by using positive `no_forged_selection_fingerprint_or_authorization` semantics.
- `7e696196a5be1fb36cc804761e366a4b42d3b8bd`: numeric evidence `full_canonical_ir_build_count=0` was incorrectly placed inside `all(...)`, where integer zero is false; fixed by retaining the numeric count separately and gating on `full_canonical_ir_build_count_is_zero`.
- `bb057de0fa1abc9ecab668836d2482d1fcee7ee3`: prior code-validation head passed before REVIEW discovered the independent cross-graph cycle defect.
- `3d2a4806d6cbe40abd1f3f6f130cad0bf6aff185`, run `34120718536`: production DFS remediation compiled and all upstream S8C1A/S8C1B checks passed, but the new fixture over-specified that B rather than C must be the DFS back-edge target. The test assertion was corrected without changing production semantics or weakening the required cycle/provenance property.
- `8f4aa5df14abc7cc5a9385a86330a987228ddb0b`, run `34121219910`: current remediation code-validation head; compile, all upstream regressions, focused Fast 11/11, focused Direct, and PR-base diff check all passed.

## 9. Deferred / remaining scope

A1 still does **not** claim or implement A2. The following remains deferred exactly as the execution card requires:

- action-window status callback -> nested formal ability continuation/hook transport and routing;
- status-hook composition or any `StatusCallbackSystem` RandomConfig/RNG implementation;
- PR #9 weighted-selection caller / RandomConfig caller-RNG-ledger implementation;
- any task-graph executor/IR/materializer change;
- broader P9/S8C aggregate acceptance or unrelated mechanic families.

PR #9 remains outside this PR's implementation scope. The present remediation is limited to the REVIEW finding on A1 formal-admission cross-graph cycle detection.

## 10. Handoff

- EXEC result: `ready_for_review`
- REVIEW return-for-fix `5570308533`: remediated.
- Remaining implementation work in A1 known to EXEC: none.
- Next role: `REVIEW`.
- REVIEW should independently reproduce the explicit A->{B,C}, B->C, C->B Fast cycle case, the real-source flat-vs-action-root-closure Direct evidence, the public target query/accept -> ActionContract path, zero full-build gate, final-head hosted CI, and authorized diff boundary before acceptance.

## 11. REVIEW acceptance checkpoint

- REVIEW dispatch: `PR10-REVIEW-5570727999`.
- Independently reviewed implementation head: `84ee94b4d1bf25221d783f8a84d7b79f8e46f896`.
- Hosted implementation-head CI: run `34122026242`, job `101742022231`, **success** on the exact PR head merged against planning base.
- The REVIEW rechecked the prior finding rather than trusting the remediation report: one-time support scanning may de-duplicate graph bodies globally, but all resolved nested-call edges are recorded and a separate three-state DFS from formal roots detects path-sensitive active cycles. The required `A -> {B,C}, B -> C, C -> B` regression fails closed with `task_graph_active_cycle:*` / `nested_graph_cycle` provenance.
- Final implementation-head Fast: `cases=11`, `ok=true`; S8C1A, S8C1B Fast/Direct, A1 real-TBGD Direct and PR-base `git diff --check` all passed. A1 Direct remained under the unchanged `180s / 1 GiB` limits, used the pinned TBGD submodule, and measured `full_canonical_ir_build_count=0`.
- The full PR production write remains confined to `systems/action_contract.py`; A2, PR #9 caller/RNG-ledger, task-graph executor/IR/materializer and sibling domains remain deferred.
- No unique P9 total-plan checklist leaf corresponds to this dependency prerequisite. Therefore no checklist box is added or checked here, and the parent `P9-S8C` item remains deliberately unchecked.
- REVIEW verdict: `accepted`, subject only to the governance-head hosted CI merge gate. The governance-head CI run and real squash merge SHA are recorded in the final PR `[REVIEW:ACCEPTED]` comment because this file cannot self-reference those values.
