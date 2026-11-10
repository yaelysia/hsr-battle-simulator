from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from ..builds.models import OwnedCombatantBuildAssemblyResult
from ..core.model import BattleState, JSONValue, UnitState, current_max_hp, freeze_json
from ..core.unit_state_codec import unit_state_from_payload
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
    # Formation positions already present on the owner's team when this request
    # was planned. Relative First/Last/BeforeCaster/AfterCaster bindings allocate
    # the next free slot from these facts instead of reusing an occupied slot.
    formation_positions: tuple[int, ...] = ()
    source_trace: dict[str, JSONValue] = field(default_factory=dict)
    entry_source_trace: dict[str, JSONValue] = field(default_factory=dict)
    # Effective battle level/difficulty context for a summoned monster. It is
    # resolved from the current battle's stage level policy at spawn time, so a
    # compiled template never freezes one level into every instance.
    level_context: dict[str, JSONValue] = field(default_factory=dict)

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
            "formation_positions": list(self.formation_positions),
            "source_trace": self.source_trace,
            "entry_source_trace": self.entry_source_trace,
            "level_context": self.level_context,
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
            formation_positions=_optional_position_tuple(raw.get("formation_positions")),
            source_trace=dict(raw.get("source_trace") or {}) if isinstance(raw.get("source_trace"), dict) else {},
            entry_source_trace=dict(raw.get("entry_source_trace") or {})
            if isinstance(raw.get("entry_source_trace"), dict)
            else {},
            # A malformed context collapses to an empty map so request validation
            # rejects it; it never becomes a valid default context.
            level_context=dict(raw.get("level_context") or {})
            if isinstance(raw.get("level_context"), dict)
            else {},
        )


@dataclass(frozen=True)
class UnitBirthFact:
    """Native spawn inputs, not reconstructed from plan/settlement JSON.

    The caller supplies evaluated creation inputs separately at consumption.
    Keeping these on the mutation lets audit re-materialize the formal template
    with the actual immutable owner instead of comparing two audited copies.
    """

    request: UnitSpawnRequest
    owner: UnitState
    state: BattleState
    initial_values: Mapping[str, JSONValue] = field(default_factory=dict)

    @property
    def parameter_values(self) -> dict[str, float]:
        return {name: entry["value"] for name, entry in self.initial_values.items()}

    def __post_init__(self) -> None:
        if type(self.request) is not UnitSpawnRequest or type(self.owner) is not UnitState:
            raise TypeError("unit birth fact requires native request and owner")
        if self.request.owner_id != self.owner.unit_id:
            raise ValueError("unit birth fact owner mismatch")
        if type(self.state) is not BattleState or self.state.units.get(self.owner.unit_id) != self.owner:
            raise ValueError("unit birth fact requires the native pre-birth state")
        values = dict(self.initial_values)
        if any(not isinstance(key, str) or not key or not isinstance(entry, dict)
               or type(entry.get("value")) not in (int, float)
               or not math.isfinite(entry["value"])
               or not isinstance(entry.get("hash"), str) or not entry["hash"]
               for key, entry in values.items()):
            raise ValueError("unit birth fact parameters invalid")
        object.__setattr__(self, "initial_values", freeze_json(values))
        object.__setattr__(self, "request", replace(self.request,
            source_trace=freeze_json(self.request.source_trace),
            entry_source_trace=freeze_json(self.request.entry_source_trace),
            level_context=freeze_json(self.request.level_context),
        ))


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

    def to_unit(
        self,
        *,
        expected_request: UnitSpawnRequest,
        expected_template: UnitBirthTemplateIR,
        owner: UnitState | None,
        parameter_values: Mapping[str, float] | None = None,
    ) -> UnitState:
        if not self.ok:
            raise ValueError(self.blocked_reason or "unit_spawn_plan_blocked")
        if not self.unit:
            raise ValueError("unit_spawn_plan_unit_missing")
        if not self.birth_template_id:
            raise ValueError("unit_spawn_plan_birth_template_id_missing")
        if not isinstance(expected_request, UnitSpawnRequest):
            raise ValueError("unit_spawn_plan_expected_request_missing")
        if not isinstance(expected_template, UnitBirthTemplateIR):
            raise ValueError("unit_spawn_plan_expected_template_missing")
        request = UnitSpawnRequest.from_json(self.request)
        _validate_spawn_request_complete(request)
        _validate_spawn_request_complete(expected_request)
        if _spawn_request_identity(request) != _spawn_request_identity(expected_request):
            raise ValueError("unit_spawn_plan_request_mismatch")
        if _spawn_request_source_identity(request) != _spawn_request_source_identity(
            expected_request
        ):
            raise ValueError("unit_spawn_plan_request_source_mismatch")
        template_reason = _template_request_blocked_reason(
            expected_template,
            expected_request,
            owner,
            parameter_values=parameter_values,
        )
        if template_reason:
            raise ValueError(f"unit_spawn_plan_expected_template_invalid:{template_reason}")
        if expected_template.coverage_status != "executable":
            raise ValueError("unit_spawn_plan_expected_template_not_executable")
        if self.birth_template_id != expected_template.birth_template_id:
            raise ValueError("unit_spawn_plan_expected_template_id_mismatch")
        _validate_expected_birth_template_source(self, expected_template)
        expected_unit = _materialize_unit_payload(
            expected_template,
            expected_request,
            owner,
            parameter_values=parameter_values,
        )
        _validate_nested_source_proofs(self.unit, "unit")
        _validate_nested_source_proofs(expected_unit, "expected_unit")
        if _evidence_neutral_json(self.unit) != _evidence_neutral_json(expected_unit):
            raise ValueError("unit_spawn_plan_template_payload_mismatch")
        unit = unit_state_from_payload(self.unit)
        if unit.unit_id != self.unit_id:
            raise ValueError("unit_spawn_plan_unit_id_mismatch")
        flags = dict(unit.flags)
        _validate_birth_plan_source_fields(self, request, flags)
        _validate_unit_request_binding(self, request, self.unit, flags)
        return unit


class UnitSpawnSystem:
    """Materializes pre-lowered birth templates without reading content cards."""

    def plan(
        self,
        template: UnitBirthTemplateIR,
        request: UnitSpawnRequest,
        *,
        owner: UnitState | None = None,
        parameter_values: Mapping[str, float] | None = None,
    ) -> UnitSpawnPlan:
        request_reason = _template_request_blocked_reason(
            template,
            request,
            owner,
            parameter_values=parameter_values,
        )
        if request_reason:
            return self._blocked(request_reason, request=request, source_trace=request.entry_source_trace)
        if template.coverage_status != "executable":
            return self._blocked(
                template.blocked_reason or f"unit_birth_template_not_executable:{template.coverage_status}",
                request=request,
                source_trace=request.entry_source_trace,
            )
        try:
            unit = _materialize_unit_payload(
                template,
                request,
                owner,
                parameter_values=parameter_values,
            )
            plan = UnitSpawnPlan(
                ok=True,
                unit_id=request.unit_id,
                birth_template_id=template.birth_template_id,
                source_trace=request.entry_source_trace,
                request=request.to_json(),
                unit=unit,
                metadata={
                    "spawn_plan_kind": template.spawn_kind,
                    "birth_template_id": template.birth_template_id,
                    "birth_template_source_trace": template.source.to_json(),
                    "template_source_role": template.request_contract.get(
                        "template_source_role"
                    ),
                },
            )
            plan.to_unit(
                expected_request=request,
                expected_template=template,
                owner=owner,
                parameter_values=parameter_values,
            )
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


_LEVEL_CONTEXT_KIND = "battle_stage_level_hard_level_group_inherited_from_summoner"
_LEVEL_CONTEXT_STAT_FIELDS = ("max_hp", "attack", "defense", "speed", "max_toughness")
_LEVEL_CONTEXT_FIELD_NAMES = frozenset(
    {"level", "stage_id", "hard_level_group", "elite_group", "source_trace"}
)


def _level_context_ratios(context: dict[str, JSONValue]) -> dict[str, JSONValue]:
    ratios = context.get("ratios")
    return dict(ratios) if isinstance(ratios, dict) else {}


def _required_level_context(request: UnitSpawnRequest) -> dict[str, JSONValue]:
    """Validate the effective battle level context carried by a spawn request.

    This context is the only authority allowed to scale a summoned monster's
    profile base panel. A missing, malformed or non-executable context blocks the
    spawn; it never falls back to base stats, level 1 or an owner panel.
    """

    context = request.level_context
    if not isinstance(context, dict) or not context:
        raise ValueError("unit_spawn_request_level_context_missing")
    if str(context.get("kind") or "") != _LEVEL_CONTEXT_KIND:
        raise ValueError("unit_spawn_request_level_context_kind_unsupported")
    if context.get("admission_status") != "executable":
        raise ValueError("unit_spawn_request_level_context_not_admitted")
    for key in ("stage_id", "wave_definition_id"):
        value = context.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"unit_spawn_request_level_context_{key}_missing")
    for key in ("level", "hard_level_group"):
        value = context.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"unit_spawn_request_level_context_{key}_missing")
    elite_group = context.get("elite_group")
    if elite_group is not None and (
        isinstance(elite_group, bool)
        or not isinstance(elite_group, int)
        or elite_group <= 0
    ):
        raise ValueError("unit_spawn_request_level_context_elite_group_invalid")
    ratios = _level_context_ratios(context)
    for field_name in _LEVEL_CONTEXT_STAT_FIELDS:
        ratio = _strict_number(ratios.get(field_name))
        if ratio is None or ratio <= 0 or not math.isfinite(ratio):
            raise ValueError(
                f"unit_spawn_request_level_context_ratio_invalid:{field_name}"
            )
    _required_source_trace_identity(
        context.get("source_trace"),
        "request_level_context_source_trace",
    )
    return dict(context)


def _level_context_identity(context: dict[str, JSONValue]) -> tuple[JSONValue, ...]:
    """Behavioral identity of the level context; source traces stay audit-only."""

    if not isinstance(context, dict) or not context:
        return ()
    ratios = _level_context_ratios(context)
    return (
        str(context.get("kind") or ""),
        str(context.get("admission_status") or ""),
        str(context.get("stage_id") or ""),
        str(context.get("wave_definition_id") or ""),
        context.get("level"),
        context.get("hard_level_group"),
        context.get("elite_group"),
        tuple((name, _strict_number(ratios.get(name))) for name in _LEVEL_CONTEXT_STAT_FIELDS),
    )


def _template_request_blocked_reason(
    template: UnitBirthTemplateIR,
    request: UnitSpawnRequest,
    owner: UnitState | None,
    *,
    parameter_values: Mapping[str, float] | None = None,
) -> str:
    try:
        _validate_spawn_request_complete(request)
    except ValueError as exc:
        return str(exc)
    source_reason = _spawn_request_source_proof_blocked_reason(template, request)
    if source_reason:
        return source_reason
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
    owner_entity_refs = template.request_contract.get("owner_entity_refs")
    if owner_entity_refs is not None:
        if (
            not isinstance(owner_entity_refs, (list, tuple))
            or not owner_entity_refs
            or not all(isinstance(item, str) and item for item in owner_entity_refs)
        ):
            return "unit_birth_template_owner_entity_refs_invalid"
        if owner is None or owner.template_id not in owner_entity_refs:
            return "unit_birth_template_owner_entity_ref_mismatch"
    source_role = str(template.request_contract.get("template_source_role") or "")
    expected_source_role = "source" if request.spawn_kind == "wave_enemy" else "entry"
    if source_role != expected_source_role:
        return "unit_birth_template_source_role_mismatch"
    creation_bindings = template.request_contract.get("creation_parameter_bindings")
    if creation_bindings:
        if not isinstance(creation_bindings, Mapping):
            return "unit_birth_template_creation_parameter_bindings_invalid"
        max_hp_name = str(creation_bindings.get("max_hp") or "")
        if not max_hp_name:
            return "unit_birth_template_creation_max_hp_parameter_missing"
        max_hp_value = _strict_number((parameter_values or {}).get(max_hp_name))
        if (
            max_hp_value is None
            or not math.isfinite(max_hp_value)
            or max_hp_value <= 0
        ):
            return "unit_birth_template_creation_max_hp_parameter_missing_or_nonpositive"
        current_hp_name = str(creation_bindings.get("current_hp") or "")
        if current_hp_name:
            current_hp_value = _strict_number((parameter_values or {}).get(current_hp_name))
            if (
                current_hp_value is None
                or not math.isfinite(current_hp_value)
                or current_hp_value <= 0
            ):
                return "unit_birth_template_creation_current_hp_parameter_invalid"
    return ""


def _materialize_unit_payload(
    template: UnitBirthTemplateIR,
    request: UnitSpawnRequest,
    owner: UnitState | None,
    parameter_values: Mapping[str, float] | None = None,
) -> dict[str, JSONValue]:
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
        "max_toughness",
        "toughness",
        "action_value",
    ):
        if field_name not in template.unit_field_specs:
            raise ValueError(f"unit_birth_template_field_missing:{field_name}")
        fields[field_name] = _resolve_spec(
            template.unit_field_specs[field_name],
            request=request,
            owner=owner,
            fields=fields,
            parameters=parameter_values,
        )
    flags = {
        key: _resolve_spec(
            spec,
            request=request,
            owner=owner,
            fields=fields,
            parameters=parameter_values,
        )
        for key, spec in template.flag_specs.items()
    }
    resources = {
        key: _resolve_spec(
            spec,
            request=request,
            owner=owner,
            fields=fields,
            parameters=parameter_values,
        )
        for key, spec in template.resource_specs.items()
    }
    return {
        **fields,
        "lifecycle_status": "active",
        "statuses": [],
        "shield_instances": [],
        "flags": flags,
        "resources": resources,
        "stat_pools": [],
    }


def _evidence_neutral_json(value: JSONValue) -> JSONValue:
    if isinstance(value, list):
        return [_evidence_neutral_json(item) for item in value]
    if not isinstance(value, dict):
        return value
    if all(
        isinstance(value.get(key), str) and bool(str(value.get(key)).strip())
        for key in ("source_path", "raw_type", "raw_id")
    ):
        return {
            "source_path": str(value["source_path"]),
            "raw_type": str(value["raw_type"]),
            "raw_id": str(value["raw_id"]),
        }
    return {
        str(key): _evidence_neutral_json(item)
        for key, item in value.items()
    }


def _resolve_spec(
    spec: JSONValue,
    *,
    request: UnitSpawnRequest,
    owner: UnitState | None,
    fields: dict[str, JSONValue],
    parameters: Mapping[str, float] | None = None,
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
    if kind == "creation_parameter":
        parameter_name = str(spec.get("parameter_name") or "")
        parameter_family = str(spec.get("parameter_family") or "")
        value = _strict_number((parameters or {}).get(parameter_name))
        if (
            parameter_name
            and parameter_family in {"max_hp", "current_hp"}
            and value is not None
            and math.isfinite(value)
            and value > 0
        ):
            return value
        fallback = spec.get("fallback")
        if isinstance(fallback, dict):
            return _resolve_spec(
                fallback,
                request=request,
                owner=owner,
                fields=fields,
                parameters=parameters,
            )
        raise ValueError(
            f"unit_birth_binding_creation_parameter_missing:{parameter_name}"
        )
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
    if kind == "level_context_field":
        context = _required_level_context(request)
        field_name = str(spec.get("field") or "")
        if field_name not in _LEVEL_CONTEXT_FIELD_NAMES:
            raise ValueError(
                f"unit_birth_binding_level_context_field_unsupported:{field_name}"
            )
        return _json_copy(context.get(field_name))
    if kind == "level_context_scaled_stat":
        context = _required_level_context(request)
        field_name = str(spec.get("field_name") or "")
        if field_name not in _LEVEL_CONTEXT_STAT_FIELDS:
            raise ValueError(
                f"unit_birth_binding_level_context_stat_unsupported:{field_name}"
            )
        base_value = _strict_number(spec.get("base_value"))
        ratio = _strict_number(_level_context_ratios(context).get(field_name))
        if (
            base_value is None
            or base_value < 0
            or not math.isfinite(base_value)
            or ratio is None
            or not math.isfinite(ratio)
        ):
            raise ValueError(
                f"unit_birth_binding_level_context_scaled_stat_invalid:{field_name}"
            )
        return base_value * ratio
    if kind == "level_context_scaling_summary":
        context = _required_level_context(request)
        return {
            "binding_kind": "combatant_profile_base_stat_times_battle_level_ratio",
            "level_context_kind": str(context.get("kind") or ""),
            "stage_id": str(context.get("stage_id") or ""),
            "wave_definition_id": str(context.get("wave_definition_id") or ""),
            "level": context.get("level"),
            "hard_level_group": context.get("hard_level_group"),
            "elite_group": context.get("elite_group"),
            "ratios": _json_copy(_level_context_ratios(context)),
            "source_trace": _json_copy(context.get("source_trace")),
            "resolved_at": "unit_spawn_from_current_battle_stage_level_policy",
        }
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
        occupied = frozenset(request.formation_positions)
        # First/Last are formation endpoints, not merely the historical +-1000
        # anchors: when a present formation already reaches past the anchor
        # (multi-copy spawn_index growth, or a gap left by a departed sibling),
        # scanning from the anchor would land inside the formation. The result
        # is computed outside [min(occupied), max(occupied)] directly, so no
        # free-slot scan is needed on these two paths.
        if location_type in {"First", "KeepOnFirst"}:
            return min(-1000, min(occupied, default=0) - 1) - offset
        if location_type in {"Last", "KeepOnLast"}:
            return max(1000, max(occupied, default=0) + 1) + offset
        if location_type == "BeforeCaster" and owner_position is not None:
            return _first_free_relative_position(
                owner_position - (offset + 1), -1, occupied
            )
        if location_type == "AfterCaster" and owner_position is not None:
            return _first_free_relative_position(
                owner_position + (offset + 1), 1, occupied
            )
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
    if kind == "owner_relation":
        if owner is None:
            raise ValueError("unit_birth_binding_owner_missing")
        relations = spec.get("relations")
        if not isinstance(relations, list):
            raise ValueError("unit_birth_binding_owner_relations_missing")
        matches = tuple(
            relation
            for relation in relations
            if isinstance(relation, dict)
            and relation.get("owner_entity_ref") == owner.template_id
            and relation.get("coverage_status") == "executable"
        )
        if len(matches) != 1:
            raise ValueError("unit_birth_binding_owner_relation_not_unique")
        return _json_copy(matches[0])
    if kind == "owner_owned_combatant_build":
        definition_id = str(spec.get("servant_definition_id") or "")
        return _owned_combatant_result(owner, definition_id).to_json()
    if kind == "owned_combatant_stat":
        definition_id = str(spec.get("servant_definition_id") or "")
        property_type = str(spec.get("property_type") or "")
        result = _owned_combatant_result(owner, definition_id)
        return _resolve_owned_combatant_stat(
            owner,
            result,
            property_type,
            inactive_value=spec.get("inactive_value"),
        )
    if kind == "owned_combatant_runtime_stat_values":
        definition_id = str(spec.get("servant_definition_id") or "")
        result = _owned_combatant_result(owner, definition_id)
        values = {
            binding.property_type: _resolve_owned_combatant_stat(
                owner,
                result,
                binding.property_type,
                inactive_value=(
                    0.0 if binding.binding_kind == "inactive_schema_slot" else None
                ),
            )
            for binding in result.stat_bindings
        }
        return {
            "owned_build_id": result.owned_build_id,
            "owned_build_fingerprint": result.result_fingerprint,
            "materialized_values": values,
            "stat_bindings": [binding.to_json() for binding in result.stat_bindings],
        }
    if kind == "owned_combatant_damage_stat_admission":
        definition_id = str(spec.get("servant_definition_id") or "")
        result = _owned_combatant_result(owner, definition_id)
        required = ("attack", "defense", "critical_chance", "critical_damage")
        bindings = {
            property_type: _owned_combatant_stat_binding(result, property_type)
            for property_type in required
        }
        if any(
            binding.binding_kind == "inactive_schema_slot"
            for binding in bindings.values()
        ):
            raise ValueError("unit_birth_binding_damage_stat_inactive")
        values = {
            property_type: _resolve_owned_combatant_stat(
                owner,
                result,
                property_type,
            )
            for property_type in required
        }
        return {
            "coverage_status": "executable",
            "owned_build_id": result.owned_build_id,
            "owned_build_fingerprint": result.result_fingerprint,
            "servant_definition_id": result.servant_definition_id,
            "required_property_types": list(required),
            "materialized_values": values,
            "stat_bindings": [
                bindings[property_type].to_json() for property_type in required
            ],
        }
    if kind == "not_scheduled_timeline_trace":
        if spec.get("timeline_admitted") is not False:
            raise ValueError("unit_birth_binding_not_scheduled_trace_invalid")
        return {
            **{
                key: _json_copy(value)
                for key, value in spec.items()
                if key != "binding_kind"
            },
            "speed": 0.0,
            "base_action_value": 0.0,
            "delay_ratio": 0.0,
            "initial_action_value": 0.0,
            "scheduled": False,
        }
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
    raise ValueError(f"unit_birth_binding_kind_unsupported:{kind}")


def _owned_combatant_result(
    owner: UnitState | None,
    definition_id: str,
) -> OwnedCombatantBuildAssemblyResult:
    if owner is None:
        raise ValueError("unit_birth_binding_owner_missing")
    raw_results = owner.flags.get("owned_combatant_build_results")
    if not definition_id or not isinstance(raw_results, dict):
        raise ValueError("unit_birth_binding_owned_combatant_build_missing")
    raw_result = raw_results.get(definition_id)
    try:
        result = OwnedCombatantBuildAssemblyResult.from_json(raw_result)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"unit_birth_binding_owned_combatant_build_invalid:{exc}"
        ) from exc
    if (
        result.servant_definition_id != definition_id
        or result.owner_entity_ref != owner.template_id
        or result.battle_admission_status != "admitted"
    ):
        raise ValueError("unit_birth_binding_owned_combatant_build_not_admitted")
    expected_fingerprints = owner.flags.get(
        "owned_combatant_build_result_fingerprints"
    )
    if (
        not isinstance(expected_fingerprints, dict)
        or expected_fingerprints.get(definition_id) != result.result_fingerprint
    ):
        raise ValueError("unit_birth_binding_owned_combatant_build_fingerprint_mismatch")
    return result


def _owned_combatant_stat_binding(
    result: OwnedCombatantBuildAssemblyResult,
    property_type: str,
):
    if not property_type:
        raise ValueError("unit_birth_binding_owned_combatant_property_missing")
    matches = tuple(
        binding
        for binding in result.stat_bindings
        if binding.property_type == property_type
    )
    if len(matches) != 1:
        raise ValueError(
            f"unit_birth_binding_owned_combatant_stat_not_unique:{property_type}"
        )
    return matches[0]


def _owned_owner_stat(owner: UnitState, field_name: str) -> float | None:
    """Resolve inherited combat stats at birth from the shared stat authority."""
    from .unit_stats import effective_unit_stat

    if field_name == "max_hp":
        return current_max_hp(owner)
    if field_name in {"attack", "defense", "speed", "critical_chance", "critical_damage"}:
        value = effective_unit_stat(owner, field_name).value
        return value if math.isfinite(value) else None
    return None


def _resolve_owned_combatant_stat(
    owner: UnitState | None,
    result: OwnedCombatantBuildAssemblyResult,
    property_type: str,
    *,
    inactive_value: JSONValue = None,
) -> float:
    if owner is None:
        raise ValueError("unit_birth_binding_owner_missing")
    binding = _owned_combatant_stat_binding(result, property_type)
    if binding.binding_kind == "owner_linear":
        owner_value = _owned_owner_stat(owner, binding.owner_field)
        scale = _finite_decimal_number(binding.scale)
        offset = _finite_decimal_number(binding.offset)
        if owner_value is None or scale is None or offset is None:
            raise ValueError(
                f"unit_birth_binding_owned_combatant_owner_linear_invalid:{property_type}"
            )
        return owner_value * scale + offset
    if binding.binding_kind == "owner_field":
        value = _owned_owner_stat(owner, binding.owner_field)
        if value is None:
            raise ValueError(
                f"unit_birth_binding_owned_combatant_owner_field_invalid:{property_type}"
            )
        return value
    if binding.binding_kind == "owner_resource":
        value = _owned_owner_stat(owner, binding.owner_field)
        if value is None:
            raise ValueError(
                f"unit_birth_binding_owned_combatant_owner_resource_missing:{property_type}"
            )
        return value
    if binding.binding_kind == "fixed":
        value = _finite_decimal_number(binding.exact_value)
        if value is None:
            raise ValueError(
                f"unit_birth_binding_owned_combatant_fixed_value_invalid:{property_type}"
            )
        return value
    if binding.binding_kind == "inactive_schema_slot":
        value = _strict_number(inactive_value)
        if value is None:
            raise ValueError(
                f"unit_birth_binding_owned_combatant_inactive_value_missing:{property_type}"
            )
        return value
    raise ValueError(
        f"unit_birth_binding_owned_combatant_stat_kind_unsupported:{binding.binding_kind}"
    )


def _finite_decimal_number(value: str | None) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _first_free_relative_position(
    start: int,
    step: int,
    occupied: frozenset[int],
) -> int:
    """Return the nearest free formation slot from the anchor direction.

    Siblings in one plan are planned sequentially, so each request receives the
    formation facts that already include the earlier allocations. Reusing an
    occupied slot would make EntityRelationResolver's formation adjacency
    ambiguous (a duplicate position), so allocation stays unique instead.
    """

    candidate = start
    for _ in range(4096):
        if candidate not in occupied:
            return candidate
        candidate += step
    raise ValueError("unit_birth_binding_position_allocation_exhausted")


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
    if request.spawn_kind in {"summoned_monster", "servant"}:
        if not request.owner_id or not request.summoner_id:
            raise ValueError("unit_spawn_request_owner_missing")
    if request.spawn_kind == "summoned_monster":
        for field_name in ("entry_index", "copy_index", "spawn_index"):
            value = getattr(request, field_name)
            if not isinstance(value, int) or value < 0:
                raise ValueError(f"unit_spawn_request_{field_name}_missing")
        _required_level_context(request)
    positions = request.formation_positions
    if not isinstance(positions, tuple):
        raise ValueError("unit_spawn_request_formation_positions_not_tuple")
    if any(
        isinstance(value, bool) or not isinstance(value, int) for value in positions
    ):
        raise ValueError("unit_spawn_request_formation_position_not_integer")
    if len(positions) != len(set(positions)):
        raise ValueError("unit_spawn_request_formation_position_duplicate")
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
        }
    elif request.spawn_kind == "servant":
        expected = {
            "summon_kind": "servant",
            "owner_id": request.owner_id,
            "summoner_id": request.summoner_id,
            "servant_definition_id": request.source_id,
            "servant_ref": request.entity_ref,
            "summon_intent_id": request.source_id,
        }
    else:
        expected = {
            "wave_definition_id": request.wave_definition_id,
            "stage_id": request.stage_id,
            "wave_index": request.wave_index,
            "wave_position": request.position,
            "position": request.position,
            "wave_entry_id": request.entry_id,
        }
    for key, value in expected.items():
        if flags.get(key) != value:
            raise ValueError(f"unit_spawn_plan_request_flag_mismatch:{key}")
    if request.spawn_kind == "wave_enemy" and data.get("level") != flags.get("stage_level"):
        raise ValueError("unit_spawn_plan_request_stage_level_mismatch")
    if request.spawn_kind == "summoned_monster":
        _validate_summoned_monster_level_context(data, flags, request)


def _validate_summoned_monster_level_context(
    data: dict[str, JSONValue],
    flags: dict[str, JSONValue],
    request: UnitSpawnRequest,
) -> None:
    """The born unit must carry exactly the level context the request declared."""

    context = _required_level_context(request)
    if flags.get("stage_id") != context["stage_id"]:
        raise ValueError("unit_spawn_plan_request_level_context_stage_mismatch")
    if flags.get("hard_level_group") != context["hard_level_group"]:
        raise ValueError("unit_spawn_plan_request_level_context_group_mismatch")
    carried = flags.get("summon_level_context")
    if not isinstance(carried, Mapping) or _level_context_identity(dict(carried)) != _level_context_identity(context):
        raise ValueError("unit_spawn_plan_request_level_context_mismatch")
    _require_matching_flag_source(
        flags,
        "summon_level_source_trace",
        _required_source_trace_identity(
            context.get("source_trace"),
            "request_level_context_source_trace",
        ),
    )
    if data.get("level") != context["level"]:
        raise ValueError("unit_spawn_plan_request_level_context_level_mismatch")
    scaling = flags.get("summon_stat_scaling")
    if not isinstance(scaling, Mapping) or scaling.get("level") != context["level"]:
        raise ValueError("unit_spawn_plan_request_level_context_scaling_missing")
    max_hp = _strict_number(data.get("max_hp"))
    hp = _strict_number(data.get("hp"))
    max_toughness = _strict_number(data.get("max_toughness"))
    toughness = _strict_number(data.get("toughness"))
    if max_hp is None or hp != max_hp:
        raise ValueError("unit_spawn_plan_request_birth_hp_not_full")
    if max_toughness is None or toughness != max_toughness:
        raise ValueError("unit_spawn_plan_request_birth_toughness_not_full")


def _validate_birth_plan_source_fields(
    plan: UnitSpawnPlan,
    request: UnitSpawnRequest,
    flags: dict[str, JSONValue],
) -> None:
    request_source_identity = _required_source_trace_identity(
        request.source_trace,
        "request_source_trace",
    )
    entry_source_identity = _required_source_trace_identity(
        request.entry_source_trace,
        "request_entry_source_trace",
    )
    if _required_source_trace_identity(plan.source_trace, "plan_source_trace") != entry_source_identity:
        raise ValueError("unit_spawn_plan_source_proof_mismatch")
    expected_source_role = "source" if request.spawn_kind == "wave_enemy" else "entry"
    if plan.metadata.get("template_source_role") != expected_source_role:
        raise ValueError("unit_spawn_plan_template_source_role_mismatch")
    template_source_identity = _required_source_trace_identity(
        plan.metadata.get("birth_template_source_trace"),
        "birth_template_source_trace",
    )
    expected_template_identity = (
        request_source_identity
        if expected_source_role == "source"
        else entry_source_identity
    )
    if template_source_identity != expected_template_identity:
        raise ValueError("unit_spawn_plan_birth_template_source_mismatch")
    if request.spawn_kind == "summoned_monster":
        _required_flag_string(flags, "owner_id")
        _required_flag_string(flags, "summoner_id")
        _require_matching_flag_source(
            flags,
            "summon_source_trace",
            request_source_identity,
        )
        _require_matching_flag_source(
            flags,
            "summon_entry_source_trace",
            entry_source_identity,
        )
    elif request.spawn_kind == "servant":
        _required_flag_string(flags, "owner_id")
        _required_flag_string(flags, "summoner_id")
        _require_matching_flag_source(
            flags,
            "summon_source_trace",
            request_source_identity,
        )
        _require_matching_flag_source(
            flags,
            "servant_definition_source_trace",
            entry_source_identity,
        )
    else:
        _required_flag_string(flags, "wave_definition_id")
        _required_flag_string(flags, "wave_entry_id")
        _required_flag_int(flags, "stage_level")
        _required_flag_int(flags, "hard_level_group")
        _require_matching_flag_source(
            flags,
            "wave_definition_source_trace",
            request_source_identity,
        )
        _require_matching_flag_source(
            flags,
            "wave_entry_source_trace",
            entry_source_identity,
        )
        stage_source_identity = _required_source_trace_identity(
            flags.get("stage_level_source_trace"),
            "stage_level_source_trace",
        )
        stage_level_policy = flags.get("stage_level_policy")
        if not isinstance(stage_level_policy, Mapping):
            raise ValueError("unit_spawn_plan_stage_level_policy_missing")
        if _required_source_trace_identity(
            stage_level_policy.get("source_trace"),
            "stage_level_policy_source_trace",
        ) != stage_source_identity:
            raise ValueError("unit_spawn_plan_stage_level_source_mismatch")


def _validate_expected_birth_template_source(
    plan: UnitSpawnPlan,
    expected_template: UnitBirthTemplateIR,
) -> None:
    if _required_source_trace_identity(
        plan.metadata.get("birth_template_source_trace"),
        "birth_template_source_trace",
    ) != _required_source_trace_identity(
        expected_template.source.to_json(),
        "expected_birth_template_source_trace",
    ):
        raise ValueError("unit_spawn_plan_expected_template_source_mismatch")


def _validate_nested_source_proofs(value: JSONValue, field_name: str) -> None:
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_nested_source_proofs(item, f"{field_name}_{index}")
        return
    if not isinstance(value, dict):
        return
    identity_keys = ("source_path", "raw_type", "raw_id")
    if all(key in value for key in identity_keys):
        _required_source_trace_identity(value, field_name)
        return
    for key, item in value.items():
        _validate_nested_source_proofs(item, f"{field_name}_{key}")


def _spawn_request_source_proof_blocked_reason(
    template: UnitBirthTemplateIR,
    request: UnitSpawnRequest,
) -> str:
    try:
        request_source_identity = _required_source_trace_identity(
            request.source_trace,
            "request_source_trace",
        )
        entry_source_identity = _required_source_trace_identity(
            request.entry_source_trace,
            "request_entry_source_trace",
        )
        template_source_identity = _required_source_trace_identity(
            template.source.to_json(),
            "birth_template_source_trace",
        )
    except ValueError as exc:
        return str(exc)
    source_role = str(template.request_contract.get("template_source_role") or "")
    expected_source_role = "source" if request.spawn_kind == "wave_enemy" else "entry"
    if source_role != expected_source_role:
        return "unit_birth_template_source_role_mismatch"
    expected_template_identity = (
        request_source_identity
        if source_role == "source"
        else entry_source_identity
    )
    if template_source_identity != expected_template_identity:
        return "unit_birth_template_source_identity_mismatch"
    return ""


def _required_source_trace_identity(
    value: object,
    field_name: str,
) -> tuple[tuple[str, str, str], ...]:
    if not isinstance(value, Mapping):
        raise ValueError(f"unit_spawn_plan_{field_name}_missing")
    identity_keys = ("source_path", "raw_type", "raw_id")
    if any(key in value for key in identity_keys):
        identity: list[str] = []
        for key in identity_keys:
            item = value.get(key)
            if not isinstance(item, str) or not item.strip():
                raise ValueError(f"unit_spawn_plan_{field_name}_{key}_missing")
            identity.append(item)
        evidence = value.get("evidence")
        if not isinstance(evidence, Mapping):
            raise ValueError(f"unit_spawn_plan_{field_name}_evidence_missing")
        return ((identity[0], identity[1], identity[2]),)
    nested_identities: list[tuple[str, str, str]] = []
    for key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
        if not isinstance(item, Mapping):
            continue
        nested_identities.extend(
            _required_source_trace_identity(item, f"{field_name}_{key}")
        )
    if not nested_identities:
        raise ValueError(f"unit_spawn_plan_{field_name}_identity_missing")
    return tuple(sorted(set(nested_identities)))


def _spawn_request_source_identity(
    request: UnitSpawnRequest,
) -> tuple[
    tuple[tuple[str, str, str], ...],
    tuple[tuple[str, str, str], ...],
]:
    return (
        _required_source_trace_identity(request.source_trace, "request_source_trace"),
        _required_source_trace_identity(
            request.entry_source_trace,
            "request_entry_source_trace",
        ),
    )


def _require_matching_flag_source(
    flags: dict[str, JSONValue],
    key: str,
    expected_identity: tuple[tuple[str, str, str], ...],
) -> None:
    if _required_source_trace_identity(flags.get(key), key) != expected_identity:
        raise ValueError(f"unit_spawn_plan_{key}_mismatch")


def _spawn_request_identity(request: UnitSpawnRequest) -> tuple[JSONValue, ...]:
    """Behavioral request identity; deliberately excludes audit/source traces."""

    return (
        request.spawn_kind,
        request.unit_id,
        request.birth_template_id,
        request.entity_ref,
        request.source_id,
        request.entry_id,
        request.owner_id,
        request.summoner_id,
        request.entry_index,
        request.copy_index,
        request.spawn_index,
        request.wave_definition_id,
        request.stage_id,
        request.wave_index,
        request.position,
        tuple(request.formation_positions),
        _level_context_identity(request.level_context),
    )


def _required_flag_string(flags: dict[str, JSONValue], key: str) -> str:
    value = flags.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"unit_spawn_plan_{key}_missing")
    return value


def _required_flag_int(flags: dict[str, JSONValue], key: str) -> int:
    value = flags.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"unit_spawn_plan_{key}_missing")
    return value


def _optional_position_tuple(value: JSONValue) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    positions: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            continue
        positions.append(item)
    return tuple(positions)


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
