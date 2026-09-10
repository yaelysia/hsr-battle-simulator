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
- Exact numeric ID equality across families is not identity proof.
- A family may be `mixed` even when some records or operations are clearly battle-authoritative or presentation-only.
- `unresolved` means not yet semantically closed; it must not be treated as exclusion.
- A missing executable definition can be an `export_gap` when an ordinary pinned consumer/key proves the mechanism exists.
- An exported raw constant/opcode can be `engine_consumer_unavailable` when the generic GameCore implementation needed to interpret it is outside the release-data dump.
- Mode-specific sources currently deferred by scope remain deferred, but a shared primitive independently reached by ordinary combat stays in scope.

## Status values

- `include` — inspected source/record provides ordinary-combat semantics or a required battle relationship.
- `mixed` — battle and non-battle/presentation/progression semantics coexist; lower-level filtering is required.
- `exclude` — inspected evidence shows no ordinary-combat consequence under the current scope.
- `deferred` — genuine battle authority intentionally postponed with its special mode/event owner.
- `unresolved` — candidate family/record has not yet been semantically closed.
- `export_gap` — ordinary consumer/identity is present but a required executable definition/loader is absent from the pinned corpus.
- `engine_consumer_unavailable` — raw data-facing constants/opcodes are present but their generic engine implementation is not exported.

## Core playable-character and ability sources

| Family / path | Status | Manually inspected anchors | Current interpretation / next closure |
| --- | --- | --- | --- |
| `ExcelOutput/AvatarConfig.json` | `mixed` | March, Sampo, Natasha, Gepard, YaoGuang and other ordinary identity/config references | Playable identity and joins coexist with display/non-combat metadata; filter fields. |
| `ExcelOutput/AvatarSkillConfig.json` | `include` / mixed | exact pinned blob `a5416ced...`; March `100102`; Aglaea construction `140204`; Dan Heng cross-check | Ordinary per-level `SkillParam` producer. Earlier “100102/140204 absent” claim was a large-file/search false negative and is superseded. |
| `ExcelOutput/AvatarSkillConfigLD.json` | `mixed` | battle-facing rows inspected; no longer needed for March producer closure | Contains battle-facing skill data for some rows but is not ordinary March `100102` authority. Audit only when a chain points here. |
| `ExcelOutput/AvatarSkillTreeConfig.json` | `mixed/include` | March PointB2 plus concrete Gepard/Welt/Sampo/Natasha table -> ability -> shared-modifier chains | The pinned table is populated and can be ordinary battle authority. What may remain unexported is generic GameCore ability attachment/loading, not table existence/population. Do not reintroduce empty/missing claims. |
| `ExcelOutput/AvatarRankConfig.json` | `mixed/include` | March Rank02/Rank06; Anaxa Rank01 | Rank parameter arrays and rank-ability joins can be ordinary battle authority; acquisition/progression neighbors remain out of scope. |
| `Config/ConfigCharacter/Avatar/**` | `mixed` | March, Dan Heng, Aglaea, Asta, Silver Wolf, etc. | Skill/target/entry ability and DynamicValue binding coexist with presentation/config metadata. |
| `Config/ConfigAbility/Avatar/**` | `mixed` | March, Aglaea, Silver Wolf, Asta, Bailu, Aventurine, etc. | Battle execution/modifiers/triggers and presentation operations coexist; operation-level review mandatory. |

### Same-ID / family false positive

| Family / path | Status | Anchor | Interpretation |
| --- | --- | --- | --- |
| `ExcelOutput/ILBattleAvatar.json` / `ILBattleAvatarSkill.json` | `deferred` / false positive for ordinary March | `ILBattleAvatarSkill[100102]` vs ordinary March SkillID `100102` | RtBattle/event family. Same numeric ID must not bridge source families. |

## Servants / memosprites / special battle entities

| Family / path | Status | Manually inspected anchors | Current interpretation / next closure |
| --- | --- | --- | --- |
| `ExcelOutput/AvatarServantConfig.json` | `mixed/include` | Servant `11402`; cross-servant `11413` | Config/AI/skill refs, HP/Speed construction tokens and aggro are battle inputs; owner is proven by CreateServant edge, not an AvatarID field. |
| `ExcelOutput/AvatarServantSkillConfig.json` | `include` | `1140205/SkillP03`, `1140206/SkillP04` | Servant passive numeric producer: inspected values close BattleCry `-1 normalized delay` and DeathRattle `+20 ModifySPNew` raw chains. |
| `Config/ConfigCharacter/Servant/**` | `mixed/include` | `Servant_AglaeaServant_00_Config.json` | Memosprite type, own skills/AI/passives/property wiring; speed family excluded from checked generic sync. |
| `Config/ConfigAbility/Servant/**` | `mixed/include` | Aglaea servant Ability | Own Speed/action-delay operations, death-rattle retention and cleanup surfaces are battle authority; generic scheduler/death dispatcher remains outside local graph. |
| `Config/ConfigSummonUnit/**` | `unresolved` family-wide | Aglaea sample | Aglaea sample is scene/maze/Technique-side and not Garmentmaker battle authority. Do not generalize the sample to all records. |
| logical BattleEvent family (`BattleEventData/Config/SkillConfig` + ConfigCharacter/ConfigAbility) | `mixed/include` | Lingsha `11222`; Elation/YaoGuang `70001`; Aglaea separate event namespace | BattleEvent can be ordinary special-battle-entity/scheduling authority and also reused by modes/events. Classify per owner. |

Confirmed servant construction rule for inspected samples:

> corresponding `SpeedSkill/HPSkill` selects an `AvatarSkillConfig.SkillID` ParamList; `#N` selects its 1-based slot.

The generic parser body for `#N` is not exported, but the practical producer/slot mapping is closed.

## Monsters / enemy execution and difficulty

| Family / path | Status | Manually inspected anchors | Current interpretation / next closure |
| --- | --- | --- | --- |
| `ExcelOutput/MonsterConfig.json` | `mixed/include` | Monster `1002011`; non-zero flat SpeedModifyValue samples | Concrete identity/template/skills/resists and per-instance modification inputs. |
| `ExcelOutput/MonsterTemplateConfig.json` | `include` | corrected `MonsterTemplateID=1002011` | Base HP/ATK/DEF/SPD/Stance/config/AI inputs; not final encounter stats. |
| `ExcelOutput/HardLevelGroup.json` | `include` | blob `9ee36b...`; group/level cross-samples | **Ordinary** five-stat ATK/DEF/HP/SPD/Stance scaling-input family. Final arithmetic/precedence still requires the consumer. |
| `ExcelOutput/ILHardLevelGroup.json` / `ILBattleMonster.json` | `deferred` / false positive for ordinary W14 | numeric collision around `1002011` / group-level rows | Separate IL/RtBattle family for the inspected chain. The older ordinary classification is superseded. |
| `ExcelOutput/EliteGroup.json` | `include` candidate/context | Stage and MonsterConfig EliteGroup coexistence | Additional encounter/monster context input; replace/compose/order semantics unresolved. |
| `ExcelOutput/MonsterUniqueConfig.json` | `mixed/unresolved` | representative ordinary IDs had no matching row | Conditional family; do not insert as a universal override layer without an explicit reference. |
| `ExcelOutput/MonsterSkillConfig.json` | `include` | `100201101.ParamList[0]=2`; Yanqing phase-param skill rows | Skill numeric producer when a DynamicHash/consumer chain closes the semantics. |
| `Config/ConfigCharacter/Monster/**` | `mixed/include` | CocoliaP1, Yanqing RL, Svarog, Mecha, Sam, Junk, etc. | Enemy skills/AI/passives/phase/common-pool edges coexist with other config. |
| `Config/ConfigAbility/Monster/**` | `mixed/include` | damage, common-property, phase, death-rattle and pool-consumer samples | Operation-level battle authority mixed with presentation. |
| ordinary monster AI under `Config/ConfigAI/**` | `mixed/unresolved` | sequence AI plus random-source candidates | Need final skill/target selection semantics and RNG ownership. |

## Encounter / stage / phase construction

| Family / path | Status | Anchors | Current interpretation / next closure |
| --- | --- | --- | --- |
| `ExcelOutput/StageConfig.json` and reachable stage/wave data | `mixed/include` | stages `103201`, `301001`; recurring monster IDs across levels | Stage level/hard-level/elite/wave/StageAbility are independent context inputs; not complete monster state. |
| `Config/Level/StageCommonTemplate.json` | `include` / mixed | stage bootstrap | Ordinary bootstrap installs shared stage abilities, binds pre/post-birth hooks, waves and BattleEvent infrastructure; presentation tasks coexist. |
| `StageAbilityConfig` / level battle abilities | `mixed/include` | StageAbility_301001; StageAbility_BattleCommonRule; StageAbility_Elation | Can mutate live state or maintain global state; classify per StageAbility/owner. |
| `Config/ConfigGlobalTaskListTemplate/**` | `mixed/include` | `Wave_CommonProcess`, `Monster_ChangePhase`, `DealSuperBreakDamage`, `StanceBreak_*`, camera/RT/GM negatives | Contains ordinary executable state authority and presentation/tooling templates. Template-level classification required. |
| phase-property configuration / `SetMonsterPhase` surface | `mixed/include` inputs, operator unresolved | Yanqing variants; FeixiaoPart `ApplyOverrideConfig=false` | Phase can alter properties on the existing entity and is not wave respawn; exact application arithmetic/defaults remain engine/operator work. |

## Global/shared battle producers

The W17 broad reverse scan is complete enough to replace the previous all-`unresolved` family placeholders with representative owner-backed classifications. W17 remains an event-driven sentinel for new ordinary consumers/source families rather than a standing whole-tree rescan.

| Family / path | Status | Confirmed ordinary anchors / residual gap |
| --- | --- | --- |
| `Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json` | `mixed/include` | ordinary `StanceBreakState`, elemental break statuses, monster common damage-reduction lifecycle, plus source-facing `OneMore` / `OneMorePerTurn` marker-controller protocol with ordinary Gepard and W4 Claymore consumers. |
| `Config/ConfigGlobalModifier/GlobalModifier_Common_Property.json` | `mixed/include` | ordinary Svarog defence down; Mecha status-resistance down/fatigue; Sam_01 speed up. Do not bulk-promote siblings without owners. |
| `Config/ConfigGlobalModifier/GlobalModifier_Reference.json` | `mixed/include` | Anaxa Rank01 -> `MReference_DefenceRatioDown` closes a real ordinary reference-prototype chain. |
| `Config/ConfigGlobalModifier/GlobalModifier_Avatar.json` | `mixed/include` | Sampo `M_Ultra_ExtraSP`, Natasha heal-ratio, Gepard skill-tree aggro. Generic skill-tree attachment/loading implementation may remain unexported. |
| `Config/ConfigGlobalModifier/GlobalModifier_Avatar_AssistantTrigger.json` | `unresolved` ordinary ownership | Real battle callbacks/assistant insertion exist, but no ordinary owner/assistant-ID authority was closed. |
| `Config/ConfigGlobalModifier/GlobalModifier_System.json` | `exclude` at pin | empty `ModifierMap` in inspected pinned file. |
| `Config/ConfigGlobalModifier/GlobalModifier.json` | `mixed/unresolved` | some definitions/listeners are battle-capable; representative unowned/debug-only entries retained as unresolved/negative evidence. |
| `Config/ConfigCommonSkillPool/**` | `export_gap` | ordinary Painter Ability contains exact pool consumer/key, but pinned executable pool JSON is absent; opaque opcode identity unresolved. |
| logical BattleEvent family | `mixed/include` | Lingsha and YaoGuang/Elation ordinary chains; special modes/events coexist. |
| `Config/GlobalConfig/GameCoreConstValue.json` | `engine_consumer_unavailable` | raw constants such as SpeedToDelayDistance, BP/SP, resistance and damage-random bounds exist; generic formula consumers not exported. |
| `Config/GlobalConfig/PriorityConfig.json` | `include` shared ordering input | separate event/insert priority domains; lower number earlier within inspected domains; equal-priority/cross-domain arbitration unresolved. |
| `Config/GlobalConfig/DamageBehaviorTemplateListConfig.json` | `mixed/include` data-side semantics | enum/template mapping has a closed representative ordinary released/Mainline Sam Stage -> Monster -> Skill -> ConfigCharacter/Ability chain to `DamageBehavior=1 -> DirectlyLoseHp`; hidden engine arithmetic remains outside explicit template/behavior flags. |
| shared common Avatar/Monster Ability producers | `mixed/include` | `Avatar_Common_PassiveSkill -> Local_SPAdd`, `TriggerStanceCountDown_Test`, common monster break passive. Important producer family outside global-modifier directories; `_Test` suffix is not an exclusion rule. |

## RNG / callback cross-cutting sources

| Source family | Status | Current interpretation |
| --- | --- | --- |
| Ability `RandomConfig` | `mixed/include` | ordinary Silver Wolf weighted choice closes a stateful chain; Jing Yuan shows presentation-risk occurrence. `OddsList` is raw weights/odds input, not final probability. |
| `Retarget(ByRandom=true)` / shared bounce selector | `mixed/include` | Asta `MaxNumber=1` closes one random-target chain; no-MaxNumber cardinality/traversal remains unresolved. |
| `SetDynamicValueByRandom` | `include` representative | Aventurine closes an ordinary random integer/state chain; endpoint/distribution/stream unresolved. |
| `AddModifier.Chance` + StatusProbability/Resistance properties | input chain confirmed / `engine_consumer_unavailable` for final equation | raw application chance and probability/resistance state exist, but evaluator arithmetic is not exported. |
| ComplexSkillAI random sources | `mixed/unresolved` | distinct AI decision-plane random sources exist; shared/separate RNG stream authority unresolved. |
| modifier event / insert priorities | `include` inputs | PriorityConfig plus causal callback samples prove multiple ordering surfaces; full dispatcher/tie-break remains unresolved. |

## Techniques / maze-to-battle boundary

| Family / path | Status | Current interpretation / next closure |
| --- | --- | --- |
| `Config/ConfigMazeBuff/**` | `unresolved` | Include only proven ordinary battle-entry consequences. |
| `Config/ConfigAdventureAbility/**` | `mixed/include` representative | [R5](../../../../../docs/tbgd_evidence/shared/battle_start_build_construction_v1.md): `LocalPlayer_DanHeng_MazeSkill` -> `AddMazeBuff100201` -> ordinary `SkillMaze` battle-entry property; presentation neighbors remain filtered. |
| `ExcelOutput/AvatarMazeBuff.json` | `mixed/include` representative | R5 row `100201`: `CharacterSkill` / `SkillMaze` / `AddBattleBuff` bridge; metadata is not the numerical producer and the native loader remains separate. |
| `Config/ConfigAdventureModifier/**` | `unresolved` | Same boundary rule. |
| `Config/ConfigSummonUnit/**` | `unresolved` | Aglaea sample is a concrete scene/maze false friend; other records need owner tracing. |

## Equipment and ordinary build effects

| Family / path | Status | Anchor | Current interpretation / next closure |
| --- | --- | --- | --- |
| Light Cone/equipment identity/effect tables | `mixed/include` representative | Light Cone `20000` closed chain | Battle effect/rank data in scope; acquisition/progression data excluded. Need generic augment/rank semantics and complex effects. |
| relic / planar stat and set-effect sources | `mixed/include` representative | [R5](../../../../../docs/tbgd_evidence/shared/battle_start_build_construction_v1.md): six slots, Set102/301 | `RelicConfig`/base type -> main/sub affix -> `RelicSetConfig`/set skill -> `RelicAbility` is closed for the selected build; not corpus-exhaustive or runtime-verified. |
| `ExcelOutput/RelicMainAffixConfig.json` / `RelicSubAffixConfig.json` | `include` selected rules | main groups 51-56; sub group 5 | Source coefficients and typed local readers; main level and sub count/step operators remain distinct. Finished-piece fields only; acquisition/roll history is excluded. |
| `Config/ConfigAbility/Equip/RelicAbility.json` | `mixed/include` representative | Ability51021 / Ability53011 | Normal-hit damage-context versus Speed120 conditional attack-property effects; static `PropertyList` must not be counted twice. |
| equipment augment/superimposition/rank families | `unresolved` generically | one Light Cone sample | Determine generic active battle-value transport. |

## Presentation-oriented candidates / negative evidence

These are never excluded by naming alone. Current representative findings include:

- camera/RT global task templates: presentation-only in inspected samples;
- GM/test files: can contain battle-real opcodes without ordinary reachability;
- WhiteBox definitions: can contain battle producers without ordinary consumer;
- battle-perform target lookup: can address an existing entity but is not creation/config-selection authority;
- animation/preshow timing: not timeline authority without a logical scheduling consumer.

Remaining presentation families (BattlePerform, camera states/blends, BGM, UI/audio/localization) should be closed with representative negative evidence rather than blanket prefix rules.

## Explicitly deferred special-mode families

The current phase does not require exhaustive archaeology of:

- Simulated Universe;
- Divergent Universe;
- Currency Wars;
- event-specific/mode-owned battle mechanics, including inspected RtBattle/IL families.

These are `deferred`, not `non_battle`. Shared lower-level primitives independently reached by ordinary combat remain in scope.

## Current checkpoint gaps

After the 2026-09-09 post-integration compaction, the highest-value unresolved source-family boundaries are:

1. **Monster final-stat engine/operator:** ordinary `HardLevelGroup` inputs and join topology are known; final arithmetic/precedence/flat placement/phase application remain unclosed and should not be re-searched without a new engine source.
2. **Generic Shield/Modifier engine semantics:** March-local numerics/application/replacement hooks, main-shield `CanDispel=true` and snapshot-routing inputs are closed; generic ShieldByCasterDefence arithmetic, snapshot capture, lifetime/depletion and replacement callback order remain engine-bound.
3. **Timeline scheduler engine boundary:** Speed/action-delay opcodes, servant scheduling and the data-facing `OneMore` / `OneMorePerTurn` protocol are source-backed; SPD→AV/queue/requeue/tie-break and exact runnable OneMore ordering are not exported.
4. **RNG/application engine boundary:** RandomConfig algorithm, SetDynamicValueByRandom range semantics, AddModifier.Chance final equation and RNG stream owner remain outside located TBGD consumer data.
5. **Death/callback dispatcher:** priorities and several causal/revive/death-rattle chains are closed, but universal non-muted death total order and equal-priority/cross-domain arbitration remain.
6. **W17 residual owners/export gaps:** AssistantTrigger ordinary owner, opaque CommonSkillPool operation identity and generic skill-tree attachment/loading implementation where required. Broad reverse scan itself is complete and event-driven only.
7. **Major source-facing work still needing dedicated vertical closure:** W03 battle execution language, W04 full damage, W06 full toughness/break, W08 resource system, W09 generic modifier lifecycle, W11/W15 targeting+AI, W16 encounter termination, and W01/W18 battle-start build/equipment construction.

No new W19+ mechanism was justified by the completed broad W17 pass; the current taxonomy remains mutable if later evidence reveals an unrepresented battle-state consequence.
