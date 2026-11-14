# Public mechanics models: healing and shield reconciliation v1

## 1. Result and authority

Reviewed 2026-09-23. TBGD remains pinned to `DimbreathBot/TurnBasedGameData@14c1d18f91a8101d610e6c523447a7517de3fae1`. Evidence parent: `61541a5c692314bbd33e5ac835b12da0044dd8ce`. PR #8 remains Draft and documentation/evidence-only.

**A missing native evaluator body is not evidence that the observable formula is unknown.** This checkpoint adopts attributed public gameplay models, joins them to previously audited pinned operands, and separates externally tested behavior from our own arithmetic predictions. It corrects the blanket restrictions on using public formulas in the former R3 and March records. It neither changes raw values nor claims recovery of GameCore code.

Positive results: Natasha's direct and periodic base-heal equations; Gallagher's flat base heal; March's DEF-based base shield; the selected Natasha HOT's recipient-turn-start interpretation; and a historical first-hand test establishing damage reduction before shield loss. Exact native snapshot, replacement and dispatcher implementation remains a different question.

## 2. Method: work from a known mechanic back to its data

Start with a precise public rule or tested outcome, not an unconstrained filename search. Identify the quantities, owner, conditions, timing and exceptions that rule predicts. Then locate the pinned producer, binding, authored operation and downstream effect that explain those predictions.

Record three complementary kinds of evidence:

- **Pinned data:** exact values, fields, occurrence identity and reference/binding chains.
- **Public gameplay evidence:** published equations, descriptions or first-hand experiments, with author, URL, version/date and actual test scope.
- **Reconciled interpretation:** the explicit mapping from those equations and observations to the pinned inputs and operations.

A public model can establish useful gameplay semantics without exposing a native function body. It must not be relabeled as a raw opcode implementation or silently supply an absent pinned row. Conversely, a model is not demoted to mere search advice just because the dump contains no evaluator.

Use a discriminator when competing explanations matter: vary healer rather than recipient HP; distinguish flat from stat-scaled healing; vary mitigation without changing shield creation; separate a normal periodic tick from an extra activation. Predictions alone do not verify themselves. Two data sites may share a dump, and repeated quotations are not independent experiments. Existing credible tests may be reused without demanding that every researcher repeat them.

No backend implementation, acceptance gate or repair is a prerequisite for this process.

## 3. Public-source register

All resources below were consulted on 2026-09-23. A page's displayed version is recorded rather than inferred to be the current game version or the TBGD pin's release.

| Ref | Source and context | Evidence role and limit |
| --- | --- | --- |
| P1 | [Honey Hunter: Natasha Skill](https://starrail.honeyhunterworld.com/love-heal-and-choose-skill/?lang=EN). Retrieved page header says live 3.7 / beta 3.8 (3.7.54). | Published description and level table: healer-MaxHP scaling, separate direct/periodic operands, turn-start HOT, duration and trace extension. A data publication, not an independent gameplay experiment. |
| P2 | [KQM Gallagher quick guide](https://hsr.keqingmains.com/q/gallagher-quickguide/), marked Version 3.0. | Authored explanation distinguishes flat Skill healing from stat-scaled attacks and describes Outgoing Healing contributions. Not a pin-specific native default-enum definition. |
| P3 | [KQM March guide](https://hsr.keqingmains.com/march-7th/), marked Version 1.5. | Authored explanation of caster-DEF shield creation and separate defensive benefits. Its displayed coefficient summary is not an exact substitute for pinned decimals. |
| P4 | [bobrokrot: damage reduction before shields](https://hsr-tickets.keqingmains.com/transcripts/dmg-reduction-before-shields), tested 2023-05-16. | Original experiment with setup, reported measurements, video link and review acknowledgements. The SRL evidence file is `KQM-git/SRL/docs/evidence/combat-mechanics/damage/Shielding.md`, blob `ce4dc27dd3d156e1d6540fc82c97e964c052b288`. We read the report, not a new run or frame-by-frame video audit. |
| P5 | [Ludgerz/Ludgeria: SAM healing-reduction analysis](https://www.reddit.com/r/HonkaiStarRail/comments/1au9po0/dont_make_this_simple_mistake_when_facing_boss/), historical SAM encounter discussion. | Original author reports testing an additive Outgoing-Healing/reduction model. The plotted comparisons are calculations using the author's build; do not count them as separately measured observations. Used as attributed corroboration, not as a new pinned SAM audit. |
| P6 | [KQM Kafka guide](https://hsr.keqingmains.com/kafka/), marked Version 1.2. | A bounded model for navigating ordinary DoT ownership and extra activations. Not proof of every later DoT exception or a new complete pinned DoT trace. |

Negative checks: `library.keqingmains.com` healing/shield results involving Barbara or Genshin artifacts are the wrong game. A correct KQM brand is not sufficient game identity. Honey Hunter's unfilled description placeholders are not zero-valued skill parameters. Rounded web percentages must not replace exact raw decimals. Empty Evidence Vault headings are not experiments.

## 4. Reused and re-read pinned anchors

The full raw investigations remain in [R3](healing_modifier_lifecycle_core_v1.md) and [March](../characters/march_7th_preservation_skill02_shield.md). Their original versions are retained at the evidence parent above; this checkpoint changes interpretation, not the audited rows.

Natasha's [Ability at the pin](https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Natasha_00_Ability.json), blob `0dd71d6942e4f8420749c56c8151710dee0bf9f0`, was re-read at the direct-heal/install, trace-startup and HOT callback occurrences. The selected table rows and typed ConfigCharacter bindings below reuse the prior raw audit; no new table enumeration or skill materialization is claimed.

| Claim | Pinned source chain |
| --- | --- |
| Natasha direct heal | Avatar1105 -> Skill110502 -> Skill02; index0/hash `-1544075911` -> `HealPercentage`; index3/hash `-203632277` -> `ModifyValue`; `Avatar_Natasha_00_Skill02_Phase02.OnStart[4]`, `FormulaType=HealByHealerMaxHP`, recipient `AbilityTargetEntity`. |
| Natasha HOT | Same row indices1/4 -> hashes `-754957899` / `-1192384503` -> installation `MDF_ShowValue1/2` -> modifier-local hashes `1733325153` / `2136609680` -> periodic `HealHP`. |
| Natasha timing | `GlobalModifiers.MAvatar_Natasha_00_HOT_HPByMaxHP`: `OnPhase1`, holder HP>0, recipient `ModifierOwnerEntity`, `LifeStepMoment=ModifierPhase1End`; duration index2 plus PointB3's explicit 0/1 branch. |
| Natasha healing bonus | Point1105102 -> hash `103268114` -> `M_SkillTree_HealRatioUp` -> `HealRatioBase`; separate talent Skill110504 -> target-HP predicate and `ModifyHealData.Healer_HealRatio`. |
| Gallagher flat heal | Avatar1301 -> Skill130102 Lv1 index0=200 -> ConfigCharacter hash `2082775117` -> Skill02 Phase02 `HealHP.ModifyValue`; recipient `AbilityTargetEntity`. Raw `FormulaType` and `HealPercentage` are omitted. |
| March base shield | Avatar1001 -> Skill100102 -> index0/hash `-1091495116` and index3/hash `1935511666` -> named shield inputs -> `MAvatar_March7th_00_BPSkill_Shield.OnStack` -> `InitShield`, `FormulaType=ShieldByCasterDefence`. |

## 5. Accepted healing models and selected mappings

Let `H_N` denote Natasha's effective maximum HP used for the heal. The base amount is before healing bonuses and before limiting actual HP recovery by the target's missing HP.

Combining P1's gameplay description with the pinned operand chain gives:

```text
Natasha Skill02 Lv1 direct base heal = 0.07 * H_N + 70
Natasha Skill02 Lv1 HOT base pulse   = 0.048 * H_N + 48
Natasha Skill02 Lv2 direct base heal = 0.074375 * H_N + 112
Natasha Skill02 Lv2 HOT base pulse   = 0.051 * H_N + 76.8
Gallagher Skill02 Lv1 base heal      = 200
```

These are **cross-validated gameplay interpretations of pinned inputs**, not quotations of exported evaluator code. In particular, Gallagher's observable flat-heal behavior is established without inventing the missing `FormulaType` enum value or adding `HealPercentage=0` to the raw JSON. P2 agrees on the level-1 base amount and non-HP/ATK/DEF scaling of that base.

For ordinary healing with no received-healing modifier or special conversion, use the public model:

```text
heal amount = base heal * (1 + applicable Outgoing Healing Boost)
```

P5 supplies an attributed, reported-test discriminator for a reduction sharing this multiplier rather than multiplying the final result separately. It is not a full proof of every received-healing modifier, minimum clamp or special healer attribution. Those are specific follow-on checks, not reasons to leave the base equation unknown. P2's Break-Effect-to-Outgoing-Healing conversion is evidence that a flat base does not imply an unmodifiable final heal.

At the source boundary, Natasha's persistent `HealRatioBase` contribution and conditional `Healer_HealRatio` mutation now have an explicit public gameplay role: outgoing-healing contributions, not additional base-heal coefficients. The low-HP predicate is a per-application condition; a healed recipient may no longer satisfy it on a later pulse. This checkpoint does not claim a newly executed sum of every bonus or recovery event.

**Selected timing reconciliation:** P1 places the HOT at the healed ally's turn starts for two turns, with the trace adding one. Together with the modifier holder, `OnPhase1` and supplied duration, this supports the recipient-turn-start interpretation of this specific callback. It is no longer simply an unexplained phase-name token. It does not establish every `OnPhase1` dispatcher, extra-turn exception, reapplication timing or snapshot-refresh rule in the game.

## 6. Accepted shield model and a measured ordering rule

For the ordinary March Skill02 base shield, let `D_M` be March's effective DEF used in shield creation:

```text
base shield = selected shield percentage * D_M + selected flat shield value
Lv11: base shield = 0.589 * D_M + 802.75
Lv12: base shield = 0.608 * D_M + 845.5
```

The equation's interpretation is supported by P3 and the pinned formula family plus distinct input bindings. Precise coefficients stay pinned; the guide's summarized percentages are not exact-value authority. Shield-generation bonuses, recipient mitigation and shield loss are separate stages.

This resolves the basic creator-stat question: creation scales with March's DEF, not automatically the shield recipient's DEF. It does not prove the native snapshot-capture mechanism. The nearby `CasterDefence` working read still has no demonstrated direct transfer into the main AddModifier; knowing the equation does not justify fabricating that raw edge.

**P4 is positive empirical evidence, not only a search hint.** Its author reports 154 damage under a 10% reduction both without and with a shield, versus 171 shield damage after the reduction expired. `171 * 0.9 = 153.9`, consistent with the reported displayed 154. The selected observation supports applying damage reduction before consuming shield capacity. It does not determine the exact integer-rounding stage, shield replacement order or whether zero shield immediately destroys a modifier.

## 7. Arithmetic checks are predictions, not gameplay runs

| Deliberately specified inputs | Model prediction |
| --- | --- |
| Natasha Lv1, `H_N=3000`, no healing modifiers | Direct 280; each eligible HOT pulse 192. |
| Same, only a 10% outgoing-healing contribution | Direct 308; each eligible pulse 211.2 before display rounding and HP limits. |
| Gallagher Lv1, no healing modifiers | Base/final pre-cap amount 200. |
| March Lv12, `D_M=2000`, no shield-generation modifier | Initial amount 2061.5 before rounding. |

These calculations illustrate how the published model consumes the pinned values. They are not independent observations and cannot by themselves validate the model. P4's reported measurements remain separately identified external evidence. No game, simulator, Direct or test suite was run here; no local-runtime E is added.

## 8. Applying the same method to DoT

P6 gives a useful historical model before opening new raw files: an ordinary ATK-scaling DoT keeps its originating damage source; an extra activation is not the ordinary duration-decrement event. This immediately directs archaeology toward caster/owner identities, installed damage operands, normal periodic callbacks, extra-activation callers and lifetime stepping as separate edges.

A selected ordinary model may be written `tick = source ATK * DoT coefficient * applicable damage multipliers`; it must not be imposed on Break-derived statuses or every DoT family. The existing R3/R2 contrast already separates ordinary periodic healing from Fire Break Burn's `ByBreakDamage` request.

This checkpoint supplies model-led navigation, not a new completed Kafka/Guinaifen source chain. The productive missing work is exact status ownership and activation/parameter mapping, not a fresh search for whether the entire notion of DoT arithmetic exists.

## 9. What is known versus still specific

| Question | Current disposition |
| --- | --- |
| Do the selected healing/shield operands have usable arithmetic meaning? | Yes: the equations above are positive, attributed, cross-validated models. |
| Which character supplies the selected scaling stat? | Natasha for her MaxHP heals; March for her DEF shield; Gallagher's selected base is flat. |
| What does the selected Natasha HOT callback represent? | Recipient-turn-start healing, reconciled with public description; exact generic scheduling is separate. |
| Can mitigation apply before shield depletion? | Yes in P4's documented ordinary test; accepted as scoped external empirical evidence. |
| Is the native evaluator body recovered? | No; this does not undo the known gameplay equations. |
| Are precise snapshot capture, replacement total order, all received-healing interactions and rounding/overheal event payloads closed? | Not by this checkpoint. Seek specific public tests/source discriminators, not necessarily native code. |
| Does a backend implementation or passing CI decide whether these source/model findings are useful? | No. Backend consumption is separate. |

The old condition that these questions may reopen only upon finding a native-engine implementation is superseded: credible new gameplay experiments and independently supported models can also resolve the corresponding observable behavior. Missing pinned values still remain missing; no external value is silently rewritten as a raw fact.
