# v8 Ability Task Execution Checkpoint v0_222

## Scope

- Added `AbilityTaskIR` as the Canonical IR task graph for ability phase callbacks.
- Linked `AbilityPhaseIR.task_ids` to lowered phase-local tasks.
- Lowered `OnStart / OnAttack / OnHit / OnEnd` task trees from mainline avatar `ConfigAbility` files.
- Reused existing effect/condition/formula standardization for phase tasks.
- Added `AbilityTaskSystem` so `CombatExecutor` schedules phase-local tasks without embedding effect semantics in executor.
- Added settlement and coverage records for `ability_task_graph` and individual `ability_task` execution.

## v0_222 Counts

- Discovery files: 8683
- Action definitions: 6949
- Action ability bindings: 6949
- Ability phases: 5944
- Ability tasks: 83202
- Executable ability tasks: 9045
- Blocked ability tasks: 74072
- Lowered predicate tasks: 85
- Effects: 140852
- Hit profiles: 5132

Top task opcodes by count include:

- `WaitAnimState`: 11853
- `TriggerAbility`: 9770
- `AddModifier`: 5417
- `PredicateTaskList`: 4569
- `SetDynamicValue`: 3050

## Runtime Validation

The v0_222 validator used structured predicates, not fixed role names, fixed action ids, fixed filenames, or fixed hashes.

Validated behavior:

- A real mainline avatar action phase lowered executable `AddModifier` task and produced mutation-linked settlement.
- A real unsupported `PredicateTaskList` condition was blocked and did not default into its success branch.
- Unsupported tasks/effects/targets/formulas carry source trace and blocked reason.
- Transition records include `ability_task_graph` and `ability_task` records.
- Ability task mutations replay from before snapshot to after snapshot.

Sample structured runtime result:

- Executable task action: `avatar_skill:130804` level 1
- Selected task opcode: `AddModifier`
- Action enabled: `true`
- Ability task records: 9
- Ability task mutations: 5

Predicate blocked sample:

- Selected task opcode: `PredicateTaskList`
- Blocked reason: `condition_not_executable:unsupported:ByRankActivated`
- Success branch was not executed by default.

## Validation

Commands run from `hsr_v075_baseline_clean/hsr`:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_200 --output-dir /tmp/hsr_v8_regression_v0_200
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_203 --output-dir /tmp/hsr_v8_regression_v0_203
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_204 --output-dir /tmp/hsr_v8_regression_v0_204
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_205 --output-dir /tmp/hsr_v8_regression_v0_205
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_206 --output-dir /tmp/hsr_v8_regression_v0_206
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_207 --output-dir /tmp/hsr_v8_regression_v0_207
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_208 --output-dir /tmp/hsr_v8_regression_v0_208
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_209 --output-dir /tmp/hsr_v8_regression_v0_209
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_210 --output-dir /tmp/hsr_v8_regression_v0_210
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_211 --output-dir /tmp/hsr_v8_regression_v0_211
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_212 --output-dir /tmp/hsr_v8_regression_v0_212
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_213 --output-dir /tmp/hsr_v8_regression_v0_213
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_214 --output-dir /tmp/hsr_v8_regression_v0_214
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_215 --output-dir /tmp/hsr_v8_regression_v0_215
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_216 --output-dir /tmp/hsr_v8_regression_v0_216
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_217 --output-dir /tmp/hsr_v8_regression_v0_217
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_218 --output-dir /tmp/hsr_v8_regression_v0_218
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_219 --output-dir /tmp/hsr_v8_regression_v0_219
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_220 --output-dir /tmp/hsr_v8_regression_v0_220
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_221 --output-dir /tmp/hsr_v8_regression_v0_221
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_222 --output-dir validation_outputs_v0_222
```

Result: all commands passed, including v0_222 `ok=true`.

## Remaining Risks

- This is not a complete Ability VM. It only executes standardized effect tasks.
- `TriggerAbility`, animation, camera, UI, projectile, timeline, and many client/performance tasks remain blocked or unsupported.
- Predicate branch execution only runs when condition evaluation is executable; unsupported conditions block the task.
- `OnHit` is scheduled after current damage packets as a structural baseline, not as final per-hit game-equivalent timing.
- Multi-hit, bounce RNG, per-hit trigger context, toughness, break, DoT, super-break, and queue insertion remain out of scope.
