from __future__ import annotations

import argparse
import json
import resource
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping
from dataclasses import fields, replace
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

from ..ir_types import IRSource, JSONValue
from ..rules.ir import (
    CanonicalIR,
    CharacterAbilityBindingGapIR,
    CharacterAbilityBindingIR,
    CharacterAbilityDefinitionIR,
    CharacterAbilityGraphRefIR,
    CharacterAbilitySourceGraphCatalogIR,
    CharacterNonGameplaySkillSourceIR,
    CharacterDataCardIR,
    character_ability_stable_id, _ambiguous_character_action_source_ids,
)
from ..rules.rulebook import (
    CharacterAbilitySourceGraphQuery,
    CharacterAbilitySourceGraphQueryResult,
)
from ..tbgd.character_ability_scope import (
    build_character_ability_raw_snapshot,
    build_character_ability_scope_projection,
)
from ..tbgd.character_ability_source_graph import (
    _non_gameplay_skill_retired_reason,
    same_character_ability_s0_sources,
)
from ..tbgd.character_cards import (
    CHARACTER_ACTION_DEFINITION_TABLES,
    build_character_card_ir,
)
from ..tbgd import lowering as lowering_module
from ..tbgd.lowering import TBGDLowering, build_character_action_definition_ir


WALL_CLOCK_BUDGET_SECONDS = 8 * 60
RSS_BUDGET_BYTES = 1024 * 1024 * 1024
EVIDENCE_BUDGET_BYTES = 5 * 1024 * 1024
VALIDATOR_LINE_BUDGET = 900
GAMEPLAY_KINDS = {"entry", "phase", "passive"}


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate P9-S1 source graph")
    parser.add_argument("--tbgd-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def _rejected(operation: Callable[[], object]) -> bool:
    try:
        operation()
    except (AttributeError, TypeError, ValueError):
        return True
    return False


def _synthetic_retired_source(
    *,
    graph_id: str = "graph",
    owner: str = "1001",
    skill_id: str = "skill",
    attack_type: str = "MazeNormal",
    skill_effect: str = "SyntheticEffect",
    row_index: int = 0,
    digest: str = "a" * 64,
    source_path: str = "action_table",
) -> CharacterNonGameplaySkillSourceIR:
    reason = "maze_normal_without_skill_trigger"
    source_id = character_ability_stable_id(
        "character_non_gameplay_skill_source",
        graph_id,
        owner,
        skill_id,
        source_path,
        row_index,
        attack_type,
        skill_effect,
        reason,
    )
    evidence = {"graph_id": graph_id, "owner_avatar_id": owner, "skill_id": skill_id, "skill_trigger_key": "", "attack_type": attack_type, "skill_effect": skill_effect, "row_index": row_index, "retired_reason": reason, "content_sha256": digest}
    return CharacterNonGameplaySkillSourceIR(source_id, graph_id, owner, skill_id, attack_type, skill_effect, row_index, digest, reason, IRSource(source_path, "CharacterSkillActionRow", skill_id, evidence))


def _preflight_model_contracts() -> dict[str, bool]:
    digest = "a" * 64
    relation_id = character_ability_stable_id(
        "character_ability_relation", "graph", "1001", "action", "skill", "Cam", "presentation", 0, "config", "$.Phase"
    )
    evidence = {
        "relation_id": relation_id,
        "graph_id": "graph",
        "owner_avatar_id": "1001",
        "action_source_id": "action",
        "skill_id": "skill",
        "binding_kind": "presentation",
        "relation_ordinal": 0,
        "json_path": "$.Phase",
        "content_sha256": digest,
    }
    raw_evidence = dict(evidence)
    binding = CharacterAbilityBindingIR(
        binding_id=character_ability_stable_id(
            "character_ability_binding", relation_id, "definition"
        ),
        relation_id=relation_id,
        graph_id="graph",
        owner_avatar_id="1001",
        action_source_id="action",
        ability_definition_id="definition",
        ability_name="Cam",
        binding_kind="presentation",
        ordinal=0,
        relation_source=IRSource("config", "CharacterAbilityRelation", "Cam", raw_evidence),
    )
    raw_evidence["json_path"] = "mutated"
    ref = CharacterAbilityGraphRefIR(
        graph_ref_id="character_ability_graph_ref:card:owned:graph",
        character_data_card_id="card",
        owner_avatar_id="1001",
        graph_id="graph",
        reference_kind="owned",
        source=IRSource(
            "inventory",
            "AvatarConfig",
            "card",
            {
                "graph_id": "graph",
                "reference_kind": "owned",
                "source_graph_catalog_id": "catalog",
                "source_id": "source",
                "avatar_id": "1001",
                "row_index": 0,
                "selected_version": "base",
                "character_config_path": "config",
                "content_sha256": digest,
            },
        ),
    )
    raw_action_set = {"actions": [{"ids": ["x"]}]}
    raw_refs = [ref]
    card = CharacterDataCardIR(
        card_id="card",
        entity_ref="avatar:1001",
        profile_id="profile",
        skill_ids=("skill",),
        skill_formula_binding_ids=(),
        bounce_policy_ids=(),
        source=IRSource("inventory", "AvatarConfig", "1001", {}),
        action_set=raw_action_set,
        ability_source_graph_refs=raw_refs,
    )
    raw_action_set["actions"][0]["ids"].append("mutated")
    raw_refs.clear()
    retired = _synthetic_retired_source()

    class _RefSubclass(CharacterAbilityGraphRefIR):
        pass

    subclass = _RefSubclass(
        **{field.name: getattr(ref, field.name) for field in fields(CharacterAbilityGraphRefIR)}
    )
    return {
        "action_bound_presentation_admitted_as_audit": binding.action_source_id == "action"
        and binding.binding_kind == "presentation",
        "ordinary_evidence_copied_frozen": binding.relation_source.evidence["json_path"] == "$.Phase"
        and _rejected(lambda: binding.relation_source.evidence.__setitem__("x", 1)),
        "card_containers_copied_frozen": card.action_set["actions"][0]["ids"] == ["x"]
        and bool(card.ability_source_graph_refs)
        and _rejected(lambda: card.action_set["actions"][0]["ids"].append("y")),
        "internal_ref_subclass_rejected": _rejected(
            lambda: replace(card, ability_source_graph_refs=(subclass,))
        ),
        "duplicate_query_result_identity_rejected": _rejected(
            lambda: CharacterAbilitySourceGraphQueryResult(
                status="blocked",
                owner_avatar_id="1001",
                action_id="probe",
                ability_name="",
                action_source_ids=("duplicate", "duplicate"),
                non_gameplay_skill_source_ids=(),
                binding_ids=(),
                definition_ids=(),
                gap_ids=(),
                blocked_reason="probe",
            )
        ),
        "maze_normal_without_trigger_is_typed_retired": _non_gameplay_skill_retired_reason({"SkillTriggerKey": "", "AttackType": "MazeNormal"}) == "maze_normal_without_skill_trigger"
        and retired.raw_attack_type == "MazeNormal"
        and retired.source.evidence["skill_trigger_key"] == "",
        "combat_types_cannot_be_retired": _non_gameplay_skill_retired_reason({"SkillTriggerKey": "", "AttackType": "BPSkill"}) is None
        and _non_gameplay_skill_retired_reason({"SkillTriggerKey": "", "AttackType": "Ultra"}) is None
        and _non_gameplay_skill_retired_reason({"SkillTriggerKey": "", "AttackType": "UnknownCombat"}) is None
        and _rejected(
            lambda: _synthetic_retired_source(attack_type="BPSkill")
        )
        and _rejected(lambda: _synthetic_retired_source(attack_type="Ultra")),
        "retired_row_forgery_rejected": _rejected(
            lambda: replace(retired, row_index=1)
        ),
        "retired_digest_forgery_rejected": _rejected(
            lambda: replace(retired, content_sha256="b" * 64)
        ),
        "retired_attack_forgery_rejected": _rejected(
            lambda: replace(retired, raw_attack_type="BPSkill")
        ),
        "retired_owner_forgery_rejected": _rejected(
            lambda: replace(retired, owner_avatar_id="1002")
        ),
    }


def _avatar_path(config_path: str, camera: bool = False) -> str:
    path = PurePosixPath(config_path)
    prefix = PurePosixPath("Config/ConfigCharacter/Avatar").parts
    if path.parts[: len(prefix)] != prefix or ".." in path.parts:
        raise ValueError("oracle avatar path outside schema")
    suffix = path.parts[len(prefix) :]
    name = suffix[-1]
    if not name.endswith(".json"):
        raise ValueError("oracle avatar path is not JSON")
    stem = name[: -len("_Config.json")] if name.endswith("_Config.json") else name[:-5]
    root = "Config/ConfigAbility/Avatar/Camera" if camera else "Config/ConfigAbility/Avatar"
    return str(PurePosixPath(root).joinpath(*suffix[:-1], stem + ("_Camera.json" if camera else "_Ability.json")))


def _selected_rows(snapshot: Any) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for source in snapshot.sources:
        if source.source_kind != "character_main":
            continue
        evidence = source.source.evidence
        path = evidence["config_source_path"]
        index = evidence["config_row_index"]
        document = json.loads(snapshot.inventory_bytes[path])
        row = document[index]
        if (
            str(row.get("AvatarID")) != source.avatar_id
            or _avatar_path(row.get("JsonPath")) != source.source.source_path
            or evidence["selected_version"] not in {"base", "enhanced"}
        ):
            raise ValueError("oracle S0 inventory selection mismatch")
        rows[source.avatar_id] = {
            "source_id": source.source_id,
            "source_path": path,
            "row_index": index,
            "selected_version": evidence["selected_version"],
            "content_sha256": sha256(snapshot.inventory_bytes[path]).hexdigest(),
            "config_path": row["JsonPath"],
            "ability_path": source.source.source_path,
            "skill_ids": tuple(sorted({str(value) for value in row.get("SkillList") or ()})),
        }
    return rows


def _read(root: Path, path: str, cache: dict[str, Any]) -> Any:
    if path not in cache:
        cache[path] = json.loads((root / path).read_bytes())
    return cache[path]


def _ability_rows(document: Mapping[str, Any]) -> tuple[tuple[int, str], ...]:
    values = document.get("AbilityList")
    return tuple(
        (index, row["Name"])
        for index, row in enumerate(values if isinstance(values, list) else ())
        if isinstance(row, Mapping) and isinstance(row.get("Name"), str) and row["Name"]
    )


def _definition_oracle(root: Path, snapshot: Any, rows: Mapping[str, Mapping[str, Any]]) -> tuple[Counter[tuple[Any, ...]], dict[str, Any]]:
    expected: Counter[tuple[Any, ...]] = Counter()
    cameras: list[str] = []
    for source in snapshot.sources:
        for index, name in _ability_rows(snapshot.documents[source.source.source_path]):
            expected[(source.source_kind, source.avatar_id, source.source.source_path, index, name, source.content_sha256)] += 1
    for avatar_id, row in sorted(rows.items()):
        path = _avatar_path(str(row["config_path"]), camera=True)
        file_path = root / path
        if not file_path.is_file():
            continue
        raw = file_path.read_bytes()
        document = json.loads(raw)
        cameras.append(path)
        for index, name in _ability_rows(document):
            expected[("presentation", avatar_id, path, index, name, sha256(raw).hexdigest())] += 1
    return expected, {"camera_source_count": len(cameras), "camera_sources": cameras}


def _entries(document: Mapping[str, Any], trigger: str) -> tuple[tuple[str, Mapping[str, Any]], ...]:
    values = document.get("SkillList")
    if isinstance(values, list):
        return tuple((f"$.SkillList[{i}]", value) for i, value in enumerate(values) if isinstance(value, Mapping) and value.get("Name") == trigger)
    if isinstance(values, Mapping) and isinstance(values.get(trigger), Mapping):
        return ((f"$.SkillList.{trigger}", values[trigger]),)
    return ()


def _phases(document: Mapping[str, Any], trigger: str) -> tuple[tuple[str, Any], ...]:
    values = document.get("SkillAbilityList")
    if isinstance(values, list):
        return tuple((f"$.SkillAbilityList[{i}]", value) for i, value in enumerate(values) if isinstance(value, Mapping) and value.get("Skill") == trigger)
    if isinstance(values, Mapping) and trigger in values:
        return ((f"$.SkillAbilityList.{trigger}", values[trigger]),)
    return ()


def _names(value: Any) -> tuple[str, ...]:
    result: list[str] = []
    if isinstance(value, str) and value:
        result.append(value)
    elif isinstance(value, list):
        for item in value:
            result.extend(_names(item))
    elif isinstance(value, Mapping):
        for key in ("AbilityName", "PhaseAbility", "PhaseAbilityName"):
            if isinstance(value.get(key), str) and value[key]:
                result.append(value[key])
        for key in ("AbilityList", "AbilityNameList", "PhaseList", "PhaseAbilityList"):
            result.extend(_names(value.get(key)))
    return tuple(dict.fromkeys(result))


def _kinds(row: Mapping[str, Any], entry: Mapping[str, Any]) -> tuple[str, ...]:
    attack = {"Normal": "basic", "BPSkill": "skill", "Ultra": "ultimate", "Talent": "passive", "Passive": "passive", "TalentPassive": "passive", "Maze": "maze", "MazeNormal": "maze"}.get(str(row.get("AttackType") or ""))
    skill = {"Normal": "basic", "Skill": "skill", "Ultra": "ultimate", "Passive": "passive", "Maze": "maze"}.get(str(entry.get("SkillType") or ""))
    use = "passive" if entry.get("UseType") == "Passive" else None
    return tuple(sorted({value for value in (attack, skill, use) if value}))


def _action_key(action: Any) -> tuple[Any, ...]:
    return (
        action.owner_avatar_id,
        action.skill_id,
        action.skill_trigger_key,
        action.action_kind,
        action.levels,
        action.config_source.source_path,
        action.config_source.evidence["json_path"],
        tuple((source.source_path, source.evidence["row_index"], source.evidence["level"]) for source in action.skill_sources),
    )


def _request(source: IRSource, owner: str, action_id: str, skill_id: str) -> tuple[str, ...]:
    return (
        owner,
        action_id,
        skill_id,
        source.raw_id,
        str(source.evidence["binding_kind"]),
        str(source.evidence["relation_ordinal"]),
        source.source_path,
        str(source.evidence["json_path"]),
    )


def _oracle_request(
    owner: str,
    action_id: str,
    skill_id: str,
    raw_id: str,
    binding_kind: str,
    ordinal: int,
    source_path: str,
    json_path: str,
) -> tuple[str, ...]:
    return (
        owner,
        action_id,
        skill_id,
        raw_id,
        binding_kind,
        str(ordinal),
        source_path,
        json_path,
    )


def _actual_outcomes(catalog: CharacterAbilitySourceGraphCatalogIR) -> dict[tuple[str, ...], tuple[Any, ...]]:
    outcomes: dict[tuple[str, ...], tuple[Any, ...]] = {}
    for binding in catalog.bindings:
        key = _request(binding.relation_source, binding.owner_avatar_id, binding.action_source_id, str(binding.relation_source.evidence["skill_id"]))
        outcomes[key] = ("resolved", binding.binding_kind, "", (binding.ability_definition_id,), (), ())
    for gap in catalog.gaps:
        key = _request(gap.source, gap.owner_avatar_id, gap.action_source_id, str(gap.source.evidence["skill_id"]))
        if key in outcomes:
            raise ValueError("oracle observed duplicate production relation outcome")
        outcomes[key] = ("blocked", gap.expected_binding_kind, gap.gap_kind, gap.candidate_definition_ids, gap.candidate_action_source_ids, gap.searched_source_ids)
    return outcomes


def _relationship_oracle(root: Path, snapshot: Any, catalog: CharacterAbilitySourceGraphCatalogIR, selected: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    cache: dict[str, Any] = {}
    shared_ids = tuple(sorted(source.source_id for source in snapshot.sources if source.source_kind == "character_shared"))
    searched = {owner: tuple(sorted((row["source_id"], *shared_ids))) for owner, row in selected.items()}
    tables: list[tuple[str, str, list[Any]]] = []
    table_digests: dict[str, str] = {}
    for path, _entity, id_key in CHARACTER_ACTION_DEFINITION_TABLES:
        document = _read(root, path, cache)
        tables.append((path, id_key, document if isinstance(document, list) else []))
        table_digests[path] = sha256((root / path).read_bytes()).hexdigest()
    expected_actions: set[tuple[Any, ...]] = set()
    expected_retired: set[tuple[Any, ...]] = set()
    pre_gaps: list[tuple[tuple[str, ...], tuple[Any, ...]]] = []
    for owner, selected_row in selected.items():
        config_path = str(selected_row["config_path"])
        config = _read(root, config_path, cache) if (root / config_path).is_file() else None
        for skill_id in selected_row["skill_ids"]:
            groups = [(path, [(i, row) for i, row in enumerate(values) if isinstance(row, Mapping) and str(row.get(id_key)) == skill_id]) for path, id_key, values in tables]
            groups = [(path, values) for path, values in groups if values]
            if not groups:
                key = _oracle_request(owner, "", skill_id, skill_id, "entry", 0, str(selected_row["source_path"]), f"$[{selected_row['row_index']}]")
                pre_gaps.append((key, ("blocked", "entry", "missing_action_source_blocked", (), (), searched[owner])))
                continue
            for path, values in groups:
                variants: dict[str, list[tuple[int, Mapping[str, Any]]]] = defaultdict(list)
                for index, row in values:
                    raw_trigger = row.get("SkillTriggerKey")
                    trigger = str(raw_trigger or "")
                    if not trigger:
                        if (raw_trigger is None or raw_trigger == "") and row.get("AttackType") == "MazeNormal":
                            effect = row.get("SkillEffect")
                            if not isinstance(effect, str):
                                raise ValueError("oracle MazeNormal SkillEffect is not a string")
                            expected_retired.add((owner, skill_id, path, index, "", "MazeNormal", effect, table_digests[path], "maze_normal_without_skill_trigger"))
                            continue
                        key = _oracle_request(owner, "", skill_id, skill_id, "entry", 0, path, f"$[{index}]")
                        pre_gaps.append((key, ("blocked", "entry", "missing_action_source_blocked", (), (), searched[owner])))
                    else:
                        variants[trigger].append((index, row))
                for trigger, variant in variants.items():
                    levels = tuple(int(row.get("Level", 1)) for _, row in variant)
                    if len(levels) != len(set(levels)):
                        key = _oracle_request(owner, "", skill_id, skill_id, "entry", 0, path, "$")
                        pre_gaps.append((key, ("blocked", "entry", "missing_action_source_blocked", (), (), searched[owner])))
                        continue
                    ordered = tuple(sorted(variant, key=lambda item: (int(item[1].get("Level", 1)), item[0])))
                    if not isinstance(config, Mapping):
                        key = _oracle_request(owner, "", skill_id, skill_id, "entry", 0, str(selected_row["source_path"]), f"$[{selected_row['row_index']}]")
                        pre_gaps.append((key, ("blocked", "entry", "missing_action_source_blocked", (), (), searched[owner])))
                        continue
                    entry_rows = _entries(config, trigger)
                    if not entry_rows:
                        key = _oracle_request(owner, "", skill_id, trigger, "entry", 0, config_path, "$")
                        pre_gaps.append((key, ("blocked", "entry", "missing_action_source_blocked", (), (), searched[owner])))
                        continue
                    ordered_levels = tuple(int(row.get("Level", 1)) for _, row in ordered)
                    for skill_path, entry in entry_rows:
                        for kind in {kind for _, row in ordered for kind in _kinds(row, entry)}:
                            expected_actions.add((owner, skill_id, trigger, kind, ordered_levels, config_path, skill_path, tuple((path, index, int(row.get("Level", 1))) for index, row in ordered)))
    actual_actions = {_action_key(action): action for action in catalog.action_sources}
    action_sets_match = set(actual_actions) == expected_actions
    actual_retired = {(source.owner_avatar_id, source.skill_id, source.source.source_path, source.row_index, source.source.evidence["skill_trigger_key"], source.raw_attack_type, source.raw_skill_effect, source.content_sha256, source.retired_reason) for source in catalog.non_gameplay_skill_sources}
    retired_sets_match = actual_retired == expected_retired
    expected: dict[tuple[str, ...], tuple[Any, ...]] = {}

    def add(key: tuple[str, ...], value: tuple[Any, ...]) -> None:
        if key in expected:
            raise ValueError(f"oracle duplicate request:{key}")
        expected[key] = value

    for key, value in pre_gaps:
        add(key, value)
    definitions_by_name: dict[str, list[Any]] = defaultdict(list)
    for item in catalog.definitions:
        definitions_by_name[item.ability_name].append(item)
    actions_by_public: dict[str, list[Any]] = defaultdict(list)
    for action in catalog.action_sources:
        actions_by_public[action.action_id].append(action)
    used_definition_ids: set[str] = set()
    repeated_phase_relation_count = 0
    repeated_phase_action_name_group_count = 0
    entry_only_action_count = 0
    resolvable_actions: list[Any] = []
    for _action_id, actions in actions_by_public.items():
        for owner in sorted({action.owner_avatar_id for action in actions}):
            own = sorted((action for action in actions if action.owner_avatar_id == owner), key=lambda item: item.action_source_id)
            if len(own) == 1:
                resolvable_actions.append(own[0])
                continue
            kinds = {action.action_kind for action in own}
            gap_kind = "cross_kind_blocked" if len(kinds) > 1 else "duplicate_action_source_blocked"
            source_action = own[0]
            key = _oracle_request(owner, "", source_action.skill_id, source_action.skill_trigger_key, "entry", 0, source_action.config_source.source_path, str(source_action.config_source.evidence["json_path"]))
            add(key, ("blocked", "entry", gap_kind, (), tuple(action.action_source_id for action in own), searched[owner]))
    for action in sorted(resolvable_actions, key=lambda item: item.action_source_id):
        config = _read(root, action.config_source.source_path, cache)
        entry_rows = _entries(config, action.skill_trigger_key)
        if len(entry_rows) != 1 or entry_rows[0][0] != action.config_source.evidence["json_path"]:
            raise ValueError("oracle action config selection mismatch")
        skill_path, entry = entry_rows[0]
        phase_rows = _phases(config, action.skill_trigger_key)
        entry_name = entry.get("EntryAbility") if isinstance(entry.get("EntryAbility"), str) else ""
        requests: list[tuple[str, str, int, str]] = []
        if action.action_kind == "passive":
            names = ([(entry_name, f"{skill_path}.EntryAbility")] if entry_name else []) + [(name, path) for path, value in phase_rows for name in _names(value)]
            requests.extend((name, "passive", index, path) for index, (name, path) in enumerate(names))
            if not names:
                raw = f"{action.skill_trigger_key}:PassiveAbility"
                key = _oracle_request(action.owner_avatar_id, action.action_source_id, action.skill_id, raw, "passive", 0, action.config_source.source_path, f"{skill_path}.EntryAbility|$.SkillAbilityList")
                add(key, ("blocked", "passive", "missing_phase_blocked", (), (), searched[action.owner_avatar_id]))
        else:
            if entry_name:
                requests.append((entry_name, "entry", 0, f"{skill_path}.EntryAbility"))
            else:
                raw = f"{action.skill_trigger_key}:EntryAbility"
                key = _oracle_request(action.owner_avatar_id, action.action_source_id, action.skill_id, raw, "entry", 0, action.config_source.source_path, f"{skill_path}.EntryAbility")
                add(key, ("blocked", "entry", "missing_entry_blocked", (), (), searched[action.owner_avatar_id]))
            if entry_name and not phase_rows:
                entry_only_action_count += 1
            ordinal = 0
            for path, value in phase_rows:
                for name in _names(value):
                    if name != entry_name:
                        requests.append((name, "phase", ordinal, path))
                        ordinal += 1
        phase_counts = Counter(name for name, kind, _ordinal, _path in requests if kind == "phase")
        repeated_phase_action_name_group_count += sum(count > 1 for count in phase_counts.values())
        repeated_phase_relation_count += sum(count for count in phase_counts.values() if count > 1)
        for name, expected_kind, ordinal, path in requests:
            candidates = definitions_by_name.get(name, ())
            gameplay = tuple(item for item in candidates if item.definition_kind in {"character_main", "character_shared"} and item.owner_avatar_id in {"", action.owner_avatar_id})
            presentation = tuple(item for item in candidates if item.definition_kind == "presentation" and item.owner_avatar_id == action.owner_avatar_id)
            foreign = tuple(item for item in candidates if item.owner_avatar_id not in {"", action.owner_avatar_id})
            if len(gameplay) > 1:
                key = _oracle_request(action.owner_avatar_id, action.action_source_id, action.skill_id, name, expected_kind, ordinal, action.config_source.source_path, path)
                add(key, ("blocked", expected_kind, "ambiguous_binding_blocked", tuple(sorted(item.definition_id for item in gameplay)), (), searched[action.owner_avatar_id]))
            elif gameplay:
                item = gameplay[0]
                key = _oracle_request(action.owner_avatar_id, action.action_source_id, action.skill_id, name, expected_kind, ordinal, action.config_source.source_path, path)
                add(key, ("resolved", expected_kind, "", (item.definition_id,), (), ()))
                used_definition_ids.add(item.definition_id)
            elif len(presentation) > 1:
                key = _oracle_request(action.owner_avatar_id, action.action_source_id, action.skill_id, name, "presentation", ordinal, action.config_source.source_path, path)
                add(key, ("blocked", "presentation", "ambiguous_binding_blocked", tuple(sorted(item.definition_id for item in presentation)), (), searched[action.owner_avatar_id]))
            elif presentation:
                item = presentation[0]
                key = _oracle_request(action.owner_avatar_id, action.action_source_id, action.skill_id, name, "presentation", ordinal, action.config_source.source_path, path)
                add(key, ("resolved", "presentation", "", (item.definition_id,), (), ()))
                used_definition_ids.add(item.definition_id)
            elif foreign:
                key = _oracle_request(action.owner_avatar_id, action.action_source_id, action.skill_id, name, expected_kind, ordinal, action.config_source.source_path, path)
                add(key, ("blocked", expected_kind, "cross_character_blocked", tuple(sorted(item.definition_id for item in foreign)), (), searched[action.owner_avatar_id]))
            else:
                key = _oracle_request(action.owner_avatar_id, action.action_source_id, action.skill_id, name, expected_kind, ordinal, action.config_source.source_path, path)
                add(key, ("blocked", expected_kind, "source_gap_blocked", (), (), searched[action.owner_avatar_id]))
    presentation_groups: dict[tuple[str, str], list[Any]] = defaultdict(list)
    gameplay_groups: dict[tuple[str, str], list[Any]] = defaultdict(list)
    graph_by_source = {graph.source_id: graph for graph in catalog.graphs}
    for item in catalog.definitions:
        if item.definition_kind == "presentation":
            presentation_groups[(item.owner_avatar_id, item.ability_name)].append(item)
        else:
            gameplay_groups[(graph_by_source[item.source_id].graph_id, item.ability_name)].append(item)
    for (owner, name), items in presentation_groups.items():
        remaining = sorted((item for item in items if item.definition_id not in used_definition_ids), key=lambda item: item.definition_id)
        if not remaining:
            continue
        item = remaining[0]
        key = _oracle_request(owner, "", "", name, "presentation", 0, item.source.source_path, str(item.source.evidence["json_path"]))
        value = ("resolved", "presentation", "", (item.definition_id,), (), ()) if len(remaining) == 1 else ("blocked", "presentation", "ambiguous_binding_blocked", tuple(item.definition_id for item in remaining), (), searched[owner])
        add(key, value)
    for (graph_id, name), items in gameplay_groups.items():
        remaining = sorted((item for item in items if item.definition_id not in used_definition_ids), key=lambda item: item.definition_id)
        if not remaining:
            continue
        item = remaining[0]
        owner = item.owner_avatar_id
        key = _oracle_request(owner, "", "", name, "standalone", 0, item.source.source_path, str(item.source.evidence["json_path"]))
        searched_ids = searched[owner] if owner else shared_ids
        value = ("resolved", "standalone", "", (item.definition_id,), (), ()) if len(remaining) == 1 else ("blocked", "standalone", "ambiguous_binding_blocked", tuple(item.definition_id for item in remaining), (), searched_ids)
        add(key, value)
    action_collision_shapes = [{"action_id": action_id, "owner_candidate_counts": dict(sorted(counts.items())), "all_owners_unique": all(count == 1 for count in counts.values())} for action_id, actions in sorted(actions_by_public.items()) if len((counts := Counter(action.owner_avatar_id for action in actions))) > 1]
    actions_by_source_id = {action.action_source_id: action for action in catalog.action_sources}
    cross_character_shapes = []
    for gap in (item for item in catalog.gaps if item.gap_kind == "cross_character_blocked"):
        relevant = [item for item in definitions_by_name.get(gap.requested_ability_name, ()) if (item.definition_kind == "presentation") == (gap.expected_binding_kind == "presentation")]; refs = ([(source_id, actions_by_source_id[source_id].owner_avatar_id) for source_id in gap.candidate_action_source_ids] if gap.candidate_action_source_ids else [(item.definition_id, item.owner_avatar_id) for item in relevant])
        own_ids = [source_id for source_id, owner in refs if owner in ({gap.owner_avatar_id} if gap.candidate_action_source_ids else {"", gap.owner_avatar_id})]; foreign_ids = [source_id for source_id, owner in refs if owner not in {"", gap.owner_avatar_id}]
        shape = "owner_unique" if len(own_ids) == 1 else "owner_ambiguous" if own_ids else "foreign_only" if foreign_ids else "no_candidate"
        cross_character_shapes.append({"gap_id": gap.gap_id, "owner_avatar_id": gap.owner_avatar_id, "expected_binding_kind": gap.expected_binding_kind, "requested_ability_name": gap.requested_ability_name, "source_path": gap.source.source_path, "json_path": gap.source.evidence["json_path"], "own_candidate_ids": own_ids, "foreign_candidate_ids": foreign_ids, "shape": shape})
    actual = _actual_outcomes(catalog)
    return {
        "ok": action_sets_match and retired_sets_match and actual == expected,
        "action_source_set_matches": action_sets_match,
        "retired_source_set_matches": retired_sets_match,
        "retired_source_count": len(actual_retired),
        "retired_attack_type_counts": dict(sorted(Counter(item[5] for item in actual_retired).items())),
        "retired_skill_effect_counts": dict(sorted(Counter(item[6] for item in actual_retired).items())),
        "missing_expected_retired_sources": len(expected_retired - actual_retired),
        "unexpected_production_retired_sources": len(actual_retired - expected_retired),
        "expected_relation_count": len(expected),
        "actual_relation_count": len(actual),
        "checked_gap_count": sum(value[0] == "blocked" for value in expected.values()),
        "unique_gameplay_resolution_count": sum(value[0] == "resolved" and value[1] in GAMEPLAY_KINDS for value in expected.values()),
        "repeated_phase_relation_count": repeated_phase_relation_count,
        "repeated_phase_action_name_group_count": repeated_phase_action_name_group_count,
        "entry_only_action_count": entry_only_action_count,
        "independent_relation_parse_count": len(cache),
        "missing_expected_requests": len(set(expected) - set(actual)),
        "unexpected_production_requests": len(set(actual) - set(expected)),
        "mismatched_outcomes": sum(expected[key] != actual[key] for key in set(expected) & set(actual)),
        "public_action_cross_owner_shapes": action_collision_shapes,
        "cross_character_gap_shapes": cross_character_shapes,
        "cross_character_gaps_foreign_only": all(item["shape"] == "foreign_only" for item in cross_character_shapes),
    }


def _replace_graph(catalog: Any, graph_id: str, **changes: Any) -> tuple[Any, ...]:
    return tuple(replace(graph, **changes) if graph.graph_id == graph_id else graph for graph in catalog.graphs)


def _negative_matrix(catalog: CharacterAbilitySourceGraphCatalogIR, cards: tuple[Any, ...]) -> dict[str, bool]:
    query = CharacterAbilitySourceGraphQuery(catalog)
    unique_action = next(action for action in catalog.action_sources if len([item for item in catalog.action_sources if item.action_id == action.action_id]) == 1 and query.query_action(action.owner_avatar_id, action.action_id).status == "resolved")
    action_result = query.query_action(unique_action.owner_avatar_id, unique_action.action_id)
    gameplay_binding = next(binding for binding in catalog.bindings if binding.binding_id in action_result.binding_ids and binding.binding_kind in GAMEPLAY_KINDS)
    gameplay_definition = next(item for item in catalog.definitions if item.definition_id == gameplay_binding.ability_definition_id)
    other_owner = next(source.avatar_id for source in catalog.sources if source.source_kind == "character_main" and source.avatar_id != unique_action.owner_avatar_id)
    duplicate_query = CharacterAbilitySourceGraphQuery(catalog)
    duplicate_query._actions_by_action_id = {**duplicate_query._actions_by_action_id, unique_action.action_id: (unique_action, replace(unique_action, action_source_id=unique_action.action_source_id + ":probe"))}
    cross_kind_query = CharacterAbilitySourceGraphQuery(catalog)
    cross_kind_query._actions_by_action_id = {**cross_kind_query._actions_by_action_id, unique_action.action_id: (unique_action, replace(unique_action, action_source_id=unique_action.action_source_id + ":kind", action_kind="passive" if unique_action.action_kind != "passive" else "skill"))}
    foreign_config = IRSource(unique_action.config_source.source_path, unique_action.config_source.raw_type, unique_action.config_source.raw_id, {**unique_action.config_source.evidence, "avatar_id": other_owner}); foreign_rows = tuple(IRSource(source.source_path, source.raw_type, source.raw_id, {**source.evidence, "avatar_id": other_owner}) for source in unique_action.skill_sources); foreign_action = replace(unique_action, action_source_id=unique_action.action_source_id + ":foreign", owner_avatar_id=other_owner, config_source=foreign_config, skill_sources=foreign_rows)
    owner_first_query = CharacterAbilitySourceGraphQuery(catalog); owner_first_query._actions_by_action_id = {**owner_first_query._actions_by_action_id, unique_action.action_id: (unique_action, foreign_action)}
    same_kind_name = "p9_s1_same_kind_candidate_probe"
    same_kind_source = IRSource(gameplay_definition.source.source_path, gameplay_definition.source.raw_type, same_kind_name, gameplay_definition.source.evidence)
    same_kind_a = replace(gameplay_definition, definition_id="p9_s1_same_kind_definition:a", ability_name=same_kind_name, source=same_kind_source)
    same_kind_b = replace(same_kind_a, definition_id="p9_s1_same_kind_definition:b")
    ambiguous_query = CharacterAbilitySourceGraphQuery(catalog)
    ambiguous_query._definitions_by_name = {**ambiguous_query._definitions_by_name, same_kind_name: (same_kind_a, same_kind_b)}
    presentation = next(item for item in catalog.definitions if item.definition_kind == "presentation")
    presentation_name = "p9_s1_presentation_only_probe"
    presentation_source = IRSource(presentation.source.source_path, presentation.source.raw_type, presentation_name, {**presentation.source.evidence, "avatar_id": unique_action.owner_avatar_id})
    presentation_probe = replace(presentation, definition_id="p9_s1_presentation_definition", owner_avatar_id=unique_action.owner_avatar_id, ability_name=presentation_name, source=presentation_source)
    presentation_query = CharacterAbilitySourceGraphQuery(catalog)
    presentation_query._definitions_by_name = {**presentation_query._definitions_by_name, presentation_name: (presentation_probe,)}
    graph = next(item for item in catalog.graphs if unique_action.action_source_id in item.action_source_ids)
    graph_by_id = {item.graph_id: item for item in catalog.graphs}
    searched_ids = tuple(sorted({graph.source_id, *(graph_by_id[graph_id].source_id for graph_id in graph.shared_graph_ids)}))
    gap_name = "p9_s1_presentation_gap_probe"
    gap_path = str(gameplay_binding.relation_source.evidence["json_path"])
    gap_ordinal = 0
    gap_relation_id = character_ability_stable_id("character_ability_relation", graph.graph_id, unique_action.owner_avatar_id, unique_action.action_source_id, unique_action.skill_id, gap_name, "presentation", gap_ordinal, unique_action.config_source.source_path, gap_path)
    presentation_gap = CharacterAbilityBindingGapIR(
        gap_id=character_ability_stable_id("character_ability_binding_gap", gap_relation_id, "source_gap_blocked"),
        relation_id=gap_relation_id,
        graph_id=graph.graph_id,
        owner_avatar_id=unique_action.owner_avatar_id,
        action_source_id=unique_action.action_source_id,
        requested_ability_name=gap_name,
        expected_binding_kind="presentation",
        ordinal=gap_ordinal,
        gap_kind="source_gap_blocked",
        candidate_definition_ids=(),
        candidate_action_source_ids=(),
        searched_source_ids=searched_ids,
        source=IRSource(unique_action.config_source.source_path, "CharacterAbilityRelation", gap_name, {"relation_id": gap_relation_id, "graph_id": graph.graph_id, "owner_avatar_id": unique_action.owner_avatar_id, "action_source_id": unique_action.action_source_id, "skill_id": unique_action.skill_id, "binding_kind": "presentation", "relation_ordinal": gap_ordinal, "json_path": gap_path, "content_sha256": gameplay_binding.relation_source.evidence["content_sha256"]}),
        blocked_reason="synthetic_presentation_audit_gap",
    )
    presentation_gap_catalog = replace(catalog, gaps=(*catalog.gaps, presentation_gap), graphs=_replace_graph(catalog, graph.graph_id, gap_ids=(*graph.gap_ids, presentation_gap.gap_id)))
    retired_query_ok = all(
        (result := query.query_action(source.owner_avatar_id, f"avatar_skill:{source.skill_id}")).status == "blocked"
        and result.blocked_reason == "non_gameplay_skill_retired"
        and result.non_gameplay_skill_source_ids == (source.non_gameplay_skill_source_id,)
        for source in catalog.non_gameplay_skill_sources
    )
    retired = catalog.non_gameplay_skill_sources[0] if catalog.non_gameplay_skill_sources else None
    retired_membership_rejected = retired_omission_rejected = retired_gameplay_overlap_rejected = retired_gap_overlap_rejected = retired is None
    if retired is not None:
        retired_graph = graph_by_id[retired.graph_id]
        other_graph = next((item for item in catalog.graphs if item.source_kind == "character_main" and item.graph_id != retired.graph_id), None)
        if other_graph is not None:
            moved_graphs = tuple(replace(item, non_gameplay_skill_source_ids=tuple(value for value in item.non_gameplay_skill_source_ids if value != retired.non_gameplay_skill_source_id)) if item.graph_id == retired.graph_id else replace(item, non_gameplay_skill_source_ids=(*item.non_gameplay_skill_source_ids, retired.non_gameplay_skill_source_id)) if item.graph_id == other_graph.graph_id else item for item in catalog.graphs)
            retired_membership_rejected = _rejected(lambda: replace(catalog, graphs=moved_graphs))
        retired_omission_rejected = _rejected(lambda: replace(catalog, non_gameplay_skill_sources=tuple(item for item in catalog.non_gameplay_skill_sources if item.non_gameplay_skill_source_id != retired.non_gameplay_skill_source_id), graphs=_replace_graph(catalog, retired.graph_id, non_gameplay_skill_source_ids=tuple(value for value in retired_graph.non_gameplay_skill_source_ids if value != retired.non_gameplay_skill_source_id))))
        overlap_action = next((item for item in catalog.action_sources if item.action_source_id in retired_graph.action_source_ids), None)
        if overlap_action is not None:
            overlap = _synthetic_retired_source(graph_id=retired.graph_id, owner=retired.owner_avatar_id, skill_id=overlap_action.skill_id, skill_effect=retired.raw_skill_effect, row_index=retired.row_index, digest=retired.content_sha256, source_path=retired.source.source_path)
            retired_gameplay_overlap_rejected = _rejected(lambda: replace(catalog, non_gameplay_skill_sources=(*catalog.non_gameplay_skill_sources, overlap), graphs=_replace_graph(catalog, retired.graph_id, non_gameplay_skill_source_ids=(*retired_graph.non_gameplay_skill_source_ids, overlap.non_gameplay_skill_source_id))))
        retired_path = f"$[{retired.row_index}]"
        retired_relation_id = character_ability_stable_id("character_ability_relation", retired.graph_id, retired.owner_avatar_id, "", retired.skill_id, retired.skill_id, "entry", 0, retired.source.source_path, retired_path)
        retired_gap = CharacterAbilityBindingGapIR(character_ability_stable_id("character_ability_binding_gap", retired_relation_id, "missing_action_source_blocked"), retired_relation_id, retired.graph_id, retired.owner_avatar_id, "", "", "entry", 0, "missing_action_source_blocked", (), (), (retired_graph.source_id,), IRSource(retired.source.source_path, "CharacterAbilityRelation", retired.skill_id, {"relation_id": retired_relation_id, "graph_id": retired.graph_id, "owner_avatar_id": retired.owner_avatar_id, "action_source_id": "", "skill_id": retired.skill_id, "binding_kind": "entry", "relation_ordinal": 0, "json_path": retired_path, "content_sha256": retired.content_sha256}), "synthetic_retired_gap_overlap")
        retired_gap_overlap_rejected = _rejected(lambda: replace(catalog, gaps=(*catalog.gaps, retired_gap), graphs=_replace_graph(catalog, retired.graph_id, gap_ids=(*retired_graph.gap_ids, retired_gap.gap_id))))
    definition = catalog.definitions[0]
    forged_definition_source = IRSource(definition.source.source_path, definition.source.raw_type, definition.source.raw_id, {**definition.source.evidence, "content_sha256": "f" * 64})
    digest_rejected = _rejected(lambda: replace(catalog, definitions=tuple(replace(item, source=forged_definition_source) if item.definition_id == definition.definition_id else item for item in catalog.definitions)))
    action = catalog.action_sources[0]
    level_source = action.skill_sources[0]
    forged_level_source = IRSource(level_source.source_path, level_source.raw_type, level_source.raw_id, {**level_source.evidence, "row_index": int(level_source.evidence["row_index"]) + 1})
    row_rejected = _rejected(lambda: replace(catalog, action_sources=tuple(replace(item, skill_sources=(forged_level_source, *item.skill_sources[1:])) if item.action_source_id == action.action_source_id else item for item in catalog.action_sources)))
    binding = catalog.bindings[0]
    forged_relation = IRSource(binding.relation_source.source_path, binding.relation_source.raw_type, binding.relation_source.raw_id, {**binding.relation_source.evidence, "json_path": str(binding.relation_source.evidence["json_path"]) + ".forged"})
    relation_rejected = _rejected(lambda: replace(catalog, bindings=tuple(replace(item, relation_source=forged_relation) if item.binding_id == binding.binding_id else item for item in catalog.bindings)))
    typed_binding = next(item for item in catalog.bindings if item.binding_kind in {"entry", "phase"})
    conflict_source = IRSource(typed_binding.relation_source.source_path, typed_binding.relation_source.raw_type, typed_binding.relation_source.raw_id, {**typed_binding.relation_source.evidence, "binding_kind": "passive"})
    entry_passive = _rejected(lambda: replace(catalog, bindings=tuple(replace(item, binding_kind="passive", relation_source=conflict_source) if item.binding_id == typed_binding.binding_id else item for item in catalog.bindings)))
    card = next(item for item in cards if item.ability_source_graph_refs)
    ref = card.ability_source_graph_refs[0]
    forged_ref_source = IRSource(ref.source.source_path, ref.source.raw_type, ref.source.raw_id, {**ref.source.evidence, "row_index": int(ref.source.evidence["row_index"]) + 1})
    forged_ref = replace(ref, source=forged_ref_source)
    ref_rejected = _rejected(lambda: CanonicalIR(version="forged_ref", character_data_cards=tuple(replace(item, ability_source_graph_refs=(forged_ref, *item.ability_source_graph_refs[1:])) if item.card_id == card.card_id else item for item in cards), character_ability_source_graph_catalog=catalog))
    extra_skill_rejected = _rejected(lambda: CanonicalIR(version="extra_skill", character_data_cards=tuple(replace(item, skill_ids=(*item.skill_ids, "validation_extra_skill")) if item.card_id == card.card_id else item for item in cards), character_ability_source_graph_catalog=catalog))
    reordered = replace(catalog, sources=tuple(reversed(catalog.sources)), relation_source_digests=dict(reversed(tuple(catalog.relation_source_digests.items()))), definitions=tuple(reversed(catalog.definitions)), action_sources=tuple(reversed(catalog.action_sources)), non_gameplay_skill_sources=tuple(reversed(catalog.non_gameplay_skill_sources)), bindings=tuple(reversed(catalog.bindings)), gaps=tuple(reversed(catalog.gaps)), graphs=tuple(reversed(catalog.graphs)), build_counters=dict(reversed(tuple(catalog.build_counters.items()))))
    alternate_counters = replace(catalog, build_counters={**catalog.build_counters, "snapshot_build_count": 999})

    class _DefinitionSubclass(CharacterAbilityDefinitionIR):
        pass

    subclass = _DefinitionSubclass(**{field.name: getattr(definition, field.name) for field in fields(CharacterAbilityDefinitionIR)})
    return {
        "synthetic_same_kind_candidates_ambiguous": ambiguous_query.query_standalone_ability(unique_action.owner_avatar_id, same_kind_name).blocked_reason == "ambiguous_binding_blocked",
        "synthetic_missing_ability_source_gap": query.query_standalone_ability(unique_action.owner_avatar_id, "p9_s1_absent_ability_probe").blocked_reason == "source_gap_blocked",
        "synthetic_presentation_gap_does_not_block_gameplay": CharacterAbilitySourceGraphQuery(presentation_gap_catalog).query_action(unique_action.owner_avatar_id, unique_action.action_id).status == "resolved",
        "synthetic_presentation_not_gameplay": presentation_query.query_standalone_ability(unique_action.owner_avatar_id, presentation_name).blocked_reason == "wrong_kind_blocked",
        "retired_action_query_is_explicit": retired_query_ok,
        "retired_graph_membership_forgery_rejected": retired_membership_rejected,
        "retired_selected_skill_omission_rejected": retired_omission_rejected,
        "retired_gameplay_overlap_rejected": retired_gameplay_overlap_rejected,
        "retired_gap_overlap_rejected": retired_gap_overlap_rejected,
        "entry_passive_conflict_rejected": entry_passive,
        "cross_owner_query_blocked": query.query_action(other_owner, unique_action.action_id).blocked_reason == "cross_character_blocked",
        "owner_unique_candidate_resolves_before_foreign": owner_first_query.query_action(unique_action.owner_avatar_id, unique_action.action_id).status == "resolved", "catalog_action_ambiguity_is_owner_scoped": not _ambiguous_character_action_source_ids((unique_action, foreign_action)) and _ambiguous_character_action_source_ids((unique_action, replace(unique_action, action_source_id=unique_action.action_source_id + ":same_owner"))) == frozenset({unique_action.action_source_id, unique_action.action_source_id + ":same_owner"}),
        "duplicate_query_blocked": duplicate_query.query_action(unique_action.owner_avatar_id, unique_action.action_id).blocked_reason == "duplicate_action_source_blocked",
        "cross_kind_query_blocked": cross_kind_query.query_action(unique_action.owner_avatar_id, unique_action.action_id).blocked_reason == "cross_kind_blocked",
        "content_digest_forgery_rejected": digest_rejected,
        "row_index_forgery_rejected": row_rejected,
        "relation_path_forgery_rejected": relation_rejected,
        "card_ref_source_forgery_rejected": ref_rejected,
        "card_extra_skill_rejected": extra_skill_rejected,
        "source_set_mismatch_rejected": not same_character_ability_s0_sources(catalog.sources, catalog.sources[:-1]),
        "input_reorder_stable": reordered.catalog_id == catalog.catalog_id,
        "build_path_counters_identity_neutral": alternate_counters.catalog_id == catalog.catalog_id,
        "internal_definition_subclass_rejected": _rejected(lambda: replace(catalog, definitions=(subclass, *catalog.definitions[1:]))),
    }


def _direct_regressions(root: Path, lowerer: TBGDLowering, catalog: CharacterAbilitySourceGraphCatalogIR, cards: tuple[Any, ...]) -> dict[str, Any]:
    query = CharacterAbilitySourceGraphQuery(catalog)
    definitions = build_character_action_definition_ir(root)
    definitions_by_row = {(item.source.source_path, item.source.evidence["row_index"], item.level, item.action_id): item for item in definitions}

    def has_definition(action: Any) -> bool:
        return all((source.source_path, source.evidence["row_index"], source.evidence["level"], action.action_id) in definitions_by_row for source in action.skill_sources)

    bindings_by_action: dict[str, list[Any]] = defaultdict(list)
    for binding in catalog.bindings:
        if binding.action_source_id:
            bindings_by_action[binding.action_source_id].append(binding)
    unique_actions = [action for action in catalog.action_sources if has_definition(action) and len([item for item in catalog.action_sources if item.action_id == action.action_id]) == 1 and query.query_action(action.owner_avatar_id, action.action_id).status == "resolved"]
    camera_action = min(
        (
            action
            for action in unique_actions
            if {binding.binding_kind for binding in bindings_by_action[action.action_source_id]} & GAMEPLAY_KINDS
            and any(binding.binding_kind == "presentation" for binding in bindings_by_action[action.action_source_id])
        ),
        key=lambda action: (
            sum(binding.binding_kind in GAMEPLAY_KINDS for binding in bindings_by_action[action.action_source_id]),
            action.action_id,
        ),
    )
    graphs_by_owner = {graph.owner_avatar_id: graph for graph in catalog.graphs if graph.source_kind == "character_main"}
    enhanced_action = min(
        (action for action in unique_actions if graphs_by_owner[action.owner_avatar_id].inventory_source.evidence["selected_version"] == "enhanced"),
        key=lambda action: (
            sum(binding.binding_kind in GAMEPLAY_KINDS for binding in bindings_by_action[action.action_source_id]),
            action.action_id,
        ),
    )
    def run(action: Any, *, lower_tasks: bool = False) -> tuple[Any, list[Any], Any]:
        source = action.skill_sources[-1]
        definition = definitions_by_row[(source.source_path, source.evidence["row_index"], source.evidence["level"], action.action_id)]
        return lowerer._avatar_action_binding(definition, lower_tasks=lower_tasks)

    camera_binding, camera_phases, camera_lowered = run(camera_action)
    enhanced_binding, enhanced_phases, enhanced_lowered = run(enhanced_action)
    gameplay_probe = next(item for item in catalog.definitions if item.definition_kind in {"character_main", "character_shared"}); presentation_probe = next(item for item in catalog.definitions if item.definition_kind == "presentation")
    ambiguous_probe = replace(gameplay_probe, definition_id=gameplay_probe.definition_id + ":ambiguous_probe")
    original_names = lowering_module._trigger_ability_names_from_value; original_selector = lowering_module._select_trigger_ability_candidate; original_phase_lowering = lowerer._lower_ability_phase_tasks
    phase_lowering_calls: list[str] = []
    def phase_lowering_probe(**_kwargs: Any) -> Any: phase_lowering_calls.append("called"); return lowering_module._LoweredAbility()
    try:
        lowering_module._trigger_ability_names_from_value = lambda _value: ["p9_s1_missing_trigger_child_probe"]; lowerer._lower_ability_phase_tasks = phase_lowering_probe
        missing_child_result = run(camera_action, lower_tasks=True)
        lowering_module._select_trigger_ability_candidate = lambda _candidates: original_selector((gameplay_probe, ambiguous_probe)); ambiguous_child_result = run(camera_action, lower_tasks=True)
    finally:
        lowering_module._trigger_ability_names_from_value = original_names; lowering_module._select_trigger_ability_candidate = original_selector
        lowerer._lower_ability_phase_tasks = original_phase_lowering
    def formal_channels_empty(result: tuple[Any, list[Any], Any]) -> bool: binding, phases, lowered = result; return binding.coverage_status == "blocked" and binding.blocked_reason == "source_graph_definition_resolution_blocked" and not phases and all(not getattr(lowered, item.name) for item in fields(lowered))
    trigger_missing_ok = formal_channels_empty(missing_child_result); trigger_ambiguous_ok = original_selector((gameplay_probe, ambiguous_probe)) is None and formal_channels_empty(ambiguous_child_result)
    trigger_priority_ok = original_selector((gameplay_probe, presentation_probe)) is gameplay_probe and original_selector((presentation_probe,)) is presentation_probe
    retired_direct_ok = True
    retired_blocked_reason = ""
    if catalog.non_gameplay_skill_sources:
        retired_source = catalog.non_gameplay_skill_sources[0]
        retired_definition = next((item for item in definitions if item.action_id == f"avatar_skill:{retired_source.skill_id}" and item.source.source_path == retired_source.source.source_path and item.source.evidence["row_index"] == retired_source.row_index), None)
        retired_direct_ok = retired_definition is not None
        if retired_definition is not None:
            retired_binding, retired_phases, retired_lowered = lowerer._avatar_action_binding(retired_definition, lower_tasks=False)
            retired_blocked_reason = retired_binding.blocked_reason
            retired_direct_ok = retired_binding.coverage_status == "blocked" and retired_blocked_reason == "non_gameplay_skill_retired" and not retired_phases and not retired_lowered.ability_tasks
    camera_names = {binding.ability_name for binding in bindings_by_action[camera_action.action_source_id] if binding.binding_kind == "presentation"}
    gameplay_ids = {binding.ability_definition_id for binding in bindings_by_action[camera_action.action_source_id] if binding.binding_kind in GAMEPLAY_KINDS}
    phase_definition_ids = {phase.source.evidence["source_graph_definition_id"] for phase in camera_phases}
    enhanced_graph = graphs_by_owner[enhanced_action.owner_avatar_id]
    enhanced_card = next(card for card in cards if card.entity_ref == f"avatar:{enhanced_action.owner_avatar_id}")
    return {
        "ok": camera_binding.coverage_status == "executable"
        and enhanced_binding.coverage_status == "executable"
        and camera_names.issubset(set(camera_binding.source.evidence["client_only_ability_names"]))
        and camera_names.isdisjoint({phase.ability_name for phase in camera_phases})
        and gameplay_ids.issubset(phase_definition_ids)
        and enhanced_card.source.source_path == enhanced_graph.inventory_source.source_path
        and enhanced_card.source.evidence["row_index"] == enhanced_graph.inventory_source.evidence["row_index"]
        and not camera_lowered.ability_tasks
        and not enhanced_lowered.ability_tasks
        and retired_direct_ok
        and trigger_missing_ok and trigger_ambiguous_ok and trigger_priority_ok and not phase_lowering_calls,
        "camera_gameplay_action_id": camera_action.action_id,
        "camera_gameplay_owner": camera_action.owner_avatar_id,
        "camera_audit_names": sorted(camera_names),
        "camera_gameplay_phase_count": len(camera_phases),
        "enhanced_action_id": enhanced_action.action_id,
        "enhanced_owner": enhanced_action.owner_avatar_id,
        "enhanced_selected_version": enhanced_graph.inventory_source.evidence["selected_version"],
        "enhanced_phase_count": len(enhanced_phases),
        "task_lowering_count": len(camera_lowered.ability_tasks) + len(enhanced_lowered.ability_tasks),
        "retired_action_blocked_reason": retired_blocked_reason,
        "trigger_child_fail_closed": {"missing": trigger_missing_ok, "ambiguous": trigger_ambiguous_ok, "gameplay_priority_and_presentation_audit": trigger_priority_ok, "phase_lowering_calls": len(phase_lowering_calls)},
    }


def _nonempty_lines() -> int:
    return sum(bool(line.strip()) for line in Path(__file__).read_text(encoding="utf-8").splitlines())


def main() -> int:
    args = _args()
    started = time.perf_counter()
    root = args.tbgd_root.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    preflight = _preflight_model_contracts()
    original_build = TBGDLowering.build
    full_calls: list[str] = []

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        full_calls.append("TBGDLowering.build")
        raise AssertionError("P9-S1 invoked full lowering")

    TBGDLowering.build = forbidden  # type: ignore[assignment]
    try:
        snapshot = build_character_ability_raw_snapshot(root)
        scope = build_character_ability_scope_projection(root, snapshot=snapshot)
        scope_before = scope.summary_json()
        lowerer = TBGDLowering(root)
        catalog = lowerer.build_character_ability_source_graph_catalog(snapshot=snapshot, scope_catalog=scope)
        cards = tuple(build_character_card_ir(root, max_records_per_table=None, skill_tables=CHARACTER_ACTION_DEFINITION_TABLES, ability_source_graph_catalog=catalog, ability_scope_catalog=scope).character_data_cards)
        narrow = CanonicalIR(version="p9_s1_narrow", character_data_cards=cards, character_ability_source_graph_catalog=catalog)
        selected = _selected_rows(snapshot)
        expected_definitions, camera_observation = _definition_oracle(root, snapshot, selected)
        actual_definitions = Counter((item.definition_kind, item.owner_avatar_id, item.source.source_path, item.source.evidence["ability_index"], item.ability_name, item.source.evidence["content_sha256"]) for item in catalog.definitions)
        relationship = _relationship_oracle(root, snapshot, catalog, selected)
        negatives = _negative_matrix(catalog, cards)
        direct = _direct_regressions(root, lowerer, catalog, cards)
    finally:
        TBGDLowering.build = original_build  # type: ignore[assignment]
    ledger = CharacterAbilitySourceGraphQuery(catalog).resolution_ledger()
    ledger_payload = [(item.relation_id, item.outcome, item.binding_kind, item.result_id, item.source_path, item.json_path) for item in ledger]
    ledger_sha = sha256(json.dumps(ledger_payload, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
    decode_count = sum(record.effective_scope == "decode_required" for record in scope.scope_records)
    topology = tuple(item.dependency_id for item in scope.external_dependencies if item.projection_kind == "unit_topology")
    binding_kind_counts = Counter(binding.binding_kind for binding in catalog.bindings)
    elapsed = time.perf_counter() - started
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    business = {
        "preflight_model_contracts": all(preflight.values()),
        "s0_snapshot_scope_reused": catalog.snapshot_id == snapshot.snapshot_id and catalog.scope_catalog_id == scope.catalog_id and scope.summary_json() == scope_before,
        "selected_inventory_one_per_main_source": len(selected) == sum(source.source_kind == "character_main" for source in snapshot.sources),
        "raw_definition_multimap_matches": actual_definitions == expected_definitions,
        "raw_relationship_ledger_reconciles": relationship["ok"], "raw_non_gameplay_sources_reconcile": relationship["retired_source_set_matches"],
        "cross_character_gaps_are_foreign_only": relationship["cross_character_gaps_foreign_only"],
        "classification_is_typed_and_exclusive": len(ledger) == len(catalog.bindings) + len(catalog.gaps) == len({item.relation_id for item in ledger}) and set(binding_kind_counts) <= {"entry", "phase", "passive", "standalone", "presentation"},
        "unique_gameplay_candidates_resolved": relationship["unique_gameplay_resolution_count"] > 0 and relationship["mismatched_outcomes"] == 0,
        "lowering_gap_zero": not any(gap.gap_kind == "lowering_gap" for gap in catalog.gaps),
        "shared_graphs_built_once": len([graph for graph in catalog.graphs if graph.source_kind == "character_shared"]) == len({source.source_id for source in catalog.sources if source.source_kind == "character_shared"}),
        "canonical_card_graph_closure": narrow.character_data_cards == cards,
        "all_negative_contracts": all(negatives.values()),
        "required_direct_regressions": direct["ok"],
        "full_lowering_zero": not full_calls and catalog.build_counters["full_lowering_build_count"] == 0,
        "builder_forbidden_counts_zero": all(
            catalog.build_counters[key] == 0
            for key in (
                "full_lowering_build_count",
                "canonical_ir_build_count",
                "rulebook_build_count",
                "task_execution_count",
                "condition_execution_count",
                "target_execution_count",
                "event_execution_count",
            )
        ),
    }
    governance = {
        "snapshot_build_count": 1,
        "scope_projection_build_count": 1,
        "source_graph_build_count": 1,
        "full_lowering_build_count": len(full_calls),
        "full_canonical_ir_build_count": 0,
        "narrow_canonical_closure_probe_count": 1,
        "full_rulebook_build_count": 0,
        "wall_clock_seconds": elapsed,
        "peak_rss_bytes": rss,
        "validator_nonempty_lines": _nonempty_lines(),
    }
    summary: dict[str, Any] = {
        "ok": False,
        "business_checks": business,
        "preflight": preflight,
        "negative_matrix": negatives,
        "direct_regressions": direct,
        "resolution_ledger": {"entry_count": len(ledger), "sha256": ledger_sha, "resolved_count": sum(item.outcome == "resolved" for item in ledger), "blocked_count": sum(item.outcome == "blocked" for item in ledger), "binding_kind_counts": dict(sorted(binding_kind_counts.items()))},
        "observations": {
            "source_count": len(catalog.sources),
            "definition_count": len(catalog.definitions),
            "action_source_count": len(catalog.action_sources),
            "non_gameplay_skill_source_count": len(catalog.non_gameplay_skill_sources),
            "binding_count": len(catalog.bindings),
            "gap_count": len(catalog.gaps),
            "gap_kind_counts": dict(sorted(Counter(gap.gap_kind for gap in catalog.gaps).items())),
            "selected_version_counts": dict(sorted(Counter(row["selected_version"] for row in selected.values()).items())),
            "decode_required_count_inherited_from_s0": decode_count,
            "unit_topology_external_dependency_ids": topology,
            "camera_oracle": camera_observation,
            "relationship_oracle": relationship,
        },
        "catalog_identity": {"catalog_id": catalog.catalog_id, "snapshot_id": catalog.snapshot_id, "scope_catalog_id": catalog.scope_catalog_id, "source_fingerprint": catalog.source_fingerprint},
        "governance": governance,
    }
    path = output / "p9_s1_ability_source_graph_summary.json"
    path.write_text(json.dumps(summary, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    evidence_bytes = sum(item.stat().st_size for item in output.iterdir() if item.is_file())
    governance["evidence_bytes"] = evidence_bytes
    governance_ok = elapsed < WALL_CLOCK_BUDGET_SECONDS and rss < RSS_BUDGET_BYTES and evidence_bytes <= EVIDENCE_BUDGET_BYTES and governance["validator_nonempty_lines"] <= VALIDATOR_LINE_BUDGET
    summary["governance_ok"] = governance_ok
    summary["ok"] = all(business.values()) and governance_ok
    path.write_text(json.dumps(summary, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
