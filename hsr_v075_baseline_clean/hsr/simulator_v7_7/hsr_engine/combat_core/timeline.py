from __future__ import annotations

from typing import Any, Optional

from ._adapter import SimulatorRuntimeAdapter


class TimelineRuntime(SimulatorRuntimeAdapter):
    """Timeline and turn adapter for the combat core migration."""

    def begin_turn(self, *args: Any, **kwargs: Any) -> Any:
        return self.sim.begin_turn(*args, **kwargs)

    def end_turn(self, *args: Any, **kwargs: Any) -> Any:
        return self.sim.end_turn(*args, **kwargs)

    def finish_regular_action(self, *args: Any, **kwargs: Any) -> Any:
        return self.sim.finish_regular_action(*args, **kwargs)
