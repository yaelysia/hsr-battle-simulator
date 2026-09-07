# Aglaea — Servant 11402 battle reference chain

## Record metadata

- Concept: normal-combat servant / memosprite creation, identity, skill wiring, property relationship and death-path evidence
- Owner avatar: Aglaea (`AvatarID = 1402`)
- Servant: Garmentmaker (`ServantID = 11402`)
- TBGD revision: `14c1d18f91a8101d610e6c523447a7517de3fae1`
- Evidence maturity: `manually_confirmed`
- Battle-scope verdict: `include`
- Confidence: high for the structural edges and field identities below; inheritance arithmetic, temporal semantics and lifecycle ordering remain unresolved
- Tracking issue: #7

## Why this chain matters

A battle servant is not safely recoverable from names such as `SummonUnit`. The pinned corpus contains an Aglaea `ConfigSummonUnit` file that is scene/maze-side, while the actual battle entity is created through the `Servant` data family. This record therefore captures both the positive battle chain and a concrete false friend.

## Confirmed battle chain

```text
Avatar_Aglaea_00_Ability.json
  CreateServant(ServantID = 11402)
        |
        v
AvatarServantConfig.json
  ServantID = 11402
  AvatarID = 1402
  Config -> Servant_AglaeaServant_00_Config.json
  AIPath -> AvatarServant_CommonAI.json
  SkillIDList -> [1140201, 1140202, 1140203, 1140204]
        |
        v
ConfigCharacter/Servant/Servant_AglaeaServant_00_Config.json
  ServantConfig / Memosprite
  skill, target, AI and property-inherit wiring
        |
        v
ConfigAbility/Servant/Servant_AglaeaServant_00_Ability.json
  servant/summoner property reads, speed modifiers and death-event abilities
```

The reference edges above were inspected in the pinned raw files. They are not inferred from current-game descriptions.

## 1. Creation edge

Path:

`Config/ConfigAbility/Avatar/Avatar_Aglaea_00_Ability.json`

A manually inspected operation uses `CreateServant` with:

- `ServantID = 11402`

This establishes a battle-side creation edge from Aglaea's avatar ability graph to the servant identity in `AvatarServantConfig.json`.

The same large ability file contains `ForceKill` operations elsewhere. Their presence is **not** sufficient to claim the servant's exact cleanup/despawn rule: the owning ability context and event ordering still need to be traced before a lifecycle statement is promoted.

Classification: `mixed_requires_filter`.

## 2. Servant identity and combat metadata

Path:

`ExcelOutput/AvatarServantConfig.json`

The inspected row with `ServantID = 11402` contains:

- `AvatarID = 1402`
- `Config = "Config/ConfigCharacter/Servant/Servant_AglaeaServant_00_Config.json"`
- `AIPath = "Config/ConfigAI/AvatarServant_CommonAI.json"`
- `SkillIDList = [1140201, 1140202, 1140203, 1140204]`
- `HPBase = "#6"`
- `HPInherit = "#5"`
- `HPSkill = 140204`
- `SpeedBase = "0"`
- `SpeedInherit = "#4"`
- `SpeedSkill = 140204`
- `Aggro = 125`

Battle consequences of these fields include owner/servant identity, skill dispatch inputs, HP/speed construction inputs and aggro. The file also contains presentation metadata, so it is not safe to consume wholesale.

The strings `#4`, `#5` and `#6` are preserved exactly as raw evidence. This record does **not** assign formulas or units to those tokens until the referenced formula/value source is located and manually read.

Classification: `mixed_requires_filter`.

## 3. Servant character definition

Path:

`Config/ConfigCharacter/Servant/Servant_AglaeaServant_00_Config.json`

Confirmed structure includes:

- `$type = "ServantConfig"`
- `AvatarServantType = "Memosprite"`
- `DamageType = "Thunder"`
- combat skill definitions and target configuration
- AI references
- passive/special ability references
- property inheritance configuration

For the inspected servant skill:

- `SkillType = Servant`
- `UseType = SelectEntity`
- `SPBase = 10`
- target configuration selects an enemy and includes adjacent-target behavior
- `EntryAbility = Servant_AglaeaServant_00_Skill01_Part01`
- AI type is `ComplexSkillAI`

`JoinSkillList` and a buff-resistance blacklist are also present and remain battle-relevant candidates requiring operation-level interpretation where their exact semantics matter.

### Speed is explicitly outside generic property sync

`PropertyInheritConfig.SyncPropertyExceptList` includes the speed-family properties:

- `SpeedPercent`
- `SpeedAddedRatio`
- `Speed`
- `SpeedDelta`
- `SpeedBase`
- `SpeedConvertedRatio`

Therefore the pinned config proves a narrow but important fact: whatever generic property synchronization this configuration provides, these speed-family properties are explicitly excluded from that generic path. It does **not** by itself prove whether the remaining inherited properties are snapshotted, continuously synchronized, or refreshed at particular events.

Classification: `mixed_requires_filter`.

## 4. Servant ability graph and summoner relationship

Path:

`Config/ConfigAbility/Servant/Servant_AglaeaServant_00_Ability.json`

Manual inspection found separate reads of:

- `CasterSummoner.Speed`
- `Caster.Speed`

and speed-related working/modifier identities including:

- `MDF_ServantSpeedStack`
- `MDF_SummonerSpeedStack`
- `Servant_AglaeaServant_00_BP_ServantAddSpeed`
- `Servant_AglaeaServant_00_BP_SummonerAddSpeed`
- `Servant_AglaeaServant_00_BP_KeepSpeed`

This is direct raw evidence that the battle ability graph distinguishes the servant (`Caster`) from its summoner (`CasterSummoner`) and handles their speed values separately. Combined with the character-config speed exceptions, it is unsafe to model servant speed as a generic copy of the owner's speed.

The same ability file contains the formal modifier:

`MAvatar_AglaeaServant_00_PassiveSkill01_DeathRattle`

and death-related ability identities including:

- `Servant_AglaeaServant_00_Ability_OnDeath_RestoreEnergy`
- `Servant_AglaeaServant_00_Ability_OnBeingKilled`
- `Servant_AglaeaServant_00_Ability_OnDeathEvent`

These establish a real death/event subgraph. They do not yet establish the exact callback ordering, cleanup point, energy recipient/value, or whether every death path runs identically.

Classification: `mixed_requires_filter`.

## 5. Negative knowledge — `ConfigSummonUnit` is a false friend here

Path:

`Config/ConfigSummonUnit/SummonUnit_Aglaea_00_Config.json`

Despite the directory and filename, the manually inspected file is not the Garmentmaker battle-servant definition. Its observed structure is scene/maze/Technique-side and includes evidence such as:

- `$type = ConfigSummonUnit`
- `GroupConfig = "FollowField"`
- collision / near-target triggers
- prop/NPC hit handling
- VFX and scene callbacks
- `AddMazeBuff`
- `AddAdventureModifier`
- scene-side summon removal behavior

For normal-combat archaeology this inspected Aglaea file is therefore **not** the battle servant authority. It is retained as negative knowledge because a filename-driven crawler would otherwise be likely to classify it incorrectly.

This does not justify blanket-excluding the entire `ConfigSummonUnit/**` family. Other files in that family remain `unresolved` until inspected or made reachable from a normal-combat chain.

## Battle-semantics established by this record

The pinned raw corpus now supports all of the following structural claims:

1. Aglaea's battle ability graph can create `ServantID 11402` through a `CreateServant` operation.
2. `AvatarServantConfig[11402]` binds that servant to owner avatar `1402`, a servant character config, a common servant AI path and four skill IDs.
3. The servant is explicitly typed as a `Memosprite` in its battle character config.
4. The servant carries its own combat skill/target/AI wiring.
5. Generic property synchronization explicitly excludes speed-family properties.
6. The servant ability graph separately addresses `CasterSummoner.Speed` and `Caster.Speed` and contains dedicated speed modifier families.
7. A concrete servant death/event subgraph exists.
8. `ConfigSummonUnit/SummonUnit_Aglaea_00_Config.json` is not a substitute for the battle servant chain.

These facts justify representing servant/memosprite identity as a distinct battle entity relationship. They are **not** yet enough to reproduce all numeric or temporal servant semantics.

## Unresolved before stronger promotion

- Locate and decode the pinned source behind `HPBase = #6`, `HPInherit = #5` and `SpeedInherit = #4`.
- Determine which properties are copied/synchronized and the exact temporal rule: creation snapshot, continuous sync, event refresh, or another mechanism.
- Trace the exact `CreateServant` owning ability/event and any normal-battle creation variants.
- Trace lifetime, countdown, replacement, `ForceKill`, death and final cleanup/despawn ordering.
- Prove action-value / turn-queue ownership from raw scheduling operations rather than inferring it from separate speed state or live behavior.
- Determine servant resource ownership and the semantic meaning of the observed `SPBase = 10` in this servant skill context.
- Resolve DeathRattle callback order, energy restoration destination/value and interaction with forced death/removal.
- Trace `JoinSkillList` semantics and any owner-servant joint-action path.

## External corroboration

Current live-game descriptions and independent mechanics references can corroborate that Garmentmaker acts as a separate memosprite with owner-linked stats and dedicated action/death behavior. Those sources are secondary only: they must not fill the unresolved `#4/#5/#6`, snapshot/sync, cleanup or ordering gaps at the pinned TBGD revision.
