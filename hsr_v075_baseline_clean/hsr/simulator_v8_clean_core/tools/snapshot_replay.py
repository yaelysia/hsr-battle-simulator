from __future__ import annotations

from ..core.executor import CombatExecutor
from ..core.model import ActionCommand, BattleState, Mutation, UnitState
from ..core.reducer import MutationReducer
from ..rules.ir import (
    AbilityPhaseIR,
    ActionAbilityBindingIR,
    ActionDefinitionIR,
    ActionEventIR,
    ActionPhaseStepIR,
    CanonicalIR,
    IRSource,
)
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
            "conflicts": [conflict.to_json() for conflict in replay.conflicts],
            "mutation_count": len(mutations),
        },
        "transaction_replay": {
            "ok": transaction_replay.ok,
            "errors": list(transaction_replay.errors),
            "conflicts": [conflict.to_json() for conflict in transaction_replay.conflicts],
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
        action_ability_bindings=(
            ActionAbilityBindingIR(
                binding_id="action_binding:avatar_skill:110201:1",
                action_id="avatar_skill:110201",
                level=1,
                skill_trigger_key="Skill01",
                skill_name="Skill01",
                entry_ability="ValidationSkill01Phase01",
                ability_names=("ValidationSkill01Phase01",),
                config_source={
                    "character_config_path": "validation/snapshot_replay_character_config",
                    "ability_file_path": "validation/snapshot_replay_ability",
                },
                phase_ids=("ability_phase:avatar_skill:110201:1:0:ValidationSkill01Phase01",),
                source_mode="validation_fixture",
                source=source,
                coverage_status="executable",
            ),
        ),
        ability_phases=(
            AbilityPhaseIR(
                phase_id="ability_phase:avatar_skill:110201:1:0:ValidationSkill01Phase01",
                binding_id="action_binding:avatar_skill:110201:1",
                action_id="avatar_skill:110201",
                level=1,
                ability_name="ValidationSkill01Phase01",
                phase_index=0,
                target_info={},
                opcode_summary={"opcode_counts": {}, "task_count": 0, "raw_task_summary_only": True},
                callback_summaries={},
                source=source,
                coverage_status="lowered",
                blocked_reason="validation_fixture_no_ability_task_execution",
            ),
        ),
        action_events=(
            ActionEventIR(
                action_event_id="action_event:avatar_skill:110201:1",
                action_id="avatar_skill:110201",
                level=1,
                target_mode="single",
                selection_mode="primary",
                phase_steps=(
                    ActionPhaseStepIR(
                        kind="trigger_window",
                        phase="before_skill_use",
                        canonical_window="before_skill_use",
                        tbgd_event="OnBeforeSkillUse",
                        source=source,
                    ),
                    ActionPhaseStepIR(
                        kind="trigger_window",
                        phase="after_skill_use",
                        canonical_window="after_skill_use",
                        tbgd_event="OnAfterSkillUse",
                        source=source,
                    ),
                ),
                hit_profile_ids=(),
                derived_status="validation_fixture",
                derived_reason="minimal replay fixture has no damage hit profile",
                source=source,
                coverage_status="audit_only",
                binding_id="action_binding:avatar_skill:110201:1",
                phase_ids=("ability_phase:avatar_skill:110201:1:0:ValidationSkill01Phase01",),
                source_mode="validation_fixture",
                event_source_status="ability_phase_graph_bound",
            ),
        ),
    )
