from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Literal, cast

from ..unit_eligibility import runtime_regarded_attack_type
from ..core.model import ActionCommand, BattleState, GameEvent, JSONValue, Mutation, RNGEvent, TargetResolution
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord
from ..core.transition_outcome import ExecutionNodeResult
from ..rules.evaluator import NumericEvaluationContext, RuleEvaluator
from ..rules.ir import AbilityPhaseIR, AbilityTaskIR, ActionDefinitionIR, IRSource
from ..rules.rulebook import RuleBook
from ..rules.task_graph import TaskGraphIR, TaskGraphNodeIR, TaskGraphNumericDefinitionIR, TaskGraphWeightedSelectionIR
from .damage import DamageModifierContribution, DamagePacket, DamageSourceFrame, DamageSystem, DamageWindowLedger
from .break_system import BreakSystem
from .mutation_events import before_toughness_calculation_event
from .dynamic_values import (
    binding_source_from_store,
    character_skill_param_binding_sources,
    ability_declared_dynamic_binding_source,
    character_declared_dynamic_binding_source,
    servant_declared_dynamic_binding_source,
    monster_skill_param_binding_sources,
    monster_standalone_skill_param_binding_sources,
    store_from_state,
)
from .effect import EffectExecutionContext, EffectRegistry
from .elation import resolve_elation_damage_context
from .event_dispatch import EventDispatchResult, EventDispatchSystem
from .action_event_contract import (
    AdmittedActionTargetFact,
    ActionWindowExpectedScope,
    admitted_action_condition_fact_provider,
    damage_listener_window_event,
    parallel_action_target_fact,
    parallel_attack_window_event,
    _issue_action_window_expected_scope,
)
from .summon import SummonSystem
from .toughness import ToughnessPacket, ToughnessSystem
from .ability_task_contract import (
    ability_task_runtime_blocked_reason,
    emission_backed_damage_audit_reference_admitted,
    is_process_only_ability_task,
)
from .target import TargetSystem
from .task_graph import (
    TaskGraphBranchResult,
    TaskGraphConditionResult,
    TaskGraphContinuation,
    TaskGraphCountResult,
    TaskGraphExecutionContext,
    TaskGraphExecutionHooks,
    TaskGraphExecutor,
    TaskGraphGraphResult,
    TaskGraphHookRequest,
    TaskGraphLeafResult,
    TaskGraphNodeProjection,
    TaskGraphSettlementRecord,
    TaskGraphTargetResult,
    TaskGraphStatusScope,
    TaskGraphWeightedSelectionResult,
    TaskGraphTemplateBindingsResult,
    evaluate_task_graph_template_bindings,
    with_template_binding_sources,
    resolve_task_graph_weighted_selection,
)
from .unit_lifecycle import UnitLifecycleSystem
from .unit_relation import (
    TargetEvaluationContext,
    committed_turn_owner_id,
    is_same_combat_team,
)


_STANDALONE_CALLBACK_ORDER = ("OnStart", "OnAttack", "OnHit", "OnEnd")


@dataclass(frozen=True)
class AbilityTaskExecutionResult:
    after_state: BattleState
    mutations: tuple[Mutation, ...] = ()
    events: tuple[GameEvent, ...] = ()
    rng_events: tuple[RNGEvent, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    task_records: tuple[dict[str, JSONValue], ...] = ()
    node_results: tuple[ExecutionNodeResult, ...] = ()
    dispatched_event_ids: frozenset[str] | None = None
    hit_target_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CharacterStartupInvocation:
    actor_id: str
    action_id: str
    action_level: int
    binding_id: str

    def __post_init__(self) -> None:
        if type(self) is not CharacterStartupInvocation:
            raise TypeError("character startup invocation must not be subclassed")
        if any(type(value) is not str or not value for value in (
            self.actor_id, self.action_id, self.binding_id,
        )) or type(self.action_level) is not int or self.action_level <= 0:
            raise ValueError("character startup invocation identity is incomplete")


@dataclass(frozen=True)
class CharacterTechniqueInvocation:
    actor_id: str
    action_id: str
    action_level: int
    binding_id: str

    def __post_init__(self) -> None:
        if type(self) is not CharacterTechniqueInvocation:
            raise TypeError("character technique invocation must not be subclassed")
        if any(type(value) is not str or not value for value in (
            self.actor_id, self.action_id, self.binding_id,
        )) or type(self.action_level) is not int or self.action_level <= 0:
            raise ValueError("character technique invocation identity is incomplete")


@dataclass(frozen=True)
class CharacterBuildStartupInvocation:
    actor_id: str
    graph_id: str
    binding_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not CharacterBuildStartupInvocation:
            raise TypeError("character build startup invocation must not be subclassed")
        bindings = tuple(self.binding_ids)
        if (not bindings or len(set(bindings)) != len(bindings)
                or any(type(value) is not str or not value
                       for value in (self.actor_id, self.graph_id, *bindings))):
            raise ValueError("character build startup invocation identity is incomplete")
        object.__setattr__(self, "binding_ids", bindings)


@dataclass(frozen=True)
class StandaloneAbilityInvocation:
    graph_id: str
    actor_id: str
    target_ids: tuple[str, ...]
    queue_name: str
    queue_entry_id: str
    queue_intent_id: str
    queue_resolution_id: str
    # Formal final-death identity of one admitted Deathrattle queue entry. Only
    # the queue admission producer may populate it; a generic event payload or
    # audit trace is not a substitute.
    death_instance_id: str = ""

    def __post_init__(self) -> None:
        if type(self) is not StandaloneAbilityInvocation:
            raise TypeError("standalone ability invocation must not be subclassed")
        values = (
            self.graph_id,
            self.actor_id,
            self.queue_name,
            self.queue_entry_id,
            self.queue_intent_id,
            self.queue_resolution_id,
        )
        if any(type(value) is not str or not value for value in values):
            raise ValueError("standalone ability invocation identity is incomplete")
        if type(self.death_instance_id) is not str:
            raise ValueError("standalone ability death instance is invalid")
        targets = tuple(self.target_ids)
        if any(type(value) is not str or not value for value in targets):
            raise ValueError("standalone ability invocation targets are invalid")
        if len(targets) != len(set(targets)):
            raise ValueError("standalone ability invocation targets are duplicated")
        object.__setattr__(self, "target_ids", targets)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "graph_id": self.graph_id,
            "actor_id": self.actor_id,
            "target_ids": list(self.target_ids),
            "queue_name": self.queue_name,
            "queue_entry_id": self.queue_entry_id,
            "queue_intent_id": self.queue_intent_id,
            "queue_resolution_id": self.queue_resolution_id,
            "death_instance_id": self.death_instance_id,
        }


@dataclass(frozen=True)
class StatusNestedAbilityContext:
    callback_id: str
    modifier_name: str
    status_instance_id: str
    owner_id: str
    root_graph_id: str
    trigger_event_id: str
    target_resolution: TargetResolution
    admitted_action_target_fact: AdmittedActionTargetFact | None = None
    expected_action_window_scope: ActionWindowExpectedScope | None = None

    def __post_init__(self) -> None:
        if type(self) is not StatusNestedAbilityContext:
            raise TypeError("status nested ability context must not be subclassed")
        for value in (
            self.callback_id,
            self.modifier_name,
            self.status_instance_id,
            self.owner_id,
            self.root_graph_id,
            self.trigger_event_id,
        ):
            if type(value) is not str or not value:
                raise ValueError("status nested ability context identity is incomplete")
        if type(self.target_resolution) is not TargetResolution:
            raise TypeError("status nested ability target resolution type is invalid")
        if bool(self.admitted_action_target_fact) != bool(
            self.expected_action_window_scope
        ):
            raise ValueError("status nested ability target capability is incomplete")
        if self.admitted_action_target_fact is not None:
            if type(self.admitted_action_target_fact) is not AdmittedActionTargetFact:
                raise TypeError("status nested ability target fact type is invalid")
            if type(self.expected_action_window_scope) is not ActionWindowExpectedScope:
                raise TypeError("status nested ability window scope type is invalid")


@dataclass(frozen=True, init=False)
class StatusNestedAbilityHookProvider:
    _factory: Callable[[StatusNestedAbilityContext], TaskGraphExecutionHooks]

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("status nested ability hook provider is AbilityTaskSystem-owned")

    @classmethod
    def _from_ability_task_system(
        cls,
        factory: Callable[[StatusNestedAbilityContext], TaskGraphExecutionHooks],
    ) -> "StatusNestedAbilityHookProvider":
        if cls is not StatusNestedAbilityHookProvider or not callable(factory):
            raise TypeError("status nested ability provider factory is invalid")
        value = object.__new__(cls)
        object.__setattr__(value, "_factory", factory)
        return value

    def hooks_for(self, context: StatusNestedAbilityContext) -> TaskGraphExecutionHooks:
        if type(self) is not StatusNestedAbilityHookProvider:
            raise TypeError("status nested ability provider type is invalid")
        if type(context) is not StatusNestedAbilityContext:
            raise TypeError("status nested ability context type is invalid")
        hooks = self._factory(context)
        if type(hooks) is not TaskGraphExecutionHooks:
            raise TypeError("status nested ability provider returned invalid hooks")
        return hooks


@dataclass(frozen=True)
class _FormalAbilityInvocation:
    invocation_kind: Literal["action", "queue_standalone", "status_nested", "character_startup", "character_build_startup", "servant_startup", "battle_event_startup", "stage_startup"]
    actor_id: str
    ability_id: str
    ability_level: int
    target_resolution: TargetResolution
    action_command: ActionCommand | None = None
    action_definition: ActionDefinitionIR | None = None
    standalone: StandaloneAbilityInvocation | None = None
    execution_path: str = ""
    iteration_index: int | None = None
    admitted_action_target_fact: AdmittedActionTargetFact | None = None
    expected_action_window_scope: ActionWindowExpectedScope | None = None
    dispatched_event_ids: set[str] = field(default_factory=set, compare=False, repr=False)
    action_damage_modifiers: tuple[DamageModifierContribution, ...] = ()
    parallel_execution: bool = False
    action_execution_token: object | None = field(default=None, compare=False, repr=False)
    accepted_action_target_fact: AdmittedActionTargetFact | None = None
    hit_target_ids: list[str] = field(default_factory=list, compare=False, repr=False)
    param_status_scope: TaskGraphStatusScope | None = None
    template_target_ids: tuple[str, ...] | None = None
    template_binding_sources: tuple[Mapping[str, JSONValue], ...] = ()
    trigger_event: GameEvent | None = field(default=None, compare=False, repr=False)
    damage_window_ledger: DamageWindowLedger = field(default_factory=DamageWindowLedger, compare=False, repr=False)
    # Assigned on first use so every task of one invocation shares one
    # execution identity even while nested events advance the state index.
    stable_ability_instance_id: str = field(default="", compare=False, repr=False)

    def __post_init__(self) -> None:
        if type(self) is not _FormalAbilityInvocation:
            raise TypeError("formal ability invocation must not be subclassed")
        if (
            type(self.actor_id) is not str
            or not self.actor_id
            or type(self.ability_id) is not str
            or not self.ability_id
            or type(self.ability_level) is not int
            or self.ability_level < 0
            or type(self.target_resolution) is not TargetResolution
        ):
            raise ValueError("formal ability invocation identity is invalid")
        if self.invocation_kind == "action":
            if (
                type(self.action_command) is not ActionCommand
                or type(self.action_definition) is not ActionDefinitionIR
                or self.standalone is not None
                or self.action_command.actor_id != self.actor_id
                or self.action_command.action_id != self.ability_id
                or self.action_command.action_level != self.ability_level
                or self.action_definition.action_id != self.ability_id
                or self.action_definition.level != self.ability_level
            ):
                raise ValueError("formal action invocation is inconsistent")
        elif self.invocation_kind in {"character_startup", "servant_startup"} and self.action_definition is not None:
            if (
                self.action_command is not None
                or self.standalone is not None
                or type(self.action_definition) is not ActionDefinitionIR
                or self.action_definition.action_id != self.ability_id
                or self.action_definition.level != self.ability_level
            ):
                raise ValueError("formal character startup invocation is inconsistent")
        elif self.invocation_kind == "queue_standalone":
            if (
                type(self.standalone) is not StandaloneAbilityInvocation
                or self.standalone.actor_id != self.actor_id
            ):
                raise ValueError("formal standalone invocation is inconsistent")
            if self.action_command is not None or self.action_definition is not None:
                if (type(self.action_command) is not ActionCommand
                        or type(self.action_definition) is not ActionDefinitionIR
                        or self.action_command.actor_id != self.actor_id
                        or self.action_command.action_id != self.action_definition.action_id
                        or self.action_command.action_level != self.action_definition.level
                        or self.action_definition.level != self.ability_level
                        or self.action_definition.source_mode != "queue_standalone"
                        or self.action_command.target_ids != self.standalone.target_ids):
                    raise ValueError("formal queued action binding is inconsistent")
        elif self.invocation_kind in {"status_nested", "character_build_startup", "servant_startup", "battle_event_startup", "stage_startup"}:
            if (
                self.action_command is not None
                or self.action_definition is not None
                or self.standalone is not None
            ):
                raise ValueError(f"formal {self.invocation_kind} invocation is inconsistent")
        else:
            raise ValueError("formal ability invocation kind is invalid")
        if bool(self.admitted_action_target_fact) != bool(
            self.expected_action_window_scope
        ):
            raise ValueError("formal ability target capability is incomplete")
        if self.admitted_action_target_fact is not None:
            if type(self.admitted_action_target_fact) is not AdmittedActionTargetFact:
                raise TypeError("formal ability target fact type is invalid")
            if type(self.expected_action_window_scope) is not ActionWindowExpectedScope:
                raise TypeError("formal ability window scope type is invalid")


def _external_legacy_trigger_is_process_only(
    rules: RuleBook,
    task: AbilityTaskIR,
) -> bool:
    """Prove that a TriggerAbility only replays admitted non-gameplay tasks.

    A missing reference, an unknown or blocked task, and an executable task are
    not presentation proof.  Only tasks that the source compiler explicitly
    marked process-only *and* whose strict lowerer-admitted source-shape
    contract still holds can be skipped.  The linked graph is the single
    source-declared reference; an executable nested trigger stays gameplay
    authority even when its own target happens to be visual.
    """
    phases: list[AbilityPhaseIR | None] = []
    if task.linked_standalone_graph_id:
        graph = rules.standalone_ability_graph(task.linked_standalone_graph_id)
        if graph is not None:
            phases = [rules.ability_phase(phase_id) for phase_id in graph.phase_ids]
    elif task.linked_ability_phase_id:
        phases = [rules.ability_phase(task.linked_ability_phase_id)]
    if not phases or any(phase is None for phase in phases):
        return False
    linked_tasks = [
        item
        for phase in phases
        if phase is not None
        for item in rules.ability_tasks_for_phase(phase.phase_id)
    ]
    if not linked_tasks:
        return False
    return all(
        is_process_only_ability_task(item)
        and not ability_task_runtime_blocked_reason(
            rules,
            item,
            topology_authority="external_legacy",
        )
        for item in linked_tasks
    )


class AbilityTaskSystem:
    """Executes Canonical IR ability tasks conservatively."""

    def __init__(
        self,
        rules: RuleBook,
        effect_registry: EffectRegistry,
        evaluator: RuleEvaluator | None = None,
        reducer: MutationReducer | None = None,
        damage: DamageSystem | None = None,
        event_dispatcher: EventDispatchSystem | None = None,
    ) -> None:
        self.rules = rules
        self.effect_registry = effect_registry
        self.evaluator = evaluator or RuleEvaluator()
        self.reducer = reducer or MutationReducer()
        self.damage = damage or DamageSystem(rules)
        self.event_dispatcher = event_dispatcher
        self.toughness = ToughnessSystem(rules)
        self.breaks = BreakSystem(
            rules, effect_registry, reducer=self.reducer, damage=self.damage,
            event_dispatcher=event_dispatcher,
        )
        self.summons = SummonSystem(rules)
        self.targets = TargetSystem(rules)
        self.task_graph_executor = TaskGraphExecutor()

    def formal_status_nested_ability_provider(self) -> StatusNestedAbilityHookProvider:
        return StatusNestedAbilityHookProvider._from_ability_task_system(
            self._formal_status_nested_hooks
        )

    def execute_character_startup(
        self, state: BattleState, *, invocation: CharacterStartupInvocation,
    ) -> AbilityTaskExecutionResult:
        """Execute a source-bound passive entry without granting action-window facts."""
        if type(invocation) is not CharacterStartupInvocation:
            raise TypeError("character startup requires typed invocation")
        definition = self.rules.action_definition(invocation.action_id, invocation.action_level)
        command = ActionCommand(invocation.actor_id, invocation.action_id, invocation.action_level)
        def blocked(reason: str) -> AbilityTaskExecutionResult:
            return self._formal_action_input_blocked(state, "OnStart", command, reason)
        unit = state.units.get(invocation.actor_id)
        binding = self.rules.action_ability_binding(invocation.action_id, invocation.action_level)
        if unit is None or definition is None or binding is None:
            return blocked("character_startup_owner_or_binding_missing")
        card = self.rules.character_data_card(str(unit.flags.get("character_data_card_id") or ""))
        levels = unit.flags.get("effective_skill_levels_by_action_id")
        if (
            unit.flags.get("build_mode") != "assembled_character_build"
            or unit.flags.get("character_build_battle_admission_status") != "admitted"
            or card is None or card.entity_ref != unit.template_id
            or not isinstance(levels, dict)
            or levels.get(invocation.action_id) != invocation.action_level
            or invocation.action_id.removeprefix("avatar_skill:") not in card.skill_ids
            or binding.binding_id != invocation.binding_id
            or binding.coverage_status != "executable" or binding.blocked_reason
            or definition.coverage_status != "executable"
            or binding.config_source.get("use_type") != "Passive"
        ):
            return blocked("character_startup_binding_not_admitted")
        phases = self.rules.ability_phases_for_binding(binding.binding_id)
        roots = tuple(phase for phase in phases
                      if phase.invocation_role == "action_root"
                      and phase.ability_name == binding.entry_ability)
        if (
            len(roots) != 1
            or any(phase.action_id != invocation.action_id or phase.level != invocation.action_level for phase in phases)
            or any(task.callback_kind != "OnStart" for phase in roots for task in self.rules.ability_tasks_for_phase(phase.phase_id))
        ):
            return blocked("character_startup_phase_lifecycle_not_admitted")
        targets = TargetResolution(
            requested=(unit.unit_id,), legal=(unit.unit_id,), selected=(unit.unit_id,),
            rejected=(), reason="source_bound_passive_startup", source="character_startup",
        )
        formal = _FormalAbilityInvocation(
            "character_startup", unit.unit_id, invocation.action_id,
            invocation.action_level, targets, action_definition=definition,
        )
        return self._execute_formal_entries(
            state, entries=tuple((phase, "OnStart") for phase in roots), invocation=formal,
        )

    def execute_character_technique(
        self, state: BattleState, *, invocation: CharacterTechniqueInvocation,
    ) -> AbilityTaskExecutionResult:
        """Apply a selected technique's sourced entry graph before OnEnterBattle."""
        if type(invocation) is not CharacterTechniqueInvocation:
            raise TypeError("character technique requires typed invocation")
        command = ActionCommand(invocation.actor_id, invocation.action_id, invocation.action_level)
        def blocked(reason: str) -> AbilityTaskExecutionResult:
            return self._formal_action_input_blocked(state, "OnStart", command, reason)
        unit = state.units.get(invocation.actor_id)
        definition = self.rules.action_definition(invocation.action_id, invocation.action_level)
        binding = self.rules.action_ability_binding(invocation.action_id, invocation.action_level)
        card = self.rules.character_data_card(str(unit.flags.get("character_data_card_id") or "")) if unit else None
        levels = unit.flags.get("effective_skill_levels_by_action_id") if unit else None
        if (unit is None or unit.hp <= 0 or unit.side != "ally"
                or unit.flags.get("build_mode") != "assembled_character_build"
                or unit.flags.get("character_build_battle_admission_status") != "admitted"
                or card is None or card.entity_ref != unit.template_id
                or invocation.action_id.removeprefix("avatar_skill:") not in card.skill_ids
                or not isinstance(levels, dict) or levels.get(invocation.action_id) != invocation.action_level
                or definition is None or definition.attack_type != "Maze"
                or definition.coverage_status != "executable"
                or binding is None or binding.binding_id != invocation.binding_id
                or binding.coverage_status != "executable" or binding.blocked_reason):
            return blocked("character_technique_binding_not_admitted")
        phases = self.rules.ability_phases_for_binding(binding.binding_id)
        roots = tuple(phase for phase in phases if phase.invocation_role == "action_root"
                      and phase.ability_name == binding.entry_ability)
        # ponytail: ordinary entry effects only. Attack techniques need their
        # own admitted pre-combat hit window rather than simulated action facts.
        if (len(roots) != 1
                or any(phase.action_id != invocation.action_id or phase.level != invocation.action_level for phase in phases)
                or any(task.callback_kind != "OnStart" or self.rules.damage_emissions_for_task(task.task_id)
                       for phase in phases for task in self.rules.ability_tasks_for_phase(phase.phase_id))):
            return blocked("character_technique_entry_lifecycle_not_admitted")
        targets = TargetResolution(
            requested=(unit.unit_id,), legal=(unit.unit_id,), selected=(unit.unit_id,),
            rejected=(), reason="source_bound_technique_entry", source="character_technique",
        )
        formal = _FormalAbilityInvocation(
            "character_startup", unit.unit_id, invocation.action_id,
            invocation.action_level, targets, action_definition=definition,
        )
        return self._execute_formal_entries(
            state, entries=tuple((phase, "OnStart") for phase in roots), invocation=formal,
        )

    def execute_battle_event_startup(
        self, state: BattleState, *, actor_id: str, phase_ids: tuple[str, ...],
    ) -> AbilityTaskExecutionResult:
        targets = TargetResolution(requested=(actor_id,), legal=(actor_id,), selected=(actor_id,), rejected=(),
                                   reason="battle_event_startup", source="ability_task_system")
        invocation = _FormalAbilityInvocation("battle_event_startup", actor_id, state.units[actor_id].template_id, 0, targets)
        phases = tuple(self.rules.ability_phase(phase_id) for phase_id in phase_ids)
        if not phases or any(
            phase is None
            or phase.invocation_role not in {"build_startup", "non_gameplay_noop"}
            for phase in phases
        ):
            return self._formal_callback_blocked(state, "OnAdd", invocation, "battle_event_startup_phase_not_admitted")
        # A creation start-up ability that lowers to process-only tasks has no
        # gameplay body; its phase is non_gameplay_noop and executes no entry.
        # An admitted phase without OnAdd tasks contributes nothing to creation.
        gameplay_phases = tuple(
            phase
            for phase in phases
            if phase.invocation_role == "build_startup"
            and any(
                task.callback_kind == "OnAdd"
                for task in self.rules.ability_tasks_for_phase(phase.phase_id)
            )
        )
        return self._execute_formal_entries(
            state,
            entries=tuple((phase, "OnAdd") for phase in gameplay_phases),
            invocation=invocation,
        )

    def execute_stage_startup(
        self, state: BattleState, *, actor_id: str, wave_definition_id: str,
    ) -> AbilityTaskExecutionResult:
        targets = TargetResolution(requested=(actor_id,), legal=(actor_id,), selected=(actor_id,), rejected=(),
                                   reason="source_bound_stage_startup", source="ability_task_system")
        invocation = _FormalAbilityInvocation("stage_startup", actor_id, wave_definition_id, 0, targets)
        def blocked(reason: str) -> AbilityTaskExecutionResult:
            return self._formal_callback_blocked(state, "OnAdd", invocation, reason)
        unit = state.units.get(actor_id)
        definition = self.rules.wave_definition(wave_definition_id)
        runtime = state.global_flags.get("wave_runtime")
        if (unit is None or unit.flags.get("system_entity_kind") != "level"
                or definition is None or definition.coverage_status != "executable"
                or definition.stage_environment_status != "executable"
                or not isinstance(runtime, dict)
                or runtime.get("wave_definition_id") != wave_definition_id
                or runtime.get("stage_id") != definition.stage_id):
            return blocked("stage_startup_binding_not_admitted")
        phases = tuple(self.rules.ability_phase(phase_id) for phase_id in definition.stage_startup_phase_ids)
        if any(phase is None or phase.invocation_role != "build_startup"
               or phase.coverage_status != "executable" or phase.blocked_reason
               or phase.ability_name not in definition.stage_ability_refs for phase in phases):
            return blocked("stage_startup_phase_not_admitted")
        return self._execute_formal_entries(state, entries=tuple((phase, "OnAdd") for phase in phases), invocation=invocation)

    def execute_servant_startup(
        self, state: BattleState, *, actor_id: str, ability_name: str,
    ) -> AbilityTaskExecutionResult:
        """Run a configured owned-unit passive through the same formal task graph."""
        from .summon import _formal_owned_combatant_build

        targets = TargetResolution(requested=(actor_id,), legal=(actor_id,), selected=(actor_id,),
                                   rejected=(), reason="source_bound_servant_startup", source="servant_startup")
        formal = _FormalAbilityInvocation("servant_startup", actor_id, ability_name, 0, targets)
        def blocked(reason: str) -> AbilityTaskExecutionResult:
            return self._formal_callback_blocked(state, "OnStart", formal, reason)
        unit = state.units.get(actor_id)
        definition = self.rules.servant_definition(str(unit.flags.get("servant_definition_id") or "")) if unit else None
        owner = state.units.get(str(unit.flags.get("owner_id") or "")) if unit else None
        if (definition is None or owner is None or definition.servant_ref != unit.template_id
                or definition.coverage_status != "executable"
                or ability_name not in definition.action_set.get("startup_abilities", ())):
            return blocked("servant_startup_definition_not_admitted")
        build, reason = _formal_owned_combatant_build(owner, definition)
        if reason or build is None or unit.flags.get("owned_combatant_build_result") != build.to_json():
            return blocked(reason or "servant_startup_owned_build_missing_or_mismatched")
        slots = tuple(entry for entry in definition.action_set.get("skill_index_map", {}).values()
                      if entry.get("role_source", {}).get("entry_ability") == ability_name)
        if slots:
            if len(slots) != 1 or slots[0].get("servant_action_role") not in {"passive", "lifecycle"}:
                return blocked("servant_startup_slot_not_unique_or_passive")
            levels = tuple(item for item in build.effective_skill_levels if item.action_id == slots[0].get("action_ref"))
            if len(levels) != 1:
                return blocked("servant_startup_skill_level_missing")
            level = levels[0]
            binding = self.rules.action_ability_binding(level.action_id, level.effective_level)
            action = self.rules.action_definition(level.action_id, level.effective_level)
            if (binding is None or action is None or binding.entry_ability != ability_name
                    or binding.coverage_status != "executable" or binding.blocked_reason
                    or action.coverage_status != "executable"):
                return blocked("servant_startup_action_binding_not_admitted")
            phases = tuple(phase for phase in self.rules.ability_phases_for_binding(binding.binding_id)
                           if phase.ability_name == ability_name)
            if len(phases) != 1:
                return blocked("servant_startup_entry_phase_not_unique")
            formal = replace(formal, ability_id=level.action_id, ability_level=level.effective_level, action_definition=action)
        else:
            # A start-up passive can own an ability that also exists as a mainline
            # action phase (the joint owner/servant sequence). Prefer that phase:
            # it carries the skill formula bindings and the action-scale context,
            # while the standalone duplicate only mirrors the task tree.
            mainline_phases = tuple(
                phase
                for phase in self.rules.ir.ability_phases
                if phase.ability_name == ability_name
                and phase.action_id.startswith("avatar_skill:")
                and phase.coverage_status in {"executable", "lowered"}
                and not phase.blocked_reason
            )
            mainline_action_ids = {phase.action_id for phase in mainline_phases}
            mainline_action = None
            if len(mainline_action_ids) == 1 and owner is not None:
                mainline_action_id = next(iter(mainline_action_ids))
                levels = owner.flags.get("effective_skill_levels_by_action_id")
                level = levels.get(mainline_action_id) if isinstance(levels, dict) else None
                if type(level) is int and level > 0:
                    action = self.rules.action_definition(mainline_action_id, level)
                    selected = tuple(
                        phase for phase in mainline_phases if phase.level == level
                    )
                    if action is not None and action.coverage_status == "executable" and selected:
                        phases = selected
                        formal = replace(
                            formal,
                            ability_id=mainline_action_id,
                            ability_level=level,
                            action_definition=action,
                        )
                        mainline_action = action
            if mainline_action is None:
                graphs = tuple(
                    graph
                    for graph in self.rules.standalone_ability_graphs_by_name(ability_name)
                    if graph.coverage_status == "executable"
                    or (
                        graph.coverage_status == "blocked"
                        and graph.blocked_reason == "standalone_ability_has_no_tasks"
                    )
                )
                if len(graphs) != 1:
                    return blocked("servant_startup_common_graph_missing_or_ambiguous:" + ability_name)
                phases = tuple(self.rules.ability_phase(phase_id) for phase_id in graphs[0].phase_ids)
        if not phases or any(phase is None for phase in phases):
            return blocked("servant_startup_phase_missing")
        # A declared start-up passive whose body lowers to process-only tasks has
        # no gameplay entries; its phase is non_gameplay_noop and stays empty.
        gameplay_phases = tuple(
            phase for phase in phases if phase.invocation_role != "non_gameplay_noop"
        )
        if any(
            phase.invocation_role
            not in {
                "action_root",
                "nested_only",
                "standalone_root",
                "build_startup",
                "unbound_definition",
            }
            for phase in gameplay_phases
        ):
            return blocked("servant_startup_phase_invocation_role_not_admitted")
        if any(
            task.callback_kind != "OnStart"
            for phase in gameplay_phases
            for task in self.rules.ability_tasks_for_phase(phase.phase_id)
        ):
            return blocked("servant_startup_phase_lifecycle_not_admitted")
        if not gameplay_phases:
            # 全部为已证明表现任务的被动：显式完成且不产生任何状态变化。
            return AbilityTaskExecutionResult(
                after_state=state,
                records=(SettlementRecord(
                    record_type="servant_startup_non_gameplay_noop", source="ability_task_system",
                    process_only=True,
                    payload={"actor_id": actor_id, "ability_name": ability_name,
                             "phase_ids": [phase.phase_id for phase in phases]},
                    trace={"phase_sources": [phase.source.to_json() for phase in phases]},
                ).to_json(),),
                node_results=(ExecutionNodeResult(
                    node_kind="ability_task_graph_callback",
                    node_id=f"ability_task_graph_callback:{state.event_index}:{actor_id}:{ability_name}:OnStart",
                    status="complete",
                    reason_code="servant_startup_non_gameplay_noop",
                ),),
            )
        return self._execute_formal_entries(
            state,
            entries=tuple((phase, "OnStart") for phase in gameplay_phases),
            invocation=formal,
        )

    def execute_character_build_startup(
        self, state: BattleState, *, invocation: CharacterBuildStartupInvocation,
    ) -> AbilityTaskExecutionResult:
        if type(invocation) is not CharacterBuildStartupInvocation:
            raise TypeError("character build startup requires typed invocation")
        actor_id = invocation.actor_id
        targets = TargetResolution(
            requested=(actor_id,), legal=(actor_id,), selected=(actor_id,), rejected=(),
            reason="source_bound_build_startup", source="character_startup",
        )
        formal = _FormalAbilityInvocation("character_build_startup", actor_id, invocation.graph_id, 0, targets)
        def blocked(reason: str) -> AbilityTaskExecutionResult:
            return self._formal_callback_blocked(state, "OnStart", formal, reason)
        unit = state.units.get(actor_id)
        if unit is None:
            return blocked("character_build_startup_owner_missing")
        card = self.rules.character_data_card(str(unit.flags.get("character_data_card_id") or ""))
        if (unit.flags.get("build_mode") != "assembled_character_build"
                or unit.flags.get("character_build_battle_admission_status") != "admitted"
                or card is None or card.entity_ref != unit.template_id):
            return blocked("character_build_startup_owner_not_admitted")
        graph, reason = self.rules.character_build_startup_graph(invocation.binding_ids)
        if graph is None:
            return blocked(reason)
        if graph.standalone_ability_graph_id != invocation.graph_id:
            return blocked("character_build_startup_graph_identity_mismatch")
        for binding_id in invocation.binding_ids:
            binding = self.rules.character_build_binding(binding_id)
            assert binding is not None
            selection_key = {"trace": "selected_trace_node_ids", "eidolon": "selected_eidolon_slot_ids"}.get(binding.selection_kind)
            if (binding.character_data_card_id != card.card_id
                    or selection_key is None
                    or binding.selection_ref_id not in unit.flags.get(selection_key, ())):
                return blocked("character_build_startup_selection_not_admitted")
        phases = tuple(self.rules.ability_phase(phase_id) for phase_id in graph.phase_ids)
        return self._execute_formal_entries(
            state, entries=tuple((phase, "OnStart") for phase in phases), invocation=formal,
        )

    def execute_callback(
        self,
        state: BattleState,
        *,
        phases: tuple[AbilityPhaseIR, ...],
        callback_kind: str,
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        target_resolution: TargetResolution,
        action_damage_modifiers: tuple[DamageModifierContribution, ...] = (),
        admitted_action_target_fact: AdmittedActionTargetFact | None = None,
        action_execution_token: object | None = None,
    ) -> AbilityTaskExecutionResult:
        # The same formal roles as admission; audit source paths have no say.
        roles = {phase.invocation_role for phase in phases}
        formal_roles = {"action_root", "nested_only"}
        formal_invocation = None
        if roles.intersection(
            {*formal_roles, "standalone_root", "build_startup", "unbound_definition"}
        ):
            if (
                command.action_id != action_definition.action_id
                or command.action_level != action_definition.level
            ):
                return self._formal_action_input_blocked(
                    state,
                    callback_kind,
                    command,
                    "ability_action_definition_identity_mismatch",
                )
            formal_invocation = _FormalAbilityInvocation(
                "action",
                command.actor_id,
                command.action_id,
                command.action_level,
                target_resolution,
                action_command=command,
                action_definition=action_definition,
                action_damage_modifiers=action_damage_modifiers,
                accepted_action_target_fact=admitted_action_target_fact,
                action_execution_token=action_execution_token,
            )
        if "action_root" in roles:
            invalid_roles = roles - formal_roles - {"non_gameplay_noop"}
            if invalid_roles:
                return self._formal_callback_blocked(
                    state,
                    callback_kind,
                    cast(_FormalAbilityInvocation, formal_invocation),
                    f"ability_action_invocation_roles_mixed:{','.join(sorted(invalid_roles))}",
                )
            return self._execute_formal_action_callback(
                state,
                phases=phases,
                callback_kind=callback_kind,
                command=command,
                action_definition=action_definition,
                target_resolution=target_resolution,
                action_damage_modifiers=action_damage_modifiers,
                admitted_action_target_fact=admitted_action_target_fact,
                action_execution_token=action_execution_token,
            )
        if "build_startup" in roles:
            return self._formal_callback_blocked(
                state, callback_kind, cast(_FormalAbilityInvocation, formal_invocation),
                "character_build_ability_requires_startup_invocation",
            )
        if "standalone_root" in roles:
            return self._formal_callback_blocked(
                state,
                callback_kind,
                cast(_FormalAbilityInvocation, formal_invocation),
                "standalone_ability_requires_admitted_queue_invocation",
            )
        if "nested_only" in roles and not roles.intersection(
            {"standalone_root", "external_legacy"}
        ):
            return self._formal_callback_blocked(
                state,
                callback_kind,
                cast(_FormalAbilityInvocation, formal_invocation),
                "nested_ability_phase_cannot_be_invoked_as_root",
            )
        if "unbound_definition" in roles:
            return self._formal_callback_blocked(
                state,
                callback_kind,
                cast(_FormalAbilityInvocation, formal_invocation),
                "unbound_ability_definition_cannot_be_invoked",
            )
        return self._execute_legacy_callback(
            state,
            phases=phases,
            callback_kind=callback_kind,
            command=command,
            action_definition=action_definition,
            target_resolution=target_resolution,
            action_damage_modifiers=action_damage_modifiers,
        )

    def _execute_legacy_callback(
        self,
        state: BattleState,
        *,
        phases: tuple[AbilityPhaseIR, ...],
        callback_kind: str,
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        target_resolution: TargetResolution,
        action_damage_modifiers: tuple[DamageModifierContribution, ...] = (),
    ) -> AbilityTaskExecutionResult:
        current = state
        mutations: list[Mutation] = []
        events: list[GameEvent] = []
        rng_events: list[RNGEvent] = []
        records: list[dict[str, JSONValue]] = []
        task_records: list[dict[str, JSONValue]] = []
        primary_target = target_resolution.selected[0] if target_resolution.selected else None

        for phase in phases:
            tasks = {
                task.task_id: task
                for task in self.rules.ability_tasks_for_phase(phase.phase_id)
                if task.callback_kind == callback_kind
            }
            roots = tuple(
                sorted(
                    (task for task in tasks.values() if not task.parent_task_id),
                    key=lambda item: (item.task_index, item.task_path, item.task_id),
                )
            )
            for task in roots:
                current, task_mutations, task_events, task_rng_events, task_records_for_root = self._execute_task(
                    current,
                    task,
                    tasks,
                    command=command,
                    action_definition=action_definition,
                    primary_target=primary_target,
                    target_resolution=target_resolution,
                    action_damage_modifiers=action_damage_modifiers,
                )
                mutations.extend(task_mutations)
                events.extend(task_events)
                rng_events.extend(task_rng_events)
                records.extend(task_records_for_root)
                task_records.extend(
                    record.get("payload", {})
                    for record in task_records_for_root
                    if isinstance(record, dict) and record.get("record_type") == "ability_task"
                )

        if task_records:
            events.append(
                GameEvent(
                    event_type="ability_task.callback",
                    source_id=command.actor_id,
                    target_id=primary_target,
                    event_id=f"event:{state.event_index}:ability_task:{callback_kind}",
                    window=callback_kind,
                    process_only=True,
                    payload={
                        "callback_kind": callback_kind,
                        "task_record_count": len(task_records),
                        "mutation_count": len(mutations),
                    },
                )
            )
        return AbilityTaskExecutionResult(
            after_state=current,
            mutations=tuple(mutations),
            events=tuple(events),
            rng_events=tuple(rng_events),
            records=tuple(records),
            task_records=tuple(task_records),
            node_results=_node_results_from_task_records(task_records),
        )

    def _execute_formal_action_callback(
        self,
        state: BattleState,
        *,
        phases: tuple[AbilityPhaseIR, ...],
        callback_kind: str,
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        target_resolution: TargetResolution,
        action_damage_modifiers: tuple[DamageModifierContribution, ...] = (),
        admitted_action_target_fact: AdmittedActionTargetFact | None = None,
        action_execution_token: object | None = None,
    ) -> AbilityTaskExecutionResult:
        invocation = _FormalAbilityInvocation(
            "action",
            command.actor_id,
            command.action_id,
            command.action_level,
            target_resolution,
            action_command=command,
            action_definition=action_definition,
            action_damage_modifiers=action_damage_modifiers,
            accepted_action_target_fact=admitted_action_target_fact,
            action_execution_token=action_execution_token,
        )
        if admitted_action_target_fact is not None and action_execution_token is not None:
            scope = _issue_action_window_expected_scope(
                execution_token=action_execution_token, actor_id=command.actor_id,
                action_id=command.action_id, action_level=command.action_level,
                canonical_action_event_id=admitted_action_target_fact.canonical_action_event_id,
                impact_fingerprint=admitted_action_target_fact.impact_fingerprint,
                event_id=f"ability:{state.event_index}:{command.actor_id}:{command.action_id}:{callback_kind}",
                window=f"ability_callback:{callback_kind}", step_id=f"ability:{callback_kind}", step_index=0,
            )
            invocation = replace(invocation, admitted_action_target_fact=admitted_action_target_fact.bind_invocation(scope),
                                 expected_action_window_scope=scope)
        roots = tuple(phase for phase in phases if phase.invocation_role == "action_root")
        if not roots:
            return self._formal_callback_blocked(
                state,
                callback_kind,
                invocation,
                "ability_action_root_missing",
            )
        if any(
            phase.action_id != command.action_id
            or phase.level != command.action_level
            or phase.action_id != action_definition.action_id
            or phase.level != action_definition.level
            for phase in phases
            if phase.invocation_role in {"action_root", "nested_only"}
        ):
            return self._formal_callback_blocked(
                state,
                callback_kind,
                invocation,
                "ability_action_phase_identity_mismatch",
            )

        selected_roots = tuple(
            phase
            for phase in roots
            if any(
                task.callback_kind == callback_kind
                for task in self.rules.ability_tasks_for_phase(phase.phase_id)
            )
        )
        if not selected_roots:
            return AbilityTaskExecutionResult(after_state=state)

        return self._execute_formal_entries(
            state,
            entries=tuple((phase, callback_kind) for phase in selected_roots),
            invocation=invocation,
        )

    def _execute_formal_entries(
        self,
        state: BattleState,
        *,
        entries: tuple[tuple[AbilityPhaseIR, str], ...],
        invocation: _FormalAbilityInvocation,
    ) -> AbilityTaskExecutionResult:
        if not entries:
            return AbilityTaskExecutionResult(after_state=state)

        current = state
        mutations: list[Mutation] = []
        events: list[GameEvent] = []
        rng_events: list[RNGEvent] = []
        records: list[dict[str, JSONValue]] = []
        task_records: list[dict[str, JSONValue]] = []
        node_results: list[ExecutionNodeResult] = []
        mutation_ids: set[str] = set()
        event_ids: set[str] = set()
        rng_event_ids: set[str] = set()
        for ordinal, (phase, callback_kind) in enumerate(entries):
            graph_result = self.rules.query_formal_task_graph(
                "ability_phase_callback",
                phase.phase_id,
                callback_kind,
                (
                    task.task_id
                    for task in self.rules.ability_tasks_for_phase(phase.phase_id)
                    if task.callback_kind == callback_kind
                ),
            )
            graph = graph_result.value
            if (
                graph_result.status != "resolved"
                or type(graph) is not TaskGraphIR
            ):
                return self._formal_callback_blocked(
                    state,
                    callback_kind,
                    invocation,
                    graph_result.blocked_reason
                    or "ability_action_task_graph_identity_mismatch",
                    node_results=tuple(node_results),
                )
            invocation_id = (
                f"ability_{invocation.invocation_kind}:{state.event_index}:"
                f"{invocation.actor_id}:{invocation.ability_id}:"
                f"{invocation.ability_level}:{callback_kind}:"
                f"{ordinal}:{phase.phase_id}"
            )
            context_values: dict[str, JSONValue] = {
                "invocation_kind": invocation.invocation_kind,
                "actor_id": invocation.actor_id,
                "ability_id": invocation.ability_id,
                "ability_level": invocation.ability_level,
                "callback_kind": callback_kind,
                "primary_target_id": invocation.target_resolution.primary,
                "selected_target_ids": list(invocation.target_resolution.selected),
            }
            if invocation.standalone is not None:
                context_values.update(invocation.standalone.to_json())
            execution = self.task_graph_executor.execute(
                current,
                graph,
                TaskGraphExecutionContext(
                    invocation_id,
                    context_values,
                ),
                self._formal_task_graph_hooks(
                    invocation=invocation,
                ),
            )
            node_results.extend(execution.outcome.node_results)
            if not execution.ok:
                return self._formal_callback_blocked(
                    state,
                    callback_kind,
                    invocation,
                    execution.errors[0]
                    if execution.errors
                    else "ability_action_task_graph_execution_blocked",
                    node_results=tuple(node_results),
                )
            new_mutation_ids = tuple(item.stable_id() for item in execution.mutations)
            new_event_ids = tuple(
                cast(str, item.to_json()["event_id"]) for item in execution.events
            )
            new_rng_event_ids = tuple(
                cast(str, item.to_json()["event_id"]) for item in execution.rng_events
            )
            duplicate_channel = next(
                (
                    channel
                    for channel, values, seen in (
                        ("mutation", new_mutation_ids, mutation_ids),
                        ("event", new_event_ids, event_ids),
                        ("rng", new_rng_event_ids, rng_event_ids),
                    )
                    if any(value in seen for value in values)
                ),
                "",
            )
            if duplicate_channel:
                return self._formal_callback_blocked(
                    state,
                    callback_kind,
                    invocation,
                    f"ability_action_task_graph_duplicate_{duplicate_channel}_identity",
                    node_results=tuple(node_results),
                )
            mutation_ids.update(new_mutation_ids)
            event_ids.update(new_event_ids)
            rng_event_ids.update(new_rng_event_ids)
            current = execution.after_state
            mutations.extend(execution.mutations)
            events.extend(execution.events)
            rng_events.extend(execution.rng_events)
            graph_records = tuple(item.to_json(detach=False) for item in execution.settlement_records)
            records.extend(graph_records)
            task_records.extend(
                cast(dict[str, JSONValue], record["payload"])
                for record in graph_records
                if record.get("record_type") == "ability_task"
                and isinstance(record.get("payload"), dict)
            )
        return AbilityTaskExecutionResult(
            after_state=current,
            mutations=tuple(mutations),
            events=tuple(events),
            rng_events=tuple(rng_events),
            records=tuple(records),
            task_records=tuple(task_records),
            node_results=tuple(node_results),
            dispatched_event_ids=frozenset(invocation.dispatched_event_ids),
            hit_target_ids=tuple(dict.fromkeys(invocation.hit_target_ids)),
        )

    def _formal_task_graph_hooks(
        self,
        *,
        invocation: _FormalAbilityInvocation,
    ) -> TaskGraphExecutionHooks:
        return TaskGraphExecutionHooks(
            leaf=lambda request, state: self._execute_formal_leaf(
                request,
                state,
                invocation=invocation,
            ),
            condition=lambda request, state: self._evaluate_formal_condition(
                request,
                state,
                invocation=invocation,
            ),
            branch=lambda _request, _state: TaskGraphBranchResult(
                "blocked",
                blocked_reason="ability_task_graph_branch_domain_not_admitted",
            ),
            count=lambda request, definition, state: self._resolve_formal_count(
                request,
                definition,
                state,
                invocation=invocation,
            ),
            targets=lambda request, state: self._resolve_formal_targets(
                request,
                state,
                invocation=invocation,
            ),
            graph=lambda request, state: self._resolve_formal_nested_graph(
                request,
                state,
                invocation=invocation,
            ),
            weighted_selection=lambda request, selection, state: self._resolve_formal_weighted_selection(
                request,
                selection,
                state,
                invocation=invocation,
            ),
            template_bindings=lambda request, parameters, state: self._resolve_formal_template_bindings(
                request, parameters, state, invocation=invocation),
        )

    def _resolve_formal_template_bindings(self, request, parameters, state, *, invocation):
        task, reason = self._formal_task_for_request(request)
        node = self.rules.query_task_graph_node(request.graph_node_id).value
        if task is None or type(node) is not TaskGraphNodeIR or node.template_parameters != parameters:
            return TaskGraphTemplateBindingsResult("blocked", blocked_reason=reason or "template_parameter_node_mismatch")
        scoped = _task_graph_target_resolution(request, invocation.target_resolution)
        return evaluate_task_graph_template_bindings(request, parameters, state, binding_sources=_binding_sources(
            self.rules, state, invocation.actor_id, scoped.primary, action_level=invocation.ability_level,
            action_id=invocation.ability_id, current_action_trigger_key=_formal_action_trigger_key(invocation),
            ability_instance_id=_ability_instance_id(state, invocation),
            template_binding_sources=request.template_binding_sources))

    def _formal_status_nested_hooks(
        self,
        context: StatusNestedAbilityContext,
    ) -> TaskGraphExecutionHooks:
        if type(context) is not StatusNestedAbilityContext:
            raise TypeError("status nested ability context type is invalid")

        def invocation_for(
            request: TaskGraphHookRequest,
            state: BattleState,
        ) -> tuple[_FormalAbilityInvocation | None, str]:
            invocation, reason = self._status_nested_invocation_for_request(context, request, state)
            return (replace(invocation, template_binding_sources=request.template_binding_sources)
                    if invocation is not None else None), reason

        def leaf(request: TaskGraphHookRequest, state: BattleState) -> TaskGraphLeafResult:
            invocation, reason = invocation_for(request, state)
            if invocation is None:
                return TaskGraphLeafResult("blocked", outcome_kind="", blocked_reason=reason)
            return self._execute_formal_leaf(request, state, invocation=invocation)

        def condition(request: TaskGraphHookRequest, state: BattleState) -> TaskGraphConditionResult:
            invocation, reason = invocation_for(request, state)
            if invocation is None:
                return TaskGraphConditionResult("blocked", blocked_reason=reason)
            return self._evaluate_formal_condition(request, state, invocation=invocation)

        def branch(request: TaskGraphHookRequest, state: BattleState) -> TaskGraphBranchResult:
            invocation, reason = invocation_for(request, state)
            if invocation is None:
                return TaskGraphBranchResult("blocked", blocked_reason=reason)
            return TaskGraphBranchResult(
                "blocked",
                blocked_reason="ability_task_graph_branch_domain_not_admitted",
            )

        def count(
            request: TaskGraphHookRequest,
            definition: TaskGraphNumericDefinitionIR,
            state: BattleState,
        ) -> TaskGraphCountResult:
            invocation, reason = invocation_for(request, state)
            if invocation is None:
                return TaskGraphCountResult("blocked", blocked_reason=reason)
            return self._resolve_formal_count(
                request,
                definition,
                state,
                invocation=invocation,
            )

        def targets(request: TaskGraphHookRequest, state: BattleState) -> TaskGraphTargetResult:
            invocation, reason = invocation_for(request, state)
            if invocation is None:
                return TaskGraphTargetResult("blocked", blocked_reason=reason)
            return self._resolve_formal_targets(request, state, invocation=invocation)

        def graph(request: TaskGraphHookRequest, state: BattleState) -> TaskGraphGraphResult:
            invocation, reason = invocation_for(request, state)
            if invocation is None:
                return TaskGraphGraphResult("blocked", blocked_reason=reason)
            return self._resolve_formal_nested_graph(request, state, invocation=invocation)

        def weighted_selection(
            request: TaskGraphHookRequest,
            selection: TaskGraphWeightedSelectionIR,
            state: BattleState,
        ) -> TaskGraphWeightedSelectionResult:
            invocation, reason = invocation_for(request, state)
            if invocation is None:
                return TaskGraphWeightedSelectionResult("blocked", blocked_reason=reason)
            return self._resolve_formal_weighted_selection(request, selection, state, invocation=invocation)

        def template_bindings(request, parameters, state):
            invocation, reason = invocation_for(request, state)
            if invocation is None:
                return TaskGraphTemplateBindingsResult("blocked", blocked_reason=reason)
            return self._resolve_formal_template_bindings(request, parameters, state, invocation=invocation)

        return TaskGraphExecutionHooks(
            leaf=leaf,
            condition=condition,
            branch=branch,
            count=count,
            targets=targets,
            graph=graph,
            weighted_selection=weighted_selection,
            template_bindings=template_bindings,
        )

    def _status_nested_invocation_for_request(
        self,
        context: StatusNestedAbilityContext,
        request: TaskGraphHookRequest,
        state: BattleState,
    ) -> tuple[_FormalAbilityInvocation | None, str]:
        if type(context) is not StatusNestedAbilityContext:
            return None, "status_nested_ability_context_type_invalid"
        if type(request) is not TaskGraphHookRequest:
            return None, "status_nested_ability_request_type_invalid"
        owner = state.units.get(context.owner_id)
        if owner is None:
            return None, "status_nested_ability_owner_missing"
        details = owner.flags.get("status_details", ())
        matching = tuple(
            detail
            for detail in details
            if isinstance(detail, dict)
            and str(detail.get("instance_id") or "") == context.status_instance_id
            and str(detail.get("modifier_name") or "") == context.modifier_name
            and str(detail.get("owner_id") or "") == context.owner_id
        ) if isinstance(details, (list, tuple)) else ()
        if len(matching) != 1:
            return None, "status_nested_ability_status_instance_identity_mismatch"
        callback = self.rules.status_callback(context.callback_id)
        if (
            callback is None
            or callback.source_mode not in {"mainline_avatar_ability", "mainline_servant_ability", "mainline_stage_ability"}
            or callback.modifier_name != context.modifier_name
        ):
            return None, "status_nested_ability_callback_identity_mismatch"
        trigger_ids = matching[0].get("trigger_ids_by_event")
        admitted = (
            trigger_ids.get(callback.event)
            if isinstance(trigger_ids, dict)
            else None
        )
        if not isinstance(admitted, list) or context.callback_id not in admitted:
            return None, "status_nested_ability_callback_not_attached"
        root_result = self.rules.query_task_graph(context.root_graph_id)
        root_graph = root_result.value
        if (
            root_result.status != "resolved"
            or type(root_graph) is not TaskGraphIR
            or root_graph.entry_kind != "status_callback"
            or root_graph.owner_id != context.callback_id
            or root_graph.callback_kind != callback.event
        ):
            return None, "status_nested_ability_root_graph_identity_mismatch"
        if (
            len(request.active_graph_stack) != 2
            or request.active_graph_stack[0] != context.root_graph_id
            or request.active_graph_stack[-1] != request.graph_id
        ):
            return None, "status_nested_ability_request_stack_mismatch"
        child_result = self.rules.query_task_graph(request.graph_id)
        child_graph = child_result.value
        if (
            child_result.status != "resolved"
            or type(child_graph) is not TaskGraphIR
            or child_graph.entry_kind != "ability_phase_callback"
        ):
            return None, "status_nested_ability_child_graph_identity_mismatch"
        phase = self.rules.ability_phase(child_graph.owner_id)
        if (
            phase is None
            or phase.invocation_role != "nested_only"
            or phase.phase_id != child_graph.owner_id
        ):
            return None, "status_nested_ability_child_phase_not_nested_only"
        task, task_reason = self._formal_task_for_request(request)
        if task is None:
            return None, task_reason
        if task.phase_id != phase.phase_id or task.callback_kind != child_graph.callback_kind:
            return None, "status_nested_ability_child_task_identity_mismatch"
        linked_root_tasks: list[str] = []
        for status_task in self.rules.status_callback_tasks_for_callback(context.callback_id):
            if status_task.coverage_status != "executable" or status_task.opcode != "TriggerAbility":
                continue
            if status_task.linked_ability_phase_id == phase.phase_id:
                linked_root_tasks.append(status_task.task_id)
                continue
            if status_task.linked_standalone_graph_id:
                standalone = self.rules.standalone_ability_graph(
                    status_task.linked_standalone_graph_id
                )
                if standalone is not None and phase.phase_id in standalone.phase_ids:
                    linked_root_tasks.append(status_task.task_id)
        if len(linked_root_tasks) != 1:
            return None, (
                "status_nested_ability_root_link_missing"
                if not linked_root_tasks
                else "status_nested_ability_root_link_ambiguous"
            )
        if any(target_id not in state.units for target_id in request.target_ids):
            return None, "status_nested_ability_request_target_missing"
        trigger = self.rules.status_callback_task(linked_root_tasks[0])
        actor_alias = str(trigger.task_payload.get("TargetType") or "Caster")
        actor_id = (str(matching[0].get("caster_id") or "") if actor_alias == "Caster"
                    else context.owner_id if actor_alias == "ModifierOwnerEntity" else "")
        if actor_id not in state.units:
            return None, "status_nested_ability_caster_binding_missing"
        scoped_resolution = _task_graph_target_resolution(
            request,
            context.target_resolution,
        )
        return (
            _FormalAbilityInvocation(
                "status_nested",
                actor_id,
                phase.action_id,
                phase.level,
                scoped_resolution,
                execution_path=_task_graph_execution_path(request),
                iteration_index=request.iteration_index,
                admitted_action_target_fact=context.admitted_action_target_fact,
                expected_action_window_scope=context.expected_action_window_scope,
                param_status_scope=request.status_scope,
                trigger_event=request.trigger_event,
            ),
            "",
        )

    def _resolve_formal_weighted_selection(
        self,
        request: TaskGraphHookRequest,
        selection: TaskGraphWeightedSelectionIR,
        state: BattleState,
        *,
        invocation: _FormalAbilityInvocation,
    ) -> TaskGraphWeightedSelectionResult:
        invocation = replace(invocation, template_binding_sources=request.template_binding_sources)
        task, reason = self._formal_task_for_request(request)
        if task is None:
            return TaskGraphWeightedSelectionResult("blocked", blocked_reason=reason)
        if task.coverage_status != "executable" or task.blocked_reason:
            return TaskGraphWeightedSelectionResult(
                "blocked",
                blocked_reason=task.blocked_reason or "ability_task_weighted_selection_not_executable",
            )
        if type(selection) is not TaskGraphWeightedSelectionIR:
            return TaskGraphWeightedSelectionResult(
                "blocked",
                blocked_reason="ability_task_weighted_selection_type_invalid",
            )
        if task.opcode != "RandomConfig" or selection.graph_node_id != request.graph_node_id:
            return TaskGraphWeightedSelectionResult(
                "blocked", blocked_reason="ability_task_weighted_selection_identity_mismatch",
            )
        scoped = _task_graph_target_resolution(request, invocation.target_resolution)
        weights: list[float] = []
        for definition in selection.numeric_definitions:
            evaluation = self.evaluator.evaluate_numeric(
                definition.expression,
                NumericEvaluationContext(
                    binding_sources=(
                        *_binding_sources(
                            self.rules, state, invocation.actor_id, scoped.primary,
                            action_level=invocation.ability_level,
                            action_id=invocation.ability_id,
                            ability_name=task.ability_name,
                            current_action_trigger_key=_formal_action_trigger_key(invocation),
                            ability_instance_id=_ability_instance_id(state, invocation),
                            template_binding_sources=invocation.template_binding_sources,
                        ),
                        *_expression_binding_sources(definition.expression),
                    ),
                    source_trace=definition.source.to_json(),
                ),
            )
            if not evaluation.ok or evaluation.value is None:
                return TaskGraphWeightedSelectionResult(
                    "blocked", blocked_reason=evaluation.blocked_reason or "ability_task_weight_not_resolved",
                )
            weights.append(float(evaluation.value))
        payload = (
            _rng_event_payload_from_command(invocation.action_command)
            if invocation.action_command is not None else request.context_values
        )
        return resolve_task_graph_weighted_selection(
            request, selection, state, tuple(weights),
            rng_choices=(
                payload.get("rng_choices")
                if isinstance(payload.get("rng_choices"), Mapping) else None
            ),
            rng_mode=str(payload.get("rng_mode") or "deterministic_seed"),
        )

    def _execute_formal_leaf(
        self,
        request: TaskGraphHookRequest,
        state: BattleState,
        *,
        invocation: _FormalAbilityInvocation,
    ) -> TaskGraphLeafResult:
        task, reason = self._formal_task_for_request(request)
        if task is None:
            return TaskGraphLeafResult("blocked", outcome_kind="", blocked_reason=reason)
        if task.opcode == "TriggerParallelAbility":
            return self._execute_parallel_abilities(request, state, task, invocation)
        if task.opcode == "WaitParallelTimeStamp":
            if not invocation.parallel_execution:
                return TaskGraphLeafResult("blocked", outcome_kind="", blocked_reason="parallel_barrier_outside_parallel_invocation")
            reason = ability_task_runtime_blocked_reason(self.rules, task, topology_authority="task_graph")
            if reason:
                return TaskGraphLeafResult("blocked", outcome_kind="", blocked_reason=reason)
            return TaskGraphLeafResult("resolved", settlement_records=_task_graph_settlement_records((
                _task_process_record(task, ok=True, blocked_reason="parallel_time_barrier"),
            )))
        if not is_process_only_ability_task(task):
            unresolved = tuple(
                reference
                for reference in request.references
                if reference.resolution_status != "resolved"
            )
            node_result = self.rules.query_task_graph_node(request.graph_node_id)
            admitted_audit_reference = (
                node_result.status == "resolved"
                and type(node_result.value) is TaskGraphNodeIR
                and not ability_task_runtime_blocked_reason(
                    self.rules,
                    task,
                    topology_authority="task_graph",
                )
                and emission_backed_damage_audit_reference_admitted(
                    self.rules,
                    task,
                    node_result.value,
                    unresolved,
                )
            )
            if unresolved and not admitted_audit_reference:
                return TaskGraphLeafResult(
                    "blocked",
                    outcome_kind="",
                    blocked_reason=unresolved[0].blocked_reason
                    or "ability_task_graph_leaf_reference_not_resolved",
                )
        scoped_resolution = _task_graph_target_resolution(
            request, invocation.target_resolution
        )
        if task.opcode in {"FireProjectile", "NewFireProjectile"} and task.execution_mode == "runtime_effect":
            reason = ability_task_runtime_blocked_reason(self.rules, task, topology_authority="task_graph")
            if reason or len(scoped_resolution.selected) != 1 or scoped_resolution.selected[0] not in state.units:
                return TaskGraphLeafResult(
                    "blocked", outcome_kind="",
                    blocked_reason=reason or "projectile_requires_one_resolved_target",
                )
            # ponytail: selected single-target, waiting projectiles only. Flight
            # time is visual; independent in-flight outcomes need a projectile producer.
            return TaskGraphLeafResult("resolved", outcome_kind="projectile_hit")
        scoped_invocation = replace(
            invocation,
            target_resolution=scoped_resolution,
            execution_path=_task_graph_execution_path(request),
            iteration_index=request.iteration_index,
            param_status_scope=request.status_scope,
            template_target_ids=request.template_target_ids,
            template_binding_sources=request.template_binding_sources,
        )
        continuation = TaskGraphContinuation.from_hook_request(request)
        created_unit_ids: list[str] = []
        _, mutations, events, rng_events, records, child_projections = (
            self._execute_formal_leaf_task(
                state,
                task,
                invocation=scoped_invocation,
                primary_target=scoped_resolution.primary,
                target_resolution=scoped_resolution,
                task_graph_continuation=continuation,
                nested_ability_hooks=self._formal_task_graph_hooks(
                    invocation=scoped_invocation,
                ),
                created_unit_ids=created_unit_ids,
            )
        )
        blocker = _ability_task_records_blocked_reason(records)
        if blocker:
            return TaskGraphLeafResult("blocked", outcome_kind="", blocked_reason=blocker)
        if task.opcode == "CreateServant" and len(created_unit_ids) != 1:
            return TaskGraphLeafResult("blocked", outcome_kind="", blocked_reason="servant_create_target_fact_missing")
        try:
            settlement = _task_graph_settlement_records(records)
        except (TypeError, ValueError):
            return TaskGraphLeafResult(
                "blocked",
                outcome_kind="",
                blocked_reason="ability_task_graph_leaf_settlement_invalid",
            )
        return TaskGraphLeafResult(
            "resolved",
            tuple(mutations),
            tuple(events),
            tuple(rng_events),
            settlement,
            child_projections=tuple(child_projections),
            outcome_kind="servant_created" if task.opcode == "CreateServant" else "success",
            continuation_target_ids=tuple(created_unit_ids) if task.opcode == "CreateServant" else None,
        )

    def _execute_formal_leaf_task(
        self,
        state: BattleState,
        task: AbilityTaskIR,
        *,
        invocation: _FormalAbilityInvocation,
        primary_target: str | None,
        target_resolution: TargetResolution,
        task_graph_continuation: TaskGraphContinuation,
        nested_ability_hooks: TaskGraphExecutionHooks,
        created_unit_ids: list[str] | None = None,
    ) -> tuple[
        BattleState,
        list[Mutation],
        list[GameEvent],
        list[RNGEvent],
        list[dict[str, JSONValue]],
        list[TaskGraphNodeProjection],
    ]:
        if self.rules.damage_emissions_for_task(task.task_id):
            admission = ability_task_runtime_blocked_reason(self.rules, task, topology_authority="task_graph")
            if admission:
                return state, [], [], [], [_task_process_record(task, ok=False, blocked_reason=admission)], []
            if invocation.action_command is not None and invocation.action_definition is not None:
                definition = invocation.action_definition
                command = replace(invocation.action_command, metadata={
                    **invocation.action_command.metadata,
                    "ability_task_execution_path": invocation.execution_path,
                    "ability_task_iteration_index": invocation.iteration_index,
                })
            else:
                emissions = self.rules.damage_emissions_for_task(task.task_id)
                attack_types = {emission.scaling_basis_expr.get("attack_type") for emission in emissions}
                if len(attack_types) != 1 or not all(isinstance(value, str) and value for value in attack_types):
                    return state, [], [], [], [_task_process_record(
                        task, ok=False, blocked_reason="nested_damage_attack_type_binding_missing",
                    )], []
                # Independent damage grants no player action or action resources.
                definition = ActionDefinitionIR(
                    f"ability_damage:{task.task_id}", task.action_id, invocation.ability_level,
                    next(iter(attack_types)), "standalone_ability", "single", 0, 0, 0, 0,
                    (), (), (), None, task.source, coverage_status="executable",
                    damage_kind="hp_damage", damage_formula_family="direct", source_mode="queue_standalone",
                )
                command = ActionCommand(invocation.actor_id, task.action_id, invocation.ability_level,
                    target_ids=target_resolution.selected,
                    source="queue" if invocation.invocation_kind == "queue_standalone" else "system",
                    metadata={"ability_task_execution_path": invocation.execution_path,
                              "ability_task_iteration_index": invocation.iteration_index})
            return self._execute_damage_task(
                state, task, command=command, action_definition=definition,
                primary_target=primary_target, target_resolution=target_resolution,
                task_graph_continuation=task_graph_continuation, nested_ability_hooks=nested_ability_hooks,
                dispatched_event_ids=invocation.dispatched_event_ids,
                hit_target_ids=invocation.hit_target_ids,
                action_damage_modifiers=invocation.action_damage_modifiers,
                window_ledger=invocation.damage_window_ledger,
                packet_sequence_id=_ability_instance_id(state, invocation),
                template_binding_sources=invocation.template_binding_sources,
            )
        admission_reason = ability_task_runtime_blocked_reason(
            self.rules,
            task,
            topology_authority="task_graph",
        )
        if admission_reason:
            return state, [], [], [], [
                _task_process_record(task, ok=False, blocked_reason=admission_reason)
            ], []
        if is_process_only_ability_task(task):
            return state, [], [], [], [
                _task_process_record(
                    task,
                    ok=True,
                    blocked_reason="process_only_ability_task",
                    effect_id=task.effect_id,
                    effect_opcode=task.opcode,
                    effect_coverage="process_only",
                )
            ], []
        if task.opcode in {
            "PredicateTaskList",
            "LoopExecuteTaskListWithInterval",
            "TriggerAbility",
        }:
            return state, [], [], [], [
                _task_process_record(
                    task,
                    ok=False,
                    blocked_reason="ability_task_graph_structural_node_reached_leaf",
                )
            ], []
        if task.opcode == "SummonMonster":
            result = self.execute_summon_monster_task(
                state, task, actor_id=invocation.actor_id,
                dispatched_event_ids=invocation.dispatched_event_ids,
            )
            return (*result, [])
        result = self._execute_effect_leaf_task(
            state,
            task,
            invocation=invocation,
            primary_target=primary_target,
            target_resolution=target_resolution,
            reduce_candidate=False,
            created_unit_ids=created_unit_ids,
            task_graph_continuation=task_graph_continuation,
        )
        if invocation.invocation_kind in {"action", "character_startup", "character_build_startup", "servant_startup", "battle_event_startup", "stage_startup", "queue_standalone"}:
            return self._dispatch_effect_leaf_events(
                state, task, result, invocation.dispatched_event_ids,
                task_graph_continuation, nested_ability_hooks,
            )
        return (*result, [])

    def _dispatch_effect_leaf_events(
        self, state: BattleState, task: AbilityTaskIR,
        result: tuple[BattleState, list[Mutation], list[GameEvent], list[RNGEvent], list[dict[str, JSONValue]]],
        dispatched_event_ids: set[str],
        task_graph_continuation: TaskGraphContinuation | None,
        nested_ability_hooks: TaskGraphExecutionHooks | None,
    ) -> tuple[BattleState, list[Mutation], list[GameEvent], list[RNGEvent], list[dict[str, JSONValue]], list[TaskGraphNodeProjection]]:
        _, mutations, emitted, rng_events, records = result
        if _ability_task_records_blocked_reason(records):
            return (*result, [])
        if emitted and self.event_dispatcher is None:
            return state, [], [], [], [_task_process_record(
                task, ok=False, blocked_reason="ability_effect_dispatcher_missing",
            )], []
        current = self.reducer.apply_all(state, mutations)
        events: list[GameEvent] = []
        projections: list[TaskGraphNodeProjection] = []
        for event in emitted:
            if (event.event_type == "status.callback"
                    or str(event.to_json()["event_id"]) in dispatched_event_ids):
                events.append(event)
                continue
            assert self.event_dispatcher is not None
            dispatch = self.event_dispatcher.dispatch_event(
                current, event=event, task_graph_continuation=task_graph_continuation,
                nested_ability_hooks=nested_ability_hooks,
            )
            current = dispatch.after_state
            dispatched_event_ids.update(dispatch.dispatched_event_ids)
            mutations.extend(dispatch.mutations)
            events.extend(dispatch.events)
            rng_events.extend(dispatch.rng_events)
            records.extend(dispatch.records)
            projections.extend(dispatch.task_graph_projections)
            if dispatch.errors:
                records.append(_task_process_record(
                    task, ok=False, blocked_reason="ability_task_listener_blocked:" + ",".join(dispatch.errors),
                ))
                break
        return current, mutations, events, rng_events, records, projections

    def _resolve_task_action_definition(
        self,
        task: AbilityTaskIR,
        invocation: _FormalAbilityInvocation,
        state: BattleState,
    ) -> ActionDefinitionIR | None:
        """Resolve the action-scale context for an effect leaf.

        A startup or standalone invocation can run a nested phase whose source
        formulas read action properties (for example SPBase). Use the invocation's
        own action first, then the task's action, then the unique mainline action
        binding of the same source ability name. Anything ambiguous stays None.
        """

        if invocation.action_definition is not None:
            return invocation.action_definition
        if task.action_id and task.level:
            action = self.rules.action_definition(task.action_id, task.level)
            if action is not None:
                return action
        phase = self.rules.ability_phase(task.phase_id)
        if phase is None:
            return None
        action_ids = {
            candidate.action_id
            for candidate in self.rules.ir.ability_phases
            if candidate.ability_name == phase.ability_name
            and candidate.action_id.startswith("avatar_skill:")
            and candidate.level > 0
        }
        if len(action_ids) != 1:
            return None
        action_id = next(iter(action_ids))
        units = [state.units.get(invocation.actor_id)]
        caster = units[0]
        if caster is not None:
            owner_id = caster.flags.get("owner_id")
            if isinstance(owner_id, str) and owner_id:
                units.append(state.units.get(owner_id))
        for unit in units:
            if unit is None:
                continue
            levels = unit.flags.get("effective_skill_levels_by_action_id")
            if not isinstance(levels, dict):
                continue
            level = levels.get(action_id)
            if type(level) is int and level > 0:
                return self.rules.action_definition(action_id, level)
        return None

    def _execute_effect_leaf_task(
        self,
        state: BattleState,
        task: AbilityTaskIR,
        *,
        invocation: _FormalAbilityInvocation,
        primary_target: str | None,
        target_resolution: TargetResolution,
        reduce_candidate: bool,
        created_unit_ids: list[str] | None = None,
        task_graph_continuation: TaskGraphContinuation | None = None,
    ) -> tuple[BattleState, list[Mutation], list[GameEvent], list[RNGEvent], list[dict[str, JSONValue]]]:
        if not task.effect_id:
            return state, [], [], [], [
                _task_process_record(task, ok=False, blocked_reason="task_has_no_effect")
            ]
        effect = self.rules.effect(task.effect_id)
        if effect is None:
            return state, [], [], [], [
                _task_process_record(task, ok=False, blocked_reason="missing_effect")
            ]
        effect_coverage = self.effect_registry.coverage(effect)
        if effect_coverage != "executable":
            return state, [], [], [], [
                _task_process_record(
                    task,
                    ok=False,
                    blocked_reason=f"effect_not_executable:{effect_coverage}",
                    effect_id=effect.effect_id,
                    effect_opcode=effect.opcode,
                    effect_coverage=effect_coverage,
                )
            ]
        ability_instance_id = _ability_instance_id(state, invocation)
        application_instance_id = (
            f"ability_task:{state.event_index}:{invocation.actor_id}:{invocation.ability_id}:"
            f"{task.task_id}:{invocation.execution_path}"
        )
        # The corpse-only ExitBreak branch consumes exactly the final-death
        # identity of this entry's admitted Deathrattle queue authority.
        death_instance_id = (
            invocation.standalone.death_instance_id
            if invocation.invocation_kind == "queue_standalone"
            and invocation.standalone is not None
            else ""
        )
        action_definition = self._resolve_task_action_definition(task, invocation, state)
        result = self.effect_registry.execute(
            effect,
            EffectExecutionContext(
                state=state,
                caster_id=invocation.actor_id,
                source_id=f"ability_task:{task.task_id}",
                action_definition=action_definition,
                ability_instance_id=ability_instance_id,
                application_instance_id=application_instance_id,
                owner_id=invocation.actor_id,
                death_instance_id=death_instance_id,
                param_entity_id=primary_target or invocation.actor_id,
                current_action_target_id=primary_target,
                target_resolution=target_resolution,
                trigger_event=invocation.trigger_event,
                event_payload={
                    **_formal_effect_event_payload(
                        invocation, primary_target, target_resolution
                    ),
                    "task_id": task.task_id,
                    "hit_index": task.task_index,
                    "rng_decision_index": task.task_index,
                    "ability_instance_id": ability_instance_id,
                    "operation_event_id": application_instance_id,
                },
                binding_sources=_binding_sources(
                    self.rules,
                    state,
                    invocation.actor_id,
                    primary_target,
                    action_level=invocation.ability_level,
                    action_id=invocation.ability_id,
                    ability_name=task.ability_name,
                    current_action_trigger_key=_formal_action_trigger_key(invocation),
                    ability_instance_id=ability_instance_id,
                    template_binding_sources=invocation.template_binding_sources,
                ),
                include_ambient_status_bindings=False,
                admitted_action_target_fact=invocation.admitted_action_target_fact,
                expected_action_window_scope=invocation.expected_action_window_scope,
                param_status_scope=invocation.param_status_scope,
                template_target_ids=invocation.template_target_ids,
                task_graph_continuation=task_graph_continuation,
            ),
        )
        invocation.dispatched_event_ids.update(result.dispatched_event_ids)
        if created_unit_ids is not None and not result.unsupported:
            created_unit_ids.extend(result.created_unit_ids)
        after = (
            self.reducer.apply_all(state, result.mutations)
            if reduce_candidate
            else state
        )
        records = [
            *result.records,
            _task_process_record(
                task,
                ok=not result.unsupported,
                blocked_reason=",".join(result.unsupported),
                effect_id=effect.effect_id,
                effect_opcode=effect.opcode,
                effect_coverage=effect_coverage,
                mutation_count=len(result.mutations),
                record_count=len(result.records),
            ),
        ]
        return (
            after,
            list(result.mutations),
            list(result.events),
            list(result.rng_events),
            records,
        )

    def _evaluate_formal_ability_condition(
        self,
        state: BattleState,
        task: AbilityTaskIR,
        *,
        invocation: _FormalAbilityInvocation,
        primary_target: str | None,
        target_resolution: TargetResolution,
    ) -> tuple[bool | None, str, dict[str, JSONValue]]:
        condition = self.rules.condition(task.condition_id) if task.condition_id else None
        if condition is None:
            return None, "missing_predicate_condition", {}
        target_context = TargetEvaluationContext(
            caster_id=invocation.actor_id,
            effect_owner_id=invocation.actor_id,
            parameter_entity_ids=((primary_target or invocation.actor_id),),
            selected_target_ids=target_resolution.selected,
            current_target_id=primary_target,
            turn_owner_id=committed_turn_owner_id(state),
            admitted_action_target_fact=invocation.admitted_action_target_fact,
            expected_action_window_scope=invocation.expected_action_window_scope,
            template_entity_ids=invocation.template_target_ids,
        )
        result = self.evaluator.evaluate_condition_result(
            condition,
            replace(self.targets.condition_evaluation_context(
                state,
                condition,
                context=target_context,
                target_resolution=target_resolution,
                condition_event_payload={
                    **_formal_event_payload(
                        invocation, primary_target, target_resolution
                    ),
                    "task_id": task.task_id,
                    "hit_index": task.task_index,
                    "rng_decision_index": task.task_index,
                },
                binding_sources=_binding_sources(
                    self.rules,
                    state,
                    invocation.actor_id,
                    primary_target,
                    action_level=invocation.ability_level,
                    action_id=invocation.ability_id,
                    ability_name=task.ability_name,
                    current_action_trigger_key=_formal_action_trigger_key(
                        invocation
                    ),
                    ability_instance_id=_ability_instance_id(state, invocation),
                    template_binding_sources=invocation.template_binding_sources,
                ),
                transient_condition_provider=_formal_condition_provider(
                    self.rules,
                    state,
                    invocation,
                    target_resolution,
                    task.task_id,
                ),
            ), trigger_event=invocation.trigger_event),
        )
        evidence = cast(dict[str, JSONValue], result.to_json())
        if not result.ok or result.result is None:
            return (
                None,
                f"blocked_condition:{condition.condition_id}:{result.reason}",
                evidence,
            )
        return result.result, "", evidence

    def _evaluate_formal_condition(
        self,
        request: TaskGraphHookRequest,
        state: BattleState,
        *,
        invocation: _FormalAbilityInvocation,
    ) -> TaskGraphConditionResult:
        task, reason = self._formal_task_for_request(request)
        if task is None:
            return TaskGraphConditionResult("blocked", blocked_reason=reason)
        if task.opcode == "SwitchByCommandType" and not task.condition_id:
            # A bare command-type switch carries no predicate; it is a
            # command-phase marker whose implicit branch always runs.
            return TaskGraphConditionResult("resolved", value=True)
        condition_refs = tuple(
            reference
            for reference in request.references
            if reference.reference_kind == "condition"
        )
        if (
            len(condition_refs) != 1
            or condition_refs[0].resolution_status != "resolved"
            or condition_refs[0].definition_id != task.condition_id
        ):
            return TaskGraphConditionResult(
                "blocked",
                blocked_reason="ability_task_graph_condition_reference_not_resolved",
            )
        scoped = _task_graph_target_resolution(request, invocation.target_resolution)
        scoped_invocation = replace(invocation, target_resolution=scoped,
                                    param_status_scope=request.status_scope,
                                    template_target_ids=request.template_target_ids,
                                    template_binding_sources=request.template_binding_sources)
        value, blocker, evidence = self._evaluate_formal_ability_condition(
            state,
            task,
            invocation=scoped_invocation,
            primary_target=scoped.primary,
            target_resolution=scoped,
        )
        if value is None:
            return TaskGraphConditionResult("blocked", blocked_reason=blocker)
        condition = self.rules.condition(task.condition_id) if task.condition_id else None
        return TaskGraphConditionResult(
            "resolved",
            value,
            progress_remaining=_dynamic_condition_progress(condition, evidence),
        )

    def _resolve_formal_count(
        self,
        request: TaskGraphHookRequest,
        definition: TaskGraphNumericDefinitionIR,
        state: BattleState,
        *,
        invocation: _FormalAbilityInvocation,
    ) -> TaskGraphCountResult:
        invocation = replace(invocation, template_binding_sources=request.template_binding_sources)
        task, reason = self._formal_task_for_request(request)
        if task is None:
            return TaskGraphCountResult("blocked", blocked_reason=reason)
        numeric_refs = tuple(
            reference
            for reference in request.references
            if reference.reference_kind == "numeric"
        )
        if (
            len(numeric_refs) != 1
            or numeric_refs[0].resolution_status != "resolved"
            or numeric_refs[0].definition_id != definition.definition_id
        ):
            return TaskGraphCountResult(
                "blocked",
                blocked_reason="ability_task_graph_numeric_reference_not_resolved",
            )
        scoped = _task_graph_target_resolution(request, invocation.target_resolution)
        result = self.evaluator.evaluate_numeric(
            definition.expression,
            NumericEvaluationContext(
                binding_sources=_binding_sources(
                    self.rules,
                    state,
                    invocation.actor_id,
                    scoped.primary,
                    action_level=invocation.ability_level,
                    action_id=invocation.ability_id,
                    ability_name=task.ability_name,
                    current_action_trigger_key=_formal_action_trigger_key(invocation),
                    ability_instance_id=_ability_instance_id(state, invocation),
                    template_binding_sources=invocation.template_binding_sources,
                ),
                source_trace=definition.source.to_json(),
            ),
        )
        if (
            not result.ok
            or result.value is None
            or not math.isfinite(result.value)
            or result.value < 0
            or not result.value.is_integer()
        ):
            return TaskGraphCountResult(
                "blocked",
                blocked_reason=result.blocked_reason
                or "ability_task_graph_count_not_nonnegative_integer",
            )
        return TaskGraphCountResult("resolved", int(result.value))

    def _resolve_formal_targets(
        self,
        request: TaskGraphHookRequest,
        state: BattleState,
        *,
        invocation: _FormalAbilityInvocation,
    ) -> TaskGraphTargetResult:
        invocation = replace(invocation, template_binding_sources=request.template_binding_sources)
        task, reason = self._formal_task_for_request(request)
        if task is None:
            return TaskGraphTargetResult("blocked", blocked_reason=reason)
        target_refs = tuple(
            reference
            for reference in request.references
            if reference.reference_kind == "target"
        )
        if len(target_refs) != 1 or target_refs[0].resolution_status != "resolved":
            return TaskGraphTargetResult(
                "blocked",
                blocked_reason="ability_task_graph_target_reference_not_resolved",
            )
        expression, lookup_reason = self.rules.target_expression_resolution(
            target_refs[0].definition_id
        )
        if expression is None:
            return TaskGraphTargetResult("blocked", blocked_reason=lookup_reason)
        scoped = _task_graph_target_resolution(request, invocation.target_resolution)
        primary = scoped.primary
        target_context = TargetEvaluationContext(
            caster_id=invocation.actor_id,
            effect_owner_id=invocation.actor_id,
            parameter_entity_ids=((primary or invocation.actor_id),),
            selected_target_ids=scoped.selected,
            current_target_id=primary,
            turn_owner_id=committed_turn_owner_id(state),
            admitted_action_target_fact=invocation.admitted_action_target_fact,
            expected_action_window_scope=invocation.expected_action_window_scope,
            template_entity_ids=request.template_target_ids,
        )
        result = self.targets.resolve_target_expression(
            state,
            expression,
            context=target_context,
            target_resolution=scoped,
            condition_event_payload={
                **_formal_event_payload(invocation, primary, scoped),
                "task_id": task.task_id,
                "event_id": f"target:{request.invocation_id}:{_task_graph_execution_path(request)}",
            },
            binding_sources=_binding_sources(
                self.rules,
                state,
                invocation.actor_id,
                primary,
                action_level=invocation.ability_level,
                action_id=invocation.ability_id,
                ability_name=task.ability_name,
                current_action_trigger_key=_formal_action_trigger_key(invocation),
                ability_instance_id=_ability_instance_id(state, invocation),
                template_binding_sources=invocation.template_binding_sources,
            ),
            transient_condition_provider=_formal_condition_provider(
                self.rules, state, invocation, scoped, task.task_id
            ),
        )
        if result.blocked:
            return TaskGraphTargetResult("blocked", blocked_reason=result.blocked_reason)
        if task.opcode == "Remodifier":
            from .status_callbacks import resolve_remodifier_status_scopes

            reason = ability_task_runtime_blocked_reason(self.rules, task, topology_authority="task_graph")
            effect = self.rules.effect(task.effect_id)
            standard = effect.payload.get("standard", {}) if effect is not None else {}
            query = standard.get("query")
            if reason or standard.get("operation") != "select_status_instances" or not isinstance(query, Mapping):
                return TaskGraphTargetResult("blocked", blocked_reason=reason or "remodifier_query_definition_missing")
            caster_id = None
            if query.get("CasterFilter"):
                caster_id = {"Caster": invocation.actor_id, "ModifierOwnerEntity": invocation.actor_id,
                    "ParamEntity": primary, "CurrentTurnOwnerEntity": committed_turn_owner_id(state)
                }.get(query["CasterFilter"])
                if caster_id not in state.units:
                    return TaskGraphTargetResult("blocked", blocked_reason="remodifier_caster_filter_unresolved")
            maximum = None
            if "MaxNumber" in query:
                numeric = resolve_runtime_numeric_expression(query["MaxNumber"],
                    binding_sources=_binding_sources(self.rules, state, invocation.actor_id, primary,
                        action_id=invocation.ability_id, action_level=invocation.ability_level,
                        ability_name=task.ability_name,
                        ability_instance_id=_ability_instance_id(state, invocation),
                        template_binding_sources=invocation.template_binding_sources),
                    source_trace=task.source.to_json())
                if (not numeric.ok or numeric.value is None or numeric.value < 0
                        or not float(numeric.value).is_integer()):
                    return TaskGraphTargetResult("blocked", blocked_reason=numeric.blocked_reason or "remodifier_max_number_invalid")
                maximum = int(numeric.value)
            predicate = None
            if query.get("predicate_filter_required"):
                if not task.condition_id or query.get("predicate_condition_id") != task.condition_id:
                    return TaskGraphTargetResult("blocked", blocked_reason="remodifier_predicate_reference_mismatched")
                def predicate(scope):
                    return self._evaluate_formal_condition(
                        replace(request, status_scope=scope,
                            invocation_id=f"{request.invocation_id}:filter:{scope.owner_id}:{scope.instance_id}"),
                        state, invocation=invocation,
                    )
            selected = resolve_remodifier_status_scopes(state, query, result.target_ids,
                caster_id=caster_id, maximum=maximum, predicate=predicate)
            return replace(selected, rng_events=(*result.rng_events, *selected.rng_events)) if selected.status == "resolved" else selected
        return TaskGraphTargetResult("resolved", result.target_ids, rng_events=result.rng_events)

    def _execute_parallel_abilities(
        self, request: TaskGraphHookRequest, state: BattleState, task: AbilityTaskIR,
        invocation: _FormalAbilityInvocation,
    ) -> TaskGraphLeafResult:
        invocation = replace(invocation, template_binding_sources=request.template_binding_sources)
        def blocked(reason: str) -> TaskGraphLeafResult:
            return TaskGraphLeafResult("blocked", outcome_kind="", blocked_reason=reason)

        reason = ability_task_runtime_blocked_reason(self.rules, task, topology_authority="task_graph")
        if reason:
            return blocked(reason)
        if invocation.invocation_kind != "action" or invocation.action_command is None:
            return blocked("parallel_ability_requires_action_context")
        if (invocation.accepted_action_target_fact is None or invocation.action_execution_token is None
                or invocation.action_definition is None):
            return blocked("parallel_attack_completion_authority_missing")
        event_definition = self.rules.action_event(invocation.ability_id, invocation.ability_level)
        if event_definition is None:
            return blocked("parallel_attack_action_event_missing")
        effect = self.rules.effect(task.effect_id)
        standard = effect.payload.get("standard", {}) if effect is not None else {}
        calls = standard.get("calls")
        refs = standard.get("target_expression_refs", {})
        if standard.get("operation") != "parallel_ability_calls" or not isinstance(calls, (list, tuple)) or not calls:
            return blocked("parallel_ability_call_contract_missing")
        parent_targets = _task_graph_target_resolution(request, invocation.target_resolution)
        target_context = TargetEvaluationContext(
            caster_id=invocation.actor_id, effect_owner_id=invocation.actor_id,
            parameter_entity_ids=((parent_targets.primary,) if parent_targets.primary else ()),
            selected_target_ids=parent_targets.selected, current_target_id=parent_targets.primary,
            template_entity_ids=request.template_target_ids,
            turn_owner_id=committed_turn_owner_id(state),
            admitted_action_target_fact=invocation.admitted_action_target_fact,
            expected_action_window_scope=invocation.expected_action_window_scope,
        )

        def targets(field: str):
            reference = refs.get(field, {})
            expression = self.rules.target_expression(str(reference.get("target_expression_id") or ""))
            if expression is None:
                return None
            return self.targets.resolve_target_expression(
                state, expression, context=target_context, target_resolution=parent_targets,
                condition_event_payload=_formal_event_payload(invocation, parent_targets.primary, parent_targets),
                binding_sources=_binding_sources(self.rules, state, invocation.actor_id, parent_targets.primary,
                    action_id=invocation.ability_id, action_level=invocation.ability_level,
                    template_binding_sources=invocation.template_binding_sources),
            )

        entries = []
        children = []
        target_rng = []
        continuation = TaskGraphContinuation.from_hook_request(request)
        for ordinal, call in enumerate(calls):
            caster = targets(f"ParallelAbilityList[{ordinal}].TargetType")
            if caster is None or not caster.resolved or len(caster.target_ids) != 1:
                return blocked("parallel_ability_caster_unresolved_or_ambiguous")
            actor_id = caster.target_ids[0]
            actor = state.units.get(actor_id)
            if actor is None or actor.hp <= 0 or actor.lifecycle_status != "active":
                return blocked("parallel_ability_caster_not_active")
            inherent_field = f"ParallelAbilityList[{ordinal}].AbilityInherentTargetType"
            inherent = targets(inherent_field) if inherent_field in refs else None
            if inherent_field in refs and (inherent is None or not inherent.resolved):
                return blocked("parallel_ability_inherent_target_unresolved")
            selected = inherent.target_ids if inherent is not None else parent_targets.selected
            if selected != parent_targets.selected:
                return blocked("parallel_ability_changed_target_footprint_not_admitted")
            target_rng.extend(caster.rng_events)
            if inherent is not None:
                target_rng.extend(inherent.rng_events)
            nested = replace(
                invocation, actor_id=actor_id, parallel_execution=True,
                admitted_action_target_fact=None, expected_action_window_scope=None,
                action_damage_modifiers=invocation.action_damage_modifiers if actor_id == invocation.actor_id else (),
                action_command=replace(invocation.action_command, actor_id=actor_id, target_ids=selected),
                target_resolution=replace(parent_targets, requested=selected, selected=selected, rejected=(),
                                          reason="parallel_ability_inherent_targets", source="ability_task_system"),
            )
            graphs = []
            for phase_id in call.get("phase_ids", ()):
                phase = self.rules.ability_phase(phase_id)
                if phase is None or phase.invocation_role != "nested_only":
                    return blocked("parallel_ability_phase_not_admitted")
                tasks = tuple(item for item in self.rules.ability_tasks_for_phase(phase_id)
                              if item.callback_kind == task.callback_kind)
                if not tasks:
                    continue
                query = self.rules.query_formal_task_graph("ability_phase_callback", phase_id,
                                                          task.callback_kind, (item.task_id for item in tasks))
                if query.status != "resolved" or type(query.value) is not TaskGraphIR:
                    return blocked(query.blocked_reason or "parallel_ability_task_graph_missing")
                graphs.append(query.value)
            if len(graphs) != 1:
                return blocked("parallel_ability_callback_missing_or_ambiguous")
            graph = graphs[0]
            times = []
            time = 0.0
            nodes = {node.graph_node_id: node for node in graph.nodes}
            for root_id in graph.root_node_ids:
                node = nodes[root_id]
                if node.opcode == "WaitParallelTimeStamp":
                    barrier = self.rules.ability_task(node.formal_task_id)
                    barrier_effect = self.rules.effect(barrier.effect_id) if barrier is not None else None
                    value = barrier_effect.payload.get("standard", {}).get("time", {}) if barrier_effect is not None else {}
                    if value.get("kind") != "fixed" or type(value.get("value")) not in (int, float):
                        return blocked("parallel_time_barrier_unresolved")
                    time = float(value["value"])
                times.append(time)
            context = continuation.child_context(
                f"{request.invocation_id}:parallel:{request.graph_node_id}:{ordinal}",
                context_values={**request.context_values, "actor_id": actor_id, "selected_target_ids": list(selected)},
            )
            try:
                fact = parallel_action_target_fact(
                    parent_fact=invocation.accepted_action_target_fact,
                    execution_token=invocation.action_execution_token,
                    command=nested.action_command, definition=invocation.action_definition,
                    action_event=event_definition,
                )
                scope = _issue_action_window_expected_scope(
                    execution_token=invocation.action_execution_token,
                    actor_id=actor_id, action_id=invocation.ability_id,
                    action_level=invocation.ability_level,
                    canonical_action_event_id=event_definition.action_event_id,
                    impact_fingerprint=fact.impact_fingerprint,
                    event_id=context.invocation_id, window=f"ability_callback:{task.callback_kind}",
                    step_id=f"ability:{task.callback_kind}", step_index=0,
                )
                nested = replace(nested, accepted_action_target_fact=fact,
                                 admitted_action_target_fact=fact.bind_invocation(scope),
                                 expected_action_window_scope=scope)
            except ValueError as exc:
                return blocked(str(exc))
            entries.append((graph, context, self._formal_task_graph_hooks(invocation=nested), tuple(times)))
            if actor_id != invocation.actor_id:
                children.append((nested, context.invocation_id, ordinal))
        current = state
        mutations, events, rng_events, records, projections = [], [], [], [], []

        def dispatch_window(child, child_id, window):
            if (self.event_dispatcher is None or invocation.accepted_action_target_fact is None
                    or invocation.action_execution_token is None):
                raise ValueError("parallel_attack_completion_authority_missing")
            if event_definition is None:
                raise ValueError("parallel_attack_action_event_missing")
            event, scope = parallel_attack_window_event(
                parent_fact=invocation.accepted_action_target_fact,
                execution_token=invocation.action_execution_token,
                command=child.action_command, definition=child.action_definition,
                action_event=event_definition, target_resolution=child.target_resolution,
                invocation_id=child_id, window=window,
            )
            return self.event_dispatcher.dispatch_action_window_listeners(
                current, event=event, damage_window_ledger=None,
                nested_ability_provider=self.formal_status_nested_ability_provider(),
                expected_window_scope=scope,
            )

        for index, (child, child_id, ordinal) in enumerate(children):
            try:
                dispatch = dispatch_window(child, child_id, "before_attack")
            except ValueError as exc:
                return blocked(str(exc))
            if dispatch.errors:
                return blocked("parallel_attack_before_window_blocked:" + ",".join(dispatch.errors))
            current = dispatch.after_state
            invocation.dispatched_event_ids.update(dispatch.dispatched_event_ids)
            mutations.extend(dispatch.mutations)
            events.extend(dispatch.events)
            rng_events.extend(dispatch.rng_events)
            records.extend(_task_graph_settlement_records(list(dispatch.records)))
            projections.extend(dispatch.task_graph_projections)
            child = replace(child, action_damage_modifiers=(*child.action_damage_modifiers, *dispatch.damage_modifiers))
            children[index] = (child, child_id, ordinal)
            graph, context, _, times = entries[ordinal]
            entries[ordinal] = (graph, context, self._formal_task_graph_hooks(invocation=child), times)
        execution = self.task_graph_executor.execute_interleaved(current, tuple(entries))
        if not execution.ok:
            return blocked(execution.errors[0] if execution.errors else "parallel_ability_execution_blocked")
        current = execution.after_state
        mutations.extend(execution.mutations)
        events.extend(execution.events)
        rng_events.extend(execution.rng_events)
        records.extend(execution.settlement_records)
        projections.extend(execution.node_projections)
        # ponytail: child completion follows the whole parallel group. Early
        # per-branch completion windows require resumable callback scheduling.
        for child, child_id, _ in children:
            try:
                dispatch = dispatch_window(child, child_id, "after_attack")
            except ValueError as exc:
                return blocked(str(exc))
            if dispatch.errors:
                return blocked("parallel_attack_completion_blocked:" + ",".join(dispatch.errors))
            current = dispatch.after_state
            invocation.dispatched_event_ids.update(dispatch.dispatched_event_ids)
            mutations.extend(dispatch.mutations)
            events.extend(dispatch.events)
            rng_events.extend(dispatch.rng_events)
            records.extend(_task_graph_settlement_records(list(dispatch.records)))
            projections.extend(dispatch.task_graph_projections)
        return TaskGraphLeafResult(
            "resolved", tuple(mutations), tuple(events), (*target_rng, *rng_events),
            tuple(records), child_projections=tuple(projections),
        )

    def _nested_caster_invocation(
        self,
        request: TaskGraphHookRequest,
        state: BattleState,
        task: AbilityTaskIR,
        invocation: _FormalAbilityInvocation,
    ) -> tuple[_FormalAbilityInvocation | None, str]:
        """TriggerAbility.TargetType names who casts the nested ability."""

        effect = self.rules.effect(task.effect_id) if task.effect_id else None
        standard = effect.payload.get("standard") if effect is not None else None
        if not isinstance(standard, dict) or standard.get("target_alias") in {None, "", "Caster"}:
            return None, ""
        reference = (standard.get("target_expression_refs") or {}).get("TargetType")
        expression_id = reference.get("target_expression_id") if isinstance(reference, dict) else None
        expression = self.rules.target_expression(str(expression_id or ""))
        if expression is None or expression.coverage_status != "executable":
            return None, "ability_task_graph_nested_caster_expression_not_admitted"
        scoped = _task_graph_target_resolution(request, invocation.target_resolution)
        resolved = self.targets.resolve_target_expression(
            state,
            expression,
            context=TargetEvaluationContext(
                caster_id=invocation.actor_id,
                effect_owner_id=invocation.actor_id,
                parameter_entity_ids=((scoped.primary or invocation.actor_id),),
                selected_target_ids=scoped.selected,
                current_target_id=scoped.primary,
                turn_owner_id=committed_turn_owner_id(state),
                template_entity_ids=request.template_target_ids,
            ),
            target_resolution=scoped,
            condition_event_payload=_formal_event_payload(invocation, scoped.primary, scoped),
            binding_sources=_binding_sources(
                self.rules, state, invocation.actor_id, scoped.primary,
                action_level=invocation.ability_level, action_id=invocation.ability_id,
                current_action_trigger_key=_formal_action_trigger_key(invocation),
                ability_instance_id=_ability_instance_id(state, invocation),
                template_binding_sources=invocation.template_binding_sources,
            ),
        )
        if not resolved.resolved:
            return None, resolved.blocked_reason or "ability_task_graph_nested_caster_unresolved"
        if len(resolved.target_ids) > 1:
            return None, "ability_task_graph_nested_caster_ambiguous"
        if not resolved.target_ids or resolved.target_ids[0] == invocation.actor_id:
            return None, ""
        actor_id = resolved.target_ids[0]
        return replace(
            invocation,
            actor_id=actor_id,
            admitted_action_target_fact=None,
            expected_action_window_scope=None,
            action_damage_modifiers=(),
            action_command=(
                replace(invocation.action_command, actor_id=actor_id)
                if invocation.action_command is not None else None
            ),
            # The queue entry identity is unchanged; only its nested caster moves.
            standalone=(
                replace(invocation.standalone, actor_id=actor_id)
                if invocation.standalone is not None else None
            ),
        ), ""

    def _resolve_formal_nested_graph(
        self,
        request: TaskGraphHookRequest,
        _state: BattleState,
        *,
        invocation: _FormalAbilityInvocation | None = None,
    ) -> TaskGraphGraphResult:
        task, reason = self._formal_task_for_request(request)
        if task is None:
            return TaskGraphGraphResult("blocked", blocked_reason=reason)
        callback_kind = task.callback_kind
        ability_refs = tuple(
            reference
            for reference in request.references
            if reference.reference_kind == "ability"
        )
        if len(ability_refs) != 1 or ability_refs[0].resolution_status != "resolved":
            return TaskGraphGraphResult(
                "blocked",
                blocked_reason="ability_task_graph_nested_reference_not_resolved",
            )
        reference = ability_refs[0]
        phase_ids: tuple[str, ...]
        if task.linked_ability_phase_id:
            if reference.definition_id != task.linked_ability_phase_id:
                return TaskGraphGraphResult(
                    "blocked",
                    blocked_reason="ability_task_graph_nested_phase_identity_mismatch",
                )
            phase_ids = (task.linked_ability_phase_id,)
        elif task.linked_standalone_graph_id:
            if reference.definition_id != task.linked_standalone_graph_id:
                return TaskGraphGraphResult(
                    "blocked",
                    blocked_reason="ability_task_graph_nested_standalone_identity_mismatch",
                )
            standalone = self.rules.standalone_ability_graph(
                task.linked_standalone_graph_id
            )
            if standalone is None:
                return TaskGraphGraphResult(
                    "blocked",
                    blocked_reason="ability_task_graph_nested_standalone_missing",
                )
            phase_ids = standalone.phase_ids
        else:
            return TaskGraphGraphResult(
                "blocked",
                blocked_reason="ability_task_graph_nested_target_missing",
            )
        candidates: list[TaskGraphIR] = []
        for phase_id in phase_ids:
            phase = self.rules.ability_phase(phase_id)
            if phase is None or phase.invocation_role != "nested_only":
                continue
            if not any(
                task.callback_kind == callback_kind
                for task in self.rules.ability_tasks_for_phase(phase_id)
            ):
                continue
            graph_result = self.rules.query_formal_task_graph(
                "ability_phase_callback",
                phase_id,
                callback_kind,
                (
                    task.task_id
                    for task in self.rules.ability_tasks_for_phase(phase_id)
                    if task.callback_kind == callback_kind
                ),
            )
            if graph_result.status != "resolved" or type(graph_result.value) is not TaskGraphIR:
                return TaskGraphGraphResult(
                    "blocked",
                    blocked_reason=graph_result.blocked_reason
                    or "ability_task_graph_nested_graph_missing",
                )
            candidates.append(graph_result.value)
        if not candidates and phase_ids and all(
            (phase := self.rules.ability_phase(phase_id)) is not None
            and phase.invocation_role == "non_gameplay_noop"
            for phase_id in phase_ids
        ):
            return TaskGraphGraphResult("resolved", reference.definition_id, noop=True)
        trigger_effect = self.rules.effect(task.effect_id) if task.effect_id else None
        if (trigger_effect is not None and isinstance(trigger_effect.payload, dict)
                and trigger_effect.payload.get("DynamicValues")):
            # 调用参数不会转发给子能力，只能用于无玩法的表现能力。
            return TaskGraphGraphResult(
                "blocked", blocked_reason="trigger_ability_dynamic_values_not_forwarded",
            )
        if len(candidates) != 1:
            return TaskGraphGraphResult(
                "blocked",
                blocked_reason=(
                    "ability_task_graph_nested_callback_missing"
                    if not candidates
                    else "ability_task_graph_nested_callback_ambiguous"
                ),
            )
        nested_hooks = None
        if invocation is not None:
            nested_invocation, caster_reason = self._nested_caster_invocation(
                request, _state, task, invocation,
            )
            if caster_reason:
                return TaskGraphGraphResult("blocked", blocked_reason=caster_reason)
            if nested_invocation is not None:
                nested_hooks = self._formal_task_graph_hooks(invocation=nested_invocation)
        return TaskGraphGraphResult(
            "resolved", reference.definition_id, candidates[0], hooks=nested_hooks,
        )

    def _formal_task_for_request(
        self,
        request: TaskGraphHookRequest,
    ) -> tuple[AbilityTaskIR | None, str]:
        task = self.rules.ability_task(request.formal_task_id)
        graph_result = self.rules.query_task_graph(request.graph_id)
        graph = graph_result.value
        node_result = self.rules.query_task_graph_node(request.graph_node_id)
        node = node_result.value
        if task is None:
            return None, "ability_task_graph_formal_task_missing"
        if (
            graph_result.status != "resolved"
            or type(graph) is not TaskGraphIR
            or node_result.status != "resolved"
            or node is None
            or node.graph_id != request.graph_id
            or node.formal_task_id != request.formal_task_id
            or task.phase_id != graph.owner_id
            or task.callback_kind != graph.callback_kind
        ):
            return None, "ability_task_graph_formal_task_identity_mismatch"
        return task, ""

    @staticmethod
    def _formal_callback_blocked(
        state: BattleState,
        callback_kind: str,
        invocation: _FormalAbilityInvocation,
        reason: str,
        *,
        node_results: tuple[ExecutionNodeResult, ...] = (),
    ) -> AbilityTaskExecutionResult:
        blocked_node = ExecutionNodeResult(
            node_kind="ability_task_graph_callback",
            node_id=(
                f"ability_task_graph_callback:{state.event_index}:"
                f"{invocation.actor_id}:{invocation.ability_id}:{callback_kind}"
            ),
            status="blocked",
            reason_code=reason,
        )
        return AbilityTaskExecutionResult(
            after_state=state,
            records=(
                SettlementRecord(
                    record_type="ability_task_graph_blocked",
                    source="ability_task_system",
                    process_only=True,
                    payload={
                        "invocation_kind": invocation.invocation_kind,
                        "actor_id": invocation.actor_id,
                        "ability_id": invocation.ability_id,
                        "ability_level": invocation.ability_level,
                        "callback_kind": callback_kind,
                        "reason": reason,
                    },
                    trace={},
                ).to_json(),
            ),
            node_results=(*node_results, blocked_node),
        )

    @staticmethod
    def _formal_action_input_blocked(
        state: BattleState,
        callback_kind: str,
        command: ActionCommand,
        reason: str,
    ) -> AbilityTaskExecutionResult:
        return AbilityTaskExecutionResult(
            after_state=state,
            records=(
                SettlementRecord(
                    record_type="ability_task_graph_blocked",
                    source="ability_task_system",
                    process_only=True,
                    payload={
                        "invocation_kind": "action",
                        "actor_id": command.actor_id,
                        "ability_id": command.action_id,
                        "ability_level": command.action_level,
                        "callback_kind": callback_kind,
                        "reason": reason,
                    },
                    trace={},
                ).to_json(),
            ),
            node_results=(
                ExecutionNodeResult(
                    node_kind="ability_task_graph_callback",
                    node_id=(
                        f"ability_task_graph_callback:{state.event_index}:"
                        f"{command.actor_id}:{command.action_id}:{callback_kind}"
                    ),
                    status="blocked",
                    reason_code=reason,
                ),
            ),
        )

    def _execute_admitted_queue_standalone(
        self,
        state: BattleState,
        *,
        invocation: StandaloneAbilityInvocation,
    ) -> AbilityTaskExecutionResult:
        if type(invocation) is not StandaloneAbilityInvocation:
            raise TypeError("standalone ability execution requires typed invocation")
        resolution = self.rules.queue_resolution(invocation.queue_resolution_id)
        graph = self.rules.standalone_ability_graph(invocation.graph_id)
        resolved_graph_id = (
            str(resolution.resolved_ids.get("standalone_ability_graph_id") or "")
            if resolution is not None
            else ""
        )
        if (
            resolution is None
            or resolution.coverage_status != "executable"
            or resolution.resolved_kind != "standalone_ability_graph"
            or resolution.queue_intent_id != invocation.queue_intent_id
            or resolved_graph_id != invocation.graph_id
        ):
            return self._standalone_invocation_blocked(
                state, invocation, "standalone_queue_resolution_identity_mismatch"
            )
        if graph is None:
            return self._standalone_invocation_blocked(
                state, invocation, "standalone_ability_graph_missing"
            )
        if (
            graph.coverage_status != "executable"
            or graph.blocked_reason
            or resolution.action_or_ability_ref != graph.ability_name
        ):
            return self._standalone_invocation_blocked(
                state, invocation, "standalone_ability_graph_not_admitted"
            )
        resolved_phase_ids = resolution.resolved_ids.get("phase_ids")
        if (
            not isinstance(resolved_phase_ids, (list, tuple))
            or tuple(resolved_phase_ids) != graph.phase_ids
        ):
            return self._standalone_invocation_blocked(
                state, invocation, "standalone_ability_phase_ledger_mismatch"
            )
        phases = tuple(
            phase
            for phase_id in graph.phase_ids
            if (phase := self.rules.ability_phase(phase_id)) is not None
        )
        if (
            len(phases) != len(graph.phase_ids)
            or tuple(phase.phase_id for phase in phases) != graph.phase_ids
            or any(phase.ability_name != graph.ability_name for phase in phases)
        ):
            return self._standalone_invocation_blocked(
                state, invocation, "standalone_ability_formal_root_mismatch"
            )
        # Character standalone graphs are materialized formal roots. Shared and
        # monster inserted abilities keep their explicit external legacy topology
        # and execute leaf tasks from their admitted queue resolution ledger.
        external_legacy_graph = graph.source_mode in {
            "mainline_monster",
            "mainline_common_additional",
            "mainline_battle_event",
            "mainline_stage",
        }
        allowed_roles = (
            {"standalone_root", "external_legacy"}
            if external_legacy_graph
            else {"standalone_root"}
        )
        if any(phase.invocation_role not in allowed_roles for phase in phases):
            return self._standalone_invocation_blocked(
                state, invocation, "standalone_ability_formal_root_mismatch"
            )
        phase_task_ids = tuple(
            task_id for phase in phases for task_id in phase.task_ids
        )
        resolved_task_ids = resolution.resolved_ids.get("task_ids")
        resolved_executable_task_ids = resolution.resolved_ids.get(
            "executable_task_ids"
        )
        if (
            graph.task_ids != phase_task_ids
            or not isinstance(resolved_task_ids, (list, tuple))
            or tuple(resolved_task_ids) != graph.task_ids
            or not isinstance(resolved_executable_task_ids, (list, tuple))
            or tuple(resolved_executable_task_ids) != graph.executable_task_ids
        ):
            return self._standalone_invocation_blocked(
                state, invocation, "standalone_ability_task_ledger_mismatch"
            )
        if invocation.actor_id not in state.units or any(
            target_id not in state.units for target_id in invocation.target_ids
        ):
            return self._standalone_invocation_blocked(
                state, invocation, "standalone_ability_combatant_identity_missing"
            )
        entries: list[tuple[AbilityPhaseIR, str]] = []
        for phase in phases:
            callbacks: set[str] = set()
            for task_id in phase.task_ids:
                task = self.rules.ability_task(task_id)
                if task is None or task.phase_id != phase.phase_id:
                    return self._standalone_invocation_blocked(
                        state, invocation, "standalone_ability_task_ledger_mismatch"
                    )
                callbacks.add(task.callback_kind)
            unknown_callbacks = callbacks - set(_STANDALONE_CALLBACK_ORDER)
            if unknown_callbacks:
                return self._standalone_invocation_blocked(
                    state,
                    invocation,
                    "standalone_ability_callback_lifecycle_not_admitted:"
                    + ",".join(sorted(unknown_callbacks)),
                )
            entries.extend(
                (phase, callback)
                for callback in _STANDALONE_CALLBACK_ORDER
                if callback in callbacks
            )
        if not entries:
            return self._standalone_invocation_blocked(
                state, invocation, "standalone_ability_callback_entry_missing"
            )
        target_resolution = TargetResolution(
            requested=invocation.target_ids,
            legal=invocation.target_ids,
            selected=invocation.target_ids,
            rejected=(),
            reason="queue_standalone_targets_from_admitted_queue",
            source="queue_resolution",
            metadata={
                "queue_entry_id": invocation.queue_entry_id,
                "queue_resolution_id": invocation.queue_resolution_id,
            },
        )
        formal_invocation = _FormalAbilityInvocation(
            "queue_standalone",
            invocation.actor_id,
            invocation.graph_id,
            0,
            target_resolution,
            standalone=invocation,
        )
        if graph.action_id:
            actor = state.units[invocation.actor_id]
            card = self.rules.character_data_card(str(actor.flags.get("character_data_card_id") or ""))
            levels = actor.flags.get("effective_skill_levels_by_action_id", {})
            level = levels.get(graph.action_id) if isinstance(levels, dict) else None
            definition = self.rules.action_definition(graph.action_id, level) if type(level) is int else None
            if (actor.flags.get("build_mode") != "assembled_character_build"
                    or actor.flags.get("character_build_battle_admission_status") != "admitted"
                    or card is None or card.entity_ref != actor.template_id
                    or graph.action_id.removeprefix("avatar_skill:") not in card.skill_ids
                    or definition is None or definition.coverage_status != "executable"):
                return self._standalone_invocation_blocked(state, invocation, "queued_character_skill_binding_not_admitted")
            command = ActionCommand(invocation.actor_id, graph.action_id, level,
                target_ids=invocation.target_ids, source="queue", metadata={
                    "parent_queue_entry_id": invocation.queue_entry_id,
                    "queue_intent_id": invocation.queue_intent_id,
                    "queue_resolution_id": invocation.queue_resolution_id,
                    "is_insert_action": True,
                })
            formal_invocation = replace(formal_invocation,
                action_command=command, action_definition=replace(definition, source_mode="queue_standalone"),
                ability_level=level)
        if external_legacy_graph and any(
            phase.invocation_role == "external_legacy" for phase in phases
        ):
            result = self._execute_external_legacy_standalone_entries(
                state,
                entries=tuple(entries),
                invocation=formal_invocation,
            )
        else:
            result = self._execute_formal_entries(
                state,
                entries=tuple(entries),
                invocation=formal_invocation,
            )
        if any(item.status != "complete" for item in result.node_results):
            return result
        execution_record = SettlementRecord(
            record_type="standalone_ability_execution",
            source="ability_task_system",
            process_only=True,
            payload={
                "invocation": invocation.to_json(),
                "ability_name": graph.ability_name,
                "phase_ids": list(graph.phase_ids),
            },
            trace={"standalone_graph_source": graph.source.to_json()},
        ).to_json()
        return replace(result, records=(execution_record, *result.records))

    def _execute_external_legacy_standalone_entries(
        self,
        state: BattleState,
        *,
        entries: tuple[tuple[AbilityPhaseIR, str], ...],
        invocation: "_FormalAbilityInvocation",
    ) -> AbilityTaskExecutionResult:
        """Execute shared/monster inserted ability tasks without a task graph.

        These definitions keep their explicit external legacy topology. The
        recursive walker honours PredicateTaskList branches, executes leaves
        through the formal leaf boundary and records strictly admitted
        process-only tasks (presentation, scoring) as non-gameplay skips. Any
        blocked, unknown, or non-process-only unexecutable task stays
        fail-closed.
        """

        current = state
        mutations: list[Mutation] = []
        events: list[GameEvent] = []
        rng_events: list[RNGEvent] = []
        records: list[dict[str, JSONValue]] = []
        node_results: list[ExecutionNodeResult] = []
        dispatched = set(invocation.dispatched_event_ids)

        def blocked(reason: str) -> AbilityTaskExecutionResult:
            return self._standalone_invocation_blocked(
                state, invocation.standalone, reason
            )

        def run_task(task: AbilityTaskIR, children: dict[str, list[AbilityTaskIR]]) -> str:
            nonlocal current
            animation_children = tuple(children.get(task.task_id, ()))
            if task.opcode == "TriggerAnimStateWithMove" and animation_children:
                if task.execution_mode != "runtime_effect":
                    # A presentation wrapper never owns executable children.
                    return (
                        "external_legacy_anim_wrapper_execution_mode_not_admitted:"
                        f"{task.execution_mode}"
                    )
                # The wrapper owns one ordered gameplay unit. Parent admission,
                # the standard EffectIR contract and the complete direct-child
                # ledger are proved before the first child runs, so a blocked or
                # incomplete wrapper can never leak an already-lowered sibling.
                wrapper_blocked = self._external_legacy_anim_wrapper_blocked_reason(
                    task, children
                )
                if wrapper_blocked:
                    return (
                        "external_legacy_anim_wrapper_not_admitted:"
                        f"{wrapper_blocked}"
                    )
                for child in self._external_legacy_anim_wrapper_child_tasks(
                    task, children
                ):
                    reason = run_task(child, children)
                    if reason:
                        return reason
                node_results.append(
                    ExecutionNodeResult(
                        "external_ability_anim_wrapper", task.task_id, "complete"
                    )
                )
                return ""
            if (
                task.opcode == "TriggerAnimStateWithMove"
                and task.execution_mode == "runtime_effect"
                and task.coverage_status == "executable"
            ):
                # A runtime wrapper is a control node, never a standalone leaf.
                return (
                    "external_legacy_anim_wrapper_child_ledger_missing:"
                    f"{task.task_path}"
                )
            if is_process_only_ability_task(task):
                process_only_blocker = ability_task_runtime_blocked_reason(
                    self.rules,
                    task,
                    topology_authority="external_legacy",
                )
                if process_only_blocker:
                    return (
                        "external_legacy_process_only_task_not_admitted:"
                        f"{task.opcode}:{task.task_path}:{process_only_blocker}"
                    )
                records.append(
                    _task_process_record(
                        task,
                        ok=True,
                        blocked_reason=(
                            "external_legacy_non_gameplay_task_skipped:"
                            f"{task.blocked_reason or 'process_only'}"
                        ),
                        effect_id=task.effect_id,
                        effect_opcode=task.opcode,
                        effect_coverage=task.coverage_status,
                    )
                )
                node_results.append(
                    ExecutionNodeResult(
                        "external_ability_process_only", task.task_id, "complete"
                    )
                )
                return ""
            if task.coverage_status != "executable":
                return (
                    "external_legacy_required_task_blocked:"
                    f"{task.opcode}:{task.task_path}:"
                    f"{task.blocked_reason or task.coverage_status}"
                )
            if task.opcode == "PredicateTaskList":
                passed, reason, _evidence = self._evaluate_formal_ability_condition(
                    current,
                    task,
                    invocation=invocation,
                    primary_target=invocation.target_resolution.primary,
                    target_resolution=invocation.target_resolution,
                )
                if passed is None:
                    return f"external_legacy_predicate_blocked:{reason}"
                taken = "success" if passed else "failed"
                for child in sorted(
                    (item for item in children.get(task.task_id, ())
                     if item.branch == taken),
                    key=lambda item: (item.task_index, item.task_path, item.task_id),
                ):
                    reason = run_task(child, children)
                    if reason:
                        return reason
                return ""
            if task.opcode in {"LoopExecuteTaskListWithInterval"}:
                return "external_legacy_task_loop_not_admitted"
            if task.opcode == "TriggerAbility":
                if _external_legacy_trigger_is_process_only(self.rules, task):
                    records.append(
                        _task_process_record(
                            task,
                            ok=True,
                            blocked_reason="external_legacy_presentation_trigger_skipped",
                            effect_id=task.effect_id,
                            effect_opcode=task.opcode,
                            effect_coverage="process_only",
                        )
                    )
                    node_results.append(
                        ExecutionNodeResult(
                            "external_ability_process_only", task.task_id, "complete"
                        )
                    )
                    return ""
                return "external_legacy_trigger_ability_not_admitted"
            if task.opcode == "SummonMonster":
                _summon_state, task_mutations, task_events, task_rng, task_records = (
                    self.execute_summon_monster_task(
                        current,
                        task,
                        actor_id=invocation.actor_id,
                        dispatched_event_ids=dispatched,
                    )
                )
                blocker = _ability_task_records_blocked_reason(task_records)
                if blocker:
                    return f"external_legacy_summon_blocked:{blocker}"
                current = self.reducer.apply_all(current, tuple(task_mutations))
                mutations.extend(task_mutations)
                rng_events.extend(task_rng)
                records.extend(task_records)
                events.extend(task_events)
                if self.event_dispatcher is not None:
                    for emitted in task_events:
                        if str(emitted.to_json()["event_id"]) in dispatched:
                            continue
                        dispatched_result = self.event_dispatcher.dispatch_event(
                            current, event=emitted
                        )
                        current = dispatched_result.after_state
                        dispatched.update(dispatched_result.dispatched_event_ids)
                        mutations.extend(dispatched_result.mutations)
                        events.extend(dispatched_result.events)
                        rng_events.extend(dispatched_result.rng_events)
                        records.extend(dispatched_result.records)
                        if dispatched_result.errors:
                            return (
                                "external_legacy_summon_listener_blocked:"
                                + ",".join(dispatched_result.errors)
                            )
                node_results.append(
                    ExecutionNodeResult(
                        "external_ability_leaf", task.task_id, "complete"
                    )
                )
                return ""
            if self.rules.damage_emissions_for_task(task.task_id):
                damage_result = self._execute_external_legacy_damage_task(
                    current,
                    task,
                    invocation=invocation,
                    dispatched_event_ids=dispatched,
                )
                if isinstance(damage_result, str):
                    return damage_result
                (
                    current,
                    task_mutations,
                    task_events,
                    task_rng,
                    task_records,
                ) = damage_result
                blocker = _ability_task_records_blocked_reason(task_records)
                if blocker:
                    return (
                        "external_legacy_task_blocked:"
                        f"{task.opcode}:{task.task_path}:{blocker}"
                    )
                mutations.extend(task_mutations)
                events.extend(task_events)
                rng_events.extend(task_rng)
                records.extend(task_records)
                node_results.append(
                    ExecutionNodeResult(
                        "external_ability_damage", task.task_id, "complete"
                    )
                )
                return ""
            # The leaf updates its invocation's dispatched-event identity before
            # the listener runs.  Give it a candidate copy so a blocked call
            # cannot publish those identities into the caller or this walk's
            # committed set.
            leaf_dispatched = set(dispatched)
            leaf_invocation = replace(
                invocation, dispatched_event_ids=leaf_dispatched
            )
            leaf_result = self._execute_effect_leaf_task(
                current,
                task,
                invocation=leaf_invocation,
                primary_target=invocation.target_resolution.primary,
                target_resolution=invocation.target_resolution,
                reduce_candidate=False,
                created_unit_ids=None,
                task_graph_continuation=None,
            )
            blocker = _ability_task_records_blocked_reason(leaf_result[4])
            if blocker:
                return (
                    f"external_legacy_task_blocked:{task.opcode}:"
                    f"{task.task_path}:{task.effect_id}:{blocker}"
                )
            (
                current,
                task_mutations,
                task_events,
                task_rng,
                task_records,
                _projections,
            ) = self._dispatch_effect_leaf_events(
                current,
                task,
                leaf_result,
                leaf_dispatched,
                None,
                None,
            )
            blocker = _ability_task_records_blocked_reason(task_records)
            if blocker:
                return (
                    f"external_legacy_task_blocked:{task.opcode}:"
                    f"{task.task_path}:{blocker}"
                )
            dispatched.update(leaf_dispatched)
            mutations.extend(task_mutations)
            events.extend(task_events)
            rng_events.extend(task_rng)
            records.extend(task_records)
            node_results.append(
                ExecutionNodeResult(
                    "external_ability_leaf", task.task_id, "complete"
                )
            )
            return ""

        for phase, callback_kind in entries:
            phase_tasks = [
                task
                for task in self.rules.ability_tasks_for_phase(phase.phase_id)
                if task.callback_kind == callback_kind
            ]
            children: dict[str, list[AbilityTaskIR]] = {}
            for task in phase_tasks:
                children.setdefault(task.parent_task_id, []).append(task)
            roots = sorted(
                children.get("", ()),
                key=lambda item: (item.task_index, item.task_path, item.task_id),
            )
            if not roots:
                return blocked(
                    "external_standalone_phase_requires_materialized_task_graph"
                )
            for root in roots:
                reason = run_task(root, children)
                if reason:
                    return blocked(reason)
        # Only a fully successful call publishes dispatch identity; every
        # blocked return above keeps the caller's set untouched.
        invocation.dispatched_event_ids.update(dispatched)
        return AbilityTaskExecutionResult(
            after_state=current,
            mutations=tuple(mutations),
            events=tuple(events),
            rng_events=tuple(rng_events),
            records=tuple(records),
            node_results=tuple(node_results),
            dispatched_event_ids=frozenset(dispatched),
        )

    def _external_legacy_anim_wrapper_blocked_reason(
        self,
        task: AbilityTaskIR,
        children: dict[str, list[AbilityTaskIR]],
    ) -> str:
        """Prove one animation wrapper unit before any child executes.

        The formal shared-task contract verifies the parent's execution mode,
        coverage, standard EffectIR payload and direct-child ledger. The walker
        additionally verifies that the phase topology it is about to run is
        exactly that ledger and that every direct child is admitted, so a
        blocked or incomplete control node executes nothing at all.
        """
        reason = ability_task_runtime_blocked_reason(
            self.rules,
            task,
            topology_authority="external_legacy",
        )
        if reason:
            return reason
        ledger = tuple(getattr(task, "child_task_ids", ()) or ())
        direct = tuple(children.get(task.task_id, ()))
        if not ledger:
            return "anim_wrapper_child_ledger_missing"
        if len(direct) != len(ledger) or {
            item.task_id for item in direct
        } != set(ledger):
            return "anim_wrapper_child_ledger_incomplete"
        by_id = {item.task_id: item for item in direct}
        for child_task_id in ledger:
            child = by_id.get(child_task_id)
            if child is None:
                return f"anim_wrapper_child_task_missing:{child_task_id}"
            if child.parent_task_id != task.task_id:
                return f"anim_wrapper_child_parent_mismatch:{child_task_id}"
            child_reason = ability_task_runtime_blocked_reason(
                self.rules,
                child,
                topology_authority="external_legacy",
            )
            if child_reason:
                return (
                    f"anim_wrapper_child_not_admitted:{child_task_id}:"
                    f"{child_reason}"
                )
        return ""

    def _external_legacy_anim_wrapper_child_tasks(
        self,
        task: AbilityTaskIR,
        children: dict[str, list[AbilityTaskIR]],
    ) -> tuple[AbilityTaskIR, ...]:
        """Resolve the wrapper's formal direct-child ledger in source order."""
        by_id = {item.task_id: item for item in children.get(task.task_id, ())}
        return tuple(
            by_id[child_task_id]
            for child_task_id in (getattr(task, "child_task_ids", ()) or ())
        )

    def _execute_external_legacy_damage_task(
        self,
        state: BattleState,
        task: AbilityTaskIR,
        *,
        invocation: "_FormalAbilityInvocation",
        dispatched_event_ids: set[str] | None = None,
    ) -> (
        tuple[
            BattleState,
            list[Mutation],
            list[GameEvent],
            list[RNGEvent],
            list[dict[str, JSONValue]],
        ]
        | str
    ):
        """Run one admitted inserted-ability damage leaf on its own packet.

        The source ability keeps the external legacy task topology, so its
        damage leaves still go through the shared damage system with the
        caster's formal spawn panel and card-level SkillParam bindings.
        """

        emissions = tuple(
            emission
            for emission in self.rules.damage_emissions_for_task(task.task_id)
            if emission.action_id == task.action_id
            and emission.level == task.level
        )
        if not emissions:
            return "external_legacy_damage_emission_missing"
        attack_types = {
            emission.scaling_basis_expr.get("attack_type")
            for emission in emissions
        }
        if len(attack_types) != 1 or not all(
            isinstance(value, str) and value for value in attack_types
        ):
            return "external_legacy_damage_attack_type_binding_missing"
        definition = ActionDefinitionIR(
            f"ability_damage:{task.task_id}",
            task.action_id,
            invocation.ability_level,
            next(iter(attack_types)),
            "standalone_ability",
            "single" if invocation.target_resolution.selected else "none",
            0,
            0,
            0,
            0,
            (),
            (),
            (),
            None,
            task.source,
            coverage_status="executable",
            damage_kind="hp_damage",
            damage_formula_family="direct",
            source_mode="queue_standalone",
        )
        command = ActionCommand(
            invocation.actor_id,
            task.action_id,
            invocation.ability_level,
            target_ids=invocation.target_resolution.selected,
            source=(
                "queue"
                if invocation.invocation_kind == "queue_standalone"
                else "system"
            ),
            metadata={
                "ability_task_execution_path": invocation.execution_path,
                "ability_task_iteration_index": invocation.iteration_index,
            },
        )
        (
            state_after,
            mutations,
            events,
            rng_events,
            records,
            _projections,
        ) = self._execute_damage_task(
            state,
            task,
            command=command,
            action_definition=definition,
            primary_target=invocation.target_resolution.primary,
            target_resolution=invocation.target_resolution,
            task_graph_continuation=None,
            nested_ability_hooks=None,
            dispatched_event_ids=(
                dispatched_event_ids
                if dispatched_event_ids is not None
                else invocation.dispatched_event_ids
            ),
            packet_sequence_id=_ability_instance_id(state, invocation),
        )
        return state_after, mutations, events, rng_events, records

    @staticmethod
    def _standalone_invocation_blocked(
        state: BattleState,
        invocation: StandaloneAbilityInvocation,
        reason: str,
    ) -> AbilityTaskExecutionResult:
        return AbilityTaskExecutionResult(
            after_state=state,
            records=(
                SettlementRecord(
                    record_type="standalone_ability_blocked",
                    source="ability_task_system",
                    process_only=True,
                    payload={"reason": reason, "invocation": invocation.to_json()},
                    trace={},
                ).to_json(),
            ),
            node_results=(
                ExecutionNodeResult(
                    node_kind="ability_graph",
                    node_id=invocation.graph_id,
                    status="blocked",
                    reason_code=reason,
                ),
            ),
        )

    def _execute_legacy_standalone(
        self,
        state: BattleState,
        *,
        phases: tuple[AbilityPhaseIR, ...],
        actor_id: str,
        target_ids: tuple[str, ...],
        queue_entry: dict[str, JSONValue],
        queue_resolution: dict[str, JSONValue],
        depth: int = 0,
    ) -> AbilityTaskExecutionResult:
        if not phases:
            return AbilityTaskExecutionResult(
                after_state=state,
                records=(
                    SettlementRecord(
                        record_type="standalone_ability_blocked",
                        source="ability_task_system",
                        process_only=True,
                        payload={
                            "reason": "standalone_ability_phases_missing",
                            "queue_entry": queue_entry,
                            "queue_resolution": queue_resolution,
                        },
                        trace={},
                    ).to_json(),
                ),
                node_results=(
                    ExecutionNodeResult(
                        node_kind="ability_graph",
                        node_id=str(queue_entry.get("entry_id") or "standalone_ability"),
                        status="blocked",
                        reason_code="standalone_ability_phases_missing",
                    ),
                ),
            )
        ability_name = phases[0].ability_name
        action_id = f"standalone_ability:{ability_name}"
        action_definition = ActionDefinitionIR(
            definition_id=f"standalone_action_def:{ability_name}",
            action_id=action_id,
            level=0,
            attack_type="StandaloneAbility",
            skill_effect="standalone_ability",
            target_mode="single" if target_ids else "none",
            bp_need=0.0,
            bp_add=0.0,
            sp_base=0.0,
            sp_multiple_ratio=0.0,
            param_list=(),
            show_stance_list=(),
            show_damage_list=(),
            stance_damage_type=None,
            source=phases[0].source if phases else IRSource("", "", ""),
            coverage_status="executable",
            damage_kind="none",
            damage_formula_family="none",
            element_type=None,
            source_mode="queue_standalone",
        )
        command = ActionCommand(
            actor_id=actor_id,
            action_id=action_id,
            action_level=0,
            target_ids=target_ids,
            source="queue",
            queue_name=str(queue_entry.get("queue_name") or ""),
            metadata={
                "parent_queue_entry_id": str(queue_entry.get("entry_id") or ""),
                "queue_intent_id": str(queue_entry.get("queue_intent_id") or ""),
                "queue_resolution_id": str(queue_resolution.get("queue_resolution_id") or ""),
                "standalone_ability_name": ability_name,
                "standalone_depth": depth,
                "is_insert_action": True,
            },
        )
        target_resolution = TargetResolution(
            requested=target_ids,
            legal=target_ids,
            selected=target_ids,
            rejected=(),
            reason="queue_standalone_targets_from_queue_entry",
            source="queue_resolution",
            metadata={
                "queue_entry_id": str(queue_entry.get("entry_id") or ""),
                "queue_resolution_id": str(queue_resolution.get("queue_resolution_id") or ""),
            },
        )
        current = state
        mutations: list[Mutation] = []
        events: list[GameEvent] = []
        rng_events: list[RNGEvent] = []
        records: list[dict[str, JSONValue]] = [
            SettlementRecord(
                record_type="standalone_ability_execution",
                source="ability_task_system",
                process_only=True,
                payload={
                    "ability_name": ability_name,
                    "phase_ids": [phase.phase_id for phase in phases],
                    "queue_entry": queue_entry,
                    "queue_resolution": queue_resolution,
                },
                trace={"standalone_phase_source": phases[0].source.to_json()},
            ).to_json()
        ]
        task_records: list[dict[str, JSONValue]] = []
        node_results: list[ExecutionNodeResult] = []
        for callback_kind in ("OnStart", "OnAttack", "OnHit", "OnEnd"):
            result = self.execute_callback(
                current,
                phases=phases,
                callback_kind=callback_kind,
                command=command,
                action_definition=action_definition,
                target_resolution=target_resolution,
            )
            current = result.after_state
            mutations.extend(result.mutations)
            events.extend(result.events)
            rng_events.extend(result.rng_events)
            records.extend(result.records)
            task_records.extend(result.task_records)
            node_results.extend(result.node_results)
        return AbilityTaskExecutionResult(
            after_state=current,
            mutations=tuple(mutations),
            events=tuple(events),
            rng_events=tuple(rng_events),
            records=tuple(records),
            task_records=tuple(task_records),
            node_results=tuple(node_results),
        )

    def _execute_task(
        self,
        state: BattleState,
        task: AbilityTaskIR,
        tasks: dict[str, AbilityTaskIR],
        *,
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        primary_target: str | None,
        target_resolution: TargetResolution,
        action_damage_modifiers: tuple[DamageModifierContribution, ...] = (),
    ) -> tuple[BattleState, list[Mutation], list[GameEvent], list[RNGEvent], list[dict[str, JSONValue]]]:
        admission_reason = ability_task_runtime_blocked_reason(
            self.rules,
            task,
            topology_authority="external_legacy",
        )
        if admission_reason:
            return state, [], [], [], [
                _task_process_record(
                    task,
                    ok=False,
                    blocked_reason=admission_reason,
                )
            ]
        if is_process_only_ability_task(task):
            return state, [], [], [], [
                _task_process_record(
                    task,
                    ok=True,
                    blocked_reason="process_only_ability_task",
                    effect_id=task.effect_id,
                    effect_opcode=task.opcode,
                    effect_coverage="process_only",
                )
            ]
        if task.opcode == "PredicateTaskList":
            return self._execute_predicate_task(
                state,
                task,
                tasks,
                command=command,
                action_definition=action_definition,
                primary_target=primary_target,
                target_resolution=target_resolution,
                action_damage_modifiers=action_damage_modifiers,
            )
        if task.opcode == "LoopExecuteTaskListWithInterval":
            return self._execute_fixed_task_loop(
                state,
                task,
                tasks,
                command=command,
                action_definition=action_definition,
                primary_target=primary_target,
                target_resolution=target_resolution,
                action_damage_modifiers=action_damage_modifiers,
            )
        if task.opcode == "TriggerAbility":
            return self._execute_trigger_ability_task(
                state,
                task,
                command=command,
                action_definition=action_definition,
                primary_target=primary_target,
                target_resolution=target_resolution,
            )
        if task.opcode == "Retarget":
            return self._execute_retarget_task(
                state,
                task,
                tasks,
                command=command,
                action_definition=action_definition,
                primary_target=primary_target,
                target_resolution=target_resolution,
                action_damage_modifiers=action_damage_modifiers,
            )
        leaf_result = self._execute_ability_leaf_task(
            state,
            task,
            command=command,
            action_definition=action_definition,
            primary_target=primary_target,
            target_resolution=target_resolution,
            action_damage_modifiers=action_damage_modifiers,
            topology_authority="external_legacy",
        )
        return leaf_result[:5]

    def _execute_ability_leaf_task(
        self,
        state: BattleState,
        task: AbilityTaskIR,
        *,
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        primary_target: str | None,
        target_resolution: TargetResolution,
        task_graph_continuation: TaskGraphContinuation | None = None,
        nested_ability_hooks: TaskGraphExecutionHooks | None = None,
        topology_authority: Literal["task_graph", "external_legacy"],
        dispatched_event_ids: set[str] | None = None,
        action_damage_modifiers: tuple[DamageModifierContribution, ...] = (),
    ) -> tuple[
        BattleState,
        list[Mutation],
        list[GameEvent],
        list[RNGEvent],
        list[dict[str, JSONValue]],
        list[TaskGraphNodeProjection],
    ]:
        admission_reason = ability_task_runtime_blocked_reason(
            self.rules,
            task,
            topology_authority=topology_authority,
        )
        if admission_reason:
            return state, [], [], [], [
                _task_process_record(task, ok=False, blocked_reason=admission_reason)
            ], []
        if is_process_only_ability_task(task):
            return state, [], [], [], [
                _task_process_record(
                    task,
                    ok=True,
                    blocked_reason="process_only_ability_task",
                    effect_id=task.effect_id,
                    effect_opcode=task.opcode,
                    effect_coverage="process_only",
                )
            ], []
        if task.opcode in {
            "PredicateTaskList",
            "LoopExecuteTaskListWithInterval",
            "TriggerAbility",
        }:
            return state, [], [], [], [
                _task_process_record(
                    task,
                    ok=False,
                    blocked_reason="ability_task_graph_structural_node_reached_leaf",
                )
            ], []
        if task.opcode == "SummonMonster":
            result = self.execute_summon_monster_task(
                state,
                task,
                actor_id=command.actor_id,
                dispatched_event_ids=dispatched_event_ids,
            )
            return (*result, [])
        if self.rules.damage_emissions_for_task(task.task_id):
            return self._execute_damage_task(
                state,
                task,
                command=command,
                action_definition=action_definition,
                primary_target=primary_target,
                target_resolution=target_resolution,
                action_damage_modifiers=action_damage_modifiers,
                task_graph_continuation=task_graph_continuation,
                nested_ability_hooks=nested_ability_hooks,
                dispatched_event_ids=dispatched_event_ids,
            )
        iteration = command.metadata.get("ability_task_iteration_index")
        invocation = _FormalAbilityInvocation(
            "action",
            command.actor_id,
            command.action_id,
            command.action_level,
            target_resolution,
            action_command=command,
            action_definition=action_definition,
            action_damage_modifiers=action_damage_modifiers,
            execution_path=str(
                command.metadata.get(
                    "ability_task_execution_path", task.task_index
                )
            ),
            iteration_index=(
                iteration if type(iteration) is int and iteration >= 0 else None
            ),
            dispatched_event_ids=dispatched_event_ids if dispatched_event_ids is not None else set(),
        )
        result = self._execute_effect_leaf_task(
            state,
            task,
            invocation=invocation,
            primary_target=primary_target,
            target_resolution=target_resolution,
            reduce_candidate=True,
        )
        if topology_authority == "task_graph":
            return self._dispatch_effect_leaf_events(
                state, task, result, invocation.dispatched_event_ids,
                task_graph_continuation, nested_ability_hooks,
            )
        return (*result, [])

    def _execute_fixed_task_loop(
        self,
        state: BattleState,
        task: AbilityTaskIR,
        tasks: dict[str, AbilityTaskIR],
        *,
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        primary_target: str | None,
        target_resolution: TargetResolution,
        action_damage_modifiers: tuple[DamageModifierContribution, ...] = (),
    ) -> tuple[BattleState, list[Mutation], list[GameEvent], list[RNGEvent], list[dict[str, JSONValue]]]:
        if task.coverage_status != "executable" or task.repeat_count <= 0:
            reason = task.blocked_reason or "fixed_positive_loop_count_required"
            return state, [], [], [], [_task_process_record(task, ok=False, blocked_reason=reason)]
        current = state
        mutations: list[Mutation] = []
        events: list[GameEvent] = []
        rng_events: list[RNGEvent] = []
        records: list[dict[str, JSONValue]] = []
        failure_reason = ""
        for iteration_index in range(task.repeat_count):
            parent_path = str(
                command.metadata.get("ability_task_execution_path") or ""
            )
            iteration_path = (
                f"{parent_path}/{task.task_id}[{iteration_index}]"
                if parent_path
                else f"{task.task_id}[{iteration_index}]"
            )
            iteration_command = replace(
                command,
                metadata={
                    **command.metadata,
                    "ability_task_execution_path": iteration_path,
                    "ability_loop_task_id": task.task_id,
                    "ability_loop_iteration": iteration_index,
                },
            )
            for child_id in task.child_task_ids:
                child = tasks.get(child_id)
                if child is None or child.parent_task_id != task.task_id:
                    failure_reason = f"loop_child_missing_or_mismatched:{child_id}"
                    break
                current, child_mutations, child_events, child_rng_events, child_records = self._execute_task(
                    current,
                    child,
                    tasks,
                    command=iteration_command,
                    action_definition=action_definition,
                    primary_target=primary_target,
                    target_resolution=target_resolution,
                    action_damage_modifiers=action_damage_modifiers,
                )
                mutations.extend(child_mutations)
                events.extend(child_events)
                rng_events.extend(child_rng_events)
                records.extend(child_records)
                if any(
                    isinstance(record.get("payload"), dict)
                    and record["payload"].get("ok") is False
                    for record in child_records
                    if isinstance(record, dict)
                    and record.get("record_type") == "ability_task"
                ):
                    failure_reason = f"loop_child_incomplete:{child_id}"
                    break
            if failure_reason:
                break
        records.insert(
            0,
            _task_process_record(
                task,
                ok=not failure_reason,
                blocked_reason=failure_reason,
                selected_child_ids=task.child_task_ids,
                mutation_count=len(mutations),
                record_count=len(records),
            ),
        )
        return current, mutations, events, rng_events, records

    def execute_summon_monster_task(
        self,
        state: BattleState,
        task: AbilityTaskIR,
        *,
        actor_id: str,
        dispatched_event_ids: set[str] | None = None,
    ) -> tuple[BattleState, list[Mutation], list[GameEvent], list[RNGEvent], list[dict[str, JSONValue]]]:
        intents = tuple(
            intent
            for intent in self.rules.summon_monster_intents()
            if intent.source_task_id == task.task_id
        )
        if len(intents) != 1:
            reason = "summon_monster_intent_missing" if not intents else "summon_monster_intent_ambiguous"
            return state, [], [], [], [_task_process_record(task, ok=False, blocked_reason=reason)]
        intent = intents[0]
        if intent.coverage_status != "executable":
            return state, [], [], [], [
                _task_process_record(
                    task,
                    ok=False,
                    blocked_reason=intent.blocked_reason
                    or f"summon_monster_intent_not_executable:{intent.coverage_status}",
                )
            ]
        if intent.source_task_id != task.task_id or intent.owner_scope != "caster":
            return state, [], [], [], [
                _task_process_record(task, ok=False, blocked_reason="summon_monster_intent_task_binding_mismatch")
            ]
        actor = state.units.get(actor_id)
        if actor is None:
            return state, [], [], [], [
                _task_process_record(task, ok=False, blocked_reason="summon_monster_caster_missing")
            ]
        caster_card_reason = _summon_monster_intent_caster_card_blocked_reason(
            self.rules, intent, actor
        )
        if caster_card_reason:
            return state, [], [], [], [
                _task_process_record(task, ok=False, blocked_reason=caster_card_reason)
            ]
        plan = self.summons.plan_spawn_from_intent(state, intent, owner_id=actor_id)
        result = self.summons.apply_spawn(state, plan)
        if not result.plan.ok:
            return state, [], [], [], [
                *result.records,
                _task_process_record(
                    task,
                    ok=False,
                    blocked_reason=result.plan.blocked_reason or "summon_monster_spawn_blocked",
                ),
            ]
        reduction = self.reducer.apply_all_result(state, result.mutations)
        if not reduction.ok:
            return state, [], [], [], [
                _task_process_record(
                    task,
                    ok=False,
                    blocked_reason=f"summon_monster_reducer_conflict:{reduction.conflicts[0].code}",
                )
            ]
        if dispatched_event_ids is not None:
            dispatched_event_ids.update(result.dispatched_event_ids)
        records = [
            *result.records,
            _task_process_record(
                task,
                ok=True,
                effect_id=task.effect_id,
                effect_opcode=task.opcode,
                effect_coverage="executable",
                mutation_count=len(result.mutations),
                record_count=len(result.records),
            ),
        ]
        return (
            reduction.after_state,
            list(result.mutations),
            list(result.events),
            list(result.rng_events),
            records,
        )

    def _execute_trigger_ability_task(
        self,
        state: BattleState,
        task: AbilityTaskIR,
        *,
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        primary_target: str | None,
        target_resolution: TargetResolution,
    ) -> tuple[BattleState, list[Mutation], list[GameEvent], list[RNGEvent], list[dict[str, JSONValue]]]:
        if task.coverage_status != "executable":
            return state, [], [], [], [_task_process_record(task, ok=False, blocked_reason=task.blocked_reason or "task_not_executable")]
        effect = self.rules.effect(task.effect_id) if task.effect_id else None
        standard = effect.payload.get("standard") if effect is not None else None
        if effect is None or not isinstance(standard, dict):
            return state, [], [], [], [_task_process_record(task, ok=False, blocked_reason="trigger_ability_effect_missing")]
        ability_name = standard.get("ability_name")
        if not isinstance(ability_name, str) or not ability_name:
            return state, [], [], [], [_task_process_record(task, ok=False, blocked_reason="trigger_ability_name_missing", effect_id=effect.effect_id, effect_opcode=effect.opcode)]
        if not command.action_id.startswith("standalone_ability:"):
            action_phase_names = {
                phase.ability_name
                for phase in self.rules.ability_phases_for_action(command.action_id, command.action_level)
            }
            if ability_name in action_phase_names:
                return state, [], [], [], [
                    _task_process_record(
                        task,
                        ok=True,
                        blocked_reason="trigger_ability_child_already_bound_to_action",
                        effect_id=effect.effect_id,
                        effect_opcode=effect.opcode,
                        effect_coverage="executable",
                    )
                ]
        depth = int(command.metadata.get("standalone_depth") or 0)
        if depth >= 4:
            return state, [], [], [], [_task_process_record(task, ok=False, blocked_reason="trigger_ability_depth_limit", effect_id=effect.effect_id, effect_opcode=effect.opcode)]
        graph = self.rules.standalone_ability_graph(task.linked_standalone_graph_id)
        if graph is None or graph.ability_name != ability_name:
            return state, [], [], [], [
                _task_process_record(
                    task,
                    ok=False,
                    blocked_reason="standalone_ability_graph_link_missing_or_mismatched",
                    effect_id=effect.effect_id,
                    effect_opcode=effect.opcode,
                )
            ]
        phases = tuple(
            phase
            for phase_id in graph.phase_ids
            if (phase := self.rules.ability_phase(phase_id)) is not None
        )
        result = self._execute_legacy_standalone(
            state,
            phases=phases,
            actor_id=command.actor_id,
            target_ids=target_resolution.selected,
            queue_entry={
                "entry_id": command.metadata.get("parent_queue_entry_id") or "",
                "queue_name": command.queue_name,
                "queue_intent_id": command.metadata.get("queue_intent_id") or "",
                "trigger_task_id": task.task_id,
            },
            queue_resolution={
                "queue_resolution_id": command.metadata.get("queue_resolution_id") or "",
                "trigger_task_id": task.task_id,
                "trigger_ability_name": ability_name,
            },
            depth=depth + 1,
        )
        records = list(result.records)
        records.append(
            _task_process_record(
                task,
                ok=not result.errors if hasattr(result, "errors") else True,
                effect_id=effect.effect_id,
                effect_opcode=effect.opcode,
                effect_coverage="executable",
                mutation_count=len(result.mutations),
                record_count=len(result.records),
            )
        )
        return result.after_state, list(result.mutations), list(result.events), list(result.rng_events), records

    def _damage_emission_identity(
        self, state: BattleState, emission, command: ActionCommand,
        target_resolution: TargetResolution, primary_target: str | None,
    ) -> tuple[str, str | None, str]:
        """Resolve the source's attacker, property and element overrides."""

        identities = {"attacker": command.actor_id, "property": command.actor_id, "element": ""}
        for role, expression_id in (
            ("attacker", emission.attacker_target_expression_id),
            ("property", emission.property_source_target_expression_id),
            ("element", emission.element_source_target_expression_id),
        ):
            if not expression_id:
                continue
            expression = self.rules.target_expression(expression_id)
            resolved = None if expression is None else self.targets.resolve_target_expression(
                state, expression,
                context=TargetEvaluationContext(
                    caster_id=command.actor_id, effect_owner_id=command.actor_id,
                    parameter_entity_ids=((primary_target or command.actor_id),),
                    selected_target_ids=target_resolution.selected, current_target_id=primary_target,
                    turn_owner_id=committed_turn_owner_id(state),
                ),
                target_resolution=target_resolution,
            )
            if resolved is None or not resolved.resolved or len(resolved.target_ids) != 1 or resolved.rng_events:
                return command.actor_id, None, f"damage_{role}_identity_not_unique_or_deterministic"
            identities[role] = resolved.target_ids[0]
        if identities["attacker"] != identities["property"]:
            return command.actor_id, None, "damage_split_property_source_not_admitted"
        element = None
        if identities["element"]:
            element = str(state.units[identities["element"]].flags.get("damage_type") or "")
            if element not in {"Physical", "Fire", "Ice", "Thunder", "Wind", "Quantum", "Imaginary"}:
                return command.actor_id, None, "damage_element_source_not_admitted"
        return identities["attacker"], element, ""

    def _execute_damage_task(
        self,
        state: BattleState,
        task: AbilityTaskIR,
        *,
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        primary_target: str | None,
        target_resolution: TargetResolution,
        task_graph_continuation: TaskGraphContinuation | None,
        nested_ability_hooks: TaskGraphExecutionHooks | None,
        dispatched_event_ids: set[str] | None = None,
        action_damage_modifiers: tuple[DamageModifierContribution, ...] = (),
        hit_target_ids: list[str] | None = None,
        window_ledger: DamageWindowLedger | None = None,
        packet_sequence_id: str = "",
        template_binding_sources: tuple[Mapping[str, JSONValue], ...] = (),
    ) -> tuple[
        BattleState,
        list[Mutation],
        list[GameEvent],
        list[RNGEvent],
        list[dict[str, JSONValue]],
        list[TaskGraphNodeProjection],
    ]:
        emissions = tuple(
            emission
            for emission in self.rules.damage_emissions_for_task(task.task_id)
            if emission.action_id == task.action_id and emission.level == task.level
        )
        if not emissions:
            return state, [], [], [], [
                _task_process_record(
                    task, ok=False, blocked_reason="damage_emission_missing"
                )
            ], []
        current = state
        mutations: list[Mutation] = []
        events: list[GameEvent] = []
        rng_events: list[RNGEvent] = []
        records: list[dict[str, JSONValue]] = []
        task_graph_projections: list[TaskGraphNodeProjection] = []
        ledger = window_ledger if window_ledger is not None else DamageWindowLedger()
        damage_modifiers: list[DamageModifierContribution] = []
        sequence_modifiers: dict[tuple[str, str], tuple[DamageModifierContribution, ...]] = {}
        target_modifiers: dict[str, tuple[DamageModifierContribution, ...]] = {}
        sequence_order: list[tuple[str, str]] = []
        sequence_context: dict[
            tuple[str, str],
            dict[str, JSONValue],
        ] = {}

        def dispatch_damage_event(event: GameEvent) -> tuple[str, ...]:
            nonlocal current
            if self.event_dispatcher is None:
                events.append(event)
                return ()
            result: EventDispatchResult = self.event_dispatcher.dispatch_event(
                current,
                event=event,
                damage_window_ledger=ledger,
                task_graph_continuation=task_graph_continuation,
                nested_ability_hooks=nested_ability_hooks,
            )
            current = result.after_state
            if dispatched_event_ids is not None:
                dispatched_event_ids.update(result.dispatched_event_ids)
            mutations.extend(result.mutations)
            events.extend(result.events)
            rng_events.extend(result.rng_events)
            records.extend(result.records)
            task_graph_projections.extend(result.task_graph_projections)
            damage_modifiers.extend(result.damage_modifiers)
            return result.errors

        for emission in emissions:
            if emission.coverage_status != "executable":
                records.append(
                    _task_process_record(
                        task,
                        ok=False,
                        blocked_reason=emission.blocked_reason or f"damage_emission_not_executable:{emission.coverage_status}",
                    )
                )
                continue
            profile = self.rules.hit_profile(emission.hit_profile_id)
            if profile is None or profile.coverage_status != "executable":
                records.append(
                    _task_process_record(
                        task,
                        ok=False,
                        blocked_reason="hit_profile_missing_or_not_executable",
                    )
                )
                continue
            if action_definition.source_mode == "queue_standalone":
                attack_type = emission.scaling_basis_expr.get("attack_type")
                if not isinstance(attack_type, str) or not attack_type:
                    records.append(_task_process_record(task, ok=False, blocked_reason="queued_damage_attack_type_missing"))
                    continue
                action_definition = replace(action_definition, attack_type=attack_type)
            ratio_eval = self.evaluator.evaluate_numeric(
                emission.scaling_ratio_expr,
                NumericEvaluationContext(
                    binding_sources=(
                        *_binding_sources(
                            self.rules,
                            current,
                            command.actor_id,
                            primary_target,
                            action_level=command.action_level,
                            action_id=command.action_id,
                            current_action_trigger_key=_action_trigger_key(action_definition),
                            template_binding_sources=template_binding_sources,
                            ability_instance_id=(
                                f"ability_action:{state.event_index}:{command.actor_id}:"
                                f"{command.action_id}:{command.action_level}"
                            ),
                        ),
                        *_expression_binding_sources(emission.scaling_ratio_expr),
                    ),
                    source_trace=emission.source.to_json(),
                ),
            )
            if not ratio_eval.ok or ratio_eval.value is None:
                records.append(
                    _task_process_record(
                        task,
                        ok=False,
                        blocked_reason=f"damage_scaling_ratio_blocked:{ratio_eval.blocked_reason}",
                    )
                )
                continue
            if emission.target_group == "all_teammate" and (
                not command.actor_id or command.actor_id not in current.units
            ):
                # The relative-side alias needs the caster to resolve its own
                # team. Absent context is not the same fact as an empty living
                # team and must not become a legal no-effect.
                records.append(
                    _task_process_record(
                        task,
                        ok=False,
                        blocked_reason=(
                            "damage_relative_side_target_group_context_missing"
                        ),
                    )
                )
                continue
            target_ids = _damage_targets_for_emission(
                emission.target_group,
                target_resolution,
                state=current,
                attacker_id=command.actor_id,
            )
            if target_ids:
                # A repeated hit (multi-hit action or loop task) may run after
                # an earlier hit already defeated the target. The corpse must
                # not receive another damage packet: it would emit a duplicate
                # zero-HP damage event identity and fake settlement records.
                damageable_targets = tuple(
                    target_id
                    for target_id in target_ids
                    if UnitLifecycleSystem().can_receive_damage(current, target_id)[0]
                )
                if not damageable_targets:
                    records.append(
                        _task_process_record(
                            task,
                            ok=True,
                            blocked_reason="damage_target_no_longer_damageable",
                        )
                    )
                    continue
                target_ids = damageable_targets
            if not target_ids:
                # A relative-side group (the caster's whole team) is a valid
                # source target even when every member is already defeated.
                # That is a legal no-effect, not an implementation failure; a
                # real single-target request with no target stays blocked.
                optional_group = emission.target_group in {
                    "adjacent",
                    "all_teammate",
                }
                records.append(
                    _task_process_record(
                        task,
                        ok=optional_group,
                        blocked_reason=(
                            "damage_relative_side_target_group_empty"
                            if emission.target_group == "all_teammate"
                            else "damage_optional_target_group_empty"
                            if optional_group
                            else "damage_target_missing"
                        ),
                    )
                )
                continue
            attacker_id, element_override, identity_reason = self._damage_emission_identity(
                current, emission, command, target_resolution, primary_target,
            )
            if identity_reason:
                records.append(_task_process_record(task, ok=False, blocked_reason=identity_reason))
                return current, mutations, events, rng_events, records, task_graph_projections
            window_command = replace(command, actor_id=attacker_id) if attacker_id != command.actor_id else command
            for target_id in target_ids:
                execution_path = str(
                    command.metadata.get("ability_task_execution_path") or ""
                )
                is_standalone = (
                    action_definition.source_mode == "queue_standalone"
                )
                damage_source_id = (
                    task.task_id
                    if is_standalone
                    else (
                        f"action:{command.action_id}:"
                        f"level:{command.action_level}"
                    )
                )
                damage_source_kind = (
                    "standalone_ability_damage"
                    if is_standalone
                    else "primary_action_damage"
                )
                damage_sequence_id = (
                    f"{command.action_id}:{task.task_id}"
                    if is_standalone
                    else (
                        f"action:{command.actor_id}:{command.action_id}:"
                        f"level:{command.action_level}:task:{task.task_id}"
                    )
                )
                packet = DamagePacket(
                    attacker_id=attacker_id,
                    target_id=target_id,
                    attack_type=runtime_regarded_attack_type(
                        current.units.get(attacker_id), action_definition.attack_type,
                    ),
                    damage_formula_family=emission.damage_formula_family,
                    damage_kind="hp_damage",
                    element_type=element_override or emission.element_type,
                    action_definition=action_definition,
                    damage_emission_id=emission.damage_emission_id,
                    hit_energy_gain=emission.hit_energy_gain,
                    source_task_id=task.task_id,
                    hit_profile_id=profile.hit_profile_id,
                    scaling_ratio=ratio_eval.value,
                    scaling_basis=emission.scaling_basis_expr,
                    hit_source_trace=profile.source.to_json(),
                    source_trace=emission.source.to_json(),
                    source_frame=DamageSourceFrame(
                        owner_id=attacker_id,
                        source_id=damage_source_id,
                        source_kind=damage_source_kind,
                        sequence_id=packet_sequence_id or damage_sequence_id,
                        target_id=target_id,
                        can_continue_after_lethal=True,
                        source_trace=emission.source.to_json(),
                    ),
                    metadata={
                        **command.metadata,
                        "SkillType": action_definition.skill_effect,
                        "skill_type": action_definition.skill_effect,
                        "attack_type": action_definition.attack_type,
                        "is_current_skill_active": not is_standalone,
                        "is_insert_action": command.source == "queue",
                        "primary_action_target_id": primary_target,
                        "hit_index": profile.hit_index,
                        "target_group": emission.target_group,
                        "numeric_evaluation": ratio_eval.to_json(),
                        "phase_id": task.phase_id,
                        "derived_event_id": (
                            f"{emission.damage_emission_id}:{execution_path}"
                            if execution_path
                            else emission.damage_emission_id
                        ),
                    },
                )
                sequence_id = (
                    f"{task.task_id}:{execution_path}"
                    if execution_path
                    else task.task_id
                )
                sequence_key = (sequence_id, target_id)
                modifier_start = len(damage_modifiers)
                if (
                    self.event_dispatcher is not None
                    and sequence_key not in sequence_context
                ):
                    before_errors = dispatch_damage_event(
                        damage_listener_window_event(
                            current,
                            window_command,
                            action_definition,
                            event_type="damage.hit_sequence.before",
                            target_id=target_id,
                            selected_target_ids=target_resolution.selected,
                            primary_target_id=primary_target,
                            source_trace=emission.source.to_json(),
                            damage_custom_name=emission.damage_custom_name,
                            damage_tags=emission.damage_tags,
                            sequence_id=sequence_id,
                        )
                    )
                    if before_errors:
                        records.append(
                            _task_process_record(
                                task,
                                ok=False,
                                blocked_reason=(
                                    "ability_task_damage_before_window_blocked:"
                                    + ",".join(before_errors)
                                ),
                            )
                        )
                        return (
                            current,
                            mutations,
                            events,
                            rng_events,
                            records,
                            task_graph_projections,
                        )
                    sequence_order.append(sequence_key)
                    sequence_context[sequence_key] = {
                        "target_id": target_id,
                        "source_trace": emission.source.to_json(),
                        "damage_custom_name": emission.damage_custom_name,
                        "damage_tags": list(emission.damage_tags),
                        "is_critical": False,
                        "final_damage": 0.0,
                    }
                    sequence_modifiers[sequence_key] = tuple(damage_modifiers[modifier_start:])
                before_windows = ["damage.before_hit"]
                if target_id not in target_modifiers:
                    before_windows[:0] = ["damage.target_attack.before", "damage.target_hit_sequence.before"]
                    target_modifiers[target_id] = ()
                hit_modifiers: tuple[DamageModifierContribution, ...] = ()
                for event_type in before_windows:
                    modifier_start = len(damage_modifiers)
                    before_errors = dispatch_damage_event(
                        damage_listener_window_event(
                            current, window_command, action_definition,
                            event_type=event_type, target_id=target_id,
                            selected_target_ids=target_resolution.selected,
                            primary_target_id=primary_target,
                            source_trace=emission.source.to_json(),
                            damage_custom_name=emission.damage_custom_name,
                            damage_tags=emission.damage_tags,
                            sequence_id=f"{sequence_id}:{emission.damage_emission_id}:{profile.hit_index}",
                        )
                    )
                    if before_errors:
                        records.append(_task_process_record(
                            task, ok=False,
                            blocked_reason="ability_task_damage_before_window_blocked:" + ",".join(before_errors),
                        ))
                        return current, mutations, events, rng_events, records, task_graph_projections
                    produced = tuple(damage_modifiers[modifier_start:])
                    if event_type == "damage.before_hit":
                        hit_modifiers = produced
                    else:
                        target_modifiers[target_id] += produced
                extra_expr = emission.scaling_basis_expr.get("extra_damage_ratio_expr")
                if extra_expr is not None:
                    extra_eval = self.evaluator.evaluate_numeric(extra_expr, NumericEvaluationContext(
                        binding_sources=(
                            *_binding_sources(self.rules, current, command.actor_id, target_id,
                                action_level=command.action_level, action_id=command.action_id,
                                current_action_trigger_key=_action_trigger_key(action_definition),
                                template_binding_sources=template_binding_sources,
                                ability_instance_id=(
                                    packet_sequence_id
                                    or f"ability_action:{state.event_index}:{command.actor_id}:{command.action_id}:{command.action_level}"
                                )),
                            *_expression_binding_sources(extra_expr),
                        ), source_trace=emission.source.to_json()))
                    if not extra_eval.ok or extra_eval.value is None:
                        records.append(_task_process_record(task, ok=False,
                            blocked_reason="damage_extra_scaling_ratio_blocked:" + extra_eval.blocked_reason))
                        return current, mutations, events, rng_events, records, task_graph_projections
                    packet = replace(packet, extra_scaling_ratio=extra_eval.value,
                                     metadata={**packet.metadata, "extra_numeric_evaluation": extra_eval.to_json()})
                packet = replace(packet, modifier_contributions=(
                    *action_damage_modifiers,
                    *sequence_modifiers.get(sequence_key, ()),
                    *target_modifiers[target_id],
                    *hit_modifiers,
                ))
                if emission.damage_formula_family == "elation":
                    try:
                        packet = replace(packet, elation_context=resolve_elation_damage_context(
                            current, command.actor_id,
                            point_source=str(emission.scaling_basis_expr.get("elation_point_source") or ""),
                        ))
                    except ValueError as exc:
                        records.append(_task_process_record(
                            task, ok=False, blocked_reason=f"elation_context_blocked:{exc}",
                        ))
                        return current, mutations, events, rng_events, records, task_graph_projections
                damage_result = self.damage.apply_packet(current, packet, window_ledger=ledger)
                if damage_result.ok and hit_target_ids is not None:
                    hit_target_ids.append(target_id)
                current = self.reducer.apply_all(current, damage_result.mutations)
                mutations.extend(damage_result.mutations)
                rng_events.extend(damage_result.rng_events)
                records.extend(damage_result.records)
                for damage_event in damage_result.events:
                    if damage_event.event_type in {"damage.hit", "damage.attacker_hit"}:
                        amount = damage_event.payload.get("final_damage")
                        if not isinstance(amount, (int, float)) or isinstance(
                            amount,
                            bool,
                        ):
                            amount = damage_event.payload.get("amount")
                        if isinstance(amount, (int, float)) and not isinstance(
                            amount,
                            bool,
                        ):
                            context = sequence_context.get(sequence_key)
                            if context is not None:
                                context["final_damage"] = float(
                                    context.get("final_damage") or 0.0
                                ) + float(amount)
                                context["is_critical"] = bool(
                                    context.get("is_critical")
                                ) or damage_event.payload.get(
                                    "is_critical"
                                ) is True
                    dispatch_errors = dispatch_damage_event(damage_event)
                    if dispatch_errors:
                        records.append(
                            _task_process_record(
                                task,
                                ok=False,
                                blocked_reason=(
                                    "ability_task_damage_event_blocked:"
                                    + ",".join(dispatch_errors)
                                ),
                            )
                        )
                        return (
                            current,
                            mutations,
                            events,
                            rng_events,
                            records,
                            task_graph_projections,
                        )
                if not damage_result.ok:
                    records.append(_task_process_record(
                        task, ok=False, blocked_reason=",".join(damage_result.errors),
                    ))
                    return current, mutations, events, rng_events, records, task_graph_projections
                toughness_blocked_reason = ""
                for toughness_emission in self.rules.toughness_emissions_for_task(
                    task.task_id
                ):
                    if toughness_emission.hit_profile_id != profile.hit_profile_id:
                        continue
                    binding_sources = (
                        *_binding_sources(
                            self.rules,
                            current,
                            command.actor_id,
                            primary_target,
                            action_level=command.action_level,
                            action_id=command.action_id,
                            current_action_trigger_key=_action_trigger_key(
                                action_definition
                            ),
                            ability_instance_id=(
                                f"ability_action:{state.event_index}:{command.actor_id}:"
                                f"{command.action_id}:{command.action_level}"
                            ),
                        ),
                        *_expression_binding_sources(
                            toughness_emission.toughness_amount_expr
                        ),
                    )
                    toughness_packet = ToughnessPacket(
                        attacker_id=command.actor_id,
                        target_id=target_id,
                        toughness_emission_id=(
                            toughness_emission.toughness_emission_id
                        ),
                        source_task_id=task.task_id,
                        hit_profile_id=profile.hit_profile_id,
                        element_type=toughness_emission.element_type,
                        amount=None,
                        amount_expr=toughness_emission.toughness_amount_expr,
                        target_group=toughness_emission.target_group,
                        coverage_status=toughness_emission.coverage_status,
                        source_trace=toughness_emission.source.to_json(),
                        metadata={
                            "primary_action_target_id": primary_target,
                            "value_binding_sources": list(binding_sources),
                            "ability_task_execution_path": command.metadata.get(
                                "ability_task_execution_path",
                                "",
                            ),
                        },
                    )
                    # Resolve HP damage first: the crossing hit retains the
                    # pre-break reduction; later hits read the changed state.
                    before_errors = dispatch_damage_event(before_toughness_calculation_event(
                        actor_id=command.actor_id, target_id=target_id,
                        event_index=current.event_index, packet=toughness_packet.to_json(),
                        extra_payload={
                            "action_id": command.action_id, "action_level": command.action_level,
                            "attacker_id": command.actor_id, "current_hit_target_id": target_id,
                            "primary_action_target_id": primary_target,
                            "source_trace": toughness_emission.source.to_json(),
                        },
                    ))
                    if before_errors:
                        toughness_blocked_reason = ",".join(before_errors)
                        break
                    toughness_result = self.toughness.apply_packet(current, toughness_packet)
                    records.extend(toughness_result.records)
                    if not toughness_result.ok:
                        toughness_blocked_reason = ",".join(toughness_result.errors)
                        break
                    current = self.reducer.apply_all(current, toughness_result.mutations)
                    mutations.extend(toughness_result.mutations)
                    for event in toughness_result.events:
                        errors = dispatch_damage_event(event)
                        if errors:
                            toughness_blocked_reason = ",".join(errors)
                            break
                    if toughness_blocked_reason:
                        break
                    break_result = self.breaks.enter_if_depleted(current, toughness_result)
                    if break_result is not None:
                        current = break_result.after_state
                        mutations.extend(break_result.mutations)
                        records.extend(break_result.records)
                        rng_events.extend(break_result.rng_events)
                        if dispatched_event_ids is not None:
                            dispatched_event_ids.update(break_result.dispatched_event_ids)
                        if not break_result.ok:
                            toughness_blocked_reason = ",".join(break_result.errors)
                            break
                        for event in break_result.events:
                            if str(event.to_json()["event_id"]) in break_result.dispatched_event_ids:
                                events.append(event)
                                continue
                            errors = dispatch_damage_event(event)
                            if errors:
                                toughness_blocked_reason = ",".join(errors)
                                break
                    if toughness_blocked_reason:
                        break
                if toughness_blocked_reason:
                    records.append(_task_process_record(
                        task, ok=False, blocked_reason=toughness_blocked_reason,
                    ))
                    return current, mutations, events, rng_events, records, task_graph_projections
                records.append(
                    _task_process_record(
                        task,
                        ok=damage_result.ok,
                        blocked_reason=",".join(damage_result.errors),
                        effect_id=task.effect_id,
                        effect_opcode=task.opcode,
                        effect_coverage="executable",
                        mutation_count=len(damage_result.mutations),
                        record_count=len(damage_result.records),
                    )
                )
        if self.event_dispatcher is not None:
            for sequence_key in sequence_order:
                context = sequence_context[sequence_key]
                sequence_tags = context.get("damage_tags")
                after_errors = dispatch_damage_event(
                    damage_listener_window_event(
                        current,
                        command,
                        action_definition,
                        event_type="damage.hit_sequence.after",
                        target_id=str(context["target_id"]),
                        selected_target_ids=target_resolution.selected,
                        primary_target_id=primary_target,
                        source_trace=(
                            context["source_trace"]
                            if isinstance(context.get("source_trace"), dict)
                            else {}
                        ),
                        is_critical=bool(context.get("is_critical")),
                        final_damage=float(
                            context.get("final_damage") or 0.0
                        ),
                        damage_custom_name=str(
                            context.get("damage_custom_name") or ""
                        ),
                        damage_tags=tuple(
                            tag
                            for tag in (
                                sequence_tags
                                if isinstance(sequence_tags, (list, tuple))
                                else ()
                            )
                            if isinstance(tag, str) and tag
                        ),
                        sequence_id=sequence_key[0],
                    )
                )
                if after_errors:
                    records.append(
                        _task_process_record(
                            task,
                            ok=False,
                            blocked_reason=(
                                "ability_task_damage_after_window_blocked:"
                                + ",".join(after_errors)
                            ),
                        )
                    )
                    return (
                        current,
                        mutations,
                        events,
                        rng_events,
                        records,
                        task_graph_projections,
                    )
        return (
            current,
            mutations,
            events,
            rng_events,
            records,
            task_graph_projections,
        )

    def _evaluate_ability_task_condition(
        self,
        state: BattleState,
        task: AbilityTaskIR,
        *,
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        primary_target: str | None,
        target_resolution: TargetResolution,
    ) -> tuple[bool | None, str, dict[str, JSONValue]]:
        invocation = _FormalAbilityInvocation(
            "action",
            command.actor_id,
            command.action_id,
            command.action_level,
            target_resolution,
            action_command=command,
            action_definition=action_definition,
        )
        return self._evaluate_formal_ability_condition(
            state,
            task,
            invocation=invocation,
            primary_target=primary_target,
            target_resolution=target_resolution,
        )

    def _execute_retarget_task(
        self,
        state: BattleState,
        task: AbilityTaskIR,
        tasks: dict[str, AbilityTaskIR],
        *,
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        primary_target: str | None,
        target_resolution: TargetResolution,
        action_damage_modifiers: tuple[DamageModifierContribution, ...] = (),
    ) -> tuple[BattleState, list[Mutation], list[GameEvent], list[RNGEvent], list[dict[str, JSONValue]]]:
        """Resolve a typed target-list selection, then run TaskList per target.

        The Retarget source shape selects up to N targets (optionally filtered
        and sampled randomly) and applies its TaskList to each selected target
        through ParamEntity.  Target selection is a typed target expression, so
        its source closure and RNG decisions stay in the target-language layer.
        """

        effect = self.rules.effect(task.effect_id) if task.effect_id else None
        standard = effect.payload.get("standard") if effect is not None else None

        def blocked(reason: str) -> tuple[
            BattleState, list[Mutation], list[GameEvent], list[RNGEvent],
            list[dict[str, JSONValue]],
        ]:
            return state, [], [], [], [
                _task_process_record(
                    task,
                    ok=False,
                    blocked_reason=reason,
                    effect_id=task.effect_id or "",
                    effect_opcode=task.opcode,
                )
            ]

        if effect is None or not isinstance(standard, dict):
            return blocked("retarget_effect_missing")
        if standard.get("operation") != "retarget_task_list" or standard.get("blocked_reason"):
            return blocked(
                str(standard.get("blocked_reason") or "retarget_task_not_admitted")
            )
        expression_id = standard.get("target_expression_id")
        expression = (
            self.rules.target_expression(str(expression_id))
            if isinstance(expression_id, str) and expression_id else None
        )
        if expression is None or expression.coverage_status != "executable":
            return blocked("retarget_target_expression_not_executable")
        target_context = TargetEvaluationContext(
            caster_id=command.actor_id,
            effect_owner_id=command.actor_id,
            parameter_entity_ids=(primary_target,) if primary_target else (),
            parameter_entity_list_ids=(primary_target,) if primary_target else (),
            selected_target_ids=target_resolution.selected,
            current_target_id=primary_target,
            turn_owner_id=committed_turn_owner_id(state),
        )
        resolved = self.targets.resolve_target_expression(
            state,
            expression,
            context=target_context,
            target_resolution=target_resolution,
            condition_event_payload={
                "action_id": command.action_id,
                "action_level": command.action_level,
                "task_id": task.task_id,
            },
            binding_sources=_binding_sources(
                self.rules,
                state,
                command.actor_id,
                primary_target,
                action_level=action_definition.level,
                action_id=action_definition.action_id,
            ),
        )
        if resolved.status != "resolved":
            return blocked(
                resolved.blocked_reason or "retarget_target_resolution_blocked"
            )
        selected_target_ids = tuple(resolved.target_ids)
        rng_events: list[RNGEvent] = list(resolved.rng_events)
        current = state
        mutations: list[Mutation] = []
        events: list[GameEvent] = []
        records: list[dict[str, JSONValue]] = [
            _task_process_record(
                task,
                ok=True,
                selected_child_ids=tuple(task.child_task_ids),
                condition_result={
                    "selected_target_ids": list(selected_target_ids),
                    "target_expression_id": expression.target_expression_id,
                    "rng_event_count": len(rng_events),
                },
            )
        ]
        for selected_target in selected_target_ids:
            scoped_resolution = TargetResolution(
                requested=(selected_target,),
                legal=(selected_target,),
                selected=(selected_target,),
                rejected=(),
                reason="retarget_param_entity",
                source="ability_task_system",
            )
            for child_id in task.child_task_ids:
                child = tasks.get(child_id)
                if child is None:
                    records.append(
                        _task_process_record(
                            task,
                            ok=False,
                            blocked_reason=f"missing_child_task:{child_id}",
                        )
                    )
                    continue
                (
                    current,
                    child_mutations,
                    child_events,
                    child_rng_events,
                    child_records,
                ) = self._execute_task(
                    current,
                    child,
                    tasks,
                    command=command,
                    action_definition=action_definition,
                    primary_target=selected_target,
                    target_resolution=scoped_resolution,
                    action_damage_modifiers=action_damage_modifiers,
                )
                mutations.extend(child_mutations)
                events.extend(child_events)
                rng_events.extend(child_rng_events)
                records.extend(child_records)
        return current, mutations, events, rng_events, records

    def _execute_predicate_task(
        self,
        state: BattleState,
        task: AbilityTaskIR,
        tasks: dict[str, AbilityTaskIR],
        *,
        command: ActionCommand,
        action_definition: ActionDefinitionIR,
        primary_target: str | None,
        target_resolution: TargetResolution,
        action_damage_modifiers: tuple[DamageModifierContribution, ...] = (),
    ) -> tuple[BattleState, list[Mutation], list[GameEvent], list[RNGEvent], list[dict[str, JSONValue]]]:
        condition_value, condition_blocker, condition_evidence = (
            self._evaluate_ability_task_condition(
                state,
                task,
                command=command,
                action_definition=action_definition,
                primary_target=primary_target,
                target_resolution=target_resolution,
            )
        )
        if condition_value is None:
            record = _task_process_record(
                task,
                ok=False,
                blocked_reason=condition_blocker,
                condition_result=condition_evidence,
            )
            return state, [], [], [], [record]

        selected_child_ids = task.success_task_ids if condition_value else task.failed_task_ids
        current = state
        mutations: list[Mutation] = []
        events: list[GameEvent] = []
        rng_events: list[RNGEvent] = []
        records: list[dict[str, JSONValue]] = [
            _task_process_record(
                task,
                ok=True,
                condition_result=condition_evidence,
                selected_child_ids=selected_child_ids,
            )
        ]
        for child_id in selected_child_ids:
            child = tasks.get(child_id)
            if child is None:
                records.append(_task_process_record(task, ok=False, blocked_reason=f"missing_child_task:{child_id}"))
                continue
            current, child_mutations, child_events, child_rng_events, child_records = self._execute_task(
                current,
                child,
                tasks,
                command=command,
                action_definition=action_definition,
                primary_target=primary_target,
                target_resolution=target_resolution,
                action_damage_modifiers=action_damage_modifiers,
            )
            mutations.extend(child_mutations)
            events.extend(child_events)
            rng_events.extend(child_rng_events)
            records.extend(child_records)
        return current, mutations, events, rng_events, records


def _summon_monster_intent_caster_card_blocked_reason(
    rules: RuleBook,
    intent: object,
    actor: object,
) -> str:
    """Verify the actual caster card owns the intent's CustomValues scope.

    Summon intents are lowered per card, but ability files are shared by several
    monster cards. The real actor must therefore be the same card whose formal
    CustomValues produced the resolved monster id. The scope is a formal IR field;
    source evidence is audit-only and trimming it must not change this decision.
    """

    scope = getattr(intent, "caster_card_scope", None)
    if not isinstance(scope, Mapping) or not scope:
        return "summon_monster_intent_caster_card_scope_missing"
    expected_monster_id = scope.get("monster_id")
    if expected_monster_id is None or str(expected_monster_id) == "":
        return str(
            scope.get("blocked_reason") or "summon_monster_caster_card_identity_missing"
        )
    template_id = str(getattr(actor, "template_id", "") or "")
    card = rules.monster_data_card_for_entity(template_id) if template_id else None
    flags = getattr(actor, "flags", None)
    card_id = str(flags.get("monster_data_card_id") or "") if isinstance(flags, Mapping) else ""
    if card is None or not card_id or card_id != card.card_id:
        return "summon_monster_caster_card_missing"
    if str(card.monster_id) != str(expected_monster_id):
        return "summon_monster_intent_caster_card_mismatch"
    binding_scope = scope.get("custom_value_binding_scope")
    if isinstance(binding_scope, Mapping) and binding_scope:
        if str(binding_scope.get("monster_id")) != str(expected_monster_id):
            return "summon_monster_intent_caster_card_binding_scope_mismatch"
        expected_path = str(scope.get("character_config_path") or "")
        bound_path = str(binding_scope.get("character_config_path") or "")
        if expected_path and bound_path and expected_path != bound_path:
            return "summon_monster_intent_caster_card_config_mismatch"
    return ""


def _task_graph_target_resolution(
    request: TaskGraphHookRequest,
    target_resolution: TargetResolution,
) -> TargetResolution:
    if not request.target_ids:
        return target_resolution
    return replace(
        target_resolution,
        requested=request.target_ids,
        selectable=request.target_ids,
        legal=request.target_ids,
        primary=request.target_ids[0],
        impact_group=request.target_ids,
        selected=request.target_ids,
        rejected=(),
        reason="task_graph_target_scope",
        source="task_graph_executor",
        metadata={
            **target_resolution.metadata,
            "ability_task_invocation_id": request.invocation_id,
            "ability_task_scope_node_id": request.graph_node_id,
        },
    )


def _task_graph_execution_path(request: TaskGraphHookRequest) -> str:
    # Catalog identities prove source authority; only execution facts identify RNG.
    parts = [
        *request.execution_path,
        request.formal_task_id,
        *(f"target:{item}" for item in request.target_ids),
    ]
    if request.iteration_index is not None:
        parts.append(f"iteration:{request.iteration_index}")
    return "/".join(parts)


def _ability_task_records_blocked_reason(
    records: list[dict[str, JSONValue]],
) -> str:
    for record in records:
        if not isinstance(record, Mapping) or record.get("record_type") != "ability_task":
            continue
        payload = record.get("payload")
        if not isinstance(payload, Mapping) or payload.get("ok") is not False:
            continue
        return str(payload.get("blocked_reason") or "ability_task_graph_leaf_blocked")
    return ""


def _task_graph_settlement_records(
    records: list[dict[str, JSONValue]],
) -> tuple[TaskGraphSettlementRecord, ...]:
    required = {
        "record_type",
        "source",
        "mutation_id",
        "process_only",
        "payload",
        "trace",
    }
    converted: list[TaskGraphSettlementRecord] = []
    for record in records:
        if not isinstance(record, Mapping) or set(record) != required:
            raise ValueError("ability task settlement record shape is invalid")
        payload = record.get("payload")
        trace = record.get("trace")
        if not isinstance(payload, Mapping) or not isinstance(trace, Mapping):
            raise TypeError("ability task settlement payload is invalid")
        converted.append(
            TaskGraphSettlementRecord(
                record_type=cast(str, record["record_type"]),
                source=cast(str, record["source"]),
                mutation_id=cast(str | None, record["mutation_id"]),
                process_only=cast(bool, record["process_only"]),
                payload=dict(payload),
                trace=dict(trace),
            )
        )
    return tuple(converted)


def _task_process_record(
    task: AbilityTaskIR,
    *,
    ok: bool,
    blocked_reason: str = "",
    effect_id: str = "",
    effect_opcode: str = "",
    effect_coverage: str = "",
    condition_result: dict[str, JSONValue] | None = None,
    selected_child_ids: tuple[str, ...] = (),
    mutation_count: int = 0,
    record_count: int = 0,
) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type="ability_task",
        source="ability_task_system",
        process_only=True,
        payload={
            "task_id": task.task_id,
            "phase_id": task.phase_id,
            "ability_name": task.ability_name,
            "callback_kind": task.callback_kind,
            "task_path": task.task_path,
            "branch": task.branch,
            "opcode": task.opcode,
            "ok": ok,
            "coverage_status": task.coverage_status,
            "blocked_reason": blocked_reason,
            "effect_id": effect_id or task.effect_id,
            "effect_opcode": effect_opcode,
            "effect_coverage": effect_coverage,
            "condition_id": task.condition_id,
            "condition_result": condition_result or {},
            "selected_child_ids": list(selected_child_ids),
            "mutation_count": mutation_count,
            "record_count": record_count,
        },
        trace=task.source.to_json(),
    ).to_json()


def _node_results_from_task_records(
    task_records: list[dict[str, JSONValue]] | tuple[dict[str, JSONValue], ...],
) -> tuple[ExecutionNodeResult, ...]:
    results: list[ExecutionNodeResult] = []
    for index, payload in enumerate(task_records):
        task_id = str(payload.get("task_id") or f"ability_task:{index}")
        ok = payload.get("ok") is True
        reason = str(payload.get("blocked_reason") or "")
        coverage_status = str(payload.get("coverage_status") or "")
        if ok:
            status = "complete"
        elif "partial" in reason or "partial" in coverage_status:
            status = "partial"
        elif coverage_status and coverage_status != "executable":
            status = "unsupported"
        elif "not_executable" in reason or "unsupported" in reason:
            status = "unsupported"
        else:
            status = "blocked"
        results.append(
            ExecutionNodeResult(
                node_kind="ability_task",
                node_id=task_id,
                status=status,
                reason_code=reason or ("" if ok else "ability_task_incomplete"),
            )
        )
    return tuple(results)


def _rng_event_payload_from_command(command: ActionCommand) -> dict[str, JSONValue]:
    payload: dict[str, JSONValue] = {}
    for key in ("rng_choices", "rng_mode", "target_random_choices"):
        value = command.metadata.get(key)
        if isinstance(value, (dict, str)):
            payload[key] = value
    return payload


def _event_payload(
    command: ActionCommand,
    action_definition: ActionDefinitionIR,
    primary_target: str | None,
    target_resolution: TargetResolution,
) -> dict[str, JSONValue]:
    return {
        **_rng_event_payload_from_command(command),
        "SkillType": action_definition.skill_effect,
        "skill_type": action_definition.skill_effect,
        "attack_type": action_definition.attack_type,
        "damage_kind": action_definition.damage_kind,
        "damage_formula_family": action_definition.damage_formula_family,
        "action_id": action_definition.action_id,
        "action_level": action_definition.level,
        "actor_id": command.actor_id,
        "primary_target_id": primary_target,
        "selected_target_ids": list(target_resolution.selected),
    }


def _formal_event_payload(
    invocation: _FormalAbilityInvocation,
    primary_target: str | None,
    target_resolution: TargetResolution,
) -> dict[str, JSONValue]:
    if invocation.invocation_kind == "action":
        return _event_payload(
            cast(ActionCommand, invocation.action_command),
            cast(ActionDefinitionIR, invocation.action_definition),
            primary_target,
            target_resolution,
        )
    payload: dict[str, JSONValue] = {
        "invocation_kind": invocation.invocation_kind,
        "ability_id": invocation.ability_id,
        "ability_level": invocation.ability_level,
        "actor_id": invocation.actor_id,
        "primary_target_id": primary_target,
        "selected_target_ids": list(target_resolution.selected),
    }
    if invocation.standalone is not None:
        payload.update(invocation.standalone.to_json())
    return payload


def _formal_effect_event_payload(
    invocation: _FormalAbilityInvocation,
    primary_target: str | None,
    target_resolution: TargetResolution,
) -> dict[str, JSONValue]:
    if invocation.invocation_kind != "action":
        return _formal_event_payload(invocation, primary_target, target_resolution)
    command = cast(ActionCommand, invocation.action_command)
    return {
        **_rng_event_payload_from_command(command),
        "actor_id": invocation.actor_id,
        "action_id": invocation.ability_id,
        "action_level": invocation.ability_level,
    }


def _dynamic_condition_progress(
    condition: object | None,
    evidence: Mapping[str, JSONValue] | None,
) -> int | None:
    """Return the compared dynamic value as loop progress for source loops.

    A conditional loop body that decrements the dynamic value compared by its
    predicate proves termination at runtime: progress_remaining must strictly
    decrease each iteration or the executor blocks.
    """

    if condition is None or getattr(condition, "opcode", None) != "ByCompareDynamicValue":
        return None
    if not isinstance(evidence, Mapping):
        return None
    details = evidence.get("details")
    if not isinstance(details, Mapping):
        return None
    evaluation = details.get("numeric_evaluation")
    bindings = evaluation.get("bindings") if isinstance(evaluation, Mapping) else None
    value = bindings.get("value") if isinstance(bindings, Mapping) else None
    if value is None:
        # The typed comparison evidence publishes the compared dynamic value
        # directly; it proves loop progress just like a numeric binding.
        value = details.get("actual")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0:
        return None
    return int(math.floor(numeric))


def _formal_action_trigger_key(
    invocation: _FormalAbilityInvocation,
) -> str | None:
    definition = invocation.action_definition
    return definition.skill_trigger_key if definition is not None else None


def _formal_condition_provider(
    rules: RuleBook,
    state: BattleState,
    invocation: _FormalAbilityInvocation,
    target_resolution: TargetResolution,
    task_id: str,
):
    base = admitted_action_condition_fact_provider(
        rules,
        state,
        command=cast(ActionCommand, invocation.action_command),
        action_definition=cast(ActionDefinitionIR, invocation.action_definition),
        target_resolution=target_resolution,
        window=f"ability_task_graph:{task_id}",
    ) if invocation.invocation_kind == "action" else None
    if invocation.param_status_scope is not None:
        from .status_callbacks import TaskGraphStatusConditionProvider

        return TaskGraphStatusConditionProvider(state, invocation.param_status_scope,
            base.invocation_id if base is not None else _ability_instance_id(state, invocation),
            base.window if base is not None else f"ability_task_graph:{task_id}", fallback=base)
    return base


def _ability_instance_id(state: BattleState, invocation: _FormalAbilityInvocation) -> str:
    if invocation.stable_ability_instance_id:
        return invocation.stable_ability_instance_id
    value = (
        f"ability_{invocation.invocation_kind}:{state.event_index}:"
        f"{invocation.actor_id}:{invocation.ability_id}:{invocation.ability_level}"
    )
    object.__setattr__(invocation, "stable_ability_instance_id", value)
    return value


def _binding_sources(
    rules: RuleBook,
    state: BattleState,
    actor_id: str,
    primary_target: str | None,
    *,
    action_level: int | None = None,
    action_id: str = "",
    current_action_trigger_key: str | None = None,
    ability_instance_id: str = "",
    ability_name: str = "",
    template_binding_sources: tuple[Mapping[str, JSONValue], ...] = (),
) -> tuple[dict[str, JSONValue], ...]:
    store_binding = binding_source_from_store(
        store_from_state(state), excluded_scopes=("status",),
        visible_scope={"target_id": actor_id, "ability_instance_id": ability_instance_id},
    )
    initial = character_declared_dynamic_binding_source(
        rules, state, actor_id, ability_instance_id=ability_instance_id,
        excluded_hashes=tuple(store_binding.get("by_hash", {})),
    )
    if initial is None:
        initial = servant_declared_dynamic_binding_source(
            rules, state, actor_id, ability_instance_id=ability_instance_id,
            excluded_hashes=tuple(store_binding.get("by_hash", {})),
        )

    sources = (
        store_binding,
        *character_skill_param_binding_sources(
            rules,
            state,
            (actor_id,),
            action_level=action_level,
            current_action_trigger_key=current_action_trigger_key,
            include_unowned_rank_defaults=True,
        ),
        *monster_skill_param_binding_sources(rules, state, actor_id, action_id, action_level),
        *monster_standalone_skill_param_binding_sources(rules, state, actor_id, action_id),
        *((initial,) if initial else ()),
    )
    # Ability-local declared slots only fill values no other source provides;
    # a declared skill parameter or committed writer must win over the zero
    # baseline.
    declared_hashes = {
        str(key)
        for source in sources
        for key in (
            source.get("by_hash", {}).keys()
            if isinstance(source.get("by_hash"), dict)
            else ()
        )
    }
    ability_initial = (
        ability_declared_dynamic_binding_source(
            rules, state, ability_name, actor_id,
            ability_instance_id=ability_instance_id,
            excluded_hashes=tuple(sorted(declared_hashes)),
        )
        if ability_name
        else None
    )
    sources = (*sources, *((ability_initial,) if ability_initial else ()))
    # The same action parameter occurs in multiple hit profiles. Bind it once;
    # committed values take precedence and conflicting profile values stay unbound.
    values: dict[str, set[float]] = {}
    traces = []
    for profile in rules.hit_profiles_for_action(action_id, action_level or 0) if action_id else ():
        expression = profile.stance_expr
        if (profile.coverage_status == "executable" and expression.get("kind") == "fixed"
                and expression.get("source_kind") == "adopted_fixed_skill_toughness"):
            values.setdefault(str(expression["dynamic_hash"]), set()).add(float(expression["value"]))
            traces.append(expression["source_trace"])
    bound = {str(key) for source in sources for field in ("by_hash", "values")
             for key in source.get(field, {})}
    parameters = {key: next(iter(items)) for key, items in values.items() if len(items) == 1 and key not in bound}
    sources = (*sources, {"source_type": "action_toughness_parameters", "values": parameters,
                          "source_trace": traces}) if parameters else sources
    return with_template_binding_sources(sources, template_binding_sources)


def _action_trigger_key(action_definition: ActionDefinitionIR) -> str:
    return action_definition.skill_trigger_key


def _damage_targets_for_emission(
    target_group: str,
    target_resolution: TargetResolution,
    *,
    state: BattleState | None = None,
    attacker_id: str = "",
) -> tuple[str, ...]:
    selected = tuple(target_resolution.selected)
    primary = target_resolution.primary or (selected[0] if selected else None)
    impact_group = tuple(target_resolution.impact_group) or selected
    if target_group in {"selected", "single"}:
        return selected
    if target_group == "primary":
        return (primary,) if primary else ()
    if target_group == "adjacent":
        return tuple(target_id for target_id in impact_group if target_id != primary)
    if target_group in {"aoe", "all_enemy"}:
        return impact_group
    if target_group == "all_teammate":
        # The source alias is relative to the caster. Only units that can still
        # receive damage are packet targets; the caster's own corpse is not.
        if state is None or not attacker_id:
            return ()
        attacker = state.units.get(attacker_id)
        if attacker is None:
            return ()
        lifecycle = UnitLifecycleSystem()
        return tuple(
            unit_id
            for unit_id, unit in sorted(state.units.items())
            # AllTeammate is the caster's team without the caster itself; the
            # alias excludes the owner, so the death explosion never hits the
            # corpse that produced it.
            if unit_id != attacker_id
            and is_same_combat_team(attacker, unit)
            and lifecycle.can_receive_damage(state, unit_id)[0]
        )
    if target_group.startswith("bounce:") and target_resolution.source == "task_graph_executor":
        return selected
    return ()


def _expression_binding_sources(expression: object) -> tuple[dict[str, JSONValue], ...]:
    if not isinstance(expression, dict):
        return ()
    source = expression.get("binding_source")
    return (
        ({**source, "binding_role": "compiled_expression_fallback"},)
        if isinstance(source, dict)
        else ()
    )
