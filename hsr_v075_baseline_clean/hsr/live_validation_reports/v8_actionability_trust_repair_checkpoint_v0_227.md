# v8 Actionability Trust Repair Checkpoint v0_227

## Scope

v0_227 fixes review blind spots instead of adding broad mechanics. It requires every `fixed_now` item to be repaired in the same checkpoint and requires every remaining `structural_only` or `blocked` item to state a concrete dependency.

## Implemented

- `LoweringLimits()` now defaults to full ability lowering with `max_ability_files=None`.
- v0_225 heal/shield sample selection now prioritizes real mainline executable effects instead of blocked examples.
- `HealHP` and `InitShield` current-scope paths are audited through real `EffectIR` plus status dynamic value bindings from modifier definitions.
- Source audit now rejects trusted mutations whose dynamic numeric value only comes from unqualified explicit/manual bindings.
- v0_227 writes `actionability_matrix_v0_227.json` and fails if any `fixed_now` item remains unrepaired.

## Current Trusted Scope

- Heal: `FormulaType is None` or `HealByBaseValue`, with fixed amount or status-bound dynamic hash.
- Shield: `FormulaType is None`, with fixed amount or status-bound dynamic hash.
- HP loss: inherited from v0_226 `LoseHPByRatio` fixed/bound `MaxHP` or `CurrentHP` ratio.

The v0_227 heal sample uses:

```json
{
  "opcode": "HealHP",
  "source_path": "Config/ConfigAbility/Avatar/Avatar_Luocha_00_Ability.json",
  "raw_id": "MAvatar_Luocha_00_Passive01_HealHP",
  "binding_source": "status_instance",
  "binding_hash": "592763048"
}
```

The v0_227 shield sample uses:

```json
{
  "opcode": "InitShield",
  "source_path": "Config/ConfigAbility/Avatar/Avatar_Gepard_00_Ability.json",
  "raw_id": "MAvatar_Gepard_00_Ultra_Shield",
  "binding_source": "status_instance",
  "binding_hash": "-295141034"
}
```

## Still Waiting

- `true_damage`: no admitted executable TBGD true-damage emission or effect source exists.
- `queue`: no admitted executable queue opcode/effect lowering exists.
- `trigger_window`: needs per-hit target context, global listener, and being-hit listener.

These are not `fixed_now` items in v0_227.

## Validation

Commands run from `hsr_v075_baseline_clean/hsr`:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_215 --output-dir /tmp/hsr_v8_regression_v0_215
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_226 --output-dir /tmp/hsr_v8_regression_v0_226
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_227 --output-dir validation_outputs_v0_227
git diff --check
```

Results:

- compileall: passed
- v0_215: `ok=true`
- v0_225: `ok=true`
- v0_226: `ok=true`
- v0_227: `ok=true`
- `git diff --check`: passed
