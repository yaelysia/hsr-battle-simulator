from __future__ import annotations

import argparse
import ast
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
import subprocess
from typing import Any, Callable

from .. import BASELINE_VERSION
from ..core.executor import CombatExecutor
from ..core.model import ActionCommand, BattleState, JSONValue, Mutation, UnitState
from ..core.reducer import MutationReducer
from ..rules.ir import (
    AbilityPhaseIR,
    AbilityTaskIR,
    ActionAbilityBindingIR,
    ActionDefinitionIR,
    ActionEventIR,
    ActionPhaseStepIR,
    CanonicalIR,
    CombatantActionSetIR,
    EffectIR,
    IRSource,
    ResourceRuleIR,
    TimelineRuleIR,
)
from ..rules.rulebook import RuleBook
from ..systems.action_availability import ActionAvailabilitySystem
from ..systems.damage import DamagePacket, DamageSystem
from ..systems.damage_formula import DamageFormulaInput, DirectDamageFormula
from ..systems.scheduler import CombatScheduler
from ..systems.status import _runtime_chance_admission
from ..systems.target import TargetPolicy, TargetSystem
from .io import write_json


VALIDATION_VERSION = "p7_s0_kernel_trust_baseline"
MATRIX_SCHEMA_VERSION = "p7_s0_issue_matrix_v1"
PROBE_SCHEMA_VERSION = "p7_s0_probe_samples_v1"
PRIOR_SCOPE_SCHEMA_VERSION = "p7_s0_prior_validation_scope_matrix_v1"
STRUCTURED_EVIDENCE_SCHEMA_VERSION = "p7_s0_structured_negative_evidence_v1"

EXPECTED_ISSUE_IDS = tuple(f"P7-I{index:02d}" for index in range(1, 25))
REQUIRED_PROBE_IDS = (
    "partial_transition_mutation_leak",
    "mutation_before_ignored",
    "action_ownership_bypass",
    "single_target_accepts_many",
    "duplicate_begin_turn_on_submit",
    "shield_not_absorbed",
    "control_turn_stalls",
    "omitted_chance_still_resisted",
    "rng_identity_collision",
    "queue_blocked_head_stalls",
)


@dataclass(frozen=True)
class EvidenceSpec:
    path: str
    tokens: tuple[str, ...]


@dataclass(frozen=True)
class IssueSpec:
    issue_id: str
    classification: str
    owner_stage: str
    current_behavior: str
    target_invariant: str
    evidence: tuple[EvidenceSpec, ...]
    probe_ids: tuple[str, ...] = ()


ISSUE_SPECS: tuple[IssueSpec, ...] = (
    IssueSpec(
        "P7-I01",
        "correctness_blocker",
        "P7-S1/P7-S3",
        "CombatExecutor applies timeline, resource, callback, damage and listener mutations while traversing the selected graph; BattleTransition has no authoritative trust result class.",
        "A selected execution graph either commits completely as a trusted successor or returns an untrusted state-unchanged result.",
        (
            EvidenceSpec("simulator_v8_clean_core/core/executor.py", ("current_state = self.reducer.apply_all(state, timeline_mutations)", "ordered_mutations.extend(ability_result.mutations)", "mutations = tuple(ordered_mutations)")),
            EvidenceSpec("simulator_v8_clean_core/core/model.py", ("class BattleTransition:", "coverage: dict[str, JSONValue]", "contract_validation: dict[str, JSONValue]")),
        ),
        ("partial_transition_mutation_leak",),
    ),
    IssueSpec(
        "P7-I02",
        "correctness_blocker",
        "P7-S6",
        "Action query reads an actor action set, but CombatExecutor resolves a submitted global action definition without checking that the definition belongs to the actor's action set or legal window.",
        "Only actions owned by the actor and admitted for the current window are queryable and submittable through one shared contract.",
        (
            EvidenceSpec("simulator_v8_clean_core/systems/action_availability.py", ("action_set = self.rules.combatant_action_set(actor.template_id)", "for skill_index, entry in _sorted_action_set_entries", "choice, reason = self._normal_action_choice(")),
            EvidenceSpec("simulator_v8_clean_core/core/executor.py", ("action_definition = self.rules.require_action_definition(command.action_id, command.action_level)", "actor_lifecycle_ok, actor_lifecycle_reason = self.lifecycle.can_act")),
        ),
        ("action_ownership_bypass",),
    ),
    IssueSpec(
        "P7-I03",
        "correctness_blocker",
        "P7-S8",
        "CombatScheduler.step always advances to the next turn before processing a normal command, even when the caller already used a no-command step to reach the decision state.",
        "Reading a decision is idempotent and submitting that decision consumes exactly the already-open turn without a second begin-turn.",
        (EvidenceSpec("simulator_v8_clean_core/systems/scheduler.py", ("begin_result = self.advance_to_next_turn(state)", "if command is None:", "after_action, action_transition = CombatExecutor(self.rules).execute")),),
        ("duplicate_begin_turn_on_submit",),
    ),
    IssueSpec(
        "P7-I04",
        "architecture_debt",
        "P7-S8",
        "Scheduler obtains EnemyActionSystem.next_candidate and rejects a submitted enemy command that does not match that internally selected candidate.",
        "Enemy and ally decisions use the same external query/submit boundary; only source-backed mandatory constraints may restrict candidates.",
        (EvidenceSpec("simulator_v8_clean_core/systems/scheduler.py", ("enemy_candidate = self.enemy_actions.next_candidate", "enemy_action_command_mismatch", "enemy_action_target_blocked_reason")),),
    ),
    IssueSpec(
        "P7-I05",
        "correctness_blocker",
        "P7-S7",
        "TargetSystem keeps every legal explicit target for target_mode=single and _target_groups returns the whole tuple as selected.",
        "A single-target command accepts exactly one primary target; derived impact targets are produced only by the action definition.",
        (EvidenceSpec("simulator_v8_clean_core/systems/target.py", ("def resolve_action_targets(", "target_groups = _target_groups", "return {\"selected\": legal}")),),
        ("single_target_accepts_many",),
    ),
    IssueSpec(
        "P7-I06",
        "correctness_blocker",
        "P7-S9",
        "Turn, action and status lifecycle work is sequenced by scheduler method order; ActionPhaseEnd status ticking is attached to turn completion rather than a single explicit phase machine.",
        "Turn begin, pre-action, decision, action, post-action and turn end are explicit legal phases with one dispatch point each.",
        (EvidenceSpec("simulator_v8_clean_core/systems/scheduler.py", ("def _complete_pending_turn_end", "self._apply_status_lifecycle_tick(state, \"ActionPhaseEnd\"", "end_result = self.end_current_turn")),),
    ),
    IssueSpec(
        "P7-I07",
        "correctness_blocker",
        "P7-S10",
        "After beginning a candidate turn, scheduler returns _blocked(state) when the actor has a control gate, discarding the begun state and leaving timeline progress unchanged.",
        "A control effect consumes or skips the appropriate turn, advances lifecycle and leaves the scheduler at a later decision point.",
        (EvidenceSpec("simulator_v8_clean_core/systems/scheduler.py", ("control_gate = status_control_gate_for_actor", "scheduler:status_control_gate", "return self._blocked(")),),
        ("control_turn_stalls",),
    ),
    IssueSpec(
        "P7-I08",
        "correctness_blocker",
        "P7-S10",
        "Timeline ties are sorted by unit_id and regular turn end resets the actor to a full action value computed from current speed, without rebasing remaining progress when speed changes.",
        "Timeline ordering and speed changes preserve elapsed progress and use an explicit auditable tie rule.",
        (EvidenceSpec("simulator_v8_clean_core/systems/timeline.py", ("sorted(candidates, key=lambda item: (item[0], item[1]))", "reset_av = self.full_action_value(unit.speed, rule)", "reason=\"reset actor action value after turn\"")),),
    ),
    IssueSpec(
        "P7-I09",
        "correctness_blocker",
        "P7-S13",
        "DamageSystem damage families subtract final damage directly from target.hp and do not read or mutate the shield resource.",
        "Shield-eligible damage is routed through shield instances before HP, with both changes represented as mutations and settlement records.",
        (EvidenceSpec("simulator_v8_clean_core/systems/damage.py", ("after = max(0.0, target.hp - final_damage)", "path=(\"units\", packet.target_id, \"hp\")", "reason=\"apply dot damage\"")),),
        ("shield_not_absorbed",),
    ),
    IssueSpec(
        "P7-I10",
        "correctness_blocker",
        "P7-S12",
        "DoT, break and super-break paths treat packet.amount as final damage rather than a family base value entering declared multiplier stages.",
        "Each damage family declares its base producer and applicable defense, resistance, vulnerability and reduction stages.",
        (EvidenceSpec("simulator_v8_clean_core/systems/damage.py", ("def _apply_dot_damage(", "final_damage = float(packet.amount)", "def _apply_break_damage(", "def _apply_super_break_damage(")),),
    ),
    IssueSpec(
        "P7-I11",
        "correctness_blocker",
        "P7-S12",
        "Executor can resolve a damage/toughness plan before listener dispatch and later apply the previously calculated mutation after listeners have changed state.",
        "Before-event listeners complete before any affected calculation stage reads its input snapshot.",
        (EvidenceSpec("simulator_v8_clean_core/core/executor.py", ("damage_value_resolution = _damage_value_resolution", "dispatch_result = self.event_dispatcher.dispatch_event", "current_state = self.reducer.apply_all(current_state, damage_result.mutations)")),),
    ),
    IssueSpec(
        "P7-I12",
        "correctness_blocker",
        "P7-S2",
        "MutationReducer writes mutation.after for supported paths without comparing the current value to mutation.before or enforcing mutation.op semantics.",
        "Reducer rejects stale before values, illegal operations, inconsistent after values and conflicting chains atomically.",
        (EvidenceSpec("simulator_v8_clean_core/core/reducer.py", ("def apply(self, state: BattleState, mutation: Mutation)", "return replace(state, **{head: mutation.after})", "replace(unit, **{field_name: mutation.after})")),),
        ("mutation_before_ignored",),
    ),
    IssueSpec(
        "P7-I13",
        "correctness_blocker",
        "P7-S14",
        "Omitted chance is labelled chance_omitted_guaranteed, but the same admission still copies target effect_resistance into a second resistance roll.",
        "A structurally guaranteed application is not reduced by ordinary effect resistance; debuff and control resistance paths remain distinct.",
        (EvidenceSpec("simulator_v8_clean_core/systems/status.py", ("source_kind = \"chance_omitted_guaranteed\"", "resist_probability = max(0.0, min(1.0, effect_resistance))", "if resist_probability > 0.0:")),),
        ("omitted_chance_still_resisted",),
    ),
    IssueSpec(
        "P7-I14",
        "correctness_blocker",
        "P7-S3/P7-S14",
        "Status lifecycle admits active_partial and replace_partial operations and can emit mutations while unsupported reasons remain attached.",
        "Any required unsupported duration, property, stack or binding prevents creation of an active status and leaves state unchanged.",
        (EvidenceSpec("simulator_v8_clean_core/systems/status.py", ("lifecycle_state=\"active_partial\" if partial_reasons else \"active\"", "\"replace_partial\": \"status_lifecycle\"", "mutations=mutations")),),
        ("partial_transition_mutation_leak",),
    ),
    IssueSpec(
        "P7-I15",
        "correctness_blocker",
        "P7-S15",
        "Direct crit identity contains event index, actor, action definition and target but omits phase/task/hit identity; RNG ledger lookup accepts rng_type and default fallbacks.",
        "Every independent random decision has one exact unique key and the replay ledger is consumed exactly once without broad fallback.",
        (
            EvidenceSpec("simulator_v8_clean_core/systems/damage_formula.py", ("f\"{formula_input.target_id}:crit\"", "choice_key=f\"crit:{formula_input.attacker_id}:{formula_input.action_definition.definition_id}:{formula_input.target_id}\"")),
            EvidenceSpec("simulator_v8_clean_core/systems/rng.py", ("for key in (request.choice_key, request.event_id, request.rng_type, \"default\")",)),
        ),
        ("rng_identity_collision",),
    ),
    IssueSpec(
        "P7-I16",
        "architecture_debt",
        "P7-S4",
        "Runtime paths still obtain executable policy or numeric binding data from source_trace/source.evidence in executor, scheduler, ability, DoT and status callbacks.",
        "Removing or trimming audit detail cannot change runtime behavior; executable inputs live in typed IR or a versioned engine rule registry.",
        (
            EvidenceSpec("simulator_v8_clean_core/core/executor.py", ("policy = source_trace.get(\"queue_intent_resource_policy\")", "_damage_custom_name_from_trace")),
            EvidenceSpec("simulator_v8_clean_core/systems/dot_formula.py", ("bindings = source_trace.get(\"status_formula_bindings\")",)),
            EvidenceSpec("simulator_v8_clean_core/systems/ability.py", ("action_definition.source.evidence.get(\"skill_trigger_key\")",)),
        ),
    ),
    IssueSpec(
        "P7-I17",
        "architecture_debt",
        "P7-S5",
        "Runtime evaluator and status callback helpers still parse raw PostfixExpr/raw condition structures instead of consuming fully typed executable IR.",
        "Lowering parses and types the supported expression subset; runtime receives typed nodes and blocks unsupported or ambiguous input.",
        (
            EvidenceSpec("simulator_v8_clean_core/rules/evaluator.py", ("return _evaluate_postfix_expr(expression.get(\"raw\") or expression", "_evaluate_raw_condition")),
            EvidenceSpec("simulator_v8_clean_core/systems/status_callbacks.py", ("postfix = raw.get(\"PostfixExpr\")", "postfix = value.get(\"PostfixExpr\")")),
        ),
    ),
    IssueSpec(
        "P7-I18",
        "architecture_debt",
        "P7-S4/P7-S5/P7-S14",
        "Modifier definition selection uses exact source paths, an /Advanced/ path heuristic, then definitions[0] as a final ambiguous fallback.",
        "Definition linking is explicit and unique before runtime; missing or ambiguous links are blocked.",
        (EvidenceSpec("simulator_v8_clean_core/systems/status.py", ("def _select_modifier_definition", "if \"/Advanced/\" in source_path", "return definitions[0]")),),
    ),
    IssueSpec(
        "P7-I19",
        "correctness_blocker",
        "P7-S11",
        "Scheduler returns blocked before dequeue when the selected queue action fails preflight, so the same higher-priority entry can be selected repeatedly.",
        "Every invalid queue entry reaches an auditable terminal or waiting state and cannot permanently block later admitted entries.",
        (EvidenceSpec("simulator_v8_clean_core/systems/scheduler.py", ("preflight_reason = self._queue_action_preflight_reason", "if preflight_reason:", "dequeue = self.queue.drain_admitted")),),
        ("queue_blocked_head_stalls",),
    ),
    IssueSpec(
        "P7-I20",
        "integration_missing",
        "P7-S16",
        "Production callers of SummonSystem plan/apply are currently setup assembly paths; action task/effect/callback execution does not invoke the spawn consumer.",
        "A real structured combat task can spawn a unit through the shared birth template and lifecycle pipeline.",
        (
            EvidenceSpec("simulator_v8_clean_core/scenarios/build_state.py", ("plan = system.plan_spawn_summoned_monster", "result = system.apply_spawn(state, plan)", "plan = system.plan_spawn_servant")),
            EvidenceSpec("simulator_v8_clean_core/systems/summon.py", ("def plan_spawn_summoned_monster", "def apply_spawn(", "def plan_spawn_servant")),
        ),
    ),
    IssueSpec(
        "P7-I21",
        "integration_missing",
        "P7-S9/P7-S17",
        "WaveSystem creates wave events and scheduler applies the transition, but the scheduler wave path does not dispatch those events through EventDispatchSystem.",
        "Wave start, monster enter, clear and battle completion use the common phase machine and event dispatcher with real payloads.",
        (
            EvidenceSpec("simulator_v8_clean_core/systems/scheduler.py", ("plan = self.wave.plan_transition(state)", "result = self.wave.apply_transition(state, plan)")),
            EvidenceSpec("simulator_v8_clean_core/systems/wave.py", ("\"wave.started\"", "\"wave.monster\"", "\"wave.cleared\"")),
        ),
    ),
    IssueSpec(
        "P7-I22",
        "architecture_debt",
        "P7-S4",
        "Timeline and resource base conventions are selected as default rules, but their engine-convention ownership and versioning are not unified in one audited registry.",
        "Every engine convention has a stable id, version, source category and explicit applicability; missing rules block.",
        (
            EvidenceSpec("simulator_v8_clean_core/rules/rulebook.py", ("def default_timeline_rule", "def default_ultimate_energy_cost_rule", "def default_kill_energy_gain_rule")),
            EvidenceSpec("simulator_v8_clean_core/systems/timeline.py", ("return float(rule.base_action_gauge) / effective_speed",)),
        ),
    ),
    IssueSpec(
        "P7-I23",
        "scalability_blocker",
        "P7-S18",
        "BattleTransition serializes full before and after snapshots; snapshot repeats queues and expanded flags/source metadata with no compact semantic state key.",
        "Search nodes use a compact immutable semantic key while complete transition and provenance remain available by reference.",
        (EvidenceSpec("simulator_v8_clean_core/core/model.py", ("\"before\": self.transaction.before.to_json()", "\"after\": self.after.to_json()", "\"queues\": {key: list(value)", "\"flags\": dict(sorted(self.flags.items()))")),),
    ),
    IssueSpec(
        "P7-I24",
        "validation_gap",
        "P7-S0/P7-S19",
        "Existing stage validations prove selected substrates and replay/source-audit self-consistency, but do not aggregate the confirmed kernel invariants in this matrix.",
        "The final aggregate inherits all 24 rows and includes positive and negative invariants for each repaired behavior.",
        (EvidenceSpec("simulator_v8_clean_core/P7_KERNEL_TRUST_AND_COMBAT_SEMANTICS_REPAIR_TASK_PLAN.md", ("P7-I24", "P7-S0", "P7-S19")),),
    ),
)


PRIOR_VALIDATION_SCOPE = (
    {
        "phase": "P1",
        "proves": "Minimum vertical battle slices, transition shape, selected replay/source-audit examples and phase-one source classification.",
        "does_not_prove": "Global atomicity, Mutation.before enforcement, strict target cardinality, shield routing or decision idempotence.",
    },
    {
        "phase": "P2",
        "proves": "Status substrate, lifecycle/chance/control examples and source-family classification under the current runtime semantics.",
        "does_not_prove": "Guaranteed-status resistance semantics, controlled-turn progress or partial-status atomicity.",
    },
    {
        "phase": "P3",
        "proves": "Summon/servant setup substrate, birth relations, target registry, cleanup examples and inherited gap classification.",
        "does_not_prove": "Real combat task/effect/callback spawn integration or complete targetability lifecycle.",
    },
    {
        "phase": "P4",
        "proves": "Combatant data-card/action-query substrate and structured source ownership for selected examples.",
        "does_not_prove": "Strict action role/window ownership or query-submit round trip for every exposed and rejected command.",
    },
    {
        "phase": "P5",
        "proves": "Formula/dynamic/static parameter binding admission and selected consumer/source-audit/replay examples.",
        "does_not_prove": "Correct damage-family multiplier stages or complete removal of audit-driven behavior reads.",
    },
    {
        "phase": "P6",
        "proves": "Explicit damage/toughness calculation entries, first-class birth templates and selected architecture boundary guards.",
        "does_not_prove": "Transition trust, reducer conflicts, combat semantics, raw runtime expression removal or audit-detail behavioral equivalence.",
    },
)


def run_validation(package_root: Path, output_dir: Path) -> dict[str, Any]:
    hsr_root = package_root.parent
    rules = _minimal_rulebook()
    probes = _run_probes(rules)
    structured_evidence = _build_structured_negative_evidence(package_root)
    worktree_scope = _worktree_scope(package_root)
    runtime_behavior_changed = bool(worktree_scope["runtime_behavior_changed_paths"])
    issue_matrix = _build_issue_matrix(
        hsr_root,
        probes,
        structured_evidence=structured_evidence,
        runtime_behavior_changed=runtime_behavior_changed,
    )
    prior_scope_matrix = _build_prior_scope_matrix(runtime_behavior_changed=runtime_behavior_changed)

    issue_summary = issue_matrix["summary"]
    probe_summary = _probe_summary(probes)
    checks = {
        "exact_issue_set": issue_summary["issue_ids"] == list(EXPECTED_ISSUE_IDS),
        "exact_issue_row_count": issue_summary["issue_row_count"] == 24,
        "all_issue_ids_unique": issue_summary["unique_issue_count"] == 24,
        "all_issues_confirmed_open": issue_summary["status_counts"] == {"confirmed_open": 24},
        "all_issue_evidence_present": issue_summary["evidence_missing_count"] == 0,
        "all_issues_have_target_invariant": issue_summary["target_invariant_missing_count"] == 0,
        "required_probe_set_complete": probe_summary["probe_ids"] == list(REQUIRED_PROBE_IDS),
        "all_required_probes_executed": probe_summary["executed_count"] == len(REQUIRED_PROBE_IDS),
        "all_required_defects_observed": probe_summary["current_defect_observed_count"] == len(REQUIRED_PROBE_IDS)
        and probe_summary["current_defect_not_observed_count"] == 0,
        "all_probe_observations_structured": probe_summary["observation_missing_count"] == 0,
        "all_probe_targets_structured": probe_summary["target_invariant_missing_count"] == 0,
        "structured_negative_evidence_complete": structured_evidence["summary"]["ok"] is True,
        "prior_validation_scope_complete": prior_scope_matrix["summary"]["row_count"] == 6,
        "runtime_behavior_unchanged": not runtime_behavior_changed,
    }
    ok = all(checks.values())
    summary = {
        "version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "ok": ok,
        "p7_s0_ready_for_review": ok,
        "p7_all_fixed": False,
        "p7_done_eligible": False,
        "runtime_behavior_changed": runtime_behavior_changed,
        "issue_summary": issue_summary,
        "probe_summary": probe_summary,
        "structured_negative_evidence_summary": structured_evidence["summary"],
        "worktree_scope": worktree_scope,
        "prior_validation_scope_summary": prior_scope_matrix["summary"],
        "checks": checks,
        "resource_budget": {
            "tbgd_lowering_build_count": 0,
            "full_rulebook_build_count": 0,
            "minimal_in_memory_rulebook_build_count": 1,
            "git_metadata_subprocess_count": 1,
            "child_validation_subprocess_count": 0,
            "large_artifacts_written": False,
            "full_ir_written": False,
            "full_transition_dump_written": False,
            "output_scope": "summary_issue_matrix_probe_samples_prior_scope_structured_evidence_only",
        },
        "selection_policy": {
            "mode": "generic_in_memory_invariants_and_full_package_ast_structural_evidence",
            "fixed_character_monster_skill_stage_file_hash_or_observation_used": False,
            "tbgd_or_textmap_read": False,
            "current_defects_are_not_treated_as_correct_behavior": True,
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "p7_s0_issue_matrix.json", issue_matrix)
    write_json(
        output_dir / "p7_s0_probe_samples.json",
        {"schema_version": PROBE_SCHEMA_VERSION, "summary": probe_summary, "probes": probes},
    )
    write_json(output_dir / "p7_s0_prior_validation_scope_matrix.json", prior_scope_matrix)
    write_json(output_dir / "p7_s0_structured_negative_evidence.json", structured_evidence)
    write_json(output_dir / "validation_summary_p7_s0_kernel_trust_baseline.json", summary)
    return summary


def _run_probes(rules: RuleBook) -> dict[str, dict[str, JSONValue]]:
    probe_functions: dict[str, Callable[[RuleBook], dict[str, JSONValue]]] = {
        "partial_transition_mutation_leak": _partial_transition_probe,
        "mutation_before_ignored": _mutation_before_probe,
        "action_ownership_bypass": _action_ownership_probe,
        "single_target_accepts_many": _single_target_probe,
        "duplicate_begin_turn_on_submit": _duplicate_begin_turn_probe,
        "shield_not_absorbed": _shield_probe,
        "control_turn_stalls": _control_stall_probe,
        "omitted_chance_still_resisted": _omitted_chance_probe,
        "rng_identity_collision": _rng_identity_probe,
        "queue_blocked_head_stalls": _queue_head_probe,
    }
    probes: dict[str, dict[str, JSONValue]] = {}
    for probe_id in REQUIRED_PROBE_IDS:
        try:
            result = probe_functions[probe_id](rules)
            probes[probe_id] = {"probe_id": probe_id, "executed": True, **result}
        except Exception as exc:  # pragma: no cover - validation surface
            probes[probe_id] = {
                "probe_id": probe_id,
                "executed": False,
                "current_defect_observed": False,
                "current_observation": {"error": f"{type(exc).__name__}: {exc}"},
                "target_invariant": "Probe must execute successfully before this issue can enter review.",
                "error": f"{type(exc).__name__}: {exc}",
            }
    return probes


def _partial_transition_probe(rules: RuleBook) -> dict[str, JSONValue]:
    state = _base_state(skill_points=3)
    command = ActionCommand(
        actor_id="ally:actor",
        action_id="validation:partial",
        action_level=1,
        target_ids=("enemy:target",),
    )
    after, transition = CombatExecutor(rules).execute(command, state)
    records = tuple(transition.transaction.settlement.records if transition.transaction.settlement else ())
    blocked_task_records = [
        record
        for record in records
        if isinstance(record, dict)
        and record.get("record_type") == "ability_task"
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("ok") is False
    ]
    transition_json = transition.to_json()
    state_changed = after.snapshot().to_json() != state.snapshot().to_json()
    observed = (
        transition.coverage.get("action_enabled") is True
        and bool(transition.transaction.mutations)
        and bool(blocked_task_records)
        and state_changed
        and not any(key in transition_json for key in ("trust_class", "result_class", "successor_trust"))
    )
    return {
        "issue_ids": ["P7-I01", "P7-I14"],
        "current_defect_observed": observed,
        "current_observation": {
            "action_enabled": transition.coverage.get("action_enabled"),
            "mutation_count": len(transition.transaction.mutations),
            "blocked_task_record_count": len(blocked_task_records),
            "state_changed": state_changed,
            "authoritative_trust_field_present": any(
                key in transition_json for key in ("trust_class", "result_class", "successor_trust")
            ),
        },
        "target_invariant": "A selected unsupported task makes the whole transition untrusted and state unchanged with zero committed mutations.",
    }


def _mutation_before_probe(_: RuleBook) -> dict[str, JSONValue]:
    state = _base_state(skill_points=3)
    mutation = Mutation(
        op="set",
        path=("skill_points",),
        before=999,
        after=1,
        reason="p7 s0 stale before probe",
        source="validation",
    )
    after = MutationReducer().apply_all(state, (mutation,))
    observed = after.skill_points == 1
    return {
        "issue_ids": ["P7-I12"],
        "current_defect_observed": observed,
        "current_observation": {
            "actual_before": state.skill_points,
            "declared_before": mutation.before,
            "declared_after": mutation.after,
            "applied_after": after.skill_points,
            "stale_before_accepted": observed,
        },
        "target_invariant": "A stale before value is rejected atomically and the original state remains unchanged.",
    }


def _action_ownership_probe(rules: RuleBook) -> dict[str, JSONValue]:
    state = _decision_state(_base_state())
    view = ActionAvailabilitySystem(rules).view(state)
    queried_action_ids = [choice.action_id for choice in view.choices]
    command = ActionCommand(
        actor_id="ally:actor",
        action_id="validation:foreign",
        action_level=1,
        target_ids=("enemy:target",),
    )
    after, transition = CombatExecutor(rules).execute(command, state)
    accepted = transition.coverage.get("action_enabled") is True and after.snapshot().to_json() != state.snapshot().to_json()
    observed = "validation:foreign" not in queried_action_ids and accepted
    return {
        "issue_ids": ["P7-I02"],
        "current_defect_observed": observed,
        "current_observation": {
            "query_mode": view.mode,
            "queried_action_ids": queried_action_ids,
            "foreign_action_queried": "validation:foreign" in queried_action_ids,
            "foreign_action_submit_action_enabled": transition.coverage.get("action_enabled"),
            "foreign_action_submit_mutation_count": len(transition.transaction.mutations),
        },
        "target_invariant": "An action absent from the actor's query result is rejected on submit with state unchanged.",
    }


def _single_target_probe(_: RuleBook) -> dict[str, JSONValue]:
    state = _base_state(include_second_enemy=True)
    result = TargetSystem().resolve_action_targets(
        state,
        "ally:actor",
        ("enemy:target", "enemy:second"),
        policy=TargetPolicy(
            policy_id="validation:single",
            allow_enemy=True,
            allow_ally=False,
            allow_self=False,
            target_mode="single",
            selection_mode="explicit",
        ),
    )
    observed = result.ok and result.resolution.selected == ("enemy:target", "enemy:second")
    return {
        "issue_ids": ["P7-I05"],
        "current_defect_observed": observed,
        "current_observation": {
            "ok": result.ok,
            "requested": list(result.resolution.requested),
            "legal": list(result.resolution.legal),
            "selected": list(result.resolution.selected),
            "errors": list(result.errors),
        },
        "target_invariant": "A single-target policy rejects more than one chosen primary target instead of filtering or accepting the list.",
    }


def _duplicate_begin_turn_probe(rules: RuleBook) -> dict[str, JSONValue]:
    state = _base_state()
    scheduler = CombatScheduler(rules)
    begin = scheduler.step(state, None)
    before_query = begin.after_state.snapshot().to_json()
    view = scheduler.action_availability(begin.after_state)
    after_query = begin.after_state.snapshot().to_json()
    choice = next(choice for choice in view.choices if choice.action_id == "validation:normal")
    targets = choice.auto_target_ids or choice.selectable_target_ids[:1]
    submitted = scheduler.step(
        begin.after_state,
        ActionCommand(
            actor_id=choice.actor_id,
            action_id=choice.action_id,
            action_level=choice.action_level,
            target_ids=targets,
        ),
    )
    duplicate_mutations = [
        mutation
        for mutation in submitted.transition.transaction.mutations
        if mutation.path == ("global_flags", "turn_sequence_index") and mutation.before == 1 and mutation.after == 2
    ]
    observed = before_query == after_query and bool(duplicate_mutations)
    return {
        "issue_ids": ["P7-I03"],
        "current_defect_observed": observed,
        "current_observation": {
            "first_turn_sequence_index": begin.after_state.global_flags.get("turn_sequence_index"),
            "query_state_unchanged": before_query == after_query,
            "submit_duplicate_begin_mutation_count": len(duplicate_mutations),
            "submit_after_turn_sequence_index": submitted.after_state.global_flags.get("turn_sequence_index"),
        },
        "target_invariant": "Query is read-only and submitting its choice does not emit another turn-begin mutation.",
    }


def _shield_probe(_: RuleBook) -> dict[str, JSONValue]:
    state = _base_state(target_hp=100.0, target_shield=50.0)
    packet = DamagePacket(
        attacker_id="ally:actor",
        target_id="enemy:target",
        attack_type="DoT",
        damage_formula_family="dot",
        amount=30.0,
        status_damage_emission_id="validation:dot",
        status_instance_id="validation:status",
        source_trace={"validation": VALIDATION_VERSION},
    )
    result = DamageSystem().apply_packet(state, packet)
    after = MutationReducer().apply_all(state, result.mutations)
    target = after.units["enemy:target"]
    observed = result.ok and target.hp == 70.0 and target.resources.get("shield") == 50.0
    return {
        "issue_ids": ["P7-I09"],
        "current_defect_observed": observed,
        "current_observation": {
            "damage_ok": result.ok,
            "before_hp": 100.0,
            "after_hp": target.hp,
            "before_shield": 50.0,
            "after_shield": target.resources.get("shield"),
            "mutation_paths": [list(mutation.path) for mutation in result.mutations],
        },
        "target_invariant": "Thirty shield-eligible damage consumes shield from 50 to 20 and leaves HP at 100.",
    }


def _control_stall_probe(rules: RuleBook) -> dict[str, JSONValue]:
    state = _base_state()
    actor = state.units["ally:actor"]
    detail: dict[str, JSONValue] = {
        "instance_id": "validation:control:1",
        "status_id": "validation:control",
        "modifier_name": "ValidationControl",
        "status_category": "control",
        "control_kind": "skip_turn",
        "lifecycle_state": "active",
        "source_trace": {"validation": VALIDATION_VERSION},
    }
    controlled_actor = replace(actor, flags={**actor.flags, "status_details": [detail]})
    controlled = replace(state, units={**state.units, "ally:actor": controlled_actor})
    command = ActionCommand(
        actor_id="ally:actor",
        action_id="validation:normal",
        action_level=1,
        target_ids=("enemy:target",),
    )
    scheduler = CombatScheduler(rules)
    first = scheduler.step(controlled, command)
    second = scheduler.step(first.after_state, command)
    unchanged_first = first.after_state.snapshot().to_json() == controlled.snapshot().to_json()
    unchanged_second = second.after_state.snapshot().to_json() == controlled.snapshot().to_json()
    first_reason = str(first.transition.coverage.get("blocked_reason") or "")
    second_reason = str(second.transition.coverage.get("blocked_reason") or "")
    observed = unchanged_first and unchanged_second and first_reason.startswith("status_control_gate:") and first_reason == second_reason
    return {
        "issue_ids": ["P7-I07"],
        "current_defect_observed": observed,
        "current_observation": {
            "first_blocked_reason": first_reason,
            "second_blocked_reason": second_reason,
            "first_state_unchanged": unchanged_first,
            "second_state_unchanged": unchanged_second,
            "action_value_after_two_attempts": second.after_state.units["ally:actor"].action_value,
            "turn_sequence_index_after_two_attempts": second.after_state.global_flags.get("turn_sequence_index"),
        },
        "target_invariant": "The control status consumes or skips the turn and the scheduler reaches a later decision state.",
    }


def _omitted_chance_probe(_: RuleBook) -> dict[str, JSONValue]:
    state = _base_state(target_effect_resistance=0.5)
    standard: dict[str, JSONValue] = {
        "modifier_name": "ValidationStatus",
        "chance": {"kind": "missing"},
    }
    effect = EffectIR(
        effect_id="validation:omitted_chance",
        opcode="AddModifier",
        payload={"standard": standard},
        source=_source("omitted_chance"),
        coverage_status="executable",
    )
    admission = _runtime_chance_admission(
        standard,
        effect,
        state,
        caster_id="ally:actor",
        target_id="enemy:target",
        dynamic_values=None,
        binding_sources=(),
    )
    observed = (
        admission.get("source_kind") == "chance_omitted_guaranteed"
        and admission.get("base_success_probability") == 1.0
        and admission.get("resist_probability") == 0.5
        and admission.get("guaranteed") is False
    )
    return {
        "issue_ids": ["P7-I13"],
        "current_defect_observed": observed,
        "current_observation": {
            "source_kind": admission.get("source_kind"),
            "base_success_probability": admission.get("base_success_probability"),
            "effect_resistance": admission.get("effect_resistance"),
            "resist_probability": admission.get("resist_probability"),
            "guaranteed": admission.get("guaranteed"),
        },
        "target_invariant": "An omitted chance that structurally means guaranteed does not create an ordinary effect-resistance roll.",
    }


def _rng_identity_probe(_: RuleBook) -> dict[str, JSONValue]:
    state = _base_state()
    action = _action_definition("validation:rng", bp_need=0.0)
    formula_input = DamageFormulaInput(
        state=state,
        attacker_id="ally:actor",
        target_id="enemy:target",
        action_definition=action,
        attack_type="Normal",
        element_type="fire",
        scaling_ratio=1.0,
        scaling_basis={"kind": "fixed", "value": 100.0},
        source_trace={"validation": VALIDATION_VERSION},
        rng_mode="deterministic_seed",
    )
    first = DirectDamageFormula().calculate(formula_input).rng_events[0]
    second = DirectDamageFormula().calculate(formula_input).rng_events[0]
    first_choice_key = str(first.metadata.get("choice_key") or "")
    second_choice_key = str(second.metadata.get("choice_key") or "")
    observed = first.event_id == second.event_id and first_choice_key == second_choice_key and bool(first_choice_key)
    return {
        "issue_ids": ["P7-I15"],
        "current_defect_observed": observed,
        "current_observation": {
            "first_event_id": first.event_id,
            "second_event_id": second.event_id,
            "first_choice_key": first_choice_key,
            "second_choice_key": second_choice_key,
            "event_ids_collide": first.event_id == second.event_id,
            "choice_keys_collide": first_choice_key == second_choice_key,
            "simulated_logical_hits": [0, 1],
        },
        "target_invariant": "Two logical hits on the same target have distinct stable event ids and exact choice keys.",
    }


def _queue_head_probe(rules: RuleBook) -> dict[str, JSONValue]:
    state = _base_state(include_second_ally=True, actor_energy=100.0, second_ally_energy=100.0)
    scheduler = CombatScheduler(rules)
    first_enqueue = scheduler.enqueue_manual_ultimate(
        state,
        ActionCommand(
            actor_id="ally:actor",
            action_id="validation:ultimate",
            action_level=1,
            target_ids=("enemy:target",),
        ),
    )
    second_enqueue = scheduler.enqueue_manual_ultimate(
        first_enqueue.after_state,
        ActionCommand(
            actor_id="ally:second",
            action_id="validation:ultimate",
            action_level=1,
            target_ids=("enemy:target",),
        ),
    )
    actor = second_enqueue.after_state.units["ally:actor"]
    stalled = replace(
        second_enqueue.after_state,
        units={**second_enqueue.after_state.units, "ally:actor": replace(actor, energy=0.0)},
    )
    queue_before = tuple(stalled.queues.get("manual_ultimate", ()))
    blocked_command = ActionCommand(
        actor_id="ally:actor",
        action_id="validation:ultimate",
        action_level=1,
        target_ids=("enemy:target",),
    )
    first = scheduler.step(stalled, blocked_command)
    second = scheduler.step(first.after_state, blocked_command)
    queue_after_first = tuple(first.after_state.queues.get("manual_ultimate", ()))
    queue_after_second = tuple(second.after_state.queues.get("manual_ultimate", ()))
    head_before = _queue_entry_id(queue_before, 0)
    head_after_second = _queue_entry_id(queue_after_second, 0)
    second_entry_id = _queue_entry_id(queue_before, 1)
    first_reason = str(first.transition.coverage.get("blocked_reason") or "")
    second_reason = str(second.transition.coverage.get("blocked_reason") or "")
    observed = (
        len(queue_before) == 2
        and queue_after_first == queue_before
        and queue_after_second == queue_before
        and head_before == head_after_second
        and bool(second_entry_id)
        and first_reason == second_reason
        and first_reason == "manual_ultimate_energy_not_ready_at_drain"
    )
    return {
        "issue_ids": ["P7-I19"],
        "current_defect_observed": observed,
        "current_observation": {
            "queue_length_before": len(queue_before),
            "queue_length_after_first": len(queue_after_first),
            "queue_length_after_second": len(queue_after_second),
            "head_entry_id_before": head_before,
            "head_entry_id_after_second": head_after_second,
            "later_entry_id": second_entry_id,
            "first_blocked_reason": first_reason,
            "second_blocked_reason": second_reason,
            "queue_unchanged_after_two_attempts": queue_after_second == queue_before,
        },
        "target_invariant": "A permanently invalid selected queue entry reaches a terminal state and the later admitted entry can progress.",
    }


class _CallSiteCollector(ast.NodeVisitor):
    def __init__(self, *, path: str, target_names: set[str]):
        self.path = path
        self.target_names = target_names
        self.scope: list[str] = []
        self.call_sites: list[dict[str, JSONValue]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_Call(self, node: ast.Call) -> None:
        call_name = _ast_call_name(node.func)
        leaf_name = call_name.rsplit(".", 1)[-1]
        if leaf_name in self.target_names:
            self.call_sites.append(
                {
                    "path": self.path,
                    "line": node.lineno,
                    "enclosing_symbol": ".".join(self.scope) or "<module>",
                    "call_name": call_name,
                    "leaf_name": leaf_name,
                }
            )
        self.generic_visit(node)


def _build_structured_negative_evidence(package_root: Path) -> dict[str, Any]:
    inventory, parse_errors = _python_ast_inventory(package_root)
    issues = {
        "P7-I20": _summon_call_graph_evidence(inventory, parse_errors),
        "P7-I21": _wave_dispatch_evidence(inventory, parse_errors),
        "P7-I23": _compact_state_interface_evidence(inventory, parse_errors),
    }
    observed = [issue_id for issue_id, evidence in issues.items() if evidence["current_defect_structurally_observed"] is True]
    return {
        "schema_version": STRUCTURED_EVIDENCE_SCHEMA_VERSION,
        "scan_scope": {
            "root": "simulator_v8_clean_core",
            "python_file_count": len(inventory),
            "parse_error_count": len(parse_errors),
            "parse_errors": parse_errors,
            "method": "full-package Python AST scan plus exact owning-function/class inventory",
        },
        "issues": issues,
        "summary": {
            "required_issue_ids": ["P7-I20", "P7-I21", "P7-I23"],
            "structurally_observed_issue_ids": observed,
            "structurally_observed_count": len(observed),
            "parse_error_count": len(parse_errors),
            "ok": len(observed) == 3 and not parse_errors,
        },
    }


def _python_ast_inventory(package_root: Path) -> tuple[dict[str, ast.Module], list[dict[str, JSONValue]]]:
    inventory: dict[str, ast.Module] = {}
    parse_errors: list[dict[str, JSONValue]] = []
    for path in sorted(package_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(package_root).as_posix()
        display_path = f"simulator_v8_clean_core/{relative}"
        try:
            inventory[display_path] = ast.parse(path.read_text(encoding="utf-8"), filename=display_path)
        except (OSError, SyntaxError) as exc:
            parse_errors.append({"path": display_path, "error": f"{type(exc).__name__}: {exc}"})
    return inventory, parse_errors


def _summon_call_graph_evidence(
    inventory: dict[str, ast.Module],
    parse_errors: list[dict[str, JSONValue]],
) -> dict[str, Any]:
    target_names = {
        "plan_spawn_from_intent",
        "plan_spawn_summoned_monster",
        "apply_spawn",
        "plan_spawn_servant",
        "apply_spawn_servant",
    }
    call_sites: list[dict[str, JSONValue]] = []
    for path, tree in inventory.items():
        collector = _CallSiteCollector(path=path, target_names=target_names)
        collector.visit(tree)
        call_sites.extend(collector.call_sites)
    call_sites.sort(key=lambda item: (str(item["path"]), int(item["line"]), str(item["call_name"])))

    validation_calls = [item for item in call_sites if "/tools/" in f"/{item['path']}"]
    production_calls = [item for item in call_sites if "/tools/" not in f"/{item['path']}"]
    setup_calls = [item for item in production_calls if item["path"] == "simulator_v8_clean_core/scenarios/build_state.py"]
    internal_delegate_calls = [item for item in production_calls if item["path"] == "simulator_v8_clean_core/systems/summon.py"]
    unexpected_production_calls = [
        item
        for item in production_calls
        if item["path"]
        not in {
            "simulator_v8_clean_core/scenarios/build_state.py",
            "simulator_v8_clean_core/systems/summon.py",
        }
    ]
    setup_leaf_names = sorted({str(item["leaf_name"]) for item in setup_calls})
    expected_setup_leaf_names = sorted(
        {"plan_spawn_summoned_monster", "apply_spawn", "plan_spawn_servant", "apply_spawn_servant"}
    )
    observed = not parse_errors and setup_leaf_names == expected_setup_leaf_names and not unexpected_production_calls
    return {
        "issue_id": "P7-I20",
        "claim": "SummonSystem 的生产调用只存在于 setup 装配和系统内部委托，战斗执行调用链没有 spawn consumer。",
        "scan_predicate": "collect every AST Call whose attribute leaf is a public SummonSystem spawn plan/apply entry; tools are validation-only; every other package file is production scope",
        "current_defect_structurally_observed": observed,
        "production_call_count": len(production_calls),
        "setup_call_count": len(setup_calls),
        "internal_delegate_call_count": len(internal_delegate_calls),
        "validation_call_count": len(validation_calls),
        "unexpected_production_call_count": len(unexpected_production_calls),
        "expected_setup_leaf_names": expected_setup_leaf_names,
        "observed_setup_leaf_names": setup_leaf_names,
        "production_call_sites": production_calls,
        "unexpected_production_call_sites": unexpected_production_calls,
    }


def _wave_dispatch_evidence(
    inventory: dict[str, ast.Module],
    parse_errors: list[dict[str, JSONValue]],
) -> dict[str, Any]:
    scheduler_path = "simulator_v8_clean_core/systems/scheduler.py"
    wave_path = "simulator_v8_clean_core/systems/wave.py"
    scheduler_tree = inventory.get(scheduler_path)
    wave_tree = inventory.get(wave_path)
    function = _find_function(scheduler_tree, "_try_wave_transition") if scheduler_tree is not None else None
    function_calls = sorted(
        (
            {
                "path": scheduler_path,
                "line": call.lineno,
                "call_name": _ast_call_name(call.func),
            }
            for call in ast.walk(function) if isinstance(call, ast.Call)
        ),
        key=lambda item: int(item["line"]),
    ) if function is not None else []
    call_names = [str(item["call_name"]) for item in function_calls]
    dispatcher_calls = [
        item
        for item in function_calls
        if str(item["call_name"]).endswith("dispatch_event")
        or str(item["call_name"]).endswith("dispatch_action_window")
    ]
    transition_event_forwards: list[dict[str, JSONValue]] = []
    if function is not None:
        for call in ast.walk(function):
            if not isinstance(call, ast.Call) or _ast_call_name(call.func) != "_transition":
                continue
            for keyword in call.keywords:
                if keyword.arg == "events" and "result.events" in ast.unparse(keyword.value):
                    transition_event_forwards.append(
                        {"path": scheduler_path, "line": call.lineno, "value": ast.unparse(keyword.value)}
                    )

    event_producers: list[dict[str, JSONValue]] = []
    if wave_tree is not None:
        for call in ast.walk(wave_tree):
            if not isinstance(call, ast.Call) or _ast_call_name(call.func).rsplit(".", 1)[-1] != "GameEvent":
                continue
            if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
                event_producers.append(
                    {"path": wave_path, "line": call.lineno, "event_type": call.args[0].value}
                )
    event_producers.sort(key=lambda item: int(item["line"]))
    event_types = sorted({str(item["event_type"]) for item in event_producers})
    required_event_types = ["battle.defeat", "battle.victory", "wave.cleared", "wave.monster", "wave.started"]
    caller_collector = _CallSiteCollector(path=scheduler_path, target_names={"_try_wave_transition"})
    if scheduler_tree is not None:
        caller_collector.visit(scheduler_tree)
    production_caller_sites = [
        item
        for item in caller_collector.call_sites
        if str(item["enclosing_symbol"]) != "CombatScheduler._try_wave_transition"
    ]
    step_function = _find_function(scheduler_tree, "step") if scheduler_tree is not None else None
    step_returns_wave_result_directly = any(
        isinstance(node, ast.Return) and isinstance(node.value, ast.Name) and node.value.id == "wave_step"
        for node in (ast.walk(step_function) if step_function is not None else ())
    )
    step_dispatcher_calls = [
        {
            "path": scheduler_path,
            "line": node.lineno,
            "call_name": _ast_call_name(node.func),
        }
        for node in (ast.walk(step_function) if step_function is not None else ())
        if isinstance(node, ast.Call)
        and (
            _ast_call_name(node.func).endswith("dispatch_event")
            or _ast_call_name(node.func).endswith("dispatch_action_window")
        )
    ]
    observed = (
        not parse_errors
        and function is not None
        and "self.wave.plan_transition" in call_names
        and "self.wave.apply_transition" in call_names
        and event_types == required_event_types
        and len(transition_event_forwards) >= 1
        and not dispatcher_calls
        and len(production_caller_sites) == 1
        and production_caller_sites[0]["enclosing_symbol"] == "CombatScheduler.step"
        and step_returns_wave_result_directly
        and not step_dispatcher_calls
    )
    return {
        "issue_id": "P7-I21",
        "claim": "WaveSystem 产生事件，scheduler 的 wave transition 只把事件写入 transition，未调用统一事件派发器。",
        "scan_predicate": "inspect the complete AST body of CombatScheduler._try_wave_transition, its full-package caller set, the public step return path, and all GameEvent constructors in systems/wave.py",
        "current_defect_structurally_observed": observed,
        "owning_function_found": function is not None,
        "function_calls": function_calls,
        "dispatcher_call_count": len(dispatcher_calls),
        "dispatcher_call_sites": dispatcher_calls,
        "transition_event_forward_count": len(transition_event_forwards),
        "transition_event_forwards": transition_event_forwards,
        "production_caller_count": len(production_caller_sites),
        "production_caller_sites": production_caller_sites,
        "step_returns_wave_result_directly": step_returns_wave_result_directly,
        "step_dispatcher_call_count": len(step_dispatcher_calls),
        "step_dispatcher_call_sites": step_dispatcher_calls,
        "required_event_types": required_event_types,
        "observed_event_types": event_types,
        "event_producer_sites": event_producers,
    }


def _compact_state_interface_evidence(
    inventory: dict[str, ast.Module],
    parse_errors: list[dict[str, JSONValue]],
) -> dict[str, Any]:
    model_path = "simulator_v8_clean_core/core/model.py"
    model_tree = inventory.get(model_path)
    class_names = ("BattleState", "Snapshot", "BattleTransition")
    classes = {name: _find_class(model_tree, name) if model_tree is not None else None for name in class_names}
    public_methods = {
        name: sorted(
            node.name
            for node in (class_node.body if class_node is not None else [])
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_")
        )
        for name, class_node in classes.items()
    }
    class_fields = {
        name: sorted(
            node.target.id
            for node in (class_node.body if class_node is not None else [])
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        )
        for name, class_node in classes.items()
    }
    battle_snapshot = _find_direct_method(classes["BattleState"], "snapshot")
    transition_to_json = _find_direct_method(classes["BattleTransition"], "to_json")
    unit_state = _find_class(model_tree, "UnitState") if model_tree is not None else None
    unit_snapshot = _find_direct_method(unit_state, "to_snapshot")
    battle_snapshot_source = ast.unparse(battle_snapshot) if battle_snapshot is not None else ""
    transition_source = ast.unparse(transition_to_json) if transition_to_json is not None else ""
    unit_snapshot_source = ast.unparse(unit_snapshot) if unit_snapshot is not None else ""

    candidate_symbols: list[dict[str, JSONValue]] = []
    candidate_tokens = ("compact_state", "semantic_state", "state_key", "search_state", "transposition")
    for path, tree in inventory.items():
        if "/tools/" in f"/{path}":
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            lowered = node.name.lower()
            if any(token in lowered for token in candidate_tokens):
                candidate_symbols.append({"path": path, "line": node.lineno, "symbol": node.name})
    candidate_symbols.sort(key=lambda item: (str(item["path"]), int(item["line"]), str(item["symbol"])))

    serializes_full_before_after = (
        "self.transaction.before.to_json()" in transition_source and "self.after.to_json()" in transition_source
    )
    repeated_queue_projection_count = battle_snapshot_source.count("self.queues")
    expands_unit_flags = "dict(sorted(self.flags.items()))" in unit_snapshot_source
    expected_public_methods = {
        "BattleState": ["snapshot"],
        "Snapshot": ["to_json"],
        "BattleTransition": ["to_json"],
    }
    observed = (
        not parse_errors
        and all(classes.values())
        and public_methods == expected_public_methods
        and serializes_full_before_after
        and repeated_queue_projection_count >= 2
        and expands_unit_flags
        and not candidate_symbols
    )
    return {
        "issue_id": "P7-I23",
        "claim": "公开状态/transition 接口只提供完整 snapshot/to_json，未提供紧凑语义状态键。",
        "scan_predicate": "inventory direct public methods and fields of BattleState/Snapshot/BattleTransition, inspect their AST serialization bodies, then scan all production symbol names for compact/search-state key candidates",
        "current_defect_structurally_observed": observed,
        "public_methods": public_methods,
        "expected_public_methods_for_current_baseline": expected_public_methods,
        "class_fields": class_fields,
        "serializes_full_before_after": serializes_full_before_after,
        "battle_snapshot_queue_projection_count": repeated_queue_projection_count,
        "unit_snapshot_expands_full_flags": expands_unit_flags,
        "compact_state_candidate_count": len(candidate_symbols),
        "compact_state_candidate_symbols": candidate_symbols,
    }


def _ast_call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _ast_call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ast.unparse(node)


def _find_function(tree: ast.AST | None, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    if tree is None:
        return None
    return next(
        (node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name),
        None,
    )


def _find_class(tree: ast.AST | None, name: str) -> ast.ClassDef | None:
    if tree is None:
        return None
    return next((node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == name), None)


def _find_direct_method(
    class_node: ast.ClassDef | None,
    name: str,
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    if class_node is None:
        return None
    return next(
        (node for node in class_node.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name),
        None,
    )


def _worktree_scope(package_root: Path) -> dict[str, Any]:
    repo_root = next((path for path in (package_root, *package_root.parents) if (path / ".git").exists()), None)
    if repo_root is None:
        return {
            "git_status_available": False,
            "git_status_error": "repository_root_not_found",
            "changed_paths": [],
            "runtime_behavior_changed_paths": ["<git status unavailable>"],
        }
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {
            "git_status_available": False,
            "git_status_error": result.stderr.strip() or f"git_status_exit_{result.returncode}",
            "changed_paths": [],
            "runtime_behavior_changed_paths": ["<git status unavailable>"],
        }
    changed_paths: list[dict[str, JSONValue]] = []
    records = result.stdout.split("\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        status = record[:2]
        path = record[3:]
        changed_path: dict[str, JSONValue] = {"status": status, "path": path}
        if "R" in status or "C" in status:
            if index < len(records) and records[index]:
                changed_path["original_path"] = records[index]
            index += 1
        changed_paths.append(changed_path)

    core_prefix = package_root.relative_to(repo_root).as_posix() + "/"
    runtime_behavior_paths = sorted(
        {
            candidate
            for item in changed_paths
            for candidate in (str(item["path"]), str(item.get("original_path") or ""))
            if candidate.startswith(core_prefix)
            and candidate.endswith(".py")
            and not candidate.startswith(f"{core_prefix}tools/")
        }
    )
    return {
        "git_status_available": True,
        "git_status_error": "",
        "changed_paths": changed_paths,
        "runtime_scope_predicate": f"{core_prefix}**/*.py excluding {core_prefix}tools/**",
        "runtime_behavior_changed_paths": runtime_behavior_paths,
    }


def _build_issue_matrix(
    hsr_root: Path,
    probes: dict[str, dict[str, JSONValue]],
    *,
    structured_evidence: dict[str, Any],
    runtime_behavior_changed: bool,
) -> dict[str, Any]:
    rows = []
    for spec in ISSUE_SPECS:
        evidence = [_evidence_row(hsr_root, item) for item in spec.evidence]
        issue_structured_evidence = structured_evidence["issues"].get(spec.issue_id)
        token_evidence_present = all(item["missing_token_count"] == 0 for item in evidence)
        structured_evidence_present = issue_structured_evidence is None or issue_structured_evidence[
            "current_defect_structurally_observed"
        ] is True
        rows.append(
            {
                "issue_id": spec.issue_id,
                "classification": spec.classification,
                "status": "confirmed_open",
                "owner_stage": spec.owner_stage,
                "current_behavior": spec.current_behavior,
                "target_invariant": spec.target_invariant,
                "probe_ids": list(spec.probe_ids),
                "probe_observations": [
                    {
                        "probe_id": probe_id,
                        "executed": probes.get(probe_id, {}).get("executed"),
                        "current_defect_observed": probes.get(probe_id, {}).get("current_defect_observed"),
                    }
                    for probe_id in spec.probe_ids
                ],
                "evidence": evidence,
                "structured_evidence_required": issue_structured_evidence is not None,
                "structured_evidence": issue_structured_evidence,
                "evidence_status": "present" if token_evidence_present and structured_evidence_present else "missing",
                "gap_classification": "confirmed_kernel_issue_not_source_gap",
            }
        )
    ids = [row["issue_id"] for row in rows]
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "issues": rows,
        "summary": {
            "issue_row_count": len(rows),
            "unique_issue_count": len(set(ids)),
            "issue_ids": sorted(ids),
            "classification_counts": dict(sorted(Counter(row["classification"] for row in rows).items())),
            "status_counts": dict(sorted(Counter(row["status"] for row in rows).items())),
            "owner_stage_counts": dict(sorted(Counter(row["owner_stage"] for row in rows).items())),
            "evidence_missing_count": sum(row["evidence_status"] != "present" for row in rows),
            "target_invariant_missing_count": sum(not row["target_invariant"] for row in rows),
            "confirmed_open_count": sum(row["status"] == "confirmed_open" for row in rows),
            "accepted_fixed_count": 0,
            "source_gap_blocked_count": 0,
            "structured_evidence_required_count": sum(row["structured_evidence_required"] for row in rows),
            "structured_evidence_missing_count": sum(
                row["structured_evidence_required"]
                and not row["structured_evidence"]["current_defect_structurally_observed"]
                for row in rows
            ),
            "runtime_behavior_changed": runtime_behavior_changed,
        },
    }


def _build_prior_scope_matrix(*, runtime_behavior_changed: bool) -> dict[str, Any]:
    rows = [
        {
            **row,
            "old_ok_covers_p7_issue_matrix": False,
            "p7_runtime_behavior_changed": runtime_behavior_changed,
        }
        for row in PRIOR_VALIDATION_SCOPE
    ]
    return {
        "schema_version": PRIOR_SCOPE_SCHEMA_VERSION,
        "rows": rows,
        "summary": {
            "row_count": len(rows),
            "phases": [str(row["phase"]) for row in rows],
            "old_ok_covers_p7_issue_matrix": False,
            "p1_p6_aggregates_run_in_s0": False,
        },
    }


def _probe_summary(probes: dict[str, dict[str, JSONValue]]) -> dict[str, JSONValue]:
    ordered = [probes[probe_id] for probe_id in REQUIRED_PROBE_IDS if probe_id in probes]
    return {
        "probe_ids": [str(probe["probe_id"]) for probe in ordered],
        "required_count": len(REQUIRED_PROBE_IDS),
        "executed_count": sum(probe.get("executed") is True for probe in ordered),
        "current_defect_observed_count": sum(probe.get("current_defect_observed") is True for probe in ordered),
        "current_defect_not_observed_count": sum(probe.get("current_defect_observed") is not True for probe in ordered),
        "observation_missing_count": sum(not isinstance(probe.get("current_observation"), dict) for probe in ordered),
        "target_invariant_missing_count": sum(not isinstance(probe.get("target_invariant"), str) or not probe.get("target_invariant") for probe in ordered),
        "current_wrong_behavior_treated_as_acceptance": False,
    }


def _evidence_row(hsr_root: Path, spec: EvidenceSpec) -> dict[str, JSONValue]:
    path = hsr_root / spec.path
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    matches: list[dict[str, JSONValue]] = []
    missing: list[str] = []
    for token in spec.tokens:
        found = next(((index, line.strip()) for index, line in enumerate(lines, start=1) if token in line), None)
        if found is None:
            missing.append(token)
        else:
            matches.append({"token": token, "line": found[0], "text": found[1]})
    return {
        "path": spec.path,
        "tokens": list(spec.tokens),
        "matches": matches,
        "missing_tokens": missing,
        "missing_token_count": len(missing),
    }


def _minimal_rulebook() -> RuleBook:
    action_ids = ("validation:normal", "validation:foreign", "validation:partial", "validation:ultimate")
    definitions = tuple(
        _action_definition(
            action_id,
            bp_need=1.0 if action_id == "validation:partial" else 0.0,
            attack_type="Ultra" if action_id == "validation:ultimate" else "Normal",
            skill_effect="Ultimate" if action_id == "validation:ultimate" else "ValidationAction",
        )
        for action_id in action_ids
    )
    bindings = tuple(_action_binding(action_id) for action_id in action_ids)
    phases = tuple(_ability_phase(action_id, include_blocked_task=action_id == "validation:partial") for action_id in action_ids)
    events = tuple(_action_event(action_id) for action_id in action_ids)
    tasks = (
        AbilityTaskIR(
            task_id="validation:partial:task:0",
            phase_id="validation:partial:phase",
            action_id="validation:partial",
            level=1,
            ability_name="ValidationPartialAbility",
            callback_kind="OnStart",
            task_index=0,
            task_path="validation/partial/task/0",
            branch="root",
            opcode="UnsupportedValidationOpcode",
            source=_source("partial_task"),
            coverage_status="blocked",
            blocked_reason="validation_selected_task_not_executable",
        ),
    )
    action_set = CombatantActionSetIR(
        combatant_action_set_id="validation:actor_a:actions",
        entity_ref="validation:actor_a",
        skill_index_map={
            "0": {
                "action_ref": "validation:normal",
                "default_level": 1,
                "coverage_status": "executable",
                "source_trace": _source("actor_a_normal_entry").to_json(),
            }
        },
        source=_source("actor_a_action_set"),
        coverage_status="executable",
    )
    ir = CanonicalIR(
        version="validation:p7_s0",
        action_definitions=definitions,
        action_ability_bindings=bindings,
        ability_phases=phases,
        ability_tasks=tasks,
        action_events=events,
        combatant_action_sets=(action_set,),
        timeline_rules=(
            TimelineRuleIR(
                timeline_rule_id="validation:timeline",
                base_action_gauge=10000.0,
                initial_action_value_rule="validation",
                turn_reset_rule="validation",
                source_kind="engine_convention",
                source=_source("timeline"),
            ),
        ),
        resource_rules=(
            ResourceRuleIR(
                resource_rule_id="validation:ultimate_energy_cost",
                rule_kind="ultimate_energy_cost",
                operation="set_to_sp_base_after_execution",
                source_kind="engine_convention",
                source=_source("ultimate_energy_cost"),
            ),
            ResourceRuleIR(
                resource_rule_id="validation:kill_energy_gain",
                rule_kind="kill_energy_gain",
                operation="add_fixed_after_kill",
                source_kind="engine_convention",
                source=_source("kill_energy_gain"),
            ),
        ),
    )
    return RuleBook(ir)


def _action_definition(
    action_id: str,
    *,
    bp_need: float,
    attack_type: str = "Normal",
    skill_effect: str = "ValidationAction",
) -> ActionDefinitionIR:
    return ActionDefinitionIR(
        definition_id=f"{action_id}:definition",
        action_id=action_id,
        level=1,
        attack_type=attack_type,
        skill_effect=skill_effect,
        target_mode="single",
        bp_need=bp_need,
        bp_add=0.0,
        sp_base=0.0,
        sp_multiple_ratio=0.0,
        param_list=(),
        show_stance_list=(),
        show_damage_list=(),
        stance_damage_type=None,
        source=_source(f"{action_id}:definition"),
        coverage_status="executable",
        damage_kind="none",
        damage_formula_family="none",
        source_mode="validation",
    )


def _action_binding(action_id: str) -> ActionAbilityBindingIR:
    return ActionAbilityBindingIR(
        binding_id=f"{action_id}:binding",
        action_id=action_id,
        level=1,
        skill_trigger_key=f"{action_id}:trigger",
        skill_name=f"{action_id}:skill",
        entry_ability=f"{action_id}:ability",
        ability_names=(f"{action_id}:ability",),
        config_source={"validation": True},
        phase_ids=(f"{action_id}:phase",),
        source_mode="validation",
        source=_source(f"{action_id}:binding"),
        coverage_status="executable",
    )


def _ability_phase(action_id: str, *, include_blocked_task: bool) -> AbilityPhaseIR:
    task_ids = ("validation:partial:task:0",) if include_blocked_task else ()
    return AbilityPhaseIR(
        phase_id=f"{action_id}:phase",
        binding_id=f"{action_id}:binding",
        action_id=action_id,
        level=1,
        ability_name=f"{action_id}:ability",
        phase_index=0,
        target_info={},
        opcode_summary={"task_count": len(task_ids)},
        callback_summaries={"OnStart": {"task_count": len(task_ids)}},
        source=_source(f"{action_id}:phase"),
        coverage_status="executable",
        task_ids=task_ids,
    )


def _action_event(action_id: str) -> ActionEventIR:
    source = _source(f"{action_id}:event")
    steps = (
        ActionPhaseStepIR(
            kind="trigger_window",
            phase="before_skill_use",
            canonical_window="before_skill_use",
            tbgd_event="OnBeforeSkillUse",
            coverage_status="lowered",
            source=source,
        ),
        ActionPhaseStepIR(
            kind="trigger_window",
            phase="after_skill_use",
            canonical_window="after_skill_use",
            tbgd_event="OnAfterSkillUse",
            coverage_status="lowered",
            source=source,
        ),
    )
    return ActionEventIR(
        action_event_id=f"{action_id}:event",
        action_id=action_id,
        level=1,
        target_mode="single",
        selection_mode="primary",
        phase_steps=steps,
        hit_profile_ids=(),
        derived_status="validation",
        derived_reason="generic in-memory P7-S0 fixture",
        source=source,
        coverage_status="lowered",
        binding_id=f"{action_id}:binding",
        phase_ids=(f"{action_id}:phase",),
        source_mode="validation",
        event_source_status="ability_phase_graph_bound",
    )


def _base_state(
    *,
    skill_points: int = 3,
    target_hp: float = 100.0,
    target_shield: float = 0.0,
    target_effect_resistance: float = 0.0,
    include_second_enemy: bool = False,
    include_second_ally: bool = False,
    actor_energy: float = 0.0,
    second_ally_energy: float = 0.0,
) -> BattleState:
    units: dict[str, UnitState] = {
        "ally:actor": UnitState(
            unit_id="ally:actor",
            side="ally",
            template_id="validation:actor_a",
            max_hp=100.0,
            hp=100.0,
            attack=100.0,
            defense=100.0,
            speed=100.0,
            energy=actor_energy,
            max_energy=100.0,
            action_value=0.0,
            resources={"critical_chance": 0.5, "critical_damage": 0.5},
        ),
        "enemy:target": UnitState(
            unit_id="enemy:target",
            side="enemy",
            template_id="validation:target",
            max_hp=100.0,
            hp=target_hp,
            attack=50.0,
            defense=0.0,
            speed=90.0,
            action_value=10.0,
            resources={"shield": target_shield, "effect_resistance": target_effect_resistance},
        ),
    }
    if include_second_enemy:
        units["enemy:second"] = UnitState(
            unit_id="enemy:second",
            side="enemy",
            template_id="validation:target_b",
            max_hp=100.0,
            hp=100.0,
            speed=80.0,
            action_value=20.0,
        )
    if include_second_ally:
        units["ally:second"] = UnitState(
            unit_id="ally:second",
            side="ally",
            template_id="validation:actor_b",
            max_hp=100.0,
            hp=100.0,
            speed=95.0,
            energy=second_ally_energy,
            max_energy=100.0,
            action_value=5.0,
        )
    return BattleState(
        units=units,
        skill_points=skill_points,
        max_skill_points=5,
        global_flags={"phase": "scenario", "current_window": "idle"},
        rng_state="validation-seed",
        event_index=0,
    )


def _decision_state(state: BattleState) -> BattleState:
    return replace(
        state,
        global_flags={
            **state.global_flags,
            "turn_owner_id": "ally:actor",
            "current_window": "turn_active",
            "active_turn": {"actor_id": "ally:actor", "turn_kind": "regular", "turn_sequence_index": 1},
            "turn_sequence_index": 1,
        },
    )


def _source(raw_id: str) -> IRSource:
    return IRSource(
        source_path="simulator_v8_clean_core.tools.validate_p7_s0_kernel_trust_baseline",
        raw_type="ValidationSynthetic",
        raw_id=raw_id,
        evidence={"validation": VALIDATION_VERSION, "negative_or_baseline_fixture": True},
    )


def _queue_entry_id(entries: tuple[JSONValue, ...], index: int) -> str:
    if index >= len(entries) or not isinstance(entries[index], dict):
        return ""
    return str(entries[index].get("entry_id") or "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the P7-S0 kernel trust issue baseline without changing runtime behavior.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/tmp/hsr_v8_p7_s0_kernel_trust_baseline"),
    )
    args = parser.parse_args(argv)
    package_root = Path(__file__).resolve().parents[1]
    result = run_validation(package_root, args.output_dir.resolve())
    print(
        "v8 p7_s0_kernel_trust_baseline "
        f"ok={result['ok']} "
        f"issues={result['issue_summary']['issue_row_count']} "
        f"probes={result['probe_summary']['executed_count']}/{result['probe_summary']['required_count']} "
        f"observed={result['probe_summary']['current_defect_observed_count']} "
        f"p7_all_fixed={result['p7_all_fixed']}"
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
