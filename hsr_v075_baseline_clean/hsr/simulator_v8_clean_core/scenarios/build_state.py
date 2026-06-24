from __future__ import annotations

from dataclasses import dataclass

from .identity import IdentityResolver
from .schema import PanelInput, ScenarioSpec
from ..core.model import ActionCommand, BattleState, UnitState
from ..rules.ir import CombatantProfileIR
from ..rules.rulebook import RuleBook


@dataclass(frozen=True)
class ScenarioBuildResult:
    state: BattleState
    commands: tuple[ActionCommand, ...]
    source_traces: tuple[dict[str, object], ...]


class ScenarioStateBuilder:
    def __init__(self, rules: RuleBook):
        self.rules = rules
        self.identity = IdentityResolver(rules)

    def build(self, scenario: ScenarioSpec) -> ScenarioBuildResult:
        validation = self.identity.validate(scenario)
        if not validation.ok:
            raise ValueError("; ".join(validation.errors))

        units = {}
        for unit in scenario.units:
            panel = unit.panel
            flags = dict(panel.flags)
            if unit.position is not None:
                flags["position"] = unit.position
            entity = self.rules.require_entity(unit.entity_ref)
            if unit.eidolon_level < 0 or unit.eidolon_level > 6:
                raise ValueError(f"unit {unit.unit_id}: eidolon_level must be between 0 and 6")
            if entity.entity_type == "avatar":
                card = self.rules.character_data_card_for_entity(unit.entity_ref)
                if card is not None:
                    eidolon_slots = self.rules.character_eidolon_slots_for_level(card.card_id, unit.eidolon_level)
                    flags["character_data_card_id"] = card.card_id
                    flags["eidolon_level_requested"] = unit.eidolon_level
                    flags["enabled_eidolon_ranks"] = tuple(slot.rank for slot in eidolon_slots)
                    flags["enabled_eidolon_slot_ids"] = tuple(slot.eidolon_slot_id for slot in eidolon_slots)
                    flags["enabled_eidolon_rank_ids"] = tuple(slot.rank_id for slot in eidolon_slots)
                    flags["enabled_eidolon_mechanism_slot_ids"] = tuple(
                        slot_id for slot in eidolon_slots for slot_id in slot.linked_mechanism_slot_ids
                    )
                    flags["eidolon_activation_policy"] = {
                        "kind": "prefix_closed",
                        "requested_level": unit.eidolon_level,
                        "independent_rank_toggle_allowed": False,
                    }
                    flags["eidolon_source_traces"] = tuple(slot.source.to_json() for slot in eidolon_slots)
                elif unit.eidolon_level:
                    raise ValueError(f"unit {unit.unit_id}: eidolon_level requires a character data card")
            profile = self.rules.combatant_profile(unit.entity_ref) if entity.entity_type in {"monster", "monster_template"} else None
            profile_values = _profile_values(profile)
            panel_overrides = _panel_overrides(panel, profile_values)
            if profile is not None:
                flags["combatant_profile_id"] = profile.profile_id
                flags["combatant_profile_source_trace"] = profile.source.to_json()
                flags["combatant_profile_coverage_status"] = profile.coverage_status
                if profile.blocked_reason:
                    flags["combatant_profile_blocked_reason"] = profile.blocked_reason
            if panel_overrides:
                flags["panel_overrides"] = panel_overrides
            if profile is not None and profile.coverage_status == "executable" and not _panel_has_flag(panel, "weaknesses"):
                flags["weaknesses"] = tuple(profile.weaknesses)
            elif entity.entity_type == "monster" and not _panel_has_flag(panel, "weaknesses"):
                weaknesses = entity.fields.get("StanceWeakList")
                if isinstance(weaknesses, list):
                    flags["weaknesses"] = tuple(str(item) for item in weaknesses)
            resources = _resources_with_profile_resistances(panel, profile)
            max_hp = _panel_or_profile_value(panel, "max_hp", profile_values, required=entity.entity_type in {"monster", "monster_template"})
            hp = panel.hp if _panel_has(panel, "hp") and panel.hp is not None else max_hp
            units[unit.unit_id] = UnitState(
                unit_id=unit.unit_id,
                side=unit.side,
                template_id=unit.entity_ref,
                level=unit.level,
                max_hp=max_hp,
                hp=hp,
                attack=_panel_or_profile_value(panel, "attack", profile_values, required=entity.entity_type in {"monster", "monster_template"}),
                defense=_panel_or_profile_value(panel, "defense", profile_values, required=entity.entity_type in {"monster", "monster_template"}),
                speed=_panel_or_profile_value(panel, "speed", profile_values, required=entity.entity_type in {"monster", "monster_template"}),
                energy=panel.energy,
                max_energy=panel.max_energy,
                toughness=_panel_or_profile_value(panel, "toughness", profile_values, required=entity.entity_type in {"monster", "monster_template"}),
                max_toughness=_panel_or_profile_value(panel, "max_toughness", profile_values, required=entity.entity_type in {"monster", "monster_template"}),
                action_value=panel.action_value,
                statuses=panel.statuses,
                flags=flags,
                resources=resources,
            )

        global_flags = dict(scenario.global_flags)
        if scenario.route:
            global_flags.setdefault("turn_owner_id", scenario.route[0].actor_id)
        global_flags.setdefault("phase", "scenario")
        global_flags.setdefault("current_window", "idle")
        state = BattleState(
            units=units,
            wave_index=scenario.wave_index,
            skill_points=scenario.skill_points,
            max_skill_points=scenario.max_skill_points,
            global_flags=global_flags,
            rng_state=scenario.rng_state,
        )
        commands = tuple(
            ActionCommand(
                actor_id=step.actor_id,
                action_id=step.action_ref,
                action_level=step.action_level,
                target_ids=step.target_ids,
                source=step.source,
                queue_name=step.queue_name,
                metadata=step.metadata,
            )
            for step in scenario.route
        )
        return ScenarioBuildResult(state=state, commands=commands, source_traces=validation.source_traces)


def _profile_values(profile: CombatantProfileIR | None) -> dict[str, float]:
    if profile is None or profile.coverage_status != "executable":
        return {}
    values: dict[str, float] = {}
    base_stats = profile.base_stats
    toughness_profile = profile.toughness_profile
    for key in ("max_hp", "attack", "defense", "speed"):
        value = base_stats.get(key)
        if isinstance(value, (int, float)):
            values[key] = float(value)
    toughness = toughness_profile.get("current_toughness")
    max_toughness = toughness_profile.get("max_toughness")
    if isinstance(toughness, (int, float)):
        values["toughness"] = float(toughness)
    if isinstance(max_toughness, (int, float)):
        values["max_toughness"] = float(max_toughness)
    return values


def _panel_or_profile_value(
    panel: PanelInput,
    key: str,
    profile_values: dict[str, float],
    *,
    required: bool,
) -> float:
    if _panel_has(panel, key):
        return float(getattr(panel, key))
    if key in profile_values:
        return profile_values[key]
    if required:
        raise ValueError(f"missing combatant profile value and explicit panel field {key!r}")
    return float(getattr(panel, key))


def _panel_has(panel: PanelInput, key: str) -> bool:
    return key in set(panel.explicit_fields)


def _panel_has_flag(panel: PanelInput, key: str) -> bool:
    return _panel_has(panel, "flags") and key in panel.flags


def _panel_overrides(panel: PanelInput, profile_values: dict[str, float]) -> tuple[str, ...]:
    return tuple(
        key
        for key in ("max_hp", "attack", "defense", "speed", "toughness", "max_toughness")
        if key in profile_values and _panel_has(panel, key)
    )


def _resources_with_profile_resistances(
    panel: PanelInput,
    profile: CombatantProfileIR | None,
) -> dict[str, float]:
    resources = dict(panel.resources)
    if profile is None or profile.coverage_status != "executable":
        return resources
    for damage_type, value in profile.resistances.items():
        if not isinstance(value, (int, float)):
            continue
        resources.setdefault(f"{damage_type}_resistance", float(value))
    return resources
