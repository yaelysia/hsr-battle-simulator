from __future__ import annotations

from typing import Any, Optional

from ._adapter import SimulatorRuntimeAdapter


class TargetRuntime(SimulatorRuntimeAdapter):
    """Target selection adapter for the combat core migration."""

    def normalize_targets(self, targets: Any) -> list[str] | None:
        return self.sim.normalize_targets(targets)

    def select_targets(self, action: dict[str, Any], context: dict[str, Any] | None) -> list[str]:
        return self.sim.select_targets(action, context)

    def resolve_packet_targets(self, packet: dict[str, Any], action: dict[str, Any], action_ctx: dict[str, Any], default_targets: list[str]) -> list[str]:
        return self.sim.resolve_packet_targets(packet, action, action_ctx, default_targets)
