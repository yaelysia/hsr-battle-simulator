# TBGD parallel archaeology integration — 2026-09-09

## Status

- Repository: `yaelysia/hsr-battle-simulator`
- PR: `#8` — `[TBGD] Establish battle evidence ledger`
- Integration input head: `5c15fc1c1c679889ca47e6ccbba1afb2c1710b2d`
- Pinned TBGD revision: `14c1d18f91a8101d610e6c523447a7517de3fae1`
- Scope: documentation/evidence only
- Runtime code changed: no

This file is the durable third parallel-integration supplement. It integrates the latest read-only lane comments that arrived after the previous repository checkpoint and provides the authoritative continuation state until the living worklist/source-family inventory are next compacted.

When this supplement conflicts with older lane comments or stale summary wording in `BATTLE_RESEARCH_WORKLIST.md` / `SOURCE_FAMILY_INVENTORY.md`, the corrected evidence files plus this supplement take precedence.

## Lane inputs integrated

### Lane A — W02/W05

Primary updated handoff/comment:

- `#issuecomment-5581271382`

Integrated mature findings:

- ordinary March `SkillID=100102` producer/binding/consumer chain remains closed;
- PointB2 lifetime expression and postfix operator evidence retained;
- ordinary main shield `AvatarStatusConfig[10010011]` has `CanDispel=true`;
- snapshot routing infrastructure (`SnapshotEntity*`, `GetSnapshot`, snapshot blacklist) is real battle data;
- independent Luka snapshot example corroborates the snapshot routing surface;
- Gepard shield-change samples show `OnListenShieldChange` is not equivalent to generic zero-shield modifier destruction;
- remaining March W05 gaps are generic GameCore Shield/snapshot/Replace/depletion semantics, not missing March data.

Durable file updated:

- repository-level `docs/tbgd_evidence/characters/march_7th_preservation_skill02_shield.md`

Lane continuation decision:

- do **not** restart March numeric discovery;
- W02/March-local W05 has reached a natural source-facing closure point;
- generic shield engine internals remain `engine_consumer_unavailable` unless a new authoritative engine source appears.

## Lane B — W14/W16

Primary updated handoff/comment:

- `#issuecomment-5581038320`

Integrated mature findings:

- ordinary scaling authority remains `HardLevelGroup.json`, not `ILHardLevelGroup`;
- typed HardLevel property reads are real data-facing battle operations;
- Stage and Monster Elite contexts can coexist, but multi-Elite slot mapping/order is not exposed;
- current ordinary HardLevel samples do not provide a clean Stage-vs-Monster conflict discriminator;
- `CharacterPhaseOverrideConfig.MonsterConfig` is the JSON runtime/config type, not `ExcelOutput/MonsterConfig` / `MonsterRow`;
- Huanlong demonstrates phase stat inputs and sibling OverrideConfig can coexist;
- `ApplyOverrideConfig=false` must not be interpreted as disabling all phase HP/Stance inputs;
- Yanqing concrete variants close phase-property producer differences;
- common `Monster_ChangePhase` acts on the existing entity and is not wave respawn;
- final configured-spawn ATK/DEF/HP/SPD/Stance arithmetic/precedence remains outside the exported implementation.

Durable file updated:

- repository-level `docs/tbgd_evidence/monsters/monster_1002011_reference_chain.md`

Lane continuation decision:

- do not restart generic final-stat formula searching in the same TBGD dump;
- W14 final configured-spawn operator is a named `engine_consumer_unavailable` subproblem;
- W16 still has source-facing value in spawn/transition/reinforcement/termination archaeology.

## Lane C — W07/W13

Latest checkpoints integrated include:

- `#issuecomment-5594568057`
- `#issuecomment-5594597961`
- `#issuecomment-5594654597`
- `#issuecomment-5594689971`
- `#issuecomment-5594706625`
- `#issuecomment-5594747146`

### W13 servant property-sync partition

Confirmed source surfaces:

- `GameCoreConstValue.ServantSyncPropertyList` exists;
- per-servant `SyncPropertyExceptList` is independent configuration;
- dedicated `AvatarServantConfig` HP/Speed construction fields are another surface;
- Aglaea excludes Speed family; Castorice independently excludes HP + Speed families;
- therefore the runtime combination rule is not safely reducible to `global list - exceptions` without the missing consumer.

Passive definition/effect bodies are closed, but generic passive auto-entry activation timing during `CreateServant` remains engine-unavailable.

### W07 OneMore protocol

Pinned shared `GlobalModifier_Common_Specific.json` defines:

- `OneMore`: lifetime/action-phase lifecycle plus `OneMore` / `LifeStepImmediately` flags;
- `OneMorePerTurn`: separate `OneMoreCount` controller with OnCreate/OnPhase1/OnActionEnd/OnListenTurnEnd/OnDestroy surfaces.

Gepard closes a turn-owner-sensitive route:

```text
revive TurnInsertAbility
-> HP restore
-> ByIsTurnOwnerEntity
     true  -> arm OneMore marker
     false -> SetActionDelay(0)
```

An ordinary W4 Claymore enemy independently consumes `OneMore` in AI selection.

Therefore OneMore, absolute delay-zero, and inserted actions are distinct source mechanisms.

### W07 Speed mutation boundary

Asta and Hanya independently show ordinary Speed buffs writing Speed-family properties without a content-side explicit remaining-ActionDelay rewrite in the relevant buff path.

Safe split:

- content authority = Speed property mutation;
- scheduler authority = already-scheduled delay/AV rescale after the mutation.

The latter remains `engine_consumer_unavailable`.

### W13 coordinated-action ownership

Pinned Aglaea/servant data distinguishes:

- servant selectable normal action: `ServantConfig.Skill01 -> Skill11_Phase01 -> Phase02 -> SkillPerformFinish`;
- owner-coordinated contribution: `Aglaea Skill11 -> TriggerParallelAbility(CasterServant) -> SkillP01-owned Skill11_Together`.

The Together path is not the servant's selectable normal-skill entry. No explicit delay mutation appears around the coordinated path, but hidden normal-slot accounting remains a scheduler boundary.

Durable files updated/added:

- repository-level `docs/tbgd_evidence/characters/aglaea_servant_11402_reference_chain.md`
- repository-level `docs/tbgd_evidence/shared/timeline_one_more_and_speed_boundary.md`

Lane continuation decision:

- C's latest useful source-facing findings are preserved;
- generic SPD→AV/queue/tie-break/rescale and passive/sync timing should not be repeatedly searched without a new engine source;
- future W07/W13 work should be narrowly triggered by a new exported consumer, resource/JoinSkill consequence, or new special-entity source.

## Lane D — W12/W10

No new durable lane comment was produced after the earlier RNG/callback handoff.

The important D findings had already been integrated before this supplement:

- Silver Wolf RandomConfig producer/choice/consumer chain;
- choice RNG distinct from application `Chance`;
- random target selection and `SetDynamicValueByRandom` as separate primitives;
- non-unit-sum `OddsList` negative evidence;
- callback/death/revive priority examples;
- RNG stream/seed, generic RandomConfig algorithm, status-probability evaluator and universal dispatcher tie-break as explicit engine boundaries.

Durable file remains:

- repository-level `docs/tbgd_evidence/shared/ordinary_rng_callback_reference_chains.md`

Continuation decision:

- do not restart the original D lane unchanged;
- reopen generic RNG/dispatcher internals only if a new authoritative engine source appears;
- otherwise W10/W12 should contribute through concrete source-facing interactions required by other active mechanisms.

## Lane E — W17 final closure

Final handoff:

- `#issuecomment-5594029984`
- `status=complete`
- `scope_completion=broad_reverse_scan_complete`
- `package_status=active_sentinel`
- `new_mechanism_candidate=none`

Final Assistant findings integrated:

- formal `AssistantAvatar` target/entity alias exists;
- global `TurnInsertAssistantAbility` scheduler/trigger definitions exist;
- pinned executable assistant Ability payloads exist and can mutate battle state;
- ordinary owner/creator and authoritative `AssistantAbilityID` injection/transport remain source-unavailable.

Classification:

**battle-real assistant infrastructure; ordinary ownership/assistant-ID transport export gap**.

W17 also corrected two stale summary premises:

1. pinned `AvatarSkillTreeConfig.json` is populated and concrete ordinary table -> ability -> shared-modifier chains exist; only generic loader/attachment implementation may remain unexported;
2. representative ordinary released/Mainline Sam chain to `DamageBehavior=1 -> DirectlyLoseHp` is closed; the old “stage-instance edge may be export-blocked” caveat is superseded for that sample.

Durable file updated:

- repository-level `docs/tbgd_evidence/shared/global_shared_reverse_scan.md`

Lane continuation decision:

- W17 broad scan is complete;
- keep W17 as an event-driven sentinel only;
- no repeated global sibling/whole-tree scan on this pin without a new ordinary consumer/source family/pin.

## Current authority boundaries that should not be reopened casually

The following have enough data-facing evidence to identify the missing layer. Repeated searching of the same TBGD release-data corpus is not meaningful progress unless a new source family is found:

- W05 generic `ShieldByCasterDefence`, snapshot capture, Replace callback order, depletion/expiry destruction;
- W07 SPD→AV, initial queue, remaining-delay rescale, requeue/clamp/rounding/tie-break;
- W10 universal callback dispatcher/tie-break/final destruction order;
- W12 RNG stream/seed, generic RandomConfig algorithm, random-range endpoint/distribution, final status-probability evaluator;
- W13 servant sync timing/merge, passive auto-entry timing, coordinated normal-slot accounting;
- W14 final configured-spawn stat operator and Stage/Monster HardLevel/Elite precedence;
- W17 Assistant owner/ID transport and CommonSkillPool executable pin payload.

These remain `engine_consumer_unavailable`, `export_gap`, or `not_proven` as applicable.

## Recommended next parallel decomposition

Do not recreate the old A/B/C/D/E assignments. Their high-value source-facing mission is largely exhausted.

A better next five-way split is:

1. **W04 — Damage resolution**: generic damage operands, DEF/resistance/crit/bonus-vulnerability layers, event emission; use actual gameplay formula understanding as the completeness model.
2. **W06 — Weakness/Toughness/Break**: hit -> toughness mutation -> broken state -> elemental break -> recovery, with arithmetic and ordering.
3. **W05 + W09 — Healing/Modifier lifecycle**: independent healing formula plus reusable modifier stacking/refresh/extend/dispel/control/DoT lifecycle; do not reopen March numeric discovery.
4. **W03 — battle execution/opcode language**: reusable opcode/selector/nested-dispatch dictionary across ordinary actors, preserving unknowns and presentation filtering.
5. **W16 — Encounter/spawn/transition/termination**: waves, delayed/reinforcement spawn, phase transitions, battle-end conditions and encounter-owned state; do not restart W14 hidden final-stat formula search.

W02/W07/W10/W12/W13/W14/W17 should become dependency/sentinel lanes unless a new source edge reopens them.

## Ledger maintenance note

The detailed durable evidence files listed above are updated by this integration.

`BATTLE_RESEARCH_WORKLIST.md` and `SOURCE_FAMILY_INVENTORY.md` may still contain summary wording that predates some of the morning lane checkpoints. Until the next compaction pass, use this supplement plus the corrected evidence files as the current continuation state. In particular, do not reintroduce:

- `AvatarSkillTreeConfig` empty/missing claims;
- unresolved March main-shield dispellability;
- W17 broad-scan-not-finished wording;
- generic OneMore unknown when the data-facing OneMore/OneMorePerTurn protocol is now closed;
- the old Sam DamageBehavior stage-edge caveat;
- assumptions that coordinated Aglaea Skill11 is the servant's selectable normal action.
