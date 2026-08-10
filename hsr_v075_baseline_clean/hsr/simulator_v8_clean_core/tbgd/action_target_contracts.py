from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from ..ir_types import IRSource, JSONValue
from ..rules.action_target_contract import (
    ActionTargetContractCatalogIR,
    ActionTargetContractIR,
    ActionTargetSourceComponentIR,
)
from ..rules.ir import (
    ActionDefinitionIR,
    CharacterAbilitySourceGraphCatalogIR,
    CharacterActionSourceIR,
    TargetExpressionIR,
)
from .character_ability_scope import CharacterAbilityRawSnapshot


_TARGET_TYPE_SELECTION = {
    "Caster": ("automatic", "self", 0, 0),
    "EnemySelect": ("explicit", "enemy", 1, 1),
    "FriendSelect": ("explicit", "ally_or_self", 1, 1),
    "AllEnemy": ("automatic", "enemy", 0, 0),
    "AllTeamMember": ("automatic", "ally_or_self", 0, 0),
}

_SUB_TARGET_DECODING = {
    "TargetAdjoinEntity": "adjacent_effect_targets",
    "TargetAllTeammate": "all_teammate_effect_targets",
    "TargetServantOrSummoner": "servant_or_summoner_selection",
}

_TARGET_INFO_FIELDS = {
    "TargetType": ("target_type", "action_selection"),
    "SubTargetType": ("sub_target_type", None),
    "AliveState": ("alive_state", "action_selection"),
    "TargetFilter": ("target_filter", "action_selection"),
    "AllowFriendServant": ("allow_friend_servant", "action_selection"),
    "AllowEnemyServant": ("allow_enemy_servant", "action_selection"),
    "MergeServantSelectToSummoner": (
        "merge_servant_select_to_summoner",
        "action_selection",
    ),
    "AvoidSelf": ("avoid_self", "action_selection"),
    "IsDynamicTarget": ("is_dynamic_target", "effect_shape"),
    "AdjoinSubTargetCount": ("adjoin_sub_target_count", "effect_shape"),
    "MaxTargetCount": ("max_target_count", "action_selection"),
    "InvalidTargetMessage": ("invalid_target_message", "non_gameplay"),
    "InvalidTargetMessageIcon": ("invalid_target_message_icon", "non_gameplay"),
}


@dataclass(frozen=True)
class _TargetInfoProjection:
    shape: tuple[str, str, int, int] | None
    semantic_signature: str
    components: tuple[ActionTargetSourceComponentIR, ...]
    candidate_alive_state: str = "alive_only"
    friend_servant_policy: str = "default"
    enemy_servant_policy: str = "default"
    servant_selection: str = "none"
    merge_servant_selection_to_summoner: bool = False
    avoid_self: bool = False
    selection_filter: TargetExpressionIR | None = None
    impact_sub_target: str = "default"
    adjacent_target_count: int | None = None
    dynamic_target: bool = False
    blocked_reason: str = ""


class _TargetExpressionCompiler:
    def __init__(self, root: Path, snapshot: CharacterAbilityRawSnapshot):
        self.root = root
        self.snapshot = snapshot
        self._definitions: tuple[Any, ...] | None = None

    def compile(
        self,
        raw: Mapping[str, Any],
        *,
        expression_id: str,
        source: IRSource,
    ) -> TargetExpressionIR | None:
        # Local imports avoid coupling the shared target-language module back to
        # this catalog while lowering.py is being initialized.
        from .lowering import _target_expression_from_raw
        from .target_source import (
            build_target_language_definitions,
            close_target_expression_language,
        )

        if self._definitions is None:
            self._definitions = build_target_language_definitions(
                self.root,
                snapshot=self.snapshot,
            )
        expression = _target_expression_from_raw(
            dict(raw),
            field_name="$self",
            expression_id=expression_id,
            source=source,
        )
        if expression is None:
            return None
        return replace(
            close_target_expression_language(expression, self._definitions),
            runtime_scope="action_selection",
        )


class _SourceReader:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self._cache: dict[str, tuple[Any, str]] = {}

    def read(self, relative_path: str) -> tuple[Any, str]:
        cached = self._cache.get(relative_path)
        if cached is not None:
            return cached
        path = (self.root / relative_path).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("action target source path escapes TBGD root") from exc
        raw = path.read_bytes()
        value = json.loads(raw)
        result = (value, sha256(raw).hexdigest())
        self._cache[relative_path] = result
        return result

    @property
    def read_count(self) -> int:
        return len(self._cache)


def build_action_target_contract_catalog(
    tbgd_root: Path,
    *,
    definitions: tuple[ActionDefinitionIR, ...] | list[ActionDefinitionIR],
    snapshot: CharacterAbilityRawSnapshot,
    source_graph_catalog: CharacterAbilitySourceGraphCatalogIR,
    definition_scope_complete: bool,
) -> ActionTargetContractCatalogIR:
    if type(snapshot) is not CharacterAbilityRawSnapshot:
        raise TypeError("action target projection requires the exact S0 snapshot")
    if type(source_graph_catalog) is not CharacterAbilitySourceGraphCatalogIR:
        raise TypeError("action target projection requires the exact S1 source graph")
    if source_graph_catalog.snapshot_id != snapshot.snapshot_id:
        raise ValueError("action target snapshot and source graph do not close")
    if type(definition_scope_complete) is not bool:
        raise TypeError("action target definition scope flag must be boolean")
    definition_values = tuple(definitions)
    if any(type(item) is not ActionDefinitionIR for item in definition_values):
        raise TypeError("action target projection definitions are invalid")
    keys = tuple((item.action_id, item.level) for item in definition_values)
    if len(keys) != len(set(keys)):
        raise ValueError("action target projection definitions contain duplicate keys")

    reader = _SourceReader(tbgd_root)
    expression_compiler = _TargetExpressionCompiler(tbgd_root.resolve(), snapshot)
    action_sources_by_key: dict[tuple[str, int], list[CharacterActionSourceIR]] = defaultdict(list)
    character_source_level_keys: list[str] = []
    for source in source_graph_catalog.action_sources:
        for level in source.levels:
            action_sources_by_key[(source.action_id, level)].append(source)
            character_source_level_keys.append(
                _character_source_level_key(source.action_source_id, source.action_id, level)
            )

    contracts = tuple(
        _contract_from_definition(
            definition,
            action_sources=tuple(
                action_sources_by_key.get((definition.action_id, definition.level), ())
            ),
            reader=reader,
            expression_compiler=expression_compiler,
        )
        for definition in definition_values
    )
    return ActionTargetContractCatalogIR(
        definition_scope="complete" if definition_scope_complete else "partial",
        source_graph_catalog_id=source_graph_catalog.catalog_id,
        source_graph_fingerprint=source_graph_catalog.source_fingerprint,
        character_source_level_keys=tuple(character_source_level_keys),
        contracts=contracts,
        build_counters={
            "action_definition_count": len(definition_values),
            "contract_count": len(contracts),
            "character_source_level_count": len(character_source_level_keys),
            "source_document_read_count": reader.read_count,
            "generic_record_limit_applied": not definition_scope_complete,
            "full_canonical_ir_build_count": 0,
            "runtime_consumer_count": 0,
        },
    )


def _contract_from_definition(
    definition: ActionDefinitionIR,
    *,
    action_sources: tuple[CharacterActionSourceIR, ...],
    reader: _SourceReader,
    expression_compiler: _TargetExpressionCompiler,
) -> ActionTargetContractIR:
    components: list[ActionTargetSourceComponentIR] = []
    table_component = _action_table_component(definition, reader)
    if table_component is not None:
        components.append(table_component)

    selections: list[_TargetInfoProjection] = []
    source_ids = tuple(source.action_source_id for source in action_sources)
    source_issue = ""
    gap_owner = "source_gap"

    if definition.action_id.startswith("avatar_skill:"):
        if not action_sources:
            source_issue = "action_outside_current_character_source_scope"
            gap_owner = "source_scope"
        elif len(action_sources) != 1:
            source_issue = "character_action_selection_source_ambiguous"
        else:
            selection = _character_selection(
                action_sources[0], definition, reader, expression_compiler
            )
            if selection is None:
                source_issue = "character_action_selection_source_missing"
            else:
                selections.append(selection)
    elif definition.action_id.startswith("monster_skill:"):
        selections.extend(
            _embedded_selections(
                definition,
                source_key="monster_target_source",
                source_role="monster_config",
                reader=reader,
                expression_compiler=expression_compiler,
            )
        )
        if not selections:
            source_issue = "monster_action_selection_source_missing"
    elif definition.action_id.startswith("servant_skill:"):
        selections.extend(
            _embedded_selections(
                definition,
                source_key="servant_target_source",
                source_role="servant_config",
                reader=reader,
                expression_compiler=expression_compiler,
            )
        )
        if not selections:
            source_issue = "servant_action_selection_source_missing"
    else:
        source_issue = "action_selection_source_not_projected"
        gap_owner = "source_scope"

    for selection in selections:
        components.extend(selection.components)
    blocked_reasons = {item.blocked_reason for item in selections if item.blocked_reason}
    if blocked_reasons:
        source_issue = (
            next(iter(blocked_reasons))
            if len(blocked_reasons) == 1
            else "action_selection_source_has_multiple_decode_failures"
        )
        gap_owner = (
            "p9_s6"
            if all(
                reason.startswith("action_target_filter_condition_deferred:")
                for reason in blocked_reasons
            )
            else "source_decode"
        )
    unique_signatures = {
        item.semantic_signature for item in selections if not item.blocked_reason
    }
    if len(unique_signatures) > 1:
        source_issue = "action_selection_source_conflict"
        gap_owner = "source_ambiguity"
    if source_issue or len(unique_signatures) != 1:
        return ActionTargetContractIR(
            definition_id=definition.definition_id,
            action_id=definition.action_id,
            level=definition.level,
            source_components=tuple(components),
            source_action_source_ids=source_ids,
            coverage_status="blocked",
            blocked_reason=source_issue or "action_selection_source_not_unique",
            gap_owner=cast(Any, gap_owner),
        )

    selected = sorted(
        (item for item in selections if not item.blocked_reason),
        key=lambda item: tuple(component.component_id for component in item.components),
    )[0]
    if selected.shape is None:
        raise AssertionError("unblocked action target projection lacks a shape")
    selection_mode, candidate_relation, selection_min, selection_max = selected.shape
    return ActionTargetContractIR(
        definition_id=definition.definition_id,
        action_id=definition.action_id,
        level=definition.level,
        source_components=tuple(components),
        source_action_source_ids=source_ids,
        coverage_status="lowered",
        selection_mode=cast(Any, selection_mode),
        candidate_relation=cast(Any, candidate_relation),
        selection_min=selection_min,
        selection_max=selection_max,
        allow_duplicates=False,
        candidate_alive_state=cast(Any, selected.candidate_alive_state),
        friend_servant_policy=cast(Any, selected.friend_servant_policy),
        enemy_servant_policy=cast(Any, selected.enemy_servant_policy),
        servant_selection=cast(Any, selected.servant_selection),
        merge_servant_selection_to_summoner=selected.merge_servant_selection_to_summoner,
        avoid_self=selected.avoid_self,
        selection_filter=selected.selection_filter,
        impact_sub_target=cast(Any, selected.impact_sub_target),
        adjacent_target_count=selected.adjacent_target_count,
        dynamic_target=selected.dynamic_target,
    )


def _character_selection(
    action_source: CharacterActionSourceIR,
    definition: ActionDefinitionIR,
    reader: _SourceReader,
    expression_compiler: _TargetExpressionCompiler,
) -> _TargetInfoProjection | None:
    try:
        document, digest = reader.read(action_source.config_source.source_path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    path = action_source.config_source.evidence.get("json_path")
    expected_digest = action_source.config_source.evidence.get("content_sha256")
    if not isinstance(document, Mapping) or not isinstance(path, str) or digest != expected_digest:
        return None
    node = _value_at_json_path(document, path)
    if not isinstance(node, Mapping):
        return None
    target_info = node.get("TargetInfo")
    if not isinstance(target_info, Mapping):
        return None
    return _selection_from_target_info(
        definition,
        target_info,
        source_path=action_source.config_source.source_path,
        source_role="character_config",
        raw_id=action_source.action_source_id,
        target_info_path=f"{path}.TargetInfo",
        content_sha256=digest,
        source_action_source_id=action_source.action_source_id,
        expression_compiler=expression_compiler,
    )


def _embedded_selections(
    definition: ActionDefinitionIR,
    *,
    source_key: str,
    source_role: str,
    reader: _SourceReader,
    expression_compiler: _TargetExpressionCompiler,
) -> tuple[_TargetInfoProjection, ...]:
    raw = definition.source.evidence.get(source_key)
    if not isinstance(raw, Mapping) or not raw:
        return ()
    candidates = [raw]
    conflict = raw.get("conflicting_target_source")
    if isinstance(conflict, Mapping):
        candidates.append(conflict)
    selections = []
    for candidate in candidates:
        config_path = candidate.get("character_config_path")
        trigger_key = candidate.get("skill_trigger_key")
        if not isinstance(config_path, str) or not config_path or not isinstance(trigger_key, str) or not trigger_key:
            continue
        try:
            document, digest = reader.read(config_path)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
        located = _locate_skill_target_infos(document, trigger_key)
        if not located:
            continue
        for target_info, target_info_path in located:
            selection = _selection_from_target_info(
                definition,
                target_info,
                source_path=config_path,
                source_role=source_role,
                raw_id=trigger_key,
                target_info_path=target_info_path,
                content_sha256=digest,
                source_action_source_id="",
                expression_compiler=expression_compiler,
            )
            if selection is not None:
                selections.append(selection)
    return tuple(selections)


def _selection_from_target_info(
    definition: ActionDefinitionIR,
    target_info: Mapping[str, Any],
    *,
    source_path: str,
    source_role: str,
    raw_id: str,
    target_info_path: str,
    content_sha256: str,
    source_action_source_id: str,
    expression_compiler: _TargetExpressionCompiler,
) -> _TargetInfoProjection | None:
    components: list[ActionTargetSourceComponentIR] = []

    def add_component(
        field_name: str,
        component_kind: str,
        semantic_role: str,
        decoded_value: str,
    ) -> None:
        components.append(
            _component(
                definition,
                component_kind=component_kind,
                source_field=field_name,
                source_role=source_role,
                semantic_role=semantic_role,
                raw_value=_raw_text(target_info[field_name]),
                decoded_value=decoded_value,
                source_path=source_path,
                raw_type="ActionSelectionTargetInfo",
                raw_id=raw_id,
                json_path=f"{target_info_path}.{field_name}",
                content_sha256=content_sha256,
                source_action_source_id=source_action_source_id,
            )
        )

    unknown_fields = tuple(sorted(set(target_info) - set(_TARGET_INFO_FIELDS)))
    for field_name in unknown_fields:
        add_component(
            field_name,
            "unclassified",
            "unclassified",
            f"unclassified_target_info_field:{field_name}",
        )

    target_type = target_info.get("TargetType")
    decoded = (
        _TARGET_TYPE_SELECTION.get(target_type)
        if isinstance(target_type, str) and target_type
        else None
    )
    if "TargetType" in target_info:
        decoded_text = (
            f"{decoded[0]}:{decoded[1]}:{decoded[2]}:{decoded[3]}"
            if decoded is not None
            else f"unsupported:{_raw_text(target_type)}"
        )
        add_component("TargetType", "target_type", "action_selection", decoded_text)

    blocked_reasons = [
        f"action_target_field_unclassified:{','.join(unknown_fields)}"
        if unknown_fields
        else ""
    ]
    if decoded is None:
        blocked_reasons.append(
            "action_target_type_missing"
            if "TargetType" not in target_info
            else f"action_target_type_unsupported:{_raw_text(target_type)}"
        )

    candidate_alive_state = "alive_only"
    if "AliveState" in target_info:
        alive_state = target_info["AliveState"]
        if alive_state == "AliveOrLimbo":
            candidate_alive_state = "alive_or_limbo"
            add_component("AliveState", "alive_state", "action_selection", candidate_alive_state)
        else:
            add_component("AliveState", "alive_state", "action_selection", f"unsupported:{_raw_text(alive_state)}")
            blocked_reasons.append("action_target_alive_state_unsupported")

    friend_servant_policy = "default"
    if "AllowFriendServant" in target_info:
        raw_policy = target_info["AllowFriendServant"]
        policies = {
            "Forbidden": "forbidden",
            "AllowWhenSummonerUnselectable": "allow_when_summoner_unselectable",
        }
        if isinstance(raw_policy, str) and raw_policy in policies:
            friend_servant_policy = policies[raw_policy]
            add_component(
                "AllowFriendServant",
                "allow_friend_servant",
                "action_selection",
                friend_servant_policy,
            )
        else:
            add_component("AllowFriendServant", "allow_friend_servant", "action_selection", f"unsupported:{_raw_text(raw_policy)}")
            blocked_reasons.append("action_target_friend_servant_policy_unsupported")

    enemy_servant_policy = "default"
    if "AllowEnemyServant" in target_info:
        raw_policy = target_info["AllowEnemyServant"]
        if raw_policy == "Forbidden":
            enemy_servant_policy = "forbidden"
            add_component(
                "AllowEnemyServant",
                "allow_enemy_servant",
                "action_selection",
                enemy_servant_policy,
            )
        else:
            add_component("AllowEnemyServant", "allow_enemy_servant", "action_selection", f"unsupported:{_raw_text(raw_policy)}")
            blocked_reasons.append("action_target_enemy_servant_policy_unsupported")

    servant_selection = "none"
    impact_sub_target = "default"
    if "SubTargetType" in target_info:
        sub_target = target_info["SubTargetType"]
        if not isinstance(sub_target, str) or sub_target not in _SUB_TARGET_DECODING:
            add_component("SubTargetType", "sub_target_type", "effect_shape", f"unsupported:{_raw_text(sub_target)}")
            blocked_reasons.append("action_sub_target_type_unsupported")
        else:
            affects_selection = sub_target == "TargetServantOrSummoner"
            add_component(
                "SubTargetType",
                "sub_target_type",
                "action_selection" if affects_selection else "effect_shape",
                _SUB_TARGET_DECODING[sub_target],
            )
            if sub_target == "TargetServantOrSummoner":
                servant_selection = "servant_or_summoner"
            elif sub_target == "TargetAdjoinEntity":
                impact_sub_target = "adjacent"
            elif sub_target == "TargetAllTeammate":
                impact_sub_target = "all_teammate"

    merge_servant = False
    if "MergeServantSelectToSummoner" in target_info:
        raw_merge = target_info["MergeServantSelectToSummoner"]
        if type(raw_merge) is bool:
            merge_servant = raw_merge
            add_component(
                "MergeServantSelectToSummoner",
                "merge_servant_select_to_summoner",
                "action_selection",
                "merge" if raw_merge else "do_not_merge",
            )
        else:
            add_component("MergeServantSelectToSummoner", "merge_servant_select_to_summoner", "action_selection", "invalid_boolean")
            blocked_reasons.append("action_target_servant_merge_schema_invalid")

    avoid_self = False
    if "AvoidSelf" in target_info:
        raw_avoid = target_info["AvoidSelf"]
        if type(raw_avoid) is bool:
            avoid_self = raw_avoid
            add_component("AvoidSelf", "avoid_self", "action_selection", "avoid_self" if raw_avoid else "allow_self")
        else:
            add_component("AvoidSelf", "avoid_self", "action_selection", "invalid_boolean")
            blocked_reasons.append("action_target_avoid_self_schema_invalid")

    selection_filter = None
    if "TargetFilter" in target_info:
        raw_filter = target_info["TargetFilter"]
        filter_source = IRSource(
            source_path=source_path,
            raw_type="ActionSelectionTargetFilter",
            raw_id=raw_id,
            evidence={"json_path": f"{target_info_path}.TargetFilter"},
        )
        try:
            selection_filter = (
                expression_compiler.compile(
                    raw_filter,
                    expression_id=_stable_expression_id(
                        definition.action_id,
                        definition.level,
                        source_path,
                        f"{target_info_path}.TargetFilter",
                    ),
                    source=filter_source,
                )
                if isinstance(raw_filter, Mapping)
                else None
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            selection_filter = None
        decoded_filter = (
            f"typed_target_expression:{selection_filter.fingerprint}"
            if selection_filter is not None and selection_filter.coverage_status == "executable"
            else f"blocked_target_expression:{selection_filter.blocked_reason if selection_filter is not None else 'not_lowerable'}"
        )
        add_component("TargetFilter", "target_filter", "action_selection", decoded_filter)
        if selection_filter is None or selection_filter.coverage_status != "executable":
            expression_reason = (
                selection_filter.blocked_reason
                if selection_filter is not None
                else "not_lowerable"
            )
            blocked_reasons.append(
                (
                    f"action_target_filter_condition_deferred:{expression_reason}"
                    if "condition_not_admitted" in expression_reason
                    else f"action_target_filter_not_executable:{expression_reason}"
                )
            )

    adjacent_target_count = None
    if "AdjoinSubTargetCount" in target_info:
        raw_count = target_info["AdjoinSubTargetCount"]
        if type(raw_count) is int and raw_count > 0 and impact_sub_target == "adjacent":
            adjacent_target_count = raw_count
            add_component("AdjoinSubTargetCount", "adjoin_sub_target_count", "effect_shape", str(raw_count))
        else:
            add_component("AdjoinSubTargetCount", "adjoin_sub_target_count", "effect_shape", "invalid_adjacent_count")
            blocked_reasons.append("action_target_adjacent_count_invalid")

    if "MaxTargetCount" in target_info:
        raw_maximum = target_info["MaxTargetCount"]
        if (
            type(raw_maximum) is int
            and raw_maximum > 0
            and decoded is not None
            and decoded[0] == "explicit"
        ):
            decoded = (decoded[0], decoded[1], 1, raw_maximum)
            add_component("MaxTargetCount", "max_target_count", "action_selection", str(raw_maximum))
        else:
            add_component("MaxTargetCount", "max_target_count", "action_selection", "invalid_explicit_maximum")
            blocked_reasons.append("action_target_maximum_count_invalid")

    dynamic_target = False
    if "IsDynamicTarget" in target_info:
        raw_dynamic = target_info["IsDynamicTarget"]
        if type(raw_dynamic) is bool:
            dynamic_target = raw_dynamic
            add_component("IsDynamicTarget", "is_dynamic_target", "effect_shape", "dynamic" if raw_dynamic else "static")
        else:
            add_component("IsDynamicTarget", "is_dynamic_target", "effect_shape", "invalid_boolean")
            blocked_reasons.append("action_target_dynamic_flag_schema_invalid")

    for field_name, component_kind in (
        ("InvalidTargetMessage", "invalid_target_message"),
        ("InvalidTargetMessageIcon", "invalid_target_message_icon"),
    ):
        if field_name in target_info:
            add_component(field_name, component_kind, "non_gameplay", "display_only")

    if servant_selection == "servant_or_summoner" and (
        decoded is None or decoded[0] != "explicit" or decoded[1] != "ally_or_self"
    ):
        blocked_reasons.append("servant_or_summoner_requires_friend_selection")
    if merge_servant and servant_selection != "servant_or_summoner":
        blocked_reasons.append("servant_merge_without_servant_selection")
    if friend_servant_policy != "default" and (
        decoded is None or decoded[1] != "ally_or_self"
    ):
        blocked_reasons.append("friend_servant_policy_requires_ally_selection")

    semantic_fields = {
        key: target_info[key]
        for key in sorted(set(target_info) - {"InvalidTargetMessage", "InvalidTargetMessageIcon"})
    }
    reason = next((item for item in blocked_reasons if item), "")
    return _TargetInfoProjection(
        shape=decoded,
        semantic_signature=json.dumps(
            semantic_fields,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ),
        components=tuple(components),
        candidate_alive_state=candidate_alive_state,
        friend_servant_policy=friend_servant_policy,
        enemy_servant_policy=enemy_servant_policy,
        servant_selection=servant_selection,
        merge_servant_selection_to_summoner=merge_servant,
        avoid_self=avoid_self,
        selection_filter=selection_filter,
        impact_sub_target=impact_sub_target,
        adjacent_target_count=adjacent_target_count,
        dynamic_target=dynamic_target,
        blocked_reason=reason,
    )


def _action_table_component(
    definition: ActionDefinitionIR,
    reader: _SourceReader,
) -> ActionTargetSourceComponentIR | None:
    document, digest = reader.read(definition.source.source_path)
    row_index = definition.source.evidence.get("row_index")
    id_key = definition.source.evidence.get("id_key")
    if (
        not isinstance(document, list)
        or not isinstance(row_index, int)
        or isinstance(row_index, bool)
        or row_index < 0
        or row_index >= len(document)
        or not isinstance(id_key, str)
    ):
        return None
    row = document[row_index]
    if not isinstance(row, Mapping) or str(row.get(id_key)) != definition.source.raw_id:
        return None
    field_name = "SkillEffect" if row.get("SkillEffect") not in {None, ""} else "AttackType"
    raw_value = row.get(field_name)
    if not isinstance(raw_value, str) or not raw_value:
        return None
    decoded = {
        "singleattack": "single_target_effect",
        "mazeattack": "single_target_effect",
        "blast": "primary_plus_adjacent_effect",
        "aoeattack": "all_enemy_effect",
        "aoe": "all_enemy_effect",
        "bounce": "random_bounce_effect",
        "enhance": "support_effect",
    }.get(raw_value.lower(), f"unclassified:{raw_value}")
    return _component(
        definition,
        component_kind="skill_effect",
        source_field=field_name,
        source_role="action_table",
        semantic_role="effect_shape",
        raw_value=raw_value,
        decoded_value=decoded,
        source_path=definition.source.source_path,
        raw_type=definition.source.raw_type,
        raw_id=definition.source.raw_id,
        json_path=f"$[{row_index}].{field_name}",
        content_sha256=digest,
        source_action_source_id="",
    )


def _component(
    definition: ActionDefinitionIR,
    *,
    component_kind: str,
    source_field: str,
    source_role: str,
    semantic_role: str,
    raw_value: str,
    decoded_value: str,
    source_path: str,
    raw_type: str,
    raw_id: str,
    json_path: str,
    content_sha256: str,
    source_action_source_id: str,
) -> ActionTargetSourceComponentIR:
    evidence: dict[str, JSONValue] = {
        "action_id": definition.action_id,
        "level": definition.level,
        "definition_id": definition.definition_id,
        "component_kind": component_kind,
        "source_field": source_field,
        "source_role": source_role,
        "semantic_role": semantic_role,
        "raw_value": raw_value,
        "decoded_value": decoded_value,
        "json_path": json_path,
        "content_sha256": content_sha256,
        "source_action_source_id": source_action_source_id,
    }
    return ActionTargetSourceComponentIR(
        action_id=definition.action_id,
        level=definition.level,
        component_kind=cast(Any, component_kind),
        source_field=source_field,
        source_role=cast(Any, source_role),
        semantic_role=cast(Any, semantic_role),
        raw_value=raw_value,
        decoded_value=decoded_value,
        source=IRSource(
            source_path=source_path,
            raw_type=raw_type,
            raw_id=raw_id,
            evidence=evidence,
        ),
    )


def _locate_skill_target_infos(
    document: Any,
    trigger_key: str,
) -> tuple[tuple[Mapping[str, Any], str], ...]:
    if not isinstance(document, Mapping):
        return ()
    skill_list = document.get("SkillList")
    candidates: list[tuple[Mapping[str, Any], str]] = []
    if isinstance(skill_list, list):
        for index, item in enumerate(skill_list):
            if not isinstance(item, Mapping):
                continue
            names = {
                str(item.get("Name") or ""),
                str(item.get("SkillName") or ""),
                str(item.get("Skill") or ""),
                str(item.get("SkillTriggerKey") or ""),
            }
            if trigger_key in names and isinstance(item.get("TargetInfo"), Mapping):
                candidates.append((cast(Mapping[str, Any], item["TargetInfo"]), f"$.SkillList[{index}].TargetInfo"))
    elif isinstance(skill_list, Mapping):
        item = skill_list.get(trigger_key)
        if isinstance(item, Mapping) and isinstance(item.get("TargetInfo"), Mapping):
            candidates.append((cast(Mapping[str, Any], item["TargetInfo"]), f"$.SkillList.{trigger_key}.TargetInfo"))
    return tuple(candidates)


def _value_at_json_path(document: Mapping[str, Any], path: str) -> Any:
    if not path.startswith("$"):
        return None
    current: Any = document
    index = 1
    while index < len(path):
        if path[index] == ".":
            index += 1
            end = index
            while end < len(path) and path[end] not in ".[":
                end += 1
            key = path[index:end]
            if not key or not isinstance(current, Mapping) or key not in current:
                return None
            current = current[key]
            index = end
        elif path[index] == "[":
            end = path.find("]", index)
            if end < 0 or not isinstance(current, (list, tuple)):
                return None
            token = path[index + 1 : end]
            if not token.isdigit() or int(token) >= len(current):
                return None
            current = current[int(token)]
            index = end + 1
        else:
            return None
    return current


def _character_source_level_key(source_id: str, action_id: str, level: int) -> str:
    return f"{source_id}\0{action_id}\0{level}"


def _raw_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _stable_expression_id(
    action_id: str,
    level: int,
    source_path: str,
    json_path: str,
) -> str:
    encoded = "\0".join((action_id, str(level), source_path, json_path)).encode("utf-8")
    return f"action_target_filter:{sha256(encoded).hexdigest()}"


__all__ = ["build_action_target_contract_catalog"]
