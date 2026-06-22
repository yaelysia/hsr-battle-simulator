# v8 v0_242 Queue Source / Priority / Drain Checkpoint

Date: 2026-06-22

## Scope

This checkpoint expands the queue subsystem from `QueueIntentIR -> QueueEntry -> blocked drain gate` to a source-audited drain path for the current admitted range:

```text
TurnInsertAbility task
-> QueueIntentIR
-> QueuePriorityIR
-> StandaloneAbilityGraphIR
-> QueueResolutionIR
-> QueueDrainPlan
-> dequeue mutation
-> standalone ability task/effect execution
```

The selected validation sample is chosen by structural predicates only:

- executable `QueueIntentIR`
- `opcode=TurnInsertAbility`
- executable callback/task source
- `QueueResolutionIR.resolved_kind=standalone_ability_graph`
- admitted priority source from `PriorityConfig.json`
- standalone graph has at least one executable task

## Implemented

- Lowered `QueuePriorityIR` from `Config/GlobalConfig/PriorityConfig.json`.
- Lowered `StandaloneAbilityGraphIR` from admitted mainline `ConfigAbility` AbilityList entries.
- Lowered `CombatantActionSetIR` from avatar/monster skill lists for future `TurnInsertAction` admission.
- Expanded queue intent source admission for mainline `ConfigGlobalModifier`, `ConfigAbility/Avatar`, `ConfigAbility/Monster`, `Common_Additional_Ability`, and `BattleEventAbility`.
- Added queue entry priority fields: priority key, value, priority IR id, and source trace.
- Added priority-aware `QueueSystem.plan_next_drain()`.
- Added admitted dequeue by queue entry id instead of always removing the first entry.
- Added `AbilityTaskSystem.execute_standalone()` for admitted standalone ability graph task/effect execution.
- Extended source audit so queue mutations must trace to `QueueIntentIR`, `QueueResolutionIR`, and `QueuePriorityIR`.
- Updated v0_240/v0_241 validations to use the unified explicit dispatcher callback path instead of relying on unrelated automatic listener matching.

## Validation Result

`validate_v0_242` selected:

- Queue intent: `queue_intent:status_callback:Config/ConfigAbility/Avatar/Avatar_Luocha_00_Ability.json:MAvatar_Luocha_00_InsertSkill02_Mark:4:OnStack:status_callback_task:Config/ConfigAbility/Avatar/Avatar_Luocha_00_Ability.json:MAvatar_Luocha_00_InsertSkill02_Mark:4:CallbackConfig[0]:TurnInsertAbility`
- Standalone graph: `standalone_ability_graph:Config_ConfigAbility_Avatar_Avatar_Luocha_00_Ability_json:Avatar_Luocha_00_Skill02_InsertAbility`
- Priority: `InsertAbilityPriority.AvatarHealOthers = 58`

The transition produced a source-audited queue dequeue mutation and admitted standalone ability effect mutation.

## Remaining Blocked Range

- `TurnInsertAction` drain remains blocked until runtime actor `template_id + SkillIndex -> CombatantActionSetIR -> ActionDefinitionIR` is admitted in the queue drain planner.
- `TurnInsertAssistantAbility` remains blocked until assistant actor identity, ability graph, target, and priority semantics are admitted.
- Full queue family total ordering across ultimate/immediate/follow-up/interrupt remains blocked.
- This checkpoint does not implement full ultimate interrupt ordering, follow-up/counter semantics, enemy AI, or bounce RNG.

## Commands

Run from `hsr_v075_baseline_clean/hsr`:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_227 --output-dir /tmp/hsr_v8_regression_v0_227
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_238 --output-dir /tmp/hsr_v8_regression_v0_238
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_240 --output-dir /tmp/hsr_v8_regression_v0_240
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_241 --output-dir /tmp/hsr_v8_regression_v0_241
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_242 --output-dir /tmp/hsr_v8_v0_242
git diff --check
```

Observed result:

- compileall: pass
- v0_225: ok
- v0_227: ok
- v0_238: ok
- v0_240: ok
- v0_241: ok
- v0_242: ok
- `git diff --check`: pass
