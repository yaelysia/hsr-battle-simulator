from __future__ import annotations

from dataclasses import dataclass, field

from ..core.model import ActionCommand, BattleState, BattleTransition, JSONValue, Mutation
from ..rules.ir import ActionDefinitionIR, MonsterDataCardIR
from ..rules.rulebook import RuleBook
from .target import TargetEnumerationResult, TargetPolicy, TargetSystem


@dataclass(frozen=True)
class EnemyActionCandidate:
    actor_id: str
    entity_ref: str = ""
    monster_data_card_id: str = ""
    sequence_index: int = 0
    action_ref: str = ""
    action_level: int = 0
    target_mode: str = ""
    selectable_target_ids: tuple[str, ...] = ()
    auto_target_ids: tuple[str, ...] = ()
    status: str = "blocked"
    blocked_reason: str = ""
    source_trace: dict[str, JSONValue] = field(default_factory=dict)
    target_policy: dict[str, JSONValue] = field(default_factory=dict)
    sequence_step: dict[str, JSONValue] = field(default_factory=dict)
    action_definition: dict[str, JSONValue] = field(default_factory=dict)
    target_enumeration: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "actor_id": self.actor_id,
            "entity_ref": self.entity_ref,
            "monster_data_card_id": self.monster_data_card_id,
            "sequence_index": self.sequence_index,
            "action_ref": self.action_ref,
            "action_level": self.action_level,
            "target_mode": self.target_mode,
            "selectable_target_ids": list(self.selectable_target_ids),
            "auto_target_ids": list(self.auto_target_ids),
            "status": self.status,
            "blocked_reason": self.blocked_reason,
            "source_trace": self.source_trace,
            "target_policy": self.target_policy,
            "sequence_step": self.sequence_step,
            "action_definition": self.action_definition,
            "target_enumeration": self.target_enumeration,
        }


class EnemyActionSystem:
    """Read-only enemy fixed sequence candidate generation.

    This system never chooses a target or executes an action. It only turns the
    already-lowered MonsterDataCardIR action sequence into an auditable candidate
    for UI, route input, or a future search policy.
    """

    def __init__(self, rules: RuleBook):
        self.rules = rules
        self.targets = TargetSystem()

    def next_candidate(self, state: BattleState, actor_id: str) -> EnemyActionCandidate:
        actor = state.units.get(actor_id)
        if actor is None:
            return self._blocked(actor_id, "enemy_actor_missing")
        if actor.side != "enemy":
            return self._blocked(actor_id, "enemy_action_actor_not_enemy", entity_ref=actor.template_id)
        card_id = str(actor.flags.get("monster_data_card_id") or "")
        if not card_id:
            return self._blocked(actor_id, "enemy_monster_data_card_id_missing", entity_ref=actor.template_id)
        card = self.rules.monster_data_card(card_id)
        if card is None:
            return self._blocked(
                actor_id,
                "enemy_monster_data_card_missing",
                entity_ref=actor.template_id,
                monster_data_card_id=card_id,
            )
        if str(card.ai_policy.get("admission_status") or "") != "executable":
            return self._blocked_from_card(actor_id, actor.template_id, card, "enemy_ai_policy_not_fixed_sequence")
        if not card.action_sequence:
            return self._blocked_from_card(actor_id, actor.template_id, card, "enemy_action_sequence_missing")
        cursor = _sequence_cursor(actor.flags.get("enemy_action_sequence_cursor"))
        sequence_index = cursor % len(card.action_sequence)
        step = card.action_sequence[sequence_index]
        if str(step.get("coverage_status") or "") == "blocked":
            reason = str(step.get("blocked_reason") or "enemy_action_sequence_step_blocked")
            return self._blocked_from_card(actor_id, actor.template_id, card, reason, sequence_index=sequence_index, step=step)
        action_ref = str(step.get("action_ref") or "")
        if not action_ref:
            return self._blocked_from_card(actor_id, actor.template_id, card, "enemy_action_sequence_action_missing", sequence_index=sequence_index, step=step)
        action_level = _action_level_for_step(self.rules, step, action_ref)
        if action_level <= 0:
            return self._blocked_from_card(actor_id, actor.template_id, card, "enemy_action_level_missing", sequence_index=sequence_index, step=step)
        definition = self.rules.action_definition(action_ref, action_level)
        if definition is None:
            return self._blocked_from_card(actor_id, actor.template_id, card, "enemy_action_definition_missing", sequence_index=sequence_index, step=step)
        event = self.rules.action_event(action_ref, action_level)
        if event is None:
            return self._blocked_from_card(actor_id, actor.template_id, card, "enemy_action_event_missing", sequence_index=sequence_index, step=step)
        target_policy = _target_policy_for_definition(self.rules, definition, event.target_mode)
        target_result = self.targets.enumerate_action_targets(state, actor_id, target_policy)
        if not target_result.ok:
            return self._blocked_from_card(
                actor_id,
                actor.template_id,
                card,
                target_result.blocked_reason or "enemy_action_targets_blocked",
                sequence_index=sequence_index,
                step=step,
                definition=definition,
                target_result=target_result,
            )
        source_trace = _candidate_source_trace(card, step, definition)
        return EnemyActionCandidate(
            actor_id=actor_id,
            entity_ref=actor.template_id,
            monster_data_card_id=card.card_id,
            sequence_index=sequence_index,
            action_ref=action_ref,
            action_level=action_level,
            target_mode=event.target_mode,
            selectable_target_ids=target_result.selectable_target_ids,
            auto_target_ids=target_result.auto_target_ids,
            status="available",
            blocked_reason="",
            source_trace=source_trace,
            target_policy=target_result.policy,
            sequence_step=dict(step),
            action_definition=definition.to_json(),
            target_enumeration=target_result.to_json(),
        )

    def command_from_candidate(
        self,
        candidate: EnemyActionCandidate,
        target_ids: tuple[str, ...] = (),
    ) -> ActionCommand:
        if candidate.status != "available":
            raise ValueError(f"blocked enemy action candidate: {candidate.blocked_reason}")
        selected_targets = target_ids or candidate.auto_target_ids
        return ActionCommand(
            actor_id=candidate.actor_id,
            action_id=candidate.action_ref,
            action_level=candidate.action_level,
            target_ids=tuple(selected_targets),
            source="ai",
            metadata={
                "enemy_action_candidate": {
                    "monster_data_card_id": candidate.monster_data_card_id,
                    "sequence_index": candidate.sequence_index,
                    "source_trace": candidate.source_trace,
                }
            },
        )

    def advance_cursor_mutation(
        self,
        state: BattleState,
        candidate: EnemyActionCandidate,
        command: ActionCommand,
        transition: BattleTransition,
    ) -> Mutation | None:
        if candidate.status != "available":
            return None
        if command.actor_id != candidate.actor_id:
            return None
        if command.action_id != candidate.action_ref or int(command.action_level) != int(candidate.action_level):
            return None
        if transition.coverage.get("action_enabled") is not True:
            return None
        actor = state.units.get(candidate.actor_id)
        if actor is None:
            return None
        before = _sequence_cursor(actor.flags.get("enemy_action_sequence_cursor"))
        after = before + 1
        return Mutation(
            op="set",
            path=("units", candidate.actor_id, "flags", "enemy_action_sequence_cursor"),
            before=before,
            after=after,
            reason="enemy_fixed_action_sequence_cursor_advanced",
            source="enemy_action_system",
            metadata={
                "operation": "advance_enemy_action_sequence_cursor",
                "actor_id": candidate.actor_id,
                "action_id": candidate.action_ref,
                "action_level": candidate.action_level,
                "monster_data_card_id": candidate.monster_data_card_id,
                "sequence_index": candidate.sequence_index,
                "source_trace": candidate.source_trace,
                "command": {
                    "actor_id": command.actor_id,
                    "action_id": command.action_id,
                    "action_level": command.action_level,
                    "target_ids": list(command.target_ids),
                    "source": command.source,
                },
            },
        )

    def _blocked(
        self,
        actor_id: str,
        reason: str,
        *,
        entity_ref: str = "",
        monster_data_card_id: str = "",
    ) -> EnemyActionCandidate:
        return EnemyActionCandidate(
            actor_id=actor_id,
            entity_ref=entity_ref,
            monster_data_card_id=monster_data_card_id,
            status="blocked",
            blocked_reason=reason,
        )

    def _blocked_from_card(
        self,
        actor_id: str,
        entity_ref: str,
        card: MonsterDataCardIR,
        reason: str,
        *,
        sequence_index: int = 0,
        step: dict[str, JSONValue] | None = None,
        definition: ActionDefinitionIR | None = None,
        target_result: TargetEnumerationResult | None = None,
    ) -> EnemyActionCandidate:
        return EnemyActionCandidate(
            actor_id=actor_id,
            entity_ref=entity_ref,
            monster_data_card_id=card.card_id,
            sequence_index=sequence_index,
            action_ref=str((step or {}).get("action_ref") or ""),
            action_level=_action_level_for_step(self.rules, step or {}, str((step or {}).get("action_ref") or "")),
            target_mode=definition.target_mode if definition is not None else "",
            status="blocked",
            blocked_reason=reason,
            source_trace=_candidate_source_trace(card, step or {}, definition),
            sequence_step=dict(step or {}),
            action_definition=definition.to_json() if definition is not None else {},
            target_enumeration=target_result.to_json() if target_result is not None else {},
            target_policy=target_result.policy if target_result is not None else {},
        )


def _sequence_cursor(raw: JSONValue) -> int:
    if isinstance(raw, bool):
        return 0
    if isinstance(raw, int):
        return max(0, raw)
    if isinstance(raw, float):
        return max(0, int(raw))
    if isinstance(raw, str):
        try:
            return max(0, int(raw))
        except ValueError:
            return 0
    return 0


def _action_level_for_step(rules: RuleBook, step: dict[str, JSONValue], action_ref: str) -> int:
    raw_level = step.get("action_level")
    if isinstance(raw_level, bool):
        return 0
    if isinstance(raw_level, int):
        return raw_level
    if isinstance(raw_level, float):
        return int(raw_level)
    if isinstance(raw_level, str):
        try:
            return int(raw_level)
        except ValueError:
            return 0
    levels = rules.action_levels(action_ref) if action_ref else ()
    return min(levels) if levels else 0


def _target_policy_for_definition(
    rules: RuleBook,
    action_definition: ActionDefinitionIR,
    target_mode: str,
) -> TargetPolicy:
    if target_mode == "self_or_team":
        return TargetPolicy(
            policy_id="self_or_team",
            allow_enemy=False,
            allow_ally=True,
            allow_self=True,
            target_mode=target_mode,
            selection_mode="explicit_ally_or_self",
        )
    if action_definition.damage_kind == "hp_damage":
        return TargetPolicy(
            policy_id="enemy_damage",
            allow_enemy=True,
            allow_ally=False,
            allow_self=False,
            target_mode=target_mode,
            selection_mode=target_mode,
            bounce_policy=_bounce_policy_for_action(rules, action_definition.action_id, action_definition.level),
        )
    return TargetPolicy(
        policy_id="explicit_any",
        allow_enemy=True,
        allow_ally=True,
        allow_self=True,
        target_mode=target_mode,
        selection_mode=target_mode,
        bounce_policy=_bounce_policy_for_action(rules, action_definition.action_id, action_definition.level),
    )


def _bounce_policy_for_action(rules: RuleBook, action_id: str, level: int) -> dict[str, JSONValue]:
    for profile in rules.hit_profiles_for_action(action_id, level):
        policy_id = profile.bounce_policy_id
        if not policy_id:
            continue
        policy = rules.bounce_policy(policy_id)
        if policy is not None:
            return policy.to_json()
    return {}


def _candidate_source_trace(
    card: MonsterDataCardIR,
    step: dict[str, JSONValue],
    definition: ActionDefinitionIR | None,
) -> dict[str, JSONValue]:
    return {
        "monster_data_card": card.source.to_json(),
        "monster_data_card_id": card.card_id,
        "monster_id": card.monster_id,
        "template_id": card.template_id,
        "ai_policy": card.ai_policy,
        "action_sequence_step": step,
        "action_definition": definition.source.to_json() if definition is not None else {},
    }
