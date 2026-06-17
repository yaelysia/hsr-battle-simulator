from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .coverage import classify_opcode
from .paths import relative_source_path
from .. import BASELINE_VERSION
from ..rules.ir import (
    ActionDefinitionIR,
    ActionEventIR,
    ActionPhaseStepIR,
    CanonicalIR,
    ConditionIR,
    EffectIR,
    FormulaIR,
    HitProfileIR,
    IRSource,
    RuleEntity,
    TriggerIR,
)


ENTITY_TABLES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "ExcelOutput/AvatarConfig.json": ("avatar", "AvatarID", ("DamageType", "SPNeed", "SkillList", "AvatarBaseType", "Rarity")),
    "ExcelOutput/AvatarConfigLD.json": ("avatar", "AvatarID", ("DamageType", "SPNeed", "SkillList", "AvatarBaseType", "Rarity")),
    "ExcelOutput/AvatarSkillConfig.json": (
        "avatar_skill",
        "SkillID",
        ("SkillTriggerKey", "SkillEffect", "AttackType", "MaxLevel", "SkillIcon", "UltraSkillIcon"),
    ),
    "ExcelOutput/AvatarSkillConfigLD.json": (
        "avatar_skill",
        "SkillID",
        ("SkillTriggerKey", "SkillEffect", "AttackType", "MaxLevel", "SkillIcon", "UltraSkillIcon"),
    ),
    "ExcelOutput/AvatarPromotionConfig.json": (
        "avatar_promotion",
        "AvatarID",
        ("Promotion", "MaxLevel", "AttackBase", "AttackAdd", "DefenceBase", "DefenceAdd", "HPBase", "HPAdd", "SpeedBase", "CriticalChance", "CriticalDamage", "BaseAggro"),
    ),
    "ExcelOutput/AvatarPromotionConfigLD.json": (
        "avatar_promotion",
        "AvatarID",
        ("Promotion", "MaxLevel", "AttackBase", "AttackAdd", "DefenceBase", "DefenceAdd", "HPBase", "HPAdd", "SpeedBase", "CriticalChance", "CriticalDamage", "BaseAggro"),
    ),
    "ExcelOutput/CommonAvatarSkillConfig.json": (
        "avatar_skill",
        "SkillID",
        ("SkillTriggerKey", "SkillEffect", "AttackType", "MaxLevel"),
    ),
    "ExcelOutput/CommonActiveSkillConfig.json": (
        "active_skill",
        "SkillID",
        ("SkillTriggerKey", "SkillEffect", "AttackType", "MaxLevel"),
    ),
    "ExcelOutput/AvatarStatusConfigLD.json": (
        "status",
        "StatusID",
        ("ModifierName", "StatusType", "CanDispel", "ReadParamList", "TagList"),
    ),
    "ExcelOutput/ILBattleMonsterSkill.json": (
        "monster_skill",
        "ID",
        ("SkillTriggerKey", "AttackType", "InitialCD", "CoolDown", "ParamList"),
    ),
    "ExcelOutput/MonsterConfig.json": (
        "monster",
        "MonsterID",
        ("MonsterTemplateID", "HardLevelGroup", "AttackModifyRatio", "DefenceModifyRatio", "HPModifyRatio", "SpeedModifyRatio", "StanceModifyRatio", "StanceWeakList", "DamageTypeResistance", "SkillList"),
    ),
    "ExcelOutput/MonsterTemplateConfig.json": (
        "monster_template",
        "MonsterTemplateID",
        ("Rank", "AttackBase", "DefenceBase", "HPBase", "SpeedBase", "StanceBase", "CriticalDamageBase", "StatusResistanceBase", "StanceType", "AIPath", "AISkillSequence"),
    ),
    "ExcelOutput/SummonUnitData.json": (
        "summon_unit",
        "ID",
        ("JsonPath", "MaxSummonCount", "UniqueGroup", "DestroyOnEnterBattle"),
    ),
    "ExcelOutput/RelicSetSkillConfig.json": (
        "relic_set_skill",
        "SetID",
        ("SkillList", "SetSkillList", "AbilityName", "ParamList"),
    ),
    "ExcelOutput/AvatarBreakDamage.json": (
        "break_damage",
        "Level",
        ("BreakBaseDamage", "HardnessBaseDamage"),
    ),
}


ACTION_DEFINITION_TABLES: tuple[tuple[str, str, str], ...] = (
    ("ExcelOutput/AvatarSkillConfig.json", "avatar_skill", "SkillID"),
    ("ExcelOutput/AvatarSkillConfigLD.json", "avatar_skill", "SkillID"),
    ("ExcelOutput/CommonAvatarSkillConfig.json", "avatar_skill", "SkillID"),
    ("ExcelOutput/CommonActiveSkillConfig.json", "active_skill", "SkillID"),
    ("ExcelOutput/ILBattleMonsterSkill.json", "monster_skill", "ID"),
)


ELATION_MECHANIC_FILES: tuple[str, ...] = (
    "Config/GlobalConfig/GameCoreConstValue.json",
    "Config/GlobalConfig/PriorityConfig.json",
)


DAMAGE_BEHAVIOR_TEMPLATE_FILE = "Config/GlobalConfig/DamageBehaviorTemplateListConfig.json"


@dataclass(frozen=True)
class LoweringLimits:
    max_records_per_table: int | None = None
    max_ability_files: int | None = 120
    max_callbacks_per_file: int = 200


class TBGDLowering:
    """Converts TBGD raw files into v8 Canonical IR."""

    def __init__(self, tbgd_root: Path, limits: LoweringLimits | None = None):
        self.tbgd_root = tbgd_root.resolve()
        self.limits = limits or LoweringLimits()

    def build(self) -> CanonicalIR:
        entities: list[RuleEntity] = []
        action_definitions: list[ActionDefinitionIR] = []
        triggers: list[TriggerIR] = []
        effects: list[EffectIR] = []
        conditions: list[ConditionIR] = []
        formulas: list[FormulaIR] = []

        table_stats: dict[str, dict[str, Any]] = {}
        for relative_path, spec in ENTITY_TABLES.items():
            entities.extend(self._lower_entity_table(relative_path, spec))
            table_stats[relative_path] = self._table_stats(relative_path, spec[1])
        entities = list(_dedupe_entities(entities).values())
        action_definitions = list(self._lower_action_definitions().values())
        action_events, hit_profiles = _lower_action_execution_ir(action_definitions)
        for relative_path, _, id_key in ACTION_DEFINITION_TABLES:
            table_stats[f"action_definitions:{relative_path}"] = self._table_stats(relative_path, id_key)

        ability_files = self._ability_files()
        selected_ability_files = _limit_sequence(ability_files, self.limits.max_ability_files)
        for path in selected_ability_files:
            lowered = self._lower_ability_file(path)
            entities.extend(lowered.entities)
            triggers.extend(lowered.triggers)
            effects.extend(lowered.effects)
            conditions.extend(lowered.conditions)
            formulas.extend(lowered.formulas)
        entities = list(_dedupe_entities(entities).values())
        formulas.extend(self._lower_elation_mechanics())
        formulas.extend(self._lower_damage_behavior_templates())

        return CanonicalIR(
            version=BASELINE_VERSION,
            entities=tuple(entities),
            action_definitions=tuple(action_definitions),
            action_events=tuple(action_events),
            hit_profiles=tuple(hit_profiles),
            triggers=tuple(triggers),
            effects=tuple(effects),
            conditions=tuple(conditions),
            formulas=tuple(formulas),
            metadata={
                "source": "turnbasedgamedata-main",
                "lowering": "tbgd_first_v0_200",
                "limits": {
                    "max_records_per_table": self.limits.max_records_per_table,
                    "max_ability_files": self.limits.max_ability_files,
                    "max_callbacks_per_file": self.limits.max_callbacks_per_file,
                },
                "sampled": {
                    "entity_tables": self.limits.max_records_per_table is not None,
                    "ability_files": self.limits.max_ability_files is not None
                    and len(selected_ability_files) < len(ability_files),
                },
                "table_status": table_stats,
                "ability_file_status": {
                    "raw_count": len(ability_files),
                    "lowered_count": len(selected_ability_files),
                    "skipped_count": max(0, len(ability_files) - len(selected_ability_files)),
                },
            },
        )

    def _lower_entity_table(
        self,
        relative_path: str,
        spec: tuple[str, str, tuple[str, ...]],
    ) -> list[RuleEntity]:
        entity_type, id_key, field_keys = spec
        path = self.tbgd_root / relative_path
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        entities: list[RuleEntity] = []
        for index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
            if not isinstance(row, dict) or id_key not in row:
                continue
            raw_id = _entity_raw_id(entity_type, id_key, row)
            fields = {key: _json_safe(row.get(key)) for key in field_keys if key in row}
            source = IRSource(
                source_path=relative_path,
                raw_type=Path(relative_path).stem,
                raw_id=raw_id,
                evidence={"row_index": index, "id_key": id_key},
            )
            entities.append(
                RuleEntity(
                    entity_id=f"{entity_type}:{raw_id}",
                    entity_type=entity_type,
                    fields=fields,
                    source=source,
                    coverage_status="audit_only",
                )
            )
        return entities

    def _lower_action_definitions(self) -> dict[tuple[str, int], ActionDefinitionIR]:
        definitions: dict[tuple[str, int], ActionDefinitionIR] = {}
        for relative_path, entity_type, id_key in ACTION_DEFINITION_TABLES:
            path = self.tbgd_root / relative_path
            if not path.exists():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                continue
            for index, row in enumerate(_limit_sequence(data, self.limits.max_records_per_table)):
                if not isinstance(row, dict) or id_key not in row:
                    continue
                definition = _action_definition_from_row(relative_path, entity_type, id_key, index, row)
                definitions[(definition.action_id, definition.level)] = definition
        return definitions

    def _table_stats(self, relative_path: str, id_key: str) -> dict[str, Any]:
        path = self.tbgd_root / relative_path
        if not path.exists():
            return {"raw_count": 0, "lowered_count": 0, "skipped_count": 0, "missing": True}
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return {"raw_count": 0, "lowered_count": 0, "skipped_count": 0, "shape": type(data).__name__}
        selected = _limit_sequence(data, self.limits.max_records_per_table)
        lowered_count = sum(1 for row in selected if isinstance(row, dict) and id_key in row)
        return {
            "raw_count": len(data),
            "lowered_count": lowered_count,
            "skipped_count": max(0, len(data) - len(selected)),
            "sampled": len(selected) < len(data),
            "id_key": id_key,
        }

    def _ability_files(self) -> list[Path]:
        roots = [self.tbgd_root / "Config/ConfigAbility", self.tbgd_root / "Config/ConfigGlobalModifier"]
        files: list[Path] = []
        for root in roots:
            if not root.exists():
                continue
            files.extend(path for path in root.rglob("*.json") if not path.name.endswith(".layout.json"))
        return sorted(files)

    def _lower_ability_file(self, path: Path) -> "_LoweredAbility":
        relative = relative_source_path(self.tbgd_root, path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return _LoweredAbility()
        modifier_maps = self._modifier_maps(data)
        lowered = _LoweredAbility()
        callback_index = 0
        for map_name, modifier_name, modifier in modifier_maps:
            lowered.entities.append(_modifier_definition_entity(relative, map_name, modifier_name, modifier))
            callbacks = modifier.get("_CallbackList") if isinstance(modifier, dict) else None
            if not isinstance(callbacks, list):
                continue
            for callback in callbacks:
                if callback_index >= self.limits.max_callbacks_per_file:
                    return lowered
                callback_index += 1
                if not isinstance(callback, dict):
                    continue
                event = str(callback.get("Event") or "UnknownEvent")
                tasks = callback.get("CallbackConfig") or []
                if not isinstance(tasks, list):
                    continue
                trigger_effects: list[str] = []
                trigger_conditions: list[str] = []
                for task_index, task in enumerate(tasks):
                    task_lowered = self._lower_task(
                        task,
                        relative,
                        map_name,
                        modifier_name,
                        callback_index,
                        task_index,
                        branch="callback",
                    )
                    lowered.merge(task_lowered)
                    trigger_effects.extend(effect.effect_id for effect in task_lowered.effects)
                    trigger_conditions.extend(condition.condition_id for condition in task_lowered.conditions)
                source = IRSource(
                    source_path=relative,
                    raw_type=map_name,
                    raw_id=modifier_name,
                    evidence={"callback_index": callback_index, "event": event},
                )
                lowered.triggers.append(
                    TriggerIR(
                        trigger_id=f"trigger:{relative}:{modifier_name}:{callback_index}",
                        event=event,
                        conditions=tuple(trigger_conditions),
                        effects=tuple(trigger_effects),
                        source=source,
                        coverage_status="audit_only",
                    )
                )
        return lowered

    def _lower_task(
        self,
        task: Any,
        relative: str,
        map_name: str,
        modifier_name: str,
        callback_index: int,
        task_index: int,
        branch: str,
    ) -> "_LoweredAbility":
        lowered = _LoweredAbility()
        if not isinstance(task, dict):
            return lowered
        opcode = _short_gamecore_type(task.get("$type"))
        source = IRSource(
            source_path=relative,
            raw_type=map_name,
            raw_id=modifier_name,
            evidence={"callback_index": callback_index, "task_index": task_index, "branch": branch},
        )
        if opcode == "PredicateTaskList":
            predicate = task.get("Predicate")
            condition = self._lower_condition(predicate, source, task_index)
            if condition:
                lowered.conditions.append(condition)
            for child_index, child in enumerate(task.get("SuccessTaskList") or []):
                child_lowered = self._lower_task(
                    child,
                    relative,
                    map_name,
                    modifier_name,
                    callback_index,
                    child_index,
                    branch="success",
                )
                lowered.merge(child_lowered)
            for child_index, child in enumerate(task.get("FailedTaskList") or []):
                child_lowered = self._lower_task(
                    child,
                    relative,
                    map_name,
                    modifier_name,
                    callback_index,
                    child_index,
                    branch="failed",
                )
                lowered.merge(child_lowered)
            return lowered

        effect_id = f"effect:{relative}:{modifier_name}:{callback_index}:{branch}:{task_index}:{opcode}"
        payload = _effect_payload(task, opcode, modifier_name)
        coverage_status = _effect_coverage_status(opcode, payload)
        lowered.effects.append(
            EffectIR(
                effect_id=effect_id,
                opcode=opcode,
                payload=payload,
                source=source,
                coverage_status=coverage_status,
            )
        )
        lowered.formulas.extend(self._extract_formulas(task, source, effect_id))
        lowered.formulas.extend(_damage_family_evidence(task, opcode, source, effect_id))
        return lowered

    def _lower_condition(self, predicate: Any, source: IRSource, task_index: int) -> ConditionIR | None:
        if not isinstance(predicate, dict):
            return None
        opcode = _short_gamecore_type(predicate.get("$type"))
        payload = _compact_payload(predicate)
        status = "executable" if _condition_payload_executable(opcode, payload) else classify_opcode(opcode)
        return ConditionIR(
            condition_id=f"condition:{source.source_path}:{source.raw_id}:{source.evidence.get('callback_index')}:{task_index}:{opcode}",
            opcode=opcode,
            payload=payload,
            source=source,
            coverage_status=status,
        )

    def _extract_formulas(self, task: Any, source: IRSource, parent_id: str) -> list[FormulaIR]:
        formulas: list[FormulaIR] = []
        for index, expression in enumerate(_iter_postfix_expr(task)):
            formulas.append(
                FormulaIR(
                    formula_id=f"formula:{parent_id}:{index}",
                    kind="postfix_expr",
                    expression=_json_safe(expression),
                    source=source,
                    coverage_status="audit_only",
                )
            )
        for index, fixed_value in enumerate(_iter_fixed_values(task)):
            formulas.append(
                FormulaIR(
                    formula_id=f"formula:{parent_id}:fixed:{index}",
                    kind="fixed_value",
                    expression=_json_safe(fixed_value),
                    source=source,
                    coverage_status="executable",
                )
            )
        return formulas

    def _lower_elation_mechanics(self) -> list[FormulaIR]:
        formulas: list[FormulaIR] = []
        for relative_path in ELATION_MECHANIC_FILES:
            path = self.tbgd_root / relative_path
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for index, (raw_path, key, value) in enumerate(_iter_elation_values(data)):
                mechanic = "elation_damage" if key == "ElationDamageAddedRatio" else "elation_runtime"
                coverage_status = "blocked" if key == "ElationDamageAddedRatio" else "discovered_only"
                source = IRSource(
                    source_path=relative_path,
                    raw_type=Path(relative_path).stem,
                    raw_id=raw_path,
                    evidence={
                        "raw_path": raw_path,
                        "key": key,
                        "mechanic": mechanic,
                        "damage_formula_family": "elation",
                    },
                )
                blocked_reason = (
                    "Elation damage property is discovered in TBGD, "
                    "but the complete 4.0 damage formula is not executable in v0_207"
                )
                formulas.append(
                    FormulaIR(
                        formula_id=f"mechanic:{mechanic}:{relative_path}:{index}",
                        kind="mechanic_property",
                        expression={
                            "mechanic": mechanic,
                            "property": key,
                            "raw_path": raw_path,
                            "value": _json_safe(value),
                            "damage_formula_family": "elation",
                            "source_mode": "mainline",
                            "runtime_status": coverage_status,
                            "blocked_reason": blocked_reason
                            if key == "ElationDamageAddedRatio"
                            else "Elation runtime property discovered for taxonomy evidence",
                        },
                        source=source,
                        coverage_status=coverage_status,
                    )
                )
        return formulas

    def _lower_damage_behavior_templates(self) -> list[FormulaIR]:
        path = self.tbgd_root / DAMAGE_BEHAVIOR_TEMPLATE_FILE
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        config = data.get("ConfigList") if isinstance(data, dict) else None
        if not isinstance(config, dict):
            return []
        formulas: list[FormulaIR] = []
        for name, payload in sorted(config.items()):
            family = _damage_behavior_family(str(name))
            if family == "unknown":
                continue
            source = IRSource(
                source_path=DAMAGE_BEHAVIOR_TEMPLATE_FILE,
                raw_type=Path(DAMAGE_BEHAVIOR_TEMPLATE_FILE).stem,
                raw_id=str(name),
                evidence={
                    "template_name": str(name),
                    "damage_formula_family": family,
                    "bypasses_normal_multipliers": family in {"true_damage", "hp_loss"},
                },
            )
            formulas.append(
                FormulaIR(
                    formula_id=f"mechanic:{family}:{DAMAGE_BEHAVIOR_TEMPLATE_FILE}:{name}",
                    kind="mechanic_property",
                    expression={
                        "mechanic": f"{family}_damage",
                        "property": str(name),
                        "value": _json_safe(payload),
                        "damage_formula_family": family,
                        "source_mode": "mainline",
                        "runtime_status": "executable",
                        "bypasses_normal_multipliers": True,
                    },
                    source=source,
                    coverage_status="lowered",
                )
            )
        return formulas

    def _modifier_maps(self, data: Any) -> list[tuple[str, str, dict[str, Any]]]:
        maps: list[tuple[str, str, dict[str, Any]]] = []
        if not isinstance(data, dict):
            return maps
        ability_list = data.get("AbilityList")
        if isinstance(ability_list, list):
            for ability_index, ability in enumerate(ability_list):
                if not isinstance(ability, dict):
                    continue
                modifiers = ability.get("Modifiers")
                if isinstance(modifiers, dict):
                    maps.extend(("Modifiers", name, value) for name, value in modifiers.items() if isinstance(value, dict))
        modifier_map = data.get("ModifierMap")
        if isinstance(modifier_map, dict):
            maps.extend(("ModifierMap", name, value) for name, value in modifier_map.items() if isinstance(value, dict))
        global_modifiers = data.get("GlobalModifiers")
        if isinstance(global_modifiers, dict):
            maps.extend(("GlobalModifiers", name, value) for name, value in global_modifiers.items() if isinstance(value, dict))
        return maps


@dataclass
class _LoweredAbility:
    entities: list[RuleEntity] = field(default_factory=list)
    triggers: list[TriggerIR] = field(default_factory=list)
    effects: list[EffectIR] = field(default_factory=list)
    conditions: list[ConditionIR] = field(default_factory=list)
    formulas: list[FormulaIR] = field(default_factory=list)

    def merge(self, other: "_LoweredAbility") -> None:
        self.entities.extend(other.entities)
        self.triggers.extend(other.triggers)
        self.effects.extend(other.effects)
        self.conditions.extend(other.conditions)
        self.formulas.extend(other.formulas)


def _short_gamecore_type(raw_type: Any) -> str:
    if not isinstance(raw_type, str):
        return "Unknown"
    return raw_type.removeprefix("RPG.GameCore.")


def _entity_raw_id(entity_type: str, id_key: str, row: dict[str, Any]) -> str:
    if entity_type == "avatar_promotion":
        promotion = row.get("Promotion", 0)
        return f"{row[id_key]}:{promotion}"
    return str(row[id_key])


def _dedupe_entities(entities: list[RuleEntity]) -> dict[str, RuleEntity]:
    deduped: dict[str, RuleEntity] = {}
    for entity in entities:
        deduped[entity.entity_id] = entity
    return deduped


def _modifier_definition_entity(
    relative_path: str,
    map_name: str,
    modifier_name: str,
    modifier: dict[str, Any],
) -> RuleEntity:
    source = IRSource(
        source_path=relative_path,
        raw_type=map_name,
        raw_id=modifier_name,
        evidence={
            "modifier_name": modifier_name,
            "map_name": map_name,
            "definition_kind": "modifier_definition",
        },
    )
    fields = {
        "modifier_name": modifier_name,
        "map_name": map_name,
        "stacking": _json_safe(modifier.get("Stacking")),
        "lifetime": _json_safe(modifier.get("LifeTime")),
        "behavior_flags": _json_safe(modifier.get("BehaviorFlagList", [])),
        "dynamic_values": _json_safe(modifier.get("DynamicValues", {})),
        "dynamic_value_bindings": _dynamic_value_bindings(modifier.get("DynamicValues")),
        "callback_events": _callback_events(modifier),
        "stack_properties": _stack_property_summaries(modifier),
    }
    return RuleEntity(
        entity_id=f"modifier_definition:{modifier_name}",
        entity_type="modifier_definition",
        fields=fields,
        source=source,
        coverage_status="lowered",
    )


def _callback_events(modifier: dict[str, Any]) -> list[str]:
    events: list[str] = []
    callbacks = modifier.get("_CallbackList")
    if not isinstance(callbacks, list):
        return events
    for callback in callbacks:
        if isinstance(callback, dict):
            events.append(str(callback.get("Event") or "UnknownEvent"))
    return events


def _stack_property_summaries(modifier: dict[str, Any]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    callbacks = modifier.get("_CallbackList")
    if not isinstance(callbacks, list):
        return summaries
    for callback_index, callback in enumerate(callbacks):
        if not isinstance(callback, dict):
            continue
        event = str(callback.get("Event") or "UnknownEvent")
        tasks = callback.get("CallbackConfig")
        if not isinstance(tasks, list):
            continue
        for task_index, task in enumerate(tasks):
            if not isinstance(task, dict) or _short_gamecore_type(task.get("$type")) != "StackProperty":
                continue
            summaries.append(
                {
                    "event": event,
                    "callback_index": callback_index,
                    "task_index": task_index,
                    "property": str(task.get("Property") or ""),
                    "target_alias": _target_alias(task.get("TargetType")),
                    "value_expr": _numeric_expr_summary(task.get("PropertyValue")),
                    "is_refresh": bool(task.get("IsRefresh", False)),
                    "raw_path": f"_CallbackList[{callback_index}].CallbackConfig[{task_index}]",
                }
            )
    return summaries


def _action_definition_from_row(
    relative_path: str,
    entity_type: str,
    id_key: str,
    row_index: int,
    row: dict[str, Any],
) -> ActionDefinitionIR:
    raw_id = str(row[id_key])
    action_id = f"{entity_type}:{raw_id}"
    level = int(_number_value(row.get("Level"), 1.0))
    skill_effect = str(row.get("SkillEffect") or row.get("AttackType") or "Unknown")
    attack_type = str(row.get("AttackType") or "Unknown")
    element_type = str(row["StanceDamageType"]) if row.get("StanceDamageType") is not None else None
    source = IRSource(
        source_path=relative_path,
        raw_type=Path(relative_path).stem,
        raw_id=raw_id,
        evidence={
            "row_index": row_index,
            "id_key": id_key,
            "level": level,
            "resource_mapping": {
                "BPNeed": "skill_point_cost_if_positive",
                "BPAdd": "skill_point_gain_if_positive",
                "SPBase": "energy_gain",
            },
            "taxonomy": {
                "attack_type": "raw TBGD AttackType; follow-up is an attack type axis",
                "damage_formula_family": "formula family axis; follow-up is not a damage family",
                "element_type": "raw TBGD StanceDamageType when present",
            },
        },
    )
    return ActionDefinitionIR(
        definition_id=f"action_def:{action_id}:{level}",
        action_id=action_id,
        level=level,
        attack_type=attack_type,
        skill_effect=skill_effect,
        target_mode=_target_mode(skill_effect),
        bp_need=_number_value(row.get("BPNeed"), 0.0),
        bp_add=_number_value(row.get("BPAdd"), 0.0),
        sp_base=_number_value(row.get("SPBase"), 0.0),
        sp_multiple_ratio=_number_value(row.get("SPMultipleRatio"), 0.0),
        param_list=tuple(_list_json_values(row.get("ParamList"))),
        show_stance_list=tuple(_list_json_values(row.get("ShowStanceList"))),
        show_damage_list=tuple(_list_json_values(row.get("ShowDamageList"))),
        stance_damage_type=element_type,
        source=source,
        coverage_status="executable",
        damage_kind=_damage_kind(skill_effect),
        damage_formula_family=_damage_formula_family(attack_type, skill_effect),
        element_type=element_type,
        source_mode=_source_mode(attack_type),
    )


def _lower_action_execution_ir(
    definitions: list[ActionDefinitionIR],
) -> tuple[list[ActionEventIR], list[HitProfileIR]]:
    events: list[ActionEventIR] = []
    profiles: list[HitProfileIR] = []
    for definition in definitions:
        action_profiles = _hit_profiles_from_definition(definition)
        profiles.extend(action_profiles)
        events.append(_action_event_from_definition(definition, action_profiles))
    return events, profiles


def _action_event_from_definition(
    definition: ActionDefinitionIR,
    hit_profiles: list[HitProfileIR],
) -> ActionEventIR:
    has_damage = definition.damage_kind == "hp_damage" and any(
        profile.coverage_status != "blocked" for profile in hit_profiles
    )
    has_attack_windows = _action_definition_is_attack(definition)
    blocked_reason = _target_blocked_reason(definition.target_mode)
    status = "blocked" if blocked_reason else "lowered"
    steps: list[ActionPhaseStepIR] = [
        ActionPhaseStepIR(
            kind="trigger_window",
            phase="before_skill_use",
            canonical_window="before_skill_use",
            tbgd_event="OnBeforeSkillUse",
            coverage_status=status,
            blocked_reason=blocked_reason,
            source=definition.source,
        )
    ]
    if has_attack_windows and not blocked_reason:
        steps.append(
            ActionPhaseStepIR(
                kind="trigger_window",
                phase="before_attack",
                canonical_window="before_attack",
                tbgd_event="OnBeforeAttack",
                coverage_status="lowered",
                source=definition.source,
            )
        )
    if has_damage and not blocked_reason:
        steps.append(
            ActionPhaseStepIR(
                kind="damage",
                phase="damage",
                coverage_status="lowered",
                source=definition.source,
            )
        )
    if has_attack_windows and not blocked_reason:
        steps.append(
            ActionPhaseStepIR(
                kind="trigger_window",
                phase="after_attack",
                canonical_window="after_attack",
                tbgd_event="OnAfterAttack",
                coverage_status="lowered",
                source=definition.source,
            )
        )
    steps.append(
        ActionPhaseStepIR(
            kind="trigger_window",
            phase="after_skill_use",
            canonical_window="after_skill_use",
            tbgd_event="OnAfterSkillUse",
            coverage_status=status,
            blocked_reason=blocked_reason,
            source=definition.source,
        )
    )
    return ActionEventIR(
        action_event_id=f"action_event:{definition.action_id}:{definition.level}",
        action_id=definition.action_id,
        level=definition.level,
        target_mode=definition.target_mode,
        selection_mode=_selection_mode(definition.target_mode),
        phase_steps=tuple(steps),
        hit_profile_ids=tuple(profile.hit_profile_id for profile in hit_profiles),
        derived_status="derived_from_action_definition",
        derived_reason=(
            "phase steps are derived from SkillEffect/AttackType/damage_kind until TBGD action event schema is fully mapped"
        ),
        source=definition.source,
        coverage_status=status,
        blocked_reason=blocked_reason,
    )


def _hit_profiles_from_definition(definition: ActionDefinitionIR) -> list[HitProfileIR]:
    if definition.damage_kind != "hp_damage":
        return []
    groups = _hit_target_groups(definition.target_mode)
    if not groups:
        groups = (definition.target_mode or "unknown",)
    profiles: list[HitProfileIR] = []
    for hit_index, target_group in enumerate(groups):
        blocked_reason = _hit_profile_blocked_reason(definition, target_group)
        profiles.append(
            HitProfileIR(
                hit_profile_id=f"hit_profile:{definition.action_id}:{definition.level}:{hit_index}:{target_group}",
                action_id=definition.action_id,
                level=definition.level,
                hit_index=hit_index,
                target_group=target_group,
                multiplier_expr=_param_multiplier_expr(definition.param_list),
                multiplier_source=_param_multiplier_source(definition),
                stance_expr=_stance_expr(definition.show_stance_list),
                stance_source=_stance_source(definition),
                damage_formula_family=definition.damage_formula_family,
                element_type=definition.element_type,
                source=definition.source,
                coverage_status="blocked" if blocked_reason else "executable",
                blocked_reason=blocked_reason,
                numeric_fidelity_status=_numeric_fidelity_status(definition, target_group),
            )
        )
    return profiles


def _hit_target_groups(target_mode: str) -> tuple[str, ...]:
    if target_mode == "blast":
        return ("primary", "adjacent")
    if target_mode in {"single", "aoe"}:
        return ("selected",)
    if target_mode in {"bounce", "unknown"}:
        return (target_mode,)
    return ()


def _hit_profile_blocked_reason(definition: ActionDefinitionIR, target_group: str) -> str:
    target_reason = _target_blocked_reason(definition.target_mode)
    if target_reason:
        return target_reason
    if definition.damage_formula_family not in {"direct", "true_damage", "hp_loss", "elation"}:
        return f"damage_formula_family_not_executable:{definition.damage_formula_family}"
    if not _param_multiplier_is_fixed(definition.param_list):
        return "param_list_multiplier_not_fixed"
    if target_group in {"adjacent", "selected"} and definition.target_mode in {"aoe", "blast"}:
        return ""
    return ""


def _param_multiplier_expr(param_list: tuple[Any, ...]) -> dict[str, Any]:
    if not param_list:
        return {"kind": "missing", "blocked_reason": "missing_param_list"}
    first = param_list[0]
    value = _number_value(first, 0.0)
    if _param_multiplier_is_fixed(param_list):
        return {"kind": "fixed", "value": value}
    return {"kind": "unsupported", "raw": _json_safe(first), "blocked_reason": "param_list_multiplier_not_fixed"}


def _param_multiplier_source(definition: ActionDefinitionIR) -> dict[str, Any]:
    first = definition.param_list[0] if definition.param_list else None
    return {
        "raw_path": "ParamList[0]",
        "raw_value": _json_safe(first),
        "param_list_count": len(definition.param_list),
        "multi_param_list_not_implemented": len(definition.param_list) > 1,
        "show_damage_count": len(definition.show_damage_list),
        "show_damage_audit_only": bool(definition.show_damage_list),
        "source": definition.source.to_json(),
    }


def _stance_expr(show_stance_list: tuple[Any, ...]) -> dict[str, Any]:
    if not show_stance_list:
        return {"kind": "missing", "blocked_reason": "show_stance_not_present"}
    first = show_stance_list[0]
    return {
        "kind": "audit_only",
        "raw": _json_safe(first),
        "blocked_reason": "show_stance_semantics_not_confirmed",
    }


def _stance_source(definition: ActionDefinitionIR) -> dict[str, Any]:
    first = definition.show_stance_list[0] if definition.show_stance_list else None
    return {
        "raw_path": "ShowStanceList[0]",
        "raw_value": _json_safe(first),
        "show_stance_count": len(definition.show_stance_list),
        "show_stance_audit_only": bool(definition.show_stance_list),
        "stance_damage_type": definition.stance_damage_type,
        "source": definition.source.to_json(),
    }


def _param_multiplier_is_fixed(param_list: tuple[Any, ...]) -> bool:
    if not param_list:
        return False
    first = param_list[0]
    if isinstance(first, dict):
        return isinstance(first.get("Value"), (int, float))
    return isinstance(first, (int, float))


def _numeric_fidelity_status(definition: ActionDefinitionIR, target_group: str) -> str:
    if definition.target_mode in {"aoe", "blast"}:
        return "structural_only"
    if len(definition.param_list) > 1 or definition.show_damage_list or definition.show_stance_list:
        return "structural_only"
    if target_group in {"bounce", "unknown"}:
        return "blocked"
    return "single_hit_ratio"


def _target_blocked_reason(target_mode: str) -> str:
    if target_mode == "bounce":
        return "bounce_not_executable"
    if target_mode == "unknown":
        return "unknown_target_mode_not_executable"
    if target_mode not in {"single", "aoe", "blast", "self_or_team"}:
        return f"unsupported_target_mode:{target_mode}"
    return ""


def _selection_mode(target_mode: str) -> str:
    if target_mode == "single":
        return "primary"
    if target_mode == "aoe":
        return "all_enemies"
    if target_mode == "blast":
        return "primary_plus_adjacent"
    if target_mode == "bounce":
        return "blocked_random_bounce"
    if target_mode == "self_or_team":
        return "explicit_ally_or_self"
    return "unknown"


def _action_definition_is_attack(definition: ActionDefinitionIR) -> bool:
    skill_effect = definition.skill_effect.lower()
    attack_type = definition.attack_type.lower()
    if definition.target_mode in {"single", "blast", "aoe", "bounce"}:
        return True
    return "attack" in skill_effect or "attack" in attack_type


def _target_mode(skill_effect: str) -> str:
    normalized = skill_effect.lower()
    if normalized in {"singleattack", "mazeattack"}:
        return "single"
    if normalized == "blast":
        return "blast"
    if normalized in {"aoeattack", "aoe"}:
        return "aoe"
    if normalized == "bounce":
        return "bounce"
    if normalized == "enhance":
        return "self_or_team"
    return "unknown"


def _damage_kind(skill_effect: str) -> str:
    return "hp_damage" if _target_mode(skill_effect) in {"single", "blast", "aoe", "bounce"} else "non_damage"


def _damage_formula_family(attack_type: str, skill_effect: str) -> str:
    normalized_attack = attack_type.lower()
    normalized_effect = skill_effect.lower()
    if normalized_attack == "elationdamage" or normalized_effect == "byelationdamage":
        return "elation"
    if normalized_attack == "truedamage":
        return "true_damage"
    if normalized_attack == "dot" or normalized_effect == "dot":
        return "dot"
    if normalized_attack == "elementdamage":
        return "direct"
    if _target_mode(skill_effect) in {"single", "blast", "aoe", "bounce"}:
        return "direct"
    return "none"


def _source_mode(attack_type: str) -> str:
    return "maze" if attack_type.lower().startswith("maze") else "mainline"


def _limit_sequence(items: list[Any], limit: int | None) -> list[Any]:
    if limit is None:
        return items
    return items[:limit]


def _number_value(value: Any, default: float) -> float:
    if isinstance(value, dict):
        nested = value.get("Value")
        return _number_value(nested, default)
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _list_json_values(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    return [_json_safe(item) for item in value]


def _compact_payload(value: dict[str, Any]) -> dict[str, Any]:
    ignored = {"SuccessTaskList", "FailedTaskList", "CallbackConfig"}
    return {key: _json_safe(item) for key, item in value.items() if key not in ignored and key != "$type"}


REMOVE_MODIFIER_OPCODES = {"RemoveModifier", "RemoveSelfModifier"}
HEAL_OPCODES = {"HealHP"}
SHIELD_OPCODES = {"InitShield", "StackShield", "ModifyShield"}
MECHANISM_BAR_OPCODES = {"SetEnergyBarState", "SetMonsterEnergyBarState", "SetSummonerEnergyBarState"}
RESOURCE_DELTA_OPCODES = {"ModifySPNew"}
DYNAMIC_VALUE_OPCODES = {"SetDynamicValue", "SetDynamicValueByModifierValue"}
EXECUTABLE_TARGET_ALIASES = {"Caster", "ModifierOwnerEntity", "ParamEntity", "CurrentActionTarget"}
SUPPORTED_MODIFIER_VALUE_TYPES = {"Layer", "LifeTime"}
EXECUTABLE_CONDITION_OPCODES = {
    "AlwaysTrue",
    "ByAnd",
    "ByAny",
    "ByAttackType",
    "ByCompareDynamicValue",
    "ByCompareHPRatio",
    "ByCompareModifierValue",
    "ByCompareTarget",
    "ByCurrentSkillType",
    "ByIsContainModifier",
    "ByNot",
    "ByTargetTeam",
}


def _effect_payload(value: dict[str, Any], opcode: str, source_modifier_name: str) -> dict[str, Any]:
    payload = _compact_payload(value)
    if opcode == "AddModifier":
        payload["standard"] = _standard_add_modifier_payload(value)
    elif opcode in REMOVE_MODIFIER_OPCODES:
        payload["standard"] = _standard_remove_modifier_payload(value, opcode, source_modifier_name)
    elif opcode in HEAL_OPCODES:
        payload["standard"] = _standard_heal_payload(value)
    elif opcode in SHIELD_OPCODES:
        payload["standard"] = _standard_shield_payload(value, opcode)
    elif opcode in MECHANISM_BAR_OPCODES:
        payload["standard"] = _standard_mechanism_bar_payload(value, opcode)
    elif opcode in RESOURCE_DELTA_OPCODES:
        payload["standard"] = _standard_resource_delta_payload(value, opcode)
    elif opcode == "SetDynamicValue":
        payload["standard"] = _standard_set_dynamic_value_payload(value)
    elif opcode == "SetDynamicValueByModifierValue":
        payload["standard"] = _standard_set_dynamic_value_by_modifier_value_payload(value, source_modifier_name)
    family = _task_damage_family(value, opcode)
    if family != "unknown":
        payload["damage_formula_family"] = family
        payload["bypasses_normal_multipliers"] = family in {"true_damage", "hp_loss"}
    return payload


def _effect_coverage_status(opcode: str, payload: dict[str, Any]) -> str:
    if opcode == "AddModifier":
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        if not standard.get("modifier_name"):
            return "blocked"
        if standard.get("target_alias") in EXECUTABLE_TARGET_ALIASES:
            return "executable"
        return "blocked"
    if opcode in REMOVE_MODIFIER_OPCODES:
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        has_modifier = isinstance(standard.get("modifier_name"), str) and bool(standard.get("modifier_name"))
        has_status = isinstance(standard.get("status_id"), str) and bool(standard.get("status_id"))
        if (has_modifier or has_status) and standard.get("target_alias") in EXECUTABLE_TARGET_ALIASES:
            return "executable"
        return "blocked"
    if opcode in HEAL_OPCODES | SHIELD_OPCODES:
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        if standard.get("target_alias") not in EXECUTABLE_TARGET_ALIASES:
            return "blocked"
        if not _numeric_expr_can_be_runtime_bound(standard.get("amount")):
            return "blocked"
        return "executable"
    if opcode in MECHANISM_BAR_OPCODES:
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        if _mechanism_bar_has_runtime_payload(standard):
            return "executable"
        return "blocked"
    if opcode in RESOURCE_DELTA_OPCODES:
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        if standard.get("target_alias") not in EXECUTABLE_TARGET_ALIASES:
            return "blocked"
        if not isinstance(standard.get("resource"), str):
            return "blocked"
        if not _numeric_expr_can_be_runtime_bound(standard.get("amount")):
            return "blocked"
        return "executable"
    if opcode == "SetDynamicValue":
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        if standard.get("target_alias") not in EXECUTABLE_TARGET_ALIASES:
            return "blocked"
        if not isinstance(standard.get("value_name"), str) or not standard.get("value_name"):
            return "blocked"
        if not _numeric_expr_can_be_runtime_bound(standard.get("value_expr")):
            return "blocked"
        return "executable"
    if opcode == "SetDynamicValueByModifierValue":
        standard = payload.get("standard")
        if not isinstance(standard, dict):
            return "blocked"
        if standard.get("target_alias") not in EXECUTABLE_TARGET_ALIASES:
            return "blocked"
        if standard.get("source_target_alias") not in EXECUTABLE_TARGET_ALIASES:
            return "blocked"
        if not isinstance(standard.get("source_modifier"), str) or not standard.get("source_modifier"):
            return "blocked"
        if not isinstance(standard.get("target_value_name"), str) or not standard.get("target_value_name"):
            return "blocked"
        if standard.get("source_value_name") not in SUPPORTED_MODIFIER_VALUE_TYPES:
            return "blocked"
        if not _numeric_expr_can_be_runtime_bound(standard.get("multiplier")):
            return "blocked"
        return "executable"
    return classify_opcode(opcode)


def _condition_payload_executable(opcode: str, payload: dict[str, Any]) -> bool:
    if opcode not in EXECUTABLE_CONDITION_OPCODES:
        return False
    if opcode == "AlwaysTrue":
        return True
    if opcode == "ByCurrentSkillType":
        return isinstance(payload.get("SkillType"), str)
    if opcode == "ByAttackType":
        return isinstance(payload.get("AttackTypes"), list)
    if opcode == "ByTargetTeam":
        return _target_alias(payload.get("TargetType")) in EXECUTABLE_TARGET_ALIASES and payload.get("Team") in {"TeamLight", "TeamDark"}
    if opcode == "ByIsContainModifier":
        return _target_alias(payload.get("TargetType")) in EXECUTABLE_TARGET_ALIASES and isinstance(_value_field(payload.get("ModifierName")), str)
    if opcode == "ByCompareHPRatio":
        return (
            _target_alias(payload.get("TargetType")) in EXECUTABLE_TARGET_ALIASES
            and _numeric_expr_can_be_runtime_bound(_numeric_expr_summary(payload.get("CompareValue")))
        )
    if opcode == "ByCompareDynamicValue":
        return (
            _target_alias(payload.get("TargetType")) in EXECUTABLE_TARGET_ALIASES
            and isinstance(_value_field(payload.get("DynamicKey")), str)
            and _numeric_expr_can_be_runtime_bound(_numeric_expr_summary(payload.get("CompareValue")))
        )
    if opcode == "ByCompareModifierValue":
        return (
            _target_alias(payload.get("TargetType")) in EXECUTABLE_TARGET_ALIASES
            and payload.get("ValueType") in SUPPORTED_MODIFIER_VALUE_TYPES
            and _numeric_expr_can_be_runtime_bound(_numeric_expr_summary(payload.get("CompareValue")))
        )
    if opcode == "ByCompareTarget":
        return _target_alias(payload.get("TargetType")) in EXECUTABLE_TARGET_ALIASES and _target_alias(payload.get("CompareType")) in EXECUTABLE_TARGET_ALIASES
    if opcode in {"ByAnd", "ByAny"}:
        predicates = payload.get("PredicateList")
        return isinstance(predicates, list) and all(_raw_condition_payload_executable(item) for item in predicates)
    if opcode == "ByNot":
        return _raw_condition_payload_executable(payload.get("Predicate"))
    return False


def _raw_condition_payload_executable(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    opcode = _short_gamecore_type(value.get("$type"))
    payload = _compact_payload(value)
    return _condition_payload_executable(opcode, payload)


def _standard_add_modifier_payload(value: dict[str, Any]) -> dict[str, Any]:
    dynamic_values = {
        str(key): _numeric_expr_summary(item)
        for key, item in (value.get("DynamicValues") or {}).items()
        if isinstance(value.get("DynamicValues"), dict)
    }
    return {
        "modifier_name": _value_field(value.get("ModifierName")),
        "target_alias": _target_alias(value.get("TargetType")),
        "dynamic_values": dynamic_values,
        "dynamic_value_requests": _dynamic_value_requests(dynamic_values),
        "lifetime": _numeric_expr_summary(value.get("LifeTime")),
        "layer_add_when_stack": _numeric_expr_summary(value.get("LayerAddWhenStack")),
        "max_layer": _numeric_expr_summary(value.get("MaxLayer")),
        "chance": _numeric_expr_summary(value.get("Chance")),
    }


def _standard_remove_modifier_payload(value: dict[str, Any], opcode: str, source_modifier_name: str) -> dict[str, Any]:
    if opcode == "RemoveSelfModifier":
        modifier_name = source_modifier_name
        target_alias = "ModifierOwnerEntity"
    else:
        modifier_name = _value_field(value.get("ModifierName"))
        target_alias = _target_alias(value.get("TargetType"))
    status_id = f"modifier:{modifier_name}" if isinstance(modifier_name, str) and modifier_name else None
    return {
        "kind": "status_remove",
        "target_alias": target_alias,
        "modifier_name": modifier_name,
        "status_id": status_id,
    }


def _standard_heal_payload(value: dict[str, Any]) -> dict[str, Any]:
    amount = _numeric_expr_summary(value.get("ModifyValue"))
    percentage = _numeric_expr_summary(value.get("HealPercentage"))
    payload = {
        "kind": "heal",
        "target_alias": _target_alias(value.get("TargetType")),
        "formula_type": _value_field(value.get("FormulaType")),
        "amount": amount,
        "percentage": percentage,
        "raw_formula_fields": {
            "ModifyValue": _json_safe(value.get("ModifyValue")),
            "HealPercentage": _json_safe(value.get("HealPercentage")),
            "FormulaType": _json_safe(value.get("FormulaType")),
        },
    }
    if not _numeric_expr_can_be_runtime_bound(amount):
        payload["blocked_reason"] = "fixed_or_bound_modify_value_required"
    return payload


def _standard_shield_payload(value: dict[str, Any], opcode: str) -> dict[str, Any]:
    amount = _numeric_expr_summary(value.get("ShieldValue"))
    percentage = _numeric_expr_summary(value.get("ShieldPercentage"))
    payload = {
        "kind": "shield",
        "shield_opcode": opcode,
        "target_alias": _target_alias(value.get("TargetType")),
        "formula_type": _value_field(value.get("FormulaType")),
        "amount": amount,
        "percentage": percentage,
        "raw_formula_fields": {
            "ShieldValue": _json_safe(value.get("ShieldValue")),
            "ShieldPercentage": _json_safe(value.get("ShieldPercentage")),
            "FormulaType": _json_safe(value.get("FormulaType")),
        },
    }
    if not _numeric_expr_can_be_runtime_bound(amount):
        payload["blocked_reason"] = "fixed_or_bound_shield_value_required"
    return payload


def _standard_mechanism_bar_payload(value: dict[str, Any], opcode: str) -> dict[str, Any]:
    current_count = _numeric_expr_summary(value.get("CurrentCount"))
    max_count = _numeric_expr_summary(value.get("MaxCount"))
    payload = {
        "kind": "mechanism_bar_state",
        "opcode": opcode,
        "target_alias": _target_alias(value.get("TargetType")),
        "bar_type": _value_field(value.get("BarType")),
        "active": _value_field(value.get("Active")),
        "state": _value_field(value.get("CurrentState", value.get("State"))),
        "current_count": current_count,
        "max_count": max_count,
        "raw_formula_fields": {
            "Active": _json_safe(value.get("Active")),
            "BarType": _json_safe(value.get("BarType")),
            "CurrentState": _json_safe(value.get("CurrentState")),
            "State": _json_safe(value.get("State")),
            "CurrentCount": _json_safe(value.get("CurrentCount")),
            "MaxCount": _json_safe(value.get("MaxCount")),
        },
    }
    if not _mechanism_bar_has_runtime_payload(payload):
        payload["blocked_reason"] = "fixed_or_bound_mechanism_bar_state_or_count_required"
    return payload


def _standard_resource_delta_payload(value: dict[str, Any], opcode: str) -> dict[str, Any]:
    amount = _numeric_expr_summary(value.get("AddValue", value.get("ModifyValue")))
    payload = {
        "kind": "resource_delta",
        "resource": "skill_points" if opcode == "ModifySPNew" else opcode,
        "target_alias": _target_alias(value.get("TargetType")),
        "amount": amount,
        "raw_formula_fields": {
            "AddValue": _json_safe(value.get("AddValue")),
            "ModifyValue": _json_safe(value.get("ModifyValue")),
        },
    }
    if not _numeric_expr_can_be_runtime_bound(amount):
        payload["blocked_reason"] = "fixed_or_bound_resource_delta_required"
    return payload


def _standard_set_dynamic_value_payload(value: dict[str, Any]) -> dict[str, Any]:
    value_expr = _numeric_expr_summary(value.get("Value"))
    value_name = _value_field(value.get("DynamicKey"))
    target_alias = _target_alias(value.get("TargetType")) or "ModifierOwnerEntity"
    payload = {
        "kind": "dynamic_value_store",
        "opcode": "SetDynamicValue",
        "target_alias": target_alias,
        "status_scope": _value_field(value.get("ContextScope")) or "modifier_local",
        "value_name": value_name,
        "hash": None,
        "value_expr": value_expr,
        "raw_formula_fields": {
            "DynamicKey": _json_safe(value.get("DynamicKey")),
            "Value": _json_safe(value.get("Value")),
            "TargetType": _json_safe(value.get("TargetType")),
            "ContextScope": _json_safe(value.get("ContextScope")),
        },
    }
    if not isinstance(value_name, str) or not value_name:
        payload["blocked_reason"] = "dynamic_value_name_required"
    elif target_alias not in EXECUTABLE_TARGET_ALIASES:
        payload["blocked_reason"] = f"unsupported_target_alias:{target_alias}"
    elif not _numeric_expr_can_be_runtime_bound(value_expr):
        payload["blocked_reason"] = str(value_expr.get("reason") or "fixed_or_bound_dynamic_value_required")
    return payload


def _standard_set_dynamic_value_by_modifier_value_payload(
    value: dict[str, Any],
    source_modifier_name: str,
) -> dict[str, Any]:
    source_modifier = _value_field(value.get("ModifierName")) or source_modifier_name
    source_value_name = _value_field(value.get("ValueType"))
    target_value_name = _value_field(value.get("DynamicKey"))
    multiplier = _numeric_expr_summary(value.get("Multiplier"))
    source_target_alias = _target_alias(value.get("ReadTargetType")) or "ModifierOwnerEntity"
    target_alias = _target_alias(value.get("TargetType")) or "ModifierOwnerEntity"
    payload = {
        "kind": "dynamic_value_store",
        "opcode": "SetDynamicValueByModifierValue",
        "source_modifier": source_modifier,
        "source_value_name": source_value_name,
        "source_hash": None,
        "target_value_name": target_value_name,
        "target_hash": None,
        "target_alias": target_alias,
        "source_target_alias": source_target_alias,
        "multiplier": multiplier,
        "raw_formula_fields": {
            "ModifierName": _json_safe(value.get("ModifierName")),
            "ValueType": _json_safe(value.get("ValueType")),
            "Multiplier": _json_safe(value.get("Multiplier")),
            "DynamicKey": _json_safe(value.get("DynamicKey")),
            "ReadTargetType": _json_safe(value.get("ReadTargetType")),
            "TargetType": _json_safe(value.get("TargetType")),
            "ContextScope": _json_safe(value.get("ContextScope")),
        },
    }
    if not isinstance(source_modifier, str) or not source_modifier:
        payload["blocked_reason"] = "source_modifier_required"
    elif source_target_alias not in EXECUTABLE_TARGET_ALIASES:
        payload["blocked_reason"] = f"unsupported_source_target_alias:{source_target_alias}"
    elif target_alias not in EXECUTABLE_TARGET_ALIASES:
        payload["blocked_reason"] = f"unsupported_target_alias:{target_alias}"
    elif source_value_name not in SUPPORTED_MODIFIER_VALUE_TYPES:
        payload["blocked_reason"] = f"unsupported_modifier_value_type:{source_value_name}"
    elif not isinstance(target_value_name, str) or not target_value_name:
        payload["blocked_reason"] = "target_value_name_required"
    elif not _numeric_expr_can_be_runtime_bound(multiplier):
        payload["blocked_reason"] = str(multiplier.get("reason") or "fixed_or_bound_multiplier_required")
    return payload


def _dynamic_value_bindings(value: Any) -> dict[str, Any]:
    floats = value.get("Floats") if isinstance(value, dict) else None
    if not isinstance(floats, dict):
        return {"by_hash": {}, "raw": _json_safe(value)}
    by_hash: dict[str, Any] = {}
    for key, item in floats.items():
        by_hash[str(key)] = {
            "hash": str(key),
            "value_type": "float",
            "read_info": _json_safe(item.get("ReadInfo")) if isinstance(item, dict) else None,
            "raw": _json_safe(item),
            "raw_path": f"DynamicValues.Floats[{key}]",
        }
    return {"by_hash": by_hash, "raw": _json_safe(value)}


def _dynamic_value_requests(dynamic_values: dict[str, Any]) -> dict[str, Any]:
    requests: dict[str, Any] = {}
    for key, expr in dynamic_values.items():
        request: dict[str, Any] = {"name": key, "expr": _json_safe(expr)}
        if isinstance(expr, dict) and expr.get("kind") == "dynamic_hash":
            request["hash"] = expr.get("hash")
        requests[key] = request
    return requests


def _target_alias(value: Any) -> str | None:
    if isinstance(value, dict):
        alias = value.get("Alias")
        if isinstance(alias, str):
            return alias
    return None


def _value_field(value: Any) -> Any:
    if isinstance(value, dict) and "Value" in value:
        return _json_safe(value.get("Value"))
    return _json_safe(value)


def _numeric_expr_summary(value: Any) -> dict[str, Any]:
    if value is None:
        return {"kind": "missing", "value": None, "supported": False, "reason": "missing"}
    if isinstance(value, (int, float)):
        return {"kind": "fixed", "value": float(value), "supported": True}
    if isinstance(value, dict):
        fixed = value.get("FixedValue")
        if isinstance(fixed, dict) and isinstance(fixed.get("Value"), (int, float)):
            return {"kind": "fixed", "value": float(fixed["Value"]), "supported": True}
        if isinstance(value.get("Value"), (int, float)):
            return {"kind": "fixed", "value": float(value["Value"]), "supported": True}
        postfix = value.get("PostfixExpr")
        if isinstance(postfix, dict):
            hashes = postfix.get("DynamicHashes")
            fixed_values = postfix.get("FixedValues")
            opcodes = postfix.get("OpCodes")
            if (
                opcodes == "AQAR"
                and isinstance(hashes, list)
                and len(hashes) == 1
                and isinstance(hashes[0], int)
                and (not fixed_values)
            ):
                return {
                    "kind": "dynamic_hash",
                    "hash": int(hashes[0]),
                    "supported": True,
                    "raw": _json_safe(value),
                }
            return {
                "kind": "postfix_expr",
                "supported": False,
                "reason": "unsupported_postfix_expr",
                "raw": _json_safe(value),
            }
    return {"kind": "unsupported", "supported": False, "reason": "unsupported_numeric_expression", "raw": _json_safe(value)}


def _fixed_expr_value(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict) and value.get("kind") == "fixed" and isinstance(value.get("value"), (int, float)):
        return float(value["value"])
    return None


def _numeric_expr_can_be_runtime_bound(value: Any) -> bool:
    if _fixed_expr_value(value) is not None:
        return True
    if isinstance(value, dict) and value.get("kind") == "dynamic_hash" and value.get("hash") is not None:
        return True
    return False


def _mechanism_bar_has_fixed_payload(standard: dict[str, Any]) -> bool:
    if standard.get("state") is not None or standard.get("active") is not None:
        return True
    return _fixed_expr_value(standard.get("current_count")) is not None or _fixed_expr_value(standard.get("max_count")) is not None


def _mechanism_bar_has_runtime_payload(standard: dict[str, Any]) -> bool:
    if standard.get("state") is not None or standard.get("active") is not None:
        return True
    return _numeric_expr_can_be_runtime_bound(standard.get("current_count")) or _numeric_expr_can_be_runtime_bound(standard.get("max_count"))


def _task_damage_family(value: dict[str, Any], opcode: str) -> str:
    attack_type = str(value.get("AttackType") or "")
    formula_type = str(value.get("FormulaType") or "")
    if attack_type == "ElationDamage" or formula_type == "ByElationDamage":
        return "elation"
    if attack_type == "TrueDamage":
        return "true_damage"
    if opcode in {"LoseHPByRatio", "DirectlyLoseHp", "DirectlyLoseHpHit"}:
        return "hp_loss"
    return "unknown"


def _damage_behavior_family(template_name: str) -> str:
    if template_name == "TrueDamage":
        return "true_damage"
    if template_name in {"DirectlyLoseHp", "DirectlyLoseHpHit"}:
        return "hp_loss"
    return "unknown"


def _damage_family_evidence(
    task: dict[str, Any],
    opcode: str,
    source: IRSource,
    parent_id: str,
) -> list[FormulaIR]:
    family = _task_damage_family(task, opcode)
    if family == "unknown":
        return []
    property_name = {
        "elation": "ElationDamage",
        "true_damage": "TrueDamage",
        "hp_loss": opcode,
    }[family]
    return [
        FormulaIR(
            formula_id=f"formula:{parent_id}:damage_family:{family}",
            kind="mechanic_property",
            expression={
                "mechanic": f"{family}_damage",
                "property": property_name,
                "damage_formula_family": family,
                "source_mode": "mainline",
                "bypasses_normal_multipliers": family in {"true_damage", "hp_loss"},
                "runtime_status": "executable" if family in {"true_damage", "hp_loss"} else "blocked",
                "blocked_reason": "Elation damage formula is not executable in v0_208"
                if family == "elation"
                else "",
            },
            source=source,
            coverage_status="blocked" if family == "elation" else "lowered",
        )
    ]


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _iter_postfix_expr(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        expr = value.get("PostfixExpr")
        if isinstance(expr, dict):
            found.append(expr)
        for nested in value.values():
            found.extend(_iter_postfix_expr(nested))
    elif isinstance(value, list):
        for nested in value:
            found.extend(_iter_postfix_expr(nested))
    return found


def _iter_fixed_values(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        fixed = value.get("FixedValue")
        if isinstance(fixed, dict) and "Value" in fixed:
            found.append(fixed)
        for nested in value.values():
            found.extend(_iter_fixed_values(nested))
    elif isinstance(value, list):
        for nested in value:
            found.extend(_iter_fixed_values(nested))
    return found


def _iter_elation_values(value: Any, path: tuple[str, ...] = ()) -> list[tuple[str, str, Any]]:
    found: list[tuple[str, str, Any]] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            child_path = (*path, str(key))
            if _is_elation_key(str(key)):
                found.append((".".join(child_path), str(key), nested))
            found.extend(_iter_elation_values(nested, child_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found.extend(_iter_elation_values(nested, (*path, str(index))))
    return found


def _is_elation_key(key: str) -> bool:
    return key.startswith("Elation") or "ElationTime" in key
