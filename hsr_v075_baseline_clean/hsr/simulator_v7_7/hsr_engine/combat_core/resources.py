from __future__ import annotations

from typing import Any, Optional

from ._adapter import SimulatorRuntimeAdapter


class ResourceRuntime(SimulatorRuntimeAdapter):
    """Resource mutation adapter for the combat core migration."""

    def apply_hp_loss(self, *args: Any, **kwargs: Any) -> Any:
        return self.sim.apply_hp_loss(*args, **kwargs)

    def apply_energy_source(self, *args: Any, **kwargs: Any) -> Any:
        return self.sim.apply_energy_source(*args, **kwargs)

    def commit_skill_points(self, *args: Any, **kwargs: Any) -> Any:
        return self.sim.commit_skill_points(*args, **kwargs)
