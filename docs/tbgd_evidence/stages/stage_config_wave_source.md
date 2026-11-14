# `StageConfig` wave/source authority evidence

## Evidence status

- TBGD revision: `14c1d18f91a8101d610e6c523447a7517de3fae1`
- Maturity: `manually_confirmed`
- Scope: ordinary stage identity, wave roster/order, StageAbility references, level/difficulty inputs, and the current R6 handoff boundary
- Battle-scope verdict: `mixed`
- Runtime production code changed: no
- Runtime validation: not performed / not claimed

## Superseding correction

This record previously treated `ExcelOutput/ILHardLevelGroup.json` as ordinary encounter scaling authority and described `MonsterUniqueConfig.json` too broadly as a universal per-monster scaling layer. Later W14/W16 archaeology disproved both assumptions.

The corrected ordinary boundary is:

- **ordinary difficulty input family:** `ExcelOutput/HardLevelGroup.json`;
- **false friend for ordinary W14:** `ExcelOutput/ILHardLevelGroup.json` / `ILBattleMonster` for the inspected RtBattle/IL collision;
- **conditional family:** `ExcelOutput/MonsterUniqueConfig.json`; include a row only when the selected ordinary identity/reference chain actually reaches it;
- **final configured-spawn arithmetic/precedence:** still not exported by the pinned TBGD release-data corpus.

The corrected monster-side details are recorded in [`../monsters/monster_1002011_reference_chain.md`](../monsters/monster_1002011_reference_chain.md) and in the core `PINNED_SOURCE_INDEX.md` / `SOURCE_FAMILY_INVENTORY.md`.

## Authority classification

`ExcelOutput/StageConfig.json` is **`mixed_requires_filter`** at file/row level.

Confirmed battle-relevant fields include:

- `StageID`;
- `StageType` where mode semantics affect battle construction;
- `Level`;
- `HardLevelGroup`;
- `MonsterList` and nested wave/slot order;
- `StageConfigData` entries that declare battle/wave properties;
- `StageAbilityConfig`;
- selected battle-control flags only when a runtime consequence is traced.

Display/release/loading/client fields are not automatically battle authority. `LevelGraphPath` is a navigation edge, not proof that every task in the referenced graph is battle-semantic.

## Representative ordinary stage: 103201

At the pinned revision, Stage `103201` contains:

- `StageType = Mainline`;
- `HardLevelGroup = 1`;
- `Level = 29`;
- `LevelGraphPath = Config/Level/StageCommonTemplate.json`;
- `StageAbilityConfig = []`;
- `StageConfigData` declaring one wave and elite-battle state;
- one ordered `MonsterList` wave:
  1. `1022020`
  2. `1023010`
  3. `1022020`.

This remains a useful simple stage anchor for stage -> wave -> spawn identity without StageAbility noise.

## Representative stage with StageAbility: 301001

The inspected Stage `301001` contains:

- `Level = 40`;
- `StageAbilityConfig = ["StageAbility_301001"]`;
- an ordered roster containing `1022020`, `1023010`, `8003020`, `1022020`.

This proves stage mechanics are not reducible to a flat monster list. `StageAbilityConfig` is an independent source edge that must be resolved and classified at operation level.

Existing W14 evidence also shows Stage-level Elite context and monster-side Elite inputs can coexist. Coexistence is proven; replace/multiply/order precedence is not.

## Correct ordinary HardLevel input family

The ordinary `(HardLevelGroup, Level)` table at the pin is:

`ExcelOutput/HardLevelGroup.json`

Exact pinned blob recorded in the source index:

`9ee36b767b010d2c85aa7169e86e9f0a4220a935`

Rows expose five typed input families:

- `AttackRatio`;
- `DefenceRatio`;
- `HPRatio`;
- `SpeedRatio`;
- `StanceRatio`.

Representative ordinary row `(HardLevelGroup=1, Level=29)`:

| Input | Value |
| --- | ---: |
| AttackRatio | `5.19238` |
| DefenceRatio | `2.333333` |
| HPRatio | `5.020885` |
| SpeedRatio | `1` |
| StanceRatio | `1` |

Stage `103201` supplies the same `(1,29)` key pair. This establishes a source-facing join candidate for the ordinary encounter context. It does **not** prove that StageConfig is always the effective owner when another admitted source supplies a level/group override.

`SpeedRatio` is not a dummy field: group 1 changes from `1` at level 65 to `1.1` at level 66. The field name `Ratio` still does not prove the native arithmetic operator.

Pinned `Config/ConfigAbility/Level/Level_FarmStage_Ability.json` independently contains `SetDynamicValueByHardLevelProperty(Property=HPRatio)`, proving HardLevel properties are typed engine-readable battle inputs. That operation does not expose the generic enemy spawn-stat constructor.

## Monster inputs must remain layered

Current ordinary evidence supports this source-facing topology:

```text
StageConfig
  -> StageID / Level / HardLevelGroup / Elite context
  -> ordered wave / slot / MonsterID references
  -> StageAbility references

wave MonsterID
  -> MonsterConfig concrete row
  -> MonsterTemplateConfig base HP / ATK / DEF / SPD / Stance
  -> concrete modification / resistance / skill / AI inputs where present

(HardLevelGroup, Level)
  -> HardLevelGroup five-stat ratio inputs

explicitly participating conditional families
  -> MonsterUnique / phase / StageAbility / other overlays only when reached

source-bearing lowering / birth-template construction
  -> UnitBirthTemplateIR
  -> UnitSpawnRequest
  -> enemy UnitState
```

The following are **not** source-closed by this topology:

- the generic final ATK/DEF/HP/SPD/Stance arithmetic;
- placement of flat `*ModifyValue` terms;
- clamp/rounding rules;
- effective Stage-vs-Monster HardLevelGroup/Level precedence;
- Stage-vs-Monster Elite composition/order;
- generic phase-override application/default order.

Those remain explicit engine/convention boundaries until a new authoritative source or an actual local-kernel mismatch reopens them.

## `MonsterUniqueConfig` is conditional, not universal

The family exists and can carry battle-facing fields, but representative ordinary IDs audited in W14 — including `1002011`, `1022020`, and `1023010` — did not establish a matching participating row.

Therefore:

- family existence does not create an automatic override layer;
- a same-looking or same-ID row in another family is not authority by itself;
- R6 must prove participation for the chosen encounter before using a `MonsterUniqueConfig` row in the causal chain.

## Current local-kernel alignment target for R6

At PR head `6c1275529d4e63cb57c50c30bb73d00d65c93715`, the current v8 kernel already has formal encounter consumers:

- `systems/wave.py::WaveSystem` consumes `WaveDefinitionIR` / `WaveMonsterEntryIR`, guards pending work, starts waves, detects clears, plans next-wave spawns and emits victory/defeat/completion events;
- `systems/unit_spawn.py::UnitSpawnSystem` consumes executable `UnitBirthTemplateIR` plus a typed `UnitSpawnRequest`, verifies stage/wave/position/source identity and fails closed on source/template mismatch;
- `systems/phase_machine.py` has a dedicated `WAVE_TRANSITION` phase and gates wave/termination events to that phase;
- `systems/battle_state_transition.py` consumes typed shared state-transition rules and must not be conflated with monster-internal phase replacement or wave spawn.

These code facts are **C — local implementation present** only. R6 must trace the exact pinned producers/lowering edges before claiming D source alignment or E runtime verification.

## Confirmed semantic conclusions

1. **Wave membership and slot order are source data.** Do not reconstruct them from text or external encounter sites when TBGD supplies them.
2. **Declared wave structure and concrete roster are independent facts.** Mismatches must remain visible rather than silently normalized.
3. **Stage level/group are encounter inputs, not final enemy properties.** Ordinary difficulty ratios come from `HardLevelGroup.json`, not the inspected IL/RtBattle family.
4. **Template bases are not final stats.** Monster concrete/template/difficulty/Elite/phase/StageAbility layers must remain distinguishable.
5. **`MonsterUniqueConfig` is conditional.** It is not a universal override merely because the family exists.
6. **StageAbility is first-class encounter authority when referenced.** Its operations still require battle-vs-presentation filtering.
7. **Monster phase transition is not wave respawn by default.** Existing common phase evidence operates on the same entity and must remain separate from `WaveMonster`/spawn semantics.

## False friends / hazards

- `ILHardLevelGroup` / `ILBattleMonster` are wrong-family examples for ordinary W14 at this pin.
- `LevelGraphPath` is not automatically battle-mechanic authority.
- a `Ratio` field name is not an arithmetic implementation.
- `MonsterUniqueConfig` family membership is not participation proof.
- a typed HardLevel read is not the final spawn formula.
- StageAbility live mutation is not static spawn scaling.
- phase transition is not respawn unless an explicit spawn/removal chain proves it.
- multiple Elite inputs prove capacity/coexistence, not precedence.
- external encounter websites may reorder or regroup enemies for presentation and cannot replace raw wave/slot ordering.

## R6 continuation targets

R6 should now close one bounded encounter slice by source-aligning the pinned stage facts to the existing kernel rather than searching blindly for another generic formula:

1. select an ordinary stage and close `StageConfig -> WaveDefinitionIR / WaveMonsterEntryIR` identity, order and source evidence;
2. trace at least one selected wave enemy through concrete/template/difficulty inputs into the executable `UnitBirthTemplateIR` used by `UnitSpawnSystem`;
3. verify how StageAbility pre/post-spawn hooks participate for a stage that actually references one;
4. close one wave-clear -> next-wave or terminal victory/defeat path against `WaveSystem`;
5. keep same-entity monster phase/reinforcement semantics distinct and add a second anchor if the chosen stage does not exercise them;
6. record an A/B/C/D/E alignment matrix and preserve every remaining convention/export/validation gap.

See the current core overlay `POST_R5_RESEARCH_COMPACTION_2026-09-11.md` for the full card and stop conditions.
