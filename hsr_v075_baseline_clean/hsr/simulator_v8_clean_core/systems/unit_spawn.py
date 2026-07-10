from __future__ import annotations

from dataclasses import dataclass, field

from ..core.model import JSONValue, UnitState
from ..rules.ir import UnitBirthTemplateIR


@dataclass(frozen=True)
class UnitSpawnRequest:
    spawn_kind: str
    unit_id: str
    birth_template_id: str
    entity_ref: str
    source_id: str
    entry_id: str
    owner_id: str = ""
    summoner_id: str = ""
    entry_index: int | None = None
    copy_index: int | None = None
    spawn_index: int | None = None
    wave_definition_id: str = ""
    stage_id: str = ""
    wave_index: int | None = None
    position: int | None = None
    source_trace: dict[str, JSONValue] = field(default_factory=dict)
    entry_source_trace: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "spawn_kind": self.spawn_kind,
            "unit_id": self.unit_id,
            "birth_template_id": self.birth_template_id,
            "entity_ref": self.entity_ref,
            "source_id": self.source_id,
            "entry_id": self.entry_id,
            "owner_id": self.owner_id,
            "summoner_id": self.summoner_id,
            "entry_index": self.entry_index,
            "copy_index": self.copy_index,
            "spawn_index": self.spawn_index,
            "wave_definition_id": self.wave_definition_id,
            "stage_id": self.stage_id,
            "wave_index": self.wave_index,
            "position": self.position,
            "source_trace": self.source_trace,
            "entry_source_trace": self.entry_source_trace,
        }

    @classmethod
    def from_json(cls, value: JSONValue) -> "UnitSpawnRequest":
        raw = value if isinstance(value, dict) else {}
        return cls(
            spawn_kind=str(raw.get("spawn_kind") or ""),
            unit_id=str(raw.get("unit_id") or ""),
            birth_template_id=str(raw.get("birth_template_id") or ""),
            entity_ref=str(raw.get("entity_ref") or ""),
            source_id=str(raw.get("source_id") or ""),
            entry_id=str(raw.get("entry_id") or ""),
            owner_id=str(raw.get("owner_id") or ""),
            summoner_id=str(raw.get("summoner_id") or ""),
            entry_index=_optional_request_int(raw.get("entry_index")),
            copy_index=_optional_request_int(raw.get("copy_index")),
            spawn_index=_optional_request_int(raw.get("spawn_index")),
            wave_definition_id=str(raw.get("wave_definition_id") or ""),
            stage_id=str(raw.get("stage_id") or ""),
            wave_index=_optional_request_int(raw.get("wave_index")),
            position=_optional_request_int(raw.get("position")),
            source_trace=dict(raw.get("source_trace") or {}) if isinstance(raw.get("source_trace"), dict) else {},
            entry_source_trace=dict(raw.get("entry_source_trace") or {})
            if isinstance(raw.get("entry_source_trace"), dict)
            else {},
        )


@dataclass(frozen=True)
class UnitSpawnPlan:
    ok: bool
    unit_id: str = ""
    birth_template_id: str = ""
    blocked_reason: str = ""
    source_trace: dict[str, JSONValue] = field(default_factory=dict)
    request: dict[str, JSONValue] = field(default_factory=dict)
    unit: dict[str, JSONValue] = field(default_factory=dict)
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "unit_id": self.unit_id,
            "birth_template_id": self.birth_template_id,
            "blocked_reason": self.blocked_reason,
            "source_trace": self.source_trace,
            "request": self.request,
            "unit": self.unit,
            "metadata": self.metadata,
        }

    @classmethod
    def from_json(cls, value: JSONValue) -> "UnitSpawnPlan":
        raw = value if isinstance(value, dict) else {}
        return cls(
            ok=raw.get("ok") is True,
            unit_id=str(raw.get("unit_id") or ""),
            birth_template_id=str(raw.get("birth_template_id") or ""),
            blocked_reason=str(raw.get("blocked_reason") or ""),
            source_trace=dict(raw.get("source_trace") or {}) if isinstance(raw.get("source_trace"), dict) else {},
            request=dict(raw.get("request") or {}) if isinstance(raw.get("request"), dict) else {},
            unit=dict(raw.get("unit") or {}) if isinstance(raw.get("unit"), dict) else {},
            metadata=dict(raw.get("metadata") or {}) if isinstance(raw.get("metadata"), dict) else {},
        )

    def to_unit(self, expected_request: UnitSpawnRequest | None = None) -> UnitState:
        if not self.ok:
            raise ValueError(self.blocked_reason or "unit_spawn_plan_blocked")
        if not self.unit:
            raise ValueError("unit_spawn_plan_unit_missing")
        if not self.source_trace:
            raise ValueError("unit_spawn_plan_source_trace_missing")
        if not self.birth_template_id:
            raise ValueError("unit_spawn_plan_birth_template_id_missing")
        request = UnitSpawnRequest.from_json(self.request)
        _validate_spawn_request_complete(request)
        if expected_request is not None and request.to_json() != expected_request.to_json():
            raise ValueError("unit_spawn_plan_request_mismatch")
        unit_id = _required_string(self.unit, "unit_id")
        if unit_id != self.unit_id:
            raise ValueError("unit_spawn_plan_unit_id_mismatch")
        side = _required_side(self.unit, "side")
        template_id = _required_string(self.unit, "template_id")
        level = _required_int(self.unit, "level")
        max_hp = _required_number(self.unit, "max_hp")
        hp = _required_number(self.unit, "hp")
        attack = _required_number(self.unit, "attack")
        defense = _required_number(self.unit, "defense")
        speed = _required_number(self.unit, "speed")
        energy = _required_number(self.unit, "energy")
        max_energy = _required_number(self.unit, "max_energy")
        toughness = _required_number(self.unit, "toughness")
        max_toughness = _required_number(self.unit, "max_toughness")
        action_value = _required_number(self.unit, "action_value")
        flags = _required_dict(self.unit, "flags")
        resources = _required_resource_values(self.unit, "resources")
        _validate_required_birth_plan_values(
            level=level,
            max_hp=max_hp,
            hp=hp,
            speed=speed,
            energy=energy,
            max_energy=max_energy,
            toughness=toughness,
            max_toughness=max_toughness,
            action_value=action_value,
        )
        _validate_birth_plan_source_fields(request, flags)
        _validate_unit_request_binding(self, request, self.unit, flags)
        return UnitState(
            unit_id=unit_id,
            side=side,
            template_id=template_id,
            level=level,
            max_hp=max_hp,
            hp=hp,
            attack=attack,
            defense=defense,
            speed=speed,
            energy=energy,
            max_energy=max_energy,
            toughness=toughness,
            max_toughness=max_toughness,
            action_value=action_value,
            flags=flags,
            resources=resources,
        )


class UnitSpawnSystem:
    """Materializes pre-lowered birth templates without reading content cards."""

    def plan(
        self,
        template: UnitBirthTemplateIR,
        request: UnitSpawnRequest,
        *,
        owner: UnitState | None = None,
    ) -> UnitSpawnPlan:
        request_reason = _template_request_blocked_reason(template, request, owner)
        if request_reason:
            return self._blocked(request_reason, request=request, source_trace=request.entry_source_trace)
        if template.coverage_status != "executable":
            return self._blocked(
                template.blocked_reason or f"unit_birth_template_not_executable:{template.coverage_status}",
                request=request,
                source_trace=request.entry_source_trace,
            )
        try:
            fields: dict[str, JSONValue] = {"unit_id": request.unit_id}
            for field_name in (
                "side",
                "template_id",
                "level",
                "max_hp",
                "hp",
                "attack",
                "defense",
                "speed",
                "energy",
                "max_energy",
                "toughness",
                "max_toughness",
                "action_value",
            ):
                if field_name not in template.unit_field_specs:
                    raise ValueError(f"unit_birth_template_field_missing:{field_name}")
                fields[field_name] = _resolve_spec(
                    template.unit_field_specs[field_name],
                    request=request,
                    owner=owner,
                    fields=fields,
                )
            flags = {
                key: _resolve_spec(spec, request=request, owner=owner, fields=fields)
                for key, spec in template.flag_specs.items()
            }
            resources = {
                key: _resolve_spec(spec, request=request, owner=owner, fields=fields)
                for key, spec in template.resource_specs.items()
            }
            plan = UnitSpawnPlan(
                ok=True,
                unit_id=request.unit_id,
                birth_template_id=template.birth_template_id,
                source_trace=request.entry_source_trace,
                request=request.to_json(),
                unit={**fields, "flags": flags, "resources": resources},
                metadata={
                    "spawn_plan_kind": template.spawn_kind,
                    "birth_template_id": template.birth_template_id,
                    "birth_template_source_trace": template.source.to_json(),
                },
            )
            plan.to_unit(expected_request=request)
            return plan
        except ValueError as exc:
            return self._blocked(
                f"unit_birth_template_materialization_invalid:{exc}",
                request=request,
                source_trace=request.entry_source_trace,
            )

    def _blocked(
        self,
        reason: str,
        *,
        request: UnitSpawnRequest,
        source_trace: dict[str, JSONValue],
    ) -> UnitSpawnPlan:
        return UnitSpawnPlan(
            ok=False,
            unit_id=request.unit_id,
            birth_template_id=request.birth_template_id,
            blocked_reason=reason,
            source_trace=source_trace,
            request=request.to_json(),
            metadata={"spawn_plan_kind": request.spawn_kind},
        )


def spawn_plans_from_metadata(metadata: dict[str, JSONValue]) -> tuple[UnitSpawnPlan, ...]:
    raw = metadata.get("unit_spawn_plans") if isinstance(metadata, dict) else None
    if not isinstance(raw, list):
        return ()
    return tuple(UnitSpawnPlan.from_json(item) for item in raw)


def spawn_requests_from_metadata(metadata: dict[str, JSONValue]) -> tuple[UnitSpawnRequest, ...]:
    raw = metadata.get("unit_spawn_requests") if isinstance(metadata, dict) else None
    if not isinstance(raw, list):
        return ()
    return tuple(UnitSpawnRequest.from_json(item) for item in raw)


def _template_request_blocked_reason(
    template: UnitBirthTemplateIR,
    request: UnitSpawnRequest,
    owner: UnitState | None,
) -> str:
    try:
        _validate_spawn_request_complete(request)
    except ValueError as exc:
        return str(exc)
    if template.birth_template_id != request.birth_template_id:
        return "unit_birth_template_id_mismatch"
    if template.spawn_kind != request.spawn_kind:
        return "unit_birth_template_spawn_kind_mismatch"
    if template.entity_ref != request.entity_ref:
        return "unit_birth_template_entity_ref_mismatch"
    request_values = request.to_json()
    for key in (
        "spawn_kind",
        "entity_ref",
        "source_id",
        "entry_id",
        "wave_definition_id",
        "stage_id",
        "wave_index",
        "position",
    ):
        expected = template.request_contract.get(key)
        if expected is not None and request_values.get(key) != expected:
            return f"unit_birth_template_request_contract_mismatch:{key}"
    owner_required = template.request_contract.get("owner_required") is True
    if owner_required and owner is None:
        return "unit_birth_template_owner_missing"
    if owner is not None and request.owner_id != owner.unit_id:
        return "unit_birth_template_owner_id_mismatch"
    if template.request_contract.get("summoner_matches_owner") is True and request.summoner_id != request.owner_id:
        return "unit_birth_template_summoner_owner_mismatch"
    owner_entity_ref = str(template.request_contract.get("owner_entity_ref") or "")
    if owner_entity_ref and (owner is None or owner.template_id != owner_entity_ref):
        return "unit_birth_template_owner_entity_ref_mismatch"
    source_role = str(template.request_contract.get("template_source_role") or "")
    if source_role == "entry" and template.source.to_json() != request.entry_source_trace:
        return "unit_birth_template_entry_source_trace_mismatch"
    if source_role == "source" and template.source.to_json() != request.source_trace:
        return "unit_birth_template_source_trace_mismatch"
    if source_role not in {"entry", "source"}:
        return "unit_birth_template_source_role_missing"
    return ""


def _resolve_spec(
    spec: JSONValue,
    *,
    request: UnitSpawnRequest,
    owner: UnitState | None,
    fields: dict[str, JSONValue],
) -> JSONValue:
    if not isinstance(spec, dict) or not isinstance(spec.get("binding_kind"), str):
        return _json_copy(spec)
    kind = str(spec["binding_kind"])
    if kind == "request_field":
        return _request_field(request, str(spec.get("field") or ""))
    if kind == "owner_field":
        if owner is None:
            raise ValueError("unit_birth_binding_owner_missing")
        field_name = str(spec.get("field") or "")
        if not field_name or not hasattr(owner, field_name):
            raise ValueError(f"unit_birth_binding_owner_field_missing:{field_name}")
        return _json_copy(getattr(owner, field_name))
    if kind == "copy_unit_field":
        field_name = str(spec.get("field") or "")
        if field_name not in fields:
            raise ValueError(f"unit_birth_binding_unit_field_missing:{field_name}")
        return _json_copy(fields[field_name])
    if kind == "owner_linear":
        if owner is None:
            raise ValueError("unit_birth_binding_owner_missing")
        owner_field = str(spec.get("owner_field") or "")
        owner_value = _strict_number(getattr(owner, owner_field, None))
        scale = _strict_number(spec.get("scale"))
        offset = _strict_number(spec.get("offset"))
        minimum = _strict_number(spec.get("minimum"))
        if owner_value is None or scale is None or offset is None:
            raise ValueError(f"unit_birth_binding_owner_linear_source_missing:{owner_field}")
        value = owner_value * scale + offset
        return max(value, minimum) if minimum is not None else value
    if kind == "timeline_action_value":
        speed = _strict_number(fields.get(str(spec.get("speed_field") or "")))
        gauge = _strict_number(spec.get("base_action_gauge"))
        multiplier = _strict_number(spec.get("multiplier"))
        if speed is None or speed <= 0 or gauge is None or gauge <= 0 or multiplier is None or multiplier < 0:
            raise ValueError("unit_birth_binding_timeline_source_invalid")
        return max(0.0, gauge / speed * multiplier)
    if kind == "relative_owner_position":
        location_type = str(spec.get("location_type") or "")
        offset = _request_field(request, str(spec.get("offset_request_field") or ""))
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("unit_birth_binding_position_offset_invalid")
        owner_position = _unit_position(owner)
        if location_type == "BeforeCaster" and owner_position is not None:
            return owner_position - (offset + 1)
        if location_type == "AfterCaster" and owner_position is not None:
            return owner_position + (offset + 1)
        if location_type in {"First", "KeepOnFirst"}:
            return -1000 + offset
        if location_type in {"Last", "KeepOnLast"}:
            return 1000 + offset
        raise ValueError("unit_birth_binding_position_not_resolved")
    if kind == "owner_position":
        return _unit_position(owner)
    if kind == "owner_team_side":
        if owner is None:
            raise ValueError("unit_birth_binding_owner_missing")
        team_side = owner.flags.get("team_side")
        if team_side in {"ally", "enemy"}:
            return str(team_side)
        if owner.side in {"ally", "enemy"}:
            return owner.side
        return "neutral"
    if kind == "timeline_trace":
        speed = _strict_number(fields.get("speed"))
        action_value = _strict_number(fields.get("action_value"))
        multiplier = _strict_number(spec.get("multiplier"))
        if speed is None or speed <= 0 or action_value is None or multiplier is None or multiplier < 0:
            raise ValueError("unit_birth_binding_timeline_trace_invalid")
        base_action_value = action_value / multiplier if multiplier > 0 else 0.0
        return {
            **{key: _json_copy(value) for key, value in spec.items() if key not in {"binding_kind", "multiplier"}},
            "speed": speed,
            "base_action_value": base_action_value,
            "delay_ratio": multiplier,
            "initial_action_value": action_value,
        }
    if kind == "servant_runtime_stat_values":
        if owner is None:
            raise ValueError("unit_birth_binding_owner_missing")
        return {
            "max_hp": fields.get("max_hp"),
            "speed": fields.get("speed"),
            "attack": fields.get("attack"),
            "defense": fields.get("defense"),
            **{key: _json_copy(value) for key, value in spec.items() if key != "binding_kind"},
        }
    raise ValueError(f"unit_birth_binding_kind_unsupported:{kind}")


def _request_field(request: UnitSpawnRequest, field_name: str) -> JSONValue:
    values = request.to_json()
    if field_name not in values:
        raise ValueError(f"unit_birth_binding_request_field_unknown:{field_name}")
    return _json_copy(values[field_name])


def _unit_position(owner: UnitState | None) -> int | None:
    if owner is None:
        return None
    value = owner.flags.get("position")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _validate_spawn_request_complete(request: UnitSpawnRequest) -> None:
    if request.spawn_kind not in {"summoned_monster", "servant", "wave_enemy"}:
        raise ValueError("unit_spawn_request_kind_missing")
    for field_name in ("unit_id", "birth_template_id", "entity_ref", "source_id", "entry_id"):
        if not getattr(request, field_name):
            raise ValueError(f"unit_spawn_request_{field_name}_missing")
    if not request.source_trace or not request.entry_source_trace:
        raise ValueError("unit_spawn_request_source_trace_missing")
    if request.spawn_kind in {"summoned_monster", "servant"}:
        if not request.owner_id or not request.summoner_id:
            raise ValueError("unit_spawn_request_owner_missing")
    if request.spawn_kind == "summoned_monster":
        for field_name in ("entry_index", "copy_index", "spawn_index"):
            value = getattr(request, field_name)
            if not isinstance(value, int) or value < 0:
                raise ValueError(f"unit_spawn_request_{field_name}_missing")
    if request.spawn_kind == "wave_enemy":
        if not request.wave_definition_id or not request.stage_id:
            raise ValueError("unit_spawn_request_wave_identity_missing")
        if not isinstance(request.wave_index, int) or request.wave_index < 0 or not isinstance(request.position, int):
            raise ValueError("unit_spawn_request_wave_entry_missing")


def _validate_unit_request_binding(
    plan: UnitSpawnPlan,
    request: UnitSpawnRequest,
    data: dict[str, JSONValue],
    flags: dict[str, JSONValue],
) -> None:
    if plan.birth_template_id != request.birth_template_id:
        raise ValueError("unit_spawn_plan_birth_template_id_mismatch")
    if plan.unit_id != request.unit_id or data.get("unit_id") != request.unit_id:
        raise ValueError("unit_spawn_plan_request_unit_id_mismatch")
    if data.get("template_id") != request.entity_ref:
        raise ValueError("unit_spawn_plan_request_entity_ref_mismatch")
    if plan.metadata.get("spawn_plan_kind") != request.spawn_kind:
        raise ValueError("unit_spawn_plan_request_spawn_kind_mismatch")
    if plan.source_trace != request.entry_source_trace:
        raise ValueError("unit_spawn_plan_request_entry_source_mismatch")
    if request.spawn_kind == "summoned_monster":
        expected = {
            "summon_kind": "summoned_monster",
            "owner_id": request.owner_id,
            "summoner_id": request.summoner_id,
            "summon_intent_id": request.source_id,
            "summon_entry_id": request.entry_id,
            "summon_entry_index": request.entry_index,
            "summon_entry_copy_index": request.copy_index,
            "summon_spawn_index": request.spawn_index,
            "summon_source_trace": request.source_trace,
            "summon_entry_source_trace": request.entry_source_trace,
        }
    elif request.spawn_kind == "servant":
        expected = {
            "summon_kind": "servant",
            "owner_id": request.owner_id,
            "summoner_id": request.summoner_id,
            "servant_definition_id": request.source_id,
            "servant_ref": request.entity_ref,
            "summon_intent_id": request.source_id,
            "summon_source_trace": request.source_trace,
            "servant_definition_source_trace": request.entry_source_trace,
        }
    else:
        expected = {
            "wave_definition_id": request.wave_definition_id,
            "stage_id": request.stage_id,
            "wave_index": request.wave_index,
            "wave_position": request.position,
            "position": request.position,
            "wave_entry_id": request.entry_id,
            "wave_definition_source_trace": request.source_trace,
            "wave_entry_source_trace": request.entry_source_trace,
        }
    for key, value in expected.items():
        if flags.get(key) != value:
            raise ValueError(f"unit_spawn_plan_request_flag_mismatch:{key}")
    if request.spawn_kind == "wave_enemy" and data.get("level") != flags.get("stage_level"):
        raise ValueError("unit_spawn_plan_request_stage_level_mismatch")


def _validate_birth_plan_source_fields(request: UnitSpawnRequest, flags: dict[str, JSONValue]) -> None:
    if request.spawn_kind in {"summoned_monster", "servant"}:
        _required_flag_string(flags, "owner_id")
        _required_flag_string(flags, "summoner_id")
        _required_flag_dict(flags, "summon_source_trace")
    if request.spawn_kind == "summoned_monster":
        _required_flag_dict(flags, "summon_entry_source_trace")
        _required_flag_dict(flags, "combatant_profile_source_trace")
        _required_flag_dict(flags, "monster_data_card_source_trace")
    elif request.spawn_kind == "servant":
        _required_flag_dict(flags, "servant_definition_source_trace")
    elif request.spawn_kind == "wave_enemy":
        _required_flag_string(flags, "wave_definition_id")
        _required_flag_string(flags, "wave_entry_id")
        _required_flag_int(flags, "stage_level")
        _required_flag_int(flags, "hard_level_group")
        _required_flag_dict(flags, "stage_level_source_trace")
        _required_flag_dict(flags, "wave_entry_source_trace")
        _required_flag_dict(flags, "wave_definition_source_trace")
        _required_flag_dict(flags, "combatant_profile_source_trace")
        _required_flag_dict(flags, "monster_data_card_source_trace")


def _required_string(mapping: dict[str, JSONValue], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"unit_spawn_plan_{key}_missing")
    return value


def _required_side(mapping: dict[str, JSONValue], key: str) -> str:
    value = _required_string(mapping, key)
    if value not in {"ally", "enemy", "summon"}:
        raise ValueError("unit_spawn_plan_side_invalid")
    return value


def _required_int(mapping: dict[str, JSONValue], key: str) -> int:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"unit_spawn_plan_{key}_missing")
    return value


def _required_number(mapping: dict[str, JSONValue], key: str) -> float:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"unit_spawn_plan_{key}_missing")
    return float(value)


def _required_dict(mapping: dict[str, JSONValue], key: str) -> dict[str, JSONValue]:
    value = mapping.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"unit_spawn_plan_{key}_missing")
    return dict(value)


def _required_resource_values(mapping: dict[str, JSONValue], key: str) -> dict[str, float]:
    resources = _required_dict(mapping, key)
    converted: dict[str, float] = {}
    for resource_key, value in resources.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("unit_spawn_plan_resources_invalid")
        converted[str(resource_key)] = float(value)
    return converted


def _validate_required_birth_plan_values(
    *,
    level: int,
    max_hp: float,
    hp: float,
    speed: float,
    energy: float,
    max_energy: float,
    toughness: float,
    max_toughness: float,
    action_value: float,
) -> None:
    if level <= 0:
        raise ValueError("unit_spawn_plan_level_non_positive")
    if max_hp <= 0:
        raise ValueError("unit_spawn_plan_max_hp_non_positive")
    if hp < 0 or hp > max_hp:
        raise ValueError("unit_spawn_plan_hp_invalid")
    if speed <= 0:
        raise ValueError("unit_spawn_plan_speed_non_positive")
    if energy < 0 or max_energy < 0 or (max_energy and energy > max_energy):
        raise ValueError("unit_spawn_plan_energy_invalid")
    if toughness < 0 or max_toughness < 0 or toughness > max_toughness:
        raise ValueError("unit_spawn_plan_toughness_invalid")
    if action_value < 0:
        raise ValueError("unit_spawn_plan_action_value_invalid")


def _required_flag_string(flags: dict[str, JSONValue], key: str) -> str:
    value = flags.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"unit_spawn_plan_{key}_missing")
    return value


def _required_flag_dict(flags: dict[str, JSONValue], key: str) -> dict[str, JSONValue]:
    value = flags.get(key)
    if not isinstance(value, dict) or not value:
        raise ValueError(f"unit_spawn_plan_{key}_missing")
    return dict(value)


def _required_flag_int(flags: dict[str, JSONValue], key: str) -> int:
    value = flags.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"unit_spawn_plan_{key}_missing")
    return value


def _optional_request_int(value: JSONValue) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _strict_number(value: JSONValue) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _json_copy(value: object) -> JSONValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_copy(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_copy(item) for item in value]
    raise ValueError(f"unit_birth_template_non_json_value:{type(value).__name__}")
