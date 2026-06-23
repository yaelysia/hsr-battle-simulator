from __future__ import annotations

from dataclasses import dataclass

from ..core.model import BattleState, GameEvent, JSONValue, Mutation
from ..core.settlement import SettlementRecord
from ..rules.ir import SkillContinuationIR
from ..rules.rulebook import RuleBook


@dataclass(frozen=True)
class SkillContinuationResult:
    ok: bool
    after_state: BattleState
    mutations: tuple[Mutation, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    events: tuple[GameEvent, ...] = ()
    blocked_reason: str = ""


class SkillContinuationRunner:
    """Admission boundary for skill or ultimate internal continuation segments."""

    def __init__(self, rules: RuleBook):
        self.rules = rules

    def execute(
        self,
        state: BattleState,
        continuation: SkillContinuationIR,
        *,
        actor_id: str,
        target_ids: tuple[str, ...] = (),
    ) -> SkillContinuationResult:
        if continuation.coverage_status != "executable":
            reason = continuation.blocked_reason or f"skill_continuation_not_executable:{continuation.coverage_status}"
            return self._blocked(state, continuation, actor_id=actor_id, target_ids=target_ids, reason=reason)
        return self._blocked(
            state,
            continuation,
            actor_id=actor_id,
            target_ids=target_ids,
            reason="skill_continuation_execution_not_admitted:missing source-specific segment-to-action mapping",
        )

    def _blocked(
        self,
        state: BattleState,
        continuation: SkillContinuationIR,
        *,
        actor_id: str,
        target_ids: tuple[str, ...],
        reason: str,
    ) -> SkillContinuationResult:
        payload: dict[str, JSONValue] = {
            "reason": reason,
            "continuation_id": continuation.continuation_id,
            "opcode": continuation.opcode,
            "ability_name": continuation.ability_name,
            "actor_id": actor_id,
            "target_ids": list(target_ids),
            "not_extra_turn": True,
        }
        return SkillContinuationResult(
            ok=False,
            after_state=state,
            records=(
                SettlementRecord(
                    record_type="skill_continuation_blocked",
                    source="skill_continuation_runner",
                    process_only=True,
                    payload=payload,
                    trace={"skill_continuation_source": continuation.source.to_json()},
                ).to_json(),
            ),
            events=(
                GameEvent(
                    "skill_continuation.blocked",
                    source_id=actor_id,
                    target_id=target_ids[0] if target_ids else "",
                    window="skill_continuation",
                    process_only=True,
                    payload=payload,
                ),
            ),
            blocked_reason=reason,
        )
