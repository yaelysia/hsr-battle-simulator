# Ordinary-combat global/shared producer reverse scan

## Record metadata

- TBGD revision: `14c1d18f91a8101d610e6c523447a7517de3fae1`
- Evidence maturity: `manually_confirmed` for representative ordinary owner/consumer chains; explicit export/ownership gaps for named residuals
- Scope: W17 anti-miss reverse scan for ordinary battle producers missed by actor-centric traversal
- Lane status: **broad reverse scan complete**
- Package status: keep W17 as an `active` sentinel for future high-signal discoveries; do not mark the universe of global/shared mechanics permanently closed
- New mechanism candidate: none
- Runtime production code changed: no

## Core rule

`global/shared` is an ownership/storage property, not a scope verdict.

A source becomes ordinary battle authority only through a real owner/reference/consumer chain. Conversely, battle-capable definitions without an ordinary owner are not automatically non-battle; they remain unresolved/export gaps.

Classification therefore happens at modifier/template/owner/reference-edge level, not by filename, directory or numeric ID.

## Broad families scanned

The completed W17 pass covered the high-value surfaces:

- `Config/ConfigGlobalModifier/**`
- `Config/ConfigGlobalTaskListTemplate/**`
- logical BattleEvent sources distributed across Excel / ConfigCharacter / ConfigAbility
- `Config/ConfigCommonSkillPool/**`
- `Config/GlobalConfig/GameCoreConstValue.json`
- `Config/GlobalConfig/DamageBehaviorTemplateListConfig.json`
- common Avatar/Monster ability producers outside the global-modifier directory
- reverse scans for known battle properties/statuses/opcodes such as Speed, StanceBreakState, SetHP, ModifyActionDelay, StackProperty, WaveMonster, CreateBattleEvent, TurnInsertAbility and shared resource/damage surfaces.

Default/current search was navigation only; promoted claims were returned to the pinned revision.

## Shared Weakness-Break / action-delay authority

Ordinary monster chains reach shared `StanceBreakState` in `GlobalModifier_Common_Specific.json`.

Pinned behavior includes:

- break-state effect;
- `ModifyActionDelay` on modifier owner with normalized `+0.25`;
- `TriggerBreak`;
- lifecycle/reset work restoring stance/state;
- common monster damage-reduction state.

Elemental break templates also route ordinary combat to shared Fire/Ice/Wind/Thunder/Imaginary/Quantum status/damage/delay paths.

These are ordinary shared battle primitives, not deferred-mode content merely because they are global.

## Stage-global Super Break producer

Closed ordinary topology:

```text
StageCommonTemplate
-> StageAbility_BattleCommonRule
-> target-side SuperBreak state
-> ordinary Sam passive
-> IncludeTaskListTemplate(DealSuperBreakDamage)
-> DamageByAttackProperty / break-pure-damage path
```

This is a concrete producer family that actor-centric traversal alone can miss.

## Global task templates are mixed executable authority

Confirmed ordinary examples include:

- `Monster_ChangePhase` — real same-entity HP/Stance/state work;
- `Wave_CommonPreProcess` / `Wave_CommonProcess` — ordinary wave lifecycle;
- delayed `WaveMonster` path;
- `DealSuperBreakDamage`;
- elemental `StanceBreak_*` task families.

Other global task templates are presentation/RT/GM/tooling-oriented. The directory remains mixed and template-specific.

## BattleEvent is ordinary-capable

The logical BattleEvent family is distributed at this pin rather than represented by one directory.

Ordinary examples include:

- Lingsha `PreloadBattleEventByID/CreateBattleEvent(11222)`;
- YaoGuang/Elation ordinary activation path to BattleEvent `70001` and inserted/auto-use behavior;
- Aglaea's separate BattleEvent namespace, which also demonstrates why numeric ID equality across entity types is unsafe.

Individual BattleEvents still require owner classification.

## Shared property/modifier primitives with ordinary owners

Representative confirmed chains include:

- `MReference_DefenceRatioDown` -> ordinary Anaxa Rank01 reference-prototype chain;
- `MCommon_DefenceRatioDown` -> Svarog;
- `MCommon_StatusResistanceDown` -> ordinary Mecha;
- `MCommon_FatigueRatio` -> ordinary Mecha;
- `MCommon_SpeedUp` -> ordinary Sam/minion chain;
- `M_SkillTree_AggroUp` -> Gepard skill-tree path;
- `M_Ultra_ExtraSP` -> Sampo ordinary skill-tree path;
- `M_SkillTree_HealRatioUp` -> Natasha ordinary skill-tree path.

Positive owner-backed samples prove the family is real shared battle authority. They do not bulk-promote unowned siblings.

## AvatarSkillTreeConfig correction

A stale earlier inventory phrase treated `AvatarSkillTreeConfig.json` as potentially empty/missing for the generic skill-tree path.

That premise is superseded. Exact pinned concrete table -> ability -> shared-modifier chains were closed for examples including Gepard/Welt/Sampo/Natasha.

What can remain unexported is the **generic GameCore ability-attachment/loading implementation**, not the existence/population of the pinned table itself.

Do not describe `AvatarSkillTreeConfig.json` as empty/missing at this pin.

## Shared common-passive producers outside ConfigGlobalModifier

`Avatar_Common_PassiveSkill` provides ordinary shared behavior outside the global-modifier directory, including a confirmed `OnTriggerDeath -> ModifySPNew` path.

The same area contains a real break route with a `_Test` suffix, providing explicit negative evidence against suffix-based tooling classification.

## DamageBehavior selector/template — ordinary Sam chain closed

Pinned enum/template data maps shared `DamageBehaviorTemplate` values including `TrueDamage`, `DirectlyLoseHp`, and `DirectlyLoseHpHit`.

A corrected W17 continuation closed an ordinary released/Mainline Sam chain through populated pinned Stage/Monster/Skill/normal ConfigCharacter/Ability data to a real `DamageBehavior=1 -> DirectlyLoseHp` selector/template mapping.

Therefore the previous caveat that the ordinary Sam stage-instance edge “may be export-blocked” is superseded for this representative chain.

This closes the data-side ordinary reachability of the shared DamageBehavior selector/template. It still does not expose hidden engine arithmetic beyond explicit template/behavior flags.

## ConfigCommonSkillPool — consumer present, executable definition absent

Pinned ordinary Painter battle ability contains the exact pool key:

`CommomSkill_W5_Painter_00`

but exact pinned `Config/ConfigCommonSkillPool/**` lacks the executable pool JSON payload.

Correct classification:

**ordinary consumer/key present; executable pinned definition absent = export gap**.

Current/default pool payloads may corroborate family existence but must not fill the pin.

## GameCoreConstValue — raw values, generic engine consumers unavailable

Pinned raw contains battle-facing constants such as:

- `SpeedToDelayDistance=1000`
- `DamageRandomMin=1`, `DamageRandomMax=1`
- resistance/defence bounds
- BP/SP-related constants
- servant property-sync list.

These are raw inputs. Generic formulas/consumers are not exported in this release-data corpus.

Do not infer SPD→AV, defence/resistance formulas, BP initialization or RNG algorithms from names.

## Assistant infrastructure — final W17 boundary

The final W17 pass re-read exact pinned:

- `Config/ConfigGlobalModifier/GlobalModifier_Avatar_AssistantTrigger.json`
- `Config/GlobalConfig/TargetAliasConfig.json`
- `Config/ConfigAbility/Avatar/Assistant/**`
- representative executable `Avatar_Asta_00_Assistant.json`.

### Scheduler/trigger side

`GlobalModifier_Avatar_AssistantTrigger.json` contains real listeners for speed-down, Burn, break/weakness, team HP-loss and enter-battle/post-maze-skill surfaces, with `RPG.GameCore.TurnInsertAssistantAbility`.

The local `AssistantAbilityID` comes from dynamic hash `640129697` with `ReadInfo.Type=None`; this file does not provide the authoritative typed ID producer.

### Formal assistant entity model

Pinned `TargetAliasConfig.json` defines:

`AssistantAvatar -> RPG.GameCore.TargetFetchAvatarAssistant`.

This proves assistant-avatar is a formal battle target/entity concept. Target access still does not prove creation/ordinary ownership.

### Executable assistant payloads

Pinned `Config/ConfigAbility/Avatar/Assistant/` contains executable assistant files for multiple avatars.

Representative pinned Asta assistant performs real battle-state operations including:

- `ModifyActionDelay(AllTeamMember, AddNormalizedValue=-0.35)`;
- `ModifySPNew(Caster, AddRatio=1)`;
- ability chaining, mixed with presentation operations.

Final classification:

> formal assistant target/entity model + executable assistant battle payloads + global assistant insertion scheduler are present; ordinary owner/creator and authoritative `AssistantAbilityID` transport are source-unavailable in the inspected pin.

Freeze as a battle-real ownership/export gap. Do not classify it non-battle, and do not promote it to ordinary reachability without an owner/ID transport edge.

## Other residuals

- `MGM_Endurance_00`: real behavior definition, no ordinary owner recovered; keep unresolved.
- definition-only/mode-only `MCommon_*` siblings: retain candidate/unresolved until a concrete ordinary consumer appears.
- generic skill-tree attachment/loading body: data tables and concrete chains exist; generic engine loader may remain unexported.

## Negative evidence / false friends

- `GlobalModifier_System.json` is structurally empty at the pin.
- inspected RT/camera global task templates are presentation-only.
- GM/test/WhiteBox definitions can contain real battle opcodes without ordinary reachability.
- broad event names with only DebugLog bodies are not state authority.
- `SummonUnitGlobalConfig` is scene/navigation-heavy and is not servant battle authority without a battle consumer.
- `_Test`, `Global`, `Reference`, `GM`, `IL` and similar naming tokens are navigation hints, not scope verdicts.
- target/entity lookup proves access semantics, not creation/ownership.
- obfuscated operation identities remain opaque until independently identified.
- large pinned JSON must be re-read exactly before declaring it empty/missing.

## W17 lane closure

The assigned anti-miss broad reverse scan is **complete** for this pin and scope.

No new W19+ mechanism package is justified by this lane. Remaining unknowns are classified source/export/ownership/engine boundaries rather than unscanned ordinary producers.

Future W17 work should be event-driven only by:

- a newly discovered ordinary consumer;
- a genuinely new source family;
- a changed pinned revision.

Do not repeat whole-tree/global-family scans on the same pin as routine progress.
