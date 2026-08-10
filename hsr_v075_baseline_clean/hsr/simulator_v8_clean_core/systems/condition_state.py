from __future__ import annotations

import math
from collections.abc import Mapping

from ..core.model import BattleState
from ..rules.condition_state import (
    COMMITTED_CONDITION_FACT_KINDS,
    ConditionOperandRequest,
    ConditionOperandResolution,
)
from ..rules.rulebook import RuleBook
from ..unit_eligibility import runtime_units_are_opposing_combat_teams
from .unit_relation import EntityRelationResolver, TargetEvaluationContext
from .unit_stats import (
    control_kind_from_behavior_flags,
    effective_status_resistance,
)


_EXTERNAL_FACT_PRODUCERS = {
    "relation.body_part": "p9_s17",
    "relation.hp_shared_group": "p9_s11",
    "unit.red_stance": "p9_s15",
    "unit.battle_event_id": "p9_s17",
    "unit.is_battle_event_entity": "p9_s17",
    "unit.stance_current": "p9_s15",
    "unit.stance_ratio": "p9_s15",
    "unit.stance_segment_count": "p9_s15",
    "unit.stance_weak": "p9_s15",
}

_FACT_AUTHORITIES = {
    "battle.skill_points": "battle_state",
    "relation.body_part": "entity_relation",
    "relation.hp_shared_group": "entity_relation",
    "relation.opposing": "entity_relation",
    "relation.summoner": "entity_relation",
    "unit.avatar_base_type": "rulebook_character_definition",
    "unit.battle_event_id": "unit_definition",
    "unit.hp": "battle_state",
    "unit.is_battle_event_entity": "unit_definition",
    "unit.lifecycle_mask": "unit_lifecycle",
    "unit.monster_rank": "rulebook_monster_definition",
    "unit.red_stance": "toughness_state",
    "unit.special_resource_ratio": "character_resource_binding",
    "unit.stance_current": "toughness_state",
    "unit.stance_ratio": "toughness_state",
    "unit.stance_segment_count": "toughness_state",
    "unit.stance_weak": "toughness_state",
    "unit.status_resist_chance": "status_resistance",
    "unit.target_unselectable": "entity_relation",
}

_FACT_PARAMETER_KEYS = {
    "battle.skill_points": frozenset(),
    "relation.body_part": frozenset(),
    "relation.hp_shared_group": frozenset(),
    "relation.opposing": frozenset(),
    "relation.summoner": frozenset(),
    "unit.avatar_base_type": frozenset(),
    "unit.battle_event_id": frozenset(),
    "unit.hp": frozenset(),
    "unit.is_battle_event_entity": frozenset({"expect_sub_type"}),
    "unit.lifecycle_mask": frozenset({"mask"}),
    "unit.monster_rank": frozenset(),
    "unit.red_stance": frozenset(),
    "unit.special_resource_ratio": frozenset(),
    "unit.stance_current": frozenset(),
    "unit.stance_ratio": frozenset({"include_red_stance"}),
    "unit.stance_segment_count": frozenset(),
    "unit.stance_weak": frozenset(),
    "unit.status_resist_chance": frozenset({"behavior_flags"}),
    "unit.target_unselectable": frozenset({"source_id"}),
}

_FACT_SUBJECT_COUNTS = {
    "battle.skill_points": 0,
    "relation.body_part": 1,
    "relation.hp_shared_group": 1,
    "relation.opposing": 2,
    "relation.summoner": 1,
    "unit.avatar_base_type": 1,
    "unit.battle_event_id": 1,
    "unit.hp": 1,
    "unit.is_battle_event_entity": 1,
    "unit.lifecycle_mask": 1,
    "unit.monster_rank": 1,
    "unit.red_stance": 1,
    "unit.special_resource_ratio": 1,
    "unit.stance_current": 1,
    "unit.stance_ratio": 1,
    "unit.stance_segment_count": 1,
    "unit.stance_weak": 2,
    "unit.status_resist_chance": 1,
    "unit.target_unselectable": 1,
}

if not (
    set(_FACT_AUTHORITIES)
    == set(_FACT_PARAMETER_KEYS)
    == set(_FACT_SUBJECT_COUNTS)
    == set(COMMITTED_CONDITION_FACT_KINDS)
    and set(_EXTERNAL_FACT_PRODUCERS) <= set(COMMITTED_CONDITION_FACT_KINDS)
):
    raise RuntimeError("committed condition fact provider registry is incomplete")


class CommittedConditionFactProvider:
    """Single reader for condition facts already committed to battle state."""

    def __init__(self, rules: RuleBook | None) -> None:
        if rules is not None and type(rules) is not RuleBook:
            raise TypeError("condition fact provider rules must be an exact RuleBook")
        self.rules = rules
        self.relations = EntityRelationResolver()

    def resolve(
        self,
        state: BattleState,
        request: ConditionOperandRequest,
    ) -> ConditionOperandResolution:
        if type(state) is not BattleState:
            return self._blocked(request, "condition_committed_state_missing")
        if type(request) is not ConditionOperandRequest:
            raise TypeError("condition fact request must use the exact internal type")
        parameters = request.parameters or {}
        if set(parameters) != _FACT_PARAMETER_KEYS[request.fact_kind]:
            return self._blocked(
                request, f"condition_fact_parameters_invalid:{request.fact_kind}"
            )
        if len(request.subject_ids) != _FACT_SUBJECT_COUNTS[request.fact_kind]:
            return self._blocked(
                request,
                f"condition_fact_subject_count_invalid:{request.fact_kind}",
            )
        parameter_reason = self._parameter_reason(request)
        if parameter_reason:
            return self._blocked(request, parameter_reason)
        missing = next(
            (unit_id for unit_id in request.subject_ids if unit_id not in state.units),
            "",
        )
        if missing:
            return self._blocked(request, f"condition_fact_subject_missing:{missing}")
        external_stage = _EXTERNAL_FACT_PRODUCERS.get(request.fact_kind)
        if external_stage is not None:
            return self._blocked(
                request,
                f"condition_fact_producer_dependency:{external_stage}:{request.fact_kind}",
            )
        if request.fact_kind == "battle.skill_points":
            if request.subject_ids:
                return self._blocked(request, "battle_skill_points_rejects_subjects")
            return self._number(
                request,
                state.skill_points,
                f"battle_state.skill_points:event:{state.event_index}",
            )
        if request.fact_kind == "unit.hp":
            unit_id = self._single_subject(request)
            if unit_id is None:
                return self._blocked(request, "unit_hp_requires_one_subject")
            return self._number(request, state.units[unit_id].hp, f"unit:{unit_id}:hp")
        if request.fact_kind == "unit.lifecycle_mask":
            return self._lifecycle(state, request)
        if request.fact_kind == "unit.avatar_base_type":
            return self._avatar_base_type(state, request)
        if request.fact_kind == "unit.monster_rank":
            return self._monster_rank(state, request)
        if request.fact_kind == "unit.special_resource_ratio":
            return self._special_resource_ratio(state, request)
        if request.fact_kind == "unit.status_resist_chance":
            return self._status_resist_chance(state, request)
        if request.fact_kind == "relation.summoner":
            return self._relation(state, request, "summon.summoner")
        if request.fact_kind == "relation.opposing":
            return self._opposing(state, request)
        if request.fact_kind == "unit.target_unselectable":
            return self._target_unselectable(state, request)
        return self._blocked(
            request, f"condition_fact_provider_missing:{request.fact_kind}"
        )

    def _avatar_base_type(
        self, state: BattleState, request: ConditionOperandRequest
    ) -> ConditionOperandResolution:
        unit_id = self._single_subject(request)
        if unit_id is None:
            return self._blocked(request, "avatar_base_type_requires_one_subject")
        if self.rules is None:
            return self._blocked(request, "condition_rulebook_missing")
        card_id = state.units[unit_id].flags.get("character_data_card_id")
        if not isinstance(card_id, str) or not card_id:
            return self._blocked(request, "character_data_card_identity_missing")
        card = self.rules.character_data_card(card_id)
        if (
            card is None
            or card.coverage_status != "executable"
            or state.units[unit_id].template_id != card.entity_ref
        ):
            return self._blocked(request, "character_data_card_not_executable")
        profile = self.rules.avatar_profile_by_profile_id(card.profile_id)
        if (
            profile is None
            or profile.coverage_status != "executable"
            or profile.avatar_profile_id != card.profile_id
            or not profile.base_type
        ):
            return self._blocked(request, "character_base_type_definition_missing")
        return ConditionOperandResolution.resolved(
            "string",
            profile.base_type,
            fact_kind=request.fact_kind,
            authority=_FACT_AUTHORITIES[request.fact_kind],
            source_identity=profile.avatar_profile_id,
        )

    def _monster_rank(
        self, state: BattleState, request: ConditionOperandRequest
    ) -> ConditionOperandResolution:
        unit_id = self._single_subject(request)
        if unit_id is None:
            return self._blocked(request, "monster_rank_requires_one_subject")
        if self.rules is None:
            return self._blocked(request, "condition_rulebook_missing")
        card_id = state.units[unit_id].flags.get("monster_data_card_id")
        if not isinstance(card_id, str) or not card_id:
            return self._blocked(request, "monster_data_card_identity_missing")
        card = self.rules.monster_data_card(card_id)
        if (
            card is None
            or card.coverage_status != "executable"
            or state.units[unit_id].template_id != card.entity_ref
        ):
            return self._blocked(request, "monster_data_card_not_executable")
        canonical_scores = self.rules.ir.metadata.get("monster_rank_scores")
        committed_scores = state.global_flags.get("monster_rank_scores")
        canonical_score = (
            canonical_scores.get(card.rank)
            if isinstance(canonical_scores, Mapping)
            else None
        )
        score = (
            committed_scores.get(card.rank)
            if isinstance(committed_scores, Mapping)
            else None
        )
        if (
            not self._finite(score)
            or not self._finite(canonical_score)
            or float(score) != float(canonical_score)
            or state.units[unit_id].flags.get("monster_rank") != card.rank
            or state.units[unit_id].flags.get("monster_rank_score") != score
        ):
            return self._blocked(request, "monster_rank_score_missing")
        return self._number(
            request,
            float(score),
            f"monster_data_card:{card.card_id}:rank:{card.rank}",
        )

    def _special_resource_ratio(
        self, state: BattleState, request: ConditionOperandRequest
    ) -> ConditionOperandResolution:
        unit_id = self._single_subject(request)
        if unit_id is None:
            return self._blocked(
                request, "special_resource_ratio_requires_one_subject"
            )
        if self.rules is None:
            return self._blocked(request, "condition_rulebook_missing")
        unit = state.units[unit_id]
        card_id = unit.flags.get("character_data_card_id")
        card = self.rules.character_data_card(card_id) if isinstance(card_id, str) else None
        profile = (
            self.rules.avatar_profile_by_profile_id(card.profile_id)
            if card is not None
            else None
        )
        definition = profile.special_resource_definition if profile is not None else None
        if (
            profile is None
            or card is None
            or card.coverage_status != "executable"
            or unit.template_id != card.entity_ref
            or profile.coverage_status != "executable"
            or profile.resource_mode != "special_resource"
            or definition is None
            or definition.coverage_status != "executable"
        ):
            return self._blocked(request, "special_resource_definition_not_executable")
        if (
            unit.flags.get("special_resource_definition_id")
            != definition.resource_definition_id
            or unit.flags.get("special_resource_current_key")
            != definition.current_resource_key
            or unit.flags.get("special_resource_maximum_key")
            != definition.maximum_resource_key
        ):
            return self._blocked(request, "special_resource_binding_identity_mismatch")
        current = unit.resources.get(definition.current_resource_key)
        maximum = unit.resources.get(definition.maximum_resource_key)
        if not self._finite(current) or not self._finite(maximum) or float(maximum) <= 0:
            return self._blocked(request, "special_resource_state_missing")
        return self._number(
            request,
            float(current) / float(maximum),
            definition.resource_definition_id,
        )

    def _status_resist_chance(
        self, state: BattleState, request: ConditionOperandRequest
    ) -> ConditionOperandResolution:
        unit_id = self._single_subject(request)
        raw_flags = (request.parameters or {}).get("behavior_flags")
        if unit_id is None:
            return self._blocked(request, "status_resist_chance_requires_one_subject")
        if not isinstance(raw_flags, (list, tuple)):
            return self._blocked(request, "status_resist_behavior_flags_invalid")
        flags = tuple(raw_flags)
        if (
            not flags
            or any(not isinstance(flag, str) or not flag for flag in flags)
            or len(flags) != len(set(flags))
        ):
            return self._blocked(request, "status_resist_behavior_flags_invalid")
        control_kind = control_kind_from_behavior_flags(flags)
        resistance = effective_status_resistance(
            state.units[unit_id], control_kind=control_kind
        )
        return self._number(
            request,
            resistance.resistance_chance,
            f"unit:{unit_id}:status_resistance:{control_kind or 'effect'}",
        )

    @staticmethod
    def _parameter_reason(request: ConditionOperandRequest) -> str:
        parameters = request.parameters or {}
        if request.fact_kind == "unit.lifecycle_mask" and parameters.get(
            "mask"
        ) not in {"Mask_AliveOnly", "Mask_AliveOrLimbo"}:
            return "lifecycle_condition_mask_invalid"
        if request.fact_kind == "unit.is_battle_event_entity":
            expected = parameters.get("expect_sub_type")
            if not isinstance(expected, str):
                return "battle_event_sub_type_invalid"
        if request.fact_kind == "unit.stance_ratio" and type(
            parameters.get("include_red_stance")
        ) is not bool:
            return "stance_ratio_red_stance_flag_invalid"
        if request.fact_kind == "unit.status_resist_chance":
            raw_flags = parameters.get("behavior_flags")
            if not isinstance(raw_flags, (list, tuple)):
                return "status_resist_behavior_flags_invalid"
            flags = tuple(raw_flags)
            if (
                not flags
                or any(not isinstance(flag, str) or not flag for flag in flags)
                or len(flags) != len(set(flags))
            ):
                return "status_resist_behavior_flags_invalid"
        if request.fact_kind == "unit.target_unselectable" and not isinstance(
            parameters.get("source_id"), str
        ):
            return "target_unselectable_source_invalid"
        return ""

    def _lifecycle(
        self, state: BattleState, request: ConditionOperandRequest
    ) -> ConditionOperandResolution:
        unit_id = self._single_subject(request)
        mask = (request.parameters or {}).get("mask")
        if unit_id is None:
            return self._blocked(request, "lifecycle_condition_requires_one_subject")
        if not isinstance(mask, str) or not mask:
            return self._blocked(request, "lifecycle_condition_mask_invalid")
        context = TargetEvaluationContext(caster_id=unit_id)
        result = self.relations.resolve(
            state,
            "lifecycle.filter",
            context,
            subject_ids=(unit_id,),
            options={"mask": mask},
        )
        if result.blocked:
            return self._blocked(request, result.blocked_reason)
        return ConditionOperandResolution.resolved(
            "boolean",
            unit_id in result.target_ids,
            fact_kind=request.fact_kind,
            authority=_FACT_AUTHORITIES[request.fact_kind],
            source_identity=f"unit:{unit_id}:lifecycle:{mask}",
        )

    def _relation(
        self, state: BattleState, request: ConditionOperandRequest, relation: str
    ) -> ConditionOperandResolution:
        if len(request.subject_ids) != 1:
            return self._blocked(request, f"{request.fact_kind}_requires_one_subject")
        context = TargetEvaluationContext(caster_id=request.subject_ids[0])
        result = self.relations.resolve(
            state,
            relation,
            context,
            subject_ids=request.subject_ids,
            options={"allow_defeated": True} if relation == "summon.summoner" else None,
        )
        if result.blocked:
            return self._blocked(request, result.blocked_reason)
        identities = tuple(sorted(result.target_ids))
        return ConditionOperandResolution.resolved(
            "identity_set",
            list(identities),
            fact_kind=request.fact_kind,
            authority=_FACT_AUTHORITIES[request.fact_kind],
            source_identity=f"relation:{relation}:{request.subject_ids[0]}",
        )

    def _opposing(
        self, state: BattleState, request: ConditionOperandRequest
    ) -> ConditionOperandResolution:
        left_id, right_id = request.subject_ids
        return ConditionOperandResolution.resolved(
            "boolean",
            runtime_units_are_opposing_combat_teams(
                state.units[left_id], state.units[right_id]
            ),
            fact_kind=request.fact_kind,
            authority=_FACT_AUTHORITIES[request.fact_kind],
            source_identity=f"relation:team.opposing:{left_id}:{right_id}",
        )

    def _target_unselectable(
        self, state: BattleState, request: ConditionOperandRequest
    ) -> ConditionOperandResolution:
        unit_id = self._single_subject(request)
        source_id = (request.parameters or {}).get("source_id")
        if unit_id is None:
            return self._blocked(request, "target_unselectable_requires_one_subject")
        if not isinstance(source_id, str):
            return self._blocked(request, "target_unselectable_source_invalid")
        if source_id and source_id not in state.units:
            return self._blocked(
                request, f"target_unselectable_source_missing:{source_id}"
            )
        context = TargetEvaluationContext(caster_id=source_id or unit_id)
        result = self.relations.resolve(
            state,
            "entity.unselectable",
            context,
            subject_ids=(unit_id,),
        )
        if result.blocked:
            return self._blocked(request, result.blocked_reason)
        return ConditionOperandResolution.resolved(
            "boolean",
            unit_id in result.target_ids,
            fact_kind=request.fact_kind,
            authority=_FACT_AUTHORITIES[request.fact_kind],
            source_identity=f"relation:entity.unselectable:{source_id or unit_id}:{unit_id}",
        )

    @staticmethod
    def _single_subject(request: ConditionOperandRequest) -> str | None:
        return request.subject_ids[0] if len(request.subject_ids) == 1 else None

    @staticmethod
    def _finite(value: object) -> bool:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False
        try:
            return math.isfinite(float(value))
        except (OverflowError, TypeError, ValueError):
            return False

    def _number(
        self,
        request: ConditionOperandRequest,
        value: int | float,
        source_identity: str,
    ) -> ConditionOperandResolution:
        if not self._finite(value):
            return self._blocked(request, "condition_fact_number_invalid")
        return ConditionOperandResolution.resolved(
            "number",
            float(value),
            fact_kind=request.fact_kind,
            authority=_FACT_AUTHORITIES[request.fact_kind],
            source_identity=source_identity,
        )

    @staticmethod
    def _blocked(
        request: ConditionOperandRequest, reason: str
    ) -> ConditionOperandResolution:
        return ConditionOperandResolution.blocked(
            reason,
            fact_kind=request.fact_kind,
            authority=_FACT_AUTHORITIES[request.fact_kind],
        )


__all__ = ["CommittedConditionFactProvider"]
