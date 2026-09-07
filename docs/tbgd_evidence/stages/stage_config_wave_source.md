# `StageConfig` wave/source authority evidence

## Evidence status

- TBGD revision: `14c1d18f91a8101d610e6c523447a7517de3fae1`
- Maturity: `manually_confirmed`
- Scope: stage identity, wave roster/order, declared wave count, stage ability references, level inputs
- Runtime production code changed: no

## Authority classification

`ExcelOutput/StageConfig.json` is **`mixed_requires_filter`** at file/row level.

Confirmed battle-relevant fields include:

- `StageID`;
- `StageType` where mode semantics affect battle construction;
- `Level`;
- `HardLevelGroup`;
- `MonsterList` and its nested monster slot order;
- `StageConfigData` entries used to declare wave/battle properties;
- `StageAbilityConfig`;
- selected battle-control flags where the simulator intentionally models them.

The same row also contains fields related to UI, loading/level graphs, release state, or client restrictions that are not automatically battle-runtime authorities.

## Representative raw stage: 103201

At the pinned revision, Stage `103201` contains:

- `StageType = Mainline`;
- `HardLevelGroup = 1`;
- `Level = 29`;
- `LevelGraphPath = Config/Level/StageCommonTemplate.json`;
- `StageAbilityConfig = []`;
- `StageConfigData` declaring one wave and elite-battle state;
- one `MonsterList` wave with ordered slots:
  1. `1022020`
  2. `1023010`
  3. `1022020`
- battle/client restrictions such as auto-battle/exit flags.

## Representative stage with stage ability: 301001

The inspected `StageConfig` also contains Stage `301001`, where:

- `Level = 40`;
- `StageAbilityConfig = ["StageAbility_301001"]`;
- the wave roster contains `1022020`, `1023010`, `8003020`, `1022020`.

This is direct evidence that stage-level mechanics are not reducible to monster rosters alone. `StageAbilityConfig` is a separate reference edge that must be resolved before a stage is considered fully lowered.

## Current project lowering contract

The existing v8 lowerer already treats `StageConfig.json` as the raw source for `WaveDefinitionIR`-style data. It consumes the Stage ID, MonsterList, declared wave information, Level/HardLevelGroup and stage ability references, then records source evidence for the materialized wave entries.

The archaeology catalog should therefore preserve at least these independent concepts:

```text
Stage
  ├─ identity/mode
  ├─ level/scaling inputs
  ├─ ordered wave list
  │    └─ ordered monster slots
  ├─ stage-level ability references
  └─ environment/battle modifiers
```

Do not collapse this into a flat `stage -> monsters` mapping.

## Confirmed semantic conclusions

1. **Wave membership and slot order are source data.** They should not be reconstructed from text or encounter databases when TBGD supplies the roster.
2. **Declared wave count and the concrete `MonsterList` must be checked against one another.** The lowerer currently has fallback behavior; archaeology should record mismatches instead of silently normalizing them.
3. **Stage level is an input, not the final monster stat.** The exact Level/HardLevelGroup -> encounter stat formula/table chain is still unresolved in this record.
4. **Stage abilities are first-class references.** A stage may have battle behavior outside individual monster Ability graphs.

## False friends / hazards

- `LevelGraphPath` is not automatically the combat-mechanic authority; it may be a broader level/client graph.
- release/UI/name fields do not prove runtime battle semantics.
- a single-wave representative cannot establish all multi-wave transition semantics.
- stage `Level` must not be applied to base monster stats with an assumed community formula; the source scaling chain must be located.
- external encounter websites may reorder or group enemies for presentation and therefore cannot replace raw slot/wave ordering.

## Unresolved follow-ups

1. Resolve `StageAbilityConfig` names such as `StageAbility_301001` to the actual ConfigAbility/source graph.
2. Close `Level` + `HardLevelGroup` -> final monster HP/ATK/DEF/SPD/Stance scaling.
3. Audit a real multi-wave stage, including wave-transition events and spawn timing.
4. Determine whether monster slot position has mechanics beyond deterministic ordering/placement.
5. Identify environment/global battle modifiers that are sourced outside `StageConfig` but referenced by stage/mode data.
6. Separate normal stage construction from special-mode schemas instead of forcing every mode through the same assumptions.
