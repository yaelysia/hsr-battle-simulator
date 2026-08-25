from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Literal, cast

from ..immutable_json import freeze_json, thaw_json
from ..ir_types import IRSource, JSONValue
from .expression_ir import is_exact_numeric_expression


SourceKind = Literal["control_node", "template_definition", "template_reference"]
Disposition = Literal["materialized", "deferred", "blocked"]
EntryKind = Literal["ability_phase_callback", "status_callback"]
ScopeMode = Literal["complete_catalog", "formal_slice", "formal_catalog"]
NodeKind = Literal[
    "leaf",
    "branch",
    "loop",
    "target_scope",
    "template_call",
    "ability_call",
    "template_parameter",
    "sequence",
    "deferred",
]
ReferenceKind = Literal["condition", "target", "numeric", "effect", "ability", "template"]
ResolutionStatus = Literal["resolved", "deferred", "blocked"]


def _id(prefix: str, *parts: object) -> str:
    payload = json.dumps(
        [str(part) for part in parts],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{prefix}:{sha256(payload).hexdigest()}"


def task_graph_source_occurrence_id(source: IRSource, family: str) -> str:
    source = _source(source, "task graph occurrence")
    return _id(
        "task_graph_source",
        source.source_path,
        source.evidence["json_path"],
        family,
        source.evidence["content_sha256"],
    )


def task_graph_source_record_fingerprint(record_ids: tuple[str, ...]) -> str:
    values = _strings(record_ids, "task graph source record identities")
    payload = json.dumps(values, ensure_ascii=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return sha256(payload).hexdigest()


def task_graph_entry_id(entry_kind: EntryKind, owner_id: str, callback_kind: str) -> str:
    if entry_kind not in {"ability_phase_callback", "status_callback"}:
        raise ValueError("task graph entry kind is invalid")
    if not owner_id or not callback_kind:
        raise ValueError("task graph entry identity is incomplete")
    return _id("task_graph_entry", entry_kind, owner_id, callback_kind)


def task_graph_id(source_catalog_id: str, entry_id: str, source_fingerprint: str) -> str:
    return _id("task_graph", source_catalog_id, entry_id, source_fingerprint)


def task_graph_node_id(graph_id: str, formal_task_id: str, occurrence_id: str) -> str:
    return _id("task_graph_node", graph_id, formal_task_id, occurrence_id)


def _exact(value: object, fields: set[str], subject: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"{subject} JSON schema is invalid")
    return cast(Mapping[str, Any], value)


def _string(value: Mapping[str, Any], field_name: str, subject: str) -> str:
    result = value.get(field_name)
    if not isinstance(result, str):
        raise TypeError(f"{subject} {field_name} must be a string")
    return result


def _strings(value: object, subject: str, *, ordered: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise TypeError(f"{subject} must be a tuple or list")
    result = tuple(value)
    if any(not isinstance(item, str) or not item for item in result):
        raise ValueError(f"{subject} contains an invalid identity")
    if len(result) != len(set(result)):
        raise ValueError(f"{subject} contains duplicates")
    if not ordered and result != tuple(sorted(result)):
        raise ValueError(f"{subject} must be sorted")
    return cast(tuple[str, ...], result)


def _ordered_string_sequence(value: object, subject: str) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise TypeError(f"{subject} must be a tuple or list")
    result = tuple(value)
    if not result or any(not isinstance(item, str) or not item for item in result):
        raise ValueError(f"{subject} contains an invalid identity")
    return cast(tuple[str, ...], result)


def _domain(value: str, subject: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("p9_"):
        raise ValueError(f"{subject} must use a domain semantic identity")
    return value


def _sha256(value: str, subject: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{subject} must be a sha256 fingerprint")
    return value


def _source(value: IRSource, subject: str) -> IRSource:
    if type(value) is not IRSource:
        raise TypeError(f"{subject} source must be exact IRSource")
    if any(not isinstance(item, str) or not item for item in (value.source_path, value.raw_type, value.raw_id)):
        raise ValueError(f"{subject} source identity is incomplete")
    if not isinstance(value.evidence, Mapping):
        raise TypeError(f"{subject} source evidence must be an object")
    path = value.evidence.get("json_path")
    digest = value.evidence.get("content_sha256")
    if not isinstance(path, str) or not path.startswith("$"):
        raise ValueError(f"{subject} source path is invalid")
    _sha256(cast(Any, digest), f"{subject} source fingerprint")
    evidence = freeze_json(dict(value.evidence))
    if not isinstance(evidence, dict):
        raise TypeError(f"{subject} source evidence did not freeze as an object")
    return IRSource(value.source_path, value.raw_type, value.raw_id, evidence)


def _source_from_json(value: object, subject: str) -> IRSource:
    item = _exact(value, {"source_path", "raw_type", "raw_id", "evidence"}, subject)
    evidence = item.get("evidence")
    if not isinstance(evidence, Mapping):
        raise TypeError(f"{subject} evidence must be an object")
    return _source(
        IRSource(
            _string(item, "source_path", subject),
            _string(item, "raw_type", subject),
            _string(item, "raw_id", subject),
            dict(evidence),
        ),
        subject,
    )


@dataclass(frozen=True)
class TaskGraphSourceDispositionIR:
    source_record_id: str
    source_kind: SourceKind
    source_occurrence_id: str
    family: str
    disposition: Disposition
    owner_domains: tuple[str, ...]
    formal_materialization_ids: tuple[str, ...]
    source: IRSource
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        if type(self) is not TaskGraphSourceDispositionIR:
            raise TypeError("task graph source disposition must not be subclassed")
        if self.source_kind not in {"control_node", "template_definition", "template_reference"}:
            raise ValueError("task graph source kind is invalid")
        if self.disposition not in {"materialized", "deferred", "blocked"}:
            raise ValueError("task graph source disposition is invalid")
        if any(not isinstance(value, str) or not value for value in (self.source_record_id, self.family)):
            raise ValueError("task graph source disposition identity is incomplete")
        source = _source(self.source, "task graph source disposition")
        if self.source_occurrence_id != task_graph_source_occurrence_id(source, self.family):
            raise ValueError("task graph source occurrence identity is inconsistent")
        domains = _strings(self.owner_domains, "task graph source owner domains")
        for domain in domains:
            _domain(domain, "task graph source owner")
        materializations = _strings(
            self.formal_materialization_ids,
            "task graph formal materialization identities",
        )
        if self.disposition == "blocked":
            if not self.blocked_reason or materializations:
                raise ValueError("blocked task graph source disposition is inconsistent")
        elif self.blocked_reason:
            raise ValueError("non-blocked task graph source disposition carries a blocker")
        if self.disposition == "deferred" and not domains:
            raise ValueError("deferred task graph source disposition requires an owner")
        if self.disposition == "materialized" and domains:
            raise ValueError("materialized task graph source disposition retains an owner")
        object.__setattr__(self, "owner_domains", domains)
        object.__setattr__(self, "formal_materialization_ids", materializations)
        object.__setattr__(self, "source", source)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "source_record_id": self.source_record_id,
            "source_kind": self.source_kind,
            "source_occurrence_id": self.source_occurrence_id,
            "family": self.family,
            "disposition": self.disposition,
            "owner_domains": list(self.owner_domains),
            "formal_materialization_ids": list(self.formal_materialization_ids),
            "source": self.source.to_json(),
            "blocked_reason": self.blocked_reason,
        }

    @classmethod
    def from_json(cls, value: object) -> "TaskGraphSourceDispositionIR":
        item = _exact(value, {
            "source_record_id", "source_kind", "source_occurrence_id", "family",
            "disposition", "owner_domains", "formal_materialization_ids", "source",
            "blocked_reason",
        }, "task graph source disposition")
        return cls(
            source_record_id=_string(item, "source_record_id", "task graph source disposition"),
            source_kind=cast(Any, _string(item, "source_kind", "task graph source disposition")),
            source_occurrence_id=_string(item, "source_occurrence_id", "task graph source disposition"),
            family=_string(item, "family", "task graph source disposition"),
            disposition=cast(Any, _string(item, "disposition", "task graph source disposition")),
            owner_domains=_strings(item.get("owner_domains"), "task graph source owner domains"),
            formal_materialization_ids=_strings(item.get("formal_materialization_ids"), "task graph formal materialization identities"),
            source=_source_from_json(item.get("source"), "task graph source disposition"),
            blocked_reason=_string(item, "blocked_reason", "task graph source disposition"),
        )


@dataclass(frozen=True)
class TaskGraphDefinitionReferenceIR:
    reference_id: str
    graph_node_id: str
    reference_kind: ReferenceKind
    definition_id: str
    source_contract_record_id: str
    resolution_status: ResolutionStatus
    owner_domain: str
    source: IRSource
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        if type(self) is not TaskGraphDefinitionReferenceIR:
            raise TypeError("task graph reference must not be subclassed")
        if self.reference_kind not in {"condition", "target", "numeric", "effect", "ability", "template"}:
            raise ValueError("task graph reference kind is invalid")
        if self.resolution_status not in {"resolved", "deferred", "blocked"}:
            raise ValueError("task graph reference status is invalid")
        if any(not isinstance(value, str) or not value for value in (self.graph_node_id, self.definition_id, self.owner_domain)):
            raise ValueError("task graph reference identity is incomplete")
        _domain(self.owner_domain, "task graph reference owner")
        if not isinstance(self.source_contract_record_id, str):
            raise TypeError("task graph source contract reference must be a string")
        if (self.reference_kind == "template") != bool(self.source_contract_record_id):
            raise ValueError("task graph source contract reference is inconsistent")
        expected = _id("task_graph_reference", self.graph_node_id, self.reference_kind, self.definition_id)
        if self.reference_id != expected:
            raise ValueError("task graph reference identity is inconsistent")
        if (self.resolution_status == "resolved") == bool(self.blocked_reason):
            raise ValueError("task graph reference blocker is inconsistent")
        object.__setattr__(self, "source", _source(self.source, "task graph reference"))

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "reference_id": self.reference_id,
            "graph_node_id": self.graph_node_id,
            "reference_kind": self.reference_kind,
            "definition_id": self.definition_id,
            "source_contract_record_id": self.source_contract_record_id,
            "resolution_status": self.resolution_status,
            "owner_domain": self.owner_domain,
            "source": self.source.to_json(),
            "blocked_reason": self.blocked_reason,
        }

    @classmethod
    def from_json(cls, value: object) -> "TaskGraphDefinitionReferenceIR":
        item = _exact(value, {
            "reference_id", "graph_node_id", "reference_kind", "definition_id", "source_contract_record_id",
            "resolution_status", "owner_domain", "source", "blocked_reason",
        }, "task graph reference")
        return cls(
            reference_id=_string(item, "reference_id", "task graph reference"),
            graph_node_id=_string(item, "graph_node_id", "task graph reference"),
            reference_kind=cast(Any, _string(item, "reference_kind", "task graph reference")),
            definition_id=_string(item, "definition_id", "task graph reference"),
            source_contract_record_id=_string(item, "source_contract_record_id", "task graph reference"),
            resolution_status=cast(Any, _string(item, "resolution_status", "task graph reference")),
            owner_domain=_string(item, "owner_domain", "task graph reference"),
            source=_source_from_json(item.get("source"), "task graph reference"),
            blocked_reason=_string(item, "blocked_reason", "task graph reference"),
        )


@dataclass(frozen=True)
class TaskGraphNumericDefinitionIR:
    definition_id: str
    source_occurrence_id: str
    expression: Mapping[str, Any]
    source: IRSource

    def __post_init__(self) -> None:
        if type(self) is not TaskGraphNumericDefinitionIR:
            raise TypeError("task graph numeric definition must not be subclassed")
        if not self.source_occurrence_id:
            raise ValueError("task graph numeric source occurrence is required")
        if not isinstance(self.expression, Mapping) or not is_exact_numeric_expression(self.expression):
            raise ValueError("task graph numeric expression is invalid")
        expression = freeze_json(dict(self.expression))
        source = _source(self.source, "task graph numeric definition")
        expected = _id(
            "task_graph_numeric",
            self.source_occurrence_id,
            json.dumps(thaw_json(expression), sort_keys=True, separators=(",", ":")),
        )
        if self.definition_id != expected:
            raise ValueError("task graph numeric identity is inconsistent")
        object.__setattr__(self, "expression", expression)
        object.__setattr__(self, "source", source)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "definition_id": self.definition_id,
            "source_occurrence_id": self.source_occurrence_id,
            "expression": cast(JSONValue, thaw_json(self.expression)),
            "source": self.source.to_json(),
        }

    @classmethod
    def from_json(cls, value: object) -> "TaskGraphNumericDefinitionIR":
        item = _exact(value, {"definition_id", "source_occurrence_id", "expression", "source"}, "task graph numeric definition")
        expression = item.get("expression")
        if not isinstance(expression, Mapping):
            raise TypeError("task graph numeric expression must be an object")
        return cls(
            definition_id=_string(item, "definition_id", "task graph numeric definition"),
            source_occurrence_id=_string(item, "source_occurrence_id", "task graph numeric definition"),
            expression=expression,
            source=_source_from_json(item.get("source"), "task graph numeric definition"),
        )


@dataclass(frozen=True)
class TaskGraphBranchIR:
    branch_id: str
    graph_node_id: str
    branch_kind: str
    ordinal: int
    label: str
    child_node_ids: tuple[str, ...]
    source: IRSource

    def __post_init__(self) -> None:
        if type(self) is not TaskGraphBranchIR:
            raise TypeError("task graph branch must not be subclassed")
        if any(not isinstance(value, str) or not value for value in (self.graph_node_id, self.branch_kind)):
            raise ValueError("task graph branch identity is incomplete")
        if type(self.ordinal) is not int or self.ordinal < 0 or not isinstance(self.label, str):
            raise ValueError("task graph branch ordinal or label is invalid")
        children = _strings(self.child_node_ids, "task graph branch children", ordered=True)
        expected = _id("task_graph_branch", self.graph_node_id, self.branch_kind, self.ordinal, self.label, *children)
        if self.branch_id != expected:
            raise ValueError("task graph branch identity is inconsistent")
        object.__setattr__(self, "child_node_ids", children)
        object.__setattr__(self, "source", _source(self.source, "task graph branch"))

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "branch_id": self.branch_id,
            "graph_node_id": self.graph_node_id,
            "branch_kind": self.branch_kind,
            "ordinal": self.ordinal,
            "label": self.label,
            "child_node_ids": list(self.child_node_ids),
            "source": self.source.to_json(),
        }

    @classmethod
    def from_json(cls, value: object) -> "TaskGraphBranchIR":
        item = _exact(value, {"branch_id", "graph_node_id", "branch_kind", "ordinal", "label", "child_node_ids", "source"}, "task graph branch")
        ordinal = item.get("ordinal")
        if type(ordinal) is not int:
            raise TypeError("task graph branch ordinal must be an integer")
        return cls(
            branch_id=_string(item, "branch_id", "task graph branch"),
            graph_node_id=_string(item, "graph_node_id", "task graph branch"),
            branch_kind=_string(item, "branch_kind", "task graph branch"),
            ordinal=ordinal,
            label=_string(item, "label", "task graph branch"),
            child_node_ids=_strings(item.get("child_node_ids"), "task graph branch children", ordered=True),
            source=_source_from_json(item.get("source"), "task graph branch"),
        )


@dataclass(frozen=True)
class TaskGraphNodeIR:
    graph_node_id: str
    graph_id: str
    source_occurrence_id: str
    source_contract_node_id: str
    formal_task_id: str
    opcode: str
    source_family: str
    node_kind: NodeKind
    branches: tuple[TaskGraphBranchIR, ...]
    references: tuple[TaskGraphDefinitionReferenceIR, ...]
    termination_kind: Literal[
        "not_applicable",
        "count_expression",
        "condition_with_source_cap",
        "condition_progress_required",
        "finite_target_collection",
    ]
    termination_status: Literal[
        "not_applicable", "source_backed", "runtime_proof_required"
    ]
    termination_numeric_definition_id: str
    materialization_status: Literal["materialized", "deferred"]
    owner_domains: tuple[str, ...]
    source: IRSource
    status_reason: str = ""

    def __post_init__(self) -> None:
        if type(self) is not TaskGraphNodeIR:
            raise TypeError("task graph node must not be subclassed")
        if self.node_kind not in {"leaf", "branch", "loop", "target_scope", "template_call", "ability_call", "template_parameter", "sequence", "deferred"}:
            raise ValueError("task graph node kind is invalid")
        if self.materialization_status not in {"materialized", "deferred"}:
            raise ValueError("task graph node materialization status is invalid")
        termination_statuses = {
            "not_applicable": "not_applicable",
            "count_expression": "source_backed",
            "condition_with_source_cap": "source_backed",
            "condition_progress_required": "runtime_proof_required",
            "finite_target_collection": "source_backed",
        }
        if termination_statuses.get(self.termination_kind) != self.termination_status:
            raise ValueError("task graph termination contract is invalid")
        if any(not isinstance(value, str) or not value for value in (
            self.graph_id,
            self.source_occurrence_id,
            self.formal_task_id,
            self.opcode,
            self.source_family,
        )):
            raise ValueError("task graph node identity is incomplete")
        domains = _strings(self.owner_domains, "task graph node owners")
        for domain in domains:
            _domain(domain, "task graph node owner")
        if not isinstance(self.source_contract_node_id, str):
            raise TypeError("task graph source contract identity must be a string")
        source = _source(self.source, "task graph node")
        evidence_families = tuple(
            value
            for value in (
                source.evidence.get("source_opcode"),
                source.evidence.get("raw_opcode"),
            )
            if isinstance(value, str) and value
        )
        if (
            len(set(evidence_families)) != 1
            or evidence_families[0] != self.source_family
            or self.source_occurrence_id
            != task_graph_source_occurrence_id(source, self.source_family)
        ):
            raise ValueError("task graph node source occurrence is inconsistent")
        expected = task_graph_node_id(self.graph_id, self.formal_task_id, self.source_occurrence_id)
        if self.graph_node_id != expected:
            raise ValueError("task graph node identity is inconsistent")
        branches = tuple(self.branches)
        references = tuple(self.references)
        if any(type(item) is not TaskGraphBranchIR or item.graph_node_id != self.graph_node_id for item in branches):
            raise TypeError("task graph node branches are invalid")
        if tuple(item.ordinal for item in branches) != tuple(range(len(branches))):
            raise ValueError("task graph branch order is not canonical")
        if any(type(item) is not TaskGraphDefinitionReferenceIR or item.graph_node_id != self.graph_node_id for item in references):
            raise TypeError("task graph node references are invalid")
        if len({item.reference_id for item in references}) != len(references):
            raise ValueError("task graph node contains duplicate references")
        numeric_references = tuple(
            item.definition_id
            for item in references
            if item.reference_kind == "numeric"
        )
        requires_numeric = self.termination_kind in {
            "count_expression", "condition_with_source_cap"
        }
        if (
            (self.node_kind == "loop")
            != (self.termination_kind != "not_applicable")
            or requires_numeric != bool(self.termination_numeric_definition_id)
            or numeric_references
            != (
                (self.termination_numeric_definition_id,)
                if requires_numeric
                else ()
            )
        ):
            raise ValueError("task graph loop termination is inconsistent")
        if self.materialization_status == "materialized":
            if (
                self.status_reason
                or self.node_kind == "deferred"
                or domains != ("task_graph_execution",)
            ):
                raise ValueError("materialized task graph node status is inconsistent")
        elif (
            not self.status_reason
            or self.node_kind != "deferred"
            or not domains
            or "task_graph_execution" in domains
        ):
            raise ValueError("deferred task graph node status is inconsistent")
        object.__setattr__(self, "branches", branches)
        object.__setattr__(self, "references", tuple(sorted(references, key=lambda item: item.reference_id)))
        object.__setattr__(self, "owner_domains", domains)
        object.__setattr__(self, "source", source)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "graph_node_id": self.graph_node_id,
            "graph_id": self.graph_id,
            "source_occurrence_id": self.source_occurrence_id,
            "source_contract_node_id": self.source_contract_node_id,
            "formal_task_id": self.formal_task_id,
            "opcode": self.opcode,
            "source_family": self.source_family,
            "node_kind": self.node_kind,
            "branches": [item.to_json() for item in self.branches],
            "references": [item.to_json() for item in self.references],
            "termination_kind": self.termination_kind,
            "termination_status": self.termination_status,
            "termination_numeric_definition_id": self.termination_numeric_definition_id,
            "materialization_status": self.materialization_status,
            "owner_domains": list(self.owner_domains),
            "source": self.source.to_json(),
            "status_reason": self.status_reason,
        }

    @classmethod
    def from_json(cls, value: object) -> "TaskGraphNodeIR":
        item = _exact(value, {
            "graph_node_id", "graph_id", "source_occurrence_id", "source_contract_node_id",
            "formal_task_id", "opcode", "source_family", "node_kind", "branches", "references",
            "termination_kind", "termination_status", "termination_numeric_definition_id",
            "materialization_status", "owner_domains", "source", "status_reason",
        }, "task graph node")
        branches = item.get("branches")
        references = item.get("references")
        if not isinstance(branches, list) or not isinstance(references, list):
            raise TypeError("task graph node members must be arrays")
        return cls(
            graph_node_id=_string(item, "graph_node_id", "task graph node"),
            graph_id=_string(item, "graph_id", "task graph node"),
            source_occurrence_id=_string(item, "source_occurrence_id", "task graph node"),
            source_contract_node_id=_string(item, "source_contract_node_id", "task graph node"),
            formal_task_id=_string(item, "formal_task_id", "task graph node"),
            opcode=_string(item, "opcode", "task graph node"),
            source_family=_string(item, "source_family", "task graph node"),
            node_kind=cast(Any, _string(item, "node_kind", "task graph node")),
            branches=tuple(TaskGraphBranchIR.from_json(value) for value in branches),
            references=tuple(TaskGraphDefinitionReferenceIR.from_json(value) for value in references),
            termination_kind=cast(Any, _string(item, "termination_kind", "task graph node")),
            termination_status=cast(Any, _string(item, "termination_status", "task graph node")),
            termination_numeric_definition_id=_string(
                item, "termination_numeric_definition_id", "task graph node"
            ),
            materialization_status=cast(Any, _string(item, "materialization_status", "task graph node")),
            owner_domains=_strings(item.get("owner_domains"), "task graph node owners"),
            source=_source_from_json(item.get("source"), "task graph node"),
            status_reason=_string(item, "status_reason", "task graph node"),
        )


@dataclass(frozen=True)
class TaskGraphIR:
    graph_id: str
    entry_id: str
    entry_kind: EntryKind
    owner_id: str
    callback_kind: str
    root_node_ids: tuple[str, ...]
    nodes: tuple[TaskGraphNodeIR, ...]
    numeric_definitions: tuple[TaskGraphNumericDefinitionIR, ...]
    source_catalog_id: str
    source_fingerprint: str
    source: IRSource
    coverage_status: Literal["lowered", "lowered_with_obligation"]

    def __post_init__(self) -> None:
        if type(self) is not TaskGraphIR:
            raise TypeError("task graph must not be subclassed")
        if self.entry_kind not in {"ability_phase_callback", "status_callback"}:
            raise ValueError("task graph entry kind is invalid")
        if self.coverage_status not in {"lowered", "lowered_with_obligation"}:
            raise ValueError("task graph coverage status is invalid")
        if any(not isinstance(value, str) or not value for value in (self.entry_id, self.owner_id, self.callback_kind, self.source_catalog_id, self.source_fingerprint)):
            raise ValueError("task graph identity is incomplete")
        _sha256(self.source_fingerprint, "task graph source fingerprint")
        if self.graph_id != task_graph_id(self.source_catalog_id, self.entry_id, self.source_fingerprint):
            raise ValueError("task graph identity is inconsistent")
        if self.entry_id != task_graph_entry_id(self.entry_kind, self.owner_id, self.callback_kind):
            raise ValueError("task graph entry identity is inconsistent")
        roots = _strings(self.root_node_ids, "task graph roots", ordered=True)
        nodes = tuple(self.nodes)
        numeric = tuple(self.numeric_definitions)
        if any(type(item) is not TaskGraphNodeIR or item.graph_id != self.graph_id for item in nodes):
            raise TypeError("task graph nodes are invalid")
        node_ids = tuple(item.graph_node_id for item in nodes)
        if len(node_ids) != len(set(node_ids)) or not roots or set(roots) - set(node_ids):
            raise ValueError("task graph roots or node identities are invalid")
        if len({item.formal_task_id for item in nodes}) != len(nodes):
            raise ValueError("task graph formal task positions are not unique")
        if any(type(item) is not TaskGraphNumericDefinitionIR for item in numeric):
            raise TypeError("task graph numeric definitions are invalid")
        numeric_ids = tuple(item.definition_id for item in numeric)
        if len(numeric_ids) != len(set(numeric_ids)):
            raise ValueError("task graph numeric definitions contain duplicates")
        numeric_by_id = {item.definition_id: item for item in numeric}
        parent_counts = {node_id: 0 for node_id in node_ids}
        adjacency: dict[str, tuple[str, ...]] = {}
        for node in nodes:
            children = tuple(child for branch in node.branches for child in branch.child_node_ids)
            if len(children) != len(set(children)) or set(children) - set(node_ids) or node.graph_node_id in children:
                raise ValueError("task graph child topology is invalid")
            adjacency[node.graph_node_id] = children
            for child in children:
                parent_counts[child] += 1
            for reference in node.references:
                if reference.resolution_status == "blocked":
                    raise ValueError("materialized task graph cannot carry a blocked reference")
                if (
                    reference.reference_kind not in {"numeric", "template"}
                    and reference.source != node.source
                ):
                    raise ValueError("task graph definition reference source is inconsistent")
                if reference.reference_kind == "numeric" and reference.definition_id not in set(numeric_ids):
                    raise ValueError("task graph numeric reference is dangling")
                if reference.reference_kind == "numeric":
                    definition = numeric_by_id[reference.definition_id]
                    if (
                        definition.source_occurrence_id != node.source_occurrence_id
                        or definition.source.source_path != node.source.source_path
                        or definition.source.evidence.get("json_path")
                        != node.source.evidence.get("json_path")
                        or definition.source.evidence.get("content_sha256")
                        != node.source.evidence.get("content_sha256")
                    ):
                        raise ValueError("task graph numeric source is inconsistent")
        referenced_numeric_ids = {
            reference.definition_id
            for node in nodes
            for reference in node.references
            if reference.reference_kind == "numeric"
        }
        if referenced_numeric_ids != set(numeric_ids):
            raise ValueError("task graph numeric definition ledger is incomplete")
        root_set = set(roots)
        if any(count != (0 if node_id in root_set else 1) for node_id, count in parent_counts.items()):
            raise ValueError("task graph parent ownership is ambiguous")
        reached: set[str] = set()
        pending = list(roots)
        while pending:
            node_id = pending.pop()
            if node_id in reached:
                continue
            reached.add(node_id)
            pending.extend(adjacency[node_id])
        if reached != set(node_ids):
            raise ValueError("task graph contains a cycle or unreachable node")
        has_obligation = any(node.materialization_status == "deferred" for node in nodes) or any(
            ref.resolution_status != "resolved" for node in nodes for ref in node.references
        )
        if (self.coverage_status == "lowered_with_obligation") != has_obligation:
            raise ValueError("task graph coverage does not match its obligations")
        object.__setattr__(self, "root_node_ids", roots)
        object.__setattr__(self, "nodes", tuple(sorted(nodes, key=lambda item: item.graph_node_id)))
        object.__setattr__(self, "numeric_definitions", tuple(sorted(numeric, key=lambda item: item.definition_id)))
        object.__setattr__(self, "source", _source(self.source, "task graph"))

    @property
    def root_formal_task_ids(self) -> tuple[str, ...]:
        nodes_by_id = {item.graph_node_id: item for item in self.nodes}
        return tuple(
            nodes_by_id[node_id].formal_task_id for node_id in self.root_node_ids
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "graph_id": self.graph_id,
            "entry_id": self.entry_id,
            "entry_kind": self.entry_kind,
            "owner_id": self.owner_id,
            "callback_kind": self.callback_kind,
            "root_node_ids": list(self.root_node_ids),
            "nodes": [item.to_json() for item in self.nodes],
            "numeric_definitions": [item.to_json() for item in self.numeric_definitions],
            "source_catalog_id": self.source_catalog_id,
            "source_fingerprint": self.source_fingerprint,
            "source": self.source.to_json(),
            "coverage_status": self.coverage_status,
        }

    @classmethod
    def from_json(cls, value: object) -> "TaskGraphIR":
        item = _exact(value, {
            "graph_id", "entry_id", "entry_kind", "owner_id", "callback_kind",
            "root_node_ids", "nodes", "numeric_definitions", "source_catalog_id",
            "source_fingerprint", "source", "coverage_status",
        }, "task graph")
        nodes = item.get("nodes")
        numeric = item.get("numeric_definitions")
        if not isinstance(nodes, list) or not isinstance(numeric, list):
            raise TypeError("task graph members must be arrays")
        return cls(
            graph_id=_string(item, "graph_id", "task graph"),
            entry_id=_string(item, "entry_id", "task graph"),
            entry_kind=cast(Any, _string(item, "entry_kind", "task graph")),
            owner_id=_string(item, "owner_id", "task graph"),
            callback_kind=_string(item, "callback_kind", "task graph"),
            root_node_ids=_strings(item.get("root_node_ids"), "task graph roots", ordered=True),
            nodes=tuple(TaskGraphNodeIR.from_json(value) for value in nodes),
            numeric_definitions=tuple(TaskGraphNumericDefinitionIR.from_json(value) for value in numeric),
            source_catalog_id=_string(item, "source_catalog_id", "task graph"),
            source_fingerprint=_string(item, "source_fingerprint", "task graph"),
            source=_source_from_json(item.get("source"), "task graph"),
            coverage_status=cast(Any, _string(item, "coverage_status", "task graph")),
        )


@dataclass(frozen=True)
class TaskGraphEntryMaterializationIR:
    materialization_id: str
    entry_id: str
    entry_kind: EntryKind
    owner_id: str
    callback_kind: str
    graph_id: str
    formal_task_ids: tuple[str, ...]
    source_occurrence_ids: tuple[str, ...]
    status: Literal["materialized", "blocked"]
    source: IRSource
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        if type(self) is not TaskGraphEntryMaterializationIR:
            raise TypeError("task graph materialization must not be subclassed")
        if self.entry_id != task_graph_entry_id(self.entry_kind, self.owner_id, self.callback_kind):
            raise ValueError("task graph materialization entry is inconsistent")
        formal_tasks = _strings(
            self.formal_task_ids,
            "task graph materialization formal tasks",
            ordered=True,
        )
        occurrences = _ordered_string_sequence(
            self.source_occurrence_ids,
            "task graph materialization sources",
        )
        if len(formal_tasks) != len(occurrences):
            raise ValueError("task graph materialization positions are incomplete")
        expected = task_graph_materialization_id(
            self.entry_id,
            formal_tasks,
            occurrences,
        )
        if self.materialization_id != expected:
            raise ValueError("task graph materialization identity is inconsistent")
        if self.status == "materialized":
            if not self.graph_id or self.blocked_reason:
                raise ValueError("materialized task graph entry is incomplete")
        elif self.status == "blocked":
            if self.graph_id or not self.blocked_reason:
                raise ValueError("blocked task graph entry is inconsistent")
        else:
            raise ValueError("task graph materialization status is invalid")
        object.__setattr__(self, "formal_task_ids", formal_tasks)
        object.__setattr__(self, "source_occurrence_ids", occurrences)
        object.__setattr__(self, "source", _source(self.source, "task graph materialization"))

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "materialization_id": self.materialization_id,
            "entry_id": self.entry_id,
            "entry_kind": self.entry_kind,
            "owner_id": self.owner_id,
            "callback_kind": self.callback_kind,
            "graph_id": self.graph_id,
            "formal_task_ids": list(self.formal_task_ids),
            "source_occurrence_ids": list(self.source_occurrence_ids),
            "status": self.status,
            "source": self.source.to_json(),
            "blocked_reason": self.blocked_reason,
        }

    @classmethod
    def from_json(cls, value: object) -> "TaskGraphEntryMaterializationIR":
        item = _exact(value, {
            "materialization_id", "entry_id", "entry_kind", "owner_id", "callback_kind",
            "graph_id", "formal_task_ids", "source_occurrence_ids", "status", "source",
            "blocked_reason",
        }, "task graph materialization")
        return cls(
            materialization_id=_string(item, "materialization_id", "task graph materialization"),
            entry_id=_string(item, "entry_id", "task graph materialization"),
            entry_kind=cast(Any, _string(item, "entry_kind", "task graph materialization")),
            owner_id=_string(item, "owner_id", "task graph materialization"),
            callback_kind=_string(item, "callback_kind", "task graph materialization"),
            graph_id=_string(item, "graph_id", "task graph materialization"),
            formal_task_ids=_strings(
                item.get("formal_task_ids"),
                "task graph materialization formal tasks",
                ordered=True,
            ),
            source_occurrence_ids=_ordered_string_sequence(
                item.get("source_occurrence_ids"),
                "task graph materialization sources",
            ),
            status=cast(Any, _string(item, "status", "task graph materialization")),
            source=_source_from_json(item.get("source"), "task graph materialization"),
            blocked_reason=_string(item, "blocked_reason", "task graph materialization"),
        )


@dataclass(frozen=True)
class TaskGraphCatalogIR:
    scope_mode: ScopeMode
    source_catalog_id: str
    snapshot_id: str
    scope_catalog_id: str
    source_fingerprint: str
    dependency_fingerprint: str
    source_record_count: int
    source_record_fingerprint: str
    source_dispositions: tuple[TaskGraphSourceDispositionIR, ...]
    entry_materializations: tuple[TaskGraphEntryMaterializationIR, ...]
    graphs: tuple[TaskGraphIR, ...]
    selected_entry_ids: tuple[str, ...]
    source_ledger_complete: bool
    catalog_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self) is not TaskGraphCatalogIR:
            raise TypeError("task graph catalog must not be subclassed")
        if self.scope_mode not in {
            "complete_catalog",
            "formal_slice",
            "formal_catalog",
        }:
            raise ValueError("task graph catalog scope is invalid")
        if type(self.source_ledger_complete) is not bool or not self.source_ledger_complete:
            raise ValueError("task graph source ledger must be complete")
        if any(not isinstance(value, str) or not value for value in (
            self.source_catalog_id, self.snapshot_id, self.scope_catalog_id,
            self.source_fingerprint, self.dependency_fingerprint,
            self.source_record_fingerprint,
        )):
            raise ValueError("task graph catalog source identity is incomplete")
        if (
            type(self.source_record_count) is not int
            or self.source_record_count <= 0
        ):
            raise ValueError("task graph catalog source denominator is invalid")
        _sha256(self.source_fingerprint, "task graph catalog source fingerprint")
        _sha256(
            self.dependency_fingerprint,
            "task graph catalog dependency fingerprint",
        )
        _sha256(
            self.source_record_fingerprint,
            "task graph catalog source record fingerprint",
        )
        dispositions = tuple(self.source_dispositions)
        entries = tuple(self.entry_materializations)
        graphs = tuple(self.graphs)
        selected = _strings(self.selected_entry_ids, "task graph selected entries")
        if any(type(item) is not TaskGraphSourceDispositionIR for item in dispositions):
            raise TypeError("task graph catalog source dispositions are invalid")
        if any(type(item) is not TaskGraphEntryMaterializationIR for item in entries):
            raise TypeError("task graph catalog materializations are invalid")
        if any(type(item) is not TaskGraphIR for item in graphs):
            raise TypeError("task graph catalog graphs are invalid")
        source_record_ids = tuple(
            sorted(item.source_record_id for item in dispositions)
        )
        if (
            len(source_record_ids) != self.source_record_count
            or task_graph_source_record_fingerprint(source_record_ids)
            != self.source_record_fingerprint
        ):
            raise ValueError("task graph source denominator fingerprint is inconsistent")
        for identities, subject in (
            ((item.source_record_id for item in dispositions), "source record"),
            ((item.source_occurrence_id for item in dispositions), "source occurrence"),
            ((item.entry_id for item in entries), "entry"),
            ((item.graph_id for item in graphs), "graph"),
        ):
            values = tuple(identities)
            if len(values) != len(set(values)):
                raise ValueError(f"task graph catalog contains duplicate {subject} identities")
        graph_by_id = {item.graph_id: item for item in graphs}
        disposition_by_record = {item.source_record_id: item for item in dispositions}
        if any(
            item.graph_id not in graph_by_id
            or graph_by_id[item.graph_id].entry_id != item.entry_id
            for item in entries
            if item.status == "materialized"
        ) or any(item.graph_id for item in entries if item.status == "blocked"):
            raise ValueError("task graph materialization and graph catalog are inconsistent")
        if set(graph_by_id) != {
            item.graph_id for item in entries if item.status == "materialized"
        }:
            raise ValueError("task graph catalog contains an orphan formal graph")
        materialization_ids = {item.materialization_id for item in entries}
        if any(
            set(item.formal_materialization_ids) - materialization_ids
            for item in dispositions
        ):
            raise ValueError("task graph source ledger has a dangling materialization")
        expected_links: dict[str, set[str]] = {
            item.materialization_id: set() for item in entries
        }
        for entry in entries:
            if entry.status != "materialized":
                continue
            graph = graph_by_id[entry.graph_id]
            if (
                graph.entry_kind != entry.entry_kind
                or graph.owner_id != entry.owner_id
                or graph.callback_kind != entry.callback_kind
            ):
                raise ValueError("task graph materialization owner is inconsistent")
            if (
                tuple(sorted(entry.formal_task_ids))
                != tuple(sorted(node.formal_task_id for node in graph.nodes))
                or tuple(sorted(entry.source_occurrence_ids))
                != tuple(sorted(node.source_occurrence_id for node in graph.nodes))
            ):
                raise ValueError("task graph materialization source ledger is inconsistent")
            linked = {
                node.source_contract_node_id
                for node in graph.nodes
                if node.source_contract_node_id
            }
            linked.update(
                reference.source_contract_record_id
                for node in graph.nodes
                for reference in node.references
                if reference.source_contract_record_id
            )
            linked.update(
                reference.definition_id
                for node in graph.nodes
                for reference in node.references
                if reference.reference_kind == "template"
            )
            if any(record_id not in disposition_by_record for record_id in linked):
                raise ValueError("task graph formal slice references an unknown source record")
            for node in graph.nodes:
                if node.source_contract_node_id:
                    disposition = disposition_by_record[node.source_contract_node_id]
                    if (
                        disposition.source_kind != "control_node"
                        or disposition.source_occurrence_id != node.source_occurrence_id
                    ):
                        raise ValueError("task graph node is not closed to its source disposition")
                    expected_domains = disposition.owner_domains
                    if expected_domains:
                        if (
                            node.materialization_status != "deferred"
                            or node.owner_domains != expected_domains
                        ):
                            raise ValueError("task graph node obligation is inconsistent")
                    elif (
                        node.materialization_status != "materialized"
                        or node.owner_domains != ("task_graph_execution",)
                    ):
                        raise ValueError("task graph materialized node owner is inconsistent")
                for reference in node.references:
                    if not reference.source_contract_record_id:
                        continue
                    disposition = disposition_by_record[reference.source_contract_record_id]
                    if (
                        disposition.source_kind != "template_reference"
                        or disposition.source.source_path != reference.source.source_path
                        or disposition.source.evidence.get("json_path")
                        != reference.source.evidence.get("json_path")
                    ):
                        raise ValueError("task graph reference is not closed to its source disposition")
                    definition = disposition_by_record.get(reference.definition_id)
                    if definition is None or definition.source_kind != "template_definition":
                        raise ValueError("task graph template definition is outside the source ledger")
            expected_links[entry.materialization_id] = linked
        expected_materializations_by_record: dict[str, set[str]] = {}
        for materialization_id, records in expected_links.items():
            for record_id in records:
                expected_materializations_by_record.setdefault(record_id, set()).add(
                    materialization_id
                )
        if any(
            set(item.formal_materialization_ids)
            != expected_materializations_by_record.get(item.source_record_id, set())
            for item in dispositions
        ):
            raise ValueError("task graph source and formal materialization ledgers are not bidirectionally closed")
        if any(
            item.formal_materialization_ids
            and "task_graph_execution" in item.owner_domains
            for item in dispositions
        ):
            raise ValueError("materialized task graph source retains its task graph obligation")
        if set(selected) != {item.entry_id for item in entries}:
            raise ValueError("task graph selected entry ledger is inconsistent")
        if any(
            graph.source_catalog_id != self.source_catalog_id
            or graph.source_fingerprint != self.source_fingerprint
            for graph in graphs
        ):
            raise ValueError("task graph is outside its source catalog")
        if self.scope_mode == "complete_catalog":
            if selected or entries or graphs:
                raise ValueError("complete task graph catalog cannot carry formal slices")
        elif self.scope_mode == "formal_slice" and (
            len(selected) != 1 or len(entries) != 1
        ):
            raise ValueError("formal task graph slice must select exactly one entry")
        elif self.scope_mode == "formal_catalog" and (
            not selected or len(selected) != len(entries)
        ):
            raise ValueError("formal task graph catalog must select its complete entry set")
        canonical_dispositions = tuple(
            sorted(dispositions, key=lambda item: item.source_record_id)
        )
        canonical_entries = tuple(sorted(entries, key=lambda item: item.entry_id))
        canonical_graphs = tuple(sorted(graphs, key=lambda item: item.graph_id))
        identity = json.dumps({
            "scope_mode": self.scope_mode,
            "source_catalog_id": self.source_catalog_id,
            "snapshot_id": self.snapshot_id,
            "scope_catalog_id": self.scope_catalog_id,
            "source_fingerprint": self.source_fingerprint,
            "dependency_fingerprint": self.dependency_fingerprint,
            "source_record_count": self.source_record_count,
            "source_record_fingerprint": self.source_record_fingerprint,
            "source_dispositions": [item.to_json() for item in canonical_dispositions],
            "entry_materializations": [item.to_json() for item in canonical_entries],
            "graphs": [item.to_json() for item in canonical_graphs],
            "selected_entry_ids": list(selected),
            "source_ledger_complete": self.source_ledger_complete,
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")
        object.__setattr__(self, "source_dispositions", canonical_dispositions)
        object.__setattr__(self, "entry_materializations", canonical_entries)
        object.__setattr__(self, "graphs", canonical_graphs)
        object.__setattr__(self, "selected_entry_ids", selected)
        object.__setattr__(self, "catalog_id", f"task_graph_catalog:{sha256(identity).hexdigest()}")

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "catalog_id": self.catalog_id,
            "scope_mode": self.scope_mode,
            "source_catalog_id": self.source_catalog_id,
            "snapshot_id": self.snapshot_id,
            "scope_catalog_id": self.scope_catalog_id,
            "source_fingerprint": self.source_fingerprint,
            "dependency_fingerprint": self.dependency_fingerprint,
            "source_record_count": self.source_record_count,
            "source_record_fingerprint": self.source_record_fingerprint,
            "source_dispositions": [item.to_json() for item in self.source_dispositions],
            "entry_materializations": [item.to_json() for item in self.entry_materializations],
            "graphs": [item.to_json() for item in self.graphs],
            "selected_entry_ids": list(self.selected_entry_ids),
            "source_ledger_complete": self.source_ledger_complete,
        }

    @classmethod
    def from_json(cls, value: object) -> "TaskGraphCatalogIR":
        item = _exact(value, {
            "catalog_id", "scope_mode", "source_catalog_id", "snapshot_id", "scope_catalog_id",
            "source_fingerprint", "dependency_fingerprint", "source_record_count",
            "source_record_fingerprint", "source_dispositions", "entry_materializations",
            "graphs", "selected_entry_ids", "source_ledger_complete",
        }, "task graph catalog")
        dispositions = item.get("source_dispositions")
        entries = item.get("entry_materializations")
        graphs = item.get("graphs")
        complete = item.get("source_ledger_complete")
        count = item.get("source_record_count")
        if not isinstance(dispositions, list) or not isinstance(entries, list) or not isinstance(graphs, list) or type(complete) is not bool or type(count) is not int:
            raise TypeError("task graph catalog members are invalid")
        result = cls(
            scope_mode=cast(Any, _string(item, "scope_mode", "task graph catalog")),
            source_catalog_id=_string(item, "source_catalog_id", "task graph catalog"),
            snapshot_id=_string(item, "snapshot_id", "task graph catalog"),
            scope_catalog_id=_string(item, "scope_catalog_id", "task graph catalog"),
            source_fingerprint=_string(item, "source_fingerprint", "task graph catalog"),
            dependency_fingerprint=_string(item, "dependency_fingerprint", "task graph catalog"),
            source_record_count=count,
            source_record_fingerprint=_string(
                item,
                "source_record_fingerprint",
                "task graph catalog",
            ),
            source_dispositions=tuple(TaskGraphSourceDispositionIR.from_json(value) for value in dispositions),
            entry_materializations=tuple(TaskGraphEntryMaterializationIR.from_json(value) for value in entries),
            graphs=tuple(TaskGraphIR.from_json(value) for value in graphs),
            selected_entry_ids=_strings(item.get("selected_entry_ids"), "task graph selected entries"),
            source_ledger_complete=complete,
        )
        if _string(item, "catalog_id", "task graph catalog") != result.catalog_id:
            raise ValueError("task graph catalog fingerprint is inconsistent")
        return result


@dataclass(frozen=True)
class TaskGraphQueryResult:
    status: Literal["resolved", "blocked"]
    definition_kind: Literal["graph", "entry", "node"]
    candidate_ids: tuple[str, ...]
    value: TaskGraphIR | TaskGraphEntryMaterializationIR | TaskGraphNodeIR | None
    blocked_reason: str

    def __post_init__(self) -> None:
        if type(self) is not TaskGraphQueryResult:
            raise TypeError("task graph query result must not be subclassed")
        if self.definition_kind not in {"graph", "entry", "node"}:
            raise ValueError("task graph query definition kind is invalid")
        candidates = _strings(self.candidate_ids, "task graph query candidates")
        if self.status == "resolved":
            if self.blocked_reason or self.value is None or len(candidates) != 1:
                raise ValueError("resolved task graph query is inconsistent")
            expected_type = {
                "graph": TaskGraphIR,
                "entry": TaskGraphEntryMaterializationIR,
                "node": TaskGraphNodeIR,
            }.get(self.definition_kind)
            if expected_type is None or type(self.value) is not expected_type:
                raise TypeError("resolved task graph query returned the wrong definition type")
            if candidates != (_query_identity(self.definition_kind, self.value),):
                raise ValueError("resolved task graph query candidate identity is inconsistent")
        elif self.status == "blocked":
            if not self.blocked_reason or self.value is not None:
                raise ValueError("blocked task graph query is inconsistent")
        else:
            raise ValueError("task graph query status is invalid")
        object.__setattr__(self, "candidate_ids", candidates)


@dataclass(frozen=True)
class TaskGraphQuery:
    catalog: TaskGraphCatalogIR
    _graphs: Mapping[str, tuple[TaskGraphIR, ...]] = field(init=False, repr=False)
    _entries: Mapping[str, tuple[TaskGraphEntryMaterializationIR, ...]] = field(
        init=False, repr=False
    )
    _nodes: Mapping[str, tuple[TaskGraphNodeIR, ...]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if type(self) is not TaskGraphQuery:
            raise TypeError("task graph query must not be subclassed")
        catalog = self.catalog
        if type(catalog) is not TaskGraphCatalogIR:
            raise TypeError("task graph query requires the exact catalog type")
        object.__setattr__(self, "_graphs", MappingProxyType(
            _multimap(catalog.graphs, lambda item: item.graph_id)
        ))
        object.__setattr__(self, "_entries", MappingProxyType(
            _multimap(catalog.entry_materializations, lambda item: item.entry_id)
        ))
        object.__setattr__(self, "_nodes", MappingProxyType(_multimap(
            (node for graph in catalog.graphs for node in graph.nodes),
            lambda item: item.graph_node_id,
        )))

    @staticmethod
    def _result(kind: Literal["graph", "entry", "node"], values: tuple[Any, ...]) -> TaskGraphQueryResult:
        identities = tuple(sorted(_query_identity(kind, value) for value in values))
        if len(values) == 1:
            if kind == "entry" and values[0].status == "blocked":
                return TaskGraphQueryResult(
                    "blocked",
                    kind,
                    identities,
                    None,
                    values[0].blocked_reason,
                )
            return TaskGraphQueryResult("resolved", kind, identities, values[0], "")
        return TaskGraphQueryResult(
            "blocked",
            kind,
            identities,
            None,
            f"task_graph_{'missing' if not values else 'ambiguous'}:{kind}",
        )

    def query_graph(self, graph_id: str) -> TaskGraphQueryResult:
        if type(graph_id) is not str or not graph_id:
            return TaskGraphQueryResult(
                "blocked", "graph", (), None, "task_graph_invalid_query:graph"
            )
        return self._result("graph", self._graphs.get(graph_id, ()))

    def query_entry(self, entry_kind: EntryKind, owner_id: str, callback_kind: str) -> TaskGraphQueryResult:
        if (
            entry_kind not in {"ability_phase_callback", "status_callback"}
            or type(owner_id) is not str
            or not owner_id
            or type(callback_kind) is not str
            or not callback_kind
        ):
            return TaskGraphQueryResult(
                "blocked", "entry", (), None, "task_graph_invalid_query:entry"
            )
        return self._result("entry", self._entries.get(task_graph_entry_id(entry_kind, owner_id, callback_kind), ()))

    def query_node(self, graph_node_id: str) -> TaskGraphQueryResult:
        if type(graph_node_id) is not str or not graph_node_id:
            return TaskGraphQueryResult(
                "blocked", "node", (), None, "task_graph_invalid_query:node"
            )
        return self._result("node", self._nodes.get(graph_node_id, ()))


def _multimap(values: Any, identity: Any) -> dict[str, tuple[Any, ...]]:
    result: dict[str, list[Any]] = {}
    for value in values:
        result.setdefault(identity(value), []).append(value)
    return {key: tuple(items) for key, items in result.items()}


def _query_identity(kind: str, value: object) -> str:
    return cast(str, getattr(value, {"graph": "graph_id", "entry": "entry_id", "node": "graph_node_id"}[kind]))


def task_graph_reference_id(node_id: str, kind: ReferenceKind, definition_id: str) -> str:
    return _id("task_graph_reference", node_id, kind, definition_id)


def task_graph_branch_id(node_id: str, kind: str, ordinal: int, label: str, children: tuple[str, ...]) -> str:
    return _id("task_graph_branch", node_id, kind, ordinal, label, *children)


def task_graph_numeric_id(occurrence_id: str, expression: Mapping[str, Any]) -> str:
    return _id(
        "task_graph_numeric",
        occurrence_id,
        json.dumps(thaw_json(freeze_json(dict(expression))), sort_keys=True, separators=(",", ":")),
    )


def task_graph_materialization_id(
    entry_id: str,
    formal_task_ids: tuple[str, ...],
    occurrences: tuple[str, ...],
) -> str:
    if len(formal_task_ids) != len(occurrences):
        raise ValueError("task graph materialization identity positions are incomplete")
    positions = tuple(
        f"{task_id}:{occurrence_id}"
        for task_id, occurrence_id in zip(formal_task_ids, occurrences, strict=True)
    )
    return _id("task_graph_materialization", entry_id, *positions)
