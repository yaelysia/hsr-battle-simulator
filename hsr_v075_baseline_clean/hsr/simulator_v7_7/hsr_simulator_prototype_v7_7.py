#!/usr/bin/env python3
"""
HSR route-verification battle simulator prototype v7.7.

Purpose:
- Given a YAML battle state and a specified action route, resolve state transitions
  and produce a replayable event log.
- Keep character-specific mechanics data-driven via tags / triggers / effects where
  possible. This is not an optimizer/searcher yet.
- v1.0 adds final audit fixes for multi-HP-bar carry-over resolution.
- v1.1 clarifies HP semantics: normal_hp, segmented_hp, and phase_hp with explicit carry rules.
- v1.3 fixes legacy tag predicates such as {action_has_tag: attack}.
- v1.4 honors explicit hp_model.bars HP values and per-bar on_depleted effects.
- v1.5 applies context-specific modifiers to the packet scaling stat.
- v1.7 applies context-specific pct modifiers with split base/pct/flat stat semantics.
- v2.0 defers target selection for immediate_action effects unless targets are explicit, and normalizes single-target YAML strings.
- v2.1 preserves selected action targets for packet-level target_policy such as same_target.
- v2.2 skips queued targeted attacks whose explicit/stale targets no longer contain any valid packet target before paying costs.
- v2.3 adds energy-source aliases for effect energy, applies kill energy for effect damage, and avoids mid-action wave transitions from effect damage.
- v2.4 locks later action-owned effect/packet damage after damage_unit crosses a phase HP boundary.
- v2.5 skips stale queued damage_unit-only attacks and queued actions whose actor died before resolution.
- v2.6 applies effect-level conditions before executing individual effects.
- v2.8 adds per-packet action energy, a dedicated ultimate queue priority, and per-queued-action wave-carry policy.
- v2.9 lets queued-action wave-carry policy live on the queued action definition and parses boolean strings safely.
- v3.0 infers queued-action turn_kind from action metadata/tags so character modeling can define extra turns and ultimates.
- v3.1 parses boolean-like strings safely for energy, hit-energy, HP-carry, and duration fields; duration aliases from character text are accepted.
- v3.2 maps common character-model owner/source duration fields and supports owner-turn-start decrement lifecycles.
- v3.3 resolves action-level effects_after_action_start and effects_after_damage windows.
- v3.4 supports before-damage packet mutation effects and conditional_branch effect composition.
- v3.8 hardens boolean field parsing and queued-action offensive preflight across all action effect windows.
- v4.0 fixes video-replay fidelity issues around scalar action tags, packet crit mutation, quoted shield booleans, and route/initial queue boolean fields.
- v4.8 hardens numeric/string parsing, crit event booleans, infinite toughness, allow_dead_actor, and regular-action end advance timing.
- v5.4 adds model-pack condition-string parsing and common effect/action aliases needed by direct template replay.
- v5.8 hardens direct model-template replay for relic/light-cone before-damage predicates, formulas, multiplier references, and actionless extra-turn grants.
- v7.0 refactors scalar coercion and model-pack schema compatibility into hsr_engine.core_rules/schema_normalizer.
- v7.2 adds a canonical model-pack loader and CLI entrypoint for hsr_model_pack_v3_0.
- v7.3 adds a TurnBasedGameData content compiler that emits canonical Content IR bundles at the compiler boundary.
- v7.4 adds ability-graph inventory tooling to classify RPG.GameCore source nodes before lowering them into executable IR.
- v7.7 adds targeted ActionIR compilation from selected TurnBasedGameData avatar ability chains.
- v7.8 adds executable baseline enemy ConfigAI predicate decisions for compiled enemy templates.
- v7.9 adds enemy AI skill-use records/cooldowns, formation sort direction, and shared-HP enemy body sync hooks.
- v8.0 adds conservative enemy ConfigAI TargetFilter/custom-value/identity predicates and HP-property selector baselines.

Run:
  python hsr_simulator_prototype_v7_7.py examples/seele_five_dummy_case.yaml \
    --output output/seele_five_dummy_result.json

Input format is documented in README.md and demonstrated in examples/.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from collections import deque
from copy import deepcopy
from typing import Any, Optional
from pathlib import Path
import argparse
import json
import math
import sys

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PyYAML is required: pip install pyyaml") from exc

from hsr_engine.core_rules import (
    EPS,
    clamp,
    coerce_bool,
    normalize_str_list,
    coerce_float,
    maybe_float,
    is_infinite_marker,
    coerce_numeric_value,
    coerce_int,
    maybe_int,
    numeric_dict,
    normalize_flag_values,
    normalize_triggers,
    coerce_comparison_value,
    deep_get,
)
from hsr_engine.schema_normalizer import canonicalize_case
from hsr_engine.model_pack_loader import load_model_pack_case, ModelPack
from hsr_engine.tbgd_loader import TBGDSource, write_catalog_bundle
from hsr_engine.content_compiler import write_content_ir_bundle
from hsr_engine.ability_graph_intake import write_ability_graph_inventory
from hsr_engine.action_ir_compiler import write_target_avatar_action_ir
from hsr_engine.dynamic_expression_binder import write_bound_action_ir_bundle
from hsr_engine.status_ir_compiler import write_status_ir_bundle
from hsr_engine.status_dynamic_expression_binder import write_bound_status_ir_bundle
from hsr_engine.status_template_compiler import write_status_template_bundle
from hsr_engine.status_template_integration import attach_status_template_bundle_to_case, load_status_template_bundle, parse_owner_unit_map, parse_owner_rank_map
from hsr_engine.symbolic_formula_executor import evaluate_symbolic_expression_ir
from hsr_engine.engine_property_analyzer import write_engine_property_evidence_report, write_engine_property_inventory_report
from hsr_engine.engine_property_model import describe_engine_property, DERIVED_ENGINE_PROPERTIES, FORMULA_BUCKET_PROPERTY_HINTS
from hsr_engine.break_formula import break_base_damage, element_break_multiplier, toughness_units, max_toughness_multiplier, break_dot_base_damage
from hsr_engine.mechanism_glossary import write_glossary_report
from hsr_engine.genericity_auditor import write_genericity_audit
from hsr_engine.enemy_mechanism_auditor import write_enemy_mechanism_inventory
from hsr_engine.break_formula_auditor import write_break_formula_audit
from hsr_engine.souldragon_template import load_souldragon_action_template, write_souldragon_action_template
from hsr_engine.enemy_route_harness import write_enemy_route_harness
from hsr_engine.enemy_database_scanner import write_enemy_database_scan
from hsr_engine.enemy_template_compiler import compile_enemy_model_pack
from hsr_engine.enemy_ability_graph_lowerer import write_monster_ability_graph_lowering
from hsr_engine.character_mechanism_auditor import write_character_mechanism_audit
from hsr_engine.settlement import (
    ActionRequest,
    SettlementCollector,
    SourceRef,
    StateChange,
    ENERGY_SOURCE_ACTION,
    ENERGY_SOURCE_HIT_TAKEN,
    ENERGY_SOURCE_KILL,
    ENERGY_SOURCE_COST,
    ENERGY_SOURCE_EFFECT,
    AV_REGULAR_TURN,
    AV_ADVANCE,
    AV_DELAY,
    AV_TIMELINE_TICK,
)
from hsr_engine.data import TextMapRegistry, StatusRegistry, SkillRegistry


PROPERTY_HINT_VALUE_KEY_HINTS = {
    "AllDamageTypeAddedRatio": ("damage", "dmg", "propertyvalue"),
    "AllDamageTypePenetrate": ("penetrate", "respen", "propertyvalue"),
    "AttackAddedRatio": ("attack", "atk", "propertyvalue"),
    "DefenceAddedRatio": ("defence", "defense", "def", "propertyvalue"),
    "SpeedAddedRatio": ("speed", "spd", "propertyvalue"),
    "CriticalChanceBase": ("criticalchance", "crit_rate", "critrate", "propertyvalue"),
    "CriticalDamageBase": ("criticaldamage", "crit_dmg", "critdamage", "propertyvalue"),
    "AllDamageTypeTakenRatio": ("taken", "damage", "dmg", "propertyvalue"),
    "AllDamageReduce": ("reduce", "reduction", "propertyvalue"),
    "HPAddedRatio": ("hp", "maxhp", "propertyvalue"),
    "MaxSP": ("maxsp", "sp", "skillpoint", "propertyvalue"),
    "StatusProbabilityBase": ("statusprobability", "effect_hit", "probability", "propertyvalue"),
    "StatusResistanceBase": ("statusresistance", "effect_res", "resistance", "propertyvalue"),
    "BreakDamageAddedRatioBase": ("breakdamage", "break_damage", "break", "propertyvalue"),
}

for _element, _prefix in (
    ("physical", "Physical"),
    ("fire", "Fire"),
    ("ice", "Ice"),
    ("thunder", "Thunder"),
    ("wind", "Wind"),
    ("quantum", "Quantum"),
    ("imaginary", "Imaginary"),
):
    PROPERTY_HINT_VALUE_KEY_HINTS.setdefault(f"{_prefix}AddedRatio", (_element, "damage", "dmg", "propertyvalue"))
    PROPERTY_HINT_VALUE_KEY_HINTS.setdefault(f"{_prefix}Penetrate", (_element, "penetrate", "respen", "propertyvalue"))
    PROPERTY_HINT_VALUE_KEY_HINTS.setdefault(f"{_prefix}TakenRatio", (_element, "taken", "damage", "dmg", "propertyvalue"))


def _build_property_hint_modifier_map() -> dict[str, dict[str, Any]]:
    # Keep the runtime consumer synchronized with the engine-property model.
    # Only formula_bucket_property_hint entries become simulator modifiers;
    # engine-derived properties such as AttackConvert remain audit-only.
    out: dict[str, dict[str, Any]] = {}
    for prop, desc in FORMULA_BUCKET_PROPERTY_HINTS.items():
        bucket = desc.get("formula_bucket")
        if not bucket:
            continue
        out[prop] = {
            "modifier_key": str(bucket),
            "value_key_hints": PROPERTY_HINT_VALUE_KEY_HINTS.get(prop, ("propertyvalue",)),
        }
    return out


PROPERTY_HINT_MODIFIER_MAP = _build_property_hint_modifier_map()



def _property_hint_target_is_status_holder(hint: dict[str, Any]) -> bool:
    target = str(hint.get("target") or "actor").strip()
    return target in {"", "actor", "self", "modifier_owner", "ModifierOwnerEntity", "source", "owner"}


def _choose_dynamic_value_for_property(property_name: str, dynamic_values: dict[str, Any]) -> tuple[str | None, float | None, str]:
    """Choose a numeric status DynamicValue for a StackProperty hint conservatively.

    The compiler keeps TBGD StackProperty metadata as audit hints.  Runtime may
    only consume a hint when its property is a known simulator formula bucket and
    its value can be identified from already-bound status DynamicValues without
    interpreting raw TBGD hashes.
    """
    if not isinstance(dynamic_values, dict) or property_name not in PROPERTY_HINT_MODIFIER_MAP:
        return None, None, "unsupported_property_or_no_dynamic_values"
    numeric: dict[str, float] = {}
    for key, value in dynamic_values.items():
        if str(key).endswith("_resolve"):
            continue
        parsed = maybe_float(value)
        if parsed is not None:
            numeric[str(key)] = float(parsed)
    if not numeric:
        return None, None, "no_numeric_dynamic_values"
    hints = PROPERTY_HINT_MODIFIER_MAP[property_name].get("value_key_hints", ())
    candidates = []
    for key, value in numeric.items():
        lk = key.lower()
        if property_name == "AllDamageTypeAddedRatio" and "penetrate" in lk:
            continue
        if any(str(h).lower() in lk for h in hints):
            candidates.append((key, value))
    if len(candidates) == 1:
        return candidates[0][0], candidates[0][1], "matched_key_hint"
    if len(numeric) == 1:
        key, value = next(iter(numeric.items()))
        return key, value, "single_numeric_dynamic_value"
    return None, None, "ambiguous_numeric_dynamic_values"


def _add_property_hint_modifier(modifiers: dict[str, Any], modifier_key: str, value: float) -> tuple[str, str | None]:
    """Apply a formula-bucket property hint to a simulator modifier dict.

    Scalar buckets use keys such as ``atk_pct``.  Element-specific buckets use
    dotted keys such as ``dmg_bonus.fire`` or ``res_pen.quantum`` and are stored
    in the nested modifier maps that the damage formula already consumes.
    """
    if "." not in modifier_key:
        old = coerce_float(modifiers.get(modifier_key, 0.0))
        modifiers[modifier_key] = old + float(value)
        return modifier_key, None
    root, subkey = modifier_key.split(".", 1)
    bucket = modifiers.setdefault(root, {})
    if not isinstance(bucket, dict):
        # Existing malformed/non-dict data should not be overwritten silently.
        # Keep fail-closed by returning a synthetic skip marker to the caller.
        return modifier_key, "nested_modifier_bucket_not_dict"
    old = coerce_float(bucket.get(subkey, 0.0))
    bucket[subkey] = old + float(value)
    return modifier_key, None


def _attack_convert_scale_from_symbolic_values(symbolic_values: dict[str, Any]) -> float | None:
    """Return the SkillTree scale for Dan Heng PT AttackConvert if present.

    The TBGD formula uses runtime Attack-related operands plus SkillTree PointB1[0].
    Public kit text confirms this is a non-snapshot flat ATK add equal to source
    ATK times the scale (15% at max trace), so runtime lowering reads the scale
    but does not treat AttackConvert as atk_pct or damage bonus.
    """
    if not isinstance(symbolic_values, dict):
        return None
    for rec in symbolic_values.values():
        if not isinstance(rec, dict):
            continue
        resolve = rec.get("resolve") if isinstance(rec.get("resolve"), dict) else {}
        expr_ir = resolve.get("symbolic_expression_ir") if isinstance(resolve, dict) else None
        if not isinstance(expr_ir, dict):
            continue
        for op in expr_ir.get("operands") or []:
            if not isinstance(op, dict):
                continue
            if op.get("kind") == "numeric_binding":
                val = maybe_float(op.get("value"))
                if val is not None:
                    return float(val)
                binding = op.get("binding") if isinstance(op.get("binding"), dict) else {}
                val = maybe_float(binding.get("value"))
                if val is not None:
                    return float(val)
    return None


def _derive_attack_convert_flat_atk(raw: dict[str, Any], dynamic_values: dict[str, Any], symbolic_values: dict[str, Any], runtime_values_by_key: dict[Any, Any] | None) -> tuple[str | None, float | None, str]:
    # If a previous, explicitly materialized DynamicValue exists, consume it.
    if isinstance(dynamic_values, dict):
        numeric_values: list[tuple[str, float]] = []
        for key, raw_value in dynamic_values.items():
            if str(key).endswith("_resolve"):
                continue
            val = maybe_float(raw_value)
            if val is not None:
                numeric_values.append((str(key), float(val)))
        for key in ("MDF_AttackDelta", "AttackConvert", "attack_convert", "atk_add"):
            for nkey, val in numeric_values:
                if nkey == key:
                    return nkey, val, "materialized_attack_convert_dynamic_value"
        if len(numeric_values) == 1:
            nkey, val = numeric_values[0]
            return nkey, val, "single_numeric_attack_convert_dynamic_value"
    scale = _attack_convert_scale_from_symbolic_values(symbolic_values)
    if scale is None:
        return None, None, "attack_convert_scale_missing"
    runtime_values_by_key = runtime_values_by_key or {}
    source_atk = None
    source_key = None
    for key in ("DanHengPT_Attack", "source_attack", "source_atk", "actor_attack", "actor_atk"):
        if key in runtime_values_by_key:
            val = maybe_float(runtime_values_by_key.get(key))
            if val is not None:
                source_atk = float(val); source_key = key; break
    if source_atk is None:
        return None, None, "attack_convert_source_attack_missing"
    return source_key, source_atk * scale, "derived_attack_convert_from_source_attack"


def _materialize_symbolic_dynamic_values(raw: dict[str, Any], modifiers: dict[str, Any], runtime_values_by_key: dict[Any, Any] | None = None) -> dict[str, Any]:
    """Evaluate proven symbolic DynamicValue formulas and merge them into dynamic_values.

    This is deliberately narrow: unsupported opcodes/runtime operands remain as
    symbolic audit records and never affect formula buckets.
    """
    dynamic_values = deepcopy(raw.get("dynamic_values")) if isinstance(raw.get("dynamic_values"), dict) else {}
    symbolic_values = raw.get("symbolic_dynamic_values") if isinstance(raw.get("symbolic_dynamic_values"), dict) else {}
    if not isinstance(symbolic_values, dict) or not symbolic_values:
        return dynamic_values
    audit = modifiers.setdefault("symbolic_formula_applications", [])
    for key, record in symbolic_values.items():
        if not isinstance(record, dict):
            audit.append({"key": str(key), "applied": False, "reason": "symbolic_record_not_object"})
            continue
        resolve = record.get("resolve") if isinstance(record.get("resolve"), dict) else record
        expr_ir = resolve.get("symbolic_expression_ir") if isinstance(resolve, dict) else None
        value, trace = evaluate_symbolic_expression_ir(expr_ir, runtime_values_by_hash=runtime_values_by_key)
        rec = {"key": str(key), "applied": value is not None, "trace": trace}
        if value is None:
            rec["reason"] = trace.get("reason", trace.get("status")) if isinstance(trace, dict) else "unresolved_symbolic_expression"
            audit.append(rec)
            continue
        dynamic_values[str(key)] = float(value)
        modifiers[str(key)] = float(value)
        rec["value"] = float(value)
        audit.append(rec)
    return dynamic_values


def _lower_property_hints_to_modifiers(raw: dict[str, Any], modifiers: dict[str, Any], dynamic_values_override: dict[str, Any] | None = None, runtime_values_by_key: dict[Any, Any] | None = None) -> None:
    hints = raw.get("property_hints")
    if not isinstance(hints, list):
        return
    dynamic_values = dynamic_values_override if isinstance(dynamic_values_override, dict) else (raw.get("dynamic_values") if isinstance(raw.get("dynamic_values"), dict) else {})
    symbolic_values = raw.get("symbolic_dynamic_values") if isinstance(raw.get("symbolic_dynamic_values"), dict) else {}
    audit = modifiers.setdefault("property_hint_applications", [])
    for hint in hints:
        if not isinstance(hint, dict):
            continue
        prop = str(hint.get("property") or "")
        rec = {"property": prop, "source_path": hint.get("source_path"), "target": hint.get("target", "actor")}
        if not _property_hint_target_is_status_holder(hint):
            rec.update({"applied": False, "reason": "non_holder_target"})
            audit.append(rec)
            continue
        mapping = PROPERTY_HINT_MODIFIER_MAP.get(prop)
        desc = describe_engine_property(prop).to_dict()
        if not mapping:
            if desc.get("category") == "derived_flat_atk_modifier" and desc.get("formula_bucket"):
                mapping = {"modifier_key": str(desc.get("formula_bucket")), "value_key_hints": ("attackconvert", "attackdelta", "atk", "propertyvalue")}
            else:
                if desc.get("category") in {"engine_derived_property", "derived_flat_atk_modifier"}:
                    modifiers.setdefault("engine_property_hints", []).append({"property": prop, "source_path": hint.get("source_path"), "target": hint.get("target", "actor"), "model": desc})
                    rec.update({"applied": False, "reason": "engine_derived_property_audit_only", "engine_property_model": desc})
                else:
                    rec.update({"applied": False, "reason": "unsupported_property", "engine_property_model": desc})
                audit.append(rec)
                continue
        if prop == "AttackConvert":
            value_key, value, reason = _derive_attack_convert_flat_atk(raw, dynamic_values, symbolic_values, runtime_values_by_key)
        else:
            value_key, value, reason = _choose_dynamic_value_for_property(prop, dynamic_values)
        if value is None:
            rec.update({"applied": False, "reason": reason, "symbolic_keys": sorted(symbolic_values.keys())})
            audit.append(rec)
            continue
        mod_key = str(mapping["modifier_key"])
        applied_key, skip_reason = _add_property_hint_modifier(modifiers, mod_key, float(value))
        if skip_reason:
            rec.update({"applied": False, "reason": skip_reason, "modifier_key": applied_key, "dynamic_value_key": value_key, "value": float(value)})
        else:
            if prop == "AttackConvert":
                modifiers["__replace_existing_modifiers"] = True
                rec["refresh_policy"] = "replace_existing_attack_convert_flat_atk"
            rec.update({"applied": True, "reason": reason, "modifier_key": applied_key, "dynamic_value_key": value_key, "value": float(value)})
        audit.append(rec)


@dataclass
class LogEvent:
    av: float
    event_type: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class StatusEffect:
    id: str
    tags: set[str] = field(default_factory=set)
    modifiers: dict[str, Any] = field(default_factory=dict)
    stacks: int = 1
    max_stacks: int = 1
    duration_type: Optional[str] = None
    duration_value: Optional[int] = None
    source_id: Optional[str] = None
    duration_extra_turn_consumes: bool = False
    refresh_duration: bool = True

    @staticmethod
    def from_dict(raw: dict[str, Any], runtime_values_by_key: dict[Any, Any] | None = None) -> "StatusEffect":
        duration = raw.get("duration", {}) if isinstance(raw.get("duration", {}), dict) else {}
        stack_rule = raw.get("stack_rule", {}) if isinstance(raw.get("stack_rule", {}), dict) else {}
        duration_type = raw.get("duration_type") or duration.get("type")
        # Model-pack texts use a few human-facing duration names. Normalize the
        # stable aliases here so the simulator lifecycle stays data-driven.
        duration_aliases = {
            "wearer_turns": "source_turns",
            "owner_turn_start_decrement": "owner_turn_start_decrement",
            "source_turn_start_decrement": "owner_turn_start_decrement",
            "ally_turns_or_owner_turns": "ally_turns",
            "turns": "global_turns",
        }
        duration_type = duration_aliases.get(str(duration_type), duration_type) if duration_type is not None else None
        modifiers = deepcopy(raw.get("modifiers", {})) if isinstance(raw.get("modifiers", {}), dict) else {}
        # Generated status templates carry TBGD modifier DynamicValues separately
        # from simulator-native modifier fields. Preserve them on the runtime
        # status so property/value watcher effects can read them later without
        # leaking raw TBGD structures into the combat kernel.
        dynamic_values = _materialize_symbolic_dynamic_values(raw, modifiers, runtime_values_by_key=runtime_values_by_key)
        if isinstance(dynamic_values, dict) and dynamic_values:
            dyn_bucket = modifiers.setdefault("dynamic_values", {})
            if isinstance(dyn_bucket, dict):
                dyn_bucket.update(deepcopy(dynamic_values))
            for k, v in dynamic_values.items():
                modifiers.setdefault(str(k), deepcopy(v))
        symbolic_dynamic_values = raw.get("symbolic_dynamic_values")
        if isinstance(symbolic_dynamic_values, dict):
            sym_bucket = modifiers.setdefault("symbolic_dynamic_values", {})
            if isinstance(sym_bucket, dict):
                sym_bucket.update(deepcopy(symbolic_dynamic_values))
        property_hints = raw.get("property_hints")
        if isinstance(property_hints, list):
            modifiers.setdefault("property_hints", deepcopy(property_hints))
        _lower_property_hints_to_modifiers(raw, modifiers, dynamic_values_override=dynamic_values, runtime_values_by_key=runtime_values_by_key)
        return StatusEffect(
            id=str(raw["id"]),
            tags=set(normalize_str_list(raw.get("tags", []))),
            modifiers=modifiers,
            stacks=coerce_int(raw.get("stacks", 1), 1),
            max_stacks=coerce_int(raw.get("max_stacks", stack_rule.get("max_stacks", raw.get("stacks", 1))), 1),
            duration_type=duration_type,
            duration_value=(maybe_int(raw.get("duration_value")) if raw.get("duration_value") is not None else (maybe_int(duration.get("value")) if duration.get("value") is not None else None)),
            source_id=raw.get("source_id", raw.get("source", raw.get("owner"))),
            duration_extra_turn_consumes=coerce_bool(
                raw.get(
                    "duration_extra_turn_consumes",
                    duration.get("extra_turn_consumes", duration.get("extra_turn_consumes_duration", False)),
                )
            ),
            refresh_duration=coerce_bool(raw.get("refresh_duration", stack_rule.get("refresh_duration", True)), default=True),
        )

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["tags"] = sorted(self.tags)
        return d


@dataclass
class UnitState:
    id: str
    name: str
    side: str
    hp: float
    max_hp: float
    shield: float = 0.0
    hp_bars_total: int = 1
    hp_bars_remaining: int = 1
    hp_model_type: str = "normal_hp"  # normal_hp | segmented_hp | phase_hp
    hp_carry_over_damage: Optional[bool] = None
    hp_model_bars: list[dict[str, Any]] = field(default_factory=list)
    speed: float = 100.0
    remaining_av: float = 0.0
    level: int = 80
    energy: float = 0.0
    max_energy: float = 0.0
    toughness: Optional[float] = None
    max_toughness: Optional[float] = None
    is_broken: bool = False
    weaknesses: set[str] = field(default_factory=set)
    tags: set[str] = field(default_factory=set)
    stats: dict[str, float] = field(default_factory=dict)
    stat_base: dict[str, float] = field(default_factory=dict)
    stat_pct: dict[str, float] = field(default_factory=dict)
    stat_flat: dict[str, float] = field(default_factory=dict)
    res: dict[str, float] = field(default_factory=dict)
    statuses: list[StatusEffect] = field(default_factory=list)
    action_defs: dict[str, dict[str, Any]] = field(default_factory=dict)
    status_defs: dict[str, dict[str, Any]] = field(default_factory=dict)
    alive: bool = True
    flags: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_dict(unit_id: str, raw: dict[str, Any]) -> "UnitState":
        statuses = [StatusEffect.from_dict(s) for s in raw.get("statuses", [])]
        hp_model_raw = raw.get("hp_model", {}) or {}
        hp_model_type = hp_model_raw.get("type") or raw.get("hp_model_type")
        hp_carry_over = hp_model_raw.get("carry_over_damage", raw.get("carry_over_damage", None))

        # Explicit HP semantics:
        # - normal_hp: a single HP pool.
        # - segmented_hp: multiple visible segments within one phase; overflow damage carries by default.
        # - phase_hp: each bar is a phase boundary; overflow damage does not carry by default.
        hp_model_bars = deepcopy(hp_model_raw.get("bars", [])) if isinstance(hp_model_raw.get("bars"), list) else []
        if hp_model_bars:
            inferred_bars = len(hp_model_bars)
            raw_remaining = coerce_int(raw.get("hp_bars_remaining", raw.get("hp_bars", inferred_bars)), inferred_bars)
            current_bar_index = max(0, min(inferred_bars - 1, inferred_bars - raw_remaining))
            current_bar = hp_model_bars[current_bar_index]
            current_bar_hp = coerce_float(current_bar.get("hp", raw.get("max_hp", raw.get("hp", 1))))
            hp = coerce_float(raw.get("hp", current_bar_hp))
            max_hp = coerce_float(raw.get("max_hp", current_bar_hp))
        elif "hp_per_bar" in raw:
            hp = coerce_float(raw.get("hp", raw.get("hp_per_bar")))
            max_hp = coerce_float(raw.get("max_hp", raw.get("hp_per_bar")))
            inferred_bars = coerce_int(raw.get("hp_bars_total", raw.get("hp_bars", 1)), 1)
        else:
            hp = coerce_float(raw.get("hp", raw.get("max_hp", 1)))
            max_hp = coerce_float(raw.get("max_hp", hp))
            inferred_bars = coerce_int(raw.get("hp_bars_total", raw.get("hp_bars", 1)), 1)

        if hp_model_type is None:
            if inferred_bars > 1:
                # Historical default for multi-bar units is phase semantics.
                hp_model_type = "segmented_hp" if coerce_bool(hp_carry_over, default=False) is True else "phase_hp"
            else:
                hp_model_type = "normal_hp"

        raw_flags = normalize_flag_values(deepcopy(raw.get("flags", {})))
        for meta_key in ("path", "element", "role", "position"):
            if meta_key in raw and meta_key not in raw_flags:
                raw_flags[meta_key] = raw.get(meta_key)
        # Common model-pack equipment/relic metadata is useful for predicates such as
        # "wearer has 4 pieces of genius_of_brilliant_stars".  Keep it on flags so
        # condition evaluation can remain data-driven without extending the UnitState schema.
        for meta_key in ("relic_sets", "sets", "equipment", "light_cone", "superimposition"):
            if meta_key in raw and meta_key not in raw_flags:
                raw_flags[meta_key] = deepcopy(raw.get(meta_key))

        unit = UnitState(
            id=unit_id,
            name=raw.get("name", unit_id),
            side=raw.get("side", "ally"),
            hp=hp,
            max_hp=max_hp,
            shield=coerce_float(raw.get("shield", 0.0)),
            hp_bars_total=coerce_int(raw.get("hp_bars_total", raw.get("hp_bars", inferred_bars)), inferred_bars),
            hp_bars_remaining=coerce_int(raw.get("hp_bars_remaining", raw.get("hp_bars", inferred_bars)), inferred_bars),
            hp_model_type=str(hp_model_type),
            hp_carry_over_damage=None if hp_carry_over is None else coerce_bool(hp_carry_over),
            hp_model_bars=hp_model_bars,
            speed=coerce_float(raw.get("speed", raw.get("stats", {}).get("speed", 100))),
            # Temporary value; corrected below when remaining_av is omitted so split
            # stat models such as base_speed + flat_speed are respected.
            remaining_av=coerce_float(raw.get("remaining_av", 0.0)),
            level=coerce_int(raw.get("level", 80), 80),
            energy=coerce_float(raw.get("energy", 0)),
            max_energy=coerce_float(raw.get("max_energy", 0)),
            toughness=None if is_infinite_marker(raw.get("toughness")) else coerce_float(raw.get("toughness")),
            max_toughness=None if is_infinite_marker(raw.get("max_toughness", raw.get("toughness"))) else coerce_float(raw.get("max_toughness", raw.get("toughness", 0) or 0)),
            is_broken=coerce_bool(raw.get("is_broken", False), default=False),
            weaknesses=set(normalize_str_list(raw.get("weaknesses", []))),
            tags=set(normalize_str_list(raw.get("tags", []))),
            stats=numeric_dict(raw.get("stats", {})),
            stat_base=numeric_dict(raw.get("stat_base", raw.get("base_stats", {}))),
            stat_pct=numeric_dict(raw.get("stat_pct", raw.get("pct_stats", {}))),
            stat_flat=numeric_dict(raw.get("stat_flat", raw.get("flat_stats", {}))),
            res=numeric_dict(raw.get("res", raw.get("resistance", {}))),
            statuses=statuses,
            action_defs=deepcopy(raw.get("actions", {})),
            status_defs=deepcopy(raw.get("status_effects", raw.get("status_definitions", {}))),
            alive=coerce_bool(raw.get("alive", hp > 0), default=(hp > 0)),
            flags=raw_flags,
        )
        if "remaining_av" not in raw:
            initial_speed = unit.get_stat("speed") or unit.speed
            unit.remaining_av = 10000.0 / max(initial_speed, EPS)
        return unit

    @property
    def hp_percent(self) -> float:
        return 0.0 if self.max_hp <= 0 else self.hp / self.max_hp

    def get_stat(self, name: str) -> float:
        """Return current stat using HSR-style base/pct/flat when available.

        For stats with explicit stat_base/stat_pct/stat_flat parts, the formula is:
          final = base * (1 + pct + status_pct) + flat + status_flat
        This fixes the important SPD case: Seele 115 base + 8 flat, then +25% SPD
        becomes 115 * 1.25 + 8 = 151.75, not 123 * 1.25.

        If no split stat model is provided, fall back to legacy `stats[name]` as a
        precomputed final value, with status modifiers applied multiplicatively/additively.
        """
        has_split = name in self.stat_base or name in self.stat_pct or name in self.stat_flat
        add = 0.0
        pct = 0.0
        for st in self.statuses:
            mods = st.modifiers
            add += coerce_float(mods.get(f"{name}_add", 0.0)) * st.stacks
            pct += coerce_float(mods.get(f"{name}_pct", 0.0)) * st.stacks
        if has_split:
            base = coerce_float(self.stat_base.get(name, 0.0))
            flat = coerce_float(self.stat_flat.get(name, 0.0))
            base_pct = coerce_float(self.stat_pct.get(name, 0.0))
            return base * (1.0 + base_pct + pct) + flat + add
        base = coerce_float(self.stats.get(name, 0.0))
        return base * (1.0 + pct) + add

    def add_status(self, status: StatusEffect) -> None:
        for existing in self.statuses:
            if existing.id == status.id:
                if status.modifiers.get("__replace_existing_modifiers"):
                    existing.modifiers = deepcopy(status.modifiers)
                    existing.stacks = status.stacks
                else:
                    existing.stacks = min(existing.max_stacks, existing.stacks + status.stacks)
                if status.duration_value is not None and status.refresh_duration:
                    existing.duration_value = status.duration_value
                    existing.duration_type = status.duration_type or existing.duration_type
                    existing.duration_extra_turn_consumes = status.duration_extra_turn_consumes
                # Latest source wins only if explicitly provided.
                if status.source_id is not None:
                    existing.source_id = status.source_id
                return
        self.statuses.append(status)

    def remove_status(self, status_id: str) -> None:
        self.statuses = [s for s in self.statuses if s.id != status_id]

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "side": self.side,
            "hp": round(self.hp, 6),
            "max_hp": round(self.max_hp, 6),
            "shield": round(self.shield, 6),
            "hp_bars_total": self.hp_bars_total,
            "hp_bars_remaining": self.hp_bars_remaining,
            "hp_model_type": self.hp_model_type,
            "hp_carry_over_damage": self.hp_carry_over_damage,
            "hp_model_bars": deepcopy(self.hp_model_bars),
            "hp_percent": round(self.hp_percent, 6),
            "energy": round(self.energy, 6),
            "max_energy": round(self.max_energy, 6),
            "speed": round((self.get_stat("speed") or self.speed), 6),
            "base_speed_field": round(self.speed, 6),
            "remaining_av": round(self.remaining_av, 6),
            "toughness": None if self.toughness is None else round(self.toughness, 6),
            "max_toughness": None if self.max_toughness is None else round(self.max_toughness, 6),
            "is_broken": self.is_broken,
            "alive": self.alive,
            "weaknesses": sorted(self.weaknesses),
            "tags": sorted(self.tags),
            "stats": self.stats,
            "stat_base": self.stat_base,
            "stat_pct": self.stat_pct,
            "stat_flat": self.stat_flat,
            "res": self.res,
            "statuses": [s.to_json() for s in self.statuses],
            "status_defs": sorted(self.status_defs.keys()),
            "flags": self.flags,
        }


@dataclass
class BattleState:
    av: float
    cycle: int
    skill_points: int
    skill_point_cap: int
    units: dict[str, UnitState]
    waves: list[dict[str, Any]] = field(default_factory=list)
    wave_index: int = 0
    triggers: list[dict[str, Any]] = field(default_factory=list)
    global_flags: dict[str, Any] = field(default_factory=dict)
    trigger_usage: dict[str, int] = field(default_factory=dict)
    ultimate_queue: deque[dict[str, Any]] = field(default_factory=deque)
    immediate_queue: deque[dict[str, Any]] = field(default_factory=deque)
    interrupt_queue: deque[dict[str, Any]] = field(default_factory=deque)
    log: list[LogEvent] = field(default_factory=list)

    @staticmethod
    def from_case(raw: dict[str, Any]) -> "BattleState":
        units = {uid: UnitState.from_dict(uid, u) for uid, u in raw.get("units", {}).items()}
        g = raw.get("global", {})
        # Model-template units may carry their own triggers.  Earlier versions
        # only loaded top-level triggers, so direct model-pack replay silently
        # lost mechanics such as Seele Resurgence and Sparkle Figment.
        triggers = normalize_triggers(deepcopy(raw.get("triggers", [])))
        for uid, raw_unit in raw.get("units", {}).items():
            for trig in normalize_triggers(deepcopy(raw_unit.get("triggers", []))):
                trig.setdefault("owner", uid)
                trig.setdefault("owner_id", uid)
                trig.setdefault("source_unit", uid)
                triggers.append(trig)
        return BattleState(
            av=coerce_float(g.get("av", 0)),
            cycle=coerce_int(g.get("cycle", 0), 0),
            skill_points=coerce_int(g.get("skill_points", 3), 3),
            skill_point_cap=coerce_int(g.get("skill_point_cap", 5), 5),
            units=units,
            waves=deepcopy(raw.get("waves", [])),
            wave_index=coerce_int(g.get("wave_index", raw.get("wave_index", 0)), 0),
            triggers=triggers,
            global_flags=normalize_flag_values(deepcopy(g.get("flags", raw.get("flags", {})))),
        )

    def unit(self, unit_id: str) -> UnitState:
        if unit_id not in self.units:
            raise KeyError(f"Unknown unit: {unit_id}")
        return self.units[unit_id]

    def active_units(self) -> list[UnitState]:
        return [u for u in self.units.values() if u.alive and "not_on_timeline" not in u.tags]

    def enemies_alive(self) -> list[UnitState]:
        return [u for u in self.units.values() if u.side == "enemy" and u.alive]

    def allies_alive(self) -> list[UnitState]:
        return [u for u in self.units.values() if u.side == "ally" and u.alive]

    def log_event(self, event_type: str, message: str, data: Optional[dict[str, Any]] = None) -> None:
        self.log.append(LogEvent(round(self.av, 6), event_type, message, data or {}))

    def update_cycle_index(self, first_cycle_av: float = 150.0, later_cycle_av: float = 100.0) -> None:
        """Update completed-cycle index from AV.

        HSR-style cycle accounting is usually 150 AV for cycle 0, then 100 AV
        per cycle. We store the number of completed cycle boundaries crossed:
        AV < 150 -> 0, 150 <= AV < 250 -> 1, etc.
        """
        if self.av + EPS < first_cycle_av:
            new_cycle = 0
        else:
            new_cycle = 1 + int(math.floor((self.av - first_cycle_av + EPS) / later_cycle_av))
        if new_cycle != self.cycle:
            old = self.cycle
            self.cycle = new_cycle
            self.log_event("cycle_update", f"Cycle index {old} -> {new_cycle}", {"old": old, "new": new_cycle, "av": self.av})

    def to_json(self) -> dict[str, Any]:
        return {
            "global": {
                "av": round(self.av, 6),
                "cycle": self.cycle,
                "skill_points": self.skill_points,
                "skill_point_cap": self.skill_point_cap,
                "wave_index": self.wave_index,
                "flags": self.global_flags,
            },
            "units": {uid: u.to_json() for uid, u in self.units.items()},
            "trigger_usage": self.trigger_usage,
            "queued_actions": {
                "ultimate_queue": list(self.ultimate_queue),
                "immediate_queue": list(self.immediate_queue),
                "interrupt_queue": list(self.interrupt_queue),
            },
        }


class SimulatorError(Exception):
    pass


class BattleSimulator:
    def __init__(self, case: dict[str, Any], tbgd_source: Any = None):
        case = canonicalize_case(case)
        self.raw_case = deepcopy(case)
        self.state = BattleState.from_case(case)
        self.settings = case.get("settings", {})
        self._queued_action_transitions: list[dict[str, Any]] = []
        # Phase 1+2: 可选的数据注册表（中文名增强）
        self._text_map: TextMapRegistry | None = None
        self._status_registry: StatusRegistry | None = None
        self._skill_registry: SkillRegistry | None = None
        if tbgd_source is not None:
            try:
                self._text_map = TextMapRegistry(tbgd_source)
                self._status_registry = StatusRegistry(tbgd_source, self._text_map)
                self._skill_registry = SkillRegistry(tbgd_source, self._text_map)
            except Exception:
                pass  # registries are optional enhancements
        for unit in self.state.units.values():
            self.ensure_souldragon_unit_defaults(unit)
            self.ensure_danheng_pt_action_semantics(unit)
        if self.state.waves and not self.state.enemies_alive():
            self.spawn_wave(self.state.wave_index)
        self.resolve_initial_setup()

    # ── Phase 2 辅助 ──

    def _settlement(self, ctx: dict[str, Any]) -> SettlementCollector | None:
        """从 ctx 中提取结算收集器。"""
        return ctx.get("_settlement") if isinstance(ctx, dict) else None

    def _settle(self, ctx: dict[str, Any], record_type: str, **kwargs: Any) -> None:
        """向结算收集器写入一条记录（若存在）。"""
        stl = self._settlement(ctx)
        if stl is not None:
            method = getattr(stl, f"record_{record_type}", None)
            if method is not None:
                method(**kwargs)

    def begin_route_control_settlement(self, step: dict[str, Any]) -> SettlementCollector:
        settlement = SettlementCollector(
            text_map=self._text_map,
            status_registry=self._status_registry,
            skill_registry=self._skill_registry,
        )
        settlement.begin_action(ActionRequest.from_route_control_step(step))
        settlement.capture_before_snapshot(self.full_scene_snapshot())
        step["_settlement"] = settlement
        return settlement

    def begin_queued_action_settlement(
        self,
        item: dict[str, Any],
        queue_name: str,
        queue_index: int,
        targets: list[str],
        *,
        target_source: str,
    ) -> SettlementCollector:
        settlement = SettlementCollector(
            text_map=self._text_map,
            status_registry=self._status_registry,
            skill_registry=self._skill_registry,
        )
        request = ActionRequest.from_queued_action(
            item,
            targets or [],
            queue_name=queue_name,
            queue_index=queue_index,
            target_source=target_source,
        )
        settlement.begin_action(request)
        settlement.capture_before_snapshot(self.full_scene_snapshot())
        settlement.record_target(targets or [], method=target_source)
        return settlement

    def record_queued_action_transition(
        self,
        item: dict[str, Any],
        queue_name: str,
        queue_index: int,
        settlement: SettlementCollector,
        *,
        skipped: bool = False,
        skip_reason: str = "",
    ) -> None:
        self._queued_action_transitions.append(
            {
                "queue_name": queue_name,
                "queue_index": queue_index,
                "actor": item.get("actor"),
                "action": item.get("action"),
                "turn_kind": item.get("turn_kind"),
                "extra_turn_type": item.get("extra_turn_type"),
                "skipped": bool(skipped),
                "skip_reason": str(skip_reason or ""),
                "settlement": settlement.to_dict(),
            }
        )

    def kernel_source_from_context(self, ctx: Optional[dict[str, Any]], reason: str = "") -> SourceRef:
        ctx = ctx or {}
        action = ctx.get("action") if isinstance(ctx.get("action"), dict) else {}
        actor_id = str(ctx.get("actor_id") or action.get("actor_id") or "")
        action_id = str(action.get("id") or action.get("action_id") or reason or "")
        source_type = "effect" if str(reason).startswith("effect:") else "action"
        origin_path = ""
        stl = self._settlement(ctx)
        if stl is not None:
            request_source = stl.transition.request.source
            origin_path = request_source.origin_path
            if source_type == "action" and request_source.source_type != "action":
                source_type = request_source.source_type
        return SourceRef(source_type=source_type, source_id=action_id, owner_id=actor_id, origin_path=origin_path)

    def record_committed_state_change(self, ctx: Optional[dict[str, Any]], change: StateChange) -> None:
        stl = self._settlement(ctx or {})
        if stl is not None:
            stl.record_state_change(change)

    def commit_state_change(self, change: StateChange, ctx: Optional[dict[str, Any]] = None) -> StateChange:
        """Apply a normalized state change to BattleState and attach it to the current transition."""
        if change.scope == "global" and change.field_path == "global.skill_points":
            self.state.skill_points = int(change.new_value)
        elif change.scope == "global" and change.field_path == "global.skill_point_cap":
            self.state.skill_point_cap = int(change.new_value)
        elif change.scope == "global" and change.field_path == "global.av":
            self.state.av = float(change.new_value)
        elif change.scope == "global" and change.field_path.startswith("global.flags."):
            key = change.field_path[len("global.flags."):]
            if change.delta == "remove":
                self.state.global_flags.pop(key, None)
            else:
                self.state.global_flags[key] = deepcopy(change.new_value)
        elif change.scope == "battle" and change.field_path.startswith("battle.queues."):
            queue_name = change.field_path[len("battle.queues."):]
            queue = self.battle_queue(queue_name)
            queue.clear()
            queue.extend(deepcopy(change.new_value or []))
        elif change.scope == "unit" and change.field_path == "unit.energy":
            self.state.unit(change.subject_id).energy = float(change.new_value)
        elif change.scope == "unit" and change.field_path == "unit.hp":
            self.state.unit(change.subject_id).hp = float(change.new_value)
        elif change.scope == "unit" and change.field_path == "unit.shield":
            self.state.unit(change.subject_id).shield = float(change.new_value)
        elif change.scope == "unit" and change.field_path == "unit.max_hp":
            self.state.unit(change.subject_id).max_hp = float(change.new_value)
        elif change.scope == "unit" and change.field_path == "unit.hp_bars_remaining":
            self.state.unit(change.subject_id).hp_bars_remaining = int(change.new_value)
        elif change.scope == "unit" and change.field_path == "unit.alive":
            self.state.unit(change.subject_id).alive = bool(change.new_value)
        elif change.scope == "unit" and change.field_path == "unit.toughness":
            unit = self.state.unit(change.subject_id)
            unit.toughness = None if change.new_value is None else float(change.new_value)
        elif change.scope == "unit" and change.field_path == "unit.max_toughness":
            unit = self.state.unit(change.subject_id)
            unit.max_toughness = None if change.new_value is None else float(change.new_value)
        elif change.scope == "unit" and change.field_path == "unit.is_broken":
            self.state.unit(change.subject_id).is_broken = bool(change.new_value)
        elif change.scope == "unit" and change.field_path == "unit.remaining_av":
            self.state.unit(change.subject_id).remaining_av = float(change.new_value)
        elif change.scope == "unit" and change.field_path.startswith("unit.flags."):
            key = change.field_path[len("unit.flags."):]
            if change.delta == "remove":
                self.state.unit(change.subject_id).flags.pop(key, None)
            else:
                self.state.unit(change.subject_id).flags[key] = deepcopy(change.new_value)
        elif change.scope == "unit" and change.field_path.startswith("unit.statuses."):
            path = change.field_path[len("unit.statuses."):]
            unit = self.state.unit(change.subject_id)
            if "." not in path:
                status_id = path
                if not status_id:
                    raise SimulatorError(f"Unsupported status StateChange path: {change.field_path}")
                if change.new_value is None:
                    unit.statuses = [row for row in unit.statuses if row.id != status_id]
                else:
                    raw = deepcopy(change.new_value)
                    if isinstance(raw, StatusEffect):
                        raw = raw.to_json()
                    if not isinstance(raw, dict):
                        raise SimulatorError(f"Status StateChange new_value must be a dict: {change.field_path}")
                    if str(raw.get("id", status_id)) != status_id:
                        raise SimulatorError(f"Status StateChange id mismatch: {status_id} != {raw.get('id')}")
                    raw["id"] = status_id
                    replacement = StatusEffect.from_dict(raw)
                    for idx, row in enumerate(unit.statuses):
                        if row.id == status_id:
                            unit.statuses[idx] = replacement
                            break
                    else:
                        unit.statuses.append(replacement)
            else:
                status = None
                status_field_path = ""
                for row in sorted(unit.statuses, key=lambda item: len(item.id), reverse=True):
                    prefix = f"{row.id}."
                    if path.startswith(prefix):
                        status = row
                        status_field_path = path[len(prefix):]
                        break
                if status is None or not status_field_path:
                    raise SimulatorError(f"Unsupported status StateChange path: {change.field_path}")
                if status_field_path in {"stacks", "max_stacks"}:
                    setattr(status, status_field_path, int(change.new_value))
                elif status_field_path == "duration_value":
                    status.duration_value = None if change.new_value is None else int(change.new_value)
                elif status_field_path == "duration_type":
                    status.duration_type = None if change.new_value is None else str(change.new_value)
                elif status_field_path == "duration_extra_turn_consumes":
                    status.duration_extra_turn_consumes = bool(change.new_value)
                elif status_field_path.startswith("modifiers."):
                    key = status_field_path[len("modifiers."):]
                    if not key:
                        raise SimulatorError(f"Unsupported status modifier StateChange path: {change.field_path}")
                    status.modifiers[key] = deepcopy(change.new_value)
                else:
                    raise SimulatorError(f"Unsupported status StateChange field: {status_field_path}")
        else:
            raise SimulatorError(f"Unsupported StateChange commit path: {change.scope}:{change.field_path}")
        self.record_committed_state_change(ctx, change)
        return change

    def commit_skill_points(self, new_value: float, *, reason: str, ctx: Optional[dict[str, Any]] = None, payload: Optional[dict[str, Any]] = None) -> StateChange:
        old = self.state.skill_points
        new_sp = int(clamp(coerce_float(new_value, old), 0, self.state.skill_point_cap))
        change = StateChange(
            change_type="resource",
            scope="global",
            subject_id="team",
            field_path="global.skill_points",
            old_value=old,
            new_value=new_sp,
            delta=new_sp - old,
            source=self.kernel_source_from_context(ctx, reason),
            reason=reason,
            payload=payload or {},
        )
        return self.commit_state_change(change, ctx)

    def commit_unit_alive(self, unit: UnitState, alive: bool, *, reason: str, ctx: Optional[dict[str, Any]] = None, payload: Optional[dict[str, Any]] = None) -> StateChange:
        old = unit.alive
        new_alive = bool(alive)
        change = StateChange(
            change_type="mechanic",
            scope="unit",
            subject_id=unit.id,
            field_path="unit.alive",
            old_value=old,
            new_value=new_alive,
            source=self.kernel_source_from_context(ctx, reason),
            reason=reason,
            payload=payload or {},
        )
        return self.commit_state_change(change, ctx)

    def commit_unit_max_hp(self, unit: UnitState, new_value: float, *, reason: str, ctx: Optional[dict[str, Any]] = None, payload: Optional[dict[str, Any]] = None) -> StateChange:
        old = unit.max_hp
        new_max_hp = max(1.0, coerce_float(new_value, old))
        change = StateChange(
            change_type="resource",
            scope="unit",
            subject_id=unit.id,
            field_path="unit.max_hp",
            old_value=old,
            new_value=new_max_hp,
            delta=new_max_hp - old,
            source=self.kernel_source_from_context(ctx, reason),
            reason=reason,
            payload=payload or {},
        )
        return self.commit_state_change(change, ctx)

    def commit_unit_hp_bars_remaining(self, unit: UnitState, new_value: int, *, reason: str, ctx: Optional[dict[str, Any]] = None, payload: Optional[dict[str, Any]] = None) -> StateChange:
        old = unit.hp_bars_remaining
        total = max(0, int(unit.hp_bars_total or old or 0))
        new_bars = coerce_int(new_value, old)
        if total > 0:
            new_bars = max(0, min(total, new_bars))
        else:
            new_bars = max(0, new_bars)
        change = StateChange(
            change_type="mechanic",
            scope="unit",
            subject_id=unit.id,
            field_path="unit.hp_bars_remaining",
            old_value=old,
            new_value=new_bars,
            delta=new_bars - old,
            source=self.kernel_source_from_context(ctx, reason),
            reason=reason,
            payload=payload or {},
        )
        return self.commit_state_change(change, ctx)

    def commit_unit_toughness(self, unit: UnitState, new_value: Optional[float], *, reason: str, ctx: Optional[dict[str, Any]] = None, payload: Optional[dict[str, Any]] = None) -> StateChange:
        old = unit.toughness
        if new_value is None:
            new_toughness = None
        else:
            new_toughness = max(0.0, coerce_float(new_value, coerce_float(old, 0.0)))
        change = StateChange(
            change_type="toughness",
            scope="unit",
            subject_id=unit.id,
            field_path="unit.toughness",
            old_value=old,
            new_value=new_toughness,
            delta=None if old is None or new_toughness is None else new_toughness - old,
            source=self.kernel_source_from_context(ctx, reason),
            reason=reason,
            payload=payload or {},
        )
        return self.commit_state_change(change, ctx)

    def commit_unit_max_toughness(self, unit: UnitState, new_value: Optional[float], *, reason: str, ctx: Optional[dict[str, Any]] = None, payload: Optional[dict[str, Any]] = None) -> StateChange:
        old = unit.max_toughness
        if new_value is None:
            new_max_toughness = None
        else:
            new_max_toughness = max(0.0, coerce_float(new_value, coerce_float(old, 0.0)))
        change = StateChange(
            change_type="toughness",
            scope="unit",
            subject_id=unit.id,
            field_path="unit.max_toughness",
            old_value=old,
            new_value=new_max_toughness,
            delta=None if old is None or new_max_toughness is None else new_max_toughness - old,
            source=self.kernel_source_from_context(ctx, reason),
            reason=reason,
            payload=payload or {},
        )
        return self.commit_state_change(change, ctx)

    def commit_unit_is_broken(self, unit: UnitState, is_broken: bool, *, reason: str, ctx: Optional[dict[str, Any]] = None, payload: Optional[dict[str, Any]] = None) -> StateChange:
        old = unit.is_broken
        new_broken = bool(is_broken)
        change = StateChange(
            change_type="toughness",
            scope="unit",
            subject_id=unit.id,
            field_path="unit.is_broken",
            old_value=old,
            new_value=new_broken,
            source=self.kernel_source_from_context(ctx, reason),
            reason=reason,
            payload=payload or {},
        )
        return self.commit_state_change(change, ctx)

    def commit_unit_flag(self, unit: UnitState, key: str, value: Any, *, reason: str, ctx: Optional[dict[str, Any]] = None, payload: Optional[dict[str, Any]] = None) -> StateChange:
        key = str(key)
        old = deepcopy(unit.flags.get(key))
        change = StateChange(
            change_type="flag",
            scope="unit",
            subject_id=unit.id,
            field_path=f"unit.flags.{key}",
            old_value=old,
            new_value=deepcopy(value),
            source=self.kernel_source_from_context(ctx, reason),
            reason=reason,
            payload=payload or {},
        )
        return self.commit_state_change(change, ctx)

    def commit_unit_flag_remove(self, unit: UnitState, key: str, *, reason: str, ctx: Optional[dict[str, Any]] = None, payload: Optional[dict[str, Any]] = None) -> Optional[StateChange]:
        key = str(key)
        if key not in unit.flags:
            return None
        old = deepcopy(unit.flags.get(key))
        change = StateChange(
            change_type="flag",
            scope="unit",
            subject_id=unit.id,
            field_path=f"unit.flags.{key}",
            old_value=old,
            new_value=None,
            delta="remove",
            source=self.kernel_source_from_context(ctx, reason),
            reason=reason,
            payload=payload or {},
        )
        return self.commit_state_change(change, ctx)

    def merged_status_for_add(self, existing: Optional[StatusEffect], incoming: StatusEffect) -> StatusEffect:
        if existing is None:
            return deepcopy(incoming)
        merged = deepcopy(existing)
        if incoming.modifiers.get("__replace_existing_modifiers"):
            merged.modifiers = deepcopy(incoming.modifiers)
            merged.stacks = incoming.stacks
        else:
            merged.stacks = min(merged.max_stacks, merged.stacks + incoming.stacks)
        if incoming.duration_value is not None and incoming.refresh_duration:
            merged.duration_value = incoming.duration_value
            merged.duration_type = incoming.duration_type or merged.duration_type
            merged.duration_extra_turn_consumes = incoming.duration_extra_turn_consumes
        if incoming.source_id is not None:
            merged.source_id = incoming.source_id
        return merged

    def commit_status_entry(self, unit: UnitState, status: StatusEffect, *, reason: str, ctx: Optional[dict[str, Any]] = None, payload: Optional[dict[str, Any]] = None, change_kind: str = "set") -> StateChange:
        existing = next((row for row in unit.statuses if row.id == status.id), None)
        old_value = existing.to_json() if existing is not None else None
        new_value = status.to_json()
        origin = self.kernel_source_from_context(ctx, reason).origin_path
        change = StateChange(
            change_type="status",
            scope="unit",
            subject_id=unit.id,
            field_path=f"unit.statuses.{status.id}",
            old_value=old_value,
            new_value=new_value,
            delta=change_kind,
            source=SourceRef.status(owner_id=status.source_id or unit.id, status_id=status.id, origin_path=origin),
            reason=reason,
            payload=payload or {},
        )
        return self.commit_state_change(change, ctx)

    def commit_status_remove(self, unit: UnitState, status: StatusEffect | str, *, reason: str, ctx: Optional[dict[str, Any]] = None, payload: Optional[dict[str, Any]] = None) -> Optional[StateChange]:
        status_id = status.id if isinstance(status, StatusEffect) else str(status)
        existing = next((row for row in unit.statuses if row.id == status_id), None)
        if existing is None:
            return None
        origin = self.kernel_source_from_context(ctx, reason).origin_path
        change = StateChange(
            change_type="status",
            scope="unit",
            subject_id=unit.id,
            field_path=f"unit.statuses.{status_id}",
            old_value=existing.to_json(),
            new_value=None,
            delta="remove",
            source=SourceRef.status(owner_id=existing.source_id or unit.id, status_id=status_id, origin_path=origin),
            reason=reason,
            payload=payload or {},
        )
        return self.commit_state_change(change, ctx)

    def commit_status_field(self, unit: UnitState, status: StatusEffect, field_name: str, value: Any, *, reason: str, ctx: Optional[dict[str, Any]] = None, payload: Optional[dict[str, Any]] = None) -> StateChange:
        field_name = str(field_name)
        if field_name not in {"stacks", "max_stacks", "duration_value", "duration_type", "duration_extra_turn_consumes"}:
            raise SimulatorError(f"Unsupported status field commit: {field_name}")
        old = deepcopy(getattr(status, field_name))
        if field_name == "stacks":
            new_value = max(0, coerce_int(value, int(old or 0)))
            delta = new_value - int(old or 0)
        elif field_name == "max_stacks":
            new_value = max(0, coerce_int(value, int(old or 0)))
            delta = new_value - int(old or 0)
        elif field_name == "duration_value":
            new_value = None if value is None else coerce_int(value, int(old or 0))
            delta = None if old is None or new_value is None else new_value - int(old)
        elif field_name == "duration_type":
            new_value = None if value is None else str(value)
            delta = None
        elif field_name == "duration_extra_turn_consumes":
            new_value = bool(value)
            delta = None
        origin = self.kernel_source_from_context(ctx, reason).origin_path
        change = StateChange(
            change_type="status",
            scope="unit",
            subject_id=unit.id,
            field_path=f"unit.statuses.{status.id}.{field_name}",
            old_value=old,
            new_value=new_value,
            delta=delta,
            source=SourceRef.status(owner_id=status.source_id or unit.id, status_id=status.id, origin_path=origin),
            reason=reason,
            payload=payload or {},
        )
        return self.commit_state_change(change, ctx)

    def commit_status_stacks(self, unit: UnitState, status: StatusEffect, value: Any, *, reason: str, ctx: Optional[dict[str, Any]] = None, payload: Optional[dict[str, Any]] = None) -> StateChange:
        return self.commit_status_field(unit, status, "stacks", value, reason=reason, ctx=ctx, payload=payload)

    def commit_status_duration_value(self, unit: UnitState, status: StatusEffect, value: Any, *, reason: str, ctx: Optional[dict[str, Any]] = None, payload: Optional[dict[str, Any]] = None) -> StateChange:
        return self.commit_status_field(unit, status, "duration_value", value, reason=reason, ctx=ctx, payload=payload)

    def commit_status_modifier(self, unit: UnitState, status: StatusEffect, key: str, value: Any, *, reason: str, ctx: Optional[dict[str, Any]] = None, payload: Optional[dict[str, Any]] = None) -> StateChange:
        key = str(key)
        if not key:
            raise SimulatorError("Status modifier key cannot be empty")
        old = deepcopy(status.modifiers.get(key))
        new_value = deepcopy(value)
        origin = self.kernel_source_from_context(ctx, reason).origin_path
        change = StateChange(
            change_type="status",
            scope="unit",
            subject_id=unit.id,
            field_path=f"unit.statuses.{status.id}.modifiers.{key}",
            old_value=old,
            new_value=new_value,
            source=SourceRef.status(owner_id=status.source_id or unit.id, status_id=status.id, origin_path=origin),
            reason=reason,
            payload=payload or {},
        )
        return self.commit_state_change(change, ctx)

    def commit_unit_hp(self, unit: UnitState, new_value: float, *, reason: str, ctx: Optional[dict[str, Any]] = None, payload: Optional[dict[str, Any]] = None) -> StateChange:
        old = unit.hp
        new_hp = clamp(coerce_float(new_value, old), 0.0, unit.max_hp)
        change = StateChange(
            change_type="resource",
            scope="unit",
            subject_id=unit.id,
            field_path="unit.hp",
            old_value=old,
            new_value=new_hp,
            delta=new_hp - old,
            source=self.kernel_source_from_context(ctx, reason),
            reason=reason,
            payload=payload or {},
        )
        return self.commit_state_change(change, ctx)

    def commit_unit_shield(self, unit: UnitState, new_value: float, *, reason: str, ctx: Optional[dict[str, Any]] = None, payload: Optional[dict[str, Any]] = None) -> StateChange:
        old = unit.shield
        new_shield = max(0.0, coerce_float(new_value, old))
        change = StateChange(
            change_type="resource",
            scope="unit",
            subject_id=unit.id,
            field_path="unit.shield",
            old_value=old,
            new_value=new_shield,
            delta=new_shield - old,
            source=self.kernel_source_from_context(ctx, reason),
            reason=reason,
            payload=payload or {},
        )
        return self.commit_state_change(change, ctx)

    def commit_unit_energy(self, unit: UnitState, new_value: float, *, reason: str, ctx: Optional[dict[str, Any]] = None, payload: Optional[dict[str, Any]] = None) -> StateChange:
        old = unit.energy
        new_energy = clamp(coerce_float(new_value, old), 0.0, unit.max_energy)
        change = StateChange(
            change_type="resource",
            scope="unit",
            subject_id=unit.id,
            field_path="unit.energy",
            old_value=old,
            new_value=new_energy,
            delta=new_energy - old,
            source=self.kernel_source_from_context(ctx, reason),
            reason=reason,
            payload=payload or {},
        )
        return self.commit_state_change(change, ctx)

    def commit_global_av(self, new_value: float, *, reason: str, ctx: Optional[dict[str, Any]] = None, payload: Optional[dict[str, Any]] = None) -> StateChange:
        old = self.state.av
        new_av = max(0.0, coerce_float(new_value, old))
        change = StateChange(
            change_type="timeline",
            scope="global",
            subject_id="battle",
            field_path="global.av",
            old_value=old,
            new_value=new_av,
            delta=new_av - old,
            source=self.kernel_source_from_context(ctx, reason),
            reason=reason,
            payload=payload or {},
        )
        return self.commit_state_change(change, ctx)

    def commit_unit_remaining_av(self, unit: UnitState, new_value: float, *, reason: str, ctx: Optional[dict[str, Any]] = None, payload: Optional[dict[str, Any]] = None) -> StateChange:
        old = unit.remaining_av
        new_remaining = max(0.0, coerce_float(new_value, old))
        change = StateChange(
            change_type="av",
            scope="unit",
            subject_id=unit.id,
            field_path="unit.remaining_av",
            old_value=old,
            new_value=new_remaining,
            delta=new_remaining - old,
            source=self.kernel_source_from_context(ctx, reason),
            reason=reason,
            payload=payload or {},
        )
        return self.commit_state_change(change, ctx)

    def commit_skill_point_cap(self, new_cap: float, *, reason: str, ctx: Optional[dict[str, Any]] = None, payload: Optional[dict[str, Any]] = None) -> StateChange:
        old = self.state.skill_point_cap
        cap = int(max(0, coerce_float(new_cap, old)))
        change = StateChange(
            change_type="resource",
            scope="global",
            subject_id="team",
            field_path="global.skill_point_cap",
            old_value=old,
            new_value=cap,
            delta=cap - old,
            source=self.kernel_source_from_context(ctx, reason),
            reason=reason,
            payload=payload or {},
        )
        return self.commit_state_change(change, ctx)

    def commit_global_flag(self, key: str, value: Any, *, reason: str, ctx: Optional[dict[str, Any]] = None, payload: Optional[dict[str, Any]] = None) -> StateChange:
        key = str(key)
        old = deepcopy(self.state.global_flags.get(key))
        change = StateChange(
            change_type="flag",
            scope="global",
            subject_id="global",
            field_path=f"global.flags.{key}",
            old_value=old,
            new_value=deepcopy(value),
            source=self.kernel_source_from_context(ctx, reason),
            reason=reason,
            payload=payload or {},
        )
        return self.commit_state_change(change, ctx)

    def normalized_queue_name(self, queue_name: str) -> str:
        queue_name = str(queue_name or "immediate_queue")
        if queue_name == "extra_turn_queue":
            return "interrupt_queue"
        if queue_name not in {"ultimate_queue", "immediate_queue", "interrupt_queue"}:
            raise SimulatorError(f"Unknown queue {queue_name}")
        return queue_name

    def battle_queue(self, queue_name: str):
        queue_name = self.normalized_queue_name(queue_name)
        if queue_name == "ultimate_queue":
            return self.state.ultimate_queue
        if queue_name == "immediate_queue":
            return self.state.immediate_queue
        if queue_name == "interrupt_queue":
            return self.state.interrupt_queue
        raise SimulatorError(f"Unknown queue {queue_name}")

    def commit_queue_append(self, queue_name: str, item: dict[str, Any], *, reason: str, ctx: Optional[dict[str, Any]] = None, payload: Optional[dict[str, Any]] = None) -> StateChange:
        requested_queue = str(queue_name or "immediate_queue")
        actual_queue = self.normalized_queue_name(requested_queue)
        queue = self.battle_queue(actual_queue)
        old = list(queue)
        item_copy = deepcopy(item)
        new_queue = old + [item_copy]
        change = StateChange(
            change_type="queue",
            scope="battle",
            subject_id=actual_queue,
            field_path=f"battle.queues.{actual_queue}",
            old_value=deepcopy(old),
            new_value=deepcopy(new_queue),
            delta={"op": "append", "index": len(old), "item": item_copy, "requested_queue": requested_queue},
            source=self.kernel_source_from_context(ctx, reason),
            reason=reason,
            payload=payload or {},
        )
        return self.commit_state_change(change, ctx)

    def commit_queue_popleft(self, queue_name: str, *, reason: str, ctx: Optional[dict[str, Any]] = None, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        actual_queue = self.normalized_queue_name(queue_name)
        queue = self.battle_queue(actual_queue)
        old = list(queue)
        if not old:
            raise SimulatorError(f"Cannot pop empty queue {actual_queue}")
        item = deepcopy(old[0])
        new_queue = old[1:]
        change = StateChange(
            change_type="queue",
            scope="battle",
            subject_id=actual_queue,
            field_path=f"battle.queues.{actual_queue}",
            old_value=deepcopy(old),
            new_value=deepcopy(new_queue),
            delta={"op": "popleft", "item": item},
            source=self.kernel_source_from_context(ctx, reason),
            reason=reason,
            payload=payload or {},
        )
        self.commit_state_change(change, ctx)
        return item

    def snapshot(self) -> dict[str, Any]:
        """Return a compact debug snapshot for assertions and diagnostics."""
        return {
            "state": self.state.to_json(),
            "log": [
                {"av": e.av, "event_type": e.event_type, "message": e.message, "data": e.data}
                for e in self.state.log
            ],
        }

    def modify_skill_points_with_overflow(self, amount: float, *, overflow_record: Optional[dict[str, Any]] = None, reason: str = "skill_point_change", ctx: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Change team SP and optionally record Sparkle-style overflow.

        Sparkle's enhanced Ultimate recovers 6 SP. If this overflows, the excess
        is stored (up to 10) and consumed at ally regular-turn end to refill SP
        back to cap. Keep this as a generic reserve so future SP overflow sources
        can reuse the same mechanic.
        """
        ctx = ctx or {}
        old = self.state.skill_points
        cap = self.state.skill_point_cap
        amount_f = coerce_float(amount, 0.0)
        applied = amount_f
        overflow = 0.0
        if amount_f >= 0:
            room = max(0.0, cap - old)
            applied = min(amount_f, room)
            overflow = max(0.0, amount_f - applied)
            new_value = int(clamp(old + applied, 0, cap))
        else:
            new_value = int(clamp(old + amount_f, 0, cap))
            applied = new_value - old
        self.commit_skill_points(
            new_value,
            reason=reason,
            ctx=ctx,
            payload={"requested_delta": amount_f, "applied": applied, "overflow": overflow},
        )
        reserve_after = self.state.global_flags.get("sparkle_overflow_skill_points", 0.0)
        recorded = 0.0
        if overflow > EPS and isinstance(overflow_record, dict) and coerce_bool(overflow_record.get("enabled", True), default=True):
            reserve_key = str(overflow_record.get("reserve_key", "sparkle_overflow_skill_points"))
            max_recorded = coerce_float(overflow_record.get("max_recorded_overflow", overflow_record.get("max", 10)), 10.0)
            before_reserve = coerce_float(self.state.global_flags.get(reserve_key, 0.0), 0.0)
            reserve_after = min(max_recorded, before_reserve + overflow)
            recorded = max(0.0, reserve_after - before_reserve)
            self.commit_global_flag(
                reserve_key,
                reserve_after,
                reason=f"{reason}:overflow_reserve",
                ctx=ctx,
                payload={"old_reserve": before_reserve, "overflow": overflow, "max_recorded": max_recorded},
            )
            self.state.log_event(
                "resource",
                f"Recorded {recorded:.3f} overflow skill point(s) into {reserve_key}",
                {"old_reserve": before_reserve, "new_reserve": reserve_after, "overflow": overflow, "max_recorded": max_recorded, "reason": reason},
            )
        self.state.log_event(
            "resource",
            f"Skill points {old} -> {self.state.skill_points}",
            {"delta": amount_f, "applied": applied, "overflow": overflow, "overflow_recorded": recorded, "reserve_after": reserve_after, "reason": reason},
        )
        return {"old": old, "new": self.state.skill_points, "delta": amount_f, "applied": applied, "overflow": overflow, "overflow_recorded": recorded, "reserve_after": reserve_after}

    def consume_skill_point_overflow_reserve_at_turn_end(self, actor: UnitState, turn_kind: str, context: Optional[dict[str, Any]] = None) -> None:
        """Consume Sparkle stored overflow SP at allied regular-turn end."""
        if turn_kind != "regular" or actor.side != "ally":
            return
        reserve_key = "sparkle_overflow_skill_points"
        reserve = coerce_float(self.state.global_flags.get(reserve_key, 0.0), 0.0)
        if reserve <= EPS or self.state.skill_points >= self.state.skill_point_cap:
            return
        need = max(0.0, self.state.skill_point_cap - self.state.skill_points)
        consume = min(reserve, need)
        old_sp = self.state.skill_points
        old_reserve = reserve
        ctx = context or {}
        self.commit_skill_points(
            self.state.skill_points + consume,
            reason="overflow_reserve_restore",
            ctx=ctx,
            payload={"actor": actor.id, "old_reserve": old_reserve, "consume": consume},
        )
        self.commit_global_flag(
            reserve_key,
            max(0.0, reserve - consume),
            reason="overflow_reserve_consume",
            ctx=ctx,
            payload={"actor": actor.id, "consume": consume},
        )
        self.state.log_event(
            "resource",
            f"Sparkle overflow SP reserve restores {consume:.3f} at {actor.id} turn end",
            {"old_skill_points": old_sp, "new_skill_points": self.state.skill_points, "old_reserve": old_reserve, "new_reserve": self.state.global_flags[reserve_key], "actor": actor.id},
        )

    def generic_shield_cap(self, target_id: str, ctx: dict[str, Any], eff: dict[str, Any]) -> float | None:
        """Generic stack cap for stackable shields.

        If an effect provides cap fields, shields stack additively up to that cap;
        otherwise they still stack without an explicit cap. Dan Heng PT shield
        fields use the same helper rather than a special-only path.
        """
        if "shield_cap" in eff:
            return coerce_float(eff.get("shield_cap"), 0.0)
        if "shield_cap_amount" in eff:
            return coerce_float(eff.get("shield_cap_amount"), 0.0)
        if "shield_cap_target_max_hp_pct" in eff:
            return self.state.unit(target_id).max_hp * coerce_float(eff.get("shield_cap_target_max_hp_pct"), 0.0)
        cap = self.souldragon_shield_cap(target_id, ctx, eff)
        if cap is not None:
            return cap
        if "shield_cap_source_stat_pct" in eff or "shield_cap_flat" in eff:
            src_id = self.resolve_special_unit(eff.get("shield_cap_source", eff.get("source", "actor")), ctx)
            stat = str(eff.get("shield_cap_source_stat", eff.get("source_stat", "atk")))
            base = 0.0
            if src_id in self.state.units:
                base += self.contextual_stat(self.state.unit(src_id), stat, {**ctx, "target_id": target_id, "target": self.state.unit(target_id)}) * coerce_float(eff.get("shield_cap_source_stat_pct", 0.0), 0.0)
            base += coerce_float(eff.get("shield_cap_flat", 0.0), 0.0)
            return base * coerce_float(eff.get("shield_cap_multiplier", 1.0), 1.0)
        return None

    def refresh_shield_status_after_stack(self, unit: UnitState, eff: dict[str, Any], added: float, cap: float | None, ctx: Optional[dict[str, Any]] = None) -> None:
        """Refresh shield duration and tracked expiry amount after stacking.

        HSR shield application is modeled as stackable shield value with duration
        refresh and optional cap.  A scalar shield pool cannot perfectly track
        multiple independent shields, but tracking the source status' remaining
        remove amount keeps replay semantics correct for this live route and for
        same-source shield refreshes.
        """
        status_id = eff.get("refresh_status_duration_id") or eff.get("shield_status_id") or eff.get("status_id")
        if not status_id:
            return
        st = next((s for s in unit.statuses if s.id == str(status_id)), None)
        if st is None:
            return
        duration_value = eff.get("duration_value", eff.get("duration_turns", eff.get("shield_duration_turns")))
        if duration_value is not None:
            self.commit_status_duration_value(
                unit,
                st,
                coerce_int(duration_value, st.duration_value or 0),
                reason="shield:refresh_status_duration",
                ctx=ctx,
                payload={"effect": deepcopy(eff), "added": added, "cap": cap},
            )
        old_remove = coerce_float(st.modifiers.get("shield_expire_remove_amount", 0.0), 0.0)
        new_remove = old_remove + max(0.0, added)
        if cap is not None:
            new_remove = min(new_remove, cap)
        self.commit_status_modifier(
            unit,
            st,
            "shield_expire_remove_amount",
            new_remove,
            reason="shield:refresh_expire_remove_amount",
            ctx=ctx,
            payload={"effect": deepcopy(eff), "added": added, "cap": cap},
        )
        self.state.log_event("shield", f"{unit.id}.{st.id} shield duration refreshed", {"duration_value": st.duration_value, "old_expire_remove_amount": old_remove, "new_expire_remove_amount": new_remove, "added": added, "cap": cap})

    def apply_stackable_shield(self, target_id: str, amount: float, eff: dict[str, Any], ctx: dict[str, Any], *, reason: str = "modify_shield") -> None:
        unit = self.state.unit(target_id)
        old = unit.shield
        cap = self.generic_shield_cap(target_id, ctx, eff)
        new_shield = max(0.0, old + max(0.0, amount))
        if cap is not None:
            new_shield = min(new_shield, cap)
        self.commit_unit_shield(
            unit,
            new_shield,
            reason=reason,
            ctx=ctx,
            payload={"amount": amount, "cap": cap, "effect": deepcopy(eff)},
        )
        added = max(0.0, new_shield - old)
        self.refresh_shield_status_after_stack(unit, eff, added, cap, ctx=ctx)
        self.state.log_event("effect", f"{target_id} shield stacked by {amount:.3f}", {"old": old, "new": unit.shield, "effective_added": added, "cap": cap, "source_effect": eff, "reason": reason})

    def unit_initial_av(self, unit: UnitState, raw: dict[str, Any]) -> float:
        """Compute initial timeline AV for a spawned/summoned unit.

        The video trace starts from real battle-start technique resolution and
        enemy summons. Some data rows carry an initial delay ratio, while older
        prototype cases omitted it and implicitly meant a full action interval.
        Honoring these aliases keeps summons and later waves from being placed
        on the wrong point of the action bar when replaying an observed route.
        """
        if "remaining_av" in raw:
            return coerce_float(raw["remaining_av"])
        if "initial_av" in raw:
            return coerce_float(raw["initial_av"])
        ratio = raw.get("initial_delay_ratio", raw.get("initial_delay", raw.get("delay_ratio", 1.0)))
        return self.action_interval(unit) * coerce_float(ratio, 1.0)

    SOULDRAGON_TEMPLATE = load_souldragon_action_template()
    SOULDRAGON_DEFAULTS = SOULDRAGON_TEMPLATE

    def souldragon_template_value(self, key: str, default: float = 0.0) -> float:
        return coerce_float((self.SOULDRAGON_TEMPLATE or {}).get(key, default), default)

    def attack_convert_scale(self) -> float:
        """Return the max-trace Dan Heng PT AttackConvert ratio.

        中文语义：【同袍】固定攻击力加成比例。当前数据库/行迹
        PointB1 确认满级为丹恒攻击力的 15%。这里集中成一个
        模板值，避免散落成硬编码。
        """
        return coerce_float((self.SOULDRAGON_TEMPLATE or {}).get("attack_convert_scale", 0.15), 0.15)

    def attack_convert_status_id(self) -> str:
        return "dan_heng_pt_attack_convert_dynamic"

    def is_attack_convert_status(self, status: StatusEffect | dict[str, Any]) -> bool:
        mods = status.modifiers if isinstance(status, StatusEffect) else (status.get("modifiers", {}) if isinstance(status, dict) else {})
        sid = status.id if isinstance(status, StatusEffect) else (status.get("id") if isinstance(status, dict) else "")
        if str(sid) == self.attack_convert_status_id():
            return True
        if not isinstance(mods, dict):
            return False
        for rec in mods.get("property_hint_applications", []) if isinstance(mods.get("property_hint_applications"), list) else []:
            if isinstance(rec, dict) and rec.get("property") == "AttackConvert":
                return True
        return coerce_bool(mods.get("attack_convert_dynamic", False), default=False)

    def make_attack_convert_status_raw(self, source_id: str | None = None) -> dict[str, Any]:
        owner_id = source_id if source_id in self.state.units else self.default_souldragon_owner_id()
        scale = self.attack_convert_scale()
        return {
            "id": self.attack_convert_status_id(),
            "tags": ["bondmate", "attack_convert", "derived_stat", "dan_heng_pt"],
            "modifiers": {
                "attack_convert_dynamic": True,
                "derived_stat_add": [
                    {
                        "id": "AttackConvert",
                        "stat": "atk",
                        "source": owner_id,
                        "source_stat": "atk",
                        "scale": scale,
                        "snapshot": False,
                        "bucket": "atk_add",
                        "cn": "同袍固定攻击力加成：丹恒当前攻击力 × 15%，非快照。",
                    }
                ],
                "property_hint_applications": [
                    {
                        "property": "AttackConvert",
                        "applied": True,
                        "reason": "runtime_dynamic_attack_convert",
                        "modifier_key": "atk_add",
                        "refresh_policy": "live_source_stat_non_snapshot",
                        "scale": scale,
                    }
                ],
                "__replace_existing_modifiers": True,
            },
            "source_id": owner_id,
            "refresh_duration": True,
        }

    def normalize_attack_convert_status_for_target(self, status: StatusEffect, target_id: str, ctx: dict[str, Any]) -> StatusEffect:
        """Convert generated/static AttackConvert into a live derived stat status.

        中文语义：数据库里 AttackConvert 表示【同袍】从丹恒当前攻击力
        派生出来的一段固定攻击力，不是一次性快照。只要发现生成
        status 带 AttackConvert，就改成 derived_stat_add，由 contextual_stat
        读取丹恒实时攻击力计算。
        """
        if not self.is_attack_convert_status(status):
            return status
        owner_id = ctx.get("actor_id") if ctx.get("actor_id") in self.state.units and self.is_danheng_pt_unit(self.state.unit(ctx.get("actor_id"))) else self.default_souldragon_owner_id()
        raw = self.make_attack_convert_status_raw(str(owner_id))
        out = StatusEffect.from_dict(raw)
        out.source_id = str(owner_id)
        return out

    def clear_bondmate_runtime_state(self, keep_target: str | None = None, ctx: dict[str, Any] | None = None) -> None:
        """Remove previous bondmate marks and AttackConvert from old targets.

        中文语义：丹恒战技会先移除全队旧【同袍】/攻击转换，再给
        新目标加。否则同袍切换时旧目标会残留攻击力加成。
        """
        removed: list[dict[str, Any]] = []
        for uid, unit in self.state.units.items():
            if unit.side != "ally":
                continue
            for st in list(unit.statuses):
                is_bondmate_mark = st.id == "bondmate" or "bondmate" in {str(t).lower() for t in st.tags}
                is_attack_convert = self.is_attack_convert_status(st)
                if uid != keep_target and (is_bondmate_mark or is_attack_convert):
                    removed.append({"unit": uid, "status_id": st.id})
                    self.commit_status_remove(
                        unit,
                        st,
                        reason="bondmate:clear_runtime_state",
                        ctx=ctx,
                        payload={"keep_target": keep_target, "removed_status": st.to_json()},
                    )
                    continue
                # Even on the new target, remove old dynamic/static AttackConvert; it will be re-added below.
                if uid == keep_target and is_attack_convert:
                    removed.append({"unit": uid, "status_id": st.id})
                    self.commit_status_remove(
                        unit,
                        st,
                        reason="bondmate:clear_attack_convert",
                        ctx=ctx,
                        payload={"keep_target": keep_target, "removed_status": st.to_json()},
                    )
                    continue
        if removed:
            self.state.log_event("bondmate_state", "Cleared previous bondmate/AttackConvert runtime state", {"removed": removed, "keep_target": keep_target})

    def apply_attack_convert_to_bondmate(self, target_id: str | None = None, source_id: str | None = None, ctx: dict[str, Any] | None = None) -> None:
        ctx = ctx or {}
        target_id = target_id or self.state.global_flags.get("bondmate") or self.state.global_flags.get("bondmate_target")
        if not target_id or str(target_id) not in self.state.units:
            return
        target_id = str(target_id)
        source_id = source_id or (ctx.get("actor_id") if ctx.get("actor_id") in self.state.units else None) or self.default_souldragon_owner_id()
        raw = self.make_attack_convert_status_raw(str(source_id))
        unit = self.state.unit(target_id)
        status = StatusEffect.from_dict(raw)
        status.source_id = str(source_id)
        before = next((s for s in unit.statuses if s.id == status.id), None)
        after_status = self.merged_status_for_add(before, status)
        self.commit_status_entry(
            unit,
            after_status,
            reason="bondmate:apply_attack_convert",
            ctx=ctx,
            payload={"incoming_status": status.to_json()},
            change_kind="add" if before is None else "refresh",
        )
        current_source_atk = self.contextual_stat(self.state.unit(str(source_id)), "atk", {**ctx, "actor_id": source_id}) if str(source_id) in self.state.units else 0.0
        value = current_source_atk * self.attack_convert_scale()
        self.state.log_event("bondmate_state", "Applied live AttackConvert to bondmate", {"target": target_id, "source": source_id, "scale": self.attack_convert_scale(), "current_value": value, "was_present": before is not None})

    def derived_status_add_for_stat(self, unit: UnitState, name: str, ctx: dict[str, Any]) -> float:
        total = 0.0
        for st in unit.statuses:
            mods = st.modifiers if isinstance(st.modifiers, dict) else {}
            entries = mods.get("derived_stat_add")
            if isinstance(entries, dict):
                entries = [entries]
            if not isinstance(entries, list):
                continue
            for ent in entries:
                if not isinstance(ent, dict) or str(ent.get("stat")) != str(name):
                    continue
                src_spec = ent.get("source", ent.get("source_id", "actor"))
                try:
                    src_id = self.resolve_special_unit(src_spec, ctx)
                except Exception:
                    src_id = str(src_spec)
                if src_id not in self.state.units:
                    continue
                src_stat = str(ent.get("source_stat", name))
                # Avoid self-recursive definitions such as atk from own atk.
                if src_id == unit.id and src_stat == name:
                    continue
                source_ctx = {**ctx, "actor_id": src_id, "source_owner_id": src_id}
                source_value = self.contextual_stat(self.state.unit(src_id), src_stat, source_ctx)
                total += source_value * coerce_float(ent.get("scale", ent.get("ratio", 1.0)), 1.0) + coerce_float(ent.get("flat", 0.0))
        return total

    def is_danheng_pt_unit(self, unit: UnitState) -> bool:
        uid = str(unit.id).lower()
        name = str(unit.name).lower()
        return uid in {"dan_heng_permansor_terrae", "dan_heng", "dan_heng_pt"} or "dan_heng" in uid or "permansor" in uid or "腾荒" in str(unit.name)

    def danheng_shield_effect(self, *, target: str = "all_allies", source: str = "actor", source_kind: str = "skill") -> dict[str, Any]:
        """Return a data-derived Dan Heng PT shield effect.

        中文语义：丹恒·腾荒战技/终结技提供的全队护盾。旧模型包里
        这里曾经是固定 500；现在改成数据库最大等级参数：
        丹恒当前攻击力 × 0.23 + 512.5，并按 3 倍技能护盾做叠加上限。
        """
        pct_key = "ultimate_shield_owner_atk_pct" if source_kind == "ultimate" else "skill_shield_owner_atk_pct"
        flat_key = "ultimate_shield_flat" if source_kind == "ultimate" else "skill_shield_flat"
        return {
            "type": "modify_shield",
            "target": target,
            "source": source,
            "source_stat": "atk",
            "source_stat_pct": self.souldragon_template_value(pct_key, 0.23),
            "amount": self.souldragon_template_value(flat_key, 512.5),
            "shield_cap_source": f"dan_heng_{source_kind}_shield",
            "shield_cap_source_stat_pct": self.souldragon_template_value("skill_shield_owner_atk_pct", 0.23),
            "shield_cap_flat": self.souldragon_template_value("skill_shield_flat", 512.5),
            "shield_cap_multiplier": self.souldragon_template_value("shield_stack_cap_multiplier", 3.0),
            "duration_turns": self.souldragon_template_value("normal_shield_duration_turns", 3.0),
            "source_template": "souldragon_action_template",
            "semantic": "dan_heng_pt_skill_or_ultimate_shield",
        }

    def _is_legacy_danheng_shield_effect(self, eff: dict[str, Any]) -> bool:
        if not isinstance(eff, dict):
            return False
        if eff.get("semantic") == "dan_heng_pt_skill_or_ultimate_shield":
            return True
        if eff.get("type") in {"modify_shield", "provide_shield"}:
            if coerce_float(eff.get("amount", 0.0)) == 500.0:
                return True
            if any(k in eff for k in ("shield_formula_at_skill_10", "shield_formula_at_ultimate_10")):
                return True
        return False

    def _is_legacy_danheng_attack_convert_effect(self, eff: dict[str, Any]) -> bool:
        """Detect older model-pack static 同袍攻击力加成 effects."""
        if not isinstance(eff, dict):
            return False
        if eff.get("type") != "modify_stat":
            return False
        if str(eff.get("target")) not in {"bondmate", "selected_bondmate"}:
            return False
        if str(eff.get("stat")) != "atk":
            return False
        text = json.dumps(eff, ensure_ascii=False)
        return "dan_heng" in text or "AttackConvert" in text or "bonus_ability" in text

    def ensure_danheng_pt_action_semantics(self, unit: UnitState) -> None:
        """Normalize Dan Heng PT skill/ultimate actions to data-derived max-level semantics.

        中文语义：把丹恒·腾荒本体行动也和龙灵模板统一到数据库最大等级参数。
        这避免同一套模拟里“龙灵用满级参数、丹恒技能仍用旧 500 护盾”的不一致。
        """
        if not self.is_danheng_pt_unit(unit):
            return
        for key, action in list(unit.action_defs.items()):
            if not isinstance(action, dict):
                continue
            action_id = str(action.get("id") or key).lower()
            action_type = str(action.get("action_type") or "").lower()
            tags = {str(t).lower() for t in normalize_str_list(action.get("tags", []))}
            is_skill = key == "skill" or action_id.endswith("skill") or action_type == "skill" or "skill_use" in tags
            is_ultimate = key == "ultimate" or action_type == "ultimate" or "ultimate_use" in tags or "ultimate" in tags
            if not (is_skill or is_ultimate):
                continue
            effects = [
                deepcopy(eff)
                for eff in action.get("effects", []) or []
                if not self._is_legacy_danheng_shield_effect(eff)
                and not self._is_legacy_danheng_attack_convert_effect(eff)
            ]
            if is_skill and not any(isinstance(eff, dict) and eff.get("type") == "set_target" and str(eff.get("status_id")) == "bondmate" for eff in effects):
                effects.insert(0, {"type": "set_target", "status_id": "bondmate", "target": "selected_ally", "semantic": "dan_heng_pt_skill_sets_bondmate"})
            if is_skill and not any(isinstance(eff, dict) and eff.get("type") == "apply_attack_convert" for eff in effects):
                # 中文语义：战技指定【同袍】后，给同袍挂实时攻击力转换，
                # 数值 = 丹恒当前攻击力 × 15%，且之后丹恒攻击变化会实时反映。
                effects.append({"type": "apply_attack_convert", "target": "bondmate", "source": "actor", "semantic": "dan_heng_pt_skill_live_attack_convert"})
            if is_ultimate and not any(isinstance(eff, dict) and eff.get("type") == "enhance_souldragon" for eff in effects):
                effects.append({"type": "enhance_souldragon", "remaining_actions_added": self.souldragon_template_value("enhanced_action_count", 2.0), "semantic": "dan_heng_pt_ultimate_enhances_souldragon"})
            effects.append(self.danheng_shield_effect(source="actor", source_kind="ultimate" if is_ultimate else "skill"))
            action["effects"] = effects
            action.setdefault("semantic_patches", []).append("danheng_pt_data_derived_shield_bondmate_souldragon")

    def souldragon_owner_id_for_context(self, ctx: dict[str, Any] | None = None) -> str:
        if ctx:
            owner = ctx.get("owner_id") or ctx.get("source_owner_id")
            if owner in self.state.units:
                return str(owner)
        return self.default_souldragon_owner_id()

    def souldragon_shield_cap(self, target_id: str, ctx: dict[str, Any], eff: dict[str, Any]) -> float | None:
        if not eff.get("shield_cap_source"):
            return None
        try:
            owner_id = self.resolve_special_unit(eff.get("source", "owner"), ctx)
        except Exception:
            owner_id = self.souldragon_owner_id_for_context(ctx)
        if owner_id not in self.state.units:
            return None
        owner = self.state.unit(owner_id)
        stat = str(eff.get("source_stat", "atk"))
        cap_base = self.contextual_stat(owner, stat, {**ctx, "target_id": target_id}) * coerce_float(eff.get("shield_cap_source_stat_pct", 0.0)) + coerce_float(eff.get("shield_cap_flat", 0.0))
        mult = coerce_float(eff.get("shield_cap_multiplier", 1.0), 1.0)
        return max(0.0, cap_base * mult)

    def is_cleansable_debuff_status(self, status: StatusEffect) -> bool:
        tags = {str(t).lower() for t in getattr(status, "tags", [])}
        mods = status.modifiers if isinstance(status.modifiers, dict) else {}
        sid = str(status.id).lower()
        if tags.intersection({"debuff", "negative", "dot", "control", "cc"}):
            return True
        if any(coerce_bool(mods.get(k, False), default=False) for k in ("debuff", "negative", "dot", "control", "frozen", "action_block")):
            return True
        if any(k in sid for k in ("debuff", "burn", "shock", "bleed", "wind_shear", "freeze", "imprison", "entangle", "slow", "vulnerability")):
            return True
        return False

    def cleanse_debuffs_from_unit(self, unit: UnitState, count: int, source: str = "", ctx: Optional[dict[str, Any]] = None) -> list[str]:
        removed: list[str] = []
        if count <= 0:
            return removed
        for st in list(unit.statuses):
            if len(removed) < count and self.is_cleansable_debuff_status(st):
                removed.append(st.id)
                self.commit_status_remove(
                    unit,
                    st,
                    reason="cleanse_debuffs",
                    ctx=ctx,
                    payload={"source": source, "removed_status": st.to_json()},
                )
                continue
        if removed:
            self.state.log_event("cleanse", f"{unit.id} cleansed {removed}", {"unit": unit.id, "removed": removed, "source": source})
        return removed

    def apply_souldragon_bondmate_attack_semantics(self, action_ctx: dict[str, Any], log_start: int) -> None:
        """Fallback for Dan Heng PT trace B: bondmate attack grants energy and advances dragon.

        Generated statuses may already implement the same trigger.  This fallback
        applies only missing pieces by inspecting logs emitted after the generated
        after_bondmate_uses_attack triggers ran, so it does not double-count old
        hand-authored route tests.
        """
        owner_id = self.default_souldragon_owner_id()
        dragon_id = "souldragon"
        new_events = self.state.log[log_start:]
        owner_energy_logged = any(
            e.event_type == "resource"
            and owner_id in str(e.message)
            and "energy" in str(e.message).lower()
            for e in new_events
        )
        dragon_advance_logged = any(
            e.event_type == "av_change"
            and (dragon_id in str(e.message) or str((e.data or {}).get("unit", "")) == dragon_id)
            for e in new_events
        )
        if owner_id in self.state.units and not owner_energy_logged:
            amount = self.souldragon_template_value("bondmate_attack_energy", 6.0)
            self.apply_energy_source(self.state.unit(owner_id), {"fixed": amount, "affected_by_err": True}, "souldragon_bondmate_attack", default_affected_by_err=True)
        if dragon_id in self.state.units and not dragon_advance_logged:
            percent = self.souldragon_template_value("bondmate_attack_souldragon_advance", 0.15)
            self.apply_action_advance(self.state.unit(dragon_id), percent, ctx=action_ctx, reason="souldragon:bondmate_attack_advance")
            self.state.log_event("souldragon_semantic", "Bondmate attack advances Souldragon", {"bondmate": action_ctx.get("actor_id"), "advance_percent": percent})

    def ensure_souldragon_unit_defaults(self, unit: UnitState, ctx: Optional[dict[str, Any]] = None) -> None:
        """Attach a conservative default action kit to Dan Heng PT's Souldragon.

        Exact generated content may provide its own actions.  When only the
        summoned/attached unit shell exists, this gives the route harness a
        stable lifecycle/action target model instead of an inert placeholder.
        """
        is_dragon = str(unit.id).lower() == "souldragon" or "souldragon" in {str(t).lower() for t in unit.tags} or coerce_bool(unit.flags.get("souldragon", False), default=False)
        if not is_dragon:
            return
        unit.tags.add("souldragon")
        if "souldragon_template_version" not in unit.flags:
            self.commit_unit_flag(unit, "souldragon_template_version", str((self.SOULDRAGON_TEMPLATE or {}).get("version", "v0.1")), reason="souldragon:default_template_version", ctx=ctx)
        if "summon_action_ir" not in unit.flags:
            self.commit_unit_flag(unit, "summon_action_ir", True, reason="souldragon:default_summon_action_ir", ctx=ctx)
        if "summoned" not in unit.flags:
            self.commit_unit_flag(unit, "summoned", True, reason="souldragon:default_summoned", ctx=ctx)
        if "attached_unit" not in unit.flags:
            self.commit_unit_flag(unit, "attached_unit", True, reason="souldragon:default_attached_unit", ctx=ctx)
        if "owner_id" not in unit.flags:
            owner = "dan_heng_permansor_terrae"
            if owner not in self.state.units:
                for candidate in ("dan_heng", "dan_heng_pt"):
                    if candidate in self.state.units:
                        owner = candidate; break
                else:
                    for candidate in self.state.units:
                        if "dan_heng" in str(candidate):
                            owner = str(candidate); break
            self.commit_unit_flag(unit, "owner_id", owner, reason="souldragon:default_owner", ctx=ctx)
        if "attached_to" not in unit.flags:
            bondmate = self.state.global_flags.get("bondmate") or self.state.global_flags.get("bondmate_target")
            if bondmate:
                self.commit_unit_flag(unit, "attached_to", str(bondmate), reason="souldragon:default_attached_to", ctx=ctx)
        if not unit.action_defs:
            unit.action_defs = {}
        template_actions = ((self.SOULDRAGON_TEMPLATE or {}).get("summon_action_ir") or {}).get("actions") or (self.SOULDRAGON_TEMPLATE or {}).get("derived_actions") or {}
        for action_id, action_def in template_actions.items():
            unit.action_defs.setdefault(str(action_id), deepcopy(action_def))
        self.apply_pending_souldragon_enhancement(unit, ctx=ctx)
        # Failsafe for malformed template data: keep the unit actionable even if
        # the generated template file is missing/corrupt.
        if "normal" not in unit.action_defs:
            unit.action_defs["normal"] = {
                "id": "normal",
                "action_type": "summon",
                "tags": ["souldragon_action", "summon_action", "consumes_regular_action", "support", "failsafe_fallback"],
                "target_policy": "all_allies",
                "damage_packets": [],
                "effects": [{"type": "modify_shield", "target": "all_allies", "source": "owner", "source_stat": "atk", "source_stat_pct": 0.10, "amount": 200}],
            }

    def apply_pending_souldragon_enhancement(self, dragon: UnitState, ctx: Optional[dict[str, Any]] = None) -> None:
        """Apply global pending enhanced-action count to a newly created dragon.

        中文语义：如果终结技先记录了龙灵强化，但龙灵单位随后才因
        【同袍】创建，创建时不能丢失强化次数。
        """
        pending = coerce_int(self.state.global_flags.get("souldragon_enhanced_actions", 0), 0)
        if pending <= 0:
            return
        old = coerce_int(dragon.flags.get("remaining_enhanced_actions", 0), 0)
        if old >= pending:
            return
        self.commit_unit_flag(dragon, "remaining_enhanced_actions", pending, reason="souldragon:inherit_pending_enhancement", ctx=ctx)
        self.commit_unit_flag(dragon, "is_enhanced", True, reason="souldragon:inherit_pending_enhancement", ctx=ctx)
        self.commit_unit_flag(dragon, "souldragon_enhanced", True, reason="souldragon:inherit_pending_enhancement", ctx=ctx)
        self.state.log_event("summon_lifecycle", "souldragon inherited pending enhanced actions", {"unit": dragon.id, "old": old, "new": pending})

    def default_souldragon_owner_id(self) -> str:
        for candidate in ("dan_heng_permansor_terrae", "dan_heng", "dan_heng_pt"):
            if candidate in self.state.units:
                return candidate
        for candidate in self.state.units:
            if "dan_heng" in str(candidate):
                return str(candidate)
        return "dan_heng_permansor_terrae"

    def ensure_bondmate_souldragon(self, bondmate_id: str, ctx: dict[str, Any] | None = None) -> None:
        """Ensure Dan Heng PT's Souldragon shell exists and is attached to bondmate.

        This is still a conservative runtime fallback, not a full TBGD-generated
        dragon kit.  It gives exact-route tests a stable attached unit whenever
        the route/StatusTemplate establishes a bondmate target.
        """
        if not bondmate_id or bondmate_id not in self.state.units:
            return
        owner_id = self.default_souldragon_owner_id()
        if "souldragon" in self.state.units:
            dragon = self.state.unit("souldragon")
            old_attached = dragon.flags.get("attached_to")
            self.commit_unit_flag(dragon, "owner_id", owner_id, reason="souldragon:attach_bondmate", ctx=ctx)
            self.commit_unit_flag(dragon, "attached_to", str(bondmate_id), reason="souldragon:attach_bondmate", ctx=ctx)
            self.commit_unit_flag(dragon, "attached_unit", True, reason="souldragon:attach_bondmate", ctx=ctx)
            self.commit_unit_flag(dragon, "summoned", True, reason="souldragon:attach_bondmate", ctx=ctx)
            self.ensure_souldragon_unit_defaults(dragon, ctx=ctx)
            if old_attached != bondmate_id:
                self.state.log_event("summon_lifecycle", f"souldragon attached target {old_attached}->{bondmate_id}", {"unit": "souldragon", "owner_id": owner_id, "attached_to": bondmate_id})
            return
        raw = {
            "name": "Souldragon",
            "side": "ally",
            "hp": 1,
            "max_hp": 1,
            "speed": self.SOULDRAGON_DEFAULTS["initial_speed"],
            "level": self.state.unit(owner_id).level if owner_id in self.state.units else 80,
            "tags": ["summoned", "attached_unit", "souldragon"],
            "flags": {
                "summoned": True,
                "attached_unit": True,
                "souldragon": True,
                "owner_id": owner_id,
                "attached_to": str(bondmate_id),
                "remove_when_owner_defeated": True,
                "remove_when_attached_target_defeated": True,
            },
        }
        dragon = UnitState.from_dict("souldragon", raw)
        self.ensure_souldragon_unit_defaults(dragon, ctx=ctx)
        self.state.units["souldragon"] = dragon
        self.state.log_event("summon_lifecycle", "souldragon summoned for bondmate", {"unit": "souldragon", "owner_id": owner_id, "attached_to": bondmate_id, "speed": dragon.speed})

    def resolve_dynamic_element(self, element: Any, ctx: dict[str, Any]) -> str:
        e = str(element or "none")
        if "." not in e:
            return e.lower()
        unit_spec, field = e.split(".", 1)
        try:
            uid = self.resolve_special_unit(unit_spec, ctx)
        except Exception:
            uid = unit_spec
        if uid in self.state.units:
            u = self.state.unit(uid)
            if field == "element":
                return str(u.flags.get("element") or u.flags.get("damage_type") or "none").lower()
            val = u.flags.get(field)
            if val is not None:
                return str(val).lower()
        return e.lower()

    def eval_formula(self, formula: Any, ctx: dict[str, Any]) -> float:
        """Evaluate simple model-pack numeric formulas safely.

        Supports arithmetic over unit stat refs such as
        `0.20 * dan_heng_permansor_terrae.atk + 400` and a small set of helper
        functions needed by the current model pack. Unsupported names resolve to 0
        instead of executing arbitrary code.
        """
        if formula is None:
            return 0.0
        parsed = maybe_float(formula)
        if parsed is not None:
            return parsed
        import ast, operator
        expr = str(formula).strip()
        ops = {
            ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
            ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg,
            ast.UAdd: lambda x: x,
        }
        def ref_value(node):
            if isinstance(node, ast.Constant):
                if isinstance(node.value, (int, float)):
                    return float(node.value)
                parsed = maybe_float(node.value)
                return parsed if parsed is not None else 0.0
            if isinstance(node, ast.Name):
                name = node.id
                if name in {"sum", "min", "max", "clamp", "floor", "ceil", "stack_count"}:
                    return name
                # Allow formula aliases such as bondmate.atk through Attribute below;
                # bare names are checked against global flags and unit ids.
                if name in self.state.global_flags:
                    return coerce_float(self.state.global_flags.get(name), 0.0)
                if name in self.state.units:
                    return self.state.unit(name)
                return 0.0
            if isinstance(node, ast.Attribute):
                root = ref_value(node.value)
                attr = node.attr
                if isinstance(root, UnitState):
                    attr_alias = {"current_crit_dmg": "crit_dmg", "current_crit_rate": "crit_rate", "final_speed": "speed", "final_speed_in_battle": "speed"}.get(attr, attr)
                    return root.get_stat(attr_alias) or getattr(root, attr_alias, 0.0)
                # If the root is an alias string such as `bondmate`, try resolving it.
                if isinstance(root, str):
                    try:
                        uid = self.resolve_special_unit(root, ctx)
                        attr_alias = {"current_crit_dmg": "crit_dmg", "current_crit_rate": "crit_rate", "final_speed": "speed", "final_speed_in_battle": "speed"}.get(attr, attr)
                        return self.state.unit(uid).get_stat(attr_alias) or getattr(self.state.unit(uid), attr_alias, 0.0)
                    except Exception:
                        return 0.0
                return 0.0
            if isinstance(node, ast.BinOp) and type(node.op) in ops:
                return ops[type(node.op)](ref_value(node.left), ref_value(node.right))
            if isinstance(node, ast.UnaryOp) and type(node.op) in ops:
                return ops[type(node.op)](ref_value(node.operand))
            if isinstance(node, ast.Call):
                fn = ref_value(node.func)
                if fn == "stack_count":
                    if not node.args:
                        return 0.0
                    arg = node.args[0]
                    if isinstance(arg, ast.Name):
                        status_id = arg.id
                    elif isinstance(arg, ast.Constant):
                        status_id = str(arg.value)
                    else:
                        status_id = str(ref_value(arg))
                    unit_ids = []
                    for spec in ("actor", "target", "wearer"):
                        try:
                            uid = self.resolve_special_unit(spec, ctx)
                            if uid not in unit_ids:
                                unit_ids.append(uid)
                        except Exception:
                            pass
                    total = 0
                    for uid in unit_ids:
                        if uid in self.state.units:
                            total += sum(st.stacks for st in self.state.unit(uid).statuses if st.id == status_id)
                    return float(total)
                args = [ref_value(a) for a in node.args]
                if fn == "sum": return sum(args)
                if fn == "min": return min(args) if args else 0.0
                if fn == "max": return max(args) if args else 0.0
                if fn == "clamp":
                    return clamp(args[0], args[1], args[2]) if len(args) >= 3 else (args[0] if args else 0.0)
                if fn == "floor": return math.floor(args[0]) if args else 0.0
                if fn == "ceil": return math.ceil(args[0]) if args else 0.0
                if fn == "stack_count":
                    # ast.Name arguments are already resolved to 0.0 by ref_value;
                    # the string fallback below handles stack_count(foo) by reading
                    # the original call node directly.
                    return args[0] if args else 0.0
                return 0.0
            if isinstance(node, ast.List):
                return sum(ref_value(e) for e in node.elts)
            return 0.0
        try:
            return float(ref_value(ast.parse(expr, mode="eval").body))
        except Exception:
            self.state.log_event("formula_skip", f"Formula could not be evaluated: {expr}")
            return 0.0

    def resolve_numeric_expr(self, value: Any, ctx: dict[str, Any], default: float = 0.0) -> float:
        """Resolve numeric effect fields that may be literals, ctx refs, or formulas."""
        parsed = maybe_float(value)
        if parsed is not None:
            return parsed
        if isinstance(value, str):
            text = value.strip()
            if text in ctx:
                return coerce_float(ctx.get(text), default)
            if text.startswith(("ctx:", "flag:", "unit:")):
                return coerce_float(self.resolve_ref(text, ctx), default)
            if "." in text or any(op in text for op in ("+", "-", "*", "/", "(", ")")):
                return self.eval_formula(text, ctx)
        return default

    def lookup_status_template(self, status_id: str, ctx: dict[str, Any]) -> dict[str, Any]:
        """Find a status/buff definition by id in actor/global/unit templates."""
        candidates = []
        actor_id = ctx.get("actor_id")
        if actor_id in self.state.units:
            candidates.append(self.state.unit(actor_id))
        for uid in (ctx.get("owner_id"), ctx.get("target_id")):
            if uid in self.state.units:
                candidates.append(self.state.unit(uid))
        candidates.extend(self.state.units.values())
        seen = set()
        for unit in candidates:
            if unit.id in seen:
                continue
            seen.add(unit.id)
            if status_id in unit.status_defs:
                raw = deepcopy(unit.status_defs[status_id])
                raw.setdefault("id", status_id)
                return raw
        raw_global = self.raw_case.get("status_effects", {}).get(status_id) if isinstance(self.raw_case.get("status_effects"), dict) else None
        if raw_global:
            raw = deepcopy(raw_global); raw.setdefault("id", status_id); return raw
        return {"id": status_id}

    def materialize_status(self, status: Any, ctx: dict[str, Any], overrides: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        overrides = overrides or {}
        if isinstance(status, str):
            raw = self.lookup_status_template(status, ctx)
        elif isinstance(status, dict):
            sid = status.get("id") or status.get("status_id") or status.get("buff_id")
            if sid and not any(k in status for k in ("modifiers", "duration", "tags", "stacks", "max_stacks", "dynamic_values", "symbolic_dynamic_values")):
                raw = self.lookup_status_template(str(sid), ctx)
            else:
                raw = deepcopy(status)
                if sid:
                    raw.setdefault("id", str(sid))
        else:
            raw = {"id": str(status)}
        for key in ("stacks", "max_stacks", "duration", "duration_value", "duration_type", "refresh_duration", "source", "source_id"):
            if key in overrides:
                raw[key] = deepcopy(overrides[key])
        if "duration_turns" in overrides and "duration" not in raw:
            raw["duration"] = {"type": "owner_turns", "value": overrides["duration_turns"]}
        if isinstance(raw.get("modifiers"), dict):
            mods = deepcopy(raw["modifiers"])
            # Normalize current model-pack modifier aliases into simulator-native
            # additive/pct fields.  This keeps direct template replay from losing
            # core buffs such as Seele amplification, Sparkle skill crit damage,
            # Tribbie zone vulnerability, and Journey shield damage bonus.
            alias_adds = {
                "speed_pct_delta": "speed_pct",
                "crit_rate": "crit_rate_add",
                "crit_dmg": "crit_dmg_add",
                "dmg_bonus_multiplier_delta": "dmg_bonus_add",
                "dmg_bonus_multiplier_delta_per_stack": "dmg_bonus_add",
                "dmg_taken_multiplier_delta_per_stack_at_talent_10": "damage_taken_add",
                "enemy_dmg_taken_delta_at_ult_10": "damage_taken_add",
                "all_type_res_pen_at_skill_10": "all_res_pen",
            }
            if not mods.get("_sim_aliases_normalized"):
                for src, dst in alias_adds.items():
                    if src in mods:
                        mods[dst] = coerce_float(mods.get(dst, 0.0)) + coerce_float(mods[src], 0.0)
                for src, dst in (("dmg_bonus_multiplier_delta_by_talent_level", "dmg_bonus_add"),):
                    table = mods.get(src)
                    if isinstance(table, dict) and table:
                        vals = [coerce_float(v) for k, v in table.items() if maybe_float(v) is not None]
                        if vals:
                            mods[dst] = coerce_float(mods.get(dst, 0.0)) + max(vals)
                if "crit_dmg_formula_at_skill_10" in mods:
                    mods["crit_dmg_add"] = coerce_float(mods.get("crit_dmg_add", 0.0)) + self.eval_formula(mods["crit_dmg_formula_at_skill_10"], ctx)
                if "talent_stack_bonus_extra_vulnerability_per_stack_at_ult_10" in mods:
                    # Sparkle Cipher increases the existing Figment/talent vulnerability per stack.
                    # Represent it as damage-taken bonus per stack for validator purposes.
                    mods["damage_taken_add"] = coerce_float(mods.get("damage_taken_add", 0.0)) + coerce_float(mods["talent_stack_bonus_extra_vulnerability_per_stack_at_ult_10"], 0.0)
                mods["_sim_aliases_normalized"] = True
            raw["modifiers"] = mods
        return raw

    def resolve_initial_setup(self) -> None:
        """Apply optional battle-start setup effects before route validation.

        This is for real-video replay cases where techniques/prebattle effects
        should be represented in the case file instead of being baked into the
        initial stats by hand. The supported sections are intentionally aliases
        because the model pack has used several names while evolving.
        """
        setup_effects = []
        for key in ("initial_effects", "battle_start_effects", "setup_effects"):
            setup_effects.extend(self.raw_case.get(key, []) or [])
        if not setup_effects and not any(t.get("timing") in {"battle_start", "ability_property_change", "status_dynamic_value_change"} for t in self.state.triggers):
            return
        ctx = {"events": self.raw_case.get("initial_events", {}), "context": {"phase": "battle_start"}, "phase_locked_targets": set()}
        self.state.log_event("battle_start", "Resolve battle-start setup")
        self.run_triggers("battle_start", ctx)
        # Watcher-style generated StatusTemplates need an initial snapshot.
        self.run_triggers("ability_property_change", {**ctx, "context": {**ctx.get("context", {}), "phase": "ability_property_change", "initial_snapshot": True}})
        self.run_triggers("status_dynamic_value_change", {**ctx, "context": {**ctx.get("context", {}), "phase": "status_dynamic_value_change", "initial_snapshot": True}})
        for eff in setup_effects:
            self.apply_effect(eff, ctx)
        if coerce_bool(self.raw_case.get("resolve_initial_queues", True), default=True):
            self.drain_queues(default_events=self.raw_case.get("initial_events", {}))
        self.check_wave_transition()

    # ---------- wave manager ----------
    def spawn_wave(self, wave_index: int) -> None:
        if wave_index >= len(self.state.waves):
            self.state.log_event("battle_end", "No more waves to spawn")
            return
        wave = self.state.waves[wave_index]
        spawned = []
        for uid, raw in wave.get("units", {}).items():
            unit = UnitState.from_dict(uid, raw)
            # If not explicitly set, honor initial_delay_ratio / initial_delay /
            # delay_ratio aliases; default remains one full action interval.
            unit.remaining_av = self.unit_initial_av(unit, raw)
            self.state.units[uid] = unit
            spawned.append(uid)
        self.state.wave_index = wave_index
        self.state.log_event("wave_start", f"Spawn wave {wave_index + 1}", {"spawned": spawned})
        self.run_triggers("wave_start", {"wave_index": wave_index, "wave_number": wave_index + 1, "spawned": spawned, "context": {"phase": "wave_start"}, "phase_locked_targets": set()})

    def check_wave_transition(self) -> None:
        if self.state.enemies_alive():
            return
        if not self.state.waves:
            self.state.log_event("battle_end", "All enemies defeated")
            return
        next_idx = self.state.wave_index + 1
        if next_idx < len(self.state.waves):
            self.spawn_wave(next_idx)
        else:
            self.state.log_event("battle_end", "All waves cleared")

    # ---------- timeline ----------
    def effective_speed(self, unit: UnitState) -> float:
        speed = unit.get_stat("speed")
        if speed <= EPS:
            speed = unit.speed
        return max(speed, EPS)

    def action_interval(self, unit: UnitState) -> float:
        return 10000.0 / self.effective_speed(unit)

    def advance_until_regular_actor(self, actor_id: str, ctx: Optional[dict[str, Any]] = None) -> None:
        """Advance regular timeline until actor_id is the next actor.

        This is for route validation. If another unit acts before the requested actor,
        a route error is raised unless route step explicitly resolves that unit first.
        """
        if self.state.ultimate_queue or self.state.immediate_queue or self.state.interrupt_queue:
            raise SimulatorError("Queued ultimate/immediate/interrupt actions must be resolved before advancing regular timeline")
        alive = self.state.active_units()
        if not alive:
            return
        next_unit = min(alive, key=lambda u: u.remaining_av)
        if next_unit.id != actor_id:
            raise SimulatorError(
                f"Route asks for {actor_id}, but next regular actor is {next_unit.id} "
                f"in {next_unit.remaining_av:.6f} AV. Resolve that action or use an interrupt action."
            )
        delta = next_unit.remaining_av
        payload = {"delta": delta, "next_actor_id": actor_id}
        self.commit_global_av(self.state.av + delta, reason="timeline:advance_until_regular_actor", ctx=ctx, payload=payload)
        self.state.update_cycle_index(coerce_float(self.settings.get("first_cycle_av", 150.0)), coerce_float(self.settings.get("later_cycle_av", 100.0)))
        for u in alive:
            self.commit_unit_remaining_av(u, u.remaining_av - delta, reason="timeline:advance_until_regular_actor", ctx=ctx, payload=payload)
        self.state.log_event("timeline", f"Regular timeline advanced by {delta:.6f} AV; next actor {actor_id}", {"delta": delta})

    def advance_to_next_regular_actor(self, ctx: Optional[dict[str, Any]] = None) -> str:
        alive = self.state.active_units()
        if not alive:
            raise SimulatorError("No active units on regular timeline")
        next_unit = min(alive, key=lambda u: u.remaining_av)
        delta = next_unit.remaining_av
        payload = {"delta": delta, "next_actor_id": next_unit.id}
        self.commit_global_av(self.state.av + delta, reason="timeline:advance_to_next_regular_actor", ctx=ctx, payload=payload)
        self.state.update_cycle_index(coerce_float(self.settings.get("first_cycle_av", 150.0)), coerce_float(self.settings.get("later_cycle_av", 100.0)))
        for u in alive:
            self.commit_unit_remaining_av(u, u.remaining_av - delta, reason="timeline:advance_to_next_regular_actor", ctx=ctx, payload=payload)
        self.state.log_event("timeline", f"Regular timeline advanced by {delta:.6f} AV; next actor {next_unit.id}", {"delta": delta})
        return next_unit.id

    def finish_regular_action(self, actor: UnitState, action: dict[str, Any], ctx: Optional[dict[str, Any]] = None) -> None:
        if "consumes_regular_action" in set(normalize_str_list(action.get("tags", []))):
            self.commit_unit_remaining_av(
                actor,
                actor.remaining_av + self.action_interval(actor),
                reason="timeline:regular_action_interval",
                ctx=ctx,
                payload={"action_id": action.get("id"), "action_interval": self.action_interval(actor)},
            )
            self.state.log_event("timeline", f"{actor.id} regular action interval added", {"remaining_av": actor.remaining_av})

    def remove_unit_from_timeline(self, unit_id: str, reason: str) -> None:
        if unit_id not in self.state.units:
            return
        unit = self.state.units.pop(unit_id)
        self.state.log_event("unit_removed", f"Remove unit {unit_id}: {reason}", {"unit": unit.to_json(), "reason": reason})

    def tick_summon_lifecycle(self, actor: UnitState, action: dict[str, Any], ctx: Optional[dict[str, Any]] = None) -> None:
        # Attached/summoned units can declare a simple action lifespan.  This is a
        # generic lifecycle skeleton; character-specific summon behavior still
        # lives in generated statuses/actions.
        if actor.flags.get("summoned") or actor.flags.get("attached_unit"):
            if "remaining_enhanced_actions" in actor.flags:
                old_enh = coerce_int(actor.flags.get("remaining_enhanced_actions"), 0)
                if old_enh > 0:
                    self.commit_unit_flag(actor, "remaining_enhanced_actions", old_enh - 1, reason="summon_lifecycle:remaining_enhanced_actions", ctx=ctx, payload={"action": action.get("id")})
                    self.state.log_event("summon_lifecycle", f"{actor.id} remaining_enhanced_actions {old_enh}->{old_enh-1}", {"unit": actor.id})
                    if old_enh - 1 <= 0:
                        self.commit_unit_flag(actor, "is_enhanced", False, reason="summon_lifecycle:enhanced_expired", ctx=ctx, payload={"action": action.get("id")})
                        self.commit_unit_flag(actor, "souldragon_enhanced", False, reason="summon_lifecycle:enhanced_expired", ctx=ctx, payload={"action": action.get("id")})
                        self.state.log_event("summon_lifecycle", f"{actor.id} enhanced state expired", {"unit": actor.id})
            if "lifespan_actions" in actor.flags:
                old = coerce_int(actor.flags.get("lifespan_actions"), 0)
                self.commit_unit_flag(actor, "lifespan_actions", old - 1, reason="summon_lifecycle:lifespan_actions", ctx=ctx, payload={"action": action.get("id")})
                self.state.log_event("summon_lifecycle", f"{actor.id} lifespan_actions {old}->{old-1}", {"unit": actor.id})
                if old - 1 <= 0:
                    self.remove_unit_from_timeline(actor.id, "lifespan_actions_expired")
                    return
        to_remove = []
        for unit_id, unit in self.state.units.items():
            owner = unit.flags.get("owner_id")
            attached_to = unit.flags.get("attached_to")
            if owner and coerce_bool(unit.flags.get("remove_when_owner_defeated", True), default=True):
                if owner not in self.state.units or not self.state.unit(str(owner)).alive:
                    to_remove.append((unit_id, f"owner_defeated:{owner}"))
                    continue
            if attached_to and coerce_bool(unit.flags.get("remove_when_attached_target_defeated", True), default=True):
                if attached_to not in self.state.units or not self.state.unit(str(attached_to)).alive:
                    to_remove.append((unit_id, f"attached_target_defeated:{attached_to}"))
        for unit_id, reason in to_remove:
            self.remove_unit_from_timeline(unit_id, reason)

    def apply_action_advance(self, unit: UnitState, percent: float, ctx: Optional[dict[str, Any]] = None, reason: str = "av:advance_action") -> None:
        old = unit.remaining_av
        pct = coerce_float(percent, 0.0)
        if pct >= 1.0 - EPS:
            new_remaining = 0.0
        else:
            # HSR action advance reduces remaining AV by a percentage of the
            # unit's full action interval (10000 / current SPD), not by a
            # percentage of the currently remaining AV.
            new_remaining = max(0.0, unit.remaining_av - self.action_interval(unit) * pct)
        self.commit_unit_remaining_av(
            unit,
            new_remaining,
            reason=reason,
            ctx=ctx,
            payload={"percent": pct, "action_interval": self.action_interval(unit), "old_remaining_av": old},
        )
        self.state.log_event("av_change", f"{unit.id} action advanced by {pct:.1%}", {"old": old, "new": unit.remaining_av, "action_interval": self.action_interval(unit)})

    def apply_action_delay(self, unit: UnitState, percent: float, ctx: Optional[dict[str, Any]] = None, reason: str = "av:delay_action") -> None:
        old = unit.remaining_av
        pct = coerce_float(percent, 0.0)
        self.commit_unit_remaining_av(
            unit,
            unit.remaining_av + self.action_interval(unit) * pct,
            reason=reason,
            ctx=ctx,
            payload={"percent": pct, "action_interval": self.action_interval(unit), "old_remaining_av": old},
        )
        self.state.log_event("av_change", f"{unit.id} action delayed by {percent:.1%}", {"old": old, "new": unit.remaining_av})

    def zone_active(self) -> bool:
        return any(bool(v) for k, v in self.state.global_flags.items() if "zone" in str(k).lower() and str(k) != "zone_active") or coerce_bool(self.state.global_flags.get("zone_active", False))

    def expire_statuses_if_zone_inactive(self, reason: str = "zone_inactive", ctx: Optional[dict[str, Any]] = None) -> None:
        if self.zone_active():
            return
        for unit in list(self.state.units.values()):
            old_speed = self.effective_speed(unit)
            expired: list[StatusEffect] = []
            for st in list(unit.statuses):
                if str(st.duration_type or "") == "while_zone_active":
                    expired.append(st)
            if expired:
                for st in expired:
                    self.commit_status_remove(
                        unit,
                        st,
                        reason=reason,
                        ctx=ctx,
                        payload={"duration_type": st.duration_type, "removed_status": st.to_json()},
                    )
                    self.expire_status_effect(unit, st, reason=reason, ctx=ctx)
                self.recalculate_remaining_av_for_speed_change(unit, old_speed, reason=reason, ctx=ctx)

    # ---------- turn lifecycle / durations ----------
    def reset_owner_turn_usage(self, owner_id: str) -> None:
        """Reset all usage-limit counters scoped to this unit's owner_turn.

        Example key shape from trigger_usage_key():
          trigger_id:owner_turn:seele
        """
        suffix = f":owner_turn:{owner_id}"
        removed = [k for k in self.state.trigger_usage if k.endswith(suffix)]
        for k in removed:
            del self.state.trigger_usage[k]
        if removed:
            self.state.log_event("trigger_reset", f"Reset owner_turn trigger usage for {owner_id}", {"removed": removed})

    def begin_turn(self, actor: UnitState, turn_kind: str, action: Optional[dict[str, Any]] = None, context: Optional[dict[str, Any]] = None) -> None:
        ctx = {"actor_id": actor.id, "actor": actor, "action": action or {}, "turn_kind": turn_kind, "context": context or {}}
        # Phase 3: 从 context 中提取 settlement collector（若有）
        if isinstance(context, dict) and "_settlement" in context:
            ctx["_settlement"] = context["_settlement"]
        # Turn-scoped status creation token. A status created after the turn-start
        # boundary should not immediately lose one turn at that same turn-end; it
        # has not experienced a full start->end lifecycle yet.
        token = coerce_int(self.state.global_flags.get("_turn_token", 0), 0) + 1
        self.commit_global_flag("_turn_token", token, reason="turn_start:turn_token", ctx=ctx)
        self.commit_global_flag("_active_turn_token", token, reason="turn_start:active_turn_token", ctx=ctx)
        self.commit_global_flag("_active_turn_actor_id", actor.id, reason="turn_start:active_turn_actor_id", ctx=ctx)
        self.commit_global_flag("_active_turn_kind", turn_kind, reason="turn_start:active_turn_kind", ctx=ctx)
        self.state.log_event("turn_start", f"{actor.id} begins {turn_kind} turn")
        # Phase 2: 回合开始记录
        self._settle(context or {}, "turn", unit_id=actor.id, turn_kind=turn_kind, event="begin")
        self.apply_break_aftermath_turn_start(actor, turn_kind)
        # Phase 3: DoT 周期结算——在回合开始时触发
        self.resolve_dot_tick(actor, ctx)
        # Some character texts decrement specific buffs at the owner's turn start
        # rather than at turn end. Tick those before start triggers/actions so a
        # buff that expires at this boundary is no longer active during the turn.
        self.tick_status_durations(event="turn_start", actor=actor, turn_kind=turn_kind, action=action or {}, ctx=ctx)
        if turn_kind == "regular":
            self.reset_owner_turn_usage(actor.id)
            self.run_triggers("owner_turn_start", ctx)
            self.run_triggers("regular_turn_start", ctx)
        elif turn_kind == "extra_turn":
            self.run_triggers("extra_turn_start", ctx)
        elif turn_kind == "ultimate":
            self.run_triggers("ultimate_turn_start", ctx)
        else:
            self.run_triggers(f"{turn_kind}_turn_start", ctx)

    def end_turn(self, actor: UnitState, turn_kind: str, action: Optional[dict[str, Any]] = None, context: Optional[dict[str, Any]] = None) -> None:
        ctx = {"actor_id": actor.id, "actor": actor, "action": action or {}, "turn_kind": turn_kind}
        if isinstance(context, dict) and "_settlement" in context:
            ctx["_settlement"] = context["_settlement"]
        if turn_kind == "regular":
            self.run_triggers("regular_turn_end", ctx)
            self.run_triggers("owner_turn_end", ctx)
        elif turn_kind == "extra_turn":
            self.run_triggers("extra_turn_end", ctx)
        elif turn_kind == "ultimate":
            self.run_triggers("ultimate_turn_end", ctx)
        else:
            self.run_triggers(f"{turn_kind}_turn_end", ctx)
        self.tick_status_durations(event="turn_end", actor=actor, turn_kind=turn_kind, action=action or {}, ctx=ctx)
        self.consume_skill_point_overflow_reserve_at_turn_end(actor, turn_kind, context=context)
        self.state.log_event("turn_end", f"{actor.id} ends {turn_kind} turn")
        # Phase 2: 回合结束记录
        self._settle(context or {}, "turn", unit_id=actor.id, turn_kind=turn_kind, event="end")

    def expire_status_effect(self, unit: UnitState, status: StatusEffect, reason: str, ctx: Optional[dict[str, Any]] = None) -> None:
        """Expire/remove a status through the same lifecycle used by explicit removal.

        Earlier versions removed naturally expired statuses from the list only.
        That was not enough for resource side effects such as HPAddedRatio / MaxSP:
        the status disappeared but the resource delta stayed behind.  Keep expiry
        generic so character mechanics and future enemy states share one path.
        """
        ctx = ctx or {}
        self.remove_status_resource_side_effects(unit, status, ctx=ctx)
        self.state.log_event(
            "status_expire",
            f"{unit.id}.{status.id} expired",
            {"unit": unit.id, "status": status.id, "reason": reason, "duration_type": status.duration_type},
        )
        lifecycle_ctx = {
            **ctx,
            "target_id": unit.id,
            "target": unit,
            "status_id": status.id,
            "status": status,
            "removed_status": status,
            "trigger": {"status_id": status.id},
            "status_owner_id": unit.id,
        }
        self.run_triggers("status_destroy", lifecycle_ctx)
        self.run_triggers("ability_property_change", {**lifecycle_ctx, "context": {**lifecycle_ctx.get("context", {}), "phase": "ability_property_change", "reason": reason}})
        self.run_triggers("status_dynamic_value_change", {**lifecycle_ctx, "context": {**lifecycle_ctx.get("context", {}), "phase": "status_dynamic_value_change", "reason": reason}})

    def tick_status_durations(self, event: str, actor: UnitState, turn_kind: Optional[str] = None, action: Optional[dict[str, Any]] = None, ctx: Optional[dict[str, Any]] = None) -> None:
        """Tick generic status durations and recalculate AV when speed modifiers expire."""
        duration_ctx = {**(ctx or {}), "actor_id": actor.id, "actor": actor, "action": action or {}, "turn_kind": turn_kind}
        for unit in self.state.units.values():
            old_speed = self.effective_speed(unit)
            expired: list[StatusEffect] = []
            changed = False
            for st in list(unit.statuses):
                if self.should_tick_status(st, unit, actor, event, turn_kind, action or {}):
                    if st.duration_value is not None:
                        old = int(st.duration_value)
                        self.commit_status_duration_value(
                            unit,
                            st,
                            old - 1,
                            reason="status_duration_tick",
                            ctx=duration_ctx,
                            payload={"duration_type": st.duration_type, "event": event, "turn_kind": turn_kind},
                        )
                        changed = True
                        self.state.log_event(
                            "duration_tick",
                            f"{unit.id}.{st.id} duration {old} -> {st.duration_value}",
                            {"unit": unit.id, "status": st.id, "duration_type": st.duration_type, "event": event, "turn_kind": turn_kind},
                        )
                        if st.duration_value <= 0:
                            expired.append(st)
                            continue
            for expired_status in expired:
                self.commit_status_remove(
                    unit,
                    expired_status,
                    reason="status_duration_expire",
                    ctx=duration_ctx,
                    payload={"duration_type": expired_status.duration_type, "event": event, "turn_kind": turn_kind},
                )
                self.expire_status_effect(unit, expired_status, reason="status_duration_tick", ctx=duration_ctx)
            if changed:
                self.recalculate_remaining_av_for_speed_change(unit, old_speed, reason="status_duration_tick", ctx=duration_ctx)

    def recalculate_remaining_av_for_speed_change(self, unit: UnitState, old_speed: float, reason: str = "speed_change", ctx: Optional[dict[str, Any]] = None) -> None:
        """Recalculate remaining AV after speed-affecting status changes.

        HSR action value already accumulated should be preserved; remaining AV scales
        by old_speed/new_speed when current speed changes.
        """
        new_speed = self.effective_speed(unit)
        if unit.alive and abs(new_speed - old_speed) > EPS:
            old_av = unit.remaining_av
            self.commit_unit_remaining_av(
                unit,
                unit.remaining_av * old_speed / new_speed,
                reason=f"speed_change:{reason}",
                ctx=ctx,
                payload={"old_speed": old_speed, "new_speed": new_speed, "old_remaining_av": old_av},
            )
            self.state.log_event(
                "speed_change",
                f"{unit.id} speed {old_speed:.3f} -> {new_speed:.3f}",
                {"old_remaining_av": old_av, "new_remaining_av": unit.remaining_av, "reason": reason},
            )

    def should_tick_status(self, st: StatusEffect, holder: UnitState, actor: UnitState, event: str, turn_kind: Optional[str], action: dict[str, Any]) -> bool:
        dt = st.duration_type
        if not dt or dt == "permanent" or st.duration_value is None:
            return False
        dt = str(dt)
        is_regular = turn_kind == "regular"
        is_extra_like = turn_kind not in (None, "regular")
        regular_allowed = is_regular or (is_extra_like and st.duration_extra_turn_consumes)
        if event == "turn_start":
            if dt in {"owner_turn_start_decrement", "source_turn_start_decrement"}:
                owner_id = st.source_id or holder.id
                return owner_id == actor.id and regular_allowed
        if event == "turn_end":
            created_token = st.modifiers.get("_created_turn_token") if isinstance(st.modifiers, dict) else None
            if created_token is not None and str(created_token) == str(self.state.global_flags.get("_active_turn_token")):
                # Created inside this same turn window; do not tick until it has
                # passed through a later complete turn boundary.
                return False
            if dt in {"target_turns", "target_regular_turns", "holder_turns", "holder_regular_turns"}:
                return holder.id == actor.id and regular_allowed
            if dt in {"target_all_turns", "holder_all_turns"}:
                return holder.id == actor.id
            if dt in {"source_turns", "source_regular_turns", "owner_turns", "actor_turns"}:
                return st.source_id == actor.id and regular_allowed
            if dt in {"source_all_turns", "owner_all_turns"}:
                return st.source_id == actor.id
            if dt == "ally_turns":
                return holder.side == actor.side and regular_allowed
            if dt == "enemy_turns":
                return holder.side != actor.side and regular_allowed
            if dt == "global_turns":
                return regular_allowed
        if event == "action_end":
            if dt in {"actions", "global_actions"}:
                return True
            if dt == "holder_actions":
                return holder.id == actor.id
            if dt == "source_actions":
                return st.source_id == actor.id
        return False

    def tick_hit_durations(self, actor: UnitState, target: UnitState, action: dict[str, Any], ctx: Optional[dict[str, Any]] = None) -> None:
        """Tick per-hit statuses after one damage packet is fully resolved.

        v0.9 separates per-hit duration types from per-attack duration types. A
        multi-hit action may resolve several DamagePackets but is still one attack
        for statuses such as attacks_taken / attacks_dealt.
        """
        action_tags = set(normalize_str_list(action.get("tags", [])))
        if "attack" not in action_tags:
            return
        self._tick_specific_unit_hit_statuses(actor, {"hits_dealt"}, actor=actor, action=action, ctx=ctx)
        self._tick_specific_unit_hit_statuses(target, {"hits_taken", "hits"}, actor=actor, action=action, ctx=ctx)

    def tick_attack_durations(self, actor: UnitState, target_ids: list[str], action: dict[str, Any], ctx: Optional[dict[str, Any]] = None) -> None:
        """Tick once-per-attack duration types after all packets of an action."""
        action_tags = set(normalize_str_list(action.get("tags", [])))
        if "attack" not in action_tags:
            return
        self._tick_specific_unit_hit_statuses(actor, {"attacks_dealt"}, actor=actor, action=action, ctx=ctx)
        for target_id in target_ids:
            if target_id in self.state.units:
                self._tick_specific_unit_hit_statuses(self.state.unit(target_id), {"attacks_taken"}, actor=actor, action=action, ctx=ctx)

    def _tick_specific_unit_hit_statuses(self, unit: UnitState, duration_types: set[str], actor: Optional[UnitState] = None, action: Optional[dict[str, Any]] = None, ctx: Optional[dict[str, Any]] = None) -> None:
        duration_ctx = dict(ctx or {})
        if actor is not None:
            duration_ctx.setdefault("actor_id", actor.id)
            duration_ctx.setdefault("actor", actor)
        if action is not None:
            duration_ctx.setdefault("action", action)
        old_speed = self.effective_speed(unit)
        changed = False
        expired: list[StatusEffect] = []
        for st in list(unit.statuses):
            if st.duration_type in duration_types and st.duration_value is not None:
                old = int(st.duration_value)
                self.commit_status_duration_value(
                    unit,
                    st,
                    old - 1,
                    reason="hit_duration_tick",
                    ctx=duration_ctx,
                    payload={"duration_type": st.duration_type, "event": "hit", "duration_types": sorted(duration_types)},
                )
                changed = True
                self.state.log_event(
                    "duration_tick",
                    f"{unit.id}.{st.id} duration {old} -> {st.duration_value}",
                    {"unit": unit.id, "status": st.id, "duration_type": st.duration_type, "event": "hit"},
                )
                if st.duration_value <= 0:
                    expired.append(st)
                    continue
        for st in expired:
            self.commit_status_remove(
                unit,
                st,
                reason="hit_duration_expire",
                ctx=duration_ctx,
                payload={"duration_type": st.duration_type, "event": "hit", "duration_types": sorted(duration_types)},
            )
            self.expire_status_effect(unit, st, reason="hit_duration_tick", ctx=duration_ctx)
        if changed:
            self.recalculate_remaining_av_for_speed_change(unit, old_speed, reason="hit_duration_tick", ctx=duration_ctx)

    # ---------- actions ----------
    def get_action_def(self, actor_id: str, action_id: str) -> dict[str, Any]:
        actor = self.state.unit(actor_id)
        action_key = action_id
        if action_key not in actor.action_defs:
            for key, candidate in actor.action_defs.items():
                if isinstance(candidate, dict) and candidate.get("id") == action_id:
                    action_key = key
                    break
            else:
                raise SimulatorError(f"Unit {actor_id} has no action {action_id}")
        action = deepcopy(actor.action_defs[action_key])
        action.setdefault("id", action_id)
        action.setdefault("actor_id", actor_id)
        action["tags"] = normalize_str_list(action.get("tags", []))
        action.setdefault("cost", {})
        action.setdefault("energy_gain", {})
        if "damage_packets" not in action and "damage_packet" in action:
            action["damage_packets"] = [action["damage_packet"]]
        action.setdefault("damage_packets", [])
        action.setdefault("effects", [])
        return action

    def find_action_by_skill_type(self, actor_id: str, skill_type: str) -> str | None:
        if not actor_id or actor_id not in self.state.units:
            return None
        wanted = str(skill_type or "").strip().lower()
        if not wanted:
            return None
        aliases = {
            "controlskill01": {"skill", "skill_use", "controlskill01"},
            "controlskill02": {"skill", "skill_use", "controlskill02"},
            "basic": {"basic", "basic_use"},
            "ultra": {"ultimate", "ultimate_use"},
            "ultimate": {"ultimate", "ultimate_use"},
        }.get(wanted, {wanted})
        actor = self.state.unit(actor_id)
        for key, candidate in actor.action_defs.items():
            if not isinstance(candidate, dict):
                continue
            action_type = str(candidate.get("action_type") or "").strip().lower()
            tags = {str(t).strip().lower() for t in normalize_str_list(candidate.get("tags", []))}
            if action_type in aliases or tags.intersection(aliases):
                return str(candidate.get("id") or key)
        return None

    def resolve_route_step(self, step: dict[str, Any]) -> None:
        # Drain queued actions before route step unless explicitly suppressed.
        if coerce_bool(step.get("auto_resolve_queues_before", True), default=True):
            self.drain_queues(default_events=step.get("events", {}))

        if step.get("type") == "advance_to_next_regular":
            collector = self.begin_route_control_settlement(step)
            actor_id = self.advance_to_next_regular_actor(ctx={"_settlement": collector})
            collector.transition.request.metadata["next_actor_id"] = actor_id
            # Enter and end an empty regular turn only if explicitly requested.
            if coerce_bool(step.get("resolve_empty_turn", False), default=False):
                actor = self.state.unit(actor_id)
                turn_ctx = {"_settlement": collector}
                self.begin_turn(actor, "regular", None, context=turn_ctx)
                self.end_turn(actor, "regular", None, context=turn_ctx)
            collector.capture_after_snapshot(self.full_scene_snapshot())
            return

        if step.get("type") in ("apply_effects", "battle_start_effects", "setup_effects"):
            settlement = self.begin_route_control_settlement(step)
            ctx = {
                "events": step.get("events", {}),
                "context": {"route_step": step},
                "phase_locked_targets": set(),
                "_settlement": settlement,
            }
            self.state.log_event("route_effects", f"Apply route effects: {step.get('type')}")
            for eff in step.get("effects", []) or []:
                self.apply_effect(eff, ctx)
            settlement.capture_after_snapshot(self.full_scene_snapshot())
            return

        actor_id = step["actor"]
        action_id = step["action"]
        mode = step.get("timing", "manual")
        turn_kind = step.get("turn_kind")
        action = self.get_action_def(actor_id, action_id)
        targets = self.normalize_targets(step["targets"]) if "targets" in step else self.select_targets(action, None)
        step_context = {"route_step": step, "turn_kind": turn_kind}
        if step.get("extra_turn_type") is not None:
            step_context["extra_turn_type"] = step.get("extra_turn_type")
        # Phase 2: 为每一步创建结算收集器（可选注册表自动补中文名）
        settlement = SettlementCollector(
            text_map=self._text_map,
            status_registry=self._status_registry,
            skill_registry=self._skill_registry,
        )
        action_request = ActionRequest.from_route_step(step, targets or [])
        action_request.timing = mode
        settlement.begin_action(action_request)
        settlement.capture_before_snapshot(self.full_scene_snapshot())
        settlement.record_target(targets or [], method="explicit" if "targets" in step else "auto")
        step_context["_settlement"] = settlement
        # 让 run_route 能取出结算数据
        step["_settlement"] = settlement

        if mode == "regular_turn":
            self.advance_until_regular_actor(actor_id, ctx=step_context)
            turn_kind = turn_kind or "regular"
        elif mode == "next_regular_turn":
            next_actor = self.advance_to_next_regular_actor(ctx=step_context)
            if next_actor != actor_id:
                raise SimulatorError(f"Expected {actor_id}, got next regular actor {next_actor}")
            turn_kind = turn_kind or "regular"
        elif mode in ("extra_turn", "ultimate"):
            turn_kind = turn_kind or mode
        elif mode in ("interrupt", "manual", "immediate"):
            # Manual/interrupt actions do not tick regular-turn durations unless caller sets turn_kind.
            pass
        else:
            raise SimulatorError(f"Unknown timing mode: {mode}")
        step_context["turn_kind"] = turn_kind
        settlement.transition.request.turn_kind = turn_kind
        self.resolve_action(action, targets or [], step.get("events", {}), context=step_context)
        settlement.capture_after_snapshot(self.full_scene_snapshot())

        if coerce_bool(step.get("auto_resolve_queues_after", True), default=True):
            self.drain_queues(default_events=step.get("events", {}))

    def normalize_targets(self, targets: Any) -> Optional[list[str]]:
        """Normalize explicit target fields into a list of unit ids.

        YAML authors often write ``targets: enemy_1`` for a single target.
        Without normalization, Python would iterate the string one character at
        a time during damage resolution and silently skip the intended target.
        ``None`` is preserved so queued actions can distinguish "no explicit
        targets; resolve target_policy later" from an explicit empty list.
        """
        if targets is None:
            return None
        if isinstance(targets, str):
            return [targets]
        return list(targets)

    def ordered_alive_side_units(self, side: str) -> list[UnitState]:
        units = [u for u in self.state.units.values() if u.side == side and u.alive]
        def pos_key(u: UnitState):
            raw = u.flags.get("position", u.flags.get("slot", u.flags.get("formation_index", None)))
            num = maybe_float(raw)
            return (0, num) if num is not None else (1, list(self.state.units).index(u.id) if u.id in self.state.units else 9999)
        return sorted(units, key=pos_key)

    def adjacent_units_from_order(self, ordered: list[UnitState], selected_id: str | None, include_selected: bool = True) -> list[str]:
        if not ordered:
            return []
        idx = 0
        if selected_id and selected_id in {u.id for u in ordered}:
            idx = next(i for i, u in enumerate(ordered) if u.id == selected_id)
        picked = []
        for j in (idx - 1, idx, idx + 1):
            if 0 <= j < len(ordered):
                if include_selected or j != idx:
                    picked.append(ordered[j].id)
        return picked

    def select_targets(self, action: dict[str, Any], context: Optional[dict[str, Any]]) -> list[str]:
        policy = action.get("target_policy", "manual")
        actor = self.state.unit(action["actor_id"])
        if actor.side == "enemy":
            pending = actor.flags.get("enemy_ai_pending_target_selector")
            pending_action = actor.flags.get("enemy_ai_pending_target_action")
            if isinstance(pending, dict) and (not pending_action or str(pending_action) == str(action.get("id"))):
                picked = self.select_targets_from_enemy_ai_selector(actor, pending, action, context or {})
                if picked:
                    self.commit_unit_flag_remove(actor, "enemy_ai_pending_target_selector", reason="enemy_ai:consume_pending_target_selector", ctx=context, payload={"action": action.get("id"), "targets": picked})
                    self.commit_unit_flag_remove(actor, "enemy_ai_pending_target_action", reason="enemy_ai:consume_pending_target_action", ctx=context, payload={"action": action.get("id"), "targets": picked})
                    self.state.log_event("enemy_ai", f"{actor.id} selected targets via ConfigAI selector", {"action": action.get("id"), "targets": picked, "selector": pending})
                    return picked
        if policy == "manual":
            if not action.get("damage_packets") and not action.get("damage_packet"):
                return []
            raise SimulatorError(f"Action {action['id']} requires explicit targets")
        if policy in {"lowest_hp_percent_enemy", "lowest_hp_enemy"}:
            candidates = self.state.enemies_alive()
            if not candidates:
                return []
            return [min(candidates, key=lambda u: u.hp_percent).id]
        if policy in {"random_enemy", "random_alive_enemy", "first_enemy"}:
            candidates = self.state.enemies_alive()
            if not candidates:
                return []
            # Deterministic route validation: random choices must be supplied via
            # explicit targets/events for exact replay; the alias defaults to the
            # first currently alive enemy so template actions remain runnable.
            return [candidates[0].id]
        if policy in {"random_ally", "random_alive_ally", "first_ally"}:
            candidates = self.ordered_alive_side_units("ally")
            if not candidates:
                return []
            return [candidates[0].id]
        if policy in {"three_consecutive_allies_from_left", "sweep_three_allies_from_left"}:
            return [u.id for u in self.ordered_alive_side_units("ally")[:3]]
        if policy in {"three_consecutive_allies_from_right", "sweep_three_allies_from_right"}:
            return [u.id for u in self.ordered_alive_side_units("ally")[-3:]]
        if policy in {"selected_ally_and_adjacent", "selected_single_ally_and_adjacent", "splash_selected_ally_and_adjacent"}:
            selected = None
            if context:
                ctx_targets = self.normalize_targets(context.get("targets")) or []
                selected = context.get("target_id") or (ctx_targets[0] if ctx_targets else None)
            return self.adjacent_units_from_order(self.ordered_alive_side_units("ally"), selected, include_selected=True)
        if policy in {"all_allies_split", "split_all_allies", "even_distribution_all_allies"}:
            return [u.id for u in self.ordered_alive_side_units("ally")]
        if policy == "same_target":
            target_id = None
            if context:
                target_id = context.get("target_id")
                if not target_id:
                    context_targets = self.normalize_targets(context.get("targets")) or []
                    if len(context_targets) == 1:
                        target_id = context_targets[0]
            if target_id:
                # A deferred same-target queued action should not pay costs or
                # resolve into a dead/missing target after the source hit has
                # defeated it. Returning [] lets drain_queues skip it cleanly.
                if target_id in self.state.units and self.state.unit(target_id).alive:
                    return [target_id]
                return []
            raise SimulatorError("same_target policy needs context.target_id or one selected action target")
        if policy == "original_target_or_lowest_hp_percent_enemy":
            if context and context.get("target_id") and context["target_id"] in self.state.units and self.state.unit(context["target_id"]).alive:
                return [context["target_id"]]
            candidates = self.state.enemies_alive()
            if not candidates:
                return []
            return [min(candidates, key=lambda u: u.hp_percent).id]
        if policy in {"all_enemies", "enemy_side", "enemies_or_global_enemy_side"}:
            return [u.id for u in self.state.enemies_alive()]
        if policy in {"all_allies", "all_player_characters", "ally_side", "all_ally_characters", "all_ally_targets", "ally_characters"}:
            return [u.id for u in self.ordered_alive_side_units("ally")]
        if policy in {"highest_hp_enemy", "enemy_highest_current_hp", "highest_hp_among_hit_targets"}:
            candidates = self.state.enemies_alive()
            if not candidates:
                return []
            return [max(candidates, key=lambda u: u.hp).id]
        if policy in {"selected_ally", "selected_single_ally", "selected_enemy", "manual_selected"}:
            if context:
                ctx_targets = self.normalize_targets(context.get("targets")) or []
                return [t for t in ctx_targets if t in self.state.units and self.state.unit(t).alive]
            raise SimulatorError(f"Action {action['id']} with target_policy {policy} requires explicit targets")
        if policy in {"self", "actor"}:
            return [actor.id]
        raise SimulatorError(f"Unknown target policy: {policy}")

    def normalize_damage_packet_schema(self, packet: dict[str, Any]) -> dict[str, Any]:
        """Accept model-pack packet aliases in addition to simulator-native fields."""
        packet = deepcopy(packet or {})
        scaling = packet.get("scaling", {}) if isinstance(packet.get("scaling", {}), dict) else {}
        if "scaling_stat" not in packet and scaling.get("stat") is not None:
            packet["scaling_stat"] = scaling.get("stat")
        if "multiplier" not in packet:
            if scaling.get("multiplier") is not None:
                packet["multiplier"] = scaling.get("multiplier")
            else:
                # Model templates often store level-indexed multipliers. When a
                # concrete trace level is not supplied in the route case, use the
                # highest available level as the best explicit model value rather
                # than silently treating the packet as zero damage.
                for key in ("multiplier_by_level", "multiplier_at_level", "multiplier_by_trace_level"):
                    table = scaling.get(key)
                    if isinstance(table, dict) and table:
                        numeric_items = []
                        for lvl, val in table.items():
                            lvl_num = maybe_float(lvl)
                            val_num = maybe_float(val)
                            if lvl_num is not None and val_num is not None:
                                numeric_items.append((lvl_num, val_num))
                        if numeric_items:
                            packet["multiplier"] = sorted(numeric_items)[-1][1]
                            break
        for key in (
            "multiplier_at_talent_10", "multiplier_at_skill_10", "multiplier_at_ultimate_10", "multiplier_at_ult_10", "multiplier_at_basic_6",
            "multiplier_at_basic_10", "multiplier_at_skill_12", "multiplier_at_ultimate_12", "multiplier_at_ult_12",
        ):
            if "multiplier" not in packet and scaling.get(key) is not None:
                packet["multiplier"] = scaling.get(key)
        if "flat_damage" not in packet and scaling.get("flat_damage") is not None:
            packet["flat_damage"] = scaling.get("flat_damage")

        crit = packet.get("crit", {}) if isinstance(packet.get("crit", {}), dict) else {}
        if "can_crit" not in packet and "can_crit" in crit:
            packet["can_crit"] = crit.get("can_crit")
        if "forced_crit" not in packet and "forced_crit" in crit:
            packet["forced_crit"] = crit.get("forced_crit")

        toughness = packet.get("toughness", {}) if isinstance(packet.get("toughness", {}), dict) else {}
        if "toughness_reduction" not in packet and "toughness_reduction" in toughness:
            packet["toughness_reduction"] = toughness.get("toughness_reduction")
        if "ignore_weakness_for_toughness" not in packet and "ignore_weakness_for_toughness" in toughness:
            packet["ignore_weakness_for_toughness"] = toughness.get("ignore_weakness_for_toughness")
        packet["tags"] = normalize_str_list(packet.get("tags", []))
        return packet

    def resolve_packet_targets(self, packet: dict[str, Any], action: dict[str, Any], action_ctx: dict[str, Any], default_targets: list[str]) -> list[str]:
        if "targets" in packet:
            return self.normalize_targets(packet.get("targets")) or []
        if "target" in packet:
            raw_target = packet.get("target")
            if isinstance(raw_target, str) and raw_target in self.state.units:
                return [raw_target]
            return self.resolve_effect_targets({"target": raw_target}, action_ctx, default="target")
        if packet.get("target_policy"):
            return self.select_targets({**action, **packet}, action_ctx)
        return list(default_targets or [])

    def expand_damage_packets(self, packets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Expand model-pack hit_model.hits into per-hit packets.

        This lets multi-hit attacks tick per-hit durations/energy and expose
        mid-action ultimate windows while keeping the original total multiplier
        when hit shares sum to 1.
        """
        out: list[dict[str, Any]] = []
        for raw in packets or []:
            p = self.normalize_damage_packet_schema(raw)
            hit_model = p.get("hit_model", {}) if isinstance(p.get("hit_model", {}), dict) else {}
            hits = hit_model.get("hits")
            if isinstance(hits, list) and hits:
                base_mult = coerce_float(p.get("multiplier", 0.0))
                for idx, share in enumerate(hits, 1):
                    hp = deepcopy(p)
                    hp["id"] = f"{p.get('id', 'hit')}_{idx}"
                    hp["multiplier"] = base_mult * coerce_float(share)
                    hp.setdefault("hit_index", idx)
                    hp.setdefault("hit_count", len(hits))
                    out.append(hp)
            else:
                out.append(p)
        return out

    def resolve_action(self, action: dict[str, Any], targets: list[str], events: dict[str, Any], context: Optional[dict[str, Any]] = None) -> None:
        context = context or {}
        targets = self.normalize_targets(targets) or []
        actor = self.state.unit(action["actor_id"])
        if "owner_id" not in context and actor.flags.get("owner_id"):
            context["owner_id"] = actor.flags.get("owner_id")
        if not actor.alive and not coerce_bool(action.get("allow_dead_actor", False), default=False):
            raise SimulatorError(f"Actor {actor.id} is dead")
        action_tags = set(normalize_str_list(action.get("tags", [])))
        turn_kind = context.get("turn_kind")
        if turn_kind:
            self.begin_turn(actor, turn_kind, action, context=context)
            blockers = self.action_block_statuses(actor) if turn_kind == "regular" else []
            if blockers:
                self.state.log_event("action_block", f"{actor.id} action blocked by {blockers[0].id}", {"actor": actor.id, "statuses": [st.id for st in blockers], "turn_kind": turn_kind})
                self.finish_regular_action(actor, action, ctx=context)
                if any(st.modifiers.get("frozen") for st in blockers if isinstance(st.modifiers, dict)):
                    old_rem = actor.remaining_av
                    self.apply_action_advance(actor, 0.50, ctx=context, reason="control:frozen_auto_advance")
                    # Phase 2: 冰冻拉条记录
                    self._settle(context, "av",
                        unit_id=actor.id, old_remaining_av=old_rem, new_remaining_av=actor.remaining_av,
                        old_absolute_av=self.state.av + old_rem, new_absolute_av=self.state.av + actor.remaining_av,
                        speed=actor.speed, action_interval=self.action_interval(actor),
                        change_type=AV_ADVANCE, change_detail="冰冻自动拉条 50%",
                        record_state_change=False,
                    )
                self.end_turn(actor, turn_kind, action, context=context)
                return
        action_ctx = {
            "action": action,
            "actor_id": actor.id,
            "actor": actor,
            "targets": targets,
            "events": events,
            "context": context,
            "turn_kind": turn_kind,
            "owner_id": context.get("owner_id"),
            # Phase 2: 结算收集器通过 action_ctx 传给所有下游函数
            "_settlement": context.get("_settlement"),
            # Shared within a single action. Non-carry phase_hp boundaries
            # reached by packets or action-owned effect damage lock that target
            # against later damage sources in the same action.
            "phase_locked_targets": set(),
        }
        if len(targets) == 1:
            action_ctx["target_id"] = targets[0]
            if targets[0] in self.state.units:
                action_ctx["target"] = self.state.unit(targets[0])
        self.state.log_event("action_start", f"{actor.id} uses {action['id']} on {targets}", {"tags": sorted(action_tags), "turn_kind": turn_kind})
        self.run_triggers("before_action_check", action_ctx)
        self.validate_and_pay_cost(actor, action, action_ctx=action_ctx)
        self.run_triggers("action_start", action_ctx)

        if actor.side == "ally" and ({"skill_use", "ultimate_use"} & action_tags):
            for st in actor.statuses:
                if st.id == "savage_god_glory" or "glory" in {str(t).lower() for t in st.tags}:
                    old = st.stacks
                    self.commit_status_stacks(
                        actor,
                        st,
                        min(st.max_stacks, st.stacks + 1),
                        reason="savage_glory:ally_action_stack",
                        ctx=action_ctx,
                        payload={"action": action.get("id"), "action_tags": sorted(action_tags)},
                    )
                    if st.stacks != old:
                        self.state.log_event("enemy_mechanic", f"{actor.id} Glory stacks {old}->{st.stacks}", {"unit": actor.id, "status": st.id})

        # Some character actions have a dedicated post-start/pre-damage window
        # (for example self-buffs applied by a skill before its own damage).
        for eff in action.get("effects_after_action_start", []) or []:
            self.apply_effect(eff, action_ctx)

        # Direct action effects before damage.
        for eff in action.get("effects_before_damage", []):
            self.apply_effect(eff, action_ctx)

        attack_targets_hit: set[str] = set()
        any_packet_hit = False
        total_attack_damage = 0.0
        # Phase HP bars are semantic phase boundaries, not merely visual HP
        # segments. When a non-carry phase boundary is reached, later packets in
        # the same action must not immediately damage the newly entered phase.
        # Otherwise a multi-hit attack can leak damage across a phase boundary
        # even though carry_over_damage=false.
        phase_locked_targets: set[str] = action_ctx.setdefault("phase_locked_targets", set())
        damage_packets = self.expand_damage_packets(action.get("damage_packets", []) or [])
        packet_count_for_energy = max(1, len(damage_packets))
        for packet_idx, packet in enumerate(damage_packets):
            packet_actor_energy_applied = False
            # If packet defines target/targets/target_policy it may override route targets.
            packet_targets = self.resolve_packet_targets(packet, action, action_ctx, targets)
            packet_for_targets = packet
            if coerce_bool(packet.get("split_damage_across_targets", False), default=False) and packet_targets:
                packet_for_targets = deepcopy(packet)
                divisor = max(1, len(packet_targets))
                if "multiplier" in packet_for_targets:
                    packet_for_targets["multiplier"] = coerce_float(packet_for_targets.get("multiplier", 0.0)) / divisor
                if "flat_damage" in packet_for_targets:
                    packet_for_targets["flat_damage"] = coerce_float(packet_for_targets.get("flat_damage", 0.0)) / divisor
                packet_for_targets["split_damage_divisor"] = divisor
            for target_id in packet_targets:
                if target_id in phase_locked_targets:
                    self.state.log_event(
                        "damage_skip",
                        f"Skip {target_id}: phase HP boundary locked further damage from {actor.id}.{action['id']}",
                        {"actor": actor.id, "action": action["id"], "target": target_id, "packet": packet.get("id")},
                    )
                    continue
                if target_id not in self.state.units:
                    continue
                target_unit_for_packet = self.state.unit(target_id)
                defeated_this_action = action_ctx.get("defeated_targets_this_action")
                already_defeated_by_primary = isinstance(defeated_this_action, set) and str(target_id) in defeated_this_action
                if not target_unit_for_packet.alive and not already_defeated_by_primary:
                    continue
                if already_defeated_by_primary:
                    self.state.log_event(
                        "primary_damage_overkill",
                        f"{actor.id}.{action['id']} continues primary damage packet {packet.get('id')} on already defeated {target_id}",
                        {"actor": actor.id, "action": action["id"], "target": target_id, "packet": packet.get("id"), "reason": "primary_action_full_resolution"},
                    )
                packet_ctx = {**action_ctx, "packet": packet_for_targets, "target_id": target_id, "target": target_unit_for_packet}
                self.run_triggers("before_damage", packet_ctx)
                result = self.resolve_damage_packet(packet_for_targets, actor, self.state.unit(target_id), action, events)
                self.apply_damage_result(result, packet_ctx)
                # Phase 2: 伤害记录
                self._settle(action_ctx, "damage",
                    packet_index=packet_idx,
                    source_action_id=action.get("id", ""),
                    actor_id=actor.id,
                    target_id=target_id,
                    element=str(result.get("element", "")),
                    damage_type=str(packet.get("damage_type", "direct_damage")),
                    base_damage=float(result.get("base_damage", 0.0)),
                    crit=bool(result.get("crit", {}).get("is_critical", False)),
                    crit_multiplier=float(result.get("crit", {}).get("multiplier", 1.0)),
                    dmg_bonus_multiplier=float(result.get("multipliers", {}).get("dmg_bonus", 1.0)),
                    def_multiplier=float(result.get("multipliers", {}).get("defense", 1.0)),
                    res_multiplier=float(result.get("multipliers", {}).get("res", 1.0)),
                    damage_taken_multiplier=float(result.get("multipliers", {}).get("damage_taken", 1.0)),
                    universal_reduction_multiplier=float(result.get("multipliers", {}).get("universal_reduction", 1.0)),
                    toughness_state_multiplier=float(result.get("multipliers", {}).get("toughness_state", 1.0)),
                    final_damage=float(result.get("damage", 0.0)),
                    applied_damage=float(result.get("damage", 0.0)),
                    shield_absorbed=0.0,
                    formula_ledger=result.get("formula_ledger", {}),
                    skip_reason="",
                )
                total_attack_damage += coerce_float(result.get("final_damage", result.get("damage", 0.0)))
                if target_id in self.state.units:
                    self.apply_entanglement_hit_stack(self.state.unit(target_id), result, ctx=packet_ctx)
                packet_ctx["damage_result"] = result
                if result.get("hp_bar_depleted"):
                    self.apply_hp_bar_depleted_effects(result, packet_ctx)
                self.apply_hit_taken_energy(self.state.unit(target_id), packet_for_targets, action, result, ctx=action_ctx)
                if not packet_actor_energy_applied:
                    self.apply_packet_actor_energy_gain(actor, action, packet, packet_count_for_energy, ctx=action_ctx)
                    packet_actor_energy_applied = True
                self.run_triggers("after_damage", packet_ctx)
                self.run_triggers("after_hp_change", packet_ctx)
                if result.get("hp_bar_depleted"):
                    self.run_triggers("after_hp_bar_depleted", packet_ctx)
                if result["target_defeated"]:
                    # Defeat energy is part of resolving the killing hit.
                    # Apply it before after_defeat_enemy triggers so trigger
                    # conditions and queued follow-up actions observe the
                    # post-kill energy state.
                    self.note_action_defeat(target_id, actor.id, "primary_action_damage", action_ctx)
                    self.apply_kill_energy(actor, self.state.unit(target_id), action, ctx=action_ctx)
                    packet_ctx["actor"] = actor
                    packet_ctx["target"] = self.state.unit(target_id)
                    self.run_triggers("after_defeat_enemy", packet_ctx)
                if result.get("phase_damage_locked_until_action_end"):
                    phase_locked_targets.add(target_id)
                self.tick_hit_durations(actor, self.state.unit(target_id), action, ctx=action_ctx)
                if "attack" in action_tags:
                    any_packet_hit = True
                    attack_targets_hit.add(target_id)

        if any_packet_hit:
            self.tick_attack_durations(actor, sorted(attack_targets_hit), action, ctx=action_ctx)
        action_ctx["attacked_targets"] = sorted(attack_targets_hit)
        action_ctx["hit_target_count"] = len(attack_targets_hit)
        action_ctx["total_attack_damage"] = total_attack_damage

        # Action-level after-damage effects resolve once after all packets, not
        # after each hit. Per-packet reactions should use triggers at timing
        # after_damage instead.
        for eff in action.get("effects_after_damage", []) or []:
            self.apply_effect(eff, action_ctx)

        for eff in action.get("effects", []):
            self.apply_effect(eff, action_ctx)

        self.apply_action_energy_gain(actor, action, ctx=action_ctx)
        # For a regular action, the next action value is established before
        # action_end triggers.  Otherwise action-end action-advance effects on the
        # actor are applied to the just-spent 0 AV and then lost when the regular
        # action refreshes the timeline.  Speed/status changes still recalculate
        # the refreshed AV through their normal helpers.
        self.finish_regular_action(actor, action, ctx=action_ctx)
        # Phase 2: 常规行动 AV 记录
        self._settle(action_ctx, "av",
            unit_id=actor.id, old_remaining_av=0.0, new_remaining_av=actor.remaining_av,
            old_absolute_av=self.state.av, new_absolute_av=self.state.av + actor.remaining_av,
            speed=actor.speed, action_interval=self.action_interval(actor),
            change_type=AV_REGULAR_TURN, change_detail="行动结束, 恢复行动间隔",
            record_state_change=False,
        )

        # Model-pack semantic timings that depend on the fully resolved action,
        # not merely the raw action_start/action_end lifecycle.  These are needed
        # for stateful video replay: Dance! Dance! Dance! after the wearer's
        # Ultimate, Seele's basic-attack advance, and Dan Heng's Souldragon
        # advance after the bondmate attacks.
        if "ultimate_use" in action_tags:
            self.run_triggers("after_wearer_uses_ultimate", action_ctx)
            self.run_triggers("after_ally_uses_ultimate", action_ctx)
            if actor.side == "ally":
                self.run_triggers("after_other_ally_uses_ultimate", action_ctx)
        if "attack" in action_tags and any_packet_hit:
            self.run_triggers("after_ally_attacks" if actor.side == "ally" else "after_enemy_attacks", action_ctx)
            bondmate = self.state.global_flags.get("bondmate") or self.state.global_flags.get("bondmate_target")
            if bondmate and str(bondmate) == actor.id:
                _bondmate_trigger_log_start = len(self.state.log)
                self.run_triggers("after_bondmate_uses_attack", action_ctx)
                self.apply_souldragon_bondmate_attack_semantics(action_ctx, _bondmate_trigger_log_start)
        if actor.id == "souldragon" or "souldragon" in {str(t).lower() for t in actor.tags}:
            self.run_triggers("after_souldragon_action", action_ctx)

        if actor.side == "enemy":
            enemy_chain_context = coerce_bool(context.get("enemy_action_chain", False), default=False)
            record_chain_use = coerce_bool(context.get("chain_record_skill_use", action.get("chain_record_skill_use", True)), default=True)
            if (not enemy_chain_context) or record_chain_use:
                self.record_enemy_skill_use_after_action(actor, str(action.get("id")), ctx=action_ctx)
            else:
                self.state.log_event("enemy_ai", f"{actor.id} does not record chained skill use {action.get('id')}", {"action": action.get("id"), "chain_id": context.get("chain_id")})
        if actor.side == "enemy" and isinstance(actor.flags.get("enemy_ai_sequence"), list):
            enemy_chain_context = coerce_bool(context.get("enemy_action_chain", False), default=False)
            advance_chain = coerce_bool(context.get("chain_advances_enemy_sequence", action.get("chain_advances_enemy_sequence", False)), default=False)
            if (not enemy_chain_context) or advance_chain:
                self.advance_enemy_ai_sequence_after_action(actor, str(action.get("id")), ctx=action_ctx)
            else:
                self.state.log_event("enemy_ai", f"{actor.id} holds AI cursor after chained continuation {action.get('id')}", {"action": action.get("id"), "sequence_index": actor.flags.get("enemy_ai_sequence_index"), "chain_id": context.get("chain_id")})
        if actor.side == "enemy" and str(actor.flags.get("clear_glory_after_next_savage_action", "")).lower() == "ready":
            self.clear_savage_god_glory_after_action(actor, action_ctx)
            self.commit_unit_flag(actor, "clear_glory_after_next_savage_action", False, reason="savage_glory:clear_flag_consumed", ctx=action_ctx, payload={"action": action.get("id")})
        elif actor.side == "enemy" and str(actor.flags.get("clear_glory_after_next_savage_action", "")).lower() == "armed":
            self.commit_unit_flag(actor, "clear_glory_after_next_savage_action", "ready", reason="savage_glory:arm_clear_after_next_action", ctx=action_ctx, payload={"action": action.get("id")})
            self.state.log_event("enemy_mechanic", f"{actor.id} arms Glory clear after next action", {"flag": "clear_glory_after_next_savage_action"})

        self.run_triggers("action_end", action_ctx)
        # Summon lifecycle ticks after semantic/action_end triggers so triggers such
        # as after_souldragon_action can still observe the just-used enhanced state.
        self.tick_summon_lifecycle(actor, action, ctx=action_ctx)
        self.tick_status_durations(event="action_end", actor=actor, turn_kind=turn_kind, action=action, ctx=action_ctx)
        if turn_kind:
            self.end_turn(actor, turn_kind, action, context=action_ctx)
        self.check_wave_transition()
        self.state.log_event("action_end", f"{actor.id} finished {action['id']}")

    def action_skill_point_delta(self, actor: UnitState, action: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        """Return effective SP delta after generic next-skill cost overrides.

        Model-pack status effects may express "the next Skill does not consume SP"
        without hard-coding a character name.  The simulator convention is that
        negative skill_points consumes SP and positive skill_points restores SP.
        """
        cost = action.get("cost", {}) if isinstance(action.get("cost", {}), dict) else {}
        sp_source = cost.get("skill_points", action.get("skill_point_delta", 0))
        original = coerce_int(sp_source, 0)
        effective = original
        action_tags = set(normalize_str_list(action.get("tags", [])))
        audit: dict[str, Any] = {"original_delta": original, "effective_delta": effective, "overrides": []}
        if "skill_use" not in action_tags:
            return effective, audit
        for st in actor.statuses:
            mods = st.modifiers if isinstance(st.modifiers, dict) else {}
            if not (
                st.duration_type == "until_next_skill_use"
                or "cost_override" in st.tags
                or "skill_point_cost_override" in mods
                or "next_skill_cost_delta" in mods
            ):
                continue
            candidate = effective
            if "skill_point_cost_override" in mods:
                # cost_override=0 means SP delta becomes 0 for this skill.
                candidate = -coerce_int(mods.get("skill_point_cost_override", 0), 0)
            if "next_skill_cost_delta" in mods:
                candidate = max(candidate, original + coerce_int(mods.get("next_skill_cost_delta", 0), 0) * max(1, st.stacks))
            # Pick the least costly candidate but never turn a cost discount into SP gain.
            candidate = min(0, candidate) if original < 0 else candidate
            if candidate > effective:
                effective = candidate
                audit["overrides"].append({"status_id": st.id, "duration_type": st.duration_type, "modifiers": deepcopy(mods), "candidate_delta": candidate})
        audit["effective_delta"] = effective
        return effective, audit

    def consume_next_skill_cost_override_statuses(self, actor: UnitState, action: dict[str, Any], audit: dict[str, Any], ctx: Optional[dict[str, Any]] = None) -> None:
        """Remove one-shot cost override statuses after the matching Skill cost is resolved."""
        if not audit.get("overrides"):
            return
        action_tags = set(normalize_str_list(action.get("tags", [])))
        if "skill_use" not in action_tags:
            return
        override_ids = {str(row.get("status_id")) for row in audit.get("overrides", []) if row.get("status_id")}
        for st in list(actor.statuses):
            if st.id not in override_ids:
                continue
            old_speed = self.effective_speed(actor)
            lifecycle_ctx = {**(ctx or {}), "actor_id": actor.id, "actor": actor, "action": action, "status_id": st.id, "status": st, "removed_status": st, "trigger": {"status_id": st.id}, "status_owner_id": actor.id}
            self.remove_status_resource_side_effects(actor, st, ctx=lifecycle_ctx)
            self.commit_status_remove(
                actor,
                st,
                reason="consume_next_skill_cost_override",
                ctx=lifecycle_ctx,
                payload={"action": action.get("id"), "removed_status": st.to_json()},
            )
            self.recalculate_remaining_av_for_speed_change(actor, old_speed, reason="consume_next_skill_cost_override", ctx=lifecycle_ctx)
            self.state.log_event("resource", f"{actor.id}.{st.id} consumed by next Skill cost override", {"action": action.get("id"), "status": st.to_json()})
            self.run_triggers("status_destroy", lifecycle_ctx)

    def can_pay_action_cost(self, actor: UnitState, action: dict[str, Any]) -> tuple[bool, str | None]:
        """Return whether an action is currently affordable without mutating state."""
        sp_delta, _sp_audit = self.action_skill_point_delta(actor, action)
        if self.state.skill_points + sp_delta < 0:
            return False, f"not_enough_skill_points:{self.state.skill_points}+{sp_delta}"
        cost = action.get("cost", {}) if isinstance(action.get("cost", {}), dict) else {}
        energy_cost = coerce_float(cost.get("energy", 0))
        if energy_cost > 0 and actor.energy + EPS < energy_cost:
            return False, f"not_enough_energy:{actor.energy}<{energy_cost}"
        return True, None

    def validate_and_pay_cost(self, actor: UnitState, action: dict[str, Any], action_ctx: dict[str, Any] | None = None) -> None:
        payable, reason = self.can_pay_action_cost(actor, action)
        sp_delta, sp_audit = self.action_skill_point_delta(actor, action)
        if not payable:
            if reason and reason.startswith("not_enough_skill_points"):
                raise SimulatorError(f"Not enough skill points for {action['id']}: {self.state.skill_points} + {sp_delta}")
            cost = action.get("cost", {}) if isinstance(action.get("cost", {}), dict) else {}
            energy_cost = coerce_float(cost.get("energy", 0))
            raise SimulatorError(f"Not enough energy for {actor.id}.{action['id']}: {actor.energy} < {energy_cost}")
        if sp_delta:
            sp_ctx = dict(action_ctx or {})
            sp_ctx.update({"actor_id": actor.id, "actor": actor, "action": action})
            sp_change = self.modify_skill_points_with_overflow(sp_delta, reason=f"action_cost:{actor.id}.{action.get('id')}", ctx=sp_ctx)
            old = sp_change["old"]
            # Phase 2: 记录 SP 变化
            settlement = action_ctx.get("_settlement") if action_ctx else None
            if settlement is not None:
                settlement.record_sp(
                    delta=int(sp_delta),
                    old_value=int(old),
                    new_value=self.state.skill_points,
                    max_value=self.state.skill_point_cap,
                    reason="action_cost" if sp_delta < 0 else "action_refund",
                    reason_detail=f"{actor.id} 使用 {action.get('id', '?')}",
                    source_unit_id=actor.id,
                    record_state_change=False,
                )
            if sp_delta < 0:
                sp_ctx = {
                    "actor_id": actor.id,
                    "actor": actor,
                    "action": action,
                    "consumed_skill_points": abs(sp_delta),
                    "skill_point_delta": sp_delta,
                    "old_skill_points": old,
                    "new_skill_points": self.state.skill_points,
                }
                self.run_triggers("after_skill_point_consumed", sp_ctx)
        elif sp_audit.get("overrides"):
            self.state.log_event("resource", f"Skill point cost for {actor.id}.{action['id']} overridden to 0", {"skill_point_cost_audit": sp_audit, "skill_points": self.state.skill_points})
        self.consume_next_skill_cost_override_statuses(actor, action, sp_audit, ctx=action_ctx)
        cost = action.get("cost", {}) if isinstance(action.get("cost", {}), dict) else {}
        energy_cost = coerce_float(cost.get("energy", 0))
        if energy_cost > 0:
            if actor.energy + EPS < energy_cost:
                raise SimulatorError(f"Not enough energy for {actor.id}.{action['id']}: {actor.energy} < {energy_cost}")
            old = actor.energy
            energy_ctx = dict(action_ctx or {})
            energy_ctx.update({"actor_id": actor.id, "actor": actor, "action": action})
            self.commit_unit_energy(
                actor,
                actor.energy - energy_cost,
                reason=f"action_cost:{actor.id}.{action.get('id')}:energy",
                ctx=energy_ctx,
                payload={"energy_cost": energy_cost},
            )
            self.state.log_event("resource", f"{actor.id} energy {old:.3f} -> {actor.energy:.3f}", {"delta": -energy_cost})
            # Phase 2: 记录能量消耗
            settlement = action_ctx.get("_settlement") if action_ctx else None
            if settlement is not None:
                settlement.record_energy(
                    unit_id=actor.id,
                    delta=-energy_cost,
                    old_value=old,
                    new_value=actor.energy,
                    max_energy=actor.max_energy,
                    source_type=ENERGY_SOURCE_COST,
                    source_detail=f"使用 {action.get('id', '?')} 消耗",
                    affected_by_err=False,
                    record_state_change=False,
                )

    # ---------- damage ----------
    def resolve_packet_multiplier_reference(self, packet: dict[str, Any], actor: UnitState) -> Optional[float]:
        scaling = packet.get("scaling", {}) if isinstance(packet.get("scaling", {}), dict) else {}
        ref = scaling.get("multiplier_by_reference") or packet.get("multiplier_by_reference")
        if not isinstance(ref, dict):
            return None
        ref_action_id = ref.get("action_id") or ref.get("action")
        if not ref_action_id:
            return None
        ref_action = None
        for key, candidate in actor.action_defs.items():
            if key == ref_action_id or candidate.get("id") == ref_action_id:
                ref_action = candidate
                break
        if not isinstance(ref_action, dict):
            return None
        ref_packets = ref_action.get("damage_packets") or ([ref_action.get("damage_packet")] if ref_action.get("damage_packet") else [])
        if not ref_packets:
            return None
        ref_packet = self.normalize_damage_packet_schema(ref_packets[0])
        return coerce_float(ref_packet.get("multiplier", 0.0))

    def get_break_effect_value(self, actor: UnitState, ctx: dict[str, Any]) -> float:
        # Break Effect is a stat, but some model packs use break_effect_add or
        # break_effect_pct style modifiers.  contextual_stat handles split stats
        # and status modifiers; packet-local break_effect_add is accepted for
        # generated formula tests/effects.
        value = self.contextual_stat(actor, "break_effect", ctx)
        value += coerce_float((ctx.get("packet") or {}).get("break_effect_add", 0.0))
        return value

    def get_break_damage_bonus_multiplier(self, actor: UnitState, packet: dict[str, Any], ctx: dict[str, Any], *, super_break: bool = False) -> float:
        key = "super_break_damage_bonus" if super_break else "break_damage_bonus"
        bonus = coerce_float(packet.get(key, packet.get(f"{key}_add", 0.0)))
        # Generic break damage bonus applies to both normal break and super break;
        # super-break-specific bonus is added only for super break.
        generic = coerce_float(packet.get("break_damage_bonus", packet.get("break_damage_bonus_add", 0.0)))
        if super_break:
            bonus += generic
        for st, mods in self.applicable_status_modifiers(actor, ctx):
            bonus += coerce_float(mods.get("break_damage_bonus", mods.get("break_damage_bonus_add", 0.0))) * st.stacks
            if super_break:
                bonus += coerce_float(mods.get("super_break_damage_bonus", mods.get("super_break_damage_bonus_add", 0.0))) * st.stacks
        return 1.0 + bonus

    def resolve_break_damage_packet(self, packet: dict[str, Any], actor: UnitState, target: UnitState, action: dict[str, Any], events: dict[str, Any]) -> dict[str, Any]:
        packet = self.normalize_damage_packet_schema(packet)
        element = str(packet.get("element", "none") or "none").lower()
        dmg_ctx = {"action": action, "packet": packet, "actor_id": actor.id, "actor": actor, "owner_id": actor.flags.get("owner_id"), "target_id": target.id, "target": target}
        base = coerce_float(packet.get("break_base_damage", break_base_damage(actor.level)))
        elem_mult = coerce_float(packet.get("element_break_multiplier", element_break_multiplier(element)))
        max_toughness = coerce_float(packet.get("max_toughness", target.max_toughness or target.toughness or 0.0))
        toughness_mult = coerce_float(packet.get("break_toughness_multiplier", max_toughness_multiplier(max_toughness)))
        break_effect = self.get_break_effect_value(actor, dmg_ctx)
        break_bonus = self.get_break_damage_bonus_multiplier(actor, packet, dmg_ctx, super_break=False)
        defense = self.get_def_multiplier(actor, target, packet, dmg_ctx)
        res = self.get_res_multiplier(actor, target, element, dmg_ctx)
        taken = self.get_damage_taken_multiplier(target, packet, action, dmg_ctx)
        reduction = self.get_universal_reduction_multiplier(target, packet, action, dmg_ctx)
        other = coerce_float(packet.get("other_multiplier", 1.0))
        final = max(0.0, base * elem_mult * toughness_mult * (1.0 + break_effect) * break_bonus * defense * res * taken * reduction * other)
        return {
            "actor_id": actor.id,
            "target_id": target.id,
            "packet_id": packet.get("id"),
            "element": element,
            "damage_type": "break_damage",
            "base_damage": base,
            "crit": {"is_crit": False, "multiplier": 1.0, "source": "break_cannot_crit", "crit_rate": 0.0, "crit_dmg": 0.0},
            "multipliers": {
                "element_break": elem_mult,
                "break_toughness": toughness_mult,
                "break_effect": 1.0 + break_effect,
                "break_damage_bonus": break_bonus,
                "defense": defense,
                "res": res,
                "damage_taken": taken,
                "universal_reduction": reduction,
                "other": other,
            },
            "damage": final,
            "toughness_reduction": 0.0,
            "target_defeated": False,
        }

    def resolve_super_break_damage_packet(self, packet: dict[str, Any], actor: UnitState, target: UnitState, action: dict[str, Any], events: dict[str, Any]) -> dict[str, Any]:
        packet = self.normalize_damage_packet_schema(packet)
        element = str(packet.get("element", "none") or "none").lower()
        dmg_ctx = {"action": action, "packet": packet, "actor_id": actor.id, "actor": actor, "owner_id": actor.flags.get("owner_id"), "target_id": target.id, "target": target}
        base = coerce_float(packet.get("break_base_damage", break_base_damage(actor.level)))
        toughness_reduction = coerce_float(packet.get("final_toughness_reduction", packet.get("toughness_reduction", packet.get("toughness_damage", 0.0))))
        toughness_mult = coerce_float(packet.get("super_break_toughness_multiplier", toughness_reduction / 30.0))
        break_effect = self.get_break_effect_value(actor, dmg_ctx)
        super_bonus = self.get_break_damage_bonus_multiplier(actor, packet, dmg_ctx, super_break=True)
        defense = self.get_def_multiplier(actor, target, packet, dmg_ctx)
        res = self.get_res_multiplier(actor, target, element, dmg_ctx)
        taken = self.get_damage_taken_multiplier(target, packet, action, dmg_ctx)
        reduction = self.get_universal_reduction_multiplier(target, packet, action, dmg_ctx)
        broken_mult = coerce_float(packet.get("broken_multiplier", 1.0))
        other = coerce_float(packet.get("other_multiplier", 1.0))
        final = max(0.0, base * toughness_mult * (1.0 + break_effect) * super_bonus * defense * res * taken * reduction * broken_mult * other)
        return {
            "actor_id": actor.id,
            "target_id": target.id,
            "packet_id": packet.get("id"),
            "element": element,
            "damage_type": "super_break_damage",
            "base_damage": base,
            "crit": {"is_crit": False, "multiplier": 1.0, "source": "super_break_cannot_crit", "crit_rate": 0.0, "crit_dmg": 0.0},
            "multipliers": {
                "super_break_toughness": toughness_mult,
                "break_effect": 1.0 + break_effect,
                "super_break_damage_bonus": super_bonus,
                "defense": defense,
                "res": res,
                "damage_taken": taken,
                "universal_reduction": reduction,
                "broken": broken_mult,
                "other": other,
            },
            "damage": final,
            "toughness_reduction": 0.0,
            "target_defeated": False,
        }


    def _modifier_term(self, source_type: str, source_id: str, key: str, value: Any, *, stacks: int = 1, applied_value: Any | None = None, note: str | None = None) -> dict[str, Any]:
        value_f = coerce_float(value, 0.0)
        applied = value_f * max(1, coerce_int(stacks, 1)) if applied_value is None else coerce_float(applied_value, 0.0)
        rec = {
            "source_type": source_type,
            "source_id": source_id,
            "key": key,
            "value": round(value_f, 9),
            "stacks": stacks,
            "applied_value": round(applied, 9),
        }
        if note:
            rec["note"] = note
        return rec

    def collect_damage_formula_ledger(
        self,
        actor: UnitState,
        target: UnitState,
        packet: dict[str, Any],
        action: dict[str, Any],
        ctx: dict[str, Any],
        *,
        scaling_stat: str,
        scaling_value: float,
        base_damage: float,
        crit_info: dict[str, Any],
        multipliers: dict[str, float],
    ) -> dict[str, Any]:
        """Return source-level formula ledger for one direct damage packet.

        This ledger is audit-only: it mirrors the current formula path without
        changing final damage.  It is intentionally verbose so a later solver can
        prove which buff/debuff/packet field entered each damage bucket.
        """
        tags = set(normalize_str_list(action.get("tags", []))) | set(normalize_str_list(packet.get("tags", [])))
        element = str(packet.get("element", "none") or "none")
        ledger: dict[str, Any] = {
            "formula_type": "direct_damage",
            "actor_id": actor.id,
            "target_id": target.id,
            "action_id": action.get("id"),
            "packet_id": packet.get("id"),
            "tags": sorted(tags),
            "scaling": {
                "stat": scaling_stat,
                "scaling_value": round(coerce_float(scaling_value, 0.0), 9),
                "multiplier": round(coerce_float(packet.get("multiplier", 0.0), 0.0), 9),
                "flat_damage": round(coerce_float(packet.get("flat_damage", 0.0), 0.0), 9),
                "base_damage": round(coerce_float(base_damage, 0.0), 9),
            },
            "crit": deepcopy(crit_info),
            "buckets": {},
        }

        # Damage bonus bucket.
        dmg_terms: list[dict[str, Any]] = []
        all_bonus = coerce_float(actor.stats.get("all_dmg_bonus", 0.0))
        if abs(all_bonus) > EPS:
            dmg_terms.append(self._modifier_term("actor.stats", actor.id, "all_dmg_bonus", all_bonus, stacks=1))
        pkt_bonus = coerce_float(packet.get("dmg_bonus_add", 0.0))
        if abs(pkt_bonus) > EPS:
            dmg_terms.append(self._modifier_term("packet", str(packet.get("id")), "dmg_bonus_add", pkt_bonus, stacks=1))
        pkt_mult_alias = coerce_float(packet.get("dmg_bonus_multiplier", 0.0))
        if abs(pkt_mult_alias) > EPS:
            dmg_terms.append(self._modifier_term("packet", str(packet.get("id")), "dmg_bonus_multiplier", pkt_mult_alias, stacks=1))
        elem_bonus = coerce_float(actor.stats.get(f"{element}_dmg_bonus", 0.0)) if element else 0.0
        if abs(elem_bonus) > EPS:
            dmg_terms.append(self._modifier_term("actor.stats", actor.id, f"{element}_dmg_bonus", elem_bonus, stacks=1))
        for st, mods in self.applicable_status_modifiers(actor, ctx or {"action": action, "packet": packet}):
            val = coerce_float(mods.get("dmg_bonus_add", 0.0))
            if abs(val) > EPS:
                dmg_terms.append(self._modifier_term("actor.status", st.id, "dmg_bonus_add", val, stacks=st.stacks, note=f"source={st.source_id}"))
            if st.stacks > 0 and "next_attack_dmg_bonus_add" in mods:
                val2 = coerce_float(mods.get("next_attack_dmg_bonus_add", 0.0))
                if abs(val2) > EPS:
                    dmg_terms.append(self._modifier_term("actor.status", st.id, "next_attack_dmg_bonus_add", val2, stacks=1, note=f"source={st.source_id}; non_per_stack"))
            sub = mods.get("dmg_bonus", {})
            if isinstance(sub, dict):
                for key, val3 in sub.items():
                    if key == element or key in tags or key == "all":
                        val3f = coerce_float(val3, 0.0)
                        if abs(val3f) > EPS:
                            dmg_terms.append(self._modifier_term("actor.status", st.id, f"dmg_bonus.{key}", val3f, stacks=st.stacks, note=f"source={st.source_id}"))
        ledger["buckets"]["dmg_bonus"] = {"multiplier": round(coerce_float(multipliers.get("dmg_bonus", 1.0)), 9), "terms": dmg_terms}

        # Defense bucket.
        def_terms: list[dict[str, Any]] = []
        raw_def = target.get_stat("defense") or target.get_stat("def")
        def_ignore = coerce_float(packet.get("def_ignore", 0.0))
        if abs(def_ignore) > EPS:
            def_terms.append(self._modifier_term("packet", str(packet.get("id")), "def_ignore", def_ignore, stacks=1))
        for st, mods in self.applicable_status_modifiers(target, ctx or {"packet": packet}):
            val = coerce_float(mods.get("def_reduction", 0.0))
            if abs(val) > EPS:
                def_terms.append(self._modifier_term("target.status", st.id, "def_reduction", val, stacks=st.stacks, note=f"source={st.source_id}"))
        total_def_reduction = sum(coerce_float(t.get("applied_value", 0.0)) for t in def_terms if t.get("key") == "def_reduction") + def_ignore
        effective_def = 0.0 if coerce_bool(packet.get("ignore_defense_multiplier", False), default=False) else max(0.0, raw_def * (1 - total_def_reduction))
        ledger["buckets"]["defense"] = {
            "multiplier": round(coerce_float(multipliers.get("defense", 1.0)), 9),
            "raw_target_def": round(coerce_float(raw_def, 0.0), 9),
            "effective_target_def": round(coerce_float(effective_def, 0.0), 9),
            "ignore_defense_multiplier": coerce_bool(packet.get("ignore_defense_multiplier", False), default=False),
            "terms": def_terms,
        }

        # Resistance bucket.
        res_terms: list[dict[str, Any]] = []
        base_res = coerce_float(target.res.get(element, target.res.get("all", 0.0)))
        for st, mods in self.applicable_status_modifiers(target, ctx or {}):
            delta = mods.get("resistance_delta", {}) if isinstance(mods.get("resistance_delta", {}), dict) else {}
            val = coerce_float(delta.get(element, delta.get("all", 0.0)))
            if abs(val) > EPS:
                res_terms.append(self._modifier_term("target.status", st.id, f"resistance_delta.{element}", val, stacks=st.stacks, note=f"source={st.source_id}"))
        actor_stat_pen = coerce_float(actor.stats.get(f"{element}_res_pen", actor.stats.get("all_res_pen", 0.0)))
        if abs(actor_stat_pen) > EPS:
            res_terms.append(self._modifier_term("actor.stats", actor.id, f"{element}_or_all_res_pen", actor_stat_pen, stacks=1))
        for st, mods in self.applicable_status_modifiers(actor, ctx or {}):
            if isinstance(mods.get("res_pen"), dict):
                val = coerce_float(mods.get("res_pen", {}).get(element, 0.0))
                if abs(val) > EPS:
                    res_terms.append(self._modifier_term("actor.status", st.id, f"res_pen.{element}", val, stacks=1, note=f"source={st.source_id}"))
            val2 = coerce_float(mods.get("all_res_pen", 0.0))
            if abs(val2) > EPS:
                res_terms.append(self._modifier_term("actor.status", st.id, "all_res_pen", val2, stacks=1, note=f"source={st.source_id}"))
        target_res_delta = sum(coerce_float(t.get("applied_value", 0.0)) for t in res_terms if t.get("source_type") == "target.status")
        res_pen_total = sum(coerce_float(t.get("applied_value", 0.0)) for t in res_terms if t.get("source_type") in {"actor.stats", "actor.status"})
        ledger["buckets"]["res"] = {
            "multiplier": round(coerce_float(multipliers.get("res", 1.0)), 9),
            "base_target_res": round(base_res, 9),
            "target_res_after_delta": round(base_res + target_res_delta, 9),
            "res_pen_total": round(res_pen_total, 9),
            "terms": res_terms,
        }

        # Damage taken / vulnerability bucket.
        taken_terms: list[dict[str, Any]] = []
        base_taken = coerce_float(target.stats.get("damage_taken", 0.0))
        if abs(base_taken) > EPS:
            taken_terms.append(self._modifier_term("target.stats", target.id, "damage_taken", base_taken, stacks=1))
        for st, mods in self.applicable_status_modifiers(target, ctx or {"action": action, "packet": packet}):
            val = coerce_float(mods.get("damage_taken_add", 0.0))
            if abs(val) > EPS:
                taken_terms.append(self._modifier_term("target.status", st.id, "damage_taken_add", val, stacks=st.stacks, note=f"source={st.source_id}"))
            sub = mods.get("damage_taken", {})
            if isinstance(sub, dict):
                for key, val2 in sub.items():
                    if key == element or key in tags or key == "all":
                        val2f = coerce_float(val2, 0.0)
                        if abs(val2f) > EPS:
                            taken_terms.append(self._modifier_term("target.status", st.id, f"damage_taken.{key}", val2f, stacks=st.stacks, note=f"source={st.source_id}"))
        ledger["buckets"]["damage_taken"] = {"multiplier": round(coerce_float(multipliers.get("damage_taken", 1.0)), 9), "terms": taken_terms}

        # Universal damage reduction bucket.
        reduction_terms: list[dict[str, Any]] = []
        stat_reduction = coerce_float(target.stats.get("damage_reduction", 0.0)) if "damage_reduction" in target.stats else 0.0
        if abs(stat_reduction) > EPS:
            reduction_terms.append(self._modifier_term("target.stats", target.id, "damage_reduction", stat_reduction, stacks=1))
        for st, mods in self.applicable_status_modifiers(target, ctx or {"action": action, "packet": packet}):
            if "damage_reduction" in mods:
                if isinstance(mods.get("titanic_corpus"), dict):
                    val = coerce_float(mods["damage_reduction"], 0.0)
                    if abs(val) > EPS:
                        reduction_terms.append(self._modifier_term("target.status", st.id, "damage_reduction", val, stacks=1, note=f"source={st.source_id}; non_per_stack"))
                else:
                    val = coerce_float(mods["damage_reduction"], 0.0)
                    if abs(val) > EPS:
                        reduction_terms.append(self._modifier_term("target.status", st.id, "damage_reduction", val, stacks=st.stacks, note=f"source={st.source_id}"))
            armor = mods.get("armor_layers") if isinstance(mods.get("armor_layers"), dict) else None
            if armor:
                fixed = armor.get("damage_reduction_while_active", None)
                layers = st.stacks if st.stacks is not None else coerce_int(armor.get("layers", 0), 0)
                if fixed is not None and layers > 0:
                    val = min(0.9, max(0.0, coerce_float(fixed)))
                    reduction_terms.append(self._modifier_term("target.status", st.id, "armor_layers.damage_reduction_while_active", val, stacks=1, note=f"source={st.source_id}; layers={layers}"))
                else:
                    per = coerce_float(armor.get("damage_reduction_per_layer", 0.0))
                    if abs(per) > EPS:
                        reduction_terms.append(self._modifier_term("target.status", st.id, "armor_layers.damage_reduction_per_layer", per, stacks=layers, note=f"source={st.source_id}"))
        ledger["buckets"]["universal_reduction"] = {"multiplier": round(coerce_float(multipliers.get("universal_reduction", 1.0)), 9), "terms": reduction_terms}

        ledger["buckets"]["toughness_state"] = {
            "multiplier": round(coerce_float(multipliers.get("toughness_state", 1.0)), 9),
            "target_toughness_before_packet": None if target.toughness is None else round(target.toughness, 9),
            "target_is_broken_before_packet": target.is_broken,
            "ignore_toughness_state_multiplier": coerce_bool(packet.get("ignore_toughness_state_multiplier", False), default=False),
        }
        ledger["buckets"]["other"] = {
            "multiplier": round(coerce_float(multipliers.get("other", 1.0)), 9),
            "source": "packet.other_multiplier",
        }
        ledger["formula"] = "base * crit * dmg_bonus * defense * res * damage_taken * universal_reduction * toughness_state * other"
        return ledger

    def resolve_damage_packet(self, packet: dict[str, Any], actor: UnitState, target: UnitState, action: dict[str, Any], events: dict[str, Any]) -> dict[str, Any]:
        packet = self.normalize_damage_packet_schema(packet)
        if "multiplier" not in packet or coerce_float(packet.get("multiplier", 0.0)) == 0.0:
            ref_mult = self.resolve_packet_multiplier_reference(packet, actor)
            if ref_mult is not None:
                packet["multiplier"] = ref_mult
        dmg_ctx_for_element = {"action": action, "packet": packet, "actor_id": actor.id, "actor": actor, "owner_id": actor.flags.get("owner_id"), "target_id": target.id, "target": target}
        element = self.resolve_dynamic_element(packet.get("element", "none"), dmg_ctx_for_element)
        packet["element"] = element
        damage_type = str(packet.get("damage_type", packet.get("type", "direct_damage")) or "direct_damage").lower()
        if damage_type in {"break", "break_damage", "weakness_break"}:
            return self.resolve_break_damage_packet(packet, actor, target, action, events)
        if damage_type in {"super_break", "superbreak", "super_break_damage"}:
            return self.resolve_super_break_damage_packet(packet, actor, target, action, events)
        scaling_stat = packet.get("scaling_stat", "atk")
        multiplier = coerce_float(packet.get("multiplier", 0.0))
        flat_damage = coerce_float(packet.get("flat_damage", 0.0))
        dmg_ctx = {"action": action, "packet": packet, "actor_id": actor.id, "actor": actor, "owner_id": actor.flags.get("owner_id"), "target_id": target.id, "target": target}
        # Use contextual_stat for the scaling stat, not only for Crit stats.
        # Otherwise conditional ATK/HP/DEF bonuses attached to a specific action or
        # packet are silently ignored in damage resolution.
        scaling_value = self.contextual_stat(actor, scaling_stat, dmg_ctx)
        base = scaling_value * multiplier + flat_damage

        crit_info = self.resolve_crit(packet, actor, action, events, dmg_ctx)
        dmg_bonus = self.get_dmg_bonus_multiplier(actor, packet, action, dmg_ctx)
        defense = self.get_def_multiplier(actor, target, packet, dmg_ctx)
        res = self.get_res_multiplier(actor, target, element, dmg_ctx)
        taken = self.get_damage_taken_multiplier(target, packet, action, dmg_ctx)
        reduction = self.get_universal_reduction_multiplier(target, packet, action, dmg_ctx)
        toughness = self.get_toughness_state_multiplier(target, packet)
        other = coerce_float(packet.get("other_multiplier", 1.0))
        multipliers = {
            "dmg_bonus": dmg_bonus,
            "defense": defense,
            "res": res,
            "damage_taken": taken,
            "universal_reduction": reduction,
            "toughness_state": toughness,
            "other": other,
        }
        final = base * crit_info["multiplier"] * dmg_bonus * defense * res * taken * reduction * toughness * other
        final = max(0.0, final)
        toughness_reduction = coerce_float(packet.get("toughness_reduction", 0.0))
        formula_ledger = self.collect_damage_formula_ledger(
            actor,
            target,
            packet,
            action,
            dmg_ctx,
            scaling_stat=str(scaling_stat),
            scaling_value=scaling_value,
            base_damage=base,
            crit_info=crit_info,
            multipliers=multipliers,
        )
        formula_ledger["final_damage"] = round(final, 9)
        return {
            "actor_id": actor.id,
            "target_id": target.id,
            "packet_id": packet.get("id"),
            "element": element,
            "base_damage": base,
            "crit": crit_info,
            "multipliers": multipliers,
            "formula_ledger": formula_ledger,
            "damage": final,
            "toughness_reduction": toughness_reduction,
            "target_defeated": False,
        }

    def contextual_stat(self, unit: UnitState, name: str, ctx: dict[str, Any]) -> float:
        # Damage scaling by HP in HSR uses max HP, not the runtime remaining HP
        # resource. Several model-pack packets use scaling_stat: hp; previously
        # that fell through to stats["hp"] and became 0 for units whose HP is
        # stored as max_hp/hp resources. This made HP-scaling attacks such as
        # Tribbie follow-up calculate as zero.
        if name in {"hp", "max_hp"}:
            return coerce_float(unit.max_hp)
        if name in {"current_hp", "currenthp"}:
            return coerce_float(unit.hp)
        if isinstance(name, str) and "." in name:
            unit_spec, stat_name = name.split(".", 1)
            try:
                uid = self.resolve_special_unit(unit_spec, ctx)
            except Exception:
                uid = unit_spec
            if uid in self.state.units:
                target_unit = self.state.unit(uid)
                if stat_name in {"max_hp", "hp", "shield", "energy", "max_energy"}:
                    return coerce_float(getattr(target_unit, stat_name, 0.0))
                return self.contextual_stat(target_unit, stat_name, {**ctx, "actor_id": uid, "target_id": ctx.get("target_id")})
        """Return a stat with context-specific conditional modifiers.

        This mirrors ``UnitState.get_stat`` for split HSR stats:
          final = base * (1 + pct + contextual_pct) + flat + contextual_add

        Earlier versions applied contextual ``*_pct`` to the already-final stat,
        which over-counted flat stats for split models such as ATK/SPD/HP.
        """
        cond_add = 0.0
        cond_pct = 0.0
        for st in unit.statuses:
            # Unconditional status modifiers are needed here only when we recompute
            # split stats from base/pct/flat below. For non-split stats, unit.get_stat
            # already includes them.
            mods = st.modifiers if isinstance(st.modifiers, dict) else {}
            cms = mods.get("conditional_modifiers", [])
            if not isinstance(cms, list):
                continue
            for cm in cms:
                if self.eval_condition(cm.get("condition", {}), ctx):
                    cm_mods = cm.get("modifiers", {}) or {}
                    cond_add += coerce_float(cm_mods.get(f"{name}_add", 0.0)) * st.stacks
                    cond_pct += coerce_float(cm_mods.get(f"{name}_pct", 0.0)) * st.stacks
        packet = ctx.get("packet", {}) or {}
        cond_add += coerce_float(packet.get(f"{name}_add", 0.0))
        cond_pct += coerce_float(packet.get(f"{name}_pct", 0.0))

        has_split = name in unit.stat_base or name in unit.stat_pct or name in unit.stat_flat
        if has_split:
            base = coerce_float(unit.stat_base.get(name, 0.0))
            flat = coerce_float(unit.stat_flat.get(name, 0.0))
            base_pct = coerce_float(unit.stat_pct.get(name, 0.0))
            status_add = 0.0
            status_pct = 0.0
            for st in unit.statuses:
                mods = st.modifiers if isinstance(st.modifiers, dict) else {}
                status_add += coerce_float(mods.get(f"{name}_add", 0.0)) * st.stacks
                status_pct += coerce_float(mods.get(f"{name}_pct", 0.0)) * st.stacks
            dynamic_add = self.derived_status_add_for_stat(unit, name, ctx)
            return base * (1.0 + base_pct + status_pct + cond_pct) + flat + status_add + cond_add + dynamic_add

        value = unit.get_stat(name)
        dynamic_add = self.derived_status_add_for_stat(unit, name, ctx)
        return value * (1.0 + cond_pct) + cond_add + dynamic_add

    def resolve_crit(self, packet: dict[str, Any], actor: UnitState, action: dict[str, Any], events: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        crit_rate = self.contextual_stat(actor, "crit_rate", ctx)
        crit_dmg = self.contextual_stat(actor, "crit_dmg", ctx)
        if coerce_bool(packet.get("forced_crit", False), default=False):
            return {"is_crit": True, "multiplier": 1 + crit_dmg, "source": "forced", "crit_rate": crit_rate, "crit_dmg": crit_dmg}
        if not coerce_bool(packet.get("can_crit", True), default=True):
            return {"is_crit": False, "multiplier": 1.0, "source": "cannot_crit", "crit_rate": crit_rate, "crit_dmg": crit_dmg}
        key = packet.get("crit_event_id") or f"{action['actor_id']}.{action['id']}.{packet.get('id','damage')}.crit"
        mode = events.get(key, events.get("__crit_mode__", self.settings.get("default_crit_mode", "expected")))
        mode_norm = coerce_comparison_value(mode)
        if mode_norm is True or mode == "crit":
            is_crit = True
            mult = 1 + crit_dmg
        elif mode_norm is False or mode == "noncrit":
            is_crit = False
            mult = 1.0
        elif mode == "expected":
            is_crit = None
            mult = 1 + clamp(crit_rate, 0.0, 1.0) * crit_dmg
        else:
            raise SimulatorError(f"Unknown crit event mode for {key}: {mode}")
        return {"event_id": key, "is_crit": is_crit, "multiplier": mult, "source": mode, "crit_rate": crit_rate, "crit_dmg": crit_dmg}


    def applicable_status_modifiers(self, unit: UnitState, ctx: dict[str, Any]) -> list[tuple[StatusEffect, dict[str, Any]]]:
        """Return base and conditional modifiers from statuses that apply in this context."""
        out: list[tuple[StatusEffect, dict[str, Any]]] = []
        for st in unit.statuses:
            if st.modifiers:
                out.append((st, st.modifiers))
            for cm in st.modifiers.get("conditional_modifiers", []) if isinstance(st.modifiers.get("conditional_modifiers"), list) else []:
                if self.eval_condition(cm.get("condition", {}), ctx):
                    out.append((st, cm.get("modifiers", {})))
        return out

    def get_dmg_bonus_multiplier(self, actor: UnitState, packet: dict[str, Any], action: dict[str, Any], ctx: Optional[dict[str, Any]] = None) -> float:
        tags = set(normalize_str_list(action.get("tags", []))) | set(normalize_str_list(packet.get("tags", [])))
        element = packet.get("element")
        bonus = coerce_float(actor.stats.get("all_dmg_bonus", 0.0))
        # Packet-local damage-bonus additions can be injected by before_damage
        # effects such as modify_damage_packet. Treat these as additive damage
        # bonus terms before returning 1 + bonus.
        bonus += coerce_float(packet.get("dmg_bonus_add", 0.0))
        bonus += coerce_float(packet.get("dmg_bonus_multiplier", 0.0))
        if element:
            bonus += coerce_float(actor.stats.get(f"{element}_dmg_bonus", 0.0))
        # status modifiers: dmg_bonus_add applies to all; dmg_bonus.<tag> applies by tag; dmg_bonus.<element>
        for st, mods in self.applicable_status_modifiers(actor, ctx or {"action": action, "packet": packet}):
            bonus += coerce_float(mods.get("dmg_bonus_add", 0.0)) * st.stacks
            # Enemy statuses such as Titanic Corpus describe a one-status attack
            # enhancement, not a per-stack damage bonus. Keep it separate from
            # dmg_bonus_add to avoid multiplying +20% by 12 layers.
            if st.stacks > 0 and "next_attack_dmg_bonus_add" in mods:
                bonus += coerce_float(mods.get("next_attack_dmg_bonus_add", 0.0))
            sub = mods.get("dmg_bonus", {})
            if isinstance(sub, dict):
                for key, val in sub.items():
                    if key == element or key in tags or key == "all":
                        bonus += coerce_float(val) * st.stacks
        return 1 + bonus

    def get_def_multiplier(self, actor: UnitState, target: UnitState, packet: dict[str, Any], ctx: Optional[dict[str, Any]] = None) -> float:
        if coerce_bool(packet.get("ignore_defense_multiplier", False), default=False):
            return 1.0
        target_def = target.get_stat("defense") or target.get_stat("def")
        def_reduction = 0.0
        def_ignore = coerce_float(packet.get("def_ignore", 0.0))
        for st, mods in self.applicable_status_modifiers(target, ctx or {"packet": packet}):
            def_reduction += coerce_float(mods.get("def_reduction", 0.0)) * st.stacks
        target_def = max(0.0, target_def * (1 - def_reduction - def_ignore))
        return 1 - target_def / (target_def + 200 + 10 * actor.level) if target_def > 0 else 1.0

    def get_res_multiplier(self, actor: UnitState, target: UnitState, element: str, ctx: Optional[dict[str, Any]] = None) -> float:
        target_res = coerce_float(target.res.get(element, target.res.get("all", 0.0)))
        for st, mods in self.applicable_status_modifiers(target, ctx or {}):
            delta = mods.get("resistance_delta", {}) if isinstance(mods.get("resistance_delta", {}), dict) else {}
            target_res += coerce_float(delta.get(element, delta.get("all", 0.0))) * st.stacks
        pen = coerce_float(actor.stats.get(f"{element}_res_pen", actor.stats.get("all_res_pen", 0.0)))
        for st, mods in self.applicable_status_modifiers(actor, ctx or {}):
            pen += coerce_float(mods.get("res_pen", {}).get(element, 0.0)) if isinstance(mods.get("res_pen"), dict) else 0.0
            pen += coerce_float(mods.get("all_res_pen", 0.0))
        return 1 - (target_res - pen)

    def get_damage_taken_multiplier(self, target: UnitState, packet: dict[str, Any], action: dict[str, Any], ctx: Optional[dict[str, Any]] = None) -> float:
        tags = set(normalize_str_list(action.get("tags", []))) | set(normalize_str_list(packet.get("tags", [])))
        element = packet.get("element")
        taken = coerce_float(target.stats.get("damage_taken", 0.0))
        for st, mods in self.applicable_status_modifiers(target, ctx or {"action": action, "packet": packet}):
            taken += coerce_float(mods.get("damage_taken_add", 0.0)) * st.stacks
            sub = mods.get("damage_taken", {})
            if isinstance(sub, dict):
                for key, val in sub.items():
                    if key == element or key in tags or key == "all":
                        taken += coerce_float(val) * st.stacks
        return 1 + taken

    def target_has_modifier_flag(self, unit: UnitState, key: str) -> bool:
        for st in unit.statuses:
            mods = st.modifiers if isinstance(st.modifiers, dict) else {}
            if coerce_bool(mods.get(key, False), default=False):
                return True
        return False

    def iter_status_modifier_payloads(self, unit: UnitState, key: str):
        for st in unit.statuses:
            mods = st.modifiers if isinstance(st.modifiers, dict) else {}
            payload = mods.get(key)
            if payload is not None:
                yield st, payload

    def savage_glory_stacks(self, actor: UnitState) -> int:
        total = 0
        for st in actor.statuses:
            if st.id == "savage_god_glory" or "glory" in {str(t).lower() for t in st.tags}:
                total += max(0, coerce_int(st.stacks, 0))
        return total

    def clear_savage_god_glory_after_action(self, actor: UnitState, ctx: dict[str, Any]) -> None:
        removed = []
        for ally in list(self.state.allies_alive()):
            if any(st.id == "savage_god_glory" or "glory" in {str(t).lower() for t in st.tags} for st in ally.statuses):
                # Remove by id first.  A generated legacy template uses a fixed id;
                # if later data creates aliases, fall back to tag-based pruning.
                if any(st.id == "savage_god_glory" for st in ally.statuses):
                    self.apply_effect({"type": "remove_status", "target": ally.id, "status_id": "savage_god_glory"}, ctx)
                else:
                    for st in list(ally.statuses):
                        if "glory" in {str(t).lower() for t in st.tags}:
                            self.commit_status_remove(
                                ally,
                                st,
                                reason="savage_glory:clear_after_action",
                                ctx=ctx,
                                payload={"actor": actor.id, "removed_status": st.to_json()},
                            )
                    self.state.log_event("enemy_mechanic", f"{actor.id} clears Glory from {ally.id}", {"ally": ally.id, "reason": "savage_god_after_action"})
                removed.append(ally.id)
        if removed:
            self.state.log_event("enemy_mechanic", f"{actor.id} clears all Glory after action", {"removed_from": removed})

    def apply_titanic_corpus_glory_hit(self, actor: UnitState, target: UnitState, ctx: dict[str, Any]) -> None:
        glory = self.savage_glory_stacks(actor)
        if glory <= 0:
            return
        for st, payload in list(self.iter_status_modifier_payloads(target, "titanic_corpus")):
            if not isinstance(payload, dict) or st.stacks <= 0:
                continue
            old = st.stacks
            self.commit_status_stacks(
                target,
                st,
                max(0, old - glory),
                reason="titanic_corpus:glory_hit",
                ctx=ctx,
                payload={"actor": actor.id, "glory_stacks": glory},
            )
            self.state.log_event("enemy_mechanic", f"{actor.id} Glory removes {target.id} Titanic Corpus {old}->{st.stacks}", {"actor": actor.id, "target": target.id, "glory_stacks": glory, "old": old, "new": st.stacks})
            if old > 0 and st.stacks <= 0:
                hp_ratio = coerce_float(payload.get("on_layers_zero_self_damage_max_hp_ratio", 0.0))
                if hp_ratio > EPS:
                    self.apply_effect({"type": "damage_unit", "target": target.id, "amount": target.max_hp * hp_ratio, "element": "imaginary", "ignore_shield": True}, ctx)
                delay_ratio = coerce_float(payload.get("on_layers_zero_action_delay_ratio", 0.0))
                if delay_ratio > EPS:
                    self.apply_effect({"type": "delay_action", "target": target.id, "percent": delay_ratio}, ctx)
                energy_ratio = coerce_float(payload.get("all_allies_energy_restore_max_energy_ratio", 0.0))
                if energy_ratio > EPS:
                    for ally in self.ordered_alive_side_units("ally"):
                        self.apply_effect({"type": "modify_energy", "target": ally.id, "amount": ally.max_energy * energy_ratio}, ctx)

    def handle_enemy_on_hit_mechanics(self, actor: UnitState, target: UnitState, packet: dict[str, Any], result: dict[str, Any], ctx: dict[str, Any]) -> None:
        """Execute generic enemy core-mechanic status hooks after a hit.

        This is the runtime half of enemy harness/core_mechanics lowering.  It is
        intentionally generic: statuses expose modifier payloads such as
        immediate_action_on_hit_by_element or armor_layers; the simulator does
        not special-case a concrete monster id.
        """
        element = str(packet.get("element") or result.get("element") or "").lower()
        if result.get("damage", 0.0) > EPS:
            action_tags = set(normalize_str_list((ctx.get("action") or {}).get("tags", [])))
            packet_tags = set(normalize_str_list(packet.get("tags", [])))
            damage_type = str(packet.get("damage_type", packet.get("type", "")) or "").lower()
            non_attack_tags = {"additional_damage", "zone_additional_damage", "dot", "dot_detotation", "dot_detonation", "effect_damage", "true_damage"}
            is_attack_hit = ("attack" in action_tags or "attack" in packet_tags or "follow_up_attack" in packet_tags or "followup_damage" in packet_tags)
            is_non_attack_damage = bool(non_attack_tags & (action_tags | packet_tags)) or damage_type in {"additional_damage", "zone_additional_damage", "dot", "dot_damage", "true_damage", "effect_damage"}
            # War Armor and similar “after being attacked” counters should only
            # lose stacks on actual attacks. Tribbie/Kafka-style Additional DMG
            # and DoT detonation are damage events but are not attacks, so they
            # must not consume armor layers.
            if is_attack_hit and not is_non_attack_damage:
                action_obj = ctx.get("action") if isinstance(ctx.get("action"), dict) else None
                consumed_targets = action_obj.setdefault("_armor_layer_loss_targets", set()) if action_obj is not None else set()
                if target.id in consumed_targets:
                    if any(isinstance(payload, dict) and coerce_int(payload.get("on_hit_lose_layers", 0), 0) > 0 for _st, payload in self.iter_status_modifier_payloads(target, "armor_layers")):
                        self.state.log_event("enemy_mechanic", f"{target.id} armor layer loss skipped for repeated hit in same attack", {"unit": target.id, "packet_id": packet.get("id")})
                else:
                    did_consume = False
                    for st, payload in list(self.iter_status_modifier_payloads(target, "armor_layers")):
                        if not isinstance(payload, dict):
                            continue
                        lose = coerce_int(payload.get("on_hit_lose_layers", 0), 0)
                        if lose > 0 and st.stacks > 0:
                            old = st.stacks
                            self.commit_status_stacks(
                                target,
                                st,
                                max(0, st.stacks - lose),
                                reason="armor_layers:on_attack_hit",
                                ctx=ctx,
                                payload={"packet_id": packet.get("id"), "lose": lose},
                            )
                            did_consume = True
                            self.state.log_event("enemy_mechanic", f"{target.id}.{st.id} armor layers {old}->{st.stacks}", {"unit": target.id, "status": st.id, "old": old, "new": st.stacks, "reason": "on_attack_hit_once_per_action"})
                    if did_consume and action_obj is not None:
                        consumed_targets.add(target.id)
            elif any(isinstance(payload, dict) and coerce_int(payload.get("on_hit_lose_layers", 0), 0) > 0 for _st, payload in self.iter_status_modifier_payloads(target, "armor_layers")):
                self.state.log_event("enemy_mechanic", f"{target.id} armor layer loss skipped for non-attack damage", {"unit": target.id, "packet_id": packet.get("id"), "damage_type": damage_type, "action_tags": sorted(action_tags), "packet_tags": sorted(packet_tags)})
            if target.flags.get("corresponding_summon") and target.flags.get("corresponding_ally") in self.state.units and target.max_hp > EPS:
                ally = self.state.unit(str(target.flags.get("corresponding_ally")))
                old_ratio = coerce_float(ally.flags.get("max_restorable_hp_ratio", 1.0), 1.0)
                restored_ratio = max(0.0, result.get("damage", 0.0)) / target.max_hp
                new_ratio = min(1.0, old_ratio + restored_ratio)
                self.commit_unit_flag(ally, "max_restorable_hp_ratio", new_ratio, reason="summon:restore_recoverable_hp_cap", ctx=ctx, payload={"summon": target.id, "old_ratio": old_ratio, "restored_ratio": restored_ratio})
                self.state.log_event("enemy_mechanic", f"{ally.id} recoverable HP cap restores via {target.id} {old_ratio}->{new_ratio}", {"ally": ally.id, "summon": target.id, "old_ratio": old_ratio, "new_ratio": new_ratio, "restored_ratio": restored_ratio})
            self.apply_titanic_corpus_glory_hit(actor, target, ctx)
        if result.get("target_defeated") and target.flags.get("owner_hp_consumption_ratio_on_fatal") and target.flags.get("owner_id") in self.state.units:
            owner = self.state.unit(str(target.flags.get("owner_id")))
            ratio = coerce_float(target.flags.get("owner_hp_consumption_ratio_on_fatal"), 0.0)
            amount = owner.max_hp * ratio
            if amount > EPS and owner.alive:
                self.state.log_event("enemy_mechanic", f"{target.id} fatal hit consumes {owner.id} HP", {"summon": target.id, "owner": owner.id, "ratio": ratio, "amount": amount})
                self.apply_hp_loss(owner, amount, {**ctx, "target_id": owner.id, "target": owner}, label="effect_damage", ignore_shield=True)
        for st, payload in list(self.iter_status_modifier_payloads(target, "count_attacks_taken")):
            if not isinstance(payload, dict) or result.get("damage", 0.0) <= EPS:
                continue
            old_count = coerce_int(payload.get("count", 0), 0)
            next_payload = deepcopy(payload)
            next_payload["count"] = old_count + 1
            self.commit_status_modifier(
                target,
                st,
                "count_attacks_taken",
                next_payload,
                reason="count_attacks_taken:on_damage",
                ctx=ctx,
                payload={"damage": result.get("damage"), "old_count": old_count},
            )
            threshold = coerce_int(next_payload.get("threshold", 0), 0)
            self.state.log_event("enemy_mechanic", f"{target.id}.{st.id} attack count {old_count}->{next_payload['count']}", {"unit": target.id, "status": st.id, "threshold": threshold})
            if threshold and next_payload["count"] >= threshold and next_payload.get("action"):
                reset_payload = deepcopy(next_payload)
                reset_payload["count"] = 0
                self.commit_status_modifier(
                    target,
                    st,
                    "count_attacks_taken",
                    reset_payload,
                    reason="count_attacks_taken:threshold_reset",
                    ctx=ctx,
                    payload={"threshold": threshold},
                )
                self.apply_effect({"type": "immediate_action", "actor": target.id, "action": next_payload.get("action"), "target_policy": next_payload.get("target_policy", "first_ally")}, ctx)
        for _st, payload in list(self.iter_status_modifier_payloads(target, "immediate_action_on_hit_by_element")):
            if not isinstance(payload, dict):
                continue
            trigger_element = str(payload.get("element") or payload.get("damage_type") or "").lower()
            if trigger_element and trigger_element != element:
                continue
            action = payload.get("action") or payload.get("action_id")
            if not action:
                continue
            self.state.log_event("enemy_mechanic", f"{target.id} queues immediate action after {element} hit", {"unit": target.id, "element": element, "action": action})
            self.apply_effect({"type": "immediate_action", "actor": target.id, "action": action, "target_policy": payload.get("target_policy", "first_ally")}, ctx)

    def get_universal_reduction_multiplier(self, target: UnitState, packet: dict[str, Any], action: dict[str, Any], ctx: Optional[dict[str, Any]] = None) -> float:
        mult = 1.0
        reductions = []
        if "damage_reduction" in target.stats:
            reductions.append(coerce_float(target.stats["damage_reduction"]))
        for st, mods in self.applicable_status_modifiers(target, ctx or {"action": action, "packet": packet}):
            if "damage_reduction" in mods:
                if isinstance(mods.get("titanic_corpus"), dict):
                    reductions.append(coerce_float(mods["damage_reduction"]))
                else:
                    reductions.append(coerce_float(mods["damage_reduction"]) * st.stacks)
            armor = mods.get("armor_layers") if isinstance(mods.get("armor_layers"), dict) else None
            if armor:
                # Some enemy armor states reduce damage by a fixed amount while
                # at least one layer remains; others are truly per-layer. Keep
                # both semantics explicit so validation cannot silently multiply
                # a fixed reduction by stacks.
                fixed = armor.get("damage_reduction_while_active", None)
                layers = st.stacks if st.stacks is not None else coerce_int(armor.get("layers", 0), 0)
                if fixed is not None and layers > 0:
                    reductions.append(min(0.9, max(0.0, coerce_float(fixed))))
                else:
                    per = coerce_float(armor.get("damage_reduction_per_layer", 0.0))
                    reductions.append(min(0.9, max(0.0, per * layers)))
        for r in reductions:
            mult *= 1 - r
        return mult

    def get_toughness_state_multiplier(self, target: UnitState, packet: dict[str, Any]) -> float:
        if coerce_bool(packet.get("ignore_toughness_state_multiplier", False), default=False):
            return 1.0
        if target.toughness is None:
            return 1.0
        return 1.0 if target.toughness is None or target.is_broken or target.toughness <= 0 else 0.9

    def _resolve_hp_carry_over(self, target: UnitState, explicit: Optional[Any] = None) -> bool:
        """Resolve whether overflow damage carries across HP bars.

        The simulator distinguishes three HP semantics:
        - normal_hp: single pool, no bar transition semantics.
        - segmented_hp: multiple visible segments in one phase; overflow carries by default.
        - phase_hp: each bar is a phase boundary; overflow does not carry by default.

        An explicit packet/effect flag may override this, but enemy templates should
        prefer `hp_model.type` + `hp_model.carry_over_damage` so the semantic is visible.
        """
        if explicit is not None:
            return coerce_bool(explicit)
        if target.hp_carry_over_damage is not None:
            return coerce_bool(target.hp_carry_over_damage)
        return target.hp_model_type == "segmented_hp"

    def hp_bar_index(self, target: UnitState) -> int:
        """Return zero-based current bar index for explicit hp_model.bars data."""
        if target.hp_bars_total <= 0:
            return 0
        return max(0, min(target.hp_bars_total - 1, target.hp_bars_total - target.hp_bars_remaining))

    def hp_bar_max_hp(self, target: UnitState, index: int) -> float:
        """Return max HP for a specific bar, falling back to the unit max_hp."""
        if 0 <= index < len(target.hp_model_bars):
            return coerce_float(target.hp_model_bars[index].get("hp", target.max_hp))
        return target.max_hp

    def hp_bar_on_depleted_effects(self, target: UnitState, index: int) -> list[dict[str, Any]]:
        """Return inline on_depleted effects attached to an explicit hp_model bar."""
        if 0 <= index < len(target.hp_model_bars):
            effects = target.hp_model_bars[index].get("on_depleted", [])
            if isinstance(effects, list):
                return deepcopy(effects)
        return []

    def _apply_hp_damage_to_bars(self, target: UnitState, incoming: float, carry_over_hp_bar_damage: Optional[bool], label: str, ctx: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Apply post-shield HP loss across HP bars.

        v1.4 honors explicit ``hp_model.bars`` data:
        - next bar HP may differ from the previous bar;
        - inline ``on_depleted`` effects attached to a bar are reported so callers
          can apply them at the HP-bar-depletion timing.
        """
        carry_over_hp_bar_damage = self._resolve_hp_carry_over(target, carry_over_hp_bar_damage)
        remaining = max(0.0, incoming)
        hp_bar_depleted = False
        target_defeated = False
        bars_depleted = 0
        phase_damage_locked_until_action_end = False
        old_hp_initial = target.hp
        depleted_bar_events: list[dict[str, Any]] = []

        while remaining > EPS and target.alive:
            if remaining + EPS < target.hp:
                self.commit_unit_hp(
                    target,
                    target.hp - remaining,
                    reason=f"{label}:hp_damage",
                    ctx=ctx,
                    payload={"incoming": incoming, "remaining_before": remaining},
                )
                remaining = 0.0
                break

            # Current bar is depleted.
            depleted_index = self.hp_bar_index(target)
            inline_effects = self.hp_bar_on_depleted_effects(target, depleted_index)
            if inline_effects:
                depleted_bar_events.append({
                    "target_id": target.id,
                    "bar_index": depleted_index,
                    "bar_number": depleted_index + 1,
                    "effects": inline_effects,
                })

            overflow = max(0.0, remaining - target.hp)
            self.commit_unit_hp(
                target,
                0.0,
                reason=f"{label}:hp_bar_depleted",
                ctx=ctx,
                payload={"incoming": incoming, "remaining_before": remaining, "bar_index": depleted_index},
            )
            remaining = overflow

            if target.hp_bars_remaining > 1:
                hp_bar_depleted = True
                bars_depleted += 1
                self.commit_unit_hp_bars_remaining(
                    target,
                    target.hp_bars_remaining - 1,
                    reason=f"{label}:hp_bar_depleted",
                    ctx=ctx,
                    payload={"bar_index_depleted": depleted_index + 1, "incoming": incoming},
                )
                next_index = self.hp_bar_index(target)
                next_bar_hp = self.hp_bar_max_hp(target, next_index)
                self.commit_unit_max_hp(
                    target,
                    next_bar_hp,
                    reason=f"{label}:next_hp_bar_max_hp",
                    ctx=ctx,
                    payload={"bar_index": next_index, "hp_bars_remaining": target.hp_bars_remaining},
                )
                self.commit_unit_hp(
                    target,
                    next_bar_hp,
                    reason=f"{label}:next_hp_bar",
                    ctx=ctx,
                    payload={"bar_index": next_index, "hp_bars_remaining": target.hp_bars_remaining},
                )
                if carry_over_hp_bar_damage:
                    self.state.log_event(
                        "hp_bar",
                        f"{target.id} HP bar depleted by {label}; {target.hp_bars_remaining}/{target.hp_bars_total} bars remain",
                        {
                            "bar_index_depleted": depleted_index + 1,
                            "carry_over": True,
                            "overflow_to_next_bar": remaining,
                            "next_bar_index": next_index + 1,
                            "next_bar_hp_before_overflow": target.hp,
                        },
                    )
                    continue

                # Phase-bar semantics: no overflow into the next bar. Also
                # lock the new bar against later packets from this same action;
                # the phase boundary is a semantic boundary, not only an overflow
                # rule for the current damage packet.
                remaining = 0.0
                phase_damage_locked_until_action_end = True
                self.state.log_event(
                    "hp_bar",
                    f"{target.id} HP bar depleted by {label}; {target.hp_bars_remaining}/{target.hp_bars_total} bars remain",
                    {
                        "bar_index_depleted": depleted_index + 1,
                        "carry_over": False,
                        "overflow_discarded": overflow,
                        "next_bar_index": next_index + 1,
                        "new_hp": target.hp,
                        "new_max_hp": target.max_hp,
                        "phase_damage_locked_until_action_end": True,
                    },
                )
                break

            # Final bar depleted.
            hp_bar_depleted = True
            bars_depleted += 1
            self.commit_unit_alive(
                target,
                False,
                reason=f"{label}:target_defeated",
                ctx=ctx,
                payload={"incoming": incoming, "bar_index": depleted_index},
            )
            target_defeated = True
            remaining = 0.0
            break

        return {
            "hp_bar_depleted": hp_bar_depleted,
            "target_defeated": target_defeated,
            "bars_depleted": bars_depleted,
            "old_hp": old_hp_initial,
            "new_hp": target.hp,
            "hp_bars_remaining": target.hp_bars_remaining,
            "depleted_bar_events": depleted_bar_events,
            "phase_damage_locked_until_action_end": phase_damage_locked_until_action_end,
        }

    def apply_hp_bar_depleted_effects(self, result: dict[str, Any], ctx: dict[str, Any]) -> None:
        """Apply inline effects attached to explicit hp_model.bars[].on_depleted."""
        for event in result.get("depleted_bar_events", []) or []:
            effects = event.get("effects", []) or []
            if not effects:
                continue
            nested_ctx = {**ctx, "hp_bar_event": event, "target_id": event.get("target_id", ctx.get("target_id"))}
            if "target_id" in nested_ctx and nested_ctx["target_id"] in self.state.units:
                nested_ctx["target"] = self.state.unit(nested_ctx["target_id"])
            self.state.log_event(
                "hp_bar_effect",
                f"Apply on_depleted effects for {event.get('target_id')} bar {event.get('bar_number')}",
                {"event": event},
            )
            for eff in effects:
                self.apply_effect(eff, nested_ctx)


    def sync_shared_hp_group_after_loss(self, source: UnitState, old_hp: float, new_hp: float, ctx: dict[str, Any], label: str) -> None:
        """Mirror HP loss within linked enemy bodies such as Lance/Savage God.

        This is deliberately conservative: only units with the same explicit
        shared_hp_group_id are synchronized, and only HP loss is propagated.
        Healing and phase-bar transitions remain owned by the acted-on unit until
        a stronger source contract is compiled.
        """
        group = source.flags.get("shared_hp_group_id") or source.flags.get("shared_hp_with")
        if not group:
            return
        delta = max(0.0, old_hp - new_hp)
        if delta <= EPS:
            return
        for unit in self.state.units.values():
            if unit.id == source.id or not unit.alive:
                continue
            if unit.flags.get("shared_hp_group_id") != group and unit.flags.get("shared_hp_with") != group:
                continue
            partner_old = unit.hp
            self.commit_unit_hp(
                unit,
                unit.hp - delta,
                reason=f"{label}:shared_hp_loss",
                ctx=ctx,
                payload={"group": group, "source": source.id, "delta": delta},
            )
            if unit.hp <= EPS:
                self.commit_unit_alive(unit, False, reason=f"{label}:shared_hp_defeat", ctx=ctx, payload={"group": group, "source": source.id})
            self.state.log_event("shared_hp", f"{source.id} shares {delta:.3f} HP loss with {unit.id}", {"group": group, "source": source.id, "partner": unit.id, "old_hp": partner_old, "new_hp": unit.hp, "label": label})

    def apply_hp_loss(self, target: UnitState, amount: float, ctx: dict[str, Any], label: str = "hp_loss", ignore_shield: bool = False, carry_over_hp_bar_damage: Optional[bool] = None) -> dict[str, Any]:
        """Apply raw HP loss with the same shield / HP-bar semantics as packet damage."""
        old_hp = target.hp
        old_shield = target.shield
        incoming = max(0.0, amount)
        if target.shield > EPS and not ignore_shield:
            absorbed = min(target.shield, incoming)
            self.commit_unit_shield(
                target,
                target.shield - absorbed,
                reason=f"{label}:shield_absorb",
                ctx=ctx,
                payload={"absorbed": absorbed, "incoming_before": incoming},
            )
            incoming -= absorbed
            self.state.log_event(
                "shield",
                f"{target.id} shield absorbs {absorbed:.3f} {label}",
                {"old_shield": old_shield, "new_shield": target.shield, "remaining_damage": incoming},
            )

        bar_result = self._apply_hp_damage_to_bars(target, incoming, carry_over_hp_bar_damage, label, ctx=ctx)
        if bar_result.get("bars_depleted") and target.alive and target.hp_model_type == "phase_hp":
            old_phase = coerce_int(target.flags.get("current_phase", target.flags.get("monster_phase", 1)), 1)
            new_phase = min(target.hp_bars_total, old_phase + coerce_int(bar_result.get("bars_depleted", 1), 1))
            self.commit_unit_flag(target, "current_phase", new_phase, reason="phase_transition:current_phase", ctx=ctx, payload={"old_phase": old_phase, "bars_depleted": bar_result.get("bars_depleted")})
            self.commit_unit_flag(target, "monster_phase", new_phase, reason="phase_transition:monster_phase", ctx=ctx, payload={"old_phase": old_phase, "bars_depleted": bar_result.get("bars_depleted")})
            self.state.log_event("phase_transition", f"{target.id} phase {old_phase}->{new_phase}", {"unit": target.id, "old_phase": old_phase, "new_phase": new_phase, "bars_depleted": bar_result.get("bars_depleted")})
        self.sync_shared_hp_group_after_loss(target, old_hp, target.hp, ctx, label)
        self.state.log_event(
            label,
            f"{target.id} loses {incoming:.3f} HP from {label}",
            {"old_hp": old_hp, "new_hp": target.hp, "raw_amount": amount, "applied_hp_loss": incoming},
        )
        return {
            "target_id": target.id,
            "damage": incoming,
            "hp_bar_depleted": bar_result["hp_bar_depleted"],
            "target_defeated": bar_result["target_defeated"],
            "bars_depleted": bar_result["bars_depleted"],
            "old_hp": old_hp,
            "new_hp": target.hp,
            "hp_bars_remaining": target.hp_bars_remaining,
            "depleted_bar_events": bar_result.get("depleted_bar_events", []),
            "phase_damage_locked_until_action_end": bar_result.get("phase_damage_locked_until_action_end", False),
        }

    def is_elite_or_boss(self, unit: UnitState) -> bool:
        flags = unit.flags if isinstance(unit.flags, dict) else {}
        rank = str(flags.get("monster_rank", flags.get("rank", flags.get("enemy_rank", "")))).lower()
        return coerce_bool(flags.get("is_elite", False), default=False) or coerce_bool(flags.get("is_boss", False), default=False) or rank in {"elite", "boss", "boss_enemy", "elite_enemy"}

    def break_aftermath_damage_result(self, holder: UnitState, st: StatusEffect, payload: dict[str, Any], *, delayed: bool = False) -> dict[str, Any] | None:
        kind = str(payload.get("kind") or "")
        element = str(payload.get("element") or "none").lower()
        source_id = str(payload.get("breaker") or st.source_id or holder.id)
        source = self.state.units.get(source_id, holder)
        level = coerce_int(payload.get("source_level", getattr(source, "level", 80)), 80)
        max_toughness = coerce_float(payload.get("max_toughness", holder.max_toughness or holder.toughness or 0.0))
        elite_or_boss = coerce_bool(payload.get("elite_or_boss", self.is_elite_or_boss(holder)), default=False)
        break_effect = coerce_float(payload.get("break_effect", self.get_break_effect_value(source, {"actor_id": source.id, "target_id": holder.id, "target": holder})))
        stacks = coerce_int(payload.get("stacks", st.stacks), st.stacks)
        base, base_audit = break_dot_base_damage(kind, level=level, max_toughness=max_toughness, max_hp=holder.max_hp, elite_or_boss=elite_or_boss, stacks=stacks)
        if base <= EPS:
            return None
        packet = {
            "id": f"{st.id}.{kind}",
            "element": element,
            "damage_type": "break_delayed_damage" if delayed else "break_dot_damage",
            "can_crit": False,
            "ignore_normal_damage_bonus": True,
        }
        dmg_ctx = {"action": {"id": "break_aftermath", "tags": ["break_aftermath"]}, "packet": packet, "actor_id": source.id, "actor": source, "target_id": holder.id, "target": holder}
        break_bonus = self.get_break_damage_bonus_multiplier(source, packet, dmg_ctx, super_break=False)
        defense = self.get_def_multiplier(source, holder, packet, dmg_ctx)
        res = self.get_res_multiplier(source, holder, element, dmg_ctx)
        taken = self.get_damage_taken_multiplier(holder, packet, dmg_ctx["action"], dmg_ctx)
        reduction = self.get_universal_reduction_multiplier(holder, packet, dmg_ctx["action"], dmg_ctx)
        other = coerce_float(payload.get("other_multiplier", 1.0))
        final = max(0.0, base * (1.0 + break_effect) * break_bonus * defense * res * taken * reduction * other)
        return {
            "actor_id": source.id,
            "target_id": holder.id,
            "packet_id": packet["id"],
            "element": element,
            "damage_type": packet["damage_type"],
            "base_damage": base,
            "crit": {"is_crit": False, "multiplier": 1.0, "source": "weakness_break_aftermath_cannot_crit", "crit_rate": 0.0, "crit_dmg": 0.0},
            "multipliers": {
                "break_effect": 1.0 + break_effect,
                "break_damage_bonus": break_bonus,
                "defense": defense,
                "res": res,
                "damage_taken": taken,
                "universal_reduction": reduction,
                "other": other,
            },
            "break_aftermath_base_audit": base_audit,
            "damage": final,
            "toughness_reduction": 0.0,
            "target_defeated": False,
        }

    def apply_break_aftermath_turn_start(self, actor: UnitState, turn_kind: str) -> None:
        if turn_kind != "regular" or not actor.alive:
            return
        for st in list(actor.statuses):
            mods = st.modifiers if isinstance(st.modifiers, dict) else {}
            dot = mods.get("break_dot") if isinstance(mods.get("break_dot"), dict) else None
            delayed = mods.get("break_delayed_damage") if isinstance(mods.get("break_delayed_damage"), dict) else None
            payload = dot or delayed
            if not payload:
                continue
            if not actor.alive:
                break
            is_delayed = delayed is not None or str(payload.get("kind")) in {"entanglement", "freeze_thaw"}
            result = self.break_aftermath_damage_result(actor, st, payload, delayed=is_delayed)
            if result is None:
                self.state.log_event("break_aftermath_damage_skip", f"{actor.id}.{st.id} break aftermath damage unresolved", {"unit": actor.id, "status": st.id, "payload": payload})
                continue
            dot_ctx = {"packet": {"ignore_shield": False}, "phase_locked_targets": set(), "actor_id": result.get("actor_id"), "target_id": actor.id, "target": actor}
            if result.get("actor_id") in self.state.units:
                dot_ctx["actor"] = self.state.unit(result["actor_id"])
            self.apply_damage_result(result, dot_ctx)
            self.state.log_event("break_aftermath_damage", f"{actor.id}.{st.id} deals {result['damage']:.3f} {result['damage_type']}", result)
            if result.get("target_defeated"):
                source = self.state.units.get(str(result.get("actor_id")))
                if source is not None:
                    self.apply_kill_energy(source, actor, {"id": "break_aftermath", "tags": ["can_trigger_kill_energy"]})
                self.run_triggers("after_defeat_enemy", dot_ctx)
                break

    def action_block_statuses(self, unit: UnitState) -> list[StatusEffect]:
        return [st for st in unit.statuses if isinstance(st.modifiers, dict) and coerce_bool(st.modifiers.get("action_block", False), default=False)]

    def control_statuses(self, unit: UnitState) -> list[StatusEffect]:
        """Return statuses that should interrupt enemy multi-action chains.

        This is intentionally broader than action_block_statuses.  Some control
        effects do not directly express action_block in the current model pack
        yet, but a queued same-turn monster action sequence should not continue
        through freeze/imprisonment/control tags once those statuses are applied.
        """
        out: list[StatusEffect] = []
        for st in unit.statuses:
            tags = {str(t).lower() for t in st.tags}
            mods = st.modifiers if isinstance(st.modifiers, dict) else {}
            if tags.intersection({"control", "cc", "freeze", "frozen", "imprisonment", "stun", "action_block"}):
                out.append(st)
                continue
            if any(coerce_bool(mods.get(k, False), default=False) for k in ("control", "cc", "frozen", "freeze", "imprisonment", "stun", "action_block")):
                out.append(st)
        return out

    def apply_entanglement_hit_stack(self, target: UnitState, result: dict[str, Any], ctx: Optional[dict[str, Any]] = None) -> None:
        if result.get("damage_type") == "break_delayed_damage" or result.get("damage", 0.0) <= EPS:
            return
        for st in target.statuses:
            mods = st.modifiers if isinstance(st.modifiers, dict) else {}
            delayed = mods.get("break_delayed_damage") if isinstance(mods.get("break_delayed_damage"), dict) else None
            if delayed and delayed.get("kind") == "entanglement":
                old = int(st.stacks)
                self.commit_status_stacks(
                    target,
                    st,
                    min(int(st.max_stacks or 5), old + 1),
                    reason="break_aftermath:entanglement_hit_stack",
                    ctx=ctx,
                    payload={"damage_type": result.get("damage_type"), "damage": result.get("damage")},
                )
                delayed_payload = deepcopy(delayed)
                delayed_payload["stacks"] = st.stacks
                self.commit_status_modifier(
                    target,
                    st,
                    "break_delayed_damage",
                    delayed_payload,
                    reason="break_aftermath:entanglement_hit_stack_payload",
                    ctx=ctx,
                    payload={"old_break_delayed_damage": deepcopy(delayed)},
                )
                if st.stacks != old:
                    self.state.log_event("break_aftermath_stack", f"{target.id}.{st.id} entanglement stacks {old}->{st.stacks}", {"unit": target.id, "status": st.id, "old": old, "new": st.stacks})

    def weakness_break_aftermath_status(self, actor: UnitState, target: UnitState, element: str, ctx: dict[str, Any]) -> StatusEffect | None:
        """Return a canonical baseline status for elemental weakness-break aftermath.

        This is a generic, conservative lifecycle layer: it records the correct
        break aftermath category and handles the immediate action-delay/speed
        pieces that are formula-safe.  Exact DoT amount lowering from TBGD can
        later replace the metadata-only dot payloads with generated damage packets.
        """
        e = str(element or "").lower()
        break_payload_base = {
            "breaker": actor.id,
            "source_level": actor.level,
            "break_effect": self.get_break_effect_value(actor, {"actor_id": actor.id, "target_id": target.id, "target": target}),
            "max_toughness": target.max_toughness or target.toughness or 0.0,
            "elite_or_boss": self.is_elite_or_boss(target),
            "formula_status": "executable_baseline",
        }
        common = {
            "source_id": actor.id,
            "duration": {"type": "target_turns", "value": 2, "extra_turn_consumes_duration": False},
            "refresh_duration": True,
            "modifiers": {"weakness_break_aftermath": {"element": e, "breaker": actor.id}},
        }
        if e == "physical":
            raw = {**common, "id": "weakness_break_bleed", "tags": ["break_aftermath", "dot", "bleed", "physical"], "modifiers": {**common["modifiers"], "break_dot": {**break_payload_base, "element": "physical", "kind": "bleed"}}}
        elif e == "fire":
            raw = {**common, "id": "weakness_break_burn", "tags": ["break_aftermath", "dot", "burn", "fire"], "modifiers": {**common["modifiers"], "break_dot": {**break_payload_base, "element": "fire", "kind": "burn"}}}
        elif e in {"lightning", "thunder"}:
            raw = {**common, "id": "weakness_break_shock", "tags": ["break_aftermath", "dot", "shock", "lightning"], "modifiers": {**common["modifiers"], "break_dot": {**break_payload_base, "element": "thunder", "kind": "shock"}}}
        elif e == "wind":
            initial_stacks = 3 if self.is_elite_or_boss(target) else 1
            raw = {**common, "id": "weakness_break_wind_shear", "tags": ["break_aftermath", "dot", "wind_shear", "wind"], "max_stacks": 5, "stacks": initial_stacks, "stack_rule": {"max_stacks": 5, "on_add": "stack", "refresh_duration": True}, "modifiers": {**common["modifiers"], "break_dot": {**break_payload_base, "element": "wind", "kind": "wind_shear", "per_stack": True, "stacks": initial_stacks}}}
        elif e == "ice":
            raw = {**common, "id": "weakness_break_freeze", "tags": ["break_aftermath", "control", "freeze", "ice"], "duration": {"type": "target_turns", "value": 1, "extra_turn_consumes_duration": False}, "modifiers": {**common["modifiers"], "frozen": True, "action_block": True, "break_dot": {**break_payload_base, "element": "ice", "kind": "freeze_thaw"}}}
        elif e == "quantum":
            raw = {**common, "id": "weakness_break_entanglement", "tags": ["break_aftermath", "entanglement", "quantum"], "max_stacks": 5, "stacks": 1, "stack_rule": {"max_stacks": 5, "on_add": "stack", "refresh_duration": True}, "modifiers": {**common["modifiers"], "entanglement": True, "break_delayed_damage": {**break_payload_base, "element": "quantum", "kind": "entanglement", "per_stack": True, "stacks": 1}}}
        elif e == "imaginary":
            raw = {**common, "id": "weakness_break_imprisonment", "tags": ["break_aftermath", "control", "imprisonment", "imaginary"], "duration": {"type": "target_turns", "value": 1, "extra_turn_consumes_duration": False}, "modifiers": {**common["modifiers"], "imprisonment": True, "speed_pct": -0.10}}
        else:
            return None
        return StatusEffect.from_dict(raw)

    def apply_weakness_break_aftermath(self, actor: UnitState, target: UnitState, element: str, ctx: dict[str, Any]) -> None:
        status = self.weakness_break_aftermath_status(actor, target, element, ctx)
        if status is None:
            return
        old_speed = self.effective_speed(target)
        before = next((s for s in target.statuses if s.id == status.id), None)
        after_status = self.merged_status_for_add(before, status)
        self.commit_status_entry(
            target,
            after_status,
            reason="weakness_break_aftermath",
            ctx=ctx,
            payload={"element": str(element).lower(), "incoming_status": status.to_json()},
            change_kind="add" if before is None else "refresh",
        )
        after = next((s for s in target.statuses if s.id == status.id), after_status)
        # Phase 3: settlement 记录 aftermath 状态添加
        self._settle(ctx, "status",
            unit_id=target.id, status_id=status.id, source_id=actor.id,
            action="add", status_type="break_aftermath",
            reason=f"{element} weakness break aftermath",
            record_state_change=False,
        )
        self.recalculate_remaining_av_for_speed_change(target, old_speed, reason="weakness_break_aftermath", ctx=ctx)
        if str(element).lower() == "quantum":
            # Entanglement delays by 20% * (1 + Break Effect).
            self.apply_action_delay(
                target,
                0.20 * (1.0 + self.get_break_effect_value(actor, {"actor_id": actor.id, "target_id": target.id, "target": target})),
                ctx=ctx,
                reason="weakness_break_aftermath:quantum_delay",
            )
        elif str(element).lower() == "imaginary":
            self.apply_action_delay(target, 0.30, ctx=ctx, reason="weakness_break_aftermath:imaginary_delay")
        self.state.log_event(
            "break_aftermath",
            f"Apply {after.id} to {target.id} from {element} weakness break",
            {"actor_id": actor.id, "target_id": target.id, "element": str(element).lower(), "status": after.to_json(), "was_present": before is not None},
        )

    # ── Phase 3: DoT 周期结算 ──

    def resolve_dot_tick(self, unit: UnitState, ctx: dict[str, Any]) -> None:
        """在单位回合开始时，对该单位身上所有 DoT 状态执行周期伤害结算。

        支持两种来源：
        - break_dot / break_delayed_damage（击破 aftermath）
        - dot_damage / damage_over_time / dot（技能施加）
        """
        for st in list(unit.statuses):
            if not st.stacks or st.stacks <= 0:
                continue
            mods = st.modifiers if isinstance(st.modifiers, dict) else {}
            # 击破 aftermath DoT
            dot_cfg = mods.get("break_dot") or mods.get("break_delayed_damage")
            if isinstance(dot_cfg, dict):
                self._tick_one_dot(unit, st, dot_cfg, ctx)
                continue
            # 技能施加 DoT
            for key in ("dot_damage", "damage_over_time", "dot"):
                dot_cfg = mods.get(key)
                if isinstance(dot_cfg, dict):
                    self._tick_skill_dot(unit, st, dot_cfg, ctx)
                    break

    def _tick_one_dot(self, unit: UnitState, st: StatusEffect, dot_cfg: dict[str, Any], ctx: dict[str, Any]) -> None:
        """对单个 DoT 状态执行一次周期伤害结算。"""
        kind = str(dot_cfg.get("kind", ""))
        element = str(dot_cfg.get("element", ""))
        source_level = coerce_int(dot_cfg.get("source_level", 80), 80)
        max_toughness = coerce_float(dot_cfg.get("max_toughness", 0.0))
        break_effect = coerce_float(dot_cfg.get("break_effect", 0.0))
        per_stack = coerce_bool(dot_cfg.get("per_stack", False) if kind == "wind_shear" else False, default=False)

        base, _ = break_dot_base_damage(
            kind, level=source_level, max_toughness=max_toughness,
            max_hp=unit.max_hp,
            stacks=st.stacks, elite_or_boss=self.is_elite_or_boss(unit),
        )
        if per_stack:
            base *= st.stacks

        # 构造合成 attacker 用于 def/res 乘法计算
        breaker_id = str(dot_cfg.get("breaker", ""))
        breaker = self.state.unit(breaker_id) if breaker_id in self.state.units else None
        synth_attacker = breaker if breaker is not None else unit
        # 如果 breaker 不在场，用一个临时 UnitState 带正确 level
        if breaker is None:
            from dataclasses import replace
            synth_attacker = replace(unit, _level_override=source_level)
            if not hasattr(synth_attacker, 'level') or synth_attacker.level != source_level:
                synth_attacker = unit  # fallback
        # 实际 def 公式依赖 attacker.level，用 synth packet 注入 source_level
        synth_packet = {"_dot_source_level": source_level}
        # 直接用内联公式避免 UnitState level 限制
        target_def = unit.get_stat("defense") or unit.get_stat("def") or 0.0
        def_mult = 1.0 - target_def / (target_def + 200.0 + 10.0 * source_level) if target_def > 0.0 else 1.0

        res_mult = self.get_res_pen_mult_for_element(unit, element, ctx)

        # dmg_taken multiplier
        dmg_taken = 1.0 + coerce_float(unit.stats.get("damage_taken", 0.0))
        for s, m in self.applicable_status_modifiers(unit, ctx):
            dmg_taken += coerce_float(m.get("damage_taken_add", 0.0)) * s.stacks
            sub_dt = m.get("damage_taken", {})
            if isinstance(sub_dt, dict):
                for k, v in sub_dt.items():
                    if k == element or k == "all":
                        dmg_taken += coerce_float(v) * s.stacks

        final = max(0.0, base * (1.0 + break_effect) * def_mult * res_mult * dmg_taken)

        # 应用伤害：护盾 → HP
        shield_absorbed = 0.0
        hp_loss = 0.0
        remaining = final
        if unit.shield > EPS:
            absorbed = min(unit.shield, remaining)
            self.commit_unit_shield(
                unit,
                unit.shield - absorbed,
                reason=f"dot:{kind}:shield_absorb",
                ctx=ctx,
                payload={"absorbed": absorbed, "incoming_before": remaining, "status_id": st.id},
            )
            remaining -= absorbed
            shield_absorbed = absorbed
        if remaining > EPS and unit.alive:
            hp_loss = min(unit.hp, remaining)
            self.commit_unit_hp(
                unit,
                unit.hp - hp_loss,
                reason=f"dot:{kind}:hp_loss",
                ctx=ctx,
                payload={"hp_loss": hp_loss, "incoming_before": remaining, "status_id": st.id},
            )
            self._settle(ctx, "hp",
                unit_id=unit.id, delta=-hp_loss, reason=f"DoT {kind}",
                old_value=unit.hp + hp_loss, new_value=unit.hp,
                record_state_change=False,
            )

        self._settle(ctx, "dot",
            unit_id=unit.id, source_status=st.id, element=element,
            kind=kind, base_damage=base, per_stack=per_stack, stacks=int(st.stacks),
            break_effect=1.0 + break_effect, def_mult=def_mult,
            res_mult=res_mult, dmg_taken_mult=dmg_taken,
            final_damage=final, damage_applied=final,
            shield_absorbed=shield_absorbed, hp_loss=hp_loss,
        )

    def _tick_skill_dot(self, unit: UnitState, st: StatusEffect, dot_cfg: dict[str, Any], ctx: dict[str, Any]) -> None:
        """对技能施加的 DoT 状态执行一次周期伤害结算。

        dot_cfg 结构：{flat_damage/amount, element, source_id, ...}
        与 break aftermath 不同，技能 DoT 使用预计算的 flat_damage。
        """
        amount = coerce_float(dot_cfg.get("flat_damage", dot_cfg.get("amount", dot_cfg.get("damage", 0.0))))
        if "target_max_hp_pct" in dot_cfg:
            amount += unit.max_hp * coerce_float(dot_cfg.get("target_max_hp_pct", 0.0))
        if amount <= EPS:
            return

        element = str(dot_cfg.get("element", "none") or "none").lower()
        kind = str(dot_cfg.get("kind", "skill_dot"))
        per_stack = coerce_bool(dot_cfg.get("per_stack", False), default=False)
        stacks = int(st.stacks)

        # 应用伤害：护盾 → HP
        shield_absorbed = 0.0
        hp_loss = 0.0
        remaining = amount
        if unit.shield > EPS:
            absorbed = min(unit.shield, remaining)
            self.commit_unit_shield(
                unit,
                unit.shield - absorbed,
                reason=f"dot:{kind}:shield_absorb",
                ctx=ctx,
                payload={"absorbed": absorbed, "incoming_before": remaining, "status_id": st.id},
            )
            remaining -= absorbed
            shield_absorbed = absorbed
        if remaining > EPS and unit.alive:
            hp_loss = min(unit.hp, remaining)
            self.commit_unit_hp(
                unit,
                unit.hp - hp_loss,
                reason=f"dot:{kind}:hp_loss",
                ctx=ctx,
                payload={"hp_loss": hp_loss, "incoming_before": remaining, "status_id": st.id},
            )
            self._settle(ctx, "hp",
                unit_id=unit.id, delta=-hp_loss, reason=f"DoT {kind}",
                old_value=unit.hp + hp_loss, new_value=unit.hp,
                record_state_change=False,
            )

        self._settle(ctx, "dot",
            unit_id=unit.id, source_status=st.id, element=element,
            kind=kind, base_damage=amount, per_stack=per_stack, stacks=stacks,
            break_effect=1.0, def_mult=1.0, res_mult=1.0, dmg_taken_mult=1.0,
            final_damage=amount, damage_applied=amount,
            shield_absorbed=shield_absorbed, hp_loss=hp_loss,
        )

    def get_res_pen_mult_for_element(self, target: UnitState, element: str, ctx: Optional[dict[str, Any]] = None) -> float:
        """计算目标对特定元素的抗性因子（不考虑攻击者穿透）。"""
        target_res = coerce_float(target.res.get(element, target.res.get("all", 0.0)))
        for st, mods in self.applicable_status_modifiers(target, ctx or {}):
            delta = mods.get("resistance_delta", {})
            if isinstance(delta, dict):
                target_res += coerce_float(delta.get(element, delta.get("all", 0.0))) * st.stacks
        return 1.0 - target_res

    def apply_damage_result(self, result: dict[str, Any], ctx: dict[str, Any]) -> None:
        target = self.state.unit(result["target_id"])
        actor = self.state.units.get(str(result.get("actor_id"))) if result.get("actor_id") is not None else None
        was_alive_before_damage = bool(target.alive)
        old_hp = target.hp
        old_shield = target.shield
        shield_absorbed = 0.0
        incoming = max(0.0, result["damage"])
        if not was_alive_before_damage:
            result["target_already_defeated_before_packet"] = True
            # Primary multi-hit actions in HSR still finish their own hit window:
            # later hits are logged at full numeric damage and can be counted for
            # action-local damage totals, but they must not create a second defeat,
            # hit-taken energy, toughness break, or downstream derived-damage window.

        # Simple shield layer: shield absorbs HP damage before HP unless explicitly ignored.
        if was_alive_before_damage and target.shield > EPS and not coerce_bool(ctx.get("packet", {}).get("ignore_shield", False), default=False):
            absorbed = min(target.shield, incoming)
            self.commit_unit_shield(
                target,
                target.shield - absorbed,
                reason="damage:shield_absorb",
                ctx=ctx,
                payload={"absorbed": absorbed, "incoming_before": incoming},
            )
            incoming -= absorbed
            shield_absorbed = absorbed
            self.state.log_event(
                "shield",
                f"{target.id} shield absorbs {absorbed:.3f}",
                {"old_shield": old_shield, "new_shield": target.shield, "remaining_damage": incoming},
            )
            # Phase 2: 护盾吸收记录
            self._settle(ctx, "shield",
                unit_id=target.id, delta=-absorbed,
                old_value=old_shield, new_value=target.shield,
                reason=f"伤害吸收: {ctx.get('action', {}).get('id', ctx.get('actor_id', '?'))}",
                record_state_change=False,
            )

        packet = ctx.get("packet", {})
        carry = packet.get("carry_over_hp_bar_damage", packet.get("carry_over_damage", None))
        bar_result = self._apply_hp_damage_to_bars(target, incoming, carry, "damage", ctx=ctx) if was_alive_before_damage else {
            "hp_bar_depleted": False,
            "target_defeated": False,
            "bars_depleted": 0,
            "old_hp": old_hp,
            "new_hp": target.hp,
            "hp_bars_remaining": target.hp_bars_remaining,
            "depleted_bar_events": [],
            "phase_damage_locked_until_action_end": False,
        }
        result["hp_bar_depleted"] = bar_result["hp_bar_depleted"]
        result["target_defeated"] = bar_result["target_defeated"]
        result["bars_depleted"] = bar_result["bars_depleted"]
        result["hp_bars_remaining"] = target.hp_bars_remaining
        result["depleted_bar_events"] = bar_result.get("depleted_bar_events", [])
        result["phase_damage_locked_until_action_end"] = bar_result.get("phase_damage_locked_until_action_end", False)
        if bar_result.get("bars_depleted") and target.alive and target.hp_model_type == "phase_hp":
            old_phase = coerce_int(target.flags.get("current_phase", target.flags.get("monster_phase", 1)), 1)
            new_phase = min(target.hp_bars_total, old_phase + coerce_int(bar_result.get("bars_depleted", 1), 1))
            self.commit_unit_flag(target, "current_phase", new_phase, reason="damage:phase_transition:current_phase", ctx=ctx, payload={"old_phase": old_phase, "bars_depleted": bar_result.get("bars_depleted")})
            self.commit_unit_flag(target, "monster_phase", new_phase, reason="damage:phase_transition:monster_phase", ctx=ctx, payload={"old_phase": old_phase, "bars_depleted": bar_result.get("bars_depleted")})
            self.state.log_event("phase_transition", f"{target.id} phase {old_phase}->{new_phase}", {"unit": target.id, "old_phase": old_phase, "new_phase": new_phase, "bars_depleted": bar_result.get("bars_depleted")})

        self.state.log_event(
            "damage",
            f"{result['actor_id']} deals {result['damage']:.3f} {result['element']} damage to {target.id}",
            {"old_hp": old_hp, "new_hp": target.hp, "old_shield": old_shield, "new_shield": target.shield, **result},
        )
        # Phase 2: HP 变化记录 + 修复伤害记录的吸收值
        hp_delta = target.hp - old_hp
        if abs(hp_delta) > EPS and was_alive_before_damage:
            self._settle(ctx, "hp",
                unit_id=target.id, delta=hp_delta,
                old_value=old_hp, new_value=target.hp, max_hp=target.max_hp,
                reason=f"受到伤害: {ctx.get('action', {}).get('id', ctx.get('actor_id', '?'))}",
                record_state_change=False,
            )
        # 回填伤害记录的 shield_absorbed 和 applied_damage
        stl = self._settlement(ctx)
        if stl is not None and stl.damage_records:
            last = stl.damage_records[-1]
            last.shield_absorbed = shield_absorbed
            last.applied_damage = max(0.0, abs(hp_delta))
        if result.get("bars_depleted") and target.alive and target.flags.get("phase_transition_immediate_action"):
            action_id = target.flags.get("phase_transition_immediate_action")
            if action_id is True:
                action_id = self.default_probe_action_id(target) or next(iter(target.action_defs), None)
            if action_id:
                self.state.log_event("enemy_mechanic", f"{target.id} phase transition queues immediate action", {"action": action_id, "bars_depleted": result.get("bars_depleted")})
                self.apply_effect({"type": "immediate_action", "actor": target.id, "action": action_id, "target_policy": "first_ally"}, ctx)

        # Toughness reduction after HP damage in prototype; configurable later.
        tr = result.get("toughness_reduction", 0.0)
        packet = ctx.get("packet", {})
        if tr and not result.get("target_already_defeated_before_packet") and target.toughness is not None and target.alive:
            can_reduce = coerce_bool(packet.get("ignore_weakness_for_toughness", False), default=False) or packet.get("element") in target.weaknesses
            if can_reduce and target.toughness > 0:
                if self.target_has_modifier_flag(target, "toughness_lock"):
                    self.state.log_event("toughness_lock", f"{target.id} toughness reduction blocked", {"attempted_delta": -tr, "element": packet.get("element")})
                else:
                    old_t = target.toughness
                    self.commit_unit_toughness(
                        target,
                        target.toughness - tr,
                        reason="damage:toughness_reduction",
                        ctx=ctx,
                        payload={"element": packet.get("element"), "toughness_reduction": tr, "packet_id": packet.get("id")},
                    )
                    self.state.log_event("toughness", f"{target.id} toughness {old_t:.3f} -> {target.toughness:.3f}", {"delta": -tr})
                    if old_t > 0 and target.toughness <= 0:
                        self.commit_unit_is_broken(
                            target,
                            True,
                            reason="damage:weakness_break",
                            ctx=ctx,
                            payload={"actor_id": result.get("actor_id"), "element": packet.get("element")},
                        )
                        self.state.log_event("break", f"{target.id} is weakness broken", {"actor_id": result.get("actor_id"), "target_id": target.id, "element": packet.get("element")})
                        # Phase 3: 击破伤害计算与应用
                        break_element = str(packet.get("element", "none") or "none").lower()
                        break_actor = self.state.unit(result["actor_id"]) if result.get("actor_id") in self.state.units else None
                        if break_actor is not None:
                            break_base = break_base_damage(break_actor.level)
                            break_elem_mult = element_break_multiplier(break_element)
                            break_toughness_mult = max_toughness_multiplier(target.max_toughness or target.toughness or 0.0)
                            break_be = self.get_break_effect_value(break_actor, ctx)
                            break_final = max(0.0, break_base * break_elem_mult * break_toughness_mult * (1.0 + break_be))
                            # 应用击破伤害：护盾 → HP
                            break_shield_absorbed = 0.0
                            break_hp_loss = 0.0
                            break_remaining = break_final
                            if target.shield > EPS:
                                absorbed = min(target.shield, break_remaining)
                                self.commit_unit_shield(
                                    target,
                                    target.shield - absorbed,
                                    reason="break_damage:shield_absorb",
                                    ctx=ctx,
                                    payload={"absorbed": absorbed, "incoming_before": break_remaining},
                                )
                                break_remaining -= absorbed
                                break_shield_absorbed = absorbed
                            if break_remaining > EPS and target.alive:
                                break_hp_loss = min(target.hp, break_remaining)
                                self.commit_unit_hp(
                                    target,
                                    target.hp - break_hp_loss,
                                    reason="break_damage:hp_loss",
                                    ctx=ctx,
                                    payload={"hp_loss": break_hp_loss, "incoming_before": break_remaining},
                                )
                                self._settle(ctx, "hp",
                                    unit_id=target.id, delta=-break_hp_loss, reason="击破伤害",
                                    old_value=target.hp + break_hp_loss, new_value=target.hp,
                                    record_state_change=False,
                                )
                            # Phase 3: 结算记录
                            self._settle(ctx, "break",
                                actor_id=result.get("actor_id"), target_id=target.id,
                                element=break_element, base_break_damage=break_base,
                                element_mult=break_elem_mult, toughness_mult=break_toughness_mult,
                                break_effect=1.0 + break_be, final_break_damage=break_final,
                                damage_applied=break_final, shield_absorbed=break_shield_absorbed,
                                hp_loss=break_hp_loss,
                            )
                        # Phase 3: 韧性记录
                        self._settle(ctx, "toughness",
                            unit_id=target.id, old_value=old_t, new_value=target.toughness,
                            delta=-tr, is_break=True, element=break_element,
                            reason=f"破韧: {result.get('actor_id','?')} {break_element}",
                            record_state_change=False,
                        )
                        self.handle_armor_break_mechanics(actor if actor else None, target, packet, result, ctx)
                        if break_actor is not None:
                            self.apply_weakness_break_aftermath(break_actor, target, packet.get("element"), ctx)
                    else:
                        # Phase 3: 非破韧韧性扣减记录
                        self._settle(ctx, "toughness",
                            unit_id=target.id, old_value=old_t, new_value=target.toughness,
                            delta=-tr, is_break=False,
                            element=str(packet.get("element", "") or ""),
                            record_state_change=False,
                        )

        if actor is not None:
            # Phase 4: 超击破——目标已破韧时，每次伤害附带超击破伤害
            if target.is_broken and was_alive_before_damage and result.get("damage", 0) > EPS:
                damage_type = str(result.get("damage_type", "")).lower()
                # 排除击破/超击破/DoT 自身，避免无限递归
                skip_types = {"break_damage", "super_break_damage", "dot_damage", "dot", "effect_damage"}
                if damage_type not in skip_types:
                    sb_result = self.resolve_super_break_damage_packet(
                        packet, actor, target, ctx.get("action", {}), ctx.get("events", {})
                    )
                    sb_damage = sb_result.get("damage", 0.0)
                    if sb_damage > EPS:
                        sb_shield_absorbed = 0.0
                        sb_hp_loss = 0.0
                        sb_remaining = sb_damage
                        if target.shield > EPS:
                            absorbed = min(target.shield, sb_remaining)
                            self.commit_unit_shield(
                                target,
                                target.shield - absorbed,
                                reason="super_break:shield_absorb",
                                ctx=ctx,
                                payload={"absorbed": absorbed, "incoming_before": sb_remaining},
                            )
                            sb_remaining -= absorbed
                            sb_shield_absorbed = absorbed
                        if sb_remaining > EPS and target.alive:
                            sb_hp_loss = min(target.hp, sb_remaining)
                            self.commit_unit_hp(
                                target,
                                target.hp - sb_hp_loss,
                                reason="super_break:hp_loss",
                                ctx=ctx,
                                payload={"hp_loss": sb_hp_loss, "incoming_before": sb_remaining},
                            )
                            self._settle(ctx, "hp",
                                unit_id=target.id, delta=-sb_hp_loss, reason="超击破伤害",
                                old_value=target.hp + sb_hp_loss, new_value=target.hp,
                                record_state_change=False,
                            )
                        self._settle(ctx, "super_break",
                            actor_id=actor.id, target_id=target.id,
                            element=sb_result.get("element", ""),
                            base_damage=sb_result.get("base_damage", 0.0),
                            toughness_reduction=coerce_float(packet.get("toughness_reduction", 0.0)),
                            toughness_mult=sb_result.get("multipliers", {}).get("super_break_toughness", 1.0),
                            break_effect=sb_result.get("multipliers", {}).get("break_effect", 1.0),
                            super_break_bonus_mult=sb_result.get("multipliers", {}).get("super_break_damage_bonus", 1.0),
                            def_mult=sb_result.get("multipliers", {}).get("defense", 1.0),
                            res_mult=sb_result.get("multipliers", {}).get("res", 1.0),
                            dmg_taken_mult=sb_result.get("multipliers", {}).get("damage_taken", 1.0),
                            final_damage=sb_damage, damage_applied=sb_damage,
                            shield_absorbed=sb_shield_absorbed, hp_loss=sb_hp_loss,
                        )
            self.handle_enemy_on_hit_mechanics(actor, target, packet, result, ctx)

    def energy_regeneration_rate(self, actor: UnitState) -> float:
        """Return HSR energy regeneration rate as a multiplier.

        Accepted input conventions:
        - stats.energy_regeneration_rate = 1.194 for +19.4% ERR
        - stats.err_bonus = 0.194 for +19.4% ERR
        - stats.err = 0.194 or 1.194; values below 1 are treated as bonus,
          values >= 1 as an already-formed multiplier.
        """
        val = actor.get_stat("energy_regeneration_rate")
        if val > EPS:
            return val
        bonus = actor.get_stat("err_bonus")
        if abs(bonus) > EPS:
            return 1.0 + bonus
        err = actor.get_stat("err")
        if err > EPS:
            base = 1.0 + err if err < 1.0 else err
        else:
            base = 1.0
        bonus_from_status = 0.0
        for st, mods in self.applicable_status_modifiers(actor, {"actor_id": actor.id, "actor": actor}):
            bonus_from_status += coerce_float(mods.get("err_bonus_add", 0.0)) * st.stacks
            bonus_from_status += coerce_float(mods.get("energy_regeneration_rate_add", 0.0)) * st.stacks
        return base + bonus_from_status

    # ---------- resources ----------
    def normalize_energy_source_amount(self, source: dict[str, Any], default_affected_by_err: bool = True) -> dict[str, Any]:
        source = deepcopy(source or {})
        has_explicit_energy = any(
            key in source
            for key in ("base", "base_energy_gain", "fixed", "fixed_energy_gain_not_affected_by_err")
        )
        if "amount" in source and not has_explicit_energy:
            affected = coerce_bool(source.get("affected_by_err", default_affected_by_err), default=default_affected_by_err)
            if affected:
                source["base"] = coerce_float(source.get("amount", 0.0))
            else:
                source["fixed"] = coerce_float(source.get("amount", 0.0))
            source["affected_by_err"] = affected
        return source

    def apply_energy_source(self, unit: UnitState, source: dict[str, Any], label: str, default_affected_by_err: bool = True, ctx: dict[str, Any] | None = None) -> float:
        """Apply a generic HSR energy source to a unit and return actual gain.

        Source syntax accepts both short and explicit names:
          base / base_energy_gain: energy affected by ERR when affected_by_err is true
          fixed / fixed_energy_gain_not_affected_by_err: energy not affected by ERR
          amount: shorthand converted to base or fixed using affected_by_err
          affected_by_err: default true for normal action/hit/kill sources

        This helper is intentionally generic so hit-taken energy, kill energy,
        action energy, light cone energy and scripted enemy mechanics can share
        one path.
        """
        if unit.max_energy <= EPS:
            return 0.0
        source = self.normalize_energy_source_amount(source, default_affected_by_err=default_affected_by_err)
        base = coerce_float(source.get("base", source.get("base_energy_gain", 0.0)))
        fixed = coerce_float(source.get("fixed", source.get("fixed_energy_gain_not_affected_by_err", 0.0)))
        if not base and not fixed:
            return 0.0
        affected = coerce_bool(source.get("affected_by_err", default_affected_by_err), default=default_affected_by_err)
        err = self.energy_regeneration_rate(unit)
        gain = base * (err if affected else 1.0) + fixed
        old = unit.energy
        self.commit_unit_energy(
            unit,
            unit.energy + gain,
            reason=f"energy:{label}",
            ctx=ctx,
            payload={"gain": gain, "source": deepcopy(source), "affected_by_err": affected},
        )
        self.state.log_event("resource", f"{unit.id} gains {gain:.3f} energy from {label}", {"old": old, "new": unit.energy, "gain": gain, "source": source})
        # Phase 2: 能量获取记录
        self._settle(ctx or {}, "energy",
            unit_id=unit.id, delta=gain, old_value=old, new_value=unit.energy,
            max_energy=unit.max_energy, source_type=ENERGY_SOURCE_EFFECT if "effect:" in label else ENERGY_SOURCE_ACTION,
            source_detail=label, affected_by_err=affected, record_state_change=False,
        )
        return gain

    def energy_gain_timing(self, action: dict[str, Any]) -> str:
        eg = action.get("energy_gain", {}) or {}
        return str(eg.get("timing", action.get("energy_gain_timing", "action_end")))

    def split_energy_source(self, source: dict[str, Any], divisor: int) -> dict[str, Any]:
        divisor = max(1, int(divisor))
        out = deepcopy(source or {})
        for key in ("base", "base_energy_gain", "fixed", "fixed_energy_gain_not_affected_by_err", "amount"):
            if key in out and out[key] is not None:
                out[key] = coerce_float(out[key]) / divisor
        return out

    def packet_actor_energy_source(self, action: dict[str, Any], packet: dict[str, Any], packet_count: int) -> dict[str, Any]:
        # Packet-level definitions are already per packet. Action-level timing:
        # per_packet/per_hit splits the total action energy across damage packets,
        # allowing mid-action full-energy checks while preserving total action energy.
        if packet.get("actor_energy_gain"):
            return deepcopy(packet["actor_energy_gain"])
        if packet.get("packet_energy_gain"):
            return deepcopy(packet["packet_energy_gain"])
        timing = self.energy_gain_timing(action)
        if timing in {"per_packet", "per_hit", "split_by_packet", "split_by_hit"}:
            return self.split_energy_source(action.get("energy_gain", {}) or {}, packet_count)
        return {}

    def apply_packet_actor_energy_gain(self, actor: UnitState, action: dict[str, Any], packet: dict[str, Any], packet_count: int, ctx: dict[str, Any] | None = None) -> None:
        source = self.packet_actor_energy_source(action, packet, packet_count)
        if source:
            self.apply_energy_source(actor, source, f"packet:{action.get('id')}.{packet.get('id')}", default_affected_by_err=True, ctx=ctx)

    def apply_action_energy_gain(self, actor: UnitState, action: dict[str, Any], ctx: dict[str, Any] | None = None) -> None:
        # If action energy is explicitly split across packets, do not grant it
        # again at action end. Packet-level actor_energy_gain does not suppress
        # normal action-end energy unless the action author sets timing=per_packet.
        if self.energy_gain_timing(action) in {"per_packet", "per_hit", "split_by_packet", "split_by_hit"}:
            return
        eg = action.get("energy_gain", {}) or {}
        self.apply_energy_source(actor, eg, f"action:{action.get('id')}", default_affected_by_err=True, ctx=ctx)

    def apply_hit_taken_energy(self, target: UnitState, packet: dict[str, Any], action: dict[str, Any], result: dict[str, Any], ctx: dict[str, Any] | None = None) -> None:
        """Apply configurable energy to a target after it is hit.

        The simulator does not hard-code an HSR-wide hit energy amount because
        enemy/action data may supply different hit-energy parameters. Instead it
        supports action- or packet-level definitions:
          target_energy_gain / hit_taken_energy: {base: 10, affected_by_err: true}

        Packet-level values override action-level values. By default, defeated
        targets do not receive hit-taken energy unless grant_if_defeated=true.
        """
        source = packet.get("target_energy_gain") or packet.get("hit_taken_energy") or action.get("target_energy_gain") or action.get("hit_taken_energy")
        if not source:
            return
        if (result.get("target_defeated") or result.get("target_already_defeated_before_packet")) and not coerce_bool(source.get("grant_if_defeated", False), default=False):
            self.state.log_event("resource_skip", f"{target.id} hit-taken energy skipped because target was defeated")
            return
        self.apply_energy_source(target, source, f"hit_taken:{action.get('id')}.{packet.get('id')}", default_affected_by_err=True, ctx=ctx)

    def apply_kill_energy(self, actor: UnitState, target: UnitState, action: dict[str, Any], ctx: dict[str, Any] | None = None) -> None:
        tags = set(normalize_str_list(action.get("tags", [])))
        if "can_trigger_kill_energy" not in tags:
            return
        source = {
            "base": coerce_float(self.settings.get("kill_energy_base", 10.0)),
            "affected_by_err": coerce_bool(self.settings.get("kill_energy_affected_by_err", True), default=True),
        }
        self.apply_energy_source(actor, source, f"kill:{target.id}", default_affected_by_err=True, ctx=ctx)

    def note_action_defeat(self, target_id: str, source_id: str | None, damage_kind: str, ctx: Optional[dict[str, Any]] = None) -> None:
        """Record who actually killed a target inside the current action window.

        Primary action packets may still finish their own action-resolution loop, but
        derived damage sources (additional damage, true damage, DoT detonation,
        delayed trigger damage) must not keep damaging an already defeated target.
        This action-local record lets those derived effects stop at death while
        preserving correct kill credit for the damage source that actually killed.
        """
        if not ctx:
            return
        defeated = ctx.setdefault("defeated_targets_this_action", set())
        if isinstance(defeated, set):
            defeated.add(str(target_id))
        credits = ctx.setdefault("defeat_credits_this_action", {})
        if isinstance(credits, dict):
            credits[str(target_id)] = {"source_id": source_id, "damage_kind": damage_kind}

    def derived_damage_live_targets(self, targets: list[str], ctx: dict[str, Any], *, effect_name: str) -> list[str]:
        """Return targets still eligible for non-primary/derived damage.

        Derived damage is death-stopping: if the primary attack, an earlier
        additional-damage tick, or an earlier DoT tick already defeated the target
        in this action/effect window, later derived sources skip it instead of
        corpse-whipping.
        """
        defeated = ctx.get("defeated_targets_this_action")
        defeated_set = {str(x) for x in defeated} if isinstance(defeated, set) else set()
        out: list[str] = []
        for tid in targets:
            tid_s = str(tid)
            if tid_s in defeated_set:
                self.state.log_event("derived_damage_skip", f"{effect_name} skipped {tid_s}: target already defeated in this action", {"target": tid_s, "effect": effect_name, "reason": "already_defeated_this_action"})
                continue
            if tid_s not in self.state.units or not self.state.unit(tid_s).alive:
                self.state.log_event("derived_damage_skip", f"{effect_name} skipped {tid_s}: target is dead or missing", {"target": tid_s, "effect": effect_name, "reason": "not_alive"})
                continue
            out.append(tid_s)
        return out

    def dot_source_actor(self, holder: UnitState, status: StatusEffect, payload: dict[str, Any]) -> UnitState | None:
        source_id = str(payload.get("source_id") or payload.get("owner_id") or payload.get("applier") or payload.get("breaker") or status.source_id or "")
        return self.state.units.get(source_id) if source_id else None

    def dot_damage_result_for_status(self, holder: UnitState, status: StatusEffect, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Build a conservative damage result for a normal/break DoT status.

        Break DoT/delayed damage uses the existing break-aftershock formula.
        Generic DoT payloads may provide flat_damage/amount and source_id; this
        supports Kafka-style immediate detonation tests and later TBGD lowering.
        """
        if not holder.alive:
            return None
        if payload.get("kind") in {"bleed", "burn", "shock", "wind_shear", "freeze_thaw", "entanglement"} or payload.get("formula_status") == "executable_baseline":
            delayed = str(payload.get("kind")) in {"entanglement", "freeze_thaw"} or coerce_bool(payload.get("delayed", False), default=False)
            return self.break_aftermath_damage_result(holder, status, payload, delayed=delayed)
        source_actor = self.dot_source_actor(holder, status, payload)
        source_id = source_actor.id if source_actor is not None else str(status.source_id or payload.get("source_id") or holder.id)
        amount = coerce_float(payload.get("flat_damage", payload.get("amount", payload.get("damage", 0.0))))
        if "target_max_hp_pct" in payload:
            amount += holder.max_hp * coerce_float(payload.get("target_max_hp_pct", 0.0))
        if amount <= EPS:
            return None
        return {
            "actor_id": source_id,
            "target_id": holder.id,
            "packet_id": payload.get("id", status.id),
            "element": payload.get("element", "none"),
            "damage_type": payload.get("damage_type", "dot_damage"),
            "damage": amount,
            "toughness_reduction": 0.0,
            "target_defeated": False,
        }

    def detonatable_dot_payloads(self, target: UnitState, *, include_break_dot: bool = True) -> list[tuple[StatusEffect, dict[str, Any]]]:
        out: list[tuple[StatusEffect, dict[str, Any]]] = []
        for st in list(target.statuses):
            mods = st.modifiers if isinstance(st.modifiers, dict) else {}
            for key in ("dot_damage", "damage_over_time", "dot"):
                if isinstance(mods.get(key), dict):
                    payload = deepcopy(mods[key])
                    payload.setdefault("source_id", st.source_id)
                    payload.setdefault("id", st.id)
                    out.append((st, payload))
            if include_break_dot:
                for key in ("break_dot", "break_delayed_damage"):
                    if isinstance(mods.get(key), dict):
                        payload = deepcopy(mods[key])
                        payload.setdefault("source_id", st.source_id)
                        payload.setdefault("id", st.id)
                        out.append((st, payload))
        return out

    # ---------- triggers / effects ----------
    def condition_references_trigger_status(self, cond: Any) -> bool:
        """Return True when a condition explicitly filters on the lifecycle status id.

        Status lifecycle timings are global event windows.  A trigger attached to
        status A should not fire for status B unless its condition explicitly
        listens to trigger.status_id / status_id.
        """
        if cond in (None, {}, True, False):
            return False
        if isinstance(cond, str):
            return "trigger.status_id" in cond or "status_id" in cond
        if isinstance(cond, dict):
            for k, v in cond.items():
                if k in {"left", "right", "value", "context"} and isinstance(v, str) and ("trigger.status_id" in v or v == "status_id"):
                    return True
                if k in {"status_id", "modifier_name"}:
                    return True
                if self.condition_references_trigger_status(v):
                    return True
        if isinstance(cond, list):
            return any(self.condition_references_trigger_status(c) for c in cond)
        return False

    def status_lifecycle_trigger_applies(self, trig: dict[str, Any], ctx: dict[str, Any]) -> bool:
        event_status_id = ctx.get("status_id") or deep_get(ctx, "trigger.status_id")
        trigger_status_id = trig.get("status_id")
        if not event_status_id or not trigger_status_id:
            return True
        if str(event_status_id) == str(trigger_status_id):
            return True
        # Listener-style triggers may deliberately observe other statuses.  They
        # must say so via a condition that refers to trigger.status_id.
        return self.condition_references_trigger_status(trig.get("condition", {}))

    def run_triggers(self, timing: str, ctx: dict[str, Any]) -> None:
        # Watcher windows can be caused by status effects that themselves add
        # statuses.  Cap nested synthetic watcher dispatch so generated
        # property/dynamic-value listeners cannot recursively trigger themselves
        # forever while still allowing the first status-added snapshot window.
        if timing in {"ability_property_change", "status_dynamic_value_change", "status_dynamic_value_enter_range", "status_dynamic_value_exit_range"} and coerce_int(ctx.get("watcher_depth", 0), 0) > 1:
            self.state.log_event("trigger_skip", f"Skip nested watcher window {timing}", {"watcher_depth": ctx.get("watcher_depth")})
            return
        for trig in self.state.triggers:
            if trig.get("timing") != timing:
                continue
            if timing in {"status_create", "status_destroy", "status_stack"} and not self.status_lifecycle_trigger_applies(trig, ctx):
                continue
            owner_id = trig.get("owner_id") or trig.get("owner") or trig.get("source_unit")
            actor_id = ctx.get("actor_id")
            # Semantic model-pack timings are owner-relative.  A trigger named
            # `after_wearer_uses_ultimate` belongs only to the acting wearer, while
            # `after_other_ally_uses_ultimate` must explicitly exclude the owner.
            if timing == "after_wearer_uses_ultimate" and owner_id and actor_id and str(owner_id) != str(actor_id):
                continue
            if timing == "after_other_ally_uses_ultimate" and owner_id and actor_id and str(owner_id) == str(actor_id):
                continue
            # Generated StatusTemplate triggers carry an owner_id even for global
            # lifecycle events such as battle_start.  Their canonical effects may
            # target actor/owner; expose the owner in the runtime context without
            # overriding an existing action actor.
            trigger_ctx = ctx
            if owner_id:
                trigger_ctx = dict(ctx)
                trigger_ctx.setdefault("owner_id", owner_id)
                if owner_id in self.state.units:
                    trigger_ctx.setdefault("owner", self.state.unit(owner_id))
                    owner_context_timings = {
                        "battle_start", "wave_start",
                        "status_create", "status_destroy", "status_stack",
                        "ability_property_change",
                        "status_dynamic_value_change",
                        "status_dynamic_value_enter_range",
                        "status_dynamic_value_exit_range",
                    }
                    # For non-action generated StatusTemplate windows, TBGD aliases
                    # such as Caster/ModifierOwnerEntity refer to the modifier owner,
                    # not to the actor that happened to cause a status/property event.
                    # Keep action-owned timings unchanged so after_damage/action_end
                    # triggers can still inspect the real acting unit.
                    if "actor_id" not in trigger_ctx or timing in owner_context_timings:
                        trigger_ctx["actor_id"] = owner_id
                        trigger_ctx["actor"] = self.state.unit(owner_id)
            if not self.check_trigger_usage(trig, trigger_ctx):
                continue
            if self.eval_condition(trig.get("condition", {}), trigger_ctx):
                self.increment_trigger_usage(trig, trigger_ctx)
                self.state.log_event("trigger", f"Trigger {trig.get('id')} fired", {"timing": timing})
                effects = trig.get("effects", [])
                if not effects and "effect" in trig:
                    effects = trig.get("effect")
                if isinstance(effects, dict):
                    effects = [effects]
                for eff in effects or []:
                    self.apply_effect(eff, trigger_ctx)

    def trigger_usage_key(self, trig: dict[str, Any], ctx: dict[str, Any]) -> str:
        limit = trig.get("usage_limit", {}) or {}
        if not isinstance(limit, dict):
            return f"{trig.get('id')}:battle"
        scope = limit.get("scope", "battle")
        scope = {"per_owner_turn": "owner_turn", "once_per_owner_turn": "owner_turn", "per_action_resolution": "action_resolution"}.get(str(scope), scope)
        owner = trig.get("owner_id") or trig.get("owner") or ctx.get("actor_id") or "global"
        if scope == "battle":
            return f"{trig.get('id')}:battle"
        if scope == "owner_turn":
            # Automatically reset at that owner's regular turn start in v0.2.
            return f"{trig.get('id')}:owner_turn:{owner}"
        if scope == "action_resolution":
            return f"{trig.get('id')}:action:{id(ctx.get('action'))}"
        if scope in {"per_trigger_actor", "trigger_actor", "per_source_actor", "source_actor"}:
            # Generic support for mechanics such as "once per other ally".
            # The trigger owner remains the listener; ctx.actor_id is the unit
            # that caused the semantic window, e.g. the ally who used Ultimate.
            source_actor = ctx.get("actor_id") or ctx.get("source_actor_id") or "unknown"
            return f"{trig.get('id')}:source_actor:{source_actor}"
        return f"{trig.get('id')}:{scope}:{owner}"

    def check_trigger_usage(self, trig: dict[str, Any], ctx: dict[str, Any]) -> bool:
        limit = trig.get("usage_limit")
        if not limit or not isinstance(limit, dict):
            return True
        max_times = coerce_int(limit.get("max_times", 1), 1)
        key = self.trigger_usage_key(trig, ctx)
        return self.state.trigger_usage.get(key, 0) < max_times

    def increment_trigger_usage(self, trig: dict[str, Any], ctx: dict[str, Any]) -> None:
        if not trig.get("usage_limit") or not isinstance(trig.get("usage_limit"), dict):
            return
        key = self.trigger_usage_key(trig, ctx)
        self.state.trigger_usage[key] = self.state.trigger_usage.get(key, 0) + 1

    def eval_condition_string(self, cond: str, ctx: dict[str, Any]) -> bool:
        """Evaluate common model-pack string predicates.

        Character/enemy templates sometimes store human-readable predicates such as
        ``action.tags contains attack`` or ``target.hp_percent <= 0.5``.  The route
        validator should not require these to be rewritten into dict predicate form
        before replaying video-derived cases.  This intentionally supports only the
        simple predicate grammar used by the current model pack: AND/OR composition,
        unary ``not``, membership, and basic comparisons.
        """
        text = cond.strip()
        if not text:
            return True
        lowered = text.lower()
        if lowered in {"always", "true"}:
            return True
        if lowered in {"never", "false"}:
            return False
        if lowered == "zone_active":
            return any(bool(v) for k, v in self.state.global_flags.items() if "zone" in str(k)) or coerce_bool(self.state.global_flags.get("zone_active", False))
        if lowered in {"target_has_state_conquered", "target_has_conquered"}:
            tid = ctx.get("target_id")
            if tid in self.state.units:
                u = self.state.unit(tid)
                return bool(u.flags.get("conquered") or any("conquer" in st.id for st in u.statuses))
            return False
        if lowered == "ally_target_has_shield":
            for uid in ctx.get("targets", []) or []:
                if uid in self.state.units and self.state.unit(uid).side == "ally" and self.state.unit(uid).shield > EPS:
                    return True
            tid = ctx.get("target_id")
            return bool(tid in self.state.units and self.state.unit(tid).side == "ally" and self.state.unit(tid).shield > EPS)
        if lowered.startswith("not "):
            return not self.eval_condition_string(text[4:].strip(), ctx)
        # No parentheses in current model-pack predicates; split on explicit word
        # operators with surrounding spaces to avoid splitting identifiers.
        if " or " in text:
            return any(self.eval_condition_string(part, ctx) for part in text.split(" or "))
        if " and " in text:
            return all(self.eval_condition_string(part, ctx) for part in text.split(" and "))

        if " has " in text:
            unit_spec, status_id = [part.strip() for part in text.split(" has ", 1)]
            try:
                unit_id = self.resolve_condition_unit(unit_spec, ctx)
            except SimulatorError:
                return False
            if unit_id not in self.state.units:
                return False
            unit = self.state.unit(unit_id)
            # Status predicate: "seele has seele_amplification".
            if any(st.id == status_id for st in unit.statuses):
                return True
            # Relic-set predicate: "wearer has 4 pieces of genius_of_brilliant_stars".
            import re as _re
            m = _re.fullmatch(r"(\d+)\s+pieces\s+of\s+([A-Za-z0-9_\-]+)", status_id)
            if m:
                need = int(m.group(1)); set_id = m.group(2).strip().lower()
                raw_sets = unit.flags.get("relic_sets") or unit.flags.get("sets") or {}
                if isinstance(raw_sets, dict):
                    for key, val in raw_sets.items():
                        if isinstance(val, dict):
                            sid = str(val.get("id", key)).strip().lower(); pieces = coerce_int(val.get("pieces", 0), 0)
                        else:
                            sid = str(key).strip().lower(); pieces = coerce_int(val, 0)
                        if sid == set_id and pieces >= need:
                            return True
                if isinstance(raw_sets, list):
                    for val in raw_sets:
                        if isinstance(val, dict):
                            sid = str(val.get("id", "")).strip().lower(); pieces = coerce_int(val.get("pieces", 0), 0)
                            if sid == set_id and pieces >= need:
                                return True
            return False

        if " contains " in text:
            left_raw, right_raw = [part.strip() for part in text.split(" contains ", 1)]
            left = self.resolve_condition_ref(left_raw, ctx)
            right = self.resolve_condition_literal(right_raw, ctx)
            return self.compare(left, "contains", right)
        if " in " in text:
            left_raw, right_raw = [part.strip() for part in text.split(" in ", 1)]
            left = self.resolve_condition_ref(left_raw, ctx)
            right = self.resolve_condition_literal(right_raw, ctx)
            return self.compare(right, "contains", left)

        for op in ("==", "!=", "<=", ">=", "<", ">"):
            if op in text:
                left_raw, right_raw = [part.strip() for part in text.split(op, 1)]
                left = self.resolve_condition_ref(left_raw, ctx)
                right = self.resolve_condition_literal(right_raw, ctx)
                return self.compare(left, op, right)

        # Bare boolean reference, e.g. "target.is_alive".
        return coerce_bool(self.resolve_condition_ref(text, ctx), default=False)

    def resolve_condition_unit(self, spec: str, ctx: dict[str, Any]) -> str:
        if spec in {"actor", "source", "owner", "wearer", "target"}:
            return self.resolve_special_unit("actor" if spec in {"source", "owner", "wearer"} else spec, ctx)
        return spec

    def resolve_condition_literal(self, token: str, ctx: dict[str, Any]) -> Any:
        if (token.startswith("'") and token.endswith("'")) or (token.startswith('"') and token.endswith('"')):
            token = token[1:-1]
        # If the right side is itself a reference, resolve it. Otherwise leave it
        # as a literal and let compare() normalize booleans/numbers.
        if token.startswith("[") and token.endswith("]"):
            inner = token[1:-1].strip()
            if not inner:
                return []
            return [coerce_comparison_value(part.strip().strip("'\"")) for part in inner.split(",")]
        if token in {"actor", "self", "source", "owner", "wearer", "target"}:
            try:
                return self.resolve_condition_unit(token, ctx)
            except Exception:
                return token
        if token.startswith(("unit:", "ctx:", "flag:")) or "." in token and token.split(".", 1)[0] in {"action", "packet", "damage_packet", "target", "actor", "context", "defeated_by", "usage_limit", "wearer", "owner"}:
            return self.resolve_condition_ref(token, ctx)
        return coerce_comparison_value(token)

    def resolve_condition_ref(self, ref: str, ctx: dict[str, Any]) -> Any:
        if ref.startswith(("unit:", "ctx:", "flag:")):
            return self.resolve_ref(ref, ctx)
        if ref == "battle.wave_index":
            return self.state.wave_index
        if ref == "battle.wave_number":
            return self.state.wave_index + 1
        if ref in {"owner.rank", "actor.rank", "wearer.rank"}:
            uid = ctx.get("owner_id") or ctx.get("actor_id")
            if uid in self.state.units:
                return self.state.unit(uid).flags.get("rank", self.state.unit(uid).flags.get("eidolon", 0))
            return 0
        if ref in {"trigger.status_id", "status.id", "status_id"}:
            return ctx.get("status_id") or deep_get(ctx, "trigger.status_id")
        if ref == "current_skill_active":
            return bool(ctx.get("action")) or bool(deep_get(ctx, "context.current_skill_active", False))
        if ref in {"context.custom_event_id", "custom_event_id"}:
            return ctx.get("custom_event_id") or deep_get(ctx, "context.custom_event_id")
        if ref == "skill_point_activated":
            return coerce_bool(ctx.get("skill_point_activated", self.state.global_flags.get("skill_point_activated", True)), default=True)
        if ref in {"target", "target.id"}:
            return ctx.get("target_id")
        if ref in {"actor", "actor.id", "wearer", "wearer.id"}:
            return ctx.get("actor_id")
        if ref == "action.tags":
            return set(normalize_str_list(ctx.get("action", {}).get("tags", [])))
        if ref in {"packet.tags", "damage_packet.tags"}:
            return set(normalize_str_list(ctx.get("packet", {}).get("tags", [])))
        if ref in {"packet.damage_type", "damage_packet.damage_type"}:
            return ctx.get("packet", {}).get("damage_type")
        if ref in {"packet.actor", "packet.actor_id", "damage_packet.actor", "damage_packet.actor_id"}:
            return ctx.get("actor_id")
        if ref in {"packet.deals_damage", "damage_packet.deals_damage"}:
            packet = ctx.get("packet", {}) if isinstance(ctx.get("packet", {}), dict) else {}
            return coerce_float(packet.get("multiplier", 0.0)) > 0 or bool(packet.get("flat_damage"))
        if ref == "target.weaknesses":
            target = ctx.get("target") if isinstance(ctx.get("target"), UnitState) else None
            if target is None and ctx.get("target_id") in self.state.units:
                target = self.state.unit(ctx["target_id"])
            return set(target.weaknesses) if target else set()
        if ref == "action.id":
            return ctx.get("action", {}).get("id")
        if ref in {"action.actor", "action.actor_id"}:
            return ctx.get("action", {}).get("actor_id") or ctx.get("actor_id")
        if ref == "action.actor_is_ally":
            actor = ctx.get("actor") if isinstance(ctx.get("actor"), UnitState) else None
            if actor is None and ctx.get("actor_id") in self.state.units:
                actor = self.state.unit(ctx["actor_id"])
            return bool(actor and actor.side == "ally")
        if ref == "target.is_alive":
            target = ctx.get("target") if isinstance(ctx.get("target"), UnitState) else None
            if target is None and ctx.get("target_id") in self.state.units:
                target = self.state.unit(ctx["target_id"])
            return bool(target and target.alive)
        if ref == "target.invalid_after_damage":
            dr = ctx.get("damage_result", {}) if isinstance(ctx.get("damage_result", {}), dict) else {}
            return bool(dr.get("target_defeated") or dr.get("target_missing"))
        if ref == "target.hp_percent":
            target = ctx.get("target") if isinstance(ctx.get("target"), UnitState) else None
            if target is None and ctx.get("target_id") in self.state.units:
                target = self.state.unit(ctx["target_id"])
            return target.hp_percent if target else None
        if ref in {"defeated_by.owner", "defeated_by.actor", "defeated_by.actor_id"}:
            return ctx.get("actor_id")
        if ref.startswith("context."):
            key = ref[len("context."):]
            context = ctx.get("context", {}) if isinstance(ctx.get("context", {}), dict) else {}
            val = deep_get(context, key, None)
            if val is not None:
                return val
            return deep_get(ctx, key, None)
        if ref in {"custom_event_id", "context.custom_event_id"}:
            return ctx.get("custom_event_id") or deep_get(ctx, "context.custom_event_id")
        if ref == "usage_limit.not_used_this_owner_turn":
            # Usage limits are checked before condition evaluation; reaching this
            # predicate means the usage gate has already allowed the trigger.
            return True
        if ref.startswith("status:"):
            parts = ref.split(":", 3)
            try:
                if len(parts) == 4:
                    _, target_spec, status_id, value_type = parts
                    targets = self.resolve_effect_targets({"target": target_spec}, ctx, default="actor")
                    if not targets:
                        return 0
                    return self.read_status_value(self.state.unit(targets[0]), status_id, value_type, value_type)
                # Legacy status:<key> falls back to current trigger/status id on actor.
                _, value_type = parts[:2]
                status_id = ctx.get("status_id") or ctx.get("trigger", {}).get("status_id")
                actor_id = ctx.get("actor_id")
                if status_id and actor_id in self.state.units:
                    return self.read_status_value(self.state.unit(actor_id), status_id, value_type, value_type)
            except Exception:
                return 0
            return 0
        if ref in ctx:
            return ctx.get(ref)
        if ref.endswith("_is_on_field"):
            uid = ref[:-len("_is_on_field")]
            return uid in self.state.units and self.state.unit(uid).alive and self.state.unit(uid).side == "ally"
        if ref in self.state.global_flags:
            return self.state.global_flags.get(ref)
        if "." in ref:
            root, field = ref.split(".", 1)
            if root in {"actor", "target", "owner", "wearer"}:
                try:
                    unit_id = self.resolve_condition_unit(root, ctx)
                    unit = self.state.unit(unit_id)
                    field_alias = {
                        "current_crit_rate": "crit_rate",
                        "final_speed": "speed",
                        "final_speed_in_battle": "speed",
                    }.get(field, field)
                    if field_alias == "speed":
                        return self.effective_speed(unit)
                    if field_alias == "team":
                        return unit.flags.get("team") or ("TeamLight" if unit.side == "ally" else "TeamDark")
                    if field_alias in {"crit_rate", "crit_dmg", "atk", "hp", "def", "defense", "speed"} or field_alias.endswith("_dmg_bonus"):
                        return unit.get_stat(field_alias)
                    if field in unit.flags:
                        return unit.flags.get(field)
                    return deep_get(unit, field)
                except Exception:
                    return None
        return coerce_comparison_value(ref)

    def eval_target_alive_state_condition(self, spec: dict[str, Any], ctx: dict[str, Any]) -> bool:
        side = str(spec.get("side") or "ally")
        wants_alive = coerce_bool(spec.get("alive", True), default=True)
        idx = spec.get("formation_index")
        if side == "actor":
            targets = [ctx.get("actor_id")] if ctx.get("actor_id") else []
        elif side == "enemy":
            ordered = [u for u in self.state.units.values() if u.side == "enemy"]
            def pos_key(u: UnitState):
                raw = u.flags.get("position", u.flags.get("slot", u.flags.get("formation_index", None)))
                num = maybe_float(raw)
                return (0, num) if num is not None else (1, list(self.state.units).index(u.id) if u.id in self.state.units else 9999)
            ordered = sorted(ordered, key=pos_key, reverse=(str(spec.get("formation_order") or "asc") == "desc"))
            targets = [u.id for u in ordered]
        else:
            # TargetAliveState in ConfigAI checks formation slots, not "nth alive".
            # Keep dead units in the ordered list, then compare their alive flag.
            ordered = [u for u in self.state.units.values() if u.side == "ally"]
            def pos_key(u: UnitState):
                raw = u.flags.get("position", u.flags.get("slot", u.flags.get("formation_index", None)))
                num = maybe_float(raw)
                return (0, num) if num is not None else (1, list(self.state.units).index(u.id) if u.id in self.state.units else 9999)
            ordered = sorted(ordered, key=pos_key, reverse=(str(spec.get("formation_order") or "asc") == "desc"))
            if idx is None:
                targets = [u.id for u in ordered]
            else:
                try:
                    i = int(idx)
                except Exception:
                    i = 0
                targets = [ordered[i].id] if 0 <= i < len(ordered) else []
        if not targets:
            return not wants_alive
        for uid in targets:
            if uid in self.state.units and self.state.unit(uid).alive == wants_alive:
                return True
        return False

    def eval_unit_has_status_condition(self, spec: dict[str, Any], ctx: dict[str, Any]) -> bool:
        target_spec = spec.get("target", "actor")
        status_id = str(spec.get("status_id") or spec.get("modifier") or "")
        inverse = coerce_bool(spec.get("inverse", False), default=False)
        found = False
        target_units: list[UnitState] = []
        direct = self.condition_target_unit(target_spec, ctx)
        if direct is not None:
            target_units = [direct]
        else:
            target_units = [self.state.unit(tid) for tid in self.resolve_effect_targets({"target": target_spec}, ctx, default="actor") if tid in self.state.units]
        for unit in target_units:
            if status_id in unit.flags and coerce_bool(unit.flags.get(status_id), default=False):
                found = True
                break
            status_l = status_id.lower()
            for st in unit.statuses:
                tags = {str(t).lower() for t in st.tags}
                if st.id == status_id or st.id.lower() == status_l or status_l in tags:
                    found = True
                    break
            if found:
                break
        return (not found) if inverse else found



    def target_policy_units_for_ai(self, actor: UnitState, policy: str) -> list[UnitState]:
        policy_s = str(policy or "first_ally")
        if policy_s in {"self", "actor", "caster"}:
            return [actor] if actor.alive else []
        if policy_s in {"all_allies", "ally_side", "all_player_characters", "all_ally_team", "all_light_team"}:
            return self.ordered_alive_side_units("ally")
        if policy_s in {"all_enemies", "enemy_side", "all_monsters", "all_teammate", "all_dark_team"}:
            return [u for u in self.state.enemies_alive()]
        if policy_s in {"summoner"}:
            sid = actor.flags.get("summoner_id") or actor.flags.get("owner_id")
            return [self.state.unit(str(sid))] if sid and str(sid) in self.state.units and self.state.unit(str(sid)).alive else []
        if policy_s in {"first_ally", "random_ally", "random_alive_ally"}:
            allies = self.ordered_alive_side_units("ally")
            return allies[:1]
        if policy_s in {"first_enemy", "random_enemy", "random_alive_enemy"}:
            enemies = self.state.enemies_alive()
            return enemies[:1]
        try:
            ids = self.select_targets({"id": "ai_target_policy", "actor_id": actor.id, "target_policy": policy_s, "damage_packets": []}, {})
            return [self.state.unit(uid) for uid in ids if uid in self.state.units and self.state.unit(uid).alive]
        except Exception:
            return []

    def enemy_ai_target_candidates_from_spec(self, actor: UnitState, spec: dict[str, Any]) -> list[UnitState]:
        policy = spec.get("target_policy")
        if not policy:
            side = str(spec.get("side") or "ally")
            policy = "all_enemies" if side == "enemy" else ("self" if side == "actor" else "all_allies")
        units = self.target_policy_units_for_ai(actor, str(policy))
        order = str(spec.get("formation_order") or "asc")
        if order == "desc":
            units = list(reversed(units))
        idx = spec.get("formation_index")
        if idx is not None:
            try:
                i = int(idx)
                units = [units[i]] if 0 <= i < len(units) else []
            except Exception:
                pass
        if coerce_bool(spec.get("alive_only", True), default=True):
            units = [u for u in units if u.alive]
        return units

    def condition_target_unit(self, target_spec: Any, ctx: dict[str, Any]) -> UnitState | None:
        target_s = str(target_spec or "actor")
        if target_s in {"param_entity", "ParamEntity", "target", "target_id"}:
            uid = ctx.get("param_entity_id") or ctx.get("target_id")
            if isinstance(ctx.get("param_entity"), UnitState):
                return ctx.get("param_entity")
            if uid in self.state.units:
                return self.state.unit(uid)
            if isinstance(ctx.get("target"), UnitState):
                return ctx.get("target")
            return None
        if target_s in {"actor", "caster", "self"}:
            actor = ctx.get("actor") if isinstance(ctx.get("actor"), UnitState) else None
            if actor is None and ctx.get("actor_id") in self.state.units:
                actor = self.state.unit(ctx["actor_id"])
            return actor
        if target_s in self.state.units:
            return self.state.unit(target_s)
        return None

    def eval_unit_custom_value_bool_condition(self, spec: dict[str, Any], ctx: dict[str, Any]) -> bool:
        unit = self.condition_target_unit(spec.get("target", "actor"), ctx)
        if unit is None:
            return False
        key = str(spec.get("key") or "")
        candidates = [key]
        if key.startswith("custom_bool:"):
            suffix = key.split(":", 1)[1]
            candidates.extend([f"custom_value_bool:{suffix}", f"custom_bool_{suffix}", f"custom_value_{suffix}", suffix])
        found = any(coerce_bool(unit.flags.get(k), default=False) for k in candidates if k in unit.flags)
        return (not found) if coerce_bool(spec.get("inverse", False), default=False) else found

    def eval_unit_identity_compare_condition(self, spec: dict[str, Any], ctx: dict[str, Any]) -> bool:
        unit = self.condition_target_unit(spec.get("target", "actor"), ctx)
        if unit is None:
            return False
        field = str(spec.get("field") or "monster_id")
        if field in {"monster_id", "monster_template_id", "rank"}:
            left = unit.flags.get(field)
            if left is None and field == "monster_id":
                left = unit.flags.get("MonsterID") or unit.id
            if left is None and field == "rank":
                left = unit.flags.get("monster_rank") or unit.flags.get("Rank")
        else:
            left = unit.flags.get(field)
        return self.compare(coerce_comparison_value(left), spec.get("op", "=="), coerce_comparison_value(spec.get("value")))

    def eval_modifier_value_compare_condition(self, spec: dict[str, Any], ctx: dict[str, Any]) -> bool:
        unit = self.condition_target_unit(spec.get("target", "actor"), ctx)
        if unit is None:
            return False
        sid = str(spec.get("status_id") or "")
        status = next((st for st in unit.statuses if st.id == sid), None)
        value_type = str(spec.get("value_type") or "Layer").lower()
        if status is None:
            left = 0
        elif value_type in {"layer", "stacks", "stack"}:
            left = status.stacks
        else:
            left = status.modifiers.get(value_type, status.modifiers.get(str(spec.get("value_type")), 0))
        return self.compare(left, spec.get("op", "=="), spec.get("value", 0))

    def eval_unit_behavior_flag_condition(self, spec: dict[str, Any], ctx: dict[str, Any]) -> bool:
        unit = self.condition_target_unit(spec.get("target", "actor"), ctx)
        if unit is None:
            return False
        flag = str(spec.get("flag") or "")
        found = coerce_bool(unit.flags.get(flag), default=False)
        if not found:
            behavior_flags = unit.flags.get("behavior_flags") or unit.flags.get("BehaviorFlags") or []
            found = flag in set(normalize_str_list(behavior_flags))
        return (not found) if coerce_bool(spec.get("inverse", False), default=False) else found

    def eval_battle_point_compare_condition(self, spec: dict[str, Any], ctx: dict[str, Any]) -> bool:
        value = self.state.global_flags.get("battle_point", self.state.global_flags.get("BP", 0))
        return self.compare(coerce_float(value, 0.0), spec.get("op", "=="), coerce_float(spec.get("value", 0), 0.0))

    def eval_alive_enemy_number_condition(self, spec: dict[str, Any], ctx: dict[str, Any]) -> bool:
        count = len([u for u in self.state.enemies_alive()])
        return self.compare(count, spec.get("op", "=="), coerce_int(spec.get("value", 0), 0))

    def eval_target_identity_compare_condition(self, spec: dict[str, Any], ctx: dict[str, Any]) -> bool:
        left = self.condition_target_unit(spec.get("left", "param_entity"), ctx)
        right = self.condition_target_unit(spec.get("right", "actor"), ctx)
        matched = bool(left is not None and right is not None and left.id == right.id)
        return (not matched) if coerce_bool(spec.get("inverse", False), default=False) else matched

    def target_unit_passes_ai_filters(self, actor: UnitState, unit: UnitState, filters: list[Any], ctx: dict[str, Any]) -> bool:
        if not filters:
            return True
        filter_ctx = {**ctx, "actor": actor, "actor_id": actor.id, "target": unit, "target_id": unit.id, "param_entity": unit, "param_entity_id": unit.id}
        return all(self.eval_condition(f, filter_ctx) for f in filters)

    def unit_matches_enemy_ai_selector(self, unit: UnitState, selector: dict[str, Any], actor: UnitState) -> bool:
        typ = str(selector.get("type") or "")
        inverse = coerce_bool(selector.get("inverse", False), default=False)
        matched = False
        if typ == "target_with_status":
            status_id = str(selector.get("status_id") or "")
            status_l = status_id.lower()
            matched = any(st.id == status_id or st.id.lower() == status_l or status_l in {str(t).lower() for t in st.tags} for st in unit.statuses)
        elif typ == "monster_id":
            ids = {str(x) for x in selector.get("monster_ids") or []}
            matched = str(unit.flags.get("monster_id") or unit.id) in ids
        elif typ == "monster_rank":
            ranks = {str(x) for x in selector.get("ranks") or []}
            if ranks:
                matched = str(unit.flags.get("rank") or unit.flags.get("monster_rank") or "") in ranks
            else:
                # PropertyStrategy-only AIMonsterRankSelector is a deterministic
                # ranking selector, not a boolean filter.  Keep all candidates and
                # let select_targets_from_enemy_ai_selector sort them.
                matched = True
        elif typ == "target_policy":
            matched = unit in self.target_policy_units_for_ai(actor, str(selector.get("target_policy") or "first_ally"))
            seq = selector.get("target_sequence") if isinstance(selector.get("target_sequence"), dict) else {}
            if matched and seq.get("filters"):
                matched = self.target_unit_passes_ai_filters(actor, unit, list(seq.get("filters") or []), {"context": {"phase": "enemy_ai_selector"}, "phase_locked_targets": set()})
        elif typ == "property_extreme":
            matched = True
        elif typ == "behavior_flag":
            matched = self.eval_unit_behavior_flag_condition({"target": unit.id, "flag": selector.get("flag"), "inverse": False}, {"actor": actor, "actor_id": actor.id})
        elif typ == "custom_string_tag":
            tag = str(selector.get("tag") or "")
            matched = tag in unit.tags or tag in set(normalize_str_list(unit.flags.get("custom_string_tags", []))) or str(unit.flags.get("custom_string_tag") or "") == tag
        elif typ == "complex_skill_source":
            # ConfigAI uses this as a skill-specific helper selector.  Without a
            # full score evaluator, keep candidates alive and preserve the source
            # skill name in the selector audit.
            matched = True
        elif typ == "compose":
            results = [self.unit_matches_enemy_ai_selector(unit, sub, actor) for sub in selector.get("selectors") or [] if isinstance(sub, dict)]
            matched = any(results) if str(selector.get("compose")) == "any" else all(results) if results else False
        elif typ in {"default", "unsupported_selector"}:
            matched = True
        return (not matched) if inverse else matched

    def sort_enemy_ai_selector_targets(self, units: list[UnitState], selector: dict[str, Any]) -> list[UnitState]:
        typ = str(selector.get("type") or "")
        if not units:
            return []
        if typ == "property_extreme":
            prop = str(selector.get("property") or "CurrentHP").lower()
            strat = str(selector.get("strategy") or "MinRatio")
            def value(u: UnitState) -> float:
                if "hp" in prop and "ratio" in strat.lower():
                    return u.hp_percent
                if "hp" in prop:
                    return u.hp
                if "speed" in prop:
                    return self.effective_speed(u)
                return coerce_float(u.flags.get(prop, u.get_stat(prop)), 0.0)
            reverse = strat.lower().startswith("max")
            return sorted(units, key=value, reverse=reverse)
        if typ == "monster_rank" and selector.get("property_strategy"):
            reverse = str(selector.get("property_strategy")).lower().startswith("max")
            return sorted(units, key=lambda u: coerce_float(u.flags.get("rank", u.flags.get("monster_rank", 0)), 0.0), reverse=reverse)
        if typ == "compose":
            # Apply the first ranking subselector found inside the compose tree.
            for sub in selector.get("selectors") or []:
                if isinstance(sub, dict) and str(sub.get("type")) in {"property_extreme", "monster_rank"}:
                    return self.sort_enemy_ai_selector_targets(units, sub)
        return units

    def select_targets_from_enemy_ai_selector(self, actor: UnitState, selector: dict[str, Any], action: dict[str, Any], context: dict[str, Any]) -> list[str]:
        if not isinstance(selector, dict):
            return []
        base_policy = selector.get("target_policy") or action.get("target_policy") or "first_ally"
        candidates = self.target_policy_units_for_ai(actor, str(base_policy))
        if not candidates:
            # For selectors such as AIModifierNameSelector that do not carry a
            # target type, scan alive allies by default because most enemy
            # targeting selectors aim at player characters.  Enemy-side selectors
            # explicitly carry all_enemies.
            candidates = self.ordered_alive_side_units("ally")
        picked_units = [u for u in candidates if self.unit_matches_enemy_ai_selector(u, selector, actor)]
        if not picked_units and selector.get("type") == "target_policy":
            picked_units = candidates
        picked_units = self.sort_enemy_ai_selector_targets(picked_units, selector)
        selector_type = str(selector.get("type") or "")
        if selector_type in {"property_extreme", "monster_rank"}:
            picked_units = picked_units[:1]
        elif selector_type == "compose":
            if any(isinstance(sub, dict) and str(sub.get("type")) in {"property_extreme", "monster_rank"} for sub in selector.get("selectors") or []):
                picked_units = picked_units[:1]
        return [u.id for u in picked_units]

    def eval_target_count_condition(self, spec: dict[str, Any], ctx: dict[str, Any]) -> bool:
        actor = ctx.get("actor") if isinstance(ctx.get("actor"), UnitState) else None
        if actor is None and ctx.get("actor_id") in self.state.units:
            actor = self.state.unit(ctx["actor_id"])
        if actor is None:
            return False
        units = self.enemy_ai_target_candidates_from_spec(actor, spec)
        filters = list(spec.get("filters") or [])
        if filters:
            units = [u for u in units if self.target_unit_passes_ai_filters(actor, u, filters, ctx)]
        count = len(units)
        return self.compare(count, spec.get("op", ">="), coerce_int(spec.get("value", 0), 0))

    def eval_target_hp_ratio_condition(self, spec: dict[str, Any], ctx: dict[str, Any]) -> bool:
        actor = ctx.get("actor") if isinstance(ctx.get("actor"), UnitState) else None
        if actor is None and ctx.get("actor_id") in self.state.units:
            actor = self.state.unit(ctx["actor_id"])
        if actor is None:
            return False
        units = self.enemy_ai_target_candidates_from_spec(actor, spec)
        filters = list(spec.get("filters") or [])
        if filters:
            units = [u for u in units if self.target_unit_passes_ai_filters(actor, u, filters, ctx)]
        if not units:
            return False
        # Existential semantics: if any selected target satisfies the predicate,
        # the AI branch is considered available.
        return any(self.compare(u.hp_percent, spec.get("op", "<"), coerce_float(spec.get("value", 0.0), 0.0)) for u in units)

    def eval_enemy_skill_cooldown_ready_condition(self, spec: dict[str, Any], ctx: dict[str, Any]) -> bool:
        actor = ctx.get("actor")
        if not isinstance(actor, UnitState):
            actor_id = ctx.get("actor_id")
            actor = self.state.unit(actor_id) if actor_id in self.state.units else None
        if not isinstance(actor, UnitState):
            return False
        skill = str(spec.get("skill") or spec.get("action") or "")
        if not skill:
            return True
        cooldowns = actor.flags.get("enemy_skill_cooldowns") if isinstance(actor.flags.get("enemy_skill_cooldowns"), dict) else {}
        remaining = coerce_int(cooldowns.get(skill, 0), 0)
        return remaining <= 0

    def eval_enemy_skill_usage_delay_ready_condition(self, spec: dict[str, Any], ctx: dict[str, Any]) -> bool:
        actor = ctx.get("actor")
        if not isinstance(actor, UnitState):
            actor_id = ctx.get("actor_id")
            actor = self.state.unit(actor_id) if actor_id in self.state.units else None
        if not isinstance(actor, UnitState):
            return False
        skill = str(spec.get("skill") or spec.get("action") or "")
        delay = coerce_int(spec.get("action_delay", spec.get("delay", 0)), 0)
        if not skill or delay <= 0:
            return True
        record = actor.flags.get("enemy_skill_use_record") if isinstance(actor.flags.get("enemy_skill_use_record"), dict) else {}
        rec = record.get(skill) if isinstance(record, dict) else None
        if not isinstance(rec, dict):
            return True
        now = coerce_int(actor.flags.get("enemy_action_counter", 0), 0)
        last = coerce_int(rec.get("action_counter", now), now)
        return (now - last) >= delay

    def eval_condition(self, cond: Any, ctx: dict[str, Any]) -> bool:
        if cond in (None, {}, True):
            return True
        if cond is False:
            return False
        if isinstance(cond, str):
            return self.eval_condition_string(cond, ctx)
        if isinstance(cond, dict):
            if "all" in cond:
                return all(self.eval_condition(c, ctx) for c in cond["all"])
            if "any" in cond:
                return any(self.eval_condition(c, ctx) for c in cond["any"])
            if "not" in cond:
                return not self.eval_condition(cond["not"], ctx)
            if "target_alive_state" in cond and not any(k in cond for k in ("left", "op", "right", "value")):
                return self.eval_target_alive_state_condition(cond.get("target_alive_state") or {}, ctx)
            if "unit_has_status" in cond and not any(k in cond for k in ("left", "op", "right", "value")):
                return self.eval_unit_has_status_condition(cond.get("unit_has_status") or {}, ctx)
            if "enemy_skill_cooldown_ready" in cond and not any(k in cond for k in ("left", "op", "right", "value")):
                return self.eval_enemy_skill_cooldown_ready_condition(cond.get("enemy_skill_cooldown_ready") or {}, ctx)
            if "enemy_skill_usage_delay_ready" in cond and not any(k in cond for k in ("left", "op", "right", "value")):
                return self.eval_enemy_skill_usage_delay_ready_condition(cond.get("enemy_skill_usage_delay_ready") or {}, ctx)
            if "target_count" in cond and not any(k in cond for k in ("left", "op", "right", "value")):
                return self.eval_target_count_condition(cond.get("target_count") or {}, ctx)
            if "target_hp_ratio" in cond and not any(k in cond for k in ("left", "op", "right", "value")):
                return self.eval_target_hp_ratio_condition(cond.get("target_hp_ratio") or {}, ctx)
            if "unit_custom_value_bool" in cond and not any(k in cond for k in ("left", "op", "right", "value")):
                return self.eval_unit_custom_value_bool_condition(cond.get("unit_custom_value_bool") or {}, ctx)
            if "unit_identity_compare" in cond and not any(k in cond for k in ("left", "op", "right", "value")):
                return self.eval_unit_identity_compare_condition(cond.get("unit_identity_compare") or {}, ctx)
            if "modifier_value_compare" in cond and not any(k in cond for k in ("left", "op", "right", "value")):
                return self.eval_modifier_value_compare_condition(cond.get("modifier_value_compare") or {}, ctx)
            if "unit_behavior_flag" in cond and not any(k in cond for k in ("left", "op", "right", "value")):
                return self.eval_unit_behavior_flag_condition(cond.get("unit_behavior_flag") or {}, ctx)
            if "alive_enemy_number" in cond and not any(k in cond for k in ("left", "op", "right", "value")):
                return self.eval_alive_enemy_number_condition(cond.get("alive_enemy_number") or {}, ctx)
            if "battle_point_compare" in cond and not any(k in cond for k in ("left", "op", "right", "value")):
                return self.eval_battle_point_compare_condition(cond.get("battle_point_compare") or {}, ctx)
            if "target_identity_compare" in cond and not any(k in cond for k in ("left", "op", "right", "value")):
                return self.eval_target_identity_compare_condition(cond.get("target_identity_compare") or {}, ctx)
            if "unsupported_ai_predicate" in cond and not any(k in cond for k in ("left", "op", "right", "value")):
                self.state.log_event("condition_skip", f"Unsupported AI predicate {cond.get('unsupported_ai_predicate')}", {"condition": cond})
                return False
            # Boolean shorthand predicates. These are common in hand-written
            # trigger YAML and should evaluate directly, not as ``True == None``.
            if "action_has_tag" in cond and not any(k in cond for k in ("left", "op", "right", "value")):
                return cond["action_has_tag"] in set(normalize_str_list(ctx.get("action", {}).get("tags", [])))
            if "action_lacks_tag" in cond and not any(k in cond for k in ("left", "op", "right", "value")):
                return cond["action_lacks_tag"] not in set(normalize_str_list(ctx.get("action", {}).get("tags", [])))
            if "packet_has_tag" in cond and not any(k in cond for k in ("left", "op", "right", "value")):
                return cond["packet_has_tag"] in set(normalize_str_list(ctx.get("packet", {}).get("tags", [])))
            if "any_enemy_alive" in cond and not any(k in cond for k in ("left", "op", "right", "value")):
                wants_alive = coerce_bool(cond.get("any_enemy_alive"), default=True)
                any_alive = any(u.alive and u.side == "enemy" for u in self.state.units.values())
                return any_alive == wants_alive
            if "target_lists_intersect" in cond and not any(k in cond for k in ("left", "op", "right", "value")):
                return self.eval_target_lists_intersect(cond.get("target_lists_intersect") or {}, ctx)
            if "target_entity_type" in cond and not any(k in cond for k in ("left", "op", "right", "value")):
                return self.eval_target_entity_type(cond.get("target_entity_type") or {}, ctx)
            if "chance_gate" in cond and not any(k in cond for k in ("left", "op", "right", "value")):
                allowed, audit = self.chance_gate_allows(cond.get("chance_gate") or {}, ctx)
                self.state.log_event("chance_check", "Generated chance gate evaluated", audit)
                return allowed
            # Predicate form.
            left = self.resolve_ref(cond.get("left"), ctx) if "left" in cond else self.resolve_legacy_predicate_left(cond, ctx)
            op = cond.get("op", "==")
            raw_right = cond.get("right", cond.get("value"))
            right = self.resolve_ref(raw_right, ctx) if isinstance(raw_right, str) else raw_right
            return self.compare(left, op, right)
        raise SimulatorError(f"Unsupported condition: {cond}")

    def resolve_legacy_predicate_left(self, cond: dict[str, Any], ctx: dict[str, Any]) -> Any:
        if "unit" in cond and "field" in cond:
            unit_id = self.resolve_special_unit(cond["unit"], ctx)
            unit = self.state.unit(unit_id)
            return deep_get(unit, cond["field"], None)
        if "context" in cond:
            return self.resolve_ref(cond["context"], ctx)
        if "action_has_tag" in cond:
            return cond["action_has_tag"] in set(normalize_str_list(ctx.get("action", {}).get("tags", [])))
        return None

    def resolve_special_unit(self, spec: str, ctx: dict[str, Any]) -> str:
        if spec in {"actor", "self", "source"}:
            return ctx["actor_id"]
        if spec in {"bondmate", "selected_bondmate"}:
            uid = self.state.global_flags.get("bondmate") or self.state.global_flags.get("bondmate_target")
            if uid:
                return str(uid)
            raise SimulatorError("bondmate target is not set")
        if spec == "target":
            if "target_id" in ctx:
                return ctx["target_id"]
            targets = ctx.get("targets") or []
            if len(targets) == 1:
                return targets[0]
            raise SimulatorError("target spec is ambiguous without ctx.target_id; use explicit targets or group target")
        if spec == "owner":
            return ctx.get("owner_id") or ctx.get("actor_id")
        if spec == "tbgd_alias:DanHengPT_00_BattleEventOwner":
            uid = self.state.global_flags.get("bondmate") or self.state.global_flags.get("bondmate_target")
            if uid:
                return str(uid)
            return ctx.get("target_id") or ctx.get("owner_id") or ctx.get("actor_id")
        if spec in {"tbgd_alias:ParamEntity", "tbgd_alias:DanHengPT_00_BattleEventCaster", "tbgd_alias:DanHengPT_00_BattleEventLongLing"}:
            return ctx.get("target_id") or ctx.get("owner_id") or ctx.get("actor_id")
        return spec

    def resolve_effect_targets(self, eff: dict[str, Any], ctx: dict[str, Any], default: str = "actor") -> list[str]:
        """Resolve effect targets, including model-pack aliases.

        Exact video replay should still pass explicit route targets. These aliases
        keep character/enemy templates runnable when their text says selected_ally,
        bondmate, enemy_side, etc.
        """
        raw = eff.get("targets", eff.get("target", default))
        specs = raw if isinstance(raw, list) else [raw]
        out: list[str] = []
        for spec in specs:
            spec_s = str(spec)
            if spec_s in ("all_allies", "alive_allies", "all_player_characters", "ally_side", "all_ally_characters", "ally_characters", "sparkle_teammates"):
                out.extend([u.id for u in self.ordered_alive_side_units("ally")])
            elif spec_s in ("all_allies_except_actor", "all_player_characters_except_actor", "ally_side_except_actor"):
                actor_id = ctx.get("actor_id")
                out.extend([u.id for u in self.state.allies_alive() if str(u.id) != str(actor_id)])
            elif spec_s in ("all_enemies", "alive_enemies", "enemy_side", "enemies_or_global_enemy_side"):
                out.extend([u.id for u in self.state.enemies_alive()])
            elif spec_s == "all_units":
                out.extend([u.id for u in self.state.units.values()])
            elif spec_s == "alive_units":
                out.extend([u.id for u in self.state.units.values() if u.alive])
            elif spec_s in {"self", "actor", "source", "owner"}:
                out.append(self.resolve_special_unit("actor" if spec_s in {"self", "source"} else spec_s, ctx))
            elif spec_s in {"target", "selected_ally", "selected_single_ally", "selected_enemy"}:
                if ctx.get("targets"):
                    out.extend(ctx.get("targets") or [])
                elif ctx.get("target_id"):
                    out.append(ctx.get("target_id"))
            elif spec_s == "current_active_character":
                if ctx.get("targets"):
                    out.extend(ctx.get("targets") or [])
                else:
                    allies = self.ordered_alive_side_units("ally"); out.extend([allies[0].id] if allies else [])
            elif spec_s in {"targets_dealt_zone_additional_damage", "zone_additional_targets"}:
                out.extend(ctx.get("zone_additional_targets") or ctx.get("targets_dealt_zone_additional_damage") or [])
            elif spec_s in {"all_attacked_targets", "attacked_targets"}:
                out.extend(ctx.get("attacked_targets") or [])
            elif spec_s in {"ally_with_shield", "ally_with_lowest_current_shield"}:
                allies = [u for u in self.state.allies_alive() if u.shield > EPS]
                if spec_s == "ally_with_lowest_current_shield" and allies:
                    out.append(min(allies, key=lambda u: u.shield).id)
                else:
                    out.extend([u.id for u in allies])
            elif spec_s in {"random_single_ally_targets"}:
                allies = self.ordered_alive_side_units("ally")
                out.extend([allies[0].id] if allies else [])
            elif spec_s == "three_consecutive_allies_from_left":
                out.extend([u.id for u in self.ordered_alive_side_units("ally")[:3]])
            elif spec_s == "three_consecutive_allies_from_right":
                out.extend([u.id for u in self.ordered_alive_side_units("ally")[-3:]])
            elif spec_s == "selected_ally_and_adjacent":
                selected = ctx.get("target_id") or ((ctx.get("targets") or [None])[0])
                out.extend(self.adjacent_units_from_order(self.ordered_alive_side_units("ally"), selected, include_selected=True))
            elif spec_s == "tbgd_alias:DanHengPT_00_BattleEventOwner":
                uid = self.state.global_flags.get("bondmate") or self.state.global_flags.get("bondmate_target")
                if uid:
                    out.append(str(uid))
                elif ctx.get("targets"):
                    out.extend(ctx.get("targets") or [])
                elif ctx.get("target_id"):
                    out.append(ctx.get("target_id"))
                # No fallback to actor/owner: BattleEventOwner is the current Fellow.
                # If no Fellow context exists, skip instead of applying the buff to all owners.
            elif spec_s in {"enemy_highest_current_hp", "highest_hp_enemy", "highest_hp_among_hit_targets"}:
                enemies = self.state.enemies_alive(); out.extend([max(enemies, key=lambda u: u.hp).id] if enemies else [])
            elif spec_s == "adjacent_enemies":
                # Without formation metadata, adjacent enemies are not inferable.
                # Use all enemies except the selected target as a safe deterministic
                # approximation for template smoke tests.
                selected = set(ctx.get("targets") or ([ctx.get("target_id")] if ctx.get("target_id") else []))
                out.extend([u.id for u in self.state.enemies_alive() if u.id not in selected])
            elif spec_s == "bondmate":
                uid = self.state.global_flags.get("bondmate") or self.state.global_flags.get("bondmate_target")
                if uid:
                    out.append(str(uid))
            elif spec_s == "target" and "target_id" not in ctx and ctx.get("targets"):
                out.extend(ctx.get("targets") or [])
            else:
                out.append(self.resolve_special_unit(spec_s, ctx))
        seen = set(); result = []
        for uid in out:
            if uid and uid in self.state.units and uid not in seen:
                seen.add(uid); result.append(uid)
        return result

    def eval_target_lists_intersect(self, spec: dict[str, Any], ctx: dict[str, Any]) -> bool:
        first = spec.get("first", "actor") if isinstance(spec, dict) else "actor"
        second = spec.get("second", "target") if isinstance(spec, dict) else "target"
        first_targets = self.resolve_effect_targets({"target": first}, ctx, default="actor")
        second_targets = self.resolve_effect_targets({"target": second}, ctx, default="target")
        if coerce_bool(spec.get("first_alive_only"), default=False):
            first_targets = [uid for uid in first_targets if uid in self.state.units and self.state.unit(uid).alive]
        if coerce_bool(spec.get("second_alive_only"), default=False):
            second_targets = [uid for uid in second_targets if uid in self.state.units and self.state.unit(uid).alive]
        return bool(set(first_targets).intersection(second_targets))

    def eval_target_entity_type(self, spec: dict[str, Any], ctx: dict[str, Any]) -> bool:
        target_spec = spec.get("target", "target") if isinstance(spec, dict) else "target"
        mask = str(spec.get("entity_type_mask") or spec.get("entity_type") or "") if isinstance(spec, dict) else ""
        targets = self.resolve_effect_targets({"target": target_spec}, ctx, default="target")
        if not mask:
            return bool(targets)
        mask_l = mask.lower()
        for uid in targets:
            if uid not in self.state.units:
                continue
            u = self.state.unit(uid)
            tags = set(str(t).lower() for t in (u.tags or []))
            entity_type = str(u.flags.get("entity_type") or u.flags.get("EntityType") or "").lower()
            if mask_l == "servant":
                if "servant" in tags or entity_type == "servant" or bool(u.flags.get("is_servant")):
                    return True
            elif mask_l in tags or mask_l == entity_type:
                return True
        return False

    def resolve_ref(self, ref: Any, ctx: dict[str, Any]) -> Any:
        if not isinstance(ref, str):
            return ref
        if ref.startswith("unit:"):
            _, unit_spec, field = ref.split(":", 2)
            unit_id = self.resolve_special_unit(unit_spec, ctx)
            return deep_get(self.state.unit(unit_id), field)
        if ref.startswith("action.tags"):
            return set(normalize_str_list(ctx.get("action", {}).get("tags", [])))
        if ref.startswith("packet.tags"):
            return set(normalize_str_list(ctx.get("packet", {}).get("tags", [])))
        if ref.startswith("ctx:"):
            return deep_get(ctx, ref[4:])
        if ref.startswith("context."):
            context = ctx.get("context", {}) if isinstance(ctx.get("context", {}), dict) else {}
            return deep_get(context, ref[len("context."):])
        if ref in {"custom_event_id", "context.custom_event_id"}:
            return ctx.get("custom_event_id") or deep_get(ctx, "context.custom_event_id")
        if ref.startswith("flag:"):
            return self.state.global_flags.get(ref[5:])
        if ref == "battle.wave_index":
            return self.state.wave_index
        if ref == "battle.wave_number":
            return self.state.wave_index + 1
        if ref in {"owner.rank", "actor.rank", "wearer.rank"}:
            uid = ctx.get("owner_id") or ctx.get("actor_id")
            if uid in self.state.units:
                return self.state.unit(uid).flags.get("rank", self.state.unit(uid).flags.get("eidolon", 0))
            return 0
        if ref in {"trigger.status_id", "status.id", "status_id"}:
            return ctx.get("status_id") or deep_get(ctx, "trigger.status_id")
        return ref

    def compare(self, left: Any, op: str, right: Any) -> bool:
        left = coerce_comparison_value(left)
        right = coerce_comparison_value(right)
        if isinstance(left, str) and isinstance(right, str):
            left_cmp = left.strip().lower()
            right_cmp = right.strip().lower()
        else:
            left_cmp = left
            right_cmp = right
        if op == "==": return left_cmp == right_cmp
        if op == "!=": return left_cmp != right_cmp
        # Missing optional fields are common in generic triggers. Numeric comparisons
        # against missing data should simply be false, not crash the simulation.
        if left is None or right is None:
            if op == "contains":
                return False
            if op == "not_contains":
                return True
            return False
        if op == "<": return left < right
        if op == "<=": return left <= right
        if op == ">": return left > right
        if op == ">=": return left >= right
        if op == "contains":
            if isinstance(left, (set, list, tuple)):
                if isinstance(right, str):
                    return right.strip().lower() in {str(x).strip().lower() for x in left}
                return right in left
            if isinstance(left, str) and isinstance(right, str):
                return right.strip().lower() in left.strip().lower()
            return right in left
        if op == "not_contains":
            return not self.compare(left, "contains", right)
        raise SimulatorError(f"Unsupported op: {op}")

    def handle_armor_break_mechanics(self, actor: Optional[UnitState], target: UnitState, packet: dict[str, Any], result: dict[str, Any], ctx: dict[str, Any]) -> None:
        for st, payload in list(self.iter_status_modifier_payloads(target, "armor_layers")):
            if not isinstance(payload, dict):
                continue
            self.commit_status_stacks(
                target,
                st,
                0,
                reason="armor_layers:weakness_break",
                ctx=ctx,
                payload={"packet_id": packet.get("id"), "actor_id": actor.id if actor is not None else None},
            )
            self.state.log_event("enemy_mechanic", f"{target.id}.{st.id} armor broken", {"unit": target.id, "status": st.id})
            hp_ratio = coerce_float(payload.get("on_break_self_imaginary_damage_max_hp_ratio", 0.0))
            if hp_ratio > EPS:
                self.apply_effect({"type": "damage_unit", "target": target.id, "amount": target.max_hp * hp_ratio, "element": "imaginary", "ignore_shield": True}, ctx)
            delay_ratio = coerce_float(payload.get("on_break_action_delay_ratio", 0.0))
            if delay_ratio > EPS:
                self.apply_effect({"type": "delay_action", "target": target.id, "percent": delay_ratio}, ctx)
            energy_ratio = coerce_float(payload.get("on_break_energy_restore_max_energy_ratio_to_breaker", 0.0))
            if energy_ratio > EPS and actor is not None:
                self.apply_effect({"type": "modify_energy", "target": actor.id, "amount": actor.max_energy * energy_ratio}, ctx)

    def apply_kill_energy_for_effect_damage(self, actor: Optional[UnitState], target: UnitState, ctx: dict[str, Any]) -> None:
        """Grant kill energy when an action-owned damage_unit effect defeats a target.

        Normal damage packets already call apply_kill_energy before after_defeat_enemy
        triggers.  damage_unit effects can also be part of an attack/action, so they
        need the same ordering; otherwise after_defeat_enemy trigger conditions see
        pre-kill energy and fixed/true-damage kills never award kill energy.
        """
        if actor is None:
            return
        action = ctx.get("action", {}) or {}
        if not isinstance(action, dict) or not action:
            return
        self.apply_kill_energy(actor, target, action)

    def queued_action_carry_across_wave(self, eff: dict[str, Any], queued_action: dict[str, Any], default: bool = True) -> bool:
        """Resolve whether a queued action survives a wave transition.

        Priority:
        1. The queueing effect itself, for case-specific overrides.
        2. The queued action definition's queue metadata, so character modeling can
           encode whether that specific extra action / auto action carries across
           waves without repeating it in every trigger.
        3. Default True for backwards compatibility.
        """
        for source in (
            eff,
            queued_action.get("queued_action_policy", {}) or {},
            queued_action.get("queue_policy", {}) or {},
            queued_action.get("queue_behavior", {}) or {},
            queued_action,
        ):
            if not isinstance(source, dict):
                continue
            for key in ("carry_across_wave", "carries_across_wave"):
                if key in source:
                    return coerce_bool(source.get(key), default=default)
        return default


    def queued_action_metadata_sources(self, queued_action: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            queued_action.get("queued_action_policy", {}) or {},
            queued_action.get("queue_policy", {}) or {},
            queued_action.get("queue_behavior", {}) or {},
            queued_action,
        ]

    def queued_action_turn_kind(self, eff: dict[str, Any], queued_action: dict[str, Any], queue_name: str) -> Optional[str]:
        """Resolve queued turn kind from effect, action metadata, queue name, or tags.

        Reappearance-like actions must tick extra-turn lifecycles even when the
        trigger only says "queue this action". Encoding turn_kind on the action
        definition keeps character-specific text semantics in the character model
        instead of repeating them in every trigger.
        """
        if eff.get("turn_kind") is not None:
            return str(eff.get("turn_kind"))
        for source in self.queued_action_metadata_sources(queued_action):
            if isinstance(source, dict) and source.get("turn_kind") is not None:
                return str(source.get("turn_kind"))
        if queue_name == "extra_turn_queue":
            return "extra_turn"
        if queue_name == "ultimate_queue":
            return "ultimate"
        tags = set(normalize_str_list(queued_action.get("tags", [])))
        if "ultimate" in tags:
            return "ultimate"
        if "extra_turn" in tags:
            return "extra_turn"
        return None


    def apply_modify_damage_packet(self, eff: dict[str, Any], ctx: dict[str, Any]) -> None:
        """Mutate the currently resolving damage packet from a before_damage effect."""
        packet = ctx.get("packet")
        if not isinstance(packet, dict):
            self.state.log_event("effect_skip", "modify_damage_packet skipped outside packet context", {"effect": eff})
            return
        field = eff.get("field")
        # Direct shorthand fields used by model data.
        direct_adds = {
            "def_ignore_add": "def_ignore",
            "crit_rate_add": "crit_rate_add",
            "crit_dmg_add": "crit_dmg_add",
            "dmg_bonus_add": "dmg_bonus_add",
            "dmg_bonus_multiplier_add": "dmg_bonus_add",
        }
        for src_key, dst_key in direct_adds.items():
            if src_key in eff:
                old = coerce_float(packet.get(dst_key, 0.0))
                packet[dst_key] = old + coerce_float(eff.get(src_key, 0.0))
                self.state.log_event("effect", f"Modify damage packet {dst_key}: {old} -> {packet[dst_key]}", {"effect": eff, "packet": packet.get("id")})
        if field is None:
            return
        add = coerce_float(eff.get("add", eff.get("amount", 0.0)))
        for expr_key in ("add_expression", "formula", "add_by_superimposition_field"):
            if expr_key in eff:
                add += self.eval_formula(eff.get(expr_key), ctx)
        value = eff.get("value")
        field_alias = {
            "dmg_bonus": "dmg_bonus_add",
            "dmg_bonus_multiplier": "dmg_bonus_add",
            "damage_bonus": "dmg_bonus_add",
            "crit_dmg": "crit_dmg_add",
            "crit_rate": "crit_rate_add",
        }
        dst = field_alias.get(str(field), str(field))
        if value is not None:
            old = packet.get(dst)
            packet[dst] = value
            self.state.log_event("effect", f"Set damage packet {dst}: {old} -> {value}", {"effect": eff, "packet": packet.get("id")})
        else:
            old = coerce_float(packet.get(dst, 0.0))
            packet[dst] = old + add
            self.state.log_event("effect", f"Modify damage packet {dst}: {old} -> {packet[dst]}", {"effect": eff, "packet": packet.get("id")})

    def read_unit_property(self, unit: UnitState, prop: Any) -> Any:
        """Read a TBGD property name from a runtime unit in simulator terms.

        The property model keeps engine-derived properties such as
        AttackConvert explicit and unresolved instead of treating unknown names
        as zero-valued stats.
        """
        desc = describe_engine_property(prop)
        key = desc.simulator_key or str(prop or "")
        if desc.read_policy == "audit_unresolved":
            return None
        if key == "hp":
            return unit.hp
        if key == "max_hp":
            return unit.max_hp
        if key == "speed":
            return self.effective_speed(unit)
        if key == "energy":
            return unit.energy
        if key == "max_energy":
            return unit.max_energy
        if key == "toughness":
            return unit.toughness
        if key == "max_toughness":
            return unit.max_toughness
        if key in unit.flags:
            return unit.flags.get(key)
        if key in unit.stats or key in unit.stat_base or key in unit.stat_pct or key in unit.stat_flat:
            return unit.get_stat(key)
        return None

    def read_status_value(self, unit: UnitState, status_id: Any, value_type: Any = None, key: Any = None) -> Any:
        """Read stack/lifetime/dynamic modifier values from a runtime status."""
        status_id_s = str(status_id) if status_id is not None else None
        value_s = str(value_type or key or "")
        for st in unit.statuses:
            if status_id_s is not None and st.id != status_id_s:
                continue
            if value_s in {"LifeTime", "Lifetime", "Duration", "duration", "duration_value"}:
                return st.duration_value if st.duration_value is not None else 0
            if value_s in {"Layer", "Stack", "StackCount", "stacks", "stack"}:
                return st.stacks
            dyn = st.modifiers.get("dynamic_values") if isinstance(st.modifiers, dict) else None
            if isinstance(dyn, dict) and value_s in dyn:
                return dyn.get(value_s)
            if isinstance(st.modifiers, dict) and value_s in st.modifiers:
                return st.modifiers.get(value_s)
            if key is not None:
                key_s = str(key)
                if isinstance(dyn, dict) and key_s in dyn:
                    return dyn.get(key_s)
                if isinstance(st.modifiers, dict) and key_s in st.modifiers:
                    return st.modifiers.get(key_s)
        return 0

    def runtime_dynamic_values_for_context(self, ctx: dict[str, Any], target_id: str | None = None) -> dict[Any, Any]:
        """Expose canonical runtime dynamic keys for symbolic status formulas.

        Generated StatusTemplates may annotate symbolic operands with runtime
        keys produced by earlier generated effects such as
        SetDynamicValueByProperty.  Keep this as simulator-level canonical
        context: the formula executor sees key/value snapshots, not raw TBGD
        hash semantics.
        """
        values: dict[Any, Any] = {}
        values.update(self.state.global_flags)
        for unit_id in (ctx.get("actor_id"), target_id, ctx.get("target_id"), ctx.get("status_owner_id")):
            if unit_id in self.state.units:
                values.update(self.state.unit(unit_id).flags)
        context = ctx.get("context") if isinstance(ctx.get("context"), dict) else {}
        values.update(context)
        return values

    def read_flag_or_status_value(self, eff: dict[str, Any], ctx: dict[str, Any]) -> Any:
        source_key = eff.get("source_key")
        source_status_id = eff.get("source_status_id")
        if source_status_id:
            source_targets = self.resolve_effect_targets({"target": eff.get("source_target", eff.get("target", "actor"))}, ctx, default="actor")
            if source_targets:
                return self.read_status_value(self.state.unit(source_targets[0]), source_status_id, source_key, source_key)
        if source_key in self.state.global_flags:
            return self.state.global_flags.get(source_key)
        actor_id = ctx.get("actor_id")
        if actor_id in self.state.units and source_key in self.state.unit(actor_id).flags:
            return self.state.unit(actor_id).flags.get(source_key)
        return 0

    def effect_hit_probability(self, gate: dict[str, Any], ctx: dict[str, Any], target_id: str) -> dict[str, Any]:
        """Resolve HSR-style status/debuff hit probability.

        final = base chance * (1 + attacker effect hit) * (1 - defender effect res) * (1 - special/debuff res)
        The caller remains deterministic: route events can force hit/miss, while
        the probability is logged for validation and future stochastic/search modes.
        """
        actor_id = gate.get("actor") or gate.get("source") or ctx.get("actor_id")
        actor = self.state.unit(actor_id) if actor_id in self.state.units else None
        target = self.state.unit(target_id)
        base = coerce_float(gate.get("base_chance", gate.get("base", gate.get("chance", gate.get("probability", 1.0)))), 1.0)
        if actor is not None:
            effect_hit = self.contextual_stat(actor, "effect_hit", {**ctx, "target_id": target_id, "target": target})
        else:
            effect_hit = 0.0
        effect_res = self.contextual_stat(target, "effect_res", {**ctx, "target_id": target_id, "target": target})
        special_res = coerce_float(gate.get("special_res", gate.get("debuff_res", 0.0)), 0.0)
        # Target status modifiers may carry special resistance buckets keyed by
        # status/debuff type.  This is deliberately optional and additive.
        status_tag = str(gate.get("status_tag", gate.get("debuff_type", gate.get("tag", ""))) or "")
        for st, mods in self.applicable_status_modifiers(target, {**ctx, "target_id": target_id, "target": target}):
            special_res += coerce_float(mods.get("debuff_res", 0.0)) * st.stacks
            sub = mods.get("debuff_resistance", {})
            if isinstance(sub, dict) and status_tag:
                special_res += coerce_float(sub.get(status_tag, 0.0)) * st.stacks
        raw = base * (1.0 + effect_hit) * (1.0 - effect_res) * (1.0 - special_res)
        return {
            "base_chance": base,
            "effect_hit": effect_hit,
            "effect_res": effect_res,
            "special_res": special_res,
            "final_chance": clamp(raw, 0.0, 1.0),
            "raw_chance": raw,
            "actor_id": actor_id,
            "target_id": target_id,
        }

    def chance_gate_allows(self, gate: dict[str, Any], ctx: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        """Deterministic runtime gate for generated ByRandomChance predicates.

        If the branch applies a status, the compiler marks ``use_effect_hit`` and
        this reuses the HSR effect-hit/effect-res formula.  Otherwise it remains
        a plain chance gate whose outcome can be forced in route events.
        """
        event_id = gate.get("event_id") or f"{ctx.get('actor_id')}.{ctx.get('status_id','condition')}.chance_gate"
        default_mode = gate.get("mode", gate.get("default", self.settings.get("default_chance_gate_mode", "success")))
        mode = (ctx.get("events") or {}).get(event_id, (self.raw_case.get("events") or {}).get(event_id, default_mode))
        target_id = ctx.get("target_id")
        if gate.get("use_effect_hit") and target_id in self.state.units:
            prob = self.effect_hit_probability(gate, ctx, target_id)
            audit_type = "effect_hit_chance_gate"
        else:
            base = coerce_float(gate.get("base_chance", gate.get("base", gate.get("chance", gate.get("probability", 1.0)))), 1.0)
            prob = {"base_chance": base, "final_chance": clamp(base, 0.0, 1.0), "raw_chance": base, "actor_id": ctx.get("actor_id"), "target_id": target_id}
            audit_type = "plain_chance_gate"
        mode_norm = str(mode).strip().lower() if isinstance(mode, str) else mode
        if mode in (False,) or mode_norm in {"false", "fail", "resisted", "miss", "no", "0", "off"}:
            return False, {"event_id": event_id, "mode": mode, "gate_type": audit_type, **prob}
        if mode in (True,) or mode_norm in {"true", "success", "hit", "yes", "1", "on", "guaranteed", "always"}:
            return True, {"event_id": event_id, "mode": mode, "gate_type": audit_type, **prob}
        if mode_norm in {"threshold", "needs_100", "require_100"}:
            return prob.get("final_chance", 1.0) >= 1.0 - EPS, {"event_id": event_id, "mode": mode, "gate_type": audit_type, **prob}
        return True, {"event_id": event_id, "mode": mode, "gate_type": audit_type, **prob}

    def effect_hit_gate_allows(self, gate: Any, eff: dict[str, Any], ctx: dict[str, Any], target_id: str) -> tuple[bool, dict[str, Any]]:
        if gate is None:
            return True, {}
        if not isinstance(gate, dict):
            allowed = coerce_bool(gate, default=True)
            return allowed, {"mode": gate, "allowed": allowed}
        event_id = gate.get("event_id") or eff.get("event_id") or f"{ctx.get('actor_id')}.{eff.get('status',{}).get('id','status')}.{target_id}.effect_hit"
        default_mode = gate.get("mode", gate.get("default", self.settings.get("default_effect_hit_mode", "success")))
        mode = (ctx.get("events") or {}).get(event_id, (self.raw_case.get("events") or {}).get(event_id, default_mode))
        prob = self.effect_hit_probability(gate, ctx, target_id) if any(k in gate for k in ("base_chance", "base", "chance", "probability")) else {}
        mode_norm = str(mode).strip().lower() if isinstance(mode, str) else mode
        if mode in (False,) or mode_norm in {"false", "fail", "resisted", "miss", "no", "0", "off"}:
            return False, {"event_id": event_id, "mode": mode, **prob}
        if mode in (True,) or mode_norm in {"true", "success", "hit", "yes", "1", "on"}:
            return True, {"event_id": event_id, "mode": mode, **prob}
        if mode_norm in {"guaranteed", "always"}:
            return True, {"event_id": event_id, "mode": mode, **prob}
        if mode_norm in {"threshold", "needs_100", "require_100"}:
            return prob.get("final_chance", 1.0) >= 1.0 - EPS, {"event_id": event_id, "mode": mode, **prob}
        # Deterministic route validation defaults to applying the status and
        # logging the probability.  Stochastic/search modes can override via events.
        return True, {"event_id": event_id, "mode": mode, **prob}

    def apply_status_resource_side_effects(self, unit: UnitState, status: StatusEffect, ctx: Optional[dict[str, Any]] = None) -> None:
        """Apply non-stat resource side effects carried by formula-bucket hints.

        HPAddedRatio changes max HP and increases current HP by the same delta.
        MaxSP changes the team skill-point cap; current SP is not increased when
        the cap rises and is clamped if the cap falls.
        """
        mods = status.modifiers if isinstance(status.modifiers, dict) else {}
        hp_delta = 0.0
        if "max_hp_pct_delta" in mods:
            hp_delta += unit.max_hp * coerce_float(mods.get("max_hp_pct_delta", 0.0)) * status.stacks
        if "max_hp_add_delta" in mods:
            hp_delta += coerce_float(mods.get("max_hp_add_delta", 0.0)) * status.stacks
        if "max_hp_from_team_hp_pct" in mods:
            team_side = unit.side
            team_max_hp = sum(u.max_hp for u in self.state.units.values() if u.side == team_side and u.alive)
            hp_delta += team_max_hp * coerce_float(mods.get("max_hp_from_team_hp_pct", 0.0)) * status.stacks
        if abs(hp_delta) > EPS and not mods.get("__hp_added_ratio_applied"):
            old_hp, old_max = unit.hp, unit.max_hp
            self.commit_unit_max_hp(
                unit,
                unit.max_hp + hp_delta,
                reason=f"status:{status.id}:max_hp_side_effect",
                ctx=ctx,
                payload={"status_id": status.id, "hp_delta": hp_delta, "property": "HPAddedRatio/max_hp_from_team_hp_pct"},
            )
            self.commit_unit_hp(
                unit,
                unit.hp + hp_delta,
                reason=f"status:{status.id}:max_hp_side_effect",
                ctx=ctx,
                payload={"status_id": status.id, "hp_delta": hp_delta, "property": "HPAddedRatio/max_hp_from_team_hp_pct"},
            )
            self.commit_status_modifier(
                unit,
                status,
                "__hp_added_ratio_applied",
                True,
                reason=f"status:{status.id}:max_hp_side_effect_marker",
                ctx=ctx,
                payload={"hp_delta": hp_delta},
            )
            self.commit_status_modifier(
                unit,
                status,
                "__applied_max_hp_delta",
                hp_delta,
                reason=f"status:{status.id}:max_hp_side_effect_marker",
                ctx=ctx,
                payload={"hp_delta": hp_delta},
            )
            self.state.log_event("resource", f"{unit.id} max_hp {old_max:.3f}->{unit.max_hp:.3f}, hp {old_hp:.3f}->{unit.hp:.3f}", {"status_id": status.id, "hp_delta": hp_delta, "property": "HPAddedRatio/max_hp_from_team_hp_pct", "modifiers": deepcopy(mods)})
        sp_delta = coerce_int(mods.get("skill_point_cap_add", 0), 0)
        if sp_delta and not mods.get("__skill_point_cap_applied"):
            old_cap, old_sp = self.state.skill_point_cap, self.state.skill_points
            self.commit_skill_point_cap(
                self.state.skill_point_cap + sp_delta,
                reason=f"status:{status.id}:skill_point_cap_add",
                ctx=ctx,
                payload={"status_id": status.id, "property": "MaxSP", "unit_id": unit.id},
            )
            if self.state.skill_points > self.state.skill_point_cap:
                self.commit_skill_points(
                    self.state.skill_point_cap,
                    reason=f"status:{status.id}:skill_points_clamp",
                    ctx=ctx,
                    payload={"status_id": status.id, "old_skill_points": old_sp},
                )
            self.commit_status_modifier(
                unit,
                status,
                "__skill_point_cap_applied",
                True,
                reason=f"status:{status.id}:skill_point_cap_marker",
                ctx=ctx,
                payload={"sp_delta": sp_delta},
            )
            self.commit_status_modifier(
                unit,
                status,
                "__applied_skill_point_cap_delta",
                sp_delta,
                reason=f"status:{status.id}:skill_point_cap_marker",
                ctx=ctx,
                payload={"sp_delta": sp_delta},
            )
            self.state.log_event("resource", f"skill point cap {old_cap}->{self.state.skill_point_cap}", {"status_id": status.id, "old_skill_points": old_sp, "new_skill_points": self.state.skill_points, "property": "MaxSP"})

    def remove_status_resource_side_effects(self, unit: UnitState, status: StatusEffect, ctx: Optional[dict[str, Any]] = None) -> None:
        mods = status.modifiers if isinstance(status.modifiers, dict) else {}
        # Timed shield status support for live replay. Some shields are imported
        # as already-applied numeric shield values, but their status duration must
        # still remove the remaining shield when it expires. If the shield has
        # been partially absorbed, remove only what remains.
        shield_remove = coerce_float(mods.get("shield_expire_remove_amount", mods.get("__applied_shield_delta", 0.0)), 0.0)
        if shield_remove > EPS:
            old_shield = unit.shield
            self.commit_unit_shield(
                unit,
                unit.shield - min(unit.shield, shield_remove),
                reason=f"status:{status.id}:shield_side_effect_removed",
                ctx=ctx,
                payload={"status_id": status.id, "remove_amount": shield_remove},
            )
            self.state.log_event("resource", f"{unit.id}.{status.id} shield side effect removed", {"old_shield": old_shield, "new_shield": unit.shield, "remove_amount": shield_remove})
        hp_delta = coerce_float(mods.get("__applied_max_hp_delta", 0.0))
        if abs(hp_delta) > EPS:
            old_hp, old_max = unit.hp, unit.max_hp
            self.commit_unit_max_hp(
                unit,
                unit.max_hp - hp_delta,
                reason=f"status:{status.id}:max_hp_side_effect_removed",
                ctx=ctx,
                payload={"status_id": status.id, "hp_delta": -hp_delta, "property": "HPAddedRatio/max_hp_from_team_hp_pct", "removed": True},
            )
            self.commit_unit_hp(
                unit,
                min(unit.hp, unit.max_hp),
                reason=f"status:{status.id}:max_hp_side_effect_removed",
                ctx=ctx,
                payload={"status_id": status.id, "hp_delta": -hp_delta, "property": "HPAddedRatio/max_hp_from_team_hp_pct", "removed": True},
            )
            self.state.log_event("resource", f"{unit.id} max_hp {old_max:.3f}->{unit.max_hp:.3f}, hp {old_hp:.3f}->{unit.hp:.3f}", {"status_id": status.id, "hp_delta": -hp_delta, "property": "HPAddedRatio/max_hp_from_team_hp_pct", "removed": True})
        sp_delta = coerce_int(mods.get("__applied_skill_point_cap_delta", 0), 0)
        if sp_delta:
            old_cap, old_sp = self.state.skill_point_cap, self.state.skill_points
            self.commit_skill_point_cap(
                self.state.skill_point_cap - sp_delta,
                reason=f"status:{status.id}:skill_point_cap_remove",
                ctx=ctx,
                payload={"status_id": status.id, "property": "MaxSP", "unit_id": unit.id, "removed": True},
            )
            if self.state.skill_points > self.state.skill_point_cap:
                self.commit_skill_points(
                    self.state.skill_point_cap,
                    reason=f"status:{status.id}:skill_points_clamp",
                    ctx=ctx,
                    payload={"status_id": status.id, "old_skill_points": old_sp, "removed": True},
                )
            self.state.log_event("resource", f"skill point cap {old_cap}->{self.state.skill_point_cap}", {"status_id": status.id, "old_skill_points": old_sp, "new_skill_points": self.state.skill_points, "property": "MaxSP", "removed": True})

    def apply_effect(self, eff: dict[str, Any], ctx: dict[str, Any]) -> None:
        etype = eff.get("type")
        # Model-pack aliases: allow high-level template effects to execute in the
        # route validator without pre-translating every YAML file.
        if etype == "add_or_refresh_stack":
            status_id = eff.get("status_id") or eff.get("buff_id") or eff.get("id")
            if not status_id:
                raise SimulatorError("add_or_refresh_stack requires status_id")
            stacks = self.resolve_numeric_expr(eff.get("stacks", eff.get("amount", 1)), ctx, default=1.0)
            max_stacks = self.resolve_numeric_expr(eff.get("max_stacks", stacks), ctx, default=stacks)
            aliased = deepcopy(eff)
            aliased["type"] = "add_status"
            aliased["stacks"] = int(stacks)
            aliased["max_stacks"] = int(max_stacks)
            aliased["status"] = self.materialize_status(str(status_id), ctx, {"stacks": int(stacks), "max_stacks": int(max_stacks), "refresh_duration": True})
            return self.apply_effect(aliased, ctx)
        if etype in {"add_buff", "apply_status", "add_prebattle_status", "add_buff_on_battle_start"}:
            status = eff.get("status")
            if status is None:
                status_id = eff.get("buff_id") or eff.get("status_id") or eff.get("id")
                status = status_id if status_id else None
            if status is None:
                raise SimulatorError(f"{etype} requires status, status_id, or buff_id")
            aliased = deepcopy(eff)
            aliased["type"] = "add_status"
            aliased["status"] = self.materialize_status(status, ctx, eff)
            return self.apply_effect(aliased, ctx)
        if etype in {"remove_buff", "dispel_buff", "remove_status_effect"}:
            aliased = deepcopy(eff)
            aliased["type"] = "remove_status"
            aliased.setdefault("status_id", eff.get("buff_id") or eff.get("id"))
            return self.apply_effect(aliased, ctx)
        if etype == "follow_up_attack" and eff.get("damage_packets"):
            actor_id = eff.get("actor") or eff.get("actor_id") or ctx.get("actor_id")
            # Attached units such as Souldragon may not be modeled as standalone
            # timeline units in a reduced route case. Use the current owner/actor
            # as the executor while preserving packet scaling refs like
            # dan_heng_permansor_terrae.atk.
            if actor_id not in self.state.units:
                actor_id = ctx.get("actor_id")
            synthetic = {
                "id": eff.get("id", "follow_up_attack"),
                "actor_id": actor_id,
                "tags": normalize_str_list(eff.get("tags", [])) + ["attack", "follow_up_damage", "can_trigger_kill_energy"],
                "cost": {"skill_points": 0},
                "energy_gain": eff.get("energy_gain", {"base_energy_gain": 0, "affected_by_err": False}),
                "damage_packets": eff.get("damage_packets", []),
                "target_policy": eff.get("target_policy", "all_enemies"),
            }
            targets = self.resolve_effect_targets(eff, ctx, default=synthetic.get("target_policy", "all_enemies"))
            if not targets:
                targets = self.select_targets(synthetic, ctx)
            targets = self.derived_damage_live_targets(targets, ctx, effect_name=str(eff.get("id") or "follow_up_attack"))
            if not targets:
                return None
            return self.resolve_action(synthetic, targets, ctx.get("events", {}), context={"queued": True, "turn_kind": eff.get("turn_kind")})
        if etype in {"enqueue_extra_turn", "launch_follow_up_attack"}:
            actor_id = eff.get("actor") or eff.get("actor_id") or ctx.get("actor_id")
            explicit_action = eff.get("action") or eff.get("action_id") or eff.get("extra_turn_action") or eff.get("follow_up_action")
            if etype == "enqueue_extra_turn" and not explicit_action:
                queue_name = eff.get("queue", "extra_turn_queue")
                queued = {
                    "actor": actor_id,
                    "action": None,
                    "extra_turn_type": eff.get("extra_turn_type", "extra_turn"),
                    "turn_kind": eff.get("turn_kind", "extra_turn"),
                    "queued_wave_index": self.state.wave_index,
                    "carry_across_wave": self.queued_action_carry_across_wave(eff, {}, default=False),
                    "events": eff.get("events", {}),
                }
                self.commit_queue_append(
                    queue_name if queue_name in {"ultimate_queue", "immediate_queue", "interrupt_queue", "extra_turn_queue"} else "interrupt_queue",
                    queued,
                    reason="effect:enqueue_extra_turn",
                    ctx=ctx,
                    payload={"effect": deepcopy(eff), "requested_queue": queue_name},
                )
                self.state.log_event("effect", f"Extra turn grant queued for {actor_id}", queued)
                return
            action_id = explicit_action or eff.get("extra_turn_type")
            aliased = deepcopy(eff)
            aliased["type"] = "launch_action"
            aliased["actor"] = actor_id
            aliased["action"] = action_id
            aliased.setdefault("queue", eff.get("queue", "extra_turn_queue" if etype == "enqueue_extra_turn" else "immediate_queue"))
            aliased.setdefault("turn_kind", "extra_turn" if etype == "enqueue_extra_turn" else None)
            return self.apply_effect(aliased, ctx)
        # For normal effects, `condition` is an effect-level gate. For
        # conditional_branch, the same field is the branch selector and must allow
        # effects_if_false to execute when false.
        if etype != "conditional_branch" and "condition" in eff and not self.eval_condition(eff.get("condition"), ctx):
            self.state.log_event("effect_skip", f"Effect {eff.get('type')} skipped by condition", {"effect": eff})
            return
        if etype == "add_status":
            eff = deepcopy(eff)
            eff["status"] = self.materialize_status(eff.get("status"), ctx, eff)
            # Optional effect-hit gate for debuffs / conditional status applications.
            # Do not use ``eff.get("effect_hit") or eff.get("chance")`` here:
            # an explicit false value is meaningful and must not be discarded.
            if "effect_hit" in eff:
                gate = eff.get("effect_hit")
            else:
                gate = eff.get("chance") if "chance" in eff else None
            if gate is not None and not isinstance(gate, dict) and not coerce_bool(gate, default=True):
                self.state.log_event("effect_skip", f"Status {eff['status']['id']} skipped by chance/effect_hit=false")
                return
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                allowed, hit_audit = self.effect_hit_gate_allows(gate, eff, ctx, target_id)
                if hit_audit:
                    self.state.log_event("effect_hit_check", f"Status {eff['status']['id']} effect-hit check on {target_id}", hit_audit)
                if not allowed:
                    self.state.log_event("effect_skip", f"Status {eff['status']['id']} failed effect-hit gate", hit_audit)
                    continue
                unit = self.state.unit(target_id)
                old_speed = self.effective_speed(unit)
                status = StatusEffect.from_dict(eff["status"], runtime_values_by_key=self.runtime_dynamic_values_for_context(ctx, target_id))
                if status.source_id is None:
                    status.source_id = ctx.get("actor_id")
                status = self.normalize_attack_convert_status_for_target(status, target_id, ctx)
                before = next((s for s in unit.statuses if s.id == status.id), None)
                before_stacks = before.stacks if before else 0
                after_status = self.merged_status_for_add(before, status)
                if self.state.global_flags.get("_active_turn_token") is not None:
                    after_status.modifiers.setdefault("_created_turn_token", self.state.global_flags.get("_active_turn_token"))
                    after_status.modifiers.setdefault("_created_turn_actor_id", self.state.global_flags.get("_active_turn_actor_id"))
                    after_status.modifiers.setdefault("_created_turn_kind", self.state.global_flags.get("_active_turn_kind"))
                self.commit_status_entry(
                    unit,
                    after_status,
                    reason="effect:add_status" if before is None else "effect:refresh_status",
                    ctx=ctx,
                    payload={"effect": deepcopy(eff), "incoming_status": status.to_json()},
                    change_kind="add" if before is None else "refresh",
                )
                after = next((s for s in unit.statuses if s.id == status.id), after_status)
                if before is None:
                    self.apply_status_resource_side_effects(unit, after, ctx=ctx)
                self.recalculate_remaining_av_for_speed_change(unit, old_speed, reason="add_status", ctx=ctx)
                self.state.log_event("effect", f"Add status {status.id} to {target_id}", {"status": after.to_json(), "was_present": before is not None, "old_stacks": before_stacks, "new_stacks": after.stacks})
                # Phase 2: 状态记录
                self._settle(ctx, "status",
                    status_id=status.id, target_unit_id=target_id, source_unit_id=status.source_id or "",
                    change_type="add" if before is None else "refresh",
                    stacks_before=before_stacks, stacks_after=after.stacks,
                    max_stacks=after.max_stacks, duration_type=str(after.duration_type or ""),
                    duration_value=after.duration_value or 0,
                    modifier_keys=sorted(after.modifiers.keys()) if after.modifiers else [],
                    trigger_reason=f"effect:{ctx.get('action', {}).get('id', ctx.get('actor_id', '?'))}",
                    record_state_change=False,
                )
                lifecycle_ctx = {**ctx, "target_id": target_id, "target": unit, "status_id": after.id, "status": after, "trigger": {"status_id": after.id}, "status_owner_id": target_id}
                self.run_triggers("status_stack" if before is not None else "status_create", lifecycle_ctx)
                watcher_depth = coerce_int(ctx.get("watcher_depth", 0), 0) + 1
                self.run_triggers("ability_property_change", {**lifecycle_ctx, "watcher_depth": watcher_depth, "context": {**lifecycle_ctx.get("context", {}), "phase": "ability_property_change", "reason": "status_added"}})
                self.run_triggers("status_dynamic_value_change", {**lifecycle_ctx, "watcher_depth": watcher_depth, "context": {**lifecycle_ctx.get("context", {}), "phase": "status_dynamic_value_change", "reason": "status_added"}})
        elif etype == "remove_status":
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                unit = self.state.unit(target_id)
                old_speed = self.effective_speed(unit)
                status_id = str(eff["status_id"])
                removed = next((s for s in unit.statuses if s.id == status_id), None)
                if removed is not None:
                    self.remove_status_resource_side_effects(unit, removed, ctx=ctx)
                    self.commit_status_remove(
                        unit,
                        removed,
                        reason="effect:remove_status",
                        ctx=ctx,
                        payload={"effect": deepcopy(eff), "removed_status": removed.to_json()},
                    )
                self.recalculate_remaining_av_for_speed_change(unit, old_speed, reason="remove_status", ctx=ctx)
                self.state.log_event("effect", f"Remove status {status_id} from {target_id}")
                # Phase 2: 状态移除记录
                if removed is not None:
                    self._settle(ctx, "status",
                        status_id=status_id, target_unit_id=target_id, source_unit_id=removed.source_id or "",
                        change_type="remove", stacks_before=removed.stacks, stacks_after=0,
                        max_stacks=removed.max_stacks, duration_type=str(removed.duration_type or ""),
                        duration_value=0, modifier_keys=sorted(removed.modifiers.keys()) if removed.modifiers else [],
                        trigger_reason=f"effect_remove:{ctx.get('action', {}).get('id', ctx.get('actor_id', '?'))}",
                        record_state_change=False,
                    )
                if removed is not None:
                    lifecycle_ctx = {**ctx, "target_id": target_id, "target": unit, "status_id": status_id, "status": removed, "removed_status": removed, "trigger": {"status_id": status_id}, "status_owner_id": target_id}
                    self.run_triggers("status_destroy", lifecycle_ctx)
                    self.run_triggers("ability_property_change", {**lifecycle_ctx, "context": {**lifecycle_ctx.get("context", {}), "phase": "ability_property_change", "reason": "status_removed"}})
                    self.run_triggers("status_dynamic_value_change", {**lifecycle_ctx, "context": {**lifecycle_ctx.get("context", {}), "phase": "status_dynamic_value_change", "reason": "status_removed"}})
        elif etype == "set_unit_resource":
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                unit = self.state.unit(target_id)
                audit = {"target": target_id}
                for key in ("hp", "max_hp", "shield", "energy", "max_energy", "remaining_av", "toughness", "max_toughness"):
                    if key in eff:
                        old = getattr(unit, key)
                        val = coerce_float(eff.get(key), old)
                        if key == "hp":
                            val = max(0.0, min(val, unit.max_hp))
                            self.commit_unit_hp(unit, val, reason="effect:set_resources:hp", ctx=ctx, payload={"effect": deepcopy(eff)})
                            self.commit_unit_alive(unit, val > EPS, reason="effect:set_resources:hp_alive", ctx=ctx, payload={"hp": val})
                            audit[key] = {"old": old, "new": unit.hp}
                            audit["alive"] = unit.alive
                            continue
                        if key == "max_hp":
                            val = max(0.0, val)
                            self.commit_unit_max_hp(unit, val, reason="effect:set_resources:max_hp", ctx=ctx, payload={"effect": deepcopy(eff)})
                            audit[key] = {"old": old, "new": unit.max_hp}
                            continue
                        if key == "shield":
                            val = max(0.0, val)
                            self.commit_unit_shield(unit, val, reason="effect:set_resources:shield", ctx=ctx, payload={"effect": deepcopy(eff)})
                            audit[key] = {"old": old, "new": unit.shield}
                            continue
                        if key == "energy":
                            val = max(0.0, min(val, unit.max_energy))
                            self.commit_unit_energy(unit, val, reason="effect:set_resources:energy", ctx=ctx, payload={"effect": deepcopy(eff)})
                            audit[key] = {"old": old, "new": unit.energy}
                            continue
                        if key == "remaining_av":
                            val = max(0.0, val)
                            self.commit_unit_remaining_av(unit, val, reason="effect:set_resources:remaining_av", ctx=ctx, payload={"effect": deepcopy(eff)})
                            audit[key] = {"old": old, "new": unit.remaining_av}
                            continue
                        if key in {"shield", "remaining_av", "toughness", "max_toughness", "max_hp", "max_energy"}:
                            val = max(0.0, val)
                        setattr(unit, key, val)
                        audit[key] = {"old": old, "new": val}
                if "alive" in eff:
                    self.commit_unit_alive(unit, coerce_bool(eff.get("alive"), default=unit.alive), reason="effect:set_resources:alive", ctx=ctx, payload={"effect": deepcopy(eff)})
                    audit["alive"] = unit.alive
                self.state.log_event("effect", f"Set resources for {target_id}", audit)
        elif etype == "set_status_stacks":
            status_id = str(eff.get("status_id") or eff.get("id") or "")
            if not status_id:
                self.state.log_event("effect_skip", "set_status_stacks skipped without status_id", {"effect": eff})
            else:
                for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                    unit = self.state.unit(target_id)
                    st = next((row for row in unit.statuses if row.id == status_id), None)
                    if st is None:
                        self.state.log_event("effect_skip", f"set_status_stacks skipped missing {target_id}.{status_id}", {"effect": eff})
                        continue
                    old = st.stacks
                    old_duration = st.duration_value
                    self.commit_status_stacks(
                        unit,
                        st,
                        max(0, coerce_int(eff.get("stacks", old), old)),
                        reason="effect:set_status_stacks:stacks",
                        ctx=ctx,
                        payload={"effect": deepcopy(eff)},
                    )
                    if "max_stacks" in eff:
                        self.commit_status_field(
                            unit,
                            st,
                            "max_stacks",
                            max(st.stacks, coerce_int(eff.get("max_stacks", st.max_stacks), st.max_stacks)),
                            reason="effect:set_status_stacks:max_stacks",
                            ctx=ctx,
                            payload={"effect": deepcopy(eff)},
                        )
                    if "duration_value" in eff:
                        self.commit_status_duration_value(
                            unit,
                            st,
                            coerce_int(eff.get("duration_value"), st.duration_value or 0),
                            reason="effect:set_status_stacks:duration_value",
                            ctx=ctx,
                            payload={"effect": deepcopy(eff), "old_duration_value": old_duration},
                        )
                    self.state.log_event("effect", f"Set {target_id}.{status_id} stacks {old}->{st.stacks}", {"old": old, "new": st.stacks, "duration_value": st.duration_value})
        elif etype == "set_global_resource":
            if "skill_points" in eff:
                old = self.state.skill_points
                self.commit_skill_points(
                    coerce_float(eff.get("skill_points"), old),
                    reason="effect:set_global_resource:skill_points",
                    ctx=ctx,
                    payload={"effect": deepcopy(eff)},
                )
                self.state.log_event("effect", "Set global skill_points", {"old": old, "new": self.state.skill_points})
            if "skill_point_cap" in eff:
                old = self.state.skill_point_cap
                self.commit_skill_point_cap(
                    coerce_float(eff.get("skill_point_cap"), old),
                    reason="effect:set_global_resource:skill_point_cap",
                    ctx=ctx,
                    payload={"effect": deepcopy(eff)},
                )
                if self.state.skill_points > self.state.skill_point_cap:
                    self.commit_skill_points(
                        self.state.skill_point_cap,
                        reason="effect:set_global_resource:skill_points_clamp",
                        ctx=ctx,
                        payload={"old_skill_points": self.state.skill_points},
                    )
                self.state.log_event("effect", "Set global skill_point_cap", {"old": old, "new": self.state.skill_point_cap})
            if "av" in eff:
                old = self.state.av
                self.commit_global_av(
                    coerce_float(eff.get("av"), old),
                    reason="effect:set_global_resource:av",
                    ctx=ctx,
                    payload={"effect": deepcopy(eff)},
                )
                self.state.log_event("effect", "Set global av", {"old": old, "new": self.state.av})
        elif etype == "modify_energy":
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                u = self.state.unit(target_id)
                amount = coerce_float(eff.get("amount", 0.0))
                if "target_max_energy_pct" in eff:
                    amount += u.max_energy * coerce_float(eff["target_max_energy_pct"])
                if "source_max_energy_pct" in eff:
                    src_id = self.resolve_special_unit(eff.get("source", "actor"), ctx)
                    amount += self.state.unit(src_id).max_energy * coerce_float(eff["source_max_energy_pct"])
                old = u.energy
                self.commit_unit_energy(
                    u,
                    u.energy + amount,
                    reason="effect:modify_energy",
                    ctx=ctx,
                    payload={"amount": amount, "effect": deepcopy(eff)},
                )
                self.state.log_event("effect", f"{target_id} energy modified by {amount:.3f}", {"old": old, "new": u.energy})
                # Phase 2: 能量修改记录
                self._settle(ctx, "energy",
                    unit_id=target_id, delta=u.energy - old,
                    old_value=old, new_value=u.energy, max_energy=u.max_energy,
                    source_type=ENERGY_SOURCE_EFFECT,
                    source_detail=f"modify_energy: {ctx.get('action', {}).get('id', ctx.get('actor_id', '?'))}",
                    record_state_change=False,
                )
        elif etype in {"gain_energy", "grant_energy"}:
            source = deepcopy(eff.get("energy_gain", eff))
            if (
                "amount" in eff
                and "base" not in source
                and "base_energy_gain" not in source
                and "fixed" not in source
                and "fixed_energy_gain_not_affected_by_err" not in source
            ):
                # Model-pack shorthand often writes `amount: 30` plus
                # `affected_by_err: true`. Preserve that semantic: an amount that
                # is explicitly ERR-affected must become base energy, not fixed
                # energy. If the flag is omitted, keep the historical fixed-energy
                # behavior for compatibility.
                affected = coerce_bool(eff.get("affected_by_err", False), default=False)
                amount_value = self.resolve_numeric_expr(eff.get("amount", 0.0), ctx, default=coerce_float(eff.get("amount", 0.0)))
                if "energy_per_hit" in eff:
                    # Generic helper for effects such as Tribbie A6:
                    # gain X energy for each target hit by the triggering attack.
                    amount_value += coerce_float(eff.get("energy_per_hit", 0.0)) * coerce_float(ctx.get("hit_target_count", 0.0))
                if affected:
                    source["base"] = amount_value
                else:
                    source["fixed"] = amount_value
                source["affected_by_err"] = affected
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                self.apply_energy_source(self.state.unit(target_id), source, f"effect:{etype}", default_affected_by_err=True, ctx=ctx)
        elif etype == "consume_energy":
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                u = self.state.unit(target_id)
                amount = coerce_float(eff.get("amount", eff.get("energy", 0.0)))
                old = u.energy
                self.commit_unit_energy(
                    u,
                    u.energy - amount,
                    reason="effect:consume_energy",
                    ctx=ctx,
                    payload={"amount": amount, "effect": deepcopy(eff)},
                )
                self.state.log_event("effect", f"{target_id} consumes {amount:.3f} energy", {"old": old, "new": u.energy})
                # Phase 2: 能量消耗记录
                self._settle(ctx, "energy",
                    unit_id=target_id, delta=u.energy - old,
                    old_value=old, new_value=u.energy, max_energy=u.max_energy,
                    source_type=ENERGY_SOURCE_COST,
                    source_detail=f"consume_energy: {ctx.get('action', {}).get('id', ctx.get('actor_id', '?'))}",
                    record_state_change=False,
                )
        elif etype == "modify_skill_points":
            amount = coerce_float(eff.get("amount", 0), 0.0)
            old_sp = self.state.skill_points
            self.modify_skill_points_with_overflow(amount, overflow_record=eff.get("overflow_record") if isinstance(eff.get("overflow_record"), dict) else None, reason="effect:modify_skill_points", ctx=ctx)
            # Phase 2: SP 变化记录
            self._settle(ctx, "sp",
                delta=int(amount), old_value=int(old_sp), new_value=self.state.skill_points,
                max_value=self.state.skill_point_cap,
                reason="modify_skill_points" if amount >= 0 else "consume",
                reason_detail=f"effect: {ctx.get('action', {}).get('id', ctx.get('actor_id', '?'))}",
                source_unit_id=str(ctx.get("actor_id", "")),
                record_state_change=False,
            )
        elif etype == "modify_skill_points_from_flag":
            flag = eff.get("flag")
            scale = coerce_float(eff.get("scale", 1.0), 1.0)
            raw = self.state.global_flags.get(str(flag), ctx.get(str(flag), 0))
            amount = coerce_float(raw, 0.0) * scale
            old_sp2 = self.state.skill_points
            result = self.modify_skill_points_with_overflow(amount, overflow_record=eff.get("overflow_record") if isinstance(eff.get("overflow_record"), dict) else None, reason=f"effect:modify_skill_points_from_flag:{flag}", ctx=ctx)
            self.state.log_event("effect", f"Skill points modified from flag {flag} by {amount}", {"old": result["old"], "new": result["new"], "flag_value": raw})
            # Phase 2: SP 变化记录
            self._settle(ctx, "sp",
                delta=int(amount), old_value=int(old_sp2), new_value=self.state.skill_points,
                max_value=self.state.skill_point_cap, reason=f"modify_skill_points_from_flag:{flag}",
                reason_detail=f"flag {flag}={raw}", source_unit_id=str(ctx.get("actor_id", "")),
                record_state_change=False,
            )
        elif etype == "modify_skill_point_cap":
            amount = coerce_int(eff.get("amount", eff.get("delta", 0)), 0)
            old_cap = self.state.skill_point_cap
            self.commit_skill_point_cap(
                self.state.skill_point_cap + amount,
                reason="effect:modify_skill_point_cap",
                ctx=ctx,
                payload={"amount": amount, "effect": deepcopy(eff)},
            )
            if self.state.skill_points > self.state.skill_point_cap:
                self.commit_skill_points(
                    self.state.skill_point_cap,
                    reason="effect:modify_skill_point_cap:skill_points_clamp",
                    ctx=ctx,
                    payload={"old_skill_points": self.state.skill_points},
                )
            self.state.log_event("effect", f"Skill point cap modified by {amount}", {"old": old_cap, "new": self.state.skill_point_cap, "skill_points": self.state.skill_points})
        elif etype == "advance_action":
            # Accept simulator-native `percent`, model-pack `advance_percent`,
            # shorthand `amount`, and light-cone tables such as
            # `advance_percent_by_superimposition: {5: 0.24}`.  If a table is
            # provided without an explicit superimposition in the effect/context,
            # use the highest table entry; this matches reduced validation cases
            # where the equipped S value is already implied by the selected build.
            percent = eff.get("percent", eff.get("advance_percent", eff.get("amount")))
            if percent is None and isinstance(eff.get("advance_percent_by_superimposition"), dict):
                table = eff.get("advance_percent_by_superimposition") or {}
                raw_s = eff.get("superimposition", eff.get("source_superimposition", ctx.get("superimposition")))
                if raw_s is None:
                    keys = []
                    for k in table.keys():
                        try:
                            keys.append(int(k))
                        except Exception:
                            pass
                    raw_s = max(keys) if keys else None
                if raw_s is not None:
                    percent = table.get(raw_s, table.get(str(raw_s)))
            if percent is None:
                raise SimulatorError("advance_action requires percent, advance_percent, amount, or advance_percent_by_superimposition")
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                unit = self.state.unit(target_id)
                old_rem = unit.remaining_av
                old_abs = self.state.av + old_rem
                self.apply_action_advance(unit, coerce_float(percent), ctx=ctx, reason="effect:advance_action")
                # Phase 2: AV 提前记录
                self._settle(ctx, "av",
                    unit_id=target_id, old_remaining_av=old_rem, new_remaining_av=unit.remaining_av,
                    old_absolute_av=old_abs, new_absolute_av=self.state.av + unit.remaining_av,
                    speed=unit.speed, action_interval=self.action_interval(unit),
                    change_type=AV_ADVANCE, change_detail=f"拉条 {coerce_float(percent):.1%}",
                    record_state_change=False,
                )
        elif etype == "delay_action":
            # Accept both simulator-native `percent` and model-pack aliases such
            # as `delay_percent`.
            percent = eff.get("percent", eff.get("delay_percent", eff.get("amount")))
            if percent is None:
                raise SimulatorError("delay_action requires percent or delay_percent")
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                unit = self.state.unit(target_id)
                old_rem = unit.remaining_av
                old_abs = self.state.av + old_rem
                self.apply_action_delay(unit, coerce_float(percent), ctx=ctx, reason="effect:delay_action")
                # Phase 2: AV 延迟记录
                self._settle(ctx, "av",
                    unit_id=target_id, old_remaining_av=old_rem, new_remaining_av=unit.remaining_av,
                    old_absolute_av=old_abs, new_absolute_av=self.state.av + unit.remaining_av,
                    speed=unit.speed, action_interval=self.action_interval(unit),
                    change_type=AV_DELAY, change_detail=f"推条 {coerce_float(percent):.1%}",
                    record_state_change=False,
                )
        elif etype == "set_action_delay":
            # TBGD SetActionDelay uses a normalized delay ratio: 1.0 means the
            # target's remaining AV is set to one full action interval at its
            # current effective speed.  This is distinct from additive delay.
            percent = eff.get("percent", eff.get("delay_percent", eff.get("amount")))
            if percent is None:
                raise SimulatorError("set_action_delay requires percent/delay_percent/amount")
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                unit = self.state.unit(target_id)
                old = unit.remaining_av
                old_abs = self.state.av + old
                self.commit_unit_remaining_av(
                    unit,
                    self.action_interval(unit) * coerce_float(percent),
                    reason="effect:set_action_delay",
                    ctx=ctx,
                    payload={"percent": coerce_float(percent), "action_interval": self.action_interval(unit), "effect": deepcopy(eff)},
                )
                self.state.log_event("av_change", f"{target_id} action delay set to {coerce_float(percent):.1%}", {"old": old, "new": unit.remaining_av})
                # Phase 2: AV 置位记录
                self._settle(ctx, "av",
                    unit_id=target_id, old_remaining_av=old, new_remaining_av=unit.remaining_av,
                    old_absolute_av=old_abs, new_absolute_av=self.state.av + unit.remaining_av,
                    speed=unit.speed, action_interval=self.action_interval(unit),
                    change_type=AV_DELAY, change_detail=f"AV 置位 {coerce_float(percent):.1%}",
                    record_state_change=False,
                )
        elif etype in {"delay_self_action", "delay_next_action"}:
            aliased = deepcopy(eff)
            aliased["type"] = "delay_action"
            aliased.setdefault("target", "actor" if etype == "delay_self_action" else eff.get("target", "target"))
            aliased.setdefault("percent", eff.get("delay_percent", eff.get("amount", 0.0)))
            return self.apply_effect(aliased, ctx)
        elif etype == "set_target":
            status_id = eff.get("status_id") or eff.get("id") or "target_mark"
            targets = self.resolve_effect_targets(eff, ctx, default="target")
            if targets:
                chosen = targets[0]
                self.commit_global_flag(str(status_id), chosen, reason="effect:set_target", ctx=ctx, payload={"effect": deepcopy(eff)})
                # Bondmate is a special character-model alias used by Dan Heng.
                if str(status_id) == "bondmate":
                    self.clear_bondmate_runtime_state(keep_target=chosen, ctx=ctx)
                    self.commit_global_flag("bondmate_target", chosen, reason="effect:set_target:bondmate_target", ctx=ctx, payload={"effect": deepcopy(eff)})
                    self.ensure_bondmate_souldragon(chosen, ctx)
                status = self.materialize_status(status_id, {**ctx, "target_id": chosen}, eff)
                self.apply_effect({"type": "add_status", "status": status, "target": chosen}, ctx)
                if str(status_id) == "bondmate":
                    self.apply_attack_convert_to_bondmate(chosen, ctx.get("actor_id") if ctx.get("actor_id") in self.state.units else None, ctx)
                self.state.log_event("effect", f"Set target mark {status_id} -> {chosen}")
        elif etype == "apply_attack_convert":
            targets = self.resolve_effect_targets(eff, ctx, default="actor")
            source_id = eff.get("source")
            if source_id in {"actor", "self"}:
                source_id = ctx.get("actor_id")
            for target_id in targets:
                self.apply_attack_convert_to_bondmate(target_id, str(source_id) if source_id else None, ctx)
        elif etype == "provide_shield":
            formula = (
                eff.get("shield_formula") or eff.get("shield_formula_at_skill_10")
                or eff.get("shield_formula_at_talent_10") or eff.get("shield_formula_at_ultimate_10")
            )
            amount = coerce_float(eff.get("amount", 0.0)) if formula is None else self.eval_formula(formula, ctx)
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                old_shield = self.state.unit(target_id).shield
                self.apply_stackable_shield(target_id, amount, eff, ctx, reason="provide_shield")
                # Phase 2: 护盾记录
                new_shield = self.state.unit(target_id).shield
                self._settle(ctx, "shield",
                    unit_id=target_id, delta=new_shield - old_shield,
                    old_value=old_shield, new_value=new_shield,
                    reason=f"provide_shield: {ctx.get('action', {}).get('id', ctx.get('actor_id', '?'))}",
                )
        elif etype == "modify_stat":
            if self._is_legacy_danheng_attack_convert_effect(eff):
                aliased = {"type": "apply_attack_convert", "target": eff.get("target", "bondmate"), "source": ctx.get("actor_id"), "semantic": "legacy_modify_stat_attack_convert_redirect"}
                return self.apply_effect(aliased, ctx)
            stat = eff.get("stat")
            if not stat:
                self.state.log_event("effect_skip", "modify_stat skipped without stat", {"effect": eff})
            else:
                amount = coerce_float(eff.get("add", eff.get("amount", 0.0)))
                for key in ("delta_formula_from_bonus_ability", "formula", "add_expression", "add_by_superimposition_field"):
                    if key in eff:
                        amount += self.eval_formula(eff.get(key), ctx)
                for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                    status = {"id": f"stat_mod_{stat}_{len(self.state.unit(target_id).statuses)+1}", "modifiers": {f"{stat}_add": amount}, "source_id": ctx.get("actor_id")}
                    self.apply_effect({"type": "add_status", "status": status, "target": target_id}, ctx)
        elif etype == "add_zone":
            zone_id = eff.get("zone_id") or eff.get("id") or "zone_active"
            self.commit_global_flag(str(zone_id), True, reason="effect:add_zone", ctx=ctx, payload={"effect": deepcopy(eff)})
            self.commit_global_flag("zone_active", True, reason="effect:add_zone:zone_active", ctx=ctx, payload={"effect": deepcopy(eff)})
            self.state.log_event("effect", f"Zone {zone_id} active")
        elif etype in {"remove_zone", "clear_zone", "end_zone"}:
            zone_id = eff.get("zone_id") or eff.get("id")
            if zone_id:
                self.commit_global_flag(str(zone_id), False, reason="effect:remove_zone", ctx=ctx, payload={"effect": deepcopy(eff)})
            else:
                for key in list(self.state.global_flags):
                    if "zone" in str(key).lower():
                        self.commit_global_flag(key, False, reason="effect:remove_zone:clear_all", ctx=ctx, payload={"effect": deepcopy(eff)})
            self.commit_global_flag(
                "zone_active",
                any(bool(v) for k, v in self.state.global_flags.items() if "zone" in str(k).lower() and str(k) != "zone_active"),
                reason="effect:remove_zone:zone_active",
                ctx=ctx,
                payload={"effect": deepcopy(eff)},
            )
            self.state.log_event("effect", f"Zone {zone_id or 'all'} inactive", {"zone_active": self.state.global_flags.get("zone_active")})
            self.expire_statuses_if_zone_inactive(reason="zone_inactive", ctx=ctx)
        elif etype == "gain_skill_point_on_battle_start":
            return self.apply_effect({"type": "gain_skill_point", "amount": eff.get("amount", 0)}, ctx)
        elif etype == "deal_damage":
            packet = eff.get("damage_packet") or eff.get("packet")
            if not packet:
                self.state.log_event("effect_skip", "deal_damage skipped without damage_packet", {"effect": eff})
            else:
                action = deepcopy(ctx.get("action", {})) if isinstance(ctx.get("action"), dict) else {}
                action.setdefault("id", f"effect_{packet.get('id','damage')}")
                action.setdefault("actor_id", ctx.get("actor_id"))
                action.setdefault("tags", normalize_str_list(action.get("tags", [])) + ["attack"])
                packet = self.normalize_damage_packet_schema(packet)
                targets = self.resolve_packet_targets(packet, action, ctx, ctx.get("targets", []))
                targets = self.derived_damage_live_targets(targets, ctx, effect_name=str(eff.get("id") or packet.get("id") or "deal_damage"))
                actor = self.state.unit(action["actor_id"])
                for target_id in targets:
                    if target_id not in self.state.units or not self.state.unit(target_id).alive:
                        continue
                    packet_ctx = {**ctx, "action": action, "packet": packet, "target_id": target_id, "target": self.state.unit(target_id)}
                    self.run_triggers("before_damage", packet_ctx)
                    result = self.resolve_damage_packet(packet, actor, self.state.unit(target_id), action, ctx.get("events", {}))
                    self.apply_damage_result(result, packet_ctx)
                    packet_ctx["damage_result"] = result
                    self.run_triggers("after_damage", packet_ctx)
                    if result.get("target_defeated"):
                        self.note_action_defeat(target_id, actor.id, str(packet.get("damage_type") or "deal_damage"), ctx)
                        self.apply_kill_energy(actor, self.state.unit(target_id), action, ctx=action_ctx)
                        self.run_triggers("after_defeat_enemy", packet_ctx)
        elif etype in {"detonate_dot_damage", "detonate_dots", "trigger_dot_damage_now", "trigger_dots_now"}:
            # Kafka-style immediate DoT settlement baseline.  DoTs resolve in
            # current status order and stop as soon as the target dies.  Kill
            # credit/energy belongs to the unit that applied/generated the DoT,
            # not to the unit that triggered the detonation.
            include_break_dot = coerce_bool(eff.get("include_break_dot", True), default=True)
            for target_id in self.resolve_effect_targets(eff, ctx, default="target"):
                if target_id not in self.state.units:
                    continue
                target = self.state.unit(target_id)
                if not target.alive:
                    continue
                dot_rows = self.detonatable_dot_payloads(target, include_break_dot=include_break_dot)
                if eff.get("status_ids"):
                    wanted = {str(x) for x in (eff.get("status_ids") if isinstance(eff.get("status_ids"), list) else [eff.get("status_ids")])}
                    dot_rows = [(st, payload) for st, payload in dot_rows if st.id in wanted]
                detonated = 0
                for st, payload in dot_rows:
                    if not target.alive:
                        self.state.log_event("derived_damage_skip", f"DoT detonation stopped after {target.id} was defeated", {"target": target.id, "effect": etype, "reason": "dot_target_defeated", "detonated": detonated})
                        break
                    result = self.dot_damage_result_for_status(target, st, payload)
                    if result is None:
                        self.state.log_event("dot_damage_skip", f"{target.id}.{st.id} DoT detonation unresolved", {"unit": target.id, "status": st.id, "payload": payload})
                        continue
                    source_actor = self.state.units.get(str(result.get("actor_id")))
                    dot_action = {"id": eff.get("id", "detonate_dot_damage"), "tags": ["dot_damage", "detonated_dot", "can_trigger_kill_energy"]}
                    dot_ctx = {**ctx, "actor_id": result.get("actor_id"), "actor": source_actor, "target_id": target.id, "target": target, "status": st, "packet": {"id": result.get("packet_id"), "damage_type": result.get("damage_type", "dot_damage"), "element": result.get("element"), "ignore_shield": coerce_bool(payload.get("ignore_shield", False), default=False)}, "action": dot_action}
                    self.apply_damage_result(result, dot_ctx)
                    dot_ctx["damage_result"] = result
                    detonated += 1
                    self.state.log_event("dot_damage", f"{target.id}.{st.id} detonates for {result.get('damage', 0.0):.3f}", {"unit": target.id, "status": st.id, "source": result.get("actor_id"), "damage": result.get("damage"), "damage_type": result.get("damage_type")})
                    self.run_triggers("after_hp_change", dot_ctx)
                    if result.get("target_defeated"):
                        if source_actor is not None:
                            self.note_action_defeat(target.id, source_actor.id, str(result.get("damage_type") or "dot_damage"), ctx)
                            self.apply_kill_energy(source_actor, target, dot_action)
                        self.run_triggers("after_defeat_enemy", dot_ctx)
                        remaining = max(0, len(dot_rows) - detonated)
                        if remaining:
                            self.state.log_event("derived_damage_skip", f"DoT detonation stopped after {target.id} was defeated", {"target": target.id, "effect": etype, "reason": "dot_target_defeated", "detonated": detonated, "remaining_dot_count": remaining})
                        break
                self.state.log_event("effect", f"Detonated {detonated} DoT statuses on {target.id}", {"target": target.id, "detonated": detonated, "effect": etype})
        elif etype == "enhance_souldragon":
            # Generic Souldragon enhancement lifecycle: store both a global audit
            # flag and unit-local counters when the attached unit exists.
            self.commit_global_flag(str(etype), True, reason="effect:enhance_souldragon", ctx=ctx, payload={"effect": deepcopy(eff)})
            added = coerce_int(eff.get("remaining_actions_added", eff.get("remaining_souldragon_actions", self.souldragon_template_value("enhanced_action_count", 2.0))), 0)
            dragon_id = str(eff.get("target") or eff.get("unit_id") or "souldragon")
            if added:
                self.commit_global_flag(
                    "souldragon_enhanced_actions",
                    coerce_float(self.state.global_flags.get("souldragon_enhanced_actions", 0.0)) + added,
                    reason="effect:enhance_souldragon:pending_actions",
                    ctx=ctx,
                    payload={"effect": deepcopy(eff), "added": added},
                )
            if dragon_id in self.state.units:
                dragon = self.state.unit(dragon_id)
                old = coerce_int(dragon.flags.get("remaining_enhanced_actions", 0), 0)
                self.commit_unit_flag(dragon, "is_enhanced", True, reason="effect:enhance_souldragon", ctx=ctx, payload={"effect": deepcopy(eff)})
                self.commit_unit_flag(dragon, "souldragon_enhanced", True, reason="effect:enhance_souldragon", ctx=ctx, payload={"effect": deepcopy(eff)})
                self.commit_unit_flag(dragon, "remaining_enhanced_actions", old + added, reason="effect:enhance_souldragon:remaining_actions", ctx=ctx, payload={"effect": deepcopy(eff), "old": old, "added": added})
                self.state.log_event("summon_lifecycle", f"{dragon_id} enhanced actions {old}->{old+added}", {"unit": dragon_id, "added": added})
            else:
                self.state.log_event("effect", f"Recorded model-pack effect {etype}", {"effect": eff, "unit_missing": dragon_id})
        elif etype in {"apply_enemy_field_status", "auto_use_skill_on_battle_start"}:
            # Minimal model-pack support: these are represented as flags so route
            # cases can branch on them, while exact action execution remains route-driven.
            self.commit_global_flag(str(etype), True, reason=f"effect:{etype}", ctx=ctx, payload={"effect": deepcopy(eff)})
            self.state.log_event("effect", f"Recorded model-pack effect {etype}", {"effect": eff})
        elif etype == "record_skill_property_modifier":
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                unit = self.state.unit(target_id)
                mods = deepcopy(unit.flags.get("skill_property_modifiers", []))
                if not isinstance(mods, list):
                    mods = []
                record = {"skill_name": eff.get("skill_name"), "property": eff.get("property"), "value": eff.get("value")}
                mods.append(record)
                self.commit_unit_flag(unit, "skill_property_modifiers", mods, reason="effect:record_skill_property_modifier", ctx=ctx, payload={"effect": deepcopy(eff), "record": deepcopy(record)})
                self.state.log_event("effect", f"Recorded skill property modifier for {target_id}", record)
        elif etype == "enqueue_extra_turn_by_skill_type":
            actor_id = eff.get("actor") or eff.get("actor_id") or ctx.get("actor_id")
            skill_type = str(eff.get("skill_type") or "")
            action_id = self.find_action_by_skill_type(actor_id, skill_type) if actor_id else None
            if action_id:
                launch_eff = {"type": "launch_action", "actor": actor_id, "action": action_id, "queue": eff.get("queue", "immediate_queue"), "turn_kind": "extra_turn", "extra_turn_type": skill_type}
                if eff.get("target_policy"):
                    launch_eff["target_policy"] = eff.get("target_policy")
                return self.apply_effect(launch_eff, ctx)
            key = f"pending_extra_turn_by_skill_type:{actor_id}:{skill_type}"
            self.commit_global_flag(key, coerce_float(self.state.global_flags.get(key, 0)) + 1, reason="effect:pending_extra_turn_by_skill_type", ctx=ctx, payload={"actor": actor_id, "skill_type": skill_type})
            self.state.log_event("effect", f"Recorded pending extra turn by skill type {skill_type}", {"actor": actor_id, "skill_type": skill_type})
        elif etype == "launch_action":
            actor_id = eff.get("actor") or eff.get("actor_id") or ctx.get("actor_id")
            action_id = eff.get("action") or eff.get("action_id")
            action = self.get_action_def(actor_id, action_id)
            target_policy = eff.get("target_policy") or action.get("target_policy") or "same_target"
            # Do not permanently resolve queued targets too early. If a wave transition
            # happens before the queued action is executed, target selection must be
            # re-evaluated against the then-current enemies. Explicit eff.targets still wins.
            explicit_targets = self.normalize_targets(eff.get("targets")) if "targets" in eff else None
            queue_name = eff.get("queue", "immediate_queue")
            turn_kind = self.queued_action_turn_kind(eff, action, queue_name)
            queued = {
                "actor": actor_id,
                "action": action_id,
                "targets": explicit_targets,
                "defer_target_policy": target_policy,
                "context_target_id": ctx.get("target_id"),
                "events": eff.get("events", {}),
                "turn_kind": turn_kind,
                "extra_turn_type": eff.get("extra_turn_type"),
                "queued_wave_index": self.state.wave_index,
                "carry_across_wave": self.queued_action_carry_across_wave(eff, action, default=True),
                "queued_actor_phase": self.effective_unit_phase(ctx.get("actor") if ctx.get("actor") is not None else (self.state.unit(actor_id) if actor_id in self.state.units else None)),
                "carry_across_phase": coerce_bool(eff.get("carry_across_phase", action.get("carry_across_phase", False) if isinstance(action, dict) else False), default=False),
            }
            # Enemy one-turn multi-action chains must be interruptible.  Preserve
            # chain metadata on the queued continuation so drain_queues can
            # re-check death/break/control right before the follow-up resolves.
            for meta_key in (
                "enemy_action_chain", "enemy_chain_id", "chain_id", "chain_index",
                "interrupt_policy", "interruptible_by_break", "interruptible_by_control",
                "interruptible_by_death", "cancel_chain_on_interrupt",
            ):
                if meta_key in eff:
                    queued[meta_key] = deepcopy(eff.get(meta_key))
                elif isinstance(action, dict) and meta_key in action:
                    queued[meta_key] = deepcopy(action.get(meta_key))
            if eff.get("queue") == "immediate_queue" and ctx.get("actor") is not None and getattr(ctx.get("actor"), "side", None) == "enemy":
                queued.setdefault("enemy_action_chain", coerce_bool(eff.get("enemy_action_chain", action.get("enemy_action_chain", False) if isinstance(action, dict) else False), default=False))
            self.commit_queue_append(
                queue_name,
                queued,
                reason="effect:launch_action",
                ctx=ctx,
                payload={"effect": deepcopy(eff), "requested_queue": queue_name},
            )
            self.state.log_event("effect", f"Queued action {actor_id}.{action_id} in {queue_name}", queued)
        elif etype == "modify_damage_packet":
            self.apply_modify_damage_packet(eff, ctx)
        elif etype == "random_select_flag":
            values = list(eff.get("values") or [])
            if not values or not eff.get("key"):
                self.state.log_event("effect_skip", "random_select_flag skipped without key/values", {"effect": eff})
            else:
                event_id = eff.get("event_id") or f"{ctx.get('actor_id')}.{eff.get('key')}.random_select"
                forced = (ctx.get("events") or {}).get(event_id, (self.raw_case.get("events") or {}).get(event_id, None))
                idx = None
                if forced is not None:
                    if isinstance(forced, str) and forced in values:
                        idx = values.index(forced)
                    else:
                        try:
                            forced_i = int(forced)
                            idx = forced_i if 0 <= forced_i < len(values) else None
                        except Exception:
                            idx = None
                if idx is None:
                    idx = 0
                value = values[idx]
                self.commit_global_flag(str(eff["key"]), coerce_comparison_value(value), reason="effect:random_select_flag", ctx=ctx, payload={"event_id": event_id, "index": idx, "values": values})
                self.state.log_event("random_select", f"Random selected {eff['key']}={value}", {"event_id": event_id, "index": idx, "values": values})
        elif etype == "set_dynamic_entity_param":
            targets = self.resolve_effect_targets({"target": eff.get("target")}, ctx, default="actor")
            params = self.resolve_effect_targets({"target": eff.get("param_target")}, ctx, default="target")
            value = params[0] if params else (ctx.get("target_id") or (targets[0] if targets else None))
            if not eff.get("key") or value is None:
                self.state.log_event("effect_skip", "set_dynamic_entity_param skipped without key/value", {"effect": eff, "targets": targets, "params": params})
            else:
                self.commit_global_flag(str(eff["key"]), str(value), reason="effect:set_dynamic_entity_param", ctx=ctx, payload={"effect": deepcopy(eff), "targets": targets, "params": params})
                self.state.log_event("effect", f"Set dynamic entity {eff['key']}={value}", {"targets": targets, "params": params})
        elif etype == "trigger_custom_string":
            value = eff.get("custom_string")
            if value is None:
                self.state.log_event("effect_skip", "trigger_custom_string skipped without value", {"effect": eff})
            else:
                self.commit_global_flag("last_custom_string", str(value), reason="effect:trigger_custom_string", ctx=ctx, payload={"effect": deepcopy(eff)})
                self.state.log_event("custom_string", f"Trigger custom string {value}", {"custom_string": value})
        elif etype == "random_choice":
            choices = list(eff.get("choices") or [])
            if not choices:
                self.state.log_event("effect_skip", "random_choice skipped without choices", {"effect": eff})
            else:
                event_id = eff.get("event_id") or f"{ctx.get('actor_id')}.{ctx.get('status_id','random_choice')}.random_choice"
                forced = (ctx.get("events") or {}).get(event_id, (self.raw_case.get("events") or {}).get(event_id, None))
                available_indices = [int(row.get("index", i)) for i, row in enumerate(choices)]
                random_count = max(1, coerce_int(eff.get("random_count", 1), 1))
                mask_key = eff.get("random_mask_key")
                random_unique = coerce_bool(eff.get("random_unique", False), default=False)
                used_indices: set[int] = set()
                if random_unique and mask_key:
                    raw_mask = self.state.global_flags.get(str(mask_key), [])
                    if isinstance(raw_mask, list):
                        used_indices = {coerce_int(x, -999999) for x in raw_mask}
                    elif isinstance(raw_mask, str):
                        used_indices = {coerce_int(x.strip(), -999999) for x in raw_mask.split(',') if x.strip()}
                forced_indices: list[int] = []
                if forced is not None:
                    if isinstance(forced, list):
                        raw_items = forced
                    else:
                        raw_items = [x.strip() for x in str(forced).split(',') if str(x).strip()]
                    for item in raw_items:
                        try:
                            forced_indices.append(int(item))
                        except Exception:
                            pass
                selected_indices: list[int] = []
                for idx in forced_indices:
                    if idx in available_indices and idx not in selected_indices:
                        selected_indices.append(idx)
                        if len(selected_indices) >= random_count:
                            break
                if len(selected_indices) < random_count:
                    for idx in available_indices:
                        if idx in selected_indices:
                            continue
                        if random_unique and idx in used_indices:
                            continue
                        selected_indices.append(idx)
                        if len(selected_indices) >= random_count:
                            break
                if len(selected_indices) < random_count and random_unique:
                    # All branches are masked.  Validation mode resets the mask and
                    # deterministically takes the first remaining branches instead
                    # of failing or executing all branches.
                    used_indices.clear()
                    for idx in available_indices:
                        if idx not in selected_indices:
                            selected_indices.append(idx)
                        if len(selected_indices) >= random_count:
                            break
                selected_rows = [row for row in choices if int(row.get("index", -1)) in selected_indices]
                if not selected_rows:
                    selected_rows = [choices[0]]; selected_indices = [int(choices[0].get("index", 0))]
                if random_unique and mask_key:
                    new_used = sorted(used_indices.union(set(selected_indices)))
                    if coerce_bool(eff.get("auto_reset_random_mask", False), default=False) and len(new_used) >= len(available_indices):
                        new_used = []
                    self.commit_global_flag(str(mask_key), new_used, reason="effect:random_choice:mask", ctx=ctx, payload={"event_id": event_id, "selected_indices": selected_indices})
                self.state.log_event("random_choice", f"RandomConfig chose branches {selected_indices}", {"event_id": event_id, "indices": selected_indices, "index": selected_indices[0] if selected_indices else None, "random_count": random_count, "random_unique": random_unique, "random_mask_key": mask_key, "choice_count": len(choices), "odds": eff.get("odds")})
                for row in selected_rows:
                    idx = int(row.get("index", 0))
                    for nested in row.get("effects") or []:
                        self.apply_effect(nested, {**ctx, "random_choice_index": idx, "random_choice_indices": selected_indices})
        elif etype == "conditional_branch":
            cond = eff.get("condition", {})
            cond_ctx = ctx
            # ByRandomChance predicates around generated AddModifier branches are
            # debuff/effect-hit gates.  Give condition evaluation the first status
            # target so EHR/RES can be included in the logged probability.
            if isinstance(cond, dict) and isinstance(cond.get("chance_gate"), dict) and cond["chance_gate"].get("use_effect_hit") and "target_id" not in ctx:
                for nested_eff in eff.get("effects_if_true", eff.get("effects", [])) or []:
                    if isinstance(nested_eff, dict) and nested_eff.get("type") == "add_status":
                        targets = self.resolve_effect_targets(nested_eff, ctx, default="actor")
                        if targets:
                            tid = targets[0]
                            cond_ctx = {**ctx, "target_id": tid, "target": self.state.unit(tid)}
                        break
            branch = eff.get("effects_if_true", eff.get("effects", [])) if self.eval_condition(cond, cond_ctx) else eff.get("effects_if_false", [])
            for nested_eff in branch or []:
                self.apply_effect(nested_eff, ctx)
        elif etype == "gain_skill_point":
            self.apply_effect({"type": "modify_skill_points", "amount": coerce_float(eff.get("amount", 1), 1.0), "overflow_record": eff.get("overflow_record")}, ctx)
        elif etype == "consume_skill_point":
            self.apply_effect({"type": "modify_skill_points", "amount": -coerce_int(eff.get("amount", 1), 1)}, ctx)
        elif etype == "set_flag":
            self.commit_global_flag(str(eff["key"]), coerce_comparison_value(eff.get("value", True)), reason="effect:set_flag", ctx=ctx, payload={"effect": deepcopy(eff)})
            self.state.log_event("effect", f"Set flag {eff['key']}={self.state.global_flags[eff['key']]}")
        elif etype == "set_flag_from_context_value":
            kind = str(eff.get("context_value_type") or eff.get("variate_type") or "")
            if kind == "SetDynamicValueByAttackTargetCount":
                value = len(ctx.get("attacked_targets") or ctx.get("targets") or ([ctx.get("target_id")] if ctx.get("target_id") else []))
            elif str(eff.get("variate_type")) == "ParamValue" or kind == "SetDynamicValueByVariateType":
                value = ctx.get("consumed_skill_points", ctx.get("skill_point_delta", ctx.get("param_value", 0)))
                if isinstance(value, (int, float)) and value < 0:
                    value = abs(value)
            else:
                value = ctx.get("value", ctx.get("param_value", 0))
            self.commit_global_flag(str(eff["key"]), coerce_comparison_value(value), reason="effect:set_flag_from_context_value", ctx=ctx, payload={"effect": deepcopy(eff)})
            self.state.log_event("effect", f"Set flag {eff['key']} from context={self.state.global_flags[eff['key']]}", {"context_value_type": eff.get("context_value_type"), "variate_type": eff.get("variate_type")})
        elif etype == "set_flag_from_property":
            targets = self.resolve_effect_targets(eff, ctx, default="actor")
            value = None
            if targets:
                value = self.read_unit_property(self.state.unit(targets[0]), eff.get("property"))
            if value is None:
                # Unknown/derived engine-side properties such as AttackConvert must
                # not be silently coerced to zero; that would make downstream
                # symbolic runtime formulas look resolved with a false value.
                model = describe_engine_property(eff.get("property")).to_dict()
                self.state.log_event("effect_skip", f"Set flag {eff['key']} from unresolved property skipped", {"property": eff.get("property"), "targets": targets, "engine_property_model": model})
            else:
                self.commit_global_flag(str(eff["key"]), coerce_comparison_value(value), reason="effect:set_flag_from_property", ctx=ctx, payload={"effect": deepcopy(eff), "property": eff.get("property")})
                self.state.log_event("effect", f"Set flag {eff['key']} from property={self.state.global_flags[eff['key']]}", {"property": eff.get("property")})
        elif etype == "set_flag_from_status_value":
            targets = self.resolve_effect_targets(eff, ctx, default="actor")
            value = self.read_status_value(self.state.unit(targets[0]), eff.get("status_id"), eff.get("value_type"), eff.get("key")) if targets else 0
            self.commit_global_flag(str(eff["key"]), coerce_comparison_value(value), reason="effect:set_flag_from_status_value", ctx=ctx, payload={"effect": deepcopy(eff), "targets": targets})
            self.state.log_event("effect", f"Set flag {eff['key']} from status={self.state.global_flags[eff['key']]}", {"status_id": eff.get("status_id"), "value_type": eff.get("value_type")})
        elif etype == "copy_flag":
            value = self.read_flag_or_status_value(eff, ctx)
            self.commit_global_flag(str(eff["key"]), coerce_comparison_value(value), reason="effect:copy_flag", ctx=ctx, payload={"effect": deepcopy(eff)})
            self.state.log_event("effect", f"Copied flag {eff.get('source_key')} -> {eff['key']}={self.state.global_flags[eff['key']]}", {"source_status_id": eff.get("source_status_id")})
        elif etype == "trigger_custom_event":
            event_id = str(eff.get("custom_event_id") or eff.get("event_id") or "")
            if not event_id:
                self.state.log_event("effect_skip", "trigger_custom_event skipped without custom_event_id", {"effect": eff})
            else:
                for target_id in self.resolve_effect_targets(eff, ctx, default="actor") or [ctx.get("actor_id")]:
                    custom_ctx = {**ctx, "target_id": target_id, "custom_event_id": event_id, "context": {**ctx.get("context", {}), "custom_event_id": event_id}}
                    if target_id in self.state.units:
                        custom_ctx["target"] = self.state.unit(target_id)
                    self.state.log_event("effect", f"Trigger custom event {event_id}", {"target": target_id})
                    self.run_triggers("custom_event", custom_ctx)
        elif etype == "record_visual_effect":
            targets = self.resolve_effect_targets(eff, ctx, default="actor")
            self.state.log_event("visual_effect", f"Record visual effect {eff.get('effect_path')}", {"targets": targets, "effect_path": eff.get("effect_path")})
        elif etype == "record_preshow_event":
            self.state.log_event("preshow_audit", f"Record preshow event {eff.get('event_name')}", {"status_id": eff.get("status_id"), "owner_avatar_id": eff.get("owner_avatar_id"), "condition": eff.get("condition")})
        elif etype == "set_unit_flag":
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                unit = self.state.unit(target_id)
                self.commit_unit_flag(unit, str(eff["key"]), coerce_comparison_value(eff.get("value", True)), reason="effect:set_unit_flag", ctx=ctx, payload={"effect": deepcopy(eff)})
                self.state.log_event("effect", f"Set {target_id}.{eff['key']}={unit.flags[eff['key']]}")
        elif etype == "copy_unit_flag":
            source_targets = self.resolve_effect_targets({"target": eff.get("source_target", eff.get("target", "actor"))}, ctx, default="actor")
            value = None
            source_key = str(eff.get("source_key") or "")
            if source_targets:
                src = self.state.unit(source_targets[0])
                value = src.flags.get(source_key, 0)
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                unit = self.state.unit(target_id)
                self.commit_unit_flag(unit, str(eff["key"]), coerce_comparison_value(value), reason="effect:copy_unit_flag", ctx=ctx, payload={"effect": deepcopy(eff), "source_targets": source_targets})
                self.state.log_event("effect", f"Copy unit flag {source_key} -> {target_id}.{eff['key']}={unit.flags[eff['key']]}", {"source_targets": source_targets})
        elif etype == "set_unit_flag_from_target_count":
            actor = self.state.unit(ctx.get("actor_id")) if ctx.get("actor_id") in self.state.units else None
            count = 0
            spec = deepcopy(eff.get("target_spec") or {})
            filters = list(eff.get("filters") or []) + list(spec.get("filters") or [])
            if actor is not None:
                units = self.enemy_ai_target_candidates_from_spec(actor, spec)
                if filters:
                    units = [u for u in units if self.target_unit_passes_ai_filters(actor, u, filters, ctx)]
                count = len(units)
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                unit = self.state.unit(target_id)
                self.commit_unit_flag(unit, str(eff["key"]), count, reason="effect:set_unit_flag_from_target_count", ctx=ctx, payload={"target_spec": spec, "filters": filters})
                self.state.log_event("effect", f"Set {target_id}.{eff['key']} from target count={count}", {"target_spec": spec, "filters": filters})
        elif etype == "modify_unit_counter":
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                unit = self.state.unit(target_id)
                key = eff["key"]
                old = coerce_float(unit.flags.get(key, eff.get("default", 0)))
                new = old + coerce_float(eff.get("amount", 0))
                if "min" in eff: new = max(coerce_float(eff["min"]), new)
                if "max" in eff: new = min(coerce_float(eff["max"]), new)
                self.commit_unit_flag(unit, str(key), new, reason="effect:modify_unit_counter", ctx=ctx, payload={"effect": deepcopy(eff), "old": old})
                self.state.log_event("effect", f"{target_id}.{key} {old} -> {new}")
        elif etype == "hp_loss":
            aliased = deepcopy(eff)
            aliased["type"] = "damage_unit"
            if "amount" not in aliased:
                if "amount_percent_max_hp" in aliased:
                    aliased["target_max_hp_pct"] = aliased.get("amount_percent_max_hp")
                elif "hp_pct" in aliased:
                    aliased["target_max_hp_pct"] = aliased.get("hp_pct")
            aliased.setdefault("ignore_shield", True)
            return self.apply_effect(aliased, ctx)
        elif etype == "summon":
            for nested in eff.get("effects", []) or []:
                if isinstance(nested, dict) and "summon_entity" in nested:
                    entity = str(nested.get("summon_entity"))
                    count = coerce_int(nested.get("count", 1), 1)
                    for i in range(count):
                        base_id = f"{entity}_{i+1}" if count > 1 else entity
                        unit_id = base_id
                        n = 1
                        while unit_id in self.state.units:
                            n += 1
                            unit_id = f"{base_id}_{n}"
                        template = deepcopy(
                            (self.raw_case.get("unit_templates", {}) or {}).get(entity)
                            or (self.raw_case.get("summon_templates", {}) or {}).get(entity)
                            or nested.get("unit")
                            or {"side": "enemy", "hp": 1, "max_hp": 1, "speed": 100, "tags": ["summoned_placeholder"]}
                        )
                        self.apply_effect({"type": "summon_unit", "unit_id": unit_id, "unit": template, "side": template.get("side", "enemy")}, ctx)
                elif isinstance(nested, dict):
                    self.apply_effect(nested, ctx)
        elif etype is None and "summon_entity" in eff:
            return self.apply_effect({"type": "summon", "effects": [eff]}, ctx)
        elif etype == "force_defeat":
            for target_id in self.resolve_effect_targets(eff, ctx, default="target"):
                unit = self.state.unit(target_id)
                if not unit.alive:
                    continue
                result = self.apply_hp_loss(unit, unit.hp + unit.shield, {**ctx, "target_id": target_id, "target": unit}, label="force_defeat", ignore_shield=True, carry_over_hp_bar_damage=True)
                nested_ctx = {**ctx, "target_id": target_id, "target": unit, "damage_result": result}
                self.run_triggers("after_hp_change", nested_ctx)
                if result.get("target_defeated"):
                    self.run_triggers("after_defeat_enemy", nested_ctx)
            if not ctx.get("action"):
                self.check_wave_transition()
        elif etype == "damage_unit":
            raw_targets = self.resolve_effect_targets(eff, ctx, default="target")
            for target_id in self.derived_damage_live_targets(raw_targets, ctx, effect_name=str(eff.get("id") or "damage_unit")):
                phase_locked = ctx.get("phase_locked_targets")
                if isinstance(phase_locked, set) and target_id in phase_locked:
                    self.state.log_event(
                        "effect_damage_skip",
                        f"Skip {target_id}: phase HP boundary locked further effect damage in this action",
                        {"target": target_id, "effect": eff},
                    )
                    continue
                unit = self.state.unit(target_id)
                if not unit.alive:
                    continue
                amount = coerce_float(eff.get("amount", 0.0))
                if "target_max_hp_pct" in eff:
                    amount += unit.max_hp * coerce_float(eff["target_max_hp_pct"])
                if "source_max_hp_pct" in eff:
                    src_id = self.resolve_special_unit(eff.get("source", "actor"), ctx)
                    amount += self.state.unit(src_id).max_hp * coerce_float(eff["source_max_hp_pct"])
                result = self.apply_hp_loss(
                    unit,
                    amount,
                    {**ctx, "target_id": target_id, "target": unit, "damage_result": None},
                    label="effect_damage",
                    ignore_shield=coerce_bool(eff.get("ignore_shield", False), default=False),
                    carry_over_hp_bar_damage=eff.get("carry_over_hp_bar_damage", eff.get("carry_over_damage", None)),
                )
                nested_ctx = {**ctx, "target_id": target_id, "target": unit, "damage_result": result}
                if result.get("hp_bar_depleted"):
                    self.apply_hp_bar_depleted_effects(result, nested_ctx)
                    if unit.alive and unit.flags.get("phase_transition_immediate_action"):
                        action_id = unit.flags.get("phase_transition_immediate_action")
                        if action_id is True:
                            action_id = self.default_probe_action_id(unit) or next(iter(unit.action_defs), None)
                        if action_id:
                            self.state.log_event("enemy_mechanic", f"{unit.id} phase transition queues immediate action", {"action": action_id, "bars_depleted": result.get("bars_depleted")})
                            self.apply_effect({"type": "immediate_action", "actor": unit.id, "action": action_id, "target_policy": "first_ally"}, nested_ctx)
                if result.get("phase_damage_locked_until_action_end"):
                    phase_locked = ctx.get("phase_locked_targets")
                    if isinstance(phase_locked, set):
                        phase_locked.add(target_id)
                self.run_triggers("after_hp_change", nested_ctx)
                if result.get("hp_bar_depleted"):
                    self.run_triggers("after_hp_bar_depleted", nested_ctx)
                if result.get("target_defeated"):
                    actor = ctx.get("actor") if isinstance(ctx.get("actor"), UnitState) else None
                    if actor is None and ctx.get("actor_id") in self.state.units:
                        actor = self.state.unit(ctx["actor_id"])
                    self.note_action_defeat(target_id, actor.id if actor is not None else ctx.get("actor_id"), str(eff.get("damage_type") or eff.get("id") or "effect_damage"), ctx)
                    self.apply_kill_energy_for_effect_damage(actor, unit, ctx)
                    nested_ctx["actor"] = actor or nested_ctx.get("actor")
                    self.run_triggers("after_defeat_enemy", nested_ctx)
            # Do not spawn the next wave in the middle of an action-owned effect.
            # resolve_action performs the action-level wave transition after all
            # packets/effects/resource gains have settled. This keeps effect damage
            # consistent with normal damage packets and prevents later packets in
            # the same action from hitting a newly spawned wave.
            if not ctx.get("action"):
                self.check_wave_transition()
        elif etype == "heal_unit":
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                unit = self.state.unit(target_id)
                amount = coerce_float(eff.get("amount", 0.0))
                if "target_max_hp_pct" in eff:
                    amount += unit.max_hp * coerce_float(eff["target_max_hp_pct"])
                old = unit.hp
                heal_cap_ratio = coerce_float(unit.flags.get("max_restorable_hp_ratio", unit.flags.get("recoverable_hp_cap_ratio", 1.0)), 1.0)
                for st, mods in self.applicable_status_modifiers(unit, ctx or {}):
                    if "max_restorable_hp_ratio" in mods:
                        heal_cap_ratio = min(heal_cap_ratio, coerce_float(mods.get("max_restorable_hp_ratio"), 1.0))
                    if "recoverable_hp_cap_ratio" in mods:
                        heal_cap_ratio = min(heal_cap_ratio, coerce_float(mods.get("recoverable_hp_cap_ratio"), 1.0))
                heal_cap = unit.max_hp * max(0.0, min(1.0, heal_cap_ratio))
                self.commit_unit_hp(
                    unit,
                    min(heal_cap, unit.hp + amount),
                    reason="effect:heal",
                    ctx=ctx,
                    payload={"amount": amount, "heal_cap": heal_cap, "max_restorable_hp_ratio": heal_cap_ratio, "effect": deepcopy(eff)},
                )
                self.state.log_event("effect_heal", f"{target_id} heals {amount:.3f} HP", {"old_hp": old, "new_hp": unit.hp, "heal_cap": heal_cap, "max_restorable_hp_ratio": heal_cap_ratio})
                # Phase 2: 治疗 HP 记录
                self._settle(ctx, "hp",
                    unit_id=target_id, delta=unit.hp - old,
                    old_value=old, new_value=unit.hp, max_hp=unit.max_hp,
                    reason=f"heal: {ctx.get('action', {}).get('id', ctx.get('actor_id', '?'))}",
                    record_state_change=False,
                )
        elif etype == "cleanse_debuffs":
            count = coerce_int(eff.get("count", eff.get("amount", 1)), 1)
            source = str(eff.get("source_template") or eff.get("source") or etype)
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                if target_id in self.state.units:
                    self.cleanse_debuffs_from_unit(self.state.unit(target_id), count, source=source, ctx=ctx)
        elif etype == "summon_unit":
            unit_id = eff["unit_id"]
            raw = deepcopy(eff["unit"])
            raw.setdefault("side", eff.get("side", "enemy"))
            flags = raw.setdefault("flags", {})
            flags.setdefault("summoned", True)
            if eff.get("owner") or eff.get("owner_id") or ctx.get("actor_id"):
                flags.setdefault("owner_id", eff.get("owner") or eff.get("owner_id") or ctx.get("actor_id"))
            if eff.get("attached_to"):
                flags.setdefault("attached_to", eff.get("attached_to"))
                flags.setdefault("attached_unit", True)
            for k in ("lifespan_actions", "remove_when_owner_defeated", "remove_when_attached_target_defeated"):
                if k in eff and k not in flags:
                    flags[k] = eff[k]
            unit = UnitState.from_dict(unit_id, raw)
            self.ensure_souldragon_unit_defaults(unit)
            unit.remaining_av = self.unit_initial_av(unit, raw)
            self.state.units[unit_id] = unit
            self.state.log_event("summon", f"Summon unit {unit_id}", {"unit": unit.to_json()})
        elif etype == "modify_toughness":
            for target_id in self.resolve_effect_targets(eff, ctx, default="target"):
                unit = self.state.unit(target_id)
                if unit.toughness is not None:
                    old = unit.toughness
                    self.commit_unit_toughness(unit, unit.toughness + coerce_float(eff.get("amount", 0.0)), reason="effect:modify_toughness", ctx=ctx, payload={"effect": deepcopy(eff)})
                    self.state.log_event("toughness", f"{target_id} toughness {old} -> {unit.toughness}")
        elif etype == "modify_shield":
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                unit = self.state.unit(target_id)
                amount = coerce_float(eff.get("amount", 0.0))
                if "target_max_hp_pct" in eff:
                    amount += unit.max_hp * coerce_float(eff["target_max_hp_pct"])
                if "source_stat_pct" in eff:
                    src_id = self.resolve_special_unit(eff.get("source", "actor"), ctx)
                    stat_name = str(eff.get("source_stat", "atk"))
                    if src_id in self.state.units:
                        amount += self.contextual_stat(self.state.unit(src_id), stat_name, {**ctx, "target_id": target_id, "target": unit}) * coerce_float(eff.get("source_stat_pct", 0.0))
                self.apply_stackable_shield(target_id, amount, eff, ctx, reason="modify_shield")
        elif etype == "immediate_action":
            actor_id = eff.get("actor") or eff.get("actor_id") or ctx.get("actor_id")
            action_id = eff.get("action") or eff.get("action_id")
            action = self.get_action_def(actor_id, action_id)
            target_policy = eff.get("target_policy") or action.get("target_policy") or "manual"
            explicit_targets = self.normalize_targets(eff.get("targets")) if "targets" in eff else None
            queue_name = eff.get("queue", "immediate_queue")
            # Keep target selection lazy unless explicit targets are provided.
            # This matches launch_action and is important for after_defeat /
            # hp_bar_depleted effects: a queued immediate action may resolve only
            # after the current action finishes and a wave transition has spawned
            # new enemies. Eagerly storing [] or a now-dead target would silently
            # drop the queued action.
            queued = {
                "actor": actor_id,
                "action": action_id,
                "targets": explicit_targets,
                "defer_target_policy": target_policy,
                "context_target_id": ctx.get("target_id"),
                "events": eff.get("events", {}),
                "turn_kind": self.queued_action_turn_kind(eff, action, queue_name),
                "extra_turn_type": eff.get("extra_turn_type"),
                "queued_wave_index": self.state.wave_index,
                "carry_across_wave": self.queued_action_carry_across_wave(eff, action, default=True),
                "queued_actor_phase": self.effective_unit_phase(ctx.get("actor") if ctx.get("actor") is not None else (self.state.unit(actor_id) if actor_id in self.state.units else None)),
                "carry_across_phase": coerce_bool(eff.get("carry_across_phase", action.get("carry_across_phase", False) if isinstance(action, dict) else False), default=False),
            }
            self.commit_queue_append(
                queue_name,
                queued,
                reason="effect:immediate_action",
                ctx=ctx,
                payload={"effect": deepcopy(eff), "requested_queue": queue_name},
            )
            self.state.log_event("effect", f"Immediate action queued {actor_id}.{action_id} in {queue_name}", queued)
        elif etype == "reset_trigger_usage":
            prefix = eff.get("prefix") or eff.get("trigger_id")
            if prefix:
                for k in list(self.state.trigger_usage):
                    if k.startswith(str(prefix)):
                        del self.state.trigger_usage[k]
                self.state.log_event("effect", f"Reset trigger usage prefix {prefix}")
        elif etype == "zone_additional_damage":
            source_id = eff.get("source") or eff.get("actor") or eff.get("owner") or ctx.get("owner_id") or ctx.get("actor_id")
            if source_id not in self.state.units:
                self.state.log_event("effect_skip", "zone_additional_damage skipped without live source", {"source": source_id, "effect": eff})
                return
            raw_hit_targets = [str(tid) for tid in (ctx.get("attacked_targets", []) or [])]
            hit_targets = self.derived_damage_live_targets(raw_hit_targets, ctx, effect_name=str(eff.get("id") or "zone_additional_damage"))
            if not hit_targets:
                raw_hit_targets = self.resolve_effect_targets(eff, ctx, default="target")
                hit_targets = self.derived_damage_live_targets(raw_hit_targets, ctx, effect_name=str(eff.get("id") or "zone_additional_damage"))
            if not hit_targets:
                self.state.log_event("effect_skip", "zone_additional_damage skipped without attacked targets", {"effect": eff})
                return
            if str(eff.get("target_policy", "highest_hp_among_hit_targets")) == "highest_hp_among_hit_targets":
                target_id = max(hit_targets, key=lambda tid: self.state.unit(tid).hp)
            else:
                target_id = hit_targets[0]
            per_hit = coerce_bool(eff.get("per_target_hit", False), default=False)
            count = len(hit_targets) if per_hit else 1
            packet = {
                "id": eff.get("packet_id", "zone_additional_damage"),
                "element": eff.get("element", "quantum"),
                "damage_type": eff.get("damage_type", "additional_damage"),
                "target_policy": "selected_enemy",
                "scaling_stat": eff.get("scaling_stat", eff.get("stat", "hp")),
                "multiplier": eff.get("multiplier", eff.get("multiplier_at_ult_10", 0.0)),
                "can_crit": coerce_bool(eff.get("can_crit", False), default=False),
                "toughness_reduction": eff.get("toughness_reduction", 0.0),
                "is_attack": False,
                "tags": ["additional_damage", "zone_damage"],
            }
            source = self.state.unit(source_id)
            synthetic_action = {
                "id": eff.get("id", "zone_additional_damage"),
                "actor_id": source_id,
                "tags": ["additional_damage", "zone_damage", "can_trigger_kill_energy"],
                "target_policy": "selected_enemy",
            }
            dealt_total = 0.0
            dealt_targets: list[str] = []
            for _ in range(max(1, count)):
                if target_id not in self.state.units or not self.state.unit(target_id).alive:
                    break
                packet_ctx = {**ctx, "actor_id": source_id, "actor": source, "action": synthetic_action, "packet": packet, "target_id": target_id, "target": self.state.unit(target_id)}
                self.run_triggers("before_damage", packet_ctx)
                result = self.resolve_damage_packet(packet, source, self.state.unit(target_id), synthetic_action, [])
                self.apply_damage_result(result, packet_ctx)
                dealt_total += coerce_float(result.get("final_damage", result.get("damage", 0.0)))
                dealt_targets.append(target_id)
                packet_ctx["damage_result"] = result
                self.run_triggers("after_damage", packet_ctx)
                self.run_triggers("after_hp_change", packet_ctx)
                if result.get("hp_bar_depleted"):
                    self.run_triggers("after_hp_bar_depleted", packet_ctx)
                if result.get("target_defeated"):
                    # Tribbie-style zone/additional damage is owned by its source,
                    # not by the ally whose attack triggered it.  Kill energy and
                    # after_defeat triggers must therefore see actor_id=source_id.
                    self.note_action_defeat(target_id, source_id, "zone_additional_damage", ctx)
                    self.apply_kill_energy_for_effect_damage(source, self.state.unit(target_id), packet_ctx)
                    self.run_triggers("after_defeat_enemy", packet_ctx)
                    break
            zone_ctx = {**ctx, "actor_id": source_id, "actor": source, "zone_additional_targets": dealt_targets, "target_id": target_id, "target": self.state.unit(target_id) if target_id in self.state.units else None, "zone_additional_damage_total": dealt_total}
            self.state.log_event("effect", f"Zone additional damage by {source_id} to {target_id} x{count}", {"total": dealt_total, "targets": dealt_targets})
            self.run_triggers("after_tribbie_zone_additional_damage", zone_ctx)
        elif etype == "zone_followup_true_damage":
            effect = eff.get("effect", {}) if isinstance(eff.get("effect", {}), dict) else eff
            ratio = self.resolve_numeric_expr(effect.get("true_damage_equal_to_total_attack_damage", effect.get("ratio", 0.0)), ctx, default=0.0)
            base_damage = self.resolve_numeric_expr(effect.get("base_damage", ctx.get("total_attack_damage", 0.0)), ctx, default=0.0)
            if base_damage <= 0 and isinstance(ctx.get("damage_result"), dict):
                base_damage = coerce_float(ctx["damage_result"].get("final_damage", 0.0))
            amount = base_damage * ratio
            for target_id in self.resolve_effect_targets(effect, ctx, default="target"):
                if target_id in self.state.units and self.state.unit(target_id).alive:
                    self.apply_effect({"type": "damage_unit", "target": target_id, "amount": amount, "ignore_shield": True}, ctx)
        elif etype == "add_enemy_core_status":
            target_ids = self.resolve_effect_targets(eff, ctx, default="actor")
            status = eff.get("status") or {"id": eff.get("status_id", "enemy_core_status"), "modifiers": eff.get("modifiers", {}), "stacks": eff.get("stacks", 1), "max_stacks": eff.get("max_stacks", eff.get("stacks", 1))}
            for target_id in target_ids:
                self.apply_effect({"type": "add_status", "target": target_id, "status": status}, ctx)
        elif etype in {"control_immunity", "toughness_lock", "protect_toughness"}:
            key = "toughness_lock" if etype in {"toughness_lock", "protect_toughness"} else "control_immunity"
            self.apply_effect({"type": "add_status", "target": eff.get("target", "actor"), "status": {"id": eff.get("status_id", key), "modifiers": {key: True}}}, ctx)
        elif etype == "add_damage_taken":
            val = self.resolve_numeric_expr(eff.get("amount", eff.get("value", eff.get("damage_taken", 0.0))), ctx, default=0.0)
            self.apply_effect({"type": "add_status", "target": eff.get("target", "actor"), "status": {"id": eff.get("status_id", "damage_taken_status"), "modifiers": {"damage_taken_add": val}, "duration": eff.get("duration")}}, ctx)
        elif etype == "reduce_resistance":
            val = self.resolve_numeric_expr(eff.get("amount", eff.get("value", eff.get("resistance_reduction", 0.0))), ctx, default=0.0)
            element = str(eff.get("element", eff.get("damage_type", "all"))).lower()
            mods = {"damage_taken": {}}
            # Resistance reduction on target is equivalent to attacker res_pen for
            # damage math; store as negative target resistance via a status payload
            # consumed by an immediate target.res patch here to stay simple.
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                unit = self.state.unit(target_id)
                old = coerce_float(unit.res.get(element if element != "all" else "all", 0.0))
                unit.res[element if element != "all" else "all"] = old - val
                self.state.log_event("enemy_mechanic", f"{target_id} {element} resistance {old}->{unit.res[element if element != 'all' else 'all']}", {"property": "reduce_resistance", "element": element, "value": val})
        elif etype == "spawn_corresponding_summons":
            allies_for_correspondence = self.state.allies_alive() if coerce_bool(eff.get("per_ally", True), default=True) else []
            count = coerce_int(eff.get("count", len(allies_for_correspondence) if allies_for_correspondence else 1), 1)
            base_id = str(eff.get("unit_id", eff.get("summon_id", "enemy_summon")))
            for idx in range(count):
                uid = f"{base_id}_{idx+1}" if count > 1 else base_id
                if uid in self.state.units:
                    continue
                corresponding_ally = allies_for_correspondence[idx].id if idx < len(allies_for_correspondence) else None
                flags = {"corresponding_summon": True, "summon_monster_id": eff.get("summon_monster_id")}
                if corresponding_ally:
                    flags["corresponding_ally"] = corresponding_ally
                unit_template = deepcopy(eff.get("unit_template") or {}) if isinstance(eff.get("unit_template"), dict) else {}
                unit_raw = {**unit_template}
                unit_raw.setdefault("side", eff.get("side", "enemy"))
                unit_raw.setdefault("hp", eff.get("hp", 1000))
                unit_raw.setdefault("max_hp", eff.get("max_hp", eff.get("hp", 1000)))
                unit_raw.setdefault("speed", eff.get("speed", 100))
                unit_raw.setdefault("level", eff.get("level", 80))
                unit_raw.setdefault("stats", {"atk": eff.get("atk", 1000), "def": eff.get("def", 0)})
                unit_raw.setdefault("tags", ["summoned", "enemy_summon"])
                if "summoned" not in normalize_str_list(unit_raw.get("tags", [])):
                    unit_raw["tags"] = normalize_str_list(unit_raw.get("tags", [])) + ["summoned", "enemy_summon"]
                merged_flags = deepcopy(unit_raw.get("flags", {})) if isinstance(unit_raw.get("flags", {}), dict) else {}
                merged_flags.update(flags)
                unit_raw["flags"] = merged_flags
                self.apply_effect({"type": "summon_unit", "unit_id": uid, "side": eff.get("side", "enemy"), "owner": ctx.get("actor_id"), "unit": unit_raw}, ctx)
        elif etype == "phase_transition_immediate_action":
            target_id = eff.get("target") or ctx.get("actor_id")
            if target_id in self.state.units:
                self.commit_unit_flag(
                    self.state.unit(target_id),
                    "phase_transition_immediate_action",
                    eff.get("action") or eff.get("action_id") or True,
                    reason="effect:phase_transition_immediate_action",
                    ctx=ctx,
                    payload={"effect": deepcopy(eff)},
                )
                self.state.log_event("enemy_mechanic", f"{target_id} phase transition immediate action armed", {"action": self.state.unit(target_id).flags["phase_transition_immediate_action"]})
        elif etype == "hp_based_damage":
            amount_key = eff.get("target_max_hp_pct", eff.get("max_hp_pct", eff.get("ratio", 0.0)))
            ratio = self.resolve_numeric_expr(amount_key, ctx, default=0.0)
            for target_id in self.resolve_effect_targets(eff, ctx, default="target"):
                if target_id in self.state.units:
                    unit = self.state.unit(target_id)
                    self.apply_effect({"type": "damage_unit", "target": target_id, "amount": unit.max_hp * ratio, "element": eff.get("element"), "ignore_shield": eff.get("ignore_shield", False), "ignore_defense": eff.get("ignore_defense", True)}, ctx)
        elif etype == "add_toughness_protection":
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                self.apply_effect({"type": "add_status", "target": target_id, "status": {"id": eff.get("status_id", "toughness_protection"), "tags": ["enemy_core_mechanic", "toughness_protection"], "modifiers": {"toughness_lock": True}}}, ctx)
        elif etype == "absorb_remaining_summons":
            contains = str(eff.get("summon_id_contains", "")).lower()
            tag = str(eff.get("summon_tag", "")).lower()
            absorbed = 0
            for unit in list(self.state.units.values()):
                if not unit.alive or unit.side != "enemy":
                    continue
                tag_match = (not tag) or tag in {str(t).lower() for t in unit.tags}
                id_match = (not contains) or contains in str(unit.id).lower()
                if tag_match and id_match and unit.id != ctx.get("actor_id"):
                    self.commit_unit_hp(
                        unit,
                        0.0,
                        reason="effect:absorb_remaining_summons",
                        ctx=ctx,
                        payload={"absorbed_by": ctx.get("actor_id"), "summon_id_contains": contains, "summon_tag": tag},
                    )
                    self.commit_unit_alive(unit, False, reason="effect:absorb_remaining_summons", ctx=ctx, payload={"absorbed_by": ctx.get("actor_id"), "summon_id_contains": contains, "summon_tag": tag})
                    absorbed += 1
                    self.state.log_event("enemy_mechanic", f"{ctx.get('actor_id')} absorbs {unit.id}", {"absorbed_unit": unit.id})
            flag = eff.get("store_count_flag")
            if flag and ctx.get("actor_id") in self.state.units:
                self.commit_unit_flag(self.state.unit(ctx["actor_id"]), str(flag), absorbed, reason="effect:absorb_remaining_summons:store_count_flag", ctx=ctx, payload={"summon_id_contains": contains, "summon_tag": tag})
            self.state.log_event("enemy_mechanic", f"Absorbed {absorbed} enemy summons", {"absorbed_count": absorbed, "summon_id_contains": contains, "summon_tag": tag})
        elif etype == "dispel_status_categories":
            categories = {str(x).lower() for x in normalize_str_list(eff.get("categories", []))}
            for target_id in self.resolve_effect_targets(eff, ctx, default="actor"):
                if target_id not in self.state.units:
                    continue
                unit = self.state.unit(target_id)
                removed = []
                for st in list(unit.statuses):
                    st_tags = {str(t).lower() for t in st.tags}
                    if categories and (categories & st_tags or str(st.id).lower() in categories):
                        removed.append(st.id)
                        self.commit_status_remove(
                            unit,
                            st,
                            reason="effect:dispel_status_categories",
                            ctx=ctx,
                            payload={"categories": sorted(categories), "removed_status": st.to_json()},
                        )
                if "weakness_break" in categories or "break" in categories:
                    self.commit_unit_is_broken(unit, False, reason="effect:dispel_status_categories:is_broken", ctx=ctx, payload={"categories": sorted(categories)})
                self.state.log_event("enemy_mechanic", f"{target_id} dispels status categories", {"categories": sorted(categories), "removed": removed})
        elif etype == "reduce_recoverable_hp_cap":
            ratio = self.resolve_numeric_expr(eff.get("ratio", eff.get("amount", eff.get("value", 0.5))), ctx, default=0.5)
            cap_ratio = max(0.0, min(1.0, 1.0 - ratio))
            for target_id in self.resolve_effect_targets(eff, ctx, default="target"):
                if target_id in self.state.units:
                    unit = self.state.unit(target_id)
                    old = coerce_float(unit.flags.get("max_restorable_hp_ratio", 1.0), 1.0)
                    self.commit_unit_flag(unit, "max_restorable_hp_ratio", min(old, cap_ratio), reason="effect:reduce_recoverable_hp_cap", ctx=ctx, payload={"ratio": ratio, "cap_ratio": cap_ratio})
                    self.state.log_event("enemy_mechanic", f"{target_id} max restorable HP ratio {old}->{unit.flags['max_restorable_hp_ratio']}", {"ratio": ratio, "cap_ratio": cap_ratio})
        elif etype == "restore_recoverable_hp_cap_by_damaging_corresponding_summon":
            # Runtime restoration is handled in handle_enemy_on_hit_mechanics when
            # a corresponding summon carries flags.corresponding_ally.  This effect
            # arms the summon/template path without tying it to a concrete monster id.
            self.state.log_event("enemy_mechanic", "restore_recoverable_hp_cap_by_damaging_corresponding_summon armed", {"effect": eff})
        elif etype in {
            "damage_reduction", "reduce_stack_on_attacked", "on_stack_reaches_zero",
            "charge", "charging", "buff_self", "apply_state_to_corresponding_character",
            "summon_or_attached_unit", "boss_buff", "self_state_change", "self_state_transition",
            "deal_damage_to_self", "grant_energy_to_breaking_player_unit", "mark_armor_broken",
            "while_broken_extra_damage_on_hit", "restore_to_max_at_self_turn_end",
            "linked_to_conquered_state", "protect_toughness", "cleanse_control_and_weakness_break_on_apply",
            "mark_summon_armor_intact", "increases_fury_descends_damage_if_intact", "control_immunity",
            "toughness_lock", "replace_regular_action_pattern", "immediate_action_on_hit_by_element",
            "count_attacks_taken", "add_damage_taken", "reduce_resistance", "spawn_corresponding_summons",
            "enemy_turns",
            "dispel_debuff",
        }:
            self.state.log_event("effect_noop", f"Model-pack descriptive effect recorded as no-op: {etype}", {"effect": eff})
        else:
            raise SimulatorError(f"Unsupported effect type: {etype}")

    def _effect_is_damage_unit(self, eff: dict[str, Any]) -> bool:
        return isinstance(eff, dict) and eff.get("type") == "damage_unit"

    def iter_offensive_damage_effects(self, effects: list[dict[str, Any]], ctx: dict[str, Any]) -> list[dict[str, Any]]:
        """Return damage_unit effects that may deal damage in this context.

        Queued-action preflight must inspect every action effect window, not only
        effects_before_damage/effects. It also has to understand nested
        conditional_branch effects; otherwise stale queued actions whose damage is
        in effects_after_action_start/effects_after_damage can still pay costs and
        gain action energy despite having no live target.
        """
        out: list[dict[str, Any]] = []
        for eff in effects or []:
            if not isinstance(eff, dict):
                continue
            etype = eff.get("type")
            if etype == "conditional_branch":
                branch = eff.get("effects_if_true", eff.get("effects", [])) if self.eval_condition(eff.get("condition", {}), ctx) else eff.get("effects_if_false", [])
                out.extend(self.iter_offensive_damage_effects(branch or [], ctx))
                continue
            if "condition" in eff and not self.eval_condition(eff.get("condition"), ctx):
                continue
            if etype == "damage_unit":
                out.append(eff)
        return out

    def _effect_has_live_damage_target(self, eff: dict[str, Any], ctx: dict[str, Any]) -> bool:
        for target_id in self.resolve_effect_targets(eff, ctx, default="target"):
            if target_id in self.state.units and self.state.unit(target_id).alive:
                return True
        return False

    def queued_action_has_valid_damage_target(self, action: dict[str, Any], targets: list[str]) -> bool:
        """Return whether a queued offensive action can hit at least one live target.

        Queued actions can become stale: two follow-ups may explicitly point to
        the same enemy, but the first one defeats it before the second resolves.
        Such a stale queued attack must be skipped before SP costs/action energy
        are paid.  This preflight covers both normal damage_packets and
        action-owned damage_unit effects. Pure self-buffs, summons, resource
        effects, or non-damaging utility actions remain valid without enemy
        targets.
        """
        packets = action.get("damage_packets", []) or []
        base_ctx = {
            "action": action,
            "actor_id": action.get("actor_id"),
            "actor": self.state.unit(action["actor_id"]),
            "targets": targets,
        }
        if len(targets) == 1:
            base_ctx["target_id"] = targets[0]
            if targets[0] in self.state.units:
                base_ctx["target"] = self.state.unit(targets[0])
        effect_windows = []
        for key in ("effects_after_action_start", "effects_before_damage", "effects_after_damage", "effects"):
            effect_windows.extend(action.get(key, []) or [])
        damage_effects = self.iter_offensive_damage_effects(effect_windows, base_ctx)
        if not packets and not damage_effects:
            return True
        for packet in packets:
            packet = self.normalize_damage_packet_schema(packet)
            packet_targets = self.resolve_packet_targets(packet, action, base_ctx, targets)
            for target_id in packet_targets or []:
                if target_id in self.state.units and self.state.unit(target_id).alive:
                    return True
        for eff in damage_effects:
            if self._effect_has_live_damage_target(eff, base_ctx):
                return True
        return False

    def effective_unit_phase(self, unit: UnitState | None) -> int | None:
        """Return the combat phase used for queued-chain invalidation.

        Some enemy templates do not materialize current_phase until the first
        HP-bar transition.  For phase_hp monsters, the initial phase is still
        semantically phase 1, so queue metadata must record that baseline;
        otherwise old-phase follow-ups can leak after a transition.
        """
        if unit is None:
            return None
        if unit.flags.get("current_phase") is not None:
            return coerce_int(unit.flags.get("current_phase"), 1)
        if unit.flags.get("monster_phase") is not None:
            return coerce_int(unit.flags.get("monster_phase"), 1)
        if unit.hp_bars_total > 1:
            return max(1, unit.hp_bars_total - unit.hp_bars_remaining + 1)
        return None

    def queued_action_is_enemy_chain(self, item: dict[str, Any], action: dict[str, Any] | None = None) -> bool:
        """Return whether a queued action is a same-turn enemy action chain continuation."""
        action = action or {}
        if coerce_bool(item.get("enemy_action_chain", False), default=False):
            return True
        if item.get("chain_id") or item.get("enemy_chain_id"):
            return True
        if coerce_bool(action.get("enemy_action_chain", False), default=False):
            return True
        tags = {str(t).lower() for t in normalize_str_list(action.get("tags", []))}
        return bool(tags.intersection({"enemy_action_chain", "enemy_chain", "chain_continuation", "action_sequence_continuation"}))

    def queued_enemy_chain_interrupt_reason(self, actor: UnitState, item: dict[str, Any], action: dict[str, Any] | None = None) -> str | None:
        """Return why an enemy queued chain continuation must be skipped.

        Multi-action monsters can queue follow-up actions inside the same turn,
        but those continuations should not punch through weakness break, control,
        or death.  This guard runs at queue-resolution time so interruption that
        happens between two queued actions is observed before the next action
        starts.
        """
        if actor.side != "enemy" or not self.queued_action_is_enemy_chain(item, action):
            return None
        if not actor.alive:
            return "dead"
        policy = str(item.get("interrupt_policy", (action or {}).get("interrupt_policy", "break_or_control"))).lower()
        if policy in {"ignore", "none", "uninterruptible"}:
            return None
        queued_phase = item.get("queued_actor_phase")
        current_phase = self.effective_unit_phase(actor)
        if queued_phase is not None and current_phase is not None and str(queued_phase) != str(current_phase):
            if not coerce_bool(item.get("carry_across_phase", (action or {}).get("carry_across_phase", False)), default=False):
                return "phase_changed"
        if coerce_bool(item.get("interruptible_by_break", (action or {}).get("interruptible_by_break", True)), default=True):
            if actor.is_broken or coerce_bool(actor.flags.get("weakness_broken", False), default=False):
                return "weakness_break"
        if coerce_bool(item.get("interruptible_by_control", (action or {}).get("interruptible_by_control", True)), default=True):
            controls = self.control_statuses(actor)
            if controls:
                return "control:" + ",".join(st.id for st in controls[:3])
        return None

    def drain_queues(self, default_events: Optional[dict[str, Any]] = None) -> None:
        default_events = default_events or {}
        guard = 0
        while self.state.ultimate_queue or self.state.immediate_queue or self.state.interrupt_queue:
            guard += 1
            if guard > 100:
                raise SimulatorError("Queue drain guard exceeded; possible infinite trigger loop")
            if self.state.ultimate_queue:
                qname = "ultimate_queue"
                item = deepcopy(self.state.ultimate_queue[0])
            elif self.state.immediate_queue:
                qname = "immediate_queue"
                item = deepcopy(self.state.immediate_queue[0])
            else:
                qname = "interrupt_queue"
                item = deepcopy(self.state.interrupt_queue[0])
            self.state.log_event("queue", f"Resolve queued action from {qname}: {item['actor']}.{item.get('action')}")
            if item.get("carry_across_wave") is False and item.get("queued_wave_index") != self.state.wave_index:
                settlement = self.begin_queued_action_settlement(item, qname, guard, [], target_source="none")
                self.commit_queue_popleft(
                    qname,
                    reason="queue:popleft:skip_wave",
                    ctx={"_settlement": settlement},
                    payload={"guard": guard, "item": deepcopy(item), "current_wave_index": self.state.wave_index},
                )
                self.state.log_event(
                    "queue_skip",
                    f"Skip queued action {item['actor']}.{item['action']}: cannot carry across wave",
                    {"item": item, "current_wave_index": self.state.wave_index},
                )
                settlement.capture_after_snapshot(self.full_scene_snapshot())
                self.record_queued_action_transition(item, qname, guard, settlement, skipped=True, skip_reason="cannot_carry_across_wave")
                continue
            if not item.get("action"):
                key = f"pending_extra_turn:{item['actor']}:{item.get('extra_turn_type', 'extra_turn')}"
                grant_item = {**item, "action": "extra_turn_grant"}
                settlement = self.begin_queued_action_settlement(grant_item, qname, guard, [], target_source="none")
                settlement_ctx = {"_settlement": settlement}
                self.commit_queue_popleft(
                    qname,
                    reason="queue:popleft:extra_turn_grant",
                    ctx=settlement_ctx,
                    payload={"guard": guard, "item": deepcopy(item)},
                )
                self.commit_global_flag(
                    key,
                    coerce_float(self.state.global_flags.get(key, 0)) + 1,
                    reason="queue:extra_turn_grant",
                    ctx=settlement_ctx,
                    payload={"item": deepcopy(item)},
                )
                self.state.log_event("extra_turn_grant", f"Queued extra turn grant available for {item['actor']}", {"item": item, "flag": key})
                settlement.capture_after_snapshot(self.full_scene_snapshot())
                self.record_queued_action_transition(grant_item, qname, guard, settlement)
                continue
            if item["actor"] not in self.state.units or (not self.state.unit(item["actor"]).alive):
                settlement = self.begin_queued_action_settlement(item, qname, guard, [], target_source="none")
                self.commit_queue_popleft(
                    qname,
                    reason="queue:popleft:skip_dead_actor",
                    ctx={"_settlement": settlement},
                    payload={"guard": guard, "item": deepcopy(item)},
                )
                self.state.log_event(
                    "queue_skip",
                    f"Skip queued action {item['actor']}.{item['action']}: queued actor is dead or missing",
                    {"item": item},
                )
                settlement.capture_after_snapshot(self.full_scene_snapshot())
                self.record_queued_action_transition(item, qname, guard, settlement, skipped=True, skip_reason="queued_actor_dead_or_missing")
                continue
            action = self.get_action_def(item["actor"], item["action"])
            actor_for_queue = self.state.unit(item["actor"])
            interrupt_reason = self.queued_enemy_chain_interrupt_reason(actor_for_queue, item, action)
            if interrupt_reason:
                settlement = self.begin_queued_action_settlement(item, qname, guard, [], target_source="none")
                self.commit_queue_popleft(
                    qname,
                    reason="queue:popleft:skip_enemy_chain_interrupt",
                    ctx={"_settlement": settlement},
                    payload={"guard": guard, "item": deepcopy(item), "interrupt_reason": interrupt_reason},
                )
                self.state.log_event(
                    "queue_skip",
                    f"Skip queued enemy chain action {item['actor']}.{item['action']}: interrupted by {interrupt_reason}",
                    {"item": item, "reason": interrupt_reason, "actor_statuses": [st.id for st in actor_for_queue.statuses], "is_broken": actor_for_queue.is_broken},
                )
                settlement.capture_after_snapshot(self.full_scene_snapshot())
                self.record_queued_action_transition(item, qname, guard, settlement, skipped=True, skip_reason=f"enemy_chain_interrupted:{interrupt_reason}")
                continue
            targets = self.normalize_targets(item.get("targets"))
            resolved_from_deferred_policy = targets is None
            if targets is None:
                action["target_policy"] = item.get("defer_target_policy", action.get("target_policy", "manual"))
                targets = self.select_targets(action, {"target_id": item.get("context_target_id")})
            if resolved_from_deferred_policy and not targets:
                # Support/utility queued actions may intentionally have no explicit
                # target.  Only skip empty-target queued actions when their action
                # actually contains offensive damage that needs a live target.
                if not self.queued_action_has_valid_damage_target(action, []):
                    settlement = self.begin_queued_action_settlement(item, qname, guard, [], target_source="deferred_policy")
                    self.commit_queue_popleft(
                        qname,
                        reason="queue:popleft:skip_no_deferred_targets",
                        ctx={"_settlement": settlement},
                        payload={"guard": guard, "item": deepcopy(item)},
                    )
                    self.state.log_event(
                        "queue_skip",
                        f"Skip queued action {item['actor']}.{item['action']}: deferred target policy found no valid targets",
                        {"item": item},
                    )
                    settlement.capture_after_snapshot(self.full_scene_snapshot())
                    self.record_queued_action_transition(item, qname, guard, settlement, skipped=True, skip_reason="deferred_target_policy_no_valid_targets")
                    continue
            if not self.queued_action_has_valid_damage_target(action, targets or []):
                settlement = self.begin_queued_action_settlement(item, qname, guard, targets or [], target_source="deferred_policy" if resolved_from_deferred_policy else "queued_item")
                self.commit_queue_popleft(
                    qname,
                    reason="queue:popleft:skip_no_live_damage_targets",
                    ctx={"_settlement": settlement},
                    payload={"guard": guard, "item": deepcopy(item), "targets": targets},
                )
                self.state.log_event(
                    "queue_skip",
                    f"Skip queued action {item['actor']}.{item['action']}: no live damage targets remain",
                    {"item": item, "targets": targets},
                )
                settlement.capture_after_snapshot(self.full_scene_snapshot())
                self.record_queued_action_transition(item, qname, guard, settlement, skipped=True, skip_reason="no_live_damage_targets")
                continue
            events = {**default_events, **item.get("events", {})}
            target_source = "deferred_policy" if resolved_from_deferred_policy else "queued_item"
            settlement = self.begin_queued_action_settlement(item, qname, guard, targets or [], target_source=target_source)
            q_context = {"queued": True, "turn_kind": item.get("turn_kind"), "_settlement": settlement}
            self.commit_queue_popleft(
                qname,
                reason="queue:popleft:resolve_action",
                ctx=q_context,
                payload={"guard": guard, "item": deepcopy(item), "targets": targets or []},
            )
            if self.queued_action_is_enemy_chain(item, action):
                q_context["enemy_action_chain"] = True
                q_context["chain_id"] = item.get("chain_id") or item.get("enemy_chain_id") or action.get("chain_id") or action.get("enemy_chain_id")
                q_context["chain_record_skill_use"] = item.get("record_skill_use", item.get("chain_record_skill_use", action.get("chain_record_skill_use", True)))
                q_context["chain_advances_enemy_sequence"] = item.get("advance_ai_sequence", item.get("chain_advances_enemy_sequence", action.get("chain_advances_enemy_sequence", False)))
            if item.get("extra_turn_type") is not None:
                q_context["extra_turn_type"] = item.get("extra_turn_type")
            self.resolve_action(action, targets or [], events, context=q_context)
            settlement.capture_after_snapshot(self.full_scene_snapshot())
            self.record_queued_action_transition(item, qname, guard, settlement)

    def validate_route_step_expectation(self, expect: Any, trace_entry: dict[str, Any]) -> dict[str, Any]:
        """Validate optional exact-route step expectations.

        Route steps may include::

          expect:
            event_counts: {damage: 2}
            damage_total: {min: 1000, max: 2000}
            units:
              seele: {hp: 1000, energy: {min: 20}}
            global_flags: {bondmate: seele}

        The validator is intentionally generic; real-battle traces can start
        with broad ranges and tighten assertions as generated mechanics improve.
        """
        if not isinstance(expect, dict) or not expect:
            return {"ok": True, "check_count": 0, "failure_count": 0, "failures": []}
        failures: list[dict[str, Any]] = []
        checks = 0
        summary = trace_entry.get("event_summary") if isinstance(trace_entry.get("event_summary"), dict) else {}
        after = trace_entry.get("after") if isinstance(trace_entry.get("after"), dict) else {}

        def check_number(label: str, actual: Any, rule: Any) -> None:
            nonlocal checks
            checks += 1
            actual_f = coerce_float(actual, 0.0)
            if isinstance(rule, dict):
                if "value" in rule and abs(actual_f - coerce_float(rule.get("value"), 0.0)) > coerce_float(rule.get("eps", 1e-6), 1e-6):
                    failures.append({"check": label, "expected": rule, "actual": actual_f})
                if "min" in rule and actual_f + EPS < coerce_float(rule.get("min"), 0.0):
                    failures.append({"check": label, "expected": rule, "actual": actual_f})
                if "max" in rule and actual_f - coerce_float(rule.get("max"), 0.0) > EPS:
                    failures.append({"check": label, "expected": rule, "actual": actual_f})
                if "lt" in rule and not (actual_f < coerce_float(rule.get("lt"), 0.0) - EPS):
                    failures.append({"check": label, "expected": rule, "actual": actual_f})
                if "lte" in rule and actual_f - coerce_float(rule.get("lte"), 0.0) > EPS:
                    failures.append({"check": label, "expected": rule, "actual": actual_f})
                if "gt" in rule and not (actual_f > coerce_float(rule.get("gt"), 0.0) + EPS):
                    failures.append({"check": label, "expected": rule, "actual": actual_f})
                if "gte" in rule and actual_f + EPS < coerce_float(rule.get("gte"), 0.0):
                    failures.append({"check": label, "expected": rule, "actual": actual_f})
            elif isinstance(rule, (int, float)):
                if abs(actual_f - float(rule)) > 1e-6:
                    failures.append({"check": label, "expected": rule, "actual": actual_f})
            else:
                checks -= 1

        event_counts = expect.get("event_counts") if isinstance(expect.get("event_counts"), dict) else {}
        for etype, rule in event_counts.items():
            actual = (summary.get("event_counts") or {}).get(str(etype), 0)
            check_number(f"event_counts.{etype}", actual, rule)
        if "damage_total" in expect:
            check_number("damage_total", summary.get("damage_total", 0.0), expect.get("damage_total"))
        if "toughness_damage_total" in expect:
            check_number("toughness_damage_total", summary.get("toughness_damage_total", 0.0), expect.get("toughness_damage_total"))

        units_expect = expect.get("units") if isinstance(expect.get("units"), dict) else {}
        units_after = {u.get("id"): u for side in ("allies", "enemies") for u in after.get(side, []) or [] if isinstance(u, dict)}
        for uid, spec in units_expect.items():
            checks += 1
            if uid not in units_after:
                failures.append({"check": f"units.{uid}", "expected": spec, "actual": "missing"})
                continue
            checks -= 1
            unit = units_after.get(uid) or {}
            if isinstance(spec, dict):
                for field, rule in spec.items():
                    if field == "flags":
                        # Snapshot omits unit flags by default; use live state.
                        live_unit = self.state.units.get(str(uid))
                        live_flags = live_unit.flags if live_unit is not None else {}
                        for fk, fv in (rule or {}).items():
                            checks += 1
                            if live_flags.get(fk) != fv:
                                failures.append({"check": f"units.{uid}.flags.{fk}", "expected": fv, "actual": live_flags.get(fk)})
                    else:
                        check_number(f"units.{uid}.{field}", unit.get(field), rule)
        gf_expect = expect.get("global_flags") if isinstance(expect.get("global_flags"), dict) else {}
        for k, v in gf_expect.items():
            checks += 1
            if self.state.global_flags.get(k) != v:
                failures.append({"check": f"global_flags.{k}", "expected": v, "actual": self.state.global_flags.get(k)})
        return {"ok": not failures, "check_count": checks, "failure_count": len(failures), "failures": failures[:20]}

    def summarize_route_expectations(self, trace: list[dict[str, Any]]) -> dict[str, Any]:
        results = [e.get("expectation") for e in trace if isinstance(e.get("expectation"), dict) and e.get("expectation", {}).get("check_count", 0)]
        failures = []
        for r in results:
            failures.extend(r.get("failures") or [])
        return {"ok": not failures, "step_count_with_expectations": len(results), "failure_count": len(failures), "failures": failures[:20]}

    # ---------- run ----------
    def run_route(self, route: list[dict[str, Any]]) -> dict[str, Any]:
        route_trace: list[dict[str, Any]] = []
        for i, step in enumerate(route, start=1):
            self.state.log_event("route", f"Route step {i}: {step}")
            before_full_scene = self.full_scene_snapshot()
            trace_entry = {
                "step": i,
                "step_type": step.get("type", "action"),
                "actor": step.get("actor"),
                "action": step.get("action"),
                "timing": step.get("timing", step.get("turn_kind")),
                "targets": self.normalize_targets(step.get("targets")) if "targets" in step else None,
                "before": self.generated_route_snapshot(),
                "before_scene": before_full_scene,
            }
            before_log_len = len(self.state.log)
            queued_transition_start = len(self._queued_action_transitions)
            step["_route_step_index"] = i
            self.resolve_route_step(step)
            new_events = self.state.log[before_log_len:]
            trace_entry["event_summary"] = self.summarize_auto_probe_events(new_events)
            trace_entry["action_resolution"] = self.summarize_action_resolution(step, new_events)
            new_queue_transitions = self._queued_action_transitions[queued_transition_start:]
            if new_queue_transitions:
                trace_entry["queued_action_transitions"] = deepcopy(new_queue_transitions)
            # Phase 2: 合并结算数据
            if "_settlement" in step:
                trace_entry["settlement"] = step["_settlement"].to_dict()
            trace_entry["after"] = self.generated_route_snapshot()
            trace_entry["after_scene"] = self.full_scene_snapshot()
            if isinstance(step.get("expect"), dict):
                trace_entry["expectation"] = self.validate_route_step_expectation(step.get("expect"), trace_entry)
            route_trace.append(trace_entry)
        post_route_queue_start = len(self._queued_action_transitions)
        self.drain_queues()
        post_route_queue_transitions = self._queued_action_transitions[post_route_queue_start:]
        result = self.result()
        result.setdefault("metadata", {})["route_executed_step_count"] = len(route_trace)
        result["metadata"]["route_action_trace"] = route_trace
        if post_route_queue_transitions:
            result["metadata"]["post_route_queued_action_transitions"] = deepcopy(post_route_queue_transitions)
        generic_assertions = self.validate_auto_probe_trace(route_trace)
        expectation_assertions = self.summarize_route_expectations(route_trace)
        result["metadata"]["route_assertions"] = {**generic_assertions, "expectations": expectation_assertions, "ok": generic_assertions.get("ok", True) and expectation_assertions.get("ok", True)}
        return result

    def enemy_action_phase_allowed(self, actor: UnitState, action: dict[str, Any]) -> bool:
        """Conservative phase gate for compiled enemy actions.

        Enemy templates often carry `phase_list` from MonsterSkillConfig.  Generated
        routes should not use phase-2-only skills while the unit is still in phase 1.
        Exact route replay may still call a specific action manually, but auto-probe
        and AI fallback use this guard.
        """
        phases = action.get("phase_list") or (action.get("metadata") or {}).get("phase_list")
        if not phases:
            return True
        phase = coerce_int(actor.flags.get("current_phase", actor.flags.get("monster_phase", 1)), 1)
        allowed = set()
        for x in phases:
            try:
                allowed.add(int(x))
            except Exception:
                pass
        return not allowed or phase in allowed


    def tick_enemy_skill_cooldowns_after_action(self, actor: UnitState, used_action_id: str, ctx: Optional[dict[str, Any]] = None) -> None:
        if actor.side != "enemy":
            return
        cooldowns = actor.flags.get("enemy_skill_cooldowns")
        if not isinstance(cooldowns, dict):
            cooldowns = {}
        cooldowns = {str(k): max(0, coerce_int(v, 0) - 1) for k, v in cooldowns.items()}
        cd_cfg = actor.flags.get("enemy_skill_cooldown_config")
        if isinstance(cd_cfg, dict):
            cfg = cd_cfg.get(str(used_action_id))
            if isinstance(cfg, dict):
                cd = coerce_int(cfg.get("cd", 0), 0)
                if cd > 0:
                    cooldowns[str(used_action_id)] = cd
        self.commit_unit_flag(actor, "enemy_skill_cooldowns", cooldowns, reason="enemy_ai:tick_skill_cooldowns", ctx=ctx, payload={"used_action_id": used_action_id})

    def record_enemy_skill_use_after_action(self, actor: UnitState, action_id: str, ctx: Optional[dict[str, Any]] = None) -> None:
        if actor.side != "enemy" or not action_id:
            return
        counter = coerce_int(actor.flags.get("enemy_action_counter", 0), 0) + 1
        self.commit_unit_flag(actor, "enemy_action_counter", counter, reason="enemy_ai:record_skill_use:counter", ctx=ctx, payload={"action_id": action_id})
        counts = actor.flags.get("enemy_skill_use_counts")
        if not isinstance(counts, dict):
            counts = {}
        counts[str(action_id)] = coerce_int(counts.get(str(action_id), 0), 0) + 1
        self.commit_unit_flag(actor, "enemy_skill_use_counts", counts, reason="enemy_ai:record_skill_use:counts", ctx=ctx, payload={"action_id": action_id})
        record = actor.flags.get("enemy_skill_use_record")
        if not isinstance(record, dict):
            record = {}
        record[str(action_id)] = {"action_counter": counter, "count": counts[str(action_id)]}
        self.commit_unit_flag(actor, "enemy_skill_use_record", record, reason="enemy_ai:record_skill_use:record", ctx=ctx, payload={"action_id": action_id})
        if str(actor.flags.get("enemy_ai_pending_target_action") or "") == str(action_id):
            self.commit_unit_flag_remove(actor, "enemy_ai_pending_target_selector", reason="enemy_ai:record_skill_use:clear_pending_selector", ctx=ctx, payload={"action_id": action_id})
            self.commit_unit_flag_remove(actor, "enemy_ai_pending_target_action", reason="enemy_ai:record_skill_use:clear_pending_action", ctx=ctx, payload={"action_id": action_id})
        self.tick_enemy_skill_cooldowns_after_action(actor, str(action_id), ctx=ctx)
        self.state.log_event("enemy_ai", f"{actor.id} records skill use {action_id}", {"action_counter": counter, "counts": counts, "cooldowns": actor.flags.get("enemy_skill_cooldowns", {})})

    def advance_enemy_ai_sequence_after_action(self, actor: UnitState, action_id: str, ctx: Optional[dict[str, Any]] = None) -> None:
        """Advance AI cursor using the current cursor, not `seq.index`.

        ConfigAI-derived sequences may legitimately contain duplicate action ids
        in different decision branches.  Using `seq.index(action_id)` loops forever
        on the first duplicate; advancing from the old cursor preserves the
        deterministic baseline order for smoke/exact-route harnesses.
        """
        seq = [str(x) for x in actor.flags.get("enemy_ai_sequence", []) if str(x) in actor.action_defs]
        if not seq:
            return
        old_idx = coerce_int(actor.flags.get("enemy_ai_sequence_index", 0), 0) % len(seq)
        action_id_s = str(action_id)
        if seq[old_idx] == action_id_s:
            new_idx = (old_idx + 1) % len(seq)
        else:
            matches = [i for i, x in enumerate(seq) if x == action_id_s]
            new_idx = ((matches[0] + 1) % len(seq)) if matches else old_idx
        self.commit_unit_flag(actor, "enemy_ai_sequence_index", new_idx, reason="enemy_ai:advance_sequence", ctx=ctx, payload={"sequence": seq, "used_action": action_id_s, "old_index": old_idx})
        self.state.log_event("enemy_ai", f"{actor.id} AI sequence {old_idx}->{new_idx}", {"sequence": seq, "used_action": action_id_s})

    def apply_enemy_ai_decision_effects(self, actor: UnitState, decision: dict[str, Any]) -> None:
        ctx = {"actor_id": actor.id, "actor": actor, "context": {"phase": "enemy_ai_decision"}, "phase_locked_targets": set()}
        for eff in decision.get("pre_effects") or []:
            if isinstance(eff, dict):
                self.apply_effect(eff, ctx)

    def enemy_ai_decision_score(self, actor: UnitState, decision: dict[str, Any], cond_ctx: dict[str, Any]) -> float:
        """Deterministic baseline for TBGD DefaultDSE-style scores."""
        score = coerce_float(decision.get("ai_score_base", 0.0), 0.0)
        for axis in decision.get("ai_score_axes") or []:
            if not isinstance(axis, dict):
                continue
            try:
                if self.eval_condition(axis.get("condition", True), cond_ctx):
                    score += coerce_float(axis.get("score", 0.0), 0.0)
            except Exception as exc:
                self.state.log_event("enemy_ai", "AI score axis skipped", {"actor": actor.id, "axis": axis, "error": str(exc)})
        # RandomConfig remains deterministic for exact-route validation. Weight
        # is a tiny tie-break contribution, not stochastic sampling.
        if "random_weight" in decision:
            score += coerce_float(decision.get("random_weight", 0.0), 0.0) * 1e-6
        return score

    def select_enemy_ai_decision_action_id(self, actor: UnitState, restrict_action_id: str | None = None, *, reason: str = "score_fallback") -> str | None:
        decisions = actor.flags.get("enemy_ai_decisions")
        if not isinstance(decisions, list) or coerce_bool(actor.flags.get("does_not_act", False), default=False):
            return None
        restrict_s = str(restrict_action_id) if restrict_action_id else None
        candidates: list[tuple[float, int, str, dict[str, Any]]] = []
        for idx, decision in enumerate(decisions):
            if not isinstance(decision, dict):
                continue
            action_id = str(decision.get("skill") or decision.get("action") or "")
            if action_id == "__sequenced_skill__":
                seq = [str(x) for x in actor.flags.get("enemy_ai_sequence", []) if str(x) in actor.action_defs]
                if seq:
                    action_id = seq[coerce_int(actor.flags.get("enemy_ai_sequence_index", 0), 0) % len(seq)]
            if restrict_s is not None and action_id != restrict_s:
                continue
            if not action_id or action_id not in actor.action_defs:
                continue
            action = actor.action_defs.get(action_id, {})
            if not self.enemy_action_phase_allowed(actor, action):
                continue
            cond_ctx = {"actor_id": actor.id, "actor": actor, "action": action, "context": {"phase": "enemy_ai_decision", "decision_index": idx, "reason": reason}, "phase_locked_targets": set()}
            if not self.eval_condition(decision.get("condition", True), cond_ctx):
                continue
            payable, _reason = self.can_pay_action_cost(actor, action)
            if not payable:
                continue
            score = self.enemy_ai_decision_score(actor, decision, cond_ctx)
            candidates.append((score, idx, action_id, decision))
        if not candidates:
            return None
        # Highest score wins only within the allowed candidate set.  In
        # scripted_sequence_first mode this set is normally restricted to the
        # current sequence action; global scores are fallback, not the main
        # action-order driver.  Lower source index is the deterministic tie-break.
        score, idx, action_id, decision = sorted(candidates, key=lambda row: (-row[0], row[1]))[0]
        self.apply_enemy_ai_decision_effects(actor, decision)
        if isinstance(decision.get("target_selector"), dict):
            self.commit_unit_flag(actor, "enemy_ai_pending_target_selector", deepcopy(decision.get("target_selector")), reason="enemy_ai:select_decision:pending_target_selector", payload={"action_id": action_id, "decision_index": idx})
            self.commit_unit_flag(actor, "enemy_ai_pending_target_action", action_id, reason="enemy_ai:select_decision:pending_target_action", payload={"decision_index": idx})
        self.commit_unit_flag(actor, "enemy_ai_last_decision_index", idx, reason="enemy_ai:select_decision:last_decision_index", payload={"action_id": action_id, "reason": reason})
        self.commit_unit_flag(actor, "enemy_ai_last_action", action_id, reason="enemy_ai:select_decision:last_action", payload={"decision_index": idx, "reason": reason})
        self.commit_unit_flag(actor, "enemy_ai_last_decision_score", score, reason="enemy_ai:select_decision:last_score", payload={"action_id": action_id, "decision_index": idx})
        self.commit_unit_flag(actor, "enemy_ai_last_selection_reason", reason, reason="enemy_ai:select_decision:last_reason", payload={"action_id": action_id, "decision_index": idx})
        self.state.log_event("enemy_ai", f"{actor.id} selects {action_id} via {reason} decision {idx}", {"decision": decision, "score": score, "candidate_count": len(candidates), "restricted_action": restrict_s})
        return action_id

    def current_scripted_enemy_action_id(self, actor: UnitState) -> str | None:
        seq = [str(x) for x in actor.flags.get("enemy_ai_sequence", []) if str(x) in actor.action_defs]
        if not seq or coerce_bool(actor.flags.get("does_not_act", False), default=False):
            return None
        idx = coerce_int(actor.flags.get("enemy_ai_sequence_index", 0), 0) % len(seq)
        return seq[idx]

    def enemy_action_available_now(self, actor: UnitState, action_id: str) -> tuple[bool, str]:
        if not action_id or action_id not in actor.action_defs:
            return False, "missing_action"
        action = actor.action_defs.get(action_id, {})
        if not self.enemy_action_phase_allowed(actor, action):
            return False, "phase_gate"
        payable, reason = self.can_pay_action_cost(actor, action)
        if not payable:
            return False, str(reason or "cost")
        return True, "ok"

    def scripted_enemy_action_id(self, actor: UnitState) -> str | None:
        """Return the current fixed-sequence enemy action when it is legal.

        Most monster AIs are scripted sequence/state-machine first.  Score-based
        decisions rank branches and fallback choices; they should not globally
        jump ahead of the current sequence action when that action is legal.
        """
        action_id = self.current_scripted_enemy_action_id(actor)
        if not action_id:
            return None
        ok, reason = self.enemy_action_available_now(actor, action_id)
        if not ok:
            self.commit_unit_flag(actor, "enemy_ai_last_scripted_block_reason", {"action": action_id, "reason": reason}, reason="enemy_ai:scripted_block", payload={"action_id": action_id})
            self.state.log_event("enemy_ai", f"{actor.id} scripted action {action_id} blocked: {reason}", {"action": action_id, "reason": reason})
            return None
        # Apply decision side-effects/target selectors only for the current
        # scripted action.  If ConfigAI has conditional branches for this action
        # and none pass, do not raw-play the action; enter fallback scoring so
        # AIFlag/state-machine branches can choose the next legal scripted step.
        decisions = actor.flags.get("enemy_ai_decisions")
        has_decision_for_current = False
        if isinstance(decisions, list):
            for d in decisions:
                if not isinstance(d, dict):
                    continue
                did = str(d.get("skill") or d.get("action") or "")
                if did == "__sequenced_skill__" or did == action_id:
                    has_decision_for_current = True
                    break
        decided_current = self.select_enemy_ai_decision_action_id(actor, restrict_action_id=action_id, reason="scripted_sequence_current")
        if decided_current:
            return decided_current
        if has_decision_for_current:
            self.commit_unit_flag(actor, "enemy_ai_last_scripted_block_reason", {"action": action_id, "reason": "scripted_decision_condition"}, reason="enemy_ai:scripted_decision_condition", payload={"action_id": action_id})
            self.state.log_event("enemy_ai", f"{actor.id} scripted action {action_id} waits for a matching decision", {"sequence_index": actor.flags.get("enemy_ai_sequence_index")})
            return None
        self.commit_unit_flag(actor, "enemy_ai_last_action", action_id, reason="enemy_ai:scripted_sequence_current:last_action", payload={"sequence_index": actor.flags.get("enemy_ai_sequence_index")})
        self.commit_unit_flag(actor, "enemy_ai_last_selection_reason", "scripted_sequence_current", reason="enemy_ai:scripted_sequence_current:last_reason", payload={"action_id": action_id})
        self.state.log_event("enemy_ai", f"{actor.id} selects {action_id} via scripted sequence", {"sequence_index": actor.flags.get("enemy_ai_sequence_index")})
        return action_id

    def default_probe_action_id(self, actor: UnitState) -> str | None:
        """Pick a deterministic low-risk action for generated-template smoke probes."""
        if actor.side == "enemy":
            forced = actor.flags.get("forced_next_enemy_action")
            if forced and str(forced) in actor.action_defs:
                action = actor.action_defs.get(str(forced), {})
                if self.enemy_action_phase_allowed(actor, action):
                    self.commit_unit_flag_remove(actor, "forced_next_enemy_action", reason="enemy_ai:consume_forced_next_action", payload={"action": str(forced)})
                    self.apply_effect({"type": "remove_status", "target": actor.id, "status_id": "charging"}, {"actor_id": actor.id, "actor": actor, "context": {"phase": "forced_next_enemy_action"}, "phase_locked_targets": set()})
                    self.state.log_event("enemy_ai", f"{actor.id} uses forced next enemy action {forced}", {"action": str(forced)})
                    return str(forced)
            mode = str(actor.flags.get("enemy_ai_mode") or "scripted_sequence_first")
            if mode in {"scripted_sequence_first", "scripted_first", "sequence_first"}:
                scripted = self.scripted_enemy_action_id(actor)
                if scripted:
                    return scripted
                decided = self.select_enemy_ai_decision_action_id(actor, reason="score_fallback_after_scripted_block")
                if decided:
                    return decided
            else:
                decided = self.select_enemy_ai_decision_action_id(actor, reason="score_first")
                if decided:
                    return decided
        if actor.side == "enemy" and isinstance(actor.flags.get("enemy_ai_sequence"), list):
            # Conservative fallback for legacy cases without an explicit AI mode:
            # do not scan past the current scripted action before score/fallback
            # has had a chance, otherwise fixed enemy patterns can silently skip
            # ahead.  If no decision path exists, retain old smoke behavior by
            # selecting the first legal action in sequence order.
            seq = [str(x) for x in actor.flags.get("enemy_ai_sequence") if str(x) in actor.action_defs]
            if seq and not coerce_bool(actor.flags.get("does_not_act", False), default=False):
                start_idx = coerce_int(actor.flags.get("enemy_ai_sequence_index", 0), 0) % len(seq)
                for offset in range(len(seq)):
                    action_id = seq[(start_idx + offset) % len(seq)]
                    ok, _reason = self.enemy_action_available_now(actor, action_id)
                    if ok:
                        return action_id
        preferences = []
        if coerce_bool(actor.flags.get("is_enhanced") or actor.flags.get("souldragon_enhanced"), default=False):
            preferences.append({"souldragon_enhanced", "enhanced"})
        preferences.extend([
            {"basic", "basic_use", "normal"},
            {"skill", "skill_use", "controlskill01", "controlskill02"},
            {"ultimate", "ultimate_use", "ultra"},
        ])
        candidates = []
        for key, action in actor.action_defs.items():
            if not isinstance(action, dict):
                continue
            tags = {str(t).lower() for t in normalize_str_list(action.get("tags", []))}
            action_type = str(action.get("action_type") or "").lower()
            candidates.append((str(action.get("id") or key), tags | {action_type}, action))
        for pref in preferences:
            for action_id, tags, action in candidates:
                if actor.side == "enemy" and not self.enemy_action_phase_allowed(actor, action):
                    continue
                if tags.intersection(pref):
                    payable, _reason = self.can_pay_action_cost(actor, action)
                    if payable:
                        return action_id
        for action_id, _tags, action in candidates:
            if actor.side == "enemy" and not self.enemy_action_phase_allowed(actor, action):
                continue
            payable, _reason = self.can_pay_action_cost(actor, action)
            if payable:
                return action_id
        return None


    # ---------- audit / replay snapshots ----------
    def status_audit_record(self, status: StatusEffect) -> dict[str, Any]:
        """Human-readable status record for full scene snapshots.

        This is intentionally more verbose than StatusEffect.to_json(): route
        validation needs to know not only that a status exists, but also who
        created it, how long it lasts, which modifier keys it can affect, and
        what raw payload will be consumed by the formula/runtime.
        """
        mods = status.modifiers if isinstance(status.modifiers, dict) else {}
        rec = {
            "id": status.id,
            "source_id": status.source_id,
            "stacks": status.stacks,
            "max_stacks": status.max_stacks,
            "duration": {
                "type": status.duration_type,
                "value": status.duration_value,
                "extra_turn_consumes": status.duration_extra_turn_consumes,
                "refresh_duration": status.refresh_duration,
            },
            "tags": sorted(status.tags),
            "modifier_keys": sorted(str(k) for k in mods.keys()),
            "modifiers": deepcopy(mods),
        }
        # Phase 2.5: 自动补中文名和类型（利用 StatusRegistry）
        if self._status_registry is not None:
            try:
                info = self._status_registry.lookup(status.id)
                if info is not None:
                    rec["status_name_cn"] = info.name_cn
                    rec["status_type"] = info.status_type
            except Exception:
                pass
        return rec

    def unit_panel_snapshot(self, unit: UnitState) -> dict[str, Any]:
        """Return current battle-facing panel stats computed through UnitState.

        These are the numbers that later damage/healing/shield/AV formulas should
        consume.  Keeping base/pct/flat next to the final panel makes snapshot
        diffs useful when a buff expires or a dynamic property changes.
        """
        keys = [
            "hp", "max_hp", "atk", "attack", "def", "defense", "speed",
            "crit_rate", "crit_dmg", "break_effect", "effect_hit_rate",
            "effect_res", "energy_regeneration_rate", "err_bonus", "err",
            "all_dmg_bonus", "physical_dmg_bonus", "fire_dmg_bonus",
            "ice_dmg_bonus", "thunder_dmg_bonus", "wind_dmg_bonus",
            "quantum_dmg_bonus", "imaginary_dmg_bonus", "all_res_pen",
            "physical_res_pen", "fire_res_pen", "ice_res_pen",
            "thunder_res_pen", "wind_res_pen", "quantum_res_pen",
            "imaginary_res_pen", "healing_bonus", "outgoing_healing_bonus",
            "damage_taken", "damage_reduction",
        ]
        panel: dict[str, Any] = {}
        for key in keys:
            try:
                val = self.contextual_stat(unit, key, {"actor_id": unit.id, "actor": unit}) if key not in {"hp", "max_hp"} else getattr(unit, key, None)
            except Exception:
                val = unit.get_stat(key)
            if val is not None and abs(coerce_float(val, 0.0)) > EPS:
                panel[key] = round(coerce_float(val, 0.0), 6)
        return panel

    def special_mechanic_snapshot(self, unit: UnitState) -> dict[str, Any]:
        """Extract visible special-mechanic state from flags and status payloads."""
        flag_keys = [
            "current_phase", "monster_phase", "enemy_action_counter",
            "enemy_ai_sequence_index", "enemy_skill_cooldowns",
            "enemy_skill_cooldown_config", "enemy_ai_sequence",
            "phase_transition_immediate_action", "clear_glory_after_next_savage_action",
            "owner_id", "attached_to", "corresponding_summon", "corresponding_ally",
            "max_restorable_hp_ratio", "bondmate", "bondmate_target",
        ]
        out: dict[str, Any] = {k: deepcopy(unit.flags.get(k)) for k in flag_keys if k in unit.flags}
        status_payloads: dict[str, list[dict[str, Any]]] = {}
        for st in unit.statuses:
            mods = st.modifiers if isinstance(st.modifiers, dict) else {}
            for key in (
                "armor_layers", "titanic_corpus", "count_attacks_taken",
                "immediate_action_on_hit_by_element", "break_dot",
                "break_delayed_damage", "zone_followup_true_damage",
                "souldragon", "shield_expire_remove_amount",
            ):
                if key in mods:
                    status_payloads.setdefault(key, []).append({"status_id": st.id, "stacks": st.stacks, "payload": deepcopy(mods.get(key))})
        if status_payloads:
            out["status_payloads"] = status_payloads
        if unit.side == "enemy":
            next_action = self.default_probe_action_id(unit) if unit.alive else None
            out["inferred_next_action"] = next_action
        return out

    def full_scene_snapshot(self) -> dict[str, Any]:
        """Full scene state after/before a route step.

        This snapshot is designed for battle solving, not only smoke testing:
        it preserves the action axis, every unit resource, current panel stats,
        statuses with source/duration/modifiers, queues and visible enemy/summon
        mechanic state.
        """
        axis = []
        for unit in self.state.units.values():
            if "not_on_timeline" in unit.tags:
                continue
            interval = self.action_interval(unit) if unit.alive else None
            axis.append({
                "id": unit.id,
                "name": unit.name,
                "side": unit.side,
                "alive": unit.alive,
                "speed": round(self.effective_speed(unit), 6),
                "action_interval": None if interval is None else round(interval, 6),
                "remaining_av": round(unit.remaining_av, 6),
                "absolute_av": round(self.state.av + unit.remaining_av, 6),
                "tags": sorted(unit.tags),
            })
        axis.sort(key=lambda r: (not r["alive"], r["remaining_av"], r["side"], r["id"]))

        def entity_record(unit: UnitState) -> dict[str, Any]:
            rec = {
                "id": unit.id,
                "name": unit.name,
                "side": unit.side,
                "alive": unit.alive,
                "tags": sorted(unit.tags),
                "resources": {
                    "hp": round(unit.hp, 6),
                    "max_hp": round(unit.max_hp, 6),
                    "hp_percent": round(unit.hp_percent, 6),
                    "shield": round(unit.shield, 6),
                    "energy": round(unit.energy, 6),
                    "max_energy": round(unit.max_energy, 6),
                    "toughness": None if unit.toughness is None else round(unit.toughness, 6),
                    "max_toughness": None if unit.max_toughness is None else round(unit.max_toughness, 6),
                    "is_broken": unit.is_broken,
                    "hp_bars_total": unit.hp_bars_total,
                    "hp_bars_remaining": unit.hp_bars_remaining,
                    "hp_model_type": unit.hp_model_type,
                    "hp_carry_over_damage": unit.hp_carry_over_damage,
                },
                "action_axis": {
                    "remaining_av": round(unit.remaining_av, 6),
                    "absolute_av": round(self.state.av + unit.remaining_av, 6),
                    "speed": round(self.effective_speed(unit), 6),
                    "action_interval": None if not unit.alive else round(self.action_interval(unit), 6),
                },
                "panel": self.unit_panel_snapshot(unit),
                "stat_parts": {
                    "base": deepcopy(unit.stat_base),
                    "pct": deepcopy(unit.stat_pct),
                    "flat": deepcopy(unit.stat_flat),
                    "legacy_stats": deepcopy(unit.stats),
                },
                "resistance": deepcopy(unit.res),
                "weaknesses": sorted(unit.weaknesses),
                "statuses": [self.status_audit_record(st) for st in unit.statuses],
                "special_mechanics": self.special_mechanic_snapshot(unit),
                "flags": deepcopy(unit.flags),
            }
            return rec

        allies: list[dict[str, Any]] = []
        summons: list[dict[str, Any]] = []
        enemies: list[dict[str, Any]] = []
        others: list[dict[str, Any]] = []
        for unit in self.state.units.values():
            rec = entity_record(unit)
            tag_l = {str(t).lower() for t in unit.tags}
            if unit.side == "ally" and ("summon" in tag_l or unit.flags.get("owner_id")):
                summons.append(rec)
            elif unit.side == "ally":
                allies.append(rec)
            elif unit.side == "enemy":
                enemies.append(rec)
            else:
                others.append(rec)
        return {
            "global": {
                "av": round(self.state.av, 6),
                "cycle": self.state.cycle,
                "skill_points": self.state.skill_points,
                "skill_point_cap": self.state.skill_point_cap,
                "_sp": int(self.state.skill_points),
                "_sp_cap": int(self.state.skill_point_cap),
                "wave_index": self.state.wave_index,
                "flags": deepcopy(self.state.global_flags),
            },
            "action_axis": axis,
            "allies": allies,
            "summons": summons,
            "enemies": enemies,
            "others": others,
            "queues": {
                "ultimate_queue": list(self.state.ultimate_queue),
                "immediate_queue": list(self.state.immediate_queue),
                "interrupt_queue": list(self.state.interrupt_queue),
            },
            "trigger_usage": deepcopy(self.state.trigger_usage),
        }

    def event_record(self, event: LogEvent, index: int | None = None) -> dict[str, Any]:
        rec = {"av": event.av, "event_type": event.event_type, "message": event.message, "data": deepcopy(event.data)}
        if index is not None:
            rec["index"] = index
        return rec

    def summarize_action_resolution(self, step: dict[str, Any], events: list[LogEvent]) -> dict[str, Any]:
        """Verbose per-step settlement ledger for replay and solver debugging."""
        records = [self.event_record(e, i) for i, e in enumerate(events)]
        def pick(types: set[str]) -> list[dict[str, Any]]:
            return [r for r in records if r["event_type"] in types]
        damage_events = pick({"damage", "effect_damage", "break_damage", "damage_skip", "primary_damage_overkill"})
        status_events = pick({"status_add", "status_remove", "status_expire", "duration_tick", "effect"})
        # `effect` is broad. Keep it in all_events, but only surface resource-like
        # effect records here when the message/data clearly changes battle state.
        resource_events = pick({"resource", "resource_skip", "shield", "heal", "hp_loss"})
        resource_events += [r for r in records if r["event_type"] == "effect" and any(k in str(r.get("message", "")).lower() for k in ("energy", "skill", "resource", "hp", "shield"))]
        av_events = pick({"av_change", "timeline", "cycle_update", "turn_start", "turn_end", "queue", "queued_action", "resolve_queue"})
        mechanism_events = [
            r for r in records
            if r["event_type"] in {
                "enemy_mechanic", "trigger", "trigger_skip", "break", "toughness",
                "phase_transition", "unit_defeated", "defeat", "wave", "action_block",
            }
        ]
        return {
            "requested": {
                "step_type": step.get("type", "action"),
                "actor": step.get("actor"),
                "action": step.get("action"),
                "timing": step.get("timing", step.get("turn_kind")),
                "targets": self.normalize_targets(step.get("targets")) if "targets" in step else None,
            },
            "damage_events": damage_events,
            "status_events": status_events,
            "resource_events": resource_events,
            "av_events": av_events,
            "mechanism_events": mechanism_events,
            "all_events": records,
        }

    def generated_route_snapshot(self) -> dict[str, Any]:
        """Small deterministic state snapshot for generated-template route harnesses."""
        enemies = []
        allies = []
        for unit in self.state.units.values():
            rec = {
                "id": unit.id,
                "alive": unit.alive,
                "hp": round(unit.hp, 6),
                "max_hp": round(unit.max_hp, 6),
                "shield": round(unit.shield, 6),
                "energy": round(unit.energy, 6),
                "max_energy": round(unit.max_energy, 6),
                "remaining_av": round(unit.remaining_av, 6),
                "toughness": None if unit.toughness is None else round(unit.toughness, 6),
                "max_toughness": None if unit.max_toughness is None else round(unit.max_toughness, 6),
                "is_broken": unit.is_broken,
                "hp_bars_remaining": unit.hp_bars_remaining,
                "status_count": len(unit.statuses),
            }
            if unit.side == "enemy":
                enemies.append(rec)
            elif unit.side == "ally":
                allies.append(rec)
        return {
            "av": round(self.state.av, 6),
            "skill_points": self.state.skill_points,
            "skill_point_cap": self.state.skill_point_cap,
            "_sp": int(self.state.skill_points),
            "_sp_cap": int(self.state.skill_point_cap),
            "allies": allies,
            "enemies": enemies,
            "queue_size": len(self.state.ultimate_queue) + len(self.state.immediate_queue) + len(self.state.interrupt_queue),
        }

    def summarize_auto_probe_events(self, events: list[LogEvent]) -> dict[str, Any]:
        """Compact per-step event summary for generated-template short routes."""
        event_counts: dict[str, int] = {}
        damage_total = 0.0
        toughness_damage_total = 0.0
        defeated_units: list[str] = []
        queued_event_count = 0
        for e in events or []:
            event_counts[e.event_type] = event_counts.get(e.event_type, 0) + 1
            data = e.data if isinstance(e.data, dict) else {}
            if e.event_type == "damage":
                damage_total += coerce_float(data.get("damage", 0.0))
                toughness_damage_total += coerce_float(data.get("toughness_damage", 0.0))
            if e.event_type in {"defeat", "unit_defeated"}:
                uid = data.get("target") or data.get("unit") or data.get("unit_id")
                if uid is not None:
                    defeated_units.append(str(uid))
            if e.event_type in {"queue", "queued_action", "resolve_queue", "extra_turn_start", "ultimate_queue"}:
                queued_event_count += 1
        return {
            "event_count": len(events or []),
            "event_counts": event_counts,
            "damage_total": round(damage_total, 6),
            "toughness_damage_total": round(toughness_damage_total, 6),
            "defeated_units": defeated_units,
            "queued_event_count": queued_event_count,
        }

    def validate_auto_probe_trace(self, trace: list[dict[str, Any]], expected_actions: list[str] | None = None) -> dict[str, Any]:
        """Return deterministic short-route assertions for generated-template probes.

        These assertions intentionally check simulator invariants rather than
        exact in-game strategy.  They make generated-template smoke routes useful
        for regression testing after generated statuses change the old handwritten
        action order.
        """
        failures: list[dict[str, Any]] = []
        checks = {
            "skill_points_in_bounds": True,
            "av_monotonic": True,
            "unit_resources_non_negative": True,
            "unit_resources_not_above_known_caps": True,
            "executed_actions_have_after_snapshot": True,
            "executed_actions_emit_events": True,
            "expected_action_prefix_match": True,
        }
        expected_actions = [str(x).strip() for x in (expected_actions or []) if str(x).strip()]
        for idx, expected in enumerate(expected_actions):
            if idx >= len(trace):
                checks["expected_action_prefix_match"] = False
                failures.append({"step": idx + 1, "check": "expected_action_missing", "expected": expected})
                continue
            entry = trace[idx] if isinstance(trace[idx], dict) else {}
            actual = f"{entry.get('actor')}.{entry.get('action')}"
            if actual != expected:
                checks["expected_action_prefix_match"] = False
                failures.append({"step": idx + 1, "check": "expected_action_mismatch", "expected": expected, "actual": actual})
        last_av: float | None = None
        for entry in trace or []:
            step = entry.get("step")
            before = entry.get("before") if isinstance(entry.get("before"), dict) else {}
            after = entry.get("after") if isinstance(entry.get("after"), dict) else {}
            if not after:
                checks["executed_actions_have_after_snapshot"] = False
                failures.append({"step": step, "check": "after_snapshot_missing"})
                continue
            event_summary = entry.get("event_summary") if isinstance(entry.get("event_summary"), dict) else {}
            if coerce_int(event_summary.get("event_count", 0), 0) <= 0:
                checks["executed_actions_emit_events"] = False
                failures.append({"step": step, "check": "action_emitted_no_events"})
            for label, snap in (("before", before), ("after", after)):
                sp = coerce_float(snap.get("skill_points", 0.0))
                cap = coerce_float(snap.get("skill_point_cap", 0.0))
                if sp < -EPS or sp - cap > EPS:
                    checks["skill_points_in_bounds"] = False
                    failures.append({"step": step, "snapshot": label, "check": "skill_points_out_of_bounds", "skill_points": sp, "skill_point_cap": cap})
                av = coerce_float(snap.get("av", 0.0))
                if last_av is not None and av + EPS < last_av:
                    checks["av_monotonic"] = False
                    failures.append({"step": step, "snapshot": label, "check": "av_decreased", "previous_av": last_av, "av": av})
                last_av = av
                for side in ("allies", "enemies"):
                    for unit in snap.get(side, []) or []:
                        hp = coerce_float(unit.get("hp", 0.0))
                        max_hp = coerce_float(unit.get("max_hp", 0.0))
                        energy = coerce_float(unit.get("energy", 0.0))
                        max_energy = coerce_float(unit.get("max_energy", 0.0))
                        remaining_av = coerce_float(unit.get("remaining_av", 0.0))
                        if hp < -EPS or energy < -EPS or remaining_av < -EPS:
                            checks["unit_resources_non_negative"] = False
                            failures.append({"step": step, "snapshot": label, "check": "negative_unit_resource", "unit": unit})
                        if max_hp > EPS and hp - max_hp > EPS:
                            checks["unit_resources_not_above_known_caps"] = False
                            failures.append({"step": step, "snapshot": label, "check": "hp_above_max_hp", "unit": unit})
                        if max_energy > EPS and energy - max_energy > EPS:
                            checks["unit_resources_not_above_known_caps"] = False
                            failures.append({"step": step, "snapshot": label, "check": "energy_above_max_energy", "unit": unit})
        return {
            "ok": not failures,
            "check_count": len(checks),
            "checks": checks,
            "failure_count": len(failures),
            "failures": failures[:20],
        }

    def run_auto_probe(self, steps: int = 1, expected_actions: list[str] | None = None) -> dict[str, Any]:
        """Run a deterministic generated-template smoke route.

        This is not an optimizer and not an exact in-game route.  It exists to
        validate that imported/generated status templates can survive real turn
        advancement and at least a few automatically selected actions after they
        have changed the original handwritten action order.
        """
        executed = 0
        attempts = 0
        action_trace: list[dict[str, Any]] = []
        max_attempts = max(1, int(steps)) * 5
        while executed < max(0, int(steps)) and attempts < max_attempts:
            attempts += 1
            self.drain_queues()
            if not self.state.active_units():
                self.state.log_event("auto_probe_stop", "No active units available", {"attempt": attempts, "executed": executed})
                break
            try:
                actor_id = self.advance_to_next_regular_actor()
            except Exception as exc:
                self.state.log_event("auto_probe_stop", f"Could not advance to next actor: {exc}", {"attempt": attempts, "executed": executed})
                break
            if actor_id not in self.state.units or not self.state.unit(actor_id).alive:
                self.state.log_event("auto_probe_skip", f"Actor {actor_id} unavailable", {"attempt": attempts, "executed": executed})
                continue
            actor = self.state.unit(actor_id)
            action_id = self.default_probe_action_id(actor)
            if not action_id:
                self.state.log_event("auto_probe_skip", f"Actor {actor_id} has no action definition", {"attempt": attempts, "executed": executed})
                self.begin_turn(actor, "regular", None)
                self.end_turn(actor, "regular", None)
                continue
            action = self.get_action_def(actor_id, action_id)
            try:
                targets = self.select_targets(action, None)
            except SimulatorError as exc:
                if not action.get("damage_packets"):
                    targets = []
                else:
                    self.state.log_event("auto_probe_skip", f"Skip {actor_id}.{action_id}: {exc}", {"attempt": attempts, "executed": executed})
                    self.begin_turn(actor, "regular", None)
                    self.end_turn(actor, "regular", None)
                    continue
            step_no = executed + 1
            self.state.log_event("auto_probe", f"Auto probe step {step_no}: {actor_id}.{action_id}", {"targets": targets, "attempt": attempts})
            trace_entry = {"step": step_no, "attempt": attempts, "actor": actor_id, "action": action_id, "targets": list(targets or []), "av": round(self.state.av, 6), "before": self.generated_route_snapshot()}
            action_trace.append(trace_entry)
            before_log_len = len(self.state.log)
            probe_step = {
                "actor": actor_id,
                "action": action_id,
                "timing": "auto_probe",
                "turn_kind": "regular",
                "targets": list(targets or []),
                "_route_step_index": step_no,
            }
            settlement = SettlementCollector(
                text_map=self._text_map,
                status_registry=self._status_registry,
                skill_registry=self._skill_registry,
            )
            action_request = ActionRequest.from_route_step(probe_step, targets or [])
            action_request.source.origin_path = f"auto_probe[{step_no}]"
            action_request.metadata["target_source"] = "auto_probe"
            settlement.begin_action(action_request)
            settlement.capture_before_snapshot(self.full_scene_snapshot())
            settlement.record_target(targets or [], method="auto_probe")
            self.resolve_action(action, targets or [], {}, context={"turn_kind": "regular", "auto_probe": True, "_settlement": settlement})
            settlement.capture_after_snapshot(self.full_scene_snapshot())
            new_events = self.state.log[before_log_len:]
            trace_entry["event_summary"] = self.summarize_auto_probe_events(new_events)
            trace_entry["action_resolution"] = self.summarize_action_resolution(probe_step, new_events)
            trace_entry["settlement"] = settlement.to_dict()
            trace_entry["after"] = self.generated_route_snapshot()
            trace_entry["after_scene"] = self.full_scene_snapshot()
            executed += 1
        self.drain_queues()
        result = self.result()
        result.setdefault("metadata", {})["auto_probe_executed_step_count"] = executed
        result["metadata"]["auto_probe_attempt_count"] = attempts
        result["metadata"]["auto_probe_action_trace"] = action_trace
        if expected_actions:
            result["metadata"]["auto_probe_expected_actions"] = list(expected_actions)
        result["metadata"]["auto_probe_assertions"] = self.validate_auto_probe_trace(action_trace, expected_actions=expected_actions)
        return result

    def summarize_property_hint_applications(self) -> dict[str, Any]:
        """Summarize runtime consumption of compiled StackProperty hints.

        This is validation metadata only.  It lets generated-template harnesses
        distinguish formula-affecting property hints from audit-only hints such as
        AttackConvert without scraping every status in the JSON state.
        """
        applied = 0
        skipped = 0
        by_property: dict[str, dict[str, int]] = {}
        by_reason: dict[str, int] = {}
        records: list[dict[str, Any]] = []
        for unit_id, unit in self.state.units.items():
            for st in unit.statuses:
                mods = st.modifiers if isinstance(st.modifiers, dict) else {}
                for app in mods.get("property_hint_applications", []) or []:
                    if not isinstance(app, dict):
                        continue
                    prop = str(app.get("property") or "")
                    rec = dict(app)
                    rec.update({"unit_id": unit_id, "status_id": st.id})
                    records.append(rec)
                    bucket = by_property.setdefault(prop, {"applied": 0, "skipped": 0})
                    if app.get("applied") is True:
                        applied += 1
                        bucket["applied"] += 1
                    else:
                        skipped += 1
                        bucket["skipped"] += 1
                        reason = str(app.get("reason") or "unknown")
                        by_reason[reason] = by_reason.get(reason, 0) + 1
        return {
            "applied_count": applied,
            "skipped_count": skipped,
            "by_property": by_property,
            "skipped_reason_counts": by_reason,
            "records": records,
        }

    def summarize_symbolic_formula_applications(self) -> dict[str, Any]:
        applied = 0
        skipped = 0
        by_reason: dict[str, int] = {}
        records: list[dict[str, Any]] = []
        for unit_id, unit in self.state.units.items():
            for st in unit.statuses:
                mods = st.modifiers if isinstance(st.modifiers, dict) else {}
                for app in mods.get("symbolic_formula_applications", []) or []:
                    if not isinstance(app, dict):
                        continue
                    rec = dict(app)
                    rec.update({"unit_id": unit_id, "status_id": st.id})
                    records.append(rec)
                    if app.get("applied") is True:
                        applied += 1
                    else:
                        skipped += 1
                        reason = str(app.get("reason") or "unknown")
                        by_reason[reason] = by_reason.get(reason, 0) + 1
        return {"applied_count": applied, "skipped_count": skipped, "skipped_reason_counts": by_reason, "records": records}

    def summarize_engine_property_reads(self) -> dict[str, Any]:
        attempted = 0
        resolved = 0
        unresolved = 0
        by_property: dict[str, dict[str, int]] = {}
        records: list[dict[str, Any]] = []
        for e in self.state.log:
            data = e.data if isinstance(e.data, dict) else {}
            prop = data.get("property")
            if prop is None:
                continue
            prop_s = str(prop)
            bucket = by_property.setdefault(prop_s, {"resolved": 0, "unresolved": 0})
            if e.event_type == "effect" and "from property" in str(e.message):
                attempted += 1
                resolved += 1
                bucket["resolved"] += 1
                records.append({"property": prop_s, "resolved": True, "event_type": e.event_type, "message": e.message, "data": data})
            elif e.event_type == "effect_skip" and "unresolved property" in str(e.message):
                attempted += 1
                unresolved += 1
                bucket["unresolved"] += 1
                records.append({"property": prop_s, "resolved": False, "event_type": e.event_type, "message": e.message, "data": data})
        return {"attempted_count": attempted, "resolved_count": resolved, "unresolved_count": unresolved, "by_property": by_property, "records": records}

    def result(self) -> dict[str, Any]:
        return {
            "state": self.state.to_json(),
            "scene": self.full_scene_snapshot(),
            "log": [asdict(e) for e in self.state.log],
            "metadata": {
                "queued_action_transitions": deepcopy(self._queued_action_transitions),
            },
            "runtime_audit": {
                "property_hint_applications": self.summarize_property_hint_applications(),
                "symbolic_formula_applications": self.summarize_symbolic_formula_applications(),
                "engine_property_reads": self.summarize_engine_property_reads(),
            },
        }


def load_case(path: str) -> dict[str, Any]:
    p = Path(path)
    if p.is_dir():
        return load_model_pack_case(p)
    with open(p, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    # A MANIFEST-like file can be supplied directly; otherwise this is a normal simulator case.
    if isinstance(raw, dict) and raw.get("kind") == "model_pack_manifest":
        return load_model_pack_case(p.parent)
    return raw


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="HSR simulator prototype route validator")
    parser.add_argument("case", nargs="?", help="YAML case file, model-pack directory, or MANIFEST.yaml")
    parser.add_argument("--model-pack", help="Canonical hsr_model_pack directory. Loads a compiled case from MANIFEST.yaml")
    parser.add_argument("--case-id", default=None, help="Compiled case id inside --model-pack, e.g. arbitration_4_3_knight_3_opening")
    parser.add_argument("--validate-model-pack", action="store_true", help="Print model-pack structural validation report and exit")
    parser.add_argument("--tbgd-source", help="TurnBasedGameData zip/directory. Use with --inspect-tbgd")
    parser.add_argument("--inspect-tbgd", action="store_true", help="Inspect TurnBasedGameData source and print/write a source summary")
    parser.add_argument("--analyze-engine-property", help="Audit one engine-side property usage in TurnBasedGameData ConfigAbility graphs, e.g. AttackConvert")
    parser.add_argument("--analyze-engine-property-inventory", action="store_true", help="Audit all property read/write/watch usage in TurnBasedGameData ConfigAbility graphs")
    parser.add_argument("--engine-property-output-dir", help="Output directory for --analyze-engine-property / --analyze-engine-property-inventory")
    parser.add_argument("--write-mechanism-glossary", action="store_true", help="Write bilingual/Chinese mechanism glossary for internal terms")
    parser.add_argument("--audit-genericity", action="store_true", help="Write genericity/refactor audit for fallback vs data-driven mechanics")
    parser.add_argument("--audit-enemy-mechanisms", action="store_true", help="Inventory enemy mechanism hints in the model pack")
    parser.add_argument("--audit-break-formulas", action="store_true", help="Write break/super-break formula audit with Chinese explanations")
    parser.add_argument("--audit-current-team-mechanisms", action="store_true", help="Audit current-team character mechanisms against public/TBGD checklist")
    parser.add_argument("--mechanism-audit-output-dir", help="Output directory for glossary/genericity/enemy/break audits")
    parser.add_argument("--derive-souldragon-template", action="store_true", help="Derive Dan Heng PT Souldragon fallback action template from TurnBasedGameData skill params")
    parser.add_argument("--souldragon-template-output-dir", help="Output directory for --derive-souldragon-template")
    parser.add_argument("--generate-enemy-route-harness", action="store_true", help="Generate executable exact-route smoke cases from model-pack enemy templates")
    parser.add_argument("--scan-tbgd-enemy-database", action="store_true", help="Scan TurnBasedGameData enemy tables/graphs and emit generic enemy template")
    parser.add_argument("--compile-enemy-templates", action="store_true", help="Compile model-pack enemy templates into runtime units/actions/statuses")
    parser.add_argument("--lower-monster-ability-graphs", action="store_true", help="Audit/lower Monster ConfigAbility graphs into conservative preview IR")
    parser.add_argument("--enemy-route-harness-output-dir", help="Output directory for --generate-enemy-route-harness")
    parser.add_argument("--enemy-template-output-dir", help="Output directory for --compile-enemy-templates")
    parser.add_argument("--monster-ability-output-dir", help="Output directory for --lower-monster-ability-graphs")
    parser.add_argument("--monster-ability-max-files", type=int, default=-1, help="Optional file limit for --lower-monster-ability-graphs; -1 scans all")
    parser.add_argument("--tbgd-output-dir", help="Optional directory for extracted normalized source catalogs")
    parser.add_argument("--compile-tbgd-content", action="store_true", help="Compile TurnBasedGameData into canonical Content IR bundle")
    parser.add_argument("--content-output-dir", help="Output directory for --compile-tbgd-content")
    parser.add_argument("--stage-limit", type=int, default=500, help="StageConfig row limit for --compile-tbgd-content; use -1 for all")
    parser.add_argument("--inspect-ability-graphs", action="store_true", help="Inventory ConfigAbility/ConfigCharacter RPG.GameCore graphs")
    parser.add_argument("--ability-output-dir", help="Output directory for --inspect-ability-graphs")
    parser.add_argument("--ability-sample-limit", type=int, default=5, help="Samples per RPG.GameCore node type in ability inventory")
    parser.add_argument("--compile-action-ir", action="store_true", help="Compile selected TBGD avatars into candidate executable ActionIR")
    parser.add_argument("--action-ir-output-dir", help="Output directory for --compile-action-ir")
    parser.add_argument("--avatar-id", action="append", type=int, help="Avatar ID to compile for --compile-action-ir; repeatable")
    parser.add_argument("--action-ir-max-depth", type=int, default=5, help="Ability TriggerAbility traversal depth for --compile-action-ir")
    parser.add_argument("--bind-action-ir", action="store_true", help="Bind compiled ActionIR dynamic expressions to AvatarSkillConfig parameters")
    parser.add_argument("--action-ir-bundle", help="Path to targeted_action_ir_bundle.json for --bind-action-ir")
    parser.add_argument("--bound-action-ir-output-dir", help="Output directory for --bind-action-ir")
    parser.add_argument("--compile-status-ir", action="store_true", help="Compile bound ActionIR status hints into StatusIR")
    parser.add_argument("--bound-action-ir-bundle", help="Path to bound_action_ir_bundle.json for --compile-status-ir")
    parser.add_argument("--status-ir-output-dir", help="Output directory for --compile-status-ir")
    parser.add_argument("--bind-status-ir", action="store_true", help="Bind StatusIR dynamic expressions to source parameter contexts conservatively")
    parser.add_argument("--status-ir-bundle", help="Path to status_ir_bundle.json for --bind-status-ir")
    parser.add_argument("--bound-status-ir-output-dir", help="Output directory for --bind-status-ir")
    parser.add_argument("--compile-status-templates", action="store_true", help="Lower BoundStatusIR into simulator-facing status templates")
    parser.add_argument("--bound-status-ir-bundle", help="Path to bound_status_ir_bundle.json for --compile-status-templates")
    parser.add_argument("--status-template-output-dir", help="Output directory for --compile-status-templates")
    parser.add_argument("--status-template-tbgd-source", help="Optional TurnBasedGameData source for audit-only status property hints during --compile-status-templates")
    parser.add_argument("--status-template-bundle", help="Inject compiled StatusTemplate bundle into a simulation case")
    parser.add_argument("--status-template-owner-map", help="JSON object or JSON file mapping TBGD avatar ids to simulator unit ids")
    parser.add_argument("--output", "-o", help="Write result JSON to this path")
    parser.add_argument("--route-mode", choices=["exact", "import_only", "auto_probe"], default="exact", help="exact replays the case route; import_only resolves setup/import effects and skips the route; auto_probe runs deterministic generated-template smoke actions")
    parser.add_argument("--auto-probe-steps", type=int, default=1, help="Number of regular actions to auto-run for --route-mode auto_probe")
    parser.add_argument("--auto-probe-expected-actions", default="", help="Optional comma-separated actor.action prefix expected from auto_probe trace")
    args = parser.parse_args(argv)


    if args.derive_souldragon_template:
        if not args.tbgd_source:
            parser.error("--derive-souldragon-template requires --tbgd-source")
        out_dir = args.souldragon_template_output_dir or args.mechanism_audit_output_dir
        if not out_dir:
            parser.error("--derive-souldragon-template requires --souldragon-template-output-dir or --mechanism-audit-output-dir")
        result = write_souldragon_action_template(args.tbgd_source, out_dir)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
            print(args.output)
        else:
            print(text)
        return 0

    if args.scan_tbgd_enemy_database:
        if not args.tbgd_source:
            parser.error("--scan-tbgd-enemy-database requires --tbgd-source")
        out_dir = args.mechanism_audit_output_dir or args.tbgd_output_dir
        if not out_dir:
            parser.error("--scan-tbgd-enemy-database requires --mechanism-audit-output-dir or --tbgd-output-dir")
        result = write_enemy_database_scan(args.tbgd_source, out_dir, model_pack_dir=args.model_pack)
        compact = {
            "format": result.get("format"),
            "version": result.get("version"),
            "tables": result.get("tables"),
            "monster_ability_file_count": (result.get("monster_ability_graph_scan") or {}).get("monster_ability_file_count"),
            "monster_character_config_file_count": (result.get("monster_character_config_scan") or {}).get("monster_character_config_file_count"),
            "top_node_groups": (result.get("monster_ability_graph_scan") or {}).get("node_group_counts"),
        }
        text = json.dumps(compact, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
            print(args.output)
        else:
            print(text)
        return 0

    if args.generate_enemy_route_harness:
        if not args.model_pack:
            parser.error("--generate-enemy-route-harness requires --model-pack")
        out_dir = args.enemy_route_harness_output_dir or args.mechanism_audit_output_dir
        if not out_dir:
            parser.error("--generate-enemy-route-harness requires --enemy-route-harness-output-dir or --mechanism-audit-output-dir")
        result = write_enemy_route_harness(args.model_pack, out_dir)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
            print(args.output)
        else:
            print(text)
        return 0

    if args.compile_enemy_templates:
        if not args.model_pack:
            parser.error("--compile-enemy-templates requires --model-pack")
        out_dir = args.enemy_template_output_dir or args.mechanism_audit_output_dir
        if not out_dir:
            parser.error("--compile-enemy-templates requires --enemy-template-output-dir or --mechanism-audit-output-dir")
        result = compile_enemy_model_pack(args.model_pack, out_dir)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
            print(args.output)
        else:
            print(text)
        return 0

    if args.lower_monster_ability_graphs:
        if not args.tbgd_source:
            parser.error("--lower-monster-ability-graphs requires --tbgd-source")
        out_dir = args.monster_ability_output_dir or args.mechanism_audit_output_dir
        if not out_dir:
            parser.error("--lower-monster-ability-graphs requires --monster-ability-output-dir or --mechanism-audit-output-dir")
        max_files = None if args.monster_ability_max_files is None or args.monster_ability_max_files < 0 else args.monster_ability_max_files
        result = write_monster_ability_graph_lowering(args.tbgd_source, out_dir, max_files=max_files)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
            print(args.output)
        else:
            print(text)
        return 0

    if args.write_mechanism_glossary:
        if not args.mechanism_audit_output_dir:
            parser.error("--write-mechanism-glossary requires --mechanism-audit-output-dir")
        result = write_glossary_report(args.mechanism_audit_output_dir)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(text)
            print(args.output)
        else:
            print(text)
        return 0

    if args.audit_genericity:
        if not args.mechanism_audit_output_dir:
            parser.error("--audit-genericity requires --mechanism-audit-output-dir")
        result = write_genericity_audit(Path(__file__).resolve().parent, args.mechanism_audit_output_dir)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(text)
            print(args.output)
        else:
            print(text)
        return 0

    if args.audit_enemy_mechanisms:
        if not args.model_pack:
            parser.error("--audit-enemy-mechanisms requires --model-pack")
        if not args.mechanism_audit_output_dir:
            parser.error("--audit-enemy-mechanisms requires --mechanism-audit-output-dir")
        result = write_enemy_mechanism_inventory(args.model_pack, args.mechanism_audit_output_dir)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(text)
            print(args.output)
        else:
            print(text)
        return 0


    if args.audit_current_team_mechanisms:
        if not args.model_pack:
            parser.error("--audit-current-team-mechanisms requires --model-pack")
        if not args.mechanism_audit_output_dir:
            parser.error("--audit-current-team-mechanisms requires --mechanism-audit-output-dir")
        result = write_character_mechanism_audit(args.model_pack, args.mechanism_audit_output_dir)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(text)
            print(args.output)
        else:
            print(text)
        return 0

    if args.audit_break_formulas:
        if not args.mechanism_audit_output_dir:
            parser.error("--audit-break-formulas requires --mechanism-audit-output-dir")
        result = write_break_formula_audit(args.mechanism_audit_output_dir)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(text)
            print(args.output)
        else:
            print(text)
        return 0


    if args.analyze_engine_property:
        if not args.tbgd_source:
            parser.error("--analyze-engine-property requires --tbgd-source")
        if not args.engine_property_output_dir:
            parser.error("--analyze-engine-property requires --engine-property-output-dir")
        result = write_engine_property_evidence_report(args.tbgd_source, args.engine_property_output_dir, property_name=args.analyze_engine_property)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(text)
            print(args.output)
        else:
            print(text)
        return 0

    if args.analyze_engine_property_inventory:
        if not args.tbgd_source:
            parser.error("--analyze-engine-property-inventory requires --tbgd-source")
        if not args.engine_property_output_dir:
            parser.error("--analyze-engine-property-inventory requires --engine-property-output-dir")
        result = write_engine_property_inventory_report(args.tbgd_source, args.engine_property_output_dir)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(text)
            print(args.output)
        else:
            print(text)
        return 0



    if args.compile_status_templates:
        if not args.bound_status_ir_bundle:
            parser.error("--compile-status-templates requires --bound-status-ir-bundle")
        if not args.status_template_output_dir:
            parser.error("--compile-status-templates requires --status-template-output-dir")
        result = write_status_template_bundle(args.bound_status_ir_bundle, args.status_template_output_dir, tbgd_source=args.status_template_tbgd_source)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(text)
            print(args.output)
        else:
            print(text)
        return 0

    if args.bind_status_ir:
        if not args.status_ir_bundle:
            parser.error("--bind-status-ir requires --status-ir-bundle")
        if not args.tbgd_source:
            parser.error("--bind-status-ir requires --tbgd-source")
        if not args.bound_status_ir_output_dir:
            parser.error("--bind-status-ir requires --bound-status-ir-output-dir")
        result = write_bound_status_ir_bundle(args.status_ir_bundle, args.bound_status_ir_output_dir, args.tbgd_source)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(text)
            print(args.output)
        else:
            print(text)
        return 0

    if args.compile_status_ir:
        if not args.bound_action_ir_bundle:
            parser.error("--compile-status-ir requires --bound-action-ir-bundle")
        if not args.status_ir_output_dir:
            parser.error("--compile-status-ir requires --status-ir-output-dir")
        source = TBGDSource.open(args.tbgd_source) if args.tbgd_source else None
        result = write_status_ir_bundle(args.bound_action_ir_bundle, args.status_ir_output_dir, tbgd_source=source)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(text)
            print(args.output)
        else:
            print(text)
        return 0


    if args.bind_action_ir:
        if not args.tbgd_source:
            parser.error("--bind-action-ir requires --tbgd-source")
        if not args.action_ir_bundle:
            parser.error("--bind-action-ir requires --action-ir-bundle")
        if not args.bound_action_ir_output_dir:
            parser.error("--bind-action-ir requires --bound-action-ir-output-dir")
        result = write_bound_action_ir_bundle(args.tbgd_source, args.action_ir_bundle, args.bound_action_ir_output_dir)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(text)
            print(args.output)
        else:
            print(text)
        return 0


    if args.compile_action_ir:
        if not args.tbgd_source:
            parser.error("--compile-action-ir requires --tbgd-source")
        if not args.action_ir_output_dir:
            parser.error("--compile-action-ir requires --action-ir-output-dir")
        if not args.avatar_id:
            parser.error("--compile-action-ir requires at least one --avatar-id")
        result = write_target_avatar_action_ir(args.tbgd_source, args.action_ir_output_dir, args.avatar_id, max_depth=args.action_ir_max_depth)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(text)
            print(args.output)
        else:
            print(text)
        return 0


    if args.inspect_ability_graphs:
        if not args.tbgd_source:
            parser.error("--inspect-ability-graphs requires --tbgd-source")
        if not args.ability_output_dir:
            parser.error("--inspect-ability-graphs requires --ability-output-dir")
        result = write_ability_graph_inventory(args.tbgd_source, args.ability_output_dir, sample_limit=args.ability_sample_limit)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(text)
            print(args.output)
        else:
            print(text)
        return 0

    if args.compile_tbgd_content:
        if not args.tbgd_source:
            parser.error("--compile-tbgd-content requires --tbgd-source")
        if not args.content_output_dir:
            parser.error("--compile-tbgd-content requires --content-output-dir")
        stage_limit = None if args.stage_limit < 0 else args.stage_limit
        result = write_content_ir_bundle(args.tbgd_source, args.content_output_dir, include_stage_rows=stage_limit)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(text)
            print(args.output)
        else:
            print(text)
        return 0

    if args.inspect_tbgd:
        if not args.tbgd_source:
            parser.error("--inspect-tbgd requires --tbgd-source")
        if args.tbgd_output_dir:
            result = write_catalog_bundle(args.tbgd_source, args.tbgd_output_dir)
        else:
            result = TBGDSource.open(args.tbgd_source).core_catalog_summary()
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(text)
            print(args.output)
        else:
            print(text)
        return 0

    if args.model_pack:
        pack = ModelPack(args.model_pack)
        if args.validate_model_pack:
            result = pack.validate_index()
            text = json.dumps(result, ensure_ascii=False, indent=2)
            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    f.write(text)
                print(args.output)
            else:
                print(text)
            return 0 if result.get("ok") else 2
        case = pack.load_compiled_case(args.case_id)
    else:
        if not args.case:
            parser.error("case is required unless --model-pack is provided")
        case = load_case(args.case)

    if args.status_template_bundle:
        owner_map = parse_owner_unit_map(args.status_template_owner_map)
        owner_rank_map = parse_owner_rank_map(args.status_template_owner_map)
        case, import_summary = attach_status_template_bundle_to_case(case, load_status_template_bundle(args.status_template_bundle), owner_map, owner_rank_map=owner_rank_map)
        case.setdefault("metadata", {})["status_template_import_summary"] = import_summary

    sim = BattleSimulator(case)
    if args.route_mode == "auto_probe":
        expected_actions = [p.strip() for p in str(args.auto_probe_expected_actions or "").split(",") if p.strip()]
        result = sim.run_auto_probe(args.auto_probe_steps, expected_actions=expected_actions)
    else:
        route = [] if args.route_mode == "import_only" else case.get("route", [])
        result = sim.run_route(route)
    result.setdefault("metadata", {})["route_mode"] = args.route_mode
    if args.route_mode in {"import_only", "auto_probe"}:
        result["metadata"]["skipped_route_step_count"] = len(case.get("route", []) or [])
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
        print(args.output)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
