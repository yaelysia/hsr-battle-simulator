# v8 P4-S11 action/query contract ready_for_review

## Scope

P4-S11 validates a thin future external-controller contract. It does not implement a planner, searcher, scorer, route selector, or enemy AI.

The validation only proves that a caller can:

- query action availability through core;
- read action choices and target policy/target choices from the returned choice;
- submit an explicit `ActionCommand`;
- receive `BattleTransition` plus source audit and replay validation;
- receive structured blocked results for invalid commands with state unchanged.

## New Validation

Added:

```text
simulator_v8_clean_core/tools/validate_p4_s11_action_query_contract.py
```

Output:

```text
/tmp/hsr_v8_p4_s11_current/validation_summary_p4_s11_action_query_contract.json
/tmp/hsr_v8_p4_s11_current/p4_s11_action_query_contract_matrix.json
```

Result:

```text
ok=True
row_count=6
classification_counts={'boundary_only': 2, 'executable': 4}
positive_transition_count=3
blocked_transition_count=1
source_audit_all_ok=True
replay_all_ok=True
planner_implemented=False
enemy_action_auto_selected_by_core=False
unclassified_count=0
```

## Contract Rows

Validated rows:

```text
query_all_actionable_units_contract = executable
character_action_command_transition_contract = executable
monster_action_command_transition_contract = executable
summon_or_servant_action_command_transition_contract = executable
illegal_command_blocked_state_unchanged = boundary_only
no_planner_rule_ownership_boundary = boundary_only
```

The summon/servant execution row selected a `summoned_monster` sample because the servant availability sample is queryable but its current executor path is blocked by `summon_damage_stat_binding_not_admitted`. S11 therefore does not count servant availability as an execution positive.

## Transition Evidence

Positive transitions:

```text
character: mutation_count=5, source_audit_ok=True, replay_ok=True
monster: mutation_count=5, source_audit_ok=True, replay_ok=True
summoned_monster: mutation_count=5, source_audit_ok=True, replay_ok=True
```

Blocked command:

```text
mutation_count=0
state_unchanged=True
source_audit_ok=True
replay_ok=True
blocked_by=core target/executor preflight
```

The thin client only submits commands chosen from `ActionAvailabilitySystem.view`; target policy and target candidates come from the returned `ActionChoice`. It does not infer damage, status, resource, target, or enemy AI rules.

## Validation Commands

Commands run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile simulator_v8_clean_core/tools/validate_p4_s11_action_query_contract.py
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p4_s11_action_query_contract --output-dir /tmp/hsr_v8_p4_s11_current
```

No P1/P2/P3 aggregate was run in S11 because no runtime, lowering, RuleBook, action availability, target, summon, or executor code was changed. S12 aggregate will run the planned P1/P2/P3 regressions.

## Current Position

P4-S11 is ready for review. The project now has a validated external action/query contract sample, but no planner implementation. The minimum usable battle slice remains available through existing P1/P2/P3 substrates; full replication still requires the retained P4 source/admission backlog and later equipment/stage/environment expansion.
