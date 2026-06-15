from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .coverage import classify_opcode
from .paths import relative_source_path
from .. import BASELINE_VERSION
from ..rules.ir import CanonicalIR, ConditionIR, EffectIR, FormulaIR, IRSource, RuleEntity, TriggerIR


ENTITY_TABLES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "ExcelOutput/AvatarConfigLD.json": ("avatar", "AvatarID", ("DamageType", "SPNeed", "SkillList", "AvatarBaseType", "Rarity")),
    "ExcelOutput/CommonAvatarSkillConfig.json": (
        "avatar_skill",
        "SkillID",
        ("SkillTriggerKey", "SkillEffect", "BPNeed", "BPAdd", "SPMultipleRatio", "ParamList"),
    ),
    "ExcelOutput/CommonActiveSkillConfig.json": (
        "active_skill",
        "SkillID",
        ("SkillTriggerKey", "SkillEffect", "BPNeed", "BPAdd", "ParamList"),
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


@dataclass(frozen=True)
class LoweringLimits:
    max_records_per_table: int = 500
    max_ability_files: int = 120
    max_callbacks_per_file: int = 200


class TBGDLowering:
    """Converts TBGD raw files into v8 Canonical IR."""

    def __init__(self, tbgd_root: Path, limits: LoweringLimits | None = None):
        self.tbgd_root = tbgd_root.resolve()
        self.limits = limits or LoweringLimits()

    def build(self) -> CanonicalIR:
        entities: list[RuleEntity] = []
        triggers: list[TriggerIR] = []
        effects: list[EffectIR] = []
        conditions: list[ConditionIR] = []
        formulas: list[FormulaIR] = []

        for relative_path, spec in ENTITY_TABLES.items():
            entities.extend(self._lower_entity_table(relative_path, spec))

        ability_files = self._ability_files()
        for path in ability_files[: self.limits.max_ability_files]:
            lowered = self._lower_ability_file(path)
            triggers.extend(lowered.triggers)
            effects.extend(lowered.effects)
            conditions.extend(lowered.conditions)
            formulas.extend(lowered.formulas)

        return CanonicalIR(
            version=BASELINE_VERSION,
            entities=tuple(entities),
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
        for index, row in enumerate(data[: self.limits.max_records_per_table]):
            if not isinstance(row, dict) or id_key not in row:
                continue
            raw_id = str(row[id_key])
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
        lowered.effects.append(
            EffectIR(
                effect_id=effect_id,
                opcode=opcode,
                payload=_compact_payload(task),
                source=source,
                coverage_status=classify_opcode(opcode),
            )
        )
        lowered.formulas.extend(self._extract_formulas(task, source, effect_id))
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


def _compact_payload(value: dict[str, Any]) -> dict[str, Any]:
    ignored = {"SuccessTaskList", "FailedTaskList", "CallbackConfig"}
    return {key: _json_safe(item) for key, item in value.items() if key not in ignored and key != "$type"}


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

