"""Native lethal-cause persistence; rescue HP is an explicit component input.

This checks the shared lifecycle producer, not queued Bailu/Gepard execution.
"""
from dataclasses import replace

import pytest

from hsr.simulator_v8_clean_core.core.model import Mutation, PendingDefeatPlan
from hsr.simulator_v8_clean_core.core.reducer import MutationReducer
from hsr.simulator_v8_clean_core.core.state_integrity import CommittedStateIntegrityGate
from hsr.simulator_v8_clean_core.core.unit_state_codec import unit_state_from_payload, unit_state_to_payload
from hsr.simulator_v8_clean_core.systems.damage import DamageSystem
from hsr.simulator_v8_clean_core.systems.unit_lifecycle import UnitLifecycleSystem
from hsr.simulator_v8_clean_core.tests.test_kill_energy_shared_producer import _primitive_case


def test_native_pending_cause_survives_restore_and_closes_atomically():
    before, packet = _primitive_case()
    before = replace(before, units={uid: unit_state_from_payload(unit_state_to_payload(unit))
                                    for uid, unit in before.units.items()})
    packet = replace(packet, source_trace={"kind": "validation_fixture", "scope": "pending_lifecycle"})
    native = DamageSystem().apply_packet(before, packet)
    assert native.ok, native.errors
    hp = next(m for m in native.mutations if m.path == ("units", "target", "hp"))
    plan = PendingDefeatPlan("target", before.event_index, hp, "owner",
                             packet.source_frame.to_json(), packet.source_trace)
    from hsr.simulator_v8_clean_core.immutable_json import freeze_json
    frozen_cause = freeze_json(plan.to_json())
    decoded = PendingDefeatPlan.from_json(frozen_cause)
    assert decoded == plan
    assert PendingDefeatPlan.from_json(frozen_cause) is decoded
    lifecycle, reducer, integrity = UnitLifecycleSystem(), MutationReducer(), CommittedStateIntegrityGate()
    entering = (hp, *lifecycle.begin_limbo_mutations(before, plan))
    pending = reducer.apply_all(before, entering)
    assert integrity.check_touched(before, pending, entering).ok
    assert integrity.check_full(pending).ok
    assert pending.units["target"].lifecycle_status == "limbo"
    assert pending.units["owner"].energy == before.units["owner"].energy
    assert "defeat_record" not in pending.units["target"].flags
    assert not lifecycle.can_act(pending, "target")[0]
    assert not lifecycle.can_target(pending, "target", allow_defeated=True)[0]
    restored = unit_state_from_payload(unit_state_to_payload(pending.units["target"]))
    pending = replace(pending, units={**pending.units, "target": restored})
    assert lifecycle.pending_defeat(pending, "target") == plan
    assert reducer.replay_snapshot(before, entering, pending.snapshot().to_json()).ok

    finalizing = lifecycle.finalize_pending_defeat_mutations(pending, plan)
    defeated = reducer.apply_all(pending, finalizing)
    assert integrity.check_touched(pending, defeated, finalizing).ok
    assert defeated.units["target"].lifecycle_status == "defeated"
    record = defeated.units["target"].flags["defeat_record"]
    assert record["hp_mutation_id"] == hp.stable_id() and record["kill_credit_owner_id"] == "owner"
    assert "pending_defeat" not in defeated.units["target"].flags
    assert reducer.replay_snapshot(before, (*entering, *finalizing), defeated.snapshot().to_json()).ok

    healed = Mutation("set", ("units", "target", "hp"), pending.units["target"].hp, 10.,
                      "component rescue HP", "validation_fixture:rescue_hp",
                      metadata={"source_trace": {"kind": "validation_fixture"}})
    rescuing = lifecycle.rescue_from_limbo_mutations(pending, plan, healed)
    rescued = reducer.apply_all(pending, rescuing)
    assert integrity.check_touched(pending, rescued, rescuing).ok
    assert rescued.units["target"].lifecycle_status == "active" and rescued.units["target"].hp == 10.
    assert "pending_defeat" not in rescued.units["target"].flags and "defeat_record" not in rescued.units["target"].flags
    assert reducer.replay_snapshot(before, (*entering, *rescuing), rescued.snapshot().to_json()).ok

    failed = reducer.apply_all_result(pending, (*rescuing[:-1], replace(rescuing[-1], before={"wrong": True})))
    assert not failed.ok and failed.after_state == pending and failed.applied_count == 0
    incomplete = reducer.apply_all(pending, finalizing[:-1])
    assert not integrity.check_touched(pending, incomplete, finalizing[:-1]).ok
    with pytest.raises(ValueError, match="identity_mismatch"):
        lifecycle.finalize_pending_defeat_mutations(pending, replace(plan, event_index=plan.event_index + 1))
    with pytest.raises(ValueError):
        lifecycle.rescue_from_limbo_mutations(defeated, plan, healed)
    changed = plan.to_json()
    changed["hp_mutation"]["before"] = 999.
    with pytest.raises(ValueError, match="hp_identity_mismatch"):
        PendingDefeatPlan.from_json(changed)
