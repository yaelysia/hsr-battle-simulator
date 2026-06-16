from __future__ import annotations

from ..core.executor import CombatExecutor
from ..core.model import ActionCommand, BattleState, Mutation, UnitState
from ..core.reducer import MutationReducer
from ..rules.ir import ActionDefinitionIR, CanonicalIR, IRSource
from ..rules.rulebook import RuleBook
from ..systems.resource import ResourceSystem


def run_snapshot_replay_check() -> dict[str, object]:
    state = BattleState(
        units={
            "ally:seele": UnitState(
                unit_id="ally:seele",
                side="ally",
                template_id="avatar:1102",
                max_hp=3000.0,
                hp=3000.0,
                energy=60.0,
                max_energy=120.0,
            ),
            "enemy:dummy": UnitState(
                unit_id="enemy:dummy",
                side="enemy",
                template_id="monster:dummy",
                max_hp=10000.0,
                hp=10000.0,
                toughness=90.0,
                max_toughness=90.0,
            ),
        },
        skill_points=3,
        max_skill_points=5,
    )
    resource = ResourceSystem()
    mutations: tuple[Mutation, ...] = (
        resource.set_skill_points(state, 2, source="snapshot_replay_check"),
        resource.change_unit_energy(state, "ally:seele", 30.0, source="snapshot_replay_check"),
    )
    reducer = MutationReducer()
    after = reducer.apply_all(state, mutations)
    replay = reducer.replay_snapshot(state, mutations, after.snapshot().to_json())

    executor = CombatExecutor(RuleBook(_minimal_ir()))
    _, transition = executor.execute(
        ActionCommand(
            actor_id="ally:seele",
            action_id="avatar_skill:110201",
            action_level=1,
            target_ids=("enemy:dummy",),
        ),
        state,
    )
    transaction_replay = reducer.replay_snapshot(
        state,
        transition.transaction.mutations,
        transition.after.to_json(),
    )

    return {
        "mutation_replay": {
            "ok": replay.ok,
            "errors": list(replay.errors),
            "mutation_count": len(mutations),
        },
        "transaction_replay": {
            "ok": transaction_replay.ok,
            "errors": list(transaction_replay.errors),
            "mutation_count": len(transition.transaction.mutations),
            "has_before": bool(transition.transaction.before.to_json()),
            "has_after": bool(transition.after.to_json()),
            "has_settlement": transition.transaction.settlement is not None,
        },
        "ok": replay.ok and transaction_replay.ok,
    }


def _minimal_ir() -> CanonicalIR:
    source = IRSource(
        source_path="validation/snapshot_replay",
        raw_type="ValidationActionDefinition",
        raw_id="avatar_skill:110201",
        evidence={"level": 1},
    )
    return CanonicalIR(
        version="v0_200",
        action_definitions=(
            ActionDefinitionIR(
                definition_id="action_def:avatar_skill:110201:1",
                action_id="avatar_skill:110201",
                level=1,
                attack_type="Normal",
                skill_effect="SingleAttack",
                target_mode="single",
                bp_need=0.0,
                bp_add=0.0,
                sp_base=0.0,
                sp_multiple_ratio=0.0,
                param_list=(),
                show_stance_list=(),
                show_damage_list=(),
                stance_damage_type=None,
                source=source,
                coverage_status="executable",
            ),
        ),
    )
