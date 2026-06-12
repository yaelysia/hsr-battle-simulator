# simulator_workflow_audit_v0_74

## Fixed workspace

Local fixed workspace created at:

- `/mnt/data/hsr_fixed_workspace/current` -> `hsr_combat_workspace_v0_74`
- `/mnt/data/hsr_fixed_workspace/tbgd` -> `turnbasedgamedata-main`

Do not re-unzip on each iteration. Edit `current/` directly and export a new zip only after a versioned change.

## Commands verified

```bash
cd /mnt/data/hsr_fixed_workspace/current
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --validate-model-pack

python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode exact \
  --output validation_outputs_local/c0_to_c8_v0_74_fixed_workspace_check.json
```

Validation result:

- model-pack structural validation: ok
- live C0->C8 exact route: route_assertions.ok = true
- route steps executed: 8
- log events: 172

## Current workflow observed

The runtime path is currently:

```text
model_pack_v3_0/MANIFEST.yaml
  -> ModelPack.load_compiled_case(case_id)
  -> compiled_cases/<case>.yaml
  -> canonicalize_case()
  -> BattleSimulator(case)
  -> BattleState.from_case()
  -> run_route(route)
  -> resolve_route_step()
  -> resolve_action()
  -> resolve_damage_packet()/apply_effect()/run_triggers()
  -> result JSON
```

This means the simulator currently consumes a **compiled battle case**, not raw team/enemy/stage templates directly.

## Answer to the main question

Current code is a partial battle simulator / route executor, not yet a complete general battle simulator.

It can simulate a specified route if the case already contains:

- units with stats/resources/statuses/actions;
- global SP/AV flags;
- enemy units and statuses;
- triggers;
- explicit route steps;
- manually curated checkpoint state.

It does not yet cleanly support the desired high-level workflow:

```text
input team + light cones + relics + enemies + stage + technique choices
  -> build battle initial state automatically
  -> input/select actions over time
  -> fully resolve all buffs/debuffs/resources/timeline/damage
  -> emit complete state ledger
```

The separated model files exist under `model_pack_v3_0/models`, `teams`, `stages`, and `battles`, but the CLI path used for simulation loads precompiled cases from `model_pack_v3_0/compiled_cases`. The battle document and team/stage files are not dynamically assembled into the runtime case by the main simulation path.

## What is already real engine state

The runtime is not purely hand notes. It has real state objects:

- `UnitState`: hp, max_hp, shield, energy, max_energy, speed, remaining_av, toughness, stats, res, statuses, actions, flags.
- `BattleState`: global av/cycle/SP, units, waves, triggers, global_flags, ultimate/immediate/interrupt queues, event log.
- `StatusEffect`: id/type/tags/modifiers/stacks/duration/source.
- `resolve_action`: action lifecycle, cost, damage packets, after-damage effects, triggers, energy, queues, duration ticks.
- `resolve_damage_packet`: base damage, crit, dmg bonus, defense, resistance, damage-taken, universal reduction, toughness-state multiplier.
- `apply_damage_result`: shield absorption, HP bars, phase locks, toughness reduction, break hooks, hit energy, kill energy.

## Main structural problems found

### 1. Runtime consumes compiled cases, not raw team/enemy data

`ModelPack.load_compiled_case()` loads a YAML under `compiled_cases/` and canonicalizes it. There is no direct runtime assembly from:

- `teams/seele_sparkle_tribbie_dan_heng_pt.yaml`
- `models/characters/*.yaml`
- `models/light_cones/*.yaml`
- `models/relic_builds/*.yaml`
- `stages/arbitration_4_3_knight_3.yaml`
- `battles/arbitration_4_3_knight_3_full_combat.yaml`

into a fresh battle state. This is why the current live case depends heavily on C0 checkpoint state.

### 2. Per-step snapshots hide the important state

`generated_route_snapshot()` only records:

- hp / max_hp
- energy / max_energy
- remaining_av
- toughness
- hp_bars_remaining
- status_count

It does not record:

- exact status ids;
- status stacks;
- duration;
- source;
- modifiers;
- shield source/duration;
- active queues with action metadata;
- damage formula contribution per status.

This directly causes the current debugging pain: a missing buff appears only as a damage mismatch, not as a visible state mismatch.

### 3. Buff/debuff modifiers are too loose

Status modifiers are currently generic dictionaries. The damage formula reads keys such as:

- `dmg_bonus_add`
- `damage_taken_add`
- `def_reduction`
- `res_pen`
- `all_res_pen`
- `damage_reduction`
- `conditional_modifiers`

This is flexible, but not strict enough. There is no normalized modifier ledger like:

```text
source status -> bucket -> value -> condition -> target/action/packet scope -> applied yes/no
```

Therefore it is easy to miss or double-count buff windows.

### 4. Damage formula output lacks contribution trace

Each damage event stores aggregate multipliers, but not the individual contributing statuses. Example: it records final `dmg_bonus`, but not which of these contributed:

- quantum dmg bonus;
- generic_damage_up_12pct;
- sparkle_cipher;
- sparkle_skill_crit_dmg_buff;
- seele_technique_amplified;
- relic/light-cone modifiers;
- enemy-side vulnerability/reduction.

For validation, each damage packet needs a full component ledger.

### 5. Runtime still contains character/mechanic fallbacks

The genericity audit flags high-priority fallback areas:

- Souldragon fallback action template;
- AttackConvert derived property refresh policy;
- break/super-break formula calibration;
- enemy mechanisms inventory;
- generated debuff lowering.

This does not mean every result is wrong, but it means the runtime is still a mixture of general engine and route-specific/character-specific compatibility patches.

### 6. Initial state is checkpoint-driven

The live C0->C8 case starts from a curated checkpoint:

- `global.flags.live_checkpoint = knight3_c0_four_techniques_v0_65`
- initial statuses already attached to units;
- initial AV values already aligned to the observed battle;
- initial shields and special states are already present.

So the case is validating “from C0 onward”, not proving that the simulator can independently reproduce battle-start setup from raw team/stage/technique input.

## Current live diagnostic files produced

- `validation_outputs_local/c0_to_c8_v0_74_fixed_workspace_check.json`
- `validation_outputs_local/state_transition_diagnostic_v0_74.json`
- `mechanism_audit_local/genericity_audit.json`
- `mechanism_audit_local/genericity_audit_cn.md`

## Suggested next refactor before continuing damage hunting

Before continuing the Seele damage investigation, make the simulator observable and stricter:

1. Add `full_state_snapshot()` for every route step:
   - exact statuses with id/stacks/duration/source/modifiers;
   - HP/shield/energy/SP/AV/toughness;
   - queues;
   - global flags.

2. Add `modifier_ledger` to each damage packet:
   - actor-side stat and dmg buckets;
   - target-side vulnerability/def/res/reduction buckets;
   - each contributing status/source;
   - condition result and applied value.

3. Split state subsystems conceptually:
   - ResourceState: HP/shield/energy/SP/toughness;
   - TimelineState: AV/cycle/queues/turn kind;
   - StatusState: buffs/debuffs/durations/stacks/source;
   - FormulaTrace: packet-level damage math;
   - BattleAssembler: raw team/stage/enemy -> initial BattleState.

4. Keep current exact-route replay, but stop treating it as a complete simulator proof.

## Current verdict

The current v0.74 engine is a working exact-route validator with real state transition code. It is not yet a complete general HSR battle simulator. The user's concern is valid: the missing buff/damage-bucket problems are likely not only isolated formula bugs, but also symptoms of weak state observability and incomplete data-driven battle assembly.
