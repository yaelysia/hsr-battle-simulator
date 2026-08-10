from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from simulator_v8_clean_core.core.model import ActionCommand, BattleState, JSONValue
from simulator_v8_clean_core.core.transition_consumer import (
    transition_blocked_reason as _transition_blocked_reason,
    transition_successor_state as _transition_successor_state,
)
from simulator_v8_clean_core.rules.ir import CanonicalIR
from simulator_v8_clean_core.rules.rulebook import RuleBook
from simulator_v8_clean_core.scenarios import IdentityResolver, ScenarioLoader, ScenarioStateBuilder
from simulator_v8_clean_core.scenarios.schema import ScenarioSpec
from simulator_v8_clean_core.systems.scheduler import CombatScheduler
from simulator_v8_clean_core.systems.decision import CurrentDecision, DecisionSystem
from simulator_v8_clean_core.tbgd.lowering import TBGDLowering
from simulator_v8_clean_core.tbgd.paths import find_tbgd_root

from . import UI_REPORT_SCHEMA_VERSION
from .report import (
    build_action_prompt,
    build_battlefield_view,
    build_event_replay_view,
    build_step_report,
    scenario_to_json,
    transition_summary,
    validation_blocked_step,
)


RunMode = Literal["decision"]


@dataclass(frozen=True)
class UIRunOptions:
    mode: RunMode = "decision"
    initialize_timeline: bool = True
    include_raw_transition: bool = True
    write_tmp_report: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "UIRunOptions":
        raw = data or {}
        mode = str(raw.get("mode", "decision"))
        if mode != "decision":
            raise ValueError("运行模式只能是 'decision'")
        return cls(
            mode=mode,  # type: ignore[arg-type]
            initialize_timeline=bool(raw.get("initialize_timeline", True)),
            include_raw_transition=bool(raw.get("include_raw_transition", True)),
            write_tmp_report=bool(raw.get("write_tmp_report", True)),
        )


@dataclass(frozen=True)
class _PromptPreparation:
    state: BattleState
    decision: CurrentDecision | None = None
    transitions: tuple[dict[str, JSONValue], ...] = ()
    auto_skip_records: tuple[dict[str, JSONValue], ...] = ()
    process_notice_records: tuple[dict[str, JSONValue], ...] = ()
    blocked_records: tuple[dict[str, JSONValue], ...] = ()


class UIRunner:
    def __init__(
        self,
        *,
        hsr_root: Path | None = None,
        tbgd_root: Path | None = None,
        tmp_output_root: Path = Path("/tmp/hsr_v8_ui_runs"),
    ) -> None:
        self.hsr_root = (hsr_root or Path(__file__).resolve().parents[1]).resolve()
        self.tbgd_root = (tbgd_root or find_tbgd_root(self.hsr_root)).resolve()
        self.tmp_output_root = tmp_output_root
        self._ir: CanonicalIR | None = None
        self._rules: RuleBook | None = None

    @property
    def rules(self) -> RuleBook:
        if self._rules is None:
            self._ir = TBGDLowering(self.tbgd_root).build()
            self._rules = RuleBook(self._ir)
        return self._rules

    @property
    def ir(self) -> CanonicalIR:
        _ = self.rules
        if self._ir is None:
            raise RuntimeError("Canonical IR 尚未构建")
        return self._ir

    def run_data(
        self,
        scenario_data: dict[str, Any],
        *,
        options: UIRunOptions | None = None,
        observations: dict[str, Any] | None = None,
    ) -> dict[str, JSONValue]:
        run_options = options or UIRunOptions()
        scenario = ScenarioLoader().load_dict(scenario_data)
        validation = IdentityResolver(self.rules).validate(scenario)
        if not validation.ok:
            return self._validation_blocked_report(
                scenario=scenario,
                scenario_data=scenario_data,
                validation=validation.to_json(),
                options=run_options,
                observations=observations or {},
            )

        build = ScenarioStateBuilder(self.rules).build(scenario)
        state = build.state
        initial_snapshot = state.snapshot().to_json()
        scheduler = CombatScheduler(self.rules)
        decisions = DecisionSystem(self.rules)
        timeline_init_transition: dict[str, JSONValue] | None = None
        if run_options.initialize_timeline:
            explicit_overrides = _explicit_action_value_unit_ids(scenario)
            timeline_result = scheduler.initialize_timeline(state, explicit_overrides=explicit_overrides)
            state = _transition_successor_state(state, timeline_result.after_state, timeline_result.transition.to_json())
            timeline_init_transition = timeline_result.transition.to_json()

        steps: list[dict[str, JSONValue]] = []
        auto_skip_records: list[dict[str, JSONValue]] = []
        process_notice_records: list[dict[str, JSONValue]] = []
        prompt_preparation_transitions: list[dict[str, JSONValue]] = []
        prompt_preparation_blocked: list[dict[str, JSONValue]] = []
        for index, command in enumerate(build.commands):
            advance = decisions.advance_to_decision(state)
            for prepared in advance.transitions:
                prompt_preparation_transitions.append(
                    {
                        "stage": "decision_advance",
                        "transition": transition_summary(prepared.to_json()),
                    }
                )
            before_state = advance.after_state
            if not advance.decision.ready or advance.decision.token is None:
                result = decisions.scheduler.reject_decision_submission(
                    before_state,
                    advance.blocked_reason or "decision_not_ready",
                    {
                        "command": {
                            "actor_id": command.actor_id,
                            "action_id": command.action_id,
                            "action_level": command.action_level,
                            "target_ids": list(command.target_ids),
                            "source": command.source,
                        }
                    },
                )
            else:
                result = decisions.submit(
                    before_state,
                    advance.decision.token,
                    command,
                )
            after_state = _transition_successor_state(
                before_state,
                result.after_state,
                result.transition.to_json(),
            )
            transition = result.transition
            child_transitions = result.child_transitions
            steps.append(
                build_step_report(
                    route_index=index,
                    command=command,
                    before_state=before_state,
                    after_state=after_state,
                    transition=transition,
                    child_transitions=child_transitions,
                    rules=self.rules,
                    scenario_data=scenario_data,
                    include_raw_transition=run_options.include_raw_transition,
                )
            )
            state = after_state

        prompt_preparation = _prepare_action_prompt_state(
            state,
            decisions=decisions,
        )
        state = prompt_preparation.state
        final_snapshot = state.snapshot().to_json()
        step_blocked_records = _flatten_step_records(steps, "blocked_records")
        step_coverage_gap_records = _flatten_step_records(steps, "coverage_gap_records")
        step_process_notice_records = _flatten_step_records(steps, "process_notice_records")
        auto_skip_records.extend(prompt_preparation.auto_skip_records)
        process_notice_records.extend(step_process_notice_records)
        process_notice_records.extend(prompt_preparation.process_notice_records)
        prompt_preparation_transitions.extend(prompt_preparation.transitions)
        prompt_preparation_blocked.extend(prompt_preparation.blocked_records)
        blocked_records = [*build.blocked_setup, *step_blocked_records, *prompt_preparation_blocked]
        coverage_gap_records = step_coverage_gap_records
        report: dict[str, JSONValue] = {
            "schema_version": UI_REPORT_SCHEMA_VERSION,
            "scenario_id": scenario.scenario_id,
            "validation": {
                **validation.to_json(),
                "build_source_traces": list(build.source_traces),
                "build_setup_records": list(build.setup_records),
                "build_blocked_setup": list(build.blocked_setup),
            },
            "options": _options_to_json(run_options),
            "scenario": scenario_to_json(scenario),
            "setup_records": list(build.setup_records),
            "initial_snapshot": initial_snapshot,
            "timeline_init_transition": timeline_init_transition,
            "steps": steps,
            "final_snapshot": final_snapshot,
            "battlefield_view": build_battlefield_view(final_snapshot, scenario_data),
            "action_prompt": build_action_prompt(
                final_snapshot,
                scenario_data,
                prompt_preparation.decision.to_json()
                if prompt_preparation.decision is not None
                else {},
            ),
            "event_replay_view": build_event_replay_view(
                steps,
                auto_skip_records=auto_skip_records,
            ),
            "prompt_preparation_transitions": prompt_preparation_transitions,
            "auto_skip_records": auto_skip_records,
            "blocked_records": blocked_records,
            "coverage_gap_records": coverage_gap_records,
            "process_notice_records": process_notice_records,
            "observations": observations or {},
            "run_artifacts": {},
        }
        if run_options.write_tmp_report:
            report["run_artifacts"] = self._write_tmp_report(report, scenario.scenario_id, run_options.mode)
        return report

    def catalog(self) -> dict[str, JSONValue]:
        ir = self.ir
        action_slots_by_entity = _action_slots_by_entity(ir=ir)
        trace_nodes_by_entity = _trace_nodes_by_entity(ir=ir)
        return {
            "schema_version": "v8_ui_catalog_v0_3",
            "summary": {
                "entities": len(ir.entities),
                "avatar_profiles": len(ir.avatar_profiles),
                "action_definitions": len(ir.action_definitions),
                "combatant_profiles": len(ir.combatant_profiles),
                "character_data_cards": len(ir.character_data_cards),
                "status_callbacks": len(ir.status_callbacks),
            },
            "entities": [_entity_summary(entity) for entity in ir.entities],
            "avatar_profiles": [_avatar_profile_summary(profile) for profile in ir.avatar_profiles],
            "actions": [_action_summary(action) for action in ir.action_definitions],
            "combatant_profiles": [_profile_summary(profile) for profile in ir.combatant_profiles],
            "character_cards": [_card_summary(card) for card in ir.character_data_cards],
            "action_slots_by_entity": action_slots_by_entity,
            "trace_nodes_by_entity": trace_nodes_by_entity,
        }

    def _validation_blocked_report(
        self,
        *,
        scenario: ScenarioSpec,
        scenario_data: dict[str, Any],
        validation: dict[str, JSONValue],
        options: UIRunOptions,
        observations: dict[str, Any],
    ) -> dict[str, JSONValue]:
        errors = tuple(str(item) for item in validation.get("errors", []) if str(item))
        steps = [
            validation_blocked_step(route_index=index, route_step=step, errors=errors)
            for index, step in enumerate(scenario.route)
        ]
        report: dict[str, JSONValue] = {
            "schema_version": UI_REPORT_SCHEMA_VERSION,
            "scenario_id": scenario.scenario_id,
            "validation": validation,
            "options": _options_to_json(options),
            "initial_snapshot": None,
            "timeline_init_transition": None,
            "steps": steps,
            "final_snapshot": None,
            "battlefield_view": build_battlefield_view({}, scenario_data),
            "action_prompt": {
                "available": False,
                "current_unit_id": "",
                "reason": "测试用例校验未通过，未构建战斗状态",
                "slots": [],
                "targets": [],
            },
            "event_replay_view": build_event_replay_view(steps),
            "prompt_preparation_transitions": [],
            "auto_skip_records": [],
            "blocked_records": _flatten_step_records(steps, "blocked_records"),
            "coverage_gap_records": _flatten_step_records(steps, "coverage_gap_records"),
            "process_notice_records": _flatten_step_records(steps, "process_notice_records"),
            "observations": observations,
            "scenario": scenario_to_json(scenario),
            "scenario_input": scenario_data,
            "run_artifacts": {},
        }
        if options.write_tmp_report:
            report["run_artifacts"] = self._write_tmp_report(report, scenario.scenario_id, options.mode)
        return report

    def _write_tmp_report(
        self,
        report: dict[str, JSONValue],
        scenario_id: str,
        mode: str,
    ) -> dict[str, JSONValue]:
        self.tmp_output_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = self.tmp_output_root / f"{_safe_id(scenario_id)}_{mode}_{stamp}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {"tmp_report_path": path.as_posix()}


def load_json_file(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("JSON 根节点必须是对象")
    return data


def _explicit_action_value_unit_ids(scenario: ScenarioSpec) -> tuple[str, ...]:
    unit_ids = {
        unit.unit_id
        for unit in scenario.units
        if "action_value" in set(unit.panel.explicit_fields)
    }
    timeline = scenario.battle_setup.timeline
    if timeline is not None and timeline.mode == "explicit_action_values":
        unit_ids.update(timeline.action_values)
        unit_ids.update(timeline.explicit_overrides)
    return tuple(sorted(unit_ids))


def _options_to_json(options: UIRunOptions) -> dict[str, JSONValue]:
    return {
        "mode": options.mode,
        "initialize_timeline": options.initialize_timeline,
        "include_raw_transition": options.include_raw_transition,
        "write_tmp_report": options.write_tmp_report,
    }


def _prepare_action_prompt_state(
    state: BattleState,
    *,
    decisions: DecisionSystem,
) -> _PromptPreparation:
    advance = decisions.advance_to_decision(state)
    transitions = tuple(
        {
            "stage": "prepare_action_prompt_decision_advance",
            "transition": transition_summary(item.to_json()),
        }
        for item in advance.transitions
    )
    blocked_records: tuple[dict[str, JSONValue], ...] = ()
    if not advance.decision.ready and advance.blocked_reason:
        blocked_records = (
            {
                "record_type": "ui_decision_not_ready",
                "category": "阻断",
                "reason": advance.blocked_reason,
                "produced_mutation": False,
            },
        )
    return _PromptPreparation(
        state=advance.after_state,
        decision=advance.decision,
        transitions=transitions,
        blocked_records=blocked_records,
    )


def _flatten_step_records(steps: list[dict[str, JSONValue]], key: str) -> list[dict[str, JSONValue]]:
    result: list[dict[str, JSONValue]] = []
    for step in steps:
        route_index = step.get("route_index")
        for record in _list(step.get(key)):
            item = _dict(record)
            result.append({"route_index": route_index, **item})
    return result


def _entity_summary(entity: Any) -> dict[str, JSONValue]:
    fields = getattr(entity, "fields", {})
    name = ""
    if isinstance(fields, dict):
        for key in ("name", "Name", "modifier_name", "ModifierName", "SkillName"):
            value = fields.get(key)
            if isinstance(value, str) and value:
                name = value
                break
    return {
        "entity_id": getattr(entity, "entity_id", ""),
        "entity_type": getattr(entity, "entity_type", ""),
        "name": name,
        "source": _source_json(entity),
    }


def _avatar_profile_summary(profile: Any) -> dict[str, JSONValue]:
    return {
        "avatar_profile_id": getattr(profile, "avatar_profile_id", ""),
        "avatar_id": getattr(profile, "avatar_id", ""),
        "entity_ref": f"avatar:{getattr(profile, 'avatar_id', '')}",
        "base_type": getattr(profile, "base_type", ""),
        "damage_type": getattr(profile, "damage_type", ""),
        "skill_ids": list(getattr(profile, "skill_ids", ())),
        "promotion_tier_count": len(getattr(profile, "promotion_tiers", ())),
        "max_energy": getattr(profile, "max_energy", None),
        "coverage_status": getattr(profile, "coverage_status", ""),
        "blocked_reason": getattr(profile, "blocked_reason", ""),
        "source": _source_json(profile),
    }


def _action_summary(action: Any) -> dict[str, JSONValue]:
    return {
        "action_id": getattr(action, "action_id", ""),
        "level": getattr(action, "level", 0),
        "definition_id": getattr(action, "definition_id", ""),
        "attack_type": getattr(action, "attack_type", ""),
        "skill_effect": getattr(action, "skill_effect", ""),
        "target_mode": getattr(action, "target_mode", ""),
        "bp_need": getattr(action, "bp_need", 0),
        "bp_add": getattr(action, "bp_add", 0),
        "sp_base": getattr(action, "sp_base", 0),
        "damage_formula_family": getattr(action, "damage_formula_family", ""),
        "coverage_status": getattr(action, "coverage_status", ""),
        "blocked_reason": getattr(action, "blocked_reason", ""),
        "source": _source_json(action),
    }


def _profile_summary(profile: Any) -> dict[str, JSONValue]:
    return {
        "profile_id": getattr(profile, "profile_id", ""),
        "entity_id": getattr(profile, "entity_id", ""),
        "coverage_status": getattr(profile, "coverage_status", ""),
        "blocked_reason": getattr(profile, "blocked_reason", ""),
        "base_stats": getattr(profile, "base_stats", {}),
        "toughness_profile": getattr(profile, "toughness_profile", {}),
        "weaknesses": list(getattr(profile, "weaknesses", ())),
        "source": _source_json(profile),
    }


def _card_summary(card: Any) -> dict[str, JSONValue]:
    return {
        "card_id": getattr(card, "card_id", ""),
        "entity_ref": getattr(card, "entity_ref", ""),
        "coverage_status": getattr(card, "coverage_status", ""),
        "blocked_reason": getattr(card, "blocked_reason", ""),
        "skill_ids": list(getattr(card, "skill_ids", ())),
        "action_set": getattr(card, "action_set", {}),
        "source": _source_json(card),
    }


SLOT_DEFINITIONS: tuple[tuple[str, str, str, str], ...] = (
    ("basic", "普攻", "Normal", "Skill01"),
    ("skill", "战技", "BPSkill", "Skill02"),
    ("ultimate", "终结技", "Ultra", "Skill03"),
)


def _action_slots_by_entity(*, ir: CanonicalIR) -> dict[str, JSONValue]:
    actions_by_id: dict[str, list[Any]] = {}
    for action in ir.action_definitions:
        actions_by_id.setdefault(str(getattr(action, "action_id", "")), []).append(action)

    result: dict[str, JSONValue] = {}
    card_entity_refs = set()
    for card in sorted(ir.character_data_cards, key=lambda item: str(getattr(item, "entity_ref", ""))):
        entity_ref = str(getattr(card, "entity_ref", ""))
        if not entity_ref:
            continue
        card_entity_refs.add(entity_ref)
        result[entity_ref] = _slots_for_skill_ids(
            skill_ids=tuple(str(item) for item in getattr(card, "skill_ids", ())),
            entity_ref=entity_ref,
            action_set=getattr(card, "action_set", {}),
            actions_by_id=actions_by_id,
            source_kind="CharacterDataCardIR.action_set",
            source_trace={
                "card_id": getattr(card, "card_id", ""),
                "entity_ref": entity_ref,
                "selection_policy": getattr(card, "action_set", {}).get("selection_policy", ""),
                "coverage_status": getattr(card, "coverage_status", ""),
                "blocked_reason": getattr(card, "blocked_reason", ""),
                "source": _source_json(card),
            },
        )

    for profile in sorted(ir.avatar_profiles, key=lambda item: str(getattr(item, "avatar_id", ""))):
        avatar_id = str(getattr(profile, "avatar_id", ""))
        entity_ref = f"avatar:{avatar_id}" if avatar_id else ""
        if not entity_ref or entity_ref in card_entity_refs:
            continue
        result[entity_ref] = _slots_for_skill_ids(
            skill_ids=tuple(str(item) for item in getattr(profile, "skill_ids", ())),
            entity_ref=entity_ref,
            action_set={},
            actions_by_id=actions_by_id,
            source_kind="AvatarProfileIR.skill_ids",
            source_trace={
                "avatar_profile_id": getattr(profile, "avatar_profile_id", ""),
                "entity_ref": entity_ref,
                "coverage_status": getattr(profile, "coverage_status", ""),
                "blocked_reason": getattr(profile, "blocked_reason", ""),
                "source": _source_json(profile),
            },
        )
    return result


def _slots_for_skill_ids(
    *,
    skill_ids: tuple[str, ...],
    entity_ref: str,
    action_set: dict[str, JSONValue],
    actions_by_id: dict[str, list[Any]],
    source_kind: str,
    source_trace: dict[str, JSONValue],
) -> list[dict[str, JSONValue]]:
    slots = []
    for slot, label, attack_type, skill_trigger_key in SLOT_DEFINITIONS:
        action_set_ids = _action_set_action_ids(action_set, skill_trigger_key)
        candidate_skill_ids = action_set_ids if action_set_ids else skill_ids
        matching = [
            action
            for skill_id in candidate_skill_ids
            for action in _actions_for_skill_id(skill_id, entity_ref=entity_ref, actions_by_id=actions_by_id)
            if str(getattr(action, "attack_type", "")) == attack_type
        ]
        slots.append(
            _action_slot(
                slot=slot,
                label=label,
                attack_type=attack_type,
                skill_trigger_key=skill_trigger_key,
                candidates=matching,
                source_kind=source_kind,
                source_trace=source_trace,
            )
        )
    return slots


def _action_set_action_ids(action_set: dict[str, JSONValue], skill_trigger_key: str) -> tuple[str, ...]:
    actions = action_set.get("actions")
    if not isinstance(actions, list):
        return ()
    action_ids: list[str] = []
    for item in actions:
        if not isinstance(item, dict):
            continue
        if str(item.get("skill_trigger_key") or "") != skill_trigger_key:
            continue
        action_id = str(item.get("action_id") or item.get("raw_skill_id") or "")
        if action_id and action_id not in action_ids:
            action_ids.append(action_id)
    return tuple(action_ids)


def _actions_for_skill_id(
    skill_id: str,
    *,
    entity_ref: str,
    actions_by_id: dict[str, list[Any]],
) -> list[Any]:
    action_ids = [skill_id]
    if ":" not in skill_id and entity_ref.startswith("avatar:"):
        action_ids.append(f"avatar_skill:{skill_id}")
    seen: set[tuple[str, int]] = set()
    actions: list[Any] = []
    for action_id in action_ids:
        for action in actions_by_id.get(action_id, []):
            key = (str(getattr(action, "action_id", "")), int(getattr(action, "level", 0)))
            if key in seen:
                continue
            seen.add(key)
            actions.append(action)
    return actions


def _action_slot(
    *,
    slot: str,
    label: str,
    attack_type: str,
    skill_trigger_key: str,
    candidates: list[Any],
    source_kind: str,
    source_trace: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    action_ids = sorted({str(getattr(action, "action_id", "")) for action in candidates if getattr(action, "action_id", "")})
    candidate_json = [_action_summary(action) for action in sorted(candidates, key=lambda item: (str(getattr(item, "action_id", "")), int(getattr(item, "level", 0))))]
    base: dict[str, JSONValue] = {
        "slot": slot,
        "label": label,
        "expected_attack_type": attack_type,
        "expected_skill_trigger_key": skill_trigger_key,
        "source_kind": source_kind,
        "source_trace": source_trace,
        "candidates": candidate_json,
    }
    if not candidates:
        return {
            **base,
            "available": False,
            "action_ref": "",
            "action_level": 0,
            "blocked_reason": f"动作列表中没有 attack_type={attack_type} 的动作定义",
        }
    if len(action_ids) != 1:
        return {
            **base,
            "available": False,
            "action_ref": "",
            "action_level": 0,
            "blocked_reason": "同一槽位存在多个 action_ref，UI 不自动选择",
        }
    selected = sorted(candidates, key=lambda item: int(getattr(item, "level", 0)))[-1]
    coverage_status = str(getattr(selected, "coverage_status", ""))
    available = coverage_status == "executable"
    return {
        **base,
        "available": available,
        "action_ref": str(getattr(selected, "action_id", "")),
        "action_level": int(getattr(selected, "level", 0)),
        "definition_id": str(getattr(selected, "definition_id", "")),
        "attack_type": str(getattr(selected, "attack_type", "")),
        "skill_effect": str(getattr(selected, "skill_effect", "")),
        "target_mode": str(getattr(selected, "target_mode", "")),
        "coverage_status": coverage_status,
        "blocked_reason": "" if available else f"ActionDefinitionIR coverage_status={coverage_status}，不可执行",
        "action_source_trace": _source_json(selected),
    }


def _trace_nodes_by_entity(*, ir: CanonicalIR) -> dict[str, JSONValue]:
    slots_by_id = {
        str(getattr(slot, "mechanism_slot_id", "")): slot
        for slot in ir.character_mechanism_slots
        if str(getattr(slot, "mechanism_slot_id", ""))
    }
    result: dict[str, JSONValue] = {}
    for card in sorted(ir.character_data_cards, key=lambda item: str(getattr(item, "entity_ref", ""))):
        entity_ref = str(getattr(card, "entity_ref", ""))
        card_id = str(getattr(card, "card_id", ""))
        if not entity_ref or not card_id:
            continue
        nodes = [
            node
            for node in ir.character_trace_nodes
            if str(getattr(node, "character_data_card_id", "")) == card_id
        ]
        summaries = [
            _trace_node_summary(node, slots_by_id=slots_by_id)
            for node in sorted(nodes, key=lambda item: (str(getattr(item, "trace_id", "")), str(getattr(item, "trace_node_id", ""))))
        ]
        result[entity_ref] = summaries
    return result


def _trace_node_summary(node: Any, *, slots_by_id: dict[str, Any]) -> dict[str, JSONValue]:
    linked_slot_ids = tuple(str(item) for item in getattr(node, "linked_mechanism_slot_ids", ()))
    linked_slots = [slots_by_id[slot_id] for slot_id in linked_slot_ids if slot_id in slots_by_id]
    mapped_terms: list[dict[str, JSONValue]] = []
    source_traces: list[dict[str, JSONValue]] = []
    executable = True
    blocked_reasons: list[str] = []
    default_enabled = False
    for slot in linked_slots:
        activation = getattr(slot, "activation", {})
        semantics = getattr(slot, "semantics", {})
        if isinstance(activation, dict) and activation.get("default_enabled") is True:
            default_enabled = True
        coverage_status = str(getattr(slot, "coverage_status", ""))
        blocked_reason = str(getattr(slot, "blocked_reason", "") or "")
        if coverage_status != "executable":
            executable = False
            blocked_reasons.append(blocked_reason or f"mechanism_slot_not_executable:{coverage_status}")
        if isinstance(semantics, dict):
            for term in _list(semantics.get("mapped_terms")):
                if isinstance(term, dict):
                    mapped_terms.append(
                        {
                            "mechanism_slot_id": str(getattr(slot, "mechanism_slot_id", "")),
                            "application_kind": str(term.get("application_kind") or ""),
                            "target_key": str(term.get("target_key") or ""),
                            "value": term.get("value"),
                        }
                    )
        source_traces.append(_source_json(slot))
    node_status = str(getattr(node, "coverage_status", ""))
    node_blocked = str(getattr(node, "blocked_reason", "") or "")
    if node_status not in {"executable", "lowered", "validated"}:
        executable = False
        if node_blocked:
            blocked_reasons.append(node_blocked)
    return {
        "trace_node_id": str(getattr(node, "trace_node_id", "")),
        "character_data_card_id": str(getattr(node, "character_data_card_id", "")),
        "avatar_id": str(getattr(node, "avatar_id", "")),
        "trace_id": str(getattr(node, "trace_id", "")),
        "trace_kind": str(getattr(node, "trace_kind", "")),
        "linked_mechanism_slot_ids": list(linked_slot_ids),
        "default_enabled": default_enabled,
        "available": executable,
        "coverage_status": node_status,
        "blocked_reason": "；".join(dict.fromkeys(blocked_reasons)),
        "mapped_terms": mapped_terms,
        "source": _source_json(node),
        "slot_source_traces": source_traces,
    }


def _source_json(value: Any) -> dict[str, JSONValue]:
    source = getattr(value, "source", None)
    return source.to_json() if hasattr(source, "to_json") else {}


def _safe_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return safe or "scenario"


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []
