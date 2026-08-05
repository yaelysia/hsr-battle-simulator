from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from ..core.model import BattleState, JSONValue
from ..immutable_json import freeze_json
from ..unit_eligibility import (
    RuntimeCombatTeam as CombatTeam,
    runtime_unit_combat_team as combat_team_of,
    runtime_unit_is_dark_team as is_dark_team,
    runtime_unit_is_light_team as is_light_team,
    runtime_units_are_opposing_combat_teams as is_opposing_combat_team,
    runtime_units_share_combat_team as is_same_combat_team,
    runtime_unit_is_battle_event_entity,
    runtime_unit_is_unselectable,
)
from .summon_runtime import validate_summon_runtime
from .unit_lifecycle import UnitLifecycleSystem

if TYPE_CHECKING:
    from .target import TargetExpressionResult


@dataclass(frozen=True)
class TargetEvaluationContext:
    """Typed entity identities available to one target evaluation.

    Event payloads and other free-form dictionaries are intentionally absent.
    A producer may only populate identities represented by a formal field.
    """

    caster_id: str
    effect_owner_id: str | None = None
    parameter_entity_ids: tuple[str, ...] = ()
    selected_target_ids: tuple[str, ...] = ()
    current_target_id: str | None = None
    event_source_id: str | None = None
    event_subject_id: str | None = None
    event_target_id: str | None = None
    damage_attacker_id: str | None = None
    damage_defender_id: str | None = None
    turn_owner_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.caster_id, str) or not self.caster_id:
            raise ValueError("target context caster identity is required")
        for field_name in (
            "effect_owner_id", "current_target_id", "event_source_id",
            "event_subject_id", "event_target_id", "damage_attacker_id",
            "damage_defender_id", "turn_owner_id",
        ):
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"target context {field_name} must be a non-empty identity or null")
        for field_name in ("parameter_entity_ids", "selected_target_ids"):
            raw = getattr(self, field_name)
            if isinstance(raw, str):
                raise TypeError(f"target context {field_name} must be a tuple")
            values = tuple(raw)
            if any(not isinstance(value, str) or not value for value in values):
                raise ValueError(f"target context {field_name} contains an invalid identity")
            if len(values) != len(set(values)):
                raise ValueError(f"target context {field_name} contains duplicate identities")
            object.__setattr__(self, field_name, values)
        if (
            self.current_target_id is not None
            and self.selected_target_ids
            and self.current_target_id not in self.selected_target_ids
        ):
            raise ValueError("target context current target contradicts selected targets")

    @property
    def parameter_entity_id(self) -> str | None:
        return self.parameter_entity_ids[0] if self.parameter_entity_ids else None

    def with_parameter(self, unit_id: str) -> "TargetEvaluationContext":
        return TargetEvaluationContext(
            caster_id=self.caster_id,
            effect_owner_id=self.effect_owner_id,
            parameter_entity_ids=(unit_id,),
            selected_target_ids=self.selected_target_ids,
            current_target_id=self.current_target_id,
            event_source_id=self.event_source_id,
            event_subject_id=self.event_subject_id,
            event_target_id=self.event_target_id,
            damage_attacker_id=self.damage_attacker_id,
            damage_defender_id=self.damage_defender_id,
            turn_owner_id=self.turn_owner_id,
        )


def committed_turn_owner_id(state: BattleState) -> str | None:
    """Read the authoritative current actor from committed battle state."""

    value = state.global_flags.get("turn_owner_id")
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("committed turn owner identity is invalid")
    return value


EntityRelation = Literal[
    "context.caster", "context.owner", "context.parameter",
    "context.selected", "context.current", "context.event_source",
    "context.event_subject", "context.event_target",
    "context.damage_attacker", "context.damage_defender", "context.turn_owner",
    "team.same", "team.opposing", "team.light", "team.dark", "team.teammate",
    "summon.owner", "summon.summoner", "summon.owned",
    "formation.adjacent", "lifecycle.filter", "entity.servant",
    "entity.battle_event", "entity.creator", "entity.unselectable", "entity.partner", "entity.unique_name",
    "body_part.members", "body_part.owner",
]


class EntityRelationResolver:
    """The single target-facing reader of committed entity relations."""

    def __init__(self) -> None:
        self.lifecycle = UnitLifecycleSystem()

    def resolve(
        self,
        state: BattleState,
        relation: EntityRelation,
        context: TargetEvaluationContext,
        *,
        subject_ids: tuple[str, ...] = (),
        options: dict[str, JSONValue] | None = None,
    ) -> "TargetExpressionResult":
        options = freeze_json(options or {})
        assert isinstance(options, dict)
        context_reason = self._validate_context(state, context)
        if context_reason:
            return self._blocked(context_reason, relation)
        if isinstance(subject_ids, str):
            return self._blocked("relation_subjects_must_be_tuple", relation)
        subjects = tuple(subject_ids)
        if any(not isinstance(unit_id, str) or not unit_id for unit_id in subjects):
            return self._blocked("relation_subject_identity_invalid", relation)
        if len(subjects) != len(set(subjects)):
            return self._blocked("relation_subject_identity_duplicate", relation)
        missing = next((unit_id for unit_id in subjects if unit_id not in state.units), "")
        if missing:
            return self._blocked(f"relation_subject_unknown:{missing}", relation)

        context_values = {
            "context.caster": (context.caster_id,),
            "context.owner": (context.effect_owner_id,) if context.effect_owner_id else (),
            "context.parameter": context.parameter_entity_ids,
            "context.selected": context.selected_target_ids,
            "context.current": (context.current_target_id,) if context.current_target_id else (),
            "context.event_source": (context.event_source_id,) if context.event_source_id else (),
            "context.event_subject": (context.event_subject_id,) if context.event_subject_id else (),
            "context.event_target": (context.event_target_id,) if context.event_target_id else (),
            "context.damage_attacker": (context.damage_attacker_id,) if context.damage_attacker_id else (),
            "context.damage_defender": (context.damage_defender_id,) if context.damage_defender_id else (),
            "context.turn_owner": (context.turn_owner_id,) if context.turn_owner_id else (),
        }
        if relation in context_values:
            values = context_values[relation]
            if not values:
                return self._blocked(f"{relation.replace('.', '_')}_missing", relation)
            return self._resolved(values, relation)
        if relation.startswith("team."):
            return self._team_relation(state, relation, subjects, options)
        if relation.startswith("summon."):
            return self._summon_relation(state, relation, subjects, options)
        if relation == "formation.adjacent":
            return self._adjacent(state, subjects, options)
        if relation == "lifecycle.filter":
            return self._lifecycle_filter(state, subjects, options)
        if relation in {"entity.servant", "entity.battle_event"}:
            return self._entity_kind(state, relation, options)
        if relation == "entity.creator":
            return self._summon_relation(
                state, "summon.summoner", subjects, {"allow_defeated": True}
            )
        if relation == "entity.unselectable":
            candidates = subjects or tuple(sorted(state.units))
            selected: list[str] = []
            for unit_id in candidates:
                view = self.lifecycle.view(state, unit_id)
                if view.is_active and view.is_present and (
                    runtime_unit_is_unselectable(state.units[unit_id])
                    or not view.can_be_targeted_alive
                ):
                    selected.append(unit_id)
            return self._resolved(tuple(selected), relation)
        if relation == "entity.partner":
            return self._blocked("target_partner_producer_dependency", relation)
        if relation == "entity.unique_name":
            return self._blocked("target_unique_entity_producer_dependency", relation)
        if relation.startswith("body_part."):
            return self._blocked("body_part_producer_dependency_s17", relation)
        return self._blocked(f"entity_relation_not_supported:{relation}", relation)

    def _validate_context(self, state: BattleState, context: TargetEvaluationContext) -> str:
        identities = (
            context.caster_id,
            context.effect_owner_id,
            *context.parameter_entity_ids,
            *context.selected_target_ids,
            context.current_target_id,
            context.event_source_id,
            context.event_subject_id,
            context.event_target_id,
            context.damage_attacker_id,
            context.damage_defender_id,
            context.turn_owner_id,
        )
        unknown = next((unit_id for unit_id in identities if unit_id and unit_id not in state.units), "")
        if unknown:
            return f"target_context_unknown_identity:{unknown}"
        return ""

    def _team_relation(
        self,
        state: BattleState,
        relation: str,
        subjects: tuple[str, ...],
        options: dict[str, JSONValue],
    ) -> "TargetExpressionResult":
        if not subjects:
            return self._blocked("team_relation_subject_missing", relation)
        anchor = state.units[subjects[0]]
        if any(not is_same_combat_team(anchor, state.units[item]) for item in subjects[1:]):
            return self._blocked("team_relation_subjects_cross_team", relation)
        allow_unselectable = options.get("allow_unselectable") is True
        include_limbo = options.get("include_limbo") is True
        anchor_lifecycle = self.lifecycle.view(state, subjects[0])
        if anchor_lifecycle.is_removed or (not include_limbo and not anchor_lifecycle.is_present):
            return self._blocked("team_relation_subject_not_admitted", relation)
        include_self = options.get("include_self") is not False
        candidates: list[str] = []
        for unit_id, unit in sorted(state.units.items()):
            if relation == "team.same" and not is_same_combat_team(anchor, unit):
                continue
            if relation == "team.opposing" and not is_opposing_combat_team(anchor, unit):
                continue
            if relation == "team.light" and not is_light_team(unit):
                continue
            if relation == "team.dark" and not is_dark_team(unit):
                continue
            if relation == "team.teammate" and (
                not is_same_combat_team(anchor, unit) or unit_id in subjects
            ):
                continue
            if not include_self and unit_id in subjects:
                continue
            view = self.lifecycle.view(state, unit_id)
            if not view.is_active or (not include_limbo and not view.is_present):
                continue
            source_targetable = bool(
                isinstance(view.metadata, dict)
                and view.metadata.get("targetable") is not False
            )
            if not allow_unselectable and (runtime_unit_is_unselectable(unit) or not (
                view.can_be_targeted_alive or (include_limbo and source_targetable)
            )):
                continue
            candidates.append(unit_id)
        return self._resolved(tuple(candidates), relation)

    def _validated_runtime(self, state: BattleState) -> tuple[dict[str, JSONValue] | None, str]:
        runtime = state.global_flags.get("summon_runtime")
        validation = validate_summon_runtime(runtime, units=state.units)
        if not validation.ok:
            return None, validation.reason or "summon_runtime_invalid"
        assert isinstance(runtime, dict)
        return runtime, ""

    def _summon_relation(
        self,
        state: BattleState,
        relation: str,
        subjects: tuple[str, ...],
        options: dict[str, JSONValue],
    ) -> "TargetExpressionResult":
        if not subjects:
            return self._blocked("summon_relation_subject_missing", relation)
        runtime, reason = self._validated_runtime(state)
        if reason:
            return self._blocked(reason, relation)
        assert runtime is not None
        entities = runtime["entities"]
        by_owner = runtime["by_owner"]
        assert isinstance(entities, dict) and isinstance(by_owner, dict)
        selected: list[str] = []
        if relation == "summon.owned":
            for owner_id in subjects:
                raw_ids = by_owner.get(owner_id, [])
                if not isinstance(raw_ids, list):
                    return self._blocked("summon_runtime_by_owner_malformed", relation)
                selected.extend(str(unit_id) for unit_id in raw_ids)
        else:
            recursive = options.get("recursive") is True
            for unit_id in subjects:
                visited: set[str] = set()
                current = unit_id
                while True:
                    if current in visited:
                        return self._blocked("summon_relation_cycle", relation)
                    visited.add(current)
                    entry = entities.get(current)
                    if not isinstance(entry, dict) or entry.get("status") != "active":
                        if current == unit_id:
                            break
                        return self._blocked("summon_relation_chain_missing", relation)
                    field = "owner_id" if relation == "summon.owner" else "summoner_id"
                    related_id = entry.get(field)
                    if not isinstance(related_id, str) or related_id not in state.units:
                        return self._blocked(f"summon_relation_{field}_missing", relation)
                    selected.append(related_id)
                    if not recursive or related_id not in entities:
                        break
                    current = related_id
        if len(selected) != len(set(selected)):
            selected = list(dict.fromkeys(selected))
        allow_defeated = options.get("allow_defeated") is True
        for unit_id in selected:
            ok, lifecycle_reason = self.lifecycle.can_target(
                state, unit_id, allow_defeated=allow_defeated
            )
            if not ok:
                return self._blocked(f"summon_relation_lifecycle_blocked:{lifecycle_reason}", relation)
        return self._resolved(tuple(selected), relation)

    def _adjacent(
        self,
        state: BattleState,
        subjects: tuple[str, ...],
        options: dict[str, JSONValue],
    ) -> "TargetExpressionResult":
        if len(subjects) != 1:
            return self._blocked("formation_adjacent_requires_one_subject", "formation.adjacent")
        anchor = state.units[subjects[0]]
        anchor_lifecycle = self.lifecycle.view(state, subjects[0])
        if not anchor_lifecycle.is_active or not anchor_lifecycle.is_present:
            return self._blocked("formation_anchor_not_present", "formation.adjacent")
        position = anchor.flags.get("position")
        if not isinstance(position, int) or isinstance(position, bool):
            return self._blocked("formation_position_missing", "formation.adjacent")
        side = options.get("side", "Both")
        if side not in {"Both", "Left", "Right"}:
            return self._blocked("formation_adjacent_side_invalid", "formation.adjacent")
        ignore_servant = options.get("counting_option", "") == "IgnoreServant"
        if options.get("counting_option", "") not in {"", "IgnoreServant"}:
            return self._blocked("formation_counting_option_not_supported", "formation.adjacent")
        formation: list[tuple[int, str]] = []
        summon_ids: frozenset[str] = frozenset()
        if ignore_servant:
            runtime, reason = self._validated_runtime(state)
            if reason:
                return self._blocked(reason, "formation.adjacent")
            assert runtime is not None and isinstance(runtime["entities"], dict)
            assert isinstance(runtime["servants"], dict)
            summon_ids = frozenset(runtime["servants"])
        seen_positions: set[int] = set()
        for unit_id, unit in state.units.items():
            if not is_same_combat_team(anchor, unit):
                continue
            lifecycle = self.lifecycle.view(state, unit_id)
            if (
                not lifecycle.is_active
                or not lifecycle.is_present
                or not lifecycle.can_be_targeted_alive
                or runtime_unit_is_unselectable(unit)
            ):
                continue
            if ignore_servant and unit_id in summon_ids:
                continue
            unit_position = unit.flags.get("position")
            if not isinstance(unit_position, int) or isinstance(unit_position, bool):
                return self._blocked("formation_position_missing", "formation.adjacent")
            if unit_position in seen_positions:
                return self._blocked("formation_position_duplicate", "formation.adjacent")
            seen_positions.add(unit_position)
            formation.append((unit_position, unit_id))
        formation.sort()
        anchor_index = next((index for index, (_, unit_id) in enumerate(formation) if unit_id == subjects[0]), -1)
        if anchor_index < 0:
            return self._blocked("formation_anchor_missing", "formation.adjacent")
        selected: list[str] = []
        if side in {"Both", "Left"} and anchor_index > 0:
            selected.append(formation[anchor_index - 1][1])
        if side in {"Both", "Right"} and anchor_index + 1 < len(formation):
            selected.append(formation[anchor_index + 1][1])
        return self._resolved(tuple(selected), "formation.adjacent")

    def _lifecycle_filter(
        self,
        state: BattleState,
        subjects: tuple[str, ...],
        options: dict[str, JSONValue],
    ) -> "TargetExpressionResult":
        mask = options.get("mask", "Mask_AliveOnly")
        require_targetable = options.get("require_targetable") is True
        if mask not in {"Mask_AliveOnly", "Mask_AliveOrLimbo", "Mask_DiedButNotDispose", "Bit_Died", "Anyone"}:
            return self._blocked(f"lifecycle_mask_not_supported:{mask}", "lifecycle.filter")
        selected: list[str] = []
        for unit_id in subjects:
            view = self.lifecycle.view(state, unit_id)
            matched = (
                (mask == "Mask_AliveOnly" and view.is_active and view.is_present)
                or (mask == "Mask_AliveOrLimbo" and view.is_active and not view.is_removed)
                or (mask in {"Mask_DiedButNotDispose", "Bit_Died"} and view.is_defeated and not view.is_removed)
                or (mask == "Anyone" and not view.is_removed)
            )
            if matched:
                if require_targetable and not view.can_be_targeted_alive:
                    continue
                selected.append(unit_id)
        return self._resolved(tuple(selected), "lifecycle.filter")

    def _entity_kind(
        self,
        state: BattleState,
        relation: str,
        options: dict[str, JSONValue],
    ) -> "TargetExpressionResult":
        if relation == "entity.servant":
            runtime, reason = self._validated_runtime(state)
            if reason:
                return self._blocked(reason, relation)
            assert runtime is not None and isinstance(runtime["servants"], dict)
            candidates = tuple(sorted(runtime["servants"]))
        else:
            candidates = tuple(
                unit_id for unit_id, unit in sorted(state.units.items())
                if runtime_unit_is_battle_event_entity(unit)
            )
        return self._lifecycle_filter(
            state,
            candidates,
            {"mask": options.get("mask", "Mask_AliveOnly")},
        )

    @staticmethod
    def _resolved(target_ids: tuple[str, ...], relation: str) -> "TargetExpressionResult":
        from .target import TargetExpressionResult
        return TargetExpressionResult(
            status="resolved",
            target_ids=target_ids,
            expression_kind="EntityRelation",
            metadata={"relation": relation},
        )

    @staticmethod
    def _blocked(reason: str, relation: str) -> "TargetExpressionResult":
        from .target import TargetExpressionResult
        return TargetExpressionResult(
            status="blocked",
            blocked_reason=reason,
            expression_kind="EntityRelation",
            metadata={"relation": relation},
        )


__all__ = [
    "CombatTeam",
    "EntityRelationResolver",
    "TargetEvaluationContext",
    "combat_team_of",
    "is_dark_team",
    "is_light_team",
    "is_opposing_combat_team",
    "is_same_combat_team",
]
