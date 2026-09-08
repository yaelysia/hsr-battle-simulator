# TBGD normal-combat source-family inventory

## Purpose

This is the living corpus-audit ledger for PR #8. It is intended to converge on **all TBGD source families and reachable records that materially affect ordinary Honkai: Star Rail combat** at the pinned revision, not merely a representative sample.

Pinned TBGD revision:

`14c1d18f91a8101d610e6c523447a7517de3fae1`

The governing inclusion/exclusion rules are in [`BATTLE_SCOPE.md`](BATTLE_SCOPE.md).

## Reading rule

This inventory is triage, not a filename- or ID-based authority map.

- Search/scripts may enumerate candidates, paths, IDs and references.
- A final semantic status requires manual inspection of raw records and relevant producers/consumers.
- Exact numeric ID equality across families is not identity proof. The March `100102` / `ILBattleAvatarSkill` collision below is a confirmed counterexample.
- A family may be `mixed` even when some individual records or operations are clearly battle-authoritative or presentation-only.
- `unresolved` means not yet semantically closed; it must not be treated as exclusion.
- “not encountered yet” is not negative evidence.
- Mode-specific sources currently deferred by scope remain deferred even if mechanically easy to enumerate.
- If a deferred mode references a lower-level primitive also used by ordinary combat, that shared primitive remains in scope through the ordinary-combat chain.

## Status values

- `include` — inspected family/record provides ordinary-combat semantics or a required battle relationship.
- `mixed` — battle and non-battle/presentation/progression semantics coexist; lower-level filtering is required.
- `exclude` — inspected evidence shows no ordinary-combat consequence under the current scope.
- `deferred` — intentionally postponed by the current scope contract.
- `unresolved` — candidate family exists but has not yet been semantically closed.

## Core playable-character and ability sources

| Family / path | Status | Manually inspected anchors | Current interpretation / next closure |
| --- | --- | --- | --- |
| `ExcelOutput/AvatarConfig.json` | `mixed` | March 7th Preservation identity/config references | Supports playable-character identity and joins but also carries non-combat/display metadata. Keep field-level filtering. |
| `Config/ConfigCharacter/Avatar/**` | `mixed` | `Avatar_Mar_7th_00_Config.json`; Aglaea config/ability links | Skill type, target, entry/prepare ability, DynamicValue binding and related battle wiring coexist with animation/camera/formation metadata. |
| `Config/ConfigAbility/Avatar/**` | `mixed` | March 7th and Aglaea ability files | Contains battle execution/modifiers/triggers as well as camera/animation/presentation operations. Operation-level review is mandatory. |
| `ExcelOutput/AvatarSkillConfigLD.json` | `mixed/unresolved family role` | rows contain `SkillID`, target/effect/AI-related fields and `ParamList`; exact `SkillID=100102` absent at pinned revision | This file is **not** a pure presentation false friend. It contains battle-facing skill data for some rows, but it is not the missing ordinary March `100102` source. Audit its producer/consumer population before assigning family-wide authority. |
| ordinary avatar skill numeric/value authority beyond the above | `unresolved` | March ordinary `SkillParam(Skill02,index=0..4)` consumers known | Locate the exact pinned ordinary source for March `100102`, or prove the export omits it. Do not substitute same-ID event/live rows. |
| character trace/eidolon/rank combat-value sources | `unresolved` | March shield record exposes unresolved trace/rank contributions | Identify tables and ability consumers that alter ordinary-combat skills/modifiers; exclude upgrade-cost/material-only portions. |

### Confirmed same-ID event false positive

| Family / path | Status | Manually inspected anchors | Current interpretation |
| --- | --- | --- | --- |
| `ExcelOutput/ILBattleAvatar.json` | `deferred` | `ID=1001` points to `Config/Activity/RtBattle/ConfigCharacter/Avatar/IL_Launch_00_Config.json`, with Hunt/5★ event-character metadata | Event/RtBattle family under current scope. Its use of familiar avatar IDs does not make it ordinary avatar authority. |
| `ExcelOutput/ILBattleAvatarSkill.json` | `deferred` | `ID=100102`, `ParamList=[6,0.3,6,1,6]`, `InitialCD=6`, `CoolDown=12` | The exact ID collides with ordinary March Skill02 but belongs to the parent `ILBattleAvatar` RtBattle family. These values are explicitly rejected for ordinary March evidence. |

This is retained as a methodology guardrail: mechanical `ID=100102` matching would have produced a plausible but wrong combat record without parent-family inspection.

A previously mentioned `AvatarSkillConfigLDPath.json` path has not been re-established in the pinned tree. It is not an inventory fact until existence is confirmed.

## Servants / memosprites

| Family / path | Status | Manually inspected anchors | Current interpretation / next closure |
| --- | --- | --- | --- |
| `ExcelOutput/AvatarServantConfig.json` | `mixed` | exact `ServantID=11402` row | Provides servant config/AI/skill references, HP/speed construction tokens and aggro. The `11402` row does **not** contain `AvatarID=1402`; owner relation is proven by the ordinary Aglaea `CreateServant(11402)` edge, not by an owner field in this row. |
| `Config/ConfigCharacter/Servant/**` | `mixed` | `Servant_AglaeaServant_00_Config.json` | Memosprite type, skill/target/AI/property-inherit wiring and DeathRattle skill definition are battle-relevant; audit remaining records and non-combat fields individually. |
| `Config/ConfigAbility/Servant/**` | `mixed` | `Servant_AglaeaServant_00_Ability.json` | Separate `CasterSummoner.Speed` / `Caster.Speed` reads and a death-rattle/death-event graph are confirmed. Exact speed formula, sync timing, lifecycle and scheduling remain unresolved. |
| `Config/ConfigAI/Avatar_ComplexSkilll_AutoFight_AI.json` | `unresolved` | exact path referenced by `AvatarServantConfig[11402]` and servant `DefaultAIPath` | Reference edge is confirmed; AI decision semantics still require manual inspection. |
| `Config/ConfigSummonUnit/**` | `unresolved` family-wide | `SummonUnit_Aglaea_00_Config.json` inspected | **Do not equate with battle servants.** The Aglaea sample is a scene/maze/Technique-side follow entity using maze/adventure operations and is not the Garmentmaker battle authority. Other records remain unresolved. |

For `AvatarServantConfig[11402]`, exact confirmed raw fields include:

- `Config = Config/ConfigCharacter/Servant/Servant_AglaeaServant_00_Config.json`
- `AIPath = Config/ConfigAI/Avatar_ComplexSkilll_AutoFight_AI.json`
- `SkillIDList = [1140201, 1140203, 1140205, 1140206]`
- `HPBase = #6`, `HPInherit = #5`, `HPSkill = 140204`
- `SpeedBase = 0`, `SpeedInherit = #4`, `SpeedSkill = 140204`
- `Aggro.Value = 125`

`#4/#5/#6` remain raw tokens, not decoded formulas.

## Monsters / enemy execution

| Family / path | Status | Manually inspected anchors | Current interpretation / next closure |
| --- | --- | --- | --- |
| `ExcelOutput/MonsterConfig.json` | `mixed` | `MonsterID 1002011` | Joins concrete monster ID to template, unique config and character config. Battle-supporting identity data coexist with other metadata. |
| `ExcelOutput/MonsterTemplateConfig.json` | `include` | `MonsterTemplateID 1002010` | Base HP/ATK/DEF/SPD/Stance fields are ordinary-combat stat inputs. Final scaling equation is not yet closed. |
| `ExcelOutput/MonsterUniqueConfig.json` | `mixed` | `MonsterID 1002011` plus inspected non-unit-ratio rows | Provides HP/ATK/DEF/SPD/Stance modify ratios, HardLevelGroup and skill/ability relationships; exact final-stat composition remains unresolved. |
| `Config/ConfigCharacter/Monster/**` | `mixed` | `Monster_W1_Humanoid_01_Config.json` | Enemy skills, target/entry abilities and AI references are battle wiring; presentation/runtime-adjacent data may coexist. |
| `Config/ConfigAbility/Monster/**` | `mixed` | `Monster_W1_Humanoid_01_Ability.json` | Battle execution such as damage operations coexists with other ability operations; operation-level review required. |
| ordinary-monster AI under `Config/ConfigAI/**` | `unresolved` | `ComplexSkillAI` references observed from inspected monster/servant configs | Need close decision inputs, priority/weights/targeting and any random authority used by normal enemies. |

## Encounter, stage and difficulty scaling

| Family / path | Status | Manually inspected anchors | Current interpretation / next closure |
| --- | --- | --- | --- |
| `ExcelOutput/StageConfig.json` | `mixed` | Stage `103201` -> wave IDs, `Level = 29`, `HardLevelGroup = 1` | Ordinary encounter/wave construction and scaling keys are battle-relevant; stage records also carry non-battle context. |
| `ExcelOutput/ILHardLevelGroup.json` | `include` for the confirmed lookup edge | `(HardLevelGroup=1, Level=29)` | Provides the observed HP/ATK/DEF ratio row used by the stage-level investigation. The `IL` prefix must **not** be mechanically equated with the deferred `ILBattleAvatar*` family; final consumer/formula tracing remains required. |
| stage/wave/monster-group subordinate tables | `unresolved` | Stage `103201 -> [1022020, 1023010, 1022020]` chain previously inspected | Inventory each ordinary encounter edge through concrete enemy spawning/wave transition semantics. |
| `StageAbilityConfig` / stage battle abilities | `mixed` | representative `StageAbility_301001` previously recorded | Stage/global effects can alter combat, but family must be separated from presentation/mode-specific records and deferred-mode variants. |
| speed/stance difficulty scaling sources | `unresolved` | Monster template/unique and hard-level records expose the gap | Locate raw source/formula for final SPD and Stance, then prove precedence/composition including Stage vs MonsterUnique `HardLevelGroup`. |

## Global battle execution candidates

These families are high priority because a corpus-complete audit cannot be derived only from character/enemy forward references; global producers may affect ordinary battles without being reached from a representative actor.

| Family / path | Status | Current closure requirement |
| --- | --- | --- |
| `Config/ConfigGlobalModifier/**` | `unresolved` | Manually identify ordinary-combat global modifier producers/consumers and separate mode/presentation variants. |
| `Config/ConfigBattleEvent/**` | `unresolved` | Determine which events change battle state, spawning, transitions, victory/defeat or global effects in ordinary combat. |
| `Config/ConfigCommonSkillPool/**` | `unresolved` | Determine shared skill dispatch used by ordinary actors and its relationship to character/monster ability graphs. |
| `Config/ConfigGlobalTaskListTemplate/**` | `unresolved` | Inspect whether task lists encode battle-state callbacks or unrelated scripting/tooling. |
| shared battle modifier/opcode families inside ability configs | `unresolved` | Build semantic inventory from manually traced consumers: damage, heal, shield, modifier add/remove, control, break/toughness, resource, timeline, spawn/death and targeting. |

## Techniques / maze-to-battle boundary

| Family / path | Status | Current interpretation / next closure |
| --- | --- | --- |
| `Config/ConfigMazeBuff/**` | `unresolved` | Maze data is not automatically battle data, but some normal Techniques can establish battle-start effects. Include only proven battle-entry consequences. |
| `Config/ConfigAdventureAbility/**` | `unresolved` | Often scene/Technique-side; trace only paths that alter ordinary battle initialization or actors. |
| `Config/ConfigAdventureModifier/**` | `unresolved` | Same boundary rule: scene-only behavior excluded, ordinary-battle initialization consequence included. |
| `Config/ConfigSummonUnit/**` | `unresolved` | Aglaea sample is a concrete maze-side false friend. Do not promote family by name; follow battle-entry consequence edges only. |

## Equipment and ordinary build-derived combat effects

| Family / path | Status | Manually inspected anchors | Current interpretation / next closure |
| --- | --- | --- | --- |
| Light Cone / equipment identity and effect tables | `unresolved` family-wide | equipment `21003` reference chain already recorded | Only battle-effect identity, equipped stat/effect contribution and combat ability/modifier wiring are in scope; acquisition/EXP/promotion/material economics are excluded. Need close a nontrivial effect chain and augment/rank semantics. |
| relic / planar ornament base-stat and set-effect sources | `unresolved` | none yet promoted | Need locate normal equipment stat contributions and set-effect ability/modifier producers; exclude inventory UI, salvage, synthesis, reward and progression-only data. |
| equipment augment/superimposition/rank families | `unresolved` | equipment `21003` exposes remaining semantics | Determine which rank data changes actual battle modifiers and how the active ability consumes it. |

## Presentation-oriented candidates requiring explicit negative evidence

These are **not blanket-excluded merely by name**. They remain unresolved until representative/manual inspection is sufficient to establish that no logical combat consequence is encoded, or until individual mixed operations are separated.

| Family / path | Status | Audit note |
| --- | --- | --- |
| `Config/ConfigBattlePerform/**` | `unresolved` | Likely performance/presentation-heavy; verify no logical action/timing/state authority before exclusion. |
| `BattleMode/BattlePerformConfig/**` | `unresolved` | Same rule. Presentation timing is not automatically logical battle timing. |
| `CameraTemplate/**` | `unresolved` | Expected presentation; record inspected negative evidence before family-level exclusion. |
| `BattleMode/CameraState/**` | `unresolved` | Expected presentation; inspect representative data and references. |
| `BattleMode/CameraBlend/**` | `unresolved` | Expected presentation; inspect representative data and references. |
| `BattleMode/BattleBGMConfig.json` | `unresolved` | Expected audio/presentation; preserve negative evidence rather than assuming. |
| UI/audio/localization/display families | `unresolved` family-wide | Exclude after semantic inspection where the family could plausibly be referenced from battle graphs; pure text/icon data need not be exhaustively interpreted field-by-field once role is proven. |

## Explicitly deferred special-mode families

The current PR scope intentionally does **not** require exhaustive archaeology of mode-specific mechanics for:

- Simulated Universe;
- Divergent Universe;
- Currency Wars;
- event-specific battle modes and temporary event battle rules, including the inspected `Config/Activity/RtBattle/**` / `ILBattleAvatar*` character family.

Relevant source families/records should be marked `deferred` when encountered rather than expanded recursively. Blessings, curios, equations, scepters/components, mode currencies, mode-only actors, mode-only stage rules and event-only combat modifiers therefore do not block completion of the current normal-combat pass.

Exception: a shared primitive that is also reached by ordinary combat remains in scope through its ordinary-combat producer/consumer chain. A deferred mode's use of that primitive does not make the primitive itself deferred.

## Reverse-scan obligations

Forward traversal from playable characters, enemies and stages is insufficient for completeness. Before this inventory can be considered closed, archaeology must also manually audit candidate global producers for at least:

1. battle initialization and actor construction;
2. legal actions and external/internal target selection;
3. action value / turn ordering / extra or advanced actions;
4. HP, damage, healing and shielding;
5. energy, skill points and actor-specific resources;
6. weakness, toughness, break and recovery;
7. modifier/status/control application, refresh, stacking and expiration;
8. follow-up/counter/trigger/callback ordering;
9. summon/servant creation, ownership, actions and cleanup;
10. enemy AI and random-choice authority;
11. ordinary encounter waves, reinforcements, phases and stage/global abilities;
12. death, defeat, victory, battle end and other termination transitions;
13. ordinary Light Cone/relic/set combat effects and their rank/level-derived active values.

## Current checkpoint gaps

Highest-value unresolved edges at this checkpoint:

1. March 7th Preservation ordinary `SkillID 100102` pinned numeric `SkillParam` source (or proof that the pinned export omits it), plus shield arithmetic/refresh semantics. `ILBattleAvatarSkill[100102]` has been rejected as an event false positive.
2. Final monster-stat equation: Stage `Level + HardLevelGroup` lookup, MonsterTemplate base values, MonsterUnique modify ratios, precedence and final HP/ATK/DEF/SPD/Stance.
3. Aglaea servant `#4/#5/#6` formula/value sources, synchronization timing, action ownership and cleanup ordering.
4. A complex ordinary equipment effect chain including augment/superimposition semantics.
5. Family-wide AI/global-modifier/battle-event reverse scan needed to detect ordinary-combat producers not reached from current samples.
