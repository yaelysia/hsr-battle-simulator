# P9-A2-P4 SetEntityVisible process-only retirement — execution report

## Status

- PR: `#17` (`plan/p9-a2-p4-set-entity-visible-process-only-retirement`).
- Stage: `P9-A2-P4_SET_ENTITY_VISIBLE_PROCESS_ONLY_RETIREMENT`.
- Validated business head: `694f48e76f60357349e6d1b03b0afa4a75cc7ad6`.
- Fixed base: `4beebe293f74e37e709d5cfc978f098d1e804128`.
- Pinned TBGD: `14c1d18f91a8101d610e6c523447a7517de3fae1`.
- This closeout added no production change. PR #17 production changes remain limited to
  `tbgd/coverage.py` and `tbgd/lowering.py`.
- This report commit changes the PR head. Final-head CI is checked after push and is not written back into this
  report to avoid a report/CI commit loop.

## Delivered behavior

The existing generic formal AbilityTask process-only contract now admits source-proven `SetEntityVisible` tasks
with the strict `TargetType` / `UniqueKey` / `Visible` field schema. Each admitted task remains a process-only
formal graph leaf with exactly one same-source `audit_only` effect identity. It performs no visibility operation or
gameplay mutation.

The change applies only to the formal AbilityTask producer. Formal status-callback occurrences retain the existing
`StatusCallbackTaskIR` / `task_graph_materializer._status_task` authority and runtime-effect execution mode. The
unreferenced GlobalTemplate occurrence remains a definition with no formal producer. `SetEntityForceVisible` is
unchanged.

## Validation on `694f48e76f60357349e6d1b03b0afa4a75cc7ad6`

Local validation used the existing system `python3` because this workspace has no `python` alias and no installed
pytest module. No environment or dependency was created. The committed workflow independently runs the same
focused test file directly.

- scoped four-file `python3 -m compileall -q`: exit `0`;
- focused P4 Fast test file: `P4_FOCUSED_FAST passed=10`;
- A1 Fast regression: `mode=fast`, `ok=true`, `cases=11`, all predicates true;
- real P4 Direct: exit `0`, `mode=direct`, `ok=true`, all predicates true;
- fixed-base `git diff --check 4beebe293f74e37e709d5cfc978f098d1e804128...HEAD`: exit `0`;
- fixed-base changed-path gate: exact match to the six existing card-authorized PR paths.

The earlier exact-head hosted run `34741344455` also passed on this same business head. The local rerun above is the
closeout evidence used for this report.

## Complete source denominator

The Direct validator streamed the full pinned-source denominator from `18` source files with fingerprint
`349d9dd2ade62d32e17b25a49400c8043dfdf0cea73250aa0ee4bc23fcedb998`:

```text
117 total = 107 formal AbilityTask
          +   9 formal status-callback task
          +   1 template definition with no formal producer
          +   0 blocked or unresolved
```

The partition identity closed exactly and the formal AbilityTask slice was non-empty. Representative attribution:

- AbilityTask: `Config/ConfigAbility/Avatar/Avatar_Acheron_00_Ability.json`,
  `$.AbilityList[2].OnStart[19]`;
- status callback: `Config/ConfigAbility/Avatar/Avatar_Moze_00_Ability.json`,
  `$.AbilityList[7].Modifiers.Avatar_Moze_00_PassiveModifier._CallbackList[0].CallbackConfig[0]`;
- template definition: `Config/ConfigAbility/Avatar/Avatar_Feixiao_00_Ability.json`,
  `$.GlobalTemplates[13].TaskList[0]`; its containing template has no formal references, so no synthetic task was
  created.

## Provenance delta and residual blockers

For the dynamically selected same-owner action `avatar_skill:1100601` level `1`, baseline provenance contained two
formal `SetEntityVisible` tasks, each contributing
`effect_coverage_status:unsupported:SetEntityVisible` and
`task_graph_definition_not_admitted:effect:unsupported`. Current provenance contains no `SetEntityVisible` blocker.

The outer action remains correctly fail-closed with:

- `task_graph_definition_not_admitted:effect:audit_only`;
- `task_graph_control_requires_domains:damage_heal_shield`.

P3 `WaitAnimState` retirement remains intact. S11, damage/heal/shield, other S8C domains, PR #11 A2 runtime
transport, and PR #9 RandomConfig caller/RNG ledger remain deferred. P4 does not require the outer action to become
executable.

## Runtime non-execution and resources

The Direct run observed:

- task-graph execute calls: `0`;
- condition-evaluation calls: `0`;
- RNG draw calls: `0`;
- mutations: `0`;
- events: `0`;
- settlement records: `0`;
- replay mutations: `0`;
- pending-event, event-index, RNG-state-event, settlement-state and replay-state deltas: all `0`;
- state unchanged: `true`.

Resource result:

- peak RSS: `577024 KiB` (`< 2097152 KiB`);
- wall time: `205.876146s` (`< 300s`).

The remaining closeout step is exact report-head CI followed by FULL_AUDIT review. This execution thread does not
merge PR #17.
