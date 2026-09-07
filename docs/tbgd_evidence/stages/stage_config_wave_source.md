# `StageConfig` wave/source authority evidence

## Evidence status

- TBGD revision: `14c1d18f91a8101d610e6c523447a7517de3fae1`
- Maturity: `manually_confirmed`
- Scope: stage identity, wave roster/order, declared wave count, stage ability references, level/scaling inputs
- Battle-scope verdict: `mixed`
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
- selected battle-control flags where they actually alter battle execution.

The same row also contains fields related to UI, loading/level graphs, release state, or client restrictions that are not automatically battle-runtime authorities. Per the battle-scope contract, those fields require consumer tracing and are excluded when they only affect presentation/client flow.

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

## Hard-level scaling lookup edge now located

The pinned TBGD revision contains `ExcelOutput/ILHardLevelGroup.json`. Rows are keyed by the pair:

```text
(HardLevelGroup, Level)
```

and provide at least:

- `AttackRatio.Value`;
- `DefenceRatio.Value`;
- `HPRatio.Value`.

For example, the raw row `(HardLevelGroup=1, Level=29)` exists and supplies concrete ATK/DEF/HP hard-level ratios. Stage `103201` independently supplies exactly the same key values (`HardLevelGroup=1`, `Level=29`). This closes the previously missing **source-table lookup edge** from stage-like level/group inputs to a hard-level ratio row.

This does **not** yet prove the complete final-stat equation or precedence rules. In particular, archaeology must still determine which owner supplies the effective hard-level group when stage-, monster- or mode-level sources coexist, and how the resulting ratios compose with base monster stats and per-monster modifiers.

## Per-monster scaling inputs also located

The pinned `ExcelOutput/MonsterUniqueConfig.json` contains battle-facing fields including:

- `MonsterID` / `MonsterTemplateID`;
- `HardLevelGroup`;
- `AttackModifyRatio`;
- `DefenceModifyRatio`;
- `HPModifyRatio`;
- `SpeedModifyRatio`;
- `StanceModifyRatio`;
- `SkillList`;
- `AbilityNameList` and override-related fields.

Representative rows demonstrate that the modify ratios are not universally `1`; monster variants can carry independent ATK/HP and other modifiers. These are therefore separate source inputs that must not be collapsed into the hard-level table.

At file level `MonsterUniqueConfig.json` should still be treated conservatively as mixed/supporting-plus-authoritative because identity/name/introduction metadata can coexist with battle fields. The ratio/skill/ability fields above are battle-relevant by direct runtime consequence.

## Current scaling evidence chain

The source evidence now supports this partial chain:

```text
stage / encounter inputs
  ├─ Level
  └─ HardLevelGroup
        ↓ keyable edge confirmed
ILHardLevelGroup[(HardLevelGroup, Level)]
  ├─ AttackRatio
  ├─ DefenceRatio
  └─ HPRatio

monster identity
        ↓
MonsterUniqueConfig[MonsterID]
  ├─ AttackModifyRatio
  ├─ DefenceModifyRatio
  ├─ HPModifyRatio
  ├─ SpeedModifyRatio
  └─ StanceModifyRatio

base monster stat source + effective-group precedence + composition operators
        ↓
final encounter HP / ATK / DEF / SPD / Stance
        ↑
        still unresolved
```

The important distinction is now explicit: **the hard-level ratio table and per-monster modify ratios are proven source inputs; their final composition is not yet proven.**

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
3. **Stage level/group are scaling inputs, not final monster stats.** `ILHardLevelGroup.json` closes a concrete `(HardLevelGroup, Level) -> ATK/DEF/HP ratio` lookup edge, but the final composition equation remains unresolved.
4. **Per-monster modify ratios are independent source inputs.** `MonsterUniqueConfig.json` supplies ATK/DEF/HP/SPD/Stance modifiers and cannot be replaced by the hard-level ratio table.
5. **Stage abilities are first-class references.** A stage may have battle behavior outside individual monster Ability graphs.

## False friends / hazards

- `LevelGraphPath` is not automatically the combat-mechanic authority; it may be a broader level/client graph.
- release/UI/name fields do not prove runtime battle semantics.
- a single-wave representative cannot establish all multi-wave transition semantics.
- the existence of matching `(HardLevelGroup, Level)` keys does not by itself prove runtime precedence or the arithmetic operator used to produce final stats.
- `MonsterUniqueConfig.HardLevelGroup` introduces a second potential group owner; do not assume StageConfig always wins without tracing the consumer.
- speed/stance modify ratios do not prove the source of the corresponding base/hard-level values.
- external encounter websites may reorder or group enemies for presentation and therefore cannot replace raw slot/wave ordering.

## Unresolved follow-ups

1. Resolve `StageAbilityConfig` names such as `StageAbility_301001` to the actual ConfigAbility/source graph.
2. Locate the base monster HP/ATK/DEF/SPD/Stance sources and prove the exact composition/operator order with `ILHardLevelGroup` and `MonsterUniqueConfig` ratios.
3. Prove effective `HardLevelGroup` ownership/precedence across stage, monster and special-mode overrides.
4. Close SPD/Stance hard-level scaling, if separate tables/formulas exist.
5. Audit a real multi-wave stage, including wave-transition events and spawn timing.
6. Determine whether monster slot position has mechanics beyond deterministic ordering/placement.
7. Identify environment/global battle modifiers that are sourced outside `StageConfig` but referenced by stage/mode data.
8. Separate normal stage construction from special-mode schemas instead of forcing every mode through the same assumptions.
