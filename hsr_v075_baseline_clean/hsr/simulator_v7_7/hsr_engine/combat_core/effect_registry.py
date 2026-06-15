from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any, Callable


EffectHandler = Callable[[dict[str, Any], dict[str, Any]], Any]


class UnsupportedEffectError(RuntimeError):
    """Raised when an effect has no clean handler and no fallback."""


@dataclass
class EffectCoverageRecord:
    effect_type: str = ""
    canonical_type: str = ""
    status: str = "unsupported"
    handler: str = ""
    reason: str = ""
    source_path: str = ""
    raw_type: str = ""
    raw_id: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EffectRegistry:
    """Canonical effect dispatcher for the clean combat core."""

    DEFAULT_ALIASES: dict[str, str] = {
        "add_buff": "add_status",
        "apply_status": "add_status",
        "add_prebattle_status": "add_status",
        "add_buff_on_battle_start": "add_status",
        "add_or_refresh_stack": "add_status",
        "remove_buff": "remove_status",
        "dispel_buff": "remove_status",
        "remove_status_effect": "remove_status",
        "gain_energy": "modify_energy",
        "grant_energy": "modify_energy",
        "gain_skill_point": "modify_skill_points",
        "consume_skill_point": "modify_skill_points",
        "delay_self_action": "delay_action",
        "delay_next_action": "delay_action",
        "launch_follow_up_attack": "launch_action",
        "follow_up_attack": "launch_action",
        "detonate_dot_damage": "trigger_dot_damage_now",
        "detonate_dots": "trigger_dot_damage_now",
        "trigger_dots_now": "trigger_dot_damage_now",
    }

    def __init__(
        self,
        *,
        fallback: EffectHandler | None = None,
        aliases: dict[str, str] | None = None,
    ) -> None:
        self.handlers: dict[str, EffectHandler] = {}
        self.aliases = dict(self.DEFAULT_ALIASES)
        if aliases:
            self.aliases.update({str(k): str(v) for k, v in aliases.items()})
        self.fallback = fallback
        self.coverage_records: list[EffectCoverageRecord] = []

    def register(self, effect_type: str, handler: EffectHandler) -> None:
        self.handlers[str(effect_type or "")] = handler

    def canonical_type(self, effect_type: str) -> str:
        effect_type = str(effect_type or "")
        return self.aliases.get(effect_type, effect_type)

    def normalize_effect(self, effect: dict[str, Any]) -> dict[str, Any]:
        out = deepcopy(effect or {})
        raw_type = str(out.get("type") or "")
        out.setdefault("_raw_type", raw_type)
        out.setdefault("_canonical_type", self.canonical_type(raw_type))
        return out

    def dispatch(self, effect: dict[str, Any], ctx: dict[str, Any]) -> Any:
        normalized = self.normalize_effect(effect)
        raw_type = str(normalized.get("_raw_type") or normalized.get("type") or "")
        canonical = str(normalized.get("_canonical_type") or raw_type)
        handler = self.handlers.get(canonical)
        if handler is not None:
            self._record(normalized, canonical, "executable", handler=getattr(handler, "__name__", canonical))
            normalized["type"] = canonical
            return handler(normalized, ctx)
        if self.fallback is not None:
            self._record(normalized, canonical, "legacy_fallback", handler="legacy_effect_runtime")
            return self.fallback(effect, ctx)
        self._record(normalized, canonical, "unsupported", reason="no_effect_handler")
        raise UnsupportedEffectError(f"Unsupported effect type: {raw_type or '<missing>'}")

    def _record(
        self,
        effect: dict[str, Any],
        canonical: str,
        status: str,
        *,
        handler: str = "",
        reason: str = "",
    ) -> None:
        raw_type = str(effect.get("_raw_type") or effect.get("type") or "")
        self.coverage_records.append(
            EffectCoverageRecord(
                effect_type=raw_type,
                canonical_type=canonical,
                status=status,
                handler=handler,
                reason=reason,
                source_path=str(effect.get("source_path") or effect.get("raw_path") or ""),
                raw_type=str(effect.get("raw_type") or effect.get("source_node_type") or ""),
                raw_id=str(effect.get("raw_id") or effect.get("id") or ""),
                evidence={
                    "has_condition": "condition" in effect,
                    "keys": sorted(str(k) for k in effect.keys() if not str(k).startswith("_")),
                },
            )
        )

    def coverage_matrix(self) -> dict[str, Any]:
        rows = [record.to_dict() for record in self.coverage_records]
        summary: dict[str, int] = {}
        by_effect_type: dict[str, dict[str, Any]] = {}
        for row in rows:
            status = str(row.get("status") or "unknown")
            summary[status] = summary.get(status, 0) + 1
            key = str(row.get("effect_type") or "")
            slot = by_effect_type.setdefault(
                key,
                {
                    "effect_type": key,
                    "canonical_type": row.get("canonical_type") or "",
                    "count": 0,
                    "statuses": {},
                    "handlers": sorted({row.get("handler") or ""}),
                },
            )
            slot["count"] += 1
            slot["statuses"][status] = slot["statuses"].get(status, 0) + 1
            handlers = {h for h in slot.get("handlers", []) if h}
            if row.get("handler"):
                handlers.add(str(row.get("handler")))
            slot["handlers"] = sorted(handlers)
        return {
            "encoding": "hsr.clean_core.effect_coverage.v1",
            "summary": summary,
            "effect_type_count": len(by_effect_type),
            "records": rows,
            "by_effect_type": sorted(by_effect_type.values(), key=lambda item: item["effect_type"]),
        }
