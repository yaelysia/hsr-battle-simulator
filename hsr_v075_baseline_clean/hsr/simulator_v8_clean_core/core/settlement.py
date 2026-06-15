from __future__ import annotations

from dataclasses import dataclass, field

from .model import ActionSettlement, JSONValue, Mutation


@dataclass(frozen=True)
class SettlementRecord:
    record_type: str
    source: str
    mutation_id: str | None = None
    process_only: bool = False
    payload: dict[str, JSONValue] = field(default_factory=dict)
    trace: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "record_type": self.record_type,
            "source": self.source,
            "mutation_id": self.mutation_id,
            "process_only": self.process_only,
            "payload": self.payload,
            "trace": self.trace,
        }


@dataclass(frozen=True)
class SettlementTraceabilityResult:
    ok: bool
    checked_records: int
    process_only_records: int
    mutation_linked_records: int
    errors: tuple[str, ...] = ()

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "ok": self.ok,
            "checked_records": self.checked_records,
            "process_only_records": self.process_only_records,
            "mutation_linked_records": self.mutation_linked_records,
            "errors": list(self.errors),
        }


class SettlementTraceabilityValidator:
    def validate(
        self,
        settlement: ActionSettlement | None,
        mutations: tuple[Mutation, ...],
    ) -> SettlementTraceabilityResult:
        if settlement is None:
            return SettlementTraceabilityResult(False, 0, 0, 0, ("missing settlement",))

        mutation_ids = {mutation.stable_id() for mutation in mutations}
        errors: list[str] = []
        process_only = 0
        linked = 0
        for index, record in enumerate(settlement.records):
            if bool(record.get("process_only", False)):
                process_only += 1
                continue
            mutation_id = record.get("mutation_id")
            if isinstance(mutation_id, str) and mutation_id in mutation_ids:
                linked += 1
                continue
            errors.append(f"record[{index}] is not linked to mutation and is not process-only")
        return SettlementTraceabilityResult(
            ok=not errors,
            checked_records=len(settlement.records),
            process_only_records=process_only,
            mutation_linked_records=linked,
            errors=tuple(errors),
        )

