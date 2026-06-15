from __future__ import annotations

from typing import Any, Optional

from ._adapter import SimulatorRuntimeAdapter


class StatusRuntime(SimulatorRuntimeAdapter):
    """Status lifecycle adapter for the combat core migration."""

    def commit_status_entry(self, *args: Any, **kwargs: Any) -> Any:
        return self.sim.commit_status_entry(*args, **kwargs)

    def commit_status_remove(self, *args: Any, **kwargs: Any) -> Any:
        return self.sim.commit_status_remove(*args, **kwargs)

    def tick_status_durations(self, *args: Any, **kwargs: Any) -> Any:
        return self.sim.tick_status_durations(*args, **kwargs)
