"""Component contract: permanent-status reapplication uses the committed source identity."""
from hsr.simulator_v8_clean_core.systems.status import (
    _same_definition_permanent_reapplication,
)

_MISSING = {"kind": "missing"}
_SOURCE_ID = "ability_task:ability_phase:avatar_skill:x:OnStart:OnStart[0]:AddModifier"


def _standard(**overrides):
    standard = {
        "lifetime": _MISSING,
        "layer_add_when_stack": _MISSING,
        "max_layer": _MISSING,
        "chance": _MISSING,
    }
    standard.update(overrides)
    return standard


def _detail(**overrides):
    detail = {
        "caster_id": "caster",
        "source_id": _SOURCE_ID,
        # The audit trace must never decide this behavior.
        "source_trace": {"effect_source": {"source_path": "forged"}, "effect_id": "x"},
    }
    detail.update(overrides)
    return detail


def _same(detail, *, source_id=_SOURCE_ID, refresh=None, standard=None):
    return _same_definition_permanent_reapplication(
        detail,
        caster_id="caster",
        standard=standard or _standard(),
        refresh_admission=refresh or {"admission_status": "not_applicable"},
        source_id=source_id,
    )


def test_same_committed_source_replaces_while_the_audit_trace_is_ignored():
    assert _same(_detail()) is True
    # A different committed task identity cannot be replaced by a matching trace.
    assert _same(_detail(source_trace={"effect_source": {"source_path": "forged"}}),
                 source_id="ability_task:other") is False
    # A matching committed task identity still replaces despite a changed trace.
    assert _same(_detail(source_trace={"effect_source": {"source_path": "changed"}})) is True


def test_different_caster_missing_lifetime_or_refresh_admission_never_replaces():
    assert _same(_detail(caster_id="other")) is False
    assert _same(_detail(), standard=_standard(lifetime={"kind": "fixed", "value": 2})) is False
    assert _same(_detail(), refresh={"admission_status": "refresh"}) is False
    assert _same(_detail(), source_id="") is False
    assert _same(None) is False
