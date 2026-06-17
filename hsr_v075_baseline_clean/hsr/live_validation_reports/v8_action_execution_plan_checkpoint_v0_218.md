# v8 Action Execution Plan Checkpoint v0_218

## Scope

- Added `ActionExecutionPlan` as the executor-facing action plan derived from `ActionDefinitionIR`.
- The plan now records `event_steps`, `target_plan`, `hit_plan`, `damage_plan`, `source_trace`, and `derived_reason`.
- `CombatExecutor.execute()` now emits an `action_execution_plan` settlement record for every action transition.
- Target resolution now uses `TargetPolicy.target_mode` and structured target groups:
  - `single`: primary target only.
  - `aoe`: all alive enemies.
  - `blast`: primary target plus adjacent alive enemies by position.
  - `bounce`: blocked with `bounce_not_executable`; no fake random bounce is executed.
  - `unknown`: blocked with `unknown_target_mode_not_executable`.
- Damage packet creation now iterates over `ActionExecutionPlan.damage_plan` instead of only using the first requested target.
- Direct damage settlement payload now includes packet metadata with `hit_index`, `target_group`, `multiplier_source`, and `multi_hit_not_implemented=true`.

## Coverage

From `validation_outputs_v0_218/canonical_ir_summary_v0_218.json`:

- `single`: `2071`
- `aoe`: `1191`
- `blast`: `825`
- `bounce`: `220`
- `self_or_team`: `1003`
- `unknown`: `1639`

Validation samples are selected by structural predicates over `ActionDefinitionIR`: target mode, damage kind, damage formula family, and parameter availability. They are not selected by role name, file name, fixed action id, fixed hash, or fixed formula result.

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
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_218 --output-dir validation_outputs_v0_218
```

Result: all validations returned `ok=True`.

v0_218 checks:

- Every executor transition includes `action_execution_plan` in settlement and coverage.
- `single`, `aoe`, and `blast` target plans are generated from real TBGD-lowered action definitions.
- `aoe` and `blast` produce multiple damage records and HP mutations with traceable packet metadata.
- `bounce` and `unknown` do not execute fake target or damage logic; both keep explicit blocked reasons.
- Snapshot completeness, transition contract, settlement traceability, replay, static checks, v0_217 condition checks, v0_216 DynamicValueStore checks, and v0_209 direct/true-damage/HP-loss semantics remain passing.

## Remaining Risks

- `ActionExecutionPlan` is still derived from `ActionDefinitionIR`; it is not yet a real TBGD action/event IR.
- `ActionEventPlan` remains a conservative derived model and must not be treated as game-equivalent event sequencing.
- `blast` adjacency currently depends on runtime unit `position` flags. Missing positions produce no adjacent targets rather than guessing.
- `bounce` random targeting is blocked; no bounce RNG or per-hit target sequence is implemented yet.
- Only single-hit `ParamList[0]` damage planning is implemented. Multi-hit, split multipliers, toughness damage, break, DoT, and super-break remain future work.
