# Aglaea — Servant 11402 battle reference chain

## Record metadata

- Concept: ordinary servant/memosprite creation, numeric construction, property-sync source partition, independent scheduling, recast behavior, coordinated-action ownership, natural death/death-rattle surfaces, and muted forced cleanup
- Owner context: Aglaea (`AvatarID=1402` from the ordinary avatar chain; owner identity is not asserted from the servant row itself)
- Servant: Garmentmaker (`ServantID=11402`)
- TBGD revision: `14c1d18f91a8101d610e6c523447a7517de3fae1`
- Evidence maturity: `manually_confirmed`; `#N` rule cross-sampled on another servant; property-sync partition cross-checked with Castorice
- Battle-scope verdict: `include`
- Runtime production code changed: no

## Correction history

Two earlier statements remain explicitly superseded:

1. Aglaea Skill02's pinned `SetActionDelay(Value=0)` targets **`Caster` (Aglaea)**, not `CasterServant`; it is not servant queue-initialization evidence.
2. The exact pinned Aglaea Ability file does **not** contain a literal `ActivityOnCreate` field on the inspected creation operation.

The servant remains independently schedulable through separate servant-owned Speed/action-delay surfaces.

## Confirmed identity chain

```text
Config/ConfigAbility/Avatar/Avatar_Aglaea_00_Ability.json
  -> CreateServant(ServantID=11402)
  -> ExcelOutput/AvatarServantConfig.json[11402]
       Config = Config/ConfigCharacter/Servant/Servant_AglaeaServant_00_Config.json
       AIPath = Config/ConfigAI/Avatar_ComplexSkilll_AutoFight_AI.json
       SkillIDList = [1140201,1140203,1140205,1140206]
       SpeedInherit = "#4" ; SpeedSkill = 140204
       HPInherit = "#5" ; HPBase = "#6" ; HPSkill = 140204
       Aggro = 125
  -> ServantConfig
  -> Config/ConfigAbility/Servant/Servant_AglaeaServant_00_Ability.json
```

Owner relation is established by Aglaea's `CreateServant(11402)` edge and summoner aliases such as `CasterSummoner`, not by a fixed owner field in `AvatarServantConfig[11402]`.

## `#N` construction rule

Exact pinned `AvatarSkillConfig` blob:

`a5416ced941c247d475b2aaa83277b9cdf474dd9`

For `SkillID=140204`:

- Lv1 `ParamList=[0.12,0,0,0.35,0.44,180]`
- Lv6 `ParamList=[0.21,0,0,0.35,0.572,504]`

With `SpeedInherit="#4"`, `HPInherit="#5"`, `HPBase="#6"`, the inspected rule is:

> corresponding `SpeedSkill/HPSkill` selects an `AvatarSkillConfig.SkillID` ParamList; `#N` selects its 1-based slot.

Servant 11413 / SkillID 141304 independently follows the same positional pattern.

The generic parser implementation for literal `#N` is not exported, but the practical producer -> SkillID -> slot mapping is closed.

## Servant ConfigCharacter wiring

Pinned `Servant_AglaeaServant_00_Config.json` declares:

- selectable servant `Skill01`;
- `SkillP01 -> Servant_AglaeaServant_00_Passive`;
- `SkillP03 -> Servant_AglaeaServant_00_BattleCry`;
- `SkillP04 -> Servant_AglaeaServant_00_DeathRattle`;
- independent AI/targeting/passive wiring;
- `SPBase=10` on Skill01;
- JoinSkill entries;
- shared `Avatar_Common_PassiveSkill` / `Servant_Common_PassiveSkill` wiring;
- `SyncPropertyExceptList` for property-sync configuration.

The config proves passive definitions and ability membership. It does **not** expose the GameCore rule that automatically installs/activates passive `EntryAbility` items during `CreateServant`; passive auto-entry timing is `engine_consumer_unavailable` at this pin.

## Property-sync source partition

A later W13 pass found a global pinned producer:

`Config/GlobalConfig/GameCoreConstValue.json::ServantSyncPropertyList`

The inspected list includes broad battle-property families such as attack/defence families, level, damage bonuses, crit, elemental bonuses, resistances/penetration, break/heal/shield, status probability/resistance, SPRatio, BreakDamage and related properties.

Separate dedicated servant construction surfaces exist in `AvatarServantConfig`:

- `HPBase/HPInherit/HPSkill`
- `SpeedBase/SpeedInherit/SpeedSkill`

Per-servant exception lists are a third surface:

- Aglaea excludes the Speed family (`Speed`, `BaseSpeed`, `SpeedAddedRatio`, `SpeedConvert`, `SpeedDelta`, `SpeedOverride`);
- pinned Castorice independently excludes both HP and Speed families, including HP/MaxHP/CurrentHP and Speed variants.

Safe source-level conclusion:

```text
ServantSyncPropertyList
+ per-servant SyncPropertyExceptList
+ dedicated HP/Speed construction fields
```

are distinct data surfaces.

Unsafe conclusion:

> effective sync = `ServantSyncPropertyList - SyncPropertyExceptList` with a known timing/merge order.

Castorice's exception set includes property families not visibly present in the audited global list, so the combination rule cannot be inferred from names alone.

Still unexported:

- creation snapshot vs continuous/event-driven sync;
- precedence between generic sync and dedicated HP/Speed construction;
- runtime merge/filter semantics.

## Distinct servant/summoner Speed and self scheduling

The servant Ability graph separately reads:

- `CasterSummoner.Speed`
- `Caster.Speed`

and owns servant-side speed/action-delay machinery.

`SkillP03` binds hash `1311494286 -> SkillParam(SkillP03,index=0)`.

Exact pinned `AvatarServantSkillConfig` supplies `SkillID=1140205`, `SkillP03`, `ParamList[0]=1`.

`Servant_AglaeaServant_00_BattleCry` therefore closes:

`OnStack -> ModifyActionDelay(servant, 0 - 1) = -1 normalized`

This proves data-level independent schedulability. It does not reveal hidden SPD→AV/queue arithmetic or passive auto-entry timing.

## DeathRattle numeric chain

`SkillP04` binds `-2017292130 -> SkillParam(SkillP04,index=0)`.

Exact pinned producer `SkillID=1140206 / SkillP04` supplies `ParamList[0]=20`.

The formal DeathRattle modifier has `BehaviorFlagList=["Deathrattle"]` and:

`OnDeathrattle -> ModifySPNew(CasterSummoner,+20)`.

The raw target/amount are closed; generic player-facing resource meaning/caps remain W08.

## Aglaea Skill02 create/recast behavior

The ordinary Skill02 path distinguishes:

- no living servant -> `CreateServant(11402)`;
- living servant -> maintenance/healing path without issuing another create.

Therefore ordinary recast semantics are:

**create-if-absent / maintain-or-heal-existing**, not replacement-on-recast.

The nearby explicit sequence:

```text
CreateServant(11402)
-> SetEntityPosition(CasterServant, Caster)
-> SetActionDelay(Caster, 0)
-> ModifyCurrentSkillDelayCost(-1 normalized)
```

must not be read as servant initial-queue setup because the delay write targets Aglaea.

## Independent servant normal action vs owner-coordinated contribution

A later W13 pass narrows coordinated-action ownership.

### Servant's selectable normal action

Pinned Servant ConfigCharacter defines:

- `SkillList.Name=Skill01`
- `SkillType=Servant`
- `UseType=SelectEntity`
- enemy-select target contract
- `EntryAbility=Servant_AglaeaServant_00_Skill11_Phase01`

Its `SkillAbilityList` assigns the normal action family:

`Skill01 -> Skill11_Phase01 -> Skill11_Phase02 -> SkillPerformFinish`.

### Owner-coordinated Together path

The same ConfigCharacter assigns `Servant_AglaeaServant_00_Skill11_Together_Phase01` to passive `SkillP01`, not selectable `Skill01`.

Aglaea owner-side Skill11 dispatches the servant contribution through `TriggerParallelAbility(CasterServant)`.

The Together graph reads summoner/servant Speed separately and performs pair damage/modifier work, but is not the servant's configured selectable normal-skill entry.

Safe conclusion:

> ordinary servant action entry and owner-coordinated servant contribution are distinct source-owned execution surfaces.

Do **not** strengthen this into a claim that the coordinated contribution definitely preserves, consumes or resets the servant's existing normal action-delay slot. Manual searches of both owner Skill11 and servant Together regions found no explicit action-delay mutation there, so normal-slot accounting is an `engine_consumer_unavailable` boundary.

## Natural pre-death, DeathRattle and post-death surfaces

`MServant_AglaeaServant_Passive.OnBeforeDying` can:

- transfer speed-stack state to the summoner under a trace condition;
- remove summoner-side linked modifiers;
- silently force-kill a living `BattleEventCountDown` with `MuteHpChange=true` / `MuteAllTriggerDeath=true`.

The formal DeathRattle then exposes its own `OnDeathrattle` work.

Selected modifiers use `KeepOnDeathrattle` plus `RemoveWhenCasterDead`, proving some state can survive through the DeathRattle interval and be removed later.

Aglaea's owner passive independently listens to `OnListenCharacterDie`; when the dead entity intersects `CasterServant`, it resets an owner working value.

The pin therefore exposes distinct lifecycle surfaces:

```text
OnBeforeDying
-> DeathRattle-capable state / OnDeathrattle
-> OnListenCharacterDie
-> later RemoveWhenCasterDead / OnDestroy / entity removal surfaces
```

This is a semantic lifecycle decomposition, not a claim about the hidden universal dispatcher/tie-break implementation.

## BattleEvent-driven muted forced cleanup

A separate BattleEvent phase path schedules:

`TurnInsertAbility(Servant_Aglaea_00_PassiveSkill01_ForceKill_Insert, InsertAbilityPriority=AvatarBuffOthers)`.

The inserted cleanup ability uses:

- `ForceKill(Caster, MuteHpChange=true, MuteAllTriggerDeath=true)`
- `SetDieImmediately(Caster)`
- explicit owner/servant-linked modifier removals.

This is a priority-tiered, trigger-suppressed forced-cleanup branch and must not be used as ordinary natural-death ordering evidence.

## BattleEvent namespace hazard

Aglaea also uses BattleEvent ID `11402`. That is a separate battle-object namespace from `ServantID=11402`.

Numeric equality is not entity identity.

## Negative knowledge

- `Config/ConfigSummonUnit/SummonUnit_Aglaea_00_Config.json` is scene/maze/Technique-side in the inspected chain and is not Garmentmaker battle authority.
- `SyncPropertyExceptList` must not be modeled as a trivial subtraction rule without its consumer.
- passive `EntryAbility` listing does not prove synchronous activation inside `CreateServant`.
- absence of action-delay writes in the coordinated Skill11 graph does not prove hidden scheduler non-consumption.
- owner-side `SetActionDelay(0)` after create is not servant initial-delay evidence.

## Current closed claims

1. ordinary Aglaea can create `ServantID=11402`;
2. servant config/AI/skill/HP/Speed/agro inputs are pinned;
3. `#N` resolves through corresponding SkillID ParamList 1-based slots;
4. global servant sync producer, per-servant exception lists and dedicated HP/Speed construction are distinct data surfaces;
5. servant/summoner Speed are distinct runtime values;
6. BattleCry closes to self `ModifyActionDelay(-1 normalized)`;
7. DeathRattle closes to `CasterSummoner ModifySPNew(+20)`;
8. ordinary recast is create-if-absent / maintain-existing;
9. selectable servant Skill01 is distinct from owner-coordinated Skill11 Together passive contribution;
10. natural lifecycle exposes separate pre-death, DeathRattle, character-die-listener and later destruction surfaces;
11. BattleEvent forced cleanup is a separate muted inserted branch;
12. nearby `ConfigSummonUnit` is not battle-servant authority.

## Remaining boundaries

Data-facing work that may still be useful:

- servant Skill01 `SPBase` / resource semantics through W08;
- additional JoinSkill semantics if an exported owner/target/resource consequence is found;
- additional explicit property-sync consumers if a new source family appears.

Frozen / `engine_consumer_unavailable` at the current pin:

- passive auto-entry activation/registration timing;
- sync timing/precedence/merge algorithm;
- exact initial servant queue position and SPD→AV/requeue/tie-break;
- normal-slot accounting during owner-coordinated Skill11;
- universal natural death/DeathRattle/listener/OnDestroy/entity-removal total order;
- generic `#N` parser implementation.

These gaps must not be filled from current-game intuition or community scheduler formulas.
