from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Literal, cast

from ..immutable_json import freeze_json, thaw_json
from ..ir_types import IRSource, JSONValue
from .expression_ir import is_exact_numeric_expression


FieldResponsibility = Literal[
    "control_structure",
    "condition_contract",
    "numeric_contract",
    "dynamic_context_contract",
    "target_contract",
    "ability_source_contract",
    "child_graph",
    "downstream_gameplay",
    "presentation_excluded",
    "unclassified",
]
NodeCoverage = Literal["lowered", "lowered_with_obligation", "blocked"]


def _source(value: IRSource, subject: str) -> IRSource:
    if type(value) is not IRSource:
        raise TypeError(f"{subject} source must be exact IRSource")
    if not value.source_path or not value.raw_type or not value.raw_id:
        raise ValueError(f"{subject} source identity is incomplete")
    if not isinstance(value.evidence, Mapping):
        raise TypeError(f"{subject} source evidence must be an object")
    json_path = value.evidence.get("json_path")
    content_sha256 = value.evidence.get("content_sha256")
    if not isinstance(json_path, str) or not json_path.startswith("$"):
        raise ValueError(f"{subject} source JSON path is invalid")
    if (
        not isinstance(content_sha256, str)
        or len(content_sha256) != 64
        or any(ch not in "0123456789abcdef" for ch in content_sha256)
    ):
        raise ValueError(f"{subject} source fingerprint is invalid")
    return IRSource(
        value.source_path,
        value.raw_type,
        value.raw_id,
        cast(dict[str, JSONValue], freeze_json(dict(value.evidence))),
    )


def _strings(values: object, subject: str, *, sorted_values: bool = False) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise TypeError(f"{subject} must be a tuple or list")
    result = tuple(values)
    if any(not isinstance(item, str) or not item for item in result):
        raise ValueError(f"{subject} must contain non-empty strings")
    if len(result) != len(set(result)):
        raise ValueError(f"{subject} contains duplicates")
    if sorted_values and result != tuple(sorted(result)):
        raise ValueError(f"{subject} must be sorted")
    return cast(tuple[str, ...], result)


@dataclass(frozen=True)
class ControlFlowFieldResponsibilityIR:
    field_name: str
    responsibility: FieldResponsibility
    owner_stage: str
    covers_subtree: bool
    source: IRSource

    def __post_init__(self) -> None:
        if not isinstance(self.field_name, str) or not self.field_name or self.field_name == "$type":
            raise ValueError("control-flow field identity is invalid")
        if self.responsibility not in {
            "control_structure",
            "condition_contract",
            "numeric_contract",
            "dynamic_context_contract",
            "target_contract",
            "ability_source_contract",
            "child_graph",
            "downstream_gameplay",
            "presentation_excluded",
            "unclassified",
        }:
            raise ValueError("control-flow field responsibility is invalid")
        if not isinstance(self.owner_stage, str) or not self.owner_stage:
            raise ValueError("control-flow field owner is required")
        if type(self.covers_subtree) is not bool:
            raise TypeError("control-flow subtree flag must be bool")
        object.__setattr__(self, "source", _source(self.source, "control-flow field"))

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "field_name": self.field_name,
            "responsibility": self.responsibility,
            "owner_stage": self.owner_stage,
            "covers_subtree": self.covers_subtree,
            "source": self.source.to_json(),
        }


@dataclass(frozen=True)
class ControlFlowChildSourceIR:
    record_id: str
    family: str
    semantic_kind: str
    effective_scope: str
    ordinal: int
    source: IRSource

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value
            for value in (self.record_id, self.family, self.semantic_kind, self.effective_scope)
        ):
            raise ValueError("control-flow child source identity is incomplete")
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("control-flow child ordinal is invalid")
        object.__setattr__(self, "source", _source(self.source, "control-flow child"))

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "record_id": self.record_id,
            "family": self.family,
            "semantic_kind": self.semantic_kind,
            "effective_scope": self.effective_scope,
            "ordinal": self.ordinal,
            "source": self.source.to_json(),
        }


@dataclass(frozen=True)
class ControlFlowBranchIR:
    branch_id: str
    node_id: str
    branch_kind: str
    ordinal: int
    label: str
    children: tuple[ControlFlowChildSourceIR, ...]
    source: IRSource

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value
            for value in (self.branch_id, self.node_id, self.branch_kind)
        ) or not isinstance(self.label, str):
            raise ValueError("control-flow branch identity is invalid")
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("control-flow branch ordinal is invalid")
        children = tuple(self.children)
        if any(type(item) is not ControlFlowChildSourceIR for item in children):
            raise TypeError("control-flow branch children are invalid")
        if tuple(item.ordinal for item in children) != tuple(range(len(children))):
            raise ValueError("control-flow branch child order is not canonical")
        object.__setattr__(self, "children", children)
        object.__setattr__(self, "source", _source(self.source, "control-flow branch"))

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "branch_id": self.branch_id,
            "node_id": self.node_id,
            "branch_kind": self.branch_kind,
            "ordinal": self.ordinal,
            "label": self.label,
            "children": [item.to_json() for item in self.children],
            "source": self.source.to_json(),
        }


@dataclass(frozen=True)
class ControlFlowTerminationIR:
    node_id: str
    termination_kind: Literal[
        "not_applicable",
        "count_expression",
        "condition_with_source_cap",
        "condition_progress_required",
        "finite_target_collection",
    ]
    status: Literal["not_applicable", "source_backed", "runtime_proof_required", "blocked"]
    owner_stage: str
    expression: Mapping[str, Any] | None
    blocked_reason: str
    source: IRSource

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id:
            raise ValueError("control-flow termination node is required")
        if self.termination_kind not in {
            "not_applicable",
            "count_expression",
            "condition_with_source_cap",
            "condition_progress_required",
            "finite_target_collection",
        } or self.status not in {
            "not_applicable",
            "source_backed",
            "runtime_proof_required",
            "blocked",
        }:
            raise ValueError("control-flow termination classification is invalid")
        if not isinstance(self.owner_stage, str) or not self.owner_stage:
            raise ValueError("control-flow termination owner is required")
        expression = self.expression
        if expression is not None:
            if not isinstance(expression, Mapping):
                raise TypeError("control-flow termination expression must be an object")
            if not is_exact_numeric_expression(expression):
                raise ValueError("control-flow termination expression is not exact numeric IR")
            expression = cast(Mapping[str, Any], freeze_json(dict(expression)))
        if (self.status == "blocked") != bool(self.blocked_reason):
            raise ValueError("control-flow termination blocker is inconsistent")
        if self.termination_kind in {"count_expression", "condition_with_source_cap"} and expression is None:
            raise ValueError("source-counted control-flow termination requires an expression")
        if self.termination_kind not in {"count_expression", "condition_with_source_cap"} and expression is not None:
            raise ValueError("non-counted control-flow termination cannot carry an expression")
        valid_statuses = {
            "not_applicable": {"not_applicable"},
            "count_expression": {"source_backed", "blocked"},
            "condition_with_source_cap": {"source_backed", "blocked"},
            "condition_progress_required": {"runtime_proof_required"},
            "finite_target_collection": {"source_backed"},
        }
        if self.status not in valid_statuses[self.termination_kind]:
            raise ValueError("control-flow termination kind and status are inconsistent")
        object.__setattr__(self, "expression", expression)
        object.__setattr__(self, "source", _source(self.source, "control-flow termination"))

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "node_id": self.node_id,
            "termination_kind": self.termination_kind,
            "status": self.status,
            "owner_stage": self.owner_stage,
            "expression": cast(JSONValue, thaw_json(self.expression)),
            "blocked_reason": self.blocked_reason,
            "source": self.source.to_json(),
        }


@dataclass(frozen=True)
class ControlFlowTemplateParameterIR:
    parameter_id: str
    template_id: str
    parameter_kind: Literal["dynamic_float", "dynamic_string"]
    key: str
    index: int | None
    read_type: str
    declared_value: str
    source: IRSource

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value for value in (self.parameter_id, self.template_id, self.key)):
            raise ValueError("control-flow template parameter identity is invalid")
        if self.parameter_kind == "dynamic_float":
            if type(self.index) is not int or self.index < 0 or not isinstance(self.read_type, str) or not self.read_type or self.declared_value:
                raise ValueError("control-flow float template parameter is invalid")
        elif self.parameter_kind == "dynamic_string":
            if self.index is not None or self.read_type or not isinstance(self.declared_value, str):
                raise ValueError("control-flow string template parameter is invalid")
        else:
            raise ValueError("control-flow template parameter kind is invalid")
        object.__setattr__(self, "source", _source(self.source, "control-flow template parameter"))

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "parameter_id": self.parameter_id,
            "template_id": self.template_id,
            "parameter_kind": self.parameter_kind,
            "key": self.key,
            "index": self.index,
            "read_type": self.read_type,
            "declared_value": self.declared_value,
            "source": self.source.to_json(),
        }


@dataclass(frozen=True)
class ControlFlowTemplateDefinitionIR:
    template_id: str
    name: str
    scope_kind: Literal["document_global", "local", "shared_global"]
    namespace_path: str
    parameters: tuple[ControlFlowTemplateParameterIR, ...]
    children: tuple[ControlFlowChildSourceIR, ...]
    source: IRSource

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value
            for value in (self.template_id, self.name, self.namespace_path)
        ) or self.scope_kind not in {"document_global", "local", "shared_global"}:
            raise ValueError("control-flow template definition is invalid")
        parameters = tuple(self.parameters)
        if any(type(item) is not ControlFlowTemplateParameterIR or item.template_id != self.template_id for item in parameters):
            raise TypeError("control-flow template parameters are invalid")
        if tuple((item.parameter_kind, item.key) for item in parameters) != tuple(sorted((item.parameter_kind, item.key) for item in parameters)):
            raise ValueError("control-flow template parameter order is not canonical")
        parameter_ids = tuple(item.parameter_id for item in parameters)
        if len(parameter_ids) != len(set(parameter_ids)):
            raise ValueError("control-flow template contains duplicate parameter identities")
        children = tuple(self.children)
        if any(type(item) is not ControlFlowChildSourceIR for item in children):
            raise TypeError("control-flow template children are invalid")
        if tuple(item.ordinal for item in children) != tuple(range(len(children))):
            raise ValueError("control-flow template child order is not canonical")
        source = _source(self.source, "control-flow template")
        template_path = source.evidence["json_path"]
        content_sha256 = source.evidence["content_sha256"]
        if any(
            item.source.source_path != source.source_path
            or item.source.evidence.get("content_sha256") != content_sha256
            or not str(item.source.evidence.get("json_path", "")).startswith(f"{template_path}.Dynamic")
            for item in parameters
        ):
            raise ValueError("control-flow template parameter source is inconsistent")
        if any(
            item.source.source_path != source.source_path
            or item.source.evidence.get("content_sha256") != content_sha256
            or not str(item.source.evidence.get("json_path", "")).startswith(f"{template_path}.TaskList[")
            for item in children
        ):
            raise ValueError("control-flow template child source is inconsistent")
        object.__setattr__(self, "parameters", parameters)
        object.__setattr__(self, "children", children)
        object.__setattr__(self, "source", source)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "template_id": self.template_id,
            "name": self.name,
            "scope_kind": self.scope_kind,
            "namespace_path": self.namespace_path,
            "parameters": [item.to_json() for item in self.parameters],
            "children": [item.to_json() for item in self.children],
            "source": self.source.to_json(),
        }


@dataclass(frozen=True)
class ControlFlowTemplateReferenceIR:
    reference_id: str
    node_id: str
    name: str
    reference_kind: Literal[
        "local_document_or_shared_global",
        "document_or_shared_global",
        "parallel_local",
    ]
    candidate_template_ids: tuple[str, ...]
    resolved_template_id: str
    source: IRSource
    coverage_status: Literal["lowered", "blocked"]
    blocked_reason: str

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value
            for value in (self.reference_id, self.node_id, self.name)
        ) or self.reference_kind not in {
            "local_document_or_shared_global",
            "document_or_shared_global",
            "parallel_local",
        }:
            raise ValueError("control-flow template reference is invalid")
        candidates = _strings(
            self.candidate_template_ids,
            "control-flow template candidates",
            sorted_values=True,
        )
        if self.coverage_status == "lowered":
            if self.blocked_reason or len(candidates) != 1 or self.resolved_template_id != candidates[0]:
                raise ValueError("resolved control-flow template reference is inconsistent")
        elif self.coverage_status == "blocked":
            if not self.blocked_reason or self.resolved_template_id:
                raise ValueError("blocked control-flow template reference is inconsistent")
        else:
            raise ValueError("control-flow template reference coverage is invalid")
        object.__setattr__(self, "candidate_template_ids", candidates)
        object.__setattr__(self, "source", _source(self.source, "control-flow template reference"))

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "reference_id": self.reference_id,
            "node_id": self.node_id,
            "name": self.name,
            "reference_kind": self.reference_kind,
            "candidate_template_ids": list(self.candidate_template_ids),
            "resolved_template_id": self.resolved_template_id,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class CharacterControlFlowNodeIR:
    node_id: str
    scope_record_id: str
    family: str
    control_role: str
    peer_field_names: tuple[str, ...]
    field_responsibilities: tuple[ControlFlowFieldResponsibilityIR, ...]
    branches: tuple[ControlFlowBranchIR, ...]
    template_reference_ids: tuple[str, ...]
    termination: ControlFlowTerminationIR
    downstream_stages: tuple[str, ...]
    source: IRSource
    coverage_status: NodeCoverage
    blocked_reason: str

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value
            for value in (self.node_id, self.scope_record_id, self.family, self.control_role)
        ):
            raise ValueError("control-flow node identity is invalid")
        fields = _strings(self.peer_field_names, "control-flow peer fields", sorted_values=True)
        responsibilities = tuple(self.field_responsibilities)
        branches = tuple(self.branches)
        if any(type(item) is not ControlFlowFieldResponsibilityIR for item in responsibilities):
            raise TypeError("control-flow field responsibilities are invalid")
        if tuple(sorted(item.field_name for item in responsibilities)) != fields:
            raise ValueError("control-flow peer field responsibility is not one-to-one")
        if any(type(item) is not ControlFlowBranchIR or item.node_id != self.node_id for item in branches):
            raise TypeError("control-flow node branches are invalid")
        if tuple(item.ordinal for item in branches) != tuple(range(len(branches))):
            raise ValueError("control-flow node branch order is not canonical")
        branch_ids = tuple(item.branch_id for item in branches)
        if len(branch_ids) != len(set(branch_ids)):
            raise ValueError("control-flow node contains duplicate branch identities")
        if type(self.termination) is not ControlFlowTerminationIR or self.termination.node_id != self.node_id:
            raise TypeError("control-flow node termination is invalid")
        source = _source(self.source, "control-flow node")
        node_path = str(source.evidence["json_path"])
        content_sha256 = source.evidence["content_sha256"]
        if any(
            item.source.source_path != source.source_path
            or item.source.raw_type != self.family
            or item.source.raw_id != f"{self.node_id}:{item.field_name}"
            or item.source.evidence.get("node_id") != self.node_id
            or item.source.evidence.get("field_name") != item.field_name
            or item.source.evidence.get("content_sha256") != content_sha256
            or item.source.evidence.get("json_path") != f"{node_path}.{item.field_name}"
            for item in responsibilities
        ):
            raise ValueError("control-flow field source is inconsistent")
        if any(
            item.source.source_path != source.source_path
            or item.source.raw_type != self.family
            or item.source.raw_id != item.branch_id
            or item.source.evidence.get("node_id") != self.node_id
            or item.source.evidence.get("branch_kind") != item.branch_kind
            or item.source.evidence.get("content_sha256") != content_sha256
            or not str(item.source.evidence.get("json_path", "")).startswith(node_path)
            or any(
                child.source.source_path != source.source_path
                or child.source.evidence.get("content_sha256") != content_sha256
                or not str(child.source.evidence.get("json_path", "")).startswith(
                    str(item.source.evidence["json_path"])
                )
                for child in item.children
            )
            for item in branches
        ):
            raise ValueError("control-flow branch source is inconsistent")
        if self.termination.source != source:
            raise ValueError("control-flow termination source is inconsistent")
        refs = _strings(
            self.template_reference_ids,
            "control-flow template reference ids",
            sorted_values=True,
        )
        stages = _strings(self.downstream_stages, "control-flow downstream stages", sorted_values=True)
        if self.coverage_status == "blocked":
            if not self.blocked_reason:
                raise ValueError("blocked control-flow node requires a reason")
        elif self.coverage_status == "lowered_with_obligation":
            if self.blocked_reason or not stages:
                raise ValueError("control-flow obligation status is inconsistent")
        elif self.coverage_status == "lowered":
            if self.blocked_reason or stages:
                raise ValueError("lowered control-flow node cannot carry a gap")
        else:
            raise ValueError("control-flow node coverage is invalid")
        object.__setattr__(self, "peer_field_names", fields)
        object.__setattr__(self, "field_responsibilities", responsibilities)
        object.__setattr__(self, "branches", branches)
        object.__setattr__(self, "template_reference_ids", refs)
        object.__setattr__(self, "downstream_stages", stages)
        object.__setattr__(self, "source", source)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "node_id": self.node_id,
            "scope_record_id": self.scope_record_id,
            "family": self.family,
            "control_role": self.control_role,
            "peer_field_names": list(self.peer_field_names),
            "field_responsibilities": [item.to_json() for item in self.field_responsibilities],
            "branches": [item.to_json() for item in self.branches],
            "template_reference_ids": list(self.template_reference_ids),
            "termination": self.termination.to_json(),
            "downstream_stages": list(self.downstream_stages),
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(frozen=True)
class ControlFlowContractIssueIR:
    code: str
    subject: str
    owner_stage: str
    detail: str
    source: IRSource

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value for value in (self.code, self.subject, self.owner_stage)):
            raise ValueError("control-flow issue identity is invalid")
        if not isinstance(self.detail, str):
            raise TypeError("control-flow issue detail must be a string")
        object.__setattr__(self, "source", _source(self.source, "control-flow issue"))

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "code": self.code,
            "subject": self.subject,
            "owner_stage": self.owner_stage,
            "detail": self.detail,
            "source": self.source.to_json(),
        }


@dataclass(frozen=True)
class CharacterControlFlowContractCatalog:
    snapshot_id: str
    scope_catalog_id: str
    source_fingerprint: str
    dependency_fingerprint: str
    nodes: tuple[CharacterControlFlowNodeIR, ...]
    template_definitions: tuple[ControlFlowTemplateDefinitionIR, ...]
    template_references: tuple[ControlFlowTemplateReferenceIR, ...]
    issues: tuple[ControlFlowContractIssueIR, ...]
    denominator_record_ids: tuple[str, ...]
    direct_record_count: int
    ancestor_context_count: int
    family_counts: Mapping[str, Any]
    build_counters: Mapping[str, Any]
    catalog_id: str = field(init=False)

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value
            for value in (
                self.snapshot_id,
                self.scope_catalog_id,
                self.source_fingerprint,
                self.dependency_fingerprint,
            )
        ):
            raise ValueError("control-flow catalog source identity is incomplete")
        if any(len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value) for value in (self.source_fingerprint, self.dependency_fingerprint)):
            raise ValueError("control-flow catalog fingerprints must be sha256")
        collections = (
            (tuple(self.nodes), CharacterControlFlowNodeIR, "node_id"),
            (tuple(self.template_definitions), ControlFlowTemplateDefinitionIR, "template_id"),
            (tuple(self.template_references), ControlFlowTemplateReferenceIR, "reference_id"),
            (tuple(self.issues), ControlFlowContractIssueIR, ""),
        )
        normalized: list[tuple[Any, ...]] = []
        for values, expected, identity_field in collections:
            if any(type(item) is not expected for item in values):
                raise TypeError("control-flow catalog contains an invalid typed value")
            if identity_field:
                identities = tuple(getattr(item, identity_field) for item in values)
                if len(identities) != len(set(identities)):
                    raise ValueError(f"control-flow catalog duplicate {identity_field}")
            normalized.append(values)
        nodes, templates, references, issues = normalized
        node_ids = {item.node_id for item in nodes}
        scope_record_ids = tuple(item.scope_record_id for item in nodes)
        if len(scope_record_ids) != len(set(scope_record_ids)):
            raise ValueError("control-flow catalog contains duplicate source records")
        denominator_record_ids = _strings(
            self.denominator_record_ids,
            "control-flow denominator records",
            sorted_values=True,
        )
        if set(denominator_record_ids) != set(scope_record_ids):
            raise ValueError("control-flow catalog omits a denominator source record")
        template_ids = {item.template_id for item in templates}
        reference_ids = {item.reference_id for item in references}
        if any(item.node_id not in node_ids for item in references):
            raise ValueError("control-flow template reference has a dangling node")
        if any(set(item.candidate_template_ids) - template_ids for item in references):
            raise ValueError("control-flow template reference has a dangling candidate")
        if any(set(item.template_reference_ids) - reference_ids for item in nodes):
            raise ValueError("control-flow node has a dangling template reference")
        references_by_node: dict[str, set[str]] = {item.node_id: set() for item in nodes}
        for item in references:
            references_by_node[item.node_id].add(item.reference_id)
        if any(
            set(item.template_reference_ids) != references_by_node[item.node_id]
            for item in nodes
        ):
            raise ValueError("control-flow node and template references are not bidirectionally closed")
        node_by_id = {item.node_id: item for item in nodes}
        node_by_source_record = {item.scope_record_id: item for item in nodes}
        selected_children = tuple(
            child
            for node in nodes
            for branch in node.branches
            for child in branch.children
            if child.record_id in node_by_source_record
        )
        selected_child_ids = tuple(item.record_id for item in selected_children)
        if len(selected_child_ids) != len(set(selected_child_ids)):
            raise ValueError("control-flow source occurrence has multiple parent branches")
        if any(
            child.family != node_by_source_record[child.record_id].family
            or child.source.source_path
            != node_by_source_record[child.record_id].source.source_path
            or child.source.evidence.get("content_sha256")
            != node_by_source_record[child.record_id].source.evidence.get("content_sha256")
            or str(child.source.evidence.get("json_path", "")).removesuffix(".$type")
            != node_by_source_record[child.record_id].source.evidence.get("json_path")
            for child in selected_children
        ):
            raise ValueError("control-flow selected child source is not closed to its node")
        if any(
            item.source.source_path != node_by_id[item.node_id].source.source_path
            or item.source.raw_type != node_by_id[item.node_id].family
            or item.source.evidence.get("node_id") != item.node_id
            or item.source.evidence.get("content_sha256")
            != node_by_id[item.node_id].source.evidence.get("content_sha256")
            or not str(item.source.evidence.get("json_path", "")).startswith(
                str(node_by_id[item.node_id].source.evidence["json_path"])
            )
            for item in references
        ):
            raise ValueError("control-flow template reference source is inconsistent")
        template_fetch_names: dict[str, set[str]] = {
            item.template_id: set() for item in templates
        }
        for node in nodes:
            node_path = str(node.source.evidence["json_path"])
            owners = tuple(
                item
                for item in templates
                if item.source.source_path == node.source.source_path
                and node_path.startswith(
                    f'{item.source.evidence["json_path"]}.TaskList['
                )
            )
            if not owners:
                continue
            owner = max(
                owners,
                key=lambda item: len(str(item.source.evidence["json_path"])),
            )
            template_fetch_names[owner.template_id].update(
                branch.label
                for branch in node.branches
                if branch.branch_kind == "template_parameter_fetch"
            )
        for reference in references:
            if reference.coverage_status != "lowered":
                continue
            caller = node_by_id[reference.node_id]
            provided = {
                branch.label
                for branch in caller.branches
                if branch.branch_kind == "template_parameter_sequence"
            }
            required = template_fetch_names[reference.resolved_template_id]
            if provided != required:
                raise ValueError("control-flow template parameter subgraph is not closed")
        if type(self.direct_record_count) is not int or self.direct_record_count != len(nodes):
            raise ValueError("control-flow direct record count is inconsistent")
        if type(self.ancestor_context_count) is not int or self.ancestor_context_count < 0:
            raise ValueError("control-flow ancestor context count is invalid")
        family_counts = freeze_json(dict(self.family_counts))
        build_counters = freeze_json(dict(self.build_counters))
        if (
            not isinstance(family_counts, dict)
            or any(not isinstance(key, str) or not key for key in family_counts)
            or any(type(value) is not int or value < 0 for value in family_counts.values())
            or sum(family_counts.values()) != len(nodes)
        ):
            raise ValueError("control-flow family counts do not reconcile")
        if (
            not isinstance(build_counters, dict)
            or any(not isinstance(key, str) or not key for key in build_counters)
            or any(
                not (type(value) is bool or (type(value) is int and value >= 0))
                for value in build_counters.values()
            )
        ):
            raise ValueError("control-flow build counters are invalid")
        identity = json.dumps(
            {
                "snapshot_id": self.snapshot_id,
                "scope_catalog_id": self.scope_catalog_id,
                "source_fingerprint": self.source_fingerprint,
                "dependency_fingerprint": self.dependency_fingerprint,
                "node_ids": sorted(node_ids),
                "template_ids": sorted(template_ids),
                "reference_ids": sorted(reference_ids),
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        object.__setattr__(self, "nodes", tuple(sorted(nodes, key=lambda item: item.node_id)))
        object.__setattr__(self, "template_definitions", tuple(sorted(templates, key=lambda item: item.template_id)))
        object.__setattr__(self, "template_references", tuple(sorted(references, key=lambda item: item.reference_id)))
        object.__setattr__(self, "issues", tuple(sorted(issues, key=lambda item: (item.code, item.subject, item.detail))))
        object.__setattr__(self, "denominator_record_ids", denominator_record_ids)
        object.__setattr__(self, "family_counts", family_counts)
        object.__setattr__(self, "build_counters", build_counters)
        object.__setattr__(self, "catalog_id", f"character_control_flow_catalog:{sha256(identity).hexdigest()}")

    @property
    def complete(self) -> bool:
        return not self.issues and all(item.coverage_status != "blocked" for item in self.nodes) and all(
            item.coverage_status == "lowered" for item in self.template_references
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "catalog_id": self.catalog_id,
            "snapshot_id": self.snapshot_id,
            "scope_catalog_id": self.scope_catalog_id,
            "source_fingerprint": self.source_fingerprint,
            "dependency_fingerprint": self.dependency_fingerprint,
            "nodes": [item.to_json() for item in self.nodes],
            "template_definitions": [item.to_json() for item in self.template_definitions],
            "template_references": [item.to_json() for item in self.template_references],
            "issues": [item.to_json() for item in self.issues],
            "denominator_record_ids": list(self.denominator_record_ids),
            "direct_record_count": self.direct_record_count,
            "ancestor_context_count": self.ancestor_context_count,
            "family_counts": cast(JSONValue, thaw_json(self.family_counts)),
            "build_counters": cast(JSONValue, thaw_json(self.build_counters)),
            "complete": self.complete,
        }
