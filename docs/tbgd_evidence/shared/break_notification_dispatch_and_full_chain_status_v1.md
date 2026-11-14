# Break notification dispatch and full-chain status v1

## Current continuation — native-consumer boundary, 2026-09-28

Section 9 continues from `98c95f486c3110b80fcf377d42e7797820a0ce81` / checkpoint `5866453492`. It identifies the fixed TBGD build label, obtains a release-labelled 4.3.0 auxiliary SDK instead of silently using the earlier 4.5.0 interfaces, and follows a new native-xref lead to its actual evidence limit. The missing mapping is now localized to compiled task execution / stance-state admission / modifier-event dispatch in the acquired material. The connecting function bodies and event trace were not obtained; neither notification order nor duplicate suppression is declared solved. Sections 1-8 retain the preceding investigation and its original provenance.

## 1. Scope, answer and correction

Reviewed 2026-09-28 from evidence parent `bd417912e57f1e8196ae6a6ebbdf7b2e4509675b`, following checkpoint `5864651405`. Startup and pre-write PR #8 reads agreed on that head and open/Draft/unmerged state. Raw authority remains `DimbreathBot/TurnBasedGameData@14c1d18f91a8101d610e6c523447a7517de3fae1`.

The user explicitly reopened the Break-notification question: an existing notification path must not accidentally receive an additional logical Break merely because the common state contains `TriggerBreak(Caster)`. This is a targeted continuation, not a repeat of the phase-concluded ordinary damage/Q investigation, a backend audit, or a complete Ruan Mei kit. Buff first-step timing remains paused; lethal-hit Energy and shield-cap questions are not investigated here.

**The full chain is not closed.** In particular, this pass did not recover the native mapping, attribution, dispatch count or cross-callback order connecting `TriggerBreak` to `OnBeforeBeingBreak`, `OnTriggerBreak`, `OnBeingBreak` and other listeners. F03's earlier phrase "distinct TriggerBreak notification surface" overstates the evidence: the confirmed object is a **separately serialized task**, not a proved extra logical notification. F03 is corrected and linked here. R2 sections 10 and 14 already retained the missing native bridge; their qualification is not superseded.

The actual increment is a reachable pre-Break property consumer and a separate target-side Break-triggered damage producer, including its parameter ownership, temporary `Multiple` modifier and lack of an authored once-per-occurrence guard. These show a concrete consequence of duplicate delivery without pretending that a duplicate occurred in the game or the local backend. Auxiliary generated SDK declarations narrow the native entrypoints to seek but do not supply their implementation.

## 2. Evidence register

All A paths below use the unchanged TBGD pin. Complete blob hashes identify the files; selected read ranges and object names bound this investigation.

| Ref | File and inspected occurrence | Complete blob |
| --- | --- | --- |
| A1 | [Monster Common Ability][A1], lines 1-165: listener installation and complete `Local_ListenStanceBreak.OnBeingBreak` | `fa02f6ab070fb8da16ebd2f5976503446d633e0e` |
| A2 | [Common Specific modifiers][A2], lines 1-185: complete `StanceBreakState` callbacks | `2db782ddc81b7a1328e4086dc71c8a23295b06a8` |
| A3 | [Avatar Common Ability][A3], lines 1-111 and 800-1250: common installer and complete selected `OnTriggerBreak` element dispatcher | `21db58fafcb8fa826c5913b4e019d6c9e56e5f6f` |
| A4 | [Ruan Mei Ability][A4], principally 1510-2160 and 3465-3625: ordinary passive installation, enemy listeners, pre-Break property contribution and temporary proc damage | `25536aef20af238ffa46787860e88cf7c2cd7d2b` |
| A5 | [Ruan Mei CharacterConfig][A5], lines 100-470: SkillP01 entry/membership and typed SkillP01/Rank04/Rank06 bindings | `42d2ae46cb0327d9c7e781b8b041ca3390f37d2b` |

[R2], [F03] and [DIVE] supply the existing shared elemental templates, ordinary formulas, threshold-hit mitigation result, Super Break accounting and their precise residuals. Reusing them does not represent a fresh full audit of seven elements or of every reset site. A4's recovery-extension callbacks were also read at 4100-4580; the whole Ultimate chain and its native interception are not declared closed.

[P1], KQM's Ruan Mei guide, is marked Version 1.6, credits authors Ducc, Reens and Soul Fish, and lists publication on 2024-02-01. Retrieved 2026-09-28. Its Talent and E4 explanations corroborate the separate Ruan Mei-owned damage and property effect. The guide places Talent damage after the breaker's attack and expressly distinguishes it from a fresh Weakness Break for Thief-set activation. These are attributed behavioral statements, not replayed experiments or pin-matched native timing. No linked game recording or test was run here.

Auxiliary source [M0] is an **auto-generated SDK**, `Z4ee/AnimeSDK@3dfc8baeb886d7907c7771b5f70f9775727300d2`. Its game-build equivalence to the TBGD pin has not been established:

| Ref | Inspected declaration | Complete blob / limit |
| --- | --- | --- |
| M1 | `RPG/GameCore/TriggerBreak.h`: TaskConfig subclass with TargetType, AliveStateMask and IgnoreMuteBreak | `27886f16436ea2eea972415a6f66538598a6d8ef`; full header read, no defaults or dispatcher body |
| M2 | `Class_3_C9CFBB2710ACF1F9.h`: `ImmediateTaskBase_1<TriggerBreak*>`, constructor and OnTaskBegin | `2aa315ee9570b89aa6f1d1a33c20e429a26069d2`; full header read, methods merely call native addresses |
| M3 | `RPG/GameCore/AbilityStatic.h`: ApplyStanceDamage declaration and indexed `ComboProcessTriggerBreak(GameEntity* a1, GameEntity* a2)` wrapper | `85464c1728a5ff74b4866842b9c94f6b8a1827ec`; selected header reads and immutable declaration excerpt, not a recovered caller/callee edge |

No SDK-only field/default or anonymous argument identity is imported into the fixed-pin task. Enum values, declaration order and `ImmediateTaskBase` naming cannot prove the ordering or synchronous completion of nested game notifications. Third-party simulator search results are not adopted as original GameCore facts.

## 3. What the complete chain still needs

These are claim-level questions, not new workflow states or backend prerequisites. A missing raw transport edge does not invalidate an independently supported ordinary behavior model.

| Segment | Already usable | Still not connected | Why the missing edge matters |
| --- | --- | --- | --- |
| BNC-01: admitted toughness input and transition | Ordinary weakness/depletion model, unit convention, source-specific inputs and common state handler | Avatar loader into hash1659254037; generic matching/override/threshold admission and repeated-break suppression implementation | A displayed reduction field or an already-zero bar cannot by itself specify every admitted Break request |
| BNC-02: notification mapping, roles and multiplicity | Exact TriggerBreak task occurrence and actual handlers on both sides | Which native route produces each event; Caster/attacker/victim transport; relation to the originating hit and gauge transition; duplicate/reentrant admission | **Highest-priority gap for the user's double-dispatch concern** |
| BNC-03: state and property sampling order | Ordinary crossing hit retains common0.9 reduction; state installation/removal task order; new pre-Break property and later proc-read sites | Ordering across listeners, nested OnCreate/OnStack, common-reduction withdrawal and each damage context | Correct totals in one case do not reveal which state every initial/proc damage request samples |
| BNC-04: elemental and additional outputs | Seven shared elemental routes and formulas; separate proc/DoT/Super Break identities; new source-owned proc chain below | General source-context/working-value transport, precise per-family capture/reapplication and exceptional output eligibility | Do not collapse all ByBreakDamage outputs into one logical Break or one shared owner |
| BNC-05: recovery and re-arming | OnEndBreak -> removal -> authored reset/count/reduction restoration; public recovery-extension distinction | Native producer/interception of recovery, exact nested order, exceptional exit and next-transition admission | Ending an elemental status, ending Break and becoming eligible for another natural Break are different transitions |
| BNC-06: optional Super Break continuation | Existing target/source-qualified accounting, explicit resets, input modes and ordinary post-crossing model | Exact ParamValue2 construction, omitted-input transport, native hit grouping and nested reader/reset interleaving | This is a separate enabler/output path, not another initial-Break notification |

BNC-02 is not solved by adding another character whose callback has a similar name. The value of the selected contrast below is to expose actual input ownership and duplicate-delivery consequences. Ordinary formulas and the settled crossing-hit result are retained; none is demoted to unknown solely because a method body is absent.

## 4. Known local chains, with the native bridge left open

```text
[threshold / native admission and notification construction: unresolved]

A1 target-side Local_ListenStanceBreak.OnBeingBreak:
  request AddModifier(holder, StanceBreakState, AliveOnly=false)
  request RemoveModifier(holder, MonsterAllDamageReduce)

A2 StanceBreakState.OnCreate:
  request companion effect on holder
  request holder action delay +0.25 normalized
  execute serialized TriggerBreak(TargetType=Caster)

[TriggerBreak task -> event(s), roles, count and scheduling: unresolved]

A3 avatar-side TriggerStanceCountDown_Test.OnTriggerBreak:
  test holder's character damage type
  invoke corresponding StanceBreak_* template
  template has its own initial damage / elemental-status requests
```

The dashed conceptual bridge is not a proved `TriggerBreak -> OnTriggerBreak` call. Nor is the diagram proof that all target-side callbacks finish before any attacker-side callback. The A1 list puts state installation before reduction-removal requests; it does not reveal how the A2 creation callback nests or is queued relative to the outer continuation. Caster in A2 remains the literal selector, not an assumed synonym for the breaking avatar.

A3's complete selected dispatcher has no authored once-per-Break latch around its element branches. That is an occurrence-level property, not proof that the native event producer lacks suppression. `OnTriggerStanceCountDown` is a separate handler, not another spelling of `OnTriggerBreak`.

## 5. New source discriminator: a pre-Break property change and a separate proc

### 5.1 Ordinary owner-to-listener reachability

A5 binds SkillP01 to `Avatar_RuanMei_PassiveSkill01`; A4's OnStart installs `MAvatar_RuanMei_Passive` on Caster. Its OnEnterBattle adds `MAvatar_RuanMei_Passive_ListenBeingBreakOrHit` to AllDarkTeam. Its character-create listener installs that same listener on a newly reported TeamDark ParamEntity. These are ordinary passive paths, not the differently scoped Technique/Simulated-Universe code nearby.

With Rank04 active, the entry callback additionally installs `MAvatar_RuanMei_Rank04_PassiveStackProperty` on Caster and `MAvatar_RuanMei_Rank04_PassiveListenBreak` on AllDarkTeam; the TeamDark creation path also has this rank gate. The listener holder is therefore an enemy while the effect's source remains Ruan Mei. A5 independently binds the used parameter hashes to Rank04; a shared numeric trigger hash is not the sole rank identification.

### 5.2 OnBeforeBeingBreak has a real battle-property consumer

```text
MAvatar_RuanMei_Rank04_PassiveListenBreak.OnBeforeBeingBreak:
  AddModifier(Caster, Rank04_PassiveStackProperty,
    SkillRank_Rank04_P1_BreakDamageAdded <- hash1148819630)
  AddModifier(Caster, Rank04_Passive_BreakDamageAddedUp,
    LifeTime <- hash-304658486)

Rank04_PassiveStackProperty.OnStack:
  StackProperty(Caster, BreakDamageAddedRatioBase, working hash-1293127313)
```

A5 maps1148819630 to SkillRank(Rank04,0), and -304658486 to SkillRank(Rank04,1). The timed companion's OnDestroy reapplies the property state with the named bonus input explicitly zero. This establishes property contribution and source ownership, not a new first-decrement/expiry-order rule. No unread pinned rank numeric row is supplied from public text.

Thus a full notification model must account for a **pre-Break stat-affecting surface**, not only two main callback names. The later read below can depend on when this contribution becomes visible. Event names and the local task lists alone do not establish a universal scheduler order or certify which of every possible damage output benefits from it.

### 5.3 OnBeingBreak captures the support's parameters, not necessarily the breaker's

The complete selected `MAvatar_RuanMei_Passive_ListenBeingBreakOrHit.OnBeingBreak` requires ParamEntity to intersect `AllLightTeamWithAllLightTeamUnselectable.RemoveBattleEvent`. Its successful branch:

```text
SetDynamicValueByBreakBaseDamage(_BreakBaseDamage, ReadTarget=Caster)
SetDynamicValueByProperty(_BreakDamageAddedRatio, ReadTarget=Caster,
                         Value=BreakDamageAddedRatio)
choose _SkillP01_FinalBreakDamagePercentage:
  SkillP01[1], or SkillP01[1] + Rank06[1] when the rank gate succeeds
AddModifier(ModifierOwnerEntity, MAvatar_RuanMei_Passive_TriggerBreakDamage,
  captured base, captured Break Effect, chosen coefficient)
```

A5 binds the coefficient hashes -416268945 and -1790781914 to SkillParam(SkillP01,1) and SkillRank(Rank06,1). The installer passes named inputs `MDF_BreakBaseDamage_set`, `MDF_BreakDamageAddedRatio_set` and `SkillP01_FinalBreakDamagePercentage_set` through the working reads recorded in A4.

Here the enemy is the holder and the stat reads explicitly address the effect source. The ParamEntity predicate is source-compatible with an allied breaker notification, but its native construction is still not recovered. The common initial-Break owner must not be silently replaced by this support source, or vice versa. Captured named inputs also do not recover the generic native processing of every working slot.

### 5.4 The temporary damage state is Multiple; self-removal is not deduplication

`MAvatar_RuanMei_Passive_TriggerBreakDamage` explicitly has `Stacking=Multiple`. Its OnStack reads the holder's MaxStance, forms the toughness-dependent coefficient, requests Ice / ByBreakDamage / ElementDamage / ByPureDamage damage on that holder, and calls RemoveSelfModifier. Its coefficient expression uses literal30,2,4; the body and its caller contain no authored per-logical-Break occurrence guard.

**Conditional source consequence, not an executed test:** delivering two qualifying OnBeingBreak callbacks can author two temporary-modifier installations and their damage requests. Completing and removing the first temporary state does not itself remember that the logical Break was already handled. Conversely, this does not prove that the game's native dispatcher delivers duplicates, or that the user's current backend does so.

This proc and the shared initial `StanceBreak_*` output are distinct producers. More than one Break-formula damage request can legitimately accompany one Break. A blanket "one ByBreakDamage output per attack" restriction would conflate these outputs; it would also ignore different targets and separately enabled Super Break.

### 5.5 Public timing is not a recovered native call stack

P1 places the Talent damage after the breaker's attack. Treat that as an attributed, effect-specific behavioral model. A4 places the authored request in OnBeingBreak -> AddModifier -> OnStack; it does not expose the event producer or a universal synchronous execution contract. No claim is made that all Break callbacks or initial elemental damage wait until attack end. Resolving the public behavior to exact queue/dispatch boundaries remains BNC-02/BNC-03; neither source is rewritten to manufacture that edge.

## 6. The remaining native question now has named entrypoints

M1/M2 identify the task configuration and an executor OnTaskBegin. M3 identifies a native `AbilityStatic.ComboProcessTriggerBreak` entry with two GameEntity arguments, alongside a toughness-application entry. The next source-level discriminator is a body or trustworthy attributed trace connecting those entries to the modifier-event dispatcher, including existing-state/mute guards, argument provenance and nested-call behavior.

These are **candidate entrypoints**, not an asserted call chain. The acquired SDK functions are address trampolines; no readable native dispatch implementation was obtained. Anonymous a1/a2 do not prove attacker/victim order. Their SDK revision is not the TBGD revision. Searches yielding only declarations cannot be elevated into a whole-web or whole-corpus absence theorem.

Do not label TriggerBreak an unconditional extra event, a proved no-op, or a proved alias solely to make an implementation convenient. The ledger neither authorizes adding a second full notification pass nor verifies the user's existing notification path. No runtime/lowering/IR file was analyzed for correctness in this continuation.

## 7. Discriminators and remaining deliverable

These are proposed evidence requirements, not tests run here and not a new implementation schema.

A useful isolated observation uses one ordinary nonlethal target/bar, an identifiable breaker, and at most the selected support. Separate the ordinary crossing hit, shared initial Break output, support proc and any deliberately enabled Super Break. Use different source elements/parameters when needed to disambiguate attribution; a combined UI damage total is insufficient. Record the state before crossing, event recipient/parameter roles where observable, request owner, state/contribution changes and output timing.

For source-level replay, retain a logical hit/target/bar-cycle identity as an analytical trace label. Ask whether one admitted transition produces the paired callbacks once, whether the common-state TriggerBreak reaches an existing-state guard or another dispatcher, and which state is visible before each consumer. This label is not claimed to exist as a native JSON field. A one-per-enemy-action dedup rule is not established by this investigation.

Distinct controls are: an exact-zero crossing; another hit while the same ordinary bar remains broken; two different targets breaking within one attack; recovery followed by a new Break; and the support's pre-Break property branch enabled versus disabled. Exceptional bars, lethal transitions and recovery interception require separately identified rules rather than being silently included in the ordinary control. No predicted notification count, numerical outcome or event total order from these controls is reported as measured.

## 8. Publication and actual validation

This record and F03's narrowly corrected wording are the publication scope. R2's detailed gap, DIVE's ordinary mitigation/Q results, historical numeric inputs, broad W/F checkboxes and the pin remain intact. The current targeted inquiry does not certify whole FG-01/W06 completion or establish a backend repair prerequisite.

Actual work: GitHub immutable-file reads, inspection of complete selected callbacks and typed parameter/owner joins, comparison with an attributed guide and version-qualified metadata, and publication diff/content/head/Draft checks recorded in the checkpoint. No game session, simulator, automated test or CI workflow was run or manually started. No skipped result is called passed. The principal native mapping remains unresolved; the new reachable consumer and duplicate-delivery analysis are not substitutes for that missing result.

## 9. Continuation: version-qualified native consumption, not another database parameter

Reviewed 2026-09-28 from `98c95f486c3110b80fcf377d42e7797820a0ce81`, after checkpoint `5866453492`. Startup and pre-write remote reads matched that head and open/Draft/unmerged state. The user requested continued investigation and an explicit report if the unresolved operation is consumed below the exported database. This pass investigates that boundary instead of adding another character listener.

### 9.1 Build identity and additional evidence

The pinned TBGD commit [N0] is labelled `OSPRODWin4.3.0_D15283412_A15267128_L15257484`, dated 2026-06-03. The earlier auxiliary SDK commit [N1] is labelled **4.5.0**, dated 2026-08-30. Following its actual commit history located [N2], `Z4ee/AnimeSDK@75b0b4b1eff6c4a2a48e15b4358b0e40b0e2045b`, labelled **4.3.0**, dated 2026-06-04. Commit dates/labels are metadata, not binary authentication. N2 is closer in release identity; its full binary build/hash match to N0 remains unestablished.

| Ref | Acquired source / selected extent | Complete blob or identity; limit |
| --- | --- | --- |
| N3 | N2 `unitysdk/RPG/GameCore/TriggerBreak.h`, complete header | `a4bb41629763de9c3e43685637dcb37650e70eb3`; configuration declaration and address wrappers |
| N4 | N2 `unitysdk/Class_3_C9CFBB2710ACF1F9.h`, complete header | `60d89db75181e2af73f11baef9aa4df0e4d204ac`; typed task executor declaration, not its native body |
| N5 | N2 `unitysdk/RPG/GameCore/TurnBasedAbilityComponent.h`, selected declaration/macro occurrences for TryEnterBreakState and ExecuteAllModifierEvent | `11bb2b75d4793bf1dc414c0e7ca74af0b8d52024`; TryEnter replay 1595-1605 and exact named selectors; no complete component-body audit |
| N6 | N2 `unitysdk/RPG/GameCore/AbilityStatic.h`, ApplyStanceDamage and ComboProcessTriggerBreak declarations/macros | `7dd3e6adc3dfb223b2428d60c7ae4097be0543c1`; named interfaces, no connecting native call graph |
| N7 | N1 TurnBasedAbilityComponent header, selected TryEnterBreakState declaration | `6729f359e07ffd070003dc924f0fe24bd66da200`; 4.5.0 comparison only, especially lines 1510-1640 |
| X1 | `eryou1202/hsr-battle-agent@ce62dc0028d15cbdc7a332c3db860ed7fffb9c58`, `data/raw/4.4.54/predicate_caller_graph_04.json`; exact TryEnterBreakState-labelled reference | `845a4d55a84c880e695dd22bc4fe6ae369b41a75`; third-party static scan with short byte context, not a recovered Break dispatcher |
| X2 | Same external revision, `tools/reverse/scripts/semantic_method_xrefs.py`, lines 1-190 | `20118b1c9265e5b9217796548d870d1eb4c41c09`; actual scanner and method-association algorithm inspected, not executed |
| X3 | Same revision, `tools/reverse/scripts/semantic_batch_evidence.py`, lines 1-135 | `e37effac9d049b5f62dd3a6f34c533768fe2e3b6`; binary/manifest dependency and byte-reading helper |
| X4 | Same revision, `docs/battle_semantics/predicate_evaluation_bridge_04.md`, lines 1-105 | `bb656838b084932c324e044d242491adac7b17f1`; author identifies the comparison target and limits its reconstruction |
| X5 | Same revision, `data/semantics/4.4.54/full_reconstruction/toughness_break_packet_001.json`, complete | `c9aca43d1dbe8c9761cc75531949f30eebb2d838`; selected model using third-party formula/local reconstruction, not original native event semantics |
| X6 | Same revision, `.gitignore`, lines 1-160 | `aafb287780d63dc76aca4a08ea913056c012f74b`; exclusion policy, not by itself proof that every matching file is absent |

The fixed TBGD root tree [N8] was read completely (`truncated=false`): Config, ExcelOutput, README.md, Stages, Story and TextMap. This is export-organization evidence, not a recursive proof that no nested file could contain additional information. The decisive acquired implementation distinction below is the typed executor's native-address delegation, not a filename search miss.

### 9.2 A task configuration has a compiled consumer; candidate interfaces are not call edges

N3 declares `TriggerBreak : TaskConfig`. N4 separately declares an executor specializing `ImmediateTaskBase_1<TriggerBreak*>`, whose constructor accepts `TaskContext*` and `TriggerBreak*`. Its OnTaskBegin wrapper calls the function at `hIl2Cpp + 0x1665A550`; it contains no readable target-resolution, state-guard or event-dispatch body. This is positive auxiliary evidence of a native consumer for the task configuration, not proof of the exact factory registration used by N0.

The release-labelled 4.3.0 declarations supply these bounded investigation anchors. Offsets are local to N2's SDK, not portable addresses, execution instructions or a recovered call order:

| Interface | N2 declaration / native offset | Still missing |
| --- | --- | --- |
| TriggerBreak executor.OnTaskBegin | Typed by `ImmediateTaskBase_1<TriggerBreak*>`; `0x1665A550` | Actual callee(s), target evaluation and use of TaskContext |
| TurnBasedAbilityComponent.TryEnterBreakState | `(TaskContext*, GameEntity*, AttackDamageType, bool)`; `0x1279BE60` | Parameter provenance, state/admission checks and which notifications it emits |
| AbilityStatic.ApplyStanceDamage | `(GameEntity*, GameEntity*, AttackData*, bool, TaskContext*, Struct_2_E03B78B927A9E70C_1, AttackDamageType)`; `0x12B13630` | Threshold path and relationship to the task/native state entry |
| TurnBasedAbilityComponent.ExecuteAllModifierEvent | Takes a TurnBasedModifierEvent, an opaque context object, GameEntity, filter mask and target predicate; `0xEF10D60` | Actual calls from the Break route, payload construction, ordering and nested execution |
| AbilityStatic.ComboProcessTriggerBreak | `(GameEntity*, GameEntity*)`; `0x1292DA90` | Whether it participates in this route at all; do not assume a central dispatcher from its name |

All inspected method wrappers delegate to native addresses. **No arrow between those interfaces is promoted as a discovered caller/callee relationship.** In particular, the typed task executor has not been shown to call TryEnterBreakState, and TryEnterBreakState has not been shown to call ExecuteAllModifierEvent for a specific sequence. The wrapper's `ImmediateTaskBase` name, the order of method declarations and enum numbering cannot decide nested callback scheduling.

### 9.3 The version distinction affects the interface, not just the address

In N2's 4.3.0 header, TryEnterBreakState declares four explicit parameters, ending with one Boolean. In the earlier N1/N7 4.5.0 header it declares five, ending with two Booleans. N3 declares TargetType and AliveStateMask; the previously inspected 4.5.0 M1 additionally declares IgnoreMuteBreak. These are differences between acquired SDK declarations, not proof of a live-game feature's introduction date or a complete schema history.

Therefore the older investigation's 4.5.0 parameters, field layout and offsets must not be silently projected onto the 4.3.0 TBGD pin. Nor may an SDK omission delete a field actually present in pinned data. No Boolean meaning, default or correspondence to IgnoreMuteBreak is inferred. Using N2 improves release qualification but does not recover code or establish an exact binary match.

### 9.4 New native-xref lead: real byte context, but not the missing dispatch

A global exact-name search found X1, which records a call site `0xE741F41` under the caller label `TurnBasedAbilityComponent.TryEnterBreakState`, method index506599, start RVA `0xE741820`, five parameters. The relevant bytes are `e8 6a 26 f2 0e`. Independent integer arithmetic in this continuation confirms:

```text
0xE741F41 + 5 + little_endian_signed32(6a 26 f2 0e) = 0x1D6645B0
```

X4 identifies that destination as FixPoint's greater-than comparator. It is **not an identified modifier-event dispatch call**. The short context does not determine the compared operands, the full branch condition, true method boundaries or any emitted event. Arithmetic consistency of a stored reference is not independent verification against the original executable.

X2 explains the limit: it scans executable sections for relative-call/jump byte patterns and assigns a containing method from the preceding registered method start. It explicitly neither follows callees nor decompiles a full call graph. Instruction boundaries and accurate function extents still require verification; the scan's caller label is retained as third-party attribution, not promoted into a proven full native path.

Version/provenance also prevents joining this fragment to N2. Its containing directory and author report use 4.4.54, while X1's binary path names `D:\StarRail_4.4.53\GameAssembly.dll`; that discrepancy was not resolved. X3 loads a local GameAssembly path from `data/normalized/4.4.54/manifest.json`. Fetching that exact manifest at the external revision returned 404. X6 excludes normalized/parsed data and client directories. Together these show why the acquired repository material is insufficient to reproduce this particular scan's complete executable analysis; the ignore file alone is not an absence theorem. No local Windows path in the external report is accessible evidence in this investigation.

X5 was read and deliberately not used to close dispatch: its zero-crossing/order/no-op policies are explicitly a selected reconstruction, with a third-party damage calculator and local model/tests as support. Another simulator's chosen ordering cannot supply the missing original GameCore behavior. The external author's skipped/heavy classifications are not this investigation's passed checks. Targeted public lookups did not yield an independently inspectable event trace or connecting native body; this is a bounded retrieval result, not proof that none exists.

### 9.5 Returned boundary and precise reopening condition

**This continuation reaches the compiled-consumer boundary, not full Break-chain closure.** The acquired evidence supports locating BNC-02/BNC-03 at task execution, native stance-state admission and modifier-event dispatch below the exported JSON task lists. It does not identify an additional Excel parameter that would decide notification count/order. Repeating the same database callback names is not a substitute for the missing consumption logic.

The exact unresolved edges are: how the task resolves its Caster/context and enters native state processing; how the originating toughness transition and that task share or separate admission; which side receives each event and payload; and where existing-state/reentrant suppression and nested-callback ordering occur. None of the acquired declarations proves these guards exist, their conditions, or their absence.

The next evidence capable of changing that result is a build-qualified native body/call trace connecting the relevant entries to event dispatch, or an original isolated observation that actually discriminates the competing behaviors. A matching GameCore binary's relevant disassembly with identity/provenance would be such evidence; a new SDK signature, a same-named character listener, or a third-party test of a chosen simulator policy would not. A trustworthy behavior trace can resolve its observable claim without recovering every native instruction.

Until that evidence is available, retain TriggerBreak as an unresolved operation in the ledger. Do not authorize an additional full notification pass, declare the task a proven no-op, or claim the user's existing notification chain was verified. This is a source-boundary report, not a new backend repair dependency or a request to change runtime code. The ordinary formulas and prior crossing-hit/Q results remain usable within their recorded scopes.

Publication scope is this document's continuation notice, section9 and references only. Actual new work is immutable metadata/header/script reading, version and source-provenance comparison, one stored-branch-destination arithmetic check, public-source lookup, and the GitHub diff/readback/head/Draft checks recorded in the checkpoint. No game, simulator, test suite, SDK executor, external extraction script or CI workflow was run; no original executable was obtained or disassembled. The manifest404 and unclosed call graph are not passed validation. No raw pin, broad coverage checkbox, runtime, lowering, IR, tests or CI configuration is changed.

[R2]: weakness_toughness_break_vertical_slice_v1.md
[F03]: general_weakness_toughness_break_super_break_v1.md
[DIVE]: break_transition_hit_super_break_accounting_v1.md
[A1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Monster/Monster_Common_Ability.json
[A2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json
[A3]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Common_Ability.json
[A4]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_RuanMei_00_Ability.json
[A5]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_RuanMei_00_Config.json
[P1]: https://hsr.keqingmains.com/ruan-mei/
[M0]: https://github.com/Z4ee/AnimeSDK/blob/3dfc8baeb886d7907c7771b5f70f9775727300d2/README.md
[M1]: https://github.com/Z4ee/AnimeSDK/blob/3dfc8baeb886d7907c7771b5f70f9775727300d2/unitysdk/RPG/GameCore/TriggerBreak.h
[M2]: https://github.com/Z4ee/AnimeSDK/blob/3dfc8baeb886d7907c7771b5f70f9775727300d2/unitysdk/Class_3_C9CFBB2710ACF1F9.h
[M3]: https://github.com/Z4ee/AnimeSDK/blob/3dfc8baeb886d7907c7771b5f70f9775727300d2/unitysdk/RPG/GameCore/AbilityStatic.h
[N0]: https://github.com/DimbreathBot/TurnBasedGameData/commit/14c1d18f91a8101d610e6c523447a7517de3fae1
[N1]: https://github.com/Z4ee/AnimeSDK/commit/3dfc8baeb886d7907c7771b5f70f9775727300d2
[N2]: https://github.com/Z4ee/AnimeSDK/commit/75b0b4b1eff6c4a2a48e15b4358b0e40b0e2045b
[N3]: https://github.com/Z4ee/AnimeSDK/blob/75b0b4b1eff6c4a2a48e15b4358b0e40b0e2045b/unitysdk/RPG/GameCore/TriggerBreak.h
[N4]: https://github.com/Z4ee/AnimeSDK/blob/75b0b4b1eff6c4a2a48e15b4358b0e40b0e2045b/unitysdk/Class_3_C9CFBB2710ACF1F9.h
[N5]: https://github.com/Z4ee/AnimeSDK/blob/75b0b4b1eff6c4a2a48e15b4358b0e40b0e2045b/unitysdk/RPG/GameCore/TurnBasedAbilityComponent.h
[N6]: https://github.com/Z4ee/AnimeSDK/blob/75b0b4b1eff6c4a2a48e15b4358b0e40b0e2045b/unitysdk/RPG/GameCore/AbilityStatic.h
[N7]: https://github.com/Z4ee/AnimeSDK/blob/3dfc8baeb886d7907c7771b5f70f9775727300d2/unitysdk/RPG/GameCore/TurnBasedAbilityComponent.h
[N8]: https://api.github.com/repos/DimbreathBot/TurnBasedGameData/git/trees/db639d04caddb6be177cbced1fdfd48c602f4537
[X1]: https://github.com/eryou1202/hsr-battle-agent/blob/ce62dc0028d15cbdc7a332c3db860ed7fffb9c58/data/raw/4.4.54/predicate_caller_graph_04.json
[X2]: https://github.com/eryou1202/hsr-battle-agent/blob/ce62dc0028d15cbdc7a332c3db860ed7fffb9c58/tools/reverse/scripts/semantic_method_xrefs.py
[X3]: https://github.com/eryou1202/hsr-battle-agent/blob/ce62dc0028d15cbdc7a332c3db860ed7fffb9c58/tools/reverse/scripts/semantic_batch_evidence.py
[X4]: https://github.com/eryou1202/hsr-battle-agent/blob/ce62dc0028d15cbdc7a332c3db860ed7fffb9c58/docs/battle_semantics/predicate_evaluation_bridge_04.md
[X5]: https://github.com/eryou1202/hsr-battle-agent/blob/ce62dc0028d15cbdc7a332c3db860ed7fffb9c58/data/semantics/4.4.54/full_reconstruction/toughness_break_packet_001.json
[X6]: https://github.com/eryou1202/hsr-battle-agent/blob/ce62dc0028d15cbdc7a332c3db860ed7fffb9c58/.gitignore
