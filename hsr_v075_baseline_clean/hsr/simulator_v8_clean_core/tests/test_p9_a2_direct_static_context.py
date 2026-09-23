from __future__ import annotations

from dataclasses import replace

import pytest

from hsr.simulator_v8_clean_core.tools.validate_p9_a2_action_window_status_nested_ability_transport import (
    _action_candidates_by_window,
    _build_runtime_direct_rulebook,
    _direct_skill_param_entries,
    _direct_state_for_admission,
    _status_denominator,
)


@pytest.fixture(scope="module")
def direct_projection():
    rules, context, _audit, _denominator, evidence, _transitions = (
        _build_runtime_direct_rulebook()
    )
    return rules, context, evidence


def test_direct_static_build_is_real_but_does_not_claim_birth_admission(
    direct_projection,
) -> None:
    rules, context, evidence = direct_projection
    build = evidence["direct_static_build"]

    assert build["character_card_build_count"] == 1
    assert build["input_fingerprint"] == context.build.input_fingerprint
    assert build["result_fingerprint"] == context.assembly.result_fingerprint
    assert build["assembly_status"] == "assembled"
    assert build["battle_admission_status"] == "blocked"
    assert {item["mechanism_kind"] for item in build["diagnostics"]} == {
        "character_dynamic_graph_root"
    }
    assert rules.character_data_card(context.owner_card.card_id) == context.owner_card


def test_both_direct_state_entries_share_the_same_build_projection(
    direct_projection,
) -> None:
    rules, context, _evidence = direct_projection
    candidates = _action_candidates_by_window(rules, context)
    _definition, candidate_context = next(
        item for values in candidates.values() for item in values
    )
    candidate_state, _command, _selection, admission, _mode, _decision = (
        candidate_context
    )
    rebuilt_state = _direct_state_for_admission(rules, admission, context)
    candidate_actor = candidate_state.units["validation:actor"]
    rebuilt_actor = rebuilt_state.units["validation:actor"]

    assert candidate_actor == rebuilt_actor
    assert candidate_actor.template_id == context.owner_card.entity_ref
    assert candidate_actor.flags["effective_skill_levels_by_action_id"] == {
        item.action_id: item.effective_level
        for item in context.assembly.effective_skill_levels
    }
    assert "build_mode" not in candidate_actor.flags
    assert "character_build_admitted" not in candidate_actor.flags


def test_direct_candidates_use_only_the_effective_action_level(
    direct_projection,
) -> None:
    rules, context, _evidence = direct_projection
    effective = {
        item.action_id: item.effective_level
        for item in context.assembly.effective_skill_levels
    }
    candidates = _action_candidates_by_window(rules, context)

    assert candidates
    assert all(
        definition.level == effective[definition.action_id]
        for values in candidates.values()
        for definition, _candidate_context in values
    )


def test_static_param_projection_rejects_missing_levels_and_wrong_owner(
    direct_projection,
) -> None:
    rules, context, _evidence = direct_projection
    candidates = _action_candidates_by_window(rules, context)
    _definition, candidate_context = next(
        item for values in candidates.values() for item in values
    )
    state = candidate_context[0]
    actor = state.units["validation:actor"]

    missing_levels = replace(
        state,
        units={
            **state.units,
            actor.unit_id: replace(
                actor,
                flags={
                    key: value
                    for key, value in actor.flags.items()
                    if key != "skill_levels_by_trigger_key"
                },
            ),
        },
    )
    wrong_owner = replace(
        state,
        units={
            **state.units,
            actor.unit_id: replace(actor, template_id="avatar:wrong-owner"),
        },
    )

    with pytest.raises(AssertionError, match="no executable SkillParam"):
        _direct_skill_param_entries(rules, missing_levels, context)
    with pytest.raises(AssertionError, match="owner identity mismatch"):
        _direct_skill_param_entries(rules, wrong_owner, context)


def test_real_nested_weighted_nodes_can_reach_the_shared_dispatch(direct_projection):
    rules, _context, _evidence = direct_projection
    denominator, _events = _status_denominator(rules)
    weighted_rows = [row for row in denominator if row["weighted_selection_ids"]]
    assert weighted_rows, "real weighted denominator must not be vacuous"
    checked = set()
    for row in weighted_rows:
        query = rules.query_task_graph(row["nested_graph_id"])
        assert query.status == "resolved" and query.value is not None
        graph = query.value
        selections = {item.selection_id: item for item in graph.weighted_selections}
        nodes = {item.graph_node_id: item for item in graph.nodes}
        for selection_id in row["weighted_selection_ids"]:
            selection = selections[selection_id]
            node = nodes[selection.graph_node_id]
            assert node.source_family == selection.family == "RandomConfig"
            assert node.node_kind == "branch", (node.graph_node_id, node.status_reason)
            assert node.materialization_status == "materialized"
            assert node.owner_domains == ("task_graph_execution",)
            assert not node.status_reason
            checked.add((graph.graph_id, selection_id))
    assert checked
