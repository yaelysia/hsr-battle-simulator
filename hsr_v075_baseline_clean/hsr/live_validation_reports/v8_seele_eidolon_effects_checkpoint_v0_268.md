# v8 v0_268 - Seele Eidolon Effects Checkpoint

## Result

`ok=true`

This checkpoint fixes the Seele eidolon example after the Rank 4 semantic review.

## What Changed

- `ModifySPNew` is now treated as actor energy change, not global skill point change.
- Enhanced and base modifier definitions with the same modifier name are preserved as separate Canonical IR entities.
- `StatusSystem` selects the modifier definition matching the `AddModifier` source path, so enhanced Seele startup modifiers no longer borrow base Seele callback/source data.
- Seele eidolon startup RankAbility effects are applied through the existing `AddModifier` status path during scenario state build.
- E3/E5 skill-level increases are exposed as generic character-card flags and consumed by `CombatExecutor` as effective action level metadata.
- Seele Rank 4 now validates as: kill event -> enhanced Rank 4 status callback -> `ModifySPNew` -> actor energy `+15`, with skill points unchanged.

## What Is Still Not Executed

- Rank 1 damage-before-hit modification remains blocked because `ModifyDamageData` / `OnBeforeHitAll` damage rewrite admission is not implemented yet.
- Rank 6 has source and startup traces, but downstream behavior still depends on later admission for its advanced callbacks and damage-data hooks.
- Eidolon effects are not hardcoded into core runtime. They enter through character-card RankAbility/status/effect slots.

## Validation

Commands run from `hsr_v075_baseline_clean/hsr`:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_215 --output-dir /tmp/hsr_v8_regression_v0_215
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_249 --output-dir /tmp/hsr_v8_regression_v0_249
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_265 --output-dir /tmp/hsr_v8_regression_v0_265
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_266 --output-dir /tmp/hsr_v8_regression_v0_266
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_267 --output-dir /tmp/hsr_v8_regression_v0_267
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_268 --output-dir /tmp/hsr_v8_v0_268
git diff --check
```

All passed.

## Current Progress

The Seele card now has a concrete eidolon example beyond switch metadata: prefix activation, skill-level rank effects, startup RankAbility statuses, and Rank 4 kill energy gain are wired through generic v8 systems.

The remaining eidolon work is mostly damage-rewrite admission and Rank 6 callback behavior, not the eidolon switch/lifecycle contract itself.
