from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .coverage import classify_opcode
from .paths import relative_source_path
from .. import BASELINE_VERSION
from ..rules.ir import (
    ActionDefinitionIR,
    CanonicalIR,
    ConditionIR,
    EffectIR,
    FormulaIR,
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
        for relative_path, _, id_key in ACTION_DEFINITION_TABLES:
            table_stats[f"action_definitions:{relative_path}"] = self._table_stats(relative_path, id_key)

        ability_files = self._ability_files()
        selected_ability_files = _limit_sequence(ability_files, self.limits.max_ability_files)
        for path in selected_ability_files:
            lowered = self._lower_ability_file(path)
            triggers.extend(lowered.triggers)
            effects.extend(lowered.effects)
            conditions.extend(lowered.conditions)
            formulas.extend(lowered.formulas)
        formulas.extend(self._lower_elation_mechanics())
        formulas.extend(self._lower_damage_behavior_templates())

        return CanonicalIR(
            version=BASELINE_VERSION,
            entities=tuple(entities),
            action_definitions=tuple(action_definitions),
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
        payload = _effect_payload(task, opcode)
        lowered.effects.append(
            EffectIR(
                effect_id=effect_id,
                opcode=opcode,
                payload=payload,
                source=source,
                coverage_status=classify_opcode(opcode),
            )
        )
        lowered.formulas.extend(self._extract_formulas(task, source, effect_id))
        lowered.formulas.extend(_damage_family_evidence(task, opcode, source, effect_id))
        return lowered

    def _lower_condition(self, predicate: Any, source: IRSource, task_index: int) -> ConditionIR | None:
        if not isinstance(predicate, dict):
            return None
        opcode = _short_gamecore_type(predicate.get("$type"))
        status = "executable" if opcode == "ByCurrentSkillType" else classify_opcode(opcode)
        return ConditionIR(
            condition_id=f"condition:{source.source_path}:{source.raw_id}:{source.evidence.get('callback_index')}:{task_index}:{opcode}",
            opcode=opcode,
            payload=_compact_payload(predicate),
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
        return maps


@dataclass
class _LoweredAbility:
    triggers: list[TriggerIR] = None
    effects: list[EffectIR] = None
    conditions: list[ConditionIR] = None
    formulas: list[FormulaIR] = None

    def __post_init__(self) -> None:
        if self.triggers is None:
            self.triggers = []
        if self.effects is None:
            self.effects = []
        if self.conditions is None:
            self.conditions = []
        if self.formulas is None:
            self.formulas = []

    def merge(self, other: "_LoweredAbility") -> None:
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


def _effect_payload(value: dict[str, Any], opcode: str) -> dict[str, Any]:
    payload = _compact_payload(value)
    family = _task_damage_family(value, opcode)
    if family != "unknown":
        payload["damage_formula_family"] = family
        payload["bypasses_normal_multipliers"] = family in {"true_damage", "hp_loss"}
    return payload


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
