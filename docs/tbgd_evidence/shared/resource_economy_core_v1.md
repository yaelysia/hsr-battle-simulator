# Resource Economy Core v1

## 1. Metadata, authority and bounded result

- Thread: `R4-RESOURCE-ECONOMY-CORE-V1`; PR #8; research date: 2026-09-10.
- Research baseline: `af9b3761d3857237ed71251ab5068589d1a0f57f`; the actual PR head matched this baseline at startup.
- Raw authority: `DimbreathBot/TurnBasedGameData@14c1d18f91a8101d610e6c523447a7517de3fae1`. Raw links below are immutable at this pin.
- Evidence maturity: `manually_confirmed` for the identified inputs, bindings, operations, callbacks and ordinary reference edges. Existing numerical/ownership closures are explicitly reused, not counted as new discoveries.
- Authority class: `battle_authoritative` for the retained input/operation edges; `mixed_requires_filter` for containing files. Scope verdict: `include` at those edges and `mixed` at file level.
- Result: **complete for bounded Resource Economy Core v1**, not `W08 mechanism_closed`, a resource-opcode census, a complete economy simulation, or numerical runtime verification.
- Gameplay-name mapping: `raw_sp_semantics=partial`; `raw_bp_semantics=partial`. The actor/ultimate-associated versus team/action-resource distinction is strongly supported; exact UI-name equivalence and native mathematics are not promoted to closed facts.
- Runtime/business/lowering/IR/test changes: **none**. Fast, Direct, simulator execution and numerical reproduction: **not performed / not claimed**.
- Publication head and validation belong to the actual PR commit/checkpoint; this record does not predict its own commit SHA.

Authority remains BATTLE_SCOPE/evidence contract -> current worklist/inventory and corrected detailed evidence -> historical reconciliation/comments. Reuse [R0] parameter/selector/dispatch vocabulary, [R1] damage operands, [R2] frozen Stance boundary, [R3] Natasha/Gallagher healing entries, [SERVANT] owner/servant identity, and [GLOBAL] ordinary bootstrap context. None is rewritten here. Wide uncompleted worklist items do not require redoing their already-closed narrow examples.

## 2. Terminology and investigation model

Until the separate mapping assessment in section 14, use **raw-SP** and **raw-BP**, not Energy or Skill Points. A spelling such as SP, BP, EnergyBar, BoostPoint, Ratio or Base is not by itself a resource identity, a state owner, or an arithmetic operator.

The navigation/completeness model is two potentially distinct resources: an actor-addressed state with skill requirements and targeted changes, and a team state with action-related gain/cost inputs. A satisfactory bounded result must distinguish state input, requested change, application/gating, and presentation. This model did not supply any missing source value or formula. No new gameplay observation, live-version website or external UI-name corroboration is claimed.

The actual investigation followed the ordinary Natasha entries already established in R3, their selected table rows and common passive; the mature servant DeathRattle; the heterogeneous Gallagher heal; and concrete ordinary team/AI references. The AI material is read only for its resource source and consumer, **not** to start W11/W15 or recover the AI decision algorithm.

## 3. Source map: two namespaces, several independent surfaces

| Surface | Literal input / source | Owner or scope actually evidenced | Ordinary consumer or endpoint | Semantic status and native limit |
| --- | --- | --- | --- | --- |
| `AvatarConfig.SPNeed` | Natasha 1105: 90; Gallagher 1301: 110. [A] | Actor configuration, qualified by AvatarID and its explicit skill/config references | Natasha's linked 110503 row independently declares SPNeed=90 and resolves to an Ultra entry. [K][N] | Actor-level requirement input closed; field precedence, current-state comparison and debit consumer unavailable. Not automatically MaxSP. |
| `AvatarSkillConfig.SPBase` | Natasha Skill01/02/03 Lv1: 20/30/5. [K] | The selected skill row, not its healing/damage target | Same skill's requests expose SPHitRatio or ModifySPNew.AddRatio. [N][NA] | Inputs and request sites closed separately; no exported SPBase-to-AddRatio reference-base bridge recovered. |
| `ModifySPNew` | Ability/callback operation with explicit target and value/ratio operands. [NA][SA][CA] | Caster, CasterSummoner or modifier holder, according to the actual occurrence | Typed native resource-mutation request | Actor-addressed raw-SP operation surface; final state getter, modifiers, clamp and commit are engine-owned. |
| `SPHitRatio` | Fixed 1 in Natasha AttackData and Gallagher HealHP. [NA][GA] | Operand of an attack/heal request; **not** an independently selected resource recipient | DamageByAttackProperty / HealHP native consumer | Resource-adjacent execution input, not a display/scoring field in these layouts. Recipient, base and relation to ModifySPNew remain unclosed. |
| `TeamBPFloatStart` | Fixed exported constant 3. [GC] | Team-BP configuration namespace; ordinary team-state reading is separately evidenced by AI. [AI] | Native team/battle initialization boundary; StageCommonTemplate exposes CreatePlayerTeam/StartBattle, not the assignment. [ST] | Start input closed; no proof that every encounter starts at 3. |
| `TeamBPFloatMax` | Fixed exported constant 5; conversion input `TeamBPFloatToIntegerRatio=1`. [GC] | Same configured team namespace | Native maximum/conversion/clamp boundary | Configured maximum input closed, not an invariant effective cap for every build/mode. |
| `BPAdd` | Natasha 110501 Lv1: 1. [K] | Skill/action row | Ordinary Skill01 entry; BP-consuming/reading AI context is independently visible. [N][AI] | Authored gain input closed; automatic row-to-team mutation and timing remain engine-owned. |
| `BPNeed` | Natasha 110501/110502/110503 Lv1: -1/1/-1. [K] | Skill/action row | Skill/Ultra/basic entries; DefaultBPSkill_PreCheck, TeamBoostPoint and MaxTeamBPCost source surfaces. [N][AI] | Requirement/cost input closed; -1 sentinel meaning, actual affordability and debit are not inferred. |

The same ordinary action can contain both SPBase and BPNeed. They are not alternate spellings of one field. A per-actor mutation target must not be flattened into a single team pool; conversely the TeamBoostPoint reader must not be reinterpreted as an individual character's SP balance.

## 4. Natasha primary: identity, action and selected fields

`AvatarConfig[1105]` is released and explicitly names Natasha's CharacterConfig, with SkillList containing 110501, 110502 and 110503. The configuration is an ordinary playable-actor owner, not a same-number rank/status record. [A]

| SkillID / Level | Trigger | CharacterConfig SkillType | Table AttackType | SPBase | Skill-row SPNeed | BPNeed | BPAdd |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 110501 / 1 | Skill01 | omitted | Normal | 20 | omitted | -1 | 1 |
| 110502 / 1 | Skill02 | Skill | BPSkill | 30 | omitted | 1 | omitted |
| 110503 / 1 | Skill03 | Ultra | Ultra | 5 | 90 | -1 | omitted |

This is a **field projection of three inspected rows**, not the complete JSON objects. `omitted` means absent from that occurrence, not zero/false/free. CharacterConfig SkillType and table AttackType are separate schema fields. All three rows also serialize `SPMultipleRatio=0.5`; the global constant with that spelling is separately 0. Neither value is inserted into a resource formula or used to select a precedence rule. [K][N][GC]

R3 already closes Skill02 `SelectEntity/FriendSelect -> Avatar_Natasha_00_Skill02_Phase01 -> TriggerAbility(Caster, Phase02)`. The direct heal and HOT application address AbilityTargetEntity, whereas the later resource operation addresses **Caster**. Choosing a healed ally does not make that ally the recipient of this ModifySPNew. [R3][N][NA]

Skill01's `EnemySelect` entry reaches its same-caster Phase02 projectile-hit damage. Skill03's `Ultra` entry uses AllTeamMember and a separate PrepareAbility; those target/readiness-presentation declarations are not a recovered resource validation algorithm. [N][NA]

## 5. RES-01 — actor-level raw-SP requirement and Ultra relationship

The exact ordinary join is:

```text
AvatarConfig[1105]: SPNeed.Value=90; SkillList includes 110503
 -> AvatarSkillConfig[110503,Level=1]
      SkillTriggerKey=Skill03; SPNeed.Value=90; AttackType=Ultra
 -> Natasha CharacterConfig.SkillList[Name=Skill03]
      SkillType=Ultra; EntryAbility=Avatar_Natasha_00_Skill03_Phase01
      PrepareAbility=Avatar_Natasha_00_Skill03_EnterReady
```

This establishes an **actor requirement input and a linked Ultra requirement input**. Equal values are corroborating context after the explicit actor/skill/trigger join; equality alone is not proof that the two fields share a loader or which field wins an override. Gallagher's separate released actor row has SPNeed=110 and its own skill/config references, providing an unrelated actor-level requirement cross-check. [A][K][N][R3]

No exported current-SP-versus-SPNeed comparison, resource reservation, debit, refund or concurrent Ultra transaction is recovered in the selected Natasha entry/prepare/phase chain. `PrepareAbility`, AI priority and a skill-button/icon name are not such a comparison. The ordinary AI file referenced by Natasha terminates in `UseSkillByComplexSkillAI`; that native task is not its own implementation. The inspected `DefaultUltra` factor group supplies decision factors, not an explicit SPNeed affordability equation. [NA][AAI][AI]

**Boundary:** `ultimate raw-SP requirement/gate/debit consumer = engine_consumer_unavailable`. Do not infer currentSP >= 90, subtract 90, reset to zero, SPNeed=maximum, or immediate insertion eligibility from this record.

## 6. RES-02 / RES-04 — skill base versus AddRatio

The complete primary resource request at `Avatar_Natasha_00_Skill02_Phase02.OnStart[8]` is: [NA]

```json
{
  "$type": "RPG.GameCore.ModifySPNew",
  "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"},
  "AddRatio": {"IsDynamic": false, "FixedValue": {"Value": 1}}
}
```

The same ability's direct HealHP and HOT installation occur at separate authored sites. Its selected skill row exposes SPBase=30, but this ModifySPNew object has **no literal SPBase field, property getter, DynamicHash binding, explicit reference-base selector, AddValue or clamp operand**. A native consumer may consult skill context; its lookup/precedence is not exported here. [K][NA]

The Skill03 Phase02 resource request likewise addresses Caster with fixed AddRatio=1 after its authored heal site, while its row has SPBase=5. This is a useful same-actor discrimination: identical ratio operands accompany different skill inputs. It **does not** prove that their final additions are 30 and 5. [K][NA]

Retain both known endpoints:

```text
selected skill row SPBase                       [input closed]
same skill invocation ModifySPNew.AddRatio      [request closed]
SPBase -> native reference-base selection       [relation unavailable]
reference base + ratio -> final resource change [engine boundary]
```

Do not replace AddRatio=1 with one raw-SP unit, 100 percent of maximum, a full refill, or 100 percent of SPBase. Missing ratio defaults and the interaction with SPMultipleRatio, regeneration modifiers, reductions or negative operands remain unknown. The notation “ratio operand” preserves the schema distinction; it is not a derived multiplier formula.

## 7. RES-03 — Aglaea servant AddValue cross-sample

Reuse R0 and [SERVANT]'s ordinary owner/CreateServant11402/servant-skill identity; do not reopen construction, passive auto-entry or death order. Their already-closed producer is `AvatarServantSkillConfig[1140206,Level=3]`, `SkillTriggerKey=SkillP04`, `ParamList[0]=20`. The typed binding and actual callback were reread at this pin for R4. [SK][SC][SA]

```text
servant SkillP04 / ParamList[0]=20
 -> CharacterConfig hash -2017292130
      ReadInfo(Type=SkillParam, TriggerKey=SkillP04, Index=0)
 -> EntryAbility Servant_AglaeaServant_00_DeathRattle
 -> OnStart AddModifier(Caster, MServant_AglaeaServant_00_DeathRattle)
 -> modifier.OnDeathrattle.CallbackConfig[0]
      ModifySPNew(TargetType=CasterSummoner, AddValue=single-hash read)
```

The complete mutation request is:

```json
{
  "$type": "RPG.GameCore.ModifySPNew",
  "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "CasterSummoner"},
  "AddValue": {
    "IsDynamic": true,
    "PostfixExpr": {"OpCodes": "AQAR", "FixedValues": [], "DynamicHashes": [-2017292130]}
  }
}
```

The **direct numeric AddValue input is +20**. The operation recipient is the summoner, not the servant modifier holder, the last attacked target or the whole team. An input of 20 is not a demonstrated post-clamp balance increase of exactly 20. Regeneration amplification/bypass, overflow, native source attribution and surviving-target checks are not supplied by the operand. [R0][SERVANT][SC][SA]

### Another ordinary AddValue producer, without another character survey

Natasha explicitly installs `Avatar_Common_PassiveSkill` through PassiveSkill02. That ability injects fixed `MDF_AddValue=10` into `Local_SPAdd` on AbilityTargetEntity in its Caster-targeted invocation. Its definition declares hash901482104 and consumes it in ModifySPNew on **ModifierOwnerEntity**. [N][CA]

The actual event is **OnTriggerDeath**. The local predicate is **ByCompareMonsterID(ParamEntity, TargetMonsterID=9001013, Inverse=true)**. Preserve this literal exception; do not substitute an inferred monster-kind/tag predicate, universal kill-credit rule, or OnBeingAttacked event. `Stacking=Replace` is explicit but its generic lifecycle is not investigated. The retained causal chain is installation -> conditional callback -> AddValue request, not universal death chronology. [CA]

## 8. AddValue and AddRatio: what the comparison closes

| Question | Source-backed result | Still unavailable |
| --- | --- | --- |
| Are these two operand surfaces? | Yes: Natasha explicitly supplies AddRatio; the servant and Local_SPAdd explicitly supply AddValue. [NA][SA][CA] | They are not shown to be interchangeable. |
| Is AddValue a supplied number? | Yes: typed skill parameter 20 or explicitly injected 10 reaches that field. | Effective delta, amplification and clamp. |
| What is AddRatio relative to? | No explicit reference-base producer/selector is serialized in the inspected requests. | Whether SPBase, maximum/current state, or another native input supplies the base. |
| Can both coexist? | None of these complete inspected objects serializes both fields. | Coexistence legality, omitted defaults, additive composition and precedence; no corpus-wide exclusion is claimed. |
| Is there a final state write? | ModifySPNew is the explicit state-facing request endpoint. | Native state storage, getter/redirection, arithmetic, cap, event emission and atomicity. |

These entries reuse R0 P1/P6/P9, E1/E5/E6 and D7. They do not create a second formula language or introduce any simulator implementation.

## 9. RES-05 — SPHitRatio: actual classification, not a guessed award

| Ordinary occurrence | Exact placement / operand | Context and consequence limit |
| --- | --- | --- |
| Natasha Skill01 Phase02, FireProjectile.OnProjectileHit[0] | `DamageByAttackProperty.AttackProperty.SPHitRatio = fixed 1` inside typed AttackData; DisplayData is a separate object | Performer remains Natasha; the damage target is AbilityTargetEntity. The field is an execution operand, not display jitter or scoring output. Its resource recipient is not serialized here. [NA] |
| Gallagher Skill02 Phase02.OnStart[4] | `HealHP.SPHitRatio = fixed 1` at operation level, alongside ModifyValue hash2082775117 | Ordinary selected-ally heal with explicit inherent-target transfer, already closed in R3. It is not an AttackData member in this layout. [R3][GA] |
| Natasha Skill02 direct HealHP | SPHitRatio is omitted; a separate later ModifySPNew supplies AddRatio=1 | This is a different authored request layout. Do not backfill an implicit SPHitRatio or prove equivalence of the two authoring patterns. [R3][NA] |

**Classification:** `source-facing attack/heal resource-adjacent operand`, with `SPHitRatio -> native resource attribution/evaluation` remaining **partial / engine_consumer_unavailable**. Its location in executable requests distinguishes it from HUD counters. Its spelling alone does not prove attacker raw-SP gain, target raw-SP gain, raw-BP gain, a per-hit grant, or SPBase multiplication.

No relationship between number of visual hits, logical damage occurrences, SPHitRatio and total resource award is derived. No duplicate-award suppression, hit-finish aggregation, overheal-dependent award, death award, SPHitBase linkage or rounding rule is supplied. R1's monster SPHitRatio occurrence remains a reusable structural anchor, not a new numerical resource rule. [R1]

## 10. RES-06 / RES-07 — raw-BP configuration and ordinary bootstrap

The following is a projection of the actual global constants, not a reconstructed state object: [GC]

```json
{
  "TeamBPFloatStart": {"Value": 3},
  "TeamBPFloatMax": {"Value": 5},
  "TeamBPFloatToIntegerRatio": {"Value": 1}
}
```

The global object also has TurnAddBoostPoint=0 and RoundAddBoostPoint=2. They remain adjacent raw configuration only: no automatic turn/round award is recovered from their names.

For ordinary bootstrap, reuse [GLOBAL]'s StageCommonTemplate ownership and reread the actual pinned graph. The inspected **OnStartSequece** includes `AddStageAbilityByName(StageAbility_BattleCommonRule)`, binding/creation work, **CreatePlayerTeam**, and later **StartBattle**. These are source-facing bootstrap endpoints. Neither CreatePlayerTeam nor StartBattle in this graph serializes the three TeamBP values or a field-to-state assignment. The graph is mixed; BGM, transition, camera and UI tasks do not initialize BP merely by being nearby. [ST]

**Closure:** TeamBP configured start/max/conversion inputs exist; an ordinary player-team bootstrap exists. **Not closed:** which native team-state object receives them, default-versus-encounter/build overrides, entry persistence, initialization arithmetic, conversion rounding, and effective cap. `CreatePlayerTeam -> TeamBP initialization implementation` is an explicit **engine_consumer_unavailable** boundary, not a proof that the starting balance is always 3.

## 11. RES-08 / RES-09 — action BPAdd and BPNeed

The primary basic action 110501 carries BPAdd=1, the primary Skill02 110502 carries BPNeed=1, and the linked Ultra 110503 carries BPNeed=-1 without BPAdd. Each is attached to a real ordinary skill/config/entry chain, not inferred from a decimal ID suffix or from a skill label. [A][K][N]

This closes **authored action gain/requirement inputs**. It does not recover an executable `BPAdd -> team.balance += value` or `BPNeed -> affordability check -> debit` implementation. The inspected Natasha phase graphs contain their specific damage/heal/resource requests but do not spell out that generic table consumption. In particular, the actor-addressed ModifySPNew is **not substituted for a BP mutation** just to complete the diagram. [NA]

`BPNeed=-1` is a real serialized value. Its sentinel interpretation, whether absence behaves the same way, cost discounts/substitution, refunds, extra actions, cancellation and timing are left to the missing native skill resource consumer. Do not rewrite -1 to 0 or to an actual negative cost.

## 12. RES-10 — an ordinary BP reader and decision-plane consumer

The primary CharacterConfig supplies concrete navigation, rather than a whole-tree search:

```text
Natasha Skill02
 -> ComplexSkillAI.Groups[GroupName=DefaultBPSkill]
 -> Global_FactorGroups.GroupsMap.DefaultBPSkill.Factors[0]
      Source.$type = RPG.GameCore.ComplexSkillAIBattleGlobalData
      Source.DataType = TeamBoostPoint
 -> configured mapper -> AI factor evaluation [native consumer]
```

Natasha also references `DefaultBPSkill_PreCheck`. That group's exported factors include `ComplexSkillAISourceMaxTeamBPCost`, TeamBoostPoint reads, `ComplexSkillAIPostProcessPreCheckFail` and other conditional factors. TeamLight member-combination/turn-owner contexts appear in the actual groups. This is ordinary **team-resource reading and resource-sensitive decision input**, not a display-only number. It supplies an independent discriminator beyond the names of the three global constants. [N][AI]

The global data getter does not serialize its own team selector. Therefore the safe owner description is **a team-scoped battle resource observed in ordinary TeamLight-facing action-selection context**; an exact native storage address, universal side resolver, sharing with the opposing team or player/servant exception policy is not established.

Crucially, AI factor mapping/precheck is not the authoritative externally legal action gate. For example the inspected DefaultBPSkill mapper serializes breakpoints 1.5 and 5; those are not rewritten into “a Skill costs two” or “one BP is insufficient.” Adjacent tags, products and early-exit/score behavior are not expanded into an AI algorithm. Natasha's referenced AI file reaches native `UseSkillByComplexSkillAI` / `ComplexSkillAIAxis`; its `AIName=Monster_Common_SequenceThree` string does not invalidate the actual AvatarConfig caller. [AI][AAI]

**Remaining gate:** actual selected-skill BPNeed resolution, affordability, reservation, debit/refund and BPAdd delivery remain **engine_consumer_unavailable**. No new W11/W15 implementation or full AI study is performed.

## 13. Resource-flow diagrams, with the missing joins retained

```text
raw-SP:
Natasha actor SPNeed + linked Ultra row SPNeed
 -> requirement input                              [closed]
 -> current-state gate / consume                    [native boundary]
Natasha Skill02/03 selected row SPBase
 -> native AddRatio reference-base selection        [unavailable relation]
same actor phase ModifySPNew(Caster,AddRatio=1)      [request closed]
servant parameter20 -> ModifySPNew(CasterSummoner) [AddValue input closed]
 -> actual raw-SP balance change / cap / event      [native boundary]

raw-BP:
TeamBPFloatStart/Max/ToIntegerRatio                 [inputs closed]
ordinary CreatePlayerTeam / StartBattle            [bootstrap sites closed]
 -> initial team-BP state                           [native boundary]
ordinary TeamBoostPoint AI read                    [reader/consumer closed]
Skill01 BPAdd / Skill02 BPNeed                     [action inputs closed]
 -> gain / affordability / cost / cap               [native boundary]
```

These are evidence diagrams, not proposed IR or runtime pipelines. Native implementation arrows are not silently upgraded by their position in the diagram.

## 14. Gameplay semantic mapping: strength, not formula recovery

| Interpretation | Independent supporting evidence | Permitted wording / remaining limit |
| --- | --- | --- |
| raw-SP belongs to an actor/ultimate-associated resource domain | Actor SPNeed and explicit linked Ultra requirement; same-caster resource requests in ordinary skills; a servant callback targets its summoner rather than a team. [A][K][N][NA][SA] | **Strongly supported interpretation:** actor ultimate-energy-like resource. Exact UI-name mapping remains partial because no UI semantic bridge or external corroboration is used here. Native state/requirement/gain formulas remain unavailable. |
| raw-BP belongs to a shared action-resource domain | Team start/max inputs; distinct basic gain versus Skill requirement fields; ordinary typed TeamBoostPoint reader and MaxTeamBPCost decision surface. [GC][K][N][AI] | **Strongly supported interpretation:** shared skill-point-like action resource. This is not merely a 3/5 numerical resemblance. Exact UI-name equivalence, native side resolution and cost/gain implementation remain partial. |
| The two domains should not be merged | SPBase and BPNeed coexist on the same ordinary skill; actor/summoner-targeted writes and battle-global team reads expose different addressing; Ultra requirements and basic/Skill BP fields have distinct topology | Source-facing namespace separation is closed for these samples. This does not prove that every field containing the letters SP/BP in every source family belongs to one of them. |

Thus `raw_sp_semantics=partial` and `raw_bp_semantics=partial` are compatible with bounded R4 completion. The card permits a named native boundary; **semantic interpretation strongly supported** is never reported as **runtime arithmetic verified**. Canonical UI names would need an additional concrete semantic bridge/corroboration, and would still not supply missing mathematics.

## 15. RES-11 — initial, maximum, generation, consumption and clamp

| Dimension | raw-SP result | raw-BP result |
| --- | --- | --- |
| Initial | No baseline initial-value assignment is closed for the selected Natasha chain. No default 0, full state or carry-over policy supplied. | Configured start input 3 closed; native initialization and actual encounter starting balance unclosed. |
| Maximum | SPNeed is a requirement input, **not** a recovered MaxSP constructor or clamp bound. | Configured TeamBPFloatMax=5 closed; effective maximum, overrides and enforcement unclosed. |
| Requirement | Actor90 and linked Ultra90 closed, with unrelated actor110 cross-check. | Skill02 BPNeed=1 closed; -1 values retained in other inspected actions. |
| Generation | Targeted AddValue and AddRatio requests closed; final addition and ratio base unclosed. SPHitRatio remains separately classified. | BPAdd=1 input closed; native delivery unclosed. Ordinary team-state reader confirms a non-UI consumption surface. |
| Consumption | No negative ModifySPNew/debit/reset is substituted for the missing Ultra consume implementation. | BPNeed input is not an observed deduction; actual debit/reservation/refund unclosed. |
| Clamp / conversion | Native amplification, cap/overflow and rounding unavailable. | Native clamp/overflow and integer conversion unavailable despite conversion input1. |

None of the omitted fields in a request is filled from these constants. Resource legality, final state and emitted payloads are not reconstructible from a HUD display. No generic formula or implicit default is proposed.

## 16. Local callbacks and timing

The authored dependencies are Natasha's skill invocation reaching ModifySPNew after its separate heal/HOT sites; the servant passive installing the DeathRattle modifier whose OnDeathrattle submits an owner-addressed request; and common-passive installation feeding a conditional OnTriggerDeath AddValue request. The selected Ultra also contains its own later AddRatio site. [NA][SC][SA][CA]

This identifies **where requests originate**, not the final order of same-frame balance changes, death listeners, HP changes, pending Ultra insertion, UI updates or action completion. Serialized task order is not a recovered universal dispatcher. No W07/W10 scheduling rule, death total order or immediate-read visibility is inferred.

## 17. RES-12 — UI and resource false friends

The servant `MServant_AglaeaServant_00_AddSpeed.OnDestroy` calls **SetSummonerEnergyBarState** on CasterSummoner, with Active=False, BarType=Number, a dynamic MaxCount, CurrentCount=0, and an icon/fraction configuration. The same file separately contains the actual DeathRattle ModifySPNew. A display count reset to 0 is **not** a raw-SP reset to 0; the two operations are not interchangeable merely because they share a recipient or the word Energy. [SA]

Natasha's post-resource `Retarget(ByRandom=true,MaxNumber=1)` has a CharacterPlayVO(ReceiveHealing) continuation. It chooses a voice performer, not a random resource recipient or a random resource grant. Its execution-context selection must not be promoted into raw-SP targeting. [NA]

Other negative knowledge: skill icons/Ultra ready animations do not implement a requirement predicate; an AI factor score is not the resource balance or an external legality decision; SPMultipleRatio is not given an operator by its spelling; a parameter named ShowValue can have a real non-display consumer as R3 established; same numeric value and same hash do not identify a producer across namespaces. [R0][R3]

## 18. Reusable RES dictionary

| ID | Reusable source-facing vocabulary | Anchor and mandatory boundary |
| --- | --- | --- |
| RES-01 | Actor-qualified raw-SP requirement and explicitly linked Ultra requirement | Natasha/A/K/N and Gallagher/A; native gate, precedence, maximum and debit remain distinct. |
| RES-02 | Skill-qualified SPBase input | Natasha three-row comparison; not a proven AddRatio base lookup. |
| RES-03 | ModifySPNew.AddValue numeric input, with recipient retained | Servant20 -> CasterSummoner; common10 -> holder; input is not post-clamp delta. |
| RES-04 | ModifySPNew.AddRatio input | Natasha Skill02/03 -> Caster, fixed1; reference base and coexistence policy unknown. |
| RES-05 | SPHitRatio in attack/heal execution layout | Natasha AttackData versus Gallagher HealHP; recipient/formula unclosed, not a UI number. |
| RES-06 | Configured team-BP start | GC value3, ST ordinary bootstrap; assignment/overrides unclosed. |
| RES-07 | Configured team-BP maximum/conversion | GC values5/1; no clamp or rounding algorithm inferred. |
| RES-08 | Skill-row BPAdd | Natasha basic1; automatic native gain remains separate. |
| RES-09 | Skill-row BPNeed | Natasha -1/1/-1; no inferred -1 sentinel/default behavior. |
| RES-10 | Decision-plane team resource reader and native gate boundary | Natasha -> DefaultBPSkill/PreCheck -> TeamBoostPoint/MaxTeamBPCost; not external affordability. |
| RES-11 | Requirement / initial / max / change / cap are different contracts | Both namespace tables; never derive one from another solely by plausible values. |
| RES-12 | Presentation-counter versus resource-mutation discrimination | SetSummonerEnergyBarState and voice selection versus ModifySPNew; consumer-based classification. |

This dictionary does not assert a complete resource instruction set. A new sample must still identify its actor/skill family, level or explicit value, current invocation target, actual consumer and omitted defaults. Actor-specific gauges are not forced into raw-SP/raw-BP.

## 19. Evidence partition

`closed` always means the stated occurrence/input/edge, not its entire runtime mechanism. `partial` retains an unproved relation or interpretation. `engine_consumer_unavailable` names a native implementation after the inspected source surface. No new corpus-wide `export_gap` is asserted from a failed search or failed transport.

| Resource layer | Status | Exact extent / residual |
| --- | --- | --- |
| raw-SP ownership | closed + partial | Actor-qualified requirements and entity-targeted mutations; native storage/redirection and universal sharing unclosed. |
| raw-SP requirement | closed + engine_consumer_unavailable | Natasha actor/Ultra input90; unrelated actor110; gate/debit consumer unavailable. |
| raw-SP initial value | partial | No baseline initial input/assignment established; no zero/full/persistence guess. |
| raw-SP maximum | partial + engine_consumer_unavailable | Requirement is not maximum; native capacity constructor/clamp unclosed. |
| raw-SP generation | closed + engine_consumer_unavailable | Source requests and inputs closed; final delta unclosed. |
| raw-SP consumption | engine_consumer_unavailable | Ultra field/entry inspected; reservation/debit/refund/reset not recovered. |
| ModifySPNew AddValue | closed + engine_consumer_unavailable | Servant20 and common10, real recipient/callback; effective change unclosed. |
| ModifySPNew AddRatio | closed + engine_consumer_unavailable | Two Natasha sites with ratio1; reference-base selection unclosed. |
| SPBase relationship | partial + engine_consumer_unavailable | Three selected row inputs and same-skill request endpoints; native bridge unavailable. |
| SPHitRatio relationship | partial + engine_consumer_unavailable | Real damage/heal resource-adjacent operands; award recipient/base/aggregation unclosed. |
| raw-BP ownership | closed + partial | Ordinary battle-global TeamBoostPoint reader in team-facing context; native side/state resolution unclosed. |
| raw-BP initial | closed + engine_consumer_unavailable | Configured start3; actual bootstrap assignment/overrides unavailable. |
| raw-BP max | closed + engine_consumer_unavailable | Configured max5/conversion1; effective cap and conversion unavailable. |
| BPAdd | closed | Actual Natasha basic row input1 and action identity. |
| BPNeed | closed | Actual primary row values, including -1 without reinterpretation. |
| BP gain | partial + engine_consumer_unavailable | Authored BPAdd and ordinary team reader; automatic mutation implementation unclosed. |
| BP consumption | partial + engine_consumer_unavailable | Authored BPNeed and cost-sensitive AI surface; actual debit unclosed. |
| BP action gating | partial + engine_consumer_unavailable | Ordinary AI precheck/read consumer; external legal-action consumer unavailable. |
| resource clamp | engine_consumer_unavailable | Both namespaces, including effective limits/overflow/rounding. |
| UI counters | closed | Concrete Number-bar/icon and voice-only false friends distinguished from mutation. |
| semantic mapping | partial | Actor ultimate-energy-like versus shared skill-point-like interpretation strongly supported; exact UI labels not proven. |
| callback timing | closed + engine_consumer_unavailable | Local caller/installer/callback positions; global update/Ultra/death ordering unavailable. |

No already-identified readable core reference is left as a substitute for a native endpoint: the ordinary skill entry, actual mutation, common callback, referenced resource AI group and ordinary bootstrap were followed. An optional future gauge or different actor mechanic is not relabeled as the missing generic implementation.

## 20. Generic versus sample-local conclusions and boundaries

Reusable: family-qualified skill inputs, explicit operation recipients, separation of value/ratio fields, distinction between input/operation/evaluator, team-state readers versus individual-targeted operations, and consumer-based UI filtering.

Sample-local: Natasha90 and selected20/30/5 rows; Gallagher110; the servant20 input; the common callback's explicit exception9001013; Natasha's exact phase positions; the inspected AI mapper/factor values. No exhaustive actor coverage, universal award, global hash identity, or full ordinary-resource economy is claimed.

Named native boundaries are (a) raw-SP requirement precedence/current-state gate/debit, (b) ModifySPNew reference-base selection and final state write, (c) SPHitRatio attribution/aggregation, (d) TeamBP initialization/effective maximum, (e) BPAdd/BPNeed automatic gain/cost/affordability, and (f) clamp/conversion/event timing. These retain the release-data/engine boundary already documented in PINNED_SOURCE_INDEX, not a repeated engine-source search.

## 21. Routed residuals and stop condition

W08 retains actor-specific charge/stack/gauge initialization/spend/gain, final public-resource mathematics and stronger UI terminology corroboration. The servant's speed-associated display counter is not promoted to a new completed gauge. No unusually near-closed new gauge justifies changing the proposed next slice.

W11/W15 owns full action/target decision logic beyond the narrow resource reader/precheck surface; W07/W10 owns scheduling and callback total order. SPHitRatio's eventual damage/heal/resource integration remains a joint W08 interface with existing R1/R3, not a reopening of their hidden evaluators. No independent W19+ consequence was established.

R2's common StanceValue injection gap, generic healing/modifier/snapshot consumers, RNG, servant lifecycle, monster final-stat construction, and W17 Assistant/CommonSkillPool/broad reverse scan remain frozen. Recommended next candidate is **W11 + W15 — Targeting / Enemy AI vertical slice**, subject to the next direction correction. **This record stops at R4; no next slice is started.**

## 22. Validation, retrieval limits and replay discipline

This is a documentation-only source audit. Local checks validate Markdown structure, reference definitions, table widths, code-fence/JSON syntax and the intended write set; they do not validate resource arithmetic. Publication checks compare the fixed-parent commit's changed-file set, final head, Draft state and remote blob with the validated text. Actual results are reported in the checkpoint, not predicted here.

Large-file empty Contents responses, code-search misses, 404s for unconfirmed candidate paths, and mismatched/truncated navigation responses were **not** used as absence evidence. A compact exact-pin tree and successful direct file rereads replaced unreliable directory navigation. In particular, the retained StageCommonTemplate is blob `d76c3f1d8a2536da6a6f79e4bb44b79f48b91c5a`, with OnStartSequece/CreatePlayerTeam/StartBattle; no unconfirmed “common init” filename or inferred pre-deal graph is inserted into the chain. This is retrieval hygiene, not an upstream semantic contradiction.

The table rows are identified by SkillID+Level, not a search excerpt or transient viewer line offset. The existing servant table/owner numerical chain is explicitly reused from R0/[SERVANT]; R4 rereads its typed binding/callback without recounting that older result. No current/default-branch source supplies a pinned value.

## 23. Exact-pin replay index

| Ref | File / immutable blob where verified | Node to replay |
| --- | --- | --- |
| A | AvatarConfig; `7ef386fe8256f1374c693e4962e7599249aac9db` | AvatarID1105 and1301: SPNeed, JsonPath, SkillList, Release, AIPath. |
| K | AvatarSkillConfig; `a5416ced941c247d475b2aaa83277b9cdf474dd9` | (110501,1), (110502,1), (110503,1): resource fields and trigger/AttackType; keep full-row omissions. |
| N | Natasha CharacterConfig | SkillList Skill01/02/03 and PassiveSkill02; EntryAbility, SkillType, TargetInfo, named ComplexSkillAI groups. |
| NA | Natasha Ability; `0dd71d6942e4f8420749c56c8151710dee0bf9f0` | Skill02 Phase02.OnStart[8]; Skill03 Phase02 resource site after HealHP; Skill01 Phase02 projectile damage SPHitRatio; common-passive reference and voice-only continuation. |
| CA | Avatar_Common_Ability; `21db58fafcb8fa826c5913b4e019d6c9e56e5f6f` | Avatar_Common_PassiveSkill.OnStart[0]; GlobalModifiers.Local_SPAdd.OnTriggerDeath and its exact ByCompareMonsterID predicate, value environment and mutation. |
| SC | Servant_AglaeaServant CharacterConfig; `bbede98119cf7bc69329dfd4afac3f8151ccd19b` | SkillP04 entry and DynamicValues.Floats[-2017292130].ReadInfo. |
| SK | AvatarServantSkillConfig; prior R0/[SERVANT] numerical authority reused | SkillID1140206, Level3, SkillP04, ParamList[0]=20; do not substitute AvatarSkillConfig. |
| SA | Servant_AglaeaServant Ability; `80cb71c2d1c5b166ec4726a1828497d8ca28d640` | Servant_AglaeaServant_00_DeathRattle and local modifier callback; GlobalModifiers.MServant_AglaeaServant_00_AddSpeed.OnDestroy display counter. |
| GA | Gallagher Ability; `9c29a5776ba33334439d3b38e6988098a2925f85` | Skill02 Phase01 explicit inherent target transfer; Phase02.OnStart[4] HealHP.SPHitRatio, not an AttackData field. R3 supplies the already-closed producer/entry. |
| GC | GameCoreConstValue; `47ed0e027c76df398cf6e13de104933299ec1700` | TeamBPFloatStart/Max/ToIntegerRatio; separate adjacent SPMultipleRatio and turn/round inputs. |
| ST | StageCommonTemplate; `d76c3f1d8a2536da6a6f79e4bb44b79f48b91c5a` | OnStartSequece ordinary binding/player-team creation/start sites; no visible TeamBP assignment. |
| AI | Global_FactorGroups; `19b5f3a1674cf9b6b8e7391ed72d14ce24a42b60` | GroupsMap.DefaultBPSkill.Factors[0]; DefaultBPSkill_PreCheck TeamBoostPoint/MaxTeamBPCost/PreCheckFail inputs; DefaultUltra distinction. |
| AAI | Avatar_ComplexSkilll_AutoFight_AI; `0955a62694a20c84a4d46d8d43cd492259d18a89` | AvatarConfig-referenced DecisionList RootTask=UseSkillByComplexSkillAI and ComplexSkillAIAxis; AIName is not owner identity. |

[R0]: battle_execution_language_core_v1.md
[R1]: ordinary_damage_vertical_slice_v1.md
[R2]: weakness_toughness_break_vertical_slice_v1.md
[R3]: healing_modifier_lifecycle_core_v1.md
[SERVANT]: ../characters/aglaea_servant_11402_reference_chain.md
[GLOBAL]: global_shared_reverse_scan.md
[A]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/AvatarConfig.json
[K]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/AvatarSkillConfig.json
[N]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Natasha_00_Config.json
[NA]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Natasha_00_Ability.json
[CA]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Common_Ability.json
[SC]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Servant/Servant_AglaeaServant_00_Config.json
[SK]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/AvatarServantSkillConfig.json
[SA]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Servant/Servant_AglaeaServant_00_Ability.json
[GA]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Gallagher_00_Ability.json
[GC]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/GlobalConfig/GameCoreConstValue.json
[ST]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/Level/StageCommonTemplate.json
[AI]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAI/ComplexSkillAIGlobalGroup/Global_FactorGroups.json
[AAI]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAI/Avatar_ComplexSkilll_AutoFight_AI.json
