from __future__ import annotations

import sys
from typing import Any


def bind_simulator_module_globals(target_globals: dict[str, Any], simulator: Any) -> None:
    """Expose the legacy simulator module globals to migrated runtime methods.

    This is a temporary adapter while the runtime code is moved out of the
    monolithic simulator file. It keeps moved method bodies behavior-equivalent
    before their helper dependencies are converted into explicit contracts.
    """

    module = sys.modules.get(type(simulator).__module__)
    if module is None:
        return
    for name, value in vars(module).items():
        if name.startswith("__"):
            continue
        target_globals.setdefault(name, value)


class SimulatorRuntimeAdapter:
    """Base class for combat-core runtimes that still use simulator adapters."""

    def __init__(self, simulator: Any) -> None:
        self.sim = simulator
        bind_simulator_module_globals(sys.modules[type(self).__module__].__dict__, simulator)

    @property
    def state(self) -> Any:
        return self.sim.state

    @property
    def settings(self) -> Any:
        return self.sim.settings

    def __getattr__(self, name: str) -> Any:
        return getattr(self.sim, name)
