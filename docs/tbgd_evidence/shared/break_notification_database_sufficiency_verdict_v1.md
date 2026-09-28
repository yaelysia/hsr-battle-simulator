# Break notifications: database-only sufficiency verdict v1

## 1. Decision and scope

Reviewed 2026-09-28 from PR #8 head `3b1e1bdfbd08582d542ad67f104dc43e7d273716`, following checkpoint `5866961554`. Startup and pre-publication reads agree on that head and open/Draft/unmerged state. Database authority remains `DimbreathBot/TurnBasedGameData@14c1d18f91a8101d610e6c523447a7517de3fae1`.

**Decision: NO. This pinned export is not sufficient by itself to uniquely reconstruct the complete native Break-notification contract requested by the user.** In particular, its task/handler/configuration data do not determine the mapping from `TriggerBreak(Caster)` to the Break callbacks, the event-context construction, or the admission and cross-callback scheduling that would distinguish a second dispatch from another stage of the same transition. That missing contract requires evidence about the consumer, such as a build-qualified native implementation/trace or an appropriately isolated original behavior observation.

This is a **database-sufficiency conclusion**, not a newly proven game event order, a declaration that TriggerBreak is a no-op, or a claim that all Break mechanics are unknowable. The ordinary numerical models and directly authored callback bodies remain usable. The user can proceed with testing the unresolved behavior rather than waiting for another numeric-table join. Testing observable effects does not necessarily reveal the game's internal callback names; a behaviorally supported implementation must retain that distinction.

The scope is the fixed export and the exact contract above, not every private game resource, future TBGD revision, or possible indirect clue. This investigation does not claim to have read every byte of every unrelated exported file. Its reason for insufficiency is the terminal primitive-consumption boundary and the absence of a dispatch definition in the examined resolution/configuration surfaces, not a purported exhaustive keyword-absence proof. [MAIN] section 9 retains the separate compiled-consumer investigation and version qualification.

## 2. What was checked, and what the data actually supplies

All D references below use the fixed pin. Complete blob identities and named selectors identify the inspected occurrences. The earlier ordinary installer/state/element chains are reused from [MAIN], not reported as new discoveries.

| Ref | Source and extent | Complete blob / result |
| --- | --- | --- |
| D1 | `Config/GlobalConfig/GameCoreConfigPathInfo.json`, complete | `6eca8f5e8a406f37ee8e14a5b1e21438b5663f25`; directory/file registration, not a task-to-event definition |
| D2 | `Config/GlobalConfig/TargetAliasConfig.json`, start through selected team aliases; especially complete `AliasDict.Caster`, `ModifierOwnerEntity` and `CallBackModifierCaster` entries | `f5842163ac2eafc9f42316e521512b22f7a0b5fe`; resolves those names to typed target evaluators, not event-argument construction |
| D3 | `Config/GlobalConfig/PriorityConfig.json`, complete | `ec353c8fb5a0d8fa0848948d46289a32d2a6a5c5`; priority-key maps and the complete TurnBasedModifierEventConfigList |
| D4 | `Config/GlobalConfig/GameCoreConstValue.json`, selected global sections; complete CustomSwitchMap and ForbidRecallModifierEventList at replay 1068-1098 | `47ed0e027c76df398cf6e13de104933299ec1700`; a newly registered relevant event-policy input, not its native evaluator |
| D5 | `Config/GlobalConfig/ComponentDelayedTickConfig.json`, complete | `a48a2934c9c19686e3984334ac851a0e32df16d8`; adventure-dialogue/player-lock tick settings, no Break callback schedule in this file |
| D6 | `Config/ConfigGlobalTaskListTemplate/GlobalTaskListTemplate.layout.json`, complete | `c465a854a08129d2c6a7dc88a8e419d635bee368`; named template/type/offset index, not executable dispatch code |
| D7 | `Config/ConfigGlobalModifier/GlobalModifier.json`, selected first 500 lines, particularly the complete Break-listen callbacks of BattleEventAbility_Challenge_Month_35_FixSub | `df4e47faaaa1c7381cbf1e12a642c9ce42ae9ff4`; DebugLog consumers, not an observed event trace |
| D8 | `Config/GlobalConfig/JsonEnumDefineConfig.json`, selected enum maps, especially complete ModifierCustomEventType | `6947c752a58baf12737705a100062ded28bda6e6`; name/value dictionary for custom events, not the built-in Break-event dispatch algorithm |
| D9 | `Config/GlobalConfig/TargetOperationConfig.json`, selected named operations including GetActualOwner/GetAttacker/GetDefender | `c1f97a3b4c65a8204520f9a079db1d3c3db254b4`; target transformations/evaluator declarations, not an event-source assignment |

The fixed Config directory, GlobalConfig listing and global-template subtree were inspected as navigation. The latter subtree returned `truncated=false`. The attempted repository-root recursive tree returned **`truncated=true`** and is explicitly not counted as a complete corpus census. No all-file count, all-extension absence assertion or exhaustive content search is claimed. Default-branch searches for the exact new recall-list name were navigation only; D4 supplies the pinned fact.

## 3. The reference chain ends at a primitive, not an unvisited named template

The reused raw chain has two different kinds of edges:

```text
Local_ListenStanceBreak.OnBeingBreak
  -> AddModifier(holder, StanceBreakState)
       -> named definition StanceBreakState.OnCreate
            -> TriggerBreak(TargetAlias("Caster"))
                 -> AliasDict.Caster = TargetFetchCaster
                 -> primitive consumption boundary
  -> RemoveModifier(holder, MonsterAllDamageReduce)

TriggerStanceCountDown_Test.OnTriggerBreak
  -> IncludeTaskListTemplate("StanceBreak_<element>")
       -> named template body with authored output requests
```

A modifier name or IncludeTaskListTemplate name can be followed to an exported body. In contrast, the selected `RPG.GameCore.TriggerBreak` object supplies its type and target evaluator; it does not contain a template name, callback sequence, argument-construction body or deduplication rule to expand. D2 closes a previously implicit **alias-to-evaluator declaration** edge: Caster is `RPG.GameCore.TargetFetchCaster`. ModifierOwnerEntity separately maps to TargetFetchModifierOwner, and CallBackModifierCaster to TargetFetchCallBackModifierCaster. These distinctions must be retained. They do not tell us which entity a native Break invocation puts into the relevant context.

D1 registers where resources reside. D6 indexes exported named templates; an Offset there is not a native method body or a chronological event position. The selected task is not an IncludeTaskListTemplate request that can be redirected to a similar-sounding template. The earlier 4.3.0-labelled auxiliary SDK's typed TriggerBreak executor independently corroborates a compiled consumer, but its address trampoline does not fill in that consumer's behavior. This pass reuses that qualified result; it does not promote SDK metadata to fixed-pin execution evidence. [MAIN, D1, D2, D6]

## 4. Relevant global settings were not discarded as irrelevant

### 4.1 Priority configuration does not supply the missing total order

D3's complete TurnBasedModifierEventConfigList has entries for OnEnterBattle, OnLimboWaitHeal, OnPhase1, OnPhase2, OnBeforeBeingHeal, OnAfterAttack, selected character/global events and Elation-time events. It has no entries for OnTriggerBreak or OnBeingBreak. This is a file-local inventory result, not proof that those callbacks have no native priority/default.

The `StanceBreak=-70` key belongs to **OnEnterBattle**. `MonsterStanceBreak=50` belongs to **ModifierBehaviorVisualPriority**. Neither is a rank in a global sequence `OnBeingBreak -> TriggerBreak -> OnTriggerBreak`. Even a priority between handlers of one event would not, without a consumer rule, determine when another event is emitted or when nested creation hooks are drained. [D3]

### 4.2 Newly located ForbidRecall input: preserve it, do not invent its semantics

D4 explicitly lists `OnTriggerBreak` in `ForbidRecallModifierEventList`. `OnBeingBreak` is not an entry in that complete list. The adjacent `RangePropertyRecallLimit` is 3. These are real configuration facts and qualify any blanket statement that the export has no Break-related global policy input.

The acquired definition is a list, not an implementation of recall. It supplies no per-hit/per-target/bar-cycle identity, reset point, task-to-event mapping or rule equating two independently submitted events. Therefore it cannot be promoted to "all Break callbacks are deduplicated once per logical Break", "OnBeingBreak may be repeated freely", or "ignore the common-state TriggerBreak task". The meaning and scope of recall, and whether this list participates in the disputed path, still need the actual consumer. The adjacent value 3 is not assigned to Break repetition by proximity. The newly located input does not reverse the database-sufficiency verdict. [D4]

### 4.3 Event dictionaries and logging hooks are not execution records

D8's ModifierCustomEventType and the corresponding custom-event entries in D4 describe a separate custom-event interface, including DOT and TargetStancePreshow. They are not a definition that the TriggerBreak task emits the built-in Break callbacks. D7's selected OnListenBeforeTriggerBreak, OnListenBreak and OnListenEndBreak callbacks each request DebugLog("_"). They prove authored listeners exist; neither their serialized order nor their log-request text is an actual chronological trace. D5 likewise does not supply a deferred Break callback policy. [D4, D5, D7, D8]

## 5. Why more endpoints cannot uniquely answer the question

The missing information is a rule of execution, not a missing arithmetic operand. A concrete ambiguity is already visible without speculating about another character:

```text
Outer handler orders:  AddModifier(StanceBreakState); RemoveModifier(reduction)
Creation handler orders: effect; delay; TriggerBreak(Caster)
```

Those lists alone do not distinguish an executor that drains the creation work inside AddModifier from one that records it for a subsequent drain boundary. In the first interpretation the TriggerBreak request can precede the outer reduction-removal request; in the second it can follow it. Both readings retain the two authored local task orders. This is a **logical illustration of underdetermination**, not two claimed complete game implementations, not observed behavior, and not permission to select either order. No claimed emission count or damage result follows from the illustration.

The newly checked alias, priority, recall and custom-event inputs do not resolve that particular execution choice. Nor do they establish a binding from the TriggerBreak primitive to the attacker/defender notifications. The complete native contract requires those choices; thus having all the known handler bodies does not make the contract determined. This is the basis of the NO verdict. It is not based on treating an empty search result or an unavailable function as proof of some specific game behavior.

Additional database examples may still constrain a narrower observable claim. They cannot be counted as a recovered primitive implementation merely because their callback names agree. The verdict would need revisiting for a genuinely new authoritative definition or consumer trace, not for another unchanged example of these endpoints.

## 6. Hand-off boundary for the user's testing

Retain the fixed-data handler bodies, source ownership, elemental outputs and supported ordinary numerical results. Supply independent evidence for: which effects accompany one admitted ordinary Break; how the task and pre-existing notification route overlap; which state each output observes; and how another hit while broken differs from a fresh Break after recovery. Distinct targets and legitimate extra Break-formula damage must not be collapsed into one-per-attack suppression. The prior discriminators in [MAIN] remain proposed controls, not executed tests.

A game observation can support the observable behavior required by a simulator without proving that its internal event bus is identical to the game's. Record that as a behavior-derived contract rather than a fixed-database fact. An instrumented/native trace can additionally decide internal event identities where ordinary outputs cannot. Neither route requires replacing already supported formulas with guesses.

**Research decision:** stop treating this fixed-database-only dispatch route as pending another parameter or another character sample. The data-only sufficiency question is answered negatively; the exact original dispatch behavior remains unproven. No backend repair gate, broad coverage checkbox, runtime change or automatic additional notification is authorized by this record.

## 7. Actual work and publication

This continuation adds the database-sufficiency decision, the alias-resolution finding, the exact global recall-list occurrence, and the checked alternative mapping/scheduling surfaces. It reuses rather than repeats the earlier native/version and ordinary mechanic results. Validation consisted of GitHub source/configuration/metadata reads, reference and scope comparison, the logical ambiguity analysis above, and the publication checks recorded in the checkpoint. No game, simulator, test suite, native executor, extraction script or CI workflow was run. The truncated root-tree response is not complete validation. Repository access used only the GitHub connector; no runtime/lowering/IR/tests/CI/pin/mode files changed.

[MAIN]: break_notification_dispatch_and_full_chain_status_v1.md
[D1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/GlobalConfig/GameCoreConfigPathInfo.json
[D2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/GlobalConfig/TargetAliasConfig.json
[D3]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/GlobalConfig/PriorityConfig.json
[D4]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/GlobalConfig/GameCoreConstValue.json
[D5]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/GlobalConfig/ComponentDelayedTickConfig.json
[D6]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigGlobalTaskListTemplate/GlobalTaskListTemplate.layout.json
[D7]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigGlobalModifier/GlobalModifier.json
[D8]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/GlobalConfig/JsonEnumDefineConfig.json
[D9]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/GlobalConfig/TargetOperationConfig.json
