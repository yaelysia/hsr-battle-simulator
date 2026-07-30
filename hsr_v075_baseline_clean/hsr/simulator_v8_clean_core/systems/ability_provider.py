from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from ..core.model import BattleState, JSONValue, Mutation
from ..core.reducer import MutationReducer
from ..equipment.models import DynamicMechanismSelection, EquipmentDefinitionKey
from ..rules.rulebook import RuleBook


@dataclass(frozen=True)
class AbilityProviderRegistrationResult:
    ok: bool
    before_state: BattleState
    after_state: BattleState
    mutations: tuple[Mutation, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    blocked_reason: str = ""

    @property
    def state_unchanged(self) -> bool:
        return self.before_state == self.after_state


def register_dynamic_ability_providers(
    state: BattleState,
    rules: RuleBook,
    selections: tuple[tuple[str, DynamicMechanismSelection], ...],
) -> AbilityProviderRegistrationResult:
    """Atomically register admitted graph providers after UnitState creation.

    This is a generic graph-reference registry.  It does not interpret equipment
    payloads or execute callbacks; later event dispatch only sees canonical graph
    and parameter-read identities recorded here.
    """

    if not isinstance(state, BattleState):
        raise TypeError("state must be BattleState")
    if not isinstance(rules, RuleBook):
        raise TypeError("rules must be RuleBook")
    if not isinstance(selections, tuple):
        raise TypeError("selections must be a tuple")

    providers_by_unit: dict[str, dict[str, dict[str, JSONValue]]] = {}
    records: list[dict[str, JSONValue]] = []
    for item in selections:
        if (
            not isinstance(item, tuple)
            or len(item) != 2
            or not isinstance(item[0], str)
            or not isinstance(item[1], DynamicMechanismSelection)
        ):
            return _blocked(state, "ability_provider_selection_type_invalid")
        unit_id, selection = item
        unit = state.units.get(unit_id)
        if unit is None:
            return _blocked(state, "ability_provider_owner_unit_missing")
        if (
            selection.coverage_status != "executable"
            or selection.blocked_reason
        ):
            return _blocked(state, "ability_provider_selection_not_executable")
        if unit.flags.get("character_data_card_id") != selection.wearer_character_card_id:
            return _blocked(state, "ability_provider_wearer_identity_mismatch")
        graph = rules.standalone_ability_graph(selection.graph_ref_id)
        if (
            graph is None
            or graph.coverage_status != "executable"
            or graph.source != selection.source
        ):
            return _blocked(state, "ability_provider_graph_missing_partial_or_wrong_source")
        parameter_context, context_reason = (
            rules.equipment_dynamic_parameter_context(
                selection.target_definition_key,
                selection.parameter_basis,
            )
        )
        if (
            parameter_context is None
            or parameter_context.mechanism_ref.definition_key
            != selection.mechanism_key
            or parameter_context.graph.standalone_ability_graph_id
            != selection.graph_ref_id
            or parameter_context.graph.source != selection.source
        ):
            return _blocked(
                state,
                context_reason
                or "ability_provider_target_definition_mismatch",
            )
        mechanism = parameter_context.mechanism_ref
        selected_read_ids = tuple(
            binding.parameter_read_id for binding in selection.parameter_bindings
        )
        if selected_read_ids != mechanism.parameter_binding_ids:
            return _blocked(state, "ability_provider_parameter_read_set_mismatch")
        for binding in selection.parameter_bindings:
            parameter_read = rules.equipment_ability_parameter_read(
                binding.parameter_read_id
            )
            if (
                parameter_read is None
                or parameter_read.graph_ref_id != selection.graph_ref_id
                or parameter_read.value_type != binding.value_type
                or parameter_read.dynamic_hash != binding.dynamic_hash
                or parameter_read.parameter_index != binding.parameter_index
                or parameter_read.source != binding.read_source
                or not rules.equipment_parameter_read_matches_basis(
                    parameter_read,
                    selection.parameter_basis,
                )
            ):
                return _blocked(state, "ability_provider_parameter_binding_mismatch")
            if parameter_read.parameter_index >= len(
                parameter_context.parameters
            ):
                return _blocked(state, "ability_provider_parameter_index_out_of_range")
            parameter = parameter_context.parameters[
                parameter_read.parameter_index
            ]
            if (
                binding.exact_value != parameter.exact_value
                or binding.value_source != parameter.source
            ):
                return _blocked(state, "ability_provider_parameter_value_source_mismatch")

        semantic_key = _provider_semantic_key(
            unit_id,
            selection.provider_source_id,
            selection.mechanism_key,
        )
        provider_id = _provider_id(semantic_key)
        provider = {
            "provider_id": provider_id,
            "provider_kind": "canonical_ability_graph",
            "semantic_key": semantic_key,
            "selection_id": selection.selection_id,
            "owner_unit_id": unit_id,
            "provider_source_id": selection.provider_source_id,
            "target_definition_key": selection.target_definition_key.to_json(),
            "parameter_basis": selection.parameter_basis.to_json(),
            "mechanism_key": selection.mechanism_key.to_json(),
            "graph_ref_id": selection.graph_ref_id,
            "parameter_bindings": [
                binding.to_json() for binding in selection.parameter_bindings
            ],
            "source": selection.source.to_json(),
        }
        unit_providers = providers_by_unit.setdefault(unit_id, {})
        prior = unit_providers.get(provider_id)
        if prior is not None:
            return _blocked(state, "ability_provider_request_semantic_duplicate")
        unit_providers[provider_id] = provider

    mutations: list[Mutation] = []
    for unit_id, requested_by_id in sorted(providers_by_unit.items()):
        unit = state.units[unit_id]
        raw_existing = unit.flags.get("ability_providers", [])
        if not isinstance(raw_existing, (list, tuple)) or not all(
            isinstance(item, dict) for item in raw_existing
        ):
            return _blocked(state, "ability_provider_registry_invalid")
        existing_by_id: dict[str, dict[str, JSONValue]] = {}
        for raw_provider in raw_existing:
            provider_id = raw_provider.get("provider_id")
            if not isinstance(provider_id, str) or not provider_id:
                return _blocked(state, "ability_provider_registry_identity_invalid")
            provider = dict(raw_provider)
            expected_provider_id = _existing_provider_id(unit_id, provider)
            if expected_provider_id is None or provider_id != expected_provider_id:
                return _blocked(state, "ability_provider_registry_semantic_identity_invalid")
            prior = existing_by_id.get(provider_id)
            if prior is not None:
                return _blocked(state, "ability_provider_registry_semantic_duplicate")
            existing_by_id[provider_id] = provider
        for provider_id, provider in requested_by_id.items():
            existing = existing_by_id.get(provider_id)
            if existing is not None and existing != provider:
                return _blocked(state, "ability_provider_existing_identity_conflict")
            existing_by_id[provider_id] = provider
        after = [existing_by_id[key] for key in sorted(existing_by_id)]
        before = [dict(item) for item in raw_existing]
        if before == after:
            records.extend(
                _provider_registration_record(
                    status="already_registered",
                    unit_id=unit_id,
                    provider_id=provider_id,
                    provider=requested_by_id[provider_id],
                    mutation_id=None,
                )
                for provider_id in sorted(requested_by_id)
            )
            continue
        mutation = Mutation(
            op="set",
            path=("units", unit_id, "flags", "ability_providers"),
            before=before if "ability_providers" in unit.flags else None,
            before_exists="ability_providers" in unit.flags,
            after=after,
            reason="register_canonical_ability_provider",
            source="ability_provider_registry",
            metadata={
                "provider_ids": sorted(requested_by_id),
                "owner_unit_id": unit_id,
                "providers": [
                    requested_by_id[provider_id]
                    for provider_id in sorted(requested_by_id)
                ],
                "source_trace": {
                    "provider_sources": [
                        requested_by_id[provider_id]["source"]
                        for provider_id in sorted(requested_by_id)
                    ],
                },
            },
        )
        mutations.append(mutation)
        records.extend(
            _provider_registration_record(
                status="registered",
                unit_id=unit_id,
                provider_id=provider_id,
                provider=requested_by_id[provider_id],
                mutation_id=mutation.stable_id(),
            )
            for provider_id in sorted(requested_by_id)
        )

    reduction = MutationReducer().apply_all_result(state, tuple(mutations))
    if not reduction.ok:
        return _blocked(state, "ability_provider_atomic_reduction_failed")
    return AbilityProviderRegistrationResult(
        ok=True,
        before_state=state,
        after_state=reduction.after_state,
        mutations=tuple(mutations),
        records=tuple(records),
    )


def _provider_registration_record(
    *,
    status: str,
    unit_id: str,
    provider_id: str,
    provider: dict[str, JSONValue],
    mutation_id: str | None,
) -> dict[str, JSONValue]:
    bindings = provider["parameter_bindings"]
    if not isinstance(bindings, list):
        raise TypeError("canonical provider parameter bindings must be a list")
    return {
        "record_type": "ability_provider_registration",
        "source": "ability_provider_registry",
        "mutation_id": mutation_id,
        "process_only": mutation_id is None,
        "status": status,
        "unit_id": unit_id,
        "provider_id": provider_id,
        "semantic_key": provider["semantic_key"],
        "selection_id": provider["selection_id"],
        "graph_ref_id": provider["graph_ref_id"],
        "parameter_binding_ids": [
            binding["parameter_read_id"]
            for binding in bindings
            if isinstance(binding, dict)
        ],
        "source": provider["source"],
    }


def _provider_semantic_key(
    unit_id: str,
    provider_source_id: str,
    mechanism_key: EquipmentDefinitionKey,
) -> dict[str, JSONValue]:
    return {
        "owner_unit_id": unit_id,
        "provider_source_id": provider_source_id,
        "mechanism_key": mechanism_key.to_json(),
    }


def _provider_id(semantic_key: dict[str, JSONValue]) -> str:
    encoded = json.dumps(
        semantic_key,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"ability_provider:{hashlib.sha256(encoded).hexdigest()}"


def _existing_provider_id(
    unit_id: str,
    provider: dict[str, JSONValue],
) -> str | None:
    if (
        provider.get("provider_kind") != "canonical_ability_graph"
        or provider.get("owner_unit_id") != unit_id
        or not isinstance(provider.get("provider_source_id"), str)
        or not provider.get("provider_source_id")
        or not isinstance(provider.get("selection_id"), str)
        or not provider.get("selection_id")
    ):
        return None
    try:
        mechanism_key = EquipmentDefinitionKey.from_json(provider.get("mechanism_key"))
    except (TypeError, ValueError):
        return None
    if mechanism_key.definition_kind != "equipment_mechanism":
        return None
    semantic_key = _provider_semantic_key(
        unit_id,
        provider["provider_source_id"],
        mechanism_key,
    )
    if provider.get("semantic_key") != semantic_key:
        return None
    return _provider_id(semantic_key)


def _blocked(state: BattleState, reason: str) -> AbilityProviderRegistrationResult:
    return AbilityProviderRegistrationResult(
        ok=False,
        before_state=state,
        after_state=state,
        blocked_reason=reason,
        records=(
            {
                "record_type": "ability_provider_registration",
                "status": "blocked",
                "blocked_reason": reason,
            },
        ),
    )
