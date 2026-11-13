"""Repeated hits on one target must produce distinct, replayable decisions."""
import pytest

from hsr.simulator_v8_clean_core.core.model import BattleState
from hsr.simulator_v8_clean_core.systems.status import _status_rng_event, _status_choice_rng_event


@pytest.mark.parametrize("random_dispel", [False, True])
def test_status_rng_uses_invocation_identity_not_only_action_and_target(random_dispel):
    state = BattleState(event_index=4)
    trace = {"caster_id": "caster", "target_id": "target", "status_id": "slow", "effect_id": "effect:slow"}

    def resolve(invocation):
        common = dict(state=state, source="status_system", purpose="check", trace=trace,
                      event_payload={"operation_event_id": invocation})
        if random_dispel:
            return _status_choice_rng_event(**common, rng_type="status_dispel", candidates=("a", "b"))
        return _status_rng_event(**common, rng_type="status_apply", probability=0.5,
                                 success_outcome_id="applied", fail_outcome_id="not_applied")

    first, second, replay = resolve("hit:1"), resolve("hit:2"), resolve("hit:1")
    assert first.event_id != second.event_id
    assert first.result["choice_key"] != second.result["choice_key"]
    assert first.to_json() == replay.to_json()
