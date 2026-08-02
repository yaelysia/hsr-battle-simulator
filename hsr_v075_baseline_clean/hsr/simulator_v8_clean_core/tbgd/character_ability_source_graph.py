from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

from ..immutable_json import freeze_json
from ..ir_types import IRSource
from ..rules.ir import (
    CharacterAbilityBindingGapIR,
    CharacterAbilityBindingGapKind,
    CharacterAbilityBindingIR,
    CharacterAbilityBindingKind,
    CharacterAbilityDefinitionIR,
    CharacterAbilitySourceGraphCatalogIR,
    CharacterAbilitySourceGraphIR,
    CharacterAbilitySourceIR,
    CharacterActionSourceIR,
    CharacterActionSourceKind,
    CharacterNonGameplaySkillSourceIR,
    character_ability_stable_id,
)
from .character_ability_scope import (
    CharacterAbilityRawSnapshot,
    CharacterAbilityScopeProjectionCatalog,
    build_character_ability_raw_snapshot,
    build_character_ability_scope_projection,
)
from .character_cards import CHARACTER_ACTION_DEFINITION_TABLES


_CHARACTER_CONFIG_PREFIX = PurePosixPath("Config/ConfigCharacter/Avatar")
_ABILITY_PREFIX = PurePosixPath("Config/ConfigAbility/Avatar")
_CAMERA_PREFIX = PurePosixPath("Config/ConfigAbility/Avatar/Camera")


class CharacterAbilitySourceGraphPlanMismatch(RuntimeError):
    """Raised when current raw schema requires a new P9-S1 architecture decision."""


@dataclass(frozen=True)
class _InventoryRow:
    source_id: str
    source_path: str
    content_sha256: str
    row_index: int
    avatar_id: str
    config_path: str
    skill_ids: tuple[str, ...]
    selected_version: Literal["base", "enhanced"]
    ability_source_path: str


@dataclass(frozen=True)
class _RelationDocument:
    source_path: str
    content_sha256: str
    document: Mapping[str, Any] | tuple[Any, ...]


def _stable_id(prefix: str, *parts: object) -> str:
    return character_ability_stable_id(prefix, *parts)


def _non_gameplay_skill_retired_reason(row: Mapping[str, Any]) -> str | None:
    trigger = row.get("SkillTriggerKey")
    if trigger is not None and trigger != "":
        return None
    if row.get("AttackType") == "MazeNormal":
        return "maze_normal_without_skill_trigger"
    return None


def _derived_avatar_ability_path(
    character_config_path: str,
    *,
    presentation: bool,
) -> str:
    if not isinstance(character_config_path, str) or not character_config_path:
        raise ValueError("character config path is required")
    path = PurePosixPath(character_config_path)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("character config path must be a relative canonical path")
    prefix_parts = _CHARACTER_CONFIG_PREFIX.parts
    if path.parts[: len(prefix_parts)] != prefix_parts:
        raise ValueError("character config path is outside the avatar config schema")
    suffix = path.parts[len(prefix_parts) :]
    if not suffix:
        raise ValueError("character config path has no file component")
    source_name = suffix[-1]
    if source_name.endswith("_Config.json"):
        target_name = source_name[: -len("_Config.json")] + (
            "_Camera.json" if presentation else "_Ability.json"
        )
    elif source_name.endswith(".json"):
        target_name = source_name[:-5] + (
            "_Camera.json" if presentation else "_Ability.json"
        )
    else:
        raise ValueError("character config path must identify a JSON document")
    target_prefix = _CAMERA_PREFIX if presentation else _ABILITY_PREFIX
    return str(target_prefix.joinpath(*suffix[:-1], target_name))


def character_ability_path_from_config(character_config_path: str) -> str:
    return _derived_avatar_ability_path(
        character_config_path,
        presentation=False,
    )


def character_camera_ability_path_from_config(character_config_path: str) -> str:
    return _derived_avatar_ability_path(
        character_config_path,
        presentation=True,
    )


def _frozen_json_bytes(raw_bytes: bytes, source_path: str) -> Any:
    try:
        value = json.loads(raw_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"character relation source unreadable:{source_path}") from exc
    return freeze_json(value)


def _read_relation_document(
    tbgd_root: Path,
    relative_path: str,
    *,
    required: bool,
) -> _RelationDocument | None:
    root = tbgd_root.resolve()
    path = (root / relative_path).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("character relation path escapes TBGD root") from exc
    if not path.is_file():
        if required:
            raise ValueError(f"character relation source missing:{relative_path}")
        return None
    raw_bytes = path.read_bytes()
    document = _frozen_json_bytes(raw_bytes, relative_path)
    if isinstance(document, Mapping):
        frozen_document: Mapping[str, Any] | tuple[Any, ...] = document
    elif isinstance(document, list):
        frozen_document = tuple(document)
    else:
        raise ValueError(f"character relation source root is invalid:{relative_path}")
    return _RelationDocument(
        source_path=relative_path,
        content_sha256=sha256(raw_bytes).hexdigest(),
        document=frozen_document,
    )


def _inventory_rows(snapshot: CharacterAbilityRawSnapshot) -> tuple[_InventoryRow, ...]:
    documents: dict[str, tuple[Any, ...]] = {}
    digests: dict[str, str] = {}
    for source_path, raw_bytes in snapshot.inventory_bytes.items():
        document = _frozen_json_bytes(raw_bytes, source_path)
        if not isinstance(document, list):
            raise ValueError(f"character inventory source is not a list:{source_path}")
        documents[source_path] = tuple(document)
        digests[source_path] = sha256(raw_bytes).hexdigest()
    rows: list[_InventoryRow] = []
    for source in snapshot.sources:
        if source.source_kind != "character_main":
            continue
        evidence = source.source.evidence
        source_path = cast(str, evidence.get("config_source_path"))
        row_index = evidence.get("config_row_index")
        selected_version = evidence.get("selected_version")
        if (
            source_path not in documents
            or not isinstance(row_index, int)
            or isinstance(row_index, bool)
            or row_index < 0
            or row_index >= len(documents[source_path])
            or selected_version not in {"base", "enhanced"}
        ):
            raise ValueError("S0 selected inventory row is invalid")
        row = documents[source_path][row_index]
        if not isinstance(row, Mapping) or str(row.get("AvatarID")) != source.avatar_id:
            raise ValueError("S0 selected inventory avatar does not match its source")
        config_path = row.get("JsonPath")
        if not isinstance(config_path, str) or not config_path:
            raise ValueError("S0 selected inventory row has no character config path")
        ability_source_path = character_ability_path_from_config(config_path)
        if ability_source_path != source.source.source_path:
            raise ValueError("S0 selected inventory JsonPath does not match ability source")
        raw_skill_ids = row.get("SkillList")
        if not isinstance(raw_skill_ids, (list, tuple)):
            raw_skill_ids = ()
        skill_ids = tuple(
            sorted(
                {
                    str(skill_id)
                    for skill_id in raw_skill_ids
                    if skill_id is not None and str(skill_id)
                }
            )
        )
        rows.append(
            _InventoryRow(
                source_id=source.source_id,
                source_path=source_path,
                content_sha256=digests[source_path],
                row_index=row_index,
                avatar_id=source.avatar_id,
                config_path=config_path,
                skill_ids=skill_ids,
                selected_version=cast(Literal["base", "enhanced"], selected_version),
                ability_source_path=ability_source_path,
            )
        )
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                row.avatar_id,
                row.config_path,
                row.source_path,
                row.row_index,
            ),
        )
    )


def _ability_rows(document: Mapping[str, Any]) -> tuple[tuple[int, Mapping[str, Any]], ...]:
    raw_rows = document.get("AbilityList")
    if not isinstance(raw_rows, (list, tuple)):
        return ()
    return tuple(
        (index, row)
        for index, row in enumerate(raw_rows)
        if isinstance(row, Mapping)
        and isinstance(row.get("Name"), str)
        and bool(row.get("Name"))
    )


def _definition(
    *,
    source_id: str,
    owner_avatar_id: str,
    definition_kind: Literal[
        "character_main", "character_shared", "presentation"
    ],
    source_path: str,
    content_sha256: str,
    ability_index: int,
    ability_name: str,
) -> CharacterAbilityDefinitionIR:
    return CharacterAbilityDefinitionIR(
        definition_id=_stable_id(
            "character_ability_definition",
            definition_kind,
            source_id,
            source_path,
            ability_index,
            ability_name,
        ),
        source_id=source_id,
        owner_avatar_id=owner_avatar_id,
        ability_name=ability_name,
        definition_kind=definition_kind,
        source=IRSource(
            source_path=source_path,
            raw_type=(
                "PresentationAbilityList"
                if definition_kind == "presentation"
                else "AbilityList"
            ),
            raw_id=ability_name,
            evidence={
                "source_id": source_id,
                "source_kind": definition_kind,
                "avatar_id": owner_avatar_id,
                "json_path": f"$.AbilityList[{ability_index}]",
                "ability_index": ability_index,
                "content_sha256": content_sha256,
            },
        ),
    )


def _action_kinds(
    row: Mapping[str, Any],
    skill_entry: Mapping[str, Any],
) -> tuple[CharacterActionSourceKind, ...]:
    attack_type = str(row.get("AttackType") or "")
    attack_type_kinds: dict[str, CharacterActionSourceKind] = {
        "Normal": "basic",
        "BPSkill": "skill",
        "Ultra": "ultimate",
        "Talent": "passive",
        "Passive": "passive",
        "TalentPassive": "passive",
        "Maze": "maze",
        "MazeNormal": "maze",
    }
    skill_type = str(skill_entry.get("SkillType") or "")
    skill_type_kinds: dict[str, CharacterActionSourceKind] = {
        "Normal": "basic",
        "Skill": "skill",
        "Ultra": "ultimate",
        "Passive": "passive",
        "Maze": "maze",
    }
    if attack_type and attack_type not in attack_type_kinds:
        raise CharacterAbilitySourceGraphPlanMismatch(
            f"plan_mismatch:new_character_attack_type:{attack_type}"
        )
    if skill_type and skill_type not in skill_type_kinds:
        raise CharacterAbilitySourceGraphPlanMismatch(
            f"plan_mismatch:new_character_skill_type:{skill_type}"
        )
    use_type = str(skill_entry.get("UseType") or "")
    use_type_kind: CharacterActionSourceKind | None = (
        "passive" if use_type == "Passive" else None
    )
    action_kinds = {
        kind
        for kind in (
            attack_type_kinds.get(attack_type),
            skill_type_kinds.get(skill_type),
            use_type_kind,
        )
        if kind is not None
    }
    if not action_kinds:
        raise CharacterAbilitySourceGraphPlanMismatch(
            "plan_mismatch:character_action_kind_sources_missing"
        )
    return tuple(sorted(action_kinds))


def _positive_level(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError("character action level must be a positive integer")
    return value


def _skill_entries(
    document: Mapping[str, Any],
    skill_trigger_key: str,
) -> tuple[tuple[str, Mapping[str, Any]], ...]:
    skill_list = document.get("SkillList")
    matches: list[tuple[str, Mapping[str, Any]]] = []
    if isinstance(skill_list, (list, tuple)):
        for index, item in enumerate(skill_list):
            if isinstance(item, Mapping) and item.get("Name") == skill_trigger_key:
                matches.append((f"$.SkillList[{index}]", item))
    elif isinstance(skill_list, Mapping):
        item = skill_list.get(skill_trigger_key)
        if isinstance(item, Mapping):
            matches.append((f"$.SkillList.{skill_trigger_key}", item))
    return tuple(matches)


def _phase_relations(
    document: Mapping[str, Any],
    skill_trigger_key: str,
) -> tuple[tuple[str, Any], ...]:
    phase_list = document.get("SkillAbilityList")
    matches: list[tuple[str, Any]] = []
    if isinstance(phase_list, (list, tuple)):
        for index, item in enumerate(phase_list):
            if isinstance(item, Mapping) and item.get("Skill") == skill_trigger_key:
                matches.append((f"$.SkillAbilityList[{index}]", item))
    elif isinstance(phase_list, Mapping) and skill_trigger_key in phase_list:
        matches.append(
            (f"$.SkillAbilityList.{skill_trigger_key}", phase_list[skill_trigger_key])
        )
    return tuple(matches)


def _phase_names(value: Any) -> tuple[str, ...]:
    names: list[str] = []
    if isinstance(value, str):
        if value:
            names.append(value)
    elif isinstance(value, (list, tuple)):
        for item in value:
            names.extend(_phase_names(item))
    elif isinstance(value, Mapping):
        for field_name in (
            "AbilityName",
            "PhaseAbility",
            "PhaseAbilityName",
        ):
            field_value = value.get(field_name)
            if isinstance(field_value, str) and field_value:
                names.append(field_value)
        for field_name in (
            "AbilityList",
            "AbilityNameList",
            "PhaseList",
            "PhaseAbilityList",
        ):
            names.extend(_phase_names(value.get(field_name)))
    return tuple(dict.fromkeys(names))


def _relation_source(
    *,
    source_path: str,
    raw_type: str,
    raw_id: str,
    evidence: Mapping[str, Any],
) -> IRSource:
    return IRSource(
        source_path=source_path,
        raw_type=raw_type,
        raw_id=raw_id,
        evidence=cast(dict[str, Any], dict(evidence)),
    )


def same_character_ability_s0_sources(
    left: Iterable[Any],
    right: Iterable[Any],
) -> bool:
    left_values = tuple(left)
    right_values = tuple(right)
    return (
        all(type(source) is CharacterAbilitySourceIR for source in left_values)
        and all(type(source) is CharacterAbilitySourceIR for source in right_values)
        and {source.source_id: source for source in left_values}
        == {source.source_id: source for source in right_values}
        and len(left_values) == len(right_values)
    )


def build_character_ability_source_graph(
    tbgd_root: Path,
    *,
    snapshot: CharacterAbilityRawSnapshot | None = None,
    scope_catalog: CharacterAbilityScopeProjectionCatalog | None = None,
) -> CharacterAbilitySourceGraphCatalogIR:
    snapshot_build_count = 0
    scope_projection_build_count = 0
    if snapshot is None:
        snapshot = build_character_ability_raw_snapshot(tbgd_root)
        snapshot_build_count = 1
    elif type(snapshot) is not CharacterAbilityRawSnapshot:
        raise TypeError("source graph builder requires the exact S0 snapshot type")
    if scope_catalog is None:
        scope_catalog = build_character_ability_scope_projection(
            tbgd_root,
            snapshot=snapshot,
        )
        scope_projection_build_count = 1
    elif type(scope_catalog) is not CharacterAbilityScopeProjectionCatalog:
        raise TypeError("source graph builder requires the exact S0 scope catalog type")
    if (
        scope_catalog.snapshot_id != snapshot.snapshot_id
        or scope_catalog.source_fingerprint != snapshot.source_fingerprint
        or scope_catalog.fingerprint_kind != snapshot.fingerprint_kind
        or scope_catalog.source_filter != snapshot.source_filter
        or scope_catalog.family_filter
        or not same_character_ability_s0_sources(
            scope_catalog.sources, snapshot.sources
        )
    ):
        raise ValueError("S0 snapshot and scope catalog do not describe one source closure")

    main_sources_by_avatar = {
        source.avatar_id: source
        for source in snapshot.sources
        if source.source_kind == "character_main"
    }
    if len(main_sources_by_avatar) != sum(
        source.source_kind == "character_main" for source in snapshot.sources
    ):
        raise ValueError("S0 snapshot has duplicate character ability owners")
    shared_sources = tuple(
        source
        for source in snapshot.sources
        if source.source_kind == "character_shared"
    )
    if not main_sources_by_avatar or not shared_sources:
        raise ValueError("S1 requires both owned and shared S0 ability sources")

    inventory_rows = tuple(
        row
        for row in _inventory_rows(snapshot)
        if row.avatar_id in main_sources_by_avatar
    )
    if len(inventory_rows) != len(main_sources_by_avatar):
        raise ValueError("S0 source closure must select one inventory row per avatar")
    rows_by_avatar: dict[str, list[_InventoryRow]] = defaultdict(list)
    rows_by_avatar_skill: dict[tuple[str, str], list[_InventoryRow]] = defaultdict(list)
    for row in inventory_rows:
        rows_by_avatar[row.avatar_id].append(row)
        for skill_id in row.skill_ids:
            rows_by_avatar_skill[(row.avatar_id, skill_id)].append(row)

    relation_documents: dict[str, _RelationDocument] = {}
    relation_source_digests: dict[str, str] = {
        row.source_path: row.content_sha256 for row in inventory_rows
    }
    missing_config_paths: set[str] = set()

    def load_relation(relative_path: str, *, required: bool) -> _RelationDocument | None:
        cached = relation_documents.get(relative_path)
        if cached is not None:
            return cached
        document = _read_relation_document(
            tbgd_root,
            relative_path,
            required=required,
        )
        if document is not None:
            relation_documents[relative_path] = document
            relation_source_digests[relative_path] = document.content_sha256
        return document

    for config_path in sorted({row.config_path for row in inventory_rows}):
        if load_relation(config_path, required=False) is None:
            missing_config_paths.add(config_path)

    selected_skill_ids = {
        skill_id for row in inventory_rows for skill_id in row.skill_ids
    }
    skill_rows: dict[
        tuple[str, str], list[tuple[int, Mapping[str, Any]]]
    ] = defaultdict(list)
    action_table_read_count = 0
    action_table_selected_row_count = 0
    for relative_path, _entity_type, id_key in CHARACTER_ACTION_DEFINITION_TABLES:
        relation = load_relation(relative_path, required=False)
        if relation is None:
            continue
        action_table_read_count += 1
        if not isinstance(relation.document, tuple):
            raise ValueError(f"character action table is not a list:{relative_path}")
        for row_index, row in enumerate(relation.document):
            if not isinstance(row, Mapping) or row.get(id_key) is None:
                continue
            skill_id = str(row[id_key])
            if skill_id not in selected_skill_ids:
                continue
            skill_rows[(relative_path, skill_id)].append((row_index, row))
            action_table_selected_row_count += 1

    definitions: list[CharacterAbilityDefinitionIR] = []
    graph_id_by_source_id: dict[str, str] = {}
    graph_id_by_avatar: dict[str, str] = {}
    for source in snapshot.sources:
        graph_id = _stable_id("character_ability_source_graph", source.source_id)
        graph_id_by_source_id[source.source_id] = graph_id
        if source.source_kind == "character_main":
            graph_id_by_avatar[source.avatar_id] = graph_id
        document = snapshot.documents[source.source.source_path]
        for ability_index, ability in _ability_rows(document):
            ability_name = cast(str, ability["Name"])
            definitions.append(
                _definition(
                    source_id=source.source_id,
                    owner_avatar_id=source.avatar_id,
                    definition_kind=source.source_kind,
                    source_path=source.source.source_path,
                    content_sha256=source.content_sha256,
                    ability_index=ability_index,
                    ability_name=ability_name,
                )
            )

    presentation_path_count = 0
    missing_presentation_path_count = 0
    for avatar_id, source in sorted(main_sources_by_avatar.items()):
        camera_paths: set[str] = set()
        for row in rows_by_avatar.get(avatar_id, ()):
            camera_paths.add(
                character_camera_ability_path_from_config(row.config_path)
            )
        for camera_path in sorted(camera_paths):
            relation = load_relation(camera_path, required=False)
            if relation is None:
                missing_presentation_path_count += 1
                continue
            presentation_path_count += 1
            if not isinstance(relation.document, Mapping):
                raise ValueError(
                    f"character presentation ability source is not an object:{camera_path}"
                )
            for ability_index, ability in _ability_rows(relation.document):
                definitions.append(
                    _definition(
                        source_id=source.source_id,
                        owner_avatar_id=avatar_id,
                        definition_kind="presentation",
                        source_path=camera_path,
                        content_sha256=relation.content_sha256,
                        ability_index=ability_index,
                        ability_name=cast(str, ability["Name"]),
                    )
                )

    definitions.sort(key=lambda definition: definition.definition_id)
    definitions_by_name: dict[str, list[CharacterAbilityDefinitionIR]] = defaultdict(list)
    for definition in definitions:
        definitions_by_name[definition.ability_name].append(definition)

    action_sources: list[CharacterActionSourceIR] = []
    non_gameplay_skill_sources: list[CharacterNonGameplaySkillSourceIR] = []
    action_contexts: dict[
        str,
        tuple[Mapping[str, Any], Mapping[str, Any], str, str],
    ] = {}
    gaps: list[CharacterAbilityBindingGapIR] = []
    bindings: list[CharacterAbilityBindingIR] = []
    graph_action_ids: dict[str, list[str]] = defaultdict(list)
    graph_non_gameplay_ids: dict[str, list[str]] = defaultdict(list)
    graph_binding_ids: dict[str, list[str]] = defaultdict(list)
    graph_gap_ids: dict[str, list[str]] = defaultdict(list)
    searched_source_ids_by_avatar = {
        avatar_id: tuple(
            sorted(
                {
                    main_sources_by_avatar[avatar_id].source_id,
                    *(source.source_id for source in shared_sources),
                }
            )
        )
        for avatar_id in main_sources_by_avatar
    }

    def typed_relation_source(
        *,
        graph_id: str,
        owner_avatar_id: str,
        action_source_id: str,
        skill_id: str,
        ability_name: str,
        binding_kind: CharacterAbilityBindingKind,
        ordinal: int,
        source_path: str,
        json_path: str,
        content_sha256: str,
    ) -> IRSource:
        relation_id = _stable_id(
            "character_ability_relation",
            graph_id,
            owner_avatar_id,
            action_source_id,
            skill_id,
            ability_name,
            binding_kind,
            ordinal,
            source_path,
            json_path,
        )
        return _relation_source(
            source_path=source_path,
            raw_type="CharacterAbilityRelation",
            raw_id=ability_name,
            evidence={
                "relation_id": relation_id,
                "graph_id": graph_id,
                "owner_avatar_id": owner_avatar_id,
                "action_source_id": action_source_id,
                "skill_id": skill_id,
                "binding_kind": binding_kind,
                "relation_ordinal": ordinal,
                "json_path": json_path,
                "content_sha256": content_sha256,
            },
        )

    def add_gap(
        *,
        graph_id: str,
        owner_avatar_id: str,
        action_source_id: str,
        requested_ability_name: str,
        expected_binding_kind: CharacterAbilityBindingKind,
        gap_kind: CharacterAbilityBindingGapKind,
        candidate_definition_ids: Iterable[str] = (),
        candidate_action_source_ids: Iterable[str] = (),
        searched_source_ids: Iterable[str],
        source: IRSource,
        blocked_reason: str,
        skill_id: str = "",
        ordinal: int = 0,
        request_key: str = "",
        request_json_path: str = "",
    ) -> CharacterAbilityBindingGapIR:
        candidate_definitions = tuple(sorted(set(candidate_definition_ids)))
        candidate_actions = tuple(sorted(set(candidate_action_source_ids)))
        searched_sources = tuple(sorted(set(searched_source_ids)))
        if not skill_id and isinstance(source.evidence.get("skill_id"), str):
            skill_id = cast(str, source.evidence["skill_id"])
        raw_json_path = request_json_path or source.evidence.get("json_path")
        if not isinstance(raw_json_path, str) or not raw_json_path:
            row_index = source.evidence.get("row_index")
            raw_json_path = (
                f"$[{row_index}]"
                if isinstance(row_index, int) and not isinstance(row_index, bool)
                else "$"
            )
        content_digest = source.evidence.get("content_sha256")
        if not isinstance(content_digest, str):
            content_digest = relation_source_digests.get(source.source_path)
        if not isinstance(content_digest, str):
            content_digest = next(
                (
                    item.content_sha256
                    for item in snapshot.sources
                    if item.source.source_path == source.source_path
                ),
                "",
            )
        gap_raw_id = requested_ability_name or request_key or source.raw_id
        relation_id = _stable_id(
            "character_ability_relation",
            graph_id,
            owner_avatar_id,
            action_source_id,
            skill_id,
            gap_raw_id,
            expected_binding_kind,
            ordinal,
            source.source_path,
            raw_json_path,
        )
        gap_source = _relation_source(
            source_path=source.source_path,
            raw_type="CharacterAbilityRelation",
            raw_id=gap_raw_id,
            evidence={
                "relation_id": relation_id,
                "graph_id": graph_id,
                "owner_avatar_id": owner_avatar_id,
                "action_source_id": action_source_id,
                "skill_id": skill_id,
                "binding_kind": expected_binding_kind,
                "relation_ordinal": ordinal,
                "json_path": raw_json_path,
                "content_sha256": content_digest,
            },
        )
        gap = CharacterAbilityBindingGapIR(
            gap_id=_stable_id(
                "character_ability_binding_gap",
                relation_id,
                gap_kind,
                *candidate_definitions,
                *candidate_actions,
            ),
            relation_id=relation_id,
            graph_id=graph_id,
            owner_avatar_id=owner_avatar_id,
            action_source_id=action_source_id,
            requested_ability_name=requested_ability_name,
            expected_binding_kind=expected_binding_kind,
            ordinal=ordinal,
            gap_kind=gap_kind,
            candidate_definition_ids=candidate_definitions,
            candidate_action_source_ids=candidate_actions,
            searched_source_ids=searched_sources,
            source=gap_source,
            blocked_reason=blocked_reason,
        )
        gaps.append(gap)
        graph_gap_ids[graph_id].append(gap.gap_id)
        return gap

    for (avatar_id, skill_id), owner_rows in sorted(rows_by_avatar_skill.items()):
        graph_id = graph_id_by_avatar[avatar_id]
        table_groups = tuple(
            (relative_path, rows)
            for (relative_path, grouped_skill_id), rows in sorted(skill_rows.items())
            if grouped_skill_id == skill_id
        )
        if not table_groups:
            inventory_row = owner_rows[0]
            add_gap(
                graph_id=graph_id,
                owner_avatar_id=avatar_id,
                action_source_id="",
                requested_ability_name="",
                expected_binding_kind="entry",
                gap_kind="missing_action_source_blocked",
                searched_source_ids=searched_source_ids_by_avatar[avatar_id],
                source=_relation_source(
                    source_path=inventory_row.source_path,
                    raw_type=Path(inventory_row.source_path).stem,
                    raw_id=skill_id,
                    evidence={
                        "row_index": inventory_row.row_index,
                        "avatar_id": avatar_id,
                        "skill_id": skill_id,
                    },
                ),
                blocked_reason="skill_id_missing_from_character_action_tables",
                skill_id=skill_id,
            )
            continue
        for table_path, rows in table_groups:
            variants: dict[str, list[tuple[int, Mapping[str, Any]]]] = defaultdict(list)
            for row_index, row in rows:
                trigger_key = str(row.get("SkillTriggerKey") or "")
                if not trigger_key:
                    attack_type = row.get("AttackType")
                    retired_reason = _non_gameplay_skill_retired_reason(row)
                    if retired_reason is not None:
                        skill_effect = row.get("SkillEffect")
                        if not isinstance(skill_effect, str):
                            raise CharacterAbilitySourceGraphPlanMismatch(
                                "MazeNormal non-gameplay skill has a non-string SkillEffect"
                            )
                        retired_id = _stable_id(
                            "character_non_gameplay_skill_source",
                            graph_id,
                            avatar_id,
                            skill_id,
                            table_path,
                            row_index,
                            attack_type,
                            skill_effect,
                            retired_reason,
                        )
                        retired = CharacterNonGameplaySkillSourceIR(
                            non_gameplay_skill_source_id=retired_id,
                            graph_id=graph_id,
                            owner_avatar_id=avatar_id,
                            skill_id=skill_id,
                            raw_attack_type=attack_type,
                            raw_skill_effect=skill_effect,
                            row_index=row_index,
                            content_sha256=relation_source_digests[table_path],
                            retired_reason=retired_reason,
                            source=_relation_source(
                                source_path=table_path,
                                raw_type="CharacterSkillActionRow",
                                raw_id=skill_id,
                                evidence={
                                    "graph_id": graph_id,
                                    "owner_avatar_id": avatar_id,
                                    "skill_id": skill_id,
                                    "skill_trigger_key": "",
                                    "attack_type": attack_type,
                                    "skill_effect": skill_effect,
                                    "row_index": row_index,
                                    "retired_reason": retired_reason,
                                    "content_sha256": relation_source_digests[
                                        table_path
                                    ],
                                },
                            ),
                        )
                        non_gameplay_skill_sources.append(retired)
                        graph_non_gameplay_ids[graph_id].append(retired_id)
                        continue
                    add_gap(
                        graph_id=graph_id,
                        owner_avatar_id=avatar_id,
                        action_source_id="",
                        requested_ability_name="",
                        expected_binding_kind="entry",
                        gap_kind="missing_action_source_blocked",
                        searched_source_ids=searched_source_ids_by_avatar[avatar_id],
                        source=_relation_source(
                            source_path=table_path,
                            raw_type=Path(table_path).stem,
                            raw_id=skill_id,
                            evidence={"row_index": row_index, "skill_id": skill_id},
                        ),
                        blocked_reason=(
                            "character_action_missing_skill_trigger_key:"
                            f"{attack_type!s}"
                        ),
                        skill_id=skill_id,
                    )
                    continue
                variants[trigger_key].append((row_index, row))
            for trigger_key, variant_rows in sorted(variants.items()):
                levels = tuple(
                    _positive_level(row.get("Level", 1))
                    for _row_index, row in variant_rows
                )
                if len(levels) != len(set(levels)):
                    add_gap(
                        graph_id=graph_id,
                        owner_avatar_id=avatar_id,
                        action_source_id="",
                        requested_ability_name="",
                        expected_binding_kind="entry",
                        gap_kind="missing_action_source_blocked",
                        searched_source_ids=searched_source_ids_by_avatar[avatar_id],
                        source=_relation_source(
                            source_path=table_path,
                            raw_type=Path(table_path).stem,
                            raw_id=skill_id,
                            evidence={
                                "skill_id": skill_id,
                                "skill_trigger_key": trigger_key,
                                "duplicate_levels": list(levels),
                            },
                        ),
                        blocked_reason="duplicate_character_action_level_rows",
                        skill_id=skill_id,
                    )
                    continue
                ordered_rows = tuple(
                    sorted(
                        variant_rows,
                        key=lambda item: (_positive_level(item[1].get("Level", 1)), item[0]),
                    )
                )
                ordered_levels = tuple(
                    _positive_level(row.get("Level", 1)) for _index, row in ordered_rows
                )
                for inventory_row in owner_rows:
                    relation = relation_documents.get(inventory_row.config_path)
                    if relation is None or not isinstance(relation.document, Mapping):
                        add_gap(
                            graph_id=graph_id,
                            owner_avatar_id=avatar_id,
                            action_source_id="",
                            requested_ability_name="",
                            expected_binding_kind="entry",
                            gap_kind="missing_action_source_blocked",
                            searched_source_ids=searched_source_ids_by_avatar[avatar_id],
                            source=_relation_source(
                                source_path=inventory_row.source_path,
                                raw_type=Path(inventory_row.source_path).stem,
                                raw_id=skill_id,
                                evidence={
                                    "row_index": inventory_row.row_index,
                                    "config_path": inventory_row.config_path,
                                },
                            ),
                            blocked_reason="character_skill_config_not_readable",
                            skill_id=skill_id,
                        )
                        continue
                    skill_entries = _skill_entries(relation.document, trigger_key)
                    if not skill_entries:
                        add_gap(
                            graph_id=graph_id,
                            owner_avatar_id=avatar_id,
                            action_source_id="",
                            requested_ability_name=trigger_key,
                            expected_binding_kind="entry",
                            gap_kind="missing_action_source_blocked",
                            searched_source_ids=searched_source_ids_by_avatar[avatar_id],
                            source=_relation_source(
                                source_path=inventory_row.config_path,
                                raw_type="CharacterSkillList",
                                raw_id=trigger_key,
                                evidence={
                                    "avatar_id": avatar_id,
                                    "skill_id": skill_id,
                                    "content_sha256": relation.content_sha256,
                                },
                            ),
                            blocked_reason="skill_trigger_key_not_in_character_config",
                            skill_id=skill_id,
                        )
                        continue
                    for skill_json_path, skill_entry in skill_entries:
                        action_kinds = {
                            action_kind
                            for _row_index, row in ordered_rows
                            for action_kind in _action_kinds(row, skill_entry)
                        }
                        for action_kind in sorted(action_kinds):
                            action_source_id = _stable_id(
                                "character_action_source",
                                avatar_id,
                                skill_id,
                                table_path,
                                trigger_key,
                                action_kind,
                                inventory_row.config_path,
                                skill_json_path,
                                *(
                                    f"{row_index}:{_positive_level(row.get('Level', 1))}"
                                    for row_index, row in ordered_rows
                                ),
                            )
                            action = CharacterActionSourceIR(
                                action_source_id=action_source_id,
                                action_id=f"avatar_skill:{skill_id}",
                                owner_avatar_id=avatar_id,
                                skill_id=skill_id,
                                skill_trigger_key=trigger_key,
                                action_kind=action_kind,
                                levels=ordered_levels,
                                highest_level=ordered_levels[-1],
                                config_source=_relation_source(
                                    source_path=inventory_row.config_path,
                                    raw_type="CharacterSkillList",
                                    raw_id=trigger_key,
                                    evidence={
                                        "source_id": inventory_row.source_id,
                                        "avatar_id": avatar_id,
                                        "skill_id": skill_id,
                                        "skill_trigger_key": trigger_key,
                                        "json_path": skill_json_path,
                                        "inventory_source_path": inventory_row.source_path,
                                        "inventory_row_index": inventory_row.row_index,
                                        "selected_version": inventory_row.selected_version,
                                        "ability_source_path": inventory_row.ability_source_path,
                                        "inventory_content_sha256": inventory_row.content_sha256,
                                        "content_sha256": relation.content_sha256,
                                    },
                                ),
                                skill_sources=tuple(
                                    _relation_source(
                                        source_path=table_path,
                                        raw_type=Path(table_path).stem,
                                        raw_id=skill_id,
                                        evidence={
                                            "avatar_id": avatar_id,
                                            "skill_id": skill_id,
                                            "row_index": row_index,
                                            "level": _positive_level(row.get("Level", 1)),
                                            "skill_trigger_key": trigger_key,
                                            "content_sha256": relation_source_digests[table_path],
                                        },
                                    )
                                    for row_index, row in ordered_rows
                                ),
                            )
                            action_sources.append(action)
                            action_contexts[action_source_id] = (
                                relation.document,
                                skill_entry,
                                skill_json_path,
                                relation.content_sha256,
                            )
                            graph_action_ids[graph_id].append(action_source_id)

    action_sources.sort(key=lambda action: action.action_source_id)
    actions_by_action_id: dict[str, list[CharacterActionSourceIR]] = defaultdict(list)
    for action in action_sources:
        actions_by_action_id[action.action_id].append(action)

    ambiguous_action_source_ids: set[str] = set()
    for action_id, candidates in sorted(actions_by_action_id.items()):
        owners = sorted({candidate.owner_avatar_id for candidate in candidates})
        for owner_avatar_id in owners:
            owner_candidates = tuple(
                candidate for candidate in candidates
                if candidate.owner_avatar_id == owner_avatar_id
            )
            if len(owner_candidates) == 1:
                continue
            ambiguous_action_source_ids.update(
                candidate.action_source_id for candidate in owner_candidates
            )
            kinds = {candidate.action_kind for candidate in owner_candidates}
            gap_kind: CharacterAbilityBindingGapKind = (
                "cross_kind_blocked"
                if len(kinds) > 1
                else "duplicate_action_source_blocked"
            )
            source = owner_candidates[0].config_source
            add_gap(
                graph_id=graph_id_by_avatar[owner_avatar_id],
                owner_avatar_id=owner_avatar_id,
                action_source_id="",
                requested_ability_name="",
                expected_binding_kind="entry",
                gap_kind=gap_kind,
                candidate_action_source_ids=(
                    candidate.action_source_id for candidate in owner_candidates
                ),
                searched_source_ids=searched_source_ids_by_avatar[owner_avatar_id],
                source=source,
                blocked_reason=f"ambiguous_action_source:{action_id}",
            )

    def resolve_definition(
        *,
        graph_id: str,
        owner_avatar_id: str,
        action_source_id: str,
        ability_name: str,
        binding_kind: CharacterAbilityBindingKind,
        ordinal: int,
        relation_source: IRSource,
    ) -> CharacterAbilityDefinitionIR | None:
        candidates = definitions_by_name.get(ability_name, ())
        gameplay = tuple(
            definition
            for definition in candidates
            if definition.definition_kind in {"character_main", "character_shared"}
            and definition.owner_avatar_id in {"", owner_avatar_id}
        )
        presentation = tuple(
            definition
            for definition in candidates
            if definition.definition_kind == "presentation"
            and definition.owner_avatar_id == owner_avatar_id
        )
        foreign = tuple(
            definition
            for definition in candidates
            if definition.owner_avatar_id not in {"", owner_avatar_id}
        )
        if len(gameplay) > 1:
            add_gap(
                graph_id=graph_id,
                owner_avatar_id=owner_avatar_id,
                action_source_id=action_source_id,
                requested_ability_name=ability_name,
                expected_binding_kind=binding_kind,
                gap_kind="ambiguous_binding_blocked",
                candidate_definition_ids=(
                    definition.definition_id for definition in gameplay
                ),
                searched_source_ids=searched_source_ids_by_avatar[owner_avatar_id],
                source=relation_source,
                blocked_reason="multiple_gameplay_definitions_match_relation",
                ordinal=ordinal,
            )
            return None
        if not gameplay and len(presentation) > 1:
            add_gap(
                graph_id=graph_id,
                owner_avatar_id=owner_avatar_id,
                action_source_id=action_source_id,
                requested_ability_name=ability_name,
                expected_binding_kind="presentation",
                gap_kind="ambiguous_binding_blocked",
                candidate_definition_ids=(
                    definition.definition_id for definition in presentation
                ),
                searched_source_ids=searched_source_ids_by_avatar[owner_avatar_id],
                source=relation_source,
                blocked_reason="multiple_presentation_definitions_match_relation",
                ordinal=ordinal,
            )
            return None
        if gameplay:
            definition = gameplay[0]
            resolved_kind: CharacterAbilityBindingKind = binding_kind
        elif presentation:
            definition = presentation[0]
            resolved_kind = "presentation"
        elif foreign:
            add_gap(
                graph_id=graph_id,
                owner_avatar_id=owner_avatar_id,
                action_source_id=action_source_id,
                requested_ability_name=ability_name,
                expected_binding_kind=binding_kind,
                gap_kind="cross_character_blocked",
                candidate_definition_ids=(
                    definition.definition_id for definition in foreign
                ),
                searched_source_ids=searched_source_ids_by_avatar[owner_avatar_id],
                source=relation_source,
                blocked_reason="ability_relation_only_matches_a_foreign_character",
                ordinal=ordinal,
            )
            return None
        else:
            add_gap(
                graph_id=graph_id,
                owner_avatar_id=owner_avatar_id,
                action_source_id=action_source_id,
                requested_ability_name=ability_name,
                expected_binding_kind=binding_kind,
                gap_kind="source_gap_blocked",
                searched_source_ids=searched_source_ids_by_avatar[owner_avatar_id],
                source=relation_source,
                blocked_reason="structured_ability_candidates_exhausted",
                ordinal=ordinal,
            )
            return None
        typed_source = typed_relation_source(
            graph_id=graph_id,
            owner_avatar_id=owner_avatar_id,
            action_source_id=action_source_id,
            skill_id=cast(str, relation_source.evidence["skill_id"]),
            ability_name=ability_name,
            binding_kind=resolved_kind,
            ordinal=ordinal,
            source_path=relation_source.source_path,
            json_path=cast(str, relation_source.evidence["json_path"]),
            content_sha256=cast(
                str, relation_source.evidence["content_sha256"]
            ),
        )
        relation_id = cast(str, typed_source.evidence["relation_id"])
        binding = CharacterAbilityBindingIR(
            binding_id=_stable_id(
                "character_ability_binding",
                relation_id,
                definition.definition_id,
            ),
            relation_id=relation_id,
            graph_id=graph_id,
            owner_avatar_id=owner_avatar_id,
            action_source_id=action_source_id,
            ability_definition_id=definition.definition_id,
            ability_name=ability_name,
            binding_kind=resolved_kind,
            ordinal=ordinal,
            relation_source=typed_source,
        )
        bindings.append(binding)
        graph_binding_ids[graph_id].append(binding.binding_id)
        return definition

    used_definition_ids: set[str] = set()
    for action in action_sources:
        if action.action_source_id in ambiguous_action_source_ids:
            continue
        graph_id = graph_id_by_avatar[action.owner_avatar_id]
        document, skill_entry, skill_json_path, config_digest = action_contexts[
            action.action_source_id
        ]
        phase_relations = _phase_relations(document, action.skill_trigger_key)
        entry_ability = skill_entry.get("EntryAbility")
        entry_name = entry_ability if isinstance(entry_ability, str) else ""
        request_rows: list[
            tuple[str, CharacterAbilityBindingKind, int, str]
        ] = []
        if action.action_kind == "passive":
            passive_names: list[tuple[str, str]] = []
            if entry_name:
                passive_names.append((entry_name, f"{skill_json_path}.EntryAbility"))
            for phase_path, phase_value in phase_relations:
                passive_names.extend(
                    (name, phase_path) for name in _phase_names(phase_value)
                )
            for ordinal, (name, json_path) in enumerate(passive_names):
                request_rows.append((name, "passive", ordinal, json_path))
            if not passive_names:
                add_gap(
                    graph_id=graph_id,
                    owner_avatar_id=action.owner_avatar_id,
                    action_source_id=action.action_source_id,
                    requested_ability_name="",
                    expected_binding_kind="passive",
                    gap_kind="missing_phase_blocked",
                    searched_source_ids=searched_source_ids_by_avatar[
                        action.owner_avatar_id
                    ],
                    source=action.config_source,
                    blocked_reason="passive_action_has_no_ability_relation",
                    request_key=f"{action.skill_trigger_key}:PassiveAbility",
                    request_json_path=f"{skill_json_path}.EntryAbility|$.SkillAbilityList",
                )
        else:
            if entry_name:
                request_rows.append(
                    (entry_name, "entry", 0, f"{skill_json_path}.EntryAbility")
                )
            else:
                add_gap(
                    graph_id=graph_id,
                    owner_avatar_id=action.owner_avatar_id,
                    action_source_id=action.action_source_id,
                    requested_ability_name="",
                    expected_binding_kind="entry",
                    gap_kind="missing_entry_blocked",
                    searched_source_ids=searched_source_ids_by_avatar[
                        action.owner_avatar_id
                    ],
                    source=action.config_source,
                    blocked_reason="character_action_has_no_entry_ability",
                    request_key=f"{action.skill_trigger_key}:EntryAbility",
                    request_json_path=f"{skill_json_path}.EntryAbility",
                )
            phase_ordinal = 0
            for phase_path, phase_value in phase_relations:
                for phase_name in _phase_names(phase_value):
                    if phase_name == entry_name:
                        continue
                    request_rows.append(
                        (phase_name, "phase", phase_ordinal, phase_path)
                    )
                    phase_ordinal += 1

        for name, binding_kind, ordinal, json_path in request_rows:
            relation_source = typed_relation_source(
                graph_id=graph_id,
                owner_avatar_id=action.owner_avatar_id,
                action_source_id=action.action_source_id,
                skill_id=action.skill_id,
                ability_name=name,
                binding_kind=binding_kind,
                ordinal=ordinal,
                source_path=action.config_source.source_path,
                json_path=json_path,
                content_sha256=config_digest,
            )
            definition = resolve_definition(
                graph_id=graph_id,
                owner_avatar_id=action.owner_avatar_id,
                action_source_id=action.action_source_id,
                ability_name=name,
                binding_kind=binding_kind,
                ordinal=ordinal,
                relation_source=relation_source,
            )
            if definition is not None:
                used_definition_ids.add(definition.definition_id)

    presentation_by_owner_name: dict[
        tuple[str, str], list[CharacterAbilityDefinitionIR]
    ] = defaultdict(list)
    for definition in definitions:
        if definition.definition_kind == "presentation":
            presentation_by_owner_name[
                (definition.owner_avatar_id, definition.ability_name)
            ].append(definition)
    for (avatar_id, ability_name), candidates in sorted(
        presentation_by_owner_name.items()
    ):
        remaining = tuple(
            definition
            for definition in candidates
            if definition.definition_id not in used_definition_ids
        )
        if not remaining:
            continue
        graph_id = graph_id_by_avatar[avatar_id]
        if len(remaining) != 1:
            add_gap(
                graph_id=graph_id,
                owner_avatar_id=avatar_id,
                action_source_id="",
                requested_ability_name=ability_name,
                expected_binding_kind="presentation",
                gap_kind="ambiguous_binding_blocked",
                candidate_definition_ids=(
                    definition.definition_id for definition in remaining
                ),
                searched_source_ids=searched_source_ids_by_avatar[avatar_id],
                source=remaining[0].source,
                blocked_reason="duplicate_presentation_ability_definitions",
            )
            continue
        definition = remaining[0]
        relation_source = typed_relation_source(
            graph_id=graph_id,
            owner_avatar_id=avatar_id,
            action_source_id="",
            skill_id="",
            ability_name=ability_name,
            binding_kind="presentation",
            ordinal=0,
            source_path=definition.source.source_path,
            json_path=cast(str, definition.source.evidence["json_path"]),
            content_sha256=cast(
                str, definition.source.evidence["content_sha256"]
            ),
        )
        relation_id = cast(str, relation_source.evidence["relation_id"])
        binding = CharacterAbilityBindingIR(
            binding_id=_stable_id(
                "character_ability_binding",
                relation_id,
                definition.definition_id,
            ),
            relation_id=relation_id,
            graph_id=graph_id,
            owner_avatar_id=avatar_id,
            action_source_id="",
            ability_definition_id=definition.definition_id,
            ability_name=ability_name,
            binding_kind="presentation",
            ordinal=0,
            relation_source=relation_source,
        )
        bindings.append(binding)
        graph_binding_ids[graph_id].append(binding.binding_id)

    own_gameplay_by_graph_name: dict[
        tuple[str, str], list[CharacterAbilityDefinitionIR]
    ] = defaultdict(list)
    for definition in definitions:
        if definition.definition_kind == "presentation":
            continue
        graph_id = graph_id_by_source_id[definition.source_id]
        own_gameplay_by_graph_name[(graph_id, definition.ability_name)].append(
            definition
        )
    for (graph_id, ability_name), candidates in sorted(
        own_gameplay_by_graph_name.items()
    ):
        remaining = tuple(
            definition
            for definition in candidates
            if definition.definition_id not in used_definition_ids
        )
        if not remaining:
            continue
        owner_avatar_id = remaining[0].owner_avatar_id
        if len(remaining) != 1:
            add_gap(
                graph_id=graph_id,
                owner_avatar_id=owner_avatar_id,
                action_source_id="",
                requested_ability_name=ability_name,
                expected_binding_kind="standalone",
                gap_kind="ambiguous_binding_blocked",
                candidate_definition_ids=(
                    definition.definition_id for definition in remaining
                ),
                searched_source_ids=(
                    searched_source_ids_by_avatar[owner_avatar_id]
                    if owner_avatar_id
                    else tuple(source.source_id for source in shared_sources)
                ),
                source=remaining[0].source,
                blocked_reason="duplicate_standalone_ability_definitions",
            )
            continue
        definition = remaining[0]
        relation_source = typed_relation_source(
            graph_id=graph_id,
            owner_avatar_id=owner_avatar_id,
            action_source_id="",
            skill_id="",
            ability_name=ability_name,
            binding_kind="standalone",
            ordinal=0,
            source_path=definition.source.source_path,
            json_path=cast(str, definition.source.evidence["json_path"]),
            content_sha256=cast(
                str, definition.source.evidence["content_sha256"]
            ),
        )
        relation_id = cast(str, relation_source.evidence["relation_id"])
        binding = CharacterAbilityBindingIR(
            binding_id=_stable_id(
                "character_ability_binding",
                relation_id,
                definition.definition_id,
            ),
            relation_id=relation_id,
            graph_id=graph_id,
            owner_avatar_id=owner_avatar_id,
            action_source_id="",
            ability_definition_id=definition.definition_id,
            ability_name=ability_name,
            binding_kind="standalone",
            ordinal=0,
            relation_source=relation_source,
        )
        bindings.append(binding)
        graph_binding_ids[graph_id].append(binding.binding_id)

    bindings.sort(key=lambda binding: binding.binding_id)
    gaps.sort(key=lambda gap: gap.gap_id)
    shared_graph_ids = tuple(
        sorted(
            graph_id_by_source_id[source.source_id] for source in shared_sources
        )
    )
    definitions_by_source_id: dict[str, list[str]] = defaultdict(list)
    presentation_definition_ids_by_avatar: dict[str, list[str]] = defaultdict(list)
    for definition in definitions:
        if definition.definition_kind == "presentation":
            presentation_definition_ids_by_avatar[definition.owner_avatar_id].append(
                definition.definition_id
            )
        else:
            definitions_by_source_id[definition.source_id].append(
                definition.definition_id
            )
    graphs: list[CharacterAbilitySourceGraphIR] = []
    for source in snapshot.sources:
        graph_id = graph_id_by_source_id[source.source_id]
        definition_ids = list(definitions_by_source_id[source.source_id])
        inventory_source: IRSource | None = None
        selected_skill_ids: tuple[str, ...] = ()
        if source.source_kind == "character_main":
            definition_ids.extend(
                presentation_definition_ids_by_avatar.get(source.avatar_id, ())
            )
            selected_row = rows_by_avatar[source.avatar_id][0]
            selected_skill_ids = selected_row.skill_ids
            inventory_source = _relation_source(
                source_path=selected_row.source_path,
                raw_type=Path(selected_row.source_path).stem,
                raw_id=source.avatar_id,
                evidence={
                    "source_id": source.source_id,
                    "avatar_id": source.avatar_id,
                    "row_index": selected_row.row_index,
                    "selected_version": selected_row.selected_version,
                    "character_config_path": selected_row.config_path,
                    "ability_source_path": selected_row.ability_source_path,
                    "skill_ids": selected_skill_ids,
                    "content_sha256": selected_row.content_sha256,
                },
            )
        graphs.append(
            CharacterAbilitySourceGraphIR(
                graph_id=graph_id,
                source_id=source.source_id,
                source_kind=source.source_kind,
                owner_avatar_id=source.avatar_id,
                definition_ids=tuple(definition_ids),
                action_source_ids=tuple(graph_action_ids.get(graph_id, ())),
                non_gameplay_skill_source_ids=tuple(
                    graph_non_gameplay_ids.get(graph_id, ())
                ),
                binding_ids=tuple(graph_binding_ids.get(graph_id, ())),
                gap_ids=tuple(graph_gap_ids.get(graph_id, ())),
                selected_skill_ids=selected_skill_ids,
                inventory_source=inventory_source,
                shared_graph_ids=(
                    shared_graph_ids
                    if source.source_kind == "character_main"
                    else ()
                ),
            )
        )

    build_counters = {
        "snapshot_build_count": snapshot_build_count,
        "scope_projection_build_count": scope_projection_build_count,
        "source_graph_build_count": 1,
        "ability_source_read_count": 0,
        "ability_source_parse_count": 0,
        "inventory_parse_count": len(snapshot.inventory_bytes),
        "relation_source_read_count": len(relation_documents),
        "relation_source_parse_count": len(relation_documents),
        "action_table_read_count": action_table_read_count,
        "action_table_selected_row_count": action_table_selected_row_count,
        "character_config_missing_count": len(missing_config_paths),
        "presentation_source_count": presentation_path_count,
        "presentation_candidate_missing_count": missing_presentation_path_count,
        "definition_count": len(definitions),
        "action_source_count": len(action_sources),
        "non_gameplay_skill_source_count": len(non_gameplay_skill_sources),
        "binding_count": len(bindings),
        "gap_count": len(gaps),
        "full_lowering_build_count": 0,
        "canonical_ir_build_count": 0,
        "rulebook_build_count": 0,
        "task_execution_count": 0,
        "condition_execution_count": 0,
        "target_execution_count": 0,
        "event_execution_count": 0,
    }
    return CharacterAbilitySourceGraphCatalogIR(
        snapshot_id=snapshot.snapshot_id,
        scope_catalog_id=scope_catalog.catalog_id,
        source_fingerprint=snapshot.source_fingerprint,
        fingerprint_kind=snapshot.fingerprint_kind,
        sources=snapshot.sources,
        relation_source_digests=relation_source_digests,
        definitions=tuple(definitions),
        action_sources=tuple(action_sources),
        non_gameplay_skill_sources=tuple(non_gameplay_skill_sources),
        bindings=tuple(bindings),
        gaps=tuple(gaps),
        graphs=tuple(graphs),
        build_counters=build_counters,
    )
