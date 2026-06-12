# HSR Combat Simulator Project Handoff for Codex

## 0. Current status in one paragraph

This project is a Honkai: Star Rail battle simulator / route validator being built toward a general combat solver. The current workspace is based on `hsr_combat_workspace_v0_74`, with a v0.75 foundation-audit layer added locally. The simulator can execute compiled battle cases and exact routes, and the live C0→C8 validation route currently runs successfully. However, it is not yet a fully general simulator assembled from raw team + equipment + relics + stage + enemy data. It currently relies on compiled cases/checkpoints, and the next major work is to refactor the engine into a stricter, observable, data-driven simulator that records full battlefield state and every action settlement.

## 1. Project goal

Long-term goal:

```text
team + light cones + relics + enemy templates + stage rules + technique choices + route/policy
  -> build initial BattleState
  -> simulate HSR combat accurately
  -> output full state/action/damage ledgers
  -> support route search / solver for target objectives
```

Primary target scenario:

- Game: Honkai: Star Rail.
- Scenario: v4.3 Apocalyptic Shadow / Arbitration, Knight 3 style battle.
- Current validation route: live C0→C8 trace from an observed combat segment.
- Current team:
  - Seele, E3, signature light cone `In the Night` S1.
  - Sparkle, E1, signature light cone `Earthly Escapade` S1.
  - Tribbie, E1, `Dance! Dance! Dance!` S5.
  - Dan Heng · Permansor Terrae, E0, `Journey, Forever Peaceful` S1.
- Current enemies include wave 1 Daybreak Squadron / Titan Vanguard and wave 2 Lance of Fury variants.

The project must not become a hand-tuned spreadsheet. The engine should model state transitions, action queues, buffs/debuffs, resources, damage formula, enemy mechanics, and observable combat state in a reproducible way.

## 2. Fixed workspace layout

Current local fixed workspace:

```text
/mnt/data/hsr_fixed_workspace/
  current -> /mnt/data/hsr_fixed_workspace/hsr_combat_workspace_v0_74
  tbgd    -> /mnt/data/hsr_fixed_workspace/turnbasedgamedata-main
```

Edit `current/` directly. Do not repeatedly unzip the archive during development. Export a new zip only after a versioned change.

Important project directories:

```text
current/
  simulator_v7_7/
    hsr_simulator_prototype_v7_7.py      # current main simulator file
    hsr_engine/                          # schema/core helpers where present
    ENGINE_ARCHITECTURE_v7_0.md          # architecture direction
    README.md

  model_pack_v3_0/
    MANIFEST.yaml
    schema/hsr_model_pack_schema_v3_0.yaml
    rules/combat_rules_v3_0.yaml
    models/characters/*.yaml
    models/light_cones/*.yaml
    models/relic_builds/*.yaml
    models/enemies/*.yaml
    teams/seele_sparkle_tribbie_dan_heng_pt.yaml
    stages/arbitration_4_3_knight_3.yaml
    battles/arbitration_4_3_knight_3_full_combat.yaml
    compiled_cases/*.yaml

  live_validation_reports/
    simulator_workflow_audit_v0_74.md
    foundation_audit_layer_v0_75.md
    damage_formula_component_audit_v0_74.md

  validation_outputs_v0_75/
    c0_to_c8_full_audit_v0_75.json
```

Raw TurnBasedGameData source:

```text
/mnt/data/hsr_fixed_workspace/tbgd
```

Use TBGD as source/evidence. Do not directly leak raw opcode/hash schema into the battle engine. Normalize through model pack / IR boundaries.

## 3. Current runtime workflow

The current simulator path is:

```text
model_pack_v3_0/MANIFEST.yaml
  -> load compiled_cases/<case>.yaml
  -> canonicalize_case()
  -> BattleSimulator(case)
  -> BattleState.from_case()
  -> run_route(route)
  -> resolve_route_step()
  -> resolve_action()
  -> resolve_damage_packet() / apply_effect() / run_triggers()
  -> result JSON
```

This means the simulator currently consumes a compiled battle case, not raw team/stage/enemy templates.

It can simulate a specified route if the case already contains:

- unit stats/resources/statuses/actions;
- global SP/AV/checkpoint flags;
- enemy units/statuses/mechanic flags;
- triggers;
- explicit route steps;
- manually curated checkpoint state.

It does **not** yet cleanly support:

```text
input raw team + equipment + relics + stage + enemies + techniques
  -> automatically build battle-start BattleState
  -> choose actions dynamically
  -> fully simulate battle from start
```

This is the main architectural gap.

## 4. Commands to verify current baseline

Run from workspace root:

```bash
cd /mnt/data/hsr_fixed_workspace/current
python3 -m compileall -q simulator_v7_7

python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --validate-model-pack

python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode exact \
  --output validation_outputs_v0_75/c0_to_c8_full_audit_v0_75.json
```

Expected current baseline:

```text
route_assertions.ok = true
route steps = 8
log events = 172
```

Known issue:

- `run_validations_v7_7.py` has at least one old route failure where the route expects `dan_heng` but the current action axis next actor is `seele`. Treat this as a separate investigation, not as the v0.75 baseline pass condition.

## 5. Current live validation result

Current case:

```text
arbitration_4_3_knight_3_live_c0_to_c8_simulator_only
```

Current route steps:

```text
1. Sparkle skill -> Seele
2. Dan Heng basic -> Titan Vanguard
3. Sparkle ultimate
4. Tribbie follow-up
5. Seele skill -> Titan Vanguard
6. Souldragon shield_action
7. Titan Vanguard heaven_to_dawn
8. Daybreak Squadron daybreak_blade
```

Current key results:

```text
Tribbie follow-up:
  Daybreak Squadron: 2312.108210
  Titan Vanguard:    2080.897389
  Total:             4393.005600
  Observed:          4401
  Error:             about -0.18%

Seele skill:
  Hit 1: 27496.850523
  Hit 2: 2966.116652
  Hit 3: 2966.116652
  Hit 4: 82490.551568
  Total: 115919.635395
  Observed: 109262
  Error: about +6.09%
```

Conclusion:

- Tribbie follow-up is now close after fixing Sparkle ultimate Cipher extra damage bonus.
- Seele skill is still high. Do not assume Tribbie E1 fixes this; adding Tribbie E1 would only make damage higher unless other windows differ.

## 6. Important recent mechanism findings

### Sparkle ultimate Cipher extra damage bonus

C0 state had `damage up 12%`, equivalent to two Sparkle talent stacks. Sparkle ultimate Cipher adds +6% per stack, so C0→C8 should add another:

```text
2 stacks * 6% = +12% damage bonus
```

This was added to the live case as part of v0.74:

```yaml
modifiers:
  atk_pct: 0.4
  dmg_bonus_add: 0.12
```

This fixed Tribbie follow-up from about 3999.60 to 4393.01.

### Tribbie E1 should not be forced into the current route

Tribbie E1 requires the ultimate zone/field to be active and zone additional damage to trigger. Current observed C0→C8 state clearly has:

- `Divine Revelation` / all RES PEN +24% style state;
- `Busy as Tribbie` / follow-up after ultimate style state.

But current trace does not clearly confirm:

- Tribbie ultimate zone active;
- zone damage-taken/vulnerability state;
- zone additional damage trigger.

Therefore do not automatically add E1 true damage to C3/C4. If E1 is enabled later, verify that `total_attack_damage` is correctly carried in trigger context. Do not accidentally base E1 true damage on the zone add-damage packet itself.

### Titan Vanguard armor rule currently modeled

Current understanding:

- Armor reduces damage by 10% while present.
- One attack action removes at most one armor stack.
- Additional damage / DoT / true damage should not consume armor unless explicitly proven.
- Titan Vanguard restores armor to 6/6 after its own action.

## 7. v0.75 foundation-audit layer

The latest local change added observability without changing numeric logic.

Every `route_action_trace[*]` now has:

```text
before_scene
action_resolution
after_scene
```

### full scene snapshot includes

- global AV, cycle, SP, wave index, global flags;
- action axis: each unit's remaining AV, absolute AV, speed, interval, alive state, tags;
- allies/summons/enemies/others with:
  - HP / max HP / HP%;
  - shield;
  - energy / max energy;
  - toughness / max toughness / broken state;
  - HP-bar model;
  - current panel stats;
  - stat_base / stat_pct / stat_flat / legacy stats;
  - resistances and weaknesses;
  - statuses with id, source, stacks, duration, tags, modifiers;
  - special mechanism flags such as phase, armor, counters, summon binding, enemy AI metadata;
- queues: ultimate, immediate, interrupt.

### action settlement currently includes

- requested actor/action/timing/targets;
- damage events;
- status events;
- resource events;
- AV events;
- mechanism events;
- all raw events in this action step.

### damage formula ledger currently includes

Each direct damage event attempts to output:

- scaling source and base damage;
- crit result and crit multiplier;
- damage bonus bucket and contributing terms;
- DEF multiplier and contributing terms;
- RES multiplier and contributing terms;
- damage-taken bucket;
- universal reduction bucket;
- toughness-state bucket;
- other bucket;
- final damage.

This is an audit layer. It does not yet make the engine semantically strict; it mainly exposes hidden state and hidden formula contributions.

## 8. Current structural problems

The simulator is not yet sufficiently “simulator-like” for solver work. Main issues:

1. **Compiled-case dependency**
   - Runtime starts from curated checkpoints.
   - No clean raw team/stage/enemy assembly pipeline yet.

2. **Status/modifier model is too loose**
   - Buffs/debuffs use generic dict modifiers like `dmg_bonus_add`, `all_res_pen`, `damage_taken_add`, etc.
   - There is no strict source -> condition -> bucket -> applied/not-applied ledger as first-class data.

3. **Action settlement is still partly derived from logs**
   - v0.75 records action_resolution, but this is mostly categorizing existing log events.
   - Need first-class `ActionSettlement` generated by the engine during resolution.

4. **Action axis / queue system needs stronger types**
   - Normal turn, ultimate insertion, immediate actions, extra turns, summons, AV advance/delay, speed-change recomputation should be represented explicitly.

5. **Buff/debuff lifecycle needs stronger rules**
   - Need strict duration types, turn-kind consumption rules, per-hit/per-attack trigger counts, source ownership, wave carry policy.

6. **Enemy mechanics are incomplete**
   - Enemy intent and special mechanics are not fully normalized.
   - Some flags exist, but a solver needs exact enemy AI/intent/mechanism state.

7. **RNG / target selection ledger missing**
   - Crit, effect hit/resist, random target choice, and enemy AI random branches need stable event ids and reproducible policy.

8. **Resource/cost ledger incomplete**
   - SP, energy, HP cost, special resource cost, free action, refund, kill energy, hit energy all need explicit source and timing.

9. **Character/mechanic fallbacks remain**
   - Genericity audit flags Souldragon fallback, AttackConvert refresh, break formula calibration, enemy mechanism inventory, generated debuff lowering.

## 9. Recommended next refactor order

Do not immediately chase the Seele damage difference by hand-patching more buffs. First make the engine stricter and more observable.

Recommended order:

### Phase 1: create explicit engine data objects

Split or add explicit structures for:

```text
SceneSnapshot
ActionRequest
ActionSettlement
DamageSettlement
StatusChange
ResourceChange
AVChange
MechanismEvent
ModifierTerm
ModifierLedger
RNGEvent
TargetResolution
```

The v0.75 audit output can be used as the expected JSON shape, but the data should be produced by the engine directly, not reconstructed from logs after the fact.

### Phase 2: strict modifier system

Create a normalized modifier model:

```text
status/equipment/relic/lightcone/enemy mechanic
  -> source id/name
  -> bucket
  -> value
  -> stack rule
  -> duration rule
  -> condition predicate
  -> target/action/packet scope
  -> applied yes/no with reason
```

The damage engine should consume only normalized terms and emit a full ledger for every packet.

### Phase 3: state lifecycle and action scheduler

Refactor:

- action lifecycle: turn start, action start, before damage, each packet, after damage, after action, turn end;
- duration ticking: regular turn vs extra turn vs ultimate vs summon turn;
- queue scheduler: ultimate/immediate/interrupt/extra-turn/summon;
- AV changes: speed change, action advance, delay, reset.

### Phase 4: raw battle assembly

Build:

```text
BattleAssembler(team, light cones, relics, stage, enemies, technique choices)
  -> BattleState
```

This should eventually replace curated C0 checkpoint dependency for full-battle simulation. Keep compiled case replay as validation harness.

### Phase 5: resume live damage investigation

After strict ledgers exist, re-check Seele C4 skill:

- Sparkle Cipher +12% should/should not apply to this action?
- Seele amplified state 88% window correct?
- Seele quantum RES PEN 25% window correct?
- Sparkle skill crit damage buff +111.816% window correct?
- Crit hits 1 and 4 assumption correct?
- Titan armor / toughness / RES / DEF states correct?

## 10. Coding rules for Codex

Important constraints:

1. Do not convert observed damage numbers into simulation inputs. Observed damage belongs only in trace/diff reports.
2. Do not solve damage mismatch by adding route-specific hacks unless the mechanism is proven and modeled generically.
3. Do not bypass the model pack with raw TBGD fields inside the engine. Normalize first.
4. Preserve current C0→C8 baseline unless intentionally changing a rule:
   - route assertions should remain ok;
   - Tribbie follow-up should remain about 4393.0056;
   - Seele skill current baseline is about 115919.6354 until investigated.
5. Prefer adding tests and audit ledgers before changing formula behavior.
6. Keep generated outputs versioned under `validation_outputs_vX_YY/` and reports under `live_validation_reports/`.
7. When changing schema/behavior, update a short report describing what changed and what command was used to verify it.
8. Avoid large rewrites without preserving the current exact-route replay path.

## 11. Suggested IDE task prompt for Codex

Use this as the first Codex instruction after opening the workspace:

```text
Read CODEX_HANDOFF.md, simulator_v7_7/ENGINE_ARCHITECTURE_v7_0.md, live_validation_reports/foundation_audit_layer_v0_75.md, and live_validation_reports/simulator_workflow_audit_v0_74.md.

Goal: refactor the HSR simulator from a compiled-case route executor toward a stricter battle simulator without breaking the current C0→C8 baseline.

First task: introduce explicit settlement/ledger data structures for action resolution and damage modifier terms. Keep the existing CLI and exact route case working. Do not change damage numbers yet. After the refactor, rerun compileall and the C0→C8 exact route, and write a short report under live_validation_reports/.
```

## 12. Files to read first

Read in this order:

```text
CODEX_HANDOFF.md
simulator_v7_7/ENGINE_ARCHITECTURE_v7_0.md
live_validation_reports/foundation_audit_layer_v0_75.md
live_validation_reports/simulator_workflow_audit_v0_74.md
model_pack_v3_0/MANIFEST.yaml
model_pack_v3_0/README.md
model_pack_v3_0/compiled_cases/arbitration_4_3_knight_3_live_c0_to_c8_simulator_only.yaml
simulator_v7_7/hsr_simulator_prototype_v7_7.py
validation_outputs_v0_75/c0_to_c8_full_audit_v0_75.json
```

