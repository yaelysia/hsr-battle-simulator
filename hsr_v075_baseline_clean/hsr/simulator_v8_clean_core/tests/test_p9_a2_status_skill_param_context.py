from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
from hsr.simulator_v8_clean_core.systems.dynamic_values import (
    character_skill_param_binding_source,
)
from hsr.simulator_v8_clean_core.systems.status_callbacks import (
    _callback_binding_sources,
    _condition_context,
    _effect_context,
    _evaluate_callback_numeric,
)


class _Source:
    def to_json(self) -> dict[str, str]:
        return {"source": "fixture"}


def _rules(slots: tuple[object, ...]) -> object:
    card = SimpleNamespace(
        card_id="card:caster", entity_ref="avatar:caster", source=_Source()
    )
    return SimpleNamespace(
        character_data_card=lambda card_id: card if card_id == card.card_id else None,
        character_data_card_for_entity=lambda template_id: (
            card if template_id == card.entity_ref else None
        ),
        character_dynamic_value_bindings_for_card=lambda _card_id: {
            "by_hash": {
                "passive": {
                    "read_info": {"Type": "SkillParam", "TriggerKey": "Passive", "Index": 0}
                }
            }
        },
        character_mechanism_slots_for_card=lambda _card_id: slots,
    )


def _slot(slot_id: str, *, level: int = 5, param_index: object = 0) -> object:
    return SimpleNamespace(
        mechanism_kind="skill_param_slot",
        coverage_status="executable",
        mechanism_slot_id=slot_id,
        source=_Source(),
        semantics={
            "skill_trigger_key": "Passive",
            "param_index": param_index,
            "level": level,
            "param_value": {"Value": 2.5},
        },
    )


def _state(*, configured: bool = True, configured_value: object = 5, card_id: object = "card:caster") -> object:
    flags = {"character_data_card_id": card_id}
    if configured:
        flags["skill_levels_by_trigger_key"] = {"Passive": configured_value}
    return SimpleNamespace(
        units={"caster": SimpleNamespace(flags=flags, template_id="avatar:caster")},
        global_flags={},
    )


def _battle_state() -> BattleState:
    return BattleState(
        units={
            "caster": UnitState(
                unit_id="caster",
                side="ally",
                template_id="avatar:caster",
                max_hp=100.0,
                hp=100.0,
                flags={
                    "character_data_card_id": "card:caster",
                    "skill_levels_by_trigger_key": {"Passive": 5},
                },
            ),
            "owner": UnitState(
                unit_id="owner",
                side="ally",
                template_id="avatar:owner",
                max_hp=100.0,
                hp=100.0,
            ),
        },
        global_flags={"turn_owner_id": "owner"},
    )


def _detail() -> dict[str, object]:
    return {
        "instance_id": "status:1",
        "status_id": "status:fixture",
        "modifier_name": "Modifier_Fixture",
        "owner_id": "owner",
        "caster_id": "caster",
        "source_id": "source:fixture",
        "source_trace": {},
    }


def test_skill_param_uses_caster_configured_trigger_level_not_outer_action_level() -> None:
    source = character_skill_param_binding_source(
        _rules((_slot("slot:passive"),)),
        _state(),
        "caster",
        action_level=1,
        current_action_trigger_key="Attack",
    )
    assert source is not None
    entry = next(iter(source["entries"].values()))
    assert entry["value"] == 2.5
    assert entry["source_trace"]["skill_level"] == 5
    assert entry["source_trace"]["skill_level_source"] == "unit.skill_levels_by_trigger_key"


def test_skill_param_missing_or_ambiguous_slot_stays_unbound() -> None:
    assert (
        character_skill_param_binding_source(
            _rules((_slot("slot:passive"),)), _state(configured=False), "caster"
        )
        is None
    )

    assert (
        character_skill_param_binding_source(
            _rules((_slot("slot:passive"),)),
            _state(configured_value=True),
            "caster",
            action_level=5,
            current_action_trigger_key="Passive",
        )
        is None
    )
    assert (
        character_skill_param_binding_source(
            _rules((_slot("slot:passive"),)),
            _state(card_id="card:wrong"),
            "caster",
        )
        is None
    )
    assert (
        character_skill_param_binding_source(
            _rules((_slot("slot:a"), _slot("slot:b"))), _state(), "caster"
        )
        is None
    )
    assert (
        character_skill_param_binding_source(
            _rules((_slot("slot:bool-index", param_index=False),)),
            _state(),
            "caster",
        )
        is None
    )


def test_callback_sources_use_caster_and_keep_current_status_shadowing() -> None:
    current = {
        "by_hash": {"shadowed": {"value": 1.0}},
        "by_name": {"shadowed": {"value": 1.0}},
    }
    character = {
        "by_hash": {"character": {"value": 2.0}},
        "by_name": {"character": {"value": 2.0}},
    }
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def fake_character_sources(_rules, _state, unit_ids, **kwargs):
        calls.append((unit_ids, kwargs))
        return (character,)

    with patch(
        "hsr.simulator_v8_clean_core.systems.status_callbacks.character_skill_param_binding_sources",
        fake_character_sources,
    ):
        sources = _callback_binding_sources(
            _rules((_slot("slot:passive"),)),
            _state(),
            {"caster_id": "caster", "owner_id": "owner"},
            current,
            "status:current",
            ("shadowed",),
            ("shadowed",),
            include_ambient=False,
        )

    assert sources == (current, character)
    assert calls == [
        (("caster",), {"excluded_hashes": ("shadowed",), "excluded_names": ("shadowed",)})
    ]


def test_declared_skill_param_shadows_ambient_even_when_slot_is_missing() -> None:
    captured: dict[str, object] = {}

    def fake_store(_store, **kwargs):
        captured.update(kwargs)
        return {"entries": {}, "by_hash": {}, "by_name": {}}

    with patch(
        "hsr.simulator_v8_clean_core.systems.status_callbacks.binding_source_from_store",
        fake_store,
    ):
        _callback_binding_sources(
            _rules(()),
            _battle_state(),
            _detail(),
            None,
            "status:1",
            (),
            (),
        )

    assert "passive" in captured["excluded_hashes"]


def test_effect_condition_and_numeric_consumers_share_caster_bindings() -> None:
    rules = _rules((_slot("slot:passive"),))
    state = _battle_state()
    detail = _detail()
    task = SimpleNamespace(task_id="task:fixture", source=_Source())

    condition = _condition_context(rules, state, detail, None)
    effect = _effect_context(rules, state, task, detail, None)
    captured: dict[str, object] = {}

    def fake_resolve(_expression, *, binding_sources, source_trace):
        captured["binding_sources"] = binding_sources
        captured["source_trace"] = source_trace
        return SimpleNamespace(ok=True, value=2.5)

    with patch(
        "hsr.simulator_v8_clean_core.systems.status_callbacks.engine_numeric_binding_source",
        return_value=(None, ""),
    ), patch(
        "hsr.simulator_v8_clean_core.systems.status_callbacks.resolve_runtime_numeric_expression",
        fake_resolve,
    ):
        numeric = _evaluate_callback_numeric(
            {"fixture": "numeric"}, state, detail, task, object(), rules
        )

    for sources in (
        condition.binding_sources,
        effect.binding_sources,
        captured["binding_sources"],
    ):
        character = next(
            source
            for source in sources
            if source.get("source_type") == "character_skill_param_slot"
        )
        assert character["unit_id"] == "caster"
        assert character["by_hash"]["passive"]
        assert next(iter(character["entries"].values()))["value"] == 2.5
    assert numeric.ok and numeric.value == 2.5
