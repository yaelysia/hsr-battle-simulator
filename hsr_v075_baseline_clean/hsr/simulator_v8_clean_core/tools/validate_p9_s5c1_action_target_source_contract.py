from __future__ import annotations

import argparse
import json
import resource
import time
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Any

from ..rules.action_target_contract import ActionTargetContractCatalogIR
from ..rules.ir import (
    ActionDefinitionIR,
    CanonicalIR,
    CharacterAbilitySourceGraphCatalogIR,
)
from ..rules.rulebook import RuleBook
from ..tbgd.lowering import ACTION_DEFINITION_TABLES, TBGDLowering


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_TBGD = ROOT / "turnbasedgamedata-main"
CORE = Path(__file__).resolve().parents[1]

_TARGET_TYPE_SELECTION = {
    "Caster": ("automatic", "self", 0, 0),
    "EnemySelect": ("explicit", "enemy", 1, 1),
    "FriendSelect": ("explicit", "ally_or_self", 1, 1),
    "AllEnemy": ("automatic", "enemy", 0, 0),
    "AllTeamMember": ("automatic", "ally_or_self", 0, 0),
}

_TARGET_INFO_CLASSIFICATION = {
    "TargetType": ("target_type", "action_selection"),
    "SubTargetType": ("sub_target_type", "dynamic"),
    "AliveState": ("alive_state", "action_selection"),
    "TargetFilter": ("target_filter", "action_selection"),
    "AllowFriendServant": ("allow_friend_servant", "action_selection"),
    "AllowEnemyServant": ("allow_enemy_servant", "action_selection"),
    "MergeServantSelectToSummoner": ("merge_servant_select_to_summoner", "action_selection"),
    "AvoidSelf": ("avoid_self", "action_selection"),
    "IsDynamicTarget": ("is_dynamic_target", "effect_shape"),
    "AdjoinSubTargetCount": ("adjoin_sub_target_count", "effect_shape"),
    "MaxTargetCount": ("max_target_count", "action_selection"),
    "InvalidTargetMessage": ("invalid_target_message", "non_gameplay"),
    "InvalidTargetMessageIcon": ("invalid_target_message_icon", "non_gameplay"),
}


def _write(path: Path, value: object) -> int:
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode()
    path.write_bytes(encoded)
    return len(encoded)


def _raw_level(value: object) -> int:
    if isinstance(value, Mapping):
        value = value.get("Value")
    if value is None:
        return 1
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("raw action level is not numeric")
    level = int(value)
    if level <= 0 or level != value:
        raise ValueError("raw action level is invalid")
    return level


def _raw_action_keys(tbgd_root: Path) -> tuple[tuple[str, int], ...]:
    keys = []
    for relative_path, entity_type, id_key in ACTION_DEFINITION_TABLES:
        rows = json.loads((tbgd_root / relative_path).read_bytes())
        if not isinstance(rows, list):
            raise ValueError(f"action table is not an array:{relative_path}")
        for row in rows:
            if not isinstance(row, Mapping) or id_key not in row:
                continue
            keys.append((f"{entity_type}:{row[id_key]}", _raw_level(row.get("Level"))))
    if len(keys) != len(set(keys)):
        raise ValueError("raw action definition keys are not unique")
    return tuple(sorted(keys))


class _RawOracle:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.cache: dict[str, tuple[Any, str]] = {}

    def value(self, source_path: str, json_path: str) -> tuple[Any, str]:
        if source_path not in self.cache:
            path = (self.root / source_path).resolve()
            path.relative_to(self.root)
            raw = path.read_bytes()
            self.cache[source_path] = (json.loads(raw), sha256(raw).hexdigest())
        document, digest = self.cache[source_path]
        return _value_at(document, json_path), digest


def _value_at(document: object, path: str) -> object:
    if not path.startswith("$"):
        return None
    current = document
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
            token = path[index + 1 : end] if end >= 0 else ""
            if (
                end < 0
                or not token.isdigit()
                or not isinstance(current, (list, tuple))
                or int(token) >= len(current)
            ):
                return None
            current = current[int(token)]
            index = end + 1
        else:
            return None
    return current


def _raw_text(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _expected_target_payload(target_info: Mapping[str, object]) -> dict[str, object] | None:
    target_type = target_info.get("TargetType")
    shape = _TARGET_TYPE_SELECTION.get(target_type) if isinstance(target_type, str) else None
    if shape is None:
        return None
    mode, relation, minimum, maximum = shape
    raw_maximum = target_info.get("MaxTargetCount")
    if raw_maximum is not None:
        if type(raw_maximum) is not int or raw_maximum <= 0 or mode != "explicit":
            return None
        maximum = raw_maximum
    alive = target_info.get("AliveState")
    if alive not in {None, "AliveOrLimbo"}:
        return None
    friend_policy = {
        None: "default",
        "Forbidden": "forbidden",
        "AllowWhenSummonerUnselectable": "allow_when_summoner_unselectable",
    }.get(target_info.get("AllowFriendServant"))
    enemy_policy = {None: "default", "Forbidden": "forbidden"}.get(
        target_info.get("AllowEnemyServant")
    )
    if friend_policy is None or enemy_policy is None:
        return None
    sub_target = target_info.get("SubTargetType")
    sub_payload = {
        None: ("none", "default"),
        "TargetServantOrSummoner": ("servant_or_summoner", "default"),
        "TargetAdjoinEntity": ("none", "adjacent"),
        "TargetAllTeammate": ("none", "all_teammate"),
    }.get(sub_target)
    if sub_payload is None:
        return None
    for field_name in ("MergeServantSelectToSummoner", "AvoidSelf", "IsDynamicTarget"):
        if field_name in target_info and type(target_info[field_name]) is not bool:
            return None
    adjacent_count = target_info.get("AdjoinSubTargetCount")
    if adjacent_count is not None and (
        type(adjacent_count) is not int or adjacent_count <= 0 or sub_payload[1] != "adjacent"
    ):
        return None
    return {
        "selection_mode": mode,
        "candidate_relation": relation,
        "selection_min": minimum,
        "selection_max": maximum,
        "candidate_alive_state": "alive_or_limbo" if alive == "AliveOrLimbo" else "alive_only",
        "friend_servant_policy": friend_policy,
        "enemy_servant_policy": enemy_policy,
        "servant_selection": sub_payload[0],
        "merge_servant_selection_to_summoner": target_info.get("MergeServantSelectToSummoner", False),
        "avoid_self": target_info.get("AvoidSelf", False),
        "has_selection_filter": "TargetFilter" in target_info,
        "impact_sub_target": sub_payload[1],
        "adjacent_target_count": adjacent_count,
        "dynamic_target": target_info.get("IsDynamicTarget", False),
    }


def _locate_target_infos(document: object, trigger_key: str) -> list[tuple[Mapping[str, object], str]]:
    if not isinstance(document, Mapping):
        return []
    skill_list = document.get("SkillList")
    found = []
    if isinstance(skill_list, list):
        for index, item in enumerate(skill_list):
            if not isinstance(item, Mapping):
                continue
            names = {str(item.get(key) or "") for key in ("Name", "SkillName", "Skill", "SkillTriggerKey")}
            if trigger_key in names and isinstance(item.get("TargetInfo"), Mapping):
                found.append((item["TargetInfo"], f"$.SkillList[{index}].TargetInfo"))
    elif isinstance(skill_list, Mapping):
        item = skill_list.get(trigger_key)
        if isinstance(item, Mapping) and isinstance(item.get("TargetInfo"), Mapping):
            found.append((item["TargetInfo"], f"$.SkillList.{trigger_key}.TargetInfo"))
    return found


def _target_info_inventory(
    definitions: tuple[ActionDefinitionIR, ...],
    source_graph: CharacterAbilitySourceGraphCatalogIR,
    oracle: _RawOracle,
) -> tuple[list[tuple[str, int, str, str, Mapping[str, object]]], list[str]]:
    records = []
    issues = []
    for source in source_graph.action_sources:
        config_path = source.config_source.source_path
        node_path = source.config_source.evidence.get("json_path")
        node, _digest = oracle.value(config_path, str(node_path))
        target_info = node.get("TargetInfo") if isinstance(node, Mapping) else None
        if not isinstance(target_info, Mapping):
            issues.append(f"{source.action_source_id}:target_info_missing")
            continue
        for level in source.levels:
            records.append((source.action_id, level, config_path, f"{node_path}.TargetInfo", target_info))
    for definition in definitions:
        source_key = (
            "monster_target_source"
            if definition.action_id.startswith("monster_skill:")
            else "servant_target_source"
            if definition.action_id.startswith("servant_skill:")
            else ""
        )
        raw_source = definition.source.evidence.get(source_key) if source_key else None
        if not isinstance(raw_source, Mapping) or not raw_source:
            continue
        candidates = [raw_source]
        if isinstance(raw_source.get("conflicting_target_source"), Mapping):
            candidates.append(raw_source["conflicting_target_source"])
        for candidate in candidates:
            config_path = candidate.get("character_config_path")
            trigger_key = candidate.get("skill_trigger_key")
            if not isinstance(config_path, str) or not isinstance(trigger_key, str):
                continue
            document, _digest = oracle.value(config_path, "$")
            located = _locate_target_infos(document, trigger_key)
            for target_info, target_path in located:
                records.append((definition.action_id, definition.level, config_path, target_path, target_info))
    unique = {
        (action_id, level, source_path, target_path): target_info
        for action_id, level, source_path, target_path, target_info in records
    }
    return [(*key, unique[key]) for key in sorted(unique)], issues


def _source_audit(
    catalog: ActionTargetContractCatalogIR,
    definitions: tuple[ActionDefinitionIR, ...],
    source_graph: CharacterAbilitySourceGraphCatalogIR,
    root: Path,
) -> dict[str, Any]:
    oracle = _RawOracle(root)
    mismatches = []
    selection_mismatches = []
    field_mismatches = []
    unclassified_fields = Counter()
    observed_fields = Counter()
    source_roles = Counter()
    contracts = {(item.action_id, item.level): item for item in catalog.contracts}
    expected_payloads: dict[tuple[str, int], list[dict[str, object]]] = defaultdict(list)
    inventory, inventory_issues = _target_info_inventory(definitions, source_graph, oracle)
    for action_id, level, source_path, target_info_path, target_info in inventory:
        contract = contracts[(action_id, level)]
        raw_fields = set(target_info)
        represented = {
            component.source_field: component
            for component in contract.source_components
            if component.source.source_path == source_path
            and str(component.source.evidence.get("json_path", "")).rsplit(".", 1)[0]
            == target_info_path
        }
        if set(represented) != raw_fields:
            field_mismatches.append(f"{contract.contract_id}:field_denominator")
        for field_name in raw_fields:
            observed_fields[field_name] += 1
            expected = _TARGET_INFO_CLASSIFICATION.get(field_name)
            component = represented.get(field_name)
            if expected is None:
                unclassified_fields[field_name] += 1
                if component is None or component.component_kind != "unclassified" or contract.coverage_status != "blocked":
                    field_mismatches.append(f"{contract.contract_id}:unclassified:{field_name}")
                continue
            expected_kind, expected_role = expected
            if field_name == "SubTargetType":
                expected_role = "action_selection" if target_info[field_name] == "TargetServantOrSummoner" else "effect_shape"
            if component is None or (component.component_kind, component.semantic_role) != (expected_kind, expected_role):
                field_mismatches.append(f"{contract.contract_id}:classification:{field_name}")
        payload = _expected_target_payload(target_info)
        if payload is not None:
            expected_payloads[(action_id, level)].append(payload)
    for contract in catalog.contracts:
        for component in contract.source_components:
            evidence = component.source.evidence
            raw_value, digest = oracle.value(
                component.source.source_path,
                str(evidence["json_path"]),
            )
            if _raw_text(raw_value) != component.raw_value or digest != evidence["content_sha256"]:
                mismatches.append(component.component_id)
            if str(evidence["json_path"]).rsplit(".", 1)[-1] != component.source_field:
                mismatches.append(component.component_id)
            source_roles[(component.source_role, component.semantic_role)] += 1
        if contract.coverage_status == "lowered":
            expected = expected_payloads[(contract.action_id, contract.level)]
            if not expected:
                selection_mismatches.append(contract.contract_id)
                continue
            actual = {
                "selection_mode": contract.selection_mode,
                "candidate_relation": contract.candidate_relation,
                "selection_min": contract.selection_min,
                "selection_max": contract.selection_max,
                "candidate_alive_state": contract.candidate_alive_state,
                "friend_servant_policy": contract.friend_servant_policy,
                "enemy_servant_policy": contract.enemy_servant_policy,
                "servant_selection": contract.servant_selection,
                "merge_servant_selection_to_summoner": contract.merge_servant_selection_to_summoner,
                "avoid_self": contract.avoid_self,
                "has_selection_filter": contract.selection_filter is not None,
                "impact_sub_target": contract.impact_sub_target,
                "adjacent_target_count": contract.adjacent_target_count,
                "dynamic_target": contract.dynamic_target,
            }
            unique_expected = {
                json.dumps(item, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
                for item in expected
            }
            if len(unique_expected) != 1 or actual != expected[0]:
                selection_mismatches.append(contract.contract_id)
    return {
        "ok": not mismatches and not selection_mismatches and not field_mismatches and not inventory_issues,
        "component_count": sum(len(item.source_components) for item in catalog.contracts),
        "target_info_field_count": sum(observed_fields.values()),
        "source_document_count": len(oracle.cache),
        "source_roles": {f"{key[0]}:{key[1]}": value for key, value in sorted(source_roles.items())},
        "observed_target_info_fields": dict(sorted(observed_fields.items())),
        "unclassified_target_info_fields": dict(sorted(unclassified_fields.items())),
        "target_info_inventory_issues": inventory_issues[:20],
        "raw_value_or_digest_mismatches": mismatches[:20],
        "target_info_field_mismatches": field_mismatches[:20],
        "selection_contract_mismatches": selection_mismatches[:20],
    }


def _fixture_definition(contract: object) -> ActionDefinitionIR:
    source = contract.source_components[0].source
    return ActionDefinitionIR(
        definition_id=contract.definition_id,
        action_id=contract.action_id,
        level=contract.level,
        attack_type="validation_fixture",
        skill_effect="validation_fixture",
        target_mode="unknown",
        bp_need=0.0,
        bp_add=0.0,
        sp_base=0.0,
        sp_multiple_ratio=0.0,
        param_list=(),
        show_stance_list=(),
        show_damage_list=(),
        stance_damage_type=None,
        source=source,
        coverage_status="blocked",
    )


def _query_audit(catalog: ActionTargetContractCatalogIR) -> dict[str, Any]:
    lowered = next(item for item in catalog.contracts if item.coverage_status == "lowered")
    blocked = next(item for item in catalog.contracts if item.coverage_status == "blocked")
    fixture_catalog = ActionTargetContractCatalogIR(
        definition_scope="partial",
        source_graph_catalog_id=catalog.source_graph_catalog_id,
        source_graph_fingerprint=catalog.source_graph_fingerprint,
        character_source_level_keys=catalog.character_source_level_keys,
        contracts=(lowered, blocked),
        build_counters={"generic_record_limit_applied": True},
    )
    canonical = CanonicalIR(
        version="p9_s5c1_query_fixture",
        action_definitions=(
            _fixture_definition(lowered),
            _fixture_definition(blocked),
        ),
        action_target_contract_catalog=fixture_catalog,
    )
    rules = RuleBook(canonical)
    resolved = rules.action_target_contract(lowered.action_id, lowered.level)
    blocked_result = rules.action_target_contract(blocked.action_id, blocked.level)
    missing = rules.action_target_contract("validation_fixture:missing", 1)
    return {
        "ok": (
            resolved.resolution_status == "resolved"
            and resolved.value == lowered
            and blocked_result.resolution_status == "blocked"
            and blocked_result.value is None
            and missing.resolution_status == "blocked"
            and missing.blocked_reason == "action_target_contract_missing"
            and canonical.to_json()["action_target_contract_catalog"]
            == fixture_catalog.to_json()
        ),
        "resolved": resolved.to_json(),
        "blocked": blocked_result.to_json(),
        "missing": missing.to_json(),
    }


def _rejects(callable_: object) -> bool:
    try:
        callable_()
    except (TypeError, ValueError):
        return True
    return False


def _negative_audit(catalog: ActionTargetContractCatalogIR) -> dict[str, bool]:
    lowered = next(item for item in catalog.contracts if item.coverage_status == "lowered")
    blocked = next(item for item in catalog.contracts if item.coverage_status == "blocked")
    selection = next(
        item for item in lowered.source_components if item.semantic_role == "action_selection"
    )
    filtered = next(
        item
        for item in catalog.contracts
        if item.coverage_status == "lowered" and item.selection_filter is not None
    )
    max_count = next(
        item
        for item in catalog.contracts
        if item.coverage_status == "lowered" and item.selection_max is not None and item.selection_max > 1
    )
    encoded = catalog.to_json()
    restored = ActionTargetContractCatalogIR.from_json(encoded)
    before = restored.to_json()
    encoded["contracts"][0]["source_components"][0]["source"]["evidence"]["forged"] = True
    tampered = catalog.to_json()
    tampered["catalog_id"] = "action_target_catalog:" + "0" * 64
    unknown_field = catalog.to_json()
    unknown_field["legacy_target_policy"] = {}
    partial = ActionTargetContractCatalogIR(
        definition_scope="partial",
        source_graph_catalog_id=catalog.source_graph_catalog_id,
        source_graph_fingerprint=catalog.source_graph_fingerprint,
        character_source_level_keys=catalog.character_source_level_keys,
        contracts=(lowered,),
        build_counters={"generic_record_limit_applied": True},
    )
    cases = {
        "duplicate_contract_key_rejected": lambda: replace(
            catalog, contracts=(*catalog.contracts, catalog.contracts[0])
        ),
        "cross_action_source_rejected": lambda: replace(
            selection, action_id="validation_fixture:other"
        ),
        "invalid_cardinality_rejected": lambda: replace(lowered, selection_max=2),
        "blocked_payload_rejected": lambda: replace(
            blocked,
            selection_mode="explicit",
            candidate_relation="enemy",
            selection_min=1,
            selection_max=1,
            allow_duplicates=False,
        ),
        "lowered_without_selection_source_rejected": lambda: replace(
            lowered,
            source_components=tuple(
                item for item in lowered.source_components if item.semantic_role != "action_selection"
            ),
        ),
        "action_table_selection_forgery_rejected": lambda: replace(
            selection, source_role="action_table"
        ),
        "selection_payload_without_source_rejected": lambda: replace(
            lowered,
            friend_servant_policy=(
                "forbidden" if lowered.friend_servant_policy == "default" else "default"
            ),
        ),
        "typed_filter_without_source_component_rejected": lambda: replace(
            filtered,
            source_components=tuple(
                item
                for item in filtered.source_components
                if item.component_kind != "target_filter"
            ),
        ),
        "multi_target_without_maximum_source_rejected": lambda: replace(
            max_count,
            source_components=tuple(
                item
                for item in max_count.source_components
                if item.component_kind != "max_target_count"
            ),
        ),
        "complete_limit_masquerade_rejected": lambda: replace(
            partial, definition_scope="complete"
        ),
        "catalog_fingerprint_tamper_rejected": lambda: ActionTargetContractCatalogIR.from_json(tampered),
        "unknown_codec_field_rejected": lambda: ActionTargetContractCatalogIR.from_json(unknown_field),
    }
    result = {name: _rejects(callable_) for name, callable_ in cases.items()}
    result["input_mutation_isolated"] = restored.to_json() == before
    return result


def _runtime_consumer_audit() -> dict[str, Any]:
    consumers = []
    for relative in ("core", "systems", "scenarios", "queries"):
        for path in (CORE / relative).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "action_target_contract" in text:
                consumers.append(path.relative_to(CORE).as_posix())
    production = (CORE / "tbgd/action_target_contracts.py").read_text(encoding="utf-8")
    forbidden_inference = [
        token
        for token in ("_target_relation_from_action_semantics", "damage_kind")
        if token in production
    ]
    return {
        "ok": not consumers and not forbidden_inference,
        "runtime_consumers": consumers,
        "forbidden_semantic_inference": forbidden_inference,
    }


def _strict_true(values: object) -> bool:
    return isinstance(values, Mapping) and bool(values) and all(
        type(value) is bool and value for value in values.values()
    )


def validate(tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    started = time.monotonic()
    lowering = TBGDLowering(tbgd_root)
    catalog = lowering.build_action_target_contract_catalog()
    source_graph = lowering.build_character_ability_source_graph_catalog()
    definitions = tuple(lowering._lower_action_definitions())
    raw_keys = _raw_action_keys(tbgd_root)
    definition_keys = tuple(sorted((item.action_id, item.level) for item in definitions))
    contract_keys = tuple((item.action_id, item.level) for item in catalog.contracts)
    expected_source_levels = tuple(
        sorted(
            f"{source.action_source_id}\0{source.action_id}\0{level}"
            for source in source_graph.action_sources
            for level in source.levels
        )
    )
    covered_source_levels = tuple(
        sorted(
            f"{source_id}\0{item.action_id}\0{item.level}"
            for item in catalog.contracts
            for source_id in item.source_action_source_ids
        )
    )
    source_audit = _source_audit(catalog, definitions, source_graph, tbgd_root)
    query_audit = _query_audit(catalog)
    negatives = _negative_audit(catalog)
    runtime_audit = _runtime_consumer_audit()
    round_trip = ActionTargetContractCatalogIR.from_json(catalog.to_json())
    by_status = Counter(item.coverage_status for item in catalog.contracts)
    gap_groups: dict[tuple[str, str], list[object]] = defaultdict(list)
    for item in catalog.contracts:
        if item.coverage_status == "blocked":
            gap_groups[(item.gap_owner, item.blocked_reason)].append(item)
    gap_ledger = [
        {
            "gap_owner": owner,
            "blocked_reason": reason,
            "count": len(items),
            "representative_action_id": items[0].action_id,
            "representative_level": items[0].level,
            "representative_source_path": (
                items[0].source_components[0].source.source_path
                if items[0].source_components
                else ""
            ),
        }
        for (owner, reason), items in sorted(gap_groups.items())
    ]
    predicates = {
        "raw_action_denominator_matches_contracts": raw_keys == definition_keys == contract_keys,
        "one_contract_per_definition_key": len(contract_keys) == len(set(contract_keys)),
        "character_source_level_denominator_closed": (
            catalog.character_source_level_keys
            == expected_source_levels
            == covered_source_levels
        ),
        "current_character_action_contracts_all_lowered": all(
            item.coverage_status == "lowered"
            for item in catalog.contracts
            if item.source_action_source_ids
        ),
        "catalog_is_complete_and_not_limited": (
            catalog.definition_scope == "complete"
            and catalog.build_counters.get("generic_record_limit_applied") is False
        ),
        "contracts_only_lowered_or_blocked": set(by_status) <= {"lowered", "blocked"},
        "blocked_contracts_have_precise_owner": all(
            item.gap_owner
            in {"source_scope", "source_gap", "source_ambiguity", "source_decode", "p9_s6"}
            and bool(item.blocked_reason)
            for item in catalog.contracts
            if item.coverage_status == "blocked"
        ),
        "raw_sources_reversible_and_selection_independent": source_audit["ok"],
        "target_info_field_denominator_closed": not source_audit["target_info_field_mismatches"],
        "all_observed_target_info_fields_classified": not source_audit["unclassified_target_info_fields"],
        "deferred_filter_conditions_owned_by_s6": all(
            item.gap_owner == "p9_s6"
            for item in catalog.contracts
            if item.blocked_reason.startswith("action_target_filter_condition_deferred:")
        ),
        "blocked_gap_ledger_is_complete": sum(item["count"] for item in gap_ledger) == by_status["blocked"],
        "selection_never_allows_duplicate_submission": all(
            item.allow_duplicates is False
            for item in catalog.contracts
            if item.coverage_status == "lowered"
        ),
        "catalog_round_trip_stable": round_trip.to_json() == catalog.to_json(),
        "rulebook_query_strict": query_audit["ok"],
        "production_boundaries_reject_contradictions": _strict_true(negatives),
        "runtime_behavior_unchanged": runtime_audit["ok"],
        "full_canonical_ir_build_count_zero": catalog.build_counters.get("full_canonical_ir_build_count") == 0,
        "strict_total_gate_rejects_integer_false_control": not _strict_true({"valid": True, "false_control": 0}),
    }
    elapsed = time.monotonic() - started
    rss_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    output_dir.mkdir(parents=True, exist_ok=False)
    evidence_bytes = 0
    for name, value in (
        ("source_audit.json", source_audit),
        ("query_audit.json", query_audit),
        ("negative_cases.json", negatives),
        ("runtime_consumer_audit.json", runtime_audit),
        ("blocked_gap_ledger.json", gap_ledger),
    ):
        evidence_bytes += _write(output_dir / name, value)
    resource_gate = {
        "elapsed_seconds": elapsed,
        "peak_rss_kib": rss_kib,
        "evidence_bytes_before_summary": evidence_bytes,
        "elapsed_within_budget": elapsed < 180,
        "rss_within_budget": rss_kib < 700 * 1024,
        "evidence_within_budget": evidence_bytes < 1024 * 1024,
    }
    ok = _strict_true(predicates) and all(
        resource_gate[name] is True
        for name in ("elapsed_within_budget", "rss_within_budget", "evidence_within_budget")
    )
    summary = {
        "ok": ok,
        "predicates": predicates,
        "catalog": {
            "catalog_id": catalog.catalog_id,
            "definition_scope": catalog.definition_scope,
            "contract_count": len(catalog.contracts),
            "by_status": dict(sorted(by_status.items())),
            "character_source_level_count": len(catalog.character_source_level_keys),
            "blocked_gap_count": sum(item["count"] for item in gap_ledger),
            "build_counters": dict(catalog.build_counters),
        },
        "resource": resource_gate,
        "output_dir": str(output_dir),
    }
    _write(output_dir / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tbgd-root", type=Path, default=DEFAULT_TBGD)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = validate(args.tbgd_root, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["ok"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
