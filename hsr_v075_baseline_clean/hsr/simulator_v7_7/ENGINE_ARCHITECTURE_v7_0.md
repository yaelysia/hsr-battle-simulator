# HSR Battle Simulator v7.0 Architecture

## Goal

This project is no longer a narrow route checker.  The long-term target is a general HSR battle simulator: given character templates, equipment/relic/light-cone effects, enemy templates, stage rules, and a route or policy, it should reproduce the in-game battle settlement system as closely as possible.

A route/video case is only a validation harness.  The engine must be based on stable battle rules, not on hand-patching one video.

## v7.0 refactor boundary

Earlier versions accumulated compatibility fixes directly inside the simulator file.  v7.0 introduces an explicit data boundary:

```text
external YAML / model pack / generated trace
        ↓
hsr_engine.schema_normalizer.canonicalize_case()
        ↓
canonical simulator IR
        ↓
BattleSimulator battle engine
        ↓
event log + state snapshots
```

The engine should not care whether a field came from a hand-written validation case or a Dimbreath-derived model pack.  It should receive canonical action, packet, effect, trigger, status, unit, and route structures.

## Modules

### `hsr_engine.core_rules`

Central scalar and structural coercion rules:

- `coerce_bool`: quoted false/true, numeric booleans, native booleans.
- `coerce_float`: numbers, quoted numbers, percentages, infinity markers.
- `coerce_int`, `maybe_float`, `maybe_int`.
- `normalize_str_list`: scalar tags/weaknesses/targets are single tokens, not character sequences.
- `normalize_triggers`: list and dict trigger styles, singular `effect` and plural `effects`.
- `normalize_flag_values`: recursively normalizes flag/checkpoint values.

All future parser compatibility should go here first when it is a scalar/list/trigger rule.

### `hsr_engine.schema_normalizer`

Canonicalizes external schemas into simulator IR:

- unit fields: tags, weaknesses, stats, flags, HP model, status definitions, actions, triggers.
- action fields: `action_id`, `skill_point_delta`, queue-policy aliases, effect windows, singular/plural damage packets.
- damage packets: nested `scaling`, `crit`, `toughness`, `target`, hit-model expansion.
- effects: effect containers, action/status aliases, booleans/numerics, nested branches.
- route steps: action alias, scalar target lists, queue-resolution booleans.

Only aliases that the core engine does not already handle specially are rewritten.  Character-text semantic aliases such as `launch_follow_up_attack` are preserved when the engine has dedicated behavior for them.

## Core battle-rule targets

The simulation layer should converge on these stable systems:

1. **Action value / timeline**
   - Base interval: `10000 / speed`.
   - AV decreases globally until a unit reaches 0.
   - Regular action completion refreshes next AV before action-end advance/delay effects.
   - Ultimate/extra-turn queues are separate from normal timeline turns.

2. **Damage formula**
   - Base damage from scaling stat and multiplier.
   - Crit multiplier / expected crit mode.
   - DMG% multiplier.
   - DEF multiplier.
   - RES multiplier.
   - Damage-taken multiplier.
   - Toughness-state multiplier.

3. **Event bus**
   - Action lifecycle: turn start → action start → after-action-start effects → before-damage effects/triggers → damage packets → after-damage effects → action-end triggers.
   - Trigger contexts must carry actor, target, action, packet, damage result, queue metadata, and extra-turn type.

4. **Queue scheduler**
   - Ultimate queue before immediate/extra-turn queue before interrupt queue.
   - Queued actions have explicit wave-carry policy and turn-kind policy.
   - Target selection for deferred queued actions happens at execution time.

5. **State lifecycle**
   - Buff/debuff duration types are explicit.
   - Extra turns do not consume regular-turn durations unless the status says so.
   - Per-hit vs per-attack duration and energy windows are distinct.

6. **HP model**
   - `normal_hp`: one HP pool.
   - `segmented_hp`: multi-segment same-phase HP, damage carries by default.
   - `phase_hp`: phase boundary HP, damage does not carry by default, later hits in the same action are locked out unless explicitly allowed.

## External references used as architecture checks

This project follows the common HSR damage decomposition and AV model used in public theorycrafting references, but the implementation remains local and test-driven.  Public references are for sanity checks, not authoritative executable code.

## Next refactor targets

v7.0 only moves scalar/schema compatibility out of the battle engine.  The next structural split should be:

- `formula_engine.py`: safe formulas and model-pack expression evaluation.
- `condition_engine.py`: string and dict predicates.
- `damage_engine.py`: packet resolution and damage formula.
- `event_bus.py`: trigger dispatch and usage limits.
- `queue_scheduler.py`: ultimate/immediate/interrupt queues.
- `trace_runner.py`: state-chain validation against video-derived checkpoints.
