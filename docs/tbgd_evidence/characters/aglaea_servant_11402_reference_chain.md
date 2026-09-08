# Aglaea — Servant 11402 battle reference chain

## Record metadata

- Concept: ordinary-combat servant/memosprite creation, numeric construction inputs, independent scheduling evidence, recast behavior, natural pre-death/death-rattle/post-death surfaces, and muted forced cleanup
- Owner context: Aglaea (`AvatarID=1402` from the ordinary avatar chain; owner identity is not asserted from the servant row itself)
- Servant: Garmentmaker (`ServantID=11402`)
- TBGD revision: `14c1d18f91a8101d610e6c523447a7517de3fae1`
- Evidence maturity: `manually_confirmed`; `#N` construction rule cross-sampled on another servant
- Battle-scope verdict: `include`
- Runtime production code changed: no

## Correction history

Two earlier statements are explicitly superseded:

1. In Aglaea Skill02's servant-creation branch, the pinned `SetActionDelay(Value=0)` targets **`Caster` (Aglaea)**, not `CasterServant`. It is not servant queue initialization evidence.
2. The exact pinned Aglaea Ability file does **not** contain a literal `ActivityOnCreate` field on the inspected creation operation. Do not report `ActivityOnCreate=false` as observed raw evidence unless a separate pinned schema/default producer is found.

The independent-schedulability conclusion for Servant 11402 remains supported by separate servant-owned Speed/action-delay operations described below.

## Confirmed battle identity chain

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
  -> ServantConfig / Memosprite
  -> Config/ConfigAbility/Servant/Servant_AglaeaServant_00_Ability.json
```

The servant row does not carry a fixed owner AvatarID. The owner relation is established by Aglaea's ordinary `CreateServant(11402)` edge and the runtime aliases such as `CasterSummoner`.

## `#N` construction parameter rule

The earlier `#4/#5/#6 unknown` state is closed at the practical producer level.

For Servant 11402:

- `SpeedSkill=140204`, `SpeedInherit="#4"`
- `HPSkill=140204`, `HPInherit="#5"`, `HPBase="#6"`

Exact pinned `ExcelOutput/AvatarSkillConfig.json` blob:

`a5416ced941c247d475b2aaa83277b9cdf474dd9`

contains `SkillID=140204` level-dependent `ParamList` rows. Manually inspected examples:

- Lv1: `[0.12, 0, 0, 0.35, 0.44, 180]`
- Lv6: `[0.21, 0, 0, 0.35, 0.572, 504]`

Therefore the servant row resolves as:

| Level sample | `#4` SpeedInherit | `#5` HPInherit | `#6` HPBase |
|---|---:|---:|---:|
| Lv1 | `0.35` | `0.44` | `180` |
| Lv6 | `0.35` | `0.572` | `504` |

Servant 11413 with `SpeedSkill/HPSkill=141304` independently follows the same positional pattern.

The supported reusable rule is:

> the corresponding `SpeedSkill` or `HPSkill` selects an `AvatarSkillConfig.SkillID` ParamList, and `#N` selects the **1-based** slot from that ParamList.

The literal generic parser implementation for the `"#N"` token is not exported. That missing parser body does not reopen the already closed producer -> SkillID -> positional-slot mapping.

## Servant character configuration

`Config/ConfigCharacter/Servant/Servant_AglaeaServant_00_Config.json` confirms:

- `$type = ServantConfig`
- Thunder damage type
- independent AI/skill/passive wiring
- Skill01 as a selectable servant action with `SPBase=10`
- `SkillP01 -> Servant_AglaeaServant_00_Passive`
- `SkillP03 -> Servant_AglaeaServant_00_BattleCry`
- `SkillP04 -> Servant_AglaeaServant_00_DeathRattle`
- JoinSkill entries
- shared `Avatar_Common_PassiveSkill` / `Servant_Common_PassiveSkill` wiring
- property-inherit configuration.

The exact config declares the passive entry abilities, but the generic GameCore rule that automatically activates/registers passive entries during `CreateServant` is not exported in this release-data corpus. Treat passive auto-entry timing as `engine_consumer_unavailable`, not as an inferred creation-time guarantee.

`SyncPropertyExceptList` explicitly excludes the speed family, including `Speed`, `BaseSpeed`, `SpeedDelta`, `SpeedAddedRatio`, `SpeedConvert` and `SpeedOverride` in the pinned config.

Therefore generic property synchronization is not authority for servant Speed. The exact creation-time versus continuous/event-driven synchronization rules for HP and other inherited properties remain unresolved.

## Distinct servant and summoner Speed/state

The servant Ability graph separately reads:

- `CasterSummoner.Speed`
- servant/self `Caster.Speed`

and contains servant-side speed/action-delay machinery. This proves summoner Speed and servant Speed are distinct runtime values and prevents flattening Garmentmaker into a live mirror of all summoner properties.

## Servant-owned scheduling mutation

The servant ConfigCharacter declares:

- `SkillP03` -> `Servant_AglaeaServant_00_BattleCry`
- `SkillP04` -> `Servant_AglaeaServant_00_DeathRattle`

with DynamicValue bindings:

- hash `1311494286` -> `SkillParam(SkillP03,index=0)`
- hash `-2017292130` -> `SkillParam(SkillP04,index=0)`

Exact pinned `ExcelOutput/AvatarServantSkillConfig.json` closes the numeric producers:

- `SkillID=1140205`, `SkillTriggerKey=SkillP03`, inspected `ParamList[0]=1`
- `SkillID=1140206`, `SkillTriggerKey=SkillP04`, inspected `ParamList[0]=20`

### BattleCry

`Servant_AglaeaServant_00_BattleCry` adds its modifier to the servant. OnStack it performs:

`ModifyActionDelay(Target=ModifierOwnerEntity, AddNormalizedValue = 0 - SkillP03[0])`

With `SkillP03[0]=1`, this is:

`ModifyActionDelay(servant, -1 normalized)`

This is direct numeric evidence that the servant owns/mutates its own scheduling state. It does **not** establish the hidden SPD→AV formula or the exact time at which passive entry abilities activate during servant creation.

### DeathRattle

`MServant_AglaeaServant_00_DeathRattle` is a formal modifier with `BehaviorFlagList=["Deathrattle"]`. Its `OnDeathrattle` callback performs:

`ModifySPNew(Target=CasterSummoner, AddValue=SkillP04[0])`

With `SkillP04[0]=20`, the raw chain closes as:

`OnDeathrattle -> ModifySPNew(CasterSummoner,+20)`

The exact player-facing meaning/cap model of internal `SP` remains W08/shared-resource work. This record preserves only the raw target and amount.

## Aglaea Skill02 create/recast behavior

The pinned ordinary Skill02 path distinguishes absence and presence of a living `CasterServant`:

- **no living servant:** `CreateServant(11402)` and perform the surrounding Aglaea/current-skill scheduling/state setup;
- **servant already present:** the changed Skill21 path operates on the existing servant with maintenance/healing behavior rather than issuing another `CreateServant`.

Therefore the inspected ordinary recast semantics are:

**create-if-absent / maintain-or-heal-existing**

not replacement-on-recast.

### Important action-delay correction in the creation branch

The exact pinned sequence includes:

```text
CreateServant(11402)
-> SetEntityPosition(Target=CasterServant, PosTarget=Caster)
-> SetActionDelay(Target=Caster, Value=0)
-> ModifyCurrentSkillDelayCost(NormalizedValue=-1)
-> ...
```

The explicit `SetActionDelay(0)` belongs to Aglaea/current-action scheduling context, not the new servant's initial queue position.

Seele and Jingliu independently show a reusable W07 distinction: ordinary current-action delay adjustment uses `ModifyCurrentSkillDelayCost`, while insert-action cases route equivalent changes through actor `ActionDelay` depending on turn ownership. The generic scheduler implementation remains outside the pinned release-data dump.

## Natural pre-death, death-rattle and post-death surfaces

The exact pinned servant passive supplies a stronger lifecycle decomposition than the earlier generic “death-rattle versus cleanup” note.

### `OnBeforeDying` — pre-death cleanup/state transfer

`MServant_AglaeaServant_Passive` registers `OnBeforeDying`. The inspected callback can:

- when the summoner's PointB2 is active and the servant carries its speed-stack modifier, read that modifier layer and transfer a keep-speed modifier to `CasterSummoner`;
- remove summoner-side battle modifiers including `MAvatar_Aglaea_00_Skill02_ChangeSkill`, `MAvatar_Aglaea_Rank06_Effect2` and `MAvatar_Aglaea_Rank06_Listen`;
- if `BattleEventCountDown` is still alive, `ForceKill` that BattleEvent with `MuteHpChange=true` and `MuteAllTriggerDeath=true`.

This establishes a **pre-death cleanup/state-transfer surface**. It does not by itself state what generic engine event runs immediately next.

### `OnDeathrattle` — trigger-enabled death-rattle work

The formal DeathRattle modifier executes its `OnDeathrattle` callback and restores the raw `+20` value to `CasterSummoner` via `ModifySPNew`.

A separate servant modifier carries both `KeepOnDeathrattle` and `RemoveWhenCasterDead`, proving selected state can survive the death-rattle interval and be removed only once caster-death state is reached. This is strong negative evidence against “destroy every modifier before death-rattle”.

### `OnListenCharacterDie` — owner post-death listener

Aglaea's owner passive `MAvatar_Aglaea_Passive` listens for `OnListenCharacterDie`. If the dead `ParamEntity` intersects `CasterServant` with `FirstTargetAliveOnly=false`, it sets the owner's internal `_Energy` working value to `0`.

This gives a pinned owner-side **character-death listener surface** after the servant is recognized as dead. The generic dispatcher body that orders this listener relative to all death-rattle/destruction callbacks is not exported.

### What is and is not closed

The pin therefore exposes distinct lifecycle stages/surfaces:

```text
servant passive OnBeforeDying
  -> death-rattle-capable state / OnDeathrattle
  -> character-death listeners such as owner OnListenCharacterDie
  -> later RemoveWhenCasterDead / OnDestroy / entity removal surfaces
```

The arrows above describe the semantic lifecycle progression evidenced by the event names/state predicates and retention flags, not a claimed universal callback queue implementation. Exact same-priority/cross-event arbitration and the final destruction/removal total order remain `engine_consumer_unavailable`.

## BattleEvent-driven muted forced cleanup

Aglaea also owns a separate BattleEvent-phase cleanup route that must not be merged into natural death.

Pinned chain:

```text
MAvatar_Aglaea_00_PassiveSkill01_BattleEvent.OnPhase1
  -> Retarget(AllLightTeam entities containing MServant_AglaeaServant_Passive)
  -> TurnInsertAbility(
       Servant_Aglaea_00_PassiveSkill01_ForceKill_Insert,
       InsertAbilityPriority=AvatarBuffOthers,
       target=that servant,
       OwnerAliveState=Anyone,
       TargetAliveState=Mask_AliveOrLimbo)
  -> forced cleanup ability
       ForceKill(Caster, MuteHpChange=true, MuteAllTriggerDeath=true)
       SetDieImmediately(Caster)
       remove owner/servant-linked battle modifiers
```

The BattleEvent modifier also force-kills its own owner with death triggers muted after scheduling the servant cleanup.

This closes a real **priority-tiered, trigger-suppressed forced cleanup branch**. The configured insert priority is source authority for that branch; the hidden global queue implementation/tie-break remains outside the pin.

Presentation waits/effects inside `ForceKill_Insert` are not promoted into logical death timing.

## BattleEvent namespace hazard

Aglaea also creates a BattleEvent with numeric ID `11402`. That BattleEvent is a separate battle object/namespace from ServantID `11402`. Numeric equality does not imply one entity or one timeline.

This is another concrete reason to track owner/type/reference edges rather than IDs alone.

## Negative knowledge — `ConfigSummonUnit` is not Garmentmaker battle authority

`Config/ConfigSummonUnit/SummonUnit_Aglaea_00_Config.json` is scene/maze/Technique-side in the inspected chain, with follow-field/collision/prop/VFX/MazeBuff/AdventureModifier behavior. It is not the ordinary Garmentmaker battle-servant definition.

Do not generalize this one negative example into a blanket exclusion of all `ConfigSummonUnit/**` records.

## Current closed claims

1. Aglaea ordinary battle graph can create `ServantID=11402`.
2. `AvatarServantConfig[11402]` supplies battle config/AI/skill IDs, HP/Speed construction references and aggro.
3. `#N` construction inputs resolve through corresponding `SpeedSkill/HPSkill` -> `AvatarSkillConfig.ParamList` 1-based slots.
4. The servant is a distinct battle entity with its own AI/skills/property wiring.
5. Generic property sync excludes the speed family; servant/summoner Speed are separately read.
6. Servant `SkillP03` numerically closes to self `ModifyActionDelay(-1 normalized)`.
7. Servant `SkillP04` numerically closes to `OnDeathrattle -> CasterSummoner ModifySPNew(+20)`.
8. Ordinary Aglaea recast is create-if-absent / maintain-existing, not replacement-on-recast.
9. Natural lifecycle data exposes separate `OnBeforeDying`, `OnDeathrattle` and owner `OnListenCharacterDie` surfaces, plus later death-dependent destruction/removal surfaces.
10. Aglaea BattleEvent `OnPhase1` can schedule `ForceKill_Insert` at `AvatarBuffOthers` priority; that branch explicitly mutes death triggers, force-kills the servant and sets it dead immediately.
11. Natural death-rattle and muted forced cleanup are distinct lifecycle branches.
12. The nearby Aglaea `ConfigSummonUnit` is not battle-servant authority.

## Remaining boundaries

- generic passive-entry activation/registration timing during `CreateServant` (`engine_consumer_unavailable` at this pin);
- exact initial servant queue position and equal-delay ordering;
- hidden SPD→AV conversion, clamp/round/requeue/tie-break rules;
- creation-time versus continuous/event-driven HP/property synchronization;
- exact universal total order/tie-break across `OnBeforeDying`, `OnDeathrattle`, `OnListenCharacterDie`, `OnDestroy` and final entity removal (`engine_consumer_unavailable`); 
- exact generic shared-resource semantics/caps for `ModifySPNew`;
- `JoinSkillList` coordinated owner-servant action semantics;
- generic `#N` parser implementation (the practical data mapping itself is closed).

If the pinned release-data corpus does not export these engine/dispatcher consumers, preserve them as explicit `blocked_evidence` / `not_proven` boundaries rather than filling them from live-game descriptions.
