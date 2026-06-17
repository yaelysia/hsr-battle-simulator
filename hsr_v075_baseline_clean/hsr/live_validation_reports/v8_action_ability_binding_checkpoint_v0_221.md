# v8 Action Ability Binding Checkpoint v0_221

## Scope

- Added `ActionAbilityBindingIR` and `AbilityPhaseIR` to Canonical IR.
- Lowered mainline avatar action bindings from:
  `ActionDefinitionIR -> AvatarConfig.JsonPath -> ConfigCharacter SkillList/SkillAbilityList/EntryAbility -> ConfigAbility AbilityList`.
- Updated `ActionEventIR` to carry `binding_id`, `phase_ids`, `source_mode`, and `event_source_status`.
- Updated `RuleBook` and `CombatExecutor` so runtime consumes binding/phase IR only.
- Added settlement and coverage records for `action_ability_binding` and `ability_phase_graph`.
- Added static guard against runtime core/systems reading raw `ConfigAbility`, `ConfigCharacter`, or `AbilityList` schema.

## v0_221 Counts

- Discovery files: 8683
- Action definitions: 6949
- Action ability bindings: 6949
- Executable mainline bindings: 5944
- Blocked bindings: 1005
- Ability phases: 5944
- Action events: 6949
- Hit profiles: 5132

Binding blocked reason counts:

- `missing_mainline_avatar_config`: 673
- `non_avatar_ability_binding_not_executable`: 165
- `missing_skill_trigger_key`: 103
- `missing_entry_ability_or_skill_ability_list`: 45
- `missing_ability_phase_in_ability_file`: 19

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
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_221 --output-dir validation_outputs_v0_221
```

Result: all commands passed, including v0_221 `ok=true`.

v0_221 validation confirmed:

- At least one real mainline avatar action binds through `ConfigCharacter` and `ConfigAbility` phase graph by structured predicate.
- Executor transitions include `action_ability_binding` and `ability_phase_graph` settlement records.
- No executable binding / blocked binding action produces process-only transition and unchanged snapshot.
- v0_220 HitProfileIR/direct damage/preflight/multi-target structural-only behavior did not regress.
- Static checks, snapshot completeness, transition contract, settlement traceability, and replay all passed.

## Remaining Risks

- `AbilityPhaseIR` currently lowers phase structure and opcode summaries only; Ability task semantics are not executed.
- Event windows are still projected from the bound phase graph and existing action taxonomy; this is cleaner than v0_220, but not yet a full TBGD action event VM.
- Enemy action binding remains discovered/blocked unless stable config paths are available; no filename guessing was added.
- Multi-hit, bounce RNG, toughness, break, DoT, super-break, per-hit trigger context, and queue systems remain out of scope for this checkpoint.
