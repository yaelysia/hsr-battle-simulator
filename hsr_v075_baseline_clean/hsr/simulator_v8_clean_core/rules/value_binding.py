from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.model import JSONValue
from .evaluator import NumericEvaluationContext, RuleEvaluator
from .expression_ir import numeric_dynamic_hash, numeric_fixed_value
from .rulebook import RuleBook


ACTION_DEFINITION_NUMERIC_FIELDS = frozenset(
    {
        "bp_need",
        "bp_add",
        "sp_base",
        "sp_multiple_ratio",
    }
)
ACTION_DEFINITION_LIST_FIELDS = frozenset(
    {
        "param_list",
        "show_damage_list",
        "show_stance_list",
    }
)


@dataclass(frozen=True)
class StaticValueBindingContext:
    action_id: str = ""
    action_level: int | None = None
    skill_level: int | None = None
    data_card_level: int | None = None
    actor_id: str = ""
    target_id: str = ""
    owner_id: str = ""
    summoner_id: str = ""
    data_card_id: str = ""
    data_card_kind: str = ""
    source_trace: dict[str, JSONValue] = field(default_factory=dict)

    def level_with_source(self) -> tuple[int | None, str]:
        if self.action_level is not None:
            return self.action_level, "action_level"
        if self.skill_level is not None:
            return self.skill_level, "skill_level"
        if self.data_card_level is not None:
            return self.data_card_level, "data_card_level"
        return None, ""

    def to_trace(self) -> dict[str, JSONValue]:
        level, level_source = self.level_with_source()
        return {
            "action_id": self.action_id,
            "level": level,
            "level_source": level_source,
            "actor_id": self.actor_id,
            "target_id": self.target_id,
            "owner_id": self.owner_id,
            "summoner_id": self.summoner_id,
            "data_card_id": self.data_card_id,
            "data_card_kind": self.data_card_kind,
            "source_trace": self.source_trace,
        }


@dataclass(frozen=True)
class ValueContext:
    actor_id: str = ""
    target_id: str = ""
    owner_id: str = ""
    summoner_id: str = ""
    action_id: str = ""
    action_level: int | None = None
    skill_level: int | None = None
    data_card_level: int | None = None
    hit_id: str = ""
    hit_index: int | None = None
    status_id: str = ""
    modifier_name: str = ""
    event_payload: dict[str, JSONValue] | None = None
    combatant_profile_id: str = ""
    data_card_id: str = ""
    data_card_kind: str = ""
    dynamic_values: dict[str, float] | None = None
    binding_sources: tuple[dict[str, Any], ...] = ()
    source_trace: dict[str, JSONValue] = field(default_factory=dict)

    def to_static_context(self) -> StaticValueBindingContext:
        return StaticValueBindingContext(
            action_id=self.action_id,
            action_level=self.action_level,
            skill_level=self.skill_level,
            data_card_level=self.data_card_level,
            actor_id=self.actor_id,
            target_id=self.target_id,
            owner_id=self.owner_id,
            summoner_id=self.summoner_id,
            data_card_id=self.data_card_id,
            data_card_kind=self.data_card_kind,
            source_trace=self.source_trace,
        )

    def available_keys(self) -> tuple[str, ...]:
        keys: list[str] = []
        if self.actor_id:
            keys.append("actor")
        if self.target_id:
            keys.append("target")
        if self.owner_id:
            keys.append("owner")
        if self.summoner_id:
            keys.append("summoner")
        if self.action_id:
            keys.append("action")
        if self.hit_id or self.hit_index is not None:
            keys.append("hit")
        if self.status_id or self.modifier_name:
            keys.append("status_modifier")
        if self.event_payload is not None:
            keys.append("event_payload")
        if self.combatant_profile_id:
            keys.append("combatant_profile")
        if self.data_card_id or self.data_card_kind:
            keys.append("data_card_source")
        if self.dynamic_values is not None or self.binding_sources:
            keys.append("dynamic_value_source")
        return tuple(keys)

    def has_key(self, key: str) -> bool:
        return key in self.available_keys()

    def to_trace(self) -> dict[str, JSONValue]:
        return {
            **self.to_static_context().to_trace(),
            "hit_id": self.hit_id,
            "hit_index": self.hit_index,
            "status_id": self.status_id,
            "modifier_name": self.modifier_name,
            "event_payload_keys": sorted((self.event_payload or {}).keys()) if self.event_payload is not None else [],
            "combatant_profile_id": self.combatant_profile_id,
            "available_keys": list(self.available_keys()),
            "dynamic_value_key_count": len(self.dynamic_values or {}),
            "binding_source_count": len(self.binding_sources),
        }


@dataclass(frozen=True)
class ValueBindingRequest:
    binding_kind: str
    binding_id: str = ""
    param_index: int | None = None
    formula_role: str = ""
    field_name: str = ""
    expression: JSONValue = None
    required_context_keys: tuple[str, ...] = ()
    source_trace: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True)
class ValueResolution:
    ok: bool
    value: float | None
    binding_kind: str
    source_trace: dict[str, JSONValue]
    context_trace: dict[str, JSONValue]
    blocked_reason: str = ""
    request: dict[str, JSONValue] = field(default_factory=dict)
    delegate_resolution: dict[str, JSONValue] = field(default_factory=dict)
    context_keys: tuple[str, ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "value": self.value,
            "binding_kind": self.binding_kind,
            "source_trace": self.source_trace,
            "context_trace": self.context_trace,
            "blocked_reason": self.blocked_reason,
            "request": self.request,
            "delegate_resolution": self.delegate_resolution,
            "context_keys": list(self.context_keys),
        }


@dataclass(frozen=True)
class StaticValueResolution:
    ok: bool
    value: float | None
    binding_kind: str
    source_trace: dict[str, JSONValue]
    context_trace: dict[str, JSONValue]
    blocked_reason: str = ""
    binding_id: str = ""
    action_id: str = ""
    level: int | None = None
    level_source: str = ""
    param_index: int | None = None
    formula_role: str = ""
    field_name: str = ""
    candidate_ids: tuple[str, ...] = ()
    value_source: str = ""
    raw_value: JSONValue = None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "value": self.value,
            "binding_kind": self.binding_kind,
            "binding_id": self.binding_id,
            "action_id": self.action_id,
            "level": self.level,
            "level_source": self.level_source,
            "param_index": self.param_index,
            "formula_role": self.formula_role,
            "field_name": self.field_name,
            "candidate_ids": list(self.candidate_ids),
            "value_source": self.value_source,
            "raw_value": self.raw_value,
            "source_trace": self.source_trace,
            "context_trace": self.context_trace,
            "blocked_reason": self.blocked_reason,
        }


class StaticValueBindingResolver:
    """Source-backed static value resolver for P5-S2.

    This resolver only admits values already projected into Canonical IR and
    RuleBook. It never reads raw TBGD and never supplies missing numeric
    defaults.
    """

    def __init__(self, rules: RuleBook) -> None:
        self.rules = rules

    def resolve_skill_formula_param(
        self,
        context: StaticValueBindingContext,
        *,
        param_index: int | None,
        formula_role: str,
        binding_id: str = "",
    ) -> StaticValueResolution:
        level, level_source = context.level_with_source()
        blocked = self._blocked_factory(
            "skill_formula_param",
            context,
            action_id=context.action_id,
            level=level,
            level_source=level_source,
            param_index=param_index,
            formula_role=formula_role,
            binding_id=binding_id,
        )
        if not context.action_id:
            return blocked("action_id_missing")
        if level is None:
            return blocked("level_missing")
        if param_index is None:
            return blocked("param_index_missing")
        if not isinstance(param_index, int) or isinstance(param_index, bool) or param_index < 0:
            return blocked("param_index_invalid")
        if not formula_role:
            return blocked("formula_role_missing")

        if binding_id:
            binding = self.rules.skill_formula_binding(binding_id)
            if binding is None:
                return blocked("binding_missing")
            if (
                binding.action_id != context.action_id
                or binding.level != level
                or binding.param_index != param_index
                or binding.formula_role != formula_role
            ):
                return blocked(
                    "binding_context_mismatch",
                    candidate_ids=(binding.binding_id,),
                    source_trace=_source_trace(binding),
                )
            candidates = (binding,)
        else:
            candidates = self.rules.skill_formula_bindings_for_action_param(
                context.action_id,
                level,
                param_index,
                formula_role,
            )
            if not candidates:
                return blocked("binding_missing")
            executable_candidates = tuple(item for item in candidates if item.coverage_status == "executable")
            if len(executable_candidates) != 1:
                reason = "binding_ambiguous" if executable_candidates else "binding_not_executable"
                return blocked(reason, candidate_ids=tuple(item.binding_id for item in candidates))
            candidates = executable_candidates

        binding = candidates[0]
        if binding.coverage_status != "executable":
            return blocked(
                f"binding_not_executable:{binding.coverage_status}",
                candidate_ids=(binding.binding_id,),
                source_trace=_source_trace(binding),
            )
        value = _numeric_json_value(binding.param_value)
        if value is None:
            return blocked(
                "param_value_not_numeric",
                candidate_ids=(binding.binding_id,),
                source_trace=_source_trace(binding),
            )
        return StaticValueResolution(
            ok=True,
            value=value,
            binding_kind="skill_formula_param",
            binding_id=binding.binding_id,
            action_id=context.action_id,
            level=level,
            level_source=level_source,
            param_index=param_index,
            formula_role=formula_role,
            field_name="param_value",
            candidate_ids=tuple(item.binding_id for item in candidates),
            value_source="SkillFormulaBindingIR.param_value",
            raw_value=_json_safe(binding.param_value),
            source_trace=_source_trace(binding),
            context_trace=context.to_trace(),
        )

    def resolve_action_definition_numeric_field(
        self,
        context: StaticValueBindingContext,
        *,
        field_name: str,
    ) -> StaticValueResolution:
        level, level_source = context.level_with_source()
        blocked = self._blocked_factory(
            "action_definition_numeric_field",
            context,
            action_id=context.action_id,
            level=level,
            level_source=level_source,
            field_name=field_name,
        )
        if field_name not in ACTION_DEFINITION_NUMERIC_FIELDS:
            return blocked("unsupported_action_definition_field")
        definition = self._action_definition(context, level, blocked)
        if isinstance(definition, StaticValueResolution):
            return definition
        value = _numeric_json_value(getattr(definition, field_name))
        if value is None:
            return blocked("field_value_not_numeric", source_trace=_source_trace(definition))
        return StaticValueResolution(
            ok=True,
            value=value,
            binding_kind="action_definition_numeric_field",
            binding_id=definition.definition_id,
            action_id=context.action_id,
            level=level,
            level_source=level_source,
            field_name=field_name,
            value_source=f"ActionDefinitionIR.{field_name}",
            raw_value=_json_safe(getattr(definition, field_name)),
            source_trace=_source_trace(definition),
            context_trace=context.to_trace(),
        )

    def resolve_action_definition_list_item(
        self,
        context: StaticValueBindingContext,
        *,
        field_name: str,
        param_index: int | None,
    ) -> StaticValueResolution:
        level, level_source = context.level_with_source()
        blocked = self._blocked_factory(
            "action_definition_list_item",
            context,
            action_id=context.action_id,
            level=level,
            level_source=level_source,
            param_index=param_index,
            field_name=field_name,
        )
        if field_name not in ACTION_DEFINITION_LIST_FIELDS:
            return blocked("unsupported_action_definition_list")
        if param_index is None:
            return blocked("param_index_missing")
        if not isinstance(param_index, int) or isinstance(param_index, bool) or param_index < 0:
            return blocked("param_index_invalid")
        definition = self._action_definition(context, level, blocked)
        if isinstance(definition, StaticValueResolution):
            return definition
        values = getattr(definition, field_name)
        if param_index >= len(values):
            return blocked("param_index_out_of_range", source_trace=_source_trace(definition))
        raw_value = values[param_index]
        value = _numeric_json_value(raw_value)
        if value is None:
            return blocked("field_value_not_numeric", source_trace=_source_trace(definition))
        return StaticValueResolution(
            ok=True,
            value=value,
            binding_kind="action_definition_list_item",
            binding_id=definition.definition_id,
            action_id=context.action_id,
            level=level,
            level_source=level_source,
            param_index=param_index,
            field_name=field_name,
            value_source=f"ActionDefinitionIR.{field_name}[{param_index}]",
            raw_value=_json_safe(raw_value),
            source_trace=_source_trace(definition),
            context_trace=context.to_trace(),
        )

    def resolve_fixed_numeric_expression(
        self,
        expression: Any,
        context: StaticValueBindingContext,
        *,
        source_trace: dict[str, JSONValue] | None = None,
    ) -> StaticValueResolution:
        trace = source_trace or context.source_trace
        value = _static_expression_value(expression)
        if value is None:
            return StaticValueResolution(
                ok=False,
                value=None,
                binding_kind="fixed_numeric_expression",
                action_id=context.action_id,
                source_trace=trace,
                context_trace=context.to_trace(),
                blocked_reason="unsupported_static_numeric_expression",
                raw_value=_json_safe(expression),
            )
        return StaticValueResolution(
            ok=True,
            value=value,
            binding_kind="fixed_numeric_expression",
            action_id=context.action_id,
            value_source="static_numeric_expression",
            raw_value=_json_safe(expression),
            source_trace=trace,
            context_trace=context.to_trace(),
        )

    def _action_definition(
        self,
        context: StaticValueBindingContext,
        level: int | None,
        blocked: Any,
    ) -> Any:
        if not context.action_id:
            return blocked("action_id_missing")
        if level is None:
            return blocked("level_missing")
        definition = self.rules.action_definition(context.action_id, level)
        if definition is None:
            return blocked("action_definition_missing")
        if definition.coverage_status != "executable":
            return blocked(
                f"action_definition_not_executable:{definition.coverage_status}",
                source_trace=_source_trace(definition),
            )
        return definition

    def _blocked_factory(
        self,
        binding_kind: str,
        context: StaticValueBindingContext,
        *,
        action_id: str = "",
        level: int | None = None,
        level_source: str = "",
        param_index: int | None = None,
        formula_role: str = "",
        field_name: str = "",
        binding_id: str = "",
    ) -> Any:
        def blocked(
            reason: str,
            *,
            candidate_ids: tuple[str, ...] = (),
            source_trace: dict[str, JSONValue] | None = None,
        ) -> StaticValueResolution:
            return StaticValueResolution(
                ok=False,
                value=None,
                binding_kind=binding_kind,
                binding_id=binding_id,
                action_id=action_id,
                level=level,
                level_source=level_source,
                param_index=param_index,
                formula_role=formula_role,
                field_name=field_name,
                candidate_ids=candidate_ids,
                source_trace=source_trace or context.source_trace,
                context_trace=context.to_trace(),
                blocked_reason=reason,
            )

        return blocked


class ValueResolver:
    SUPPORTED_BINDING_KINDS = frozenset(
        {
            "skill_formula_param",
            "action_definition_numeric_field",
            "action_definition_list_item",
            "fixed_numeric_expression",
            "dynamic_hash",
            "runtime_numeric_expression",
            "combatant_profile_base_stat",
        }
    )

    def __init__(self, rules: RuleBook) -> None:
        self.rules = rules
        self.static_resolver = StaticValueBindingResolver(rules)
        self.numeric_evaluator = RuleEvaluator()

    def resolve(self, request: ValueBindingRequest, context: ValueContext) -> ValueResolution:
        missing_context = tuple(key for key in request.required_context_keys if not context.has_key(key))
        if request.binding_kind not in self.SUPPORTED_BINDING_KINDS:
            return self._blocked(request, context, f"unknown_binding_kind:{request.binding_kind}")
        if missing_context:
            return self._blocked(
                request,
                context,
                "context_missing:" + ",".join(missing_context),
            )
        if request.binding_kind == "skill_formula_param":
            result = self.static_resolver.resolve_skill_formula_param(
                context.to_static_context(),
                param_index=request.param_index,
                formula_role=request.formula_role,
                binding_id=request.binding_id,
            )
            return self._from_static(request, context, result)
        if request.binding_kind == "action_definition_numeric_field":
            result = self.static_resolver.resolve_action_definition_numeric_field(
                context.to_static_context(),
                field_name=request.field_name,
            )
            return self._from_static(request, context, result)
        if request.binding_kind == "action_definition_list_item":
            result = self.static_resolver.resolve_action_definition_list_item(
                context.to_static_context(),
                field_name=request.field_name,
                param_index=request.param_index,
            )
            return self._from_static(request, context, result)
        if request.binding_kind == "combatant_profile_base_stat":
            result = self._resolve_combatant_profile_base_stat(request, context)
            return result
        if request.binding_kind == "fixed_numeric_expression":
            result = self.static_resolver.resolve_fixed_numeric_expression(
                request.expression,
                context.to_static_context(),
                source_trace=request.source_trace or context.source_trace,
            )
            return self._from_static(request, context, result)
        if request.binding_kind == "dynamic_hash":
            return self._resolve_dynamic_hash(request, context)
        return self._resolve_runtime_numeric_expression(request, context)

    def _resolve_combatant_profile_base_stat(
        self,
        request: ValueBindingRequest,
        context: ValueContext,
    ) -> ValueResolution:
        if not context.combatant_profile_id:
            return self._blocked(request, context, "combatant_profile_id_missing")
        profile = self.rules.combatant_profile_by_profile_id(context.combatant_profile_id)
        if profile is None:
            return self._blocked(request, context, "combatant_profile_missing")
        if profile.coverage_status != "executable":
            return self._blocked(
                request,
                context,
                f"combatant_profile_not_executable:{profile.coverage_status}",
                source_trace=_source_trace(profile),
            )
        value = _numeric_json_value(profile.base_stats.get(request.field_name))
        if value is None:
            return self._blocked(
                request,
                context,
                "combatant_profile_base_stat_not_numeric",
                source_trace=_source_trace(profile),
            )
        return ValueResolution(
            ok=True,
            value=value,
            binding_kind=request.binding_kind,
            source_trace=_source_trace(profile),
            context_trace=context.to_trace(),
            request=_request_json(request),
            delegate_resolution={
                "ok": True,
                "value": value,
                "binding_kind": request.binding_kind,
                "binding_id": profile.profile_id,
                "field_name": request.field_name,
                "value_source": f"CombatantProfileIR.base_stats.{request.field_name}",
                "source_trace": _source_trace(profile),
            },
            context_keys=context.available_keys(),
        )

    def _resolve_dynamic_hash(self, request: ValueBindingRequest, context: ValueContext) -> ValueResolution:
        if context.dynamic_values is None and not context.binding_sources:
            return self._blocked(request, context, "dynamic_value_source_missing")
        expression = request.expression
        if not isinstance(expression, dict) or expression.get("hash") is None:
            return self._blocked(request, context, "dynamic_hash_payload_missing")
        result = self.numeric_evaluator.evaluate_numeric(
            numeric_dynamic_hash(expression.get("hash")),
            NumericEvaluationContext(
                dynamic_values=context.dynamic_values or {},
                binding_sources=context.binding_sources,
                source_trace=request.source_trace or context.source_trace,
            ),
        )
        if not result.ok:
            return self._blocked(
                request,
                context,
                result.blocked_reason or "dynamic_hash_unresolved",
                source_trace=result.source_trace,
                delegate_resolution=result.to_json(),
            )
        return ValueResolution(
            ok=True,
            value=result.value,
            binding_kind=request.binding_kind,
            source_trace=result.source_trace,
            context_trace=context.to_trace(),
            request=_request_json(request),
            delegate_resolution=result.to_json(),
            context_keys=context.available_keys(),
        )

    def _resolve_runtime_numeric_expression(
        self,
        request: ValueBindingRequest,
        context: ValueContext,
    ) -> ValueResolution:
        result = self.numeric_evaluator.evaluate_numeric(
            request.expression,
            NumericEvaluationContext(
                dynamic_values=context.dynamic_values or {},
                binding_sources=context.binding_sources,
                source_trace=request.source_trace or context.source_trace,
            ),
        )
        if not result.ok or result.value is None:
            return self._blocked(
                request,
                context,
                result.blocked_reason or "runtime_numeric_expression_unresolved",
                source_trace=result.source_trace,
                delegate_resolution=result.to_json(),
            )
        return ValueResolution(
            ok=True,
            value=result.value,
            binding_kind=request.binding_kind,
            source_trace=result.source_trace,
            context_trace=context.to_trace(),
            request=_request_json(request),
            delegate_resolution=result.to_json(),
            context_keys=context.available_keys(),
        )

    def _from_static(
        self,
        request: ValueBindingRequest,
        context: ValueContext,
        result: StaticValueResolution,
    ) -> ValueResolution:
        if not result.ok:
            return self._blocked(
                request,
                context,
                result.blocked_reason or "static_resolution_blocked",
                source_trace=result.source_trace,
                delegate_resolution=result.to_json(),
            )
        return ValueResolution(
            ok=True,
            value=result.value,
            binding_kind=request.binding_kind,
            source_trace=result.source_trace,
            context_trace=context.to_trace(),
            request=_request_json(request),
            delegate_resolution=result.to_json(),
            context_keys=context.available_keys(),
        )

    def _blocked(
        self,
        request: ValueBindingRequest,
        context: ValueContext,
        reason: str,
        *,
        source_trace: dict[str, JSONValue] | None = None,
        delegate_resolution: dict[str, JSONValue] | None = None,
    ) -> ValueResolution:
        return ValueResolution(
            ok=False,
            value=None,
            binding_kind=request.binding_kind,
            source_trace=source_trace or request.source_trace or context.source_trace,
            context_trace=context.to_trace(),
            blocked_reason=reason,
            request=_request_json(request),
            delegate_resolution=delegate_resolution or {},
            context_keys=context.available_keys(),
        )


def _numeric_json_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        return _numeric_json_value(value.get("Value"))
    return None


def _static_expression_value(expression: Any) -> float | None:
    return numeric_fixed_value(expression)


def _source_trace(item: Any) -> dict[str, JSONValue]:
    source = getattr(item, "source", None)
    if source is None:
        return {}
    try:
        trace = source.to_json()
    except AttributeError:
        return {}
    return trace if isinstance(trace, dict) else {}


def _json_safe(value: Any) -> JSONValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def _request_json(request: ValueBindingRequest) -> dict[str, JSONValue]:
    return {
        "binding_kind": request.binding_kind,
        "binding_id": request.binding_id,
        "param_index": request.param_index,
        "formula_role": request.formula_role,
        "field_name": request.field_name,
        "expression": _json_safe(request.expression),
        "required_context_keys": list(request.required_context_keys),
        "source_trace": request.source_trace,
    }
