# Ordinary-combat global/shared producer reverse scan

## Record metadata

- TBGD revision: `14c1d18f91a8101d610e6c523447a7517de3fae1`
- Evidence maturity: `manually_confirmed` for representative ordinary owner/consumer chains; unresolved/export-gap for named residual families
- Scope: W17 reverse scan for ordinary battle producers missed by actor-centric forward traversal
- Runtime production code changed: no

## Core semantic rule

`global/shared` is an ownership/storage property, not a scope verdict.

A source can be ordinary battle authority when it is:

- a shared modifier referenced by an ordinary actor;
- a global task template invoked by ordinary actor/stage logic;
- a stage-common producer maintaining state consumed later by an actor;
- a BattleEvent entity created/activated by an ordinary character or stage bootstrap;
- a global prototype copied into a local modifier;
- an opaque shared-pool consumer whose executable definition is missing from the pin.

Conversely, a battle-capable definition is not ordinary-reachable until an owner/invocation edge is established.

Classification therefore happens at modifier/template/owner/reference-edge level, not by filename or directory.

## Reverse-scanned families

The first broad pass manually inspected/reverse-scanned high-value surfaces including:

- `Config/ConfigGlobalModifier/**`
- `Config/ConfigGlobalTaskListTemplate/**`
- logical BattleEvent sources distributed across Excel / ConfigCharacter / ConfigAbility
- `Config/ConfigCommonSkillPool/**`
- `Config/GlobalConfig/GameCoreConstValue.json`
- `Config/GlobalConfig/DamageBehaviorTemplateListConfig.json`
- common avatar/monster Ability producers outside the global-modifier directory
- known battle properties/statuses/opcodes such as Speed, StanceBreakState, SetHP, ModifyActionDelay, StackProperty, WaveMonster, CreateBattleEvent and TurnInsertAbility.

Default/current search was navigation only; promoted claims were returned to pinned raw chains.

## Ordinary shared Weakness-Break / action-delay chain

Representative ordinary monster chain:

```text
normal monster ConfigCharacter
  -> Monster_Common_PassiveSkill_StanceBreak_Action
  -> Monster_Common_Ability OnBeingBreak
  -> AddModifier(StanceBreakState)
  -> ConfigGlobalModifier/GlobalModifier_Common_Specific.json
```

Pinned `StanceBreakState` performs battle-state work including:

- adds break-state effect;
- `ModifyActionDelay` on the modifier owner with normalized `+0.25`;
- `TriggerBreak`;
- on lifecycle exit/reset, restores stance/state and common damage-reduction state.

`MonsterAllDamageReduce` stacks `AllDamageReduce=0.1` for monsters wired to that common passive.

This is ordinary shared authority relevant to W06/W07/W09/W10, not a deferred-mode primitive merely because it lives in a global modifier file.

## Shared elemental break templates

Ordinary common passive/break routing reaches shared `StanceBreak_*` templates. Confirmed element-specific paths apply shared statuses/damage behavior such as:

- Fire -> `MCommon_Element_Burn`
- Ice -> `MCommon_Element_Frozen`
- Wind -> `MCommon_Element_Poison`
- Thunder -> `MCommon_Element_Electric`

Imaginary/Quantum templates also inject raw action-delay values into their shared status paths.

Downstream global modifier definitions confirm real battle behavior such as snapshot DOT/control state, break-damage callbacks and delay mutation. Exact generic break arithmetic/ordering remains W06/W04/W10 work.

## Stage-global Super Break producer

Actor-centric traversal can miss target-side state maintained globally.

Closed ordinary chain:

```text
StageCommonTemplate
  -> StageAbility_BattleCommonRule
  -> MStageAbility_BattleCommonRule_SuperBreak
       accumulates target-side stance-damage state
  -> ordinary Sam passive
  -> IncludeTaskListTemplate(DealSuperBreakDamage)
  -> DamageByAttackProperty with break/pure-damage formula tags
```

The actor owns the final trigger, but the target-side accumulated state is stage/global-owned. This is a representative reason W17 reverse scanning is required even after character forward traversal.

## Global task templates are mixed executable authority

### Monster phase template

A normal monster Ability reaches:

`IncludeTaskListTemplate("Monster_ChangePhase")`

The shared template performs real state work such as SetHP/reset stance/modifier add-remove/custom events. It is not merely phase presentation.

### Stage wave template

`StageCommonTemplate -> IncludeTaskListTemplate("Wave_CommonProcess")`

participates in wave completion / next-wave progression. The stage bootstrap also coordinates `WaveMonster`, passive activation, StageAbility binding, delayed monster creation and BattleEvent preload/start behavior.

### Negative mixed examples

Other global task files/templates inspected are camera/UI/GM/tooling-oriented. The directory must therefore stay `mixed`; shared task authority is template-specific.

## BattleEvent is an ordinary-capable special battle entity family

The logical family is distributed at this pin rather than backed by one `ConfigBattleEvent/**` directory.

### Lingsha example

Ordinary Lingsha Ability:

`PreloadBattleEventByID(11222)` / `CreateBattleEvent(11222)`

joins to pinned BattleEvent data and a real `RPG.GameCore.BattleEventConfig`. Its passive/action graph can schedule inserted abilities.

### Elation / YaoGuang example

The first reverse pass also closed an ordinary activation chain for BattleEvent `70001`:

```text
StageCommonTemplate
  -> StageAbility_Elation preload/common state
  -> released ordinary YaoGuang Elation skill
  -> IncludeTaskListTemplate(Elation_StartElationTime)
  -> find-or-create BattleEvent 70001
  -> BattleEvent_Elation_Config AutoUse skills / inserted action
```

Therefore BattleEvent is not inherently event-mode/deferred infrastructure. Individual BattleEvents still require owner classification.

## Shared property/modifier primitives with ordinary owners

Representative confirmed ordinary chains include:

### `MReference_DefenceRatioDown`

Global reference prototype -> local Anaxa Rank01 modifier via `ReferenceModifierName` -> ordinary damage-preparation callback -> defence property mutation.

This proves `MReference_*` is a real shared combat prototype family; siblings still need their own consumer evidence.

### `MCommon_DefenceRatioDown`

Global common-property modifier -> normal Svarog Skill05 consumer -> target defence-ratio property mutation.

### `MCommon_StatusResistanceDown`

Global common-property modifier -> normal Mecha01_02 battle ability -> target `StatusResistanceBase` mutation.

### `MCommon_FatigueRatio`

Global common-property modifier -> normal Mecha01_00 Skill01 path -> `FatigueRatio` mutation.

### `MCommon_SpeedUp`

Global common-property modifier -> normal Sam_01 skill graph -> summoned-minion Speed property mutation.

No SPD→AV formula is inferred from this property write.

### `M_SkillTree_AggroUp`

Global avatar modifier -> released Gepard skill-tree ability -> `AggroAddedRatio` mutation. Parameter role is wired through `SkillTreeParam(PointB1,index=0)`; generic skill-tree loader transport remains an export gap.

### `M_Ultra_ExtraSP`

Global avatar modifier -> ordinary/released avatar skill-tree consumer (Sampo representative) -> `OnAfterSkillUse` + Ultra predicate -> `ModifySPNew` with injected value.

### `M_SkillTree_HealRatioUp`

Global avatar modifier -> ordinary/released Natasha skill-tree consumer -> `HealRatioBase` mutation.

These examples establish shared ordinary reachability without bulk-promoting every sibling in the same files.

## Shared ordinary common-passive producers outside ConfigGlobalModifier

`Avatar_Common_PassiveSkill` supplies ordinary shared behavior not discoverable by scanning only `ConfigGlobalModifier/**`.

Representative producer:

`Local_SPAdd -> OnTriggerDeath -> ModifySPNew(+10 raw injected value)`

The user-facing resource meaning/caps remain W08 work.

The same ordinary common-passive area also includes `TriggerStanceCountDown_Test`, which routes real break logic. This is a concrete counterexample to suffix-based filtering: `_Test` is not sufficient to classify a symbol as tooling-only.

## DamageBehavior shared selector/template

Pinned enum data maps `DamageBehaviorTemplate` values such as:

- `TrueDamage`
- `DirectlyLoseHp`
- `DirectlyLoseHpHit`

and `DamageBehaviorTemplateListConfig.json` supplies shared behavior flags.

A normal Sam Ability contains a real `DamageBehavior` selector that resolves through the enum to `DirectlyLoseHp`, establishing a data-side consumer for the shared template.

The inspected normal battle ConfigCharacter/Ability owner is confirmed; a final stage-instance creation edge for the sampled Sam ID remains export-blocked in the inspected pin sources. Do not infer engine behavior beyond explicit template flags.

## ConfigCommonSkillPool — consumer present, executable definition absent

Exact pinned `Config/ConfigCommonSkillPool/` contains only the empty Painter layout payload, with no executable pool JSON.

However, pinned ordinary Painter Ability contains an `OnCreate` callback with an obfuscated operation and exact pool key:

`CommomSkill_W5_Painter_00`

The corresponding ordinary monster ConfigCharacter is a real battle config.

Therefore the correct classification is:

**pinned ordinary combat consumer/key present; executable CommonSkillPool definition absent**

not `non-battle`.

Current/default executable pool files can corroborate that the family exists, but cannot fill the pinned semantics. The obfuscated opcode must remain opaque until independently identified.

## GameCoreConstValue — raw authority / engine consumer unavailable

Pinned `GameCoreConstValue.json` contains real raw values including representative:

- `SpeedToDelayDistance=1000`
- `DamageRandomMin=1`, `DamageRandomMax=1`
- `DamageTakenRatioMax=3.5`
- resistance bounds
- defence-related constants
- BP/SP-related constants.

Repeated reverse searches did not expose their generic ordinary GameCore formula consumers in the release-data dump.

Classification:

**raw global value authority; exported engine consumer unavailable**

Do not infer SPD→AV, defence/resistance, BP initialization, clamping or RNG formulas from the field names.

## Residual unresolved shared infrastructure

### AssistantTrigger

`GlobalModifier_Avatar_AssistantTrigger.json` contains real battle listeners and `TurnInsertAssistantAbility` operations, but no ordinary avatar/monster/stage owner or authoritative assistant-ID table was closed in the first pass.

Classification: battle-capable infrastructure, ordinary owner unresolved.

### `MGM_Endurance_00`

Real behavior definition exists, but reverse search found no ordinary consumer. Keep unresolved.

### Definition-only/mode-only `MCommon_*` siblings

Several siblings remain candidate/unresolved or mode-specific because the first pass did not find an ordinary owner. They are not `non-battle`; they simply lack the required ordinary reachability evidence.

## Negative evidence / false friends

- `GlobalModifier_System.json` is structurally empty at the pin.
- inspected RT/camera global task templates are presentation-only.
- GM/test definitions can contain battle-real opcodes without ordinary reachability.
- WhiteBox definitions can contain damage producers without an ordinary consumer.
- broad callback/event names whose bodies only DebugLog are not state authority.
- `SummonUnitGlobalConfig` is dominated by scene placement/navigation/interaction behavior and is not servant battle authority without a battle consumer.
- `_Test`, `Global`, `Reference`, `GM`, `IL` and similar naming tokens are navigation hints, never sufficient scope classification.
- an entity target lookup is not creation/config-selection authority.

## First-pass W17 conclusion

The broad reverse scan found multiple important ordinary producers missed by actor-centric forward traversal, but no battle-state consequence requiring a new W19+ work package. Findings fit existing W04/W06/W07/W08/W09/W10/W13/W16 domains.

The broad scan is now near diminishing returns. Follow-up should be narrow:

1. resolve or freeze AssistantTrigger ordinary ownership;
2. preserve CommonSkillPool as consumer-present/export-gap unless another pinned artifact exposes the executable payload;
3. seek a generic skill-tree loader only if a new source family appears; otherwise preserve the export gap;
4. inspect additional global siblings only when navigation finds a concrete ordinary consumer;
5. stop repeatedly searching `GameCoreConstValue` formulas inside the same release-data dump without a new engine/source family.
